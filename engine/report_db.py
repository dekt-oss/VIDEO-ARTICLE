"""리포트 팩토리 Supabase 접근 계층 (report_* 테이블).

engine/db.py 의 report_* 슬라이스. 같은 client()(service_role — RLS 우회)를 재사용한다.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import config
from .db import client
from .util import log


def existing_external_ids(external_ids: Iterable[str]) -> set[str]:
    """이미 reports 에 존재하는 external_id 집합(재탕 방지 사전 조회)."""
    ids = [e for e in external_ids if e]
    if not ids:
        return set()
    found: set[str] = set()
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("reports").select("external_id").in_("external_id", chunk).execute()
        found.update(r["external_id"] for r in (resp.data or []))
    return found


def upsert_reports(rows: list[dict[str, Any]]) -> int:
    """reports 멱등 upsert(external_id 충돌 시 갱신). 반환: 처리 건수."""
    if not rows:
        return 0
    client().table("reports").upsert(rows, on_conflict="external_id").execute()
    log.info("reports upsert: %d rows", len(rows))
    return len(rows)


def fetch_reports_to_score(only_unscored: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
    """채점 대상 reports 조회. only_unscored 면 report_scores 에 없는 것만."""
    resp = client().table("reports").select(
        "id, external_id, title, summary, theme, company, ticker, broker, "
        "target_price, opinion, aria_priority, signal_level, is_risk"
    ).order("collected_at", desc=True).execute()
    reports = resp.data or []
    if only_unscored:
        scored = client().table("report_scores").select("report_id").execute()
        scored_ids = {r["report_id"] for r in (scored.data or [])}
        reports = [r for r in reports if r["id"] not in scored_ids]
    if limit:
        reports = reports[:limit]
    return reports


def upsert_report_scores(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    client().table("report_scores").upsert(rows, on_conflict="report_id").execute()
    log.info("report_scores upsert: %d rows", len(rows))
    return len(rows)


def fetch_report_scores_for(report_ids: Iterable[str]) -> list[dict[str, Any]]:
    """daily_batch 산출용 점수 조회(정렬 지수 + ARIA 강도 동점 보정)."""
    ids = list(report_ids)
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("report_scores").select(
            "report_id, interest_index, story_index, safety_index"
        ).in_("report_id", chunk).execute()
        out.extend(resp.data or [])
    return out


def fetch_report_ids_all() -> list[str]:
    resp = client().table("reports").select("id").execute()
    return [r["id"] for r in (resp.data or [])]


def fetch_reports_aria_priority(report_ids: Iterable[str]) -> dict[str, float]:
    """report_id → aria_priority(신호 강도). 정렬 동점 보정용."""
    ids = list(report_ids)
    out: dict[str, float] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("reports").select("id, aria_priority").in_("id", chunk).execute()
        for r in (resp.data or []):
            out[r["id"]] = float(r.get("aria_priority") or 0)
    return out


def fetch_recent_tickers(days: int) -> set[str]:
    """최근 N일 배치/결정에 등장한 ticker 집합(쿨다운 — 펌핑 오해 방지).

    간단화: report_daily_batch 에 오른 reports 의 ticker 를 모은다(날짜 필터는 배치일 기준).
    """
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=max(0, days))).isoformat()
    batch = client().table("report_daily_batch").select("report_id").gte("batch_date", cutoff).execute()
    rids = [r["report_id"] for r in (batch.data or [])]
    tickers: set[str] = set()
    for i in range(0, len(rids), 200):
        chunk = rids[i:i + 200]
        resp = client().table("reports").select("ticker").in_("id", chunk).execute()
        for r in (resp.data or []):
            if r.get("ticker"):
                tickers.add(r["ticker"])
    return tickers


def fetch_prior_report_batch_ids(before_date: str) -> set[str]:
    """before_date 이전(미포함)의 report_daily_batch 에 이미 등장한 report_id 집합(신선도)."""
    resp = client().table("report_daily_batch").select("report_id").lt("batch_date", before_date).execute()
    return {r["report_id"] for r in (resp.data or [])}


def replace_report_daily_batch(batch_date: str, rows: list[dict[str, Any]]) -> int:
    """그날 배치를 멱등 재생성(기존 삭제 후 삽입)."""
    client().table("report_daily_batch").delete().eq("batch_date", batch_date).execute()
    if rows:
        client().table("report_daily_batch").insert(rows).execute()
    log.info("report_daily_batch[%s]: %d rows", batch_date, len(rows))
    return len(rows)


# ─────────────────────────────────────────────────────────────
# PF1 (report_drafts / report_draft_requests) — 논문 db.py P1 슬라이스 미러
# ─────────────────────────────────────────────────────────────
def get_report(report_id: str) -> dict[str, Any] | None:
    resp = client().table("reports").select(
        "id, external_id, title, summary, theme, company, ticker, broker, analyst, "
        "target_price, opinion, report_url"
    ).eq("id", report_id).maybe_single().execute()
    return resp.data if resp else None


def fetch_report_ids_by_external(external_ids: Iterable[str]) -> dict[str, str]:
    """external_id → reports.id. 수집 직후 원문 보관 행에 FK 를 채우는 데 쓴다."""
    ids = [e for e in external_ids if e]
    out: dict[str, str] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("reports").select("id, external_id").in_(
            "external_id", chunk).execute()
        for r in resp.data or []:
            out[r["external_id"]] = r["id"]
    return out


def get_report_source(external_id: str) -> dict[str, Any] | None:
    """보관된 원문 중 가장 최근 것(0033). 없으면 None → 호출측이 ARIA 를 부른다.

    ★ 조회 키가 doc_hash 가 아니라 external_id 인 이유: 우리는 "이 리포트의 원문이 있는가"를
      묻는 것이지 "이 해시의 원문이 있는가"를 묻는 게 아니다. 해시는 저장 시 중복 방지와
      인용 대조 앵커로 쓴다.
    """
    if not external_id:
        return None
    resp = client().table("report_sources").select(
        "id, report_id, external_id, source_type, source_depth, source_url, "
        "doc_hash, char_count, truncated, text, chunks"
    ).eq("external_id", external_id).order("fetched_at", desc=True).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def insert_report_source(row: dict[str, Any]) -> None:
    """원문 보관. 같은 (external_id, doc_hash) 재저장은 조용히 무시한다(멱등).

    ★ 실패해도 예외를 올리지 않는다 — 보관은 부수 효과이고, 여기서 죽으면 초안 생성 전체가
      멈춘다. 저장에 실패하면 다음 실행이 ARIA 를 다시 부를 뿐이다.
    """
    try:
        client().table("report_sources").upsert(
            row, on_conflict="external_id,doc_hash"
        ).execute()
        log.info("report_source 보관: %s (%s자)", row.get("external_id"), row.get("char_count"))
    except Exception as exc:  # noqa: BLE001 — 보관 실패가 파이프라인을 막지 않는다
        log.warning("report_source 보관 실패(무시): %s", exc)


def upsert_report_draft(row: dict[str, Any]) -> None:
    client().table("report_drafts").upsert(row, on_conflict="report_id").execute()
    log.info("report_draft upsert: report=%s", row.get("report_id"))


def get_report_draft(report_id: str) -> dict[str, Any] | None:
    resp = client().table("report_drafts").select(
        "report_id, fact_sheet, script_md, scenes, self_check, compliance, "
        "story_plan, evidence, video_flow, financial_reasoning"
    ).eq("report_id", report_id).maybe_single().execute()
    return resp.data if resp else None


def update_report_draft_compliance(report_id: str, compliance: dict[str, Any],
                                   evidence: dict[str, Any] | None = None,
                                   fact_sheet: dict[str, Any] | None = None,
                                   scenes: list[dict[str, Any]] | None = None,
                                   self_check: dict[str, Any] | None = None,
                                   validated_script_hash: str | None = None) -> None:
    """[재검사] — 컴플라이언스(+근거 게이트) 결과 갱신. 대본은 건드리지 않는다.

    ★ fact_sheet 를 받으면 함께 쓴다 — 재검사가 validation 을 다시 계산했기 때문이다.
      게이트(hard_blocks)가 저장된 validation 을 읽으므로, 다시 계산해 놓고 저장하지 않으면
      다음 조회에서 옛 판정이 되살아난다.
    """
    patch: dict[str, Any] = {"compliance": compliance}
    if evidence is not None:
        patch["evidence"] = evidence
    if fact_sheet is not None:
        patch["fact_sheet"] = fact_sheet
    # ★ 재검사가 편집된 대본으로 씬을 맞추고 자기검증을 다시 돌렸다면 그 결과도 저장한다
    #   (PR #94 후속 P1-2). 저장하지 않으면 다음 조회에서 옛 판정이 되살아난다 —
    #   fact_sheet 를 함께 저장하는 것과 같은 이유다.
    if scenes is not None:
        patch["scenes"] = scenes
    if self_check is not None:
        patch["self_check"] = self_check
    if validated_script_hash is not None:
        patch["validated_script_hash"] = validated_script_hash
    client().table("report_drafts").update(patch).eq("report_id", report_id).execute()


def claim_report_draft_requests(limit: int = 5) -> list[dict[str, Any]]:
    """'queued' 요청을 원자적으로 잡아(→'processing') 반환(claim_render_jobs 원자 패턴).

    ★ 논문 claim_draft_requests 는 비원자적이라 동시 워커 시 중복 처리 가능 →
      리포트는 status='queued' 조건부 갱신(compare-and-swap)으로 중복 방지.
    """
    from datetime import datetime, timezone
    def _fetch(cols: str):
        return client().table("report_draft_requests").select(cols).eq(
            "status", "queued"
        ).order("requested_at").limit(limit).execute()

    try:
        resp = _fetch("id, report_id, mode, instruction, version_types")
    except Exception:  # noqa: BLE001
        # 0046 미적용 DB — 지시서 자동 생성 없이 예전대로 처리한다(워커를 멈추지 않는다).
        try:
            log.warning("report_draft_requests.version_types 없음(0046 미적용) — 지시서 자동 생성 없이 처리")
            resp = _fetch("id, report_id, mode, instruction")
        except Exception:  # noqa: BLE001
            # 0038 미적용 DB — 세부 수정 요청 없이 예전대로 처리한다.
            log.warning("report_draft_requests.instruction 없음(0038 미적용) — 지시 없이 처리")
            resp = _fetch("id, report_id, mode")
    claimed: list[dict[str, Any]] = []
    for r in resp.data or []:
        upd = (client().table("report_draft_requests")
               .update({"status": "processing",
                        "updated_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", r["id"]).eq("status", "queued").execute())
        if upd.data:  # 이 워커가 실제로 잡음
            claimed.append(r)
    return claimed


def update_report_draft_request(req_id: str, status: str, error: str | None = None) -> None:
    from datetime import datetime, timezone
    client().table("report_draft_requests").update(
        {"status": status, "error": error,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", req_id).execute()


# ─────────────────────────────────────────────────────────────
# PF2 영상화 (report_directives / report_render_jobs) — db.py 렌더 슬라이스 미러
# ─────────────────────────────────────────────────────────────
def insert_report_directive(row: dict[str, Any]) -> str:
    resp = client().table("report_directives").insert(row).execute()
    data = resp.data or []
    dir_id = data[0]["id"] if data else ""
    log.info("report_directive insert: report=%s id=%s", row.get("report_id"), dir_id)
    return dir_id


def get_report_directive(directive_id: str) -> dict[str, Any] | None:
    resp = client().table("report_directives").select(
        "id, report_id, version_type, header, cuts, status"
    ).eq("id", directive_id).maybe_single().execute()
    return resp.data if resp else None


def get_latest_report_directive(report_id: str) -> dict[str, Any] | None:
    resp = (client().table("report_directives")
            .select("id, report_id, version_type, header, cuts, status, created_at, approved_at")
            .eq("report_id", report_id).order("created_at", desc=True).limit(1)
            .maybe_single().execute())
    return resp.data if resp else None


def update_report_directive_status(directive_id: str, status: str) -> None:
    patch: dict[str, Any] = {"status": status}
    if status == "approved":
        from datetime import datetime, timezone
        patch["approved_at"] = datetime.now(timezone.utc).isoformat()
    client().table("report_directives").update(patch).eq("id", directive_id).execute()


def claim_report_directive_requests(limit: int = 5) -> list[dict[str, Any]]:
    """'queued' 요청을 원자적으로 잡아(→'processing') 반환(compare-and-swap)."""
    from datetime import datetime, timezone
    resp = client().table("report_directive_requests").select("id, report_id, version_type").eq(
        "status", "queued"
    ).order("requested_at").limit(limit).execute()
    claimed: list[dict[str, Any]] = []
    for r in resp.data or []:
        upd = (client().table("report_directive_requests")
               .update({"status": "processing",
                        "updated_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", r["id"]).eq("status", "queued").execute())
        if upd.data:
            claimed.append(r)
    return claimed


def update_report_directive_request(req_id: str, status: str, error: str | None = None) -> None:
    from datetime import datetime, timezone
    client().table("report_directive_requests").update(
        {"status": status, "error": error,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", req_id).execute()


def insert_report_directive_request(report_id: str, version_type: str) -> str:
    """워커가 **직접 처리할** 지시서 요청 행을 'processing' 으로 적재한다 → 요청 id.

    초안→지시서 연쇄(0046)용. db.insert_directive_request 미러 — 행이 있어야 화면이
    "지시서 만드는 중"을 보여주고 실패 흔적이 남는다. 처음부터 processing 이라 다른 워커가
    집어가지 않는다.
    """
    from datetime import datetime, timezone
    resp = client().table("report_directive_requests").insert(
        {"report_id": report_id, "version_type": version_type, "status": "processing",
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).execute()
    return str(((resp.data or [{}])[0]).get("id") or "")


def _reclaim_stale_report_render_jobs() -> int:
    """진행중(assets/tts/assembling) 방치 잡 재큐(watchdog). db._reclaim_stale_render_jobs 미러."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=config.RENDER_STALE_MINUTES)).isoformat()
    resp = (client().table("report_render_jobs")
            .update({"status": "queued", "progress": 0,
                     "error_log": "이전 워커 무응답으로 재큐됨(watchdog)",
                     "updated_at": datetime.now(timezone.utc).isoformat()})
            # ★ config 정본. 사람 대기 상태는 일부러 빠져 있다(db._reclaim_stale_render_jobs 주석).
            .in_("status", list(config.RENDER_STATUS_IN_PROGRESS))
            .lt("updated_at", cutoff).execute())
    n = len(resp.data or [])
    if n:
        log.warning("watchdog: 정체된 리포트 렌더 잡 %d건 재큐(>%d분)", n, config.RENDER_STALE_MINUTES)
    return n


def claim_report_render_jobs(limit: int = 3) -> list[dict[str, Any]]:
    """'queued' 렌더 잡을 원자적으로 잡아(→'assets') 반환. 정체 잡은 먼저 watchdog 재큐."""
    from datetime import datetime, timezone
    _reclaim_stale_report_render_jobs()
    resp = client().table("report_render_jobs").select("id, directive_id, lang").eq(
        "status", "queued"
    ).order("created_at").limit(limit).execute()
    claimed: list[dict[str, Any]] = []
    for r in resp.data or []:
        upd = (client().table("report_render_jobs")
               .update({"status": "assets", "progress": 5,
                        "updated_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", r["id"]).eq("status", "queued").execute())
        if upd.data:
            claimed.append(r)
    return claimed


def update_report_render_job(
    job_id: str, *, status: str | None = None, progress: int | None = None,
    cost_estimate: float | None = None, output_url: str | None = None,
    error_log: str | None = None, finished: bool = False,
    qa: dict[str, Any] | None = None,
) -> None:
    from datetime import datetime, timezone
    patch: dict[str, Any] = {}
    if status is not None:
        patch["status"] = status
    if progress is not None:
        patch["progress"] = progress
    if cost_estimate is not None:
        patch["cost_estimate"] = cost_estimate
    if output_url is not None:
        patch["output_url"] = output_url
    if error_log is not None:
        patch["error_log"] = error_log
    if qa is not None:
        patch["qa"] = qa          # 0036. 기록 전용 — 차단하지 않는다.
    if finished:
        patch["finished_at"] = datetime.now(timezone.utc).isoformat()
    if patch:
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()
        client().table("report_render_jobs").update(patch).eq("id", job_id).execute()


def get_report_render_job(job_id: str) -> dict[str, Any] | None:
    resp = client().table("report_render_jobs").select(
        "id, directive_id, status, output_url, lang"
    ).eq("id", job_id).maybe_single().execute()
    return resp.data if resp else None


def get_report_hook(report_id: str) -> str:
    """영상 상단 부제용 후킹: report_scores.one_liner_ko(없으면 빈값)."""
    if not report_id:
        return ""
    s = client().table("report_scores").select("one_liner_ko").eq(
        "report_id", report_id).maybe_single().execute()
    return ((s.data or {}).get("one_liner_ko") if s else "") or ""


def upload_render(local_path: str, dest_path: str, content_type: str = "video/mp4") -> str:
    """리포트 mp4 업로드 — 논문과 같은 'renders' 버킷(경로만 report/ 접두). db.upload_render 위임."""
    from . import db
    return db.upload_render(local_path, dest_path, content_type)


# ─────────────────────────────────────────────────────────────
# PF-V 유튜브 업로드 (report_upload_requests) — db.py 업로드 슬라이스 미러
# ─────────────────────────────────────────────────────────────
def get_report_upload_meta(report_id: str) -> dict[str, Any]:
    """업로드 제목·설명 조립용 메타. 리포트 출처 + 업로드 제목(초안) + 한 줄 요약(점수).

    반환: {"report": {...}, "title_ko", "upload_title_ko/en", "one_liner_ko/en"}.
    빈 값은 호출측이 폴백(제목은 리포트 제목, teaser 는 생략)한다.
    """
    report = get_report(report_id) or {}
    d = client().table("report_drafts").select(
        "upload_title_ko, upload_title_en"
    ).eq("report_id", report_id).maybe_single().execute()
    draft = (d.data if d else None) or {}
    s = client().table("report_scores").select(
        "one_liner_ko, one_liner_en, title_ko"
    ).eq("report_id", report_id).maybe_single().execute()
    score = (s.data if s else None) or {}
    return {
        "report": report,
        "title_ko": score.get("title_ko"),
        "upload_title_ko": draft.get("upload_title_ko"),
        "upload_title_en": draft.get("upload_title_en"),
        "one_liner_ko": score.get("one_liner_ko") or "",
        "one_liner_en": score.get("one_liner_en") or "",
    }


def get_report_render_job_for_upload(job_id: str) -> dict[str, Any] | None:
    """업로드 워커 입력용: 리포트 렌더 mp4 URL·언어·지시서. get_report_render_job 재사용."""
    return get_report_render_job(job_id)


def claim_report_upload_requests(limit: int = 3) -> list[dict[str, Any]]:
    """'queued' 리포트 업로드 요청을 원자적으로 잡아(→'processing') 반환.

    ★ 논문과 동일: watchdog 재큐 없음(업로드는 되돌리기 어려운 외부 행위 — 중복 방지).
      정체된 'processing' 은 사람이 수동 재시도한다.
    """
    from datetime import datetime, timezone
    resp = client().table("report_upload_requests").select(
        "id, render_job_id, report_id, lang, privacy_status"
    ).eq("status", "queued").order("requested_at").limit(limit).execute()
    claimed: list[dict[str, Any]] = []
    for r in resp.data or []:
        upd = (client().table("report_upload_requests")
               .update({"status": "processing", "progress": 5,
                        "updated_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", r["id"]).eq("status", "queued").execute())
        if upd.data:  # 이 워커가 실제로 잡음
            claimed.append(r)
    return claimed


def update_report_upload_request(
    req_id: str, *, status: str | None = None, progress: int | None = None,
    youtube_video_id: str | None = None, youtube_url: str | None = None,
    error: str | None = None, finished: bool = False,
    source_factory: str | None = None, content_type: str | None = None,
    series_id: str | None = None, channel_id: str | None = None,
) -> None:
    """업로드 요청 행 갱신. 출처·분류(0032)는 값이 주어질 때만 기록한다."""
    from datetime import datetime, timezone
    patch: dict[str, Any] = {}
    for col, val in (("source_factory", source_factory), ("content_type", content_type),
                     ("series_id", series_id), ("channel_id", channel_id)):
        if val is not None:
            patch[col] = val
    if status is not None:
        patch["status"] = status
    if progress is not None:
        patch["progress"] = progress
    if youtube_video_id is not None:
        patch["youtube_video_id"] = youtube_video_id
    if youtube_url is not None:
        patch["youtube_url"] = youtube_url
    if error is not None:
        patch["error"] = error[:1000]
    if finished:
        patch["finished_at"] = datetime.now(timezone.utc).isoformat()
    if patch:
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()
        client().table("report_upload_requests").update(patch).eq("id", req_id).execute()


def record_report_youtube_publish(report_id: str, lang: str, video_id: str, url: str) -> None:
    """report_published.platforms 에 유튜브 결과를 병합 기록(기존 값 보존). PK=report_id."""
    if not report_id:
        return
    existing = client().table("report_published").select(
        "final_script, platforms"
    ).eq("report_id", report_id).maybe_single().execute()
    row = (existing.data if existing else None) or {}
    platforms = row.get("platforms") if isinstance(row.get("platforms"), dict) else {}
    platforms = dict(platforms)
    platforms[f"youtube_{lang}"] = {"video_id": video_id, "url": url}
    client().table("report_published").upsert(
        {
            "report_id": report_id,
            "final_script": row.get("final_script") or f"[유튜브:{lang}] {url}",
            "platforms": platforms,
        },
        on_conflict="report_id",
    ).execute()
    log.info("report_published 유튜브 기록: report=%s lang=%s url=%s", report_id, lang, url)
