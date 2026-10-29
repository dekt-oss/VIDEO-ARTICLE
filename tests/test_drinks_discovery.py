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


def test_korean_question_endings_count_without_question_mark():
    """네이버 검색 요약 모양의 문장 5개 — 물음표가 잘렸어도 끝말로 질문을 알아본다(질문 3, 아닌 것 2)."""
    snippets = [
        "개봉한 지 한 달 된 사케를 냉장고에 두면 얼마나 오래 마셔도 되는 건가요",      # 질문 (물음표 없음)
        "위스키 입문용으로 어떤 제품을 사면 좋을까요...",                              # 질문 (말줄임표)
        "막걸리 유통기한이 지난 것을 마셔도 괜찮은지 궁금",                              # 질문 (궁금)
        "어제 마트에서 사케를 한 병 사서 냉장고에 넣어 두었어요",                        # 서술
        "전통주는 우리나라의 고유한 술로 지역마다 빚는 방식이 다릅니다.",                 # 서술
    ]
    got = [dd.extract_questions(x) for x in snippets]
    assert [bool(g) for g in got] == [True, True, True, False, False]
    assert got[1] == [snippets[1]], "원문 그대로(번역·요약 없음)"
    assert dd.extract_questions("사케 궁금") == [], "한글 6자 미만 조각은 질문으로 치지 않는다"
    assert dd.extract_questions("Which is better for me") == [], "한글이 아닌 문장은 물음표 없이는 질문이 아니다"
    assert "인가요" in config.DRINKS_QUESTION_ENDINGS_KO and "?" not in "".join(config.DRINKS_QUESTION_ENDINGS_KO)


def test_per_source_lookback_days_replaces_global_first_run_default():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    assert (now - dd.first_run_start({}, now)).days == config.DRINKS_DISCOVERY_BACKFILL_DAYS
    assert (now - dd.first_run_start({"lookback_days": 3000}, now)).days == 3000
    for bad in (0, -5, 3651, "3000", True, None, 12.5):
        assert (now - dd.first_run_start({"lookback_days": bad}, now)).days == config.DRINKS_DISCOVERY_BACKFILL_DAYS, bad
    # 실제 요청의 fromdate 도 그 값으로 간다
    h, seen = _se_pages([{"items": [], "has_more": False}])
    dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake"], "lookback_days": 3000}, None, 10)
    age_days = (datetime.now(timezone.utc).timestamp() - int(seen[0].url.params["fromdate"])) / 86400
    assert 2999 < age_days < 3001
    # 워처마크(since)가 있으면 그것이 우선이다
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    h2, seen2 = _se_pages([{"items": [], "has_more": False}])
    dd.stackexchange(fetcher(h2, ["api.stackexchange.com"]), {"queries": ["sake"], "lookback_days": 3000}, since, 10)
    assert int(seen2[0].url.params["fromdate"]) == int(since.timestamp())


def _se_pages(pages):
    """쪽 번호별 응답. 마지막 쪽 다음은 빈 쪽."""
    seen = []

    def h(req):
        seen.append(req)
        n = int(req.url.params.get("page", "1"))
        return js(pages[n - 1] if n <= len(pages) else {"items": [], "has_more": False})
    return h, seen


def test_stackexchange_reads_oldest_first_and_keeps_only_provided_metrics():
    h, seen = _se_pages([SE, {"items": [], "has_more": False}])
    b = dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake"], "site": "alcohol"}, None, 10)
    assert [x.external_id for x in b.found] == ["2", "1"], "생성 시각 오름차순"
    w, a = b.found
    assert a.metrics == {"views": 147, "score": 0, "answers": 1}
    assert w.metrics == {"views": 11116, "score": 4}, "answer_count 가 없으면 키가 없다 — 0 으로 채우지 않는다"
    assert b.incomplete == 0 and b.advance_to is None, "다 받았으면 다 못 봤다고 하지 않는다"
    item = a.item()
    assert item["coverage"] == "title_summary" and item["platform"] == "stackexchange"
    assert "storage" in item["signals"] and item["questions"][0].startswith("How long")
    q = seen[0].url.params
    assert (q["tagged"], q["order"], q["filter"]) == ("sake", "asc", "withbody") and int(q["fromdate"]) > 0, "첫 실행도 시작 시각을 둔다"


def test_stackexchange_limit_advances_only_to_what_was_seen():
    h, _ = _se_pages([SE])
    b = dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake"]}, None, 1)
    assert len(b.found) == 1 and b.incomplete == 1
    assert b.advance_to == dd._epoch_iso(1622853616), "받은 마지막 글(가장 오래된 것) 시각까지만 전진"


def test_stackexchange_negative_score_is_a_provided_value():
    neg = {"items": [{**SE["items"][0], "score": -2}], "has_more": False}
    h, _ = _se_pages([neg])
    b = dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake"]}, None, 10)
    assert b.found[0].metrics["score"] == -2


def test_stackexchange_backoff_stops_the_run():
    calls = []

    def h(req):
        calls.append(1)
        return js({**SE, "has_more": True, "backoff": 10})
    b = dd.stackexchange(fetcher(h, ["api.stackexchange.com"]), {"queries": ["sake", "whisky"]}, None, 10)
    assert len(calls) == 1 and b.incomplete == 1


def test_keyed_connectors_refuse_without_key_and_send_key_only_in_header(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(youtube_data_api_key="", naver_client_id="", naver_client_secret=""))
    with pytest.raises(FetchError) as e:
        dd.youtube(fetcher(lambda r: js({}), ["www.googleapis.com"]), {"queries": ["sake"]}, None, 5)
    assert e.value.code == "api_key_missing"
    with pytest.raises(FetchError) as e:
        dd.naver(fetcher(lambda r: js({}), ["naverapihub.apigw.ntruss.com"]), {"queries": ["막걸리"]}, None, 5)
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
        # 술째리고와 같은 API HUB 키 — developers.naver.com 헤더로 보내면 401(2026-10-23 실측)
        assert req.url.host == "naverapihub.apigw.ntruss.com" and req.url.path.startswith("/search/v1/")
        assert req.headers.get("x-ncp-apigw-api-key-id") == "id-test" and req.headers.get("x-ncp-apigw-api-key") == "secret-test"
        assert "secret-test" not in str(req.url), "키를 URL 에 넣지 않는다"
        if "cafearticle" in req.url.path:
            # API HUB 실응답은 JSON 본문을 text/plain 으로 보낸다(2026-10-23 실측) — 이걸 거절하면 네이버 발견이 통째로 멈춘다
            r = js({"total": 900, "items": [{"title": "<b>막걸리</b> 개봉 후 보관?", "link": "https://cafe.naver.com/x/1",
                                             "description": "냉장고에 며칠까지 괜찮나요?", "cafename": "전통주 카페"}]})
            return httpx.Response(200, headers={"content-type": "text/plain;charset=UTF-8"}, content=r.content)
        return js({"total": 1, "items": [{"title": "막걸리 추천", "link": "https://blog.naver.com/y/2", "description": "입문용",
                                          "bloggername": "블로거", "postdate": "20261020"}]})
    b = dd.naver(fetcher(h, ["naverapihub.apigw.ntruss.com"]), {"queries": ["막걸리"]}, None, 10)
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
    assert out == {"new": 0, "added": 0, "skipped_items": 1, "refreshed": 0}
    assert [fn for fn, _ in calls] == ["drinks_discovery_backlog", "drinks_discovery_backlog"], "후보 생성 없음(다시 계산 조회만)"


def test_adding_to_an_open_candidate_recomputes_from_all_its_items():
    old = [{"id": f"o{i}", "platform": "stackexchange", "channel_name": f"ch{i}", "title": "How long does opened sake last?",
            "summary_hash": f"h{i}", "questions": ["How long does opened sake last?"], "signals": ["question", "storage"]} for i in range(4)]
    new = {"id": "n1", "platform": "youtube", "channel_name": "Y", "title": "opened sake how long does it last?", "summary_hash": "hn",
           "questions": ["opened sake how long does it last?"], "signals": ["question", "storage"]}
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        if fn == "drinks_discovery_backlog":
            return {"items": [new], "topics": [], "candidates": [{"id": "c1", "key_question": "How long does opened sake last?", "items": old}]}
        return {"candidate_id": "c1"}
    dd.suggest_candidates(rpc)
    add = next(p for fn, p in calls if fn == "drinks_suggest_candidate" and p["item_ids"])
    assert add["candidate_id"] == "c1" and add["interest"]["independent_sources"] == 5, "기존 4곳 + 새 1곳 — 새 묶음만으로 덮지 않는다"


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


def test_naver_keeps_same_day_posts_after_the_watermark(monkeypatch):
    """게시일이 날짜뿐이라 시각 비교로 같은 날 늦은 글을 잃던 것(검토 지적)."""
    from datetime import datetime, timezone
    monkeypatch.setattr(config, "SECRETS", config.Secrets(naver_client_id="id-test", naver_client_secret="secret-test"))

    def h(req):
        return js({"items": [{"title": "막걸리 같은 날 글", "link": "https://blog.naver.com/y/9", "description": "d", "postdate": "20261022"}]})
    since = datetime(2026, 10, 21, 21, 30, tzinfo=timezone.utc)   # = 2026-10-22 06:30 KST
    b = dd.naver(fetcher(h, ["naverapihub.apigw.ntruss.com"]), {"queries": ["막걸리"], "kinds": ["blog"]}, since, 10)
    assert [x.url for x in b.found] == ["https://blog.naver.com/y/9"]


# ── 잡음 거르기(2026-10-29) ──

NOISE_TITLES = ["구룡포 햇 과메기 공구 스타트!!!", "(11월 3일 발송) 복동이네 프리미엄 유라조생/노지감귤",
                "마지막 공구) 나주 전통방식 한우 순살 갈비탕 & 편육 공동 구매", "20261024 주간 경제전망",
                "아고다 10월 할인코드 알아볼 때 · 후지카와구치코 독채 위치", "Q2 체크인·체크아웃 시간과 짐 보관은요?", "목요일 강습 인증"]
GOOD_TITLES = ["막걸리는 왜 병마다 가라앉는 정도가 다를까요", "생 막걸리와 살균 막걸리는 무엇이 다를까요",
               "다들 위스키를 왜 드시는거죠? 왜 위스키였죠?", "광주 gs25에서 막걸리 사고 제주도 왔는데 유통기한 5개월 지나있네요"]


def test_is_relevant_drops_commerce_travel_and_offtopic_titles():
    for t in NOISE_TITLES:
        assert dd.is_relevant(t, "") is False, t
    for t in GOOD_TITLES:
        assert dd.is_relevant(t, "") is True, t


def test_is_relevant_noise_only_counts_in_the_title_and_false_friends_are_ignored():
    assert dd.is_relevant("막걸리 개봉 후 보관", "택배로 받았는데 며칠 지나도 괜찮나요") is True, "요약의 택배는 허용"
    assert dd.is_relevant("막걸리 공구 마감", "") is False, "제목의 공구는 거른다"
    assert dd.is_relevant("신기술 소개", "예술 이야기") is False, "기술·예술의 '술' 은 술이 아니다"
    assert dd.is_relevant("Sake storage question", None) is True
    assert dd.is_relevant("Hotel review", "great view") is False


def test_storage_signal_requires_a_drink_word():
    assert "storage" not in dd.extract_signals("Q2 체크인·체크아웃 시간과 짐 보관은요?")
    assert "storage" in dd.extract_signals("막걸리 유통기한 5개월 지나있네요")
    assert "storage" in dd.extract_signals("How long does an open bottle of Sake last?")
    assert "storage" in dd.extract_signals("How long does an opened bottle keep in the fridge?"), "bottle 은 보관 신호에만 인정"
    assert dd.is_relevant("How long does an opened bottle keep?", "") is False, "bottle 은 관련성 필터에는 쓰지 않는다"
    assert "question" in dd.extract_signals("Q2 체크인·체크아웃 시간과 짐 보관은요?"), "다른 신호는 그대로"


def test_naver_calls_every_query_and_kind_once_and_drops_irrelevant(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(naver_client_id="id-test", naver_client_secret="secret-test"))
    queries = ["막걸리 보관", "위스키 입문", "사케 추천", "전통주 선물", "소주 도수", "와인 말고 술"]
    asked: list[tuple[str, str, int]] = []

    def h(req):
        kind = "cafearticle" if "cafearticle" in req.url.path else "blog"
        q = req.url.params["query"]
        asked.append((kind, q, int(req.url.params["display"])))
        return js({"items": [
            {"title": f"{q} 이야기", "link": f"https://blog.naver.com/{kind}/{q}", "description": "막걸리 이야기", "postdate": "20261028"},
            {"title": "구룡포 햇 과메기 공구 스타트!!!", "link": f"https://blog.naver.com/noise/{kind}/{q}", "description": "", "postdate": "20261028"},
        ]})
    b = dd.naver(fetcher(h, ["naverapihub.apigw.ntruss.com"]), {"queries": queries}, None, 50)
    assert {(k, q) for k, q, _ in asked} == {(k, q) for k in ("cafearticle", "blog") for q in queries}, "6검색어 × 2종류 모두 불린다"
    assert all(1 <= d <= 50 // 12 for _, _, d in asked)
    assert b.parsed == 24, "API 가 돌려준 건수는 그대로 센다"
    assert len(b.found) == 12 and all("공구" not in (x.title or "") for x in b.found)
    assert {x.url for x in b.found} == {x.url for x in b.found if "noise" not in x.url}
    # 한도가 호출 수보다 작아도 호출당 최소 1건으로 모두 부른다
    asked.clear()
    dd.naver(fetcher(h, ["naverapihub.apigw.ntruss.com"]), {"queries": queries}, None, 3)
    assert len(asked) == 12 and {d for _, _, d in asked} == {1}


def test_naver_full_page_is_judged_against_the_per_call_display(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(config, "SECRETS", config.Secrets(naver_client_id="id-test", naver_client_secret="secret-test"))

    def h(req):
        n = int(req.url.params["display"])
        return js({"items": [{"title": f"막걸리 {i}", "link": f"https://blog.naver.com/z/{i}", "description": "", "postdate": "20261029"}
                             for i in range(n)]})
    since = datetime(2026, 10, 20, tzinfo=timezone.utc)
    b = dd.naver(fetcher(h, ["naverapihub.apigw.ntruss.com"]), {"queries": ["a", "b"], "kinds": ["blog"]}, since, 10)
    assert b.incomplete == 2, "호출당 5건을 꽉 채웠고 가장 오래된 글도 워처마크 이후 → 호출마다 다 못 봤다"
