"""주류 C단계 카드뉴스 — 페이지 순서·출처 페이지·잘림·없는 글자(두부) 검사. ffmpeg·네트워크 없음."""
import pytest
from PIL import Image

from engine import drinks_cards as dc
from engine import drinks_render as dr

JOB = {"topic": {"title": "t"}, "claims": [{"claim_id": "c1"}],
       "sources": [{"publisher": "国税庁", "title": "酒類の地理的表示", "url": "https://www.nta.go.jp/x"}],
       "plan": {"pages": [{"position": 2, "role": "explain", "heading": "정미율", "body": "쌀을 깎은 비율", "claim_ids": ["c1"]},
                          {"position": 1, "role": "cover", "heading": "다이긴조"},
                          {"position": 3, "role": "checklist", "heading": "라벨에서 볼 것", "body": "지역 이름\n제조 지역"},
                          {"position": 4, "role": "source", "heading": "출처"}]}}


def test_pages_in_plan_order_at_card_size(tmp_path):
    r = dc.render_carousel(JOB, str(tmp_path / "p"))
    assert [f["position"] for f in r.files] == [1, 2, 3, 4]
    assert all(Image.open(f["path"]).size == (1080, 1350) for f in r.files)
    assert set(r.qa["warnings"]) <= {"glyph_missing"}, "잘림·순서 문제 없음(일본어 글꼴이 없는 환경만 두부 경고)"
    if dr._cjk_font(28) is None:
        assert r.qa["missing_glyphs"], "일본어 글꼴이 없으면 두부 글자를 경고로 올린다(조용히 넘기지 않는다)"
    else:
        assert r.qa["missing_glyphs"] == []


def test_missing_glyphs_are_detected_and_checkbox_is_a_shape():
    f = dr._font("body", 40)
    assert "☐" in dr.missing_glyphs(f, "☐ 한글")
    assert dr.missing_glyphs(f, "한글 ABC 123 → ·") == []


def test_overflow_is_reported_not_hidden(tmp_path):
    long = {**JOB, "plan": {"pages": [{"position": 1, "role": "explain", "heading": "제목 " * 40, "body": "본문 " * 400}]}}
    r = dc.render_carousel(long, str(tmp_path / "q"))
    assert r.qa["truncated_pages"] == [1] and "text_truncated" in r.qa["warnings"]


def test_page_limit(tmp_path):
    with pytest.raises(dr.RenderError):
        dc.render_carousel({**JOB, "plan": {"pages": [{"position": i, "role": "explain", "heading": "x"} for i in range(1, 14)]}},
                           str(tmp_path / "r"))
