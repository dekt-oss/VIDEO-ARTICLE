"""장면 경계 크로스페이드(2026-10-09 운영자 "뚝뚝 끊긴다"). 길이·음성 유지, 같은 영상 구간끼리는 하드컷 그대로."""

from __future__ import annotations

from engine import assemble, config, stage_render


def _cut(no, stage):
    return {"cut_no": no, "resolved_visual_plan": {"stage_ref": stage}}


def test_fade_only_where_the_stage_changes(monkeypatch):
    monkeypatch.setattr(config, "STAGE_TRANSITION_SEC", 0.5)
    monkeypatch.setattr(config, "STAGE_FINAL_CUT_OWN_CLIP", False)
    cuts = [_cut(1, "S0"), _cut(2, "S1"), _cut(3, "S1"), _cut(4, "S2")]
    assert stage_render.transitions(cuts) == [0.5, 0.0, 0.5]
    monkeypatch.setattr(config, "STAGE_TRANSITION_SEC", 0.0)
    assert stage_render.transitions(cuts) == [0.0, 0.0, 0.0]


def test_crossfade_keeps_total_length_and_original_audio():
    argv = assemble.build_crossfade_command(["a.mp4", "b.mp4", "c.mp4"], [4.0, 6.0, 5.0], [0.5, 0.0], "joined.mp4", "o.mp4")
    graph = argv[argv.index("-filter_complex") + 1]
    assert "tpad=stop_mode=clone:stop_duration=0.500" in graph       # 앞 컷을 늘려 겹친다 → 길이 불변
    assert "xfade=transition=fade:duration=0.500:offset=4.000" in graph
    assert "concat=n=2:v=1:a=0" in graph                            # 0 이면 그냥 잇는다
    assert argv[argv.index("-map", argv.index("-filter_complex")) + 3] == "3:a"   # 음성은 이어 붙인 원본 그대로
