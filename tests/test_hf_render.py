"""engine/hf_render 순수 로직 — 박자 계획·템플릿 채우기·실패 경로. 렌더·npx 는 부르지 않는다(0원)."""

import json
import os

import pytest

from engine import config, hf_render as h

TRACK = h.load_track("sooljjerigo-groove-117")
GRID = h.beat_grid(TRACK)
P = TRACK.beat_period_sec


def test_ledger_grid_is_117bpm_from_first_beat():
    assert GRID[0] == pytest.approx(0.3598)
    assert GRID[1] - GRID[0] == pytest.approx(60 / 117, abs=1e-3)
    assert GRID[-1] < TRACK.duration_sec
    assert os.path.exists(TRACK.path)


def test_unknown_or_unowned_track_is_refused(tmp_path):
    with pytest.raises(h.HfRenderError, match="없는 곡"):
        h.load_track("nope")
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"tracks": {"x": {"file": "x.m4a", "rights": "unknown", "beat_period_sec": 0.5,
                                                "first_beat_sec": 0, "duration_sec": 10}}}), encoding="utf-8")
    with pytest.raises(h.HfRenderError, match="권리"):
        h.load_track("x", str(led))


def test_every_word_lands_on_a_beat_and_last_holds_two_seconds():
    slots, dur = h.plan_slots(h.DEMO["items"], GRID, P)
    for s in slots:
        assert min(abs(s.start - g) for g in GRID) < 1e-9
    assert slots[-1].end - slots[-1].start >= config.HF_CLOSING_HOLD_SEC
    assert dur == slots[-1].end
    assert [s.end for s in slots[:-1]] == [s.start for s in slots[1:]]  # 빈틈 없이 이어진다


def test_plan_failures():
    with pytest.raises(h.HfRenderError, match="글이 없"):
        h.plan_slots([], GRID, P)
    with pytest.raises(h.HfRenderError, match="박자가 0"):
        h.plan_slots([{"text": "a"}], [], P)
    with pytest.raises(h.HfRenderError, match="비어"):
        h.plan_slots([{"text": "  "}], GRID, P)
    with pytest.raises(h.HfRenderError, match="음원이 짧"):
        h.plan_slots([{"text": "a", "ms": 999_000}], GRID, P)


def test_html_escapes_text_and_fills_every_slot():
    tpl = open(os.path.join(h.TEMPLATE_DIR, "meme-beat", "index.template.html"), encoding="utf-8").read()
    slots, dur = h.plan_slots([{"text": "<b>&위스키"}, {"text": "끝", "key": True}], GRID, P)
    page = h.build_html(tpl, top_line='"인용" <script>', slots=slots, duration=dur, pulses=GRID)
    assert "&lt;b&gt;&amp;위스키" in page and "&lt;script&gt;" in page
    assert "__" not in page.replace("__timelines", "")
    assert 'data-start="0.000"' in page  # 첫 글은 0프레임부터 보인다
    assert 'class="word key clip"' in page
    assert "cdn." not in page  # 렌더가 네트워크에 기대지 않는다


def test_commands_are_pinned_and_strict():
    cmd = h.render_command("o.mp4")
    assert f"hyperframes@{config.HF_CLI_VERSION}" in cmd and "--strict" in cmd
    assert f"hyperframes@{config.HF_CLI_VERSION}" in h.beats_command("a.wav")
    assert h._env()["HYPERFRAMES_NO_TELEMETRY"] == "1"


def test_beats_json_parsing_and_matching():
    assert h.parse_beats_json('log line\n{"ok":true,"beatTimes":[0.36,0.87]}') == [0.36, 0.87]
    with pytest.raises(h.HfRenderError):
        h.parse_beats_json('{"ok":true,"beatTimes":[]}')
    with pytest.raises(h.HfRenderError):
        h.parse_beats_json("no json")
    assert h.match_ratio([g + 0.01 for g in GRID[:10]], GRID) == 1.0
    assert h.match_ratio([g + P / 2 for g in GRID[:10]], GRID) == 0.0


def test_verify_output_rejects_bad_results():
    good = {"width": 1080, "height": 1920, "audio_streams": 1, "duration_sec": 5.5}
    h.verify_output(good, 5.49)
    for bad in ({"width": 720}, {"audio_streams": 0}, {"duration_sec": 4.0}):
        with pytest.raises(h.HfRenderError):
            h.verify_output({**good, **bad}, 5.49)


def test_worker_switch_stays_off_until_s3_approval():
    assert config.DRINKS_HF_ENABLED is False
