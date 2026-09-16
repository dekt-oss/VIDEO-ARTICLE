"""클립 움직임 문턱 — 발행 벤치마크가 기준선이 된 뒤에야 생긴 검사(2026-09-04).

배경: 운영자가 첫 실사형 렌더($5.39)를 보고 "역동적으로 움직이며 원리를 설명해야 하는데
의미 없는 화면"이라 했다. 그 인상평을 숫자로 확인했다 —

    발행 벤치마크(신비한 건축사전 시화호 편, 105초, 3구간)
        0.0078 / 0.0134 / 0.0150  → 중앙값 0.0117
    우리 첫 실사형 렌더 13컷
        0.0005 ~ 0.0028           → 중앙값 0.0012   (**1/9.5**)

종전에는 motion_median 을 clip_metrics 에 **기록만** 했다. 문턱이 없던 이유는 정당했다
(좋은 표본이 없었다). 이제 생겼으므로 문턱을 건다 — 다만 경고까지다.

★ 여기 쓰는 숫자는 지어낸 것이 아니라 **실측 렌더의 값**이다.
  docs/벤치마크_시화호_구조분석_2026-09-04.md 4절.
"""

from __future__ import annotations

from engine import config, render_qa


# 첫 실사형 렌더(2026-09-03)의 영상 컷 실측 motion_median.
OUR_FIRST_RENDER = [0.0005, 0.0008, 0.0011, 0.0012, 0.0019, 0.0023, 0.0028]
BENCH_MEDIAN = 0.0117
# ★ 2026-09-14 재교정의 근거 두 무리.
#   운영자가 같은 그림·같은 비트 A/B 클립을 보고 "둘 다 괜찮다"고 판정한 값(무광 CG 화풍):
OPERATOR_ACCEPTED = [0.00093, 0.00113]
#   스틸 한 장을 8초로 늘린 **진짜 정지 영상**(같은 측정기, 실측):
TRULY_STATIC = [0.00001, 0.00001, 0.00001]


def _rows(values, measured=True):
    return [{"cut_no": i, "measured": measured, "motion_median": v}
            for i, v in enumerate(values, 1)]


def test_a_truly_static_video_is_flagged_entirely():
    """정지 화면은 여전히 '영상 전체' 경고가 떠야 한다 — 안 뜨면 문턱이 헐겁다.

    ★ 2026-09-14 전에는 이 자리가 "우리 첫 렌더 전부 경고"였다. 그 판정은 실사 벤치 기준이었고,
      운영자가 우리 화풍의 같은 수준 클립을 보고 괜찮다고 해서 뒤집혔다(config 주석).
    """
    out = render_qa.evaluate_clip_motion(_rows(TRULY_STATIC))
    assert out["low_cuts"] == [1, 2, 3]
    assert len(out["warnings"]) == 1
    assert "거의 정지" in out["warnings"][0]


def test_our_style_at_the_operator_accepted_level_is_not_noise():
    """운영자가 괜찮다고 본 수준(무광 CG)에 경고를 달면 경고가 소음이 된다 — 실제로 그랬다."""
    for values in (OPERATOR_ACCEPTED, OUR_FIRST_RENDER):
        out = render_qa.evaluate_clip_motion(_rows(values))
        assert out["warnings"] == [], values


def test_benchmark_level_motion_passes_clean():
    """발행 영상 수준이면 경고가 없어야 한다 — 있으면 문턱이 과하다(경고가 소음이 된다)."""
    out = render_qa.evaluate_clip_motion(_rows([0.0078, 0.0134, 0.0150]))
    assert out["warnings"] == []
    assert out["low_cuts"] == []


def test_a_single_still_cut_is_a_soft_note_not_a_whole_video_warning():
    """컷 하나 정지는 연출 선택일 수 있다(마지막 여운). 문장이 달라야 한다."""
    # 정지 컷 값은 **진짜 정지** 실측(0.00001)을 쓴다 — 2026-09-14 재교정 전에는 0.0005 였고
    # 그 값은 이제 우리 화풍의 정상 범위다.
    out = render_qa.evaluate_clip_motion(_rows([0.00001, 0.012, 0.013, 0.014]))
    assert out["low_cuts"] == [1]
    assert "영상 컷" in out["warnings"][0] and "/" not in out["warnings"][0].split("개")[0]


def test_unmeasured_cuts_do_not_count_as_low():
    """★ 스틸 컷은 정지가 정상이다. 측정 실패를 품질 미달로 부르면 지표가 거짓말한다."""
    rows = _rows([0.012, 0.013]) + _rows([0.0], measured=False)
    out = render_qa.evaluate_clip_motion(rows)
    assert out["measured_cuts"] == 2 and out["warnings"] == []


def test_negative_sentinel_is_not_treated_as_zero_motion():
    """clip_candidates 는 '못 쟀다'를 -1.0 으로 표시한다. 그걸 0 으로 읽으면 전부 미달이 된다."""
    out = render_qa.evaluate_clip_motion(
        [{"cut_no": 1, "measured": True, "motion_median": -1.0},
         {"cut_no": 2, "measured": True, "motion_median": 0.013}])
    assert out["measured_cuts"] == 1 and out["low_cuts"] == []


def test_multi_candidate_cut_uses_its_best_candidate():
    """후보 여럿이면 최고치로 본다 — '가장 잘 움직인 후보조차 미달'이 더 강한 진술이다."""
    rows = [{"cut_no": 5, "measured": True, "motion_median": 0.0005},
            {"cut_no": 5, "measured": True, "motion_median": 0.0200}]
    assert render_qa.evaluate_clip_motion(rows)["low_cuts"] == []


def test_merge_puts_it_in_warnings_never_in_hard_fail():
    """★ 차단하면 운영자가 게이트 전체를 불신한다(RENDER_QA_* 규율)."""
    qa = {"passed": True, "hard_fail": [], "warnings": []}
    render_qa.merge_clip_motion_qa(qa, _rows(TRULY_STATIC))
    assert qa["hard_fail"] == [] and qa["passed"] is True
    assert len(qa["warnings"]) == 1


def test_floor_sits_between_truly_static_and_operator_accepted():
    """문턱이 실측 두 무리 사이에 있어야 의미가 있다 — 밖에 있으면 전부 통과하거나 전부 걸린다.

    ★ 2026-09-14: 두 무리가 '우리 첫 렌더 ↔ 실사 벤치'에서 '진짜 정지 ↔ 운영자가 괜찮다고 본
      우리 화풍'으로 바뀌었다. 후보 순위용 벤치 눈금(CANDIDATE_MOTION_MEDIAN_TARGET)은 그대로다.
    """
    assert max(TRULY_STATIC) < config.CLIP_MOTION_MEDIAN_FLOOR < min(OPERATOR_ACCEPTED)
    assert config.CANDIDATE_MOTION_MEDIAN_TARGET == BENCH_MEDIAN


def test_empty_records_are_silent():
    out = render_qa.evaluate_clip_motion([])
    assert out == {"warnings": [], "low_cuts": [], "median": None, "measured_cuts": 0}
