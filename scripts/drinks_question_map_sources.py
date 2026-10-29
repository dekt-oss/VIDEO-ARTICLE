"""주류 공장 - 질문 지도 수집원 교체(2026-10-29). docs/deviation-drinks-discovery.md "질문 지도로 수집"

    python -m scripts.drinks_question_map_sources                      # 미리보기(기본, 아무것도 안 쓴다)
    python -m scripts.drinks_question_map_sources --apply              # 옛 네이버 발견 수집원 종료 + 새 6개 등록 + 검증 실행 요청
    python -m scripts.drinks_question_map_sources --activate           # 검증이 성공한 질문 지도 수집원 활성화 계획 미리보기
    python -m scripts.drinks_question_map_sources --activate --apply   # 이용 조건 확인 표시 + 검증 완료 + 활성화 + 첫 수집 요청

순서: ① --apply  ② 검증 실행이 끝나길 기다린다(drinks-collect 워크플로가 큐를 처리한다)  ③ --activate --apply.
수집원 6개 = 주종 3 × 둘로 나눈 질문 유형(4칸 × 검색어 2개 = 8개, 수집원당 10개 상한 아래). 검색어 정본은 config.DRINKS_QUESTION_MAP.

대시보드 [검증 실행]·[검증 완료로 표시]·[활성화]·[종료] 가 부르는 것과 같은 DB 함수(drinks_register_discovery_source·
drinks_request_run·drinks_source_action)로 한다 - 새 경로가 아니다. 키는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from typing import Any, Callable, Optional

from engine import config

Rpc = Callable[[str, dict[str, Any]], Any]

RETIRE_REASON = "질문 지도로 교체(2026-10-29)"
TERMS_NOTE = ("네이버 검색 API(API HUB) — 검색 결과 제목·요약·링크만 저장, 회원 전용 본문 수집 안 함. "
              "운영자 위임 확인(2026-10-29)")
TERMS_URL = "https://api.ncloud-docs.com/docs/ai-naver-search"
LIVE_STATES = ("proposed", "validated", "active", "paused")
# 수집원 이름에 쓰는 짧은 질문 유형 이름(화면 목록에서 한눈에 구별되게)
SHORT_KIND = {"storage": "보관", "selection": "고르기", "difference": "차이", "howto": "마시는 법",
              "pairing": "음식 궁합", "label": "라벨", "misconception": "오해", "making": "만드는 법"}


def plan_sources() -> list[dict[str, Any]]:
    """질문 지도 수집원 6개의 등록 입력. 주종마다 질문 유형 4칸씩 둘로 나눈다."""
    out: list[dict[str, Any]] = []
    for cat, cat_ko in config.DRINKS_CATEGORY_KO.items():
        for n, kinds in enumerate(config.DRINKS_QUESTION_MAP_SPLIT, 1):
            cells = [c for c in config.DRINKS_QUESTION_MAP if c[0] == cat and c[1] in kinds]
            queries = [q for c in cells for q in c[3]]
            label = "·".join(SHORT_KIND.get(c[1], c[2]) for c in cells)
            out.append({"platform": "naver", "name": f"{config.DRINKS_QUESTION_MAP_SOURCE_PREFIX} — {cat_ko} {n}({label})",
                        "categories": [cat], "language": "ko", "queries": queries,
                        "max_items_per_run": 100, "request_interval_sec": 3})
    return out


class Store:
    """수집원·검증 실행 조회(읽기). 쓰기는 모두 rpc 로 한다."""

    def sources(self) -> list[dict[str, Any]]:
        from engine import db
        return db.select_all("drink_sources", "id,name,state,platform,purpose,version,terms_status",
                             key=("id",), where=lambda q: q.eq("purpose", "discovery"))

    def validation_status(self, source_id: str) -> Optional[str]:
        """가장 최근에 끝난 검증 실행의 상태(없으면 None). 활성화 트리거가 보는 것과 같은 기준."""
        from engine import db
        rows = (db.client().table("drink_collection_runs").select("status,finished_at").eq("source_id", source_id).eq("mode", "validate")
                .not_.in_("status", ["queued", "running"]).order("finished_at", desc=True).limit(1).execute().data or [])
        return rows[0]["status"] if rows else None


def to_retire(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """질문 지도로 바꿀 옛 네이버 발견 수집원(이름이 머리말로 시작하지 않고, 아직 종료하지 않은 것)."""
    return [s for s in existing if s.get("platform") == "naver" and s.get("state") in LIVE_STATES
            and not str(s.get("name") or "").startswith(config.DRINKS_QUESTION_MAP_SOURCE_PREFIX)]


def map_sources(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in existing if s.get("platform") == "naver" and s.get("state") in LIVE_STATES
            and str(s.get("name") or "").startswith(config.DRINKS_QUESTION_MAP_SOURCE_PREFIX)]


def apply_replace(rpc: Rpc, existing: list[dict[str, Any]], planned: list[dict[str, Any]]) -> dict[str, list]:
    from engine.drinks_collect import DbError

    res: dict[str, list] = {"retired": [], "registered": [], "kept": [], "validate_requested": [], "failed": []}
    for s in to_retire(existing):
        try:
            rpc("drinks_source_action", {"source_id": s["id"], "expected_version": s["version"], "action": "retire", "reason": RETIRE_REASON})
            res["retired"].append(s["name"])
        except DbError as exc:
            res["failed"].append((f"종료 {s['name']}", exc.message or exc.code))
    have = {s["name"]: s for s in existing if s.get("state") != "retired"}
    for p in planned:
        if p["name"] in have:
            res["kept"].append(p["name"])
            sid = have[p["name"]]["id"]
        else:
            try:
                sid = (rpc("drinks_register_discovery_source", p) or {}).get("source_id")
                res["registered"].append(p["name"])
            except DbError as exc:
                res["failed"].append((f"등록 {p['name']}", exc.message or exc.code))
                continue
        if have.get(p["name"], {}).get("state") == "active" or not sid:
            continue
        try:
            rpc("drinks_request_run", {"source_id": sid, "mode": "validate"})
            res["validate_requested"].append(p["name"])
        except DbError as exc:
            res["failed"].append((f"검증 요청 {p['name']}", exc.message or exc.code))
    return res


def apply_activate(rpc: Rpc, store: Any, today: Optional[date] = None) -> dict[str, list]:
    """검증 실행이 성공한 질문 지도 수집원만: 이용 조건 확인 표시 → 검증 완료 → 활성화 → 첫 수집 요청. 다시 읽어 version 을 맞춘다."""
    from engine.drinks_collect import DbError

    from engine.util import today_local

    today = today or today_local()
    res: dict[str, list] = {"activated": [], "waiting": [], "failed": []}

    def fresh(sid: str) -> dict[str, Any]:
        return next(s for s in store.sources() if s["id"] == sid)

    for s in map_sources(store.sources()):
        if s["state"] == "active":
            continue
        if store.validation_status(s["id"]) != "succeeded":
            res["waiting"].append(s["name"])
            continue
        try:
            cur = s
            if cur["terms_status"] != "verified":
                rpc("drinks_source_action", {"source_id": s["id"], "expected_version": cur["version"], "action": "update_terms",
                                             "terms_status": "verified", "terms_note": TERMS_NOTE, "terms_url": TERMS_URL,
                                             "terms_checked_at": today.isoformat()})
                cur = fresh(s["id"])
            if cur["state"] == "proposed":
                rpc("drinks_source_action", {"source_id": s["id"], "expected_version": cur["version"], "action": "validate",
                                             "reason": "질문 지도 검증 실행 성공(2026-10-29)"})
                cur = fresh(s["id"])
            rpc("drinks_source_action", {"source_id": s["id"], "expected_version": cur["version"], "action": "activate",
                                         "reason": "질문 지도 수집 시작(2026-10-29)"})
            rpc("drinks_request_run", {"source_id": s["id"], "mode": "collect"})
            res["activated"].append(s["name"])
        except DbError as exc:
            res["failed"].append((s["name"], exc.message or exc.code))
    return res


def _lines(title: str, rows: list) -> list[str]:
    return [f"{title} {len(rows)}건"] + [f"  - {r if isinstance(r, str) else ' — '.join(map(str, r))}" for r in rows]


def main(argv: Optional[list[str]] = None, rpc: Optional[Rpc] = None, store: Any = None) -> int:
    ap = argparse.ArgumentParser(description="질문 지도 수집원으로 교체(기본은 미리보기)")
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다 - SUPABASE_URL·SUPABASE_SERVICE_KEY 필요")
    ap.add_argument("--activate", action="store_true", help="검증이 성공한 질문 지도 수집원을 활성화한다(--apply 가 있어야 쓴다)")
    args = ap.parse_args(argv)
    planned = plan_sources()
    live_env = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))
    if args.apply and rpc is None and not live_env:
        print("--apply 는 SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다.", file=sys.stderr)
        return 2
    if rpc is None and live_env:
        from engine.drinks_collect import supabase_rpc
        rpc = supabase_rpc()
    if store is None and (live_env or rpc is not None):
        store = Store()
    existing: Optional[list[dict[str, Any]]] = None
    if store is not None:
        existing = store.sources()
    out: list[str] = []
    if args.activate:
        if store is None:
            print("--activate 는 수집원 조회에 SUPABASE_URL·SUPABASE_SERVICE_KEY 가 필요합니다.", file=sys.stderr)
            return 2
        mine = map_sources(existing or [])
        ready = [s["name"] for s in mine if s["state"] != "active" and store.validation_status(s["id"]) == "succeeded"]
        out += _lines("활성화 대상(검증 성공)", ready)
        out += _lines("검증 대기·실패", [s["name"] for s in mine if s["state"] != "active" and s["name"] not in ready])
        if args.apply:
            r = apply_activate(rpc, store)
            out += ["", "적용 결과"] + _lines("활성화", r["activated"]) + _lines("검증 대기", r["waiting"]) + _lines("실패", r["failed"])
            print("\n".join(out))
            return 1 if r["failed"] else 0
    else:
        out.append("질문 지도 수집원 계획(검색어 8개씩, 수집원당 10개 상한 아래)")
        out += [f"  - {p['name']}: {len(p['queries'])}개 — {' / '.join(p['queries'])}" for p in planned]
        if existing is None:
            out.append("기존 수집원은 확인하지 못했습니다(SUPABASE 환경변수 없음) - 종료할 옛 수집원은 --apply 때 조회합니다.")
        else:
            out += _lines("종료할 옛 네이버 발견 수집원", [s["name"] for s in to_retire(existing)])
            have = {s["name"] for s in existing if s.get("state") != "retired"}
            out += _lines("이미 있어 건너뛸 수집원", [p["name"] for p in planned if p["name"] in have])
        if args.apply:
            r = apply_replace(rpc, existing or [], planned)
            out += ["", "적용 결과"] + _lines("종료", r["retired"]) + _lines("등록", r["registered"]) + _lines("이미 있음", r["kept"]) \
                + _lines("검증 실행 요청", r["validate_requested"]) + _lines("실패", r["failed"])
            out.append("검증 실행은 drinks-collect 워크플로(또는 대시보드 [지금 수집] 깨우기)가 처리합니다. 끝나면 --activate --apply.")
            print("\n".join(out))
            return 1 if r["failed"] else 0
    if not args.apply:
        out.append("\n(미리보기입니다 - 아무것도 쓰지 않았습니다. 실제로 하려면 --apply)")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
