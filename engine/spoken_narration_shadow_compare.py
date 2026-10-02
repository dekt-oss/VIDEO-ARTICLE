"""Contract-only comparison for Phase 6 spoken narration shadow artifacts."""

from __future__ import annotations

from typing import Any

from . import narrative_planner, spoken_narration


def _legacy_errors(legacy_case: Any, plan: dict[str, Any]) -> list[str]:
    if not isinstance(legacy_case, dict):
        return ["case_not_dict"]
    errors: list[str] = []
    if legacy_case.get("domain") != plan.get("domain"):
        errors.append("domain_mismatch")
    if legacy_case.get("case_id") != plan.get("content_id"):
        errors.append("content_id_mismatch")
    if not isinstance(legacy_case.get("findings"), list):
        errors.append("findings_not_list")
    return errors


def _axis(outcome: str, evidence: list[str]) -> dict[str, Any]:
    return {"outcome": outcome, "evidence": evidence}


def compare(legacy_case: dict[str, Any], narration: dict[str, Any],
            plan: dict[str, Any], ir: dict[str, Any], resolution: dict[str, Any],
            pack: dict[str, Any]) -> dict[str, Any]:
    """Compare only deterministic Phase 6 properties; never infer final quality."""
    plan_errors = narrative_planner.validate(plan, ir, resolution, pack)
    if plan_errors:
        raise ValueError("narrative_plan_invalid:" + ",".join(plan_errors))
    legacy_errors = _legacy_errors(legacy_case, plan)
    if legacy_errors:
        raise ValueError("legacy_case_invalid:" + ",".join(legacy_errors))
    narration_errors = spoken_narration.validate(
        narration, plan, ir, resolution, pack
    )
    if narration_errors:
        raise ValueError("spoken_narration_invalid:" + ",".join(narration_errors))

    status = narration["generation_status"]
    blocked = status == "BLOCKED_UPSTREAM"
    qa_errors = narration.get("qa", {}).get("errors") or []
    qa_warnings = narration.get("qa", {}).get("warnings") or []
    expected_ids = [beat["beat_id"] for beat in plan["beats"]]
    actual_ids = [beat["beat_id"] for beat in narration["narration_beats"]]
    trace_ok = all(
        narration["narration_beats"][position].get(field) == plan_beat.get(field)
        for position, plan_beat in enumerate(plan["beats"])
        for field in (
            "reasoning_ids", "evidence_ids", "raw_refs", "concept_ids",
            "knowledge_refs", "causal_levels", "uncertainties", "attributions",
        )
    ) if actual_ids == expected_ids else False
    setup_positions = [
        position for position, beat in enumerate(plan["beats"])
        if beat.get("stage") == "SETUP" and beat.get("concept_ids")
    ]
    reasoning_positions = [
        position for position, beat in enumerate(plan["beats"])
        if beat.get("reasoning_ids")
    ]
    prerequisite_ok = (
        not setup_positions or not reasoning_positions
        or max(setup_positions) < min(reasoning_positions)
    )
    hook_errors = [error for error in qa_errors if error.startswith("hook_")]
    qualifier_errors = [
        error for error in qa_errors
        if error.startswith((
            "numbers_changed:", "scope_intensifier_added:",
            "protected_meaning_changed:", "association_upgraded:",
            "attribution_dropped:",
        ))
    ]

    if blocked:
        contract_outcome = "blocked_upstream"
        axes = {
            "plan_coverage": _axis(contract_outcome, [plan["planning_status"]]),
            "stable_trace": _axis(contract_outcome, ["no_narration_emitted"]),
            "prerequisite_order": _axis(contract_outcome, [plan["planning_status"]]),
            "hook_grounding": _axis(contract_outcome, ["no_hook_emitted"]),
            "qualifier_preservation": _axis(contract_outcome, ["no_claim_emitted"]),
            "spoken_structure": _axis(contract_outcome, ["no_narration_emitted"]),
        }
    else:
        axes = {
            "plan_coverage": _axis(
                "passed" if actual_ids == expected_ids else "failed",
                [f"beats:{len(actual_ids)}/{len(expected_ids)}"],
            ),
            "stable_trace": _axis(
                "passed" if trace_ok else "failed",
                ["plan_owned_provenance" if trace_ok else "trace_mismatch"],
            ),
            "prerequisite_order": _axis(
                "passed" if prerequisite_ok else "failed",
                ["setup_before_reasoning" if prerequisite_ok else "setup_after_reasoning"],
            ),
            "hook_grounding": _axis(
                "passed" if not hook_errors else "failed", hook_errors or ["question_hook"],
            ),
            "qualifier_preservation": _axis(
                "passed" if not qualifier_errors else "failed",
                qualifier_errors or ["deterministic_guards_clear"],
            ),
            "spoken_structure": _axis(
                "warning" if qa_warnings else "passed", list(qa_warnings),
            ),
        }
    axes["semantic_entailment"] = _axis("not_measured", ["phase_7_required"])
    axes["final_directive_quality"] = _axis("not_measured", ["phase_9_required"])
    return {
        "case_id": legacy_case["case_id"],
        "domain": plan["domain"],
        "generation_status": status,
        "legacy_finding_codes": [
            finding.get("code") for finding in legacy_case["findings"]
            if isinstance(finding, dict) and finding.get("code")
        ],
        "axes": axes,
    }
