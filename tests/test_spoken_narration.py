from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine import (
    narrative_planner,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
    spoken_narration,
    spoken_narration_shadow_compare,
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


def _paper_ready() -> tuple[dict, dict, dict, dict]:
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": "paper-1",
        "source": {
            "source_depth": "full_body",
            "source_chars": 5000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "",
            "attribution": {},
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
            "source_refs": [],
            "uncertainty": None,
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
            "reason": "연관 해석",
            "evidence_ids": ["paper:C01"],
            "required": True,
        }],
    )
    plan = narrative_planner.build(ir, resolution, pack)
    return pack, ir, resolution, plan


def _report_ready() -> tuple[dict, dict, dict, dict]:
    pack = {
        "contract_version": "evidence-pack-v1",
        "domain": "report",
        "content_id": "report-1",
        "source": {
            "source_depth": "full_text",
            "source_chars": 8000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "",
            "attribution": {"broker": "유안타증권"},
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
            "interpretation": "neutral",
            "verification_state": "SUPPORTED",
            "verification_scope": {
                "quote_presence": True,
                "numeric_value": True,
                "unit": True,
                "period": True,
                "semantic_entailment": False,
            },
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
    return pack, ir, resolution, plan


def _safe_payload(plan: dict) -> dict:
    return {
        "beats": [{
            "beat_id": beat["beat_id"],
            "sentences": list(beat["content_points"]),
        } for beat in plan["beats"]],
    }


def test_ready_payload_normalizes_shape_and_injects_exact_plan_trace():
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    payload["beats"][0]["narration_id"] = "MODEL-ID"
    payload["beats"][0]["evidence_ids"] = ["invented"]
    before = deepcopy((pack, ir, resolution, plan, payload))

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["contract_version"] == "spoken-narration-v1"
    assert result["generation_status"] == "DRAFT_ACCEPTED"
    assert result["qa"]["semantic_entailment"] == "NOT_CHECKED"
    assert [row["narration_id"] for row in result["narration_beats"]] == [
        f"SN{i:02d}" for i in range(1, len(plan["beats"]) + 1)
    ]
    assert result["narration_beats"][0]["evidence_ids"] == plan["beats"][0]["evidence_ids"]
    assert result["narration_beats"][-1]["reasoning_ids"] == plan["beats"][-1]["reasoning_ids"]
    assert (pack, ir, resolution, plan, payload) == before


def test_blocked_plan_returns_before_caller_invocation():
    pack, ir, resolution, _ = _paper_ready()
    resolution["concepts"][0].update(
        status="UNRESOLVED", simple_explanation="", knowledge_refs=[]
    )
    resolution["unresolved_concepts"] = ["gwas_association"]
    resolution["scope_action"] = "NARROW_SCOPE"
    plan = narrative_planner.build(ir, resolution, pack)
    calls = []

    result = spoken_narration.generate(
        plan, ir, resolution, pack, caller=lambda **kwargs: calls.append(kwargs)
    )

    assert result["generation_status"] == "BLOCKED_UPSTREAM"
    assert result["narration_beats"] == []
    assert calls == []


def test_malformed_upstream_contract_fails_before_model_call():
    pack, ir, resolution, plan = _paper_ready()
    plan["contract_version"] = "made-up"
    calls = []

    with pytest.raises(ValueError, match="narrative_plan_invalid"):
        spoken_narration.generate(
            plan, ir, resolution, pack, caller=lambda **kwargs: calls.append(kwargs)
        )

    assert calls == []


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered", "unknown", "empty"])
def test_invalid_model_beat_coverage_rejects_draft(mutation: str):
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    if mutation == "missing":
        payload["beats"].pop()
    elif mutation == "duplicate":
        payload["beats"][-1]["beat_id"] = payload["beats"][0]["beat_id"]
    elif mutation == "reordered":
        payload["beats"][0], payload["beats"][1] = payload["beats"][1], payload["beats"][0]
    elif mutation == "unknown":
        payload["beats"][0]["beat_id"] = "NB99"
    else:
        payload["beats"][0]["sentences"] = []

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "REJECTED_DRAFT"
    assert result["qa"]["errors"]


def test_generate_uses_only_constrained_prompt_payload():
    pack, ir, resolution, plan = _report_ready()
    captured = {}

    def caller(**kwargs):
        captured.update(kwargs)
        return _safe_payload(plan)

    result = spoken_narration.generate(plan, ir, resolution, pack, caller=caller)

    assert result["generation_status"] == "DRAFT_ACCEPTED"
    assert "full_text" not in captured["user"]
    assert "source_quote" not in captured["user"]
    assert "report:num_price" not in captured["user"]
    assert captured["model"]
    assert captured["max_tokens"] <= 8192


@pytest.mark.parametrize(
    ("replacement", "error_prefix"),
    [
        ("1,260명 변이가 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다.",
         "numbers_changed:NB03"),
        ("변이가 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다.",
         "numbers_changed:NB03"),
        ("1,260개 변이와 2개 유전자가 성격과 연관됐다.",
         "numbers_changed:NB03"),
        ("1,260개 변이가 모든 사람의 성격과 연관됐지만 결정한다고 입증하지 않았다.",
         "scope_intensifier_added:NB03"),
        ("1,260개 변이가 성격을 결정한다.",
         "association_upgraded:NB03"),
        ("1,260개 변이가 성격과 연관됐다.",
         "protected_meaning_changed:NB03"),
    ],
)
def test_paper_semantic_drift_rejects_draft(replacement: str, error_prefix: str):
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    payload["beats"][-1]["sentences"] = [replacement]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "REJECTED_DRAFT"
    assert any(error.startswith(error_prefix) for error in result["qa"]["errors"])


def test_report_attribution_and_uncertainty_must_remain_spoken():
    pack, ir, resolution, plan = _report_ready()
    payload = _safe_payload(plan)
    payload["beats"][-1]["sentences"] = ["2026년 가격이 1% 상승한다."]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "REJECTED_DRAFT"
    assert "attribution_dropped:NB02:유안타증권" in result["qa"]["errors"]
    assert any(error.startswith("protected_meaning_changed:NB02")
               for error in result["qa"]["errors"])


def test_non_question_hook_is_restored_to_the_approved_core_question():
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    payload["beats"][0]["sentences"] = ["변이는 성격을 결정한다."]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "DRAFT_ACCEPTED"
    assert result["narration_beats"][0]["sentences"] == [plan["core_question"]]
    assert result["repairs"] == [{
        "beat_id": "NB01",
        "repair": "hook_restored_to_core_question",
        "model_sentences": ["변이는 성격을 결정한다."],
    }]
    assert spoken_narration.validate(result, plan, ir, resolution, pack) == []


def test_hook_may_change_only_the_question_ending():
    pack, ir, resolution, plan = _paper_ready()
    core = plan["core_question"]
    spoken = core.rstrip("?").removesuffix("는가") + "는 걸까요?"
    assert spoken != core
    payload = _safe_payload(plan)
    payload["beats"][0]["sentences"] = [spoken]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "DRAFT_ACCEPTED"
    assert result["narration_beats"][0]["sentences"] == [spoken]
    assert result["repairs"] == []


@pytest.mark.parametrize("text, expected", [
    ("이 연구는 무엇을 보여 주는가?", True),
    ("이 연구는 무엇을 보여 주는 걸까요?", True),
    ("이 연구는 무엇을 보여 주나요?", True),
    ("이 연구는 무엇을 보여주는가 ?", True),
    ("이 연구는 무엇을 증명하는 걸까요?", False),
    ("인간만 발뒤꿈치로 걷는 이유를 이 연구는 무엇을 보여 주는가?", False),
    ("이 연구는 무엇을 보여 주는가? 정답은 충격이다.", False),
    ("이 연구는 무엇을 보여 주는가? 그렇지?", False),
    ("이 연구는 무엇을 보여 주는가.", False),
    ("", False),
])
def test_hook_matches_core_question_allows_only_ending_changes(text, expected):
    assert spoken_narration.hook_matches_core_question(
        text, "이 연구는 무엇을 보여 주는가?"
    ) is expected


def test_validation_rejects_factual_narration_with_no_trace():
    pack, ir, resolution, plan = _paper_ready()
    result = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )
    factual = result["narration_beats"][-1]
    factual["reasoning_ids"] = []
    factual["evidence_ids"] = []
    factual["raw_refs"] = []

    errors = spoken_narration.validate(result, plan, ir, resolution, pack)

    assert "factual_trace_missing:NB03" in errors


def test_spoken_structure_heuristics_warn_without_claiming_entailment():
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    payload["beats"][1]["sentences"] = [
        plan["beats"][1]["content_points"][0] + " 본 연구에서 관찰되었다고 할 수 있습니다."
    ]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "DRAFT_ACCEPTED"
    # 도입 질문은 정규화에서 한 문장으로 되돌려지므로, 반복 경고는 가드에 직접 확인한다.
    doubled = [dict(beat) for beat in result["narration_beats"]]
    doubled[0]["sentences"] = [plan["core_question"], plan["core_question"]]
    _, guard_warnings, _ = spoken_narration._draft_guard_findings(doubled, plan)
    assert "core_question_repeated" in guard_warnings
    assert "sentence_too_long:NB02" in result["qa"]["warnings"]
    assert "academic_register:NB02" in result["qa"]["warnings"]
    assert "unexplained_abbreviation:NB02:GWAS" in result["qa"]["warnings"]
    assert result["qa"]["semantic_entailment"] == "NOT_CHECKED"


def test_safe_polish_changes_expression_but_preserves_trace_and_input():
    pack, ir, resolution, plan = _paper_ready()
    draft = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )
    before = deepcopy(draft)
    payload = {"beats": [{
        "beat_id": beat["beat_id"],
        "sentences": deepcopy(beat["sentences"]),
    } for beat in draft["narration_beats"]]}
    payload["beats"][1]["sentences"] = [
        payload["beats"][1]["sentences"][0].replace("연구다.", "연구입니다.")
    ]

    polished = spoken_narration.apply_polish(
        draft, payload, plan, ir, resolution, pack
    )

    assert polished["polish"]["applied"] == ["NB02"]
    assert polished["polish"]["rejected"] == []
    assert polished["narration_beats"][1]["sentences"] == payload["beats"][1]["sentences"]
    assert polished["narration_beats"][1]["knowledge_refs"] == plan["beats"][1]["knowledge_refs"]
    assert draft == before


@pytest.mark.parametrize(
    ("domain", "replacement", "expected_reason"),
    [
        ("paper", "1,260명 변이가 성격과 연관됐지만 결정한다고 입증하지 않았다.",
         "polish_numbers_changed"),
        ("paper", "1,260개 변이가 성격을 결정한다.",
         "polish_meaning_changed"),
        ("paper", "", "polish_empty"),
        ("report", "2026년 가격이 1% 상승할 것으로 전망했다.",
         "attribution_dropped"),
    ],
)
def test_unsafe_polish_is_rejected_and_original_sentences_remain(
    domain: str, replacement: str, expected_reason: str
):
    pack, ir, resolution, plan = _paper_ready() if domain == "paper" else _report_ready()
    draft = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )
    target_index = len(draft["narration_beats"]) - 1
    original = deepcopy(draft["narration_beats"][target_index]["sentences"])
    payload = {"beats": [{
        "beat_id": beat["beat_id"],
        "sentences": deepcopy(beat["sentences"]),
    } for beat in draft["narration_beats"]]}
    payload["beats"][target_index]["sentences"] = [replacement] if replacement else []

    polished = spoken_narration.apply_polish(
        draft, payload, plan, ir, resolution, pack
    )

    assert polished["polish"]["applied"] == []
    assert any(expected_reason in row["reason"] for row in polished["polish"]["rejected"])
    assert polished["narration_beats"][target_index]["sentences"] == original


def test_polish_requires_exact_beat_coverage():
    pack, ir, resolution, plan = _paper_ready()
    draft = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )
    payload = {"beats": [{
        "beat_id": beat["beat_id"], "sentences": beat["sentences"]
    } for beat in draft["narration_beats"][:-1]]}

    polished = spoken_narration.apply_polish(
        draft, payload, plan, ir, resolution, pack
    )

    assert polished["polish"]["applied"] == []
    assert polished["polish"]["rejected"] == [{
        "beat_id": "*", "reason": "polish_beat_coverage_invalid"
    }]
    assert polished["narration_beats"] == draft["narration_beats"]


@pytest.mark.parametrize("status", ["REJECTED_DRAFT", "BLOCKED_UPSTREAM"])
def test_polish_refuses_nonaccepted_drafts(status: str):
    pack, ir, resolution, plan = _paper_ready()
    draft = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )
    draft["generation_status"] = status

    with pytest.raises(ValueError, match="narration_not_accepted"):
        spoken_narration.apply_polish(draft, {"beats": []}, plan, ir, resolution, pack)


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
        (FIXTURES / "prerequisite_resolution_gold_cases.json").read_text(encoding="utf-8")
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


def test_shadow_comparison_reports_phase6_axes_without_final_quality_claims():
    legacy, pack, ir, resolution, plan = next(
        row for row in _gold_artifacts() if row[0]["case_id"] == "personality-gwas-2026-09"
    )
    narration = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )

    comparison = spoken_narration_shadow_compare.compare(
        legacy, narration, plan, ir, resolution, pack
    )

    assert comparison["axes"]["plan_coverage"]["outcome"] == "passed"
    assert comparison["axes"]["stable_trace"]["outcome"] == "passed"
    assert comparison["axes"]["prerequisite_order"]["outcome"] == "passed"
    assert comparison["axes"]["hook_grounding"]["outcome"] == "passed"
    assert comparison["axes"]["qualifier_preservation"]["outcome"] == "passed"
    assert comparison["axes"]["semantic_entailment"]["outcome"] == "not_measured"
    assert comparison["axes"]["final_directive_quality"]["outcome"] == "not_measured"
    assert "improvement_percent" not in comparison


def test_shadow_comparison_rejects_legacy_identity_mismatch():
    pack, ir, resolution, plan = _paper_ready()
    narration = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )

    with pytest.raises(ValueError, match="legacy_case_invalid:domain_mismatch"):
        spoken_narration_shadow_compare.compare(
            {"case_id": "paper-1", "domain": "report", "findings": []},
            narration, plan, ir, resolution, pack,
        )
    with pytest.raises(ValueError, match="legacy_case_invalid:content_id_mismatch"):
        spoken_narration_shadow_compare.compare(
            {"case_id": "wrong", "domain": "paper", "findings": []},
            narration, plan, ir, resolution, pack,
        )


def test_six_gold_cases_have_deterministic_phase6_status_and_zero_blocked_calls():
    statuses = {}
    call_counts = {}
    comparisons = {}
    for legacy, pack, ir, resolution, plan in _gold_artifacts():
        calls = []

        def caller(**kwargs):
            calls.append(kwargs)
            return _safe_payload(plan)

        narration = spoken_narration.generate(
            plan, ir, resolution, pack, caller=caller
        )
        comparison = spoken_narration_shadow_compare.compare(
            legacy, narration, plan, ir, resolution, pack
        )
        case_id = legacy["case_id"]
        statuses[case_id] = narration["generation_status"]
        call_counts[case_id] = len(calls)
        comparisons[case_id] = comparison

    assert statuses == {
        "heel-strike-2026-09": "BLOCKED_UPSTREAM",
        "deaf-retinotopic-remap-2026-09": "BLOCKED_UPSTREAM",
        "personality-gwas-2026-09": "DRAFT_ACCEPTED",
        "samsung-memory-cycle-2026-09": "BLOCKED_UPSTREAM",
        "nh-ai-mid-cycle-2026-09": "BLOCKED_UPSTREAM",
        "shipbuilding-rerating-2026-09": "BLOCKED_UPSTREAM",
    }
    assert call_counts == {
        "heel-strike-2026-09": 0,
        "deaf-retinotopic-remap-2026-09": 0,
        "personality-gwas-2026-09": 1,
        "samsung-memory-cycle-2026-09": 0,
        "nh-ai-mid-cycle-2026-09": 0,
        "shipbuilding-rerating-2026-09": 0,
    }
    for comparison in comparisons.values():
        assert comparison["axes"]["semantic_entailment"]["outcome"] == "not_measured"
        assert comparison["axes"]["final_directive_quality"]["outcome"] == "not_measured"


def test_phase6_boundary_rejects_required_setup_deleted_from_canonical_plan():
    pack, ir, resolution, plan = _paper_ready()
    plan["beats"].pop(1)
    for position, beat in enumerate(plan["beats"], 1):
        beat["beat_id"] = f"NB{position:02d}"
    calls = []

    with pytest.raises(ValueError, match="plan_not_canonical"):
        spoken_narration.generate(
            plan, ir, resolution, pack, caller=lambda **kwargs: calls.append(kwargs)
        )

    assert calls == []


def test_direct_normalization_of_blocked_plan_stays_blocked():
    blocked = [row for row in _gold_artifacts() if row[-1]["planning_status"] != "READY"]

    for _, pack, ir, resolution, plan in blocked:
        result = spoken_narration.normalize_draft(
            {"beats": []}, plan, ir, resolution, pack
        )
        assert result["generation_status"] == "BLOCKED_UPSTREAM"
        assert result["narration_beats"] == []


def test_validation_recomputes_guards_and_rejects_stale_qa_or_status():
    pack, ir, resolution, plan = _paper_ready()
    narration = spoken_narration.normalize_draft(
        _safe_payload(plan), plan, ir, resolution, pack
    )
    narration["narration_beats"][-1]["sentences"] = ["999개 변이가 성격을 결정한다."]

    errors = spoken_narration.validate(narration, plan, ir, resolution, pack)

    assert "qa_errors_stale" in errors
    assert "accepted_draft_has_guard_errors" in errors
    with pytest.raises(ValueError, match="spoken_narration_invalid"):
        spoken_narration_shadow_compare.compare(
            {"case_id": "paper-1", "domain": "paper", "findings": []},
            narration, plan, ir, resolution, pack,
        )

    clean = spoken_narration.normalize_draft(_safe_payload(plan), plan, ir, resolution, pack)
    clean["generation_status"] = "BLOCKED_UPSTREAM"
    assert "generation_status_upstream_mismatch" in spoken_narration.validate(
        clean, plan, ir, resolution, pack
    )
    clean["generation_status"] = "DRAFT_ACCEPTED"
    clean["narration_beats"].pop()
    assert "accepted_beat_coverage_invalid" in spoken_narration.validate(
        clean, plan, ir, resolution, pack
    )


def test_added_direct_cause_is_rejected_even_when_association_and_negation_remain():
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    payload["beats"][-1]["sentences"][0] += " 원인이다."

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "REJECTED_DRAFT"
    assert any(error.startswith("causal_language_added:NB03")
               for error in result["qa"]["errors"])

    draft = spoken_narration.normalize_draft(_safe_payload(plan), plan, ir, resolution, pack)
    polish_payload = {"beats": [{
        "beat_id": beat["beat_id"], "sentences": deepcopy(beat["sentences"])
    } for beat in draft["narration_beats"]]}
    polish_payload["beats"][-1]["sentences"][0] += " 원인이다."
    polished = spoken_narration.apply_polish(
        draft, polish_payload, plan, ir, resolution, pack
    )
    assert polished["polish"]["applied"] == []
    assert any("causal_language_added:NB03" in row["reason"]
               for row in polished["polish"]["rejected"])
    assert polished["narration_beats"][-1]["sentences"] == draft["narration_beats"][-1]["sentences"]


def test_numeric_guard_preserves_sign_currency_and_all_whitespace():
    pack, ir, resolution, plan = _report_ready()
    negative = _safe_payload(plan)
    negative["beats"][-1]["sentences"][0] = negative["beats"][-1]["sentences"][0].replace(
        "1%", "-1%"
    )
    assert spoken_narration.normalize_draft(
        negative, plan, ir, resolution, pack
    )["generation_status"] == "REJECTED_DRAFT"

    tabbed = _safe_payload(plan)
    tabbed["beats"][-1]["sentences"][0] = tabbed["beats"][-1]["sentences"][0].replace(
        "1%", "1\t%"
    )
    assert spoken_narration.normalize_draft(
        tabbed, plan, ir, resolution, pack
    )["generation_status"] == "DRAFT_ACCEPTED"

    paper_pack, _, _, _ = _paper_ready()
    paper_pack["claims"][0]["text"] = "비용 30원과 성격은 연관됐지만 원인이라고 입증하지 않았다."
    paper_ir = paper_reasoning_adapter.build(
        paper_pack,
        core_question="비용과 성격은 연관됐는가?",
        thesis="비용과 성격은 연관됐지만 원인이라고 입증하지 않았다.",
    )
    paper_resolution = prerequisite_resolver.resolve(paper_ir, paper_pack, [])
    paper_plan = narrative_planner.build(paper_ir, paper_resolution, paper_pack)
    currency = _safe_payload(paper_plan)
    currency["beats"][-1]["sentences"][0] = currency["beats"][-1]["sentences"][0].replace(
        "30원", "30달러"
    )
    result = spoken_narration.normalize_draft(
        currency, paper_plan, paper_ir, paper_resolution, paper_pack
    )
    assert result["generation_status"] == "REJECTED_DRAFT"
    assert any(error.startswith("numbers_changed:") for error in result["qa"]["errors"])


def test_hook_factual_assertion_is_dropped_by_restore_and_rejected_in_polish():
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    unsafe = plan["core_question"] + " 변이는 성격을 결정한다."
    payload["beats"][0]["sentences"] = [unsafe]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "DRAFT_ACCEPTED"
    assert result["narration_beats"][0]["sentences"] == [plan["core_question"]]
    assert result["repairs"][0]["model_sentences"] == [unsafe]

    # 다듬기(polish)는 되돌리지 않고 거절한다 — 같은 가드가 그 경로에서 살아 있다.
    polish = {"beats": [{
        "beat_id": beat["beat_id"], "sentences": list(beat["sentences"]),
    } for beat in result["narration_beats"]]}
    polish["beats"][0]["sentences"] = [unsafe]
    polished = spoken_narration.apply_polish(result, polish, plan, ir, resolution, pack)
    assert polished["narration_beats"][0]["sentences"] == [plan["core_question"]]
    assert polished["polish"]["rejected"][0]["beat_id"] == "NB01"
    guarded = [dict(beat) for beat in result["narration_beats"]]
    guarded[0]["sentences"] = [unsafe]
    guard_errors, _, _ = spoken_narration._draft_guard_findings(guarded, plan)
    assert "hook_factual_assertion_added:NB01" in guard_errors
    assert "hook_not_grounded:NB01" in guard_errors


def test_each_scope_qualifier_must_survive_when_another_hedge_remains():
    pack, _, _, _ = _paper_ready()
    pack["claims"][0]["text"] = "일부 환자에게서 평균 30% 개선과 성격이 연관됐다."
    ir = paper_reasoning_adapter.build(
        pack,
        core_question="개선과 성격은 연관됐는가?",
        thesis="일부 환자에게서 평균 30% 개선과 성격이 연관됐다.",
    )
    resolution = prerequisite_resolver.resolve(ir, pack, [])
    plan = narrative_planner.build(ir, resolution, pack)
    payload = _safe_payload(plan)
    payload["beats"][-1]["sentences"][0] = payload["beats"][-1]["sentences"][0].replace(
        "일부 ", ""
    )

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "REJECTED_DRAFT"
    assert any(error.startswith("qualifier_dropped:") and error.endswith(":일부")
               for error in result["qa"]["errors"])
