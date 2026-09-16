"""신규 시각 컴포넌트 4종 드로잉 (작업지시서 영상엔진품질 v3 §7-1 P2-d).

PIL 로 실제로 그려 보고 결과 Placement 를 본다 — "구현했다"를 주장이 아니라 검사로 만든다.
폰트가 없는 환경에서는 건너뛴다(visual_contract 가 FontContractError 를 던진다).
"""

from __future__ import annotations

import pytest

from engine import board_layout as bl
from engine import board_render as br
from engine import component_registry as cr
from engine import visual_contract as vc
from engine.board_layout import Box

SERIES = [("1Q26", 12.0), ("2Q26", 18.5), ("3Q26F", 27.4)]


def _fonts_ok() -> bool:
    try:
        vc.preflight_fonts()
    except Exception:                      # noqa: BLE001
        return False
    return True


pytestmark = pytest.mark.skipif(not _fonts_ok(), reason="렌더 폰트 없음")


@pytest.fixture()
def canvas():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1080, 1920), vc.TOKENS["bg"])
    return ImageDraw.Draw(img)


# ── 전부 그려지는가 ───────────────────────────────────────────
def test_all_four_new_components_are_no_longer_draft():
    """구현했으면 레지스트리에서 내려야 라우터가 실제로 고른다."""
    for name in ("step_climb", "gauge_fill", "strike_reveal", "section_kicker"):
        assert not cr.get_component(name).draft, f"{name} 이 아직 draft 다"
    # ★ dual_marker 는 여기 없다 — 그리는 코드가 없으므로 draft 가 맞다. 예전에 이 자리에
    #   `implemented == registered` 를 적어 뒀는데 그건 사실이 아니었다(자세한 사유는
    #   tests/test_component_registry.py 의 test_implemented_is_a_subset_of_registered).
    assert cr.get_component("dual_marker").draft


@pytest.mark.parametrize("name", ["step_climb", "gauge_fill", "strike_reveal", "section_kicker"])
def test_component_has_a_draw_branch(name, canvas):
    """레지스트리에 등록만 하고 draw_component 분기를 안 만들면 폴백으로 조용히 샌다."""
    import inspect

    src = inspect.getsource(br.draw_component)
    assert f'name == "{name}"' in src


# ── 움직이는가 (§7-2 애니메이션 계약) ──────────────────────────
def test_step_climb_grows_with_progress(canvas):
    core = bl.band_box("CORE")
    early = br._draw_step_climb(canvas, core, SERIES, vc.TOKENS, p=0.1)
    late = br._draw_step_climb(canvas, core, SERIES, vc.TOKENS, p=1.0)
    assert len(late) > len(early), "진행해도 그려지는 것이 늘지 않는다 = 정지 화면"


def test_strike_reveal_does_not_show_both_texts_at_once(canvas):
    """상반된 두 주장이 같이 떠 있으면 시청자가 어느 쪽이 맞는지 모른다."""
    core = bl.band_box("CORE")
    early = br._draw_strike_reveal(canvas, core, "틀린 통념입니다", "옳은 설명입니다",
                                   vc.TOKENS, p=0.2)
    texts = [e.text for e in early if e.kind == "text"]
    assert "옳은 설명입니다" not in texts, "취소선이 다 그어지기 전에 정답이 나왔다"

    late = br._draw_strike_reveal(canvas, core, "틀린 통념입니다", "옳은 설명입니다",
                                  vc.TOKENS, p=1.0)
    assert any(e.kind == "rule" for e in late), "취소선이 없다"
    assert len(late) > len(early)


def test_section_kicker_lands_in_the_meta_band(canvas):
    """META 밴드는 지금까지 정의만 있고 한 번도 그려지지 않았다 — 이 컴포넌트가 첫 입주자다."""
    out = br._draw_section_kicker(canvas, bl.band_box("META"), "iM증권", vc.TOKENS, p=1.0)
    assert out and all(e.band == "META" for e in out)


# ── gauge_fill 의 안전장치 ────────────────────────────────────
def test_gauge_never_exceeds_the_goal(canvas):
    """목표를 넘게 그리면 '초과 달성'이라는 없는 주장을 화면이 하게 된다(V3 clamp)."""
    core = bl.band_box("CORE")
    out = br._draw_gauge_fill(canvas, core, 999.0, 10.0, vc.TOKENS, p=1.0)
    gauge = next(e for e in out if e.kind == "gauge")
    marker = next(e for e in out if e.kind == "marker")
    # 채움은 트랙 안에서 끝나야 하고, 목표 마커는 트랙 오른쪽 끝에 있다.
    assert marker.box.x1 >= gauge.box.x2 - 6


def test_gauge_shows_a_fraction_not_a_percentage(canvas):
    """퍼센트로 바꾸면 원문에 없는 수치를 화면이 만들어낸다."""
    out = br._draw_gauge_fill(canvas, bl.band_box("CORE"), 7.6, 12.0, vc.TOKENS,
                              p=1.0, unit="조원")
    texts = " ".join(e.text for e in out if e.text)
    assert "/" in texts and "조원" in texts
    assert "%" not in texts


# ── 레이아웃 계약 (§20-7) ─────────────────────────────────────
@pytest.mark.parametrize("name,call", [
    ("step_climb", lambda d: br._draw_step_climb(d, bl.band_box("CORE"), SERIES, vc.TOKENS, p=1.0)),
    ("gauge_fill", lambda d: br._draw_gauge_fill(d, bl.band_box("CORE"), 7.6, 12.0, vc.TOKENS, p=1.0)),
    ("section_kicker", lambda d: br._draw_section_kicker(d, bl.band_box("META"), "iM증권", vc.TOKENS, p=1.0)),
])
def test_new_components_pass_layout_qa(name, call, canvas):
    """자기 밴드를 넘거나 safe zone 을 벗어나면 화면이 잘리거나 UI 에 가려진다."""
    out = call(canvas)
    qa = bl.evaluate_layout(out, core_fill_ratio=1.0)   # 충전율은 여기 관심사가 아니다
    assert qa["fail"] == [], f"{name}: {qa['fail']}"


# ── P2-f META 밴드 배선 ───────────────────────────────────────
def test_meta_band_is_assigned_once_not_per_frame():
    """프레임마다 중복 판정을 하면 킥커가 컷 도중 나타났다 사라진다.

    ★ 실제로 그렇게 짰다가 EVIDENCE_BOARD 에서 깜빡이는 것을 잡았다 — CORE 의 증권사명은
      prog("speaker") 가 올라간 뒤에야 그려지므로 앞 프레임엔 중복이 아니고 뒷 프레임엔
      중복이 된다. render_board 가 밴드 배정을 한곳에서 끝내라고 이미 경고한 함정이다.
    """
    import inspect

    from engine import board_render

    rb = inspect.getsource(board_render.render_board)
    assert "meta_kicker" in rb, "META 배정이 render_board 에서 정해지지 않는다"

    df = inspect.getsource(board_render._draw_frame)
    assert 'ctx.get("meta_kicker")' in df
    assert "is_duplicate_text" not in df, "프레임 안에서 중복 판정을 하면 깜빡인다"


def test_evidence_board_does_not_double_print_the_broker():
    """CORE 카드가 이미 증권사명을 그린다 — META 에 또 그리면 K10 이 잡 전체를 죽인다."""
    from engine import component_registry as cr2

    assert cr2.resolve_for_board("EVIDENCE_BOARD", allow_draft=False).component == "source_badge"


def test_source_band_is_left_to_the_ass_footer():
    """출처를 보드에도 그리면 자막과 이중 인쇄된다 — 그 결정을 코드에 남겨 둔다."""
    import inspect

    from engine import board_render

    df = inspect.getsource(board_render._draw_frame)
    assert "SOURCE 밴드는 여기서 그리지 않는다" in df


# ── 컷이 선언하지 않은 숫자를 화면에 그리지 않는다 (§7-3 라우팅의 선행 조건) ──
def test_chart_items_only_uses_numbers_the_cut_declared():
    """★ 이 PR 에서 가장 중요한 테스트다 — 화면이 거짓말을 하지 않는다는 보장이다.

    예전에는 컷에 `number_claim_refs` 가 없으면 리포트의 **모든** number_claims 를 끌어다
    썼다. 그 시절엔 그 보드들이 전부 text_core 로 가서 이 값이 안 쓰였기 때문에 무해했지만,
    §7-3 의미 라우팅을 켜는 순간 유해해진다 — gauge_fill 은 items[0] 을 현재값, items[-1] 을
    목표로 그리므로, **리포트에 그런 말이 없는데도** 무관한 두 수치가 "현재 → 목표"로
    화면에 박힌다.

    빈 목록이면 컴포넌트 가드가 None 을 내고 text_core 로 폴백한다.
    정직한 빈 화면이 지어낸 차트보다 낫다.
    """
    header = {"explainer": {"number_claims": [
        {"claim_no": 1, "value": "900.1", "unit": "억 달러", "label": "매출"},
        {"claim_no": 2, "value": "43", "unit": "억 달러", "label": "영업이익"},
    ]}}

    # 선언이 없으면 아무것도 안 그린다
    items, _ = br._chart_items(header, {"cut_no": 1, "board": "MECHANISM_BOARD"})
    assert items == [], "컷이 선언하지 않은 숫자를 끌어다 쓰면 안 된다"

    items, _ = br._chart_items(header, {"cut_no": 1, "number_claim_refs": []})
    assert items == [], "빈 목록도 '선언 없음'이다"

    # 선언한 것만 나온다
    items, _ = br._chart_items(header, {"cut_no": 1, "number_claim_refs": [2]})
    assert [lbl for lbl, _ in items] == ["영업이익"]
    assert [v for _, v in items] == [43.0]


def test_dataless_cut_cannot_reach_a_chart_component():
    """위 보장이 실제 라우팅 경로에서도 유지되는가 — 가드가 None 을 내야 폴백이 걸린다."""
    header = {"explainer": {"number_claims": [
        {"claim_no": 1, "value": "900.1", "unit": "억 달러", "label": "매출"},
        {"claim_no": 2, "value": "43", "unit": "억 달러", "label": "영업이익"},
    ]}}
    items, _ = br._chart_items(header, {"cut_no": 1, "board": "MECHANISM_BOARD"})
    # gauge_fill·step_climb 의 가드는 "항목 2개 미만이면 None" 이다.
    assert len(items) < 2


def test_step_climb_fills_enough_to_pass_the_core_gate(canvas):
    """★ 실측: 선만 그렸을 때 충전율 0.212 로 0.25 게이트에 걸려 **렌더가 아예 실패**했다.

    추이선 아래를 면으로 채워 해소했다. 면적 차트는 추이 표현의 표준이고 없는 정보를
    더하지 않는다. 면을 다시 걷어내면 이 테스트가 막는다.
    """
    from engine import config

    core = bl.band_box("CORE")
    out = br._draw_step_climb(canvas, core, SERIES, vc.TOKENS, p=1.0)
    assert any(e.kind == "area" for e in out), "면이 없으면 CORE 가 비어 보인다"
    assert bl.core_coverage(out) >= config.EXPLAINER_CORE_MIN_FILL, (
        f"충전율 {bl.core_coverage(out):.3f} < 게이트 {config.EXPLAINER_CORE_MIN_FILL}")


def test_step_climb_area_is_counted_per_segment_not_as_one_big_box(canvas):
    """면을 하나의 큰 상자로 세면 계단 위 빈 공간까지 '찼다'고 세어 충전율이 부풀려진다."""
    out = br._draw_step_climb(canvas, bl.band_box("CORE"), SERIES, vc.TOKENS, p=1.0)
    areas = [e for e in out if e.kind == "area"]
    assert len(areas) == len(SERIES) - 1, "구간마다 하나씩이어야 한다"
