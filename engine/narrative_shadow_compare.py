"""Phase 5 contract-only comparison against stored Production failures."""

from __future__ import annotations

from typing import Any

from . import narrative_planner


CONTRACT_VERSION = "narrative-shadow-comparison-v1"


def _axis(outcome: str, legacy: str, current: str) -> dict[str, str]:
    return {"outcome": outcome, "legacy": legacy, "current": current}


def compare(legacy_case: dict[str, Any], ir: dict[str, Any],
            resolution: dict[str, Any], plan: dict[str, Any],
            pack: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(legacy_case, dict):
        raise ValueError("legacy_case_invalid:not_dict")
    if not str(legacy_case.get("case_id") or "").strip():
        raise ValueError("legacy_case_invalid:case_id_missing")
    if legacy_case.get("domain") != ir.get("domain"):
        raise ValueError("legacy_case_invalid:domain_mismatch")
    if not isinstance(legacy_case.get("findings"), list):
        raise ValueError("legacy_case_invalid:findings_not_list")
    errors = narrative_planner.validate(plan, ir, resolution, pack)
    if errors:
        raise ValueError("narrative_plan_invalid:" + ",".join(errors))
    findings = {
        str(item.get("code") or "") for item in legacy_case.get("findings") or []
        if isinstance(item, dict)
    }
    blocked = plan["planning_status"] != "READY"
    beats = plan["beats"]
    setup = [i for i, beat in enumerate(beats) if beat["stage"] == "SETUP"
             and beat["concept_ids"]]
    reasoning = [i for i, beat in enumerate(beats) if beat["reasoning_ids"]]
    prerequisite_ok = bool(setup) and (not reasoning or max(setup) < min(reasoning))
    traced = (not blocked and [rid for beat in beats for rid in beat["reasoning_ids"]]
              == ir.get("explanation_chain"))

    if blocked:
        prerequisite_axis = _axis(
            "unresolved", "missing_or_unverified_prerequisite",
            "planning_blocked_before_story_expansion",
        )
        trace_axis = _axis("not_applicable", "legacy_directive", "plan_not_generated")
    else:
        prerequisite_axis = _axis(
            "improved" if prerequisite_ok else "not_applicable",
            "prerequisite_missing" if "polygenic_prerequisite_missing" in findings else "not_recorded",
            "resolved_prerequisite_before_reasoning" if prerequisite_ok else "no_prerequisite_requested",
        )
        trace_axis = _axis(
            "improved" if traced else "unchanged", "reasoning_link_not_stable",
            "complete_reasoning_evidence_raw_ref_trace" if traced else "incomplete_trace",
        )

    source_mode = str((ir.get("source") or {}).get("source_mode") or "")
    brief_safe = source_mode != "BRIEF_EXPLAINER" or len(ir.get("reasoning_units") or []) <= 3
    semantic_failures = {
        "scope_expansion_exclusivity", "visual_field_scope_expansion",
        "cross_sensory_transfer_invented", "anthropomorphic_adaptation_overclaim",
        "association_to_determination_hook", "qualifier_dropped_prefrontal",
        "unsupported_factual_hook_context", "unsupported_replacement_claim",
    }
    has_semantic_failure = bool(findings & semantic_failures)
    if blocked and has_semantic_failure:
        semantic_axis = _axis(
            "unresolved", "stored_semantic_failure", "story_blocked_pending_prerequisite",
        )
    elif has_semantic_failure:
        semantic_axis = _axis(
            "improved", "stored_semantic_failure", "upstream_calibration_preserved_exactly",
        )
    else:
        semantic_axis = _axis("not_applicable", "not_recorded", "metadata_preserved")
    axes = {
        "one_core_question": _axis(
            "not_applicable" if blocked else
            "improved" if plan.get("core_question") == ir.get("core_question") else "unchanged",
            "legacy_story_focus_not_contractual",
            "plan_not_generated" if blocked else "single_ir_core_question",
        ),
        "prerequisite_order": prerequisite_axis,
        "reasoning_traceability": trace_axis,
        "semantic_calibration": semantic_axis,
        "source_depth_safety": _axis(
            "improved" if brief_safe and source_mode == "BRIEF_EXPLAINER" else "not_applicable",
            "source_depth_overexpanded" if "source_depth_overexpanded" in findings else "not_recorded",
            "upstream_ir_limit_preserved" if brief_safe else "limit_exceeded",
        ),
        "final_output_quality": _axis(
            "not_measured", "stored_production_directive", "no_new_production_output",
        ),
    }
    counts = {key: 0 for key in (
        "improved", "unchanged", "unresolved", "not_applicable", "not_measured"
    )}
    for axis in axes.values():
        counts[axis["outcome"]] += 1
    return {
        "contract_version": CONTRACT_VERSION,
        "case_id": str(legacy_case.get("case_id") or ""),
        "domain": ir.get("domain"),
        "planning_status": plan["planning_status"],
        "axes": axes,
        "improvement_summary": counts,
        "non_claims": [
            "spoken_narration_not_generated", "directive_not_generated",
            "render_not_generated", "retention_not_measured",
        ],
    }
