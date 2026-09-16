"""운영자 실측 세 가지(2026-09-14, 성격 유전 후반부 렌더)를 못박는다.

① "결론이나 마무리가 좀 이상한데?" — 결론 컷이 앞 stage 의 지도 영상에서 잘려 자기 그림이
   한 번도 안 그려졌다. 최근 16편 중 13편이 마지막 컷을 그렇게 만들고 있었다.
② "세계지도에서 서구에 한정된다면서 전세계에 찍혀 있고 표시도 엉망" — 생성 모델은 지리를 모르고
   지명을 지어낸다("gene marker", "italy"). 저장 지시서 333컷 중 8컷이 지도·지구본(오탐 0).
③ "시퀀스의 배경이 뇌의 이미지로 너무 한정" — 13컷 전부 실험실 탁자 한 세계였다.
"""
import pathlib

import pytest

from engine import config
from engine import photo_contract as pc
from engine import stage_render as sr

DIRECTIVE_SRC = (pathlib.Path(__file__).resolve().parents[1] / "engine" / "directive.py").read_text(encoding="utf-8")


def _cut(no, stage, base="MECHANISM_SEQUENCE", connective=False):
    reasons = ["connective_in_world"] if connective else ["in_visual_sequence"]
    return {"cut_no": no, "estimated_sec": 5,
            "resolved_visual_plan": {"stage_ref": stage, "base": base, "reasons": reasons}}


def _groups(cuts):
    return [[cuts[i]["cut_no"] for i in g["indexes"]] for g in sr.group_cuts(cuts)]


# ── ① 혼자 서는 컷 ───────────────────────────────────────────
def test_the_real_failure_the_ending_no_longer_rides_the_map_stage():
    """실측 그대로: 컷 11(연결)·12(기전)·13(결론)이 S9 한 묶음이었다."""
    cuts = [_cut(10, "S8"),
            _cut(11, "S9", base="OVERLAY", connective=True),
            _cut(12, "S9"),
            _cut(13, "S9", base="REALITY", connective=True)]
    assert _groups(cuts) == [[10], [11], [12], [13]]


def test_mechanism_cuts_in_one_stage_still_share_one_continuous_video():
    """시퀀스 렌더의 본체는 그대로다 — 기전 컷끼리는 연속 영상 한 덩어리."""
    cuts = [_cut(1, "S1"), _cut(2, "S1"), _cut(3, "S1"), _cut(4, "S2")]
    assert _groups(cuts) == [[1, 2, 3], [4]]


def test_the_final_cut_gets_its_own_clip_even_when_it_is_mechanism():
    cuts = [_cut(1, "S1"), _cut(2, "S1"), _cut(3, "S1")]
    assert _groups(cuts) == [[1, 2], [3]]


def test_a_cut_after_a_solo_cut_does_not_merge_into_it():
    """혼자 선 컷 뒤에 같은 stage 가 이어져도 그 컷에 붙이지 않는다(그 컷의 그림은 다른 장면이다)."""
    cuts = [_cut(1, "S1", base="REALITY", connective=True), _cut(2, "S1"), _cut(3, "S1"), _cut(4, "S2")]
    assert _groups(cuts) == [[1], [2, 3], [4]]


def test_the_switches_restore_the_old_grouping(monkeypatch):
    monkeypatch.setattr(config, "STAGE_FINAL_CUT_OWN_CLIP", False)
    monkeypatch.setattr(config, "STAGE_CONNECTIVE_OWN_CLIP", False)
    cuts = [_cut(11, "S9", base="OVERLAY", connective=True), _cut(12, "S9"),
            _cut(13, "S9", base="REALITY", connective=True)]
    assert _groups(cuts) == [[11, 12, 13]]


def test_the_group_contract_keys_are_unchanged():
    g = sr.group_cuts([_cut(1, "S1"), _cut(2, "S1", base="REALITY", connective=True)])
    assert all(set(x) == {"stage_id", "indexes"} for x in g)


# ── ② 지도·지구본 ────────────────────────────────────────────
@pytest.mark.parametrize("prompt", [
    "A world map with Western countries highlighted, overlaid with a subtle grid.",
    "A large, translucent digital globe, with only the Western geography lit.",
    "Researchers in front of a large screen showing a glowing world map.",
    "A political map of Europe on the wall.",
    "a map of the world with pins",
])
def test_maps_and_globes_are_requests_to_draw_geography(prompt):
    assert pc._FORBIDDEN_SCREEN.search(prompt), prompt


@pytest.mark.parametrize("prompt", [
    "The highlighted region of the prefrontal cortex glows faintly.",   # 뇌 도해의 '강조된 영역'
    "A glowing ring around its axis.",
    "A gene map of variants along the DNA helix model.",                # 유전자 지도는 지리가 아니다
])
def test_brain_regions_and_gene_maps_are_not_geography(prompt):
    assert not pc._FORBIDDEN_SCREEN.search(prompt), prompt


def test_gate_prompt_and_feedback_all_name_the_map_rule():
    """검사만 있고 고지·처방이 없으면 게이트가 아니라 함정이다(skill: gate-prompt-feedback-parity)."""
    assert "지도·지구본도 그리지 마라" in DIRECTIVE_SRC
    fb = pc.feedback_prompt(["photo_forbidden_screen_request:11"])
    assert "지도" in fb and "물체의 양" in fb


# ── ③ 결과·한계·결론은 실험실 밖 ─────────────────────────────
def test_the_one_world_rule_is_scoped_to_the_mechanism_part():
    assert "결과·한계·결론은 실험실 밖으로 나가라" in DIRECTIVE_SRC
    assert "기전 구간은 하나의 세계, 결과·결론 구간은 사람의 세계" in DIRECTIVE_SRC


def test_two_worlds_in_an_episode_do_not_trip_the_churn_warning():
    """기전 세계 + 사람 세계 = 80초에 2개(분당 1.5) — 경고 문턱(분당 2) 아래여야 권고와 경고가 싸우지 않는다."""
    assert 2 / (80 / 60) <= config.PHOTO_MAX_WORLDS_PER_MIN
