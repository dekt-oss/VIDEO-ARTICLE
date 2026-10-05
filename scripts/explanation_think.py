"""Phase 3 "생각하는 단계" 미리보기 — 콘텐츠 한 편의 설명 설계를 만들어 보여 준다(대본·지시서는 만들지 않는다).

    python -m scripts.explanation_think paper <논문 id>
    python -m scripts.explanation_think report <리포트 id>

DB 는 읽기만 한다. 모델 1회 호출(비용 장부 `generation_attempts` 에 기록). 결과는 artifacts/explanation-v2-think/ 에
.json·.md 로 남는다(gitignore). 운영자가 이 결과를 보고 "원한 설명 흐름"인지 판정한 뒤에만 대본 단계에 잇는다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import db, evidence_pack, explanation_reasoning, report_db  # noqa: E402
from scripts.compare_explanation_v2 import canonical_content_id, count_ledger_writes  # noqa: E402


def _paper_title(paper_id: str) -> str:
    rows = db.client().table("scores").select("title_ko").eq("paper_id", paper_id).limit(1).execute().data
    title_ko = (rows[0].get("title_ko") if rows else "") or ""
    paper = db.client().table("papers").select("title").eq("id", paper_id).limit(1).execute().data
    title = (paper[0].get("title") if paper else "") or ""
    return f"{title_ko} ({title})" if title_ko and title else (title_ko or title)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3 생각 결과 미리보기(대본·지시서 없음)")
    parser.add_argument("domain", choices=("paper", "report"))
    parser.add_argument("content_id")
    parser.add_argument("--model", default=None)
    parser.add_argument("--output-dir", default="artifacts/explanation-v2-think")
    args = parser.parse_args(argv)

    content_id = canonical_content_id(args.content_id)
    if args.domain == "paper":
        draft = db.get_draft_full(content_id)
        report_meta, financial_reasoning, title = None, None, _paper_title(content_id)
    else:
        draft = report_db.get_report_draft(content_id)
        report_meta = report_db.get_report(content_id) or {}
        financial_reasoning = (draft or {}).get("financial_reasoning")
        title = f"{report_meta.get('broker') or ''} · {report_meta.get('title') or ''}"
    if not draft:
        raise SystemExit(f"draft_not_found:{args.domain}:{content_id}")
    pack = evidence_pack.build(draft.get("fact_sheet"), args.domain, content_id=content_id,
                               financial_reasoning=financial_reasoning)
    with count_ledger_writes() as writes:
        out = explanation_reasoning.think(pack, title=title, financial_reasoning=financial_reasoning,
                                          report_meta=report_meta, model=args.model)
    out["title"] = title
    out["side_effects"] = {"database_writes": dict(writes), "directive_inserts": 0}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / f"{args.domain}-{content_id}-think-{stamp}"
    stem.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    stem.with_suffix(".md").write_text(explanation_reasoning.markdown(
        out, title=title, evidence=explanation_reasoning.evidence_index(pack, financial_reasoning)), encoding="utf-8")
    print(json.dumps({"markdown": str(stem.with_suffix(".md")), "errors": out["qa"]["errors"],
                      "ledger_writes": dict(writes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
