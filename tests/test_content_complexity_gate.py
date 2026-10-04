from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine import (
    config,
    narrative_planner,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
    semantic_fidelity,
    spoken_narration,
)


def _scope() -> dict[str, bool]:
    return {
        "quote_presence": True,
        "numeric_value": False,
        "unit": False,
        "period": False,
        "semantic_entailment": True,
    }


def _artifacts(*, source_depth: str = "full_body", role: str = "mechanism",
               text: str = "압력이 높아지면 구조가 변한다.",
               content_id: str = "paper-complexity-1",
               blocked: bool = False,
               spoken_text: str | None = None) -> tuple:
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": content_id,
        "source": {
            "source_depth": source_depth,
            "source_chars": 5000,
            "source_mode": "FULL_EXPLAINER" if source_depth == "full_body" else "BRIEF_EXPLAINER",
            "provider": "publisher",
            "attribution": {"title": "테스트 논문"},
        },
        "claims": [{
            "evidence_id": "paper:C01",
            "raw_ref": "claims:C01",
            "text": text,
            "claim_type": role,
            "domain_role": "claim",
            "causal_strength": "causal" if role == "mechanism" else "descriptive",
            "evidence_grade": "A",
            "verification_state": "SUPPORTED",
            "verification_scope": _scope(),
            "source_refs": [{"quote": "pressure changes structure"}],
            "uncertainty": "",
            "limitations": [],
            "attribution": "",
            "domain_fields": {},
        }],
        "numbers": [],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }
    ir = paper_reasoning_adapter.build(
        pack,
        core_question="압력이 높아지면 왜 구조가 변하는가?",
        thesis="압력 변화가 구조 변화를 일으킨다.",
    )
    requested = [{
        "concept_id": "missing_required_concept",
        "reason": "원문에 없는 선행 개념",
        "evidence_ids": [],
        "required": True,
    }] if blocked else []
    resolution = prerequisite_resolver.resolve(ir, pack, requested)
    plan = narrative_planner.build(ir, resolution, pack)
    narration = spoken_narration.normalize_draft(
        {"beats": []} if blocked else {
            "beats": [{
                "beat_id": beat["beat_id"],
                "sentences": [spoken_text] if spoken_text and beat["stage"] != "HOOK"
                else list(beat["content_points"]),
            } for beat in plan["beats"]]
        },
        plan,
        ir,
        resolution,
        pack,
    )
    if blocked:
        fidelity = semantic_fidelity.review(
            narration, plan, ir, resolution, pack,
            caller=lambda **_: pytest.fail("blocked upstream called critic"),
        )
        assert fidelity["qa_status"] == "BLOCKED_UPSTREAM"
        return pack, ir, resolution, plan, narration, fidelity
    critic = {"clauses": []}
    for beat in narration["narration_beats"]:
        for sentence_index, sentence in enumerate(beat["sentences"], 1):
            hook = beat["stage"] == "HOOK"
            critic["clauses"].append({
                "narration_id": beat["narration_id"],
                "sentence_index": sentence_index,
                "clause_text": sentence,
                "clause_kind": "RHETORICAL" if hook else "FACTUAL",
                "verdict": "RHETORICAL" if hook else "ENTAILED",
                "evidence_ids": [] if hook else list(beat["evidence_ids"]),
                "finding_codes": [],
                "rationale": "핵심 질문" if hook else "직접 근거",
            })
    fidelity = semantic_fidelity.normalize_review(
        critic, narration, plan, ir, resolution, pack
    )
    assert fidelity["qa_status"] == "PASSED"
    return pack, ir, resolution, plan, narration, fidelity


def _gate_module():
    try:
        from engine import content_complexity_gate
    except ImportError as exc:  # RED: Phase 8 contract does not exist yet.
        pytest.fail(f"Phase 8 module missing: {exc}")
    return content_complexity_gate


def _shadow_module():
    try:
        from engine import content_complexity_shadow_compare
    except ImportError as exc:
        pytest.fail(f"Phase 8 shadow comparator missing: {exc}")
    return content_complexity_shadow_compare


def _report_artifacts(*, content_id: str = "report-complexity-1",
                      blocked: bool = False) -> tuple:
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": "report",
        "content_id": content_id,
        "source": {
            "source_depth": "partial_text",
            "source_chars": 1072,
            "source_mode": "BRIEF_EXPLAINER",
            "provider": "",
            "attribution": {"broker": "테스트증권", "company": "테스트기업"},
        },
        "claims": [],
        "numbers": [{
            "evidence_id": "report:num_price",
            "raw_ref": "number_facts:num_price",
            "value": 1,
            "unit": "%",
            "period": "2026F",
            "metric": "가격",
            "scope": "company",
            "basis": "broker_estimate",
            "attribution": "테스트증권",
            "display": "테스트증권은 2026년 가격이 1% 상승할 것으로 전망했다.",
            "comparator": {},
            "interpretation": "projection",
            "verification_state": "SUPPORTED",
            "verification_scope": {
                **_scope(), "numeric_value": True, "unit": True, "period": True,
            },
            "validation": {},
            "source_refs": [],
        }],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }
    financial = {"units": [{
        "reasoning_id": "R01",
        "unit_type": "EARNINGS_BRIDGE",
        "title": "가격 전망이 실적으로 이어지는 경로",
        "carries_thesis": True,
        "attributed_to": "테스트증권",
        "assumption": "가격 상승 유지",
        "breaks_if": "가격 하락",
        "steps": [{
            "step": 1,
            "text": "테스트증권은 2026년 가격이 1% 상승할 것으로 전망했다.",
            "fact_ids": ["num_price"],
            "source_refs": [],
        }],
    }]}
    ir = report_reasoning_adapter.build(pack, financial)
    requested = [{
        "concept_id": "missing_required_concept",
        "reason": "원문에 없는 선행 개념",
        "evidence_ids": [],
        "required": True,
    }] if blocked else []
    resolution = prerequisite_resolver.resolve(ir, pack, requested)
    plan = narrative_planner.build(ir, resolution, pack)
    narration = spoken_narration.normalize_draft(
        {"beats": []} if blocked else {
            "beats": [{"beat_id": beat["beat_id"], "sentences": list(beat["content_points"])}
                      for beat in plan["beats"]]
        },
        plan, ir, resolution, pack,
    )
    if blocked:
        fidelity = semantic_fidelity.review(
            narration, plan, ir, resolution, pack,
            caller=lambda **_: pytest.fail("blocked upstream called critic"),
        )
        assert fidelity["qa_status"] == "BLOCKED_UPSTREAM"
        return pack, ir, resolution, plan, narration, fidelity
    critic = {"clauses": []}
    for beat in narration["narration_beats"]:
        for sentence_index, sentence in enumerate(beat["sentences"], 1):
            hook = beat["stage"] == "HOOK"
            critic["clauses"].append({
                "narration_id": beat["narration_id"],
                "sentence_index": sentence_index,
                "clause_text": sentence,
                "clause_kind": "RHETORICAL" if hook else "FACTUAL",
                "verdict": "RHETORICAL" if hook else "ENTAILED",
                "evidence_ids": [] if hook else list(beat["evidence_ids"]),
                "finding_codes": [],
                "rationale": "핵심 질문" if hook else "검증된 숫자 근거",
            })
    fidelity = semantic_fidelity.normalize_review(
        critic, narration, plan, ir, resolution, pack
    )
    assert fidelity["qa_status"] == "PASSED"
    return pack, ir, resolution, plan, narration, fidelity


def _gold_pack(case: dict) -> dict:
    domain = case["domain"]
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": domain,
        "content_id": case["case_id"],
        "source": {
            "source_depth": case["source_depth"],
            "source_chars": case.get("source_chars", 12000),
            "source_mode": case["source_mode"],
            "provider": "",
            "attribution": case.get("source_attribution", {}),
        },
        "claims": [],
        "numbers": [],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }
    for item in case["evidence"]:
        projected = deepcopy(item)
        projected["verification_scope"] = {
            "quote_presence": True,
            "numeric_value": domain == "report",
            "unit": domain == "report",
            "period": domain == "report",
            "semantic_entailment": False,
        }
        if domain == "paper":
            projected.update(
                domain_role="claim",
                evidence_grade="B",
                source_refs=[],
                uncertainty=projected.get("uncertainty"),
                limitations=[],
                attribution="",
                domain_fields={},
            )
            pack["claims"].append(projected)
        else:
            projected.update(
                scope="company",
                basis="broker_estimate",
                display=projected["text"],
                comparator={},
                interpretation=projected.get("interpretation", "neutral"),
                validation={},
                source_refs=[],
            )
            projected.pop("text")
            pack["numbers"].append(projected)
    return pack


def _content_plan(**changes) -> dict:
    plan = {
        "selected_mode": "standard",
        "target_duration_max_sec": 50,
        "series_split_reason": "",
    }
    plan.update(changes)
    return plan


def test_ready_gate_preserves_source_and_mechanism_constraints():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts()

    result = gate.evaluate(
        _content_plan(), narration, fidelity, plan, ir, resolution, pack
    )

    assert result["gate_status"] == "READY"
    assert result["required_actions"] == []
    assert result["constraints"] == {
        "source_depth": "full_body",
        "source_mode": "FULL_EXPLAINER",
        "max_duration_sec": 80,
        "max_content_mode": "extended",
        "mechanism_visual_allowed": True,
        "mechanism_reasoning_ids": ["XR01"],
    }
    assert gate.validate(
        result, _content_plan(), narration, fidelity, plan, ir, resolution, pack
    ) == []


def test_series_split_requires_explicit_reasoned_override():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts()
    content_plan = _content_plan(
        selected_mode="series_split",
        target_duration_max_sec=80,
        series_split_reason="결과와 적용을 두 편으로 나눈다.",
    )

    blocked = gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    assert blocked["gate_status"] == "ACTION_REQUIRED"
    assert [row["action"] for row in blocked["required_actions"]] == ["SPLIT_SERIES"]

    missing_reason = gate.evaluate(
        content_plan,
        narration,
        fidelity,
        plan,
        ir,
        resolution,
        pack,
        overrides={"series_split": {"approved": True, "reason": ""}},
    )
    assert missing_reason["gate_status"] == "ACTION_REQUIRED"

    overridden = gate.evaluate(
        content_plan,
        narration,
        fidelity,
        plan,
        ir,
        resolution,
        pack,
        overrides={
            "series_split": {
                "approved": True,
                "reason": "두 주장이 같은 핵심 질문에 종속됨을 사람이 확인했다.",
            }
        },
    )
    assert overridden["gate_status"] == "READY"
    assert overridden["required_actions"] == []
    assert overridden["applied_overrides"] == [{
        "signal": "series_split",
        "reason": "두 주장이 같은 핵심 질문에 종속됨을 사람이 확인했다.",
    }]


def test_too_many_spoken_numbers_requires_regeneration_and_cannot_be_overridden():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts()
    overloaded = deepcopy(narration)
    overloaded["qa"]["metrics"]["number_count"] = config.MAX_SPOKEN_NUMBERS + 1

    with pytest.raises(ValueError, match="spoken_narration_invalid"):
        gate.evaluate(
            _content_plan(), overloaded, fidelity, plan, ir, resolution, pack,
            overrides={"too_many_spoken_numbers": {"approved": True, "reason": "무시"}},
        )



def test_number_heavy_unit_goes_to_screen_and_narration_stays_within_budget():
    """Phase 12 파일럿 회귀: 숫자가 예산보다 많은 근거는 화면으로 가고 대본은 말로 푼다.

    종전에는 Phase 5 가 숫자를 전부 대본 재료로 넘기고 Phase 6 이 숫자 삭제를 금지해서
    Phase 8 의 REGENERATE_NARRATION 이 풀 수 없는 판정이었다(실측 16·15개 > 2).
    """
    gate = _gate_module()
    text = "압력은 1에서 2를 거쳐 3으로 변한다."
    pack, ir, resolution, plan, narration, fidelity = _artifacts(
        text=text, spoken_text="압력은 여러 단계를 거쳐 변한다.",
    )
    screen = [fact for beat in plan["beats"] for fact in beat["number_delivery"]["screen_facts"]]
    assert screen == [{"ref": "XR01", "text": text, "numbers": ["1", "2", "3"]}]
    assert narration["qa"]["metrics"]["number_count"] == 0

    result = gate.evaluate(_content_plan(), narration, fidelity, plan, ir, resolution, pack)

    assert result["gate_status"] == "READY"
    assert result["required_actions"] == []


def test_reading_screen_numbers_is_rejected_before_the_gate():
    from engine import narrative_planner as planner

    pack, ir, resolution, plan, _, _ = _artifacts(text="압력은 1에서 2를 거쳐 3으로 변한다.",
                                                  spoken_text="압력은 여러 단계를 거쳐 변한다.")
    verbatim = spoken_narration.normalize_draft(
        {"beats": [{"beat_id": beat["beat_id"], "sentences": list(beat["content_points"])}
                   for beat in plan["beats"]]},
        plan, ir, resolution, pack,
    )
    assert planner.validate(plan, ir, resolution, pack) == []
    assert verbatim["generation_status"] == "REJECTED_DRAFT"
    assert any(error.startswith("screen_number_spoken:") for error in verbatim["qa"]["errors"])


def test_shallow_source_forces_length_downgrade_and_missing_mechanism_is_forbidden():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts(
        source_depth="abstract_only", role="main_result"
    )

    result = gate.evaluate(
        _content_plan(selected_mode="standard", target_duration_max_sec=50),
        narration,
        fidelity,
        plan,
        ir,
        resolution,
        pack,
    )

    assert result["gate_status"] == "ACTION_REQUIRED"
    assert [row["action"] for row in result["required_actions"]] == [
        "DOWNGRADE_LENGTH"
    ]
    assert result["constraints"]["max_duration_sec"] == 35
    assert result["constraints"]["max_content_mode"] == "flash"
    assert result["constraints"]["mechanism_visual_allowed"] is False
    assert result["constraints"]["mechanism_reasoning_ids"] == []


def test_nonpassed_semantic_fidelity_blocks_before_complexity_actions():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts()
    critic = {"clauses": [{
        field: row[field]
        for field in (
            "narration_id", "sentence_index", "clause_text", "clause_kind",
            "verdict", "evidence_ids", "finding_codes", "rationale",
        )
    } for row in fidelity["clauses"]]}
    factual = next(row for row in critic["clauses"] if row["clause_kind"] == "FACTUAL")
    factual["verdict"] = "UNSUPPORTED"
    factual["finding_codes"] = ["unsupported_background"]
    factual["rationale"] = "직접 근거가 부족하다."
    rejected = semantic_fidelity.normalize_review(
        critic, narration, plan, ir, resolution, pack
    )
    assert rejected["qa_status"] == "REJECTED"

    result = gate.evaluate(
        _content_plan(selected_mode="series_split"),
        narration,
        rejected,
        plan,
        ir,
        resolution,
        pack,
    )

    assert result["gate_status"] == "BLOCKED_UPSTREAM"
    assert result["required_actions"] == []
    assert result["qa"]["errors"] == ["semantic_fidelity_not_passed:REJECTED"]
    assert result["constraints"]["mechanism_visual_allowed"] is False
    assert result["constraints"]["mechanism_reasoning_ids"] == []


def test_validation_rejects_forged_ready_status_and_removed_actions():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts()
    content_plan = _content_plan(
        selected_mode="series_split",
        series_split_reason="두 편 필요",
    )
    result = gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    forged = deepcopy(result)
    forged["gate_status"] = "READY"
    forged["required_actions"] = []

    errors = gate.validate(
        forged, content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    assert "gate_not_canonical" in errors


def test_partial_report_keeps_brief_limits_and_financial_bridge_trace():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _report_artifacts()

    result = gate.evaluate(
        _content_plan(selected_mode="flash", target_duration_max_sec=35),
        narration, fidelity, plan, ir, resolution, pack,
    )

    assert result["gate_status"] == "READY"
    assert result["constraints"] == {
        "source_depth": "partial_text",
        "source_mode": "BRIEF_EXPLAINER",
        "max_duration_sec": 35,
        "max_content_mode": "",
        "mechanism_visual_allowed": True,
        "mechanism_reasoning_ids": ["XR01"],
    }


def test_source_mode_cannot_be_forged_consistently_across_shadow_artifacts():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts(
        source_depth="abstract_only"
    )
    forged_pack = deepcopy(pack)
    forged_ir = deepcopy(ir)
    forged_plan = deepcopy(plan)
    for source in (
        forged_pack["source"], forged_ir["source"], forged_plan["source"]
    ):
        source["source_mode"] = "FULL_EXPLAINER"

    with pytest.raises(ValueError, match="source_policy_mode_mismatch"):
        gate.evaluate(
            _content_plan(selected_mode="flash", target_duration_max_sec=35),
            narration, fidelity, forged_plan, forged_ir, resolution, forged_pack,
        )


def test_gold_cases_never_create_complexity_actions_from_unsafe_upstream():
    gate = _gate_module()
    fixtures = Path(__file__).parent / "fixtures"
    cases = json.loads(
        (fixtures / "explanation_ir_gold_cases.json").read_text(encoding="utf-8")
    )
    requests = json.loads(
        (fixtures / "prerequisite_resolution_gold_cases.json").read_text(
            encoding="utf-8"
        )
    )
    request_by_id = {row["case_id"]: row["requested_concepts"] for row in requests}
    statuses = {}
    gate_statuses = {}
    for case in cases:
        pack = _gold_pack(case)
        ir = (
            paper_reasoning_adapter.build(pack)
            if case["domain"] == "paper"
            else report_reasoning_adapter.build(pack, case["financial_reasoning"])
        )
        resolution = prerequisite_resolver.resolve(
            ir, pack, request_by_id[case["case_id"]]
        )
        plan = narrative_planner.build(ir, resolution, pack)
        narration = spoken_narration.normalize_draft(
            {
                "beats": [{
                    "beat_id": beat["beat_id"],
                    "sentences": list(beat["content_points"]),
                } for beat in plan["beats"]]
            },
            plan, ir, resolution, pack,
        )
        critic_payload = {"clauses": []}
        for beat in narration["narration_beats"]:
            for sentence_index, sentence in enumerate(beat["sentences"], 1):
                hook = beat["stage"] == "HOOK"
                critic_payload["clauses"].append({
                    "narration_id": beat["narration_id"],
                    "sentence_index": sentence_index,
                    "clause_text": sentence,
                    "clause_kind": "RHETORICAL" if hook else "FACTUAL",
                    "verdict": "RHETORICAL" if hook else "ENTAILED",
                    "evidence_ids": [] if hook else list(beat["evidence_ids"]),
                    "finding_codes": [],
                    "rationale": "핵심 질문" if hook else "고정 critic 판정",
                })
        calls = []

        def critic(**kwargs):
            calls.append(kwargs)
            return critic_payload

        fidelity = semantic_fidelity.review(
            narration, plan, ir, resolution, pack, caller=critic
        )
        case_id = case["case_id"]
        statuses[case_id] = fidelity["qa_status"]
        policy = config.SOURCE_ADEQUACY_POLICIES[case["domain"]][case["source_depth"]]
        content_plan = _content_plan(
            selected_mode=(
                "series_split" if case_id == "nh-ai-mid-cycle-2026-09"
                else policy.get("max_content_mode") or "flash"
            ),
            target_duration_max_sec=policy["max_duration_sec"],
            series_split_reason="두 편 분할 경고",
        )
        result = gate.evaluate(
            content_plan, narration, fidelity, plan, ir, resolution, pack
        )
        gate_statuses[case_id] = result["gate_status"]
        assert result["required_actions"] == []
    assert statuses == {
        "heel-strike-2026-09": "BLOCKED_UPSTREAM",
        "deaf-retinotopic-remap-2026-09": "BLOCKED_UPSTREAM",
        "personality-gwas-2026-09": "REJECTED",
        "samsung-memory-cycle-2026-09": "BLOCKED_UPSTREAM",
        "nh-ai-mid-cycle-2026-09": "BLOCKED_UPSTREAM",
        "shipbuilding-rerating-2026-09": "BLOCKED_UPSTREAM",
    }
    assert set(gate_statuses.values()) == {"BLOCKED_UPSTREAM"}


def test_shadow_comparison_reports_enforced_actions_without_claiming_video_quality():
    gate = _gate_module()
    shadow = _shadow_module()
    gold = json.loads(
        (Path(__file__).parent / "fixtures" / "explanation_quality_gold_set.json")
        .read_text(encoding="utf-8")
    )
    legacy = next(
        case for case in gold["cases"] if case["case_id"] == "heel-strike-2026-09"
    )
    pack, ir, resolution, plan, narration, fidelity = _artifacts(
        content_id=legacy["case_id"]
    )
    result = gate.evaluate(
        _content_plan(
            selected_mode="series_split",
            target_duration_max_sec=80,
            series_split_reason="결과와 적용을 나눈다.",
        ),
        narration, fidelity, plan, ir, resolution, pack,
    )

    comparison = shadow.compare(legacy, result)

    assert "content_mode_warning_not_enforced" in comparison["legacy_finding_codes"]
    assert comparison["axes"] == {
        "series_split": "ACTION_REQUIRED",
        "spoken_numbers": "CLEAR",
        "source_depth": "CLEAR",
        "mechanism_visual": "ALLOWED",
    }
    assert comparison["final_directive_quality"] == "not_measured"
    assert comparison["rendered_video_quality"] == "not_measured"


def test_shadow_comparison_rejects_legacy_identity_mismatch():
    shadow = _shadow_module()
    result = {
        "contract_version": "content-complexity-gate-v1",
        "domain": "paper",
        "content_id": "case-a",
        "gate_status": "READY",
        "required_actions": [],
        "applied_overrides": [],
        "constraints": {"mechanism_visual_allowed": False},
        "qa": {"errors": [], "warnings": [], "metrics": {}},
    }

    with pytest.raises(ValueError, match="legacy_identity_mismatch"):
        shadow.compare(
            {"case_id": "case-b", "domain": "paper", "findings": []}, result
        )


def test_shadow_comparison_rejects_malformed_gate_shape():
    shadow = _shadow_module()
    malformed = {
        "contract_version": "content-complexity-gate-v1",
        "domain": "paper",
        "content_id": "case-a",
        "gate_status": "READY",
        "required_actions": "SPLIT_SERIES",
        "applied_overrides": [],
        "constraints": {},
        "qa": {},
    }

    with pytest.raises(ValueError, match="gate_result_invalid"):
        shadow.compare(
            {"case_id": "case-a", "domain": "paper", "findings": []}, malformed
        )


def _blank_source_mode(*artifacts):
    copies = [deepcopy(item) for item in artifacts]
    for item in copies:
        item["source"]["source_mode"] = ""
    return copies


def test_legacy_unknown_source_mode_is_accepted_only_at_depth_none():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts(source_depth="none")
    legacy_pack, legacy_ir, legacy_plan = _blank_source_mode(pack, ir, plan)

    result = gate.evaluate(
        _content_plan(selected_mode="flash", target_duration_max_sec=35),
        narration, fidelity, legacy_plan, legacy_ir, resolution, legacy_pack,
    )

    assert result["constraints"]["source_mode"] == "BRIEF_EXPLAINER"


def test_blank_source_mode_with_a_deeper_depth_is_still_rejected():
    gate = _gate_module()
    pack, ir, resolution, plan, narration, fidelity = _artifacts(source_depth="full_body")
    blank_pack, blank_ir, blank_plan = _blank_source_mode(pack, ir, plan)

    with pytest.raises(ValueError, match="source_policy_mode_mismatch"):
        gate.evaluate(
            _content_plan(), narration, fidelity, blank_plan, blank_ir, resolution, blank_pack,
        )
