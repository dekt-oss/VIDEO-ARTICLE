"""순수 로직 단위 테스트 (네트워크/LLM 불필요).

수집 파이프라인의 결정적 부분만 검증한다.
"""

from datetime import date

from engine.models import Paper
from engine.pipeline import attach_buzz, dedupe, primary_filter
from engine.sources.openalex import reconstruct_abstract
from engine.util import (
    arxiv_external_id,
    collection_window,
    extract_external_ids,
    normalize_doi,
    normalize_title,
)


def test_reconstruct_abstract_orders_words():
    inv = {"Hello": [0], "brave": [2], "world": [1]}
    assert reconstruct_abstract(inv) == "Hello world brave"
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""


def test_extract_external_ids_doi_and_arxiv():
    text = (
        "see https://arxiv.org/abs/2401.01234v2 and "
        "https://doi.org/10.1038/s41586-020-2649-2 and arXiv: 2312.99999"
    )
    ids = extract_external_ids(text)
    assert "arxiv:2401.01234" in ids
    assert "arxiv:2312.99999" in ids
    assert "10.1038/s41586-020-2649-2" in ids


def test_normalize_doi_strips_prefixes():
    assert normalize_doi("https://doi.org/10.1/AbC") == "10.1/abc"
    assert normalize_doi("doi:10.2/x).") == "10.2/x"


def test_arxiv_external_id_drops_version():
    assert arxiv_external_id("2401.01234v3") == "arxiv:2401.01234"


def test_normalize_title():
    assert normalize_title("A Study, of Things!") == "a study of things"


def test_collection_window_length():
    start, end = collection_window(5)
    assert (end - start).days == 4  # 5일 윈도우 = 종료일 포함 5일


def _p(ext, title="t", abstract="a" * 200, source="openalex", **kw):
    return Paper(external_id=ext, source=source, title=title, abstract=abstract, **kw)


def test_dedupe_by_external_id():
    a = _p("10.1/x", abstract="short")
    b = _p("10.1/x", abstract="a much longer abstract that should win" * 5)
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0].abstract.startswith("a much longer")  # 더 긴 초록 보존


def test_dedupe_by_title_author():
    a = _p("arxiv:1", title="Same Title", authors=[{"name": "Kim"}])
    b = _p("10.5/y", title="same title", authors=[{"name": "kim"}])
    out = dedupe([a, b])
    assert len(out) == 1


def test_attach_buzz_matches_external_id():
    papers = [_p("10.1/x"), _p("arxiv:1")]
    attach_buzz(papers, {"10.1/x": {"total": 42}})
    assert papers[0].buzz_raw == {"total": 42}
    assert papers[1].buzz_raw is None


def test_primary_filter_requires_abstract_and_sorts_by_buzz(stub_lang_detect):
    short = _p("10.1/short", abstract="too short")
    big_buzz = _p("10.1/buzz", buzz_raw={"total": 100})
    small_buzz = _p("10.1/small", buzz_raw={"total": 1})
    out = primary_filter([small_buzz, short, big_buzz])
    exts = [p.external_id for p in out]
    assert "10.1/short" not in exts          # 초록 미달 제외
    assert exts.index("10.1/buzz") < exts.index("10.1/small")  # buzz 높은 순


# ── 언어 게이트 ─────────────────────────────────────────────
# ★ 이 세 건은 CI 첫 실행이 드러낸 구멍을 메운다. 언어 게이트에 테스트가 **한 건도** 없어서,
#   샌드박스(langdetect 미설치)에서는 게이트가 통째로 건너뛰어지는데도 아무도 몰랐다.
#   탐지기를 직접 갈아끼워 세 갈래(대상 언어·비대상 언어·판별 불가)를 모두 고정한다.
def _filtered_ids(monkeypatch, detected):
    """탐지기가 `detected` 를 돌려줄 때 통과하는 external_id 목록."""
    from engine import pipeline

    monkeypatch.setattr(pipeline, "_detect", lambda _text: detected)
    return [p.external_id for p in primary_filter([_p("10.1/x")])]


def test_language_gate_passes_target_languages(monkeypatch):
    for lang in ("en", "ko"):
        assert _filtered_ids(monkeypatch, lang) == ["10.1/x"], lang


def test_language_gate_drops_other_languages(monkeypatch):
    assert _filtered_ids(monkeypatch, "de") == []


def test_language_gate_passes_when_detection_fails(monkeypatch):
    """판별 불가는 보수적으로 통과시킨다 — langdetect 미설치 환경이 여기로 떨어진다."""
    assert _filtered_ids(monkeypatch, None) == ["10.1/x"]
