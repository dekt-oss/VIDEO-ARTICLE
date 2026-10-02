"""Honest, contract-only Phase 7 shadow comparison against the Phase 0 Gold Set."""

from __future__ import annotations

from typing import Any

from . import explanation_quality, semantic_fidelity


_AXIS_FINDINGS = {
    "scope_calibration": frozenset({"scope_expansion"}),
    "causal_calibration": frozenset({"causal_upgrade"}),
    "qualifier_preservation": frozenset({"missing_qualifier"}),
    "attribution_preservation": frozenset({"attribution_loss"}),
    "hook_grounding": frozenset({"unsupported_factual_hook"}),
}


def _axis(outcome: str, evidence: list[str]) -> dict[str, Any]:
    return {"outcome": outcome, "evidence": evidence}


def _validate_legacy(legacy_case: Any, *, domain: str, content_id: str) -> None:
    try:
        explanation_quality.validate_case(legacy_case)
    except (TypeError, explanation_quality.GoldSetError) as exc:
        raise ValueError(f"legacy_case_invalid:{exc}") from exc
    errors: list[str] = []
    if legacy_case.get("domain") != domain:
        errors.append("domain_mismatch")
    if legacy_case.get("case_id") != content_id:
        errors.append("content_id_mismatch")
    if errors:
        raise ValueError("legacy_case_invalid:" + ",".join(errors))


def _clause_evidence(clauses: list[dict[str, Any]], codes: frozenset[str]) -> list[str]:
    return [
        f"{clause['clause_id']}:{code}"
        for clause in clauses
        for code in clause.get("finding_codes", [])
        if code in codes
    ]


def compare(
    legacy_case: dict[str, Any],
    fidelity: dict[str, Any],
    narration: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
) -> dict[str, Any]:
    """Recompute observed Phase 7 axes without claiming final directive quality."""
    _validate_legacy(
        legacy_case,
        domain=str(pack.get("domain") or ""),
        content_id=str(pack.get("content_id") or ""),
    )
    fidelity_errors = semantic_fidelity.validate(
        fidelity, narration, plan, ir, resolution, pack
    )
    if fidelity_errors:
        raise ValueError("semantic_fidelity_invalid:" + ",".join(fidelity_errors))

    status = fidelity["qa_status"]
    outcome = {
        "PASSED": "passed",
        "REJECTED": "failed",
        "BLOCKED_UPSTREAM": "blocked_upstream",
        "REJECTED_UPSTREAM": "rejected_upstream",
        "CRITIC_ERROR": "critic_error",
    }[status]
    clauses = fidelity["clauses"]
    if status in {"BLOCKED_UPSTREAM", "REJECTED_UPSTREAM", "CRITIC_ERROR"}:
        evidence = [status.lower()]
        axes = {
            name: _axis(outcome, evidence)
            for name in (
                "clause_coverage",
                "stable_trace",
                "semantic_entailment",
                "scope_calibration",
                "causal_calibration",
                "qualifier_preservation",
                "attribution_preservation",
                "hook_grounding",
            )
        }
    else:
        axes = {
            "clause_coverage": _axis(
                "passed", [f"clauses:{len(clauses)}", "lossless_ordered_coverage"]
            ),
            "stable_trace": _axis(
                "passed", ["canonical_plan_owned_trace", "canonical_raw_refs"]
            ),
            "semantic_entailment": _axis(
                outcome,
                [
                    clause["clause_id"]
                    for clause in clauses
                    if clause.get("verdict") not in {"ENTAILED", "RHETORICAL"}
                ] or ["all_factual_clauses_entailed"],
            ),
        }
        for axis, codes in _AXIS_FINDINGS.items():
            failures = _clause_evidence(clauses, codes)
            axes[axis] = _axis("failed" if failures else "passed", failures or ["clear"])

    axes["final_directive_quality"] = _axis(
        "not_measured", ["production_directive_and_render_not_evaluated"]
    )
    return {
        "case_id": legacy_case["case_id"],
        "domain": pack["domain"],
        "qa_status": status,
        "legacy_finding_codes": [finding["code"] for finding in legacy_case["findings"]],
        "axes": axes,
    }
