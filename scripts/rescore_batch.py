"""최근 daily_batch 의 논문만 **다시 채점**한다(운영자 지시 2026-09-04).

왜 전체가 아닌가: `mechanism` 축(원리 제공)이 2026-09-04 에 추가됐다. 저장된 채점 3,976행은
그 축이 없지만 **등급은 그대로 유효하다** — `scoring.stored_scale` 이 옛 행을 옛 자(만점 10)로
재기 때문이다(실측: 등급이 달라지는 행 0건). 그래서 4,000건 재채점(LLM 4,000회)은 불필요하다.

다만 **새 축의 효과(원리 있는 논문이 위로 온다)는 재채점된 논문에서만** 나타난다. 그래서
지금 눈앞에서 고르는 최근 배치만 다시 채점한다.

    python -m scripts.rescore_batch                 # 최근 1개 배치
    python -m scripts.rescore_batch --batches 3     # 최근 3개 배치
    python -m scripts.rescore_batch --dry-run       # 대상만 세고 끝(비용 0)

★ 멱등: 같은 논문을 다시 돌려도 scores 를 upsert 할 뿐이다.
★ daily_batch 는 건드리지 않는다 — 순위가 바뀌는 것을 운영자가 보고 판단해야 한다.
  (배치 재생성이 필요하면 `python -m engine.score` 가 한다.)
"""

from __future__ import annotations

import argparse
import collections
import logging
import sys

from engine import db, score as score_mod, scoring

log = logging.getLogger("rescore")


def recent_batch_paper_ids(batches: int) -> list[str]:
    """최근 N개 배치일의 논문 id(중복 제거, 최신 배치 우선 순서)."""
    rows = db.client().table("daily_batch").select("batch_date,paper_id").order(
        "batch_date", desc=True).limit(1000).execute().data or []
    by_date: dict[str, list[str]] = collections.OrderedDict()
    for r in rows:
        by_date.setdefault(str(r["batch_date"]), []).append(str(r["paper_id"]))
    out: list[str] = []
    seen: set[str] = set()
    for _date, ids in list(by_date.items())[:max(1, batches)]:
        for pid in ids:
            if pid not in seen:
                seen.add(pid)
                out.append(pid)
    return out


def run(batches: int = 1, dry_run: bool = False) -> int:
    ids = recent_batch_paper_ids(batches)
    if not ids:
        log.warning("최근 배치가 비어 있다 — 재채점할 대상이 없다")
        return 0

    # ★ 논문 본문(제목·초록)이 있어야 채점할 수 있다. 배치에는 id 만 있다.
    papers = [p for p in db.fetch_papers_to_score(only_unscored=False) if p["id"] in set(ids)]
    order = {pid: i for i, pid in enumerate(ids)}
    papers.sort(key=lambda p: order.get(p["id"], 10**6))
    log.info("재채점 대상: %d편(최근 배치 %d개)", len(papers), batches)
    if dry_run:
        for p in papers[:10]:
            log.info("  %s | %s", p["id"][:8], (p.get("title") or "")[:70])
        return len(papers)

    before = {r["paper_id"]: r for r in db.fetch_scores_for_papers([p["id"] for p in papers])}
    rows = [score_mod._score_one(p) for p in papers]
    db.upsert_scores(rows)

    # ★ 무엇이 달라졌는지 **숫자로** 보고한다 — "돌렸다"가 아니라 "이렇게 바뀌었다".
    moved = collections.Counter()
    mech = collections.Counter()
    for r in rows:
        prod = r.get("production") or {}
        mech[int((prod.get("axes") or {}).get("mechanism", {}).get("score", 0))] += 1
        old = before.get(r["paper_id"]) or {}
        old_gate = ((old.get("production") or {}).get("gate")) if old else None
        if old_gate and old_gate != prod.get("gate"):
            moved[f"{old_gate}→{prod.get('gate')}"] += 1
    log.info("원리 축 분포: 2점 %d편 · 1점 %d편 · 0점 %d편",
             mech[2], mech[1], mech[0])
    log.info("게이트 변동: %s", dict(moved) or "(없음)")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="최근 배치 논문만 재채점")
    ap.add_argument("--batches", type=int, default=1, help="최근 배치 며칠치(기본 1)")
    ap.add_argument("--dry-run", action="store_true", help="대상만 세고 끝(API 호출 없음)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = run(batches=a.batches, dry_run=a.dry_run)
    log.info("=== 재채점 %s: %d편 ===", "대상 확인" if a.dry_run else "완료", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
