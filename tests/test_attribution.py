"""engine.attribution 순수 로직 테스트 (출처 블록 + 발행 캡션)."""

from engine.attribution import build_publish_caption, build_source


def _paper(**kw):
    base = {
        "title": "PixelRAG: Seeing the Web",
        "venue": "arXiv",
        "published_date": "2026-06-01",
        "url": "https://arxiv.org/abs/xxxx",
        "authors": [
            {"name": "Jane Doe", "institution": "Stanford University"},
            {"name": "John Roe", "institution": "Stanford University"},
            {"name": "A B", "institution": "MIT"},
        ],
    }
    base.update(kw)
    return base


def test_build_source_extracts_names_institutions_year():
    s = build_source(_paper())
    assert s["year"] == "2026"
    assert s["authors"] == ["Jane Doe", "John Roe", "A B"]
    assert s["institutions"] == ["Stanford University", "MIT"]  # 중복 제거·순서 보존
    assert s["url"].startswith("https://")


def test_build_source_safe_on_missing():
    s = build_source({})
    assert s == {"title": "", "venue": "", "year": "", "authors": [], "institutions": [], "url": ""}


def test_build_source_authors_without_institution():
    s = build_source({"authors": [{"name": "Solo"}], "published_date": None})
    assert s["authors"] == ["Solo"]
    assert s["institutions"] == []
    assert s["year"] == ""


def test_publish_caption_ko_has_source_link_hashtags():
    cap = build_publish_caption(build_source(_paper()), teaser="AI가 웹을 본다", lang="ko")
    assert "AI가 웹을 본다" in cap
    assert "📄 원논문: PixelRAG: Seeing the Web (arXiv, 2026)" in cap
    assert "🏛️ Stanford University · MIT" in cap  # 기관 우선
    assert "🔗 https://arxiv.org/abs/xxxx" in cap
    assert "#논문" in cap


def test_publish_caption_en_and_author_fallback():
    src = build_source({"title": "T", "url": "u", "authors": [{"name": "Solo"}]})
    cap = build_publish_caption(src, lang="en")
    assert "📄 Paper: T" in cap
    assert "🏛️ Solo" in cap          # 기관 없으면 저자
    assert "#research" in cap


def test_publish_caption_venue_fallback_when_no_author():
    src = build_source({"title": "T", "venue": "Nature", "url": "u"})
    cap = build_publish_caption(src, lang="ko")
    assert "🏛️ Nature" in cap        # 기관·저자 없으면 게재처
