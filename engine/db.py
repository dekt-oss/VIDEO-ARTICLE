"""Supabase 접근 계층 (service_role 키 — 서버/엔진 전용, RLS 우회).

CLAUDE.md: SUPABASE_SERVICE_KEY 는 절대 클라이언트에 노출하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Iterable

from . import config
from .util import log

if TYPE_CHECKING:
    from supabase import Client


@lru_cache(maxsize=1)
def client() -> "Client":
    # 지연 임포트: supabase SDK 미설치 환경에서도 순수 로직 임포트가 가능하도록.
    from supabase import create_client

    config.SECRETS.require("supabase_url", "supabase_service_key")
    return create_client(config.SECRETS.supabase_url, config.SECRETS.supabase_service_key)


def existing_external_ids(external_ids: Iterable[str]) -> set[str]:
    """이미 papers 에 존재하는 external_id 집합(재탕 방지용 사전 조회)."""
    ids = [e for e in external_ids if e]
    if not ids:
        return set()
    found: set[str] = set()
    # in_ 필터 길이 제한 대비 청크 분할
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("papers").select("external_id").in_("external_id", chunk).execute()
        found.update(r["external_id"] for r in (resp.data or []))
    return found


def upsert_papers(rows: list[dict[str, Any]]) -> int:
    """papers 멱등 upsert(external_id 충돌 시 갱신). 반환: 처리 건수."""
    if not rows:
        return 0
    client().table("papers").upsert(rows, on_conflict="external_id").execute()
    log.info("papers upsert: %d rows", len(rows))
    return len(rows)


def get_paper_ids_by_external(external_ids: Iterable[str]) -> dict[str, str]:
    """external_id → paper uuid 매핑."""
    ids = [e for e in external_ids if e]
    out: dict[str, str] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("papers").select("id, external_id").in_("external_id", chunk).execute()
        for r in (resp.data or []):
            out[r["external_id"]] = r["id"]
    return out


# ─ 수집 커버리지 v2: 워터마크 · 발견 이벤트 · 미매칭 큐 ─
def get_watermark(key: str) -> str | None:
    """collection_state 워터마크(ISO timestamptz) 조회. 없으면 None(최초 실행)."""
    resp = client().table("collection_state").select("watermark").eq("key", key).maybe_single().execute()
    row = resp.data if resp else None
    return (row or {}).get("watermark")


def set_watermark(key: str, watermark_iso: str) -> None:
    """워터마크 전진(§3-2) — 반드시 papers 저장 성공 후에만 호출한다."""
    from datetime import datetime, timezone
    client().table("collection_state").upsert(
        {"key": key, "watermark": watermark_iso,
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="key",
    ).execute()
    log.info("워터마크 전진: %s → %s", key, watermark_iso)


def record_discovery_events(events: list[dict[str, Any]]) -> None:
    """발견 이벤트 멱등 기록(§7). (route, external_id, source_item_url) unique 로 중복 흡수."""
    if not events:
        return
    client().table("paper_discovery_events").upsert(
        events, on_conflict="route,external_id,source_item_url", ignore_duplicates=True
    ).execute()
    log.info("발견 이벤트 기록: %d건", len(events))


def upsert_unresolved_buzz(items: list[dict[str, Any]]) -> None:
    """DOI 자동연결 임계 미달 항목을 검토 큐에 적재(§6). (route, source_item_url) unique."""
    if not items:
        return
    client().table("unresolved_buzz_items").upsert(
        items, on_conflict="route,source_item_url", ignore_duplicates=True
    ).execute()
    log.info("미매칭 화제성 큐: %d건", len(items))


def fetch_papers_to_score(only_unscored: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
    """채점 대상 papers 조회. only_unscored 면 scores 에 없는 것만."""
    resp = client().table("papers").select(
        "id, external_id, title, abstract, venue, buzz_raw, published_date"
    ).order("published_date", desc=True).execute()
    papers = resp.data or []
    if only_unscored:
        scored = client().table("scores").select("paper_id").execute()
        scored_ids = {r["paper_id"] for r in (scored.data or [])}
        papers = [p for p in papers if p["id"] not in scored_ids]
    if limit:
        papers = papers[:limit]
    return papers


def fetch_scores_for_papers(paper_ids: Iterable[str]) -> list[dict[str, Any]]:
    """daily_batch 산출용 점수 조회."""
    ids = list(paper_ids)
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("scores").select(
            "paper_id, fun_index, importance_index"
        ).in_("paper_id", chunk).execute()
        out.extend(resp.data or [])
    return out


def upsert_scores(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    client().table("scores").upsert(rows, on_conflict="paper_id").execute()
    log.info("scores upsert: %d rows", len(rows))
    return len(rows)


def fetch_papers_needing_title_ko(limit: int | None = None) -> list[dict[str, Any]]:
    """번역 백필 대상: daily_batch·decisions 에 등장하고 scores.title_ko 가 빈 논문.

    반환: [{"id": paper_uuid, "title": 원제}]. 표시 대상만 겨냥해 불필요한 번역 비용을 막는다.
    """
    # 표시 대상 후보 = 배치에 편성됐거나 사람이 결정(낙점/후보/탈락)한 논문.
    batch = client().table("daily_batch").select("paper_id").execute()
    decs = client().table("decisions").select("paper_id").execute()
    candidate_ids = {r["paper_id"] for r in (batch.data or [])}
    candidate_ids |= {r["paper_id"] for r in (decs.data or [])}
    if not candidate_ids:
        return []

    ids = list(candidate_ids)
    # title_ko 가 채워진 paper 집합(채워진 것은 제외).
    has_ko: set[str] = set()
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("scores").select("paper_id, title_ko").in_("paper_id", chunk).execute()
        for r in (resp.data or []):
            if (r.get("title_ko") or "").strip():
                has_ko.add(r["paper_id"])
    need_ids = [pid for pid in ids if pid not in has_ko]
    if not need_ids:
        return []

    out: list[dict[str, Any]] = []
    for i in range(0, len(need_ids), 200):
        chunk = need_ids[i:i + 200]
        resp = client().table("papers").select("id, title").in_("id", chunk).execute()
        for r in (resp.data or []):
            if (r.get("title") or "").strip():
                out.append({"id": r["id"], "title": r["title"]})
    if limit:
        out = out[:limit]
    return out


def recent_batch_dates(limit: int = 7) -> list[str]:
    """최근 배치 날짜(내림차순) 목록."""
    resp = client().table("daily_batch").select("batch_date").order(
        "batch_date", desc=True
    ).execute()
    seen: list[str] = []
    for r in (resp.data or []):
        d = r["batch_date"]
        if d not in seen:
            seen.append(d)
        if len(seen) >= limit:
            break
    return seen


def batch_paper_ids(batch_date: str) -> list[str]:
    resp = client().table("daily_batch").select("paper_id").eq("batch_date", batch_date).execute()
    return [r["paper_id"] for r in (resp.data or [])]


def decisions_for(paper_ids: Iterable[str]) -> dict[str, str]:
    """paper_id → status 매핑."""
    ids = list(paper_ids)
    out: dict[str, str] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        resp = client().table("decisions").select("paper_id, status").in_("paper_id", chunk).execute()
        for r in (resp.data or []):
            out[r["paper_id"]] = r["status"]
    return out


def fetch_prior_batch_paper_ids(before_date: str) -> set[str]:
    """before_date 이전(미포함)의 daily_batch 에 이미 등장한 paper_id 집합.

    '이전 후보 리스트에 오른 논문은 다음 리스트에서 제외'(신선도)를 위해 쓴다.
    같은 날 재실행은 그날 배치를 재생성하므로 before_date=오늘 로 호출해 오늘 것은 제외 대상에서 뺀다(멱등).
    """
    resp = client().table("daily_batch").select("paper_id").lt("batch_date", before_date).execute()
    return {r["paper_id"] for r in (resp.data or [])}


def replace_daily_batch(batch_date: str, rows: list[dict[str, Any]]) -> int:
    """그날 배치를 멱등 재생성(기존 삭제 후 삽입)."""
    client().table("daily_batch").delete().eq("batch_date", batch_date).execute()
    if rows:
        client().table("daily_batch").insert(rows).execute()
    log.info("daily_batch[%s]: %d rows", batch_date, len(rows))
    return len(rows)


# ─────────────────────────────────────────────────────────────
# P1 (drafts / draft_requests)
# ─────────────────────────────────────────────────────────────
def get_paper(paper_id: str) -> dict[str, Any] | None:
    resp = client().table("papers").select(
        "id, external_id, title, abstract, venue, authors, url, published_date"
    ).eq("id", paper_id).maybe_single().execute()
    return resp.data if resp else None


def get_paper_source(external_id: str) -> dict[str, Any] | None:
    """보관된 논문 원문 중 가장 최근 것(0041). 없으면 None → 호출측이 확보 체인을 돈다.

    ★ 조회 키가 doc_hash 가 아니라 external_id 인 이유는 report_db.get_report_source 와 같다 —
      우리는 "이 논문의 원문이 있는가"를 묻는 것이지 "이 해시의 원문이 있는가"를 묻지 않는다.
    """
    if not external_id:
        return None
    resp = client().table("paper_sources").select(
        "id, paper_id, external_id, provider, content_format, source_url, version, license, "
        "source_depth, doc_hash, char_count, truncated, parse_error, text, chunks"
    ).eq("external_id", external_id).order("fetched_at", desc=True).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def insert_paper_source(row: dict[str, Any]) -> None:
    """원문 보관. 같은 (external_id, doc_hash) 재저장은 조용히 무시한다(멱등).

    ★ 실패해도 예외를 올리지 않는다 — 보관은 부수 효과다. 여기서 죽으면 초안 생성 전체가
      멈춘다. 저장에 실패하면 다음 실행이 확보 체인을 다시 돌 뿐이다.
    """
    try:
        client().table("paper_sources").upsert(
            row, on_conflict="external_id,doc_hash"
        ).execute()
        log.info("paper_source 보관: %s (%s자)", row.get("external_id"), row.get("char_count"))
    except Exception as exc:  # noqa: BLE001 — 보관 실패가 파이프라인을 막지 않는다
        log.warning("paper_source 보관 실패(무시): %s", exc)


def upsert_draft(row: dict[str, Any]) -> None:
    client().table("drafts").upsert(row, on_conflict="paper_id").execute()
    log.info("draft upsert: paper=%s", row.get("paper_id"))


def claim_draft_requests(limit: int = 5) -> list[dict[str, Any]]:
    """'queued' 요청을 가져와 'processing' 으로 표시(폴링 워커용)."""
    def _fetch(cols: str):
        return client().table("draft_requests").select(cols).eq(
            "status", "queued"
        ).order("requested_at").limit(limit).execute()

    # ★ version_types(0046) — 초안 뒤 이어서 만들 지시서 버전. 컬럼이 없는 DB(0046 미적용)에서는
    #   예전대로 처리한다(워커를 멈추지 않는다) — report_db.claim_report_draft_requests 와 같은 자세.
    try:
        resp = _fetch("id, paper_id, version_types")
    except Exception:  # noqa: BLE001
        log.warning("draft_requests.version_types 없음(0046 미적용) — 지시서 자동 생성 없이 처리")
        resp = _fetch("id, paper_id")
    rows = resp.data or []
    for r in rows:
        update_draft_request(r["id"], "processing")
    return rows


def update_draft_request(req_id: str, status: str, error: str | None = None) -> None:
    client().table("draft_requests").update(
        {"status": status, "error": error}
    ).eq("id", req_id).execute()


# ─────────────────────────────────────────────────────────────
# 영상화 (directives / directive_requests / render_jobs / render_assets)
# ─────────────────────────────────────────────────────────────
def get_draft_full(paper_id: str) -> dict[str, Any] | None:
    """지시서 생성 입력용: 대본·Fact Sheet·기존 장면."""
    resp = client().table("drafts").select(
        "paper_id, fact_sheet, script_md, video_flow, video_prompts"
    ).eq("paper_id", paper_id).maybe_single().execute()
    return resp.data if resp else None


def insert_directive(row: dict[str, Any]) -> str:
    """지시서 1건 삽입. 반환: 생성된 directive id."""
    resp = client().table("directives").insert(row).execute()
    data = resp.data or []
    dir_id = data[0]["id"] if data else ""
    log.info("directive insert: paper=%s id=%s", row.get("paper_id"), dir_id)
    return dir_id


def get_directive(directive_id: str) -> dict[str, Any] | None:
    resp = client().table("directives").select(
        "id, paper_id, version_type, header, cuts, status"
    ).eq("id", directive_id).maybe_single().execute()
    return resp.data if resp else None


def list_recent_approved_directives(limit: int = 5) -> list[dict[str, Any]]:
    """작업 A 자동 Batch 제출 대상(§7): 승인/렌더 흐름에 든 최근 지시서(재렌더·편집 재시도 포함)."""
    resp = client().table("directives").select("id").in_(
        "status", ["approved", "rendering", "rendered"]
    ).order("approved_at", desc=True).limit(limit).execute()
    return resp.data or []


def update_directive_status(directive_id: str, status: str) -> None:
    client().table("directives").update({"status": status}).eq("id", directive_id).execute()


def get_paper_hook(paper_id: str) -> str:
    """영상 상단 부제용 후킹 문장: scores.one_liner_ko 우선, 없으면 draft video_flow.logline."""
    s = client().table("scores").select("one_liner_ko").eq("paper_id", paper_id).maybe_single().execute()
    hook = ((s.data or {}).get("one_liner_ko") if s else "") or ""
    if hook.strip():
        return hook.strip()
    d = client().table("drafts").select("video_flow").eq("paper_id", paper_id).maybe_single().execute()
    flow = (d.data or {}).get("video_flow") if d else None
    if isinstance(flow, dict):
        return str(flow.get("logline") or "").strip()
    return ""


def requeue_stale_directive_requests(table: str = "directive_requests") -> int:
    """임대가 만료된 processing 요청을 되집어 온다(0043, 리뷰 §8). 반환: 재큐 건수.

    ★ 왜 필요한가: 워커나 Edge 가 중간에 죽으면 catch 가 안 돌아 상태가 processing 인 채로
      영원히 남는다(2026-08-28 실측: Edge isolate 가 47초에 shutdown, 요청은 그대로).
      임대 만료를 기준으로 삼으면 "죽었는지"를 묻지 않고도 회수된다.
    ★ 시도 횟수가 상한을 넘으면 재큐하지 않고 **error 로 확정**한다 — 유료 호출을 무한히
      태우지 않기 위해서다. 사유가 last_error 에 남아 화면에서 보인다.
    """
    now = datetime.now(timezone.utc)
    resp = client().table(table).select("id, attempt_count").eq("status", "processing").execute()
    rows = resp.data or []
    if not rows:
        return 0
    # lease 가 살아 있는 행은 건드리지 않는다. NULL lease 는 임대 이전 옛 행 → 회수 대상.
    alive = client().table(table).select("id").eq("status", "processing").gt(
        "lease_expires_at", now.isoformat()).execute().data or []
    alive_ids = {r["id"] for r in alive}
    n = 0
    for r in rows:
        if r["id"] in alive_ids:
            continue
        attempts = int(r.get("attempt_count") or 0)
        if attempts >= config.REQUEST_MAX_ATTEMPTS:
            client().table(table).update({
                "status": "error", "updated_at": now.isoformat(),
                "last_error": f"시도 {attempts}회 초과 — 자동 재큐 중단",
            }).eq("id", r["id"]).execute()
            log.warning("%s 요청 %s: 시도 %d회 초과 → error 확정", table, r["id"], attempts)
            continue
        client().table(table).update({
            "status": "queued", "lease_expires_at": None, "updated_at": now.isoformat(),
            "last_error": "임대 만료(워커 중단 추정) — 자동 재큐",
        }).eq("id", r["id"]).execute()
        n += 1
    if n:
        log.info("%s: 임대 만료 요청 %d건 재큐", table, n)
    return n


def claim_directive_requests(limit: int = 5) -> list[dict[str, Any]]:
    """queued 요청을 **임대**로 잡는다(0043). 만료된 처리중 행을 먼저 회수한다."""
    try:
        requeue_stale_directive_requests()
    except Exception as exc:  # noqa: BLE001 — 회수 실패가 정상 폴링을 막지 않는다
        log.warning("만료 요청 회수 실패(무시): %s", exc)
    resp = client().table("directive_requests").select(
        "id, paper_id, version_type, attempt_count"
    ).eq("status", "queued").order("requested_at").limit(limit).execute()
    rows = resp.data or []
    for r in rows:
        lease_directive_request(r["id"], int(r.get("attempt_count") or 0) + 1)
    return rows


def lease_directive_request(req_id: str, attempt: int,
                            table: str = "directive_requests") -> None:
    """요청을 processing 으로 잡고 임대 만료 시각을 찍는다."""
    now = datetime.now(timezone.utc)
    client().table(table).update({
        "status": "processing",
        "attempt_count": attempt,
        "worker_id": config.WORKER_ID,
        "heartbeat_at": now.isoformat(),
        "lease_expires_at": (now + timedelta(seconds=config.REQUEST_LEASE_SEC)).isoformat(),
        "updated_at": now.isoformat(),
    }).eq("id", req_id).execute()


def heartbeat_directive_request(req_id: str, table: str = "directive_requests") -> None:
    """살아 있음을 알리고 임대를 연장한다. 실패는 무시한다(렌더를 막지 않는다)."""
    now = datetime.now(timezone.utc)
    try:
        client().table(table).update({
            "heartbeat_at": now.isoformat(),
            "lease_expires_at": (now + timedelta(seconds=config.REQUEST_LEASE_SEC)).isoformat(),
        }).eq("id", req_id).execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("heartbeat 실패(무시) %s: %s", req_id, exc)


def update_directive_request(req_id: str, status: str, error: str | None = None) -> None:
    # ★ 끝난 요청은 임대를 놓는다(0043). 안 놓으면 done 인 행이 lease 를 들고 있어
    #   재큐 스캔이 매번 훑는다(무해하지만 상태가 거짓말을 한다).
    client().table("directive_requests").update(
        {"status": status, "error": error, "last_error": error,
         "lease_expires_at": None}
    ).eq("id", req_id).execute()


def insert_directive_request(paper_id: str, version_type: str) -> str:
    """워커가 **직접 처리할** 지시서 요청 행을 적재하고 곧바로 임대한다 → 요청 id.

    ★ 왜 행을 남기나(초안→지시서 연쇄, 0046): 지시서를 바로 만들 것이라도 큐 행이 있어야
      화면(/api/draft-status)이 "지시서 만드는 중"을 보여주고, 실패했을 때 ⑤ 에서 다시
      누를 수 있는 흔적이 남는다. 다른 워커가 집어가지 않게 적재와 임대를 **한 번의 insert** 로
      한다 — queued 로 넣고 따로 임대하면 그 사이 다른 워커(로컬 engine.directive)가 집어가
      같은 지시서를 두 번 만든다(2026-09-11 리뷰).
    """
    now = datetime.now(timezone.utc)
    resp = client().table("directive_requests").insert({
        "paper_id": paper_id, "version_type": version_type, "status": "processing",
        "attempt_count": 1, "worker_id": config.WORKER_ID,
        "heartbeat_at": now.isoformat(),
        "lease_expires_at": (now + timedelta(seconds=config.REQUEST_LEASE_SEC)).isoformat(),
        "updated_at": now.isoformat(),
    }).execute()
    return str(((resp.data or [{}])[0]).get("id") or "")


def _reclaim_stale_render_jobs() -> int:
    """워커가 죽어 진행중 상태(assets/tts/assembling)로 방치된 잡을 다시 'queued' 로 되돌린다.

    폴러는 'queued' 만 잡으므로, 워커가 중간에 취소/크래시되면 그 잡은 영원히 방치된다(orphan).
    updated_at 하트비트가 RENDER_STALE_MINUTES 보다 오래된 진행중 잡을 재큐해 다음 폴에서 재시도.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=config.RENDER_STALE_MINUTES)).isoformat()
    resp = (client().table("render_jobs")
            .update({"status": "queued", "progress": 0,
                     "error_log": "이전 워커가 응답 없어 재큐됨(watchdog)",
                     "updated_at": datetime.now(timezone.utc).isoformat()})
            # ★ config 가 정본이다. 여기 문자열을 다시 적으면 새 상태를 추가할 때 갈린다.
            #   사람 대기 상태(qa_pending·degraded)는 **일부러 빠져 있다** — 워치독이 재큐하면
            #   승인 대기 중인 잡이 queued 로 되돌아가 승인이 지워진다.
            .in_("status", list(config.RENDER_STATUS_IN_PROGRESS))
            .lt("updated_at", cutoff)
            .execute())
    n = len(resp.data or [])
    if n:
        log.warning("watchdog: 정체된 렌더 잡 %d건 재큐(>%d분)", n, config.RENDER_STALE_MINUTES)
    return n


def claim_render_jobs(limit: int = 3) -> list[dict[str, Any]]:
    """'queued' 렌더 잡을 원자적으로 잡아(→'assets') 반환. 정체 잡은 먼저 watchdog 재큐."""
    from datetime import datetime, timezone
    _reclaim_stale_render_jobs()
    resp = client().table("render_jobs").select("id, directive_id, lang").eq(
        "status", "queued"
    ).order("created_at").limit(limit).execute()
    claimed: list[dict[str, Any]] = []
    for r in resp.data or []:
        # 원자적 클레임: status 가 아직 'queued' 일 때만 'assets' 로. 동시 실행 워커의 중복 처리 방지.
        upd = (client().table("render_jobs")
               .update({"status": "assets", "progress": 5,
                        "updated_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", r["id"]).eq("status", "queued").execute())
        if upd.data:  # 이 워커가 실제로 잡음
            claimed.append(r)
    return claimed


def update_render_job(
    job_id: str, *, status: str | None = None, progress: int | None = None,
    cost_estimate: float | None = None, output_url: str | None = None,
    error_log: str | None = None, qa: dict[str, Any] | None = None, finished: bool = False,
) -> None:
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
        patch["qa"] = qa  # §7 렌더 QA 결과(jsonb) — 승인 화면 표시
    from datetime import datetime, timezone
    if finished:
        patch["finished_at"] = datetime.now(timezone.utc).isoformat()
    if patch:
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()  # 하트비트(정체 감지용)
        client().table("render_jobs").update(patch).eq("id", job_id).execute()


def get_render_asset(directive_id: str, cut_no: int, asset_type: str) -> dict[str, Any] | None:
    """멱등 캐시 조회: (directive, cut, type) 에 이미 생성된 에셋."""
    resp = client().table("render_assets").select(
        "id, asset_url, content_hash, meta"
    ).eq("directive_id", directive_id).eq("cut_no", cut_no).eq(
        "asset_type", asset_type
    ).maybe_single().execute()
    return resp.data if resp else None


def upsert_render_asset(row: dict[str, Any]) -> None:
    client().table("render_assets").upsert(
        row, on_conflict="directive_id,cut_no,asset_type"
    ).execute()


def find_active_batch_job(directive_id: str, payload_hash: str) -> dict[str, Any] | None:
    """제출 전 중복 대조(§7.3): 같은 (directive, payload_hash) 로 진행 중/완료된 잡이 있으면 재사용."""
    resp = client().table("image_batch_jobs").select(
        "id, provider_job_id, status"
    ).eq("directive_id", directive_id).eq("payload_hash", payload_hash).in_(
        "status", ["submitted", "running", "succeeded"]
    ).order("created_at", desc=True).limit(1).maybe_single().execute()
    return resp.data if resp else None


def insert_image_batch_job(row: dict[str, Any]) -> str:
    resp = client().table("image_batch_jobs").insert(row).execute()
    data = resp.data or []
    job_id = data[0]["id"] if data else ""
    log.info("image_batch_job insert: directive=%s job=%s id=%s",
             row.get("directive_id"), row.get("provider_job_id"), job_id)
    return job_id


def update_image_batch_job(job_id: str, **fields: Any) -> None:
    client().table("image_batch_jobs").update(fields).eq("id", job_id).execute()


def claim_pending_batch_jobs(limit: int = 10) -> list[dict[str, Any]]:
    """폴링 대상: submitted/running 상태 잡. render_jobs 폴러와 동일한 경량 폴링 패턴(웹훅 없음)."""
    resp = client().table("image_batch_jobs").select(
        "id, directive_id, provider_job_id, status"
    ).in_("status", ["submitted", "running"]).order("created_at").limit(limit).execute()
    return resp.data or []


def insert_generation_attempt(row: dict[str, Any]) -> None:
    """비용 원장(작업 C) 1행 삽입. 호출 시점 completed_at·price_verified_at 스탬프.

    service_role 삽입(RLS 무관). 원장 기록 실패는 호출측(cost.record)이 삼켜 렌더를 막지 않는다.

    ★ 실측 사고(2026-08-03): 이 함수만 `datetime` 지역 import 가 빠져 있어 **호출될 때마다
      NameError** 가 났다. cost.record 가 그것을 삼켜(설계상 옳다 — 원장 때문에 렌더를 죽일 수는
      없다) 로그에 경고 한 줄만 남았고, generation_attempts 는 계속 0행이었다:
        `WARNING engine: 비용 원장 기록 실패(무시): name 'datetime' is not defined`
      §8-4 가 "리포트 라인 비용이 0행"을 고쳤다고 했지만(#82) 그건 record_ledger 불린이었고,
      정작 그 뒤의 insert 가 이 한 줄 때문에 매번 죽고 있었다. import 를 모듈 최상단으로 올려
      이 계열이 다시 나지 않게 한다.
    """
    payload = dict(row)
    now = datetime.now(timezone.utc).isoformat()
    payload.setdefault("completed_at", now)
    payload.setdefault("price_verified_at", now)
    client().table("generation_attempts").insert(payload).execute()


# ─────────────────────────────────────────────────────────────
# 유튜브 업로드 (upload_requests) — docs/deviation-youtube-upload.md
# ─────────────────────────────────────────────────────────────
def get_render_job(job_id: str) -> dict[str, Any] | None:
    """업로드 워커 입력용: 렌더 mp4 URL·언어·지시서."""
    resp = client().table("render_jobs").select(
        "id, directive_id, status, output_url, lang"
    ).eq("id", job_id).maybe_single().execute()
    return resp.data if resp else None


def get_upload_meta(paper_id: str) -> dict[str, Any]:
    """업로드 제목·설명 조립용 메타. 논문 출처 + 업로드 제목(초안) + 한 줄 요약(점수).

    반환: {"paper": {...}, "upload_title_ko/en": str|None, "one_liner_ko/en": str}.
    빈 값은 호출측이 폴백(제목은 논문 제목, teaser 는 생략)한다.
    """
    paper = get_paper(paper_id) or {}
    d = client().table("drafts").select(
        "upload_title_ko, upload_title_en"
    ).eq("paper_id", paper_id).maybe_single().execute()
    draft = (d.data if d else None) or {}
    s = client().table("scores").select(
        "one_liner_ko, one_liner_en, title_ko"
    ).eq("paper_id", paper_id).maybe_single().execute()
    score = (s.data if s else None) or {}
    return {
        "paper": paper,
        "title_ko": score.get("title_ko"),
        "upload_title_ko": draft.get("upload_title_ko"),
        "upload_title_en": draft.get("upload_title_en"),
        "one_liner_ko": score.get("one_liner_ko") or "",
        "one_liner_en": score.get("one_liner_en") or "",
    }


def claim_upload_requests(limit: int = 3) -> list[dict[str, Any]]:
    """'queued' 업로드 요청을 원자적으로 잡아(→'processing') 반환.

    ★ 렌더 잡과 달리 정체(watchdog) 재큐를 하지 않는다 — 업로드는 되돌리기 어려운 외부 행위라
      재큐가 채널에 중복 영상을 만들 수 있다. 정체된 'processing' 은 사람이 수동 재시도한다.
    """
    from datetime import datetime, timezone
    resp = client().table("upload_requests").select(
        "id, render_job_id, paper_id, lang, privacy_status"
    ).eq("status", "queued").order("requested_at").limit(limit).execute()
    claimed: list[dict[str, Any]] = []
    for r in resp.data or []:
        upd = (client().table("upload_requests")
               .update({"status": "processing", "progress": 5,
                        "updated_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", r["id"]).eq("status", "queued").execute())
        if upd.data:  # 이 워커가 실제로 잡음
            claimed.append(r)
    return claimed


def update_upload_request(
    req_id: str, *, status: str | None = None, progress: int | None = None,
    youtube_video_id: str | None = None, youtube_url: str | None = None,
    error: str | None = None, finished: bool = False,
    source_factory: str | None = None, channel_id: str | None = None,
) -> None:
    """업로드 요청 행 갱신. 출처(0032)는 값이 주어질 때만 기록한다.

    논문 라인은 content_type 이 없다(리포트 소재 분류라 NULL 로 둔다 — 명세서 §3-2).
    """
    from datetime import datetime, timezone
    patch: dict[str, Any] = {}
    for col, val in (("source_factory", source_factory), ("channel_id", channel_id)):
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
        client().table("upload_requests").update(patch).eq("id", req_id).execute()


def record_youtube_publish(paper_id: str, lang: str, video_id: str, url: str) -> None:
    """published.platforms 에 유튜브 결과를 병합 기록(기존 video_url 등은 보존).

    published PK 는 paper_id 라 upsert 는 platforms 를 통째로 덮어쓴다 → 기존 행을 읽어
    platforms 를 병합한 뒤 저장한다(발행 원장에 언어별 유튜브 링크 누적).
    """
    if not paper_id:
        return
    existing = client().table("published").select(
        "final_script, platforms"
    ).eq("paper_id", paper_id).maybe_single().execute()
    row = (existing.data if existing else None) or {}
    platforms = row.get("platforms") if isinstance(row.get("platforms"), dict) else {}
    platforms = dict(platforms)
    platforms[f"youtube_{lang}"] = {"video_id": video_id, "url": url}
    client().table("published").upsert(
        {
            "paper_id": paper_id,
            "final_script": row.get("final_script") or f"[유튜브:{lang}] {url}",
            "platforms": platforms,
        },
        on_conflict="paper_id",
    ).execute()
    log.info("published 유튜브 기록: paper=%s lang=%s url=%s", paper_id, lang, url)


def upsert_youtube_analytics(rows: list[dict[str, Any]]) -> None:
    """유튜브 쇼츠 성과 스냅샷을 (video_id, snapshot_date) 기준으로 멱등 upsert.

    같은 날 재실행하면 최신 지표로 덮어쓴다(하루 여러 스냅샷 아님 — 일 단위 최신값 보관).
    engine.analytics.merge_video_metrics 가 만든 행 형식 그대로 받는다.
    """
    if not rows:
        return
    client().table("youtube_analytics").upsert(
        rows, on_conflict="video_id,snapshot_date"
    ).execute()
    log.info("youtube_analytics upsert: %d행", len(rows))


def upsert_youtube_analytics_daily(rows: list[dict[str, Any]]) -> None:
    """채널 날짜별 시계열을 (lang, day) 기준으로 멱등 upsert(일간/주간/월간 리포트용).

    engine.analytics.build_daily_rows 가 만든 행 형식 그대로 받는다. 같은 (lang, day) 재실행 시
    최신 지표로 갱신 — 지표가 확정되며 값이 바뀌어도 최신값 보관.
    """
    if not rows:
        return
    client().table("youtube_analytics_daily").upsert(
        rows, on_conflict="lang,day"
    ).execute()
    log.info("youtube_analytics_daily upsert: %d행", len(rows))


def fetch_youtube_analytics_daily(lang: str, since_day: str) -> list[dict[str, Any]]:
    """since_day(YYYY-MM-DD) 이후 날짜별 채널 지표를 오름차순으로 반환(리포트 규칙 계산 입력)."""
    resp = (client().table("youtube_analytics_daily")
            .select("*").eq("lang", lang).gte("day", since_day)
            .order("day").execute())
    return resp.data or []


def fetch_latest_video_snapshot(lang: str) -> list[dict[str, Any]]:
    """해당 언어의 가장 최근 snapshot_date 스냅샷 행들(상/하위 영상 규칙 계산 입력)."""
    latest = (client().table("youtube_analytics")
              .select("snapshot_date").eq("lang", lang)
              .order("snapshot_date", desc=True).limit(1).execute())
    if not latest.data:
        return []
    snapshot_date = latest.data[0]["snapshot_date"]
    resp = (client().table("youtube_analytics")
            .select("*").eq("lang", lang).eq("snapshot_date", snapshot_date)
            .execute())
    return resp.data or []


def upsert_performance_report(report: dict[str, Any]) -> None:
    """성과 리포트를 (period_type, period_start, lang) 기준으로 멱등 upsert.

    engine.perf_report 가 만든 행(규칙 facts + LLM 문장화 결과)을 그대로 받는다.
    """
    client().table("performance_reports").upsert(
        report, on_conflict="period_type,period_start,lang"
    ).execute()
    log.info("performance_reports upsert: %s/%s/%s",
             report.get("period_type"), report.get("period_start"), report.get("lang"))


def upload_render(local_path: str, dest_path: str, content_type: str = "video/mp4") -> str:
    """로컬 파일을 Storage 'renders' 버킷에 올리고 public URL 반환(멱등 덮어쓰기)."""
    with open(local_path, "rb") as f:
        data = f.read()
    bucket = client().storage.from_("renders")
    try:
        bucket.upload(dest_path, data, {"content-type": content_type, "upsert": "true"})
    except Exception as exc:  # noqa: BLE001 — 이미 존재 시 update 로 폴백
        log.warning("upload 실패, update 재시도: %s", exc)
        bucket.update(dest_path, data, {"content-type": content_type})
    return bucket.get_public_url(dest_path)
