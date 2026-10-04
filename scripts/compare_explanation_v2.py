"""Create a local, read-only Phase 11 comparison for one exact content id."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import db, explanation_shadow_pipeline, report_db


def latest_directive(client: Any, domain: str, content_id: str) -> dict[str, Any]:
    if not str(content_id).strip():
        raise ValueError("content_id_required")
    if domain == "paper":
        table, id_field = "directives", "paper_id"
    elif domain == "report":
        table, id_field = "report_directives", "report_id"
    else:
        raise ValueError(f"domain_invalid:{domain}")
    response = (
        client.table(table)
        .select(f"id, {id_field}, version_type, header, cuts, status, created_at")
        .eq(id_field, content_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else {}


def _load(domain: str, content_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    draft = (
        db.get_draft_full(content_id)
        if domain == "paper"
        else report_db.get_report_draft(content_id)
    )
    if not draft:
        raise ValueError(f"draft_not_found:{domain}:{content_id}")
    directive = latest_directive(db.client(), domain, content_id)
    return draft, directive


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="정확한 콘텐츠 ID 한 건을 읽어 V2 Shadow 전후 비교를 로컬에 저장합니다."
    )
    parser.add_argument("domain", choices=("paper", "report"))
    parser.add_argument("content_id")
    parser.add_argument("--with-model", action="store_true")
    parser.add_argument("--output-dir", default="artifacts/explanation-v2-phase11")
    args = parser.parse_args(argv)

    draft, directive = _load(args.domain, args.content_id)
    result = explanation_shadow_pipeline.run(
        domain=args.domain,
        content_id=args.content_id,
        fact_sheet=draft.get("fact_sheet"),
        financial_reasoning=draft.get("financial_reasoning"),
        legacy_draft=draft,
        legacy_directive=directive,
        allow_model_calls=args.with_model,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.domain}-{args.content_id}.json"
    md_path = output_dir / f"{args.domain}-{args.content_id}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(explanation_shadow_pipeline.render_markdown(result), encoding="utf-8")
    print(json.dumps({
        "run_status": result["run_status"],
        "json": str(json_path),
        "markdown": str(md_path),
        "database_writes": 0,
        "render_calls": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
