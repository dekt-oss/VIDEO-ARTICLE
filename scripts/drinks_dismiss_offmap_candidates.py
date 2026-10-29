"""주류 공장 - 질문 지도 기준에 안 맞는 열린 후보 일괄 기각(2026-10-29). docs/deviation-drinks-discovery.md "질문 지도로 수집"

    python -m scripts.drinks_dismiss_offmap_candidates                 # 미리보기(기본, 아무것도 안 쓴다)
    python -m scripts.drinks_dismiss_offmap_candidates --jev           # + Jev 판정도 해서 걸러낸다(건당 1센트 미만, 호출 상한 있음)
    python -m scripts.drinks_dismiss_offmap_candidates --apply         # 실제로 기각한다 - SUPABASE_URL·SUPABASE_SERVICE_KEY 필요

기각 기준(열린 'suggested' 후보의 대표 질문): ① 질문 문장에 술 낱말이 없다 ② 길이 상한(config.DRINKS_QUESTION_MAX_CHARS)을 넘는다
③ --jev 일 때 Jev 가 '시청자가 궁금해할 술 질문'으로 보지 않는다(config.DRINKS_DISCOVERY_JEV_MIN_P 미만).
대시보드 [기각] 이 부르는 것과 같은 DB 함수(drinks_candidate_action 'dismiss')로 한다. 기각은 되돌릴 수 있다(reopen). 키는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable, Optional

from engine import config
from engine import drinks_discover as dd

Rpc = Callable[[str, dict[str, Any]], Any]

DISMISS_REASON = "질문 지도 기준 미달(2026-10-29)"
NO_TERM, TOO_LONG, JEV_LOW = "술 낱말 없음", "질문이 너무 김", "Jev 기각"


def read_candidates() -> list[dict[str, Any]]:
    from engine import db
    return db.select_all("drink_discovery_candidates", "id,key_question,version,status", key=("id",),
                         where=lambda q: q.eq("status", "suggested"))


def why_offmap(key_question: str) -> Optional[str]:
    """규칙으로 보는 미달 사유. 통과면 None."""
    q = " ".join((key_question or "").split())
    if len(q) > dd.question_max_chars(q):
        return TOO_LONG
    if not dd.question_ok(q):
        return NO_TERM
    return None


def select_offmap(cands: list[dict[str, Any]], jev: bool = False) -> list[tuple[dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], str]] = []
    judge = dd.JevJudge() if jev else None
    for c in cands:
        if c.get("status") not in (None, "suggested"):
            continue
        why = why_offmap(c.get("key_question") or "")
        if why is None and judge is not None:
            status, _p = judge.verdict(c["key_question"])
            if status == "rejected":
                why = JEV_LOW
        if why:
            out.append((c, why))
    return out


def apply_dismiss(rpc: Rpc, picked: list[tuple[dict[str, Any], str]]) -> dict[str, Any]:
    from engine.drinks_collect import DbError

    done, failed = [], []
    for c, why in picked:
        try:
            rpc("drinks_candidate_action", {"candidate_id": c["id"], "expected_version": c["version"], "action": "dismiss",
                                            "reason": f"{DISMISS_REASON} — {why}"})
            done.append(c["id"])
        except DbError as exc:
            failed.append((c["id"], exc.message or exc.code))
    return {"dismissed": done, "failed": failed}


def render(picked: list[tuple[dict[str, Any], str]], total: int, applied: Optional[dict[str, Any]] = None) -> str:
    by: dict[str, int] = {}
    for _c, why in picked:
        by[why] = by.get(why, 0) + 1
    head = "적용 결과" if applied else "미리보기(아무것도 쓰지 않았습니다)"
    lines = [f"{head}: 열린 후보 {total}건 중 기준 미달 {len(picked)}건 — " + (" · ".join(f"{k} {v}" for k, v in by.items()) or "없음")]
    lines += [f"  - [{why}] {(c.get('key_question') or '')[:60]}" for c, why in picked]
    if applied:
        lines.append(f"기각 {len(applied['dismissed'])}건, 실패 {len(applied['failed'])}건")
        lines += [f"  ! {cid}: {msg}" for cid, msg in applied["failed"]]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None, rpc: Optional[Rpc] = None, candidates: Optional[list[dict[str, Any]]] = None) -> int:
    ap = argparse.ArgumentParser(description="질문 지도 기준에 안 맞는 열린 후보를 기각(기본은 미리보기)")
    ap.add_argument("--apply", action="store_true", help="실제로 기각한다 - SUPABASE_URL·SUPABASE_SERVICE_KEY 필요")
    ap.add_argument("--jev", action="store_true", help="Jev 판정도 한다(JEV_ENABLED·JEV_API_KEY 필요, 꺼져 있으면 규칙만)")
    args = ap.parse_args(argv)
    live_env = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))
    if candidates is None:
        if not live_env:
            print("후보 조회에는 SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다.", file=sys.stderr)
            return 2
        candidates = read_candidates()
    if args.apply and rpc is None:
        if not live_env:
            print("--apply 는 SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다.", file=sys.stderr)
            return 2
        from engine.drinks_collect import supabase_rpc
        rpc = supabase_rpc()
    if args.jev and not dd.decide.enabled():
        print("Jev 가 꺼져 있습니다(JEV_ENABLED·JEV_API_KEY 없음) - 규칙으로만 가립니다.", file=sys.stderr)
    picked = select_offmap(candidates, jev=args.jev)
    if not args.apply:
        print(render(picked, len(candidates)))
        return 0
    res = apply_dismiss(rpc, picked)
    print(render(picked, len(candidates), res))
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
