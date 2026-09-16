"""engine.report_publish 순수 로직 테스트 (업로드 제목/설명 조립 + 절단 + 공개상태).

네트워크·DB 없이 순수 함수만 검증한다(youtube.upload_video·report_db 는 대상 아님).
논문 tests/test_publish.py 의 report 미러.
"""

from engine import config
from engine.report_publish import (
    _truncate,
    _validate_privacy,
    build_upload_description,
    build_upload_title,
)


def _meta(**kw):
    base = {
        "report": {
            "title": "SK하이닉스 목표가 330만원 유지",
            "broker": "현대차증권",
            "analyst": "노근창",
            "company": "SK하이닉스",
            "theme": "메모리반도체",
            "opinion": "BUY",
            "target_price": 3300000,
            "report_url": "https://example.com/report/123",
        },
        "title_ko": "SK하이닉스 목표가 330만원",
        "upload_title_ko": "SK하이닉스 목표가 330만원… 공급구조가 바뀌었다",
        "upload_title_en": "SK Hynix target raised to 3.3M won",
        "one_liner_ko": "AI 사이클로 공급구조가 바뀌며 목표가가 제시됐다",
        "one_liner_en": "A supply-dynamics shift sets the target",
    }
    base.update(kw)
    return base


def test_title_prefers_upload_title_ko():
    assert build_upload_title(_meta(), "ko") == "SK하이닉스 목표가 330만원… 공급구조가 바뀌었다"


def test_title_prefers_upload_title_en():
    assert build_upload_title(_meta(), "en") == "SK Hynix target raised to 3.3M won"


def test_title_falls_back_to_title_ko_then_report_title():
    m = _meta(upload_title_ko=None)
    assert build_upload_title(m, "ko") == "SK하이닉스 목표가 330만원"     # 번역제목 폴백
    m2 = _meta(upload_title_ko=None, title_ko=None)
    assert build_upload_title(m2, "ko") == "SK하이닉스 목표가 330만원 유지"  # 원제 폴백
    m3 = _meta(upload_title_en=None)
    assert build_upload_title(m3, "en") == "SK하이닉스 목표가 330만원 유지"  # en 원제 폴백


def test_title_truncated_to_youtube_limit():
    long = "가" * 250
    out = build_upload_title(_meta(upload_title_ko=long), "ko")
    assert len(out) <= config.YOUTUBE_TITLE_MAX


def test_title_strips_html_markup():
    m = _meta(upload_title_ko=None, title_ko=None,
              report={"title": "A <i>study</i> on <b>rates</b>", "broker": "X", "report_url": "u"})
    out = build_upload_title(m, "ko")
    assert "<" not in out and ">" not in out
    assert "study" in out


def test_description_uses_report_caption_with_teaser_source_and_disclaimer():
    desc = build_upload_description(_meta(), "ko")
    assert "AI 사이클로 공급구조가 바뀌며 목표가가 제시됐다" in desc   # teaser=one_liner_ko
    assert "현대차증권" in desc                                      # 출처(broker)
    assert "https://example.com/report/123" in desc                  # 링크
    assert config.REPORT_DISCLAIMER_TEXT in desc                     # 면책 고정
    assert "#증권" in desc                                           # 해시태그


def test_description_en_uses_english_teaser_and_disclaimer():
    desc = build_upload_description(_meta(), "en")
    assert "A supply-dynamics shift sets the target" in desc
    assert "Not investment advice" in desc
    assert "#stocks" in desc


def test_description_truncated_to_5000():
    m = _meta(one_liner_ko="설명 " * 4000)
    desc = build_upload_description(m, "ko")
    assert len(desc) <= config.YOUTUBE_DESC_MAX


def test_validate_privacy_defaults_and_allows():
    assert _validate_privacy("public") == "public"
    assert _validate_privacy("UNLISTED") == "unlisted"
    assert _validate_privacy(None) == config.YOUTUBE_DEFAULT_PRIVACY
    assert _validate_privacy("bogus") == config.YOUTUBE_DEFAULT_PRIVACY


# ── 채널 통합 M2: 소재 분류 파생 (docs/specs/20260730-report-merge-into-paper-ko.md §3-1) ──

def test_derive_content_type_entity_when_ticker_present():
    from engine.report_publish import derive_content_type

    assert derive_content_type({"ticker": "005930", "theme": "메모리반도체"}) == "entity"


def test_derive_content_type_entity_when_company_present():
    from engine.report_publish import derive_content_type

    assert derive_content_type({"ticker": None, "company": "LG전자"}) == "entity"


def test_derive_content_type_industry_for_theme_only():
    """실제 수집 데이터의 지배적 형태 — theme 만 있고 ticker/company 는 비어 있다."""
    from engine.report_publish import derive_content_type

    assert derive_content_type({"ticker": None, "company": None, "theme": "로봇"}) == "industry"


def test_derive_content_type_ignores_fact_sheet_company_trap():
    """fact_sheet.company 는 테마명도 담는다 — 그걸로 파생하면 전부 entity 가 된다(§1-1).

    파생은 reports 컬럼만 본다. fact_sheet 가 섞여 들어와도 결과가 바뀌면 안 된다.
    """
    from engine.report_publish import derive_content_type

    report_like = {"ticker": None, "company": None, "theme": "시황",
                   "fact_sheet": {"company": "시황"}}
    assert derive_content_type(report_like) == "industry"


def test_derive_content_type_treats_blank_strings_as_empty():
    from engine.report_publish import derive_content_type

    assert derive_content_type({"ticker": "  ", "company": ""}) == "industry"
