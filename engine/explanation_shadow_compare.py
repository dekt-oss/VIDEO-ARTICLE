"""Deterministic comparison of legacy directive findings and shadow contracts.

This module measures only properties present in structured artifacts. It never
turns a contract check into a claim about narration, directives, renders, or
audience retention.
"""

from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "explanation-shadow-comparison-v1"
TRACE_FAILURES = frozenset({
    "reasoning_link_lost_before_visual",
    "reasoning_claim_link_missing_shipbuilding",
})
SEMANTIC_FAILURES = frozenset({
    "association_to_determination_hook",
    "scope_expansion_exclusivity",
    "cross_sensory_transfer_invented",
    "unsupported_replacement_claim",
    "polygenic_prerequisite_missing",
})
SOURCE_DEPTH_FAILURES = frozenset({"source_depth_overexpanded"})


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _finding_codes(case: dict[str, Any]) -> list[str]:
    return [
        _text(item.get("code"))
        for item in case.get("findings") or []
        if isinstance(item, dict) and _text(item.get("code"))
    ]


def _axis(outcome: str, *, legacy: str, current: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "legacy": legacy,
        "current": current,
        "evidence": evidence,
    }


def _prerequisite_axis(codes: list[str], resolution: dict[str, Any]) -> dict[str, Any]:
    concepts = resolution.get("concepts") if isinstance(resolution.get("concepts"), list) else []
    required = [item for item in concepts if isinstance(item, dict) and item.get("required") is not False]
    unresolved = [
        _text(item.get("concept_id"))
        for item in required
        if item.get("status") == "UNRESOLVED"
    ]
    legacy_missing = any("prerequisite" in code for code in codes)
    if unresolved:
        return _axis(
            "unresolved",
            legacy="missing_or_unverified" if legacy_missing else "not_recorded",
            current="scope_reduction_required",
            evidence=[f"unresolved:{concept_id}" for concept_id in unresolved],
        )
    if required:
        refs = [
            ref
            for item in required
            for ref in (item.get("knowledge_refs") or [])
            if isinstance(ref, str) and ref
        ]
        return _axis(
            "improved" if legacy_missing else "unchanged",
            legacy="prerequisite_missing" if legacy_missing else "not_recorded",
            current="all_required_concepts_resolved",
            evidence=refs,
        )
    return _axis("not_applicable", legacy="none", current="none_requested", evidence=[])


def _semantic_axis(
    codes: list[str], ir: dict[str, Any], resolution: dict[str, Any]
) -> dict[str, Any]:
    relevant = sorted(set(codes) & SEMANTIC_FAILURES)
    if not relevant:
        return _axis("not_applicable", legacy="none", current="not_compared", evidence=[])
    units = ir.get("reasoning_units") if isinstance(ir.get("reasoning_units"), list) else []
    causal_levels = sorted({
        _text(unit.get("causal_level"))
        for unit in units if isinstance(unit, dict) and _text(unit.get("causal_level"))
    })
    guardrails = [
        guardrail
        for concept in resolution.get("concepts") or []
        if isinstance(concept, dict)
        for guardrail in concept.get("guardrails") or []
        if isinstance(guardrail, str) and guardrail
    ]
    association_failures = {
        "association_to_determination_hook",
        "polygenic_prerequisite_missing",
    }
    machine_checkable = bool(set(relevant) & association_failures)
    calibrated = machine_checkable and (
        "association_only" in causal_levels or bool(guardrails)
    )
    return _axis(
        "improved" if calibrated else "unresolved",
        legacy=",".join(relevant),
        current="calibrated_ir_and_guardrails" if calibrated else "no_machine_checkable_guardrail",
        evidence=[f"causal_level:{value}" for value in causal_levels]
        + [f"guardrail:{value}" for value in guardrails],
    )


def _trace_axis(codes: list[str], ir: dict[str, Any]) -> dict[str, Any]:
    relevant = sorted(set(codes) & TRACE_FAILURES)
    if not relevant:
        return _axis("not_applicable", legacy="none", current="not_compared", evidence=[])
    units = ir.get("reasoning_units") if isinstance(ir.get("reasoning_units"), list) else []
    complete = bool(units) and all(
        isinstance(unit, dict) and unit.get("evidence_ids") and unit.get("raw_refs")
        for unit in units
    )
    ids = [
        _text(unit.get("reasoning_id"))
        for unit in units if isinstance(unit, dict) and _text(unit.get("reasoning_id"))
    ]
    return _axis(
        "improved" if complete else "unresolved",
        legacy=",".join(relevant),
        current="complete_ir_trace" if complete else "incomplete_ir_trace",
        evidence=ids,
    )


def _source_depth_axis(codes: list[str], ir: dict[str, Any]) -> dict[str, Any]:
    relevant = sorted(set(codes) & SOURCE_DEPTH_FAILURES)
    if not relevant:
        return _axis("not_applicable", legacy="none", current="not_compared", evidence=[])
    source = ir.get("source") if isinstance(ir.get("source"), dict) else {}
    depth = _text(source.get("source_depth"))
    units = ir.get("reasoning_units") if isinstance(ir.get("reasoning_units"), list) else []
    safe = (depth == "partial_text" and len(units) <= 3) or (
        depth in ("summary_only", "none") and not units
    )
    current = (
        f"brief_ir_with_{len(units)}_units" if depth == "partial_text"
        else f"{depth or 'unknown'}_with_{len(units)}_units"
    )
    return _axis(
        "improved" if safe else "unresolved",
        legacy=",".join(relevant),
        current=current,
        evidence=[f"source_depth:{depth or 'unknown'}", f"reasoning_units:{len(units)}"],
    )


def compare(
    legacy_case: dict[str, Any], ir: dict[str, Any], resolution: dict[str, Any]
) -> dict[str, Any]:
    """Compare machine-checkable shadow contracts with recorded legacy findings."""
    if not isinstance(legacy_case, dict) or not _text(legacy_case.get("case_id")):
        raise ValueError("legacy_case_invalid")
    if ir.get("contract_version") != "explanation-ir-v1":
        raise ValueError("explanation_ir_contract_invalid")
    if resolution.get("contract_version") != "prerequisite-resolution-v1":
        raise ValueError("resolution_contract_invalid")
    if legacy_case.get("domain") != ir.get("domain"):
        raise ValueError("legacy_ir_domain_mismatch")
    if resolution.get("domain") != ir.get("domain"):
        raise ValueError("resolution_ir_domain_mismatch")
    if resolution.get("content_id") != ir.get("content_id"):
        raise ValueError("resolution_ir_content_mismatch")

    codes = _finding_codes(legacy_case)
    axes = {
        "prerequisite_coverage": _prerequisite_axis(codes, resolution),
        "semantic_calibration": _semantic_axis(codes, ir, resolution),
        "evidence_traceability": _trace_axis(codes, ir),
        "source_depth_safety": _source_depth_axis(codes, ir),
        "final_output_quality": _axis(
            "not_measured",
            legacy="stored_directive_findings",
            current="shadow_contract_only",
            evidence=[],
        ),
    }
    summary = {key: 0 for key in (
        "improved", "unchanged", "unresolved", "not_applicable", "not_measured"
    )}
    for axis in axes.values():
        summary[axis["outcome"]] += 1

    return {
        "contract_version": CONTRACT_VERSION,
        "case_id": _text(legacy_case.get("case_id")),
        "domain": ir.get("domain"),
        "legacy_finding_codes": codes,
        "axes": axes,
        "improvement_summary": summary,
        "non_claims": [
            "spoken_narration_not_generated",
            "directive_not_generated",
            "render_not_generated",
            "retention_not_measured",
        ],
    }
