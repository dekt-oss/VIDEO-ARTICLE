"""Compare audited Production directive outcomes with a Phase 9 Shadow plan."""

from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "visual-plan-shadow-comparison-v1"


def _shape_errors(plan: Any) -> list[str]:
    if not isinstance(plan, dict):
        return ["plan_not_dict"]
    errors: list[str] = []
    if plan.get("contract_version") != "visual-plan-v1":
        errors.append("contract_version_invalid")
    if plan.get("planner_status") not in {"READY", "BLOCKED_GATE"}:
        errors.append("planner_status_invalid")
    if not isinstance(plan.get("visual_beats"), list):
        errors.append("visual_beats_not_list")
    if not isinstance(plan.get("sequences"), list):
        errors.append("sequences_not_list")
    qa = plan.get("qa")
    if not isinstance(qa, dict) or not isinstance(qa.get("metrics"), dict):
        errors.append("qa_metrics_invalid")
    if plan.get("planner_status") == "BLOCKED_GATE" and (
        plan.get("visual_beats") or plan.get("sequences")
    ):
        errors.append("blocked_plan_contains_visuals")
    return sorted(set(errors))


def compare(legacy_case: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Return an evidence-bounded before/after report without inferring render quality."""
    errors = _shape_errors(plan)
    if (
        plan.get("content_id") != legacy_case.get("case_id")
        or plan.get("domain") != legacy_case.get("domain")
    ):
        errors.append("comparison_identity_mismatch")
    if errors:
        raise ValueError("visual_plan_invalid:" + ",".join(errors))
    output = legacy_case.get("output") if isinstance(legacy_case.get("output"), dict) else {}
    findings = [row for row in legacy_case.get("findings") or [] if isinstance(row, dict)]
    p0_codes = sorted({
        str(row.get("code") or "").strip() for row in findings
        if row.get("severity") == "p0" and str(row.get("code") or "").strip()
    })
    status = plan["planner_status"]
    metrics = plan.get("qa", {}).get("metrics", {})
    legacy_emitted = bool(output.get("cut_count"))
    blocked = status == "BLOCKED_GATE"
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": legacy_case.get("domain"),
        "content_id": legacy_case.get("case_id"),
        "legacy_spec": {
            "directive_emitted": legacy_emitted,
            "duration_sec": output.get("duration_sec"),
            "cut_count": output.get("cut_count"),
            "p0_finding_codes": p0_codes,
        },
        "v2_spec": {
            "planner_status": status,
            "visual_beat_count": int(metrics.get("visual_beat_count") or 0),
            "traced_stage_count": int(metrics.get("traced_stage_count") or 0),
            "mechanism_stage_count": int(metrics.get("mechanism_stage_count") or 0),
        },
        "axes": {
            "unsafe_semantic_release": (
                "PREVENTED_BEFORE_VISUAL" if legacy_emitted and p0_codes and blocked
                else "NOT_DEMONSTRATED"
            ),
            "reasoning_to_stage_trace": (
                "NOT_APPLICABLE_BLOCKED" if blocked
                else "MEASURED_IN_V2_PLAN"
            ),
            "rendered_motion": "NOT_MEASURED",
        },
        "actual_before_after": bool(
            legacy_case.get("case_id") and output.get("render_review") == "directive_only"
        ),
        "final_directive_quality": "not_measured",
        "rendered_video_quality": "not_measured",
    }
