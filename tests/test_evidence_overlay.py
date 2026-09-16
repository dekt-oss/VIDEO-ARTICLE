"""근거 오버레이 — 화면으로 증명하는 레이어 (수정명세 §11 / M-E3).

개정 전 이 저장소에는 오버레이 렌더 경로가 **없었다** — `overlay_plan` 이 미구현인 정도가 아니라
기존 `text_overlay:<문구>` 이펙트조차 `assemble.effect_filter` 가 켄번스/팬만 해석해 버렸다.
여기선 (1) 규칙이 코드로 강제되는가, (2) 기존 출력이 바이트 단위로 불변인가를 본다.
"""

from engine import config, subtitles
from engine.evidence_overlay import (
    build_overlay_cues,
    normalize_overlay_plan,
)


def _ov(**kw):
    base = {"type": "evidence_card", "text": "표본 1,240개 기업", "start_sec": 0.5,
            "duration_sec": 3.0}
    base.update(kw)
    return base


# ── 정규화 규칙 (§11-4) ──
def test_min_duration_enforced():
    # 2초 미만으로 지나가는 카드는 읽히지 않는다.
    out = normalize_overlay_plan([_ov(duration_sec=0.5)])
    assert out[0]["duration_sec"] == config.OVERLAY_MIN_SEC == 2.0


def test_max_two_overlays_per_cut():
    out = normalize_overlay_plan([_ov(text="a"), _ov(text="b"), _ov(text="c")])
    assert len(out) == config.OVERLAY_MAX_PER_CUT == 2


def test_only_one_number_punch_per_cut():
    """한 화면에 핵심 숫자는 1개. 두 번째부터는 보조 카드로 강등한다."""
    out = normalize_overlay_plan([
        _ov(type="number_punch", text="3.2%p"),
        _ov(type="number_punch", text="1,240개"),
    ])
    assert out[0]["type"] == "number_punch"
    assert out[1]["type"] == "evidence_card"


def test_unknown_type_falls_back():
    assert normalize_overlay_plan([_ov(type="쓰레기")])[0]["type"] == "evidence_card"


def test_payload_rendered_when_text_absent():
    out = normalize_overlay_plan([{
        "type": "evidence_card",
        "payload": {"표본": "1,240개 기업", "기간": "2016-2022", "지역": ""},
    }])
    assert out[0]["text"] == "표본: 1,240개 기업 · 기간: 2016-2022"


def test_empty_and_garbage_dropped():
    assert normalize_overlay_plan([{"type": "evidence_card"}, None, "x", 3]) == []
    assert normalize_overlay_plan(None) == []


# ── 타임라인 배치 ──
def test_cues_offset_by_cut_start():
    cuts = [{"overlay_plan": [_ov(start_sec=0.5, duration_sec=2.0)]},
            {"overlay_plan": [_ov(start_sec=1.0, duration_sec=2.0)]}]
    cues = build_overlay_cues(cuts, starts=[0.0, 6.0], durations=[6.0, 6.0])
    assert [round(c[0], 2) for c in cues] == [0.5, 7.0]


def test_overlay_clipped_at_cut_end():
    """오버레이가 다음 컷으로 새면 근거가 엉뚱한 장면에 붙는다."""
    cuts = [{"overlay_plan": [_ov(start_sec=3.0, duration_sec=10.0)]}]
    cues = build_overlay_cues(cuts, starts=[0.0], durations=[5.0])
    assert cues[0][1] == 5.0


def test_legacy_text_overlay_effect_is_resurrected():
    """지금까지 렌더에서 버려지던 text_overlay: 토큰을 실제 화면으로 올린다."""
    cuts = [{"effects": ["ken_burns_zoom_in", "text_overlay:2016-2022년 1,240개 기업"]}]
    cues = build_overlay_cues(cuts, starts=[0.0], durations=[6.0])
    assert len(cues) == 1
    assert cues[0][2] == "2016-2022년 1,240개 기업"


def test_overlay_plan_wins_over_legacy_effect():
    cuts = [{"overlay_plan": [_ov(text="구조화 카드")],
             "effects": ["text_overlay:레거시"]}]
    cues = build_overlay_cues(cuts, starts=[0.0], durations=[6.0])
    assert [c[2] for c in cues] == ["구조화 카드"]


def test_number_punch_uses_its_own_style():
    cuts = [{"overlay_plan": [_ov(type="number_punch", text="3.2%p")]}]
    assert build_overlay_cues(cuts, [0.0], [6.0])[0][3] == "NumberPunch"


def test_caveat_uses_muted_style():
    cuts = [{"overlay_plan": [_ov(type="caveat_tag", text="인과 아님")]}]
    assert build_overlay_cues(cuts, [0.0], [6.0])[0][3] == "Caveat"


def test_more_cuts_than_timings_is_safe():
    cuts = [{"overlay_plan": [_ov()]}, {"overlay_plan": [_ov()]}]
    assert len(build_overlay_cues(cuts, [0.0], [6.0])) == 1


# ── ASS 출력: 기존 산출물 불변 + 오버레이 이벤트 ──
def test_ass_byte_identical_without_overlays():
    """오버레이가 없으면 스타일 정의조차 추가되지 않는다(Footer 패턴 계승)."""
    cues = [(0.0, 2.0, "안녕")]
    before = subtitles.build_ass(cues, total_sec=2.0)
    after = subtitles.build_ass(cues, total_sec=2.0, overlays=[])
    assert before == after
    assert "Style: Evidence" not in before


def test_ass_adds_styles_and_events_with_overlays():
    cues = [(0.0, 2.0, "안녕")]
    ass = subtitles.build_ass(cues, total_sec=6.0, overlays=[
        (0.5, 3.0, "표본 1,240개 기업", "Evidence"),
        (3.0, 5.0, "3.2%p", "NumberPunch"),
    ])
    assert "Style: Evidence," in ass and "Style: NumberPunch," in ass
    assert "Style: Caveat," in ass
    # Layer=1 로 자막(Layer=0) 위에 얹는다 — 겹칠 때 근거가 가려지지 않게.
    assert "Dialogue: 1," in ass
    assert "표본 1,240개 기업" in ass and "3.2%p" in ass


def test_ass_skips_blank_overlay_text():
    ass = subtitles.build_ass([(0.0, 2.0, "안녕")], total_sec=2.0,
                              overlays=[(0.0, 2.0, "   ", "Evidence")])
    assert "Style: Evidence" not in ass  # 빈 텍스트뿐이면 스타일도 안 만든다


def test_overlay_margin_clears_subtitle_and_header():
    """자막(하단)·헤더(상단)와 겹치지 않는 중상단이어야 한다."""
    assert config.OVERLAY_MARGIN_V > config.LETTERBOX_CAPTION_MARGIN_V
    assert config.OVERLAY_MARGIN_V < config.RENDER_HEIGHT - config.LETTERBOX_HEADER_MARGIN_V


def test_directive_normalizes_overlay_plan():
    from engine.directive import normalize_directive
    out = normalize_directive({"cuts": [{
        "cut_no": 1, "narration_ko": "a", "source_facts": ["what_found[0]"],
        "overlay_plan": [_ov(duration_sec=0.1), _ov(text="b"), _ov(text="c")],
    }]}, "webtoon")
    plan = out["cuts"][0]["overlay_plan"]
    assert len(plan) == config.OVERLAY_MAX_PER_CUT
    assert plan[0]["duration_sec"] == config.OVERLAY_MIN_SEC


def test_legacy_directive_gets_empty_overlay_plan():
    from engine.directive import normalize_directive
    out = normalize_directive({"cuts": [{"cut_no": 1, "narration_ko": "a"}]}, "comic")
    assert out["cuts"][0]["overlay_plan"] == []


# ── M-E4 배선 회귀 가드 (리뷰에서 발견한 버그) ──
def test_attach_fact_sheet_fills_ledger_from_draft(monkeypatch):
    """★ directives 테이블에는 fact_sheet 컬럼이 없다.

    렌더가 `directive["fact_sheet"]` 를 그냥 읽으면 항상 None 이다. 원래 소비처였던 editorial
    data_viz 코드차트는 폐기됐지만(docs/deviation-webtoon-b1-removal.md), 이 배선 자체는
    Manim 데모 경로가 쓰고 코드차트를 되살릴 때 다시 필요하다 — 그래서 남겨 두고 지킨다.
    """
    import engine.render as render

    monkeypatch.setattr(render.db, "get_draft_full",
                        lambda pid: {"fact_sheet": {"claims": [{"claim_id": "C01"}]}})
    d = {"paper_id": "p1", "header": {}, "cuts": []}   # db.get_directive 가 주는 모양
    render.attach_fact_sheet(d)
    assert d["fact_sheet"]["claims"][0]["claim_id"] == "C01"


def test_attach_fact_sheet_is_noop_without_paper_id():
    import engine.render as render
    d = {"header": {}, "cuts": []}
    render.attach_fact_sheet(d)
    assert "fact_sheet" not in d


def test_attach_fact_sheet_survives_db_failure(monkeypatch):
    """원장을 못 읽어도 렌더는 계속돼야 한다(차트 대신 스틸)."""
    import engine.render as render

    def boom(_pid):
        raise RuntimeError("db down")

    monkeypatch.setattr(render.db, "get_draft_full", boom)
    d = {"paper_id": "p1", "header": {}, "cuts": []}
    render.attach_fact_sheet(d)   # 예외가 새어나오면 렌더 전체가 죽는다
    assert d.get("fact_sheet") is None


def test_data_viz_renders_as_still_in_every_offered_version(monkeypatch):
    """코드차트 폐기 후: 원장이 붙어 있어도 data_viz 는 스틸이다.

    예전에는 editorial + data_viz 만 Manim 클립으로 갔다. 그 분기를 없앴으므로 제공 버전에서는
    무엇을 넘겨도 "image" 여야 한다 — 화면의 숫자는 overlay_plan(ASS 레이어)이 담당한다.
    """
    import engine.render as render

    monkeypatch.setattr(render.db, "get_draft_full", lambda pid: {"fact_sheet": {
        "claims": [{"claim_id": "C01", "effect_size": "3.2", "effect_unit": "%p"}]}})
    d = {"paper_id": "p1", "version_type": "webtoon",
         "header": {"version_type": "webtoon"},
         "cuts": [{"cut_no": 2, "scene_kind": "data_viz", "claim_ids": ["C01"]}]}
    render.attach_fact_sheet(d)
    for version in config.VIDEO_VERSIONS:
        assert render.render_kind_for_scene(
            "data_viz", version, d["cuts"][0], d["fact_sheet"]) == "image", version
