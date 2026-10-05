"""Explanation Engine v2 Phase 2 — common Evidence Pack contract tests."""

from __future__ import annotations

from copy import deepcopy

from engine import config, evidence_pack


def paper_fact_sheet() -> dict:
    return {
        "what_found": ["보행 방식 사이에 에너지-충격 trade-off가 관찰됐다."],
        "how": ["인간과 침팬지의 보행을 비교했다."],
        "numbers": ["인간 forefoot 보행은 에너지를 26~41% 더 사용했다."],
        "limitations": ["침팬지 표본은 3마리였다."],
        "source": {
            "title": "Heel-strike mechanics",
            "venue": "PNAS",
            "authors": ["A. Researcher"],
            "institutions": ["Example University"],
            "url": "https://example.test/paper",
        },
        "source_provenance": {
            "source_depth": "full_body",
            "char_count": 60000,
            "provider": "pmc",
        },
        "source_adequacy": {
            "contract_version": "source-adequacy-v1",
            "domain": "paper",
            "source_depth": "full_body",
            "source_chars": 60000,
            "source_mode": "FULL_EXPLAINER",
            "max_duration_sec": 80,
            "max_content_mode": "extended",
            "max_reasoning_units": 0,
            "max_reasoning_steps": 0,
            "warnings": [],
        },
        "claims": [{
            "claim_id": "C01",
            "claim_kind": "main_result",
            "claim_ko": "침팬지는 인간보다 더 넓은 발 접촉 각도 범위를 사용했다.",
            "population": "인간, 침팬지",
            "comparison": "인간 대 침팬지",
            "effect_size": "2.4 to 8.6",
            "effect_unit": "배",
            "causal_strength": "descriptive",
            "uncertainty": None,
            "source_section": "abstract",
            "source_quote": "chimpanzees used 2.4 to 8.6 times greater ranges",
            "source_page": None,
            "table_or_figure": None,
            "evidence_grade": "B",
            "limitations": [],
            "validation": {
                "quote_verified": True,
                "chunk_id": "P018",
                "evidence_state": "SUPPORTED",
                "contract_version": config.EVIDENCE_CONTRACT_VERSION,
            },
        }],
    }


def report_fact_sheet() -> dict:
    return {
        "company": "삼성전자",
        "what": ["메모리 가격 상승세가 이어질 것으로 추정된다."],
        "basis": ["HBM이 범용 DRAM 생산능력을 잠식할 수 있다고 본다."],
        "risks": ["2028년 피크아웃 가능성을 시장이 우려한다."],
        "opinion": "유안타증권 목표주가 63만원",
        "source_depth": "full_text",
        "source_chars": 11997,
        "source": {
            "broker": "유안타증권",
            "analyst": "",
            "company": "삼성전자",
            "url": "https://example.test/report",
        },
        "source_adequacy": {
            "contract_version": "source-adequacy-v1",
            "domain": "report",
            "source_depth": "full_text",
            "source_chars": 11997,
            "source_mode": "FULL_EXPLAINER",
            "max_duration_sec": 80,
            "max_content_mode": "",
            "max_reasoning_units": 5,
            "max_reasoning_steps": 5,
            "warnings": [],
        },
        "number_facts": [{
            "fact_id": "num_target_price",
            "value": 630000,
            "unit": "원",
            "unit_norm": "원",
            "period": "",
            "metric": "목표주가",
            "scope": "company",
            "basis": "broker_estimate",
            "attribution": "유안타증권",
            "display": "목표주가 630,000원",
            "comparator": {"basis": "직전 목표주가", "value": "530,000원"},
            "interpretation": "neutral",
            "source_page": None,
            "source_refs": [{"chunk_id": "C001", "quote": "목표주가 630,000원 (U)"}],
            "validation": {
                "number_match": True,
                "unit_match": True,
                "period_match": False,
                "quote_supports_claim": True,
            },
        }],
    }


def test_paper_claim_ledger_maps_one_to_one_without_losing_verification():
    pack = evidence_pack.build(paper_fact_sheet(), "paper", content_id="p1")
    assert evidence_pack.validate(pack) == []
    assert pack["source"]["source_mode"] == "FULL_EXPLAINER"
    assert pack["source"]["source_depth"] == "full_body"
    assert len(pack["claims"]) == 1

    claim = pack["claims"][0]
    assert claim["evidence_id"] == "paper:C01"
    assert claim["raw_ref"] == "claims:C01"
    assert claim["claim_type"] == "main_result"
    assert claim["causal_strength"] == "descriptive"
    assert claim["evidence_grade"] == "B"
    assert claim["verification_state"] == "SUPPORTED"
    assert claim["source_refs"][0]["chunk_id"] == "P018"
    assert claim["domain_fields"]["effect_size"] == "2.4 to 8.6"


def test_stale_paper_validation_is_not_promoted_to_supported():
    fs = paper_fact_sheet()
    fs["claims"][0]["validation"]["contract_version"] = "old-contract"
    pack = evidence_pack.build(fs, "paper")
    assert pack["claims"][0]["verification_state"] == "STALE"


def test_report_qualitative_claims_are_not_falsely_marked_verified():
    pack = evidence_pack.build(report_fact_sheet(), "report", content_id="r1")
    assert evidence_pack.validate(pack) == []
    by_role = {c["domain_role"]: c for c in pack["claims"]}

    assert by_role["what"]["verification_state"] == "NOT_CHECKED"
    assert by_role["basis"]["verification_state"] == "NOT_CHECKED"
    assert by_role["opinion"]["verification_state"] == "NOT_CHECKED"
    assert by_role["basis"]["attribution"] == "유안타증권"
    assert by_role["basis"]["raw_ref"] == "basis[0]"


def test_report_validated_number_keeps_raw_validation_instead_of_flattening_it():
    pack = evidence_pack.build(report_fact_sheet(), "report")
    number = pack["numbers"][0]

    assert number["evidence_id"] == "report:num_target_price"
    assert number["raw_ref"] == "number_facts:num_target_price"
    assert number["verification_state"] == "SUPPORTED"
    assert number["value"] == 630000
    assert number["basis"] == "broker_estimate"
    # 기간이 없는 목표주가라 period_match=False여도 quote/value 검증을 없던 일로 만들지 않는다.
    assert number["validation"]["period_match"] is False
    assert number["source_refs"][0]["chunk_id"] == "C001"


def test_report_number_mismatch_is_unsupported():
    fs = report_fact_sheet()
    fs["number_facts"][0]["validation"]["number_match"] = False
    pack = evidence_pack.build(fs, "report")
    assert pack["numbers"][0]["verification_state"] == "UNSUPPORTED"


def test_risks_and_limitations_remain_domain_semantics_not_fake_common_claims():
    paper = evidence_pack.build(paper_fact_sheet(), "paper")
    report = evidence_pack.build(report_fact_sheet(), "report")

    assert paper["risks"] == []
    assert paper["limitations"][0]["text"] == "침팬지 표본은 3마리였다."
    assert report["limitations"] == []
    assert report["risks"][0]["text"].startswith("2028년")
    assert report["risks"][0]["verification_state"] == "NOT_CHECKED"


def test_pack_is_a_projection_and_does_not_mutate_source_of_truth():
    fs = report_fact_sheet()
    before = deepcopy(fs)
    pack = evidence_pack.build(fs, "report")
    pack["claims"][0]["text"] = "edited in consumer"

    assert fs == before
    assert fs["what"][0] != "edited in consumer"


def test_every_projected_evidence_item_has_a_raw_reference():
    for fs, domain in ((paper_fact_sheet(), "paper"), (report_fact_sheet(), "report")):
        pack = evidence_pack.build(fs, domain)
        for section in ("claims", "numbers", "risks", "limitations", "background_context"):
            for item in pack[section]:
                assert item["evidence_id"]
                assert item["raw_ref"]


def test_legacy_pack_does_not_invent_source_mode():
    legacy = {"what": ["요약"], "basis": [], "risks": [], "number_facts": []}
    pack = evidence_pack.build(legacy, "report")
    assert pack["source"]["source_depth"] == "none"
    assert pack["source"]["source_mode"] == ""


def test_unknown_domain_is_rejected():
    try:
        evidence_pack.build({}, "other")
    except ValueError as exc:
        assert "unknown evidence-pack domain" in str(exc)
    else:
        raise AssertionError("unknown domain must be rejected")


def test_background_context_is_traceable_but_not_promoted_to_verified_evidence():
    paper = evidence_pack.build(paper_fact_sheet(), "paper")
    context = paper["background_context"]
    assert context
    assert all(item["evidence_id"] and item["raw_ref"] for item in context)
    assert all(item["verification_state"] == "NOT_CHECKED" for item in context)


def test_supported_does_not_mean_semantic_entailment():
    """Quote-presence verification must not become a blanket truth label in Phase 3."""
    paper = evidence_pack.build(paper_fact_sheet(), "paper")
    claim = paper["claims"][0]
    assert claim["verification_state"] == "SUPPORTED"
    assert claim["verification_scope"]["quote_presence"] is True
    assert claim["verification_scope"]["semantic_entailment"] is False

    report = evidence_pack.build(report_fact_sheet(), "report")
    number = report["numbers"][0]
    assert number["verification_state"] == "SUPPORTED"
    assert number["verification_scope"] == {
        "quote_presence": True,
        "numeric_value": True,
        "unit": True,
        "period": False,
        "semantic_entailment": False,
    }


def test_validate_rejects_missing_verification_scope():
    pack = evidence_pack.build(paper_fact_sheet(), "paper")
    del pack["claims"][0]["verification_scope"]
    assert "verification_scope_invalid:paper:C01" in evidence_pack.validate(pack)


# ─── 설계 점검 E(2026-10-05): 원문 인용이 확인된 논리 단계를 근거로 ─────────────

def _reasoning_with_quotes():
    return {"units": [{
        "reasoning_id": "R04", "unit_type": "RISK_PATH", "attributed_to": "테스트증권",
        "steps": [
            {"step": 1, "text": "시장은 2028년 피크아웃을 우려한다.", "fact_ids": [],
             "source_refs": [{"quote": "2028년 피크아웃 우려", "chunk_id": "C1", "verified": True}]},
            {"step": 2, "text": "확인 안 된 인용만 있는 단계.", "fact_ids": [],
             "source_refs": [{"quote": "원문에 없는 말", "verified": False}]},
        ],
    }]}


def test_verified_step_quotes_become_quote_supported_evidence():
    pack = evidence_pack.build(report_fact_sheet(), "report", financial_reasoning=_reasoning_with_quotes())

    steps = [c for c in pack["claims"] if c["claim_type"] == "reasoning_step"]
    assert [c["evidence_id"] for c in steps] == ["report:step:R04#1"]       # 확인 안 된 인용은 싣지 않는다
    assert steps[0]["verification_state"] == "SUPPORTED"
    assert steps[0]["verification_scope"]["quote_presence"] is True
    assert steps[0]["verification_scope"]["semantic_entailment"] is False   # 뜻까지 확인한 것은 아니다
    assert steps[0]["attribution"] == "테스트증권"
    assert evidence_pack.validate(pack) == []


def test_without_reasoning_the_pack_is_unchanged():
    assert evidence_pack.build(report_fact_sheet(), "report") == \
        evidence_pack.build(report_fact_sheet(), "report", financial_reasoning=None)
