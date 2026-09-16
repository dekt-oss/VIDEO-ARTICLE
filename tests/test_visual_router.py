"""Visual Router (v3 Phase 2, 코덱스 리뷰 반영 2026-08-30) — 무엇을 어떻게 보여줄 것인가.

★ 이 파일이 고정하는 것은 우리가 **실제로 저지른** 실패들이다:
  ① 초록만 있는 논문에 코→뇌 분자 이동을 그렸다(v2, 근거 없는 기전).
  ② 15% 를 동전 개수로 표현하려 했다(Phase 0 실측: 생성 모델은 개수를 못 지킨다).
  ③ beat 고정표만 보고 라우팅해 시퀀스 stage 8개를 차트로 보냈다(골든 실측 08-29).
  ④ 수치가 시퀀스를 이기게 만들어 세계를 끊었다(코덱스 리뷰 R1 — 08-30 에 뒤집었다).
  ⑤ 시퀀스에 든 것만으로 CTA 컷이 기전 도해가 됐다(코덱스 리뷰 §10).

★★ ②와 ④의 차이가 이 파일의 핵심이다. 실측이 말한 것은
   "생성 이미지에게 정확한 개수를 그리라고 하면 안 된다"이지
   "수치를 말하는 장면은 3D 로 만들면 안 된다"가 아니었다.
   그래서 지금은 **세계를 유지한 채 코드 오버레이를 얹는다**(base + precision_layer).
"""

from __future__ import annotations

from engine import config, visual_router as vr


def _cut(**kw):
    base = {"cut_no": 1, "beat": "MECHANISM", "narration_ko": "원리를 설명합니다"}
    base.update(kw)
    return base


# ── 근거 깊이는 **미디어가 아니라 구체성**을 제한한다 (코덱스 리뷰 R2) ──
def test_abstract_only_no_longer_downgrades_the_media():
    """★ 뒤집힌 결정(R2): `abstract_only ≠ 기전 시각화 금지`.

    종전에는 REALITY 로 후퇴시켰는데, 그 후퇴는 근거 없는 컷을 막지 못하면서
    (골든A 는 후퇴하고도 "사전 등록된 무작위 실험"을 그렸다) 정상 컷만 벌했다.
    """
    got = vr.route(_cut(beat="INTERVENTION"), source_depth="abstract_only")
    assert got["base"] == "MECHANISM_SEQUENCE"
    assert not any(r.startswith("depth_blocks_mechanism") for r in got["reasons"])


def test_abstract_only_carries_detail_restrictions_instead():
    """후퇴 대신 **구체성 제약**을 실어 보낸다 — 실제 판정은 원문 대조가 한다."""
    got = vr.route(_cut(beat="INTERVENTION"), source_depth="abstract_only")
    assert set(got["detail_restrictions"]) == {"protocol", "apparatus", "physiology"}
    assert any(r.startswith("depth_restricts_detail") for r in got["reasons"])


def test_full_body_has_no_detail_restrictions():
    """전문이 있으면 원문이 곧 근거다 — 제약을 걸 이유가 없다."""
    got = vr.route(_cut(beat="MECHANISM"), source_depth="full_body")
    assert got["base"] == "MECHANISM_SEQUENCE" and got["detail_restrictions"] == []


def test_no_source_is_the_most_restricted():
    """대조가 안 돈 초안(엣지 경로)은 무엇이 지불되는지 모른다 — 가장 좁게 제한한다."""
    got = vr.route(_cut(beat="MECHANISM"), source_depth="none")
    assert got["detail_restrictions"] == ["protocol", "apparatus", "physiology"]


# ── 수치는 세계를 끊지 않고 **얹힌다** (코덱스 리뷰 R1) ──────────────
def test_a_number_inside_a_sequence_keeps_the_world_and_adds_a_layer():
    """★★ ENTRY-3 회귀. 골든B 컷9("7분 주기가 8초 변했다")가 실측에서 세계 밖으로
    튕겨 나갔다. 지금은 같은 로켓이 계속 돌고 정확한 수치는 코드 오버레이가 말한다.
    """
    cuts = [_cut(cut_no=1, beat="RESULT", claim_ids=["C1"],
                 narration_ko="7분 주기가 8초 넘게 변한 겁니다")]
    got = vr.route_all(cuts, source_depth="full_body", sequences=[_seq()])[0]
    assert got["base"] == "MECHANISM_SEQUENCE"          # 세계가 유지된다
    assert got["precision_layer"] == "CODE_OVERLAY"     # 수치는 코드가 그린다
    assert "number_needs_precision_layer" in got["reasons"]


def test_a_number_outside_a_sequence_is_the_whole_visual():
    """세계가 없으면 화면 전체가 그래픽이다 — 그 위에 레이어를 또 얹지 않는다."""
    got = vr.route(_cut(beat="RESULT", narration_ko="위약 그룹보다 15% 증가했습니다"),
                   source_depth="full_body")
    assert got["base"] == "CODE_VIZ" and got["precision_layer"] == ""
    assert "number_is_the_visual" in got["reasons"]


def test_english_narration_numbers_are_caught_too():
    got = vr.route(_cut(beat="RESULT", narration_ko="", narration_en="a 16.9 percent increase"),
                   source_depth="full_body")
    assert got["base"] == "CODE_VIZ"


def test_prose_without_numbers_gets_no_precision_layer():
    """방향·관계만 말하는 컷에 오버레이를 붙이면 화면이 카드로 뒤덮인다."""
    got = vr.route(_cut(beat="MECHANISM", narration_ko="궤도를 거꾸로 되짚어 갑니다"),
                   source_depth="full_body")
    assert got["base"] == "MECHANISM_SEQUENCE" and got["precision_layer"] == ""


def test_year_alone_is_not_a_measurement():
    """연도·순번까지 수치로 보면 거의 모든 컷에 오버레이가 붙는다 — 단위를 요구한다."""
    got = vr.route(_cut(beat="MECHANISM", narration_ko="2026년에 관측했습니다"),
                   source_depth="full_body")
    assert got["precision_layer"] == ""


def test_a_date_next_to_a_real_measurement_still_gets_the_layer():
    """연도를 지우되 **진짜 수치는 남아야** 한다 — 지우기가 과해지면 수치가 그림으로 샌다."""
    got = vr.route(_cut(beat="MECHANISM", narration_ko="2026년 관측에서 8초가 늘었습니다"),
                   source_depth="full_body")
    assert got["precision_layer"] == "CODE_OVERLAY"


def test_year_scrub_does_not_eat_real_quantities():
    assert vr.speaks_a_number({"narration_ko": "참가자는 359명이었습니다"})
    assert vr.speaks_a_number({"narration_ko": "2026년 관측에서 8초가 늘었습니다"})
    assert not vr.speaks_a_number({"narration_ko": "2026년에 관측했습니다"})
    # 1900~2099 밖의 네 자리는 연도가 아니다 — 지워지면 안 된다.
    assert vr.speaks_a_number({"narration_ko": "표본은 3500명입니다"})


# ── 잡다 ─────────────────────────────────────────────────────────
def test_unknown_beat_falls_back_instead_of_failing():
    assert vr.sanitize_beat("무언가") == config.DEFAULT_BEAT_KIND
    assert vr.sanitize_beat("mechanism") == "MECHANISM"


def test_source_depth_comes_from_the_fact_sheet_provenance():
    assert vr.source_depth_of({"source_provenance": {"source_depth": "full_body"}}) == "full_body"
    assert vr.source_depth_of({}) == "none"          # 대조가 안 돈 초안
    assert vr.source_depth_of(None) == "none"


def test_summary_counts_what_actually_happened():
    cuts = [_cut(cut_no=1, beat="INTERVENTION"),
            _cut(cut_no=2, beat="RESULT", narration_ko="15% 증가"),
            _cut(cut_no=3, beat="QUESTION")]
    summary = vr.routing_summary(vr.route_all(cuts, source_depth="abstract_only"))
    assert summary["treatments"]["CODE_VIZ"] == 1
    assert summary["detail_restricted"] == 3         # abstract_only 는 전 컷에 제약이 걸린다
    assert summary["precision_layer_count"] == 0     # CODE_VIZ 위에는 레이어를 얹지 않는다


# ── 시퀀스가 라우팅을 이긴다 (2026-08-29 골든 실측) ──────────────────
def _seq(role="REALITY_ANCHOR", stages=None):
    return {"sequence_id": "SEQ1", "sequence_role": role,
            "world": {"world_id": "W"}, "entities": [],
            "stages": stages if stages is not None else [
                {"stage_id": "S1", "cut_refs": [1], "observable_change": "로켓이 다가온다",
                 "claim_ids": ["C1"], "state_before": {"a": 1}, "state_after": {"a": 2}},
                {"stage_id": "S2", "cut_refs": [2], "observable_change": "궤적이 그려진다",
                 "claim_ids": ["C2"], "state_before": {"a": 2}, "state_after": {"a": 3}}]}


def test_a_cut_inside_a_sequence_becomes_a_mechanism_cut():
    """★ 골든 실측의 실패: beat 고정표만 보니 `RESULT` 라벨 8개가 전부 차트로 갔는데,
    그 컷들은 **시퀀스의 stage** 였다. 시퀀스는 "같은 세계에서 궤적을 거꾸로 그린다"고 하고
    라우터는 같은 컷을 "차트로 그려라"라고 했다 — 둘을 맞추는 코드가 없었다.
    """
    cuts = [_cut(cut_no=1, beat="RESULT", claim_ids=["C1"],
                 narration_ko="궤도를 거꾸로 추적했습니다")]
    got = vr.route_all(cuts, source_depth="full_body", sequences=[_seq()])
    assert got[0]["base"] == "MECHANISM_SEQUENCE"
    assert "in_visual_sequence" in got[0]["reasons"]
    assert got[0]["stage_ref"] == "S1" and got[0]["world_ref"] == "W"


def test_a_cut_that_pays_no_claim_only_inherits_the_background():
    """★★ ENTRY-6 회귀. 골든B 컷15 는 CTA("댓글로 의견을 남겨주세요")인데 stage 의
    cut_refs 에 들어 있다는 것만으로 MECHANISM_SEQUENCE 가 됐다.

    사실 주장을 지불하지 않는 컷에는 기전 도해를 붙일 근거가 없다. 다만 세계 참조는
    남겨 배경 연속성은 잇는다 — 컷을 세계 밖으로 내던지지 않는다.
    """
    cuts = [_cut(cut_no=1, beat="CONCLUSION", claim_ids=[],
                 narration_ko="어떻게 생각하시나요? 댓글로 남겨주세요")]
    got = vr.route_all(cuts, source_depth="full_body", sequences=[_seq()])[0]
    assert got["base"] != "MECHANISM_SEQUENCE"
    assert "connective_in_world" in got["reasons"]
    assert got["world_ref"] == "W"                   # 배경은 이어진다


def test_a_claim_mismatch_warns_but_does_not_break_the_world():
    """★ 반대 방향의 오탐을 막는다: 골든B 컷4("정체는 팰컨 9 상단부입니다")는 그 시퀀스의
    일부인데 모델이 stage 와 다른 claim 을 달았다. 여기서 끊으면 옳게 만든 시퀀스가
    태깅 실수 하나로 조각난다 — 세계는 잇고 사유만 남긴다.
    """
    cuts = [_cut(cut_no=1, beat="RESULT", claim_ids=["C9"], narration_ko="정체가 밝혀졌습니다")]
    got = vr.route_all(cuts, source_depth="full_body", sequences=[_seq()])[0]
    assert got["base"] == "MECHANISM_SEQUENCE"
    assert "cut_claim_not_in_stage" in got["reasons"]


def test_a_cut_outside_any_sequence_keeps_the_beat_default():
    cuts = [_cut(cut_no=9, beat="RESULT", narration_ko="결과입니다")]
    got = vr.route_all(cuts, source_depth="full_body", sequences=[_seq()])
    assert got[0]["base"] == "CODE_VIZ" and got[0]["stage_ref"] == ""


def test_the_model_label_does_not_decide_whether_it_is_a_progression():
    """★ 실측: 세계 하나에서 6단계가 이어지는 완벽한 기전 진행을 모델이 `REALITY_ANCHOR`
    라고 라벨했다. 라벨을 믿으면 그 시퀀스가 통째로 무시된다 — **구조를 보고 코드가 판정한다.**
    """
    assert vr.sequence_is_progression(_seq(role="REALITY_ANCHOR")) is True
    assert vr.sequence_is_progression(_seq(role="MECHANISM_SEQUENCE")) is True


def test_a_single_stage_sequence_is_not_a_progression():
    """stage 하나짜리는 시퀀스가 아니다 — 그것까지 도해로 보내면 라우터가 무의미해진다."""
    one = _seq(stages=[{"stage_id": "S1", "cut_refs": [1], "observable_change": "x",
                        "claim_ids": ["C1"], "state_before": {}, "state_after": {}}])
    assert vr.sequence_is_progression(one) is False
    got = vr.route_all([_cut(cut_no=1, beat="RESULT", claim_ids=["C1"], narration_ko="결과")],
                       source_depth="full_body", sequences=[one])
    assert got[0]["base"] == "CODE_VIZ"


def test_the_resolved_plan_is_the_single_authoritative_object():
    """★ 코덱스 리뷰 R3: Phase 3 렌더러가 무엇을 믿을지 여기서 못박는다.

    계약·비용·렌더·QA 가 전부 이 객체 하나를 소비한다 — 넷이 각자 판정하면
    "schema 필드를 renderer 가 무시한다"가 그대로 재현된다.
    """
    got = vr.route(_cut(beat="MECHANISM"), source_depth="full_body")
    for key in ("base", "precision_layer", "representation_mode", "sequence_ref",
                "world_ref", "stage_ref", "claim_refs", "detail_restrictions", "reasons"):
        assert key in got, key
    assert got["representation_mode"] in config.REPRESENTATION_MODES
