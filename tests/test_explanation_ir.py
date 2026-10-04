"""Explanation Engine v2 Phase 3 — common reasoning IR shadow contract."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from engine import explanation_ir, paper_reasoning_adapter, report_reasoning_adapter


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


def test_non_entailing_evidence_is_an_explicit_warning():
    """Catches quote presence being silently promoted to whole-claim truth."""
    ir = explanation_ir.normalize(_candidate(), _pack())

    assert "semantic_entailment_unverified:paper:C01" in ir["warnings"]


def test_never_checked_evidence_cannot_carry_positive_reasoning():
    """설계 점검 B(2026-10-05): NOT_CHECKED 는 STALE 처럼 근거로 못 쓴다."""
    pack = _pack()
    pack["claims"][0]["verification_state"] = "NOT_CHECKED"

    ir = explanation_ir.normalize(_candidate(), pack)

    assert "evidence_state_disallowed:paper:C01:NOT_CHECKED" in ir["warnings"]
    assert all("paper:C01" not in unit["evidence_ids"] for unit in ir["reasoning_units"])


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


def test_validate_rejects_invalid_pack_and_disallowed_positive_evidence():
    """Catches post-normalization tampering bypassing the evidence-state gate."""
    pack = _pack()
    ir = explanation_ir.normalize(_candidate(), pack)
    ir["reasoning_units"][0]["evidence_ids"] = ["paper:C02"]
    ir["reasoning_units"][0]["raw_refs"] = ["claims:C02"]

    assert "evidence_state_disallowed:paper:C02:UNSUPPORTED" in explanation_ir.validate(
        ir, pack)

    invalid_pack = deepcopy(pack)
    del invalid_pack["claims"][0]["raw_ref"]
    assert any(
        error.startswith("evidence_pack_invalid:")
        for error in explanation_ir.validate(ir, invalid_pack)
    )


def test_validate_rejects_report_attribution_tampering():
    """Catches a traced broker fact being relabeled as another broker's view."""
    pack = _report_pack()
    ir = report_reasoning_adapter.build(pack, _report_reasoning())
    ir["reasoning_units"][0]["attribution"] = "다른증권"

    assert "attribution_mismatch:XR01:다른증권!=하나증권" in explanation_ir.validate(
        ir, pack)


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
    assert "caller_core_question_semantics_unverified" in ir["warnings"]
    assert "caller_thesis_semantics_unverified" in ir["warnings"]


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


def _report_pack(*, depth: str = "full_text") -> dict:
    mode = "FULL_EXPLAINER" if depth == "full_text" else "BRIEF_EXPLAINER"
    return {
        "contract_version": "evidence-pack-v1",
        "domain": "report",
        "content_id": "report-1",
        "source": {
            "source_depth": depth,
            "source_chars": 12000 if depth == "full_text" else 1072,
            "source_mode": mode,
            "provider": "",
            "attribution": {"broker": "하나증권", "company": "LS일렉트릭"},
        },
        "claims": [],
        "numbers": [
            {
                "evidence_id": "report:num_op",
                "raw_ref": "number_facts:num_op",
                "value": 860,
                "unit": "억원",
                "period": "2026F",
                "metric": "영업이익",
                "scope": "company",
                "basis": "broker_estimate",
                "attribution": "하나증권",
                "display": "2026F 영업이익 860억원",
                "comparator": {},
                "interpretation": "growth",
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
            }
        ],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }


def _report_reasoning(unit_count: int = 1, steps_per_unit: int = 1) -> dict:
    return {
        "units": [
            {
                "reasoning_id": f"R{unit_no:02d}",
                "unit_type": "EARNINGS_BRIDGE",
                "title": "수주가 실적으로 이어지는 경로",
                "carries_thesis": unit_no == 1,
                "attributed_to": "하나증권",
                "assumption": "수주가 계획대로 인식돼야 한다.",
                "breaks_if": "납기가 지연되면 깨진다.",
                "steps": [
                    {
                        "step": step_no,
                        "text": f"수주 단계 {step_no}가 실적 전망으로 이어진다.",
                        "fact_ids": ["num_op"],
                        "source_refs": [],
                    }
                    for step_no in range(1, steps_per_unit + 1)
                ],
            }
            for unit_no in range(1, unit_count + 1)
        ]
    }


def test_report_adapter_maps_existing_fact_ids_and_preserves_attribution():
    """Catches report steps losing their ledger link or becoming objective facts."""
    ir = report_reasoning_adapter.build(_report_pack(), _report_reasoning())

    unit = ir["reasoning_units"][0]
    assert unit["evidence_ids"] == ["report:num_op"]
    assert unit["raw_refs"] == ["number_facts:num_op"]
    assert unit["attribution"] == "하나증권"
    assert unit["causal_level"] == "broker_projection"
    assert ir["thesis"] == "수주가 실적으로 이어지는 경로"


def test_report_adapter_drops_source_only_and_unknown_fact_steps():
    """Catches raw quotes or invented fact IDs bypassing Evidence Pack traceability."""
    reasoning = _report_reasoning()
    reasoning["units"][0]["steps"] = [
        {"step": 1, "text": "원문 인용만 있는 단계", "fact_ids": [],
         "source_refs": [{"quote": "원문 문장"}]},
        {"step": 2, "text": "없는 숫자", "fact_ids": ["num_ghost"], "source_refs": []},
    ]

    ir = report_reasoning_adapter.build(_report_pack(), reasoning)

    assert ir["reasoning_units"] == []
    assert "report_step_without_evidence_id:R01#1" in ir["warnings"]
    assert "evidence_ref_unknown:report:num_ghost" in ir["warnings"]


def test_report_adapter_reapplies_partial_source_one_by_three_ceiling():
    """Catches a shallow report recovering deep reasoning in the shadow layer."""
    ir = report_reasoning_adapter.build(
        _report_pack(depth="partial_text"),
        _report_reasoning(unit_count=3, steps_per_unit=5),
    )

    assert len(ir["reasoning_units"]) == 3
    assert all(unit["attribution"] == "하나증권" for unit in ir["reasoning_units"])
    assert "source_reasoning_units_capped:3>1" in ir["warnings"]
    assert "source_reasoning_steps_capped:R01:5>3" in ir["warnings"]


def test_report_adapter_summary_only_does_not_leak_deep_reasoning_into_thesis():
    """Catches a zero-unit source retaining a thesis from disabled reasoning."""
    ir = report_reasoning_adapter.build(
        _report_pack(depth="summary_only"),
        _report_reasoning(),
    )

    assert ir["reasoning_units"] == []
    assert ir["thesis"] == ""
    assert "source_reasoning_units_capped:1>0" in ir["warnings"]


def test_report_adapter_derives_missing_broker_attribution_from_evidence():
    """Catches a broker projection becoming unattributed when the ledger knows the broker."""
    reasoning = _report_reasoning()
    reasoning["units"][0]["attributed_to"] = ""

    ir = report_reasoning_adapter.build(_report_pack(), reasoning)

    assert ir["reasoning_units"][0]["attribution"] == "하나증권"
    assert "report_attribution_derived:R01#1:하나증권" in ir["warnings"]


def test_report_adapter_corrects_conflicting_attribution_to_evidence_pack():
    """Catches stale financial reasoning overriding the Fact Sheet broker."""
    reasoning = _report_reasoning()
    reasoning["units"][0]["attributed_to"] = "다른증권"

    ir = report_reasoning_adapter.build(_report_pack(), reasoning)

    assert ir["reasoning_units"][0]["attribution"] == "하나증권"
    assert "report_attribution_corrected:R01#1:다른증권!=하나증권" in ir["warnings"]


def _pack_from_gold_case(case: dict) -> dict:
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
                domain_role="claim", evidence_grade="B", source_refs=[],
                uncertainty=projected.get("uncertainty"),
                limitations=projected.get("limitations", []),
                attribution=projected.get("attribution", ""),
                domain_fields={},
            )
            pack["claims"].append(projected)
        else:
            projected.update(
                value=projected.get("value"), unit=projected.get("unit", ""),
                period=projected.get("period", ""), metric=projected.get("metric", ""),
                scope="company", basis="broker_estimate",
                attribution=projected.get("attribution", ""),
                display=projected["text"], comparator={},
                interpretation=projected.get("interpretation", "neutral"),
                validation={}, source_refs=[],
            )
            projected.pop("text")
            pack["numbers"].append(projected)
    return pack


def test_six_gold_cases_have_deterministic_calibrated_shadow_ir():
    """Catches recurrence of the six Phase 0 semantic failure anchors."""
    path = Path(__file__).parent / "fixtures" / "explanation_ir_gold_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 6

    outputs: dict[str, dict] = {}
    for case in cases:
        pack = _pack_from_gold_case(case)
        if case["domain"] == "paper":
            first = paper_reasoning_adapter.build(pack)
            second = paper_reasoning_adapter.build(pack)
        else:
            first = report_reasoning_adapter.build(pack, case["financial_reasoning"])
            second = report_reasoning_adapter.build(pack, case["financial_reasoning"])
        assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
            second, ensure_ascii=False, sort_keys=True)
        assert explanation_ir.validate(first, pack) == []
        outputs[case["case_id"]] = first

    heel = outputs["heel-strike-2026-09"]
    assert "유일" not in " ".join(unit["text"] for unit in heel["reasoning_units"])
    remap = outputs["deaf-retinotopic-remap-2026-09"]
    assert "청각" not in " ".join(unit["text"] for unit in remap["reasoning_units"])
    personality = outputs["personality-gwas-2026-09"]
    assert {u["causal_level"] for u in personality["reasoning_units"]} == {"association_only"}
    samsung = outputs["samsung-memory-cycle-2026-09"]
    assert samsung["reasoning_units"][0]["attribution"] == "유안타증권"
    nh = outputs["nh-ai-mid-cycle-2026-09"]
    assert len(nh["reasoning_units"]) <= 3
    ship = outputs["shipbuilding-rerating-2026-09"]
    assert all(u["causal_level"] == "broker_projection" for u in ship["reasoning_units"])
    assert all(u["attribution"] == "한국투자증권" for u in ship["reasoning_units"])
