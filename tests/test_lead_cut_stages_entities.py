"""여는 컷이 **뒤에 움직일 배우를 무대에 세웠는가** (2026-09-10).

운영자 지적(2026-09-09): "쥐 다음 나오는 세포와 분자같은 도해가 좀 어색한데?
원리 설명이랑 잘 들어맞는느낌이 아닌데? 왜그런거지??"

원인: NEW_WORLD stage 의 여는 컷이 그 세계의 **유일한 새 그림**이고, 뒤 stage 는 그것을
첨부해 "이것만 바꿔라"로 만든다(`sequence_render.reference_decision`). 그래서 여는 그림에
없는 물체는 **줄일 수도 키울 수도 없다** — 모델은 장면을 그대로 두고, 여러 컷이 같은 화면이 된다.

실측 사고(지시서 4baede40): 여는 컷4 가 세포 모형만 그렸는데 뒤 stage 가
SENESCENCE_MARKERS 를 SHRINK 하라고 했다. 컷 7·8·9 가 사실상 같은 화면으로 나왔다.

지금까지 있던 검사는 개체가 `entities` 에 **선언**됐는지만 봤다
(`vseq_state_entity_undeclared`). 여는 그림이 실제로 **그리는지**는 아무도 안 봤다.

★ 실측 히트율(저장된 photo 지시서 20건): NEW_WORLD stage 38개 중 9개(23.7%)·지시서 8/20.
  잡힌 9건을 눈으로 확인했고 명백한 오탐은 1건이었다. 그래서 **경고**다.
"""

from __future__ import annotations

from engine import config, photo_contract as pc


def _cut(no: int, prompt: str) -> dict:
    return {"cut_no": no, "visual_prompt": prompt, "estimated_sec": 4}


def _header(lead_prompt_world: str, entities: list[dict], later_muts: list[dict]) -> dict:
    return {"visual_sequences": [{
        "sequence_id": "SEQ2",
        "world": {"world_id": "W2", "style": lead_prompt_world},
        "entities": entities,
        "stages": [
            {"stage_id": "S4", "continuity_mode": "NEW_WORLD", "cut_refs": [4]},
            {"stage_id": "S5", "continuity_mode": "CONTINUE_WORLD", "cut_refs": [5],
             "continuity_from": "S4", "mutations": later_muts},
        ],
    }]}


CELL_ENTITIES = [
    {"entity_id": "CELL_MODEL_A",
     "visual_identity": "A detailed cutaway model of an aged animal cell."},
    {"entity_id": "SENESCENCE_MARKERS",
     "visual_identity": "Small, yellow, irregular resin pieces representing senescent cells."},
]
SHRINK_MARKERS = [{"entity_id": "SENESCENCE_MARKERS", "property": "size", "operation": "SHRINK"}]


def test_the_actual_accident_is_caught():
    """여는 컷4 가 노란 조각을 안 그렸는데 뒤 stage 가 그것을 줄이라고 한다."""
    header = _header("A plain studio tabletop holding cutaway teaching models of animal cells.",
                     CELL_ENTITIES, SHRINK_MARKERS)
    cuts = [_cut(4, "A cutaway teaching model of an aged animal cell on a plain studio tabletop,"
                    " showing visible signs of inflammation and cellular damage."),
            _cut(5, "The same model, markers receding.")]
    assert pc.unstaged_lead_entities(header, cuts) == ["S4(SENESCENCE_MARKERS)"]
    assert any(w.startswith("photo_lead_cut_missing_entity")
               for w in pc.evaluate(header, cuts, None)["warnings"])


def test_a_lead_that_actually_draws_the_pieces_passes():
    header = _header("A plain studio tabletop holding cutaway teaching models of animal cells.",
                     CELL_ENTITIES, SHRINK_MARKERS)
    cuts = [_cut(4, "A cutaway teaching model of an aged animal cell on a plain studio tabletop,"
                    " with many small yellow irregular resin pieces (senescence) crowded around"
                    " and inside it."),
            _cut(5, "The same model, fewer pieces.")]
    assert pc.unstaged_lead_entities(header, cuts) == []


def test_looks_can_stand_in_for_the_name():
    """이름을 안 써도 **생김새로** 무대에 서 있으면 통과한다 — 필요조건만 본다."""
    header = _header("A plain studio tabletop.", CELL_ENTITIES, SHRINK_MARKERS)
    cuts = [_cut(4, "A cell model surrounded by small yellow irregular resin pieces."),
            _cut(5, "Fewer pieces.")]
    assert pc.unstaged_lead_entities(header, cuts) == []


def test_one_accidental_word_is_not_enough():
    """★ 한 낱말 우연 일치는 근거로 치지 않는다(실측: 'senescent cells' 가 세계의
    'animal cells' 에 통과해 버렸다)."""
    header = _header("A plain studio tabletop holding models of animal cells.",
                     CELL_ENTITIES, SHRINK_MARKERS)
    cuts = [_cut(4, "A cutaway model of an aged animal cell on a tabletop."),
            _cut(5, "Fewer pieces.")]
    assert pc.unstaged_lead_entities(header, cuts) == ["S4(SENESCENCE_MARKERS)"]


def test_appear_is_exempt():
    """★ APPEAR 만은 없던 것을 등장시키는 연산이고, 코드가 그 외형을 참조 프롬프트에 실어 준다
    (`sequence_render.appearing_entity_prose`). 실험실 세계에 연구원 손이 뒤에서 등장하는 것은
    옳은 설계다 — 옳게 한 것을 벌하는 게이트는 무시당한다."""
    header = _header("A plain studio tabletop.", CELL_ENTITIES,
                     [{"entity_id": "SENESCENCE_MARKERS", "operation": "APPEAR"}])
    cuts = [_cut(4, "A cutaway model of an aged animal cell."), _cut(5, "Pieces appear.")]
    assert pc.unstaged_lead_entities(header, cuts) == []


def test_an_entity_that_appears_later_may_then_shrink():
    """★ "S5 에 등장 → S6 에 줄어듦"은 옳은 설계다(2026-09-11 리뷰). S6 의 참조 그림은 S5 의
    결과라 그 개체가 이미 있다. 여는 컷에 없다고 벌하면 안 된다."""
    header = {"visual_sequences": [{
        "sequence_id": "SEQ2", "world": {"world_id": "W2", "style": "A plain studio tabletop."},
        "entities": CELL_ENTITIES,
        "stages": [
            {"stage_id": "S4", "continuity_mode": "NEW_WORLD", "cut_refs": [4]},
            {"stage_id": "S5", "continuity_mode": "CONTINUE_WORLD", "cut_refs": [5],
             "continuity_from": "S4",
             "mutations": [{"entity_id": "SENESCENCE_MARKERS", "operation": "APPEAR"}]},
            {"stage_id": "S6", "continuity_mode": "CONTINUE_WORLD", "cut_refs": [6],
             "continuity_from": "S5", "mutations": SHRINK_MARKERS},
        ],
    }]}
    cuts = [_cut(4, "A cutaway model of an aged animal cell."), _cut(5, "Pieces appear."),
            _cut(6, "Pieces shrink.")]
    assert pc.unstaged_lead_entities(header, cuts) == []


def test_generic_only_entity_is_not_judged():
    """총칭뿐인 이름(THE_MODEL)은 특정할 낱말이 없다 — 판정 불가로 두고 넘어간다."""
    header = _header("A plain studio tabletop.",
                     [{"entity_id": "THE_MODEL", "visual_identity": "A model."}],
                     [{"entity_id": "THE_MODEL", "operation": "SHRINK"}])
    assert pc.unstaged_lead_entities(header, [_cut(4, "A rocket on a launch pad.")]) == []


def test_a_missing_lead_cut_is_not_judged():
    header = _header("A plain studio tabletop.", CELL_ENTITIES, SHRINK_MARKERS)
    assert pc.unstaged_lead_entities(header, [_cut(9, "Something else.")]) == []


def test_only_later_stages_count():
    """여는 stage 자기 변이는 보지 않는다 — 그 stage 의 컷들은 각자 새로 그려진다."""
    header = {"visual_sequences": [{
        "sequence_id": "SEQ2", "world": {"world_id": "W2", "style": "A tabletop."},
        "entities": CELL_ENTITIES,
        "stages": [{"stage_id": "S4", "continuity_mode": "NEW_WORLD", "cut_refs": [4],
                    "mutations": SHRINK_MARKERS}],
    }]}
    assert pc.unstaged_lead_entities(header, [_cut(4, "A cutaway model of a cell.")]) == []


def test_it_is_a_warning_not_a_block():
    """★ 실측 히트 23.7% 에 오탐이 섞여 있다. 차단으로 올리면 옳게 한 컷을 벌한다."""
    header = _header("A tabletop.", CELL_ENTITIES, SHRINK_MARKERS)
    res = pc.evaluate(header, [_cut(4, "A cutaway model of a cell.")], None)
    assert not any(r.startswith("photo_lead_cut_missing_entity") for r in res["block_reasons"])


def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setattr(config, "PHOTO_LEAD_STAGES_ENTITIES", False)
    header = _header("A tabletop.", CELL_ENTITIES, SHRINK_MARKERS)
    assert pc.unstaged_lead_entities(header, [_cut(4, "A cutaway model of a cell.")]) == []


def test_the_feedback_tells_the_model_what_to_draw():
    """게이트는 셋이 함께 있어야 한다: 검사 · 모델 고지 · 되먹임."""
    fb = pc.feedback_prompt([], ["photo_lead_cut_missing_entity:S4(SENESCENCE_MARKERS)"])
    assert "여는 컷" in fb
    assert "모양과 색" in fb
    # 코드 이름만 나열하고 끝나지 않는다 — 처방을 준 사유는 목록에서 뺀다.
    assert fb.count("photo_lead_cut_missing_entity") == 0, fb


def test_the_warning_triggers_one_regeneration():
    """경고인데도 재생성을 한 번 띄우는 사유여야 한다 — 안 그러면 말을 건네지 않는다."""
    assert "photo_lead_cut_missing_entity" in config.RETRYABLE_QUALITY_WARNINGS


# ─────────────────────────────────────────────────────────────
# `signs of` 계열 — 판정을 우회해 적는 말
# ─────────────────────────────────────────────────────────────
def test_signs_of_is_now_an_undrawable_judgement():
    """실측 사고의 그 문장. '염증의 징후'는 물체가 아니라서 아무 표지도 안 그려졌다."""
    header = {"visual_sequences": []}
    cuts = [_cut(4, "A cutaway teaching model of an aged animal cell on a plain studio tabletop,"
                    " showing visible signs of inflammation and cellular damage.")]
    _, warned = pc.style_vocabulary_hits(header, cuts)
    assert any("signs of" in w for w in warned)


def test_the_other_measured_hits_are_covered():
    """히트율 측정에서 실제로 나온 것들(2026-09-10, 237컷 중 23컷)."""
    for text, term in [
        ("two cages, suggesting a longer lifespan", "suggesting"),
        ("the lighting is dimmer, conveying a sense of caution", "sense of"),
        ("nodding slightly with a look of understanding", "look of"),
    ]:
        _, warned = pc.style_vocabulary_hits({"visual_sequences": []}, [_cut(1, text)])
        assert any(term in w for w in warned), text


def test_appearing_to_was_deliberately_left_out():
    """★ 실측 2건이 둘 다 정당했다 — 'a hand appearing to highlight a section' 은 그릴 수 있다."""
    _, warned = pc.style_vocabulary_hits(
        {"visual_sequences": []},
        [_cut(1, "a hand appearing to highlight a section of the documents")])
    assert warned == []


def test_it_stays_a_warning():
    """★ 판정 어휘는 기본이 경고다. 히트율을 재기 전에 차단으로 올리지 않는다."""
    cuts = [_cut(1, "showing visible signs of inflammation")]
    res = pc.evaluate({"visual_sequences": []}, cuts, None)
    assert any(w.startswith("photo_undrawable_difference") for w in res["warnings"])
    assert not any(r.startswith("photo_undrawable_difference") for r in res["block_reasons"])


# ─────────────────────────────────────────────────────────────
# 따옴표 라벨 — 소유격을 라벨로 읽지 않는가 (2026-09-11 실측 사고)
# ─────────────────────────────────────────────────────────────
def test_two_possessives_are_not_a_quoted_label():
    """실측 사고: 소유격 두 개 사이가 통째로 '라벨'로 읽혀 **지시서가 차단됐다.**

    "A close-up of a researcher's gloved hand … The mouse's fur is visible"
    → 잡힌 것: 's fur as the researcher'
    """
    cut = _cut(3, "A close-up of a researcher's gloved hand gently holding a single aged"
                  " mouse. The mouse's fur is visible in detail.")
    assert pc.quoted_label_cuts([cut]) == []


def test_real_labels_are_still_blocked():
    """오탐을 없애면서 진짜 라벨을 놓치면 안 된다 — 실측 264컷에서 34종을 그대로 잡는다."""
    for text in ("The left model represents 'Calorie Restriction'",
                 "a screen showing 'ad quality'",
                 "a paper marked 'arXiv'"):
        assert pc.quoted_label_cuts([_cut(8, text)]), text


def test_a_label_right_after_a_word_boundary_still_counts():
    """따옴표 앞이 공백·문장부호면 여전히 라벨이다(소유격만 뺐다)."""
    assert pc.quoted_label_cuts([_cut(8, "two dishes labelled 'Placebo' and 'Oxytocin'")])
