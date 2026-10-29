"""주류 동향 수집(engine/drinks_trends.py) — 제품 사전 매칭·카페 화이트리스트·반응 점수·이슈 거르기·워커 한 바퀴.
네트워크·Jev·DB 없음(httpx.MockTransport + 가짜 rpc + 가짜 판정). 실제 네이버 뉴스 응답과 Jev 반응 판정 정확도는 **미검증**.
"""
import json
import re
from pathlib import Path

import httpx
import pytest

from engine import config
from engine import drinks_trends as dt
from engine.drinks_fetch import FetchError, SafeFetcher

HOSTS = ["naverapihub.apigw.ntruss.com"]


def fetcher(handler, max_requests=200):
    return SafeFetcher(HOSTS, interval_sec=3, max_requests=max_requests, transport=httpx.MockTransport(handler),
                       resolver=lambda h, p: ["8.8.8.8"], verify_peer=False, sleep=lambda s: None)


def js(obj, status=200):
    # API HUB 는 JSON 을 text/plain 으로 내려보낸다(실측) - 같은 모양으로 시험한다.
    return httpx.Response(status, headers={"content-type": "text/plain; charset=utf-8"}, content=json.dumps(obj, ensure_ascii=False).encode())


HDR = {"X-NCP-APIGW-API-KEY-ID": "id-test", "X-NCP-APIGW-API-KEY": "secret-test"}


# ── 제품 사전 ──

def names(text):
    return [c for c, _ in dt.matcher().find(text)]


def test_lexicon_is_well_formed_and_has_no_alias_shared_by_two_products():
    lex = config.DRINKS_PRODUCT_LEXICON
    assert len(lex) >= 70
    seen: dict[str, str] = {}
    for canonical, spec in lex.items():
        assert spec["category"] in ("sake", "traditional", "whisky"), canonical
        assert spec["aliases"], canonical
        for a in spec["aliases"]:
            key = a.lower().strip()
            assert key and key not in seen, f"표기 '{a}' 가 {seen.get(key)} 와 {canonical} 에 겹친다"
            seen[key] = canonical
    assert {s["category"] for s in lex.values()} == {"sake", "traditional", "whisky"}


def test_matcher_finds_korean_and_english_aliases_once_each_in_text_order():
    got = dt.matcher().find("Macallan 12 보다 발베니 14가 낫다는 얘기, 맥캘란 18은 비싸다 / balvenie 도 좋음")
    assert got == [("맥캘란", "whisky"), ("발베니", "whisky")], "같은 제품은 표기가 달라도 한 번 - 글에 나온 순서"


def test_matcher_latin_uses_word_boundary_but_korean_is_substring():
    assert names("hwayo41 후기") == ["화요"], "영문 뒤에 숫자가 붙어도(영문자만 아니면) 걸린다"
    assert names("Dassai 23 마셔봄") == ["닷사이"]
    assert names("macallanx 같은 건 없음") == [], "영문자가 이어 붙으면 다른 낱말이다"
    assert names("thehibikis") == []
    assert names("닷사이23과 쿠보타만주") == ["닷사이", "쿠보타"], "한글은 조사·숫자가 붙어도 걸린다"


def test_matcher_false_friends_and_longest_alias_wins():
    assert names("이번 주 화요일에 모임") == [], "'화요일' 안의 '화요' 는 술이 아니다"
    assert names("화요일 모임에서 화요 41 마심") == ["화요"]
    # '산토리 가쿠빈' 이 '가쿠빈' 을 먹는다 - 같은 자리가 두 번 세어지지 않는다
    assert dt.matcher().find("산토리 가쿠빈 하이볼") == [("산토리 가쿠빈", "whisky")]
    assert names("가쿠빈 하이볼") == ["산토리 가쿠빈"], "짧은 표기만 있어도 같은 제품"
    # 긴 표기 안의 짧은 표기('지평 막걸리' vs 다른 표기)가 다른 제품으로 새지 않는다
    assert names("김창수 위스키 시음") == ["김창수 위스키"]
    assert names("글렌 피딕 15 / 글렌피딕 18") == ["글렌피딕"]


def test_matcher_ignores_generic_words_and_empty_text():
    assert dt.matcher().find("") == [] and dt.matcher().find(None) == []
    assert names("요즘 막걸리랑 위스키 입문 추천해주세요") == [], "주종 낱말만으로는 제품이 아니다"
    assert names("지평선 너머로 해가 진다") == [], "'지평' 단독 표기는 일부러 뺐다"


# ── 카페 화이트리스트 ──

def test_cafe_slug_and_whitelist():
    assert dt.cafe_slug("https://cafe.naver.com/whiskycognac") == "whiskycognac"
    assert dt.cafe_slug("cafe.naver.com/SakeLove/") == "sakelove"
    assert dt.cafe_slug("oakmen") == "oakmen"
    assert dt.cafe_slug(None) == ""
    assert dt.in_whitelist("https://cafe.naver.com/whiskycognac") and dt.in_whitelist("https://cafe.naver.com/kliquor")
    assert not dt.in_whitelist("https://cafe.naver.com/wineclub") and not dt.in_whitelist("") and not dt.in_whitelist(None)
    assert set(config.DRINKS_COMMUNITY_CAFES) >= {"whiskycognac", "oakmen", "sakelove", "kliquor", "sakeholics"}


# ── 반응 점수 ──

def test_sentiment_mapping_is_two_p_minus_one_and_labels_follow_config_thresholds():
    assert dt.sentiment_from_p(1.0) == 1.0 and dt.sentiment_from_p(0.0) == -1.0 and dt.sentiment_from_p(0.5) == 0.0
    assert dt.sentiment_from_p(0.9) == 0.8 and dt.sentiment_from_p(0.123) == -0.75
    assert dt.sentiment_from_p(1.4) == 1.0 and dt.sentiment_from_p(-0.2) == -1.0, "범위 밖 p 는 잘라낸다"
    assert dt.sentiment_label(None) == "판정 없음"
    assert dt.sentiment_label(0.21) == "긍정" and dt.sentiment_label(0.2) == "중립"
    assert dt.sentiment_label(-0.21) == "부정" and dt.sentiment_label(-0.2) == "중립"


def test_jev_sentiment_maps_p_and_fails_open_to_none(monkeypatch):
    from engine import decide

    calls = []

    def fake_noul(state, instructions, criteria, site="", subject=""):
        calls.append((state, site, subject))
        return 0.9
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "noul", fake_noul)
    assert dt.jev_sentiment("발베니", "발베니 12 후기", "부드럽고 맛있다") == (0.8, 0.9)
    assert "PRODUCT: 발베니" in calls[0][0] and calls[0][1] == "drink_trend_sentiment"
    monkeypatch.setattr(decide, "noul", lambda *a, **k: None)   # Jev 실패·차단기
    assert dt.jev_sentiment("발베니", "t", "s") is None
    monkeypatch.setattr(decide, "enabled", lambda: False)        # 꺼짐·키 없음 - 묻지도 않는다
    monkeypatch.setattr(decide, "noul", lambda *a, **k: pytest.fail("Jev 가 꺼졌는데 물었다"))
    assert dt.jev_sentiment("발베니", "t", "s") is None


def test_migration_view_thresholds_match_config():
    sql = Path(__file__).resolve().parent.parent.joinpath("supabase/migrations/0059_drinks_trends.sql").read_text(encoding="utf-8")
    assert f"sentiment > {config.DRINKS_TRENDS_POSITIVE_ABOVE}" in sql
    assert f"sentiment < {config.DRINKS_TRENDS_NEGATIVE_BELOW}" in sql


def test_trend_constants_do_not_pollute_jev_threshold_snapshot():
    """decide.thresholds_snapshot 은 JEV_*_MIN/_BELOW 이름을 전부 모아 문턱 지문을 만든다 - 우리 상수가 거기 섞이면 안 된다."""
    assert not [k for k in dir(config) if k.startswith("JEV_") and "TREND" in k]


# ── 이슈 거르기 ──

def news_item(title, desc, original, pub="Thu, 29 Oct 2026 10:00:00 +0900"):
    return {"title": title, "description": desc, "originallink": original, "link": "https://n.news.naver.com/x", "pubDate": pub}


def test_issue_lane_keeps_only_relevant_articles_and_prefers_original_link():
    def h(req):
        assert req.url.path.endswith("/news") and req.url.params["sort"] == "date"
        return js({"items": [
            news_item("<b>주세</b> 개정안 국회 통과… 위스키 세율 변화", "위스키 수입사 반응", "https://www.example-news.co.kr/a/1?utm_source=x"),
            news_item("기술 혁신 포럼 개최", "예술과 기술의 만남", "https://www.example-news.co.kr/a/2"),         # '기술/예술' 은 술이 아니다
            news_item("호텔 숙소 특가 위스키 바 포함", "체크인 안내", "https://www.example-news.co.kr/a/3"),     # 제목 잡음 낱말
            news_item("전통주 온라인 판매 허용 확대", "막걸리 업계 기대", "https://www.example-news.co.kr/a/4"),
        ]})
    posts, stat = dt.collect_issues(fetcher(h), HDR, 1000)
    urls = [p["canonical_url"] for p in posts]
    assert urls == ["https://www.example-news.co.kr/a/1", "https://www.example-news.co.kr/a/4"], "추적 파라미터는 지우고, 술 이야기만"
    assert stat["irrelevant"] == 2 * len(config.DRINKS_ISSUE_QUERIES), "검색어마다 술과 무관한 2건이 걸러진다"
    p = posts[0]
    assert p["kind"] == "issue" and p["platform"] == "naver_news" and p["title"].startswith("주세 개정안")
    assert p["posted_at"] == "2026-10-29T10:00:00+09:00" and p["channel_name"] == "www.example-news.co.kr"


def test_issue_lane_survives_a_failed_query():
    def h(req):
        if req.url.params["query"] == config.DRINKS_ISSUE_QUERIES[0]:   # 안전 요청기가 재시도해도 계속 실패하는 검색어
            return httpx.Response(500, content=b"boom")
        return js({"items": [news_item("주류 규제 완화", "술 광고", f"https://news.example.kr/{req.url.params['query']}")]})
    posts, stat = dt.collect_issues(fetcher(h), HDR, 1000)
    assert stat["requests_failed"] == 1 and len(posts) == len(config.DRINKS_ISSUE_QUERIES) - 1


# ── 워커 한 바퀴 ──

class FakeRpc:
    """0059 함수의 최소 흉내 - 주소 중복 제거, (글, 제품) 유일, 판정 채우기."""

    def __init__(self):
        self.posts: dict[str, dict] = {}
        self.mentions: dict[tuple[str, str], dict] = {}
        self.calls: list[str] = []

    def __call__(self, fn, p):
        self.calls.append(fn)
        if fn == "drinks_trends_record_post":
            new = p["canonical_url"] not in self.posts
            if new:
                self.posts[p["canonical_url"]] = {**p, "id": f"post{len(self.posts)}"}
            return {"post_id": self.posts[p["canonical_url"]]["id"], "created": new}
        if fn == "drinks_trends_record_mention":
            k = (p["post_id"], p["product"])
            new = k not in self.mentions
            if new:
                self.mentions[k] = {"category": p["category"], "sentiment": None}
            if p.get("sentiment") is not None and self.mentions[k]["sentiment"] is None:
                self.mentions[k].update(sentiment=p["sentiment"], jev_p=p.get("jev_p"))
            return {"created": new, "judged": self.mentions[k]["sentiment"] is not None}
        if fn == "drinks_trends_pending_mentions":
            by_id = {v["id"]: v for v in self.posts.values()}
            return [{"post_id": pid, "product": prod, "category": m["category"], "title": by_id[pid]["title"],
                     "summary": by_id[pid].get("summary")}
                    for (pid, prod), m in self.mentions.items() if m["sentiment"] is None][: p["limit"]]
        raise AssertionError(fn)


def naver_handler(req):
    path = req.url.path
    if path.endswith("/cafearticle"):
        start = int(req.url.params["start"])
        q = req.url.params["query"]
        if start > 1:
            return js({"items": []})
        return js({"items": [
            {"title": f"<b>발베니</b> 12 후기 {q}", "link": f"https://cafe.naver.com/whiskycognac/{abs(hash(q)) % 9999}",
             "description": "발베니 12년 부드럽고 좋네요 맥캘란이랑 비교", "cafename": "위스키 코냑 클럽", "cafeurl": "https://cafe.naver.com/whiskycognac"},
            {"title": "와인 후기 발베니 아님", "link": "https://cafe.naver.com/wineclub/1", "description": "발베니", "cafename": "와인클럽",
             "cafeurl": "https://cafe.naver.com/wineclub"},                                   # 화이트리스트 밖
            {"title": f"화요일 모임 {q}", "link": f"https://cafe.naver.com/sakelove/{abs(hash(q)) % 9999}", "description": "다음 주 화요일",
             "cafename": "내가사케", "cafeurl": "https://cafe.naver.com/sakelove"},          # 제품 없음
        ]})
    return js({"items": [news_item("주세 개정 위스키 가격 영향", "위스키", f"https://news.example.kr/{abs(hash(req.url.params['query'])) % 9999}")]})


def test_run_records_whitelisted_posts_mentions_issues_and_judges_with_cap(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_TRENDS_JEV_MAX_PER_RUN", 3)
    rpc = FakeRpc()
    asked: list[str] = []

    def judge(product, title, summary):
        asked.append(product)
        return (0.8, 0.9) if product == "발베니" else (-0.4, 0.3)
    out = dt.run(rpc, fetcher(naver_handler), judge=judge, hdr=HDR)
    # 커뮤니티: 검색어 10개 × (화이트리스트 통과 2건) - 같은 검색어라도 주소가 다르면 다른 글
    assert out["community_posts"] == 2 * len(config.DRINKS_COMMUNITY_QUERIES)
    assert all("wineclub" not in u for u in rpc.posts)
    assert out["issues"] == len(config.DRINKS_ISSUE_QUERIES) and out["issues_new"] == out["issues"]
    kinds = {p["kind"] for p in rpc.posts.values()}
    assert kinds == {"community", "issue"}
    # 언급: 글마다 발베니+맥캘란(발베니 글 10개) / 화요일 글은 제품 없음
    assert out["mentions"] == 2 * len(config.DRINKS_COMMUNITY_QUERIES) and out["mentions_new"] == out["mentions"]
    assert {p for (_, p) in rpc.mentions} == {"발베니", "맥캘란"}
    # 판정은 상한 3건까지, 나머지는 null 로 남아 다음 실행에 넘어간다
    assert out["judged"] == 3 and len(asked) == 3
    judged = [m for m in rpc.mentions.values() if m["sentiment"] is not None]
    assert len(judged) == 3
    assert {m["sentiment"] for m in judged} <= {0.8, -0.4}
    # 같은 실행을 한 번 더 - 새 글·새 언급은 0, 판정 대기만 이어서 처리
    out2 = dt.run(rpc, fetcher(naver_handler), judge=judge, hdr=HDR)
    assert out2["community_new"] == 0 and out2["mentions_new"] == 0 and out2["issues_new"] == 0
    assert out2["judged"] == 3


def test_run_leaves_sentiment_null_when_jev_is_unavailable():
    rpc = FakeRpc()
    out = dt.run(rpc, fetcher(naver_handler), judge=lambda *a: None, hdr=HDR)
    assert out["judged"] == 0 and out["judge_unavailable"] == out["mentions"]
    assert rpc.mentions and all(m["sentiment"] is None for m in rpc.mentions.values()), "추측해서 채우지 않는다"


def test_run_survives_a_rejected_record_and_a_failed_search():
    rpc = FakeRpc()
    real = rpc.__call__

    def flaky(fn, p):
        if fn == "drinks_trends_record_post" and p["kind"] == "issue":
            raise RuntimeError("db down")
        return real(fn, p)
    def h(req):
        if req.url.path.endswith("/cafearticle") and req.url.params["query"] == config.DRINKS_COMMUNITY_QUERIES[1]:
            return httpx.Response(503, content=b"x")
        return naver_handler(req)
    out = dt.run(flaky, fetcher(h), judge=lambda *a: None, hdr=HDR)
    assert out["records_failed"] == len(config.DRINKS_ISSUE_QUERIES) and out["issues_new"] == 0
    assert out["requests_failed"] >= 1 and out["community_posts"] > 0


def test_run_requires_naver_key(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(naver_client_id="", naver_client_secret=""))
    with pytest.raises(FetchError) as e:
        dt.run(FakeRpc(), fetcher(naver_handler), judge=lambda *a: None)
    assert e.value.code == "api_key_missing"


def test_requests_use_the_api_hub_headers_and_stay_under_the_cap():
    seen = []

    def h(req):
        seen.append(req)
        assert req.headers["X-NCP-APIGW-API-KEY-ID"] == "id-test" and "secret-test" not in str(req.url)
        return naver_handler(req)
    f = fetcher(h)
    dt.run(FakeRpc(), f, judge=lambda *a: None, hdr=HDR)
    assert f.requests == len(seen) <= config.DRINKS_TRENDS_MAX_REQUESTS
    assert all(r.url.host == "naverapihub.apigw.ntruss.com" for r in seen)


def test_log_lines_never_carry_keys_or_summaries(caplog):
    caplog.set_level("INFO")
    dt.run(FakeRpc(), fetcher(naver_handler), judge=lambda *a: None, hdr=HDR)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "secret-test" not in text and "부드럽고" not in text


def test_workflow_has_continue_on_error_trends_step_at_the_end():
    wf = Path(__file__).resolve().parent.parent.joinpath(".github/workflows/drinks-collect.yml").read_text(encoding="utf-8")
    tail = wf[wf.index("- name: trends"):]
    assert "continue-on-error: true" in tail and "python -m engine.drinks_trends" in tail
    assert not re.search(r"^\s+- name: ", tail.split("python -m engine.drinks_trends", 1)[1], re.M), "trends 가 마지막 단계다"
