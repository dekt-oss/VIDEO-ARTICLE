"""설명판 레이아웃·§20-7 판정 테스트 (최종명세 v3.3 §20-3).

순수 로직만 — PIL·ffmpeg 없이 돈다. 검사 대상은 "화면이 잘리거나 UI 에 가려지는 것":
DEAD 밴드 침범 · x>930 초과 · 출처 바 위치 · CORE 밀도 · 단계 길이 총합.
"""

from __future__ import annotations

from engine import board_layout as bl
from engine import config
from engine.board_layout import Box, Placement


def _p(x1: int, y1: int, x2: int, y2: int, **kw) -> Placement:
    return Placement(kind=kw.pop("kind", "text"), box=Box(x1, y1, x2, y2), **kw)


def _box(b: Box) -> tuple[int, int, int, int]:
    return b.x1, b.y1, b.x2, b.y2


# ── 밴드 그리드 ──
def test_bands_cover_the_frame_without_gaps_or_overlap():
    """밴드가 프레임을 빈틈·겹침 없이 덮는가. 한 칸이라도 어긋나면 좌표 계산이 전부 틀어진다."""
    ordered = sorted(config.EXPLAINER_BANDS.values())
    assert ordered[0][0] == 0
    assert ordered[-1][1] == config.RENDER_HEIGHT
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:]):
        assert prev_end == next_start, f"밴드 사이 틈/겹침: {prev_end} != {next_start}"


def test_band_box_respects_safe_x():
    box = bl.band_box("CORE")
    assert (box.x1, box.x2) == config.EXPLAINER_SAFE_X
    assert (box.y1, box.y2) == config.EXPLAINER_BANDS["CORE"]


def test_core_anchor_is_inside_core_band():
    top, bottom = config.EXPLAINER_BANDS["CORE"]
    assert top < config.EXPLAINER_CORE_ANCHOR_Y < bottom


# ── §20-7 판정 ──
def test_dead_band_violation_fails():
    """유튜브 UI 구역(y>1500)에 정보를 놓으면 실패. 이게 §20-3 의 핵심 금지다."""
    out = bl.evaluate_layout([_p(90, 1600, 900, 1700, text="출처")])
    assert any(f.startswith("band_violation:DEAD_BOTTOM") for f in out["fail"])
    out = bl.evaluate_layout([_p(90, 100, 900, 200, text="제목")])
    assert any(f.startswith("band_violation:DEAD_TOP") for f in out["fail"])


def test_safe_x_overflow_fails():
    """x>930 은 쇼츠 우측 버튼 스택에 가린다."""
    out = bl.evaluate_layout([_p(90, 600, 1000, 700, text="넘침")])
    assert any(f.startswith("safe_x_overflow") for f in out["fail"])
    out = bl.evaluate_layout([_p(40, 600, 900, 700, text="왼쪽넘침")])
    assert any(f.startswith("safe_x_underflow") for f in out["fail"])


def test_source_bar_must_stay_in_source_band():
    src = bl.band_box("SOURCE")
    inside = _p(src.x1, src.y1 + 8, src.x2, src.y2 - 8, band="SOURCE", kind="card")
    # core_fill_ratio=1.0 — 여기 관심사는 출처 바 위치지 CORE 충전율이 아니다. 안 주면
    # CORE 가 비어 core_underfilled 로 fail 해 이 규칙을 검사하지 못한다
    # (test_board_components.py 가 쓰는 것과 같은 격리 방식).
    assert bl.evaluate_layout([inside], core_fill_ratio=1.0)["fail"] == []
    cap = bl.band_box("CAPTION")
    outside = _p(cap.x1, cap.y1, cap.x2, cap.y2, band="SOURCE", kind="card")
    assert any(f.startswith("source_bar_outside_band") for f in bl.evaluate_layout([outside])["fail"])


def test_clean_layout_has_no_failures():
    # ★ 좌표를 테스트에 적지 않는다. 밴드에서 해소해야 해상도·비율이 바뀌어도 같이 따라온다
    #   (실측 결함 F2 — 절대좌표를 두 곳에 적어 어긋난 것이 그대로 재현됐다).
    ok = [
        _p(*_box(bl.band_box("TITLE")), band="TITLE"),
        _p(*_box(bl.band_box("CORE")), band="CORE"),
        _p(*_box(bl.band_box("SOURCE")), band="SOURCE", kind="card"),
    ]
    assert bl.evaluate_layout(ok)["fail"] == []


# ── CORE 밀도 ──
def test_core_coverage_counts_area_not_strokes():
    """★ 픽셀이 아니라 요소 면적으로 잰다 — 글자는 획이 얇아 잘 채운 화면도 4~5% 밖에 안 된다."""
    top, bottom = config.EXPLAINER_BANDS["CORE"]
    x1, x2 = config.EXPLAINER_SAFE_X
    full = _p(x1, top, x2, bottom, band="CORE")
    assert bl.core_coverage([full]) > 0.95
    assert bl.core_coverage([]) == 0.0


def test_overlapping_boxes_are_not_double_counted():
    top, _ = config.EXPLAINER_BANDS["CORE"]
    x1, _ = config.EXPLAINER_SAFE_X
    a = _p(x1, top, x1 + 400, top + 400, band="CORE")
    b = _p(x1, top, x1 + 400, top + 400, band="CORE")
    assert abs(bl.core_coverage([a]) - bl.core_coverage([a, b])) < 1e-9


def test_empty_core_fails():
    """빈 CORE 는 **차단**이다 (v3 §9 승격).

    ★ 예전엔 warn 이었고 이 자리에 "허전함은 경고지 차단이 아니다"라고 적혀 있었다.
      그 정책에서 충전율 0.235 짜리 화면이 `fail: []` 로 통과해 그대로 나갔다. 경고는
      아무도 안 읽었고, 읽었을 땐 이미 발행된 뒤였다.
      기준값 근거: docs/measure-core-fill-2026-08-03.md.
    """
    out = bl.evaluate_layout([_p(90, 340, 900, 470, band="TITLE")])
    assert any(f.startswith("core_underfilled") for f in out["fail"])
    assert not any(w.startswith("core_underfilled") for w in out["warn"]), \
        "승격했으면 warn 에 남아 있으면 안 된다 — 두 번 세어진다"


def test_core_fill_threshold_is_the_measured_one():
    """기준값이 조용히 움직이면 이 게이트의 의미가 바뀐다 — 실측 문서와 함께만 바꿀 것."""
    assert config.EXPLAINER_CORE_MIN_FILL == 0.25


def test_well_filled_core_passes():
    """게이트가 '무조건 fail' 이 아니라는 반대 증거. 채운 화면은 통과해야 한다."""
    out = bl.evaluate_layout([_p(*_box(bl.band_box("CORE")), band="CORE")])
    assert not any(f.startswith("core_underfilled") for f in out["fail"])


# ── 단계 길이 ──
def test_stage_durations_sum_exactly_to_total():
    """★ 총합이 나레이션 실측과 어긋나면 clip_fit 이 줌·페이드를 붙여 밴드 좌표가 깨진다."""
    for total in (3.0, 5.5, 8.0):
        for n in (1, 2, 3, 4):
            d = bl.stage_durations(total, n)
            assert len(d) == n
            assert abs(sum(d) - total) < 0.01, (total, n, d)
            assert all(x > 0 for x in d)


def test_stage_count_is_capped():
    assert len(bl.stage_durations(10.0, 99)) == config.EXPLAINER_STAGE_MAX


# ── 줄바꿈 — v3.4 §22 K9 ──
def test_layout_module_no_longer_truncates():
    """말줄임 함수가 **존재하지 않아야** 한다.

    전에는 넘치는 글자를 '…' 로 잘라 화면에서 조용히 지웠다. 시청자는 무엇이 사라졌는지 모른다.
    이제 줄바꿈·축소는 visual_contract.fit_text 만 하고, 못 담으면 예외로 대본을 고치게 한다.
    """
    assert not hasattr(bl, "wrap_text")
    assert not hasattr(bl, "fit_font_size")


def test_bands_come_from_the_visual_contract():
    """밴드 픽셀의 원본이 visual_contract 인가(§22-1 — 모듈이 규범)."""
    from engine import visual_contract as vc

    for b in vc.BANDS:
        assert config.EXPLAINER_BANDS[b.name] == (
            vc.y_of(b.name, 0.0, config.RENDER_HEIGHT),
            vc.y_of(b.name, 1.0, config.RENDER_HEIGHT))
    assert config.EXPLAINER_SAFE_X == vc.x_bounds(config.RENDER_WIDTH)


# ── 차트 상단 여유 — 값 라벨과 증감 배지가 겹치던 결함 ──
def test_chart_top_reserve_fits_both_value_label_and_diff_badge():
    """★ 실측 결함: 막대가 가장 높은 계열에서 값 라벨("43%") 위에 증감 배지("+4%")가
    **겹쳐 찍혔다.** 둘 다 draw.text 로 직접 그려 Placement 를 안 남기므로 §20-7 판정기가
    못 잡았고, 프레임을 눈으로 봐야만 드러났다.

    ★★ 이 테스트의 첫 판은 **너무 약해서 결함을 못 잡았다.** 배지가 상자 맨 위가 아니라
       20px 내려온 자리에 앉는다는 것을 빼먹어, 실제 여유가 **1px** 인 상태를 통과시켰다.
       그래서 애니메이션 전 구간을 실제 공식으로 훑고 최소 간격을 본다 — 상수 비교가 아니라
       "정말 안 겹치나"를 묻는다.
    """
    from engine import board_layout as bl2, board_motion as bm, board_render as br, config

    box = bl2.band_box("CORE")
    base_y = box.y2 - 84
    top_room = base_y - box.y1 - br.CHART_TOP_RESERVE
    badge_h = int(config.EXPLAINER_FONT_SIZES["label"] * 1.32)

    worst = min(
        # 값 라벨 상단 — 막대 머리를 따라 올라온다
        (base_y - int(top_room * bm.ease_out_cubic(i / 100)) - br.CHART_VALUE_LABEL_LIFT)
        # 배지 하단 — 위에서 내려앉는다(ease_out_back)
        - (box.y1 + int(br.CHART_BADGE_TOP_OFFSET * (2 - bm.ease_out_back(i / 100))) + badge_h)
        for i in range(101))

    assert worst >= 16, (
        f"값 라벨과 증감 배지의 최소 간격 {worst}px — 폰트가 조금만 바뀌어도 겹친다. "
        f"CHART_TOP_RESERVE(={br.CHART_TOP_RESERVE})를 넓힐 것")


def test_diff_badge_waits_for_the_bars_to_finish():
    """★ 실측 결함: 막대가 카운트업하는 동안 배지가 **최종** 델타를 미리 보여줬다.

    재생 60% 지점 프레임에서 화면이 "39%" 와 "38%" 를 나란히 놓고 "+4%" 라고 말했다 —
    눈에 보이는 두 숫자의 차이는 -1 인데 배지는 +4 다. 그 순간 시청자는 화면을 믿을 수 없다.
    §9 의 읽기 순서("첫 데이터 → 비교 데이터 → 차이 강조")도 배지가 나중이다.

    이 게이트를 지우면 같은 결함이 조용히 돌아온다 — 판정기는 배지를 draw.text 로만
    그려 Placement 를 안 남기므로 원리적으로 못 잡는다.
    """
    import inspect

    from engine import board_render as br

    src = inspect.getsource(br._draw_bars)
    assert "bars_done" in src, "배지가 막대 완료를 기다리지 않는다"
    assert "and bars_done" in src, "bars_done 이 배지 조건에 걸려 있지 않다"
