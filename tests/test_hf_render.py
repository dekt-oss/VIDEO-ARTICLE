"""engine/hf_render 순수 로직 — 박자 계획·템플릿 채우기·실패 경로. 렌더·npx 는 부르지 않는다(0원)."""

import json
import os
import sys

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
    slots, dur = h.plan_slots([{"text": "<b>&위스키"}, {"text": "가격표만 기억난다", "keyword": "가격표"}], GRID, P)
    page = h.build_html(tpl, top_line='"인용" <script>', slots=slots, duration=dur, pulses=GRID)
    assert "&lt;b&gt;&amp;위스키" in page and "&lt;script&gt;" in page
    assert "__" not in page.replace("__timelines", "")
    assert 'data-start="0.000"' in page  # 첫 글은 0프레임부터 보인다
    assert '<span class="kw">가격표</span>만 기억난다' in page  # 강조 낱말만 칠한다
    assert h._mark("abc", "z") == "abc" and h._mark("<a>", "<a>") == '<span class="kw">&lt;a&gt;</span>'
    assert "cdn." not in page  # 렌더가 네트워크에 기대지 않는다
    with pytest.raises(h.HfRenderError, match="칸이 없"):
        h.build_html(tpl.replace("__WORDS__", ""), top_line="t", slots=slots, duration=dur, pulses=GRID)


def test_commands_are_pinned_and_strict():
    cmd = h.render_command("o.mp4")
    assert config.HF_HYPERFRAMES_PKG in cmd and "--strict" in cmd
    assert config.HF_HYPERFRAMES_PKG == config.MOTION_HYPERFRAMES_PKG  # 저장소에 고정 버전은 하나
    assert config.HF_HYPERFRAMES_PKG in h.beats_command("a.wav")
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
    good = {"width": 1080, "height": 1920, "audio_streams": 1, "duration_sec": 5.5, "fps": 30.0}
    h.verify_output(good, 5.49)
    for bad in ({"width": 720}, {"audio_streams": 0}, {"duration_sec": 4.0}, {"fps": 24.0}):
        with pytest.raises(h.HfRenderError):
            h.verify_output({**good, **bad}, 5.49)


def test_run_wraps_missing_command_and_failure():
    with pytest.raises(h.HfRenderError, match="찾을 수 없"):
        h._run(["no-such-command-hf-xyz"])
    with pytest.raises(h.HfRenderError, match="명령 실패"):
        h._run([sys.executable, "-c", "import sys; sys.exit(3)"])


def test_broken_result_never_reaches_out_path(tmp_path, monkeypatch):
    """렌더 도중 깨진 mp4(2026-11-26 실제 사고) — 최종 위치에 아무것도 남지 않고 임시 파일도 지운다."""
    import subprocess as sp
    from engine import drinks_render

    def fake_run(cmd, cwd=None):
        out = cmd[-1]
        if "render" in cmd:
            out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"not an mp4")
        return ""

    def broken_probe(path):
        raise sp.CalledProcessError(1, ["ffprobe"])

    monkeypatch.setattr(h, "_run", fake_run)
    monkeypatch.setattr(drinks_render, "_probe", broken_probe)
    out = tmp_path / "o.mp4"
    with pytest.raises(h.HfRenderError, match="깨진"):
        h.render_meme(out_path=str(out), **h.DEMO)
    assert list(tmp_path.iterdir()) == []


def test_worker_switch_is_on_and_env_can_turn_it_off(monkeypatch):
    """S3 승인(2026-11-27) 뒤 기본 켜짐. 되돌리기는 환경변수 하나."""
    import importlib
    monkeypatch.delenv("DRINKS_HF_ENABLED", raising=False)
    assert importlib.reload(config).DRINKS_HF_ENABLED is True
    monkeypatch.setenv("DRINKS_HF_ENABLED", "0")
    assert importlib.reload(config).DRINKS_HF_ENABLED is False
    monkeypatch.delenv("DRINKS_HF_ENABLED")
    importlib.reload(config)


def test_changed_music_file_is_refused(tmp_path):
    led = tmp_path / "ledger.json"
    (tmp_path / "x.m4a").write_bytes(b"other")
    led.write_text(json.dumps({"tracks": {"x": {"file": "x.m4a", "sha256": "0" * 64, "rights": "owned_code_synth",
                                                "beat_period_sec": 0.5, "first_beat_sec": 0, "duration_sec": 10}}}), encoding="utf-8")
    with pytest.raises(h.HfRenderError, match="다릅니다"):
        h.load_track("x", str(led))


def test_ledger_without_sha_is_refused(tmp_path):
    led = tmp_path / "ledger.json"
    (tmp_path / "x.m4a").write_bytes(b"a")
    for sha in (None, ""):
        entry = {"file": "x.m4a", "rights": "owned_code_synth", "beat_period_sec": 0.5, "first_beat_sec": 0, "duration_sec": 10}
        if sha is not None:
            entry["sha256"] = sha
        led.write_text(json.dumps({"tracks": {"x": entry}}), encoding="utf-8")
        with pytest.raises(h.HfRenderError, match="sha256"):
            h.load_track("x", str(led))


def test_template_text_box_matches_config():
    tpl = open(os.path.join(h.TEMPLATE_DIR, "meme-beat", "index.template.html"), encoding="utf-8").read()
    assert f"font-size: {config.HF_MEME_WORD_PX}px" in tpl and f"font-size: {config.HF_MEME_TOP_PX}px" in tpl
    assert "left: 80px; right: 140px" in tpl and config.HF_MEME_TEXT_WIDTH_PX == 1080 - 80 - 140
