"""Explanation Engine v2 Phase 3 — common reasoning IR shadow contract."""

from __future__ import annotations

from copy import deepcopy

from engine import explanation_ir, paper_reasoning_adapter


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


def test_paper_adapter_preserves_association_instead_of_promoting_causality():
    """Catches personality association becoming genetic determination."""
    ir = paper_reasoning_adapter.build(_pack())

    assert ir["core_question"] == "이 연구는 무엇을 보여 주는가?"
    assert ir["thesis"] == "변이는 성격과 연관됐다."
    assert len(ir["reasoning_units"]) == 1
    assert ir["reasoning_units"][0]["role"] == "result"
    assert ir["reasoning_units"][0]["causal_level"] == "association_only"
    assert ir["reasoning_units"][0]["evidence_ids"] == ["paper:C01"]
    assert "paper:C02" not in {
        eid for unit in ir["reasoning_units"] for eid in unit["evidence_ids"]
    }


def test_paper_adapter_keeps_author_interpretation_explicit():
    """Catches an author's interpretation being relabeled as a proven mechanism."""
    pack = _pack()
    claim = pack["claims"][0]
    claim["claim_type"] = "author_interpretation"
    claim["causal_strength"] = "speculation"
    claim["text"] = "저자들은 이 변화가 적응을 반영할 수 있다고 해석했다."

    ir = paper_reasoning_adapter.build(pack)

    unit = ir["reasoning_units"][0]
    assert unit["role"] == "mechanism"
    assert unit["causal_level"] == "speculation"
    assert unit["uncertainty"] == "author_interpretation"
    assert "author_interpretation:paper:C01" in ir["warnings"]


def test_paper_adapter_emits_claim_limitations_after_the_claim_with_same_trace():
    """Catches a qualifier being dropped or detached from its evidence."""
    pack = _pack()
    pack["claims"][0]["limitations"] = ["표본은 한 집단에 한정됐다."]

    ir = paper_reasoning_adapter.build(pack)

    assert [unit["role"] for unit in ir["reasoning_units"]] == ["result", "limitation"]
    limitation = ir["reasoning_units"][1]
    assert limitation["text"] == "표본은 한 집단에 한정됐다."
    assert limitation["evidence_ids"] == ["paper:C01"]
    assert limitation["transition_relation"] == "qualifies"


def test_paper_adapter_uses_explicit_question_and_thesis_without_rewriting():
    """Catches the shadow layer turning an explicit calibrated claim into stronger prose."""
    ir = paper_reasoning_adapter.build(
        _pack(),
        core_question="성격 변이 연구가 실제로 말하는 것은 무엇인가?",
        thesis="변이는 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다.",
    )

    assert ir["core_question"] == "성격 변이 연구가 실제로 말하는 것은 무엇인가?"
    assert ir["thesis"] == "변이는 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다."


def test_paper_adapter_rejects_report_pack():
    """Catches domain adapters accepting the other domain's semantics."""
    pack = _pack()
    pack["domain"] = "report"

    try:
        paper_reasoning_adapter.build(pack)
    except ValueError as exc:
        assert str(exc) == "paper_reasoning_adapter_requires_paper_pack"
    else:
        raise AssertionError("Paper adapter must reject Report evidence")


def test_paper_adapter_does_not_promote_background_context_to_reasoning():
    """Catches unverified method summaries becoming invented prerequisite facts."""
    pack = _pack()
    pack["background_context"] = [{
        "evidence_id": "paper:context:method:01",
        "raw_ref": "how[0]",
        "text": "GWAS는 여러 변이의 연관을 함께 본다.",
        "verification_state": "NOT_CHECKED",
        "verification_scope": _scope(),
    }]

    ir = paper_reasoning_adapter.build(pack)

    assert all(unit["role"] != "prerequisite" for unit in ir["reasoning_units"])
    assert all(
        "paper:context:method:01" not in unit["evidence_ids"]
        for unit in ir["reasoning_units"]
    )
