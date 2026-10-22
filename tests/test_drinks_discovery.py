"""주류 공장 소재 발견(B 보완) — 커넥터·신호·후보 묶기. 네트워크 없음(httpx.MockTransport + 기록한 응답 모양).

실제 Stack Exchange 호출은 로컬 e2e 로 따로 확인했다(docs/deviation-drinks-discovery.md). 유튜브·네이버는 키가 없어
**테스트 응답으로만** 확인했다 — 실제 호출 검증이 아니다.
"""
import json

import httpx
import pytest

from engine import config
from engine import drinks_discover as dd
from engine.drinks_fetch import FetchError, SafeFetcher


def fetcher(handler, hosts):
    return SafeFetcher(hosts, interval_sec=3, max_requests=50, transport=httpx.MockTransport(handler),
                       resolver=lambda h, p: ["8.8.8.8"], verify_peer=False, sleep=lambda s: None)


def js(obj, status=200):
    return httpx.Response(status, headers={"content-type": "application/json; charset=utf-8"}, content=json.dumps(obj).encode())


SE = {"items": [
    {"question_id": 1, "link": "https://alcohol.stackexchange.com/questions/1/how-long-does-opened-sake-last",
     "title": "How long does opened sake last in the fridge?", "body": "<p>I opened a bottle of junmai. Should I store it cold?</p>",
     "creation_date": 1689952481, "view_count": 147, "score": 0, "answer_count": 1},
    {"question_id": 2, "link": "https://alcohol.stackexchange.com/questions/2/x", "title": "Johnnie Walker Green vs Gold Label?",
     "body": "<p>Which one is better for a beginner?</p>", "creation_date": 1622853616, "view_count": 11116, "score": 4},
], "has_more": True, "quota_remaining": 299}


def test_signals_and_questions_are_rules_not_translation():
    assert set(dd.extract_signals("개봉한 사케 냉장 보관 얼마나 가요?")) >= {"question", "storage"}
    assert "debate" in dd.extract_signals("Johnnie Walker Green vs Gold Label")
    assert "new_product" in dd.extract_signals("한정판 출시 소식")
    assert dd.extract_questions("Intro text. How long does it last? More.") == ["How long does it last?"]
    assert dd.extract_questions("質問です。これはどうですか？") == ["これはどうですか？"]


def test_stackexchange_connector_keeps_only_provided_metrics_and_reports_more_pages():
    seen = []

    def h(req):
        seen.append(req)
        return js(SE)
    b = dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake"], "site": "alcohol"}, None, 10)
    assert b.parsed == 2 and b.incomplete == 1, "has_more → 다 못 봤음"
    a, w = b.found
    assert a.metrics == {"views": 147, "score": 0, "answers": 1}
    assert w.metrics == {"views": 11116, "score": 4}, "answer_count 가 없으면 키가 없다 — 0 으로 채우지 않는다"
    item = a.item()
    assert item["coverage"] == "title_summary" and item["platform"] == "stackexchange"
    assert "storage" in item["signals"] and item["questions"][0].startswith("How long")
    assert seen[0].url.params["tagged"] == "sake" and seen[0].url.params["filter"] == "withbody"


def test_stackexchange_backoff_stops_further_queries():
    calls = []

    def h(req):
        calls.append(1)
        return js({**SE, "has_more": False, "backoff": 10})
    b = dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake", "whisky"]}, None, 10)
    assert len(calls) == 1 and b.incomplete == 1


def test_keyed_connectors_refuse_without_key_and_send_key_only_in_header(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(youtube_data_api_key="", naver_client_id="", naver_client_secret=""))
    with pytest.raises(FetchError) as e:
        dd.youtube(fetcher(lambda r: js({}), ["www.googleapis.com"]), {"queries": ["sake"]}, None, 5)
    assert e.value.code == "api_key_missing"
    with pytest.raises(FetchError) as e:
        dd.naver(fetcher(lambda r: js({}), ["openapi.naver.com"]), {"queries": ["막걸리"]}, None, 5)
    assert e.value.code == "api_key_missing"

    monkeypatch.setattr(config, "SECRETS", config.Secrets(youtube_data_api_key="TESTKEY-not-real"))
    seen = []

    def yt(req):
        seen.append(req)
        p = req.url.path
        if p.endswith("/search"):
            return js({"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "사케 개봉 후 보관 어떻게?", "channelTitle": "채널A"}}]})
        if p.endswith("/videos"):
            return js({"items": [{"id": "v1", "snippet": {"title": "사케 개봉 후 보관 어떻게?", "channelTitle": "채널A",
                                                          "description": "냉장 보관 팁", "publishedAt": "2026-10-01T00:00:00Z"},
                                  "statistics": {"viewCount": "1200", "commentCount": "30"}}]})
        return js({"error": {"code": 403, "message": "commentsDisabled"}}, status=403)
    b = dd.youtube(fetcher(yt, ["www.googleapis.com"]), {"queries": ["사케 보관"]}, None, 5)
    v = b.found[0]
    assert v.metrics == {"views": 1200, "comments": 30}, "likeCount 미제공(숨김) → 키 없음"
    assert v.coverage == "title_summary", "댓글을 못 받으면 확보 범위가 줄어든 것으로 드러낸다"
    assert v.url == "https://www.youtube.com/watch?v=v1"
    for req in seen:
        assert "TESTKEY" not in str(req.url), "키를 URL 에 넣지 않는다"
        assert req.headers.get("x-goog-api-key") == "TESTKEY-not-real"


def test_naver_returns_search_snippets_only(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(naver_client_id="id-test", naver_client_secret="secret-test"))

    def h(req):
        if "cafearticle" in req.url.path:
            return js({"total": 900, "items": [{"title": "<b>막걸리</b> 개봉 후 보관?", "link": "https://cafe.naver.com/x/1",
                                                "description": "냉장고에 며칠까지 괜찮나요?", "cafename": "전통주 카페"}]})
        return js({"total": 1, "items": [{"title": "막걸리 추천", "link": "https://blog.naver.com/y/2", "description": "입문용",
                                          "bloggername": "블로거", "postdate": "20261020"}]})
    b = dd.naver(fetcher(h, ["openapi.naver.com"]), {"queries": ["막걸리"]}, None, 10)
    cafe, blog = b.found
    assert cafe.platform == "naver_cafe" and cafe.title == "막걸리 개봉 후 보관?" and cafe.coverage == "title_summary"
    assert cafe.metrics == {} and blog.posted_at.startswith("2026-10-20")
    assert b.incomplete == 0, "검색 결과 전체 건수(total)를 미수집으로 세지 않는다"


def test_independent_sources_do_not_inflate_on_reposts():
    items = [
        {"platform": "naver_blog", "channel_name": "A", "summary_hash": "h1"},
        {"platform": "naver_blog", "channel_name": "B", "summary_hash": "h1"},   # 같은 보도자료 전재
        {"platform": "naver_cafe", "channel_name": "C", "summary_hash": "h2", "origin_group": "공지"},
        {"platform": "youtube", "channel_name": "D", "summary_hash": "h3", "origin_group": "공지"},
        {"platform": "stackexchange", "channel_name": "E", "summary_hash": "h4"},
    ]
    assert dd._independent(items) == 3


def test_card_is_provisional_with_versioned_reason_and_no_cross_platform_sum():
    items = [
        {"id": "1", "platform": "stackexchange", "channel_name": "SE", "title": "How long does opened sake last?",
         "summary": "fridge 50% ...", "summary_hash": "a", "questions": ["How long does opened sake last?"],
         "signals": ["question", "storage"], "latest_metrics": {"views": 100}},
        {"id": "2", "platform": "youtube", "channel_name": "Y", "title": "opened sake last how long?", "summary_hash": "b",
         "questions": ["opened sake last how long?"], "signals": ["question", "storage"], "latest_metrics": {"views": 5000}},
    ]
    card = dd.build_card(items, topics=[{"id": "t1", "title": "How long does opened sake last", "question": "x"}])
    assert card["rubric"] == config.DRINKS_DISCOVERY_RUBRIC and "임시" in card["score_reason"]
    assert card["interest"]["by_platform"]["stackexchange"]["max_views"] == 100
    assert card["interest"]["by_platform"]["youtube"]["max_views"] == 5000
    assert "views" not in card["interest"], "플랫폼끼리 지표를 더한 숫자가 없다"
    assert card["duplicate_topic_ids"] == ["t1"]
    assert card["first_scene"].startswith("[규칙 제안]")
    assert any("50%" in f for f in card["facts_to_check"])
    assert len(dd.cluster(items)) == 1


def test_suggest_skips_items_without_any_signal():
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        if fn == "drinks_discovery_backlog":
            return {"items": [{"id": "1", "platform": "web", "title": "Brewery news", "signals": [], "questions": []}],
                    "candidates": [], "topics": []}
        return {"candidate_id": "c"}
    out = dd.suggest_candidates(rpc)
    assert out == {"new": 0, "added": 0, "skipped_items": 1}
    assert [fn for fn, _ in calls] == ["drinks_discovery_backlog"]


def test_discovery_processor_records_items_and_api_key_missing_fails_validation(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets())
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        return {"status": "finished", **p} if fn == "drinks_finish_run" else {}
    run = {"run_id": "r", "lease_token": "t", "mode": "validate", "cursor_from": None,
           "limits": {"max_items": 10, "max_bodies": 0, "interval_sec": 3, "max_requests": 20},
           "source": {"id": "s", "name": "yt", "method": "api", "purpose": "discovery", "platform": "youtube",
                      "parser_config": {"queries": ["sake"]}, "allowed_hosts": ["www.googleapis.com"], "item_hosts": ["www.youtube.com"]}}
    out = dd.DiscoveryProcessor(run, rpc, fetcher(lambda r: js({}), ["www.googleapis.com"])).process()
    assert out["error_code"] == "api_key_missing"
    run2 = {**run, "mode": "collect", "source": {**run["source"], "platform": "stackexchange", "allowed_hosts": ["api.stackexchange.com"]}}
    calls.clear()
    out = dd.DiscoveryProcessor(run2, rpc, fetcher(lambda r: js(SE), ["api.stackexchange.com"])).process()
    items = [p["item"] for fn, p in calls if fn == "drinks_collect_discovery"]
    assert len(items) == 2 and out["parsed_count"] == 2 and out["incomplete_count"] == 1
