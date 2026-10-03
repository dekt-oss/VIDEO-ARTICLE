"""Read-only Phase 10 comparison of flat and traceable directive shapes."""

from __future__ import annotations

from typing import Any

from . import explanation_directive


CONTRACT_VERSION = "explanation-directive-shadow-comparison-v1"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _cuts(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _fully_traced(cut: dict[str, Any]) -> bool:
    trace = cut.get("explanation_trace")
    if not isinstance(trace, dict):
        return False
    return all((
        trace.get("visual_beat_id"),
        trace.get("narration_refs"),
        trace.get("stage_id"),
        trace.get("mutation_ids"),
        trace.get("shot_id"),
    ))


def _calibration_preserved(cut: dict[str, Any]) -> bool:
    trace = cut.get("explanation_trace")
    if not isinstance(trace, dict):
        return False
    return all(
        list(cut.get(field) or []) == list(trace.get(field) or [])
        for field in ("causal_levels", "uncertainties", "attributions")
    )


def compare(
    legacy: Any,
    projected: Any,
    visual_plan: dict[str, Any],
    narration: dict[str, Any],
    ir: dict[str, Any],
    pack: dict[str, Any],
) -> dict[str, Any]:
    """Compare observable structure only; never infer visual or rendered quality."""
    if not isinstance(legacy, dict) or not isinstance(projected, dict):
        raise ValueError("comparison_input_not_dict")
    if projected.get("contract_version") != "explanation-directive-shadow-v1":
        raise ValueError("projected_contract_invalid")
    if projected.get("projection_status") != "READY":
        raise ValueError("projected_directive_not_ready")
    legacy_identity = (_text(legacy.get("domain")), _text(legacy.get("content_id")))
    projected_identity = (_text(projected.get("domain")), _text(projected.get("content_id")))
    if legacy_identity != projected_identity:
        raise ValueError("comparison_identity_mismatch")
    upstream_identities = {
        (_text(item.get("domain")), _text(item.get("content_id")))
        for item in (visual_plan, narration, ir, pack)
        if isinstance(item, dict)
    }
    if upstream_identities != {projected_identity}:
        raise ValueError("comparison_identity_mismatch")

    projected_errors = explanation_directive.validate(
        projected, visual_plan, narration, ir, pack,
        version_type=_text(projected.get("version_type")),
    )
    if projected_errors:
        raise ValueError("projected_directive_invalid:" + ",".join(projected_errors))

    legacy_cuts = _cuts(legacy.get("cuts"))
    projected_cuts = _cuts(projected.get("cuts"))
    legacy_header = legacy.get("header") if isinstance(legacy.get("header"), dict) else {}
    projected_header = (
        projected.get("header") if isinstance(projected.get("header"), dict) else {}
    )
    expected_narration = [
        " ".join(_text(sentence) for sentence in row.get("sentences") or [] if _text(sentence))
        for row in narration.get("narration_beats") or []
        if isinstance(row, dict)
    ]
    legacy_narration = [_text(cut.get("narration_ko")) for cut in legacy_cuts]
    projected_narration = [_text(cut.get("narration_ko")) for cut in projected_cuts]
    if (
        not expected_narration
        or legacy_narration != expected_narration
        or projected_narration != expected_narration
        or _text(legacy.get("version_type")) != _text(projected.get("version_type"))
    ):
        raise ValueError("comparison_input_mismatch")
    traced_count = sum(_fully_traced(cut) for cut in projected_cuts)
    calibration_count = sum(_calibration_preserved(cut) for cut in projected_cuts)

    return {
        "contract_version": CONTRACT_VERSION,
        "comparison_basis": "deterministic_repository_fixture",
        "same_input_comparison": True,
        "domain": projected_identity[0],
        "content_id": projected_identity[1],
        "legacy_spec": {
            "version_type": _text(legacy.get("version_type")),
            "cut_count": len(legacy_cuts),
            "duration_sec": legacy_header.get("total_estimated_sec", 0),
            "reasoning_linked_cut_count": sum(bool(_text(cut.get("reasoning_id")))
                                               for cut in legacy_cuts),
            "evidence_linked_cut_count": sum(bool(cut.get("claim_ids"))
                                              for cut in legacy_cuts),
            "fully_traced_cut_count": sum(_fully_traced(cut) for cut in legacy_cuts),
        },
        "v2_spec": {
            "contract_version": projected["contract_version"],
            "version_type": _text(projected.get("version_type")),
            "cut_count": len(projected_cuts),
            "duration_sec": projected_header.get("total_estimated_sec", 0),
            "reasoning_linked_cut_count": sum(bool(_text(cut.get("reasoning_id")))
                                               for cut in projected_cuts),
            "evidence_linked_cut_count": sum(bool(cut.get("claim_ids"))
                                              for cut in projected_cuts),
            "fully_traced_cut_count": traced_count,
        },
        "axes": {
            "trace_chain": "COMPLETE_V2" if traced_count == len(projected_cuts)
            else "INCOMPLETE_V2",
            "semantic_calibration": (
                "PRESERVED_V2" if calibration_count == len(projected_cuts)
                else "CALIBRATION_LOSS"
            ),
            "production_wiring": "SHADOW_ONLY",
        },
        "final_directive_visual_quality": "not_measured",
        "rendered_video_quality": "not_measured",
    }
