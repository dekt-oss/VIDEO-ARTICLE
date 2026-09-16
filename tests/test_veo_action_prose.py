"""Veo 발주 문장: 행동 먼저·카메라 한 벌 (config.VEO_BEAT_ACTION_PROSE, 2026-09-14 부터 기본 on).

A/B 1쌍(2026-09-14, 0e808e83 컷10, $0.40): 옛 문장은 중간에 종이가 폭발하듯 흩날리고 얼굴 초근접으로
장면을 떠났고, 새 문장은 표정 변화·서류 더미 성장이 장면 안에서 보였다. 대신 "symbolizing …"
구절이 아이콘 배지로 그려졌다 → 뜻 설명 구절을 뺀다.
"""
from engine import config
from engine import temporal_plan as tp
from engine.providers import video

BEATS = [{"beat": 1, "t0": 0.0, "t1": 4.0, "entity_id": "PERSON_WORKING", "mutation": "TRANSFORM", "camera": "TRACK"},
         {"beat": 2, "t0": 4.0, "t1": 8.0, "entity_id": "STACK_OF_PAPERS", "mutation": "GROW", "camera": "DOLLY_IN"}]
MUTS = [{"entity_id": "PERSON_WORKING", "operation": "TRANSFORM",
         "result_state": "The person at the desk shifts from thoughtful to confident, with a slight smile."},
        {"entity_id": "STACK_OF_PAPERS", "operation": "GROW",
         "result_state": "One stack of papers visibly grows taller, symbolizing accumulating life outcomes."}]
CUT = {"cut_no": 10, "visual_role": "REALITY", "temporal_plan": BEATS, "stage_mutations": MUTS,
       "motion_prompt": "The camera tracks from the growing stack of papers to the person's face, "
                        "as their expression changes to confident."}


def test_action_prose_carries_the_declared_action_not_a_generic_verb():
    p = tp.action_prose(BEATS, MUTS)
    assert "shifts from thoughtful to confident" in p
    assert "changes form" not in p
    assert "symboliz" not in p and "life outcomes" not in p


def test_sweep_defect_classes_never_reach_the_video_prompt():
    """저장 지시서 251컷 스윕에서 나온 부류 — 한 번에 막는다(유료 반복 확인 없이)."""
    bad = [
        ("GAUGE", "GROW", "The ad quality gauge visibly rises"),                 # 화면 계기
        ("ICON", "APPEAR", "Small character icons stream in from the edges"),    # 아이콘
        ("THUMBS", "GROW", "A rapid cascade of 7,266 ad thumbnails"),            # 숫자
        ("CARD", "HIGHLIGHT", "The 'good match' ad card brightens"),              # 따옴표 라벨
        ("LAYOUT", "APPEAR", "An ad layout on the left side of a split screen"),  # 화면분할
    ]
    for eid, op, rs in bad:
        p = tp.action_prose([{"beat": 1, "t0": 0.0, "t1": 8.0, "entity_id": eid, "mutation": op,
                              "camera": "DOLLY_IN"}],
                            [{"entity_id": eid, "operation": op, "result_state": rs}])
        assert rs.lower()[:20] not in p.lower(), (rs, p)
    for clause in ("represented by a larger cluster", "indicated by a subtle jolt",
                   "emphasizing the comparison", "creating a sense of approach"):
        assert "represent" not in tp.clean_action(f"The pile grows, {clause}")
        assert tp.clean_action(f"The pile grows, {clause}") == "The pile grows"


def test_korean_or_graphic_entity_ids_are_not_named():
    assert tp.entity_name("광고_품질_게이지") == ""
    assert tp.entity_name("SPECTRAL_GRAPH") == ""
    assert tp.entity_name("STACK_OF_PAPERS") == "stack of papers"
    old = tp.prose([{"beat": 1, "t0": 0.0, "t1": 4.0, "entity_id": "광고_품질_게이지",
                     "mutation": "HIGHLIGHT", "camera": "HOLD"}])
    assert "광고" not in old and "as it stands out" in old


def test_operation_mismatch_still_uses_the_declared_action():
    """129비트가 연산만 달라 일반 동사로 떨어졌다 — 같은 개체의 선언을 쓴다."""
    p = tp.action_prose([{"beat": 1, "t0": 0.0, "t1": 8.0, "entity_id": "PERSON_WORKING",
                          "mutation": "MOVE", "camera": "TRACK"}], MUTS)
    assert "shifts from thoughtful to confident" in p


def test_camera_clauses_are_stripped_from_motion_prompt():
    assert tp.strip_camera_clauses(CUT["motion_prompt"]) == "their expression changes to confident"
    assert tp.strip_camera_clauses("A slow dolly-in towards the photos.") == ""


def test_flag_off_keeps_the_old_prompt(monkeypatch):
    monkeypatch.setattr(config, "VEO_BEAT_ACTION_PROSE", False)
    p = video.build_motion_prompt(dict(CUT), {})
    assert "shot sequence within the clip" in p and "The camera tracks" in p


def test_flag_on_has_one_camera_plan(monkeypatch):
    monkeypatch.setattr(config, "VEO_BEAT_ACTION_PROSE", True)
    p = video.build_motion_prompt(dict(CUT), {})
    assert "what happens in the clip" in p
    assert "The camera tracks" not in p
    assert p.index("shifts from thoughtful") < p.index("the camera moves laterally")
