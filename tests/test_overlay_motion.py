"""화면 표현 다음 단계 S2~S5 — 코드가 그리는 움직임(렌더 없이 ASS 문자열로 확인한다)."""

from __future__ import annotations

import pytest

from engine import config, evidence_overlay, overlay_motion as om, subtitles, v2_directive_bridge as bridge


# ── S2 화면 글자 등장 ─────────────────────────────────────────
def test_cards_pop_and_fade_in():
    cut = {"cut_no": 1, "overlay_plan": [
        {"type": "keyword", "term": "HBM", "gloss_ko": "쌓아 올린 메모리"}]}
    cues = evidence_overlay.build_overlay_cues([cut], [0.0], [5.0])
    text = cues[0][2]
    assert text.startswith(r"{\fad(250,150)\fscx85\fscy85\t(0,220,\fscx100\fscy100)}")
    assert "HBM" in om.strip_entrance(text)


def test_after_caption_appears_after_before_caption():
    cut = {"cut_no": 1, "overlay_plan": [{"type": "label_pair", "payload": {"top": "전", "bottom": "후"}}]}
    cues = evidence_overlay.build_overlay_cues([cut], [2.0], [6.0])
    starts = {style: start for start, _e, _t, style in cues}
    assert starts["LabelTop"] == 2.0
    assert starts["LabelBottom"] == pytest.approx(2.0 + config.OVERLAY_LABEL_STAGGER_SEC)


def test_after_caption_is_not_delayed_when_the_cut_is_too_short():
    cues = om.animate([(0.0, 2.2, "후", "LabelBottom")])
    assert cues[0][0] == 0.0


def test_pointer_draws_from_tail_to_tip():
    text = om.animate([(0.0, 3.0, r"{\an7\pos(1,2)\p1}m 0 0{\p0}", "Pointer")])[0][2]
    assert text.startswith(r"{\fad(250,150)\fscx0\t(0,350,\fscx100)}")


def test_motion_switch_off_keeps_the_old_static_output(monkeypatch):
    monkeypatch.setattr(config, "OVERLAY_MOTION_ENABLED", False)
    assert om.animate([(0.0, 3.0, "전", "LabelTop")]) == [(0.0, 3.0, "전", "LabelTop")]


# ── S3 숫자 카운트업 ─────────────────────────────────────────
def test_count_up_keeps_number_shape_and_leaves_periods_alone():
    text = "3Q26E 매출 1,240억원 · 마진 18.0%"
    assert om.counted_text(text, 0.0) == "3Q26E 매출 0억원 · 마진 0.0%"
    assert om.counted_text(text, 1.0) == text
    middle = om.counted_text(text, 0.5)
    assert middle.startswith("3Q26E 매출 1,") and middle.endswith("%")      # 쉼표·소수 자릿수 유지


def test_count_up_frames_then_a_held_final_card():
    cues = om.count_up_cues(1.0, 6.0, "DRAM 가격 18.0%", "ScreenFact")
    frames = int(round(config.OVERLAY_COUNT_UP_SEC * config.OVERLAY_COUNT_UP_FPS))
    assert len(cues) == frames + 1
    assert cues[0][2].endswith("DRAM 가격 0.0%") and r"\alpha&HFF&" in cues[0][2]   # 투명하게 시작
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(cues, cues[1:])), "프레임이 빈틈없이 이어진다"
    assert cues[-1] == (pytest.approx(1.0 + frames / config.OVERLAY_COUNT_UP_FPS), 6.0,
                        r"{\fad(0,150)}DRAM 가격 18.0%", "ScreenFact")
    # 이미 등장 처리가 된 프레임에는 S2 태그가 또 붙지 않는다
    assert om.animate(cues) == cues


def test_short_card_or_no_number_skips_count_up():
    assert len(om.count_up_cues(0.0, 1.2, "18.0%", "ScreenFact")) == 1
    assert len(om.count_up_cues(0.0, 6.0, "HBM4 양산", "ScreenFact")) == 1


# ── S5 실적/전망 · 관측/모델/가설 ─────────────────────────────
@pytest.mark.parametrize("domain,text,kind", [
    ("report", "2026년 영업이익 전망 13.7조원", "forecast"),
    ("report", "3Q26E 매출 1,240억원", "forecast"),
    ("report", "회사 가이던스 매출 성장 10%", "guidance"),
    ("report", "2분기 영업이익 13.7조원", ""),
    ("paper", "시뮬레이션으로 26%~41% 절감", "modelled"),
    ("paper", "참가자 120명에서 26% 감소", ""),
    ("paper", "30% 높일 가능성", "hypothesis"),
])
def test_fact_kind(domain, text, kind):
    assert om.fact_kind(text, domain) == kind


def test_forecast_card_gets_a_badge_and_a_hollow_box():
    cues = om.screen_fact_cues(0.0, 6.0, "영업이익 13.7조", "forecast")
    assert {c[3] for c in cues} == {"ScreenFactEstimate"}
    assert "전망{" in cues[-1][2] and cues[-1][2].endswith("영업이익 13.7조")
    assert "전망{" in cues[0][2], "이름표는 숫자가 올라가는 동안에도 처음부터 보인다"
    ass = subtitles.build_ass([], overlays=cues)
    style = next(line for line in ass.splitlines() if line.startswith("Style: ScreenFactEstimate,"))
    assert style.split(",")[8] == "1", "상자 없음(BorderStyle=1) — 실적 카드(3)와 다르다"


def test_actual_card_has_no_badge():
    cues = om.screen_fact_cues(0.0, 6.0, "영업이익 13.7조", "")
    assert {c[3] for c in cues} == {"ScreenFact"} and "전망" not in cues[-1][2]


def test_bridge_tags_card_kind_and_render_reads_it():
    shadow = {"gate": {"gate_status": "READY"},
              "narration": {"generation_status": "DRAFT_ACCEPTED", "narration_beats": [{
                  "beat_id": "b1", "sentences": ["영업이익이 크게 늘어납니다."],
                  "number_delivery": {"screen_facts": [
                      {"ref": "r1", "text": "2026년 영업이익 전망 13.7조원"}]}}]}}
    directive = {"cuts": [{"cut_no": 1, "narration_ko": "영업이익이 크게 늘어납니다.",
                           "v2_trace": {"beat_id": "b1"}}]}
    assert bridge.attach_screen_cards(directive, shadow, "report") == 1
    item = directive["cuts"][0]["overlay_plan"][0]
    assert item["kind"] == "forecast"
    plan = evidence_overlay.normalize_overlay_plan(directive["cuts"][0]["overlay_plan"])
    assert plan[0]["payload"] == {"kind": "forecast"}
    again = evidence_overlay.normalize_overlay_plan(plan)              # 렌더 때 두 번째 정규화
    assert again[0]["payload"] == {"kind": "forecast"}
    cues = evidence_overlay.build_overlay_cues(directive["cuts"], [0.0], [6.0])
    assert cues[-1][3] == "ScreenFactEstimate"


# ── S4 장면 동작 → 움직임 ───────────────────────────────────
@pytest.mark.parametrize("stage,effect", [
    ({"operation": "ZOOM_INTO", "camera_operation": "HOLD"}, "ken_burns_zoom_in"),
    ({"operation": "ACCUMULATE", "camera_operation": "HOLD"}, "ken_burns_zoom_out"),
    ({"operation": "FLOW", "camera_operation": "HOLD"}, "pan_right"),
    ({"operation": "FLOW", "camera_operation": "DOLLY_IN"}, "ken_burns_zoom_in"),   # 카메라가 먼저
    ({"operation": "REVEAL", "camera_operation": "HOLD"}, ""),
    (None, ""),
])
def test_stage_effect(stage, effect):
    assert om.stage_effect(stage) == effect


def test_stage_effect_switch_off(monkeypatch):
    monkeypatch.setattr(config, "STAGE_MOTION_ENABLED", False)
    assert om.stage_effect({"operation": "ZOOM_INTO"}) == ""


def _stages(op: str) -> dict[int, dict]:
    stage = {"stage_id": "S1", "operation": op, "cut_refs": [1, 2]}
    return {1: stage, 2: stage}


def test_reveal_wipe_on_the_first_still_cut_of_a_stage_only():
    cuts = [{"cut_no": 1}, {"cut_no": 2}]
    cues = om.stage_motion_cues(cuts, [0.0, 4.0], [4.0, 4.0], _stages("REVEAL"), (0, 300, 1300))
    assert len(cues) == 1
    start, end, text, style = cues[0]
    assert (start, style) == (0.0, "StageMotion")
    assert end == pytest.approx(config.STAGE_REVEAL_WIPE_SEC + 0.1)
    assert r"\clip(0,300,1080,1600)" in text and r"\t(0," in text and r"\clip(1080,300,1080,1600)" in text


def test_video_cuts_get_no_stage_layer():
    cuts = [{"cut_no": 1, "motion_source": "video"}]
    assert om.stage_motion_cues(cuts, [0.0], [4.0], _stages("REVEAL"), (0, 300, 1300)) == []


def test_flow_arrow_is_off_by_default_and_draws_left_to_right_when_on(monkeypatch):
    cuts = [{"cut_no": 1}]
    assert om.stage_motion_cues(cuts, [0.0], [4.0], _stages("FLOW"), (0, 300, 1300)) == []
    monkeypatch.setattr(config, "STAGE_FLOW_ARROW_ENABLED", True)
    (cue,) = om.stage_motion_cues(cuts, [0.0], [4.0], _stages("FLOW"), (0, 300, 1300))
    assert cue[1] == 4.0 and r"\p1}m " in cue[2]


def test_stage_layer_sits_under_the_narration_subtitles():
    ass = subtitles.build_ass([(0.0, 2.0, "나레이션")],
                              overlays=[(0.0, 1.0, om.reveal_wipe_ass(300, 1300), "StageMotion")])
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert events[0].startswith("Dialogue: 0,") and ",StageMotion," in events[0]
    assert ",Default," in events[1]
    assert "Style: StageMotion," in ass
