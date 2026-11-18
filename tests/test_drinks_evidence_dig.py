"""막히기 전에 한 번 더 찾기(2026-11-18, 운영자 "내가 원하는 주제가 선택되면 그 주제로 어떻게든 내용을 만들어 달라").
첫 근거가 질문에 답하지 못하면, 질문은 그대로 두고 다른 검색 문장으로 웹을 다시 찾아 읽은 뒤 다시 판정한다. 모델·네트워크 호출 0(가짜 주입)."""
from __future__ import annotations

from types import SimpleNamespace

import test_drinks_develop as base
import test_drinks_factcheck as fc
from engine import config
from engine import drinks_develop as dd

IDS = ("c1", "c2", "c3", "c4")
PAGE = " ".join(fc.QUOTES) + " " + "본문을 채우는 문장입니다. " * 30


class Fetcher:
    def get(self, url, accept=None, params=None):
        if url.endswith("robots.txt"):
            return SimpleNamespace(body=b"", charset="utf-8", url=url, status=200, content_type="text/plain")
        return SimpleNamespace(body=f"<html><title>T</title><body><p>{PAGE}</p></body></html>".encode(), charset="utf-8", url=url,
                               status=200, content_type="text/html")


def run(answered_on_call: int, search_hits):
    calls = {"fc": 0, "search": []}

    def factcheck(topic, ctx, claims):
        calls["fc"] += 1
        ok = calls["fc"] >= answered_on_call
        qa = {"answered": True, "answer_ko": "답", "claim_ids": ["c1"]} if ok else {"answered": False, "claim_ids": [], "missing_ko": "핵심"}
        return {**fc.good(ids=IDS), "question_answer": qa}

    def search(q):
        calls["search"].append(q)
        return search_hits(len(calls["search"]))

    rpc = base.FakeRpc(sources=[base.src_row()])
    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(fc.QUOTES), factcheck=factcheck, reframe=lambda t, c: None,
                                                    web_search=search, fetcher_factory=lambda hosts: Fetcher()))
    return rpc, res, calls


def test_off_topic_first_pass_digs_with_new_queries_and_saves_without_changing_the_question():
    hits = lambda n: [{"url": f"https://news{n}.example/a", "title": "기사"}]
    rpc, res, calls = run(2, hits)
    assert res["status"] == "succeeded", rpc.finish
    assert rpc.saved_evidence is not None, "막히지 않고 근거를 저장했다"
    assert len(calls["search"]) == 1 + len(dd.deep_queries(base.TOPIC)), "처음 1번 + 더 찾기 문장들"
    assert all(base.TOPIC["question"] in q for q in calls["search"]), "질문은 바꾸지 않는다"
    holds = [p["note"] for n, p in rpc.calls if n == "drinks_develop_hold"]
    assert sum("웹 검색" in h for h in holds) == len(calls["search"]), "검색마다 결재 장부를 탄다"


def test_dig_runs_once_and_still_blocks_honestly_when_nothing_answers():
    hits = lambda n: [{"url": f"https://news{n}.example/a", "title": "기사"}]
    rpc, res, calls = run(99, hits)
    assert res["status"] == "blocked" and rpc.finish["error_code"] == "evidence_off_topic"
    assert len(calls["search"]) == 1 + len(dd.deep_queries(base.TOPIC)), "더 찾기는 한 번만(돈이 새지 않게)"


def test_dig_skips_documents_already_read():
    hits = lambda n: [{"url": "https://same.example/a", "title": "같은 문서"}]
    rpc, res, calls = run(2, hits)
    assert res["status"] == "blocked", "새 문서가 없으면 같은 자료로 다시 판정하지 않는다"
    assert any("새로 읽을 문서를 찾지 못함" in str(s.get("why")) for s in rpc.finish["result"].get("skipped") or [])


def test_dig_is_off_without_web_search():
    rpc = base.FakeRpc(sources=[base.src_row()])
    calls = []

    def factcheck(topic, ctx, claims):
        calls.append(1)
        return {**fc.good(ids=IDS), "question_answer": {"answered": False, "claim_ids": [], "missing_ko": "핵심"}}

    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(fc.QUOTES), factcheck=factcheck, reframe=lambda t, c: None))
    assert res["status"] == "blocked" and len(calls) == 1
    assert config.DRINKS_DEVELOP_WEB_DEEP_ENABLED is True


def test_dig_does_not_download_the_same_document_twice_and_respects_the_read_cap():
    fetched = []

    class Counting(Fetcher):
        def get(self, url, accept=None, params=None):
            if not url.endswith("robots.txt"):
                fetched.append(url)
            return super().get(url, accept, params)

    calls = {"fc": 0}

    def factcheck(topic, ctx, claims):
        calls["fc"] += 1
        qa = {"answered": calls["fc"] >= 2, "answer_ko": "답", "claim_ids": ["c1"]} if calls["fc"] >= 2 else {"answered": False, "claim_ids": [], "missing_ko": "핵심"}
        return {**fc.good(ids=IDS), "question_answer": qa}

    many = [{"url": f"https://n{i}.example/a", "title": "기사"} for i in range(8)]
    rpc = base.FakeRpc(sources=[base.src_row()])
    dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(fc.QUOTES), factcheck=factcheck, reframe=lambda t, c: None,
                                              web_search=lambda q: many, fetcher_factory=lambda hosts: Counting()))
    assert len(fetched) == len(set(fetched)), "같은 문서를 두 번 내려받지 않는다"
    assert len(fetched) <= config.DRINKS_DEVELOP_WEB_MAX_SOURCES + config.DRINKS_DEVELOP_WEB_DEEP_MAX_SOURCES


def test_dig_never_revives_a_document_the_operator_set_aside():
    aside = base.src_row(title="운영자가 뺀 글", linked=True, role="discovery", url="https://aside.example/a", sid="s9")
    hits = lambda n: [{"url": "https://aside.example/a", "title": "뺀 글"}]
    rpc = base.FakeRpc(sources=[base.src_row(), aside])
    seen = []

    class Watch(Fetcher):
        def get(self, url, accept=None, params=None):
            seen.append(url)
            return super().get(url, accept, params)

    def factcheck(topic, ctx, claims):
        return {**fc.good(ids=IDS), "question_answer": {"answered": False, "claim_ids": [], "missing_ko": "핵심"}}

    dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(fc.QUOTES), factcheck=factcheck, reframe=lambda t, c: None,
                                              web_search=lambda q: hits(1), fetcher_factory=lambda hosts: Watch()))
    assert not any("aside.example/a" in u and not u.endswith("robots.txt") for u in seen), seen


def test_dig_budget_failure_keeps_the_first_result_instead_of_losing_it():
    calls = {"n": 0}

    def search(q):
        calls["n"] += 1
        if calls["n"] > 1:
            raise dd.DevelopError("budget_exceeded", "한도")
        return [{"url": "https://first.example/a", "title": "기사"}]

    def factcheck(topic, ctx, claims):
        return {**fc.good(ids=IDS), "question_answer": {"answered": False, "claim_ids": [], "missing_ko": "핵심"}}

    rpc = base.FakeRpc(sources=[base.src_row()])
    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(fc.QUOTES), factcheck=factcheck, reframe=lambda t, c: None,
                                                    web_search=search, fetcher_factory=lambda hosts: Fetcher()))
    assert res["status"] == "blocked" and rpc.finish["error_code"] == "evidence_off_topic", "앞 결과로 정직하게 판정"
    assert rpc.finish["result"].get("unsaved_evidence"), "만든 주장·판정을 잃지 않는다"
