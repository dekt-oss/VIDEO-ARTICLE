from __future__ import annotations

from copy import deepcopy

import pytest

from engine import (
    narrative_planner,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
    spoken_narration,
)


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


def test_hook_must_remain_a_grounded_question():
    pack, ir, resolution, plan = _paper_ready()
    payload = _safe_payload(plan)
    payload["beats"][0]["sentences"] = ["변이는 성격을 결정한다."]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "REJECTED_DRAFT"
    assert "hook_not_question:NB01" in result["qa"]["errors"]
    assert "hook_not_grounded:NB01" in result["qa"]["errors"]


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
    payload["beats"][0]["sentences"] = [plan["core_question"], plan["core_question"]]
    payload["beats"][1]["sentences"] = [
        plan["beats"][1]["content_points"][0] + " 본 연구에서 관찰되었다고 할 수 있습니다."
    ]

    result = spoken_narration.normalize_draft(payload, plan, ir, resolution, pack)

    assert result["generation_status"] == "DRAFT_ACCEPTED"
    assert "core_question_repeated" in result["qa"]["warnings"]
    assert "sentence_too_long:NB02" in result["qa"]["warnings"]
    assert "academic_register:NB02" in result["qa"]["warnings"]
    assert "unexplained_abbreviation:NB02:GWAS" in result["qa"]["warnings"]
    assert result["qa"]["semantic_entailment"] == "NOT_CHECKED"
