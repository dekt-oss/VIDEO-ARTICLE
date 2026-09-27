"""전문이 있어도 **초록 인용은 원문에 있는 것**이다 (2026-09-27 실측).

PMC XML 본문에는 초록이 없다. PNAS 나무 논문(0fc84ce2)에서 초록에 그대로 있는 인용 5개가
"원문에 없음"(cut_claim_not_in_source)으로 판정돼 지시서 승인이 잠겼고, 재생성은 같은 원장을
쓰니 몇 번을 돌려도 풀리지 않았다(운영자: "왜 무한으로 도는지").
"""

from __future__ import annotations

from engine import config, paper_evidence

ABSTRACT = "Using 2,953 tree-ring sites, we identify VPD thresholds for tree growth."
BODY = "Forests play a critical role in regulating the global carbon cycle."


def test_an_abstract_quote_is_verified_when_the_body_lacks_the_abstract():
    packet = paper_evidence.verification_packet(
        {"text": BODY, "source_depth": "full_body", "provider": "pmc_xml"}, ABSTRACT)
    v = paper_evidence.verify_claim({"source_quote": ABSTRACT, "evidence_grade": "A"}, packet)
    assert v["quote_verified"] is True
    assert packet["source_depth"] == "full_body", "초록을 붙여도 확보 수준은 그대로다"


def test_a_made_up_quote_is_still_rejected():
    packet = paper_evidence.verification_packet({"text": BODY, "source_depth": "full_body"}, ABSTRACT)
    v = paper_evidence.verify_claim({"source_quote": "A double-blind placebo-controlled trial."}, packet)
    assert v["quote_verified"] is False


def test_the_abstract_is_not_duplicated_when_already_in_the_body():
    packet = paper_evidence.verification_packet({"text": ABSTRACT + "\n\n" + BODY}, ABSTRACT)
    assert packet["text"].count(ABSTRACT) == 1


def test_old_judgments_are_no_longer_current():
    """버전을 올려 옛 false 판정을 판정 불가로 돌린다 — 다음 지시서 생성이 무료로 재대조한다."""
    assert not paper_evidence.is_current({"contract_version": "2026-08-30.contiguous-ratio"})
    assert "abstract" in config.EVIDENCE_CONTRACT_VERSION
