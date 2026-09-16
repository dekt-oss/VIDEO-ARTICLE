"""TTS 제공자. P-V0: placeholder(추정 길이만큼 무음). P-V1(M-V5): edge(Edge TTS, 무료).

Edge TTS 는 키가 필요 없고 WordBoundary 로 단어 타임스탬프를 준다 → 정밀 자막 싱크.
반환: dict(path, sec, cost, words). words=[{text,start,end}](컷 로컬 초). placeholder 는 words=[].

주의: Edge TTS 는 Microsoft 공개 엔드포인트(wss)에 연결한다. TLS 가로채기 프록시 환경에서는
막힐 수 있으나, GitHub Actions/일반 네트워크에서는 정상 동작한다(엔진 실행 위치는 러너/로컬).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from .. import config, speech_text
from ..util import log


def _silent_audio(out_path: str, duration: int) -> None:
    argv = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(max(1, int(duration))),
        "-c:a", "aac", out_path,
    ]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"무음 오디오 생성 실패: {proc.stderr[-300:]}")


def _probe_duration(path: str) -> float:
    """ffprobe 로 오디오 파일의 실제 재생 길이(초, float)를 잰다. 못 재면 0.0.

    ★★ **바이너리가 없는 경우를 잡는다**(2026-09-08 실측). 종전에는 `try` 가 float 파싱만
      감쌌고 `subprocess.run` 은 밖에 있었다 — ffprobe 가 PATH 에 없으면 여기서
      `FileNotFoundError` 가 터져 호출부(`_edge_synthesize`)까지 올라갔고, 거기서
      "edge TTS 실패 → 무음 폴백"으로 처리됐다. **길이를 못 잰 것뿐인데 나레이션이 통째로
      사라졌다** — 실측에서 14컷 전부 무음이었고, 로그만 보면 TTS 가 실패한 것처럼 보였다.
      독스트링이 이미 "ffprobe 실패 시에만 단어 끝으로 폴백"이라고 약속하고 있었다.
      판정 불가(길이를 못 잼)와 실패(합성이 안 됨)를 섞지 않는다.
    """
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError) as exc:
        log.warning("ffprobe 없음 → 오디오 길이는 단어 타임스탬프로 폴백: %s", exc)
        return 0.0
    try:
        return float(proc.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _edge_synthesize(text: str, out_path: str, voice: str) -> tuple[float, list[dict[str, Any]]]:
    """edge-tts 로 합성 + 단어 타임스탬프. 반환: (measured_sec, words). ffmpeg 로 mp3→m4a.

    ★ measured 는 '실제 오디오 파일 길이'(ffprobe)다. 예전엔 마지막 단어 끝을 반올림해
    실제보다 짧아져(round down + 끝소리 무시) 나레이션이 잘리고 자막이 밀렸다.
    """
    import asyncio
    import edge_tts

    async def run() -> tuple[bytes, list[dict[str, Any]]]:
        audio = b""
        words: list[dict[str, Any]] = []
        comm = edge_tts.Communicate(text, voice, rate=config.EDGE_TTS_RATE)
        async for ch in comm.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                dur = ch["duration"] / 1e7
                words.append({"text": ch["text"], "start": start, "end": start + dur})
        return audio, words

    # ★ wss 스트림이 멈추면 렌더 전체가 무한 대기하므로 하드 타임아웃을 건다.
    async def _run_with_timeout() -> tuple[bytes, list[dict[str, Any]]]:
        return await asyncio.wait_for(run(), timeout=config.TTS_TIMEOUT_SEC)

    audio, words = asyncio.run(_run_with_timeout())
    mp3 = out_path + ".mp3"
    with open(mp3, "wb") as f:
        f.write(audio)
    # mp3 → m4a(aac) 통일(조립 파이프라인 코덱 일관성).
    proc = subprocess.run(["ffmpeg", "-y", "-i", mp3, "-c:a", "aac", out_path],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"edge-tts 변환 실패: {proc.stderr[-300:]}")
    # 실제 파일 길이(초). ffprobe 실패 시에만 단어 끝으로 폴백.
    measured = _probe_duration(out_path)
    if measured <= 0.0:
        measured = float(words[-1]["end"]) if words else float(config.CUT_MIN_SEC)
    return measured, words


def _mp3_bytes_to_m4a(raw: bytes, out_path: str, speed: float = 1.0) -> float:
    """mp3 바이트 → m4a. speed>1 이면 atempo 로 가속. 반환: 실측 길이(초).

    ★ 왜 여기서 가속하나: ElevenLabs 에는 rate 파라미터가 없고, Google 은 있지만 값이
      제각각이다. **어느 제공자를 쓰든 같은 속도가 나오게** 하려면 한 자리에서 맞춰야 한다.
    ★ atempo 는 0.5~2.0 만 받는다 — 그 밖은 무시하고 원속도로 둔다(무리해서 체인 걸지 않는다).
    """
    tmp = out_path + ".src.mp3"
    with open(tmp, "wb") as fh:
        fh.write(raw)
    argv = ["ffmpeg", "-y", "-i", tmp]
    if 0.5 <= float(speed) <= 2.0 and abs(float(speed) - 1.0) > 0.01:
        argv += ["-filter:a", f"atempo={float(speed):.3f}"]
    argv += ["-c:a", "aac", out_path]
    proc = subprocess.run(argv, capture_output=True, text=True)
    os.remove(tmp)
    if proc.returncode != 0:
        raise RuntimeError(f"mp3→m4a 변환 실패: {proc.stderr[-300:]}")
    return _probe_duration(out_path)


def _google_synthesize(text: str, out_path: str, lang: str) -> tuple[float, list[dict[str, Any]]]:
    """Google Cloud TTS(REST). 무료 100만자/월. **단어 타임스탬프 없음** → words=[].

    ★ 자막은 호출측이 어절 청킹으로 만든다(subtitles.chunk_text_by_rate). Edge 보다
      싱크가 거칠다 — 음질과 맞바꾼 것이고, 그 사실을 config 주석에 적어 뒀다.
    """
    import base64
    import json
    import urllib.request

    key = config.GOOGLE_TTS_API_KEY
    if not key:
        raise RuntimeError("GOOGLE_TTS_API_KEY 없음")
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": config.GOOGLE_TTS_LANG_CODE.get(lang, "ko-KR"),
                  "name": config.GOOGLE_TTS_VOICE_BY_LANG.get(lang)},
        "audioConfig": {"audioEncoding": "MP3",
                        "speakingRate": config.GOOGLE_TTS_SPEAKING_RATE},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raw = base64.b64decode(payload["audioContent"])
    # speakingRate 로 이미 가속했으므로 여기서 또 하지 않는다.
    return _mp3_bytes_to_m4a(raw, out_path, speed=1.0), []


def _elevenlabs_synthesize(text: str, out_path: str) -> tuple[float, list[dict[str, Any]]]:
    """ElevenLabs. 무료 1만자/월. **단어 타임스탬프 없음** → words=[].

    ★ 속도 파라미터가 없어 atempo 로 맞춘다(config.ELEVENLABS_SPEED).
    ★ 무료 한도를 넘기면 401 이 온다 — 호출측이 잡아 무음 폴백하지만, 로그에 남겨
      운영자가 "왜 이 편만 무음인가"를 알 수 있게 한다.
    """
    import urllib.error
    import urllib.request

    # ★★ `config.secrets()` 라는 함수는 **없다**(2026-09-08 실측). 정본은 `config.SECRETS`
    #   인스턴스다. 그래서 이 경로는 호출되는 순간 AttributeError 가 났고, 호출부의
    #   "그 컷만 무음 폴백" 이 그것을 삼켜 **일래븐랩스를 켜도 전부 무음**이 됐다.
    #   운영자가 키까지 넣어 뒀는데 소리가 안 나던 이유다 — 한 번도 실행된 적 없는 줄이었다.
    key = config.SECRETS.elevenlabs_api_key
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY 없음")
    body = __import__("json").dumps({
        "text": text, "model_id": config.ELEVENLABS_MODEL,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        hint = " (무료 한도 소진 가능성)" if exc.code in (401, 429) else ""
        raise RuntimeError(f"ElevenLabs HTTP {exc.code}{hint}") from exc
    return _mp3_bytes_to_m4a(raw, out_path, speed=config.ELEVENLABS_SPEED), []


def synthesize(cut: dict[str, Any], out_path: str, lang: str = "ko") -> dict[str, Any]:
    """컷 나레이션 → 오디오. ⑤언어별: narration_{lang} + 언어별 Edge TTS 보이스.

    lang 은 config.LANGUAGES 중 하나. narration_{lang} 이 비면 ko 로 폴백(부분 번역 누락 방지).
    """
    provider = config.TTS_PROVIDER
    est = int(cut.get("estimated_sec") or config.CUT_MIN_SEC)
    if provider in ("edge", "google", "elevenlabs"):
        # ★ 소리로 읽을 문장은 **자막과 다를 수 있다**(engine/speech_text.py): 영문 병기
        #   괄호를 빼고 발음 교정을 적용한다. 2026-09-11 운영자 실측 — "네이처(Nature)" 를
        #   한국어 TTS 가 "네이처 네이처" 로 두 번 읽었다. 화면에는 병기를 남긴다.
        text = speech_text.for_speech(cut.get(f"narration_{lang}") or cut.get("narration_ko") or "")
        if not text:
            _silent_audio(out_path, est)
            return {"path": out_path, "sec": est, "cost": 0.0, "words": []}
        try:
            if provider == "edge":
                voice = config.EDGE_TTS_VOICE_BY_LANG.get(lang, config.EDGE_TTS_VOICE)
                sec, words = _edge_synthesize(text, out_path, voice)
            elif provider == "google":
                sec, words = _google_synthesize(text, out_path, lang)
            else:
                sec, words = _elevenlabs_synthesize(text, out_path)
        except Exception as exc:  # noqa: BLE001 — 그 컷만 무음 폴백(전체 중단 금지)
            log.warning("%s TTS 실패(무음 폴백) cut=%s: %s",
                        provider, cut.get("cut_no"), str(exc)[:140])
            _silent_audio(out_path, est)
            return {"path": out_path, "sec": est, "cost": 0.0, "words": []}
        return {"path": out_path, "sec": sec, "cost": 0.0, "words": words}
    if provider != "placeholder":
        log.warning("알 수 없는 TTS_PROVIDER=%s → placeholder", provider)
    _silent_audio(out_path, est)
    return {"path": out_path, "sec": est, "cost": 0.0, "words": []}
