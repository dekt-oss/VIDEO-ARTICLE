"""자막 싱크 — 침묵 구간에 글자를 배분하지 않는다 (2026-09-09 운영자 지적).

★ 무엇이 문제였나: 컷 길이는 `나레이션 + CLIP_FIT_TAIL_PAD_SEC`(숨 쉴 틈)인데, 자막을 그
  **패드까지 포함한 길이**에 비례 배분하고 있었다. 꼬리는 침묵이라 거기서 말하는 단어가
  없는데도 글자를 밀어 넣은 셈이라, 컷마다 자막이 조금씩 뒤로 밀리고 마지막 어절은
  목소리가 끝난 뒤에 떴다. 바로 위 주석이 이미 "[t, t+measured]" 라고 약속하고 있었다.

★★ 왜 눈에 잘 띄었나: **한국어 Edge 음성 3종(SunHi·InJoon·Hyunsu)이 단어 타임스탬프를
  주지 않는다**(실측 확인). 그래서 한국어 렌더는 **항상** 이 추정 경로를 타고,
  이 어긋남이 모든 한국어 영상에 걸려 있었다.
"""

from __future__ import annotations

from engine import config, subtitles


def test_cues_do_not_run_past_the_narration():
    """★ 마지막 자막이 목소리보다 늦게 끝나면 안 된다."""
    cues = subtitles.chunk_text_by_rate("가나다 라마바 사아자 차카타", 0.0, 4.0, lang="ko")
    assert cues, "자막이 비었다"
    assert cues[-1][1] <= 4.0 + 0.51, cues[-1]   # tail_hold 최대 0.5s 는 허용


def test_the_spread_uses_the_narration_span_not_the_padded_clip():
    """★★ 이것이 실제 결함이다 — 같은 글을 침묵까지 늘려 배분하면 뒤로 밀린다."""
    narrated = subtitles.chunk_text_by_rate("가나다 라마바 사아자", 0.0, 3.0, lang="ko")
    padded = subtitles.chunk_text_by_rate("가나다 라마바 사아자", 0.0,
                                          3.0 + config.CLIP_FIT_TAIL_PAD_SEC, lang="ko")
    assert narrated[-1][1] < padded[-1][1], "패드를 포함하면 자막이 뒤로 밀린다(그것이 버그였다)"


def test_the_render_passes_the_narration_length():
    """상수만 알고 배선이 그대로면 화면은 안 바뀐다 — 실제 호출 인자를 본다."""
    src = open(__import__("engine.render", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert "chunk_text_by_rate(text, t, t + float(measured), lang=lang)" in src
    assert "chunk_text_by_rate(text, t, t + clip_dur, lang=lang)" not in src, "옛 배선이 남았다"


def test_the_vo_span_matches_the_narration_too():
    """★ 더킹 구간도 같다 — 침묵까지 BGM 을 눌러 두면 음악이 늦게 돌아온다."""
    src = open(__import__("engine.render", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert 'vo_words.append({"start": t, "end": t + float(measured)})' in src


def test_word_timestamps_still_win_when_available():
    """★ 실제 발음 시각이 있으면 그것이 정본이다 — 추정 경로는 폴백일 뿐이다."""
    src = open(__import__("engine.render", fromlist=["x"]).__file__, encoding="utf-8").read()
    i_words = src.index("if words:")
    i_text = src.index("elif text:", i_words)
    assert "chunk_by_rate(words" in src[i_words:i_text]
