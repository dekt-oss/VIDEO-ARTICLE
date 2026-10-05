"""Phase 13 성적표를 렌더 뒤에 다시 매긴다 — 모델을 다시 부르지 않는다(비용 0, DB 읽기만).

    python -m scripts.publish_gate_v2 <지난 비교 결과 .json> --render-job-id <렌더 작업 id>
    python -m scripts.publish_gate_v2 <지난 비교 결과 .json> --render-qa <렌더 QA .json>

`compare_explanation_v2 --render-job-id` 도 같은 일을 하지만 V2 대본을 처음부터 다시 만든다(유료).
최종 렌더를 한 뒤에는 대본은 그대로이고 렌더 칸만 비어 있으므로, 저장된 비교 결과에 렌더 QA 만 붙인다.
새 파일로 쓴다(`…-gate-<UTC>.json/.md`) — 원래 비교 자료는 덮어쓰지 않는다.
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

from engine import explanation_shadow_pipeline, publish_gate_v2  # noqa: E402
from scripts import compare_explanation_v2  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="저장된 V2 비교 결과에 렌더 QA 를 붙여 Phase 13 성적표를 다시 매긴다")
    parser.add_argument("dossier", help="compare_explanation_v2 가 만든 .json")
    parser.add_argument("--render-job-id", default=None)
    parser.add_argument("--render-qa", default=None, metavar="JSON")
    args = parser.parse_args(argv)
    if not (args.render_job_id or args.render_qa):
        parser.error("--render-job-id 또는 --render-qa 가 필요합니다")

    source = Path(args.dossier)
    result = json.loads(source.read_text(encoding="utf-8"))
    render_qa = compare_explanation_v2._render_qa(result["domain"], args.render_qa, args.render_job_id)
    result["publish_gate"] = publish_gate_v2.evaluate(result, render_qa)
    result.setdefault("run", {})["render_job_id"] = args.render_job_id or ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = source.with_name(f"{source.stem}-gate-{stamp}.json")
    md_path = json_path.with_suffix(".md")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(explanation_shadow_pipeline.render_markdown(result), encoding="utf-8")
    print(json.dumps({"publish_gate": result["publish_gate"]["verdict"],
                      "blocked_at": result["publish_gate"]["blocked_at"],
                      "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
