"""시각 구현 계약 — v3.4 §22 킬 스위치 K8~K11 테스트.

이 파일이 지키는 것은 "화면이 예쁜가"가 아니라 **조용히 나빠지지 않는가**다. v3.3 구현에서
실제로 일어난 네 가지가 전부 조용했다: 폰트가 환경마다 달랐고(K8), 넘치는 글자를 말줄임으로
지웠고(K9), 같은 문장을 두 번 찍었고(K10), 막대 하나가 화면의 37%를 먹었다(K11).
전부 사람이 영상을 눈으로 봐야만 발견됐다. 여기서는 코드가 발견한다.
"""

from __future__ import annotations

import os

import pytest
from PIL import Image, ImageDraw

from engine import board_render, config
from engine import visual_contract as vc


@pytest.fixture()
def draw():
    return ImageDraw.Draw(Image.new("RGB", vc.CANVAS, vc.BG))


# ── K8 폰트 계약 ──
def test_repo_ships_every_required_font():
    """폰트를 저장소가 들고 다녀야 러너·로컬·샌드박스가 같은 화면을 낸다."""
    vc.preflight_fonts()
    for name in vc.FONT_FILES.values():
        assert os.path.getsize(os.path.join(vc.FONT_DIR, name)) > 10_000


def test_missing_font_raises_instead_of_falling_back(monkeypatch):
    """★ 없으면 **죽는다.** 기본 폰트로 조용히 폴백하면 한글이 두부가 되거나 미학이 무너진다."""
    monkeypatch.setattr(vc, "FONT_DIR", "/nonexistent/fonts")
    monkeypatch.setattr(vc, "_cache", {})
    with pytest.raises(vc.FontContractError):
        vc.load_font("head", 40)
    with pytest.raises(vc.FontContractError):
        vc.preflight_fonts()


def test_board_renderer_has_no_font_fallback_chain():
    """후보 목록이 남아 있으면 K8 이 반쪽이다 — 있는 폰트를 조용히 고르게 된다."""
    assert not hasattr(config, "EXPLAINER_FONT_CANDIDATES")
    assert not hasattr(board_render, "_font_path")


def test_every_font_size_key_maps_to_a_real_role():
    for key in config.EXPLAINER_FONT_SIZES:
        assert config.EXPLAINER_FONT_ROLES[key] in vc.FONT_FILES


# ── K9 말줄임 금지 ──
def test_fit_text_shrinks_rather_than_truncating(draw):
    long = "클라우드 성장이 둔화되지 않고 오히려 가속되고 있다는 것이 이번 리포트의 핵심입니다"
    font, lines = vc.fit_text(draw, long, "head", 62, 840, max_lines=2)
    assert "…" not in "".join(lines)
    assert "".join(lines).replace(" ", "") == long.replace(" ", "")   # 한 글자도 잃지 않는다
    assert font.size <= 62


def test_fit_text_raises_when_it_cannot_fit(draw):
    """담기지 않으면 자르지 않고 예외 — '대본 문장을 줄여라'는 신호다."""
    with pytest.raises(ValueError):
        vc.fit_text(draw, "가나다라마바사아자차카타파하" * 12, "body", 48, 840,
                    max_lines=1, min_size=40)


def test_single_word_wider_than_box_is_rejected(draw):
    """★ 이것이 x=930 안전선을 1268px 까지 넘긴 실측 결함이다.

    어절 하나가 한 줄보다 길면 wrap 은 그 어절만으로 한 줄을 만든다 — 줄 수 기준은 통과하는데
    글자는 밖으로 나간다. 줄 수만 보면 못 잡으므로 폭까지 확인해야 한다.
    """
    with pytest.raises(ValueError):
        vc.fit_text(draw, "가" * 60, "head", 62, 400, max_lines=2, min_size=48)


def test_draw_text_in_propagates_instead_of_cropping(draw):
    from engine.board_layout import Box

    with pytest.raises(ValueError):
        board_render._draw_text_in(draw, Box(89, 500, 300, 560), "가나다라마바사아자차카타" * 6,
                                   40, vc.WHITE, max_lines=1, min_size=32)


# ── K10 중복 금지 ──
def test_duplicate_on_screen_text_raises():
    with pytest.raises(ValueError):
        vc.assert_no_duplicate_text("클라우드 부문이 성장을 주도한다",
                                    "클라우드 부문이 성장을 주도한다")
    # 한쪽이 다른 쪽에 포함돼도 중복이다(제목이 본문 앞부분과 같은 흔한 사고).
    with pytest.raises(ValueError):
        vc.assert_no_duplicate_text("클라우드 부문이 성장을 주도한다",
                                    "클라우드 부문이 성장을 주도한다고 리포트는 말한다")
    vc.assert_no_duplicate_text("클라우드 부문이 성장을 주도한다", "Azure 연간 성장률 43%")


def test_text_board_without_overlay_body_does_not_duplicate_the_sentence(tmp_path):
    """★ 실측 사고(리포트 KO 렌더 실패): 오버레이 본문이 없는 텍스트 보드는 TITLE 과 CORE 가
    **둘 다** so_what 으로 폴백해 같은 문장을 두 번 찍었다 — 그 컷이 있는 편은 무조건 죽었다.

    고친 뒤에도 문장이 사라지면 안 된다: 전용 밴드(CORE)에 정확히 한 번 남아야 한다.
    """
    sw = "이례적인 수준의 일일 급등으로 시장의 강한 매수세를 나타냄"
    header = {"version_type": "explainer", "explainer": {
        "number_claims": [{"claim_no": 1, "value": "6600", "unit": "p",
                           "label": "코스피", "why_significant": sw}],
        "report_claim_summary": {"speaker": "메리츠증권", "statement": sw}}}
    cut = {"cut_no": 1, "board": "HOOK_BOARD", "number_claim_refs": [1], "overlay_plan": []}
    res = board_render.render_board(cut, header, None, str(tmp_path), 0, total_sec=3.0)
    # META 밴드(섹션 킥커)는 이 검사의 관심사가 아니다 — 그 밴드는 증권사명을 싣고
    # 여기서 보는 것은 **so_what 문장이 두 밴드에 중복되는가**다(P2-f 로 META 가 생겼다).
    drawn = [(p.band, p.text) for p in res.placements
             if p.kind == "text" and p.text and p.band != "META"]
    assert drawn == [("CORE", sw)]


def test_number_board_title_yields_to_the_sowhat_band(tmp_path):
    """모델이 오버레이 본문과 why_significant 에 같은 문장을 써도 렌더는 살아야 한다.

    제목이 전용 밴드(SOWHAT)와 겹치면 **제목을 비운다** — 문장은 전용 밴드에 한 번 남는다.
    """
    sw = "이례적인 수준의 일일 급등으로 시장의 강한 매수세를 나타냄"
    header = {"version_type": "explainer", "explainer": {
        "number_claims": [{"claim_no": 1, "value": "6600", "unit": "p",
                           "label": "코스피", "why_significant": sw}]}}
    cut = {"cut_no": 1, "board": "NUMBER_BOARD", "number_claim_refs": [1],
           "overlay_plan": [{"type": "caption", "text": sw}]}
    res = board_render.render_board(cut, header, None, str(tmp_path), 0, total_sec=3.0)
    drawn = [(p.band, p.text) for p in res.placements
             if p.kind == "text" and p.text and p.band != "META"]
    assert ("SOWHAT", sw) in drawn
    assert [b for b, _ in drawn].count("TITLE") == 0


def test_layout_dedupe_uses_the_same_rule_as_the_kill_switch(tmp_path):
    """포함관계도 K10 위반이다 — 레이아웃이 완전일치로만 피하면 렌더 끝에서 잡이 죽는다."""
    assert vc.is_duplicate_text("클라우드 부문이 성장을 주도한다",
                                "클라우드 부문이 성장을 주도한다고 리포트는 말한다")
    assert not vc.is_duplicate_text("클라우드 부문이 성장을 주도한다", "Azure 연간 성장률 43%")
    assert not vc.is_duplicate_text("짧다", "짧다")     # 8자 미만은 판정 대상이 아니다

    sw = "코스피 상승은 반도체 업황 회복에 기댄 것이라는 해석"
    header = {"version_type": "explainer", "explainer": {
        "report_claim_summary": {"speaker": "메리츠증권", "statement": sw}}}
    cut = {"cut_no": 1, "board": "CLAIM_BOARD",
           "overlay_plan": [{"type": "caption", "text": "코스피 상승은 반도체 업황 회복"}]}
    res = board_render.render_board(cut, header, None, str(tmp_path), 0, total_sec=3.0)
    drawn = [p.text for p in res.placements
             if p.kind == "text" and p.text and p.band != "META"]
    assert drawn == [sw]


def test_evidence_board_does_not_print_the_claim_twice(tmp_path):
    """실측 사고: 같은 주장이 TITLE 밴드와 카드 본문에 두 번 찍혔다. K10 이 잡았다."""
    header = {"version_type": "explainer",
              "explainer": {"report_claim_summary": {"speaker": "메리츠증권",
                                                     "statement": "같은 문장이 두 번 나오면 안 된다"}}}
    cut = {"cut_no": 1, "board": "EVIDENCE_BOARD",
           "overlay_plan": [{"type": "source_card", "text": "메리츠증권 리서치센터"},
                            {"type": "evidence_card", "text": "같은 문장이 두 번 나오면 안 된다"}]}
    res = board_render.render_board(cut, header, None, str(tmp_path), 0, total_sec=5.0)
    drawn = [p.text for p in res.placements if p.kind == "text" and p.text]
    assert len(drawn) == len(set(drawn))


# ── K11 차트 최소 요건 ──
def test_bar_width_never_exceeds_22_percent(tmp_path):
    """실측: 2계열이면 막대 하나가 화면의 37%를 먹었다 — 차트가 아니라 거대 사각형이었다."""
    header = {"version_type": "explainer", "explainer": {"number_claims": [
        {"claim_no": 1, "value": "43", "unit": "%", "label": "Azure",
         "comparison_basis": "직전", "comparison_value": "39",
         "why_significant": "성장이 가속되고 있습니다"}]}}
    cut = {"cut_no": 1, "board": "CHART_BOARD", "number_claim_refs": [1], "overlay_plan": [
        {"type": "source_card", "text": "메리츠증권 리서치센터"}]}
    res = board_render.render_board(cut, header, None, str(tmp_path), 0, total_sec=5.0)
    bars = [p for p in res.placements if p.kind == "bar"]
    assert bars
    cap = vc.CHART_MIN["bar_max_width_r"] * config.RENDER_WIDTH
    for b in bars:
        assert b.box.w <= cap, f"막대 폭 {b.box.w}px > 상한 {cap:.0f}px"
    assert vc.validate_chart_spec(res.chart_spec) == []
    assert res.chart_spec["unit_label"] is True    # 단위 없는 숫자는 읽을 수 없다


def test_validate_chart_spec_catches_each_missing_element():
    assert "chart missing required element: baseline" in vc.validate_chart_spec({})
    over = {"baseline": 1, "value_labels": 1, "unit_label": 1, "so_what": 1, "source": 1,
            "series": ["a", "b", "c", "d"], "bar_width_r": 0.37, "emphasis_count": 2}
    errs = vc.validate_chart_spec(over)
    assert any("too many series" in e for e in errs)
    assert any("bar too wide" in e for e in errs)
    assert any("amber emphasis" in e for e in errs)


# ── §22-6 프레임 판정 ──
def test_validate_frame_detects_letterbox():
    """K3 회귀 감시 — 검은 바가 다시 붙으면 여기서 걸린다."""
    im = Image.new("RGB", vc.CANVAS, vc.BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, vc.CANVAS[0], 210], fill=(0, 0, 0))
    assert any("letterbox" in f for f in vc.validate_frame(im)["fail"])
    assert not vc.validate_frame(Image.new("RGB", vc.CANVAS, vc.BG))["fail"]


def test_validate_frame_detects_dead_band_content():
    im = Image.new("RGB", vc.CANVAS, vc.BG)
    d = ImageDraw.Draw(im)
    y = vc.y_of("DEAD_BOTTOM", 0.3)
    d.rectangle([0, y, vc.CANVAS[0], y + 200], fill=vc.AMBER)
    assert any("DEAD_BOTTOM" in f for f in vc.validate_frame(im)["fail"])


def test_validate_frame_rejects_wrong_aspect():
    assert any("aspect" in f for f in vc.validate_frame(Image.new("RGB", (1080, 1080), vc.BG))["fail"])


def test_every_demo_board_passes_the_frame_gate(tmp_path):
    """§22-7 ③ — 보드 4종을 모듈 API 로만 그렸을 때 validate_frame fail 이 0인가."""
    from scripts.preview_board import DEMO_CUTS, DEMO_HEADER

    for i, cut in enumerate(DEMO_CUTS):
        res = board_render.render_board(cut, DEMO_HEADER, None, str(tmp_path), i, total_sec=5.0)
        assert res.frame_qa["fail"] == [], (cut["board"], res.frame_qa["fail"])
        assert res.layout_qa["fail"] == [], (cut["board"], res.layout_qa["fail"])


# ── 밴드 그리드가 비율에서 나오는가(F2) ──
def test_bands_are_contiguous_at_any_resolution():
    for h in (1920, 1280, 2560):
        edges = [(vc.y_of(b.name, 0.0, h), vc.y_of(b.name, 1.0, h)) for b in vc.BANDS]
        assert edges[0][0] == 0
        assert edges[-1][1] == h
        for (_, end), (start, _) in zip(edges, edges[1:]):
            assert end == start, f"h={h} 밴드 사이 틈: {end} != {start}"


# ── 밴드 침범 — 눈으로만 잡히던 결함을 게이트로 ──
def test_band_overflow_is_detected(tmp_path):
    """★ 실측 결함: CORE 배경 패널이 위로 16px 튀어나와 TITLE 밴드의 2줄짜리 제목 아랫줄을
    덮었다. 당시 검사는 '금지 밴드 침범'과 '가로 초과'만 봐서 전부 통과했고, 프레임을 눈으로
    봐야만 드러났다. 밴드를 선언한 요소는 그 밴드 안에 있어야 한다.
    """
    from engine import board_layout as bl
    from engine.board_layout import Box, Placement

    core = bl.band_box("CORE")
    over = Placement(kind="panel", band="CORE",
                     box=Box(core.x1, core.y1 - 16, core.x2, core.y2 + 16))
    fails = bl.evaluate_layout([over])["fail"]
    assert any(f.startswith("band_overflow:CORE") for f in fails), fails

    ok = Placement(kind="panel", band="CORE", box=Box(core.x1, core.y1, core.x2, core.y2))
    assert not any(f.startswith("band_overflow") for f in bl.evaluate_layout([ok])["fail"])


def test_demo_boards_have_no_band_overflow(tmp_path):
    from engine import board_render
    from scripts.preview_board import DEMO_CUTS, DEMO_HEADER

    for i, cut in enumerate(DEMO_CUTS):
        res = board_render.render_board(cut, DEMO_HEADER, None, str(tmp_path), i, total_sec=2.0)
        bad = [f for f in res.layout_qa["fail"] if f.startswith("band_overflow")]
        assert not bad, (cut["board"], bad)


# ── §7-4 디자인 토큰 통일 ─────────────────────────────────────
def test_tokens_are_the_single_source_of_colour():
    """색이 여러 곳에 적히면 갈라진다 — 실제로 갈라져 있었다.

    ★ board_render 의 fg·muted 가 visual_contract 의 WHITE·GRAY 와 달랐고, 화면에 나가는
      것은 board_render 쪽이었다(저쪽은 참조 0건인 죽은 상수). 파생 관계를 고정한다.
    """
    from engine import config

    assert config.FIN_TOKEN_BG == vc.token_hex("bg")
    assert config.FIN_TOKEN_ACCENT == vc.token_hex("accent")
    assert config.FIN_TOKEN_POINT == vc.token_hex("point")
    # 운영자 결정: 강조색은 현행 유지.
    assert config.FIN_TOKEN_ACCENT == "#FFB020"


def test_legacy_colour_aliases_track_tokens():
    """옛 이름을 남기되 값이 두 벌이 되지 않게."""
    assert vc.BG is vc.TOKENS["bg"]
    assert vc.AMBER is vc.TOKENS["accent"]
    assert vc.WHITE is vc.TOKENS["fg"]
    assert vc.GRAY is vc.TOKENS["muted"]


def test_board_render_does_not_hardcode_colours():
    """토큰을 모아 놓고 렌더러가 다시 리터럴을 쓰면 통일이 무의미하다."""
    import inspect

    from engine import board_render

    src = inspect.getsource(board_render.render_board)
    block = src.split("tokens =")[1].split("\n\n")[0]
    assert "vc.TOKENS" in block, "render_board 가 TOKENS 를 쓰지 않는다"
    assert "238, 242, 247" not in block and "156, 170, 188" not in block


def test_new_tokens_exist_for_panel_and_danger():
    """danger 가 없어서 '위험'이 '강조'와 같은 색이었다 — 화면에서 구분되지 않았다."""
    assert vc.TOKENS["danger"] != vc.TOKENS["accent"]
    assert "panel" in vc.TOKENS


# ── 그려진 글자의 실제 범위 (2026-08-19) ──────────────────────

def test_ink_span_is_lower_than_the_naive_height():
    """`y + text_size()[1]` 을 글자 아래로 쓰면 안 된다 — 큰 폰트일수록 위로 크게 어긋난다.

    실측 사고: NUMBER_BOARD·CHART_BOARD 의 앰버 밑줄과 라벨이 대형 숫자 **위로 올라타** 서로
    겹쳐 읽을 수 없었다. 원인이 이 오차 하나다(Anton 220pt 에서 67px).
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1080, 1920))
    draw = ImageDraw.Draw(img)
    font = vc.load_font("num_en", 220)
    _, h = vc.text_size(draw, "18.5%", font)
    top, bottom = vc.text_ink_span(draw, "18.5%", font)

    assert bottom > h, "잉크 바닥이 잉크 높이보다 아래여야 한다(윗여백만큼)"
    assert top > 0, "큰 폰트는 줄 상자 위쪽과 글자 위쪽 사이에 여백이 있다"
    assert bottom - top == h, "잉크 높이는 두 값의 차이와 같아야 한다"
