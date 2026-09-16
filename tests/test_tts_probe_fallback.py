"""ffprobe 가 없을 때 **나레이션이 사라지지 않는다** (2026-09-08 실측).

★ 무엇이 문제였나: `_probe_duration` 의 `try` 가 float 파싱만 감싸고 `subprocess.run` 은
  밖에 있었다. ffprobe 가 PATH 에 없으면 거기서 `FileNotFoundError` 가 터져 호출부까지
  올라갔고, 호출부는 그것을 "edge TTS 실패"로 읽어 **무음으로 폴백**했다.
  실측: 로컬 렌더에서 14컷 전부 무음이었고, 로그만 보면 TTS 서버가 죽은 것처럼 보였다.
  실제로는 **합성은 성공했고 길이만 못 쟀다.**

★★ 판정 불가와 실패를 섞지 않는다(skill: error-vs-empty-audit). 독스트링이 이미
  "ffprobe 실패 시에만 단어 끝으로 폴백"이라고 약속하고 있었다 — 코드가 그 약속을
  안 지키고 있었을 뿐이다.
"""

from __future__ import annotations

import subprocess

from engine.providers import tts


def test_a_missing_ffprobe_returns_zero_instead_of_raising(monkeypatch):
    """★ 바이너리가 없으면 0.0 을 돌려줘야 한다 — 예외가 올라가면 나레이션이 통째로 죽는다."""
    def _boom(*a, **kw):
        raise FileNotFoundError(2, "지정된 파일을 찾을 수 없습니다")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert tts._probe_duration("whatever.m4a") == 0.0


def test_an_unreadable_file_still_returns_zero(monkeypatch):
    """ffprobe 는 돌았지만 길이를 못 읽은 경우 — 기존 계약 그대로."""
    class _P:
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _P())
    assert tts._probe_duration("whatever.m4a") == 0.0


def test_a_normal_probe_returns_the_duration(monkeypatch):
    class _P:
        stdout = "12.345\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _P())
    assert tts._probe_duration("whatever.m4a") == 12.345


def test_the_caller_falls_back_to_word_timestamps_not_to_silence():
    """★★ 이것이 이 수정의 **뜻**이다 — 길이를 못 재도 나레이션은 남는다.

    `_edge_synthesize` 는 measured<=0 이면 마지막 단어 끝을 쓴다. 그 경로가 살아 있어야
    ffprobe 없는 환경에서도 소리가 나간다(정밀도만 떨어진다).
    """
    src = open(tts.__file__, encoding="utf-8").read()
    assert 'measured = float(words[-1]["end"]) if words else float(config.CUT_MIN_SEC)' in src
