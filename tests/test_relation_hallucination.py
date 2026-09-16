"""관계 환각 — 원문에 없는 관계를 화면이 지어내는 컷 (리뷰 §14).

★ 무엇을 지키는가: 이 게이트의 값어치는 **어휘가 아니라 대조**에 있다. 어휘 목록만으로
  막으면 논문이 실제로 말하는 관계("수용체에 결합한다")까지 벌하고, 그러면 운영자가
  게이트를 무시하기 시작한다(리뷰 §17). 그래서 아래 테스트의 절반은 통과 케이스다.
"""

from __future__ import annotations

from engine.directive import ungrounded_relation_cuts as check

SOURCE = ("Oxytocin binds to receptors in the amygdala. "
          "Trust ratings increased in the treatment group.")


def cut(no: int, **f):
    return {"cut_no": no, **f}


# ── 잡아야 하는 것 ────────────────────────────────────────────

def test_catches_a_relation_the_source_never_claims():
    """골든B 컷14 의 실제 실패 — '정렬된다' 는 원문에 없는 관계다."""
    cuts = [cut(14, visual_prompt="다른 궤도들이 기준 궤도에 맞춰 정렬된다")]
    assert check(cuts, "The probe orbits the moon.") == ["cut_relation_not_in_source:14"]


def test_catches_invented_causation():
    cuts = [cut(2, motion_prompt="the hormone triggers a cascade of neural firing")]
    assert check(cuts, SOURCE) == ["cut_relation_not_in_source:2"]


def test_lists_every_offending_cut():
    cuts = [cut(1, visual_prompt="molecules align into a lattice"),
            cut(2, visual_prompt="a calm laboratory bench"),
            cut(5, state_change="신호가 억제된다")]
    assert check(cuts, SOURCE) == ["cut_relation_not_in_source:1,5"]


# ── 잡으면 안 되는 것 (오탐 방지 — 여기가 이 게이트의 값어치다) ──

def test_a_relation_the_source_states_is_fine():
    """원문이 'binds to receptors' 라고 말한다 — 화면이 그려도 된다."""
    cuts = [cut(3, visual_prompt="oxytocin binds to a receptor on the cell surface")]
    assert check(cuts, SOURCE) == []


def test_a_relation_the_fact_sheet_pays_for_is_fine():
    """우리가 이미 검증한 주장이 그 관계를 말하면 그것도 지불된 근거다."""
    fs = {"claims": [{"id": "C1", "text": "옥시토신이 편도체 활동을 억제한다"}]}
    cuts = [cut(4, state_change="편도체 활동이 억제된다")]
    assert check(cuts, "Oxytocin was administered.", fs) == []


def test_a_cut_with_no_relation_language_is_fine():
    cuts = [cut(1, visual_prompt="a wide shot of the laboratory at dusk")]
    assert check(cuts, SOURCE) == []


def test_no_source_means_no_judgement():
    """대조할 원문이 없으면 판정하지 않는다 — 확보 실패를 위반으로 기록하지 않는다."""
    cuts = [cut(1, visual_prompt="the orbits align perfectly")]
    assert check(cuts, "") == []
    assert check(cuts, "", {"claims": []}) == []


def test_empty_cuts_are_handled():
    assert check([], SOURCE) == []


# ── 설계 계약 ─────────────────────────────────────────────────

def test_the_vocabulary_only_chooses_where_to_look():
    """판정은 대조가 한다 — 같은 낱말이 원문에 있으면 통과, 없으면 걸린다."""
    cuts = [cut(1, visual_prompt="the signal is amplified")]
    assert check(cuts, "Amplified responses were observed.") == []
    assert check(cuts, "Responses were observed.") == ["cut_relation_not_in_source:1"]


def test_it_warns_and_does_not_block():
    from engine import photo_contract, visual_sequence_contract

    code = "cut_relation_not_in_source"
    assert code not in photo_contract.BLOCK_REASONS
    assert code not in visual_sequence_contract.BLOCK_REASONS


def test_the_warning_reaches_the_directive_header():
    """만들어 놓고 한쪽만 연결하지 않는다."""
    import inspect

    from engine import directive

    src = inspect.getsource(directive)
    assert "ungrounded_relation_cuts(cuts, source_text, fact_sheet)" in src
    assert "*relation_warnings," in src


def test_the_terms_live_in_config():
    """CLAUDE.md 규약 — 어휘·상수는 config 단일 출처."""
    import inspect

    from engine import config, directive

    assert "config.RELATION_TERMS" in inspect.getsource(directive.ungrounded_relation_cuts)
    assert len(config.RELATION_TERMS) > 10
