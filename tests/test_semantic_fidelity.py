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
    semantic_fidelity_shadow_compare,
    spoken_narration,
)


FIXTURES = Path(__file__).parent / "fixtures"


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


def _blocked_paper_artifacts() -> tuple[dict, dict, dict, dict, dict]:
    pack, ir, _, _, _ = _paper_artifacts()
    resolution = prerequisite_resolver.resolve(
        ir,
        pack,
        [{
            "concept_id": "unknown_mechanism",
            "reason": "원문에 없는 기전",
            "evidence_ids": [],
            "required": True,
        }],
    )
    plan = narrative_planner.build(ir, resolution, pack)
    blocked = spoken_narration.normalize_draft(
        {"beats": []}, plan, ir, resolution, pack
    )
    assert blocked["generation_status"] == "BLOCKED_UPSTREAM"
    return pack, ir, resolution, plan, blocked


def _critic_payload(narration: dict) -> dict:
    clauses = []
    for beat in narration["narration_beats"]:
        for sentence_index, sentence in enumerate(beat["sentences"], 1):
            is_hook = beat["stage"] == "HOOK"
            clauses.append({
                "narration_id": beat["narration_id"],
                "sentence_index": sentence_index,
                "clause_text": sentence,
                "clause_kind": "RHETORICAL" if is_hook else "FACTUAL",
                "verdict": "RHETORICAL" if is_hook else "ENTAILED",
                "evidence_ids": [] if is_hook else list(beat["evidence_ids"]),
                "finding_codes": [],
                "rationale": "핵심 질문" if is_hook else "인용 근거가 직접 뒷받침한다.",
            })
    return {"clauses": clauses}


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


def test_normalize_review_assigns_canonical_shape_trace_and_metrics():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    payload = _critic_payload(narration)
    before = deepcopy((pack, ir, resolution, plan, narration, payload))

    first = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, pack
    )
    second = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, pack
    )

    assert first == second
    assert first["contract_version"] == "semantic-fidelity-v1"
    assert first["qa_status"] == "PASSED"
    assert first["critic"] == {
        "independence": "separate_call",
        "semantic_entailment": "PASSED",
    }
    assert [row["clause_id"] for row in first["clauses"]] == ["SC01", "SC02", "SC03"]
    assert first["clauses"][0]["beat_id"] == "NB01"
    assert first["clauses"][0]["reasoning_ids"] == []
    assert first["clauses"][1]["concept_ids"] == ["gwas_association"]
    assert first["clauses"][1]["knowledge_refs"]
    assert first["clauses"][1]["raw_refs"] == []
    assert first["clauses"][2]["raw_refs"] == ["claims:C01"]
    assert first["clauses"][2]["reasoning_ids"] == ["XR01"]
    assert first["qa"]["metrics"] == {
        "clause_count": 3,
        "sentence_count": 3,
        "verdict_counts": {"ENTAILED": 2, "RHETORICAL": 1},
    }
    assert semantic_fidelity.validate(
        first, narration, plan, ir, resolution, pack
    ) == []
    assert (pack, ir, resolution, plan, narration, payload) == before


@pytest.mark.parametrize("mutation", ["omit", "reverse", "duplicate"])
def test_clause_coverage_rejects_omitted_or_reordered_text(mutation: str):
    pack, ir, resolution, plan, narration = _paper_artifacts()
    payload = _critic_payload(narration)
    source = narration["narration_beats"][-1]["sentences"][0]
    assert source == "1,260개 변이가 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다."
    original = payload["clauses"][-1]
    first = {**original, "clause_text": "1,260개 변이가 성격과 연관됐지만"}
    second = {**original, "clause_text": "성격을 결정한다고 입증하지 않았다."}
    replacement = {
        "omit": [first],
        "reverse": [second, first],
        "duplicate": [first, second, second],
    }[mutation]
    payload["clauses"][-1:] = replacement

    result = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, pack
    )

    assert result["qa_status"] == "CRITIC_ERROR"
    assert result["critic"]["semantic_entailment"] == "NOT_CHECKED"
    assert result["clauses"] == []
    assert any(error.startswith("clause_coverage_invalid:SN03:1")
               for error in result["qa"]["errors"])


@pytest.mark.parametrize(("verdict", "finding"), [
    ("CONTRADICTED", "contradiction"),
    ("UNSUPPORTED", "unsupported_background"),
    ("UNVERIFIABLE", "missing_qualifier"),
])
def test_negative_semantic_verdicts_reject_without_critic_error(
    verdict: str, finding: str,
):
    pack, ir, resolution, plan, narration = _paper_artifacts()
    payload = _critic_payload(narration)
    payload["clauses"][-1]["verdict"] = verdict
    payload["clauses"][-1]["finding_codes"] = [finding]

    result = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, pack
    )

    assert result["qa_status"] == "REJECTED"
    assert result["critic"]["semantic_entailment"] == "FAILED"
    assert result["clauses"][-1]["verdict"] == verdict
    assert finding in result["clauses"][-1]["finding_codes"]


def test_entailed_clause_requires_eligible_beat_owned_support():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    payload = _critic_payload(narration)

    quote_only = deepcopy(pack)
    quote_only["claims"][0]["source_refs"] = []
    result = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, quote_only
    )
    assert result["qa_status"] == "REJECTED"
    assert "support_surface_ineligible:SC03:paper:C01" in result["qa"]["errors"]

    for state in ("UNSUPPORTED", "STALE"):
        disallowed = deepcopy(pack)
        disallowed["claims"][0]["verification_state"] = state
        with pytest.raises(ValueError, match="explanation_ir_invalid:evidence_state_disallowed"):
            semantic_fidelity.normalize_review(
                payload, narration, plan, ir, resolution, disallowed
            )

    other_beat = deepcopy(pack)
    other_beat["claims"].append({
        **deepcopy(other_beat["claims"][0]),
        "evidence_id": "paper:C99",
        "raw_ref": "claims:C99",
        "text": "다른 비트의 근거",
    })
    laundered = deepcopy(payload)
    laundered["clauses"][-1]["evidence_ids"] = ["paper:C99"]
    result = semantic_fidelity.normalize_review(
        laundered, narration, plan, ir, resolution, other_beat
    )
    assert result["qa_status"] == "CRITIC_ERROR"
    assert "evidence_ref_outside_beat:SN03:paper:C99" in result["qa"]["errors"]


def test_verified_report_numeric_surface_can_support_entailed_clause():
    pack, ir, resolution, plan, narration = _report_artifacts()

    result = semantic_fidelity.normalize_review(
        _critic_payload(narration), narration, plan, ir, resolution, pack
    )

    assert result["qa_status"] == "PASSED"
    assert result["clauses"][-1]["evidence_ids"] == ["report:num_price"]


def test_rhetorical_exemption_is_only_for_pure_grounded_hook_question():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    safe = semantic_fidelity.normalize_review(
        _critic_payload(narration), narration, plan, ir, resolution, pack
    )
    assert safe["qa_status"] == "PASSED"

    non_hook = _critic_payload(narration)
    non_hook["clauses"][-1].update(
        clause_kind="RHETORICAL", verdict="RHETORICAL", evidence_ids=[]
    )
    result = semantic_fidelity.normalize_review(
        non_hook, narration, plan, ir, resolution, pack
    )
    assert result["qa_status"] == "REJECTED"
    assert "rhetorical_exemption_invalid:SC03" in result["qa"]["errors"]

    cited_hook = _critic_payload(narration)
    cited_hook["clauses"][0]["evidence_ids"] = ["paper:C01"]
    result = semantic_fidelity.normalize_review(
        cited_hook, narration, plan, ir, resolution, pack
    )
    assert result["qa_status"] == "CRITIC_ERROR"
    assert "evidence_ref_outside_beat:SN01:paper:C01" in result["qa"]["errors"]

    factual_hook = _critic_payload(narration)
    factual_hook["clauses"][0].update(
        clause_kind="FACTUAL", verdict="ENTAILED", evidence_ids=[]
    )
    result = semantic_fidelity.normalize_review(
        factual_hook, narration, plan, ir, resolution, pack
    )
    assert result["qa_status"] == "REJECTED"
    assert result["clauses"][0]["finding_codes"] == ["unsupported_factual_hook"]


@pytest.mark.parametrize(("label", "finding", "domain"), [
    ("heel_scope", "scope_expansion", "paper"),
    ("retinotopic_transfer", "unsupported_background", "paper"),
    ("personality_determination", "causal_upgrade", "paper"),
    ("shipbuilding_replacement", "unsupported_background", "paper"),
    ("broker_projection", "attribution_loss", "report"),
])
def test_semantic_scope_causal_and_attribution_failures_remain_distinct(
    label: str, finding: str, domain: str,
):
    artifacts = _paper_artifacts() if domain == "paper" else _report_artifacts()
    pack, ir, resolution, plan, narration = artifacts
    payload = _critic_payload(narration)
    payload["clauses"][-1]["verdict"] = "UNSUPPORTED"
    payload["clauses"][-1]["finding_codes"] = [finding]
    payload["clauses"][-1]["rationale"] = label

    result = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, pack
    )

    assert result["qa_status"] == "REJECTED"
    assert result["clauses"][-1]["finding_codes"] == [finding]
    assert result["clauses"][-1]["rationale"] == label


def test_validate_recomputes_status_metrics_and_trace():
    pack, ir, resolution, plan, narration = _paper_artifacts()
    passed = semantic_fidelity.normalize_review(
        _critic_payload(narration), narration, plan, ir, resolution, pack
    )
    assert passed["qa_status"] == "PASSED"

    verdict = deepcopy(passed)
    verdict["clauses"][-1]["verdict"] = "UNSUPPORTED"
    assert "qa_status_stale" in semantic_fidelity.validate(
        verdict, narration, plan, ir, resolution, pack
    )

    evidence = deepcopy(passed)
    evidence["clauses"][-1]["evidence_ids"] = ["paper:C99"]
    assert "evidence_ref_unknown:SC03:paper:C99" in semantic_fidelity.validate(
        evidence, narration, plan, ir, resolution, pack
    )

    status = deepcopy(passed)
    status["qa_status"] = "REJECTED"
    assert "qa_status_stale" in semantic_fidelity.validate(
        status, narration, plan, ir, resolution, pack
    )

    summary = deepcopy(passed)
    summary["critic"]["semantic_entailment"] = "FAILED"
    assert "semantic_entailment_stale" in semantic_fidelity.validate(
        summary, narration, plan, ir, resolution, pack
    )

    metrics = deepcopy(passed)
    metrics["qa"]["metrics"]["clause_count"] = 999
    assert "qa_metrics_stale" in semantic_fidelity.validate(
        metrics, narration, plan, ir, resolution, pack
    )


def test_upstream_nonaccepted_states_never_call_critic():
    blocked_pack, blocked_ir, blocked_resolution, blocked_plan, blocked = (
        _blocked_paper_artifacts()
    )
    calls = []
    result = semantic_fidelity.review(
        blocked, blocked_plan, blocked_ir, blocked_resolution, blocked_pack,
        caller=lambda **kwargs: calls.append(kwargs),
    )
    assert result["qa_status"] == "BLOCKED_UPSTREAM"

    pack, ir, resolution, plan, _ = _paper_artifacts()
    rejected = spoken_narration.normalize_draft(
        {"beats": [{"beat_id": beat["beat_id"], "sentences": []}
                   for beat in plan["beats"]]},
        plan, ir, resolution, pack,
    )
    assert rejected["generation_status"] == "REJECTED_DRAFT"
    result = semantic_fidelity.review(
        rejected, plan, ir, resolution, pack,
        caller=lambda **kwargs: calls.append(kwargs),
    )
    assert result["qa_status"] == "REJECTED_UPSTREAM"
    tampered = deepcopy(rejected)
    tampered["narration_beats"][0]["reasoning_ids"] = ["XR999"]
    with pytest.raises(ValueError, match="rejected_draft_not_canonical"):
        semantic_fidelity.review(
            tampered, plan, ir, resolution, pack,
            caller=lambda **kwargs: calls.append(kwargs),
        )
    assert calls == []


def test_independent_critic_invocation_uses_selfcheck_model_and_constrained_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    pack, ir, resolution, plan, narration = _paper_artifacts()
    captured = {}
    purposes = []

    def caller(**kwargs):
        captured.update(kwargs)
        return _critic_payload(narration)

    monkeypatch.setattr(semantic_fidelity, "set_text_purpose", purposes.append)
    result = semantic_fidelity.review(
        narration, plan, ir, resolution, pack, caller=caller
    )

    assert result["qa_status"] == "PASSED"
    assert purposes == ["semantic_fidelity_shadow"]
    assert captured["model"] == config.MODEL_SELFCHECK
    assert captured["max_tokens"] == config.LLM_SELFCHECK_MAX_TOKENS
    assert json.loads(captured["user"]) == semantic_fidelity.prompt_payload(
        narration, plan, ir, resolution, pack
    )
    assert "qa_status" not in json.loads(captured["user"])


def test_critic_exception_returns_error_without_passed_clauses():
    pack, ir, resolution, plan, narration = _paper_artifacts()

    def boom(**kwargs):
        raise RuntimeError("critic unavailable")

    result = semantic_fidelity.review(
        narration, plan, ir, resolution, pack, caller=boom
    )

    assert result["qa_status"] == "CRITIC_ERROR"
    assert result["critic"]["semantic_entailment"] == "NOT_CHECKED"
    assert result["clauses"] == []
    assert result["qa"]["errors"] == ["critic_call_failed:RuntimeError"]


@pytest.mark.parametrize("payload", [
    None,
    [],
    {},
    {"clauses": None},
    {"clauses": {}},
])
def test_malformed_critic_payload_returns_deterministic_error(payload):
    pack, ir, resolution, plan, narration = _paper_artifacts()

    result = semantic_fidelity.review(
        narration, plan, ir, resolution, pack, caller=lambda **kwargs: payload
    )

    assert result["qa_status"] == "CRITIC_ERROR"
    assert result["clauses"] == []
    assert result["qa"]["errors"] == ["critic_clauses_not_list"]


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


def _gold_artifacts() -> list[tuple[dict, dict, dict, dict, dict]]:
    cases = json.loads(
        (FIXTURES / "explanation_ir_gold_cases.json").read_text(encoding="utf-8")
    )
    requests = json.loads(
        (FIXTURES / "prerequisite_resolution_gold_cases.json").read_text(
            encoding="utf-8"
        )
    )
    quality = json.loads(
        (FIXTURES / "explanation_quality_gold_set.json").read_text(encoding="utf-8")
    )
    request_by_id = {row["case_id"]: row["requested_concepts"] for row in requests}
    legacy_by_id = {row["case_id"]: row for row in quality["cases"]}
    artifacts = []
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
        artifacts.append((legacy_by_id[case["case_id"]], pack, ir, resolution, plan))
    return artifacts


def test_six_gold_cases_have_deterministic_phase7_status_and_call_accounting():
    statuses = {}
    critic_call_counts = {}
    comparisons = {}
    for legacy, pack, ir, resolution, plan in _gold_artifacts():
        narration = spoken_narration.normalize_draft(
            {
                "beats": [
                    {
                        "beat_id": beat["beat_id"],
                        "sentences": list(beat["content_points"]),
                    }
                    for beat in plan["beats"]
                ]
            },
            plan,
            ir,
            resolution,
            pack,
        )
        calls = []

        def critic(**kwargs):
            calls.append(kwargs)
            return _critic_payload(narration)

        fidelity = semantic_fidelity.review(
            narration, plan, ir, resolution, pack, caller=critic
        )
        case_id = legacy["case_id"]
        statuses[case_id] = fidelity["qa_status"]
        critic_call_counts[case_id] = len(calls)
        comparisons[case_id] = semantic_fidelity_shadow_compare.compare(
            legacy, fidelity, narration, plan, ir, resolution, pack
        )

    assert statuses == {
        "heel-strike-2026-09": "BLOCKED_UPSTREAM",
        "deaf-retinotopic-remap-2026-09": "BLOCKED_UPSTREAM",
        "personality-gwas-2026-09": "REJECTED",
        "samsung-memory-cycle-2026-09": "BLOCKED_UPSTREAM",
        "nh-ai-mid-cycle-2026-09": "BLOCKED_UPSTREAM",
        "shipbuilding-rerating-2026-09": "BLOCKED_UPSTREAM",
    }
    assert critic_call_counts == {
        "heel-strike-2026-09": 0,
        "deaf-retinotopic-remap-2026-09": 0,
        "personality-gwas-2026-09": 1,
        "samsung-memory-cycle-2026-09": 0,
        "nh-ai-mid-cycle-2026-09": 0,
        "shipbuilding-rerating-2026-09": 0,
    }
    for comparison in comparisons.values():
        assert comparison["axes"]["final_directive_quality"]["outcome"] == "not_measured"
        assert "improvement_percent" not in comparison
    assert comparisons["personality-gwas-2026-09"]["axes"][
        "semantic_entailment"
    ]["outcome"] == "failed"


def test_phase7_shadow_comparison_validates_legacy_identity_and_findings():
    legacy, pack, ir, resolution, plan = next(
        row for row in _gold_artifacts()
        if row[0]["case_id"] == "personality-gwas-2026-09"
    )
    narration = _safe_narration(plan, ir, resolution, pack)
    fidelity = semantic_fidelity.normalize_review(
        _critic_payload(narration), narration, plan, ir, resolution, pack
    )

    bad_domain = deepcopy(legacy)
    bad_domain["domain"] = "report"
    with pytest.raises(ValueError, match="legacy_case_invalid:domain_mismatch"):
        semantic_fidelity_shadow_compare.compare(
            bad_domain, fidelity, narration, plan, ir, resolution, pack
        )
    bad_findings = deepcopy(legacy)
    bad_findings["findings"] = []
    with pytest.raises(ValueError, match="legacy_case_invalid"):
        semantic_fidelity_shadow_compare.compare(
            bad_findings, fidelity, narration, plan, ir, resolution, pack
        )


@pytest.mark.parametrize(("finding", "failed_axis"), [
    ("scope_expansion", "scope_calibration"),
    ("causal_upgrade", "causal_calibration"),
    ("missing_qualifier", "qualifier_preservation"),
    ("attribution_loss", "attribution_preservation"),
])
def test_phase7_shadow_comparison_preserves_synthetic_failure_axes(
    finding: str, failed_axis: str,
):
    pack, ir, resolution, plan, narration = _paper_artifacts()
    payload = _critic_payload(narration)
    payload["clauses"][-1].update(
        verdict="UNSUPPORTED",
        finding_codes=[finding],
        rationale=f"synthetic:{finding}",
    )
    fidelity = semantic_fidelity.normalize_review(
        payload, narration, plan, ir, resolution, pack
    )
    legacy = {
        "case_id": pack["content_id"],
        "domain": pack["domain"],
        "title": "synthetic",
        "source": {"depth": "full_body", "chars": 5000},
        "output": {"duration_sec": 1, "cut_count": 1, "render_review": "not_audited"},
        "ratings": {
            "source_adequacy": "not_audited",
            "fact_fidelity": "not_audited",
            "reasoning_quality": "not_audited",
            "explanation_quality": "not_audited",
            "script_coherence": "not_audited",
            "narration_naturalness": "not_audited",
            "visual_explanatory_power": "not_audited",
            "visual_narration_alignment": "not_audited",
            "pacing": "not_audited",
            "uncertainty_calibration": "not_audited",
        },
        "findings": [{
            "code": finding,
            "stage": "script",
            "severity": "p0",
            "observed": "synthetic failure",
            "expected": "reject",
            "evidence": ["fixed critic payload"],
        }],
    }

    comparison = semantic_fidelity_shadow_compare.compare(
        legacy, fidelity, narration, plan, ir, resolution, pack
    )

    assert comparison["qa_status"] == "REJECTED"
    assert comparison["axes"][failed_axis]["outcome"] == "failed"
    assert comparison["axes"]["final_directive_quality"]["outcome"] == "not_measured"
    assert "improvement_percent" not in comparison
