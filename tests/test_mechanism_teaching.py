"""기전 시퀀스 교육력 T1·T2·T3·T5 (2026-09-18, docs/연구_기전시퀀스_교육력_2026-09-17.md).

운영자 판정: "원리 설명하는 시퀀스가 너무 별로야 … 의미없는 배경사진으로 채워져 있을 뿐이야."
연구가 찾은 원인 넷 중 셋을 코드로 고친다 — 이 파일은 그 배선이 **실제로 이어졌는지**를 본다
(이 저장소의 단골 실패: 만들어 놓고 부르지 않음).

  T1  mechanism 구조가 이미지 프롬프트에 실린다 + 구조와 장면이 딴 말이면 차단
  T2  상태가 바뀌는 stage 는 전·후 분할 스틸(I2V 대신)
  T3  legend / label_pair 오버레이가 ASS 로 나간다 + 없으면 경고
  T5  기전 컷 색 규약(앰버 + 비교용 두 색)이 프롬프트·범례·지시서 안내에서 같은 표를 읽는다
"""

from __future__ import annotations

import os
import tempfile

from engine import (assemble, config, evidence_overlay as eo, photo_contract as pc, render,
                    subtitles, visual_sequence as vs)
from engine.providers import image as image_provider

MECH = {
    "subject": "cortical rewiring after hearing loss",
    "components": ["a hearing brain", "a deaf brain", "the visual cortex"],
    "relationship": "the idle auditory area is taken over by vision",
    "initial_state": "both brains identical",
    "transformation": "the visual cortex of the deaf brain grows into the idle auditory area",
    "final_state": "the deaf brain has an enlarged visual cortex",
    "highlighted_element": "the visual cortex",
    "claim_ids": ["C01"],
}


def _cut(n, **kw):
    base = {"cut_no": n, "visual_role": "MECHANISM", "motion_source": "video",
            "visual_prompt": ("two brains side by side on a studio tabletop, the hearing brain "
                              "muted blue, the deaf brain muted coral, its visual cortex enlarged"),
            "mechanism": dict(MECH), "overlay_plan": []}
    base.update(kw)
    return base


def _stage(sid, cut_no, *, ops=(), cont=""):
    return {"stage_id": sid, "cut_refs": [cut_no], "continuity_mode": "MUTATE_STATE" if cont else "NEW_WORLD",
            "continuity_from": cont, "entity_refs": ["BRAIN"],
            "mutations": [{"entity_id": "BRAIN", "operation": op, "property": "shape",
                           "visible_change": True, "result_state": "bigger"} for op in ops]}


def _header(stages):
    return {"version_type": "photo", "hook_ko": "훅",
            "visual_sequences": [{"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
                                  "entities": [{"entity_id": "BRAIN"}], "stages": stages}]}


# ── T1-a 구조가 프롬프트에 닿는다 ─────────────────────────────────────────
def test_mechanism_prose_reaches_the_image_prompt():
    got = image_provider._build_image_prompt(_cut(4), {"version_type": "photo"})
    assert "a hearing brain, a deaf brain and the visual cortex all visible together" in got
    assert "the visual cortex is the part being explained" in got
    # ★ 전·후를 나열하지 않는다 — 유료 실측에서 "before: …; after: …" 가 세로 3단 스토리보드가 됐다.
    assert "before:" not in got and "after:" not in got
    assert "One single scene (no panels, no grid, no storyboard)" in got
    # 구조가 장면 묘사보다 **앞**에 온다 — 무엇이 보여야 하는지가 먼저다.
    assert got.index("all visible") < got.index("two brains side by side")


def test_sentence_shaped_fields_do_not_become_prompt_fragments():
    """실측 파편: 'the The two models as a comparative pair. is the part being explained'."""
    cut = _cut(4, mechanism={**MECH, "highlighted_element": "The two models as a comparative pair."})
    prose = vs.mechanism_prose(cut)
    assert "pair." not in prose and "The two models as a comparative pair is the part" in prose
    long_focus = _cut(4, mechanism={**MECH, "highlighted_element": (
        "the specific larger area representing peripheral vision which is highlighted with a bright amber glow")})
    assert "part being explained" not in vs.mechanism_prose(long_focus), "문장은 이름이 아니다 — 버린다"


def test_referenced_cut_only_carries_the_change_not_the_before_state():
    """참조 컷에서 전·후를 다 말하면 '이것만 바꿔라'와 싸운다."""
    got = image_provider._build_image_prompt(_cut(4), {"version_type": "photo"}, referenced=True)
    assert "The change to show: the visual cortex of the deaf brain grows" in got
    assert "both brains identical" not in got


def test_korean_fields_are_not_sent_to_the_image():
    """한글이 섞인 필드는 그림에 안 간다 — 글자로 구워질 위험, 언어판 공유."""
    cut = _cut(4, mechanism={**MECH, "subject": "청각 상실 뒤 재배선",
                              "components": ["a hearing brain", "a deaf brain"],
                              "initial_state": "두 뇌가 같다", "final_state": "시각 피질이 커졌다"})
    prose = vs.mechanism_prose(cut)
    assert "청각" not in prose and "두 뇌" not in prose
    assert "a hearing brain and a deaf brain all visible together" in prose


def test_cuts_without_mechanism_are_byte_for_byte_unchanged():
    """만화식 등 mechanism 이 없는 컷·버전은 출력이 그대로다(비교 실험 불변식)."""
    cut = {"cut_no": 1, "visual_prompt": "a red sphere"}
    assert vs.mechanism_prose(cut) == ""
    got = image_provider._build_image_prompt(cut, {"version_type": "comic"})
    assert got.startswith("a red sphere, vertical 9:16")


# ── T1-b 구조와 장면이 딴 말을 하면 차단 ─────────────────────────────────
def test_detached_prompt_is_blocked_and_matching_prompt_is_not():
    header = {"hook_ko": "훅", "total_estimated_sec": 12}
    ok = pc.evaluate(header, [_cut(1), _cut(2, visual_role="REALITY", mechanism=None,
                                             visual_prompt="a research lab bench")])
    assert not any(r.startswith("photo_mechanism_prompt_detached") for r in ok["block_reasons"]), ok
    # 실측에서 잡힌 꼴 그대로 — entity_id 를 구성요소라고 적고 장면은 딴 것을 그린다.
    bad = pc.evaluate(header, [_cut(1, mechanism={**MECH, "components": ["HUMAN_GENERIC", "AI_GENERIC"]},
                                    visual_prompt="a group of diverse people looking to the right")])
    assert "photo_mechanism_prompt_detached:1" in bad["block_reasons"]


def test_korean_components_count_as_detached():
    """한글 구성요소는 그림에 못 가므로 영어 구성요소가 2개 미만이면 같은 사유다."""
    got = pc.evaluate({"hook_ko": "훅"}, [_cut(1, mechanism={**MECH, "components": ["뇌", "시각 피질"]})])
    assert "photo_mechanism_prompt_detached:1" in got["block_reasons"]


def test_component_hits_measure():
    assert vs.mechanism_component_hits(_cut(1)) == (3, 3)
    assert vs.mechanism_component_hits({"mechanism": {"components": ["뇌", "the moon"]},
                                        "visual_prompt": "a lunar surface"}) == (0, 1)


def test_the_text_gates_see_the_mechanism_prose_too():
    """구조 문장이 프롬프트에 실리므로 따옴표 라벨 검사도 그것을 봐야 한다."""
    cut = _cut(1, mechanism={**MECH, "highlighted_element": "the 'Visual Cortex'"})
    got = pc.evaluate({"hook_ko": "훅"}, [cut])
    assert any(r.startswith("photo_quoted_label_in_prompt") for r in got["block_reasons"])


# ── T3 범례·캡션 ─────────────────────────────────────────────────────────
def test_legend_and_label_pair_normalize_and_become_ass_cues():
    plan = eo.normalize_overlay_plan([
        {"type": "legend", "payload": {"items": [{"color": "blue", "label": "정상 청각"},
                                                {"color": "coral", "label": "청각 상실"},
                                                {"color": "neon", "label": "모르는 색"}]}},
        {"type": "label_pair", "payload": {"top": "변화 전", "bottom": "변화 후"}},
    ])
    assert [p["type"] for p in plan] == ["legend", "label_pair"]
    assert plan[0]["payload"]["items"][2]["color"] == "white", "모르는 색은 흰색으로 — 조용히 버리지 않는다"
    cues = eo.build_overlay_cues([{"cut_no": 1, "overlay_plan": plan}], [0.0], [5.0])
    styles = [c[3] for c in cues]
    assert styles == ["Legend", "LabelTop", "LabelBottom"]
    legend_text = cues[0][2]
    assert config.LEGEND_COLORS_ASS["blue"] in legend_text and "정상 청각" in legend_text
    assert "\\N" in legend_text, "항목은 줄바꿈으로 쌓인다"
    assert cues[1][2] == "변화 전" and cues[2][2] == "변화 후"


def test_legend_survives_when_the_model_writes_text_instead_of_payload():
    plan = eo.normalize_overlay_plan([{"type": "legend", "text": "amber=시각 피질 / blue=정상 뇌"}])
    assert plan and plan[0]["payload"]["items"] == [
        {"color": "amber", "label": "시각 피질"}, {"color": "blue", "label": "정상 뇌"}]
    pair = eo.normalize_overlay_plan([{"type": "label_pair", "text": "전 / 후"}])
    assert pair and pair[0]["payload"] == {"top": "전", "bottom": "후"}


def test_label_pair_without_both_halves_is_dropped():
    assert eo.normalize_overlay_plan([{"type": "label_pair", "payload": {"top": "전"}}]) == []


def test_ass_defines_the_three_new_styles_only_when_overlays_exist():
    cues = [(0.0, 2.0, "x", "Legend")]
    with_ov = subtitles.build_ass([(0.0, 2.0, "자막")], header_title="t", header_hook="h", overlays=cues)
    for name in ("Style: Legend,", "Style: LabelTop,", "Style: LabelBottom,"):
        assert name in with_ov, name
    # 범례는 좌하단(1). 캡션 두 줄은 **분할선을 위·아래로 끼고** 붙는다 —
    #   위 캡션은 하단 기준(2)으로 선 위에, 아래 캡션은 상단 기준(8)으로 선 아래에.
    def _style(name: str) -> list[str]:
        return next(l for l in with_ov.splitlines() if l.startswith(f"Style: {name},")).split(",")
    assert _style("Legend")[11] == "1"
    # ★ 캡션 두 줄은 **각자 자기 화면의 머리**에 붙는다(둘 다 상단 기준 8). 실측 세 번 끝에 정했다:
    #   분할선을 끼면 몰려서 주인이 안 보이고, 화면 아래에 두면 나레이션 자막과 12px 까지 붙는다.
    assert _style("LabelTop")[11] == "8" and _style("LabelBottom")[11] == "8"
    # ★ 자리는 레터박스 기하에서 **유도**된다 — 숫자를 박으면 밴드를 바꿀 때 캡션만 딴 곳에 남는다.
    top_mv, bot_mv = int(_style("LabelTop")[14]), int(_style("LabelBottom")[14])
    # ★ 위 캡션은 **키워드 카드 아래 줄**이다 — 같은 줄이면 좌측 카드와 가운데 캡션이 붙는다.
    assert top_mv == (config.OVERLAY_KEYWORD_MARGIN_V + config.OVERLAY_KEYWORD_FONT_SIZE
                      + config._SPLIT_CAPTION_GAP_PX)
    assert top_mv > config._HEADER_BLOCK_BOTTOM_Y, "헤더(제목·훅) 아래에서 시작해야 한다"
    assert bot_mv == config._SPLIT_DIVIDER_Y + config._SPLIT_CAPTION_GAP_PX
    assert top_mv < bot_mv, "위 화면 캡션이 아래 화면 캡션보다 위에 있어야 한다"
    assert bot_mv - top_mv > 400, "둘이 가까우면 어느 캡션이 어느 화면 것인지 안 보인다"
    # 아래 캡션이 나레이션 자막(하단)까지 내려오면 두 글자가 붙어 읽힌다(실측 12px).
    assert bot_mv + config.OVERLAY_LABEL_FONT_SIZE < config.RENDER_HEIGHT - int(
        config.RENDER_HEIGHT * config.SUBTITLE_SAFE_BOTTOM)
    without = subtitles.build_ass([(0.0, 2.0, "자막")], header_title="t", header_hook="h")
    assert "Style: Legend," not in without, "오버레이가 없으면 출력 바이트 불변"


def test_labels_render_while_evidence_cards_stay_off():
    """★ 2026-09-18 운영자 "오버레이 스위치 켜줘" — 9/8 에 뺀 수치·출처 카드는 그대로 꺼 둔 채
    범례·캡션만 나간다. 같은 스위치를 통째로 켰다면 그 카드가 돌아왔을 것이다."""
    assert config.MECHANISM_LABEL_OVERLAYS_ENABLED is True
    assert config.EVIDENCE_OVERLAY_ENABLED is False, "9/8 지시(수치·출처 카드 빼기)는 유지"
    cuts = [{"cut_no": 1, "overlay_plan": [
                {"type": "number_punch", "text": "+92일"},
                {"type": "legend", "payload": {"items": [{"color": "blue", "label": "정상"}]}}]},
            {"cut_no": 2, "overlay_plan": [{"type": "label_pair", "payload": {"top": "전", "bottom": "후"}}]}]
    only = eo.build_overlay_cues(cuts, [0.0, 5.0], [5.0, 5.0], only_types=set(config.OVERLAY_STRUCTURED_TYPES))
    assert [c[3] for c in only] == ["Legend", "LabelTop", "LabelBottom"], "수치 카드는 안 나간다"
    everything = eo.build_overlay_cues(cuts, [0.0, 5.0], [5.0, 5.0])
    assert "NumberPunch" in [c[3] for c in everything]
    # 렌더가 실제로 이 분기를 탄다(만들고 안 부르는 것 방지).
    import inspect
    src = inspect.getsource(render)
    assert "config.MECHANISM_LABEL_OVERLAYS_ENABLED" in src and "only_types=only_types" in src


def test_new_overlay_types_are_offered_to_the_directive_model():
    """게이트가 legend 를 요구하는데 프롬프트가 그 유형을 안 주면 함정이다(gate-prompt-feedback-parity)."""
    from engine import directive
    assert "legend" in config.OVERLAY_TEXT_TYPES and "label_pair" in config.OVERLAY_TEXT_TYPES
    assert "legend|label_pair" in directive._OVERLAY_TYPES_HELP or "label_pair" in directive._OVERLAY_TYPES_HELP
    assert "photo_mechanism_unlabeled" in config.RETRYABLE_QUALITY_WARNINGS


def test_mechanism_sequence_without_legend_warns_on_its_first_cut(monkeypatch):
    # 범례 스위치가 꺼져 있으면 검사도 꺼진다(렌더가 안 그리는 것을 요구하지 않는다).
    monkeypatch.setattr(config, "MECHANISM_LABEL_OVERLAYS_ENABLED", False)
    off = pc.evaluate(_header([_stage("S1", 3), _stage("S2", 4, ops=("TRANSFORM",), cont="S1")]), [_cut(3), _cut(4)])
    assert not any(w.startswith("photo_mechanism_unlabeled") for w in off["warnings"])
    monkeypatch.setattr(config, "MECHANISM_LABEL_OVERLAYS_ENABLED", True)
    header = _header([_stage("S1", 3), _stage("S2", 4, ops=("TRANSFORM",), cont="S1")])
    cuts = [_cut(3), _cut(4)]
    got = pc.evaluate(header, cuts)
    warned = [w for w in got["warnings"] if w.startswith("photo_mechanism_unlabeled")]
    assert warned and "3" in warned[0] and "4" in warned[0], got["warnings"]
    # legend 를 시퀀스 어딘가에, label_pair 를 바뀌는 stage 의 컷에 넣으면 조용하다.
    cuts[0]["overlay_plan"] = [{"type": "legend", "payload": {"items": [{"color": "blue", "label": "정상"}]}}]
    cuts[1]["overlay_plan"] = [{"type": "label_pair", "payload": {"top": "전", "bottom": "후"}}]
    got = pc.evaluate(header, cuts)
    assert not any(w.startswith("photo_mechanism_unlabeled") for w in got["warnings"])


# ── T2 전·후 분할 스틸 ────────────────────────────────────────────────────
def test_split_applies_only_to_state_changing_stages_with_a_before_image():
    header = _header([_stage("S1", 3), _stage("S2", 4, ops=("TRANSFORM",), cont="S1"),
                      _stage("S3", 5, ops=("MOVE",), cont="S2")])
    assert render.split_before_after_applies(_cut(4), header) is True
    assert render.split_before_after_applies(_cut(3), header) is False, "여는 stage 는 전이 없다"
    assert render.split_before_after_applies(_cut(5), header) is False, "운동(MOVE)은 I2V 가 한다"
    assert render.split_before_after_applies(_cut(4, visual_role="REALITY"), header) is False


def test_split_changes_the_stage_video_cache_key():
    """스위치를 켠 뒤 옛 Veo 영상이 캐시에서 되살아나면 안 된다."""
    header = _header([_stage("S1", 3), _stage("S2", 4, ops=("TRANSFORM",), cont="S1")])
    cuts = [_cut(3), _cut(4)]
    plan = {"stage_id": "S2", "indexes": [1], "total_sec": 6.0}
    on = render.stage_video_hash(plan, cuts, header)
    config.MECHANISM_SPLIT_BEFORE_AFTER = False
    try:
        off = render.stage_video_hash(plan, cuts, header)
    finally:
        config.MECHANISM_SPLIT_BEFORE_AFTER = True
    assert on != off


def test_compose_split_still_stacks_before_over_after():
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        before, after, out = (os.path.join(d, n) for n in ("b.png", "a.png", "split.png"))
        Image.new("RGB", (540, 960), (0, 0, 255)).save(before)
        Image.new("RGB", (540, 960), (255, 0, 0)).save(after)
        assert render._compose_split_still(before, after, out) is True
        img = Image.open(out)
        # ★★ 캔버스는 **콘텐츠 밴드 크기**다(전체 프레임이 아니다). 전체 프레임으로 만들면 조립이
        #   다시 밴드로 cover-crop 하면서 위 화면의 위·아래 화면의 아래를 잘라낸다(2026-09-18).
        w, h = assemble.layout_content_dims()
        assert (img.width, img.height) == (w, h)
        assert img.getpixel((10, 10)) == (0, 0, 255), "위가 전"
        assert img.getpixel((10, h - 10)) == (255, 0, 0), "아래가 후"
        assert img.getpixel((10, h // 2)) == tuple(config.MECHANISM_SPLIT_DIVIDER_RGB), "가운데 분할선"


def test_compose_split_still_fails_soft():
    with tempfile.TemporaryDirectory() as d:
        assert render._compose_split_still(os.path.join(d, "nope.png"), os.path.join(d, "nope2.png"),
                                           os.path.join(d, "out.png")) is False


def test_still_video_command_has_no_audio_and_exact_length():
    argv = assemble.build_still_video_command(image_path="s.png", duration=6.25,
                                              effects=["ken_burns_zoom_in"], out_path="o.mp4")
    assert "-an" in argv and "-t" in argv and argv[argv.index("-t") + 1] == "6.250"
    assert "zoompan" in argv[argv.index("-vf") + 1]


def test_the_split_still_gets_no_camera_move():
    """★ 합성본이 이미 밴드 크기라 켄번스를 걸면 **비교하라고 만든 가장자리를 잘라낸다.**
    비교는 멈춰서 보는 화면이다(참고 영상도 구도를 고정하고 주석만 움직인다).
    대가는 freezedetect 경고이고, 그 경고는 사실이므로 숨기지 않는다."""
    assert config.MECHANISM_SPLIT_EFFECT == ""
    import inspect
    assert "if e]" in inspect.getsource(render._build_split_stage_video), "빈 효과를 넘기면 안 된다"


def test_the_split_is_actually_wired_into_the_stage_loop():
    """만들어 놓고 안 부르는 것을 막는다(dead-wiring-audit)."""
    import inspect
    src = inspect.getsource(render)
    assert "split_before_after_applies(cut, header)" in src
    assert "_compose_split_still(split_ref, img0, split_img)" in src
    assert 'decision["split_before_after"] = True' in src, "결정을 seq_decision 에 남겨야 화면이 안다"


# ── T5 색 규약이 한 표에서 나온다 ─────────────────────────────────────────
def test_color_code_is_one_table_read_by_prompt_legend_and_directive():
    from engine import directive
    style = config.VISUAL_ROLE_STYLE["MECHANISM"]
    for color in config.MECHANISM_COLOR_CODE:
        assert color in style, color
        assert color in config.LEGEND_COLORS_ASS, color
    src = inspect_src(directive)
    assert "amber=설명하는 부분" in src and "coral=둘째 집단" in src
    # 참조 컷에서도 비교색은 남는다(범례가 거짓이 되지 않게). 앰버 강조만 뗀다.
    cont = image_provider._build_image_prompt(_cut(4), {"version_type": "photo"}, referenced=True)
    assert "muted blue and muted coral" in cont
    assert "amber accent on the part being explained" not in cont


def inspect_src(mod):
    import inspect
    return inspect.getsource(mod)


def test_prompt_is_recorded_in_asset_meta():
    """연구 때 '구조가 그림에 닿았는가'를 확인할 기록이 없었다 — 이제 남긴다."""
    import inspect
    src = inspect.getsource(render)
    assert 'asset_meta["prompt"]' in src


# ── 키워드 카드 · 지시 화살표 (2026-09-18 저녁, 참고 영상 문법) ──────────────
#
# 운영자가 참고 영상(고기 핏물 편)을 주며 "키워드 카드랑 화살표까지". 그 영상이 모든 컷에서 하는
# 두 가지다: ① 화면 속 물체에 **낱말 하나**로 이름표를 단다 ② 설명 대상을 **화살표로 찍는다**.
# 둘 다 생성 모델이 아니라 코드가 그린다(ASS 텍스트·도형) — 추가 비용 0.

def test_keyword_card_becomes_a_boxed_ass_cue():
    plan = eo.normalize_overlay_plan([{"type": "keyword", "text": "  MYOGLOBIN \n"}])
    assert plan[0]["type"] == "keyword" and plan[0]["text"] == "MYOGLOBIN"
    cues = eo.build_overlay_cues([{"cut_no": 1, "overlay_plan": plan}], [0.0], [4.0])
    assert [c[3] for c in cues] == ["Keyword"]
    with_ov = subtitles.build_ass([(0.0, 4.0, "자막")], header_title="t", header_hook="h",
                                  overlays=cues)
    line = next(l for l in with_ov.splitlines() if l.startswith("Style: Keyword,"))
    parts = line.split(",")
    # ★ ASS 는 BorderStyle=3 에서 **OutlineColour** 를 박스로 칠한다(BackColour 가 아니다).
    #   거꾸로 넣었더니 시안 카드가 검게 나왔다(2026-09-18 실측).
    assert parts[4] == config.OVERLAY_KEYWORD_BOX_ASS, "박스 색이 Outline 자리에 있어야 한다"
    assert parts[8] == "3", "BorderStyle=3 이어야 불투명 박스가 된다"
    assert parts[11] == "7", "좌상단"


def test_the_annotation_layer_is_one_colour():
    """★ 카드 박스와 화살표가 같은 색이어야 '이건 우리가 얹은 설명'으로 읽힌다(참고 영상의 문법)."""
    assert config.OVERLAY_KEYWORD_BOX_ASS == config.OVERLAY_ANNOTATION_COLOR_ASS
    assert config.OVERLAY_POINTER_COLOR_ASS == config.OVERLAY_ANNOTATION_COLOR_ASS


def test_the_card_sits_below_the_header_not_on_top_of_the_hook():
    """★ 밴드 맨 위로 잡았더니 불투명 카드가 훅을 덮었다(실측) — 헤더 높이에서 유도한다."""
    assert config.OVERLAY_KEYWORD_MARGIN_V >= config._HEADER_BLOCK_BOTTOM_Y
    assert config.OVERLAY_LABEL_TOP_MARGIN_V > config.OVERLAY_KEYWORD_MARGIN_V, \
        "분할 캡션이 카드와 같은 줄이면 좌측 카드와 가운데 캡션이 붙는다"


def test_pointer_draws_one_arrow_per_zone_with_the_tip_on_target():
    plan = eo.normalize_overlay_plan([{"type": "pointer", "payload": {"at": ["left", "right"]}}])
    assert plan[0]["payload"]["zones"] == ["left", "right"]
    cues = eo.build_overlay_cues([{"cut_no": 1, "overlay_plan": plan}], [0.0], [4.0])
    assert [c[3] for c in cues] == ["Pointer", "Pointer"], "구역마다 화살표 하나"
    # ★ 회전 중심(\org)이 화살촉이어야 각도가 바뀌어도 촉이 목표에 남는다.
    for cue, zone in zip(cues, ("left", "right")):
        fx, _fy, deg = eo._POINTER_ZONE[zone]
        tip_x = int(config.RENDER_WIDTH * fx)
        assert f"\\org({tip_x}," in cue[2], cue[2]
        assert f"\\frz{deg}" in cue[2]
        assert "\\p1}" in cue[2] and "{\\p0}" in cue[2], "ASS 도형 모드로 열고 닫아야 한다"


def test_pointers_stay_inside_the_content_band():
    """★ 상하 검은 바 위에 화살표를 그리면 띠를 가린다 — 밴드 안에서만 논다."""
    _, top, height = eo.content_band()
    for zone in config.OVERLAY_POINTER_ZONES:
        text = eo.pointer_ass_text(zone)
        y = int(text.split("\\org(")[1].split(",")[1].split(")")[0])
        assert top <= y <= top + height, (zone, y)


def test_unknown_zones_are_reported_not_silently_dropped():
    """조용히 사라지면 운영자는 화살표를 시켰다고 믿는다(error-vs-empty)."""
    assert eo.normalize_overlay_plan([{"type": "pointer", "payload": {"at": "nowhere"}}]) == []
    got = pc.evaluate({"hook_ko": "훅"}, [_cut(1, overlay_plan=[
        {"type": "pointer", "payload": {"at": "nowhere"}}])])
    assert any(w.startswith("photo_pointer_zone_unknown") for w in got["warnings"])


def test_a_sentence_card_is_flagged_but_a_word_card_is_not():
    """★ 9/8 에 운영자가 뺀 것은 카드가 아니라 **문장짜리 카드**였다."""
    bad = pc.evaluate({"hook_ko": "훅"}, [_cut(1, narration_ko="문장", overlay_plan=[
        {"type": "keyword", "text": "캘리포니아 대학교 버클리 연구팀"}])])
    assert any(w.startswith("photo_keyword_is_a_sentence") for w in bad["warnings"])
    ok = pc.evaluate({"hook_ko": "훅"}, [_cut(1, narration_ko="문장", overlay_plan=[
        {"type": "keyword", "text": "75% WATER"}])])
    assert not any(w.startswith("photo_keyword") for w in ok["warnings"])


def test_a_card_that_copies_the_narration_is_flagged_but_naming_is_not():
    """낱말 하나가 나레이션에 나오는 것은 **정상이다** — 말하면서 이름을 다는 것이 문법이다."""
    copied = pc.evaluate({"hook_ko": "훅"}, [_cut(1, narration_ko="이건 그냥 붉은 물입니다",
                                                 overlay_plan=[{"type": "keyword", "text": "붉은 물"}])])
    assert any(w.startswith("photo_keyword_repeats_narration") for w in copied["warnings"])
    naming = pc.evaluate({"hook_ko": "훅"}, [_cut(1, narration_ko="이건 미오글로빈입니다",
                                                 overlay_plan=[{"type": "keyword", "text": "미오글로빈"}])])
    assert not any(w.startswith("photo_keyword") for w in naming["warnings"])


def test_the_model_is_told_about_both_new_types():
    """게이트가 요구하는 것을 프롬프트가 안 주면 함정이다(gate-prompt-feedback-parity)."""
    from engine import directive, report_directive
    for src in (inspect_src(directive), inspect_src(report_directive)):
        assert "keyword" in src and "pointer" in src
        assert "payload.at" in src or "at: [구역" in src
    for code in ("photo_keyword_is_a_sentence", "photo_keyword_repeats_narration",
                 "photo_pointer_zone_unknown"):
        assert code in config.RETRYABLE_QUALITY_WARNINGS, code
        assert code in pc.WARNING_REASONS, code
        assert pc.feedback_prompt([], [f"{code}:1"]).strip(), code


def test_pointer_aims_at_the_object_not_the_grid(tmp_path):
    """★★ 격자만 쓰면 화살표가 **빈 벽을 가리킨다**(2026-09-18 실측).

    모델은 "오른쪽 뇌"라는 뜻으로 `right` 를 적는데 격자는 화면 오른쪽 한가운데를 찍는다 —
    생성된 그림에서 대상은 아래쪽에 앉아 있었고 화살표는 그 위 허공에 떴다. 모델에게 좌표를
    물을 수는 없으니(자기 그림을 본 적이 없다) **코드가 그림을 본다.**
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (config.RENDER_WIDTH, config.RENDER_HEIGHT), (200, 200, 200))
    dr = ImageDraw.Draw(img)
    # 오른쪽 **아래**에만 물체를 둔다 — 격자(가운데)와 확실히 다른 자리.
    dr.ellipse([700, 1500, 1000, 1800], fill=(20, 20, 20))
    p = tmp_path / "scene.png"
    img.save(p)
    grid = eo.pointer_ass_text("right")
    aimed = eo.pointer_ass_text("right", str(p))
    assert grid != aimed, "그림을 줬는데 격자 자리 그대로면 배선이 끊긴 것이다"
    found = eo._edge_centroid(str(p), "right")
    assert found is not None
    assert found[0] > config.RENDER_WIDTH * 0.5, "오른쪽 절반에서 찾아야 한다"
    assert found[1] > config._SPLIT_DIVIDER_Y, "물체는 아래쪽에 있다"


def test_a_missing_or_broken_image_falls_back_to_the_grid():
    """그림을 못 읽는다고 화살표를 통째로 버리지 않는다 — 격자로라도 가리킨다."""
    assert eo._edge_centroid("없는파일.png", "right") is None
    assert eo.pointer_ass_text("right", "없는파일.png") == eo.pointer_ass_text("right")


def test_every_arrow_stays_fully_inside_the_frame():
    """★ 촉만 클램프하면 **꼬리가 화면 밖으로 잘린다**(2026-09-18 실측: 오른쪽 끝에서 잘렸다)."""
    import math
    import re
    _, top, height = eo.content_band()
    length = config.OVERLAY_POINTER_LENGTH_PX
    for zone in config.OVERLAY_POINTER_ZONES:
        text = eo.pointer_ass_text(zone)
        tip_x, tip_y = map(int, re.search(r"org\((-?\d+),(-?\d+)\)", text).groups())
        deg = int(re.search(r"frz(-?\d+)", text).group(1))
        rad = math.radians(deg)
        tail_x, tail_y = tip_x - length * math.cos(rad), tip_y + length * math.sin(rad)
        assert 0 <= min(tip_x, tail_x) and max(tip_x, tail_x) <= config.RENDER_WIDTH, zone
        assert top <= min(tip_y, tail_y) and max(tip_y, tail_y) <= top + height, zone


def test_the_render_hands_the_images_to_the_overlay_builder():
    """만들어 놓고 안 넘기면 화살표는 영원히 격자를 가리킨다(dead-wiring)."""
    import inspect
    src = inspect.getsource(render)
    assert "images={no: p for no, p in asset_index.items() if p}" in src


# ── 발광 어휘를 앰버 강조로 (2026-09-18 밤) ──────────────────────────────
#
# 화풍은 "no glowing effects, no neon, no bloom, no light emission" 이라고 이미 말한다.
# 그런데 실제 그림에 발광이 나왔다(지시서 79298b9f 컷3, 산호 뇌의 주황 테두리). 이 저장소의
# 결론 그대로다 — **부정어는 긍정 어휘를 못 이긴다.** 그러니 프롬프트에서 그 어휘를 뺀다.
# 저장된 40편 437컷 중 **143회**가 이 어휘를 들고 있었다(셋 중 한 컷).

def test_glow_becomes_an_amber_accent_not_a_hole_in_the_sentence():
    """★ 지우기만 하면 문장이 깨진다 — 실측: 'The model is glowing softly, emphasizing…' 이
    'The model is softly, emphasizing…' 이 됐다. 동사형을 **먼저** 잡아야 한다."""
    got = pc.strip_glow("The model is glowing softly, emphasizing its folded structure.")
    assert got == "The model is picked out in amber, emphasizing its folded structure."
    assert "glow" not in pc.strip_glow("824 markers glow more intensely and are highlighted")
    assert "glow" not in pc.strip_glow("the cortex glows brightly, indicating expression")


def test_glow_as_an_adjective_is_simply_dropped():
    """형용사는 지워도 장면이 남는다(실측 문장 그대로)."""
    assert pc.strip_glow("A, glowing blue double-helix DNA strand model") \
        == "A blue double-helix DNA strand model"
    # ★ 첫 글자 대문자화는 공용 정리 규칙(strip_optics)이 하는 일이다 — 문장 머리를 지운 뒤
    #   소문자로 시작하지 않게 한다. 여기서 바꾸지 않는다.
    assert pc.strip_glow("subtle glowing lines represent hydrogen bonds") \
        == "Subtle lines represent hydrogen bonds"


def test_prompts_without_glow_are_untouched():
    """★ 멀쩡한 프롬프트를 건드리면 안 된다(strip_optics 와 같은 규율)."""
    clean = "two brains side by side on a studio tabletop, the left one muted blue"
    assert pc.strip_glow(clean) == clean


def test_the_normalizer_reaches_prompt_world_and_mechanism():
    """★ 도해 구조도 봐야 한다 — 2026-09-18 부터 그 문장이 그림에 실린다(mechanism_prose)."""
    header = {"visual_sequences": [{"sequence_id": "S", "world": {"lighting": "a soft glow"},
                                    "stages": []}]}
    cuts = [{"cut_no": 1, "visual_prompt": "a glowing cube",
             "mechanism": {"highlighted_element": "the glowing rim"}}]
    touched = pc.normalize_glow(header, cuts)
    assert touched, "고친 자리를 돌려줘야 화면이 그 사실을 안다"
    assert "glow" not in cuts[0]["visual_prompt"]
    assert "glow" not in cuts[0]["mechanism"]["highlighted_element"]
    assert "glow" not in header["visual_sequences"][0]["world"]["lighting"]


def test_the_pipeline_actually_calls_it_and_says_so():
    """만들어 놓고 안 부르면 발광은 그대로 나간다(dead-wiring). 그리고 조용히 고치지 않는다."""
    from engine import directive
    src = inspect_src(directive)
    assert "photo_contract.normalize_glow(header, cuts)" in src
    assert "photo_glow_normalized" in src
    assert "photo_glow_normalized" in pc.WARNING_REASONS
    # 발광은 "그릴 수 없는 판정"이 아니라 **너무 잘 그려지는 것**이다 — 그 목록에서 뺐다.
    assert "glowing" not in config.PHOTO_UNDRAWABLE_QUALITY_TERMS
