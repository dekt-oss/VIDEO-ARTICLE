from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine import (
    explanation_ir,
    explanation_shadow_compare,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
)


def _scope(*, semantic: bool) -> dict[str, bool]:
    return {
        "quote_presence": True,
        "numeric_value": False,
        "unit": False,
        "period": False,
        "semantic_entailment": semantic,
    }


def _pack(*, semantic: bool = False, state: str = "SUPPORTED") -> dict:
    return {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": "paper-1",
        "source": {
            "source_depth": "full_body",
            "source_chars": 5000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "publisher",
            "attribution": {},
        },
        "claims": [{
            "evidence_id": "paper:C01",
            "raw_ref": "claims:C01",
            "text": "GWAS는 변이와 성격 사이의 통계적 연관을 찾는다.",
            "claim_type": "background_context",
            "domain_role": "claim",
            "causal_strength": "association_only",
            "evidence_grade": "A",
            "verification_state": state,
            "verification_scope": _scope(semantic=semantic),
            "source_refs": [{"quote": "variants associated with personality"}],
            "uncertainty": None,
            "limitations": [],
            "attribution": "",
            "domain_fields": {"prerequisite_concept_id": "gwas_association"},
        }],
        "numbers": [],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }


def _ir(pack: dict) -> dict:
    candidate = {
        "domain": "paper",
        "core_question": "성격과 유전 변이의 관계를 어떻게 해석해야 하는가?",
        "thesis": "변이는 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다.",
        "reasoning_units": [{
            "role": "result",
            "text": pack["claims"][0]["text"],
            "evidence_ids": ["paper:C01"],
            "causal_level": "association_only",
        }],
    }
    return explanation_ir.normalize(candidate, pack)


def _request(concept_id: str, *, evidence_ids: list[str] | None = None) -> list[dict]:
    return [{
        "concept_id": concept_id,
        "reason": "결과를 인과로 오해하지 않으려면 먼저 필요하다.",
        "evidence_ids": evidence_ids or [],
        "required": True,
    }]


def test_resolver_prefers_semantically_verified_primary_source():
    pack = _pack(semantic=True)
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(
        ir,
        pack,
        _request("gwas_association", evidence_ids=["paper:C01"]),
    )

    concept = result["concepts"][0]
    assert concept["status"] == "RESOLVED_SOURCE"
    assert concept["evidence_ids"] == ["paper:C01"]
    assert concept["knowledge_refs"] == ["evidence:paper:C01"]
    assert result["scope_action"] == "KEEP"
    assert prerequisite_resolver.validate(result, ir, pack) == []


def test_quote_presence_without_semantic_entailment_falls_back_to_glossary():
    pack = _pack(semantic=False)
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(
        ir,
        pack,
        _request("gwas_association", evidence_ids=["paper:C01"]),
    )

    concept = result["concepts"][0]
    assert concept["status"] == "RESOLVED_GLOSSARY"
    assert concept["evidence_ids"] == []
    assert concept["knowledge_refs"] == ["glossary:gwas_association"]
    assert concept["guardrails"] == [
        "통계적 연관은 해당 변이가 특성을 직접 결정하거나 원인임을 뜻하지 않는다."
    ]
    assert "source_semantic_entailment_unverified:gwas_association:paper:C01" in result["warnings"]


def test_semantically_verified_but_different_concept_cannot_be_reused():
    pack = _pack(semantic=True)
    pack["claims"][0]["domain_fields"]["prerequisite_concept_id"] = "different_concept"
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(
        ir,
        pack,
        _request("gwas_association", evidence_ids=["paper:C01"]),
    )

    assert result["concepts"][0]["status"] == "RESOLVED_GLOSSARY"
    assert "source_concept_mismatch:gwas_association:paper:C01" in result["warnings"]


def test_unknown_required_concept_fails_closed_and_narrows_scope():
    pack = _pack()
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(ir, pack, _request("unknown-concept"))

    assert result["concepts"][0]["status"] == "UNRESOLVED"
    assert result["unresolved_concepts"] == ["unknown-concept"]
    assert result["scope_action"] == "NARROW_SCOPE"
    assert "glossary_concept_unknown:unknown-concept" in result["warnings"]


def test_non_required_unknown_concept_does_not_force_scope_reduction():
    pack = _pack()
    ir = _ir(pack)
    request = _request("unknown-concept")
    request[0]["required"] = False

    result = prerequisite_resolver.resolve(ir, pack, request)

    assert result["scope_action"] == "KEEP"
    assert result["unresolved_concepts"] == ["unknown-concept"]


def test_resolver_is_deterministic_and_does_not_mutate_inputs():
    pack = _pack()
    ir = _ir(pack)
    requests = _request("gwas_association", evidence_ids=["paper:C01"])
    before = deepcopy((ir, pack, requests))

    first = prerequisite_resolver.resolve(ir, pack, requests)
    second = prerequisite_resolver.resolve(ir, pack, requests)

    assert first == second
    assert (ir, pack, requests) == before


def test_duplicate_requested_concept_is_ignored_with_warning():
    pack = _pack()
    ir = _ir(pack)
    requests = _request("gwas_association") + _request("gwas_association")

    result = prerequisite_resolver.resolve(ir, pack, requests)

    assert [item["concept_id"] for item in result["concepts"]] == ["gwas_association"]
    assert "requested_concept_duplicate:gwas_association" in result["warnings"]


def test_invalid_glossary_provenance_is_rejected():
    pack = _pack()
    ir = _ir(pack)
    glossary = [{
        "concept_id": "gwas_association",
        "domains": ["paper"],
        "label": "GWAS 연관",
        "simple_explanation": "설명",
        "guardrails": [],
        "source": {"publisher": "", "title": "", "url": "", "checked_at": ""},
    }]

    with pytest.raises(ValueError, match="glossary_invalid"):
        prerequisite_resolver.resolve(ir, pack, _request("gwas_association"), glossary=glossary)


def test_domain_mismatch_is_rejected():
    pack = _pack()
    ir = _ir(pack)
    ir["domain"] = "report"

    with pytest.raises(ValueError, match="explanation_ir_invalid"):
        prerequisite_resolver.resolve(ir, pack, _request("gwas_association"))


def test_shadow_compare_marks_personality_prerequisite_as_contract_improvement():
    pack = _pack()
    ir = _ir(pack)
    resolution = prerequisite_resolver.resolve(
        ir,
        pack,
        _request("gwas_association") + _request("polygenic_trait"),
    )
    legacy = {
        "case_id": "personality-gwas-2026-09",
        "domain": "paper",
        "findings": [{"code": "polygenic_prerequisite_missing", "severity": "p1"}],
    }

    comparison = explanation_shadow_compare.compare(legacy, ir, resolution)

    assert comparison["axes"]["prerequisite_coverage"]["outcome"] == "improved"
    assert comparison["axes"]["semantic_calibration"]["outcome"] == "improved"
    assert comparison["axes"]["final_output_quality"]["outcome"] == "not_measured"
    assert comparison["improvement_summary"] == {
        "improved": 2,
        "unchanged": 0,
        "unresolved": 0,
        "not_applicable": 2,
        "not_measured": 1,
    }


def test_shadow_compare_reports_unresolved_without_fake_percentage():
    pack = _pack()
    ir = _ir(pack)
    resolution = prerequisite_resolver.resolve(ir, pack, _request("heel_strike"))
    legacy = {
        "case_id": "heel-strike-2026-09",
        "domain": "paper",
        "findings": [{"code": "scope_expansion_exclusivity", "severity": "p0"}],
    }

    comparison = explanation_shadow_compare.compare(legacy, ir, resolution)

    assert comparison["axes"]["prerequisite_coverage"]["outcome"] == "unresolved"
    assert "improvement_percent" not in comparison
    assert comparison["non_claims"] == [
        "spoken_narration_not_generated",
        "directive_not_generated",
        "render_not_generated",
        "retention_not_measured",
    ]
    assert comparison["axes"]["semantic_calibration"]["outcome"] == "unresolved"


def test_shadow_compare_detects_repaired_evidence_trace_from_legacy_directive():
    pack = _pack()
    ir = _ir(pack)
    resolution = prerequisite_resolver.resolve(ir, pack, [])
    legacy = {
        "case_id": "samsung-memory-cycle-2026-09",
        "domain": "paper",
        "findings": [{"code": "reasoning_link_lost_before_visual", "severity": "p0"}],
    }

    comparison = explanation_shadow_compare.compare(legacy, ir, resolution)

    assert comparison["axes"]["evidence_traceability"]["outcome"] == "improved"
    assert comparison["axes"]["evidence_traceability"]["current"] == "complete_ir_trace"


def test_shadow_compare_detects_shallow_source_contract_safety():
    pack = _pack()
    pack["source"].update(
        source_depth="partial_text", source_mode="BRIEF_EXPLAINER", source_chars=1072
    )
    ir = _ir(pack)
    ir["domain"] = "report"
    pack["domain"] = "report"
    resolution = {
        "contract_version": "prerequisite-resolution-v1",
        "domain": "report",
        "content_id": ir["content_id"],
        "concepts": [],
        "unresolved_concepts": [],
        "scope_action": "KEEP",
        "warnings": [],
    }
    legacy = {
        "case_id": "nh-ai-mid-cycle-2026-09",
        "domain": "report",
        "findings": [{"code": "source_depth_overexpanded", "severity": "p0"}],
    }

    comparison = explanation_shadow_compare.compare(legacy, ir, resolution)

    assert comparison["axes"]["source_depth_safety"]["outcome"] == "improved"
    assert comparison["axes"]["source_depth_safety"]["current"] == "brief_ir_with_1_units"


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
                limitations=projected.get("limitations", []),
                attribution=projected.get("attribution", ""),
                domain_fields={},
            )
            pack["claims"].append(projected)
        else:
            projected.update(
                value=projected.get("value"),
                unit=projected.get("unit", ""),
                period=projected.get("period", ""),
                metric=projected.get("metric", ""),
                scope="company",
                basis="broker_estimate",
                attribution=projected.get("attribution", ""),
                display=projected["text"],
                comparator={},
                interpretation=projected.get("interpretation", "neutral"),
                validation={},
                source_refs=[],
            )
            projected.pop("text")
            pack["numbers"].append(projected)
    return pack


def test_six_gold_cases_compare_legacy_directives_without_claiming_final_quality():
    fixtures = Path(__file__).parent / "fixtures"
    ir_cases = json.loads((fixtures / "explanation_ir_gold_cases.json").read_text(encoding="utf-8"))
    requests = json.loads(
        (fixtures / "prerequisite_resolution_gold_cases.json").read_text(encoding="utf-8")
    )
    quality = json.loads(
        (fixtures / "explanation_quality_gold_set.json").read_text(encoding="utf-8")
    )
    request_by_id = {case["case_id"]: case["requested_concepts"] for case in requests}
    legacy_by_id = {case["case_id"]: case for case in quality["cases"]}
    comparisons = {}

    assert len(ir_cases) == len(requests) == 6
    for case in ir_cases:
        pack = _gold_pack(case)
        if case["domain"] == "paper":
            ir = paper_reasoning_adapter.build(pack)
        else:
            ir = report_reasoning_adapter.build(pack, case["financial_reasoning"])
        resolution = prerequisite_resolver.resolve(ir, pack, request_by_id[case["case_id"]])
        comparison = explanation_shadow_compare.compare(
            legacy_by_id[case["case_id"]], ir, resolution
        )
        assert comparison["axes"]["final_output_quality"]["outcome"] == "not_measured"
        assert "improvement_percent" not in comparison
        comparisons[case["case_id"]] = comparison

    assert comparisons["personality-gwas-2026-09"]["axes"][
        "prerequisite_coverage"
    ]["outcome"] == "improved"
    assert comparisons["heel-strike-2026-09"]["axes"][
        "prerequisite_coverage"
    ]["outcome"] == "unresolved"
    assert comparisons["samsung-memory-cycle-2026-09"]["axes"][
        "evidence_traceability"
    ]["outcome"] == "improved"
    assert comparisons["nh-ai-mid-cycle-2026-09"]["axes"][
        "source_depth_safety"
    ]["outcome"] == "improved"
    assert comparisons["shipbuilding-rerating-2026-09"]["axes"][
        "evidence_traceability"
    ]["outcome"] == "improved"
