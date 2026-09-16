"""원문 확보 수준을 **프롬프트가 모델에게 말하는지** 본다 (2026-08-31 재생성 실측 반영).

★ 무엇이 문제였나: 재생성본이 `vseq_literal_without_source:SEQ2/S4` 로 승인 차단됐다.
  게이트(engine/visual_sequence_contract)는 `fact_sheet.source_provenance.source_depth`
  를 보고 LITERAL_OBSERVATION 을 **통째로** 금지하는데, 모델은 자기가 어느 수준의 원문을
  받았는지 프롬프트에서 들은 적이 없었다. 지침은 "확실치 않으면 SCHEMATIC_PRINCIPLE" 이라고만
  했고 — 모델 입장에서 초록인지 전문인지 구분할 방법이 없으니 "확실하다"고 판단할 수도 있다.

★ 컷 수 상한·영상 상한·에셋 상한에 이은 **네 번째** "프롬프트와 코드가 다른 것을 안다" 다.
  그래서 이 파일이 보는 것은 문구가 아니라 **두 쪽이 같은 함수를 쓰는가**이다.
"""

from __future__ import annotations

from engine import (config, directive as dv, visual_router,
                    visual_sequence as vs, visual_sequence_contract as vc)


def _row(fact_sheet: dict) -> dict:
    return {"fact_sheet": fact_sheet,
            "script_md": "한 문장이다. 두 문장이다. 세 문장이다.",
            "video_prompts": [],
            "video_flow": {"content_plan": {"selected_mode": "standard"}}}


def _fs(depth: str | None) -> dict:
    fs: dict = {"title": "T", "claims": []}
    if depth is not None:
        fs["source_provenance"] = {"source_depth": depth}
    return fs


def test_forbidden_depths_are_told_outright_not_left_to_judgment():
    """★ 금지 수준에서는 **단정**해야 한다 — "알아서 판단하라"가 실패의 원인이었다."""
    for depth in config.DEPTH_LITERAL_FORBIDDEN:
        g = dv.source_depth_guidance(_fs(depth))
        assert "[원문 확보 수준]" in g
        assert depth in g, "어느 수준인지 이름으로 말해야 한다"
        assert "LITERAL_OBSERVATION" in g and "차단" in g, (depth, g)
        assert "SCHEMATIC_PRINCIPLE" in g, "대신 무엇을 쓸지 알려줘야 한다"


def test_allowed_depth_does_not_forbid_but_does_not_hand_out_a_blank_check():
    """★ 반대 방향. 깊다고 전부 실측 장면이 되는 것도 아니다 — 옳게 한 것을 벌하지 않되
    조건을 지운 것도 아니다."""
    g = dv.source_depth_guidance(_fs("full_body"))
    assert "LITERAL_OBSERVATION" in g
    assert "차단" not in g
    assert "SCHEMATIC_PRINCIPLE" in g, "조건 미달 stage 는 여전히 도식이다"


def test_missing_provenance_is_treated_as_forbidden_like_the_gate_does():
    """★ source_provenance 가 아예 없는 Fact Sheet(엣지 경로 초안)도 금지 쪽이다.

    게이트가 그렇게 판정하므로 프롬프트도 그렇게 말해야 한다. 실제로 재생성 실측의
    Fact Sheet 가 바로 이 모양이었다.
    """
    assert visual_router.source_depth_of(_fs(None)) in config.DEPTH_LITERAL_FORBIDDEN
    assert "차단" in dv.source_depth_guidance(_fs(None))


def test_prompt_and_gate_read_the_same_function():
    """★★ 이 파일의 핵심. 문구가 아니라 **같은 함수를 쓰는가**를 본다.

    둘이 각자 판정하면 오늘 맞고 내일 어긋난다 — 이 저장소가 세 번 겪은 실패다.
    """
    for depth in ("full_body", "partial_body", "abstract_only", "parse_failed", "none", None):
        fs = _fs(depth)
        resolved = visual_router.source_depth_of(fs)   # 게이트가 쓰는 바로 그 함수
        g = dv.source_depth_guidance(fs)
        forbidden_in_prompt = "차단" in g
        assert forbidden_in_prompt == (resolved in config.DEPTH_LITERAL_FORBIDDEN), (depth, g)


def test_the_stated_rule_actually_passes_the_gate():
    """★ 프롬프트가 시킨 대로(SCHEMATIC_PRINCIPLE) 만들면 실제로 통과해야 한다.

    "말은 이렇게 하고 검사는 저렇게 한다"를 막는 대조다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "REALITY_ANCHOR",
           "world": {"world_id": "W"}, "entities": [],
           "stages": [{"stage_id": "S1", "cut_refs": [1],
                       "representation_mode": "SCHEMATIC_PRINCIPLE",
                       "observable_change": "x", "claim_ids": ["C1"]}]}
    for depth in config.DEPTH_LITERAL_FORBIDDEN:
        got = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}], source_depth=depth)
        assert not any(r.startswith("vseq_literal_without_source")
                       for r in got["block_reasons"]), (depth, got["block_reasons"])


def test_guidance_reaches_the_photo_prompt_and_only_there():
    """★ 만들어 놓고 한쪽만 연결하는 것이 이 저장소의 상습 실패다 — 배선을 본다.

    시퀀스를 쓰는 것은 photo 뿐이다. 시퀀스가 없는 버전에는 representation_mode 자체가
    없으므로, 거기까지 설교를 붙이면 프롬프트만 희석된다.
    """
    row = _row(_fs("abstract_only"))
    assert "[원문 확보 수준]" in dv.directive_user_prompt(row, "photo")
    for other in ("comic", "webtoon", "image_sequence"):
        if other not in dv.VERSION_GUIDANCE:
            continue
        assert "[원문 확보 수준]" not in dv.directive_user_prompt(row, other), other


def test_depth_labels_cover_every_depth_the_engine_can_produce():
    """★ 라벨이 빠지면 화면에 원시 코드가 나간다. 원장(paper_evidence)이 기준이다."""
    from engine import paper_evidence
    for depth in paper_evidence.DEPTH_GRADE_CEILING:
        assert depth in dv.DEPTH_LABELS, depth
