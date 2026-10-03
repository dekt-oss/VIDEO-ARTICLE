from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine import (
    explanation_ir,
    narrative_planner,
    narrative_shadow_compare,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _scope() -> dict[str, bool]:
    return {
        "quote_presence": True,
        "numeric_value": False,
        "unit": False,
        "period": False,
        "semantic_entailment": False,
    }


def _paper_pack() -> dict:
    return {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": "paper-1",
        "source": {"source_depth": "full_body", "source_chars": 5000,
                   "source_mode": "FULL_EXPLAINER", "provider": "", "attribution": {}},
        "claims": [{
            "evidence_id": "paper:C01", "raw_ref": "claims:C01",
            "text": "1,260개 변이가 성격과 연관됐다.", "claim_type": "main_result",
            "domain_role": "claim", "causal_strength": "association_only",
            "evidence_grade": "B", "verification_state": "SUPPORTED",
            "verification_scope": _scope(), "source_refs": [], "uncertainty": None,
            "limitations": [], "attribution": "", "domain_fields": {},
        }],
        "numbers": [], "risks": [], "limitations": [], "background_context": [],
    }


def _paper_ready() -> tuple[dict, dict, dict]:
    pack = _paper_pack()
    ir = paper_reasoning_adapter.build(
        pack,
        core_question="변이는 성격을 결정하는가?",
        thesis="변이는 성격과 연관됐지만 결정한다고 입증하지 않았다.",
    )
    requests = [{"concept_id": "gwas_association", "reason": "연관 해석",
                 "evidence_ids": ["paper:C01"], "required": True}]
    resolution = prerequisite_resolver.resolve(ir, pack, requests)
    return pack, ir, resolution


def _report_ready() -> tuple[dict, dict, dict]:
    pack = {
        "contract_version": "evidence-pack-v1", "domain": "report", "content_id": "report-1",
        "source": {"source_depth": "full_text", "source_chars": 8000,
                   "source_mode": "FULL_EXPLAINER", "provider": "",
                   "attribution": {"broker": "유안타증권"}},
        "claims": [],
        "numbers": [{
            "evidence_id": "report:num_price", "raw_ref": "number_facts:num_price",
            "value": 1, "unit": "%", "period": "2026F", "metric": "가격",
            "scope": "company", "basis": "broker_estimate", "attribution": "유안타증권",
            "display": "유안타증권은 가격 상승을 전망했다.", "comparator": {},
            "interpretation": "neutral", "verification_state": "SUPPORTED",
            "verification_scope": {**_scope(), "numeric_value": True, "unit": True, "period": True},
            "validation": {}, "source_refs": [],
        }],
        "risks": [], "limitations": [], "background_context": [],
    }
    reasoning = {"units": [{
        "reasoning_id": "R01", "unit_type": "EARNINGS_BRIDGE",
        "title": "가격 전망이 실적으로 이어지는 경로", "carries_thesis": True,
        "attributed_to": "유안타증권", "assumption": "가격 상승 유지",
        "breaks_if": "가격 하락", "steps": [{"step": 1,
            "text": "유안타증권은 가격 상승이 매출 전망으로 이어진다고 봤다.",
            "fact_ids": ["num_price"], "source_refs": []}],
    }]}
    ir = report_reasoning_adapter.build(pack, reasoning)
    resolution = prerequisite_resolver.resolve(ir, pack, [])
    return pack, ir, resolution


def test_ready_plan_places_question_then_prerequisite_then_reasoning_with_exact_trace():
    pack, ir, resolution = _paper_ready()

    plan = narrative_planner.build(ir, resolution, pack)

    assert plan["planning_status"] == "READY"
    assert plan["core_question"] == ir["core_question"]
    assert [beat["stage"] for beat in plan["beats"]] == ["HOOK", "SETUP", "EVIDENCE"]
    assert plan["beats"][0]["content_points"] == [ir["core_question"]]
    assert plan["beats"][0]["reasoning_ids"] == []
    assert plan["beats"][1]["knowledge_refs"] == ["glossary:gwas_association"]
    assert plan["beats"][2]["reasoning_ids"] == ["XR01"]
    assert plan["beats"][2]["evidence_ids"] == ["paper:C01"]
    assert plan["beats"][2]["raw_refs"] == ["claims:C01"]
    assert narrative_planner.validate(plan, ir, resolution, pack) == []


def test_source_backed_prerequisite_keeps_evidence_trace_on_setup_beat():
    pack = _paper_pack()
    pack["claims"][0]["verification_scope"]["semantic_entailment"] = True
    pack["claims"][0]["domain_fields"]["prerequisite_concept_id"] = "gwas_association"
    ir = paper_reasoning_adapter.build(pack)
    resolution = prerequisite_resolver.resolve(ir, pack, [{
        "concept_id": "gwas_association", "reason": "연관 해석",
        "evidence_ids": ["paper:C01"], "required": True,
    }])

    plan = narrative_planner.build(ir, resolution, pack)

    assert plan["beats"][1]["evidence_ids"] == ["paper:C01"]
    assert plan["beats"][1]["knowledge_refs"] == ["evidence:paper:C01"]


def test_unresolved_required_prerequisite_blocks_instead_of_writing_reduced_story():
    pack, ir, _ = _paper_ready()
    resolution = prerequisite_resolver.resolve(ir, pack, [{
        "concept_id": "unknown", "reason": "필수", "evidence_ids": [], "required": True,
    }])

    plan = narrative_planner.build(ir, resolution, pack)

    assert plan["planning_status"] == "BLOCKED_PREREQUISITE"
    assert plan["beats"] == []
    assert plan["excluded_reasoning_ids"] == ["XR01"]
    assert "required_prerequisite_unresolved:unknown" in plan["warnings"]


def test_report_plan_preserves_broker_attribution_uncertainty_and_refs():
    pack, ir, resolution = _report_ready()

    plan = narrative_planner.build(ir, resolution, pack)
    evidence = plan["beats"][1]

    assert [beat["stage"] for beat in plan["beats"]] == ["HOOK", "EXPLANATION"]
    assert evidence["attributions"] == ["유안타증권"]
    assert evidence["causal_levels"] == ["broker_projection"]
    assert evidence["uncertainties"] == ["assumption=가격 상승 유지; breaks_if=가격 하락"]
    assert evidence["evidence_ids"] == ["report:num_price"]
    assert evidence["raw_refs"] == ["number_facts:num_price"]


def test_planner_is_deterministic_and_does_not_mutate_inputs():
    pack, ir, resolution = _paper_ready()
    before = deepcopy((ir, resolution))

    assert narrative_planner.build(ir, resolution, pack) == narrative_planner.build(ir, resolution, pack)
    assert (ir, resolution) == before


def test_validation_rejects_dangling_reasoning_and_rewritten_content():
    pack, ir, resolution = _paper_ready()
    plan = narrative_planner.build(ir, resolution, pack)
    plan["beats"][-1]["reasoning_ids"] = ["XR99"]
    plan["beats"][-1]["content_points"] = ["성격을 결정하는 유전자다."]

    errors = narrative_planner.validate(plan, ir, resolution, pack)

    assert "reasoning_ref_unknown:NB03:XR99" in errors
    assert "content_points_invalid:NB03" in errors


def test_validation_rejects_semantic_metadata_or_prerequisite_trace_tampering():
    pack, ir, resolution = _paper_ready()
    plan = narrative_planner.build(ir, resolution, pack)
    plan["beats"][1]["knowledge_refs"] = []
    plan["beats"][2]["causal_levels"] = ["proven_cause"]
    plan["beats"][2]["uncertainties"] = ["certain"]
    plan["beats"][2]["attributions"] = ["invented"]
    plan["beats"][2]["transition_relations"] = ["causes"]

    errors = narrative_planner.validate(plan, ir, resolution, pack)

    assert "knowledge_refs_invalid:NB02" in errors
    assert "causal_levels_invalid:NB03" in errors
    assert "uncertainties_invalid:NB03" in errors
    assert "attributions_invalid:NB03" in errors
    assert "transition_relations_invalid:NB03" in errors


def test_empty_reasoning_ir_is_blocked_instead_of_emitting_question_only_story():
    pack, ir, resolution = _paper_ready()
    ir["reasoning_units"] = []
    ir["explanation_chain"] = []

    plan = narrative_planner.build(ir, resolution, pack)

    assert plan["planning_status"] == "BLOCKED_NO_REASONING"
    assert plan["beats"] == []
    assert "reasoning_units_missing" in plan["warnings"]


def test_malformed_upstream_contracts_fail_closed():
    pack, ir, resolution = _paper_ready()
    resolution["contract_version"] = "made-up"

    with pytest.raises(ValueError, match="prerequisite_resolution_invalid"):
        narrative_planner.build(ir, resolution, pack)


def test_tampered_ir_trace_is_rejected_against_evidence_pack():
    pack, ir, resolution = _paper_ready()
    ir["reasoning_units"][0]["evidence_ids"] = ["paper:UNKNOWN"]
    ir["reasoning_units"][0]["raw_refs"] = ["claims:FAKE"]

    with pytest.raises(ValueError, match="explanation_ir_invalid"):
        narrative_planner.build(ir, resolution, pack)


def test_shadow_comparison_reports_contract_axes_not_final_video_quality():
    pack, ir, resolution = _paper_ready()
    plan = narrative_planner.build(ir, resolution, pack)
    legacy = {"case_id": "personality-gwas-2026-09", "domain": "paper", "findings": [
        {"code": "polygenic_prerequisite_missing", "severity": "p1"},
        {"code": "association_to_determination_hook", "severity": "p0"},
    ]}

    result = narrative_shadow_compare.compare(legacy, ir, resolution, plan, pack)

    assert result["axes"]["one_core_question"]["outcome"] == "improved"
    assert result["axes"]["prerequisite_order"]["outcome"] == "improved"
    assert result["axes"]["reasoning_traceability"]["outcome"] == "improved"
    assert result["axes"]["semantic_calibration"]["outcome"] == "improved"
    assert result["axes"]["final_output_quality"]["outcome"] == "not_measured"
    assert "improvement_percent" not in result


def test_shadow_comparison_rejects_mismatched_legacy_domain():
    pack, ir, resolution = _paper_ready()
    plan = narrative_planner.build(ir, resolution, pack)

    with pytest.raises(ValueError, match="legacy_case_invalid:domain_mismatch"):
        narrative_shadow_compare.compare(
            {"case_id": "wrong", "domain": "report", "findings": []},
            ir, resolution, plan, pack,
        )


def _gold_pack(case: dict) -> dict:
    domain = case["domain"]
    pack = {
        "contract_version": "evidence-pack-v1", "domain": domain,
        "content_id": case["case_id"],
        "source": {"source_depth": case["source_depth"],
                   "source_chars": case.get("source_chars", 12000),
                   "source_mode": case["source_mode"], "provider": "",
                   "attribution": case.get("source_attribution", {})},
        "claims": [], "numbers": [], "risks": [], "limitations": [],
        "background_context": [],
    }
    for item in case["evidence"]:
        projected = deepcopy(item)
        projected["verification_scope"] = {
            "quote_presence": True, "numeric_value": domain == "report",
            "unit": domain == "report", "period": domain == "report",
            "semantic_entailment": False,
        }
        if domain == "paper":
            projected.update(domain_role="claim", evidence_grade="B", source_refs=[],
                             uncertainty=projected.get("uncertainty"), limitations=[],
                             attribution="", domain_fields={})
            pack["claims"].append(projected)
        else:
            projected.update(scope="company", basis="broker_estimate",
                             display=projected["text"], comparator={},
                             interpretation=projected.get("interpretation", "neutral"),
                             validation={}, source_refs=[])
            projected.pop("text")
            pack["numbers"].append(projected)
    return pack


def test_six_gold_cases_are_deterministic_and_unresolved_cases_fail_closed():
    cases = json.loads((FIXTURES / "explanation_ir_gold_cases.json").read_text(encoding="utf-8"))
    requests = json.loads(
        (FIXTURES / "prerequisite_resolution_gold_cases.json").read_text(encoding="utf-8")
    )
    quality = json.loads(
        (FIXTURES / "explanation_quality_gold_set.json").read_text(encoding="utf-8")
    )
    request_by_id = {row["case_id"]: row["requested_concepts"] for row in requests}
    legacy_by_id = {row["case_id"]: row for row in quality["cases"]}
    statuses = {}
    comparisons = {}

    for case in cases:
        pack = _gold_pack(case)
        ir = (paper_reasoning_adapter.build(pack) if case["domain"] == "paper" else
              report_reasoning_adapter.build(pack, case["financial_reasoning"]))
        resolution = prerequisite_resolver.resolve(ir, pack, request_by_id[case["case_id"]])
        plan = narrative_planner.build(ir, resolution, pack)
        comparison = narrative_shadow_compare.compare(
            legacy_by_id[case["case_id"]], ir, resolution, plan, pack
        )
        assert narrative_planner.validate(plan, ir, resolution, pack) == []
        assert comparison["axes"]["final_output_quality"]["outcome"] == "not_measured"
        statuses[case["case_id"]] = plan["planning_status"]
        comparisons[case["case_id"]] = comparison

    assert statuses == {
        "heel-strike-2026-09": "BLOCKED_PREREQUISITE",
        "deaf-retinotopic-remap-2026-09": "BLOCKED_PREREQUISITE",
        "personality-gwas-2026-09": "READY",
        "samsung-memory-cycle-2026-09": "BLOCKED_PREREQUISITE",
        "nh-ai-mid-cycle-2026-09": "BLOCKED_PREREQUISITE",
        "shipbuilding-rerating-2026-09": "BLOCKED_PREREQUISITE",
    }
    assert comparisons["personality-gwas-2026-09"]["axes"][
        "prerequisite_order"
    ]["outcome"] == "improved"
    assert comparisons["personality-gwas-2026-09"]["axes"][
        "semantic_calibration"
    ]["outcome"] == "improved"
    assert comparisons["heel-strike-2026-09"]["axes"][
        "semantic_calibration"
    ]["outcome"] == "unresolved"
    assert comparisons["deaf-retinotopic-remap-2026-09"]["axes"][
        "semantic_calibration"
    ]["outcome"] == "unresolved"
    assert comparisons["nh-ai-mid-cycle-2026-09"]["axes"][
        "source_depth_safety"
    ]["outcome"] == "improved"
    assert comparisons["shipbuilding-rerating-2026-09"]["axes"][
        "semantic_calibration"
    ]["outcome"] == "unresolved"
