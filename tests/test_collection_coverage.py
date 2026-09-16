"""수집 커버리지 v2 순수 로직 테스트 — 플래그십 판정·바이패스·진단·언론 DOI 매칭.

네트워크·DB 없이 순수 함수만 검증한다.
"""

from datetime import date

from engine import config
from engine.collect import _route_of
from engine.diagnose import classify
from engine.models import Paper
from engine.pipeline import primary_filter
from engine.sources.openalex import _build_paper, _source_id, _FLAGSHIP_IDS
from engine.sources.press import (
    match_to_paper,
    normalize_title_for_match,
    resolve_press_item,
    title_similarity,
)


# ── 플래그십 판정 (openalex) ──
def test_flagship_ids_loaded():
    assert "S137773608" in _FLAGSHIP_IDS  # Nature
    assert "S3880285" in _FLAGSHIP_IDS    # Science


def test_source_id_shortens_url():
    assert _source_id({"primary_location": {"source": {"id": "https://openalex.org/S3880285"}}}) == "S3880285"
    assert _source_id({}) is None


def test_build_paper_flags_flagship_and_extracts_fields():
    work = {
        "id": "https://openalex.org/W123", "doi": "https://doi.org/10.1126/science.aea9708",
        "title": "LHS 1140 b", "type": "article", "publication_date": "2026-07-06",
        "created_date": "2026-07-16",
        "primary_location": {"source": {"id": "https://openalex.org/S3880285", "display_name": "Science"}},
        "authorships": [], "abstract_inverted_index": {"An": [0], "exoplanet": [1]},
    }
    p = _build_paper(work)
    assert p is not None
    assert p.is_flagship is True and p.source_id == "S3880285"
    assert p.external_id == "10.1126/science.aea9708" and p.doi == p.external_id
    assert p.work_type == "article" and p.openalex_id == "W123"
    assert p.source_created_date == date(2026, 7, 16)


def test_build_paper_skips_no_doi():
    assert _build_paper({"title": "x", "primary_location": {}}) is None


# ── 프리스티지 바이패스 ──
def test_flagship_bypasses_cutoff(stub_lang_detect):
    flagship = Paper(external_id="doi:flag", source="openalex", title="Flagship",
                     abstract="a" * 100, is_flagship=True)  # buzz 없음
    filler = [Paper(external_id=f"d{i}", source="openalex", title=f"t{i}",
                    abstract="b" * 100, buzz_raw={"total": i + 1})
              for i in range(config.SCORE_CUTOFF_N + 30)]
    cut = primary_filter([flagship] + filler)
    assert flagship in cut                         # buzz 0 이어도 진입 보장
    assert len(cut) == config.SCORE_CUTOFF_N + 1    # 비플래그십 N + 플래그십 1


def test_route_of():
    assert _route_of(Paper(external_id="x", source="openalex", title="", abstract="", is_flagship=True)) == "flagship_openalex"
    assert _route_of(Paper(external_id="x", source="openalex", title="", abstract="")) == "main_openalex"
    assert _route_of(Paper(external_id="x", source="arxiv", title="", abstract="")) == "arxiv"
    assert _route_of(Paper(external_id="x", source="hn", title="", abstract="")) == "buzz"


# ── 진단 분류 ──
def test_diagnose_classify():
    assert classify({"lookup_status": "not_found"}).startswith("not_in_openalex")
    assert classify({"lookup_status": "error: x"}).startswith("lookup_error")
    assert "index_lag" in classify({"lookup_status": "found", "created_date": "2026-07-16",
                                    "publication_date": "2026-07-06", "in_flagship_config": True, "type": "article"})
    assert "source_mapping" in classify({"lookup_status": "found", "created_date": "2026-07-06",
                                         "publication_date": "2026-07-06", "in_flagship_config": False,
                                         "openalex_source_id": "S9"})
    assert "type_filter" in classify({"lookup_status": "found", "created_date": "2026-07-06",
                                      "publication_date": "2026-07-06", "in_flagship_config": True, "type": "editorial"})


# ── 언론 DOI 매칭 ──
def test_title_similarity_and_normalize():
    assert normalize_title_for_match("A Novel Method, for X!") == "a novel method for x"
    assert title_similarity("A Novel Method for X", "a novel method, for X!") == 1.0
    assert title_similarity("Cats", "Quantum gravity") < 0.3


def test_resolve_press_item_stages():
    assert resolve_press_item({"url": "https://doi.org/10.1126/science.aea9708"})[0] == "10.1126/science.aea9708"
    assert resolve_press_item({"url": "https://arxiv.org/abs/2401.01234"})[0] == "arxiv:2401.01234"
    assert resolve_press_item({"title": "no id", "url": "https://phys.org/x", "summary": "y"})[0] is None


def test_match_to_paper_threshold_and_author_year():
    papers = [Paper(external_id="doi:m", source="openalex", title="A Novel Method for X",
                    abstract="", authors=[{"name": "Jane Doe"}], published_date=date(2026, 7, 1))]
    # 유사도·연도·저자 모두 충족 → 매칭
    ext, sim = match_to_paper({"title": "A novel method for X", "year": "2026", "first_author": "Jane Doe"}, papers)
    assert ext == "doi:m" and sim >= config.PRESS_TITLE_SIMILARITY_MIN
    # 연도 불일치 → 매칭 실패
    assert match_to_paper({"title": "A novel method for X", "year": "2020", "first_author": "Jane Doe"}, papers)[0] is None
    # 제목 다름 → 실패
    assert match_to_paper({"title": "Unrelated topic entirely", "year": "2026"}, papers)[0] is None
