"""제미나이 TTS(주류 기본 목소리, 2026-11-28) — 0원 시험(네트워크·ffmpeg 를 바꿔 끼운다)."""
from __future__ import annotations

import base64
import io
import json
import urllib.error
from unittest import mock

import pytest

from engine import config
from engine.providers import gemini_tts, tts


def _resp(tokens_in=10, tokens_out=100):
    body = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000",
                                                                    "data": base64.b64encode(b"\0\0" * 100).decode()}}]}}],
            "usageMetadata": {"promptTokenCount": tokens_in, "candidatesTokenCount": tokens_out}}
    r = mock.MagicMock(); r.read.return_value = json.dumps(body).encode(); r.__enter__.return_value = r
    return r


def test_provider_switch_reaches_gemini():
    with mock.patch.object(config, "TTS_PROVIDER", "gemini"), mock.patch.object(gemini_tts, "synthesize", return_value=3.3) as spy:
        out = tts.synthesize({"cut_no": 1, "narration_ko": "효모가 향을 만들어요.", "estimated_sec": 4}, "o.m4a", "ko")
    assert spy.called and out["sec"] == 3.3 and out["words"] == []


def test_cost_is_counted_from_tokens_and_style_is_sent():
    gemini_tts.reset()
    with mock.patch.dict("os.environ", {"GEMINI_TTS_API_KEY": "k"}), \
         mock.patch("urllib.request.urlopen", return_value=_resp(1_000_000, 1_000_000)) as up:
        gemini_tts._call("안녕", "Alnilam")
    sent = json.loads(up.call_args[0][0].data)
    assert sent["contents"][0]["parts"][0]["text"].startswith(config.GEMINI_TTS_STYLE)
    assert sent["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Alnilam"
    assert gemini_tts.SPENT["usd"] == pytest.approx(config.GEMINI_TTS_PRICE_IN_PER_M + config.GEMINI_TTS_PRICE_OUT_PER_M)


def test_error_message_hides_the_key():
    err = urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b'{"error": "bad key AQ.Ab12-x_y"}'))
    with mock.patch.dict("os.environ", {"GEMINI_TTS_API_KEY": "k"}), mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError) as e:
            gemini_tts._call("안녕", "Alnilam")
    assert "AQ.Ab12" not in str(e.value) and "***" in str(e.value)


def test_pitch_glitch_is_regenerated_and_best_take_kept():
    """★ 사케 1편: 문장 하나가 0.44초 피치가 튀었다 → 점수가 넘으면 다시 받는다. 좋아지면 거기서 멈춘다."""
    gemini_tts.reset()
    scores = iter([0.6, 0.2])
    with mock.patch.object(gemini_tts, "_call", return_value=b"pcm") as call, \
         mock.patch.object(gemini_tts, "_pcm_to_wav"), \
         mock.patch.object(gemini_tts.voice_qc, "stats", return_value=(120.0, 0.0)), \
         mock.patch.object(gemini_tts.voice_qc, "score", side_effect=lambda p, r: next(scores)), \
         mock.patch.object(gemini_tts.subprocess, "run") as run:
        run.return_value.stdout = "2.5"
        sec = gemini_tts.synthesize("사과 향", "o.m4a")
    assert call.call_count == 2 and sec == 2.5
    enc = run.call_args_list[0][0][0]
    assert enc[enc.index("-i") + 1].endswith("c1.wav"), "더 나은 두 번째 것을 써야 한다"


def test_gives_up_after_max_tries_with_the_best_take():
    with mock.patch.object(gemini_tts, "_call", return_value=b"pcm") as call, \
         mock.patch.object(gemini_tts, "_pcm_to_wav"), \
         mock.patch.object(gemini_tts.voice_qc, "stats", return_value=(120.0, 0.0)), \
         mock.patch.object(gemini_tts.voice_qc, "score", return_value=0.9), \
         mock.patch.object(gemini_tts.subprocess, "run") as run:
        run.return_value.stdout = "2.0"
        gemini_tts.synthesize("퀴즈!", "o.m4a")
    assert call.call_count == config.GEMINI_TTS_MAX_TRIES


def test_drinks_render_allows_gemini_but_still_blocks_other_paid_tts():
    from engine import drinks_render
    drinks_render._guard_free("gemini")
    with pytest.raises(drinks_render.RenderError):
        drinks_render._guard_free("elevenlabs")


def test_drinks_default_is_gemini_and_clay_uses_it():
    from engine import drinks_clay
    assert config.DRINKS_TTS_PROVIDER == "gemini"
    with mock.patch.object(config, "DRINKS_TTS_PROVIDER", "gemini"), mock.patch.object(gemini_tts, "synthesize") as spy:
        assert drinks_clay.speak("효모", "x.mp3") == []
    assert spy.called


def test_edge_choice_never_calls_gemini_in_clay():
    """★ Codex P1: --tts edge 로 돌리면 사진클레이도 Edge — 제미나이(유료)를 부르면 안 된다."""
    from engine import drinks_clay
    with mock.patch.object(config, "DRINKS_TTS_PROVIDER", "edge"), \
         mock.patch.object(gemini_tts, "synthesize") as spy, \
         mock.patch("edge_tts.Communicate", side_effect=RuntimeError("네트워크 없음")):
        with pytest.raises(RuntimeError):
            drinks_clay.speak("효모", "x.mp3")
    assert not spy.called


def test_cli_and_job_tts_choice_reach_the_clay_switch():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    q = (root / "engine" / "drinks_explainer_queue.py").read_text(encoding="utf-8")
    body = q[q.index("def process_explainer_job"):]
    assert body.index("config.DRINKS_TTS_PROVIDER, tts") < body.index("_run_plan(")
    assert "config.DRINKS_TTS_PROVIDER = args.tts" in (root / "engine" / "drinks_produce.py").read_text(encoding="utf-8")


def test_final_render_tts_cost_is_recorded_on_both_paths():
    """★ Codex P2: 최종 렌더도 음성을 다시 합성한다 — 두 경로 모두 누계를 비우고 실제 비용을 적는다."""
    from pathlib import Path
    from engine import drinks_explainer_queue as q
    src = (Path(__file__).resolve().parent.parent / "engine" / "drinks_explainer_queue.py").read_text(encoding="utf-8")
    for fn in ("def _run_render_clay", "def _run_render("):
        body = src[src.index(fn):]
        body = body[:body.index("\ndef ", 1)]
        assert "_tts_spend_reset()" in body and "_record_tts_spend(" in body, fn
    calls = []
    gemini_tts.reset(); gemini_tts.SPENT["usd"] = 0.0123
    with mock.patch.object(q, "_lease", return_value={"job_id": "j"}):
        q._record_tts_spend({"job_id": "j"}, lambda name, args: calls.append((name, args)), "gemini", 10, "최종 렌더", False)
    assert calls[0][0] == "drinks_record_cost" and calls[0][1]["cost"]["cost_usd"] == 0.0123 and calls[0][1]["cost"]["provider"] == "gemini"


def test_retry_failure_keeps_the_take_already_received():
    """다시 받기가 429·타임아웃으로 죽어도 이미 받은 테이크를 쓴다(그 컷을 무음으로 만들지 않는다)."""
    calls = iter([b"pcm", RuntimeError("429")])

    def call(*_):
        v = next(calls)
        if isinstance(v, Exception):
            raise v
        return v
    with mock.patch.object(gemini_tts, "_call", side_effect=call), mock.patch.object(gemini_tts, "_pcm_to_wav"), \
         mock.patch.object(gemini_tts.voice_qc, "stats", return_value=(120.0, 0.0)), \
         mock.patch.object(gemini_tts.voice_qc, "score", return_value=0.9), \
         mock.patch.object(gemini_tts.subprocess, "run") as run:
        run.return_value.stdout = "2.0"
        assert gemini_tts.synthesize("퀴즈!", "o.m4a") == 2.0


def test_job_tts_choice_does_not_leak_after_the_job():
    from engine import drinks_explainer_queue as q
    before = config.DRINKS_TTS_PROVIDER
    with mock.patch.object(q, "_heartbeat", side_effect=RuntimeError("멈춤")):
        try:
            q.process_explainer_job({"job_id": "j" * 8, "renderer": "explainer_plan"}, lambda *a: {}, None, tts="placeholder")
        except Exception:
            pass
    assert config.DRINKS_TTS_PROVIDER == before
