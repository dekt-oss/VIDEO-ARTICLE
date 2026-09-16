"""렌더 워커 (P-V1) + render_jobs 폴러.

승인된 지시서(directives) → 컷별 에셋(이미지/오디오) → 컷 mp4 → concat+loudnorm → 최종 mp4.
DV1: 실행 위치는 GitHub Actions 러너(.github/workflows/render.yml) 또는 로컬. ffmpeg 필요.

이번 라운드(P-V0)는 placeholder 제공자로 버전2(이미지 나열식)를 관통해 실제 mp4 를 만든다.
실제 무료/유료 제공자(Gemini 이미지·Edge TTS·힉스필드 I2V)는 P-V1(M-V5~M-V6).

실행:
  python -m engine.render                    # render_jobs 큐 1회 폴링(DB+Storage)
  python -m engine.render <directive_id>     # 특정 지시서 즉시 렌더(DB)
  python -m engine.render --demo <out.mp4>   # 데모 지시서 → 로컬 mp4 (DB 불필요, CI 관통 검증용)
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Callable

from . import (assemble, board_render, clip_fit_types, config, cost as cost_ledger, crop, db,
               claim_viz, evidence_overlay, generation_spec, render_manifest as rm, render_qa,
               clip_candidates, sequence_tier,
               sequence_render, stage_metrics as sm, stage_render, subtitles)
from . import continuity_qa
from .providers import image as image_provider
from .providers import tts as tts_provider
from .providers import video as video_provider
from .util import log


def ledger_key(local: str, render_job_id: str | None, directive_id: str | None) -> str:
    """비용 원장 idempotency_key — **어느 렌더 작업의** 발주인지를 앞에 붙인다.

    ★ 2026-09-14 발견: stage 클립 키가 `stage:{stage_id}#clip{i}` 뿐이라, 다른 지시서(또는 같은
      지시서의 다음 렌더)가 같은 stage 이름(S5 등)을 쓰면 `unique(idempotency_key, attempt_no)`
      위반으로 새 행이 **조용히 거부**됐다(record 는 실패를 로그로만 남긴다) → 원장 과소 집계.
    ★ 작업 번호를 우선한다: 같은 지시서를 다시 렌더해 또 돈을 냈으면 그것도 별개의 발주다.
      작업 번호가 없는 호출(스크립트 등)만 지시서 번호로 물러난다.
    """
    scope = str(render_job_id or directive_id or "-")
    return f"{scope}:{local}"


def _download_to(url: str, dest: str) -> None:
    import httpx
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client:
        resp = client.get(url)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)


def render_kind_for_scene(scene_kind: str | None, version_type: str = "animation",
                          cut: dict[str, Any] | None = None,
                          fact_sheet: dict[str, Any] | None = None) -> str:
    """컷 렌더 방식(클립 vs 스틸).

    ★ Manim 코드 클립은 애니메이션 버전에서만 쓴다. 만화/이미지 버전에 성긴 텍스트 클립(어두운
    배경+불릿)을 섞으면 그림들 사이에서 "빈 화면"처럼 보여 완성도가 떨어진다(사용자 피드백).
    → comic/webtoon/image_sequence 는 전부 스틸 이미지로 일관되게, animation 만 Manim.

    ★ 2026-07-28: editorial 의 `data_viz` → 코드차트 분기를 제거했다(운영자 결정,
      docs/deviation-webtoon-b1-removal.md). 그 분기가 제공 버전에서 Manim 을 타는 유일한
      경로였으므로, 논문·리포트 라인은 이제 스틸 단일 경로다. `animation` 은 제공 버전이 아니고
      `--demo-anim` 관통 검증에만 남아 있다.
      화면에 뜨는 숫자는 `overlay_plan`(ASS 레이어)이 담당하므로 기능 공백은 없다.
    """
    if version_type == "animation":
        return "clip"
    return "image"


def attach_fact_sheet(directive: dict[str, Any]) -> dict[str, Any]:
    """지시서에 Claim Ledger 를 붙인다.

    ★ `directives` 테이블에는 fact_sheet 컬럼이 없다(`db.get_directive` 는 header·cuts 만 읽는다).
      그래서 렌더가 `directive["fact_sheet"]` 를 그냥 읽으면 **항상 None** 이다. 원장은 `drafts` 에
      있으므로 paper_id 로 당겨 온다. 실패해도 렌더는 계속한다.
    ★ 원래 소비처는 editorial 의 data_viz 코드차트였고 그건 폐기됐다(위 참조). 지금은 Manim 데모
      경로만 쓴다 — 20줄짜리 배선이고 코드차트를 되살릴 때 다시 필요해 남겨 뒀다.
    """
    if directive.get("fact_sheet") is not None:
        return directive
    paper_id = directive.get("paper_id")
    if not paper_id:
        return directive
    try:
        draft = db.get_draft_full(str(paper_id))
    except Exception as exc:  # noqa: BLE001 — 원장을 못 읽어도 렌더는 막지 않는다
        log.warning("Fact Sheet 조회 실패(코드 차트 없이 진행): %s", exc)
        return directive
    if draft and draft.get("fact_sheet"):
        directive["fact_sheet"] = draft["fact_sheet"]
    return directive


def _reuse_base_image(cut: dict[str, Any], img_path: str,
                      asset_index: dict[int, str] | None,
                      reuse_out: list[dict[str, Any]] | None = None) -> bool:
    """재사용 전략 컷이면 기준 컷의 스틸을 복사해 쓴다 (수정명세 §10-5). 성공하면 True.

    ★ 이게 "길이가 늘어도 이미지 수가 함께 늘지 않는다"를 실제로 만드는 지점이다. 지시서가
      asset_strategy=reuse_* 로 선언해도 렌더가 새로 생성하면 절감은 서류상으로만 남는다.
    ★ 언어 독립 불변식(I2) 유지: 파일 복사에는 locale 이 없다. KO 가 만든 스틸을 EN 이 그대로
      쓰는 기존 캐시 경로와 같은 성질이다.
    ★ 참조가 깨졌으면 False 를 돌려 평소대로 생성한다 — 화면이 비는 것보다 낫다(정규화가 이미
      new_asset 으로 강등하지만, 저장된 옛 지시서를 렌더할 때를 대비한 방어).
    """
    if asset_index is None:
        return False
    if cut.get("asset_strategy") not in config.ASSET_STRATEGY_REUSE:
        return False
    try:
        base_no = int(str(cut.get("base_asset_ref") or "").strip())
    except (TypeError, ValueError):
        return False
    base_path = asset_index.get(base_no)
    if not base_path or not os.path.exists(base_path):
        log.warning("컷 %s 재사용 기준(컷 %s) 에셋 없음 → 새로 생성",
                    cut.get("cut_no"), cut.get("base_asset_ref"))
        return False

    cut_no = cut.get("cut_no")
    crop_spec = cut.get("crop") if isinstance(cut.get("crop"), dict) else None
    tone = str(cut.get("tone_grade") or config.DEFAULT_TONE_GRADE)

    # ★ 크롭도 톤도 없는 재사용은 **같은 그림을 두 번 트는 것**이다(2026-08-29 실측: 컷5와
    #   컷6 이 바이트까지 동일한 파일로 나갔다). 재사용의 값어치는 "같은 대상이 다음 단계로
    #   다시 나온다"에 있지 "같은 프레임을 아낀다"에 있지 않다 — 화면이 안 변하면 시청자는
    #   영상이 멈춘 줄 안다. 오버레이가 달라지는 컷만 예외로 둔다(코드 그래픽이 차이를 만든다).
    if not crop.has_work(crop_spec, tone):
        if cut.get("overlay_plan"):
            shutil.copyfile(base_path, img_path)
            log.info("컷 %s 에셋 재사용(기준 컷 %s, 전략 %s) — 배경 동일·오버레이가 차이를 만든다",
                     cut_no, base_no, cut.get("asset_strategy"))
            return True
        log.warning("컷 %s 재사용이 화면 변화를 못 만든다(크롭·톤·오버레이 전부 없음) → 새로 생성",
                    cut_no)
        return False

    # ★ 여기가 "카메라 이동을 크롭으로 만든다"의 실행 지점이다.
    #   실패해도 **유료 생성으로 떨어지지 않는다** — 기준 이미지를 그대로 쓰는 것이 최악이다.
    #   크롭이 틀린 화면보다 확대가 안 된 화면이 낫고, 둘 다 새 이미지값보다 낫다.
    try:
        crop.derive_image(base_path, img_path, crop_spec, tone)
        log.info("컷 %s 파생(기준 컷 %s, 전략 %s, crop=%s, tone=%s) — 생성 호출 0",
                 cut_no, base_no, cut.get("asset_strategy"), crop_spec, tone)
    except Exception as exc:  # noqa: BLE001 — 파생 실패가 과금으로 이어지면 안 된다
        log.warning("컷 %s 파생 실패 → 기준 이미지 그대로 사용(생성 호출 0): %s", cut_no, exc)
        shutil.copyfile(base_path, img_path)

    # ★ 선언이 아니라 **결과**를 본다. 크롭·톤을 걸었는데도 화면이 사실상 안 변했으면
    #   그것은 진행이 아니라 반복이다 — 새로 생성한다. 실측 기준: 복붙 0.0 / 톤 20.4 /
    #   크롭 39.2 라 REUSE_MIN_PIXEL_DELTA=2.0 은 정상 파생을 벌하지 않는다.
    #   판정 불가(-1.0)는 통과시킨다 — 이미지 하나 못 읽었다고 렌더를 멈추지 않는다.
    if config.REUSE_REQUIRES_VISIBLE_DELTA and not cut.get("overlay_plan"):
        delta = crop.mean_abs_delta(base_path, img_path)
        if 0.0 <= delta < config.REUSE_MIN_PIXEL_DELTA:
            log.warning("컷 %s 파생 결과가 기준 컷과 사실상 같은 그림(Δ=%.3f) → 새로 생성",
                        cut_no, delta)
            # ★ 여기가 `photo_reuse_identical_render` 의 **유일한 발생 지점**이다.
            #   사유 코드와 처방 문구는 photo_contract 에 2026-08-29 부터 있었는데
            #   **이 사실을 남기는 곳이 없어서** 코드가 한 번도 밖으로 나가지 않았다.
            #   sweep_unwired 도 못 잡는다 — 상수는 목록에서 참조되고 있으니까.
            #   선언한 변화가 화면에 안 나타났다는 뜻이라, 다음 지시서를 고칠 근거다.
            if reuse_out is not None:
                reuse_out.append({"cut_no": cut_no, "base_cut_no": base_no,
                                  "delta": round(float(delta), 3),
                                  "reason": "photo_reuse_identical_render"})
            return False
    return True


def _gen_still(cut: dict[str, Any], header: dict[str, Any], img_path: str,
               directive_id: str | None = None,
               render_job_id: str | None = None,
               render_job_kind: str = "paper",
               ref_path: str | None = None,
               reference_key: str = "") -> float:
    """이미지 스틸 생성. 실패 시 재시도 → placeholder 폴백. 반환: cost.

    유료 제공자(gemini 등)일 때만 content_hash 멱등 캐시를 쓴다 — 재렌더 시 변경 안 된 컷은
    Storage 에 저장된 에셋을 재사용해 재생성 비용을 아낀다(placeholder 는 공짜라 캐시 불필요).
    """
    # ★ 두 개념을 쪼갠다 (v3 §8-4 P3-c). 예전엔 하나였다:
    #     use_cache = bool(directive_id) and PROVIDER not in (...)
    #   그래서 directive_id 가 없는 **리포트 라인은 원장 기록 3곳이 전부 건너뛰어졌다** —
    #   generation_attempts 가 0행이었던 이유가 이 불린 하나다(report_render.py 가
    #   directive_id=None 으로 부른다). 캐시는 directive_id 로 키를 잡아야 하지만
    #   원장은 그럴 이유가 없다.
    paid = config.IMAGE_PROVIDER not in ("placeholder", "")
    use_cache = bool(directive_id) and paid
    record_ledger = paid
    # ★ 이 컷을 **실제로** 무엇으로 만드는가. 캐시 키·원장·로그가 전부 이 하나를 읽는다
    #   (engine/generation_spec.py). 예전엔 호출은 역할별 모델, 원장은 config.IMAGE_MODEL 이라
    #   프리미엄으로 그려 놓고 flash 로 기록되는 일이 가능했다.
    img_spec = generation_spec.image_spec(cut, header, generation_mode="realtime",
                                          reference_key=reference_key)
    content_h = assemble.content_hash(cut, header, reference_key=reference_key)
    cut_no = int(cut.get("cut_no") or 0)

    if use_cache:
        existing = db.get_render_asset(directive_id, cut_no, "image")
        if assemble.cache_hit(existing, content_h) and existing.get("asset_url"):
            try:
                _download_to(existing["asset_url"], img_path)
                log.info("컷 %s 이미지 캐시 재사용", cut_no)
                return 0.0
            except Exception as exc:  # noqa: BLE001 — 캐시 다운로드 실패면 재생성
                log.warning("캐시 다운로드 실패, 재생성: %s", exc)

    cost = 0.0
    generated = False
    last_exc: Exception | None = None
    attempts_used = 0
    # ★ 역할 상향 모델은 더 오래 매달린다 — 여기서 일찍 포기하면 도해 컷이 flash 로 내려가고,
    #   flash 는 도해에 **깨진 글자 라벨**을 그린다(2026-08-29 실측). 상세는 config 주석.
    retries = (config.ASSET_RETRY_ROLE_MODEL
               if img_spec.model != config.IMAGE_MODEL else config.ASSET_RETRY)
    for attempt in range(retries + 1):
        attempts_used = attempt + 1
        try:
            # ★ 참조가 없으면 **인자 자체를 넘기지 않는다** — 옛 경로를 한 글자도 바꾸지 않는다.
            # ★★ 모델은 **명시로 넘긴다**(2026-08-30 Mini Render 실측). 안 넘기면 공급자가
            #    자기 나름대로 `cut["visual_role"]` — 모델이 붙인 옛 라벨 — 로 다시 고른다.
            #    그래서 정본이 기전 시퀀스로 판정한 컷1이 **flash 로 그려졌다**(예상 $0.346 vs
            #    실제 $0.251 이 그것을 드러냈다). 이 저장소가 이미 한 번 고친 버그의 재발이다:
            #    호출과 원장이 서로 다른 모델을 보는 상태. generation_spec 이 유일한 출처다.
            _, cost = image_provider.generate_image(
                cut, header, img_path, model=img_spec.model,
                **({"ref_path": ref_path} if ref_path else {}))
            generated = True
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("컷 %s 이미지 실패(attempt %d): %s", cut_no, attempt + 1, exc)
            # ★ 재시도 실패분도 원장에 남긴다. 지금까지 실패는 흔적이 0이라 "왜 이 편이
            #   비쌌나"를 물으면 성공한 호출만 보였다. attempt_no 파라미터는 cost.py 에
            #   이미 있었는데 호출 4곳이 전부 기본값 1만 쓰고 있었다.
            if record_ledger:
                cost_ledger.record(cost_ledger.build_attempt(
                    asset_type="image", provider=img_spec.provider,
                    model_id=img_spec.model, generation_mode="realtime",
                    unit_type="image_standard", requested_units=1,
                    directive_id=directive_id, render_job_id=render_job_id, render_job_kind=render_job_kind, cut_no=cut_no,
                    attempt_no=attempt + 1, status="failed",
                    error_class=type(exc).__name__))
    # ★ 모델 폴백(2026-08-29 실측): 역할 상향 모델이 죽어도 **작동하는 모델이 있으면 그걸 쓴다.**
    #   실측에서 gemini-3-pro-image 가 503("high demand")로 죽자 3D 도해 컷이 전부 회색
    #   placeholder 로 나갔다 — 같은 순간 flash 모델은 정상이었다. 유료 렌더에서 "덜 좋은 그림"과
    #   "그림 없음"은 비교 대상이 아니다.
    #   ★ 캐시는 **실제로 쓴 모델의 키**에 저장한다. pro 키로 저장하면 pro 가 살아난 뒤에도
    #     flash 그림이 재사용되어 상향이 영영 도달하지 못한다.
    if (not generated and config.IMAGE_MODEL_FALLBACK
            and img_spec.model != config.IMAGE_MODEL and paid):
        fb_cut = {**cut, "visual_role": ""}          # 역할을 비워 전역 모델을 고르게 한다
        img_spec = generation_spec.image_spec(fb_cut, header, generation_mode="realtime",
                                              reference_key=reference_key)
        content_h = assemble.content_hash(fb_cut, header, reference_key=reference_key)
        log.warning("컷 %s 역할 모델 실패 → 기본 모델로 폴백해 다시 만든다: %s → %s",
                    cut_no, config.image_model_for(cut.get("visual_role")), img_spec.model)
        try:
            _, cost = image_provider.generate_image(
                cut, header, img_path, model=img_spec.model,
                **({"ref_path": ref_path} if ref_path else {}))
            generated = True
            attempts_used += 1
        except Exception as exc:  # noqa: BLE001 — 폴백까지 실패하면 placeholder
            last_exc = exc
            log.error("컷 %s 폴백 모델도 실패: %s", cut_no, exc)
            if record_ledger:
                cost_ledger.record(cost_ledger.build_attempt(
                    asset_type="image", provider=img_spec.provider, model_id=img_spec.model,
                    generation_mode="realtime", unit_type="image_standard", requested_units=1,
                    directive_id=directive_id, render_job_id=render_job_id,
                    render_job_kind=render_job_kind, cut_no=cut_no,
                    attempt_no=attempts_used + 1, status="failed",
                    error_class=type(exc).__name__))

    if not generated:
        log.error("컷 %s 이미지 최종 실패 → placeholder 폴백: %s", cut_no, last_exc)
        # ★ 폴백 사실 자체를 원장에 남긴다(§8-2). placeholder 는 무료지만 **무료라는 것이
        #   기록하지 않을 이유가 아니다** — "이 편의 컷 3은 생성이 아니라 폴백이었다"가
        #   화면 품질을 설명하는 가장 중요한 한 줄이다. 지금까지 이 사실은 로그에만 있었다.
        if record_ledger:
            cost_ledger.record(cost_ledger.build_attempt(
                asset_type="image", provider="placeholder", model_id=img_spec.model,
                generation_mode="realtime", unit_type="image_standard", requested_units=0,
                directive_id=directive_id, render_job_id=render_job_id, render_job_kind=render_job_kind, cut_no=cut_no,
                attempt_no=attempts_used, status="fallback",
                error_class=type(last_exc).__name__ if last_exc else "unknown"))
        prev = config.IMAGE_PROVIDER
        config.IMAGE_PROVIDER = "placeholder"
        try:
            image_provider.generate_image(cut, header, img_path)
        finally:
            config.IMAGE_PROVIDER = prev
        return 0.0  # 폴백 placeholder 는 캐시에 기록하지 않음(다음 렌더에 재시도되게)

    # ★ 종횡비 실측(웹툰 v1 §4). 프롬프트의 "vertical 9:16" 은 무시될 수 있고, 파라미터가 먹었는지도
    #   응답만 봐서는 알 수 없다 — 그래서 산출물을 직접 잰다. 어긋나도 **예외를 던지지 않는다**:
    #   던지면 유료 호출이 재시도된다. 대신 에러 로그 + 에셋 meta 플래그로 ⑥ 화면에 남긴다.
    asset_meta: dict[str, Any] = {}
    size = image_provider.measure_aspect(img_path)
    if size is not None:
        asset_meta["aspect"] = [size[0], size[1]]
        if not image_provider.is_portrait_916(*size):
            asset_meta["aspect_mismatch"] = True
            log.error("컷 %s 이미지가 9:16 이 아니다(%sx%s) — 종횡비 파라미터를 확인하라",
                      cut_no, size[0], size[1])

    # 유료 실제 이미지 성공 → 비용 원장 1행(작업 C) + Storage 업로드 + 캐시 기록(멱등).
    # 원장은 '생성이 일어난 1회'만 기록(캐시 재사용은 위에서 이미 반환) → 공유 에셋 중복 계상 방지(§6.3).
    if record_ledger:
        cost_ledger.record(cost_ledger.build_attempt(
            asset_type="image", provider=img_spec.provider, model_id=img_spec.model,
            generation_mode="realtime", unit_type="image_standard", requested_units=1,
            directive_id=directive_id, render_job_id=render_job_id, render_job_kind=render_job_kind, cut_no=cut_no,
            attempt_no=attempts_used))
    if use_cache:
        try:
            dest = f"{directive_id}/assets/cut_{cut_no}.png"
            url = db.upload_render(img_path, dest, "image/png")
            db.upsert_render_asset({
                "directive_id": directive_id, "cut_no": cut_no, "asset_type": "image",
                "asset_url": url, "content_hash": content_h, "meta": asset_meta,
            })
        except Exception as exc:  # noqa: BLE001 — 캐시 기록 실패는 렌더를 막지 않음
            log.warning("에셋 캐시 기록 실패(무시): %s", exc)
    return cost


def _veo_generate_scored(cut: dict[str, Any], header: dict[str, Any], clip_path: str,
                         tier_sec: int, start_image: str, vid_spec: Any,
                         *, cut_no: int,
                         clip_metrics_out: list[dict[str, Any]] | None = None,
                         metrics_extra: dict[str, Any] | None = None,
                         ) -> tuple[float, dict[str, Any] | None]:
    """Veo 클립 하나를 **뽑아서 고른다.** 반환: (비용, 후보 선택 기록 또는 None).

    ★★ 컷 경로(`_gen_veo_clip`)와 시퀀스 경로(`_build_stage_video`)가 **같은 이 함수**를
      쓴다. 갈라 두면 한쪽만 고치는 일이 반복된다 — 이 저장소가 `_obtain_still` 에서 이미
      겪은 실패다(스틸/영상 분기가 갈려 v3 참조 생성이 영상 컷에서만 안 돌았다).
      특히 **후보 선택은 조용히 사라지기 쉽다**: 새 경로가 provider 를 직접 부르면
      invest 등급 컷이 2발 대신 1발이 되고, 품질 상한이 내려간 것을 아무도 모른다.

    ★ 스펙을 넘긴다 — provider 가 길이·모델을 **다시 정하지 않는다**(P0-2).
    ★★ 단, 등급이 없으면 **인자 자체를 넘기지 않는다.** 이미지 경로에서 이미 겪은
      사고와 같은 계열이다(`test_a_cut_without_a_sequence_calls_the_provider_exactly
      _as_before`): 새 kwarg 를 무조건 넘기면 옛 시그니처 호출부가 TypeError 를 내고,
      그 예외가 **재시도 루프에 삼켜져 조용히 스틸로 떨어진다.** 영상이 사라지는데
      사유는 "I2V 실패"로만 남는다. 실측으로 3건 재현됐다(2026-08-31).
      등급제 밖 버전은 종전 호출 형태 그대로 간다.

    metrics_extra: 지표 행에 덧붙일 필드(시퀀스 경로가 stage_id·clip_index 를 남긴다).
    """
    if not vid_spec.tier:
        _, cost = video_provider.generate_clip(
            cut, header, clip_path, tier_sec, start_image=start_image)
        return cost, None

    # ★★ 후보 선택(v2 Phase E3) — **뽑아서 고른다.**
    #   생성형 영상은 확률적이라 1발과 2발-선택은 결과 품질의 **상한**이 다르다.
    #   벤치마크가 그렇게 만든다: "8초를 뽑아 좋은 3초만 쓴다."
    #   ★ 직렬로 돈다 — Gemini 동시 호출은 429 를 만든다(운영 제약).
    #   ★ 판정은 코드가 한다(freeze·scene change). 모델에게 "어느 쪽이 좋냐"고
    #     물으면 그 답이 또 자기보고다.
    n = max(1, int(vid_spec.candidates))
    cost = 0.0
    cand_pick: dict[str, Any] | None = None
    paths: list[str] = []
    scored: list[dict[str, Any]] = []
    for k in range(n):
        cand = clip_path if k == 0 else f"{clip_path}.cand{k}.mp4"
        _, c = video_provider.generate_clip(
            cut, header, cand, tier_sec, start_image=start_image, spec=vid_spec)
        cost += c
        paths.append(cand)
        # ★★ **후보가 하나여도 잰다**(2026-08-31). 종전에는 n>1 일 때만 쟀는데,
        #   그러면 지표가 **후보 선택하는 컷에서만** 생기고 나머지는 아무 기록이
        #   없다. 그 상태로는 "세계이탈이 얼마부터 나쁜가" 같은 문턱을 영영
        #   못 정한다 — 실측 4개가 전부 나쁜 표본이라 경계를 못 그은 것이
        #   정확히 그 문제였다(docs/실측_품질/교정_2026-08-31.md §5).
        #   ★ 비용 0이다. 이미 받아 둔 파일에 ffmpeg 를 한 번 더 돌릴 뿐이고,
        #     렌더가 돌 때마다 **좋은 클립·나쁜 클립이 섞여** 표본이 쌓인다.
        #     그러면 사람이 손으로 샘플을 뽑아 주지 않아도 교정이 된다.
        sig = clip_candidates.probe_motion(cand, tier_sec)
        scored.append(clip_candidates.score(
            sig, min_beats=int(config.tier_profile(vid_spec.tier).get("min_beats") or 1)))
        if clip_metrics_out is not None:
            clip_metrics_out.append({
                "cut_no": cut_no, "tier": vid_spec.tier,
                "clip_sec": tier_sec, "candidate": k,
                "beats_declared": len(cut.get("temporal_plan") or []),
                **{key: sig.get(key) for key in
                   ("measured", "freeze_sec", "scene_changes",
                    "motion_median", "world_drift", "text_burn_in")},
                "score": scored[-1].get("score"),
                **(metrics_extra or {}),
            })
    if n > 1:
        chosen = clip_candidates.pick(scored)
        # ★ 코드가 못 가른 동점만 **그림을 보고** 가른다(리뷰 §9 멀티모달 판정).
        #   매번 묻지 않는다 — 그러면 그 답이 새로운 자기보고가 되고, 왜 그 후보를
        #   골랐는지 코드가 설명하지 못한다. 코드 판정을 먼저 두는 규율 그대로다.
        #   묻는 것은 좁다: 글자 번인과 세계 유지, 둘뿐이다(clip_candidates 참조).
        #   ★ 프레임 경로는 clip_path 에서 만든다 — 이 함수에는 work_dir·idx 가
        #     없다(첫 구현에서 그걸 쓰다 NameError 를 낼 뻔했고, 아래 테스트가
        #     실제로 이 경로를 실행해 잡는다).
        base = os.path.splitext(clip_path)[0]
        frames = []
        for k2, cand2 in enumerate(paths):
            fp = f"{base}_cand{k2}_last.png"
            if clip_candidates.last_frame(cand2, fp):
                frames.append(fp)
        chosen = clip_candidates.review_tie(chosen, frames)
        cand_pick = {"n": n, "index": chosen["index"],
                     "reason": chosen["reason"], "scores": scored}
        log.info("컷 %s 후보 %d개 → %d번 채택(%s) 점수=%s", cut_no, n,
                 chosen["index"] + 1, chosen["reason"],
                 [s.get("score") for s in scored])
        if chosen["index"] != 0:
            shutil.copyfile(paths[chosen["index"]], clip_path)
        for extra in paths[1:]:
            # 탈락 후보는 지운다 — 저장소 할당량이 이미 한 번 잠긴 적이 있다.
            with contextlib.suppress(OSError):
                os.remove(extra)
    return cost, cand_pick


def _gen_veo_clip(cut: dict[str, Any], header: dict[str, Any], clip_path: str,
                  start_image: str, directive_id: str | None = None,
                  narration_sec: float = 0.0,
                  render_job_id: str | None = None,
                  render_job_kind: str = "paper",
                  start_asset_key: str = "",
                  clip_metrics_out: list[dict[str, Any]] | None = None,
                  ) -> tuple[bool, str | None, float]:
    """hybrid I2V Veo 클립 생성 + 언어 무관 content_hash 캐시. 반환: (성공, cost).

    ★ 캐시 키는 비주얼(cut+header)만이라 언어 독립 — KO 렌더가 만든 클립을 EN 재렌더가 그대로
    재사용해 Veo 이중 과금을 막는다("공통 영상" 공유).
    ★ 클립 길이는 나레이션 실측 이상인 최소 티어(§3-2, pick_clip_tier)로 요청한다. 상한
    VEO_CLIP_MAX_TIER_SEC 에서 묶이면 남는 갭은 조립 단계의 무료 보정(§3-3 clip_fit)이 흡수한다.
    ★ 캐시는 언어 공유라 첫 언어가 결정한 티어를 뒤 언어가 물려받는다 — 그래서 같은 클립이
    KO 에서는 홀드, EN 에서는 트림이 될 수 있다(정상 동작, 명세 §2-2).
    ★ Veo 는 과금 생성이라 실패 시 재시도하지 않고 스틸로 폴백(호출측).

    start_asset_key: 이 클립의 **시작 화면을 결정한 값**. 연쇄면 앞 컷의 클립 캐시 키,
      아니면 이 컷 스틸의 캐시 키다. 캐시 키에 들어가므로 **앞 컷이 바뀌면 이 컷 캐시가
      무효화된다** — 예전에는 이 연결이 없어 앞이 바뀌어도 뒤가 옛 클립을 그대로 썼다.

    반환: (성공, 이 클립의 캐시 키 또는 None, cost). 캐시 키를 돌려주는 이유는 다음 컷의
      start_asset_key 가 되어 연쇄를 잇기 때문이다.
    """
    # ★ 이미지 경로와 같은 이유로 캐시/원장을 쪼갠다(v3 §8-4 P3-c).
    paid = config.VIDEO_PROVIDER not in ("placeholder", "")
    use_cache = bool(directive_id) and paid
    record_ledger = paid
    cut_no = int(cut.get("cut_no") or 0)
    # 요청 티어(비용 원장·예외 처리에서 실제 요청 초수를 써야 정확하다).
    # ★ 버전별 클립 길이 상한으로 티어를 고른다(2026-08-20). 실사형은 8초까지 살 수 있어
    #   나레이션이 5~6초인 컷도 얼지 않는다 — 기본 4초 상한이 정지 구간의 직접 원인이었다.
    version_cap = config.clip_tier_max(str((header or {}).get("version_type") or ""))
    tier_sec = video_provider.pick_clip_tier(
        narration_sec or config.VEO_CLIP_SEC, max_sec=version_cap)

    # ★★ 등급제(v2): 이 컷이 **무엇을 설명하는가**가 클립 길이를 정한다.
    #   기전을 실제로 설명하는 컷(invest)은 8초를 받아 시간축 연출(비트 2~3)을 담고,
    #   연결·CTA 컷은 4초로 간다. 종전에는 나레이션 길이만 봤다 — 그래서 짧게 말하는
    #   기전 컷이 4초로 묶이고, 길게 말하는 CTA 가 8초를 먹었다.
    #   ★ 나레이션보다 짧아지지는 않는다(길이 보정이 흡수할 수 있는 방향으로만 조정).
    tier_info = sequence_tier.effective_tier(cut, header)
    if tier_info["tier"]:
        want = sequence_tier.clip_sec_for(cut, header, version_cap=version_cap)
        tier_sec = max(tier_sec, want) if want else tier_sec
        log.info("컷 %s 등급 %s → 클립 %ss%s", cut.get("cut_no"), tier_info["tier"], tier_sec,
                 (" (사유 " + ",".join(tier_info["reasons"]) + ")") if tier_info["reasons"] else "")

    vid_spec = generation_spec.video_spec(
        cut, header, clip_sec=tier_sec,
        start_asset_hash=generation_spec.asset_logical_hash(start_asset_key),
        tier=tier_info["tier"],
        candidates=sequence_tier.candidates_for(cut, header))
    content_h = assemble.clip_content_hash(
        cut, header, clip_sec=tier_sec,
        start_asset_hash=generation_spec.asset_logical_hash(start_asset_key))

    if use_cache:
        existing = db.get_render_asset(directive_id, cut_no, "clip")
        if assemble.cache_hit(existing, content_h) and existing.get("asset_url"):
            try:
                _download_to(existing["asset_url"], clip_path)
                log.info("컷 %s 클립 캐시 재사용(언어 공유)", cut_no)
                return True, content_h, 0.0
            except Exception as exc:  # noqa: BLE001 — 캐시 다운로드 실패면 재생성
                log.warning("클립 캐시 다운로드 실패, 재생성: %s", exc)

    cand_pick: dict[str, Any] | None = None
    try:
        cost, cand_pick = _veo_generate_scored(
            cut, header, clip_path, tier_sec, start_image, vid_spec,
            cut_no=cut_no, clip_metrics_out=clip_metrics_out)
    except video_provider.VeoBilledRejection as exc:
        # 생성(operation)은 끝났으나(과금 유력) 산출물을 못 씀 → 스틸 폴백하되 실효 비용은 원장에
        # 남긴다(§8.5 "미채택 영상 비용도 실효비용에 포함"). 캐시엔 안 남김(재시도 시 다시 시도).
        billed_cost = float(exc.clip_sec) * config.VEO_COST_PER_SEC_USD
        log.error("hybrid 컷 %s I2V 생성됐으나 산출물 무효(과금 포함) → 스틸 폴백: %s", cut_no, exc)
        if record_ledger:
            cost_ledger.record(cost_ledger.build_attempt(
                asset_type="video", provider=vid_spec.provider, model_id=vid_spec.model,
                generation_mode=vid_spec.generation_mode, unit_type=vid_spec.unit_type,
                requested_units=tier_sec, billed_units=exc.clip_sec,
                status="failed", error_class="billed_rejection",
                directive_id=directive_id, render_job_id=render_job_id, render_job_kind=render_job_kind, cut_no=cut_no))
        return False, None, billed_cost
    except Exception as exc:  # noqa: BLE001 — 생성 자체가 안 된 실패는 미과금(비용 0)
        log.error("hybrid 컷 %s I2V 실패 → 스틸 폴백: %s", cut_no, exc)
        # ★ 미과금이라도 남긴다. "이 컷은 영상이 아니라 스틸이다"가 화면 품질을 설명하는
        #   신호이고, Veo 실패율은 폴백률 지표(§10)의 입력이다. 지금까지 로그에만 있었다.
        if record_ledger:
            cost_ledger.record(cost_ledger.build_attempt(
                asset_type="video", provider=vid_spec.provider, model_id=vid_spec.model,
                generation_mode=vid_spec.generation_mode, unit_type=vid_spec.unit_type,
                requested_units=tier_sec, billed_units=0.0,
                status="fallback", error_class=type(exc).__name__,
                directive_id=directive_id, render_job_id=render_job_id, render_job_kind=render_job_kind, cut_no=cut_no))
        return False, None, 0.0

    # 원장(작업 C): Veo 는 Batch 할인 없음 → mode=standard. 생성 1회만 기록(언어 공유 중복 방지, §6.3).
    #
    # ★★ 후보를 여러 개 뽑았으면 **후보마다 한 행**이다(attempt_no). 한 행으로 묶으면
    #   원장이 비용을 절반으로 거짓말한다 — 2개를 뽑았으면 2개 값을 낸 것이다.
    #   `attempt_no` 컬럼이 원래 그 용도라 마이그레이션이 필요 없다.
    #   채택 여부는 idempotency_key 꼬리(`#cand{k}{*}`)로 남긴다 — 나중에 "왜 이걸
    #   썼나"를 물을 수 있어야 한다.
    if record_ledger:
        _n = int((cand_pick or {}).get("n") or 1)
        _chosen = int((cand_pick or {}).get("index") or 0)
        for _k in range(_n):
            cost_ledger.record(cost_ledger.build_attempt(
                asset_type="video", provider=vid_spec.provider, model_id=vid_spec.model,
                generation_mode=vid_spec.generation_mode, unit_type=vid_spec.unit_type,
                requested_units=tier_sec, directive_id=directive_id,
                render_job_id=render_job_id, render_job_kind=render_job_kind, cut_no=cut_no,
                attempt_no=_k + 1,
                idempotency_key=(ledger_key(f"{content_h}#cand{_k}{'*' if _k == _chosen else ''}",
                                            render_job_id, directive_id)
                                 if _n > 1 else None)))
    if use_cache:
        try:
            dest = f"{directive_id}/assets/cut_{cut_no}.mp4"
            url = db.upload_render(clip_path, dest, "video/mp4")
            db.upsert_render_asset({
                "directive_id": directive_id, "cut_no": cut_no, "asset_type": "clip",
                "asset_url": url, "content_hash": content_h, "meta": {},
            })
        except Exception as exc:  # noqa: BLE001 — 캐시 기록 실패는 렌더를 막지 않음
            log.warning("클립 캐시 기록 실패(무시): %s", exc)
    return True, content_h, cost


def stage_video_hash(plan: dict[str, Any], cuts: list[dict[str, Any]],
                     header: dict[str, Any]) -> str:
    """stage 영상 캐시 키. **언어·나레이션 길이를 넣지 않는다** — 그래야 KO 가 만든 영상을 EN 이 쓴다.

    결정 요인: stage 소속 컷들의 화면 해시(assemble.content_hash — 이미지·모션 프롬프트·생성 사양)와
    연출 계약(temporal_plan). 클립 분할(plan['clips'])은 나레이션 길이에서 나오므로 넣지 않는다.
    """
    import hashlib
    import json

    parts = [str(plan.get("stage_id") or "")]
    for idx in plan.get("indexes") or []:
        c = cuts[idx]
        parts.append(assemble.content_hash(c, header))
        parts.append(json.dumps(c.get("temporal_plan") or [], ensure_ascii=False, sort_keys=True))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _stage_lead_no(plan: dict[str, Any], cuts: list[dict[str, Any]]) -> int:
    return int(cuts[plan["indexes"][0]].get("cut_no") or 0)


def _cached_stage_video(plan: dict[str, Any], cuts: list[dict[str, Any]], header: dict[str, Any],
                        work_dir: str, gi: int, directive_id: str | None) -> tuple[str | None, float]:
    """캐시된 stage 영상이 있으면 (경로, 0.0), 없으면 (None, 0.0). 실패는 조용히 재생성으로 넘긴다."""
    paid = config.VIDEO_PROVIDER not in ("placeholder", "")
    if not (directive_id and paid and config.STAGE_VIDEO_CACHE_ENABLED):
        return None, 0.0
    try:
        existing = db.get_render_asset(directive_id, _stage_lead_no(plan, cuts), "stage_video")
        h = stage_video_hash(plan, cuts, header)
        if not (assemble.cache_hit(existing, h) and existing.get("asset_url")):
            return None, 0.0
        path = os.path.join(work_dir, f"stage_{gi}.mp4")
        _download_to(existing["asset_url"], path)
    except Exception as exc:  # noqa: BLE001 — 캐시 실패면 만든다(렌더를 막지 않는다)
        log.warning("stage %s 영상 캐시 조회 실패(재생성): %s", plan.get("stage_id") or gi, exc)
        return None, 0.0
    # 이 언어의 나레이션이 캐시 영상보다 길면 마지막 프레임으로 메운다(_build_stage_video 와 같은 규칙).
    have = assemble.probe_duration(path)
    need = float(plan["total_sec"])
    if have > 0 and need - have > config.STAGE_SHORTFALL_TOLERANCE_SEC:
        padded = os.path.join(work_dir, f"stage_{gi}_padded.mp4")
        try:
            assemble.run_ffmpeg(assemble.build_pad_video_command(
                video_path=path, out_path=padded, target_sec=need))
            path = padded
        except Exception as exc:  # noqa: BLE001
            log.error("캐시 stage %s 길이 메우기 실패: %s", plan.get("stage_id") or gi, exc)
    log.info("stage %s 영상 캐시 재사용(언어 공유, 생성비 0) %.1f초 → 필요 %.1f초",
             plan.get("stage_id") or gi, have, need)
    return path, 0.0


def _store_stage_video(path: str, plan: dict[str, Any], cuts: list[dict[str, Any]],
                       header: dict[str, Any], directive_id: str | None) -> None:
    """방금 만든 stage 영상을 캐시에 남긴다. 실패는 무시(렌더를 막지 않는다)."""
    paid = config.VIDEO_PROVIDER not in ("placeholder", "")
    if not (directive_id and paid and config.STAGE_VIDEO_CACHE_ENABLED and path):
        return
    try:
        lead = _stage_lead_no(plan, cuts)
        url = db.upload_render(path, f"{directive_id}/assets/stage_{lead}.mp4", "video/mp4")
        db.upsert_render_asset({
            "directive_id": directive_id, "cut_no": lead, "asset_type": "stage_video",
            "asset_url": url, "content_hash": stage_video_hash(plan, cuts, header),
            "meta": {"stage_id": plan.get("stage_id") or "", "total_sec": plan.get("total_sec")},
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("stage 영상 캐시 기록 실패(무시): %s", exc)


def _obtain_still(cut: dict[str, Any], header: dict[str, Any], img_path: str,
                  *, asset_index: dict[int, str] | None,
                  seq_decision: dict[str, Any] | None,
                  directive_id: str | None, render_job_id: str | None,
                  render_job_kind: str,
                  reuse_out: list[dict[str, Any]] | None = None) -> float:
    """이 컷의 **첫 그림**을 얻는다. 반환: 비용(재사용·파생이면 0).

    ★★ 스틸 컷과 영상 컷이 **같은 이 함수**를 쓴다. 예전엔 두 분기가 각자 그림을 얻었고,
      그래서 v3 참조 조건 생성을 스틸 쪽에만 넣었더니 **영상 컷에서는 안 돌았다** —
      실사형은 대부분이 영상 컷이라 사실상 주 경로가 빠진 셈이었다.
      갈라져 있으면 한쪽만 고치는 일이 반복된다. 합쳐서 그것을 구조로 막는다.

    우선순위:
      ① base_asset_ref 재사용 (기존 계약)
      ② RETURN_WORLD 파생 — 이미 그린 세계로 돌아간다(생성 호출 0).
         **변화를 선언하지 않은 컷만** 여기로 온다 — 파생은 변화를 그리지 못한다
         (`_derive_from_stage` 참조). 갈림은 `sequence_render.reference_decision` 이 정한다.
      ③ 참조 조건 생성 — 앞 stage 그림에서 다음 상태를 만든다
      ④ 텍스트 전용 생성 — 참조가 아예 없을 때만
    """
    # ★ 실사형은 스틸 복사 재사용을 타지 않는다(2026-09-05). 정규화가 이미 new_asset 으로
    #   바꾸지만, **저장된 옛 지시서**를 렌더할 때를 위해 여기서도 막는다 — 한쪽만 두면
    #   옛 지시서가 다시 "같은 사진 20초"를 만든다.
    if (str(header.get("version_type") or "") != "photo"
            and _reuse_base_image(cut, img_path, asset_index, reuse_out)):
        return 0.0
    dec = seq_decision or {}
    if dec.get("kind") == "derive" and _derive_from_stage(cut, img_path, dec):
        return 0.0
    # ★ 파생이 **실패했을 때도 참조는 붙인다.** 예전엔 `kind == "reference"` 일 때만 참조를
    #   실어서, 파생이 실패하면 텍스트 전용 생성으로 떨어지고 **세계가 통째로 사라졌다** —
    #   RETURN_WORLD 는 "이미 그린 세계로 돌아간다"는 뜻인데 그 세계를 잃는 것이 가장 나쁜
    #   결말이다. 파생이든 참조든 우리가 가진 것은 같은 앞 그림 하나다.
    ref_path = (dec.get("ref_asset") or None) if dec.get("kind") in ("reference", "derive") else None
    ref_key = str(dec.get("reference_key") or "")
    cost = _gen_still(
        cut, header, img_path, directive_id, render_job_id, render_job_kind,
        ref_path=ref_path, reference_key=ref_key)

    # ★ 멀티모달 연속성 QA (계획서 Phase 3 D2). 참조를 걸고 그린 컷만 본다 —
    #   참조가 없으면 "이어졌는가"라는 질문 자체가 성립하지 않는다.
    #   ★★ 계획서 그대로: 실패하면 **재생성 1회**, 그래도 실패면 기록하고 **진행한다.**
    #     렌더를 죽이지 않는다 — 화면이 비는 것이 가장 나쁜 결말이다(§10-5 와 같은 자세).
    #   ★ 기록은 `dec["degraded"]` 로 간다. sequence_render.degraded_summary 가 이미
    #     그 코드를 세는 그릇이라 새 표면을 만들지 않는다 — 그릇은 있는데 넣는 곳이
    #     없던 것이 이 작업 전의 상태였다.
    if ref_path and continuity_qa.enabled():
        if continuity_qa.failed(continuity_qa.judge(ref_path, img_path)):
            log.warning("컷 %s 연속성 실패 → 재생성 1회", cut.get("cut_no"))
            cost += _gen_still(
                cut, header, img_path, directive_id, render_job_id, render_job_kind,
                ref_path=ref_path, reference_key=ref_key)
            if continuity_qa.failed(continuity_qa.judge(ref_path, img_path)):
                dec.setdefault("degraded", []).append(
                    continuity_qa.DEGRADED_WORLD_CHANGED)
                log.warning("컷 %s 재생성 뒤에도 세계가 다르다 — 기록하고 진행",
                            cut.get("cut_no"))
    return cost


def _gen_cut_assets(cut: dict[str, Any], header: dict[str, Any], work_dir: str, idx: int,
                    directive_id: str | None = None, lang: str = "ko",
                    asset_index: dict[int, str] | None = None,
                    fact_sheet: dict[str, Any] | None = None,
                    render_job_id: str | None = None,
                    render_job_kind: str = "paper",
                    board_qa_out: list[dict[str, Any]] | None = None,
                    stage_out: dict[str, Any] | None = None,
                    chain: dict[str, Any] | None = None,
                    seq_decision: dict[str, Any] | None = None,
                    clip_metrics_out: list[dict[str, Any]] | None = None,
                    reuse_out: list[dict[str, Any]] | None = None,
                    ) -> tuple[str, str, str, int, float, list[dict[str, Any]]]:
    """컷 1개의 오디오 + 비주얼(애니 클립 or 스틸) 생성. 컷 화면 시간 = 나레이션 길이.
    반환: (visual_path, kind['image'|'clip'], audio_path, measured_sec, cost, words).

    ③ scene_kind 가 고효율(코드 기반)이면 Manim 클립을 먼저 시도하고, 실패 시(예: manim 미설치)
    placeholder 스틸로 폴백한다(전체 중단 금지, 명세 §7-3). 그 외는 스틸+켄번스.
    ⑤ lang 은 TTS 보이스·나레이션·클립 텍스트에 반영(언어별 재렌더).

    ★ 실행 순서는 TTS 우선이다(수정명세 v1 §3-2) — 나레이션 실측 길이를 먼저 확정한 뒤 그 값으로
    영상 클립 길이 티어를 고른다. TTS 는 무료·재시도가 싸고 유료 영상 생성이 뒤로 밀려 비용에도 유리.
    """
    aud_path = os.path.join(work_dir, f"cut_{idx}.m4a")
    # §10 — TTS 를 따로 잰다. 이 함수 전체가 asset_ms 한 덩어리로 잡히면 "느린 렌더의 원인이
    # TTS 인가 유료 생성인가 컷 ffmpeg 인가"를 구분할 수 없다. 컷마다 누적한다.
    _t0 = time.monotonic()
    tts = tts_provider.synthesize(cut, aud_path, lang)
    if stage_out is not None:
        stage_out["tts_ms"] = stage_out.get("tts_ms", 0) + int((time.monotonic() - _t0) * 1000)
    measured, cost, words = tts["sec"], tts["cost"], tts["words"]

    scene_kind = cut.get("scene_kind") or config.VERSION_DEFAULT_SCENE_KIND.get(
        header.get("version_type"), "")

    # ★ 설명판형 코드 보드(최종명세 v3.3 §21 K1·K2) — 화면의 숫자·차트는 코드가 그린다.
    #   이 분기가 **Veo/이미지 분기보다 앞**에 있는 것이 핵심이다: 보드 컷은 유료 생성 경로에
    #   도달할 수 없다. K2("보드에 생성 자산 절대 금지")가 정책이 아니라 구조로 강제된다.
    #   반환 kind 는 "clip" 이다 — 스틸로 내면 호출측이 켄번스(zoompan 1.18 크롭)를 자동 주입해
    #   밴드 좌표가 깨진다. clip 으로 내면 _render_cut_clips 를 한 줄도 고치지 않는다.
    #   논문 라인은 code_render_board 가 version_type 을 보고 즉시 None → 도달 불가.
    if board_render.code_render_board(cut, header):
        try:
            res = board_render.render_board(cut, header, fact_sheet, work_dir, idx,
                                            total_sec=measured, lang=lang)
            clip_path = os.path.join(work_dir, f"cut_{idx}.mp4")
            assemble.run_ffmpeg(assemble.build_board_clip_command(
                frame_paths=res.frame_paths, fps=res.fps, audio_path=aud_path,
                out_path=clip_path, concat_file=os.path.join(work_dir, f"board_{idx}.txt")))
            # ★ v3.4 §22-6 — fail 이 하나라도 있으면 **잡을 실패시킨다.** 예전에는 경고만 남기고
            #   진행했고, 그 아래 except 가 계약 위반(K9 말줄임 대상·K10 중복)까지 삼켜 생성
            #   스틸로 폴백했다. 그 폴백 자체가 K2("보드에 생성 자산 금지") 위반이라 원래
            #   틀린 길이었다. 지금은 화면이 규격을 어기면 영상이 안 나온다.
            # ★ 보드 판정을 기록한다 (v3 §9 Q1 선행 · P3-b). 지금까지 fail 만 예외로 쓰고
            #   core_fill·frame_qa·warn 은 **어디에도 남지 않았다** — 그래서 "충전율 기준을
            #   0.30 에서 올려도 되나"를 물으면 답할 데이터가 없었다.
            #   ★★ 판정 정책은 그대로 둔다(warn 은 여전히 warn). 기록만 시작한다.
            if board_qa_out is not None:
                board_qa_out.append({
                    "cut_no": int(cut.get("cut_no") or (idx + 1)),
                    "board": cut.get("board") or "",
                    "core_fill": round(res.core_fill, 4),
                    # ★ layout_fail 을 반드시 함께 남긴다. 충전율 판정이 warn → fail 로
                    #   올라간 순간(v3 §9), core_underfilled 는 layout_warn 에서 빠진다 —
                    #   이 줄이 없으면 승격과 동시에 **기록이 눈이 먼다**(실패 사유가 잡
                    #   error_log 에만 남아 컷 단위로 못 센다). 이 append 는 아래 raise 보다
                    #   앞에 있으므로 규격 위반으로 죽는 컷도 여기 남는다.
                    "layout_fail": res.layout_qa.get("fail") or [],
                    "layout_warn": res.layout_qa.get("warn") or [],
                    # §8-1 — 선언한 레이어 중 무엇이 빠졌고 무엇이 폴백으로 그려졌나.
                    "manifest": res.manifest,
                    # §9 Q3 — 카운트업이 정지된 숫자로, 막대가 안 자란 채로 나갔는가.
                    #   terminal_status 가 이 목록을 important(degraded)로 올린다.
                    "animation": res.animation,
                    "animation_fail": res.animation_fail,
                    "frame_fail": res.frame_qa.get("fail") or [],
                    "frame_warn": res.frame_qa.get("warn") or [],
                })
            # ★ 실패를 둘로 가른다. "화면 규격 위반"(밴드 침범·안전선 초과·중복)은 즉시
            #   실패 — 그 화면은 나가면 안 된다. "허전함"(core_underfilled)은 영상을 만들어
            #   올린 뒤 사람에게 넘긴다(degraded). 둘을 한 덩어리로 두는 바람에 설명판형이
            #   두 주 동안 렌더 자체를 못 했다(8건 중 5건이 이 한 사유로 사망).
            blocking = [f for f in (res.layout_qa.get("fail") or [])
                        if not f.startswith(config.LAYOUT_FAIL_REVIEWABLE)]
            if blocking:
                raise ValueError(
                    f"컷 {cut.get('cut_no')} 보드 규격 위반(§22-6): " + ", ".join(blocking))
            return clip_path, "clip", aud_path, measured, cost, words
        except (board_render.BoardFontError, ValueError):
            # 폰트 부재(K8) · 텍스트 초과(K9) · 화면 중복(K10) · 프레임 판정(§22-6)은 전부
            # "대본이나 자산을 고쳐라"는 신호다. 삼키면 킬 스위치가 무력해진다.
            raise
        except Exception as exc:  # noqa: BLE001
            # 계약과 무관한 사고(디스크·ffmpeg)만 편 전체를 죽이지 않게 스틸로 폴백한다.
            log.error("컷 %s 보드 렌더 실패 → 스틸 폴백: %s", cut.get("cut_no"), exc)

    # motion_source=video 컷은 I2V(스틸 첫 프레임 → Veo 모션). 모든 버전 공통. 미배선/실패 시 스틸 폴백.
    if cut.get("motion_source") == "video":
        img_path = os.path.join(work_dir, f"cut_{idx}.png")
        # ★ I2V 연쇄(실사형): 앞 영상 컷의 **마지막 프레임**을 이 컷의 시작 화면으로 쓴다.
        #   그래야 카메라가 끊기지 않고 같은 장소가 이어진다 — 벤치마크 채널의 "이어지는 느낌"이
        #   화풍 일관성이 아니라 여기서 나온다(docs/benchmark-realistic-shorts-2026-08-19.md).
        #   부수 효과: 이 컷은 새 이미지를 사지 않는다($0.039 절약).
        chained = False
        prev_frame = (chain or {}).get("frame")
        # ★ 시작 화면을 결정한 값. 연쇄면 앞 클립의 캐시 키, 아니면 이 컷 스틸의 캐시 키다.
        #   이 값이 클립 캐시 키에 들어가 **앞 컷이 바뀌면 뒤 컷 캐시가 무효화**된다.
        start_asset_key = assemble.content_hash(cut, header)
        if (prev_frame and os.path.exists(prev_frame)
                and str(header.get("version_type") or "") in config.I2V_CHAIN_VERSIONS
                and cut.get("asset_strategy") not in config.ASSET_STRATEGY_REUSE):
            shutil.copyfile(prev_frame, img_path)
            chained = True
            # 생성물을 anchor 로 한 번 더 쓴다 — 깊이를 센다(상한은 호출측이 검사).
            chain["depth"] = int(chain.get("depth") or 0) + 1
            start_asset_key = str((chain or {}).get("clip_key") or prev_frame)
            log.info("컷 %s I2V 연쇄 — 앞 영상 컷의 마지막 프레임에서 이어 만든다(생성 호출 0)",
                     cut.get("cut_no"))
        # ★ 영상 컷의 첫 프레임도 재사용·파생 경로를 먼저 탄다. 예전엔 무조건 새로 생성했는데,
        #   그러면 "1번 장면으로 돌아오는 마지막 영상 컷"이 같은 그림을 돈 주고 다시 만든다.
        # ★ 연쇄가 걸리면 앞 클립의 마지막 프레임이 이미 첫 화면이다(카메라가 끊기지 않는다).
        #   연쇄가 없을 때만 그림을 얻는다 — 스틸 컷과 **같은 함수**를 쓴다.
        if not chained:
            cost += _obtain_still(
                cut, header, img_path, asset_index=asset_index, seq_decision=seq_decision,
                directive_id=directive_id, render_job_id=render_job_id,
                render_job_kind=render_job_kind, reuse_out=reuse_out)
        # ★ 그리고 그 스틸을 인덱스에 남긴다. 호출측은 kind=="image" 인 컷만 인덱싱하므로,
        #   여기서 넣지 않으면 뒤 컷이 이 영상 컷을 base_asset_ref 로 가리켜도 기준을 못 찾아
        #   유료 생성으로 떨어진다(이미 만들어 둔 스틸이 있는데도).
        if asset_index is not None:
            asset_index.setdefault(int(cut.get("cut_no") or (idx + 1)), img_path)
        clip_path = os.path.join(work_dir, f"cut_{idx}.mp4")
        # I2V Veo 클립(언어 무관 캐시 — KO/EN 이 같은 클립 공유). 실패 시 그 스틸로 폴백.
        # ★ 실패해도 c 는 더한다 — VeoBilledRejection 이면 c>0(과금된 산출물 폐기, §8.5) 이라
        # 폴백해도 실효 비용은 이 컷의 총비용에 반영돼야 job 예산 가드(_on_cost)가 이를 본다.
        ok, clip_key, c = _gen_veo_clip(cut, header, clip_path, img_path, directive_id,
                                        narration_sec=measured, render_job_id=render_job_id,
                                        render_job_kind=render_job_kind,
                                        start_asset_key=start_asset_key,
                                        clip_metrics_out=clip_metrics_out)
        if ok:
            # 다음 영상 컷이 이어받을 마지막 프레임. 실패해도 렌더를 세우지 않는다 —
            # 프레임이 없으면 다음 컷은 평소대로 새 스틸을 만든다(연쇄만 끊긴다).
            if chain is not None and str(header.get("version_type") or "") in config.I2V_CHAIN_VERSIONS:
                frame_path = os.path.join(work_dir, f"chain_{idx}.png")
                try:
                    assemble.run_ffmpeg(assemble.build_last_frame_command(clip_path, frame_path))
                    chain["frame"] = frame_path
                    # 다음 컷의 시작 화면을 결정한 값 = 이 클립의 캐시 키.
                    chain["clip_key"] = clip_key
                except Exception as exc:  # noqa: BLE001
                    log.warning("컷 %s 마지막 프레임 추출 실패 — 연쇄 끊김(무시): %s",
                                cut.get("cut_no"), exc)
            return clip_path, "clip", aud_path, measured, cost + c, words
        return img_path, "image", aud_path, measured, cost + c, words

    wants_clip = config.ANIMATION_ENGINE != "off" and \
        render_kind_for_scene(scene_kind, header.get("version_type"),
                              cut, fact_sheet) == "clip"
    if wants_clip:
        clip_path = os.path.join(work_dir, f"cut_{idx}.mp4")
        last_exc: Exception | None = None
        for attempt in range(config.ASSET_RETRY + 1):
            try:
                _, c = video_provider.generate_clip(cut, header, clip_path, measured, lang,
                                                    fact_sheet=fact_sheet)
                return clip_path, "clip", aud_path, measured, cost + c, words
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("컷 %s 클립 실패(attempt %d): %s", cut.get("cut_no"), attempt + 1, exc)
        log.error("컷 %s 클립 최종 실패 → 스틸 폴백: %s", cut.get("cut_no"), last_exc)

    img_path = os.path.join(work_dir, f"cut_{idx}.png")
    # §10-5 재사용 · v3 파생 · v3 참조 조건 생성 — 전부 _obtain_still 안에 있다.
    cost += _obtain_still(
        cut, header, img_path, asset_index=asset_index, seq_decision=seq_decision,
        directive_id=directive_id, render_job_id=render_job_id,
        render_job_kind=render_job_kind, reuse_out=reuse_out)
    return img_path, "image", aud_path, measured, cost, words


def _derive_from_stage(cut: dict[str, Any], img_path: str,
                       decision: dict[str, Any]) -> bool:
    """RETURN_WORLD — 앞서 그린 세계의 그림에서 **파생**한다(생성 호출 0).

    ★ 왜 새로 만들지 않는가: 되돌아가는 것이므로 같은 픽셀에서 나오는 편이 더 정확하고 공짜다.
      컷이 크롭·톤을 선언했으면 그것을 적용하고, 아니면 그대로 복사한다.

    ★★ **이 함수는 변화를 그리지 못한다.** 크롭·톤 말고는 앞 그림 그대로다. 그래서
      "눈에 보이는 변화를 선언한 stage" 는 애초에 여기로 오지 않는다 —
      `sequence_render.reference_decision` 이 그런 컷을 `reference`(참조 조건 생성)로
      보낸다. 그 갈림이 없던 시절 골든B 컷6 이 HIGHLIGHT 를 선언하고도 앞 그림을
      바이트 복사로 내보냈다(2026-08-30 실측). 판정을 여기서 **다시** 하지 않는 이유는
      같은 질문에 두 벌의 답을 만들지 않기 위해서다 — 정본은 저 한 곳이다.

    ★ 실패하면 False 를 돌려 **참조 조건 생성으로 떨어진다**(`_obtain_still`).
      파생이 안 된다고 컷을 비우지도, 세계를 잃지도 않는다.
    """
    base = str(decision.get("ref_asset") or "")
    if not base or not os.path.exists(base):
        return False
    try:
        if crop.has_work(cut.get("crop"), cut.get("tone_grade")):
            crop.derive_image(base, img_path, cut.get("crop"), cut.get("tone_grade"))
        else:
            shutil.copyfile(base, img_path)
        log.info("컷 %s RETURN_WORLD → stage %s 에서 파생(생성 호출 0)",
                 cut.get("cut_no"), decision.get("ref_stage"))
        return True
    except Exception as exc:  # noqa: BLE001 — 파생 실패는 생성으로 떨어질 뿐이다
        log.warning("컷 %s 파생 실패 → 생성으로 진행: %s", cut.get("cut_no"), exc)
        return False


def _decide_clip_fit(clip_path: str, cut: dict[str, Any],
                     narration_sec: float) -> clip_fit_types.Strategy:
    """클립 실측 길이 ↔ 나레이션 길이 갭 → 보정 전략(§3-3). 컷별 로그 1줄을 남긴다.

    loop_safe 는 지시서가 컷 단위로 선언한다(§3-4). 미지정이면 안전측 기본값(핑퐁 금지 → 홀드).
    실측이 실패해 clip_sec=0 이면 "클립이 나레이션보다 훨씬 짧다"와 같아 홀드/플래그로 처리된다.
    """
    clip_sec = assemble.probe_duration(clip_path)
    loop_safe = bool(cut.get("loop_safe", config.CLIP_FIT_LOOP_SAFE_DEFAULT))
    strategy = clip_fit_types.decide(clip_sec, narration_sec, loop_safe)
    log.info("컷 %s 길이보정: clip=%.2fs narration=%.2fs ratio=%.3f loop_safe=%s strategy=%s",
             cut.get("cut_no"), strategy.clip_sec, strategy.narration_sec,
             strategy.ratio, loop_safe, strategy.kind)
    return strategy


def _build_stage_video(plan: dict[str, Any], cuts: list[dict[str, Any]],
                       header: dict[str, Any], work_dir: str, gi: int,
                       *, start_image: str, lang: str,
                       clip_metrics_out: list[dict[str, Any]] | None = None,
                       directive_id: str | None = None,
                       render_job_id: str | None = None,
                       render_job_kind: str = "paper",
                       qa_out: list[dict[str, Any]] | None = None,
                       ) -> tuple[str, float]:
    """stage 하나 → **끊김 없는 연속 영상 하나**. 반환: (mp4 경로, 비용).

    ★★ 이것이 시퀀스 렌더의 본체다. 컷마다 클립을 만들던 것을 그만두고, stage 길이를
      덮는 클립들을 **연쇄로** 만들어(앞 클립의 마지막 프레임 → 다음 클립의 첫 프레임)
      하나로 잇는다. 컷은 나중에 이 영상의 서로 다른 구간을 볼 뿐이다.

    ★ 왜 연쇄인가: Veo 가 한 번에 8초까지만 만든다(물리 제약). 20초 stage 를 한 번에
      만들 수는 없고, 이어 만드는 것이 "같은 장면이 계속되는" 유일한 길이다.
    ★ 연쇄가 끊기는 지점(chain_breaks 가 False)에서는 **원본 그림으로 되돌아간다** —
      깊이가 깊을수록 인물·재질이 흐려지기 때문이다(MAX_CHAIN_DEPTH 의 근거).
    ★ 클립 하나가 실패하면 **거기까지 만든 것으로 잇는다.** stage 전체를 버리면 화면이
      비고, 그것이 가장 나쁜 결말이다(이 파일의 일관된 자세).

    프롬프트는 그 구간을 **대표하는 컷**의 것을 쓴다 — 클립 i 가 덮는 시간대에 걸친
    첫 컷이다. 한 stage 안 컷들은 같은 세계를 공유하므로 화면이 튀지 않는다.

    ★ lang 을 받지만 생성에 넘기지 않는다 — 화면은 언어와 무관하고(컷 경로도 같다)
      KO/EN 이 같은 영상을 공유한다. 인자를 남겨 둔 것은 호출 형태를 컷 경로와 맞추기
      위해서다. 자막·나레이션만 언어를 탄다.
    """
    del lang  # 위 주석 참조 — 화면은 언어를 타지 않는다.
    lead = cuts[plan["indexes"][0]]
    sid = plan["stage_id"] or str(gi)
    clips: list[str] = []
    cost = 0.0
    anchor_img = start_image
    prev_frame: str | None = None
    # 클립 i 가 덮는 시간대 → 그 시간대를 여는 컷(프롬프트 출처)
    windows = plan["windows"]
    elapsed = 0.0
    paid = config.VIDEO_PROVIDER not in ("placeholder", "")
    for i, (sec, chained) in enumerate(zip(plan["clips"], plan["chained"])):
        # 이 클립이 시작하는 시각에 해당하는 컷을 찾는다(없으면 stage 의 첫 컷).
        owner = lead
        for k, (w_start, w_dur) in enumerate(windows):
            if w_start <= elapsed < w_start + w_dur:
                owner = cuts[plan["indexes"][k]]
                break
        clip_path = os.path.join(work_dir, f"stage_{gi}_{i}.mp4")
        start_img = prev_frame if (chained and prev_frame) else anchor_img
        cut_no = int(owner.get("cut_no") or 0)
        # ★ 스펙을 만들어 넘긴다 — 컷 경로와 **같은 계약**이다(P0-2: 예상 = 발주 = 기록).
        #   길이는 여기서 정한다(plan 이 정본) — 나레이션에서 티어를 다시 고르면 시퀀스
        #   계획이 무의미해진다. 등급·후보 수는 컷 경로와 같은 판정을 그대로 쓴다.
        tier_info = sequence_tier.effective_tier(owner, header)
        vid_spec = generation_spec.video_spec(
            owner, header, clip_sec=int(sec),
            start_asset_hash=generation_spec.asset_logical_hash(start_img or ""),
            tier=tier_info["tier"],
            candidates=sequence_tier.candidates_for(owner, header))
        try:
            c, _pick = _veo_generate_scored(
                owner, header, clip_path, int(sec), start_img, vid_spec,
                cut_no=cut_no, clip_metrics_out=clip_metrics_out,
                metrics_extra={"stage_id": plan["stage_id"], "clip_index": i,
                               "chained": bool(chained)})
            cost += c
            clips.append(clip_path)
            # ★★ 원장에 남긴다. 시퀀스 경로가 provider 를 직접 부르던 첫 구현은 **비용을
            #   한 줄도 기록하지 않았다** — 그러면 stage 로 렌더한 편은 영상비가 0으로
            #   보이고, Phase 4 하드 게이트(영상 비용 원장)가 조용히 눈이 먼다.
            if paid:
                cost_ledger.record(cost_ledger.build_attempt(
                    asset_type="video", provider=vid_spec.provider, model_id=vid_spec.model,
                    generation_mode=vid_spec.generation_mode, unit_type=vid_spec.unit_type,
                    requested_units=int(sec), directive_id=directive_id,
                    render_job_id=render_job_id, render_job_kind=render_job_kind,
                    cut_no=cut_no, attempt_no=i + 1,
                    idempotency_key=ledger_key(f"stage:{sid}#clip{i}",
                                               render_job_id, directive_id)))
            # 다음 클립이 이어받을 마지막 프레임
            nxt = os.path.join(work_dir, f"stage_{gi}_{i}_last.png")
            prev_frame = nxt if clip_candidates.last_frame(clip_path, nxt) else None
        except Exception as exc:  # noqa: BLE001
            log.warning("stage %s 클립 %d 실패(여기까지로 잇는다): %s", sid, i, str(exc)[:140])
            if paid:
                cost_ledger.record(cost_ledger.build_attempt(
                    asset_type="video", provider=vid_spec.provider, model_id=vid_spec.model,
                    generation_mode=vid_spec.generation_mode, unit_type=vid_spec.unit_type,
                    requested_units=int(sec), billed_units=0.0,
                    status="fallback", error_class=type(exc).__name__,
                    directive_id=directive_id, render_job_id=render_job_id,
                    render_job_kind=render_job_kind, cut_no=cut_no, attempt_no=i + 1))
            break
        elapsed += float(sec)

    if not clips:
        raise RuntimeError(f"stage {sid} 클립을 하나도 못 만들었다")
    out = os.path.join(work_dir, f"stage_{gi}.mp4")
    if len(clips) == 1:
        shutil.copyfile(clips[0], out)
    else:
        assemble.run_ffmpeg(assemble.build_concat_clips_command(
            clip_paths=clips, out_path=out,
            concat_file=os.path.join(work_dir, f"stage_{gi}_concat.txt")))

    # ★★ 컷들이 볼 구간이 영상 끝을 넘지 않는지 **실측으로** 확인한다. 계획은 나레이션을
    #   덮도록 세웠지만(plan_clips), 클립이 실패해 중간에 끊겼으면 짧다. 그대로 두면 뒤
    #   컷의 -ss 가 영상 밖을 가리켜 **나레이션이 잘린다** — 말이 잘리는 것이 화면이
    #   멈추는 것보다 나쁘다. 짧으면 마지막 프레임으로 메우고 **반드시 남긴다**.
    have = assemble.probe_duration(out)
    need = float(plan["total_sec"])
    short_by = round(need - have, 3)
    if have > 0 and short_by > config.STAGE_SHORTFALL_TOLERANCE_SEC:
        padded = os.path.join(work_dir, f"stage_{gi}_padded.mp4")
        try:
            assemble.run_ffmpeg(assemble.build_pad_video_command(
                video_path=out, out_path=padded, target_sec=need))
            out = padded
            log.warning("stage %s 영상이 %.2f초 짧다 → 마지막 프레임으로 메움(정지 발생)",
                        sid, short_by)
        except Exception as exc:  # noqa: BLE001 — 메우기 실패해도 있는 영상으로 간다
            log.error("stage %s 길이 메우기 실패(나레이션이 잘릴 수 있다): %s", sid, exc)
        if qa_out is not None:
            qa_out.append({"stage_id": sid, "code": "stage_short",
                           "need_sec": need, "have_sec": round(have, 3),
                           "short_by_sec": short_by,
                           "clips_planned": len(plan["clips"]), "clips_made": len(clips)})
    log.info("stage %s 영상 완성: 클립 %d개 %.1f초 (나레이션 %.1f초)",
             sid, len(clips), sum(plan["clips"][:len(clips)]), need)
    return out, cost


def _render_cut_clips(directive: dict[str, Any], work_dir: str,
                      on_cost: Callable[[float], None] | None = None,
                      directive_id: str | None = None, lang: str = "ko",
                      fit_log: list[dict[str, Any]] | None = None,
                      clip_metrics_out: list[dict[str, Any]] | None = None,
                      overlay_out: list[tuple[float, float, str, str]] | None = None,
                      cut_map_out: list[dict[str, Any]] | None = None,
                      render_job_id: str | None = None,
                      render_job_kind: str = "paper",
                      board_qa_out: list[dict[str, Any]] | None = None,
                      # ★ stage 영상이 계획보다 짧아 마지막 프레임으로 메운 기록.
                      #   board_qa 와 섞지 않는다 — 저건 **컷별** 보드 판정이고 이건 stage 단위다.
                      #   (terminal_status 가 board_qa 의 manifest 를 읽어 잡의 성패를 정하므로
                      #    성격이 다른 항목을 그 통에 넣으면 나중에 판정이 흐려진다.)
                      stage_qa_out: list[dict[str, Any]] | None = None,
                      stage_out: dict[str, Any] | None = None,
                      seq_out: list[dict[str, Any]] | None = None,
                      reuse_out: list[dict[str, Any]] | None = None,
                      ) -> tuple[list[str], list[tuple[float, float, str]], float,
                                 list[tuple[float, float]]]:
    """지시서의 모든 컷 → (컷 mp4 목록, 자막 큐, 총길이, 더킹 구간). 컷 화면 시간 = 나레이션 길이.

    ⑤ lang: 언어별 나레이션·보이스·클립·자막(탄력 섹션 — 언어별 독립 재타이밍).
    ① 자막: 단어 타임스탬프가 있으면 레이트 기반 청킹(chunk_by_rate), 없으면 컷 단위.
    ④ 더킹: 전역 VO 스팬을 모아 반환(엔벨로프 더킹 입력). 자막은 조립 최종 단계에서 번인.
    ⑥ fit_log(수정명세 v1 §3-6): 컷별 길이 보정 결정을 여기에 append 한다(렌더 로그·QA 입력).
    ⑦ overlay_out(§11): 근거 오버레이 ASS 이벤트를 여기에 채운다. 컷 시작시각은 나레이션 실측
       기준이라 여기서만 알 수 있다(fit_log 와 같은 out-param 패턴 — 반환 시그니처 불변).
    ⑧ cut_map_out(v3 §8-1 P3-a): 컷 ↔ 최종 mp4 시간축 대응. 지금까지 cut_starts/cut_durs 를
       계산해 놓고 오버레이에만 쓰고 **버렸다** — 그래서 "몇 초 지점의 어느 컷이 실패했나"를
       뒤에서 물을 수 없었다. manifest 대조(§8-1)와 AV 길이 QA(§9 Q5)의 공통 선행 재료다.
       fit_log·overlay_out 과 같은 패턴이라 반환 시그니처는 그대로다.
    ⑨ seq_out(v3 Phase 3): 컷별 시각 시퀀스 판정(참조·파생·세계 리셋·연속성 저하)을 채운다.
       **세계를 몇 번 새로 만들었는가**가 v3 의 핵심 지표라 렌더 밖으로 나가야 한다 —
       안에서 로그만 찍고 버리면 "이 편이 정말 이어졌나"를 나중에 물을 수 없다.
    """
    cuts = directive.get("cuts") or []
    header = directive.get("header") or {}
    # 코드 차트 수치는 원장에서 해소한다(M-E4). 지시서에 실려 있으면 그걸, 없으면 None.
    fact_sheet = directive.get("fact_sheet")
    cut_files: list[str] = []
    cues: list[tuple[float, float, str]] = []
    vo_words: list[dict[str, Any]] = []  # ④ 전역 VO 스팬(더킹 엔벨로프용)
    # §10-5 에셋 재사용: 컷 번호 → 그 컷이 만든 스틸 경로. 뒤 컷이 base_asset_ref 로 참조한다.
    # (참조는 앞선 컷만 가리킬 수 있으므로 순차 채움으로 충분하다 — validate_reuse_refs 가 강제.)
    asset_index: dict[int, str] = {}
    # I2V 연쇄 상태: 직전 영상 컷의 마지막 프레임 경로. 다음 영상 컷의 시작 화면이 된다.
    chain: dict[str, Any] = {"frame": None, "clip_key": None,
                             "world_ref": "", "depth": 0}
    # ★★ v3 Phase 3 — stage 별 그림 색인. 다음 stage 가 이것을 참조로 받는다.
    #   asset_index(컷 번호 → 그림)와 **다른 축**이다: 시퀀스는 stage 단위로 잇는다.
    stage_assets: dict[str, str] = {}
    seq_decisions: list[dict[str, Any]] = []
    prev_role: str = ""
    # ★★ 시퀀스(stage) 단위 렌더 — 설계안 docs/설계안_시퀀스단위_렌더_v1.md.
    #   컷마다 클립 1개를 만들면 컷 경계마다 화면이 끊기고, 나레이션이 클립보다 길면
    #   마지막 프레임이 얼어붙는다(실측: hold 5컷, 최악 4.7초 정지).
    #   stage 를 연속 영상 하나로 채우고 컷은 그 영상의 서로 다른 구간을 본다.
    #
    #   ★ 선행 패스로 TTS 를 먼저 돌린다 — stage 길이는 나레이션 실측의 합이라
    #     영상을 만들기 전에 알아야 한다. TTS 는 무료·빠르다(실측 14초/편).
    #   ★ 그 오디오를 루프가 다시 쓴다(_gen_cut_assets 를 건너뛴다) — 두 번 합성하면
    #     시간도 두 배고 두 파일의 길이가 미세하게 달라 싱크가 어긋난다.
    stage_mode = stage_render.enabled(header)
    stage_plans: list[dict[str, Any]] = []
    pre_audio: dict[int, dict[str, Any]] = {}
    stage_videos: dict[int, str] = {}      # 그룹 인덱스 → stage mp4
    cut_group: dict[int, tuple[int, int]] = {}   # 컷 인덱스 → (그룹, 그룹 내 순번)
    if stage_mode:
        _t0 = time.monotonic()
        for i, cut in enumerate(cuts):
            ap = os.path.join(work_dir, f"cut_{i}.m4a")
            pre_audio[i] = tts_provider.synthesize(cut, ap, lang)
        if stage_out is not None:
            stage_out["tts_ms"] = stage_out.get("tts_ms", 0) + int((time.monotonic() - _t0) * 1000)
        durations = [float(pre_audio[i]["sec"]) + float(config.CLIP_FIT_TAIL_PAD_SEC)
                     for i in range(len(cuts))]
        stage_plans = stage_render.plan_stage(cuts, durations)
        for gi, plan in enumerate(stage_plans):
            for k, ci in enumerate(plan["indexes"]):
                cut_group[ci] = (gi, k)
        log.info("시퀀스 단위 렌더: %s", stage_render.savings(stage_plans, len(cuts)))
        if stage_out is not None:
            stage_out["stage_plan"] = stage_render.savings(stage_plans, len(cuts))
    cut_starts: list[float] = []
    cut_durs: list[float] = []
    t = 0.0
    for i, cut in enumerate(cuts):
        # ★ 화면 역할이 바뀌면 앞 컷의 마지막 프레임을 물려받지 않는다(2026-08-28).
        #   실사(REALITY)와 3D 도해(MECHANISM)는 **다른 그림**이다 — 실사 화력발전소의 마지막
        #   프레임에서 3D 단면도를 이어 만들면 도해가 사진에서 뭉개지고, 그 컷에 프리미엄
        #   모델을 쓴 의미도 사라진다. 실측(8/21 지시서): 연쇄가 걸리는 2쌍(4→5, 7→8)이
        #   **둘 다** 역할을 넘고 있었다. 대가는 이미지 2장(+$0.27)이다.
        #   ★ 판정은 반드시 _gen_cut_assets **앞**이다 — 연쇄는 그 함수 안에서 소비되므로
        #     뒤에서 끊으면 이미 물려받은 뒤다(한 번 이 자리에서 틀렸다).
        if str(cut.get("visual_role") or "") != prev_role:
            chain["frame"] = None
            chain["clip_key"] = None
        # ★★ 세계가 바뀌면 사슬을 끊는다 (v2 Phase E, 코덱스 리뷰 §11).
        #
        #   종전에 사슬을 끊는 유일한 경계는 **사이에 낀 스틸**이었다. 그래서 video-first
        #   로 가면(스틸이 없어지면) 세계가 바뀌어도 사슬이 이어져 **엉뚱한 장소가 계속
        #   된다** — 데이터센터 장면 뒤에 공장 장면을 데이터센터 마지막 프레임에서
        #   이어 만드는 식이다. 비용이 아니라 정합성 문제라 video-first 의 선행조건이다.
        #
        #   ★ `None == None` 은 연쇄가 아니다(리뷰 §11 문제 1). 세계를 **모르는** 두 컷은
        #     같은 세계라는 근거가 없다 — 판정 불가를 "같다"로 읽지 않는다.
        world_ref = str((cut.get("resolved_visual_plan") or {}).get("world_ref") or "")
        _same_world = bool(world_ref) and world_ref == str(chain.get("world_ref") or "")
        if chain.get("frame") and not _same_world:
            chain["frame"] = None
            chain["clip_key"] = None
            chain["depth"] = 0
            log.info("컷 %s 세계 전환 → I2V 연쇄 끊음(%s → %s)", cut.get("cut_no"),
                     chain.get("world_ref") or "-", world_ref or "-")
        # ★ 생성물을 다시 anchor 로 쓰는 깊이 상한. 8초 클립이 길어질수록 identity·geometry
        #   드리프트가 누적된다(리뷰 §11 문제 2) — 일정 깊이마다 원본 그림으로 되돌린다.
        if int(chain.get("depth") or 0) >= config.MAX_CHAIN_DEPTH:
            chain["frame"] = None
            chain["clip_key"] = None
            chain["depth"] = 0
            log.info("컷 %s 연쇄 깊이 %s 도달 → 원본에서 다시 시작(드리프트 방지)",
                     cut.get("cut_no"), config.MAX_CHAIN_DEPTH)
        chain["world_ref"] = world_ref
        # ★★ v3 Phase 3 — 이 컷의 그림을 무엇으로 만들 것인가(순수 판정, 파일 접근 없음).
        decision = sequence_render.reference_decision(cut, header, stage_assets)
        decision["cut_no"] = int(cut.get("cut_no") or (i + 1))
        seq_decisions.append(decision)
        if seq_out is not None:
            seq_out.append(decision)
        if decision.get("degraded"):
            log.warning("컷 %s 연속성 저하: %s", cut.get("cut_no"),
                        ", ".join(decision["degraded"]))
        # ★★ 시퀀스 단위 렌더: 이 컷이 stage 그룹에 속하면 **클립을 새로 만들지 않는다.**
        #   그룹의 첫 컷에서 stage 영상을 한 번 만들고, 각 컷은 그 영상의 구간을 가져간다.
        #   시작 그림 한 장만 생성하므로 이미지 호출도 그룹당 1회로 준다.
        slice_window: tuple[float, float] | None = None
        if stage_mode and i in cut_group:
            gi, k = cut_group[i]
            plan = stage_plans[gi]
            aud = pre_audio[i]["path"]
            measured, words = float(pre_audio[i]["sec"]), pre_audio[i]["words"]
            cost = 0.0
            if gi not in stage_videos:
                # 이 stage 의 **시작 그림** 한 장. 기존 스틸 경로를 그대로 쓴다
                #   (재사용·파생·참조 조건 생성이 전부 그 안에 있다).
                img0 = os.path.join(work_dir, f"stage_{gi}_start.png")
                cost += _obtain_still(
                    cut, header, img0, asset_index=asset_index, seq_decision=decision,
                    directive_id=directive_id, render_job_id=render_job_id,
                    render_job_kind=render_job_kind, reuse_out=reuse_out)
                try:
                    # ★★ [stage 영상은 언어가 공유한다] 2026-09-14 실측. 이 경로에는 캐시가 없어서
                    #   영어판을 만들면 Veo 클립을 **처음부터 다시 샀다**(한 편 약 $5.5). 컷 경로
                    #   (_gen_veo_clip)는 처음부터 클립을 캐시해 "언어 추가 비용 0"을 지켰는데
                    #   시퀀스 렌더를 붙이면서 그 약속이 빠졌다. 화면은 언어와 무관하므로 같은 stage 의
                    #   영상은 재사용한다. 길이가 모자라면 _pad_stage_video 가 마지막 프레임으로 메운다.
                    sv, c2 = _cached_stage_video(plan, cuts, header, work_dir, gi, directive_id)
                    if sv is None:
                        # ★ 잡·지시서 번호를 넘긴다(2026-09-11 실측). 빠져 있어서 stage 영상 원장
                        #   9행($3.10)이 render_job_id·directive_id 가 비어 기록됐다 — 잡 기준으로
                        #   조회하면 영상비가 0으로 보였다(바로 위 _obtain_still 은 넘기고 있었다).
                        sv, c2 = _build_stage_video(
                            plan, cuts, header, work_dir, gi, start_image=img0, lang=lang,
                            clip_metrics_out=clip_metrics_out,
                            directive_id=directive_id, render_job_id=render_job_id,
                            render_job_kind=render_job_kind, qa_out=stage_qa_out)
                        _store_stage_video(sv, plan, cuts, header, directive_id)
                    stage_videos[gi] = sv
                    cost += c2
                except Exception as exc:  # noqa: BLE001
                    # ★ stage 영상이 실패해도 렌더를 죽이지 않는다 — 그 그룹만 옛 컷 경로로.
                    log.error("stage %s 영상 실패 → 컷 단위로 폴백: %s",
                              plan["stage_id"] or gi, str(exc)[:160])
                    for ci in plan["indexes"]:
                        cut_group.pop(ci, None)
            if gi in stage_videos:
                vis, kind = stage_videos[gi], "stage"
                slice_window = plan["windows"][k]
                asset_index.setdefault(int(cut.get("cut_no") or (i + 1)),
                                       os.path.join(work_dir, f"stage_{gi}_start.png"))
        if slice_window is None:
            vis, kind, aud, measured, cost, words = _gen_cut_assets(
                cut, header, work_dir, i, directive_id, lang, asset_index, fact_sheet,
                render_job_id=render_job_id, render_job_kind=render_job_kind, board_qa_out=board_qa_out, stage_out=stage_out,
                chain=chain, seq_decision=decision, clip_metrics_out=clip_metrics_out,
                reuse_out=reuse_out)
        if kind == "image":
            asset_index[int(cut.get("cut_no") or (i + 1))] = vis
        # ★ stage 그림을 **처음 만든 컷의 것만** 등록한다. 한 stage 가 여러 컷을 담당할 때
        #   뒤 컷으로 덮으면 다음 stage 가 이어받는 화면이 stage 안에서 밀린다.
        # ★★ **반환값(vis)이 아니라 스틸을 등록한다**(2026-08-30 실측). 영상 컷의 vis 는
        #   mp4 다 — 그걸 등록하면 뒤 stage 의 RETURN_WORLD 파생이 **동영상 파일을 .png 로
        #   복사**한다. 실제로 그렇게 나갔고 ffmpeg 가 "Option loop not found" 로 죽었다.
        #   asset_index 는 영상 컷에 대해서도 **첫 프레임 스틸**을 담고 있으므로 그것을 쓴다.
        _sid = str(decision.get("stage_id") or "")
        _still = asset_index.get(int(cut.get("cut_no") or (i + 1))) if kind != "image" else vis
        if _sid and _sid not in stage_assets and _still and os.path.exists(_still):
            stage_assets[_sid] = _still
        # ★ 연쇄는 **연달아 붙은** 영상 컷끼리만. 사이에 스틸이 끼면 장면이 이미 바뀐 것이라,
        #   멀리 떨어진 앞 영상의 마지막 화면에서 이어 만들면 엉뚱한 장소가 계속된다.
        if cut.get("motion_source") != "video":
            chain["frame"] = None
            chain["clip_key"] = None
        prev_role = str(cut.get("visual_role") or "")
        if on_cost:
            on_cost(cost)
        out = os.path.join(work_dir, f"cut_{i}_out.mp4")
        # 컷 화면 길이 = 나레이션 실측(ffprobe) + 숨 쉴 틈. 종전에는 실측과 **정확히 같아서**
        # 마지막 음절 프레임에서 다음 컷으로 넘어갔다(2026-09-03 실측 — "뚝뚝 끊긴다").
        # 오디오도 assemble 이 같은 길이로 apad 한다(-shortest 가 짧은 쪽에서 멈추므로).
        clip_dur = float(measured) + float(config.CLIP_FIT_TAIL_PAD_SEC)
        cut_starts.append(t)
        cut_durs.append(clip_dur)
        if kind == "stage" and slice_window is not None:
            # ★★ 컷이 stage 영상의 **한 구간**을 가져간다. 화면을 자르는 것이 아니라
            #   연속 영상의 다른 시각을 볼 뿐이라 컷 경계에서 끊기지 않는다.
            #   stage 영상은 나레이션 전체를 덮도록 만들어졌으므로 **메울 구멍이 없다** —
            #   hold(정지)가 구조적으로 사라진다.
            if fit_log is not None:
                fit_log.append({"cut_no": int(cut.get("cut_no") or (i + 1)),
                                "loop_safe": True, "strategy": "stage_slice",
                                "clip_sec": round(slice_window[1], 3),
                                "narration_sec": round(clip_dur, 3), "ratio": 0.0})
            argv = assemble.build_slice_cut_command(
                video_path=vis, audio_path=aud,
                start_sec=slice_window[0], duration=clip_dur, out_path=out)
        elif kind == "clip":
            # §3-3: 클립 실측 길이와 나레이션 길이의 갭을 결정론적 전략으로 메운다(자유 판단 없음).
            strategy = _decide_clip_fit(vis, cut, clip_dur)
            if fit_log is not None:
                fit_log.append({"cut_no": int(cut.get("cut_no") or (i + 1)),
                                "loop_safe": bool(cut.get("loop_safe", False)),
                                **strategy.as_log_row()})
            argv = assemble.build_clip_cut_command(
                clip_path=vis, audio_path=aud, duration=clip_dur, out_path=out,
                strategy=strategy,
            )
        else:
            # 정지화면 방지: 스틸 컷에 켄번스/팬 모션이 없으면 자동으로 하나 넣어 항상 동적으로.
            effects = list(cut.get("effects") or [])
            if not any(e in config.KEN_BURNS_EFFECTS for e in effects):
                effects.append(config.KEN_BURNS_EFFECTS[i % len(config.KEN_BURNS_EFFECTS)])
            argv = assemble.build_cut_command(
                image_path=vis, audio_path=aud, duration=clip_dur,
                effects=effects, out_path=out,
            )
        assemble.run_ffmpeg(argv)
        cut_files.append(out)
        text = str(cut.get(f"narration_{lang}") or cut.get("narration_ko") or "")
        # 자막·VO 스팬은 나레이션 구간([t, t+measured])에. 단어 타임스탬프면 정밀 싱크·레이트 청킹.
        if words:
            cues.extend(subtitles.chunk_by_rate(words, lang=lang, offset=t))
            vo_words.extend({"start": t + float(w.get("start") or 0.0),
                             "end": t + float(w.get("end") or 0.0)} for w in words)
        elif text:
            # 워드 타임스탬프 없음 → 컷 통짜 대신 어절 청킹(①). 표시가 문장 전체로 뭉치지 않게.
            #
            # ★★ **나레이션 구간(measured)에 펼친다 — clip_dur 이 아니다**(2026-09-09 실측).
            #   `clip_dur = measured + CLIP_FIT_TAIL_PAD_SEC` 이고 그 꼬리는 **침묵**이다.
            #   거기까지 글자를 배분하면 컷마다 자막이 조금씩 뒤로 밀리고, 마지막 어절은
            #   목소리가 끝난 뒤에 뜬다. 바로 위 주석이 이미 "[t, t+measured]" 라고
            #   적어 두었는데 코드가 그 약속을 어기고 있었다.
            #   ★ 한국어 Edge 음성 3종(SunHi·InJoon·Hyunsu)은 **단어 타임스탬프를 주지 않아**
            #     항상 이 경로로 온다 — 즉 이 어긋남이 모든 한국어 렌더에 걸려 있었다.
            cues.extend(subtitles.chunk_text_by_rate(text, t, t + float(measured), lang=lang))
            vo_words.append({"start": t, "end": t + float(measured)})
        t += clip_dur
    cues = subtitles.clamp_overlaps(cues)  # 컷 경계 tail_hold 겹침 제거(한 시점에 자막 1개)
    duck_spans = assemble.duck_spans_from_words(vo_words)
    if overlay_out is not None and config.EVIDENCE_OVERLAY_ENABLED:
        # ★ 코드 보드 컷은 ASS 오버레이를 내보내지 않는다 — 보드가 그 텍스트를 이미 화면에
        #   그렸다. 둘 다 내면 같은 문장이 서로 다른 자리에 두 번 뜨고, full_bleed 에서는
        #   오버레이 카드가 나레이션 자막 위에 겹쳐 둘 다 못 읽는다(실측). 즉 `overlay_plan` 은
        #   설명판형에서 **보드의 입력원**이지 자막 레이어의 입력원이 아니다.
        skip = {c.get("cut_no") for c in cuts if board_render.code_render_board(c, header)}
        overlay_out.extend(evidence_overlay.build_overlay_cues(
            cuts, cut_starts, cut_durs, skip_cut_nos=skip))
    if cut_map_out is not None:
        # ★ cut_no 가 정본이다. 예전 오버레이 경로는 결측 시 리스트 인덱스로 폴백했는데,
        #   그러면 지시서가 컷을 건너뛴 번호를 쓸 때 두 체계가 어긋난다. 여기서는 결측을
        #   폴백으로 덮지 않고 그대로 드러낸다(None) — 조용히 어긋나는 것보다 낫다.
        cut_map_out.extend({
            "cut_no": (int(c["cut_no"]) if str(c.get("cut_no") or "").strip().isdigit()
                       else None),
            "index": i,
            "start_sec": round(cut_starts[i], 3),
            "duration_sec": round(cut_durs[i], 3),
            "end_sec": round(cut_starts[i] + cut_durs[i], 3),
        } for i, c in enumerate(cuts[:len(cut_starts)]))
    return cut_files, cues, t, duck_spans


def render_directive_local(directive: dict[str, Any], out_path: str,
                           work_dir: str | None = None, lang: str = "ko",
                           platform: str | None = None) -> str:
    """DB 없이 지시서 dict → 로컬 mp4. CI 관통 검증(--demo)·로컬 테스트용.

    ⑤ lang: 언어별 산출(ko/en). ② platform: 자막 앵커(기본 DEFAULT_PLATFORM).
    """
    tmp = work_dir or tempfile.mkdtemp(prefix="render_")
    fit_log: list[dict[str, Any]] = []
    overlays: list[tuple[float, float, str, str]] = []
    seq_log: list[dict[str, Any]] = []
    cut_files, cues, total, duck_spans = _render_cut_clips(directive, tmp, lang=lang,
                                                          fit_log=fit_log,
                                                          overlay_out=overlays,
                                                          seq_out=seq_log)
    if not cut_files:
        raise ValueError("컷이 없어 렌더 불가")
    header = directive.get("header") or {}
    hook = str(header.get(f"hook_{lang}") or header.get("logline") or "")
    series_title = config.SERIES_TITLE_BY_LANG.get(lang, config.SERIES_TITLE)
    ass = subtitles.build_ass(cues, header_title=series_title, header_hook=hook,
                              total_sec=total, lang=lang,
                              platform=platform or config.DEFAULT_PLATFORM,
                              overlays=overlays)
    assemble.assemble_full(cut_files, tmp, out_path, ass_text=ass, total_sec=total,
                           duck_spans=duck_spans)
    fit_qa = render_qa.evaluate_clip_fit(fit_log)
    log.info("렌더 완료(local): %s (lang=%s, 컷 %d, 자막 %d) 길이보정=%s",
             out_path, lang, len(cut_files), len(cues), fit_qa["strategy_counts"])
    if seq_log:
        log.info("시각 시퀀스: %s", sequence_render.degraded_summary(seq_log))
    return out_path


def render_all_languages(directive: dict[str, Any], out_prefix: str,
                         platform: str | None = None) -> dict[str, str]:
    """⑤ 한/영 두 버전을 동시 산출. 비주얼 에셋 로직은 공유(언어별 재타이밍). 반환: {lang: path}."""
    outputs: dict[str, str] = {}
    for lang in config.LANGUAGES:
        outputs[lang] = render_directive_local(
            directive, f"{out_prefix}_{lang}.mp4", lang=lang, platform=platform)
    return outputs


def process_job(job_id: str, directive_id: str, lang: str = "ko") -> str:
    """render_jobs 1건 처리: 에셋→조립→Storage 업로드→done. 반환: output_url.

    ⑤ lang: 산출 언어(기본 ko). 한/영 동시 운영은 언어별 잡으로 각각 처리(에셋 로직 공유).
    """
    directive = db.get_directive(directive_id)
    if not directive:
        raise ValueError(f"directive 없음: {directive_id}")
    # M-E4: 코드 차트 수치는 원장에서 해소한다. directives 행에는 fact_sheet 가 없으므로 여기서 붙인다.
    attach_fact_sheet(directive)
    db.update_directive_status(directive_id, "rendering")

    spent = {"cost": 0.0}
    # ★ 버전별 캡을 쓴다(2026-08-28 수정). 여기가 전역 $1.2 를 직접 읽고 있어서,
    #   config.render_budget_cap() 이 실사형용으로 따로 들고 있던 캡이 **논문 라인에서만**
    #   무시됐다(리포트 라인 report_render.py:77 은 처음부터 함수를 쓴다).
    #   실사형 예상비는 $3.5 라 전역 캡이면 렌더 도중에 죽는다 — 그리고 캡은 하드 스톱이라
    #   그때까지 쓴 돈은 못 돌려받는다. 실사형이 한 번도 렌더된 적이 없어 안 드러났을 뿐이다.
    _cap = config.render_budget_cap(str((directive.get("header") or {}).get("version_type") or ""))

    def _on_cost(c: float) -> None:
        spent["cost"] += c
        if spent["cost"] > _cap:
            raise RuntimeError(f"예산 초과: ${spent['cost']:.3f} > 캡 ${_cap}")

    work_dir = tempfile.mkdtemp(prefix=f"render_{job_id}_")
    db.update_render_job(job_id, status="assets", progress=20)
    fit_log: list[dict[str, Any]] = []
    # 클립 지표 교정 표본(기록 전용). qa["clip_metrics"] 로 저장된다.
    clip_metrics: list[dict[str, Any]] = []
    overlays: list[tuple[float, float, str, str]] = []
    cut_map: list[dict[str, Any]] = []
    board_qa: list[dict[str, Any]] = []
    stage_qa: list[dict[str, Any]] = []
    seq_log: list[dict[str, Any]] = []
    reuse_log: list[dict[str, Any]] = []
    # §10 관측성 — 단계별 소요시간(리포트 라인 미러). 저장은 qa["stage_ms"].
    metrics: dict[str, Any] = {}
    with sm.stage(metrics, "asset"):
        cut_files, cues, total, duck_spans = _render_cut_clips(
            directive, work_dir, on_cost=_on_cost, directive_id=directive_id, lang=lang,
            fit_log=fit_log, overlay_out=overlays, cut_map_out=cut_map,
            clip_metrics_out=clip_metrics,
            render_job_id=job_id, board_qa_out=board_qa, stage_out=metrics,
            stage_qa_out=stage_qa,
            seq_out=seq_log, reuse_out=reuse_log)
    if not cut_files:
        raise ValueError("컷이 없어 렌더 불가")

    db.update_render_job(job_id, status="tts", progress=55, cost_estimate=spent["cost"])
    db.update_render_job(job_id, status="assembling", progress=75,
                         cost_estimate=spent["cost"])
    out_path = os.path.join(work_dir, "final.mp4")
    # 상단 헤더 후킹: 지시서 hook_{lang} 우선, 없으면 논문 후킹(DB).
    header = directive.get("header") or {}
    hook = str(header.get(f"hook_{lang}") or "")
    if not hook and directive.get("paper_id"):
        hook = db.get_paper_hook(directive.get("paper_id") or "")
    series_title = config.SERIES_TITLE_BY_LANG.get(lang, config.SERIES_TITLE)
    ass = subtitles.build_ass(cues, header_title=series_title, header_hook=hook,
                              total_sec=total, lang=lang, platform=config.DEFAULT_PLATFORM,
                              overlays=overlays)
    with sm.stage(metrics, "assemble"):
        assemble.assemble_full(cut_files, work_dir, out_path, ass_text=ass, total_sec=total,
                               duck_spans=duck_spans)

    # §7 렌더 QA: 발행 전 실제 mp4 실검(끝 검은프레임·무음·클리핑·길이). 하드 실패는 로그+저장(사람이 승인 화면에서 확인).
    # + §3-6 길이 보정 QA: ratio>0.60 빨간 플래그 · pingpong 과다 노란 경고(렌더 차단은 아님).
    with sm.stage(metrics, "qa"):
        qa = render_qa.run_qa(out_path)
    qa["clip_fit"] = render_qa.merge_clip_fit_qa(qa, fit_log)
    # ★ 보드 판정·컷 시간축도 함께 남긴다(v3 §8-1·§9 P3-a·b). 지금까지 core_fill 은
    #   계산되고 버려져 "충전율 기준을 올려도 되나"에 답할 데이터가 없었다. 기록 전용이다.
    qa["board"] = board_qa
    # ★ stage 영상이 짧아 메운 기록. 비어 있어야 정상이다 — 항목이 있으면 그 stage 는
    #   정지 화면이 들어갔다는 뜻이고, 시퀀스 렌더가 없애려던 바로 그 증상이다.
    qa["stage_short"] = stage_qa
    qa["cut_map"] = cut_map
    # ★★ v3 Phase 3 — 시각 시퀀스가 화면에서 어떻게 이어졌는가. **기록 전용이다.**
    #   world_reset 이 높으면 "시퀀스"라고 부르지만 실은 컷 나열이고, degraded_continuity 는
    #   참조를 붙이지 못한 컷이다. 둘 다 렌더 안에서 로그만 찍고 버리면 나중에 물을 수 없다.
    #   숨기지 않는다 — 작업지시서 Paper §9 "identity 완전 보장은 provider 한계로 불가능할
    #   수 있다. 숨기지 않고 degraded_continuity 로 기록한다"가 이 줄이다.
    qa["visual_sequence"] = sequence_render.degraded_summary(seq_log)
    qa["visual_sequence"]["decisions"] = seq_log
    # ★★ 클립 지표 — **기록 전용, 교정용 표본이다**(2026-08-31).
    #   지금 `world_drift` 문턱을 못 정하는 이유는 손으로 뽑은 표본 4개가 **전부 나빴기**
    #   때문이다(좋은 값이 없어 경계를 못 긋는다). 그래서 렌더가 돌 때마다 컷마다 재서
    #   남긴다 — 좋은 클립·나쁜 클립이 섞여 들어오면 **문턱이 데이터에서 나온다.**
    #   사람이 샘플을 뽑아 주지 않아도 엔진이 자기 교정 데이터를 모은다.
    #   ★ 아직 아무것도 차단하지 않는다. 기준을 정하기 전에 벌점으로 만들면 정상 컷을
    #     벌한다(리뷰 §17). 승격은 표본이 쌓인 뒤 별도 결정이다.
    # ★ 재사용이 같은 그림으로 나온 컷 — `photo_reuse_identical_render` 의 실제 발생 기록.
    #   차단하지 않는다(렌더가 이미 새로 생성해 복구했다). 다음 지시서를 고칠 근거로만 남긴다.
    if reuse_log:
        qa["reuse_identical"] = reuse_log
        log.info("재사용이 같은 그림으로 나온 컷 %d개: %s", len(reuse_log),
                 ",".join(str(r["cut_no"]) for r in reuse_log))
    qa["clip_metrics"] = clip_metrics
    # ★ 기록만 하던 지표에 문턱을 붙인다(2026-09-04). 발행 벤치마크가 생겨서
    #   "거의 정지"를 숫자로 부를 수 있게 됐다 — render_qa.evaluate_clip_motion 참조.
    qa["clip_motion"] = render_qa.merge_clip_motion_qa(qa, clip_metrics)

    dest = f"{directive_id}/{job_id}_{lang}.mp4"
    with sm.stage(metrics, "upload"):
        url = db.upload_render(out_path, dest)
    metrics["total_ms"] = sm.total_ms(metrics)
    qa["stage_ms"] = metrics
    # ★ Q4 출처 가시성(§9). 오버레이는 컷 경계에서 잘리므로, **선언한 최소 노출시간**
    #   (OVERLAY_MIN_SEC)이 실제 타임라인에서 지켜졌는지는 여기서만 알 수 있다.
    #   경고로만 남긴다 — 컷이 짧아 잘린 것은 대본·타이밍 문제라 렌더를 죽여도 안 풀린다.
    brief = evidence_overlay.cue_visibility_warnings(overlays)
    if brief:
        qa["overlay_visibility"] = brief
        qa.setdefault("warnings", []).extend(brief)
        log.warning("오버레이 노출시간 미달 %d건: %s", len(brief), "; ".join(brief[:3]))
    log.info("렌더 단계별: %s (합 %dms)", sm.summarize(metrics), metrics["total_ms"])
    # ★ §8-2·§8-3 — done 은 critical 이 전부 있을 때만. 없으면 failed, important 만 빠졌으면
    #   degraded(사람 승인 대기). **mp4 는 어느 쪽이든 올리고 output_url 을 남긴다** — 무엇이
    #   잘못됐는지 보려면 영상을 봐야 하는데, 주소가 없으면 진단이 불가능하다.
    status, reasons = rm.terminal_status(board_qa)
    db.update_render_job(job_id, status=status, progress=100,
                         output_url=url, cost_estimate=spent["cost"], qa=qa,
                         error_log="; ".join(reasons)[:1000] or None,
                         finished=status not in config.RENDER_STATUS_AWAITING_HUMAN)
    if status != "done":
        log.warning("렌더 판정 %s job=%s: %s", status, job_id, ", ".join(reasons))
    db.update_directive_status(directive_id, "rendered")
    log.info("렌더 완료: job=%s url=%s 비용=$%.3f", job_id, url, spent["cost"])
    return url


def poll_once(limit: int = 3) -> int:
    jobs = db.claim_render_jobs(limit)
    if not jobs:
        log.info("render_jobs: 대기 없음")
        return 0
    for j in jobs:
        try:
            process_job(j["id"], j["directive_id"], j.get("lang") or config.DEFAULT_LANG)
        except Exception as exc:  # noqa: BLE001
            log.exception("렌더 실패 job=%s: %s", j["id"], exc)
            db.update_render_job(j["id"], status="failed", error_log=str(exc)[:1000],
                                 finished=True)
            db.update_directive_status(j["directive_id"], "failed")
    return len(jobs)


def _demo_directive() -> dict[str, Any]:
    """버전2(이미지 나열식) 최소 데모 지시서 — CI 관통 검증용. scene_kind·이중언어 포함."""
    return {
        "version_type": "image_sequence",
        "header": {"version_type": "image_sequence", "aspect_ratio": "9:16",
                   "global_style": "clean editorial illustration",
                   "hook_ko": "이거 실화?", "hook_en": "No way this is real",
                   "total_estimated_sec": 12},
        "cuts": [
            {"cut_no": 1, "scene_kind": "broll_stock", "visual_type": "image", "estimated_sec": 4,
             "visual_prompt": "hook", "effects": ["ken_burns_zoom_in"],
             "narration_ko": "후크", "narration_en": "The hook", "source_facts": ["what_found[0]"]},
            {"cut_no": 2, "scene_kind": "kinetic_typography", "visual_type": "image",
             "estimated_sec": 4, "visual_prompt": "concept step reveal", "effects": ["pan_right"],
             "narration_ko": "개념", "narration_en": "The concept", "source_facts": ["numbers[0]"]},
            {"cut_no": 3, "scene_kind": "comic_panel", "visual_type": "image", "estimated_sec": 4,
             "visual_prompt": "cta", "effects": [],
             "narration_ko": "CTA", "narration_en": "Call to action", "source_facts": ["what_found[1]"]},
        ],
    }


def _demo_anim_directive() -> dict[str, Any]:
    """버전3(애니메이션식) 최소 데모 지시서 — Manim 도해 관통 검증용."""
    return {
        "version_type": "animation",
        "header": {"version_type": "animation", "aspect_ratio": "9:16",
                   "global_style": "schematic motion graphics", "total_estimated_sec": 12},
        "cuts": [
            {"cut_no": 1, "scene_kind": "kinetic_typography", "visual_type": "animation",
             "estimated_sec": 4, "visual_prompt": "title card of the paper", "effects": [],
             "narration_ko": "오늘의 논문", "narration_en": "Today's paper",
             "source_facts": ["what_found[0]"]},
            {"cut_no": 2, "scene_kind": "motion_graphic", "visual_type": "animation",
             "estimated_sec": 5, "visual_prompt": "arrow flow: input to processing to output",
             "effects": [], "narration_ko": "입력에서 처리를 거쳐 출력으로",
             "narration_en": "From input, through processing, to output", "source_facts": ["how[0]"]},
            {"cut_no": 3, "scene_kind": "data_viz", "visual_type": "animation",
             "estimated_sec": 4, "visual_prompt": "compare numbers before and after", "effects": [],
             "narration_ko": "전과 후를 비교하면", "narration_en": "Comparing before and after",
             "source_facts": ["numbers[0]"]},
        ],
    }


if __name__ == "__main__":
    try:
        # 선택적 언어 인자(마지막): ko|en. 없으면 기본 ko.
        lang = sys.argv[-1] if sys.argv[-1] in config.LANGUAGES else config.DEFAULT_LANG
        if len(sys.argv) > 2 and sys.argv[1] == "--demo":
            render_directive_local(_demo_directive(), sys.argv[2], lang=lang)
        elif len(sys.argv) > 2 and sys.argv[1] == "--demo-anim":
            render_directive_local(_demo_anim_directive(), sys.argv[2], lang=lang)
        elif len(sys.argv) > 2 and sys.argv[1] == "--demo-both":
            # ⑤ 한/영 동시 산출: <prefix>_ko.mp4, <prefix>_en.mp4
            print(render_all_languages(_demo_directive(), sys.argv[2]))
        elif len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
            d = db.get_directive(sys.argv[1])
            if not d:
                raise ValueError(f"directive 없음: {sys.argv[1]}")
            # 단건 렌더는 임시 job 을 만들지 않고 로컬 산출만(디버그). 큐 경로는 poll_once.
            render_directive_local(d, "render_out.mp4", lang=lang)
        else:
            poll_once()
    except Exception as exc:
        log.exception("render 실패: %s", exc)
        sys.exit(1)
