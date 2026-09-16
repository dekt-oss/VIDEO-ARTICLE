"""논문 원문 확보 순수 로직 (작업명세서_설명엔진_v2 §3 Phase 1 DoD).

여기 있는 검사는 전부 네트워크 없이 돈다. 확보 체인의 I/O 는 실측 스크립트가 실제로
돌려 봤고(docs/실측_0ABC_설명엔진.md), 이 파일이 지키는 것은 **판정과 파싱**이다:
depth 를 코드가 정하는가 · 페이지를 지어내지 않는가 · 참고문헌을 앞에서 자르지 않는가.
"""

from __future__ import annotations

from engine import config, paper_source as ps


# ─ 식별자 ─
def test_arxiv_id_from_external_id_and_url():
    assert ps.parse_arxiv_id("arxiv:2606.03136") == "2606.03136"
    assert ps.parse_arxiv_id("arxiv:2606.03136v2") == "2606.03136"
    assert ps.parse_arxiv_id(None, "http://arxiv.org/abs/2606.03136v1") == "2606.03136"
    # arXiv DOI 도 arXiv 로 간다 — 그쪽 HTML 이 출판사 PDF 보다 깨끗하다.
    assert ps.parse_arxiv_id("10.48550/arXiv.2401.00001") == "2401.00001"
    assert ps.parse_arxiv_id("10.1126/science.ael4188") is None


def test_normalize_doi_strips_url_and_case():
    assert ps.normalize_doi("10.1126/Science.AEL4188") == "10.1126/science.ael4188"
    assert ps.normalize_doi(None, "https://doi.org/10.1186/s12887-026-07516-9") \
        == "10.1186/s12887-026-07516-9"
    assert ps.normalize_doi("arxiv:2606.03136") is None


# ─ 파싱 ─
def test_html_to_text_keeps_math_alttext():
    """수식을 통째로 버리면 메커니즘 설명의 핵심이 사라진다 — alttext 는 살린다."""
    html = ('<p>The rate is <math alttext="k = A e^{-E/RT}"><mi>k</mi></math> '
            'under load.</p><script>bad()</script>')
    out = ps.html_to_text(html)
    assert "k = A e^{-E/RT}" in out
    assert "bad()" not in out


def test_jats_body_preferred_over_abstract():
    xml = ("<article><front><abstract><p>초록 문장</p></abstract></front>"
           "<body><sec><p>본문 문장</p></sec></body></article>")
    assert "본문 문장" in ps.jats_to_text(xml)
    assert "초록 문장" not in ps.jats_to_text(xml)


def test_jats_falls_back_to_abstract_when_no_body():
    xml = "<article><front><abstract><p>초록 문장</p></abstract></front></article>"
    assert "초록 문장" in ps.jats_to_text(xml)


# ─ 참고문헌 절단 ─
def test_drop_references_cuts_only_near_the_end():
    body = "본문 " * 2000 + "\nReferences\n[1] Someone et al."
    out = ps.drop_references(body)
    assert "[1] Someone" not in out
    assert out.startswith("본문")


def test_drop_references_ignores_early_mention():
    """서론의 'References' 한 줄에 걸려 논문이 앞에서 잘리면 본문이 통째로 날아간다."""
    body = "머리말\nReferences\n" + "본문 " * 2000
    out = ps.drop_references(body)
    assert len(out) > 1000


# ─ depth 판정(코드가 정한다) ─
def test_classify_depth_is_decided_by_length():
    assert ps.classify_depth("") == "abstract_only"
    assert ps.classify_depth("a" * (config.PAPER_SOURCE_MIN_BODY_CHARS - 1)) == "abstract_only"
    assert ps.classify_depth("a" * config.PAPER_SOURCE_MIN_BODY_CHARS) == "partial_body"
    assert ps.classify_depth("a" * config.PAPER_SOURCE_FULLBODY_MIN_CHARS) == "full_body"


# ─ chunk / hash ─
def test_chunks_have_offsets_and_no_page_numbers():
    """페이지 번호를 만들지 않는다 — 없는 번호가 화면에 나가는 것이 K1 사고다."""
    chunks = ps.chunk_text("x" * 2500, size=1000)
    assert [c["chunk_id"] for c in chunks] == ["P001", "P002", "P003"]
    assert chunks[1]["char_start"] == 1000 and chunks[1]["char_end"] == 2000
    assert all("page" not in k for c in chunks for k in c)


def test_doc_hash_is_stable_and_content_addressed():
    assert ps.doc_hash("같은 글") == ps.doc_hash("같은 글")
    assert ps.doc_hash("같은 글") != ps.doc_hash("다른 글")


# ─ packet ─
def test_build_packet_marks_truncation_and_keeps_parse_error():
    paper = {"id": "p1", "external_id": "arxiv:1", "url": "u"}
    long_text = "본" * (config.PAPER_SOURCE_MAX_CHARS + 10)
    packet = ps.build_packet(paper, {"provider": "arxiv_html", "content_format": "html",
                                     "text": long_text})
    assert packet["truncated"] is True
    assert packet["char_count"] == config.PAPER_SOURCE_MAX_CHARS
    assert packet["source_depth"] == "full_body"

    failed = ps.build_packet(paper, {"provider": "arxiv_pdf", "content_format": "pdf",
                                     "text": "", "parse_error": "pdf_parse_failed"})
    assert failed["parse_error"] == "pdf_parse_failed"   # 실패를 숨기지 않는다
    assert failed["source_depth"] == "abstract_only"
    assert failed["doc_hash"] == ""


def test_fulltext_block_is_empty_without_text():
    """마커만 남기고 속을 비우면 '원문을 줬다'고 착각하게 된다."""
    empty = ps.build_packet({"id": "p"}, {"text": ""})
    assert ps.fulltext_block(empty) == ""

    packet = ps.build_packet({"id": "p"}, {"text": "본문", "provider": "pmc_xml"})
    block = ps.fulltext_block(packet)
    assert block.startswith(config.PAPER_SOURCE_MARKER)
    assert block.endswith(config.PAPER_SOURCE_END_MARKER)


def test_paper_and_report_markers_do_not_collide():
    """두 라인의 마커가 같으면 프롬프트 동기화 앵커가 서로를 오탐한다(D1)."""
    assert config.PAPER_SOURCE_MARKER != config.SOURCE_FULLTEXT_MARKER
