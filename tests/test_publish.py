"""engine.publish 순수 로직 테스트 (업로드 제목/설명 조립 + 절단 + 공개상태 검증).

네트워크·DB 없이 순수 함수만 검증한다(youtube.upload_video·db 는 대상 아님).
"""

from engine import config
from engine.publish import (
    _truncate,
    _validate_privacy,
    build_upload_description,
    build_upload_title,
)


def _meta(**kw):
    base = {
        "paper": {
            "title": "PixelRAG: Seeing the Web",
            "venue": "arXiv",
            "published_date": "2026-06-01",
            "url": "https://arxiv.org/abs/xxxx",
            "authors": [{"name": "Jane Doe", "institution": "Stanford University"}],
        },
        "title_ko": "픽셀RAG: 웹을 보다",
        "upload_title_ko": "AI가 웹을 '눈'으로 본다고?",
        "upload_title_en": "An AI That Literally SEES the Web",
        "one_liner_ko": "AI가 웹을 이미지처럼 본다",
        "one_liner_en": "The AI reads the web as pixels",
    }
    base.update(kw)
    return base


def test_title_prefers_upload_title_ko():
    assert build_upload_title(_meta(), "ko") == "AI가 웹을 '눈'으로 본다고?"


def test_title_prefers_upload_title_en():
    assert build_upload_title(_meta(), "en") == "An AI That Literally SEES the Web"


def test_title_falls_back_to_title_ko_then_paper_title():
    # 업로드 제목 없음 → 번역제목 폴백(ko)
    m = _meta(upload_title_ko=None)
    assert build_upload_title(m, "ko") == "픽셀RAG: 웹을 보다"
    # 번역제목도 없음 → 원제 폴백
    m2 = _meta(upload_title_ko=None, title_ko=None)
    assert build_upload_title(m2, "ko") == "PixelRAG: Seeing the Web"
    # en: 업로드 제목 없음 → 원제 폴백
    m3 = _meta(upload_title_en=None)
    assert build_upload_title(m3, "en") == "PixelRAG: Seeing the Web"


def test_title_truncated_to_youtube_limit():
    long = "가" * 250
    out = build_upload_title(_meta(upload_title_ko=long), "ko")
    assert len(out) <= config.YOUTUBE_TITLE_MAX


def test_description_uses_attribution_caption_with_teaser():
    desc = build_upload_description(_meta(), "ko")
    assert "AI가 웹을 이미지처럼 본다" in desc          # teaser=one_liner_ko
    assert "📄 원논문: PixelRAG: Seeing the Web (arXiv, 2026)" in desc
    assert "🔗 https://arxiv.org/abs/xxxx" in desc
    assert "#논문" in desc


def test_description_en_uses_english_teaser_and_hashtags():
    desc = build_upload_description(_meta(), "en")
    assert "The AI reads the web as pixels" in desc
    assert "📄 Paper: PixelRAG: Seeing the Web" in desc
    assert "#research" in desc


def test_description_truncated_to_5000():
    m = _meta(one_liner_ko="설명 " * 4000)
    desc = build_upload_description(m, "ko")
    assert len(desc) <= config.YOUTUBE_DESC_MAX


def test_truncate_prefers_word_boundary():
    out = _truncate("hello world foobar", 12)
    assert out == "hello world"  # 공백 경계에서 절단(단어 중간 아님)


def test_validate_privacy_defaults_and_allows():
    assert _validate_privacy("public") == "public"
    assert _validate_privacy("UNLISTED") == "unlisted"
    assert _validate_privacy(None) == config.YOUTUBE_DEFAULT_PRIVACY
    assert _validate_privacy("bogus") == config.YOUTUBE_DEFAULT_PRIVACY


def test_description_strips_html_markup_from_title():
    # YouTube invalidDescription 재현: OpenAlex 제목의 <i>..</i> 가 설명란에 들어가면 400.
    m = _meta(paper={
        "title": "Health Outcomes After the <i>Dobbs</i> Decision",
        "venue": "Hospital Pediatrics", "published_date": "2025-01-01",
        "url": "https://doi.org/10.1542/hpeds.2025-009017", "authors": [],
    }, upload_title_ko=None, title_ko=None, one_liner_ko="낙태 제한과 청소년 건강")
    desc = build_upload_description(m, "ko")
    assert "<" not in desc and ">" not in desc      # 홑화살괄호 완전 제거
    assert "Dobbs Decision" in desc                  # 태그만 제거, 내용은 보존


def test_title_strips_html_markup_on_paper_fallback():
    m = _meta(upload_title_ko=None, title_ko=None,
              paper={"title": "A <sub>2</sub> study <i>in vivo</i>", "url": "x", "authors": []})
    out = build_upload_title(m, "ko")
    assert "<" not in out and ">" not in out
    assert "study" in out
