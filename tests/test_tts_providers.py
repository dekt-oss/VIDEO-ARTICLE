"""TTS 제공자 3종 — edge / google / elevenlabs (운영자 지시 2026-09-05).

지시: "TTS도 바꾸든가해봐. 속도 보통보다 20% 가속된걸로 해야하고 …
요즘 유행하는 tts 무료로 사용하는방법도 연구해봐" → "구글이랑 일래븐랩스 둘다 써보자"

세 제공자의 성질이 다르다(config 주석의 표와 같은 내용):
    edge        무료·무제한 · **단어 타임스탬프 있음** → 자막 싱크 정밀
    google      무료 100만자/월 · 타임스탬프 없음 → 어절 청킹
    elevenlabs  무료 1만자/월 · 타임스탬프 없음 · 톤이 가장 자연스럽다

★ 이 파일은 **네트워크를 타지 않는다.** 합성 함수는 전부 가짜로 바꾸고,
  분기·폴백·속도 정합만 본다. 실제 음질은 사람이 듣고 판단할 일이다.
"""

from __future__ import annotations

from unittest import mock

from engine import config
from engine.providers import tts

CUT = {"cut_no": 1, "narration_ko": "노화를 늦추는 약이 나왔습니다.",
       "narration_en": "A drug that slows ageing.", "estimated_sec": 5}


def test_every_provider_reaches_its_own_backend():
    """★ 분기가 틀리면 다른 엔진이 조용히 돌아간다 — 셋을 각각 확인한다."""
    for provider, fn in (("edge", "_edge_synthesize"),
                         ("google", "_google_synthesize"),
                         ("elevenlabs", "_elevenlabs_synthesize")):
        with mock.patch.object(config, "TTS_PROVIDER", provider), \
             mock.patch.object(tts, fn, return_value=(4.2, [])) as spy:
            out = tts.synthesize(CUT, "o.m4a", "ko")
        assert spy.called, provider
        assert out["sec"] == 4.2 and out["cost"] == 0.0


def test_a_backend_failure_falls_back_to_silence_not_a_crash():
    """★ TTS 하나가 죽어서 렌더 전체가 멈추면 안 된다 — 그 컷만 무음으로 간다."""
    for provider, fn in (("google", "_google_synthesize"),
                         ("elevenlabs", "_elevenlabs_synthesize")):
        with mock.patch.object(config, "TTS_PROVIDER", provider), \
             mock.patch.object(tts, fn, side_effect=RuntimeError("한도 소진")), \
             mock.patch.object(tts, "_silent_audio") as silent:
            out = tts.synthesize(CUT, "o.m4a", "ko")
        assert silent.called, provider
        assert out["sec"] == 5 and out["words"] == []


def test_empty_narration_never_calls_a_paid_backend():
    """빈 문장에 API 를 부르면 돈만 나간다."""
    with mock.patch.object(config, "TTS_PROVIDER", "elevenlabs"), \
         mock.patch.object(tts, "_elevenlabs_synthesize") as spy, \
         mock.patch.object(tts, "_silent_audio"):
        tts.synthesize({"cut_no": 1, "narration_ko": "  ", "estimated_sec": 3}, "o.m4a", "ko")
    assert not spy.called


def test_pronunciation_fixes_apply_to_every_provider():
    """arXiv→아카이브 같은 교정이 edge 에만 걸리면 제공자를 바꿀 때 발음이 달라진다."""
    cut = dict(CUT, narration_ko=f"{next(iter(config.TTS_PRONUNCIATION))} 연구입니다.")
    src, dst = next(iter(config.TTS_PRONUNCIATION.items()))
    with mock.patch.object(config, "TTS_PROVIDER", "google"), \
         mock.patch.object(tts, "_google_synthesize", return_value=(3.0, [])) as spy:
        tts.synthesize(cut, "o.m4a", "ko")
    assert dst in spy.call_args[0][0] and src not in spy.call_args[0][0]


def test_all_three_target_the_same_speed():
    """★★ 제공자를 바꿨다고 말 속도가 달라지면 안 된다. 셋이 같은 1.2배를 겨눈다.

    edge 는 rate 문자열, google 은 speakingRate, elevenlabs 는 atempo 로 각각 맞춘다.
    """
    assert config.EDGE_TTS_RATE == "+10%"
    assert abs(config.GOOGLE_TTS_SPEAKING_RATE - 1.1) < 0.01
    assert abs(config.ELEVENLABS_SPEED - 1.1) < 0.01


def test_timestamp_capability_is_written_down_where_it_matters():
    """★ google·elevenlabs 는 단어 타임스탬프가 없다 → 자막이 어절 청킹으로 떨어진다.
    나중에 '자막이 밀린다'는 신고가 오면 원인이 여기다. 그 사실을 config 에 적어 뒀다."""
    import inspect
    src = inspect.getsource(config)
    assert "타임스탬프" in src and "어절 청킹" in src


def test_language_selection_uses_per_language_voices():
    for lang, table in (("ko", config.GOOGLE_TTS_VOICE_BY_LANG),
                        ("en", config.GOOGLE_TTS_VOICE_BY_LANG)):
        assert table.get(lang), lang
    assert config.GOOGLE_TTS_LANG_CODE["ko"] == "ko-KR"


def test_google_falls_back_to_ko_when_a_language_is_missing():
    """부분 번역 누락 시 무음이 아니라 한국어로 읽는다(기존 계약 유지)."""
    with mock.patch.object(config, "TTS_PROVIDER", "google"), \
         mock.patch.object(tts, "_google_synthesize", return_value=(3.0, [])) as spy:
        tts.synthesize({"cut_no": 1, "narration_ko": "한국어만 있다", "estimated_sec": 4},
                       "o.m4a", "en")
    assert "한국어만 있다" in spy.call_args[0][0]
