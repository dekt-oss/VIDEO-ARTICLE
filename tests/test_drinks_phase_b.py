"""주류 공장 B단계 — 안전 요청기·파서·수집 워커(네트워크 없음). 2026-10-22.

실제 요청 경로(engine/drinks_fetch.SafeFetcher)를 httpx.MockTransport 로 돌린다. DNS 는 주입한 해석기가 답한다.
DB 동작(상태·워처마크·임대·상한)은 web/lib/drinks/collect.db.test.ts 가 실제 Postgres(PGlite)로 본다.
"""
import pathlib
import re

import httpx
import pytest

from engine import config
from engine import drinks_collect as dc
from engine.drinks_fetch import FetchError, Robots, SafeFetcher, check_url, ip_is_public
from engine.drinks_parse import TRACKING_PARAM, article_links, canonicalize, decode, parse_page

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = "www.nta.go.jp"
REAL_PUBLIC = ["8.8.8.8"]


def fetcher(handler, *, hosts=(HOST,), resolver=None, max_requests=20, clock=None):
    kw = {}
    if clock:
        kw["clock"] = clock
    return SafeFetcher(list(hosts), interval_sec=3, max_requests=max_requests, transport=httpx.MockTransport(handler),
                       resolver=resolver or (lambda h, p: REAL_PUBLIC), verify_peer=False, sleep=lambda s: None, **kw)


# ── 주소 검사 ──

@pytest.mark.parametrize("url,code", [
    ("http://www.nta.go.jp/", "url_scheme"),
    ("ftp://www.nta.go.jp/", "url_scheme"),
    ("https://user:pw@www.nta.go.jp/", "url_credentials"),
    ("https://www.nta.go.jp:8443/", "url_port"),
    ("https://127.0.0.1/", "url_ip_literal"),
    ("https://[::1]/", "url_ip_literal"),
    ("https://localhost/", "url_internal_name"),
    ("https://printer.local/", "url_internal_name"),
    ("https://metadata.internal/", "url_internal_name"),
    ("https://example.com/", "host_not_allowed"),
])
def test_check_url_rejects(url, code):
    with pytest.raises(FetchError) as e:
        check_url(url, [HOST, "localhost", "printer.local", "metadata.internal"])
    assert e.value.code == code


@pytest.mark.parametrize("ip,public", [
    ("8.8.8.8", True), ("10.0.0.1", False), ("172.16.5.5", False), ("192.168.1.1", False), ("127.0.0.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("::1", False), ("fd00::1", False), ("fe80::1", False), ("::ffff:127.0.0.1", False), ("2001:4860:4860::8888", True),
])
def test_ip_is_public(ip, public):
    assert ip_is_public(ip) is public


def test_dns_pointing_inside_is_refused_before_any_request():
    calls = []
    f = fetcher(lambda r: calls.append(r) or httpx.Response(200), resolver=lambda h, p: ["10.0.0.5"])
    with pytest.raises(FetchError) as e:
        f.get(f"https://{HOST}/x")
    assert e.value.code == "private_address"
    assert calls == [] and f.requests == 0


def test_redirect_to_other_host_or_private_is_refused_each_hop():
    def handler(req):
        if req.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x")
    with pytest.raises(FetchError) as e:
        fetcher(handler).get(f"https://{HOST}/start")
    assert e.value.code == "host_not_allowed"

    def handler2(req):
        return httpx.Response(302, headers={"location": "http://www.nta.go.jp/plain"})
    with pytest.raises(FetchError) as e:
        fetcher(handler2).get(f"https://{HOST}/start")
    assert e.value.code == "url_scheme"


def test_redirect_same_host_followed_but_capped():
    def handler(req):
        n = int(req.url.path.strip("/") or 0)
        return httpx.Response(301, headers={"location": f"/{n + 1}"})
    with pytest.raises(FetchError) as e:
        fetcher(handler).get(f"https://{HOST}/0")
    assert e.value.code == "too_many_redirects"


def test_dns_rebinding_on_redirect_hop():
    seen = {"n": 0}

    def resolver(h, p):
        seen["n"] += 1
        return REAL_PUBLIC if seen["n"] == 1 else ["169.254.169.254"]

    def handler(req):
        return httpx.Response(302, headers={"location": "/next"}) if req.url.path == "/a" else httpx.Response(200)
    with pytest.raises(FetchError) as e:
        fetcher(handler, resolver=resolver).get(f"https://{HOST}/a")
    assert e.value.code == "private_address"


def test_peer_address_is_checked_when_transport_cannot_report_it():
    f = SafeFetcher([HOST], interval_sec=3, max_requests=5, sleep=lambda s: None, resolver=lambda h, p: REAL_PUBLIC,
                    transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"})))
    with pytest.raises(FetchError) as e:
        f.get(f"https://{HOST}/x")
    assert e.value.code == "peer_unknown", "상대 주소를 모르면 받지 않는다(기본 verify_peer=True)"


def test_size_type_and_declared_length_limits(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_MAX_RESPONSE_BYTES", 1000)
    big = fetcher(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"a" * 5000))
    with pytest.raises(FetchError) as e:
        big.get(f"https://{HOST}/big")
    assert e.value.code == "too_large"
    pdf = fetcher(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    with pytest.raises(FetchError) as e:
        pdf.get(f"https://{HOST}/x.pdf")
    assert e.value.code == "unsupported_type"


def test_retry_is_bounded_and_counts_against_request_cap():
    calls = []
    f = fetcher(lambda r: calls.append(1) or httpx.Response(503), max_requests=10)
    with pytest.raises(FetchError) as e:
        f.get(f"https://{HOST}/x")
    assert e.value.http_status == 503
    assert len(calls) == 1 + config.DRINKS_FETCH_RETRIES, "재시도 횟수 상한"
    g = fetcher(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok"), max_requests=2)
    g.get(f"https://{HOST}/1")
    g.get(f"https://{HOST}/2")
    with pytest.raises(FetchError) as e:
        g.get(f"https://{HOST}/3")
    assert e.value.code == "request_cap"


def test_rate_limit_waits_between_requests():
    t = {"now": 0.0}
    waits = []
    f = SafeFetcher([HOST], interval_sec=5, max_requests=5, verify_peer=False, resolver=lambda h, p: REAL_PUBLIC,
                    transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"})),
                    clock=lambda: t["now"], sleep=lambda s: waits.append(s))
    f.get(f"https://{HOST}/1")
    t["now"] = 1.0
    f.get(f"https://{HOST}/2")
    assert waits == [4.0]


def test_robots_rules_and_failure_modes():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"},
                                  content=f"User-agent: {config.DRINKS_USER_AGENT_TOKEN}\nDisallow: /private/\n".encode())
        return httpx.Response(200)
    rb = Robots(fetcher(handler))
    assert rb.allowed(f"https://{HOST}/taxes/sake/") is True
    assert rb.allowed(f"https://{HOST}/private/x") is False
    assert Robots(fetcher(lambda r: httpx.Response(404))).allowed(f"https://{HOST}/a") is True, "robots 없음 → 제한 없음"
    assert Robots(fetcher(lambda r: httpx.Response(500))).allowed(f"https://{HOST}/a") is False, "5xx → 보수적으로 금지"


# ── 파서 ──

def test_decode_shift_jis_from_meta_and_extract_content_root():
    html = ('<html><head><meta charset="Shift_JIS"><title>お酒についてのQ&amp;A｜国税庁</title></head><body>'
            '<nav>メニュー</nav><div id="contents"><h1>お酒についてのQ&amp;A</h1><p>酒類の定義を教えてください。</p>'
            '<script>alert(1)</script></div><footer>著作権</footer></body></html>').encode("cp932")
    text = decode(html, None)
    page = parse_page(text, f"https://{HOST}/q.htm", {"content_ids": ["contents"]})
    assert page.title == "お酒についてのQ&A"
    assert "酒類の定義" in page.text
    assert "alert" not in page.text and "メニュー" not in page.text and "著作権" not in page.text


def test_article_links_stay_on_host_and_prefix():
    html = ('<a href="/newsroom/a/">A</a><a href="/newsroom/">목록</a><a href="https://evil.example.com/newsroom/x">X</a>'
            '<a href="/about/">about</a><a href="/newsroom/a/?utm_source=x">A again</a><a href="/newsroom/b/?id=2">B</a>')
    page = parse_page(html, "https://www.scotch-whisky.org.uk/newsroom/")
    got = [u for u, _ in article_links(page, ["www.scotch-whisky.org.uk"], "/newsroom/")]
    assert got == ["https://www.scotch-whisky.org.uk/newsroom/a/", "https://www.scotch-whisky.org.uk/newsroom/b/?id=2"]


def test_canonicalize_keeps_meaningful_params_and_raw_encoding():
    assert canonicalize("https://WWW.NTA.go.jp:443/a?id=1&utm_source=x&fbclid=y#top") == "https://www.nta.go.jp/a?id=1"
    assert canonicalize("https://www.nta.go.jp/a?q=%E9%85%92+x") == "https://www.nta.go.jp/a?q=%E9%85%92+x"
    assert canonicalize("https://www.nta.go.jp") == "https://www.nta.go.jp/"


def test_tracking_params_match_web_normalizer():
    ts = (ROOT / "web" / "lib" / "drinks" / "actions.ts").read_text(encoding="utf-8")
    m = re.search(r"const TRACKING_PARAM = /(.+)/i;", ts)
    assert m and m.group(1) == TRACKING_PARAM.pattern, "수동 등록과 수집의 URL 정규화가 같아야 중복 판별이 맞는다"


def test_limits_match_db_function():
    sql = (ROOT / "supabase" / "migrations" / "0051_drinks_factory_phase_b.sql").read_text(encoding="utf-8")
    body = sql[sql.index("create or replace function drinks_collect_limits()"):sql.index("create or replace function drinks_limit(")]
    db = {k: int(v) for k, v in re.findall(r"'(\w+)', (\d+)", body)}
    assert db == {
        "max_active_sources": config.DRINKS_MAX_ACTIVE_SOURCES, "max_items_ceiling": config.DRINKS_MAX_ITEMS_PER_RUN,
        "max_bodies_ceiling": config.DRINKS_MAX_BODIES_PER_RUN, "runs_per_day": config.DRINKS_RUNS_PER_DAY,
        "lease_sec": config.DRINKS_RUN_LEASE_SEC, "queued_ttl_hours": 24, "min_interval_sec": config.DRINKS_MIN_INTERVAL_SEC,
    }
    assert (config.DRINKS_MAX_ITEMS_PER_RUN, config.DRINKS_MAX_BODIES_PER_RUN) == (100, 20), "명세 기본값"
    assert config.DRINKS_RUN_TIME_BUDGET_SEC < config.DRINKS_RUN_LEASE_SEC, "시간 예산이 임대보다 짧아야 중단 처리가 앞선다"


# ── 워커 ──

class FakeRpc:
    def __init__(self, fail_on=None, known=()):
        self.calls = []
        self.fail_on = fail_on or {}
        self.known = set(known)

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn in self.fail_on:
            raise dc.DbError(self.fail_on[fn], "x")
        if fn == "drinks_finish_run":
            return {"status": "finished", **p}
        if fn == "drinks_known_urls":
            return [u for u in p["urls"] if u in self.known]
        return {"ok": True}

    def items(self):
        return [p["item"] for fn, p in self.calls if fn == "drinks_collect_item"]


def run_payload(method="approved_page", entry=None, mode="collect", retry=None, **lim):
    return {
        "run_id": "r1", "lease_token": "t1", "mode": mode, "retry_urls": retry or [], "cursor_from": None,
        "limits": {"max_items": 10, "max_bodies": 2, "interval_sec": 3, "max_requests": 20, **lim},
        "source": {"id": "s1", "name": "국세청", "method": method, "entry_urls": entry or [f"https://{HOST}/a", f"https://{HOST}/b",
                   f"https://{HOST}/c"], "allowed_hosts": [HOST], "parser_config": {"content_ids": ["contents"]}},
    }


def site(pages):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        code, ctype, body = pages.get(req.url.path, (404, "text/html", b""))
        return httpx.Response(code, headers={"content-type": ctype}, content=body)
    return handler


BODY = ("<div id='contents'><h1>タイトル</h1><p>" + "本文。" * 100 + "</p></div>").encode()


def test_worker_records_body_limit_failures_and_metadata(monkeypatch):
    pages = {"/a": (200, "text/html", BODY), "/b": (503, "text/html", b""), "/c": (200, "text/html", BODY)}
    rpc = FakeRpc()
    out = dc.RunProcessor(run_payload(), rpc, fetcher(site(pages))).process()
    items = rpc.items()
    assert [i["status"] for i in items] == ["fetched", "failed", "metadata_only"], "본문 상한 2 → 세 번째는 제목·요약만"
    assert items[0]["title"] == "タイトル" and "本文" in items[0]["body_text"]
    assert items[1]["error_code"] == "http_error" and items[1]["http_status"] == 503
    assert out["status"] == "finished" and "error_code" not in out, "부분 성공 판정은 DB 가 한다"
    assert [fn for fn, _ in rpc.calls][0] == "drinks_heartbeat_run"


def test_worker_short_or_pdf_body_is_metadata_only_not_ocr():
    pages = {"/a": (200, "text/html", b"<p>short</p>"), "/b": (200, "application/pdf", b"%PDF-1.4"),
             "/c": (200, "text/html", BODY)}
    rpc = FakeRpc()
    dc.RunProcessor(run_payload(max_bodies=5), rpc, fetcher(site(pages))).process()
    st = [i["status"] for i in rpc.items()]
    assert st == ["metadata_only", "metadata_only", "fetched"]
    assert "body_text" not in rpc.items()[1]


def test_worker_listing_failure_is_fatal_and_reported():
    rpc = FakeRpc()
    out = dc.RunProcessor(run_payload(method="listing", entry=[f"https://{HOST}/news/"]), rpc,
                          fetcher(site({"/news/": (500, "text/html", b"")}))).process()
    assert rpc.items() == []
    assert out["error_code"] == "http_error", "목록 실패를 정상 0건으로 보내지 않는다"


def test_worker_time_budget_aborts_and_lease_loss_stops(monkeypatch):
    t = {"now": 0.0}

    def handler(req):
        t["now"] += 400  # 요청 하나가 400초 걸린 것처럼
        return site({"/a": (200, "text/html", BODY), "/b": (200, "text/html", BODY), "/c": (200, "text/html", BODY)})(req)
    rpc = FakeRpc()
    out = dc.RunProcessor(run_payload(), rpc, fetcher(handler, clock=lambda: t["now"]), clock=lambda: t["now"]).process()
    assert out["aborted"] is True and out["error_code"] == "time_budget"
    assert len(rpc.items()) < 3

    lost = FakeRpc(fail_on={"drinks_collect_item": "lease_lost"})
    out = dc.RunProcessor(run_payload(), lost, fetcher(site({"/a": (200, "text/html", BODY)}))).process()
    assert out == {"status": "lease_lost"}
    assert not any(fn == "drinks_finish_run" for fn, _ in lost.calls), "임대를 잃으면 끝내기도 시도하지 않는다"


def test_worker_retry_uses_only_failed_urls_and_validate_caps_items():
    rpc = FakeRpc()
    dc.RunProcessor(run_payload(mode="retry", retry=[f"https://{HOST}/b"]), rpc,
                    fetcher(site({"/b": (200, "text/html", BODY)}))).process()
    assert [i["canonical_url"] for i in rpc.items()] == [f"https://{HOST}/b"]
    many = [f"https://{HOST}/{i}" for i in range(10)]
    rpc2 = FakeRpc()
    dc.RunProcessor(run_payload(mode="validate", entry=many), rpc2, fetcher(site({}))).process()
    assert len(rpc2.items()) == config.DRINKS_VALIDATE_ITEMS


def test_worker_never_changes_source_state_or_calls_llm():
    src = (ROOT / "engine" / "drinks_collect.py").read_text(encoding="utf-8")
    for banned in ["drinks_source_action", "drinks_register_source"]:
        assert banned not in src, banned
    for f in ["drinks_fetch.py", "drinks_parse.py", "drinks_collect.py"]:
        code = (ROOT / "engine" / f).read_text(encoding="utf-8")
        imports = "\n".join(l for l in code.splitlines() if re.match(r"\s*(import|from)\s", l))
        for mod in ["anthropic", "gemini", "deepseek", "llm", "providers", "translate", "jev", "cost"]:
            assert mod not in imports.lower(), f"{f}: {mod} 를 import 하면 유료·LLM 경로가 열린다"
        assert "follow_redirects=True" not in code
        assert "util.http_get" not in code and "http_get(" not in code, "재시도·리다이렉트가 다른 공용 요청기는 쓰지 않는다"


def test_collect_workflow_is_least_privilege_and_runs_the_worker():
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "drinks-collect.yml").read_text(encoding="utf-8"))
    assert wf["permissions"] == {"contents": "read"}
    on = wf.get("on") or wf.get(True)
    assert "workflow_dispatch" in on and on["schedule"][0]["cron"] == "30 21 * * *"
    run = "\n".join(s.get("run", "") for s in wf["jobs"]["collect"]["steps"])
    assert "python -m engine.drinks_collect" in run
    env = wf["jobs"]["collect"]["env"]
    assert not any(k in env for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY")), "LLM 키를 주지 않는다"


# ── 검토 반영(2026-10-22) ──

def test_connection_is_pinned_to_the_checked_ip():
    """검사 뒤 DNS 답이 내부 주소로 바뀌어도(재바인딩) 연결 직전 다시 해석·검사해 소켓을 열지 않는다."""
    answers = iter([REAL_PUBLIC, ["127.0.0.1"]])
    f = SafeFetcher([HOST], interval_sec=3, max_requests=5, sleep=lambda s: None, resolver=lambda h, p: next(answers))
    from engine.drinks_fetch import PinnedBackend
    assert isinstance(f._client._transport._pool._network_backend, PinnedBackend)
    with pytest.raises(FetchError) as e:
        f.get(f"https://{HOST}/x")
    assert e.value.code == "private_address"


def test_declared_content_length_over_cap_is_refused(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_MAX_RESPONSE_BYTES", 1000)
    f = fetcher(lambda r: httpx.Response(200, headers={"content-type": "text/html", "content-length": "99999"},
                                         content=b"x"))
    with pytest.raises(FetchError) as e:
        f.get(f"https://{HOST}/x")
    assert e.value.code == "too_large"


def test_worker_reports_unfetched_new_items_and_prefers_unknown_urls():
    urls = [f"https://{HOST}/{c}" for c in "abc"]
    pages = {f"/{c}": (200, "text/html", BODY) for c in "abc"}
    rpc = FakeRpc(known=[urls[0]])
    out = dc.RunProcessor(run_payload(entry=urls, max_bodies=1), rpc, fetcher(site(pages))).process()
    items = rpc.items()
    assert [i["canonical_url"] for i in items] == [urls[1], urls[2], urls[0]], "처음 보는 글 먼저"
    assert [i["status"] for i in items] == ["fetched", "metadata_only", "metadata_only"]
    assert out["incomplete_count"] == 1, "본문 상한 때문에 못 가져온 새 글은 '다 못 봤음'으로 알린다"
    rpc2 = FakeRpc()
    out2 = dc.RunProcessor(run_payload(entry=urls, max_items=2, max_bodies=5), rpc2, fetcher(site(pages))).process()
    assert out2["incomplete_count"] == 1 and len(rpc2.items()) == 2, "문서 상한 밖의 새 글도 센다"


def test_worker_robots_unavailable_is_failure_not_skip():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=BODY)
    rpc = FakeRpc()
    dc.RunProcessor(run_payload(), rpc, fetcher(handler)).process()
    assert {i["status"] for i in rpc.items()} == {"failed"}
    assert {i["error_code"] for i in rpc.items()} == {"robots_unavailable"}


def test_worker_unexpected_exception_still_finishes_the_run():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        raise RuntimeError("boom")
    rpc = FakeRpc()
    out = dc.RunProcessor(run_payload(), rpc, fetcher(handler)).process()
    assert out["error_code"] == "worker_error"
    assert rpc.calls[-1][0] == "drinks_finish_run"
    bad = run_payload()
    bad["source"]["parser_config"] = {"exclude_patterns": ["("]}
    out = dc.RunProcessor(bad, FakeRpc(), fetcher(site({}))).process()
    assert out["error_code"] == "parser_config_invalid"


def test_worker_request_cap_aborts_the_run():
    pages = {f"/{c}": (200, "text/html", BODY) for c in "abc"}
    out = dc.RunProcessor(run_payload(max_requests=2, max_bodies=5), FakeRpc(), fetcher(site(pages), max_requests=2)).process()
    assert out["aborted"] is True and out["error_code"] == "request_cap"


def test_worker_feed_counts_offhost_and_parsed_entries():
    feed = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
            b'<item><title>A</title><link>https://www.nta.go.jp/a</link></item>'
            b'<item><title>B</title><link>https://other.example.com/b</link></item></channel></rss>')
    pages = {"/feed": (200, "application/rss+xml", feed), "/a": (200, "text/html", BODY)}
    rpc = FakeRpc()
    out = dc.RunProcessor(run_payload(method="feed", entry=[f"https://{HOST}/feed"]), rpc, fetcher(site(pages))).process()
    assert out["parsed_count"] == 2 and out["offhost_count"] == 1
    assert [i["canonical_url"] for i in rpc.items()] == [f"https://{HOST}/a"]
