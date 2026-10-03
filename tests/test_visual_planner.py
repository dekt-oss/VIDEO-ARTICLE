from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from engine import content_complexity_gate
from tests.test_content_complexity_gate import (
    _artifacts,
    _content_plan,
    _report_artifacts,
)


def _planner_module():
    try:
        from engine import visual_planner
    except ImportError as exc:  # RED: Phase 9 does not exist yet.
        raise AssertionError(f"Phase 9 visual planner missing: {exc}") from exc
    return visual_planner


def _comparison_module():
    try:
        from engine import visual_plan_shadow_compare
    except ImportError as exc:  # RED: Phase 9 comparison does not exist yet.
        raise AssertionError(f"Phase 9 shadow comparator missing: {exc}") from exc
    return visual_plan_shadow_compare


def _ready_inputs():
    pack, ir, resolution, plan, narration, fidelity = _artifacts()
    content_plan = _content_plan()
    gate = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    assert gate["gate_status"] == "READY"
    return content_plan, gate, narration, fidelity, plan, ir, resolution, pack


def test_ready_plan_keeps_reasoning_evidence_stage_mutation_and_shot_trace():
    planner = _planner_module()
    inputs = _ready_inputs()

    result = planner.build(*inputs)

    assert result["contract_version"] == "visual-plan-v1"
    assert result["planner_status"] == "READY"
    assert result["content_id"] == "paper-complexity-1"
    assert [row["visual_beat_id"] for row in result["visual_beats"]] == [
        f"VB{index:02d}" for index in range(1, len(result["visual_beats"]) + 1)
    ]
    mechanism = next(row for row in result["visual_beats"] if row["visual_mode"] == "MECHANISM")
    assert mechanism["reasoning_ids"] == ["XR01"]
    assert mechanism["evidence_ids"] == ["paper:C01"]
    assert mechanism["raw_refs"] == ["claims:C01"]
    assert mechanism["stage"]["stage_id"].startswith("VS")
    assert mechanism["stage"]["mutations"] == [{
        "mutation_id": mechanism["stage"]["mutations"][0]["mutation_id"],
        "entity_ref": "reasoning:XR01",
        "operation": "TRANSFORM",
        "result_state_ref": "reasoning:XR01",
        "reasoning_ids": ["XR01"],
        "evidence_ids": ["paper:C01"],
    }]
    assert mechanism["shot_directive"]["stage_id"] == mechanism["stage"]["stage_id"]
    assert mechanism["shot_directive"]["reasoning_ids"] == ["XR01"]
    assert mechanism["shot_directive"]["source_refs"] == ["claims:C01"]
    assert mechanism["transition_relation"] == "supports"
    assert mechanism["shot_directive"]["transition_out"] == "GRAPHIC_MATCH"
    first_stage_by_sequence = {
        sequence["stage_ids"][0]: sequence["sequence_id"]
        for sequence in result["sequences"]
    }
    for row in result["visual_beats"]:
        if row["stage"]["stage_id"] in first_stage_by_sequence:
            assert row["stage"]["continuity_mode"] == "NEW_WORLD"
    assert all(
        sequence["sequence_role"] != "MECHANISM_SEQUENCE"
        or len(sequence["stage_ids"]) >= 2
        for sequence in result["sequences"]
    )
    assert result["qa"]["metrics"]["traced_stage_count"] == len(result["visual_beats"]) - 1


def test_non_ready_gate_cannot_emit_visual_stage_or_shot():
    planner = _planner_module()
    _, _, narration, fidelity, plan, ir, resolution, pack = _ready_inputs()
    content_plan = _content_plan(
        selected_mode="series_split", series_split_reason="two independent stories"
    )
    blocked = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )

    result = planner.build(
        content_plan, blocked, narration, fidelity, plan, ir, resolution, pack,
    )

    assert result["planner_status"] == "BLOCKED_GATE"
    assert result["visual_beats"] == []
    assert result["sequences"] == []
    assert result["qa"]["errors"] == ["content_complexity_gate_not_ready:ACTION_REQUIRED"]


def test_canonical_gate_validation_rejects_forged_ready_status():
    planner = _planner_module()
    content_plan, gate, narration, fidelity, plan, ir, resolution, pack = _ready_inputs()
    forged = deepcopy(gate)
    forged["constraints"]["mechanism_reasoning_ids"] = []
    forged["constraints"]["mechanism_visual_allowed"] = False

    try:
        planner.build(content_plan, forged, narration, fidelity, plan, ir, resolution, pack)
    except ValueError as exc:
        assert "content_complexity_gate_invalid:gate_not_canonical" in str(exc)
    else:
        raise AssertionError("forged gate was accepted")


def test_validator_rejects_foreign_evidence_and_mutation_trace():
    planner = _planner_module()
    inputs = _ready_inputs()
    result = planner.build(*inputs)
    forged = deepcopy(result)
    target = next(row for row in forged["visual_beats"] if row["reasoning_ids"])
    target["evidence_ids"] = ["paper:UNKNOWN"]
    target["stage"]["mutations"][0]["reasoning_ids"] = ["XR99"]

    errors = planner.validate(forged, *inputs)

    assert "visual_plan_not_canonical" in errors
    assert "unknown_evidence_id:paper:UNKNOWN" in errors
    assert "unknown_reasoning_id:XR99" in errors


def test_mechanism_mode_is_limited_to_gate_reasoning_ids():
    planner = _planner_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts(role="main_result")
    content_plan = _content_plan()
    gate = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    inputs = [content_plan, gate, narration, fidelity, plan, ir, resolution, pack]

    result = planner.build(*inputs)

    assert all(row["visual_mode"] != "MECHANISM" for row in result["visual_beats"])
    assert "mechanism_visual_forbidden" in result["qa"]["warnings"]


def test_report_plan_preserves_broker_attribution_and_projection_boundary():
    planner = _planner_module()
    pack, ir, resolution, plan, narration, fidelity = _report_artifacts()
    content_plan = _content_plan(selected_mode="flash", target_duration_max_sec=35)
    gate = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )

    result = planner.build(
        content_plan, gate, narration, fidelity, plan, ir, resolution, pack
    )

    explanation = next(row for row in result["visual_beats"] if row["reasoning_ids"])
    assert explanation["visual_mode"] == "MECHANISM"
    assert explanation["attributions"] == ["테스트증권"]
    assert explanation["causal_levels"] == ["broker_projection"]
    assert explanation["representation_mode"] == "SCHEMATIC_PRINCIPLE"
    assert explanation["shot_directive"]["attributions"] == ["테스트증권"]
    assert explanation["shot_directive"]["causal_levels"] == ["broker_projection"]


def test_actual_gold_comparison_reports_release_safety_without_claiming_visual_quality():
    planner = _planner_module()
    comparison_module = _comparison_module()
    gold = json.loads(
        (Path(__file__).parent / "fixtures" / "explanation_quality_gold_set.json")
        .read_text(encoding="utf-8")
    )
    legacy = next(
        case for case in gold["cases"]
        if case["case_id"] == "deaf-retinotopic-remap-2026-09"
    )
    content_plan, gate, narration, fidelity, plan, ir, resolution, pack = _ready_inputs()
    blocked_gate = deepcopy(gate)
    blocked_gate["domain"] = legacy["domain"]
    blocked_gate["content_id"] = legacy["case_id"]
    blocked_gate["gate_status"] = "BLOCKED_UPSTREAM"
    blocked_gate["required_actions"] = []
    blocked_gate["constraints"]["mechanism_visual_allowed"] = False
    blocked_gate["constraints"]["mechanism_reasoning_ids"] = []
    blocked_gate["qa"]["errors"] = ["semantic_fidelity_not_passed:BLOCKED_UPSTREAM"]
    blocked = planner.blocked_from_gate(blocked_gate, legacy["case_id"], legacy["domain"])

    comparison = comparison_module.compare(legacy, blocked)

    assert comparison["contract_version"] == "visual-plan-shadow-comparison-v1"
    assert comparison["legacy_spec"] == {
        "directive_emitted": True,
        "duration_sec": 58.37,
        "cut_count": 9,
        "p0_finding_codes": [
            "blocked_draft_published",
            "cross_sensory_transfer_invented",
            "visual_field_scope_expansion",
        ],
    }
    assert comparison["v2_spec"]["planner_status"] == "BLOCKED_GATE"
    assert comparison["axes"]["unsafe_semantic_release"] == "PREVENTED_BEFORE_VISUAL"
    assert comparison["axes"]["reasoning_to_stage_trace"] == "NOT_APPLICABLE_BLOCKED"
    assert comparison["actual_before_after"] is True
    assert comparison["final_directive_quality"] == "not_measured"
    assert comparison["rendered_video_quality"] == "not_measured"


def test_comparator_rejects_malformed_visual_plan():
    comparison_module = _comparison_module()
    gold = json.loads(
        (Path(__file__).parent / "fixtures" / "explanation_quality_gold_set.json")
        .read_text(encoding="utf-8")
    )
    malformed = {"contract_version": "visual-plan-v1", "planner_status": "READY"}

    try:
        comparison_module.compare(gold["cases"][0], malformed)
    except ValueError as exc:
        assert "visual_plan_invalid" in str(exc)
    else:
        raise AssertionError("malformed visual plan was accepted")


def test_comparator_rejects_cross_case_or_cross_domain_comparison():
    planner = _planner_module()
    comparison_module = _comparison_module()
    gold = json.loads(
        (Path(__file__).parent / "fixtures" / "explanation_quality_gold_set.json")
        .read_text(encoding="utf-8")
    )
    legacy = gold["cases"][0]
    wrong = planner.blocked_from_gate(
        {"gate_status": "BLOCKED_UPSTREAM", "constraints": {}},
        "different-case", "report",
    )

    try:
        comparison_module.compare(legacy, wrong)
    except ValueError as exc:
        assert "comparison_identity_mismatch" in str(exc)
    else:
        raise AssertionError("cross-case comparison was accepted")


def test_blocked_helper_refuses_ready_gate():
    planner = _planner_module()

    try:
        planner.blocked_from_gate(
            {"gate_status": "READY", "constraints": {}}, "case-1", "paper"
        )
    except ValueError as exc:
        assert "gate_is_ready" in str(exc)
    else:
        raise AssertionError("READY gate was converted into a blocked plan")


def test_all_six_audited_production_specs_compare_without_visual_quality_claims():
    planner = _planner_module()
    comparison_module = _comparison_module()
    gold = json.loads(
        (Path(__file__).parent / "fixtures" / "explanation_quality_gold_set.json")
        .read_text(encoding="utf-8")
    )

    comparisons = []
    for legacy in gold["cases"]:
        blocked = planner.blocked_from_gate(
            {
                "gate_status": "BLOCKED_UPSTREAM",
                "constraints": {
                    "mechanism_visual_allowed": False,
                    "mechanism_reasoning_ids": [],
                },
            },
            legacy["case_id"],
            legacy["domain"],
        )
        comparisons.append(comparison_module.compare(legacy, blocked))

    assert len(comparisons) == 6
    assert {row["axes"]["unsafe_semantic_release"] for row in comparisons} == {
        "PREVENTED_BEFORE_VISUAL"
    }
    assert {row["final_directive_quality"] for row in comparisons} == {"not_measured"}
    assert {row["rendered_video_quality"] for row in comparisons} == {"not_measured"}
