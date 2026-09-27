"""세계(world)는 **한 장소**다 — 둘을 적으면 모든 컷 그림이 콜라주가 된다 (2026-09-27 실측).

삼성전자 리포트 렌더(지시서 6b40e2f5): world 가 "Industrial semiconductor cleanroom manufacturing
facilities and modern corporate analysis environments". 이 문장은 시퀀스 **모든 컷 그림 앞에** 붙고,
그림 10장 중 7장이 공장|사무실(|컷 장면) 칸 나눔으로 나왔다(9컷 = 공장|사무실|크레인).
저장 세계 130개 중 Jev 가 3개를 0.91~0.97 로 짚었고 나머지는 전부 0.5 미만이었다.
"""

from __future__ import annotations

from engine import config, decide, directive as dv, photo_contract as pc, still_check
from tests.test_directive_code_repairs import _with_sequences
from tests.test_photo_contract import _raw


def _directive(world_style):
    raw = _with_sequences(_raw("좋은 훅"))
    for s in raw["visual_sequences"]:
        s["world"] = {"world_id": "W", "style": world_style, "lighting": "", "background": ""}
    return {"visual_sequences": raw["visual_sequences"], "hook_ko": "좋은 훅"}, raw["cuts"]


def _judge(monkeypatch, p):
    monkeypatch.setattr(decide, "enabled", lambda: True)
    for name in ("scene_answers", "number_as_objects", "cause_shown", "components_recognizable"):
        monkeypatch.setattr(decide, name, lambda *a, **k: None)
    monkeypatch.setattr(decide, "world_multi_place", lambda w: p)


def test_a_two_place_world_is_warned(monkeypatch):
    header, cuts = _directive("A cleanroom factory and a corporate analysis office")
    _judge(monkeypatch, 0.91)
    got = pc.evaluate(header, cuts, None)
    assert any(w.startswith("photo_world_multi_place") for w in got["warnings"]), got["warnings"]
    assert not any(b.startswith("photo_world_multi_place") for b in got["block_reasons"])


def test_one_place_passes(monkeypatch):
    header, cuts = _directive("A cleanroom with wafer carriers on a ceiling track")
    _judge(monkeypatch, 0.1)
    assert not any(w.startswith("photo_world_multi_place") for w in pc.evaluate(header, cuts, None)["warnings"])


def test_notice_check_and_feedback():
    assert "photo_world_multi_place" in dv.SEQUENCE_SCHEMA
    assert "photo_world_multi_place" in config.RETRYABLE_QUALITY_WARNINGS
    fix = pc.feedback_prompt([], ["photo_world_multi_place:SEQ2"])
    assert "한 곳" in fix and "시퀀스를 나눠" in fix


def test_a_collage_still_fails_the_pre_clip_check():
    collage = {"text_in_image": False, "subject_present": True, "split_panels": True, "reason": "3 strips"}
    cut = {"visual_prompt": "A construction site with tower cranes under an overcast sky."}
    assert still_check.failed(still_check.check("x.png", cut, lambda s, u, p: collage))


def test_a_window_in_one_scene_is_not_a_collage_by_itself():
    ok = {"text_in_image": False, "subject_present": True, "split_panels": False, "reason": "window"}
    cut = {"visual_prompt": "Engineers behind an inspection window examine a wafer."}
    assert not still_check.failed(still_check.check("x.png", cut, lambda s, u, p: ok))
