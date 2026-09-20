"""두 공장이 원문 확보 수준을 **다른 칸에** 적고 있었다 (2026-09-20).

무엇이 문제였나. `visual_router.source_depth_of` 는 논문 형식만 읽었다:

    fact_sheet["source_provenance"]["source_depth"]      ← 논문(paper_evidence.attach_evidence)
    fact_sheet["source_depth"]                           ← 리포트(report_source.attach)

리포트 초안 **41건 전부** `source_provenance` 가 없어서 게이트는 매번 `"none"` 으로 읽었고,
`vseq_literal_without_source` 가 **저장된 리포트 지시서 17/17 을 승인 차단**했다.

★ 원문은 실제로 있었다: `report_sources` 373행 중 **341행이 full_text** 다. 게이트가 근거를
  못 본 것이지 근거가 없던 것이 아니다.

★★ 이게 왜 비쌌나. 100% 뜨는 **차단**은 100% 뜨는 경고보다 나쁘다 — 차단이 있으면 재생성이
  돌고, 재생성이 그것을 고칠 수 없으면 **매번 두 번 만들고 매번 막힌다.** 게다가 되먹임
  문구가 리포트에 대해 사실이 아니었다("초록은 어떻게 봤는지 말하지 않는다" — 리포트는
  원문 전문을 갖고 있다). 모델은 고칠 수 없는 것을 고치라는 말을 매 회차 들었다.
"""

from __future__ import annotations

from engine import config, visual_router


def test_it_reads_the_report_shape():
    """리포트는 Fact Sheet 최상위에 적는다(`source_chars` 와 짝이다)."""
    assert visual_router.source_depth_of(
        {"source_depth": "full_text", "source_chars": 3706}) == "full_text"


def test_it_still_reads_the_paper_shape():
    assert visual_router.source_depth_of(
        {"source_provenance": {"source_depth": "full_text"}}) == "full_text"


def test_the_paper_shape_wins_when_both_are_present():
    """논문 쪽은 대조(attach_evidence)를 실제로 돌린 결과다 — 더 센 근거를 쓴다."""
    got = visual_router.source_depth_of(
        {"source_provenance": {"source_depth": "abstract_only"}, "source_depth": "full_text"})
    assert got == "abstract_only"


def test_an_empty_provenance_falls_through_instead_of_swallowing_the_report_value():
    """예전 코드는 `source_provenance` 가 dict 이기만 하면 그 안을 봤다 — 빈 dict 면
    'none' 으로 떨어지면서 최상위 값을 삼켰다."""
    assert visual_router.source_depth_of(
        {"source_provenance": {}, "source_depth": "full_text"}) == "full_text"


def test_no_source_is_still_no_source():
    """★ 이 수정은 **볼 수 있는 근거를 보게 하는 것**이지 게이트를 무르게 하는 것이 아니다.
    리포트 41건 중 21건은 수집이 원문을 못 받았다 — 그 건들은 계속 막혀야 한다."""
    assert visual_router.source_depth_of({}) == "none"
    assert visual_router.source_depth_of(None) == "none"
    assert visual_router.source_depth_of({"source_depth": None}) == "none"
    assert "none" in config.DEPTH_LITERAL_FORBIDDEN


def test_full_text_is_allowed_to_claim_a_literal_observation():
    """전문을 확보했으면 '실제로 이렇게 본다'고 말할 자격이 있다 — 그게 이 게이트의 뜻이다."""
    assert "full_text" not in config.DEPTH_LITERAL_FORBIDDEN
    assert "partial_text" not in config.DEPTH_LITERAL_FORBIDDEN


def test_the_literal_gate_stops_firing_once_the_depth_is_visible():
    """게이트 자체는 그대로다 — 보이는 근거가 달라졌을 뿐이라는 것을 여기서 고정한다."""
    from engine import visual_sequence_contract as vsc

    seq = [{"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
            "stages": [{"stage_id": "S1", "cut_refs": [1], "continuity_mode": "NEW_WORLD",
                        "representation_mode": "LITERAL_OBSERVATION"}]}]
    cuts = [{"cut_no": 1, "visual_role": "MECHANISM"}]
    blocked = vsc.evaluate(seq, cuts, source_depth="none")["block_reasons"]
    allowed = vsc.evaluate(seq, cuts, source_depth="full_text")["block_reasons"]
    assert any(b.startswith("vseq_literal_without_source") for b in blocked)
    assert not any(b.startswith("vseq_literal_without_source") for b in allowed)
