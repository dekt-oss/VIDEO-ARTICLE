"""주류 공장 - 비슷한 열린 후보를 하나로 합치기(2026-11-06). 운영자: "소재수집에서 비슷한 중복내용이 너무 많아. 통합해서 하나로"

    python -m scripts.drinks_merge_candidates                          # 미리보기(기본, 아무것도 안 쓴다)
    python -m scripts.drinks_merge_candidates --out merge-preview.md   # 미리보기를 마크다운 파일로도 남긴다
    python -m scripts.drinks_merge_candidates --apply --yes            # 실제로 합친다(되돌리는 동작이 없다)

읽기·쓰기 모두 SUPABASE_URL·SUPABASE_SERVICE_KEY 가 필요하다(키는 출력하지 않는다).
묶는 기준은 수집 때와 같은 engine.drinks_discover.same_question(열린 'suggested' 후보의 대표 질문끼리, 같은 칸 안에서만).
남길 후보: 자료가 가장 많은 것 → 임시 점수가 높은 것 → 먼저 만든 것.
합치기는 대시보드 [병합] 과 같은 DB 함수(drinks_candidate_action 'merge')로 한다 — 자료가 남길 후보로 옮겨지고
합쳐진 후보는 'merged' 가 된다. **되돌리는 동작(unmerge)은 없다** — 그래서 --apply 는 --yes 를 함께 줘야 돈다.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import Any, Callable, Optional

from engine import drinks_discover as dd

Rpc = Callable[[str, dict[str, Any]], Any]

MERGE_REASON = "비슷한 질문 묶기(2026-11-06, scripts/drinks_merge_candidates.py)"


def read_candidates() -> list[dict[str, Any]]:
    """열린 후보 + 후보별 자료 수. 둘 다 db.select_all 로 끝까지 읽는다 — 1,000행 잘림 방지."""
    from engine import db
    cands = db.select_all("drink_discovery_candidates", "id,key_question,version,status,provisional_score,created_at",
                          key=("id",), where=lambda q: q.eq("status", "suggested"))
    links = db.select_all("drink_candidate_items", "item_id,candidate_id", key=("item_id",))
    counts = Counter(r["candidate_id"] for r in links)
    for c in cands:
        c["items"] = counts.get(c["id"], 0)
    return cands


def _rank(c: dict[str, Any]) -> tuple:
    score = c.get("provisional_score")
    return (-(c.get("items") or 0), -(float(score) if score is not None else -1.0), c.get("created_at") or "", c["id"])


def group_candidates(cands: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """같은 질문끼리 묶는다(묶음 안 누구와든 같으면 들어간다). 각 묶음은 남길 후보가 맨 앞이다. 혼자인 후보도 묶음 하나."""
    groups: list[list[dict[str, Any]]] = []
    for c in sorted((c for c in cands if c.get("status") in (None, "suggested")), key=_rank):
        q = c.get("key_question") or ""
        g = next((g for g in groups if any(dd.same_question(q, o.get("key_question") or "") for o in g)), None)
        if g is None:
            groups.append([c])
        else:
            g.append(c)
    for g in groups:
        g.sort(key=_rank)
    return groups


def apply_merge(rpc: Rpc, groups: list[list[dict[str, Any]]]) -> dict[str, Any]:
    from engine.drinks_collect import DbError

    done, failed = [], []
    for g in groups:
        survivor = g[0]
        for c in g[1:]:
            try:
                rpc("drinks_candidate_action", {"candidate_id": c["id"], "expected_version": c["version"], "action": "merge",
                                                "into_candidate_id": survivor["id"], "reason": MERGE_REASON})
                done.append(c["id"])
            except DbError as exc:
                failed.append((c["id"], exc.message or exc.code))
    return {"merged": done, "failed": failed}


def _cell_label(q: str) -> str:
    card = dd.cell_card(dd.question_cell(q))
    return f"{card['category_ko'] or '주종 미상'} · {card['kind_ko'] or '유형 미상'}"


def render(groups: list[list[dict[str, Any]]], total: int, applied: Optional[dict[str, Any]] = None) -> str:
    multi = [g for g in groups if len(g) > 1]
    losers = sum(len(g) - 1 for g in multi)
    head = "적용 결과" if applied else "미리보기(아무것도 쓰지 않았습니다)"
    lines = [f"# 비슷한 후보 합치기 — {head}", "",
             f"- 열린 후보 {total}건 · 합칠 묶음 {len(multi)}개 · 합쳐질 후보 {losers}건 · 합친 뒤 {total - losers}건", "",
             "★ = 남길 후보(자료 수 → 임시 점수 → 먼저 만든 것). 나머지는 ★ 로 자료가 옮겨지고 '병합됨'이 됩니다.", ""]
    for i, g in enumerate(sorted(multi, key=len, reverse=True), 1):
        lines.append(f"## {i}. {_cell_label(g[0].get('key_question') or '')} — {len(g)}건")
        for j, c in enumerate(g):
            score = c.get("provisional_score")
            lines.append(f"- {'★' if j == 0 else '·'} {(c.get('key_question') or '')[:80]}"
                         f"  (자료 {c.get('items') or 0} · 점수 {score if score is not None else '-'} · `{c['id'][:8]}`)")
        lines.append("")
    if not multi:
        lines.append("합칠 묶음이 없습니다.")
    if applied:
        lines.append(f"병합 {len(applied['merged'])}건, 실패 {len(applied['failed'])}건")
        lines += [f"- ! `{cid}`: {msg}" for cid, msg in applied["failed"]]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None, rpc: Optional[Rpc] = None, candidates: Optional[list[dict[str, Any]]] = None) -> int:
    ap = argparse.ArgumentParser(description="비슷한 열린 후보를 하나로 합친다(기본은 미리보기)")
    ap.add_argument("--out", help="미리보기·결과를 이 경로에 마크다운으로도 쓴다")
    ap.add_argument("--apply", action="store_true", help="실제로 합친다(되돌리는 동작 없음) — --yes 도 함께 줘야 한다")
    ap.add_argument("--yes", action="store_true", help="--apply 확인")
    args = ap.parse_args(argv)
    if args.apply and not args.yes:
        print("--apply 는 되돌릴 수 없습니다. 미리보기를 확인한 뒤 --apply --yes 로 다시 실행하세요.", file=sys.stderr)
        return 2
    live_env = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))
    if candidates is None:
        if not live_env:
            print("후보 조회에는 SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다(읽기 전용 미리보기도 마찬가지).", file=sys.stderr)
            return 2
        candidates = read_candidates()
    if args.apply and rpc is None:
        if not live_env:
            print("--apply 는 SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다.", file=sys.stderr)
            return 2
        from engine.drinks_collect import supabase_rpc
        rpc = supabase_rpc()
    groups = group_candidates(candidates)
    applied = apply_merge(rpc, groups) if args.apply else None
    text = render(groups, len(candidates), applied)
    print(text, end="")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    return 1 if applied and applied["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
