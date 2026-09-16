"""시퀀스(stage) 단위 렌더 계획 (운영자 지시 2026-09-05: "설계안대로 구현해").

설계: docs/설계안_시퀀스단위_렌더_v1.md

무엇을 바꾸는가: 렌더 단위를 **컷 → stage** 로. 컷마다 클립 1개를 만들고 나레이션이
남으면 마지막 프레임을 얼리던 것을(clip_fit hold) 그만두고, stage 하나를 연속 영상으로
채운 뒤 컷은 그 영상의 **서로 다른 구간**을 본다.

실측 근거(세마글루타이드 렌더 c43d87a4): hold 5컷, 컷8 은 12.7초 나레이션에 8초 클립
→ 4.7초 정지. 컷 경계마다 화면이 끊겼다.

★ 이 파일은 **계획 로직만** 본다 — 순수 함수라 네트워크·파일·비용이 없다.
  실제 영상이 이어져 보이는지는 렌더를 돌려야 알고, 그건 운영자 승인 사항이다.
"""

from __future__ import annotations

from engine import config
from engine import stage_render as sr


def _cut(no, stage=None, sec=5):
    c = {"cut_no": no, "estimated_sec": sec}
    if stage is not None:
        c["resolved_visual_plan"] = {"stage_ref": stage}
    return c


# ── 컷 → stage 묶기 ──────────────────────────────────────────
def test_consecutive_cuts_in_one_stage_become_one_group():
    g = sr.group_cuts([_cut(1, "S1"), _cut(2, "S1"), _cut(3, "S2")])
    assert [(x["stage_id"], x["indexes"]) for x in g] == [("S1", [0, 1]), ("S2", [2])]


def test_a_cut_without_a_stage_inherits_the_previous_one():
    """★ 훅·CTA 는 stage 가 없다. 새 stage 를 만들면 그 컷이 독립 영상이 되어 또 끊긴다."""
    # ★ 끝에 다른 stage 컷을 하나 둔다 — 2026-09-14 부터 **마지막 컷은 늘 혼자 선다**
    #   (STAGE_FINAL_CUT_OWN_CLIP). 이 테스트가 보려는 것은 '물려받기'라 마지막 자리를 비켜 준다.
    g = sr.group_cuts([_cut(1, "S1"), _cut(2, None), _cut(3, "S1"), _cut(4, "S2")])
    assert g[0]["indexes"] == [0, 1, 2]


def test_leading_cuts_without_a_stage_do_not_get_pulled_into_the_first_stage():
    """★ 훅이 본문 세계로 끌려들어가면 화면이 어긋난다 — 자기들끼리 묶는다."""
    g = sr.group_cuts([_cut(1, None), _cut(2, None), _cut(3, "S1")])
    assert [(x["stage_id"], x["indexes"]) for x in g] == [("", [0, 1]), ("S1", [2])]


def test_the_same_stage_appearing_twice_apart_is_not_merged():
    """A B A 에서 두 A 를 이어 붙이면 없던 연속성을 주장하는 것이다."""
    g = sr.group_cuts([_cut(1, "A"), _cut(2, "B"), _cut(3, "A")])
    assert [x["indexes"] for x in g] == [[0], [1], [2]]


# ── 클립 나누기 ──────────────────────────────────────────────
def test_a_long_stage_is_split_at_the_hard_limit():
    """★ Veo 가 한 번에 8초까지만 만든다 — 이건 물리 제약이라 우회할 수 없다."""
    assert sr.plan_clips(20.0) == [8.0, 8.0, 4.0]
    assert max(sr.plan_clips(60.0)) <= max(config.VEO_CLIP_SEC_TIERS)


def test_the_remainder_uses_the_smallest_tier_that_covers_it():
    """남는 3초에 8초를 사면 5초를 버린다 — 덮는 가장 작은 티어를 고른다."""
    assert sr.plan_clips(13.6) == [8.0, 6.0]
    assert sr.plan_clips(3.0) == [4.0]


def test_generated_seconds_always_cover_the_narration():
    """★★ 이것이 hold(정지)를 없애는 조건이다 — 모자라면 반드시 얼어붙는다."""
    for sec in (1.0, 4.0, 7.9, 8.1, 13.6, 17.4, 25.0, 40.0):
        assert sum(sr.plan_clips(sec)) >= sec - 0.05, sec


def test_a_zero_length_stage_still_gets_one_clip():
    assert sr.plan_clips(0.0) == [float(min(config.VEO_CLIP_SEC_TIERS))]


# ── 연쇄 ─────────────────────────────────────────────────────
def test_the_first_clip_never_inherits():
    assert sr.chain_breaks(1) == [False]
    assert sr.chain_breaks(3)[0] is False


def test_the_chain_restarts_at_the_depth_cap():
    """★ 깊이가 깊을수록 인물·재질이 흐려진다 — 상한에서 원본으로 되돌아간다.
    이 상한을 **재 보지 않고 올리면 안 된다**(설계안 §4 ①)."""
    br = sr.chain_breaks(6, max_chain_depth=2)
    assert br == [False, True, True, False, True, True]


def test_depth_cap_of_one_alternates():
    assert sr.chain_breaks(4, max_chain_depth=1) == [False, True, False, True]


# ── 컷별 구간 ────────────────────────────────────────────────
def test_cuts_take_adjacent_windows_of_one_continuous_video():
    """★★ 이것이 핵심이다 — 컷은 화면을 자르지 않고 연속 영상의 다른 구간을 볼 뿐이다."""
    w = sr.slice_windows([3.0, 5.0, 2.5])
    assert w == [(0.0, 3.0), (3.0, 5.0), (8.0, 2.5)]
    assert w[1][0] == w[0][0] + w[0][1]        # 틈이 없다
    assert w[2][0] == w[1][0] + w[1][1]


def test_windows_never_leave_a_gap_that_would_show_a_freeze():
    durs = [4.4, 7.5, 3.1]
    w = sr.slice_windows(durs)
    assert round(w[-1][0] + w[-1][1], 3) == round(sum(durs), 3)


# ── 전체 계획 ────────────────────────────────────────────────
def test_the_real_directive_plan_matches_the_design_document():
    """★ 설계안이 예측한 수치를 그대로 재현하는가 — 6 stage, 클립 14개.

    ★ 생성 초수 96 → 92 (2026-09-13): 클립 계획이 '상한부터 채우기'에서 **덮을 수 있는 가장
      작은 합**으로 바뀌었다(운영자 지시 "자투리도 잡아줘"). 같은 나레이션을 4초 덜 사고도
      아래 '나레이션보다 짧게 생성하지 않는다'는 불변식은 그대로다.
    """
    cuts = ([_cut(1, "S1"), _cut(2, "S1")] + [_cut(3, "S2"), _cut(4, "S2")]
            + [_cut(i, "S3") for i in (5, 6, 7)] + [_cut(8, "S4"), _cut(9, "S4")]
            + [_cut(i, "S5") for i in (10, 11, 12)] + [_cut(13, "S6"), _cut(14, "S6")])
    durs = [6.06, 7.50, 4.80, 8.36, 7.20, 4.80, 4.63, 12.66, 4.70, 4.10, 3.10, 7.36, 4.40, 6.16]
    plans = sr.plan_stage(cuts, durs)
    s = sr.savings(plans, len(cuts))
    # ★ 6 → 7 묶음, 92 → 94초 (2026-09-14): 마지막 컷(14)이 S6 영상에서 떨어져 **자기 클립**을
    #   갖는다(운영자 실측 "마무리가 이상하다" — 결론 컷이 앞 영상에서 잘려 자기 그림이 없었다).
    #   S6(나레이션 10.6초)를 한 덩어리로 12초 사던 것이 컷 13(4.4초)→6초, 컷 14(6.2초)→8초로
    #   나뉘어 2초 늘었다. 클립 수는 그대로 14다(2개 → 1개+1개).
    assert s["stages"] == 7
    assert s["clips"] == 14
    assert s["generated_sec"] == 94.0
    # 어느 stage 도 나레이션보다 짧게 생성하지 않는다 = 정지 0회
    for p in plans:
        assert p["generated_sec"] >= p["total_sec"] - 0.05, p["stage_id"]


def test_every_cut_gets_exactly_one_window():
    cuts = [_cut(1, "S1"), _cut(2, "S1"), _cut(3, "S2")]
    plans = sr.plan_stage(cuts, [3.0, 4.0, 5.0])
    assert sum(len(p["windows"]) for p in plans) == len(cuts)


# ── 켜짐 조건 ────────────────────────────────────────────────
def test_a_directive_without_stages_keeps_the_old_cut_path():
    """★ 새 경로가 옛 산출물을 조용히 바꾸면 안 된다."""
    assert sr.enabled({"version_type": "photo"}) is False
    assert sr.enabled({"version_type": "photo", "visual_sequences": []}) is False


def test_only_chain_capable_versions_use_stage_mode():
    """연쇄가 없는 버전에서 stage 를 이어 붙이면 매 클립이 새 세계가 된다."""
    h = {"version_type": "comic", "visual_sequences": [{"stages": [{"stage_id": "S1"}]}]}
    assert sr.enabled(h) is False


def test_a_photo_directive_with_stages_turns_it_on():
    h = {"version_type": "photo", "visual_sequences": [{"stages": [{"stage_id": "S1"}]}]}
    assert sr.enabled(h) is True


def test_the_switch_can_turn_it_off():
    """실패했을 때 되돌리는 길이 있어야 한다."""
    from unittest import mock
    h = {"version_type": "photo", "visual_sequences": [{"stages": [{"stage_id": "S1"}]}]}
    with mock.patch.object(config, "STAGE_RENDER_ENABLED", False):
        assert sr.enabled(h) is False
