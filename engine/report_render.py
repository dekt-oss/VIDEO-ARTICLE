"""PF2: 리포트 지시서 → mp4 렌더 큐 워커 (논문 engine/render.py 미러).

렌더 엔진(render._render_cut_clips·assemble·subtitles·providers)은 그대로 재사용하고, 리포트 전용으로
① 시리즈 제목 ② 하단 고정 면책/출처 자막(footer) ③ 'report/' 업로드 경로만 제어한다.

★ 에셋 캐시는 `report_render_assets` 로 간다(2026-09-19 배선, engine/asset_cache.py).
  v1 은 `directive_id=None` 으로 불러 **캐시를 통째로 포기**했다 — 논문 표의 FK 때문이었는데,
  그 대가로 다시 렌더할 때마다 그림값을 다시 냈고 언어 간 공유도 없었다. 이제 kind 로 표를
  가른다. 논문 `render_assets` 는 여전히 미접촉이다.

실행: python -m engine.report_render                # report_render_jobs 큐 1회 폴링
     python -m engine.report_render <directive_id>  # 단건 렌더(디버그, DB 업데이트 없음)
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from typing import Any

from . import assemble, config, render_manifest, render_qa, report_db, subtitles, visual_contract
from . import render
from . import stage_metrics as sm
from .util import log


def _disclaimer_footer(broker: str, lang: str) -> str:
    """하단 고정 자막 문구: 출처 + 면책(사용자 요구 — 면책은 씬이 아니라 하단 자막)."""
    disc = config.REPORT_DISCLAIMER_TEXT
    if lang == "en":
        disc = "For information only. Not investment advice."
    # ★ 출처 라벨도 언어를 따라간다. 예전엔 "출처"가 하드코딩돼 영어 영상 하단에
    #   `출처 하나증권 · For information only…` 처럼 한 단어만 한글로 남았다.
    label = config.REPORT_SOURCE_LABEL_BY_LANG.get(lang, config.REPORT_SOURCE_LABEL_BY_LANG["ko"])
    src = f"{label} {broker} · " if broker else ""
    return f"{src}{disc}"


@contextlib.contextmanager
def _explainer_layout(version_type: str):
    """설명판형 렌더 동안만 레터박스를 끈다 (최종명세 v3.3 §21 K3 — 커버 크롭만, 필러바 금지).

    ★ 왜 전역 상수를 잠깐 바꾸는가: 검은 바를 만드는 지점이 assemble 안에 4곳(letterbox_pad_suffix ·
      layout_content_dims · effect_filter · _clip_fit_geometry)이고 전부 config.LAYOUT_MODE 를
      호출 시점에 읽는다. 인자로 전달하려면 그 4개 함수와 **논문 라인 호출자까지** 고쳐야 한다.
      같은 방식의 선례가 이미 있다 — render.py 가 placeholder 폴백 때 config.IMAGE_PROVIDER 를
      스왑한다.
    ★ 스레드 안전하지 않다. 리포트 워커는 poll_once 가 잡을 **직렬**로 처리하므로 현재 안전하다.
      병렬화하면 이 스왑이 깨진다 — 그때는 인자 전달로 바꿔야 한다.
    """
    if version_type != "explainer":
        yield
        return
    # v3.4 §22-7 착수 순서 ① — 폰트 자산이 없으면 **여기서** 멈춘다. 렌더가 절반쯤 진행된 뒤
    # 컷마다 터지면 원인이 흩어져 보이고, 무엇보다 그 사이 유료 생성이 이미 나갔을 수 있다.
    visual_contract.preflight_fonts()
    prev = config.LAYOUT_MODE
    config.LAYOUT_MODE = "full_bleed"
    log.info("설명판형 — 레터박스 해제(full_bleed), 렌더 후 '%s' 로 복원", prev)
    try:
        yield
    finally:
        config.LAYOUT_MODE = prev


def process_job(job_id: str, directive_id: str, lang: str = "ko") -> str:
    """report_render_jobs 1건 처리: 에셋→조립(면책 footer)→Storage 업로드→done. 반환: output_url."""
    directive = report_db.get_report_directive(directive_id)
    if not directive:
        raise ValueError(f"report_directive 없음: {directive_id}")
    report_db.update_report_directive_status(directive_id, "rendering")

    version_type = str((directive.get("header") or {}).get("version_type")
                       or directive.get("version_type") or "")
    # ★ §21 K5 — 설명판형은 편당 $0.25 다(코드 렌더가 주역이라 더 낮다). 그동안 이 상수를
    #   읽는 곳이 없어 실제 캡은 $1.2 하나였다. 캡은 잡을 죽이므로 닿기 전에 경고를 남긴다.
    cap = config.render_budget_cap(version_type)
    spent = {"cost": 0.0, "warned": False}

    def _on_cost(c: float) -> None:
        spent["cost"] += c
        if not spent["warned"] and spent["cost"] > cap * config.RENDER_COST_WARN_RATIO:
            spent["warned"] = True
            log.warning("생성비가 캡의 %d%% 를 넘었다: $%.3f / 캡 $%.2f (%s)",
                        int(config.RENDER_COST_WARN_RATIO * 100), spent["cost"], cap,
                        version_type or "기본")
        if spent["cost"] > cap:
            raise RuntimeError(
                f"예산 초과: ${spent['cost']:.3f} > 캡 ${cap} "
                f"(version_type={version_type or '기본'}). 실측이 이보다 크면 코드가 아니라 "
                f"EXPLAINER_COST_CAP_USD 환경변수를 올린다")

    work_dir = tempfile.mkdtemp(prefix=f"report_render_{job_id}_")
    report_db.update_report_render_job(job_id, status="assets", progress=20)
    # ★ 에셋 캐시는 report_render_assets 로 간다(engine/asset_cache.py) — 논문 표 미접촉.
    # ★ overlay_out/overlays 를 넘기지 않으면 근거 카드·출처 카드가 ASS 에 스타일조차 정의되지
    #   않아 **화면에서 사라진다**. 지시서는 만드는데 렌더가 버리고 있었다(논문 라인은 넘긴다).
    overlays: list[tuple[float, float, str, str]] = []
    cut_map: list[dict[str, Any]] = []
    board_qa: list[dict[str, Any]] = []
    # §10 관측성 — 단계별 소요시간. 8분 걸린 렌더의 8분이 어디서 갔는지 지금까지 알 수 없었다.
    metrics: dict[str, Any] = {}
    with _explainer_layout(version_type), sm.stage(metrics, "asset"):
        # ★★ 2026-09-19: directive_id 를 **넘긴다.** 예전엔 None 이었다 — 논문
        #   `render_assets.directive_id` 가 `directives(id)` 를 참조해서 리포트 id 를 넣으면
        #   FK 위반이었기 때문이다. 대가는 **다시 렌더할 때마다 그림을 다시 사는 것**이었고,
        #   언어를 늘려도 공유가 되지 않았다(논문 라인은 공유한다).
        #   이제 캐시는 `render_job_kind` 를 보고 `report_render_assets`(0020, FK 는
        #   report_directives) 로 간다. 원장(generation_attempts)은 그 표 하나만 참조하므로
        #   `cost.build_attempt` 가 kind 를 보고 directive_id 를 떨군다 — 종전과 같이
        #   render_job_id 로 묶인다.
        cut_files, cues, total, duck_spans = render._render_cut_clips(
            directive, work_dir, on_cost=_on_cost, directive_id=directive_id, lang=lang,
            render_job_kind="report",
            overlay_out=overlays, cut_map_out=cut_map, render_job_id=job_id,
            board_qa_out=board_qa, stage_out=metrics)
    if not cut_files:
        raise ValueError("컷이 없어 렌더 불가")

    report_db.update_report_render_job(job_id, status="tts", progress=55, cost_estimate=spent["cost"])
    report_db.update_report_render_job(job_id, status="assembling", progress=75,
                                       cost_estimate=spent["cost"])
    out_path = os.path.join(work_dir, "final.mp4")
    header = directive.get("header") or {}
    hook = str(header.get(f"hook_{lang}") or "")
    if not hook:
        hook = report_db.get_report_hook(directive.get("report_id") or "")
    series_title = config.REPORT_SERIES_TITLE_BY_LANG.get(lang, config.REPORT_SERIES_TITLE)
    footer = _disclaimer_footer(str(header.get("broker") or ""), lang)
    # 설명판형은 full_bleed 라 자막·출처 바를 §20-3 밴드 안으로 올린다. 그러지 않으면 자막이
    # CORE 를 침범하고 출처 바가 DEAD_BOTTOM(유튜브 UI 구역)에 놓인다.
    band_margins: dict[str, int] = {}
    if version_type == "explainer":
        band_margins = {"caption_margin_v": config.EXPLAINER_CAPTION_MARGIN_V,
                        "footer_margin_v": config.EXPLAINER_SOURCE_MARGIN_V}
    ass = subtitles.build_ass(cues, header_title=series_title, header_hook=hook,
                              total_sec=total, lang=lang, platform=config.DEFAULT_PLATFORM,
                              footer_text=footer, overlays=overlays, **band_margins)
    with sm.stage(metrics, "assemble"):
        assemble.assemble_full(cut_files, work_dir, out_path, ass_text=ass, total_sec=total,
                               duck_spans=duck_spans)

    # ★ 리포트 라인은 지금까지 **아무 검사도 받지 않고** 나갔다 — 논문 라인은 run_qa 로
    #   mp4 를 실검하는데(끝 검은프레임·무음·클리핑·길이) 여기엔 호출도, 저장할 컬럼도 없었다.
    #   0036 으로 자리를 만들고 배선한다. 판정은 **기록 전용**이다(차단하지 않는다) —
    #   충전율 warn→fail 승격은 분포를 보고 기준값을 정한 뒤다(v3 §9 · P3-b).
    # ★★ QA 는 **기록 전용**이므로 실패해도 렌더를 죽이면 안 된다. run_qa 는 ffprobe/ffmpeg
    #    subprocess 를 부르고 _ffprobe_json 은 JSONDecodeError 만 잡는다 — 바이너리가 없거나
    #    타임아웃이면 예외가 그대로 올라온다. 이 호출이 upload_render **앞**에 있어서,
    #    감싸지 않으면 잘 만들어진 mp4 를 잃고 잡이 실패한다. 관측을 켜다가 사고를 내는 꼴이다.
    #    (논문 라인은 오래 이대로였지만, 여기는 오늘 잘 돌던 경로에 새 실패 모드를 더하는 것이다.)
    try:
        with sm.stage(metrics, "qa"):
            qa = render_qa.run_qa(out_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("리포트 렌더 QA 실패 — 기록만 건너뛴다(렌더는 계속): %s", exc)
        qa = {"passed": None, "hard_fail": [], "warnings": [],
              "qa_error": f"{type(exc).__name__}: {exc}"[:200]}
    qa["board"] = board_qa           # 컷별 CORE 충전율·프레임 판정
    qa["cut_map"] = cut_map          # 컷 ↔ 최종 mp4 시간축(§8-1)

    with sm.stage(metrics, "upload"):
        url = report_db.upload_render(out_path, f"report/{directive_id}/{job_id}_{lang}.mp4")
    # §10 — 잡당 stage metric. qa jsonb 안에 둔다(마이그레이션 없음, qa["board"] 관례).
    metrics["total_ms"] = sm.total_ms(metrics)
    qa["stage_ms"] = metrics
    log.info("리포트 렌더 단계별: %s (합 %dms)", sm.summarize(metrics), metrics["total_ms"])
    # ★ §8-2·§8-3 — done 은 critical 이 전부 있을 때만(engine/render.py 미러). mp4 는 어느
    #   쪽이든 올린다 — 무엇이 잘못됐는지 보려면 영상을 봐야 한다.
    status, reasons = render_manifest.terminal_status(board_qa)
    report_db.update_report_render_job(job_id, status=status, progress=100,
                                       output_url=url, cost_estimate=spent["cost"],
                                       qa=qa, error_log="; ".join(reasons)[:1000] or None,
                                       finished=status not in config.RENDER_STATUS_AWAITING_HUMAN)
    if status != "done":
        log.warning("리포트 렌더 판정 %s job=%s: %s", status, job_id, ", ".join(reasons))
    report_db.update_report_directive_status(directive_id, "rendered")
    log.info("리포트 렌더 완료: job=%s url=%s 비용=$%.3f 판정=%s", job_id, url, spent["cost"], status)
    return url


def poll_once(limit: int = 3) -> int:
    jobs = report_db.claim_report_render_jobs(limit)
    if not jobs:
        log.info("report_render_jobs: 대기 없음")
        return 0
    for j in jobs:
        try:
            process_job(j["id"], j["directive_id"], j.get("lang") or config.DEFAULT_LANG)
        except Exception as exc:  # noqa: BLE001
            log.exception("리포트 렌더 실패 job=%s: %s", j["id"], exc)
            report_db.update_report_render_job(j["id"], status="failed",
                                               error_log=str(exc)[:1000], finished=True)
            report_db.update_report_directive_status(j["directive_id"], "failed")
    return len(jobs)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            # 단건 디버그: DB 잡 없이 지시서만 로컬 렌더(업로드/상태갱신 없음).
            d = report_db.get_report_directive(sys.argv[1])
            if not d:
                raise SystemExit(f"report_directive 없음: {sys.argv[1]}")
            hdr = d.get("header") or {}
            footer = _disclaimer_footer(str(hdr.get("broker") or ""), config.DEFAULT_LANG)
            out = f"report_render_{sys.argv[1][:8]}.mp4"
            tmp = tempfile.mkdtemp(prefix="report_render_dbg_")
            cut_files, cues, total, duck = render._render_cut_clips(d, tmp, lang=config.DEFAULT_LANG)
            ass = subtitles.build_ass(
                cues, header_title=config.REPORT_SERIES_TITLE,
                header_hook=str(hdr.get("hook_ko") or ""), total_sec=total,
                lang=config.DEFAULT_LANG, platform=config.DEFAULT_PLATFORM, footer_text=footer)
            assemble.assemble_full(cut_files, tmp, out, ass_text=ass, total_sec=total, duck_spans=duck)
            print("DONE", out)
        else:
            poll_once()
    except Exception as exc:  # noqa: BLE001
        log.exception("report_render 실패: %s", exc)
        sys.exit(1)
