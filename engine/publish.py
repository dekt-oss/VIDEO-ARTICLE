"""유튜브 업로드 워커 (P-V2 승인 이탈) + upload_requests 폴러.

⑥ 렌더 결과(render_jobs.status='done')에서 대시보드 "유튜브 업로드" 버튼 → upload_requests 큐 →
이 워커가 폴링해 mp4 를 다운로드하고 YouTube Data API v3 로 업로드한다. render_jobs 패턴 미러링.

결정(사용자 승인, docs/deviation-youtube-upload.md):
  - 트리거: 대시보드 버튼(자동 아님 — human-in-the-loop).
  - 기본 공개: private(올린 뒤 사람이 스튜디오에서 공개 전환).
  - KO/EN: 언어별 다른 채널(리프레시 토큰 분리).

실행:
  python -m engine.publish              # upload_requests 큐 1회 폴링
"""

from __future__ import annotations

import os
import sys
import tempfile

from . import config, db, storage_gc
from .attribution import build_publish_caption, build_source, strip_markup
from .util import log


def _truncate(text: str, limit: int) -> str:
    """YouTube 제목/설명 하드 제한 안전 절단(공백 경계 우선)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp >= limit - 20:  # 끝 근처에 공백이 있으면 단어 중간 절단 방지
        cut = cut[:sp]
    return cut.rstrip()


def build_upload_title(meta: dict, lang: str) -> str:
    """업로드 제목: 초안 upload_title_{lang} 우선 → 논문 번역제목/원제 폴백 → 100자 절단.

    순수 함수(네트워크 없음) — 단위 테스트 대상. meta 는 db.get_upload_meta 형식.
    """
    paper = meta.get("paper") or {}
    if lang == "en":
        title = meta.get("upload_title_en") or paper.get("title") or ""
    else:
        title = meta.get("upload_title_ko") or meta.get("title_ko") or paper.get("title") or ""
    # YouTube 는 제목에도 '<' '>' 를 불허 → 논문 제목 폴백 시 섞인 HTML 태그 제거.
    return _truncate(strip_markup(str(title)), config.YOUTUBE_TITLE_MAX)


def build_upload_description(meta: dict, lang: str) -> str:
    """업로드 설명란: 렌더결과 복붙과 동일한 attribution 캡션(teaser=한 줄 요약) → 5000자 절단.

    순수 함수 — attribution.build_publish_caption 재사용(대시보드 복붙과 문구 일치).
    """
    paper = meta.get("paper") or {}
    teaser = meta.get("one_liner_en") if lang == "en" else meta.get("one_liner_ko")
    caption = build_publish_caption(build_source(paper), teaser=str(teaser or ""), lang=lang)
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


def process_upload(req: dict) -> str:
    """upload_requests 1건 처리: 렌더 mp4 다운로드 → 유튜브 업로드 → published 기록. 반환: youtube_url."""
    from .providers import youtube  # 지연 임포트(googleapiclient 는 이 워커에만 필요)

    req_id = req["id"]
    job = db.get_render_job(req["render_job_id"])
    if not job:
        raise ValueError(f"render_job 없음: {req['render_job_id']}")
    if job.get("status") != "done" or not job.get("output_url"):
        raise ValueError("완료된 렌더 mp4 가 없어 업로드 불가")

    lang = req.get("lang") or job.get("lang") or config.DEFAULT_LANG
    privacy = _validate_privacy(req.get("privacy_status"))
    paper_id = req.get("paper_id") or ""
    meta = db.get_upload_meta(paper_id) if paper_id else {"paper": {}}

    title = build_upload_title(meta, lang)
    description = build_upload_description(meta, lang)
    if not title:
        raise ValueError("업로드 제목이 비어 업로드 불가(초안/논문 제목 확인)")

    db.update_upload_request(req_id, progress=30)
    work_dir = tempfile.mkdtemp(prefix=f"upload_{req_id}_")
    mp4_path = os.path.join(work_dir, "video.mp4")
    _download_to(job["output_url"], mp4_path)

    db.update_upload_request(req_id, progress=60)
    result = youtube.upload_video(
        mp4_path,
        title=title,
        description=description,
        privacy_status=privacy,
        category_id=config.YOUTUBE_CATEGORY_ID,
        lang=lang,
        made_for_kids=config.YOUTUBE_MADE_FOR_KIDS,
        # 논문도 같은 레지스트리·가드를 탄다(채널 통합 이후 목적지가 리포트와 같아졌으므로,
        # 두 워커가 서로 다른 경로로 채널을 고르면 오배송을 잡을 수 없다).
        channel_key=f"paper_{lang}",
        tags=list(config.CHANNEL_CORE_TAGS_KO) if lang == "ko" else None,
    )

    # 출처 기록(0032). content_type 은 리포트 소재 분류라 논문은 남기지 않는다(NULL).
    db.update_upload_request(
        req_id, status="done", progress=100,
        youtube_video_id=result["video_id"], youtube_url=result["url"], finished=True,
        source_factory="paper", channel_id=result.get("channel_id") or "")
    db.record_youtube_publish(paper_id, lang, result["video_id"], result["url"])
    log.info("업로드 완료: req=%s lang=%s url=%s", req_id, lang, result["url"])

    # ★ 유튜브로 나간 편의 저장소 산출물을 바로 회수한다(2026-08-24 신설).
    #   예전에는 지우는 장치가 아예 없어 편당 15~30MB 씩 무한히 쌓였고, 결국 Supabase
    #   무료 한도(1GB)를 넘겨 **조직 전체가 정지**됐다(대시보드·API 전면 402).
    #   여기서 지우는 것은 "유튜브에 이미 있는 최종 mp4"와 "재렌더 캐시"뿐이다 —
    #   판정은 engine/storage_gc.plan 이 하고, 미업로드 편은 절대 건드리지 않는다.
    #   실패해도 업로드는 유효하다(정리는 부수 작업, 다음 sweep 이 잡는다).
    if config.STORAGE_GC_ON_UPLOAD and job.get("directive_id"):
        storage_gc.purge_after_upload(str(job["directive_id"]))

    return result["url"]


def poll_once(limit: int = 3) -> int:
    if not config.YOUTUBE_UPLOAD_ENABLED:
        log.info("YOUTUBE_UPLOAD_ENABLED=false — 업로드 폴링 건너뜀")
        return 0
    reqs = db.claim_upload_requests(limit)
    if not reqs:
        log.info("upload_requests: 대기 없음")
        return 0
    for r in reqs:
        try:
            process_upload(r)
        except Exception as exc:  # noqa: BLE001
            log.exception("업로드 실패 req=%s: %s", r["id"], exc)
            db.update_upload_request(
                r["id"], status="error", error=str(exc)[:1000], finished=True)
    return len(reqs)


if __name__ == "__main__":
    try:
        poll_once()
    except Exception as exc:
        log.exception("publish 실패: %s", exc)
        sys.exit(1)
