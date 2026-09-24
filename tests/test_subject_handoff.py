"""주인공이 바뀌는 stage 는 앞 그림을 참조하지 않는다 (2026-09-24 렌더 실측).

무엇이 있었나
------------
운영자가 본 2차 렌더(docs/preview-2026-09-24/620e66be): "부유식 데이터센터" 컷에 **엔진 단면이
그대로** 있었고, 전·후 분할로 같은 엔진 그림 두 장이 위·아래로 붙어 있었다.

원인은 이어받기의 구현이다. CONTINUE_WORLD stage 는 앞 stage 의 그림을 첨부해 "이것만
바꿔라"로 만든다. 바지선(BARGE_PLATFORM)은 앞 그림에 없는 새 주인공인데, 첨부된 엔진 그림이
이겼다. 지시서는 그 사실을 이미 선언하고 있었다 — S3 의 entity_refs 는 [ENGINE_BLOCK],
S4 는 [BARGE_PLATFORM]. 교집합이 없다.

"세계가 하나"는 같은 장소·같은 재질이지 같은 픽셀이 아니다. 참고 영상(시화호)은 댐 → 유리병
→ 계기판 → 돌덩이로 주인공이 바뀌면서 한 세계다. 주인공이 바뀌면 세계 선언만 물려받고
그림은 새로 그린다. 그리고 "전"이 없으니 전·후 분할도 하지 않는다.
"""

from __future__ import annotations

from engine import config, render, sequence_render as sr, visual_sequence as vs
from tests.test_sequence_render import _header, _stage


def _mech_cut(no):
    return {"cut_no": no, "visual_role": "MECHANISM", "visual_prompt": "x"}


# ── 판정 함수 ──────────────────────────────────────────────────
def test_disjoint_entities_are_a_handoff():
    assert vs.subject_handoff({"entity_refs": ["BARGE"]}, {"entity_refs": ["ENGINE"]})


def test_a_shared_entity_is_not_a_handoff():
    assert not vs.subject_handoff({"entity_refs": ["ENGINE", "RACK"]}, {"entity_refs": ["ENGINE"]})


def test_missing_refs_fall_back_to_the_old_path():
    """개체를 안 적은 지시서(옛 것)는 종전대로 참조한다 — 판정할 데이터가 없으면 바꾸지 않는다."""
    assert not vs.subject_handoff({"entity_refs": ["BARGE"]}, {})
    assert not vs.subject_handoff({}, {"entity_refs": ["ENGINE"]})
    assert not vs.subject_handoff(None, None)


# ── 렌더 결정 ──────────────────────────────────────────────────
def test_a_handoff_stage_is_drawn_fresh_not_from_the_previous_image():
    """★ 실측 그 자리: 엔진 → 바지선."""
    header = _header(_stage("S3", entity_refs=["ENGINE"]),
                     _stage("S4", "CONTINUE_WORLD", "S3", cuts=(2,), entity_refs=["BARGE"]))
    got = sr.reference_decision({"cut_no": 2}, header, {"S3": "/tmp/s3.png"})
    assert got["kind"] == "new_world", got
    assert got.get("handoff") is True
    assert got["degraded"] == [], "의도한 결정이지 성능 저하가 아니다"


def test_the_same_subject_still_chains_from_the_previous_image():
    """회귀 방지 — 같은 물건이 바뀌는 stage 는 v3 그대로 참조한다."""
    header = _header(_stage("S1", entity_refs=["A"]),
                     _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,), entity_refs=["A"]))
    got = sr.reference_decision({"cut_no": 2}, header, {"S1": "/tmp/s1.png"})
    assert got["kind"] == "reference"


# ── 전·후 분할 ─────────────────────────────────────────────────
def test_a_handoff_stage_is_not_split_into_before_and_after(monkeypatch):
    """'전'이 없는데 분할하면 같은 그림 두 장이 붙는다(실측)."""
    monkeypatch.setattr(config, "MECHANISM_SPLIT_BEFORE_AFTER", True)
    grow = [{"entity_id": "BARGE", "operation": "GROW", "visible_change": True,
             "result_state": "bigger"}]
    header = _header(_stage("S3", entity_refs=["ENGINE"]),
                     _stage("S4", "CONTINUE_WORLD", "S3", cuts=(2,),
                            entity_refs=["BARGE"], mutations=grow))
    assert render.split_before_after_applies(_mech_cut(2), header) is False


def test_a_real_state_change_of_the_same_subject_is_still_split(monkeypatch):
    monkeypatch.setattr(config, "MECHANISM_SPLIT_BEFORE_AFTER", True)
    grow = [{"entity_id": "A", "operation": "GROW", "visible_change": True,
             "result_state": "bigger"}]
    header = _header(_stage("S1", entity_refs=["A"]),
                     _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,),
                            entity_refs=["A"], mutations=grow))
    assert render.split_before_after_applies(_mech_cut(2), header) is True
