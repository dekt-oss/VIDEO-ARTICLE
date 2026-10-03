from __future__ import annotations

from copy import deepcopy

import pytest

from engine import content_complexity_gate, visual_planner
from tests.test_content_complexity_gate import _artifacts, _content_plan, _report_artifacts


def _module():
    try:
        from engine import explanation_directive
    except ImportError as exc:  # RED: Phase 10 does not exist yet.
        pytest.fail(f"Phase 10 directive projector missing: {exc}")
    return explanation_directive


def _ready_inputs():
    pack, ir, resolution, plan, narration, fidelity = _artifacts()
    content_plan = _content_plan()
    gate = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    visual_plan = visual_planner.build(
        content_plan, gate, narration, fidelity, plan, ir, resolution, pack
    )
    return visual_plan, narration, ir, pack


def test_ready_visual_plan_projects_to_current_directive_shape_with_full_trace():
    projector = _module()
    visual_plan, narration, ir, pack = _ready_inputs()

    result = projector.build(visual_plan, narration, ir, pack)

    assert result["contract_version"] == "explanation-directive-shadow-v1"
    assert result["projection_status"] == "READY"
    assert result["domain"] == "paper"
    assert result["content_id"] == "paper-complexity-1"
    assert result["version_type"] == "image_sequence"
    assert set(result) == {
        "contract_version", "projection_status", "domain", "content_id",
        "version_type", "header", "cuts", "visual_sequences", "qa",
    }
    assert len(result["cuts"]) == len(visual_plan["visual_beats"])
    assert result["header"]["total_estimated_sec"] == sum(
        cut["estimated_sec"] for cut in result["cuts"]
    )
    assert result["header"]["core_question"] == visual_plan["core_question"]
    assert result["visual_sequences"]

    mechanism = next(cut for cut in result["cuts"] if cut["visual_mode"] == "MECHANISM")
    assert mechanism["narration_ko"] == "압력이 높아지면 구조가 변한다."
    assert mechanism["reasoning_id"] == "XR01"
    assert mechanism["claim_ids"] == ["C01"]
    assert mechanism["source_facts"] == ["claims:C01"]
    assert mechanism["explanation_trace"] == {
        "visual_beat_id": mechanism["visual_beat_id"],
        "narration_refs": [mechanism["narration_id"]],
        "reasoning_ids": ["XR01"],
        "evidence_ids": ["paper:C01"],
        "raw_refs": ["claims:C01"],
        "stage_id": mechanism["stage_id"],
        "mutation_ids": [mechanism["mutation_ids"][0]],
        "shot_id": mechanism["shot_id"],
        "causal_levels": ["causal"],
        "uncertainties": [],
        "attributions": [],
    }
    assert result["qa"]["metrics"]["fully_traced_cut_count"] == len(result["cuts"])
    assert projector.validate(result, visual_plan, narration, ir, pack) == []


def test_blocked_visual_plan_cannot_emit_a_directive():
    projector = _module()
    visual_plan, narration, ir, pack = _ready_inputs()
    blocked = deepcopy(visual_plan)
    blocked["planner_status"] = "BLOCKED_GATE"
    blocked["visual_beats"] = []
    blocked["sequences"] = []

    with pytest.raises(ValueError, match="visual_plan_not_ready"):
        projector.build(blocked, narration, ir, pack)


@pytest.mark.parametrize("verification_state", ["UNSUPPORTED", "STALE", "NOT_CHECKED"])
def test_non_supported_evidence_cannot_be_promoted_to_a_renderable_cut(verification_state):
    projector = _module()
    visual_plan, narration, ir, pack = _ready_inputs()
    forged_pack = deepcopy(pack)
    forged_pack["claims"][0]["verification_state"] = verification_state

    with pytest.raises(ValueError, match=f"evidence_not_supported:paper:C01#{verification_state}"):
        projector.build(visual_plan, narration, ir, forged_pack)


def test_visual_beat_cannot_borrow_another_beats_narration():
    projector = _module()
    visual_plan, narration, ir, pack = _ready_inputs()
    forged = deepcopy(visual_plan)
    assert len(forged["visual_beats"]) >= 2
    forged["visual_beats"][1]["shot_directive"]["narration_refs"] = [
        forged["visual_beats"][0]["narration_id"]
    ]

    with pytest.raises(ValueError, match="narration_ref_mismatch"):
        projector.build(forged, narration, ir, pack)


def test_blank_stage_entity_cannot_enter_a_production_sequence():
    projector = _module()
    visual_plan, narration, ir, pack = _ready_inputs()
    forged = deepcopy(visual_plan)
    forged["visual_beats"][0]["stage"]["mutations"][0]["entity_ref"] = ""

    with pytest.raises(ValueError, match="mutation_entity_ref_empty"):
        projector.build(forged, narration, ir, pack)


def test_report_projection_preserves_broker_attribution_and_projection_boundary():
    projector = _module()
    pack, ir, resolution, plan, narration, fidelity = _report_artifacts()
    content_plan = _content_plan(selected_mode="flash", target_duration_max_sec=35)
    gate = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    visual_plan = visual_planner.build(
        content_plan, gate, narration, fidelity, plan, ir, resolution, pack
    )

    result = projector.build(visual_plan, narration, ir, pack)

    linked = next(cut for cut in result["cuts"] if cut["reasoning_id"])
    assert linked["attributions"] == ["테스트증권"]
    assert linked["causal_levels"] == ["broker_projection"]
    assert linked["explanation_trace"]["attributions"] == ["테스트증권"]
    assert linked["explanation_trace"]["causal_levels"] == ["broker_projection"]


def test_validator_rejects_trace_removed_after_projection():
    projector = _module()
    visual_plan, narration, ir, pack = _ready_inputs()
    result = projector.build(visual_plan, narration, ir, pack)
    forged = deepcopy(result)
    forged["cuts"][1]["explanation_trace"]["evidence_ids"] = []

    assert projector.validate(forged, visual_plan, narration, ir, pack) == [
        "directive_not_canonical"
    ]

