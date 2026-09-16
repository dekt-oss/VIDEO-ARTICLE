"""Phase 0-A — 논문 원문 확보율 실측 (작업명세서_설명엔진_v2 §2).

최근 낙점 논문 N편에 확보 체인(arXiv → OpenAlex OA → PMC → Unpaywall)을 돌려
provider·license·content_format·char_count·source_depth·파서 실패를 기록한다.

GO 기준: full_body + partial_body ≥ 50%. 미달이면 논문 라인 설명 엔진은 보류하고
리포트 라인(Phase 5)만 진행한다.

산출물: --out 에 JSONL(본문 포함 — **저장소에 커밋하지 않는다**), --summary 에 집계 JSON.
본문은 실측 재현과 0-B/0-C 비교 입력으로만 쓰고 배포하지 않는다.

사용:
    python -m scripts.measure_paper_source --limit 100 --out <경로>.jsonl --summary <경로>.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import db, paper_source  # noqa: E402
from engine.util import log  # noqa: E402


def picked_papers(limit: int) -> list[dict]:
    """최근 낙점(picked) 논문 메타데이터. 낙점 시점 역순 — 실제 대상 분포를 그대로 본다."""
    c = db.client()
    decisions = (c.table("decisions").select("paper_id,decided_at")
                 .eq("status", "picked").order("decided_at", desc=True)
                 .limit(limit).execute().data or [])
    order = {d["paper_id"]: i for i, d in enumerate(decisions)}
    ids = list(order)
    rows: list[dict] = []
    for i in range(0, len(ids), 100):  # .in_ 는 청크로 — 긴 목록은 헤더가 넘친다
        rows += (c.table("papers")
                 .select("id,external_id,source,title,abstract,venue,url,published_date")
                 .in_("id", ids[i:i + 100]).execute().data or [])
    rows.sort(key=lambda r: order.get(r["id"], 10**6))
    return rows


def measure(papers: list[dict], workers: int = 4) -> list[dict]:
    """arXiv 는 3초 규약 때문에 순차, 나머지는 병렬. 결과는 입력 순서로 되돌린다."""
    arxiv, other = [], []
    for p in papers:
        (arxiv if paper_source.parse_arxiv_id(p.get("external_id"), p.get("url")) else other
         ).append(p)

    out: dict[str, dict] = {}
    for i, p in enumerate(arxiv, 1):
        log.info("[arXiv %d/%d] %s", i, len(arxiv), p.get("external_id"))
        out[p["id"]] = paper_source.acquire(p)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for p, packet in zip(other, ex.map(paper_source.acquire, other)):
            out[p["id"]] = packet
    return [out[p["id"]] | {"title": p.get("title"), "venue": p.get("venue"),
                            "abstract": p.get("abstract"),
                            "published_date": p.get("published_date")}
            for p in papers if p["id"] in out]


def summarize(packets: list[dict]) -> dict:
    depth = collections.Counter(p["source_depth"] for p in packets)
    provider = collections.Counter(p["provider"] for p in packets)
    fmt = collections.Counter(p["content_format"] for p in packets)
    errs = collections.Counter(e for p in packets for e in
                               (p.get("parse_error") or "").split("; ") if e)
    got = [p for p in packets if p["source_depth"] in ("full_body", "partial_body")]
    chars = sorted(p["char_count"] for p in got)
    n = len(packets)
    return {
        "n": n,
        "acquired": len(got),
        "acquire_rate": round(len(got) / n, 4) if n else 0.0,
        "go_threshold": 0.5,
        "go": bool(n and len(got) / n >= 0.5),
        "by_depth": dict(depth),
        "by_provider": dict(provider),
        "by_format": dict(fmt),
        "parse_errors": dict(errs),
        "chars_median": chars[len(chars) // 2] if chars else 0,
        "chars_mean": round(sum(chars) / len(chars)) if chars else 0,
        "truncated": sum(1 for p in packets if p.get("truncated")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", required=True, help="본문 포함 JSONL(커밋 금지)")
    ap.add_argument("--summary", required=True, help="집계 JSON")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    papers = picked_papers(args.limit)
    log.info("대상 논문 %d편", len(papers))
    packets = measure(papers, args.workers)

    with open(args.out, "w", encoding="utf-8") as f:
        for p in packets:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    summary = summarize(packets)
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
