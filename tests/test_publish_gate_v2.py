"""Phase 13 최종 발행 관문 — 원문 → 논리 → 대본 → 화면 → 렌더 성적표."""

from __future__ import annotations

from engine import config, publish_gate_v2 as gate


def _ready(**overrides):
    """모든 단계가 통과한 비교 결과(근거 묶음은 원문 검사가 통과하도록 비워 둔다)."""
    result = {
        "run_status": "READY",
        "error": None,
        "phase_status": {"phase2": "READY", "phase3": "READY", "phase4": "KEEP", "phase5": "READY",
                         "phase6": "DRAFT_ACCEPTED", "phase7": "PASSED", "phase8": "READY",
                         "phase9": "READY", "phase10": "READY", "production_generator": "READY"},
        "shadow": {
            "evidence_pack": None, "ir": None,
            "resolution": {"unresolved_concepts": []},
            "narrative_plan": {"warnings": []},
            "narration": {"qa": {"errors": [], "warnings": []}, "repairs": []},
            "fidelity": {"qa": {"errors": [], "warnings": []}},
            "gate": {"qa": {}, "required_actions": []},
            "visual_plan": {"qa": {}}, "directive": {"qa": {}},
            "generated": {"approval_blocked": False, "block_reasons": [],
                          "trace": {"untraced_cuts": 0}, "directive": {"cuts": []}},
        },
    }
    for key, value in overrides.items():
        result[key] = value
    return result


def _by_stage(report):
    return {s["stage"]: s for s in report["stages"]}


def test_stages_run_in_the_spec_order():
    report = gate.evaluate(_ready())
    assert [s["stage"] for s in report["stages"]] == ["source", "reasoning", "narration", "visual", "render"]


def test_everything_passes_but_render_is_not_run_yet():
    report = gate.evaluate(_ready())
    stages = _by_stage(report)
    assert stages["narration"]["status"] == "PASS" and stages["visual"]["status"] == "PASS"
    assert stages["render"]["status"] == "NOT_RUN"
    assert report["verdict"] == "INCOMPLETE"


def test_render_qa_completes_the_gate():
    report = gate.evaluate(_ready(), {"passed": True, "hard_fail": [], "warnings": []})
    assert report["verdict"] == "PUBLISHABLE"
    warned = gate.evaluate(_ready(), {"hard_fail": [], "warnings": ["정지 화면 4.0s"],
                                      "clip_motion": {"warnings": ["low_motion#3"]}})
    assert warned["verdict"] == "NEEDS_REVIEW"
    assert _by_stage(warned)["render"]["warnings"] == ["정지 화면 4.0s", "clip_motion: low_motion#3"]
    failed = gate.evaluate(_ready(), {"hard_fail": ["오디오 트랙 없음"], "warnings": []})
    assert failed["verdict"] == "BLOCKED" and failed["blocked_at"] == "render"


def test_a_rejected_script_stops_the_later_stages():
    result = _ready()
    result["phase_status"]["phase6"] = "REJECTED_DRAFT"
    report = gate.evaluate(result, {"hard_fail": [], "warnings": []})
    stages = _by_stage(report)
    assert stages["narration"]["status"] == "FAIL"
    assert stages["visual"]["status"] == "NOT_RUN" and "대본" in stages["visual"]["note"]
    assert stages["render"]["status"] == "NOT_RUN"
    assert report["verdict"] == "BLOCKED" and report["blocked_at"] == "narration"


def test_model_call_required_is_not_a_failure():
    result = _ready(run_status="MODEL_CALL_REQUIRED")
    result["shadow"]["narration"] = None
    stages = _by_stage(gate.evaluate(result))
    assert stages["narration"]["status"] == "NOT_RUN" and "--with-model" in stages["narration"]["note"]


def test_execution_error_lands_in_its_own_stage():
    result = _ready(error={"phase": "phase3", "type": "ValueError", "message": "bad"})
    report = gate.evaluate(result)
    assert report["blocked_at"] == "reasoning"
    assert _by_stage(report)["source"]["status"] == "PASS"


def test_approval_blocked_directive_fails_the_visual_stage():
    result = _ready()
    result["shadow"]["generated"].update(approval_blocked=True, block_reasons=["narration_lock_cut_count"])
    stages = _by_stage(gate.evaluate(result))
    assert stages["visual"]["status"] == "FAIL"
    assert stages["visual"]["fails"] == ["지시서 승인 차단: narration_lock_cut_count"]


def test_missing_bridge_directive_is_only_a_warning():
    result = _ready()
    result["shadow"]["generated"] = None
    result["phase_status"].pop("production_generator")
    stages = _by_stage(gate.evaluate(result))
    assert stages["visual"]["status"] == "WARN"


def test_stale_fact_sheet_evidence_is_a_source_warning():
    result = _ready()
    result["shadow"]["ir"] = {"warnings": ["evidence_state_disallowed:C01:STALE",
                                           "evidence_state_disallowed:C02:STALE"]}
    stages = _by_stage(gate.evaluate(result))
    assert stages["source"]["status"] == "WARN"
    assert "STALE 2건" in stages["source"]["warnings"][0]


def test_motion_plan_flags_a_card_squeezed_into_a_short_cut():
    directive = {"cuts": [
        {"cut_no": 1, "estimated_sec": 6, "overlay_plan": [{"type": "screen_fact", "text": "영업이익 13.7조"}]},
        {"cut_no": 2, "estimated_sec": 1, "overlay_plan": [{"type": "screen_fact", "text": "마진 18.0%"}]},
    ]}
    warnings = gate.motion_plan_warnings(directive)
    assert len(warnings) == 1 and "overlay_too_brief" in warnings[0]
    assert "마진" in warnings[0], "짧은 두 번째 컷의 카드만 걸린다 — 카운트업 프레임은 세지 않는다"


def test_motion_plan_flags_a_wipe_longer_than_its_cut():
    stage = {"stage_id": "S1", "operation": "REVEAL", "cut_refs": [1]}
    directive = {"header": {"visual_sequences": [{"stages": [stage]}]},
                 "cuts": [{"cut_no": 1, "estimated_sec": config.STAGE_REVEAL_WIPE_SEC / 2}]}
    assert any("장면 막" in w for w in gate.motion_plan_warnings(directive))


def test_markdown_groups_codes_into_plain_korean():
    result = _ready()
    result["shadow"]["narrative_plan"]["warnings"] = [
        "length_budget_excluded:XR08", "length_budget_excluded:XR09"]
    result["shadow"]["narration"]["qa"]["warnings"] = ["unexplained_abbreviation:NB02:DRAM"]
    text = "\n".join(gate.markdown_lines(gate.evaluate(result)))
    assert "영상 길이 때문에 뺀 논증 2건 (XR08, XR09)" in text
    assert "풀이 없이 나온 약어 1건 (DRAM)" in text
    assert "판정 미완" in text


def test_pipeline_attaches_the_gate_and_markdown_shows_it():
    from engine import explanation_shadow_pipeline as pipeline
    result = pipeline.run(domain="paper", content_id="11111111-2222-3333-4444-555555555555",
                          fact_sheet={}, legacy_draft={}, legacy_directive=None)
    assert result["publish_gate"]["contract_version"] == gate.CONTRACT_VERSION
    assert "## 최종 발행 관문 (Phase 13" in pipeline.render_markdown(result)
