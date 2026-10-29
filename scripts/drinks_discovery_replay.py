"""주류 발견 - 저장된 자료에 새 잡음 규칙을 대 본다(읽기 전용, 0원). 2026-10-29. docs/deviation-drinks-discovery.md

    python -m scripts.drinks_discovery_replay <source_id>

그 수집원이 이미 저장한 drink_discovery_items 를 읽어 `drinks_discover.is_relevant` 로 가려 본다.
아무것도 쓰지 않고 키도 찍지 않는다. 실행 환경에 SUPABASE_URL·SUPABASE_SERVICE_KEY 가 있어야 한다.
"""

from __future__ import annotations

import argparse
import sys

from engine import db
from engine import drinks_discover as dd

SHOW = 15
WIDTH = 60


def _cut(s: str | None) -> str:
    t = (s or "(제목 없음)").replace("\n", " ")
    return t if len(t) <= WIDTH else t[: WIDTH - 1] + "…"


def replay(rows: list[dict]) -> dict:
    kept = [r for r in rows if dd.is_relevant(r.get("title"), r.get("summary"))]
    dropped = [r for r in rows if r not in kept]
    storage_before = sum(1 for r in rows if "storage" in (r.get("signals") or []))
    storage_after = sum(
        1 for r in kept
        if "storage" in dd.extract_signals(" ".join(x for x in [r.get("title"), r.get("summary"), *(r.get("questions") or [])] if x)))
    return {"total": len(rows), "kept": kept, "dropped": dropped, "storage_before": storage_before, "storage_after": storage_after}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source_id")
    args = ap.parse_args(argv)
    rows = db.select_all("drink_discovery_items", "id,title,summary,signals,questions", key=("id",),
                         where=lambda q: q.eq("source_id", args.source_id))
    r = replay(rows)
    print(f"수집원 {args.source_id} — 저장 {r['total']}건")
    print(f"  새 규칙으로 남길 것 {len(r['kept'])}건 / 거를 것 {len(r['dropped'])}건")
    print(f"  보관(storage) 신호: 저장된 값 {r['storage_before']}건 -> 좁힌 뒤(남긴 것 기준) {r['storage_after']}건")
    print(f"\n[남길 것 — 최대 {SHOW}건]")
    for x in r["kept"][:SHOW]:
        print("  +", _cut(x.get("title")))
    print(f"\n[거를 것 — 최대 {SHOW}건]")
    for x in r["dropped"][:SHOW]:
        print("  -", _cut(x.get("title")))
    print("\n(읽기 전용 — 저장된 자료·후보는 바뀌지 않았습니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
