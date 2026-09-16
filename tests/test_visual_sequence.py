"""Visual Sequence 스키마·계약 (v3 Phase 1).

★ 이 파일이 고정하는 것은 **Phase 0 실측이 가르쳐 준 것들**이다
  (docs/실측_continuity_v3.md). 이론이 아니라 화면에서 관찰된 실패를 회귀로 박는다.
"""

from __future__ import annotations

from engine import config, visual_sequence as vs, visual_sequence_contract as vc


def _mutation(**kw):
    """★ 상태는 코드가 계산한다(코덱스 리뷰 S1) — 모델이 제안하는 것은 이 delta 뿐이다."""
    base = {"entity_id": "TOKEN_SET", "property": "position", "operation": "MOVE",
            "visible_change": True, "result_state": "on the right", "claim_ids": ["C01"]}
    base.update(kw)
    return base


def _stage(sid, **kw):
    # ★ 상태의 키는 **선언된 entity_id** 다. 자유 라벨을 쓰면 선언 없는 개체가 화면에
    #   등장하는 길이 열린다(골든A S5 실측 — vseq_state_entity_undeclared).
    base = {
        "stage_id": sid, "cut_refs": [1], "operation": "TRANSFER",
        "camera_operation": "HOLD", "continuity_mode": "NEW_WORLD",
        "mutations": [_mutation()],
        "state_before": {"TOKEN_SET": "on the left"},
        "state_after": {"TOKEN_SET": "on the right"},
        "observable_change": "왼쪽 사람 앞의 토큰이 오른쪽으로 옮겨간다",
        "claim_ids": ["C01"], "entity_refs": ["TOKEN_SET"],
    }
    base.update(kw)
    return base


def _seq(**kw):
    base = {
        "sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
        "world": {"world_id": "W1", "style": "clean 3d", "camera_base": "elevated_three_quarter"},
        "entities": [{"entity_id": "TOKEN_SET", "visual_identity": "small metal discs"}],
        # S2 는 S1 이 만든 상태를 물려받는다 — state_before 가 S1 의 계산 결과와 맞아야 한다.
        "stages": [_stage("S1"),
                   _stage("S2", continuity_mode="CONTINUE_WORLD", continuity_from="S1",
                          state_before={"TOKEN_SET": "on the right"},
                          state_after={"TOKEN_SET": "stacked in the centre"},
                          mutations=[_mutation(operation="GROW",
                                               result_state="stacked in the centre")])],
    }
    base.update(kw)
    return base


def _norm(*seqs):
    return vs.normalize_all(list(seqs))


# ── 규격 토큰 (Phase 0 §3-3 — 영상에 "35°" 가 글자로 박혔다) ──────────
def test_spec_tokens_are_scrubbed_from_prompts():
    """★ 실측: 세계 프롬프트의 `35 degree isometric camera` 를 Veo 가 화면에 글자로 그렸다.

    아침에 이미지에서 잡은 MECHANISM 누출과 같은 계열 — 기계에게 하는 말이 화면에 그려진다.
    금지어 목록으로는 못 막는다("35 degree isometric camera"는 정당한 카메라 서술이다).
    단어가 아니라 **형태**(숫자+단위)를 지운다.
    """
    got = vs.scrub_spec_tokens("premium 3D render, 35 degree isometric camera, 50mm lens, 4K")
    assert "35" not in got and "50mm" not in got and "4K" not in got
    assert "isometric camera" in got        # 문장은 살아남는다
    assert "premium 3D render" in got


def test_world_and_stage_prompts_are_scrubbed_on_normalize():
    seqs = _norm(_seq(world={"world_id": "W1", "style": "clean 3d, 35 degree isometric",
                             "camera_base": "top_down"},
                      stages=[_stage("S1", visual_prompt="a table shot at 24mm")]))
    assert "35" not in seqs[0]["world"]["style"]
    assert "24mm" not in seqs[0]["stages"][0]["visual_prompt"]


def test_camera_is_declared_structurally_and_rendered_as_prose_without_numbers():
    """카메라는 토큰으로만 선언하고, 프롬프트로 나갈 때 숫자 없는 산문이 된다."""
    prose = vs.camera_prose({"camera_base": "top_down"}, {"camera_operation": "DOLLY_IN"})
    assert "overhead" in prose and "closer" in prose
    assert not any(ch.isdigit() for ch in prose)


def test_unknown_camera_base_falls_back_instead_of_failing():
    seqs = _norm(_seq(world={"camera_base": "35_degree_isometric"}))
    assert seqs[0]["world"]["camera_base"] == config.DEFAULT_CAMERA_BASE


# ── VSEQ 계약 ────────────────────────────────────────────────────
def test_no_sequences_means_no_judgement():
    """시퀀스가 없는 지시서는 종전 경로 그대로다 — 계약이 아무것도 하지 않는다(D6)."""
    got = vc.evaluate([], cuts=[{"cut_no": 1}])
    assert got["block_reasons"] == [] and got["warnings"] == []


def test_valid_sequence_passes():
    got = vc.evaluate(_norm(_seq()), cuts=[{"cut_no": 1}])
    assert got["block_reasons"] == []


def test_mechanism_sequence_needs_two_stages():
    got = vc.evaluate(_norm(_seq(stages=[_stage("S1")])), cuts=[{"cut_no": 1}])
    assert any(r.startswith("vseq_too_few_stages") for r in got["block_reasons"])


def test_stage_without_state_change_is_blocked():
    """★ 리뷰 §14: 좋은 검사는 'state_before 와 state_after 가 실제로 다른가'다."""
    flat = _stage("S2", continuity_mode="CONTINUE_WORLD", continuity_from="S1",
                  state_before={"x": 1}, state_after={"x": 1}, observable_change="")
    got = vc.evaluate(_norm(_seq(stages=[_stage("S1"), flat])), cuts=[{"cut_no": 1}])
    assert any(r.startswith("vseq_no_progression") for r in got["block_reasons"])


def test_dangling_continuity_reference_is_blocked():
    bad = _stage("S2", continuity_mode="CONTINUE_WORLD", continuity_from="S99")
    got = vc.evaluate(_norm(_seq(stages=[_stage("S1"), bad])), cuts=[{"cut_no": 1}])
    assert any(r.startswith("vseq_dangling_continuity") for r in got["block_reasons"])


def test_missing_entity_reference_is_blocked():
    bad = _stage("S2", continuity_mode="CONTINUE_WORLD", continuity_from="S1",
                 entity_refs=["GHOST"], state_after={"tokens_left": "none"})
    got = vc.evaluate(_norm(_seq(stages=[_stage("S1"), bad])), cuts=[{"cut_no": 1}])
    assert any(r.startswith("vseq_missing_entity") for r in got["block_reasons"])


# ── VSEQ-7 정량 (Phase 0 §3-1 — 개수는 지켜지지 않는다) ──────────────
def test_counting_objects_to_convey_an_exact_number_is_blocked():
    """★ 실측: "ten identical discs" 를 요구했는데 화면엔 4묶음이 나왔다.

    어제 v2 의 컷7("동전 10개 vs 11~12개로 15% 증가 표현")이 정확히 이 실패였다 —
    애초에 성립 불가능한 계획이었다.
    """
    bad = _stage("S2", continuity_mode="CONTINUE_WORLD", continuity_from="S1",
                 state_after={"tokens_left": "none"},
                 visual_prompt="the right stack is exactly 15 percent taller than the left")
    got = vc.evaluate(_norm(_seq(stages=[_stage("S1"), bad])), cuts=[{"cut_no": 1}])
    assert any(r.startswith("vseq_quantitative_visual") for r in got["block_reasons"])


def test_direction_and_relation_are_allowed():
    """시각이 표현할 수 있는 것 — 방향과 관계. 이것까지 막으면 게이트가 무시당한다."""
    ok = _stage("S2", continuity_mode="CONTINUE_WORLD", continuity_from="S1",
                state_after={"tokens_left": "none"},
                visual_prompt="the stack in front of the right man is visibly taller than before")
    got = vc.evaluate(_norm(_seq(stages=[_stage("S1"), ok])), cuts=[{"cut_no": 1}])
    assert not any(r.startswith("vseq_quantitative_visual") for r in got["block_reasons"])


# ── 지표 ─────────────────────────────────────────────────────────
def test_metrics_report_direction_of_travel():
    got = vc.evaluate(_norm(_seq()), cuts=[{"cut_no": 1}])
    m = got["metrics"]
    assert m["stage_count"] == 2
    assert m["world_reset_rate"] == 0.5 and m["continuity_rate"] == 0.5


def test_all_new_worlds_warns_that_it_is_not_really_a_sequence():
    seqs = _norm(_seq(stages=[_stage("S1"), _stage("S2", state_after={"tokens_left": "none"})]))
    got = vc.evaluate(seqs, cuts=[{"cut_no": 1}])
    assert any(w.startswith("vseq_world_reset_high") for w in got["warnings"])


def test_reason_codes_have_web_labels():
    labels = open("web/lib/blockLabels.ts", encoding="utf-8").read()
    for code in vc.BLOCK_REASONS:
        assert f"{code}:" in labels, code


def test_feedback_prompt_says_what_and_why_and_how():
    fb = vc.feedback_prompt(["vseq_quantitative_visual:SEQ1/S2"])
    assert "overlay_plan" in fb and "개수" in fb


def test_cut_to_stage_keeps_cut_as_the_timing_unit():
    """Cut 을 없애지 않는다(작업지시서 Paper §2.1) — 컷에서 stage 를 찾을 수 있어야 한다."""
    seqs = _norm(_seq(stages=[_stage("S1", cut_refs=[3]),
                              _stage("S2", cut_refs=[4], continuity_mode="CONTINUE_WORLD",
                                     continuity_from="S1", state_after={"t": "none"})]))
    idx = vs.cut_to_stage(seqs)
    assert idx[3]["stage_id"] == "S1" and idx[4]["stage_id"] == "S2"
    assert idx[4]["_sequence"]["sequence_id"] == "SEQ1"


def test_percent_regex_actually_matches_a_percent_sign():
    """★ 이 저장소가 이미 한 번 한 실수의 회귀 가드.

    `%` 뒤에 `\b` 를 붙이면 "15%" 가 **영원히 매치되지 않는다**(`%` 는 비단어라 뒤 공백과의
    사이에 경계가 없다). photo_contract 에서 같은 버그를 고친 날, 나는 이 파일에서 똑같이
    반복했다 — 자기리뷰에서 발견했다. 정규식은 눈으로 읽어서 통과시키면 안 된다.
    """
    from engine.visual_sequence_contract import _QUANTITATIVE_VISUAL as Q

    for text in ("the bar shows 15%", "a 16.9 % increase", "exactly 15 discs",
                 "stacks of 20 coins represent the result", "precisely 359 figures"):
        assert Q.search(text), text
    for text in ("the stack is visibly taller than before", "more discs accumulate",
                 "two groups stand in parallel lines", "three men walk in"):
        assert not Q.search(text), text
