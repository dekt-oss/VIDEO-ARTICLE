"""allow_connective stage 는 진행 검사에서 빠진다 (2026-09-14 실측).

지시서 프롬프트는 "주장을 지불하지 않는 컷(전환·출처·CTA)을 stage 에 넣으면 allow_connective 를
true 로 하라"고 가르치는데, 계약 검사는 그 표시를 보지 않고 변이를 요구했다 — 시킨 대로 하면
막히는 함정이었다. 최근 지시서의 connective stage 27개 중 4개(15%)가 그렇게 차단됐다.
"""
from engine import visual_sequence as vs
from engine import visual_sequence_contract as vsc


def _seq(stage2_connective: bool) -> list:
    raw = [{
        "sequence_id": "SEQ1", "sequence_role": "RESULT_SEQUENCE",
        "world": {"world_id": "LAB"},
        "entities": [{"entity_id": "DNA"}],
        "stages": [
            {"stage_id": "S1", "cut_refs": [1], "continuity_mode": "NEW_WORLD",
             "observable_change": "DNA appears",
             "mutations": [{"entity_id": "DNA", "property": "state", "operation": "APPEAR",
                            "result_state": "a DNA model", "visible_change": True}]},
            {"stage_id": "S2", "cut_refs": [2], "continuity_mode": "CONTINUE_WORLD",
             "continuity_from": "S1", "allow_connective": stage2_connective,
             "observable_change": "", "mutations": []},
        ],
    }]
    return vs.normalize_all(raw)


def _codes(res) -> set:
    return {b.split(":", 1)[0] + ":" + b.split(":", 1)[1] for b in res["block_reasons"]}


def test_a_connective_source_stage_is_not_blocked_for_having_no_mutation():
    res = vsc.evaluate(_seq(stage2_connective=True))
    assert not any("SEQ1/S2" in b for b in res["block_reasons"]), res["block_reasons"]


def test_the_same_stage_without_the_flag_is_still_blocked():
    """면제는 표시가 있을 때만이다 — 표시 없이 변이가 비면 여전히 진행이 아니다."""
    res = vsc.evaluate(_seq(stage2_connective=False))
    assert any(b.startswith("vseq_no_actual_mutation:SEQ1/S2") for b in res["block_reasons"]), res
