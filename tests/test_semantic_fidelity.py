from __future__ import annotations

from copy import deepcopy

import pytest

from engine import (
    narrative_planner,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
    semantic_fidelity,
    spoken_narration,
)


def _scope(*, quote: bool = True, value: bool = False,
           unit: bool = False, period: bool = False,
           semantic: bool = False) -> dict[str, bool]:
    return {
        "quote_presence": quote,
        "numeric_value": value,
        "unit": unit,
        "period": period,
        "semantic_entailment": semantic,
    }


def _safe_narration(plan: dict, ir: dict, resolution: dict, pack: dict) -> dict:
    payload = {
        "beats": [{
            "beat_id": beat["beat_id"],
            "sentences": list(beat["content_points"]),
        } for beat in plan["beats"]],
    }
    return spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)


def _paper_artifacts() -> tuple[dict, dict, dict, dict, dict]:
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": "paper-semantic-1",
        "source": {
            "source_depth": "full_body",
            "source_chars": 5000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "publisher",
            "attribution": {"title": "Personality GWAS"},
        },
        "claims": [{
            "evidence_id": "paper:C01",
            "raw_ref": "claims:C01",
            "text": "1,260개 변이가 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다.",
            "claim_type": "main_result",
            "domain_role": "claim",
            "causal_strength": "association_only",
            "evidence_grade": "B",
            "verification_state": "SUPPORTED",
            "verification_scope": _scope(),
            "source_refs": [{
                "quote": "1,260 lead genetic variants associated with personality",
                "chunk_id": "chunk-1",
                "source_section": "Results",
                "source_page": None,
                "table_or_figure": None,
            }],
            "uncertainty": "association_only",
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
        core_question="변이는 성격을 결정하는가?",
        thesis="변이는 성격과 연관됐지만 결정한다고 입증하지 않았다.",
    )
    resolution = prerequisite_resolver.resolve(
        ir,
        pack,
        [{
            "concept_id": "gwas_association",
            "reason": "연관과 결정의 차이",
            "evidence_ids": ["paper:C01"],
            "required": True,
        }],
    )
    plan = narrative_planner.build(ir, resolution, pack)
    narration = _safe_narration(plan, ir, resolution, pack)
    assert narration["generation_status"] == "DRAFT_ACCEPTED"
    return pack, ir, resolution, plan, narration


def _report_artifacts() -> tuple[dict, dict, dict, dict, dict]:
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": "report",
        "content_id": "report-semantic-1",
        "source": {
            "source_depth": "full_text",
            "source_chars": 8000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "",
            "attribution": {"broker": "유안타증권", "company": "테스트기업"},
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
            "attribution": "유안타증권",
            "display": "유안타증권은 2026년 가격이 1% 상승할 것으로 전망했다.",
            "comparator": {},
            "interpretation": "projection",
            "verification_state": "SUPPORTED",
            "verification_scope": _scope(value=True, unit=True, period=True),
            "validation": {},
            "source_refs": [],
        }],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }
    financial = {
        "units": [{
            "reasoning_id": "R01",
            "unit_type": "EARNINGS_BRIDGE",
            "title": "가격 전망이 실적으로 이어지는 경로",
            "carries_thesis": True,
            "attributed_to": "유안타증권",
            "assumption": "가격 상승 유지",
            "breaks_if": "가격 하락",
            "steps": [{
                "step": 1,
                "text": "유안타증권은 2026년 가격이 1% 상승할 것으로 전망했다.",
                "fact_ids": ["num_price"],
                "source_refs": [],
            }],
        }],
    }
    ir = report_reasoning_adapter.build(pack, financial)
    resolution = prerequisite_resolver.resolve(ir, pack, [])
    plan = narrative_planner.build(ir, resolution, pack)
    narration = _safe_narration(plan, ir, resolution, pack)
    assert narration["generation_status"] == "DRAFT_ACCEPTED"
    return pack, ir, resolution, plan, narration


def test_prompt_boundary_rejects_tampered_upstream_contracts():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    bad_narration = deepcopy(narration)
    bad_narration["contract_version"] = "invented"

    with pytest.raises(ValueError, match="spoken_narration_invalid"):
        semantic_fidelity.prompt_payload(bad_narration, plan, ir, resolution, pack)

    bad_plan = deepcopy(plan)
    bad_plan["beats"].pop()
    with pytest.raises(ValueError, match="narrative_plan_invalid"):
        semantic_fidelity.prompt_payload(narration, bad_plan, ir, resolution, pack)


def test_prompt_includes_only_beat_owned_evidence_ir_and_prerequisites():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    pack["claims"].append({
        "evidence_id": "paper:C99",
        "raw_ref": "claims:C99",
        "text": "프롬프트에 들어가면 안 되는 무관한 주장",
        "claim_type": "background",
        "domain_role": "claim",
        "causal_strength": "",
        "evidence_grade": "C",
        "verification_state": "NOT_CHECKED",
        "verification_scope": _scope(quote=False),
        "source_refs": [],
        "uncertainty": None,
        "limitations": [],
        "attribution": "",
        "domain_fields": {},
    })

    payload = semantic_fidelity.prompt_payload(
        narration, plan, ir, resolution, pack
    )

    assert payload["domain"] == "paper"
    assert payload["content_id"] == "paper-semantic-1"
    assert [row["narration_id"] for row in payload["narration_beats"]] == [
        beat["narration_id"] for beat in narration["narration_beats"]
    ]
    assert [row["reasoning_id"] for row in payload["reasoning_units"]] == [
        unit["reasoning_id"] for unit in ir["reasoning_units"]
    ]
    assert [row["evidence_id"] for row in payload["evidence"]] == ["paper:C01"]
    assert payload["evidence"][0]["source_refs"][0]["quote"].startswith("1,260 lead")
    assert payload["evidence"][0]["verification_scope"]["semantic_entailment"] is False
    assert payload["reasoning_units"][0]["causal_level"] == "association_only"
    assert payload["concepts"][0]["concept_id"] == "gwas_association"
    assert payload["concepts"][0]["guardrails"]


def test_report_prompt_preserves_verified_numeric_surface_and_attribution():
    pack, ir, resolution, plan, narration = _report_artifacts()

    payload = semantic_fidelity.prompt_payload(
        narration, plan, ir, resolution, pack
    )

    evidence = payload["evidence"][0]
    assert evidence["evidence_id"] == "report:num_price"
    assert (evidence["value"], evidence["unit"], evidence["period"]) == (1, "%", "2026F")
    assert evidence["verification_scope"] == _scope(value=True, unit=True, period=True)
    assert evidence["attribution"] == "유안타증권"
    assert payload["reasoning_units"][0]["attribution"] == "유안타증권"


def test_prompt_inputs_are_immutable():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    before = deepcopy((pack, ir, resolution, plan, narration))

    semantic_fidelity.prompt_payload(narration, plan, ir, resolution, pack)

    assert (pack, ir, resolution, plan, narration) == before
