"""Explanation Engine v2 Phase 0 quality-audit primitives.

This module is intentionally read-only and deterministic. It does not change
drafts, directives, render jobs, or production data. Phase 0 needs a stable
gold set before later phases change generation behavior.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


QUALITY_AXES: tuple[str, ...] = (
    "source_adequacy",
    "fact_fidelity",
    "reasoning_quality",
    "explanation_quality",
    "script_coherence",
    "narration_naturalness",
    "visual_explanatory_power",
    "visual_narration_alignment",
    "pacing",
    "uncertainty_calibration",
)

RATING_VALUES: frozenset[str] = frozenset({"pass", "mixed", "fail", "not_audited"})
DOMAINS: frozenset[str] = frozenset({"paper", "report"})
FAILURE_STAGES: frozenset[str] = frozenset(
    {"source", "fact_evidence", "reasoning", "script", "narration", "visual", "render"}
)
SEVERITIES: frozenset[str] = frozenset({"p0", "p1", "p2"})


class GoldSetError(ValueError):
    """Raised when a Phase 0 gold-set case violates the audit contract."""


def _require_text(obj: dict[str, Any], key: str, *, where: str) -> str:
    value = str(obj.get(key) or "").strip()
    if not value:
        raise GoldSetError(f"{where}.{key}: non-empty text required")
    return value


def validate_case(case: dict[str, Any]) -> None:
    """Validate one hand-audited baseline case.

    The gold set is evidence, not a detector. Later phases are evaluated
    against these labels; Phase 0 must not silently infer or rewrite them.
    """
    case_id = _require_text(case, "case_id", where="case")
    _require_text(case, "title", where=case_id)

    domain = str(case.get("domain") or "")
    if domain not in DOMAINS:
        raise GoldSetError(f"{case_id}.domain: expected one of {sorted(DOMAINS)}, got {domain!r}")

    source = case.get("source")
    if not isinstance(source, dict):
        raise GoldSetError(f"{case_id}.source: object required")
    _require_text(source, "depth", where=f"{case_id}.source")
    chars = source.get("chars")
    if not isinstance(chars, int) or chars < 0:
        raise GoldSetError(f"{case_id}.source.chars: non-negative integer required")

    output = case.get("output")
    if not isinstance(output, dict):
        raise GoldSetError(f"{case_id}.output: object required")
    for key in ("duration_sec", "cut_count"):
        value = output.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise GoldSetError(f"{case_id}.output.{key}: non-negative number required")
    render_review = str(output.get("render_review") or "")
    if render_review not in {"direct", "directive_only", "not_audited"}:
        raise GoldSetError(
            f"{case_id}.output.render_review: direct/directive_only/not_audited required"
        )

    ratings = case.get("ratings")
    if not isinstance(ratings, dict):
        raise GoldSetError(f"{case_id}.ratings: object required")
    missing = [axis for axis in QUALITY_AXES if axis not in ratings]
    extra = [axis for axis in ratings if axis not in QUALITY_AXES]
    if missing or extra:
        raise GoldSetError(f"{case_id}.ratings: missing={missing}, extra={extra}")
    for axis, value in ratings.items():
        if value not in RATING_VALUES:
            raise GoldSetError(f"{case_id}.ratings.{axis}: invalid value {value!r}")

    findings = case.get("findings")
    if not isinstance(findings, list) or not findings:
        raise GoldSetError(f"{case_id}.findings: non-empty list required")
    seen: set[str] = set()
    for i, finding in enumerate(findings):
        where = f"{case_id}.findings[{i}]"
        if not isinstance(finding, dict):
            raise GoldSetError(f"{where}: object required")
        code = _require_text(finding, "code", where=where)
        if code in seen:
            raise GoldSetError(f"{case_id}: duplicate finding code {code}")
        seen.add(code)
        if finding.get("stage") not in FAILURE_STAGES:
            raise GoldSetError(f"{where}.stage: invalid stage {finding.get('stage')!r}")
        if finding.get("severity") not in SEVERITIES:
            raise GoldSetError(f"{where}.severity: invalid severity {finding.get('severity')!r}")
        _require_text(finding, "observed", where=where)
        _require_text(finding, "expected", where=where)
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(str(x).strip() for x in evidence):
            raise GoldSetError(f"{where}.evidence: non-empty text list required")


def load_gold_set(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a Phase 0 gold set."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise GoldSetError("gold set must contain a non-empty 'cases' array")
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise GoldSetError("every case must be an object")
        validate_case(case)
        case_id = str(case["case_id"])
        if case_id in ids:
            raise GoldSetError(f"duplicate case_id: {case_id}")
        ids.add(case_id)
    return cases


def summarize(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic baseline counts for CI and review."""
    cases = list(cases)
    by_domain: Counter[str] = Counter()
    by_stage: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    rating_totals: dict[str, Counter[str]] = {axis: Counter() for axis in QUALITY_AXES}
    finding_count = 0

    for case in cases:
        validate_case(case)
        by_domain[str(case["domain"])] += 1
        for axis in QUALITY_AXES:
            rating_totals[axis][str(case["ratings"][axis])] += 1
        for finding in case["findings"]:
            finding_count += 1
            by_stage[str(finding["stage"])] += 1
            by_severity[str(finding["severity"])] += 1

    return {
        "cases": len(cases),
        "findings": finding_count,
        "by_domain": dict(sorted(by_domain.items())),
        "by_stage": dict(sorted(by_stage.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "ratings": {axis: dict(sorted(counts.items())) for axis, counts in rating_totals.items()},
    }


def markdown_report(cases: Iterable[dict[str, Any]]) -> str:
    """Render a compact, review-friendly report from the fixed labels."""
    cases = list(cases)
    summary = summarize(cases)
    lines = [
        "# Explanation Engine v2 — Phase 0 Gold Set",
        "",
        f"- cases: {summary['cases']}",
        f"- findings: {summary['findings']}",
        f"- domains: {summary['by_domain']}",
        f"- stages: {summary['by_stage']}",
        "",
        "| case | domain | source | duration | cuts | P0/P1 findings |",
        "|---|---|---|---:|---:|---|",
    ]
    for case in cases:
        important = [
            f"{f['severity']}:{f['code']}"
            for f in case["findings"]
            if f["severity"] in {"p0", "p1"}
        ]
        lines.append(
            "| {case_id} | {domain} | {depth} ({chars:,} chars) | {duration:g}s | {cuts:g} | {findings} |".format(
                case_id=case["case_id"],
                domain=case["domain"],
                depth=case["source"]["depth"],
                chars=case["source"]["chars"],
                duration=case["output"]["duration_sec"],
                cuts=case["output"]["cut_count"],
                findings="<br>".join(important) or "-",
            )
        )
    return "\n".join(lines) + "\n"
