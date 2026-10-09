"""화면 품질 Jev 검사(2026-10-08 운영자: 이해도·흥미·호감, 카메라만 금지, 끊기지 않게). 가짜 Jev 만."""

from __future__ import annotations

from engine import config, decide
from engine import photo_contract as pc


def _cuts():
    return [{"cut_no": i, "visual_role": "REALITY", "narration_ko": f"문장 {i}", "staging_ko": f"장면 {i}",
             "visual_prompt": f"scene {i}", "motion_prompt": "slow push-in" if i in (1, 4) else ""}
            for i in range(1, 7)]


def _on(monkeypatch, scores):
    monkeypatch.setattr(decide, "enabled", lambda: True)

    def ask(state, questions, **kw):
        return {k: scores(k, state) for k in questions}
    monkeypatch.setattr(decide, "ask", ask)


def test_dull_unclear_and_camera_only_cuts_become_retryable_warnings(monkeypatch):
    def scores(k, state):
        if k == "engaging":
            return 0.2 if "문장 2" in state else 0.6
        if k == "understand":
            return 0.1 if ("문장 3" in state or "문장 1" in state) else 0.7
        if k == "camera_only":
            return 0.93
        return 0.5
    _on(monkeypatch, scores)
    got = pc.evaluate({"hook_ko": "훅"}, _cuts(), None)
    w = got["warnings"]
    assert "photo_scene_dull:2" in w
    assert "photo_scene_unclear:3" in w                 # 컷1(훅)은 이해도에서 뺀다
    assert "photo_motion_camera_only:1,4" in w          # motion 이 있는 컷만 묻는다
    for code in ("photo_scene_dull", "photo_scene_unclear", "photo_motion_camera_only", "photo_stages_fragmented"):
        assert code in config.RETRYABLE_QUALITY_WARNINGS and code in pc.WARNING_REASONS
    fix = pc.feedback_prompt([], w)
    assert "주인공이 무언가를 하게" in fix and "카메라만 움직이는" in fix


def test_fragmented_stages_are_measured_like_the_renderer(monkeypatch):
    monkeypatch.setattr(decide, "enabled", lambda: False)
    cuts = _cuts()
    for c in cuts:                                      # 컷마다 stage 하나 → 6컷 6영상
        c["resolved_visual_plan"] = {"stage_ref": f"S{c['cut_no']}"}
    assert any(x.startswith("photo_stages_fragmented") for x in pc.evaluate({"hook_ko": "훅"}, cuts, None)["warnings"])
    for c in cuts:                                      # 두 stage 로 묶으면 통과
        c["resolved_visual_plan"] = {"stage_ref": "S1" if c["cut_no"] <= 3 else "S2"}
    assert not any(x.startswith("photo_stages_fragmented")
                   for x in pc.evaluate({"hook_ko": "훅"}, cuts, None)["warnings"])


def test_multi_cut_stage_without_varied_beats_is_flagged(monkeypatch):
    monkeypatch.setattr(decide, "enabled", lambda: False)
    cuts = _cuts()
    for c in cuts:
        c["resolved_visual_plan"] = {"stage_ref": "S1" if c["cut_no"] <= 3 else "S2"}
    cuts[3]["temporal_plan"] = [{"camera": "PAN"}, {"camera": "DOLLY_IN"}, {"camera": "TRACK"}]
    header = {"hook_ko": "훅", "version_type": "photo",
              "visual_sequences": [{"sequence_id": "Q", "stages": [{"stage_id": "S1", "cut_refs": [1, 2, 3]},
                                                                    {"stage_id": "S2", "cut_refs": [4, 5, 6]}]}]}
    w = pc.evaluate(header, cuts, None)["warnings"]
    assert "photo_consecutive_same_view:1" in w          # S1 첫 컷(1)은 비트가 없다 / S2 첫 컷(4)은 통과
    assert "photo_consecutive_same_view" in config.RETRYABLE_QUALITY_WARNINGS


def test_photo_image_prompt_asks_for_one_frame():
    from engine.providers import image
    p = image.build_image_prompt({"cut_no": 1, "visual_role": "MECHANISM", "visual_prompt": "cells"},
                                 {"version_type": "photo"}) if hasattr(image, "build_image_prompt") else None
    if p is None:
        import inspect
        assert "PHOTO_SINGLE_FRAME_CLAUSE" in inspect.getsource(image)
    else:
        assert "no panels" in p


def test_cell_diagram_images_get_cell_anatomy_and_one_frame():
    import inspect
    from engine.providers import image
    assert image._CELL_WORDS.search("amber-highlighted fibroblast cells extend protrusions")
    assert not image._CELL_WORDS.search("an excellent cancellation")
    assert image._CELL_ANATOMY_WORDS.search("cells with round nuclei")
    src = inspect.getsource(image)
    assert "PHOTO_CELL_ANATOMY_CLAUSE" in src and "PHOTO_SINGLE_FRAME_CLAUSE" in src
    assert "nucleus" in config.PHOTO_CELL_ANATOMY_CLAUSE and "no panels" in config.PHOTO_SINGLE_FRAME_CLAUSE


def test_a_new_sequence_in_an_already_drawn_world_references_that_picture(tmp_path):
    from engine import sequence_render
    header = {"version_type": "photo", "visual_sequences": [
        {"sequence_id": "SEQ0", "world": {"world_id": "CELL"}, "stages": [{"stage_id": "S0", "cut_refs": [1], "continuity_mode": "NEW_WORLD"}]},
        {"sequence_id": "SEQ1", "world": {"world_id": "LAB"}, "stages": [{"stage_id": "S1", "cut_refs": [2], "continuity_mode": "NEW_WORLD"}]},
        {"sequence_id": "SEQ2", "world": {"world_id": "CELL"}, "stages": [{"stage_id": "S3", "cut_refs": [7], "continuity_mode": "NEW_WORLD"}]}]}
    pic = tmp_path / "s0.png"
    pic.write_bytes(b"p")
    assets = {"S0": str(pic), "S1": str(tmp_path / "lab.png")}
    got = sequence_render.reference_decision({"cut_no": 7}, header, assets)
    assert got["kind"] == "reference" and got["ref_stage"] == "S0" and got.get("same_world")
    lab = sequence_render.reference_decision({"cut_no": 2}, header, {"S0": str(pic)})
    assert lab["kind"] == "new_world"                      # 다른 세계는 새로 그린다


def test_photo_never_builds_shots_from_stills_by_default():
    """운영자 2026-10-09: 사진으로 영상 구성 금지 — 분할 스틸·영상 실패 사진 대체 둘 다 기본 꺼짐."""
    assert config.MECHANISM_SPLIT_BEFORE_AFTER is False
    assert config.PHOTO_STILL_FALLBACK is False
