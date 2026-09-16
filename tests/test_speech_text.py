"""소리로 읽을 문장은 영문 병기를 빼고, 한글 괄호는 남긴다 (2026-09-11 운영자 지적).

"네이처(Nature)" 를 한국어 TTS 가 "네이처 네이처" 로 두 번 읽었다. 자막은 병기를 유지한다.
"""
import pytest

from engine import config, speech_text


@pytest.mark.parametrize("src, want", [
    ("연구진이 네이처(Nature)에 발표한 연구입니다.", "연구진이 네이처에 발표한 연구입니다."),
    ("연구진이 네이처 (Nature) 에 발표했습니다.", "연구진이 네이처 에 발표했습니다."),
    ("네이처（Nature）에 실렸습니다.", "네이처에 실렸습니다."),
    ("전전두엽 피질(prefrontal cortex)에서 발현됩니다.", "전전두엽 피질에서 발현됩니다."),
])
def test_latin_gloss_is_dropped(src: str, want: str):
    assert speech_text.for_speech(src) == want


@pytest.mark.parametrize("src", [
    "1,260개(전체의 13%)를 설명합니다.",
    "성격 특성(외향성과 친화성)을 봤습니다.",
    "(그림 2)에서 보듯이요.",
])
def test_korean_parentheses_are_information_and_stay(src: str):
    """괄호를 전부 지우면 정보가 사라진다 — 라틴 문자 병기만 뺀다."""
    assert speech_text.for_speech(src) == src


def test_pronunciation_table_still_applies():
    assert "아카이브" in speech_text.for_speech("arXiv 에 올라온 논문입니다.")


def test_toggle_off_keeps_everything(monkeypatch):
    monkeypatch.setattr(config, "TTS_DROP_LATIN_GLOSS", False)
    src = "네이처(Nature)에 실렸습니다."
    assert speech_text.for_speech(src) == src


def test_empty_and_none_are_safe():
    assert speech_text.for_speech("") == ""
    assert speech_text.for_speech(None) == ""


def test_whitespace_only_becomes_empty_so_paid_tts_is_not_called():
    """호출측 가드가 `if not text` 다 — 공백을 돌려주면 유료 백엔드가 불린다(실측)."""
    assert speech_text.for_speech("   ") == ""
    assert speech_text.for_speech(chr(10) + chr(9) + " ") == ""


def test_tts_provider_uses_it():
    """검사와 전송 대상이 다르면 고친 의미가 없다 — providers/tts 가 이 함수를 쓰는지 못박는다."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "engine" / "providers" / "tts.py").read_text(encoding="utf-8")
    assert "speech_text.for_speech" in src
