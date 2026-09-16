"""전문 주입 회귀 가드 (작업지시서 영상엔진품질 v3 §11-1 · §0-1 #17).

왜 이 파일이 있는가: "초안·세부지시는 전체를 읽고 만들라"는 지시가 **이미 한 번 조용히
누락된 전력**이 있다. 프롬프트를 나중에 누가 다듬다가 전문 구간이 빠져도 아무도 모른다.
그래서 마커의 존재를 CI 가 검사한다 — 빠지면 빌드가 깨진다.

여기 있는 검사는 전부 네트워크 없이 돈다(FixtureAriaClient).
"""

from __future__ import annotations

import pytest

from engine import config, report_factsheet, report_source
from engine.aria.client import FixtureAriaClient

RESEARCH_REPORT = {
    "external_id": "aria_research:4902",
    "title": "[LG전자] 강해진 이익 체력과 신사업 가속화",
    "broker": "하나증권",
    "company": "LG전자",
    "summary": "[하나증권] [LG전자] 강해진 이익 체력과 신사업 가속화 (company)",
}
SIGNAL_REPORT = {
    "external_id": "aria_signal:4975",
    "title": "[장 중 시황] 빅테크 CapEx와 디레버리징 막바지 인식",
    "broker": "대신 전략. 돌직구",
    "summary": "코스피 18.50% 급등",
}


@pytest.fixture()
def client() -> FixtureAriaClient:
    return FixtureAriaClient()


# ── ① 마커 계약 — 이 검사가 §11-1 의 핵심이다 ────────────────────────────
def test_factsheet_prompt_carries_fulltext_marker(client):
    """전문이 확보되면 추출 프롬프트에 <<FULL_SOURCE>> 구간이 **반드시** 들어간다."""
    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    prompt = report_factsheet.factsheet_user_prompt(RESEARCH_REPORT, packet)

    assert config.SOURCE_FULLTEXT_MARKER in prompt
    assert config.SOURCE_FULLTEXT_END_MARKER in prompt
    # 마커만 있고 속이 비면 "전문을 줬다"는 착각이 된다 — 실제 본문이 들어갔는지 본다.
    assert "AI 데이터센터 냉각 솔루션" in prompt
    assert "목표주가 26만원" in prompt


def test_factsheet_system_prompt_instructs_to_use_fulltext():
    """시스템 프롬프트가 전문을 근거로 삼으라고 명시한다(요약만 보고 답하지 말 것)."""
    assert config.SOURCE_FULLTEXT_MARKER in report_factsheet.FACTSHEET_SYSTEM
    assert "요약만 보고 답하지 마라" in report_factsheet.FACTSHEET_SYSTEM


def test_empty_fulltext_leaves_no_marker():
    """전문을 못 구했으면 마커도 없다 — 빈 구간으로 '준 척'하지 않는다."""
    packet = report_source.build_packet(RESEARCH_REPORT, "")
    assert report_source.fulltext_block(packet) == ""
    prompt = report_factsheet.factsheet_user_prompt(RESEARCH_REPORT, packet)
    assert config.SOURCE_FULLTEXT_MARKER not in prompt


# ── ② 원문 확보 경로 — ARIA 두 도구가 실제로 불린다 ──────────────────────
def test_research_fulltext_is_reachable(client):
    """get_research(id).content_raw 가 전문으로 들어온다(Phase 0 §1-3 이 확인한 경로)."""
    text, url = report_source.fetch_fulltext(RESEARCH_REPORT, client)
    assert len(text) > 2000
    assert "2Q26 Review" in text
    assert url.endswith(".pdf")


def test_signal_fulltext_falls_back_to_raw_content(client):
    """텔레그램 계열은 get_signal(id).raw_content — 없으면 빈 문자열이지 예외가 아니다."""
    text, _ = report_source.fetch_fulltext(SIGNAL_REPORT, client)
    assert isinstance(text, str)


def test_unknown_external_id_is_not_an_error(client):
    """형식 밖 external_id 는 조용히 요약 경로로 내려간다 — 파이프라인을 세우지 않는다."""
    text, _ = report_source.fetch_fulltext({"external_id": "manual-entry"}, client)
    assert text == ""


def test_fetch_failure_degrades_instead_of_raising():
    """ARIA 호출이 터져도 예외를 올리지 않는다(요약 기반으로 계속)."""
    class Broken:
        def get_research(self, research_id: int):
            raise RuntimeError("ARIA down")

    text, _ = report_source.fetch_fulltext(RESEARCH_REPORT, Broken())
    assert text == ""


# ── ③ source_depth 판정 — 코드가 글자 수로 정한다(자기보고 불신) ─────────
def test_depth_is_classified_by_length(client):
    assert report_source.classify_depth("") == "summary_only"
    assert report_source.classify_depth("가" * 100) == "partial_text"
    assert report_source.classify_depth("가" * config.SOURCE_FULLTEXT_MIN_CHARS) == "full_text"
    assert report_source.classify_depth("가" * 100) in config.SOURCE_DEPTHS


def test_research_packet_reaches_full_text(client):
    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    assert packet["source_depth"] == "full_text"
    assert packet["source_type"] == "research"
    assert packet["truncated"] is False
    assert packet["chunks"] and packet["chunks"][0]["chunk_id"] == "C001"


def test_packet_marks_truncation(monkeypatch):
    """상한에 걸려 잘리면 그 사실을 숨기지 않는다."""
    monkeypatch.setattr(config, "SOURCE_FULLTEXT_MAX_CHARS", 100)
    packet = report_source.build_packet(RESEARCH_REPORT, "가" * 500)
    assert packet["truncated"] is True
    assert packet["char_count"] == 100
    assert "잘렸다" in report_source.fulltext_block(packet)


def test_chunks_carry_no_page_numbers(client):
    """페이지 번호를 지어내지 않는다 — PDF 를 우리가 파싱하지 않기 때문(§4-1)."""
    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    for chunk in packet["chunks"]:
        assert "page_start" not in chunk
        assert "page_end" not in chunk


def test_injection_can_be_switched_off(monkeypatch, client):
    """SOURCE_INJECT_FULLTEXT=False 면 네트워크도 타지 않고 요약 경로로 간다."""
    monkeypatch.setattr(config, "SOURCE_INJECT_FULLTEXT", False)
    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    assert packet["text"] == ""
    assert packet["source_depth"] == "summary_only"


# ── ④ ARIA 클라이언트가 두 도구를 갖췄는가(구현 누락 회귀 방지) ──────────
def test_all_aria_clients_expose_research_tools():
    """Phase 0 이 찾아낸 결함: 클라이언트에 search_research/get_research 가 없었다."""
    from engine.aria.client import HttpAriaClient, McpAriaClient

    for cls in (McpAriaClient, HttpAriaClient, FixtureAriaClient):
        assert hasattr(cls, "search_research"), f"{cls.__name__} 에 search_research 없음"
        assert hasattr(cls, "get_research"), f"{cls.__name__} 에 get_research 없음"


def test_search_research_filters_by_status(client):
    selected = client.search_research(status="selected", limit=50)["items"]
    assert selected and all(r["status"] == "selected" for r in selected)
    assert any(r["report_title"] for r in selected), "포털 계열(제목 있는 리포트)이 있어야 한다"


# ── ⑤ 포털 리포트 수집(§8-1 (가))— 전문이 있는 소재가 실제로 들어오는가 ──
def test_collect_research_ingests_portal_reports(client):
    from engine import report_collect

    reports = report_collect.collect_research(client)
    assert reports, "포털 리포트가 한 건도 안 들어오면 (가) 결정이 무의미하다"
    lg = next(r for r in reports if "LG전자" in r.title)
    assert lg.external_id == "aria_research:4902"
    assert lg.source == "aria_research"
    assert lg.report_url.endswith(".pdf"), "채널 링크가 아니라 리포트 PDF 여야 한다"
    assert "AI 데이터센터 냉각" in lg.summary, "채점이 읽을 요약은 전문에서 만든다"


def test_collected_summary_never_carries_fulltext(client):
    """저장하는 것은 요약이다 — 전문을 그대로 담지 않는다(저작권 자세 유지)."""
    from engine import report_collect

    for r in report_collect.collect_research(client):
        assert len(r.summary) <= config.REPORT_SUMMARY_MAX_CHARS


def test_telegram_items_are_not_double_ingested(client):
    """제목 없는 텔레그램 항목은 이미 aria_signal 로 들어온다 — 두 번 받지 않는다."""
    from engine import report_collect

    ids = {r.external_id for r in report_collect.collect_research(client)}
    assert "aria_research:4975" not in ids


def test_rejected_reports_are_skipped(client):
    from engine import report_collect

    ids = {r.external_id for r in report_collect.collect_research(client)}
    assert "aria_research:4936" not in ids, "status=rejected 는 받지 않는다"


def test_research_collection_can_be_switched_off(monkeypatch, client):
    from engine import report_collect

    monkeypatch.setattr(config, "REPORT_COLLECT_RESEARCH", False)
    assert report_collect.collect_research(client) == []


def test_search_failure_does_not_break_collection():
    """search_research 가 터져도 신호 수집은 계속된다."""
    from engine import report_collect

    class Broken:
        def search_research(self, **kwargs):
            raise RuntimeError("ARIA down")

    assert report_collect.collect_research(Broken()) == []


# ── ⑥ 원문 보관·재사용 (0033 report_sources · §8-1 결정) ────────────────
def test_packet_carries_doc_hash(client):
    """보관 중복 방지 키이자 인용 대조 앵커(§5-2)."""
    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    assert packet["doc_hash"].startswith("sha256:")
    assert packet["doc_hash"] == report_source.doc_hash(packet["text"])


def test_stored_source_is_reused_without_calling_aria(monkeypatch):
    """보관분이 있으면 ARIA 를 부르지 않는다 — 재생성·[재검사]에서 호출 0."""
    from engine import report_db

    stored = {
        "external_id": "aria_research:4902", "source_type": "research",
        "source_depth": "full_text", "source_url": "https://x/y.pdf",
        "doc_hash": "sha256:deadbeef", "char_count": 4, "truncated": False,
        "text": "보관된 원문", "chunks": [{"chunk_id": "C001"}],
    }
    monkeypatch.setattr(report_db, "get_report_source", lambda _e: stored)

    class MustNotBeCalled:
        def get_research(self, research_id: int):
            raise AssertionError("보관분이 있는데 ARIA 를 불렀다")

    packet = report_source.resolve(RESEARCH_REPORT, MustNotBeCalled())
    assert packet["text"] == "보관된 원문"
    assert packet["source_depth"] == "full_text"


def test_store_is_skipped_when_no_fulltext(monkeypatch):
    """전문이 없으면 보관 행을 만들지 않는다 — 빈 원문을 쌓지 않는다."""
    from engine import report_db

    calls: list[dict] = []
    monkeypatch.setattr(report_db, "insert_report_source", lambda row: calls.append(row))
    report_source.store_packet(report_source.build_packet(RESEARCH_REPORT, ""), RESEARCH_REPORT)
    assert calls == []


def test_collect_hands_sources_over_for_storage(client):
    """수집이 원문을 보관 대상으로 넘긴다 — 이게 있어야 대시보드 경로가 전문을 본다."""
    from engine import report_collect

    sources: list[dict] = []
    report_collect.collect_research(client, sources_out=sources)
    assert sources, "수집이 원문을 넘기지 않으면 Edge 경로는 영원히 요약만 본다"
    lg = next(s for s in sources if s["source_id"] == "aria_research:4902")
    assert lg["source_depth"] == "full_text"
    assert "AI 데이터센터 냉각 솔루션" in lg["text"]
    assert lg["doc_hash"].startswith("sha256:")


def test_edge_twin_shares_the_fulltext_contract():
    """대시보드(Edge)와 워커가 같은 마커·같은 지시문을 쓴다.

    한쪽에만 있으면 같은 리포트가 경로에 따라 다른 근거로 만들어진다 — Phase 0 이 찾아낸
    report-draft.yml ARIA 누락과 같은 계열의 결함이다.
    """
    import pathlib

    edge = pathlib.Path("supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert config.SOURCE_FULLTEXT_MARKER in edge
    assert config.SOURCE_FULLTEXT_END_MARKER in edge
    assert "요약만 보고 답하지 마라" in edge
    assert "report_sources" in edge, "Edge 가 보관된 원문을 읽어야 한다"


# ── ② 초안(대본) 단계 — §11-1 의 빠져 있던 절반 ──────────────────────────
# ★ 왜 뒤늦게 생겼나: §11-1 은 검사를 두 개 요구했다. ① 추출 프롬프트에 전문 마커, ②
#   **초안 프롬프트에 근거 묶음 마커 + 전문 마커**. ①만 만들어져 있었고, 하필 안 만들어진
#   ②가 지키는 쪽이 실제로 빠져 있었다 — report_scriptgen 의 프롬프트는 Fact Sheet JSON
#   한 덩어리뿐이었고 원문은 한 글자도 안 갔다. 지시서 §1-1 이 사장님 지시("초안·세부지시는
#   전체를 읽고")를 §4-2 초안 주입에 걸어 뒀는데 그 자리가 비어 있었던 것이다.
def test_script_prompt_carries_both_markers(client):
    """초안 프롬프트에 근거 묶음 **과** 전문이 둘 다 들어간다(§4-2)."""
    from engine import report_scriptgen

    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    prompt = report_scriptgen.script_user_prompt({"company": "LG전자"}, "", packet)

    assert config.DRAFT_EVIDENCE_MARKER in prompt
    assert config.DRAFT_EVIDENCE_END_MARKER in prompt
    assert config.SOURCE_FULLTEXT_MARKER in prompt
    assert config.SOURCE_FULLTEXT_END_MARKER in prompt
    # 마커만 있고 속이 비면 "전문을 줬다"는 착각이 된다 — 실제 본문이 들어갔는지 본다.
    assert "AI 데이터센터 냉각 솔루션" in prompt
    assert "LG전자" in prompt


def test_script_system_separates_context_from_facts():
    """전문은 맥락용, 수치는 Fact Sheet 만 — 이 경계가 프롬프트에 명시돼야 한다.

    전문을 주면서 이 경계를 안 적으면 대본이 검증 안 된 수치를 원문에서 끌어온다.
    환각 방지 불변식이 '입력 제한'에서 '경계 명시 + 출력 검증'으로 바뀐 지점이다.
    """
    from engine import report_scriptgen

    sys_prompt = report_scriptgen.SCRIPT_SYSTEM
    assert config.DRAFT_EVIDENCE_MARKER in sys_prompt
    assert config.SOURCE_FULLTEXT_MARKER in sys_prompt
    assert "새 수치를 끌어오지 마라" in sys_prompt


def test_script_prompt_without_fulltext_has_no_empty_marker():
    """전문이 없으면 전문 마커도 없다 — 빈 구간으로 '줬다'는 착각을 만들지 않는다."""
    from engine import report_scriptgen

    prompt = report_scriptgen.script_user_prompt({"company": "x"}, "", {})
    assert config.DRAFT_EVIDENCE_MARKER in prompt          # 근거 묶음은 항상 있다
    assert config.SOURCE_FULLTEXT_MARKER not in prompt


def test_draft_injection_can_be_switched_off(monkeypatch, client):
    """DRAFT_INCLUDE_FULLTEXT=false 면 초안에서만 빠진다(추출은 그대로)."""
    from engine import report_scriptgen

    packet = report_source.resolve(RESEARCH_REPORT, client, store=False)
    monkeypatch.setattr(config, "DRAFT_INCLUDE_FULLTEXT", False)

    assert config.SOURCE_FULLTEXT_MARKER not in report_scriptgen.script_user_prompt(
        {"company": "x"}, "", packet)
    # 추출 경로는 이 플래그와 무관하다 — 근거 추출은 전문이 **필수**다(§4-2).
    assert config.SOURCE_FULLTEXT_MARKER in report_factsheet.factsheet_user_prompt(
        RESEARCH_REPORT, packet)


def test_extract_hands_the_packet_to_the_caller(client, monkeypatch):
    """★ 배선의 급소: 추출이 확보한 원문을 초안에 넘기지 않으면 마커 검사를 통과해도
    실제 파이프라인에서는 전문이 안 들어간다(packet 이 빈 dict 로 흘러가므로)."""
    # ★ 필수 절(opinion·basis·risks)을 함께 준다 — 없으면 _require_complete 가 "잘린 시트"로
    #   보고 거부한다(그게 의도다). 실제 응답에는 이 키들이 들어 있다.
    monkeypatch.setattr(report_factsheet, "call_json",
                        lambda **kw: {"company": "LG전자", "opinion": "", "basis": [], "risks": []})
    monkeypatch.setattr(report_source, "get_client", lambda: client)

    out: dict = {}
    report_factsheet.extract(RESEARCH_REPORT, client, packet_out=out)
    assert out.get("text"), "packet_out 이 비면 초안 단계 전문 주입이 조용히 죽는다"
    assert out["source_depth"] == "full_text"


def test_orchestrator_actually_passes_the_packet():
    """report_draft 가 extract→scriptgen 으로 packet 을 실제로 나르는지 소스로 고정한다."""
    import inspect

    from engine import report_draft

    src = inspect.getsource(report_draft.generate_report_draft)
    assert "packet_out=packet" in src, "추출이 확보한 원문을 받지 않는다"
    assert "packet=packet" in src, "초안에 원문을 넘기지 않는다"


def test_edge_twin_shares_the_draft_contract():
    """엣지 폴백도 같은 두 마커를 쓴다 — 경로에 따라 대본 근거가 달라지면 안 된다."""
    import pathlib

    edge = pathlib.Path("supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert config.DRAFT_EVIDENCE_MARKER in edge
    assert config.DRAFT_EVIDENCE_END_MARKER in edge
    assert "새 수치를 끌어오지 마라" in edge
    assert "scriptUser(factSheet" in edge, "엣지가 대본 입력 빌더를 실제로 쓰는지"


# ── 엣지 트윈 정합 (Codex 리뷰 #86) ───────────────────────────
def _edge_src() -> str:
    import pathlib

    return pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")


def test_edge_boolean_parsing_matches_python():
    """★ 리뷰 지적: 파이썬 _get_bool 은 {1,true,yes,on} 만 참으로 본다. 엣지가 `!== "false"`
    로만 판정하면 DRAFT_INCLUDE_FULLTEXT=0 일 때 워커는 끄고 엣지는 켜서, 문서에 적어 둔
    되돌리기 스위치가 대시보드 경로에서만 안 먹는다."""
    edge = _edge_src()
    assert '["1", "true", "yes", "on"]' in edge, "참 목록이 파이썬과 다르다"
    # ★ 주석을 빼고 **코드 줄만** 본다 — 위 설명 주석에 옛 판정식이 그대로 인용돼 있어서,
    #   통째로 검사하면 고쳐 놓고도 실패한다(이 저장소가 반복해서 밟은 함정이다).
    code = [ln for ln in edge.splitlines()
            if not ln.strip().startswith(("//", "*", "/*"))]
    assert not any('!== "false"' in ln for ln in code), "느슨한 판정이 코드에 남아 있다"

    # 파이썬 쪽 참 목록이 바뀌면 이 테스트가 먼저 깨져야 한다.
    import inspect

    assert '{"1", "true", "yes", "on"}' in inspect.getsource(config._get_bool)


def test_edge_carries_the_truncation_warning():
    """★ 리뷰 지적: 상한에서 잘린 원문을 경고 없이 넘기면 모델이 그것을 **완전한 리포트로
    읽고**, 뒤쪽에 있던 결론·리스크 절이 처음부터 없었던 것처럼 논증을 짠다."""
    edge = _edge_src()
    assert "상한에서 잘렸다" in edge
    assert "truncated" in edge
    assert "stored.truncated" in edge, "플래그를 읽어만 두고 프롬프트로 넘기지 않는다"
    # 추출·초안 두 곳 모두에 붙어야 한다(파이썬 fulltext_block 은 한 함수라 자동으로 둘 다다).
    assert edge.count("상한에서 잘렸다 — 뒷부분 없음") == 2


def test_python_still_warns_on_truncation():
    """엣지만 고치고 파이썬 쪽 문구가 바뀌면 두 경로가 다시 갈린다."""
    from engine import report_source

    packet = {"text": "x" * 50, "truncated": True}
    assert "상한에서 잘렸다" in report_source.fulltext_block(packet)
    assert "상한에서 잘렸다" not in report_source.fulltext_block({"text": "x", "truncated": False})
