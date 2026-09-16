"""리포트 유튜브 업로드 워커 — 논문 engine/publish.py 의 report 미러.

⑥ 리포트 렌더 결과(report_render_jobs.status='done')에서 대시보드 "유튜브 업로드" 버튼 →
report_upload_requests 큐 → 이 워커가 폴링해 mp4 를 다운로드하고 YouTube Data API v3 로 업로드한다.

결정(사용자):
  - 트리거: 대시보드 버튼(human-in-the-loop).
  - 기본 공개: private.
  - 채널: 별도 금융 채널(논문과 분리), KO 만. config.YOUTUBE_REPORT_REFRESH_TOKEN_SECRET_BY_LANG.

실행:
  python -m engine.report_publish        # report_upload_requests 큐 1회 폴링
"""

from __future__ import annotations

import os
import sys
import tempfile

from . import config, report_db
from .attribution import strip_markup
from .report_attribution import build_publish_caption, build_source
from .util import log


def _truncate(text: str, limit: int) -> str:
    """YouTube 제목/설명 하드 제한 안전 절단(공백 경계 우선)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp >= limit - 20:
        cut = cut[:sp]
    return cut.rstrip()


def build_upload_title(meta: dict, lang: str) -> str:
    """업로드 제목: 초안 upload_title_{lang} 우선 → 리포트 번역제목/원제 폴백 → 100자 절단.

    순수 함수. meta 는 report_db.get_report_upload_meta 형식.
    """
    report = meta.get("report") or {}
    if lang == "en":
        title = meta.get("upload_title_en") or report.get("title") or ""
    else:
        title = meta.get("upload_title_ko") or meta.get("title_ko") or report.get("title") or ""
    return _truncate(strip_markup(str(title)), config.YOUTUBE_TITLE_MAX)


def build_upload_description(meta: dict, lang: str) -> str:
    """업로드 설명란: 리포트 출처·면책 캡션(teaser=한 줄 요약) → 5000자 절단.

    순수 함수 — report_attribution.build_publish_caption 재사용(출처·면책 고정 레이어 포함).
    """
    report = meta.get("report") or {}
    teaser = meta.get("one_liner_en") if lang == "en" else meta.get("one_liner_ko")
    caption = build_publish_caption(build_source(report), teaser=str(teaser or ""), lang=lang)
    return _truncate(caption, config.YOUTUBE_DESC_MAX)


def _download_to(url: str, dest: str) -> None:
    import httpx
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client_:
        resp = client_.get(url)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)


def _validate_privacy(privacy: str | None) -> str:
    p = (privacy or config.YOUTUBE_DEFAULT_PRIVACY).strip().lower()
    return p if p in config.YOUTUBE_ALLOWED_PRIVACY else config.YOUTUBE_DEFAULT_PRIVACY


def derive_content_type(report: dict) -> str:
    """리포트 소재 분류 — 'entity'(개별 종목) | 'industry'(테마·산업·매크로).

    순수 함수. **텍스트 분류기를 쓰지 않는다**(명세서 §3-1) — reports 테이블의 구조 필드에서
    파생한다. ARIA 수집기는 개별 종목 신호에만 ticker/company 를 채우고, 테마 신호는 theme 로
    넣는다.

    ★ 지시서 초안은 fact_sheet.company 로 파생하라고 했으나 그 필드는 종목·테마를 함께 담아
      (report_factsheet.py 프롬프트가 "<종목/테마>" 로 정의) 전부 entity 가 된다.
      근거·집계는 docs/specs/20260730-report-merge-into-paper-ko.md §1-1.

    ★ 한계(정직하게): 현재 수집 데이터는 ticker 가 비어 있어 사실상 전부 industry 로 나온다.
      ARIA 가 종목 단위 신호를 채우기 시작하면 그때부터 entity 가 생긴다.
    """
    if str(report.get("ticker") or "").strip() or str(report.get("company") or "").strip():
        return "entity"
    return "industry"


def _series_id_for(job: dict) -> str:
    """렌더 잡 → 지시서 header.series_id. 미확정이면 빈 문자열(§6-1 결정 대기)."""
    directive = report_db.get_report_directive(job.get("directive_id") or "") or {}
    header = directive.get("header") or {}
    return str(header.get("series_id") or "")


def process_upload(req: dict) -> str:
    """report_upload_requests 1건 처리: 렌더 mp4 다운로드 → 유튜브 업로드 → published 기록. 반환: youtube_url."""
    from .providers import youtube  # 지연 임포트(googleapiclient 는 이 워커에만 필요)

    req_id = req["id"]
    job = report_db.get_report_render_job(req["render_job_id"])
    if not job:
        raise ValueError(f"report_render_job 없음: {req['render_job_id']}")
    if job.get("status") != "done" or not job.get("output_url"):
        raise ValueError("완료된 렌더 mp4 가 없어 업로드 불가")

    lang = req.get("lang") or job.get("lang") or config.DEFAULT_LANG
    privacy = _validate_privacy(req.get("privacy_status"))
    report_id = req.get("report_id") or ""
    meta = report_db.get_report_upload_meta(report_id) if report_id else {"report": {}}

    title = build_upload_title(meta, lang)
    description = build_upload_description(meta, lang)
    if not title:
        raise ValueError("업로드 제목이 비어 업로드 불가(초안/리포트 제목 확인)")

    report_db.update_report_upload_request(req_id, progress=30)
    work_dir = tempfile.mkdtemp(prefix=f"report_upload_{req_id}_")
    mp4_path = os.path.join(work_dir, "video.mp4")
    _download_to(job["output_url"], mp4_path)

    report_db.update_report_upload_request(req_id, progress=60)
    result = youtube.upload_video(
        mp4_path,
        title=title,
        description=description,
        privacy_status=privacy,
        category_id=config.YOUTUBE_CATEGORY_ID,
        lang=lang,
        made_for_kids=config.YOUTUBE_MADE_FOR_KIDS,
        # 채널 통합(2026-07-30): report_ko 키는 유지하되 목적지는 하루한편 KO 다.
        # 목적지는 CHANNEL_REGISTRY 한 곳에서만 정해지고, 업로드 전 채널 가드가 돈다.
        channel_key="report_ko",
        tags=list(config.CHANNEL_CORE_TAGS_KO),
    )

    # 출처·분류 기록(0032). 한 채널에 두 공장 영상이 섞이므로, 업로드 시점에 남기지 않으면
    # 나중에 유튜브 성과만 보고는 어느 공장 산출물인지 구분할 수 없다(명세서 §3-2·§5).
    report_db.update_report_upload_request(
        req_id, status="done", progress=100,
        youtube_video_id=result["video_id"], youtube_url=result["url"], finished=True,
        source_factory="report",
        content_type=derive_content_type(meta.get("report") or {}),
        series_id=_series_id_for(job),
        channel_id=result.get("channel_id") or "")
    report_db.record_report_youtube_publish(report_id, lang, result["video_id"], result["url"])
    log.info("리포트 업로드 완료: req=%s lang=%s url=%s", req_id, lang, result["url"])
    return result["url"]


def poll_once(limit: int = 3) -> int:
    if not config.YOUTUBE_UPLOAD_ENABLED:
        log.info("YOUTUBE_UPLOAD_ENABLED=false — 리포트 업로드 폴링 건너뜀")
        return 0
    reqs = report_db.claim_report_upload_requests(limit)
    if not reqs:
        log.info("report_upload_requests: 대기 없음")
        return 0
    for r in reqs:
        try:
            process_upload(r)
        except Exception as exc:  # noqa: BLE001
            log.exception("리포트 업로드 실패 req=%s: %s", r["id"], exc)
            report_db.update_report_upload_request(
                r["id"], status="error", error=str(exc)[:1000], finished=True)
    return len(reqs)


if __name__ == "__main__":
    try:
        poll_once()
    except Exception as exc:
        log.exception("report_publish 실패: %s", exc)
        sys.exit(1)
