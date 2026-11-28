"""제미나이 TTS(AI Studio 키). 소유자 지시 2026-11-28 — 주류 공장 기본 목소리.

★ 실패는 예외로 올린다(무음으로 바꾸는 건 호출측 결정). 키는 오류 문구에서 지운다.
★ 문장마다 같은 말투 지시(config.GEMINI_TTS_STYLE)를 붙이고, engine/voice_qc 점수가 높으면 다시 받는다.
★ 단어 타임스탬프가 없다 — 호출측은 words=[] 로 받는다.
비용: 응답 usageMetadata 토큰 × 단가를 모듈 누계(SPENT)에 더한다. 렌더 한 건 앞에서 reset() 하고 뒤에서 읽는다.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request

from .. import config, voice_qc

SPENT = {"usd": 0.0, "calls": 0}
# 피치 기준(Hz). 첫 문장에서 잡고 같은 편 안에서는 고정 — 문장마다 기준이 바뀌면 들쭉날쭉을 못 잡는다.
_REF: dict[str, float] = {}


def reset() -> None:
    SPENT.update(usd=0.0, calls=0)
    _REF.clear()


def _key() -> str:
    # 렌더 워커(drinks-produce)에는 TTS 전용 이름만 준다 — 그림·영상 구매 경로가 읽는 GEMINI_API_KEY 는 없어야 한다(tests/test_drinks_explainer_queue)
    k = os.getenv("GEMINI_TTS_API_KEY", "") or config.SECRETS.gemini_api_key
    if not k:
        raise RuntimeError("제미나이 키 없음(GEMINI_TTS_API_KEY 또는 GEMINI_API_KEY)")
    return k


def _call(text: str, voice: str) -> bytes:
    body = json.dumps({"contents": [{"parts": [{"text": config.GEMINI_TTS_STYLE + text}]}],
                       "generationConfig": {"responseModalities": ["AUDIO"],
                                            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_TTS_MODEL}:generateContent",
        data=body, headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
    try:
        with urllib.request.urlopen(req, timeout=config.TTS_TIMEOUT_SEC) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"gemini TTS {e.code}: " + re.sub(r"(AQ\.|AIza)[0-9A-Za-z_.-]+", "***", e.read().decode()[:300])) from None
    u = r.get("usageMetadata") or {}
    SPENT["usd"] += (u.get("promptTokenCount", 0) * config.GEMINI_TTS_PRICE_IN_PER_M
                     + u.get("candidatesTokenCount", 0) * config.GEMINI_TTS_PRICE_OUT_PER_M) / 1e6
    SPENT["calls"] += 1
    part = r["candidates"][0]["content"]["parts"][0]["inlineData"]
    if not str(part.get("mimeType", "")).startswith("audio/L16"):
        raise RuntimeError(f"gemini TTS 예상 밖 형식: {part.get('mimeType')}")
    return base64.b64decode(part["data"])


def _pcm_to_wav(pcm: bytes, path: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(config.GEMINI_TTS_SAMPLE_RATE), "-ac", "1",
                    "-i", "-", path], input=pcm, check=True)


def synthesize(text: str, out_path: str, voice: str | None = None, speed: float | None = None) -> float:
    """text → out_path(확장자대로 인코딩). 반환: 길이(초). 피치가 튀면 최대 GEMINI_TTS_MAX_TRIES 번 받아 가장 나은 것."""
    voice = voice or config.GEMINI_TTS_VOICE
    speed = config.GEMINI_TTS_SPEED if speed is None else speed
    with tempfile.TemporaryDirectory() as td:
        best_path, best = "", 9e9
        for n in range(config.GEMINI_TTS_MAX_TRIES):
            cand = os.path.join(td, f"c{n}.wav")
            try:
                _pcm_to_wav(_call(text, voice), cand)
            except Exception:
                if not best_path:   # 첫 테이크조차 없으면 실패를 올린다. 다시 받기 실패는 이미 받은 테이크로 간다
                    raise
                break
            ref = _REF.setdefault(voice, voice_qc.stats(cand, 1)[0] or config.GEMINI_TTS_REF_HZ_FALLBACK)
            sc = voice_qc.score(cand, ref)
            if sc < best:
                best_path, best = cand, sc
            if best <= config.GEMINI_TTS_QC_LIMIT:
                break
        argv = ["ffmpeg", "-y", "-v", "error", "-i", best_path]
        if 0.5 <= speed <= 2.0 and abs(speed - 1.0) > 0.01:   # ffmpeg atempo 가 받는 범위
            argv += ["-filter:a", f"atempo={speed:.4f}"]
        subprocess.run(argv + [out_path], check=True)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
                         capture_output=True, text=True).stdout
    return float(out.strip() or 0)
