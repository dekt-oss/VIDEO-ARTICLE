"""`stylized` 는 코드가 지운다 (2026-09-11 운영자 지시).

계기: 성격 유전 논문 지시서가 재생성 1회를 거치고도 컷 10·11 에 `stylized` 가 남아
`photo_style_word_in_prompt` 로 승인이 막혔다. 형용사라 지워도 장면은 남는다.
나머지 화풍 선언 어휘(3D render·illustration …)는 여전히 게이트가 돌려보낸다.
"""
import pytest

from engine import config
from engine import photo_contract as pc


def _cut(no: int, prompt: str, motion: str = "") -> dict:
    return {"cut_no": no, "visual_role": "REALITY", "visual_prompt": prompt,
            "motion_prompt": motion, "estimated_sec": 4}


@pytest.mark.parametrize("src, want", [
    ("A stylized DNA helix on a steel bench.", "A DNA helix on a steel bench."),
    ("A cage on a bench, stylized, no text", "A cage on a bench, no text"),
    ("Stylized brain model on a tabletop.", "Brain model on a tabletop."),
    ("A stylized 3D render of a brain on a desk.", "A brain on a desk."),
])
def test_stylized_is_removed_and_the_scene_stays(src: str, want: str):
    assert pc.strip_style_words(src) == want


def test_normalize_clears_the_gate_for_stylized_in_cuts_and_world():
    header = {"visual_sequences": [{"sequence_id": "S1", "world": {
        "world_id": "W1", "style": "stylized lab", "lighting": "", "background": ""}}]}
    cuts = [_cut(10, "A stylized family at a table."), _cut(11, "a desk", "slow push, stylized")]
    touched = pc.normalize_style_words(header, cuts)
    assert touched == ["세계 W1.style", "컷10", "컷11"], touched
    assert pc.style_vocabulary_hits(header, cuts)[0] == []
    assert "family at a table" in cuts[0]["visual_prompt"]


@pytest.mark.parametrize("word", ["3D render", "illustration", "cel shading", "anime"])
def test_other_style_words_are_still_blocked(word: str):
    """예외는 stylized 하나다. 명사형 화풍 선언은 장면 구상 자체라 돌려보낸다."""
    cuts = [_cut(3, f"A cage on a bench, {word}, no text")]
    pc.normalize_style_words({}, cuts)
    assert any("컷3" in b for b in pc.style_vocabulary_hits({}, cuts)[0])


def test_untouched_prompt_is_returned_verbatim():
    src = "Two cages  side by side. No on-screen text."
    assert pc.strip_style_words(src) == src


def test_the_gate_list_still_names_stylized():
    """치환이 놓친 변형(예: 'stylised')이 들어오면 게이트가 계속 잡아야 한다."""
    assert "stylized" in config.PHOTO_RENDER_STYLE_TERMS


def test_directive_wires_the_rewrite_before_the_gate():
    from engine import directive as dv
    src = open(dv.__file__, encoding="utf-8").read()
    i_fix = src.index("photo_contract.normalize_style_words(header, cuts)")
    i_gate = src.index("photo_gate = photo_contract.evaluate(header, cuts, fact_sheet)")
    assert i_fix < i_gate, "게이트보다 먼저 고쳐야 차단이 풀린다"
