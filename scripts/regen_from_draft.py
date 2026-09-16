"""저장된 실제 초안으로 photo 지시서를 다시 생성하고 directives에 보관한다."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from engine import db, directive


def regenerate(paper_id: str) -> tuple[str, dict]:
    """Supabase의 실제 drafts 행으로 photo 지시서를 생성·저장한다."""
    draft = db.get_draft_full(paper_id)
    if not draft:
        raise ValueError(f"draft 없음(먼저 초안 생성): {paper_id}")

    generated = directive.generate(draft, "photo")
    directive_id = db.insert_directive({
        "paper_id": paper_id,
        "version_type": generated["version_type"],
        "header": generated["header"],
        "cuts": generated["cuts"],
        "status": "draft",
    })
    if not directive_id:
        raise RuntimeError("directive 저장 응답에 id 없음")
    return directive_id, generated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Supabase의 실제 drafts 행으로 photo 지시서를 재생성한다."
    )
    parser.add_argument("paper_id")
    args = parser.parse_args(argv)

    directive_id, generated = regenerate(args.paper_id)
    header = generated.get("header") or {}
    photo_gate = header.get("photo_gate") or {}
    print(json.dumps({
        "paper_id": args.paper_id,
        "directive_id": directive_id,
        "version_type": generated.get("version_type"),
        "cut_count": len(generated.get("cuts") or []),
        "approval_blocked": bool(header.get("approval_blocked")),
        "block_reasons": header.get("block_reasons") or [],
        "photo_gate_warnings": photo_gate.get("warnings") or [],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
