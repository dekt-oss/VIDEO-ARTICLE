"""Read-only Phase 0 audit runner for Explanation Engine v2.

Usage:
    python -m scripts.explanation_quality_audit
    python -m scripts.explanation_quality_audit --case heel-strike-2026-09
    python -m scripts.explanation_quality_audit --json

No API or database calls are made. The default input is the checked-in,
hand-audited gold set.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.explanation_quality import load_gold_set, markdown_report, summarize  # noqa: E402


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_GOLD_SET = ROOT / "tests" / "fixtures" / "explanation_quality_gold_set.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Explanation Engine v2 Phase 0 gold-set audit")
    parser.add_argument("--gold-set", default=str(DEFAULT_GOLD_SET))
    parser.add_argument("--case", default="", help="case_id 하나만 출력")
    parser.add_argument("--json", action="store_true", help="요약을 JSON으로 출력")
    args = parser.parse_args()

    cases = load_gold_set(args.gold_set)
    if args.case:
        cases = [case for case in cases if case["case_id"] == args.case]
        if not cases:
            raise SystemExit(f"unknown case_id: {args.case}")

    if args.json:
        print(json.dumps(summarize(cases), ensure_ascii=False, indent=2))
    else:
        print(markdown_report(cases), end="")


if __name__ == "__main__":
    main()
