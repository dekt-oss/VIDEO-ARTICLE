"""engine.subtitles 순수 로직 테스트 (SRT 생성·자막 큐)."""

from engine import config
from engine.subtitles import (
    ass_timestamp,
    build_ass,
    build_srt,
    chunk_by_rate,
    chunk_text_by_rate,
    clamp_overlaps,
    cues_from_cuts,
    merge_word_cues,
    platform_margin_v,
    srt_timestamp,
)


def _words(n: int, dur: float, char: str = "가나다라마", gap: float = 0.0):
    """연속 단어 타임스탬프 생성기(테스트용). 각 단어 길이 dur, 사이 간극 gap."""
    out = []
    t = 0.0
    for _ in range(n):
        out.append({"text": char, "start": t, "end": t + dur})
        t += dur + gap
    return out


def test_srt_timestamp_format():
    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(3.5) == "00:00:03,500"
    assert srt_timestamp(3661.25) == "01:01:01,250"
    assert srt_timestamp(-1) == "00:00:00,000"


def test_build_srt_skips_empty_and_zero_length():
    srt = build_srt([(0, 4, "후크"), (4, 4, "빈길이"), (4, 8, ""), (8, 12, "CTA")])
    assert "후크" in srt and "CTA" in srt
    assert "빈길이" not in srt  # end<=start 제외
    assert srt.count("-->") == 2
    assert srt.startswith("1\n")  # 인덱스 재부여


def test_cues_from_cuts_sequential_timeline():
    cues = cues_from_cuts([4, 5], ["a", "b"])
    assert cues == [(0.0, 4.0, "a"), (4.0, 9.0, "b")]


def test_merge_word_cues_groups_under_limit():
    words = [
        {"text": "가나", "start": 0.0, "end": 0.5},
        {"text": "다라", "start": 0.5, "end": 1.0},
        {"text": "마바사아", "start": 1.0, "end": 1.8},
    ]
    cues = merge_word_cues(words, offset=10.0, max_chars=5)
    # "가나 다라"(5자) 한 줄, "마바사아" 다음 줄. offset 반영.
    assert cues[0][0] == 10.0
    assert "가나 다라" in cues[0][2]
    assert cues[1][2] == "마바사아"
    assert cues[1][0] == 11.0  # offset + 1.0


def test_merge_word_cues_empty():
    assert merge_word_cues([], offset=0.0) == []


def test_ass_timestamp_format():
    assert ass_timestamp(0) == "0:00:00.00"
    assert ass_timestamp(3.5) == "0:00:03.50"
    assert ass_timestamp(3661.25) == "1:01:01.25"


def test_build_ass_sets_playres_and_style():
    ass = build_ass([(0, 4, "후크"), (4, 8, "개념")])
    # ★ 핵심: PlayRes 를 영상 해상도로 명시(libass 기본 288 좌표계 문제 회피).
    assert f"PlayResX: {config.RENDER_WIDTH}" in ass
    assert f"PlayResY: {config.RENDER_HEIGHT}" in ass
    assert config.SUBTITLE_FONT_NAME in ass
    # MarginV: center_band 면 하단 바 안(LETTERBOX_CAPTION_MARGIN_V), 아니면 세이프바텀.
    expected_mv = (config.LETTERBOX_CAPTION_MARGIN_V if config.LAYOUT_MODE == "center_band"
                   else int(config.RENDER_HEIGHT * config.SUBTITLE_SAFE_BOTTOM))
    assert f",{expected_mv}\n" in ass
    assert ass.count("Dialogue:") == 2
    assert "후크" in ass and "개념" in ass


def test_build_ass_skips_empty():
    ass = build_ass([(0, 4, "  "), (4, 4, "zero")])
    assert ass.count("Dialogue:") == 0


def test_build_ass_header_title_and_hook():
    # 상단 고정 헤더: 시리즈 제목 + 후킹을 [0, total] 전 구간 표시(Header 스타일, 상단 정렬).
    ass = build_ass([(0, 4, "후크"), (4, 8, "개념")],
                    header_title="하루 논문 한 편", header_hook="AI도 나이를 먹는다",
                    total_sec=8.0)
    assert "Style: Header," in ass
    assert "하루 논문 한 편" in ass and "AI도 나이를 먹는다" in ass
    assert ass.count("Dialogue:") == 3  # 자막 2 + 헤더 1
    assert "Header,,0,0,0,,하루 논문 한 편" in ass


def test_build_ass_no_header_line_when_absent():
    ass = build_ass([(0, 4, "후크")])
    assert ass.count("Dialogue:") == 1  # 제목/후킹 미전달 → 헤더 라인 없음


# ── ① 레이트 기반 청킹 + Fallback (DV7) ─────────────────────────
def test_chunk_by_rate_empty():
    assert chunk_by_rate([], lang="ko") == []


def test_chunk_by_rate_slow_speech_fills_to_max():
    # 느린 발화(단어당 1.0s): 읽을 시간 충분 → CHUNK_MAX(ko=6)까지 채운다.
    words = _words(8, dur=1.0, char="가")
    cues = chunk_by_rate(words, lang="ko")
    first_text = cues[0][2]
    assert len(first_text.split(" ")) == config.CAPTION_CHUNK_MAX["ko"]


def test_chunk_by_rate_fast_speech_reduces_chunk():
    # 빠른 발화(단어당 0.25s, 5자): 4단어 표시창 1.0s(플로어 이상)인데 R≈1.8s>W → CHUNK_FAST(4)에서 닫는다.
    words = _words(12, dur=0.25, char="가나다라마")
    cues = chunk_by_rate(words, lang="ko")
    assert len(cues[0][2].split(" ")) == config.CAPTION_CHUNK_FAST["ko"]


def test_chunk_by_rate_offset_applied():
    words = _words(4, dur=1.0, char="가")
    cues = chunk_by_rate(words, lang="ko", offset=10.0)
    assert cues[0][0] == 10.0


def test_chunk_by_rate_tail_hold_capped():
    # 마지막 청크는 tail_hold(최대 0.5s)만 연장. 발화 끝 + 0.5 이하.
    words = _words(3, dur=1.0, char="가")
    cues = chunk_by_rate(words, lang="ko")
    last_end = cues[-1][1]
    speech_end = words[-1]["end"]
    assert last_end <= speech_end + config.CAPTION_TAIL_HOLD_MAX_SEC + 1e-9


def test_chunk_by_rate_hard_floor_merges_short():
    # 아주 짧은 발화(0.05s) 8단어: 앞 청크 표시창이 플로어 미만 → 병합되어 하한 이상만 남는다.
    words = _words(8, dur=0.05, char="가나다라마")
    cues = chunk_by_rate(words, lang="ko")
    assert all(e - s >= config.CAPTION_MIN_DISPLAY_FLOOR_SEC - 1e-9 for s, e, _t in cues)


def test_chunk_by_rate_splits_coarse_korean_event():
    # 성긴 워드 이벤트 1개가 문장 전체(9어절)를 담고 있어도 통짜로 두지 않고 여러 청크로 쪼갠다.
    words = [{"text": "마치 우리가 눈으로 보듯 디자인과 맥락까지 통째로 파악하는 거죠", "start": 0.0, "end": 4.0}]
    cues = chunk_by_rate(words, lang="ko")
    assert len(cues) >= 2  # 문장 통짜(1개) 아님
    # 각 청크 어절 수는 상한 이하.
    for _s, _e, t in cues:
        assert len(t.split(" ")) <= config.CAPTION_CHUNK_MAX["ko"]


def test_chunk_text_by_rate_splits_full_narration():
    # 워드 타임스탬프 없음 → 컷 나레이션 문자열을 어절 청킹. 통짜 1개가 아니어야 함.
    text = "마치 우리가 눈으로 보듯 디자인과 맥락까지 통째로 파악하는 거죠"
    cues = chunk_text_by_rate(text, 10.0, 14.0, lang="ko")
    assert len(cues) >= 2
    assert cues[0][0] >= 10.0
    # 표시 시간은 컷 구간 + tail_hold 이내(오디오 지연 없음).
    assert cues[-1][1] <= 14.0 + config.CAPTION_TAIL_HOLD_MAX_SEC + 1e-9
    joined = " ".join(t for _s, _e, t in cues)
    assert "파악하는" in joined and "우리가" in joined  # 원문 보존


def test_chunk_text_by_rate_empty():
    assert chunk_text_by_rate("", 0.0, 3.0) == []


def test_clamp_overlaps_removes_overlap():
    # 컷 경계 tail_hold 겹침: a 가 2.5 까지, b 는 2.0 시작 → a 끝을 2.0 으로 클램프(겹침 제거).
    out = clamp_overlaps([(0.0, 2.5, "a"), (2.0, 4.0, "b")])
    assert out == [(0.0, 2.0, "a"), (2.0, 4.0, "b")]


def test_clamp_overlaps_drops_empty_and_reversed():
    out = clamp_overlaps([(0.0, 1.0, "x"), (1.0, 1.0, "  "), (2.0, 1.5, "rev")])
    assert out == [(0.0, 1.0, "x")]  # 빈 텍스트·역전 큐 제거


def test_clamp_overlaps_no_two_captions_same_time():
    # 클램프 후 어떤 두 큐도 시간이 겹치지 않는다(한 시점에 자막 1개).
    out = clamp_overlaps([(0, 3, "a"), (2, 5, "b"), (4, 6, "c")])
    for i in range(len(out) - 1):
        assert out[i][1] <= out[i + 1][0]


def test_chunk_by_rate_en_uses_en_cps():
    # EN 은 CPS 가 높아(20) 같은 조건에서 더 많이 담을 수 있다(어절/단어 상한도 7).
    words = _words(10, dur=0.5, char="model")
    cues = chunk_by_rate(words, lang="en")
    assert len(cues[0][2].split(" ")) <= config.CAPTION_CHUNK_MAX["en"]


# ── ② 플랫폼별 자막 앵커 (DV8) ─────────────────────────────────
def test_platform_margin_v_per_platform():
    h = config.RENDER_HEIGHT
    assert platform_margin_v("shorts") == int(round(h * (1 - 0.70)))
    assert platform_margin_v("tiktok") == int(round(h * (1 - 0.62)))
    # 미지 플랫폼 → 세이프바텀 폴백.
    assert platform_margin_v("myspace") == int(h * config.SUBTITLE_SAFE_BOTTOM)
    # None → DEFAULT_PLATFORM.
    assert platform_margin_v(None) == platform_margin_v(config.DEFAULT_PLATFORM)


def test_build_ass_en_lang_font():
    ass = build_ass([(0, 4, "hi")], lang="en", platform="shorts")
    assert config.CAPTION_FONT["en"] in ass          # EN 폰트


def test_build_ass_center_band_puts_caption_in_bottom_bar():
    # center_band 기본: 자막은 하단 바 안(LETTERBOX_CAPTION_MARGIN_V), 제목은 상단 바 안.
    if config.LAYOUT_MODE == "center_band":
        ass = build_ass([(0, 4, "hi")], platform="shorts")
        assert f",{config.LETTERBOX_CAPTION_MARGIN_V}\n" in ass  # 플랫폼보다 레이아웃 우선
        # 본문 자막은 굵게 + 두꺼운 외곽선(눈에 잘 띄게).
        assert f"Default,{config.SUBTITLE_FONT_NAME},{config.SUBTITLE_FONT_SIZE}," in ass


def test_build_ass_platform_margin_when_full_bleed(monkeypatch):
    # full_bleed 로 두면 플랫폼 앵커 MarginV 를 쓴다.
    monkeypatch.setattr(config, "LAYOUT_MODE", "full_bleed")
    ass = build_ass([(0, 4, "후크")], platform="shorts")
    assert f",{platform_margin_v('shorts')}\n" in ass
