"""Q3 애니메이션 계약 검사 (engine/animation_qa · 지시서 v3 §9).

★ 왜 생겼나: `component_registry` 가 컴포넌트마다 `min_change_ratio` 를 선언해 놨는데
  **그 값을 읽는 코드가 없었다**(2026-09-03). 계약만 있고 검사가 없으면 카운트업이
  정지된 숫자로 나가도 아무도 모른다. §14-1 이 Phase 4 검증 렌더의 조건으로 걸어 놨다.

★★ 이 파일이 지키는 가장 중요한 것은 **자를 잘못 대면 즉시 깨지는 것**이다.
  만드는 동안 자를 두 번 틀렸고 둘 다 "100%" 로 나타났다:
    ① CORE **밴드** 전체로 재니 정적 배경 패널이 78% 를 차지해 → 보드 11종 전부 FAIL
    ② 배경 기준을 **페이지 배경 토큰**으로 주니 빈 프레임이 통째로 잉크가 돼 → 비율 0.43
  둘 다 "전부 실패/전부 통과"였다. 그래서 아래에 **양쪽 극단을 다 박는다.**
"""

from __future__ import annotations

import tempfile

import pytest

from engine import animation_qa as aqa
from engine import component_registry as cr
from engine import config
from engine import render_manifest as rm

PANEL = 40          # 컴포넌트 뒤 패널색(페이지 배경 18 이 아니다 — 이것이 실측의 핵심)
INK = 220
N = 400


def _frame(ink_idx, val: int = INK, base: int = PANEL) -> list[int]:
    f = [base] * N
    for i in ink_idx:
        f[i] = val
    return f


# ── 판정의 두 극단 ────────────────────────────────────────────
def test_a_frozen_component_fails():
    """처음부터 끝까지 그대로면 계약 미달 — 이 검사의 존재 이유다."""
    st = _frame(range(0, 100))
    r = aqa.evaluate("number_count", st, st, st)
    assert r is not None and not r.passed
    assert r.ratio == 0.0
    assert r.reason.startswith("count_up:")


def test_a_component_that_appears_passes():
    r = aqa.evaluate("number_count", _frame([]), _frame(range(0, 50)), _frame(range(0, 100)))
    assert r is not None and r.passed and r.ratio == 1.0


def test_static_contract_components_are_not_judged():
    """min_change_ratio 가 0 이면 검사 대상이 아니다(정적 카드류)."""
    st = _frame(range(0, 100))
    spec = cr.CORE_COMPONENTS["number_count"]
    assert spec.animation.min_change_ratio > 0        # 전제
    assert aqa.evaluate("존재하지않는컴포넌트", st, st, st) is None


# ── ★ 자를 잘못 대면 깨지는 자리 (실측 회귀) ──────────────────
def test_the_baseline_comes_from_the_frame_not_from_a_token():
    """★★ 실측 회귀(2026-09-03).

    보드는 컴포넌트 뒤에 **더 밝은 패널**을 깐다. 페이지 배경 토큰(18)을 기준으로 쓰면
    패널색(40)인 빈 프레임이 통째로 잉크로 잡혀, 분모가 크롭 전체가 되고 숫자가 0 에서
    통째로 나타나도 비율이 0.43 으로 나왔다. 기준값은 **재는 대상에서** 얻어야 한다.
    """
    empty = _frame([])                       # 전 픽셀 PANEL — "아직 아무것도 없음"
    full = _frame(range(0, 100))
    assert aqa.baseline(empty) == PANEL
    assert aqa.change_ratio(empty, full) == 1.0
    # 토큰 배경(18)을 억지로 주면 옛 오답이 재현된다 — 그래서 기본값이 None 이다.
    assert aqa.change_ratio(empty, full, bg=18) < 0.5


def test_ratio_is_normalized_by_ink_not_by_area():
    """★ 넓이로 나누면 계약값이 무의미해진다.

    잉크가 크롭의 5% 뿐이어도, 그 잉크가 전부 달라졌으면 비율은 1.0 이어야 한다.
    넓이로 나눴다면 0.05 가 나와 min_change_ratio 0.60 을 영원히 못 넘는다.
    """
    a = _frame(range(0, 20))
    b = _frame(range(100, 120))
    assert aqa.change_ratio(a, b) > 0.9


def test_mismatched_lengths_are_not_judged():
    """크롭이 어긋난 것은 애니메이션 문제가 아니다 — 실패로 만들지 않는다."""
    assert aqa.change_ratio(_frame([]), [PANEL] * 10) < 0
    r = aqa.evaluate("number_count", _frame([]), _frame([]), [PANEL] * 10)
    assert r is not None and r.passed and r.reason == "not_measured"


# ── 계약이 못 잡는 것을 문서와 코드가 같이 인정하는가 ──────────
def test_appear_then_freeze_passes_but_is_recorded_as_no_progress():
    """★ 정직하게: 첫 프레임에 통째로 나타나 멈춘 것은 계약을 **통과한다**.

    계약이 선언한 것이 "첫↔끝"이기 때문이다. 그 한계를 mid_to_last 가 기록으로 남긴다
    (문턱은 두지 않는다 — 일찍 끝나는 연출이 정상적으로 0 을 낸다).
    """
    full = _frame(range(0, 100))
    r = aqa.evaluate("number_count", _frame([]), full, full)
    assert r is not None and r.passed          # 통과한다 — 과장하지 않는다
    assert r.mid_to_last == 0.0                # 그러나 진행이 없었다는 것이 남는다

    moving = aqa.evaluate("number_count", _frame([]), _frame(range(0, 50)), full)
    assert moving is not None and moving.mid_to_last > 0


def test_the_docstring_admits_the_limit():
    """★ 이 저장소의 규율: 지표가 못 하는 것을 코드 옆에 적어 둔다."""
    import inspect
    src = inspect.getsource(aqa)
    assert "못 잡는다" in src and "하한선이지 충실도 점수가 아니다" in src


# ── 배선: 사유 코드가 실제로 상태를 바꾸는가 ──────────────────
def test_reason_prefix_is_shared_by_both_sides():
    """접두사가 어긋나면 검사는 도는데 상태가 안 바뀐다(만들어 놓고 한쪽만 연결)."""
    st = _frame(range(0, 100))
    sig = aqa.board_signals(aqa.evaluate("number_count", st, st, st))
    assert sig and sig[0].startswith(config.ANIM_QA_REASON_PREFIX)


def test_animation_failure_makes_the_job_degraded_not_failed():
    """★ 잡을 죽이지 않는다 — 화면은 그려져 있고 움직임만 없다.

    core_underfilled 가 배운 처방과 같다(config.LAYOUT_FAIL_REVIEWABLE 주석):
    이미 이미지·TTS·조립 비용을 다 쓴 뒤 산출물을 버리면 로그 한 줄만 남는다.
    """
    st = _frame(range(0, 100))
    fails = aqa.board_signals(aqa.evaluate("number_count", st, st, st))
    status, reasons = rm.terminal_status(
        [{"cut_no": 3, "manifest": {}, "layout_fail": [], "animation_fail": fails}])
    assert status == "degraded", (status, reasons)
    assert any("animation_contract" in r and "#3" in r for r in reasons), reasons


def test_a_clean_cut_still_reaches_done():
    status, reasons = rm.terminal_status(
        [{"cut_no": 1, "manifest": {}, "layout_fail": [], "animation_fail": []}])
    assert status == "done" and reasons == []


# ── 통합: 진짜 보드를 그려서 끝까지 도는가 ────────────────────
def test_a_real_board_render_produces_an_animation_verdict():
    """★ 순수 함수만 테스트하면 "배선했다고 믿는" 상태가 된다 — 실제로 그려 본다."""
    pytest.importorskip("PIL")
    from engine import board_render
    try:
        from test_board_render_golden import HEADER, _cut
    except ImportError:                         # 골든 모듈 경로가 다르면 건너뛴다
        pytest.skip("골든 픽스처 없음")
    try:
        res = board_render.render_board(_cut("NUMBER_BOARD"), HEADER, None,
                                        tempfile.mkdtemp(), idx=0, total_sec=2.0,
                                        lang="ko", bg_image=None)
    except Exception as exc:                    # 폰트 없는 환경(visual_contract 가 던진다)
        pytest.skip(f"보드 렌더 불가: {type(exc).__name__}")
    assert res.animation, "Q3 판정이 결과에 실리지 않았다(배선 끊김)"
    assert res.animation["component"] == "number_count"
    assert res.animation["passed"] is True
    assert res.animation_fail == []
