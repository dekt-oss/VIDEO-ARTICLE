"""한국어 자막 뜻 단위 끊기(config.CAPTION_PHRASE_BREAKS) — 2026-10-24 운영자 "자막 보여지는것도 어절별로 자연스럽게 끊어내"."""

from __future__ import annotations

import pytest

from engine import config, subtitles


@pytest.fixture
def phrase_on(monkeypatch):
    monkeypatch.setattr(config, "CAPTION_PHRASE_BREAKS", True)


@pytest.mark.parametrize("text, want", [
    ("사케 병에 적힌 지역 이름, 아무 양조장이나 붙여도 될까요?",
     ["사케 병에", "적힌 지역 이름", "아무 양조장이나", "붙여도 될까요?"]),
    ("안 돼요. 그 지역 술만의 특징이 뚜렷해야 하고, 지역에서 신청하면 일본 국세청이 지정해 줘야 해요.",
     ["안 돼요", "그 지역 술만의 특징이", "뚜렷해야 하고", "지역에서", "신청하면", "일본 국세청이", "지정해 줘야 해요"]),
    ("이렇게 지정된 이름을 지리적 표시라고 하는데요, 그 이름은 그 지역 술만 쓸 수 있어요.",
     ["이렇게", "지정된 이름을", "지리적 표시라고", "하는데요", "그 이름은", "그 지역 술만", "쓸 수 있어요"]),
    ("먹을 수 있는 건 생각보다 많지 않아요.", ["먹을 수 있는 건", "생각보다", "많지 않아요"]),
    ("위스키 좀 마신다는 사람들, 비싼 위스키에 일부러 물을 떨어뜨려요.",
     ["위스키 좀 마신다는 사람들", "비싼 위스키에", "일부러 물을", "떨어뜨려요"]),
    ("위스키의 스모키한 향은, 과이아콜이라는 작은 분자에서 나와요.",
     ["위스키의 스모키한 향은", "과이아콜이라는 작은 분자에서", "나와요"]),
    ("술은 그 표면부터 먼저 마시게 되니까, 향이 더 잘 느껴지는 거죠.",
     ["술은 그 표면부터", "먼저 마시게 되니까", "향이", "더 잘 느껴지는 거죠"]),
])
def test_breaks_at_meaning_boundaries(phrase_on, text, want):
    assert subtitles.phrase_groups(text) == want


def test_never_splits_modifier_from_its_noun_or_bound_noun(phrase_on):
    for text in ["그 지역만의 특성이 확립된 술은 산지가 신청하고 국세청장관이 지정하면 그 산지 이름을 독점해서 쓸 수 있습니다.",
                 "다음에 사케 고를 땐, 라벨 속 지역 이름이 지리적 표시인지 한번 확인해 보세요.",
                 "수입 맥주는 왜 더 비쌀까요?"]:
        groups = subtitles.phrase_groups(text)
        assert " ".join(groups).replace(",", "").replace(".", "") == text.replace(",", "").replace(".", ""), "글자·순서는 그대로"
        for g in groups[:-1]:
            last = g.split()[-1]
            assert not subtitles._is_modifier(last), (g, groups)
        for a, b in zip(groups, groups[1:]):
            assert b.split()[0] not in subtitles._BOUND_NOUNS, (a, b)
        for g in groups:
            assert len(g.replace(" ", "")) <= config.CAPTION_PHRASE_MAX_CHARS or len(g.split()) == 1, (g, groups)


def test_bound_noun_check_is_exact_not_prefix(phrase_on):
    assert subtitles._break_score("병에", "적힌") > 0, "'적힌'은 의존 명사 '적'이 아니다"
    assert subtitles._break_score("고를", "수") < 0
    assert not subtitles._is_modifier("신청하면") and subtitles._is_modifier("확립된") and subtitles._is_modifier("쓸")


def test_cues_cover_the_narration_span_without_gaps(phrase_on):
    cues = subtitles.chunk_text_by_rate("그러다 2015년부터는 사케든 소주든, 모든 술로 넓어졌고요.", 10.0, 14.0)
    assert cues[0][0] == 10.0 and abs(cues[-1][1] - 14.0) < 1e-9
    for (s1, e1, _), (s2, _, _) in zip(cues, cues[1:]):
        assert abs(e1 - s2) < 1e-9
    assert all(e - s >= config.CAPTION_MIN_DISPLAY_FLOOR_SEC for s, e, _ in cues)


def test_short_lines_merge_without_crossing_sentences(phrase_on):
    """실측(대본 v2 미리보기): 0.7초 미만 줄을 앞 줄에 무조건 붙였더니 '안 돼요 그 지역 술만의 특징이'·'생기면서 와인과'가 됐다."""
    c = subtitles.chunk_text_by_rate("안 돼요. 그 지역 술만의 특징이 뚜렷해야 하고, 지역에서 신청하면 일본 국세청이 지정해 줘야 해요.", 0.0, 6.4)
    texts = [t for _, _, t in c]
    assert texts[0] == "안 돼요", texts
    c2 = subtitles.chunk_text_by_rate("세계무역기구가 생기면서, 와인과 증류주 산지 이름은 꼭 보호하기로 했거든요.", 0.0, 5.0)
    assert not any(t.endswith("와인과") for _, _, t in c2), [t for _, _, t in c2]


def test_off_by_default_keeps_old_word_count_chunks(monkeypatch):
    monkeypatch.setattr(config, "CAPTION_PHRASE_BREAKS", False)
    called = []
    monkeypatch.setattr(subtitles, "chunk_text_by_phrase", lambda *a, **k: called.append(1) or [])
    cues = subtitles.chunk_text_by_rate("그 지역만의 특성이 확립된 술은", 0.0, 3.0)
    assert not called and cues, "꺼져 있으면 예전 경로(어절 수 기준) — 논문·리포트 자막은 바뀌지 않는다"
    assert all(len(c[2].split()) <= config.CAPTION_CHUNK_MAX["ko"] for c in cues)


def test_drinks_render_turns_phrase_breaks_on():
    src = (__import__("pathlib").Path(__file__).resolve().parents[1] / "engine" / "drinks_render.py").read_text(encoding="utf-8")
    assert "config.CAPTION_PHRASE_BREAKS = True" in src
