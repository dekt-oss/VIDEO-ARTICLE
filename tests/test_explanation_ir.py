"""Explanation Engine v2 Phase 3 — common reasoning IR shadow contract."""

from __future__ import annotations

from copy import deepcopy

from engine import explanation_ir


def _scope(*, semantic: bool = False) -> dict[str, bool]:
    return {
        "quote_presence": True,
        "numeric_value": False,
        "unit": False,
        "period": False,
        "semantic_entailment": semantic,
    }


def _pack() -> dict:
    return {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": "paper-1",
        "source": {
            "source_depth": "full_body",
            "source_chars": 12000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "pmc",
            "attribution": {},
        },
        "claims": [
            {
                "evidence_id": "paper:C01",
                "raw_ref": "claims:C01",
                "text": "변이는 성격과 연관됐다.",
                "claim_type": "main_result",
                "domain_role": "claim",
                "causal_strength": "association_only",
                "verification_state": "SUPPORTED",
                "verification_scope": _scope(),
                "source_refs": [],
                "uncertainty": None,
                "limitations": [],
                "attribution": "",
                "domain_fields": {},
            },
            {
                "evidence_id": "paper:C02",
                "raw_ref": "claims:C02",
                "text": "근거 없는 결정론",
                "claim_type": "mechanism",
                "domain_role": "claim",
                "causal_strength": "causal",
                "verification_state": "UNSUPPORTED",
                "verification_scope": _scope(),
                "source_refs": [],
                "uncertainty": None,
                "limitations": [],
                "attribution": "",
                "domain_fields": {},
            },
        ],
        "numbers": [],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }


def _candidate() -> dict:
    return {
        "domain": "paper",
        "core_question": "이 변이는 성격을 결정하는가?",
        "thesis": "연구가 보여 준 것은 결정이 아니라 연관이다.",
        "reasoning_units": [
            {
                "reasoning_id": "MODEL-99",
                "role": "result",
                "text": "변이는 성격과 연관됐다.",
                "evidence_ids": ["paper:C01", "paper:C01", "paper:ghost"],
                "raw_refs": ["model:invented"],
                "causal_level": "association_only",
                "uncertainty": "",
                "attribution": "",
                "transition_relation": "supports",
            }
        ],
    }


def test_normalize_assigns_ids_and_derives_trace_from_evidence_pack():
    """Catches trusting model-provided IDs/raw refs or retaining dangling evidence."""
    ir = explanation_ir.normalize(_candidate(), _pack())

    assert ir["contract_version"] == "explanation-ir-v1"
    assert ir["content_id"] == "paper-1"
    assert [u["reasoning_id"] for u in ir["reasoning_units"]] == ["XR01"]
    assert ir["reasoning_units"][0]["evidence_ids"] == ["paper:C01"]
    assert ir["reasoning_units"][0]["raw_refs"] == ["claims:C01"]
    assert ir["explanation_chain"] == ["XR01"]
    assert "evidence_ref_unknown:paper:ghost" in ir["warnings"]
    assert explanation_ir.validate(ir, _pack()) == []


def test_positive_unit_cannot_use_unsupported_or_stale_evidence():
    """Catches an invalid claim surviving merely because its evidence ID exists."""
    candidate = _candidate()
    candidate["reasoning_units"][0]["evidence_ids"] = ["paper:C02"]

    ir = explanation_ir.normalize(candidate, _pack())

    assert ir["reasoning_units"] == []
    assert ir["explanation_chain"] == []
    assert "evidence_state_disallowed:paper:C02:UNSUPPORTED" in ir["warnings"]
    assert "reasoning_unit_without_evidence:1" in ir["warnings"]


def test_normalize_does_not_mutate_candidate_or_pack_and_is_deterministic():
    """Catches in-place state leaking between shadow comparisons."""
    candidate = _candidate()
    pack = _pack()
    before_candidate = deepcopy(candidate)
    before_pack = deepcopy(pack)

    first = explanation_ir.normalize(candidate, pack)
    second = explanation_ir.normalize(candidate, pack)

    assert first == second
    assert candidate == before_candidate
    assert pack == before_pack


def test_unverified_and_non_entailing_evidence_are_explicit_warnings():
    """Catches quote presence being silently promoted to whole-claim truth."""
    pack = _pack()
    pack["claims"][0]["verification_state"] = "NOT_CHECKED"

    ir = explanation_ir.normalize(_candidate(), pack)

    assert "evidence_not_checked:paper:C01" in ir["warnings"]
    assert "semantic_entailment_unverified:paper:C01" in ir["warnings"]


def test_validate_rejects_empty_core_question_and_domain_mismatch():
    """Catches multi-stage consumers receiving an unanswerable or cross-domain IR."""
    ir = explanation_ir.normalize(_candidate(), _pack())
    ir["core_question"] = ""
    ir["domain"] = "report"

    assert explanation_ir.validate(ir, _pack()) == [
        "core_question_missing",
        "domain_mismatch:report!=paper",
    ]


def test_invalid_evidence_pack_is_rejected_before_normalization():
    """Catches malformed evidence becoming a plausible-looking IR."""
    pack = _pack()
    del pack["claims"][0]["raw_ref"]

    try:
        explanation_ir.normalize(_candidate(), pack)
    except ValueError as exc:
        assert "evidence_pack_invalid" in str(exc)
        assert "claims_raw_ref_missing:paper:C01" in str(exc)
    else:
        raise AssertionError("invalid Evidence Pack must fail closed")


def test_risk_and_limitation_units_may_preserve_disallowed_state_as_constraints():
    """Catches loss of negative evidence while still forbidding it as positive proof."""
    candidate = _candidate()
    candidate["reasoning_units"][0].update(
        role="limitation",
        text="이 주장은 원문으로 지지되지 않는다.",
        evidence_ids=["paper:C02"],
    )

    ir = explanation_ir.normalize(candidate, _pack())

    assert ir["reasoning_units"][0]["role"] == "limitation"
    assert ir["reasoning_units"][0]["evidence_ids"] == ["paper:C02"]
    assert "constraint_evidence_state:paper:C02:UNSUPPORTED" in ir["warnings"]
