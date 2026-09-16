"""화풍 어휘 게이트 — 장면 묘사가 화풍을 정해 버리는 것을 막는다 (2026-09-07).

★ 무엇이 문제였나: "화풍은 코드가 정한다. visual_prompt 에 화풍 형용사를 쓰지 마라" 는
  지시가 `engine/directive.py` 에 **이미 있었다.** 검사가 없어서 모델이 매번 어겼고,
  화풍 전환 실측 4회가 전부 같은 자리에서 졌다 —
  장면 묘사의 긍정 어휘가 코드가 뒤에 붙이는 부정어를 이긴다.
  지시만 있고 검사·되먹임이 없으면 게이트가 아니라 함정이다.

★★ 검사가 `world` 선언까지 보는 것이 이 파일의 핵심이다. 화풍은 세 곳에서 정해지고
  셋째가 `visual_sequences[].world` 다(`docs/핸드오프_화풍전환_2026-09-07.md` §3-④).
  실측에서 성공·실패가 정확히 그 선언과 갈렸다 — 실험실 세계는 **장소**를 적어 목표
  화풍이 나왔고, 세포 세계는 **그리는 기법**을 적어 삽화가 나왔다.
"""

from __future__ import annotations

import pytest

from engine import config, photo_contract as pc


def _world(**kw) -> dict:
    base = {"world_id": "W1", "style": "A steel lab bench with cages",
            "lighting": "Ceiling fluorescent tubes", "background": "White tiled wall"}
    base.update(kw)
    return {"sequence_id": "SEQ1", "world": base, "stages": []}


def _cut(no: int, prompt: str) -> dict:
    return {"cut_no": no, "visual_prompt": prompt, "visual_role": "MECHANISM"}


# ─────────────────────────────────────────────────────────────
# world 선언 — 실측이 실패한 바로 그 자리
# ─────────────────────────────────────────────────────────────
def test_world_style_that_names_a_drawing_technique_is_blocked():
    """실측 원문: "Microscopic, detailed 3D rendering of cellular structures"."""
    header = {"visual_sequences": [
        _world(style="Microscopic, detailed 3D rendering of cellular structures")]}
    blocked, _ = pc.style_vocabulary_hits(header, [])
    assert any("세계 W1" in b and "3d rendering" in b for b in blocked), blocked


def test_world_lighting_glow_is_warned():
    """실측 원문: "Soft, internal glow, highlighting active elements" → 그림 4의 발광."""
    header = {"visual_sequences": [_world(lighting="Soft, internal glow")]}
    _, warned = pc.style_vocabulary_hits(header, [])
    assert any("glow" in w for w in warned), warned


def test_world_background_lens_word_is_repaired_by_code_not_blocked():
    """실측 원문: "Subtle, blurred cellular matrix" — 흐림은 코드가 정한다.

    ★ **차단이 아니라 수리다**(2026-09-07 재생성 2회 실측). 프롬프트에 금지와 대안을 둘 다
      적었는데 모델이 부분만 지켰다 — world 3개 중 1개만 고쳤다. 어휘 치환은 기계가 확실히
      하는 일이고, 모델에게 반복시키며 재시도 비용을 내는 것은 설계 실패다.
    """
    header = {"visual_sequences": [_world(background="Subtle, blurred cellular matrix")]}
    touched = pc.normalize_optics(header, [])
    bg = header["visual_sequences"][0]["world"]["background"]
    assert "blurred" not in bg.lower(), bg
    assert touched == ["세계 W1.background"], touched
    assert pc.style_vocabulary_hits(header, [])[0] == [], "수리 뒤에는 차단이 남지 않는다"


def test_a_world_that_names_a_place_passes():
    """★ 옳게 한 것을 벌하면 운영자가 게이트를 무시한다(photo_contract 설계원칙 1).

    실측에서 **통과한** 실험실 세계 선언이 그대로 통과해야 한다.
    """
    header = {"visual_sequences": [_world(
        style="Modern, sterile laboratory with scientific equipment and animal enclosures",
        lighting="Bright, even fluorescent lighting",
        background="Clean, white laboratory benches and walls")]}
    blocked, warned = pc.style_vocabulary_hits(header, [])
    assert blocked == [] and warned == [], (blocked, warned)


# ─────────────────────────────────────────────────────────────
# 컷 묘사
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("word", [
    "stylized", "photorealistic", "3D render", "illustration", "cel shading",
    "line art", "anime", "low poly", "painterly",
])
def test_art_style_words_in_a_cut_are_blocked(word: str):
    """★ 화풍 **선언**은 코드가 단어만 지워서 고칠 수 없다 — 단어를 지워도 모델이 그 장면을
    삽화로 구상했다는 사실은 남는다. 구상을 다시 하라고 돌려보낸다."""
    blocked, _ = pc.style_vocabulary_hits({}, [_cut(3, f"A cage on a bench, {word}, no text")])
    assert any("컷3" in b for b in blocked), (word, blocked)


@pytest.mark.parametrize("word", [
    "depth of field", "bokeh", "macro detail", "blurred", "out of focus",
    "film grain", "motion blur", "lens flare",
])
def test_lens_words_in_a_cut_are_repaired_not_blocked(word: str):
    """★ 렌즈 어휘는 배치 표현으로 **바꾼다**. 정보는 남기고 렌즈 지시만 뺀다."""
    cuts = [_cut(3, f"A cage on a bench with {word}. No on-screen text.")]
    touched = pc.normalize_optics({}, cuts)
    assert touched == ["컷3"], touched
    assert word.lower() not in cuts[0]["visual_prompt"].lower(), cuts[0]["visual_prompt"]
    assert "cage" in cuts[0]["visual_prompt"], "장면 정보까지 지우면 안 된다"
    assert pc.style_vocabulary_hits({}, cuts)[0] == []


def test_out_of_focus_becomes_distance_not_deletion():
    """★ 흐림을 **지우지 않고 거리로 옮긴다** — 배경이 뒤에 있다는 정보는 지켜야 한다.

    이 치환이 수동 실측에서 그림 2·3(목표 화풍)을 만든 바로 그 규칙이다.
    """
    cuts = [_cut(1, "A gloved hand holding a mouse. Equipment out of focus behind.")]
    pc.normalize_optics({}, cuts)
    assert "further back" in cuts[0]["visual_prompt"], cuts[0]["visual_prompt"]


def test_hyphenated_terms_still_match():
    """★ `\\b` 를 낱말마다 붙이면 하이픈 항목이 매치되지 않는다 — 이 저장소가 `%` 에서
    이미 두 번 한 실수다(`_SPOKEN_NUMBER_EN` 주석)."""
    blocked, _ = pc.style_vocabulary_hits(
        {}, [_cut(1, "a low-poly shape"), _cut(2, "photo-realistic surface")])
    assert len(blocked) == 2, blocked


def test_motion_prompt_is_handled_too():
    """화풍은 motion_prompt 로도 샌다 — 검사 대상과 전송 대상이 다르면 게이트는 무의미하다."""
    cuts = [{"cut_no": 5, "visual_prompt": "a cage", "motion_prompt": "slow push in, film grain"}]
    assert pc.normalize_optics({}, cuts) == ["컷5"]
    assert "film grain" not in cuts[0]["motion_prompt"]
    blocked, _ = pc.style_vocabulary_hits(
        {}, [{"cut_no": 6, "visual_prompt": "a cage", "motion_prompt": "push in, anime style"}])
    assert any("컷6" in b for b in blocked), blocked


def test_a_plain_scene_description_passes():
    blocked, warned = pc.style_vocabulary_hits(
        {}, [_cut(1, "Two cages side by side on a steel bench. No on-screen text.")])
    assert blocked == [] and warned == [], (blocked, warned)


# ─────────────────────────────────────────────────────────────
# 그릴 수 없는 판정 어휘 — 그림 4가 실패한 이유
# ─────────────────────────────────────────────────────────────
def test_the_actual_picture_4_sentence_is_warned():
    """실측(2026-09-07): 이 문장을 넣었더니 두 세포가 **똑같이** 나왔다.

    컷의 내용 전체가 비교인데 화면에 비교가 없었다 — 모델은 '건강함'을 그릴 수 없다.
    """
    prompt = ("the same aged cell with a semaglutide molecule binding to it, initiating a "
              "more pronounced transformation into a healthier, more active cell")
    _, warned = pc.style_vocabulary_hits({}, [_cut(8, prompt)])
    assert any("컷8" in w for w in warned), warned


def test_undrawable_is_a_warning_by_default_not_a_block():
    """★ 목록에 오탐이 있다("more active mice" 는 자세로 그릴 수 있다).

    히트율을 재기 전에 차단으로 올리지 않는다 — series_split 이 100% 를 막은 사고를
    이 저장소는 이미 겪었다.
    """
    header = {"visual_sequences": []}
    cuts = [_cut(1, "the cell becomes healthier"), {"cut_no": 2, "visual_role": "REALITY",
                                                    "visual_prompt": "a cage", "estimated_sec": 3}]
    res = pc.evaluate(header, cuts, None)
    assert any(r.startswith("photo_undrawable_difference") for r in res["warnings"])
    assert not any(r.startswith("photo_undrawable_difference") for r in res["block_reasons"])


def test_the_toggle_raises_undrawable_to_a_block(monkeypatch):
    """실측으로 히트율을 재고 나면 이 한 줄로 차단으로 올린다."""
    monkeypatch.setattr(config, "PHOTO_UNDRAWABLE_BLOCKS", True)
    res = pc.evaluate({"visual_sequences": []}, [_cut(1, "the cell becomes healthier")], None)
    assert any(r.startswith("photo_undrawable_difference") for r in res["block_reasons"])


# ─────────────────────────────────────────────────────────────
# 게이트 3요소 — 검사 + 고지 + 되먹임 (skill: gate-prompt-feedback-parity)
# ─────────────────────────────────────────────────────────────
def test_evaluate_wires_the_block_reason():
    res = pc.evaluate({"visual_sequences": [_world(style="stylized 3D render")]}, [], None)
    assert any(r.startswith("photo_style_word_in_prompt") for r in res["block_reasons"])


def test_the_feedback_names_the_words_and_the_world_field():
    """되먹임이 **무엇을 어떻게** 고치는지 말하지 않으면 재시도가 같은 결함을 반복한다."""
    fb = pc.feedback_prompt(["photo_style_word_in_prompt:세계 W1(3d rendering)"])
    assert "stylized" in fb
    assert "world.style" in fb, "world 를 안 말하면 모델은 컷만 고치고 세계는 그대로 둔다"


def test_the_undrawable_feedback_gives_a_concrete_replacement():
    fb = pc.feedback_prompt(["photo_undrawable_difference:컷8(healthier)"])
    assert "healthier" in fb
    assert "형태" in fb and "개수" in fb, "무엇으로 바꾸라는 말이 없으면 처방이 아니다"


def test_the_directive_prompt_tells_the_model_the_same_rule():
    """★ 검사만 있고 **고지가 없으면** 모델은 기준을 모른 채 막힌다(게이트 3요소 중 ②).

    프롬프트와 검사가 갈라지면 그날부터 게이트는 통과 불가능한 함정이 된다.
    """
    from engine import directive as dv

    src = dv.__file__ and open(dv.__file__, encoding="utf-8").read()
    assert "화풍 형용사를 쓰지 마라" in src
    for word in ("stylized", "depth of field", "healthier"):
        assert word in src, f"프롬프트가 금지 어휘 {word} 를 모델에게 알려주지 않는다"
    assert "world.style" in src, "world 규칙이 프롬프트에 없다"


def test_the_rewrite_does_not_leave_a_doubled_phrase():
    """★ 실측(2026-09-07 재생성 3회차): 모델이 이미 거리로 적은 문장 뒤에 흐림 어휘를 붙이면
    치환이 "further back along the far wall, further back" 을 만들었다.

    치환이 만든 군더더기를 그대로 발주하면 우리가 프롬프트를 더럽히는 것이다.
    """
    got = pc.strip_optics("Lab equipment further back along the far wall, blurred.")
    assert got.lower().count("further back") == 1, got
    assert "far wall" in got, got


def test_the_rewrite_keeps_two_separate_sentences_intact():
    """★ 접는 것은 **한 문장 안**에서만. 서로 다른 문장의 거리 표현까지 지우면 안 된다."""
    got = pc.strip_optics("Cages further back. A bench with blurred trays behind it.")
    assert got.lower().count("further back") == 1, got
    assert "more distant trays" in got, got


def test_a_sentence_initial_blurred_keeps_its_capital():
    """★ re.I 로 도는 표라 `Blurred` 전용 규칙을 두면 문장 중간까지 잡아간다.
    대문자 복원은 치환한 문장에만 코드가 한다."""
    got = pc.strip_optics("Blurred trays sit behind the bench.")
    assert got.startswith("More distant trays"), got


def test_an_untouched_prompt_is_returned_byte_identical():
    """★ 고칠 것이 없는 컷까지 우리가 바꾸면 안 된다 — 정리 규칙이 공백·대문자를 건드린다."""
    src = "Two cages side by side  on a bench. no on-screen text."
    assert pc.strip_optics(src) == src


# ─────────────────────────────────────────────────────────────
# 따옴표 라벨 — 실측에서 그림에 글자로 박힌 그것
# ─────────────────────────────────────────────────────────────
def test_the_actual_cut8_sentence_is_blocked():
    """실측(2026-09-07 시퀀스 렌더): 이 문장의 다섯 이름이 그림에 영어 글자로 박혔다."""
    prompt = ("The left model represents 'Calorie Restriction' and the right model represents "
              "'Semaglutide'. New areas stand for 'Exploratory Behavior', 'Spatial Memory', "
              "and 'Glucose Control'.")
    got = pc.quoted_label_cuts([_cut(8, prompt)])
    assert got and got[0].startswith("컷8("), got
    assert "Calorie Restriction" in got[0]


def test_quoted_labels_block_approval():
    res = pc.evaluate({"visual_sequences": []}, [_cut(8, "a dish labeled 'Glucose Control'")], None)
    assert any(r.startswith("photo_quoted_label_in_prompt") for r in res["block_reasons"])


def test_lowercase_labels_are_caught_too():
    """★ 처음에는 대문자로 시작하는 것만 봤는데 `'weight loss'` 가 빠져나갔다(2026-09-08 실측).

    같은 224컷으로 다시 쟀다 — 대문자만 4.9% → 소문자 포함 12.1%. 늘어난 17건을 전부
    눈으로 봤고 **하나도 빠짐없이 진짜 라벨**이었다('calorie restriction', 'good match',
    'ad quality', 'arXiv' …). 오탐 0이라 넓혔다.
    """
    got = pc.quoted_label_cuts([_cut(8, "an indicator for 'weight loss' recedes")])
    assert got and "weight loss" in got[0], got


def test_text_on_a_prop_is_a_label_too():
    """★ 소품에 적힌 글자도 그림에 구워진다 — 이건 오탐이 아니라 잡아야 할 것이다."""
    assert pc.quoted_label_cuts([_cut(1, "a sign that reads 'no entry'")]) != []


def test_a_scene_without_names_passes():
    prompt = ("Two dishes side by side: the left one is low and flat, the right one is taller "
              "and divided into three compartments. No on-screen text.")
    assert pc.quoted_label_cuts([_cut(8, prompt)]) == []


def test_the_feedback_says_to_move_the_name_to_an_overlay():
    fb = pc.feedback_prompt(["photo_quoted_label_in_prompt:컷8(Calorie Restriction)"])
    assert "overlay_plan" in fb and "따옴표" in fb


# ─────────────────────────────────────────────────────────────
# 세계를 여는 컷이 그 세계를 그리는가
# ─────────────────────────────────────────────────────────────
def _seq(style: str, lead_cut: int, mode: str = "NEW_WORLD") -> dict:
    return {"sequence_id": "SEQ1", "world": {"world_id": "W1", "style": style},
            "stages": [{"stage_id": "S1", "continuity_mode": mode, "cut_refs": [lead_cut]}]}


def test_the_actual_cellular_mismatch_is_warned():
    """실측: world 는 '세포 단면 모형'인데 여는 컷이 벤 다이어그램을 그렸다 → 세포가 사라졌다."""
    header = {"visual_sequences": [_seq(
        "A plain studio tabletop holding a cutaway teaching model of an animal cell", 8)]}
    cuts = [_cut(8, "Two translucent overlapping circular resin discs, partially overlapping.")]
    assert pc.world_lead_disagreements(header, cuts) == ["S1"]
    assert any(r.startswith("photo_world_lead_disagrees")
               for r in pc.evaluate(header, cuts, None)["warnings"])


def test_a_lead_that_draws_its_world_passes():
    header = {"visual_sequences": [_seq(
        "A plain studio tabletop holding a cutaway teaching model of an animal cell", 8)]}
    cuts = [_cut(8, "A cutaway teaching model of an animal cell on a studio tabletop.")]
    assert pc.world_lead_disagreements(header, cuts) == []


def test_only_the_world_opening_stage_is_checked():
    """★ 이어받는 stage 는 앞 그림이 세계를 이미 확정했다 — 여기서 볼 일이 아니다."""
    header = {"visual_sequences": [_seq("A cell culture room with incubators", 8,
                                        mode="CONTINUE_WORLD")]}
    assert pc.world_lead_disagreements(header, [_cut(8, "A rocket on a launch pad.")]) == []


def test_it_is_a_warning_not_a_block():
    """★ 낱말 겹침은 거친 대리 판정이다(실측 히트 14.7%에 오탐 포함). 차단으로 올리지 않는다."""
    header = {"visual_sequences": [_seq("A cell culture room with incubators", 8)]}
    res = pc.evaluate(header, [_cut(8, "A rocket on a launch pad.")], None)
    assert not any(r.startswith("photo_world_lead_disagrees") for r in res["block_reasons"])


# ─────────────────────────────────────────────────────────────
# 세계 선언이 실제로 그림에 닿는가 (죽어 있던 배선)
# ─────────────────────────────────────────────────────────────
def test_the_world_declaration_reaches_the_image_prompt():
    """★★ `visual_sequence.world_prose` 는 저장소 어디에서도 불리지 않았다 —
    지시서가 세계를 선언해도 그림에는 안 닿았고, 세계는 장식이었다.

    실측 사고: world 가 '세포 단면 모형'인데 여는 컷이 벤 다이어그램을 그려 세포가 사라졌다.
    낱말 겹침 경고로는 못 막았다("studio tabletop" 을 공유해 통과) — 대리 판정으로 막을
    문제가 아니라 **세계를 실제로 보내야 하는** 문제였다.
    """
    from engine.providers import image as ip

    header = {
        "version_type": "photo",
        "visual_sequences": [{
            "sequence_id": "SEQ1",
            "world": {"world_id": "W1",
                      "style": "A plain studio tabletop holding a cutaway teaching model of an animal cell",
                      "lighting": "Soft studio lighting from above",
                      "background": "A neutral gray backdrop"},
            "stages": [{"stage_id": "S1", "continuity_mode": "NEW_WORLD", "cut_refs": [8]}],
        }],
    }
    cut = {"cut_no": 8, "visual_role": "MECHANISM",
           "visual_prompt": "Two translucent overlapping discs."}
    got = ip._build_image_prompt(cut, header)
    assert "cutaway teaching model of an animal cell" in got, got
    assert "neutral gray backdrop" in got
    assert "Two translucent overlapping discs" in got, "컷 묘사도 그대로 남아야 한다"


def test_a_referenced_cut_does_not_repeat_the_world():
    """★ 참조 컷에는 붙이지 않는다 — 첨부 그림이 이미 세계를 확정했고,
    말로 다시 설명하면 'keep the SAME … 이것만 바꿔라' 와 싸운다."""
    from engine.providers import image as ip

    header = {
        "version_type": "photo",
        "visual_sequences": [{
            "sequence_id": "SEQ1",
            "world": {"world_id": "W1", "style": "A plain studio tabletop",
                      "lighting": "Soft light", "background": "A neutral backdrop"},
            "stages": [{"stage_id": "S1", "continuity_mode": "NEW_WORLD", "cut_refs": [8]}],
        }],
    }
    cut = {"cut_no": 8, "visual_role": "MECHANISM", "visual_prompt": "Two discs."}
    got = ip._build_image_prompt(cut, header, referenced=True)
    assert "A plain studio tabletop" not in got, got


def test_versions_without_a_world_are_unchanged(monkeypatch):
    """★ 만화식·웹툰 등 세계를 선언하지 않는 버전은 출력이 그대로여야 한다."""
    from engine.providers import image as ip

    cut = {"cut_no": 1, "visual_prompt": "a red sphere"}
    before = ip._build_image_prompt(cut, {"version_type": "comic"})
    monkeypatch.setattr(config, "IMAGE_PROMPT_CARRIES_WORLD", False)
    assert ip._build_image_prompt(cut, {"version_type": "comic"}) == before
