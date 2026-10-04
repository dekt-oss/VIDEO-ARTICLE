"""Create a local, read-only Phase 11 comparison for one exact content id.

Database boundary: Production rows are only SELECTed. The one write this script can
cause is the cost ledger (`generation_attempts`) that `engine.llm` records for every
real model call under `--with-model` — it is counted and reported, not hidden.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import db, explanation_shadow_pipeline, report_db

_DIRECTIVE_TABLES = {
    "paper": ("directives", "paper_id"),
    "report": ("report_directives", "report_id"),
}


def canonical_content_id(content_id: str) -> str:
    """Production content ids are UUIDs; anything else is refused before any DB access."""
    text = str(content_id or "").strip()
    if not text:
        raise ValueError("content_id_required")
    try:
        return str(uuid.UUID(text))
    except ValueError:
        raise ValueError(f"content_id_not_uuid:{text[:80]}") from None


def _directive_table(domain: str) -> tuple[str, str]:
    if domain not in _DIRECTIVE_TABLES:
        raise ValueError(f"domain_invalid:{domain}")
    return _DIRECTIVE_TABLES[domain]


def latest_directive(client: Any, domain: str, content_id: str) -> dict[str, Any]:
    if not str(content_id).strip():
        raise ValueError("content_id_required")
    table, id_field = _directive_table(domain)
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


def exact_directive(client: Any, domain: str, content_id: str,
                    directive_id: str) -> dict[str, Any]:
    """운영자가 지정한 지시서 1건. 다른 콘텐츠의 지시서면 거절한다."""
    table, id_field = _directive_table(domain)
    response = (
        client.table(table)
        .select(f"id, {id_field}, version_type, header, cuts, status, created_at")
        .eq("id", directive_id)
        .eq(id_field, content_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError(f"directive_not_found_for_content:{directive_id}")
    return rows[0]


def _load(domain: str, content_id: str,
          directive_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    draft = (
        db.get_draft_full(content_id)
        if domain == "paper"
        else report_db.get_report_draft(content_id)
    )
    if not draft:
        raise ValueError(f"draft_not_found:{domain}:{content_id}")
    if directive_id:
        directive = exact_directive(db.client(), domain, content_id, directive_id)
        return draft, directive, "운영자가 지정한 지시서(--directive-id)"
    directive = latest_directive(db.client(), domain, content_id)
    return draft, directive, "이 콘텐츠의 가장 최근 지시서(version_type·상태 무관)"


def _load_concepts(path: str | None) -> list[dict[str, Any]] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("concepts_file_not_list")
    return data


@contextmanager
def count_ledger_writes() -> Iterator[dict[str, int]]:
    """`db.insert_generation_attempt` 가 실제로 성공한 횟수를 센다(실패는 세지 않는다)."""
    counts = {"generation_attempts": 0}
    original = db.insert_generation_attempt

    def counted(row: dict[str, Any]) -> None:
        original(row)
        counts["generation_attempts"] += 1

    db.insert_generation_attempt = counted
    try:
        yield counts
    finally:
        db.insert_generation_attempt = original


def _output_paths(output_dir: Path, domain: str, content_id: str,
                  with_model: bool) -> tuple[Path, Path]:
    """실행마다 새 파일 — 유료 실행 결과를 다음 실행이 덮어쓰지 않게 한다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "model" if with_model else "dry"
    for attempt in range(1000):
        suffix = f"-{attempt}" if attempt else ""
        stem = f"{domain}-{content_id}-{mode}-{stamp}{suffix}"
        json_path, md_path = output_dir / f"{stem}.json", output_dir / f"{stem}.md"
        if not json_path.exists() and not md_path.exists():
            return json_path, md_path
    raise RuntimeError("output_path_exhausted")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="정확한 콘텐츠 ID 한 건을 읽어 V2 Shadow 비교 자료를 로컬에 저장합니다."
    )
    parser.add_argument("domain", choices=("paper", "report"))
    parser.add_argument("content_id")
    parser.add_argument("--with-model", action="store_true")
    parser.add_argument("--directive-id", default=None,
                        help="비교할 Production 지시서 id(이 콘텐츠의 것만 허용)")
    parser.add_argument("--concepts-file", default=None,
                        help="Phase 4 선행 개념 명시 요청 JSON 목록")
    parser.add_argument("--override-series-split", default="", metavar="REASON",
                        help="Phase 8 series_split 명시적 override 사유(비우면 override 없음)")
    parser.add_argument("--output-dir", default="artifacts/explanation-v2-phase11")
    args = parser.parse_args(argv)

    content_id = canonical_content_id(args.content_id)
    directive_id = canonical_content_id(args.directive_id) if args.directive_id else None
    requested_concepts = _load_concepts(args.concepts_file)
    draft, directive, selection = _load(args.domain, content_id, directive_id)
    with count_ledger_writes() as writes:
        result = explanation_shadow_pipeline.run(
            domain=args.domain,
            content_id=content_id,
            fact_sheet=draft.get("fact_sheet"),
            financial_reasoning=draft.get("financial_reasoning"),
            production_content_plan=(draft.get("video_flow") or {}).get("content_plan"),
            requested_concepts=requested_concepts,
            series_split_override_reason=args.override_series_split,
            legacy_draft=draft,
            legacy_directive=directive,
            allow_model_calls=args.with_model,
        )
    result["legacy_selection"] = selection
    result["side_effects"] = {
        "database_writes": dict(writes),
        "approvals": 0,
        "queue_inserts": 0,
        "render_calls": 0,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = _output_paths(output_dir, args.domain, content_id, args.with_model)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(explanation_shadow_pipeline.render_markdown(result), encoding="utf-8")
    print(json.dumps({
        "run_status": result["run_status"],
        "error": result.get("error"),
        "json": str(json_path),
        "markdown": str(md_path),
        **result["side_effects"],
    }, ensure_ascii=False))
    return 1 if result["run_status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
