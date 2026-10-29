"""주류 동향 수집 — 술 커뮤니티에서 많이 언급되는 술 + 그 반응 + 주류 이슈. 2026-10-29. docs/deviation-drinks-trends.md

    python -m engine.drinks_trends     # drinks-collect 워크플로의 마지막 단계(실패해도 수집을 막지 않는다)

운영자: "주류 커뮤니티도 수집에 추가. 언급 많은 주류를 소재와 같이 보여줘. 긍정/부정도 점수화. 제품 말고 이슈도."
하는 일 넷:
  1) 커뮤니티 — 네이버 카페 검색(최신순)에서 **화이트리스트 카페**(config.DRINKS_COMMUNITY_CAFES) 글만 기록한다
  2) 언급 — 글 제목·요약에서 제품 사전(config.DRINKS_PRODUCT_LEXICON)의 표기를 찾아 (글, 제품) 한 건씩 기록한다
  3) 반응 — 언급마다 Jev 에 두 질문("좋게 평가하나"·"나쁘게 평가하나")을 한 호출로 묻고 점수 = p_good - p_bad (-1~1).
     한 질문만 쓰면 의견 없는 글(질문·구매글)이 '좋지 않다'로 읽혀 부정이 됐다(2026-10-29 실측) — 둘 다 낮으면 중립.
     Jev 를 못 쓰면 **null**(화면에 '판정 없음') — 추측해 채우지 않는다. 실행당 질문 상한 config.DRINKS_TRENDS_JEV_MAX_PER_RUN
     (언급 하나 = 질문 2건), 넘는 것은 다음 실행에
  4) 이슈 — 네이버 뉴스 검색에서 술 이야기(`is_relevant`)인 기사를 기록한다(제품이 아니라 세금·규제·가격·수입 소식)

규칙: 외부 요청은 안전 요청기(SafeFetcher)만 쓴다 · 검색 결과 요약만 저장(회원 전용 본문은 받지 않는다) ·
로그에는 건수만(키·요약 전문 금지) · 한 검색어가 실패해도 나머지는 계속한다.
"""

from __future__ import annotations

import email.utils
import json
import re
import sys
from datetime import timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import config
from .drinks_discover import html_text, is_relevant
from .drinks_fetch import JSON_TYPES, TEXT_TYPES, FetchError, SafeFetcher
from .drinks_parse import canonicalize
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]
#: (product, title, summary) → (점수 -1~1, p_good, p_bad) 또는 None(못 물었다).
Judge = Callable[[str, str, str], Optional[tuple[float, float, float]]]

NAVER_HOST = "naverapihub.apigw.ntruss.com"


# ── 제품 찾기 ──

class ProductMatcher:
    """사전 표기로 글에서 제품을 찾는다. 긴 표기부터 찾고, 찾은 자리는 지워 짧은 표기가 그 안에서 다시 걸리지 않게 한다.

    영문(ASCII) 표기는 앞뒤가 **영문자가 아닐 때만**(낱말 경계 - 'hwayo41' 은 걸리고 'macallanx' 는 안 걸린다),
    한글·일본어는 부분 문자열로 찾는다. 같은 제품은 글당 한 번만 센다.
    """

    def __init__(self, lexicon: dict[str, dict], false_friends: tuple[str, ...] = ()):
        self._false = tuple(x.lower() for x in false_friends)
        entries: list[tuple[str, str, str, Optional[re.Pattern]]] = []
        for canonical, spec in lexicon.items():
            for alias in spec["aliases"]:
                a = alias.lower().strip()
                if not a:
                    continue
                pat = re.compile(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])") if a.isascii() else None
                entries.append((a, canonical, spec["category"], pat))
        entries.sort(key=lambda e: (-len(e[0]), e[0]))   # 긴 표기 먼저(같은 길이는 이름순 - 결과가 매번 같게)
        self._entries = entries

    def find(self, text: str) -> list[tuple[str, str]]:
        """[(대표 이름, 주종)] - 글에서 나온 순서. 같은 제품은 한 번."""
        t = (text or "").lower()
        for w in self._false:
            t = t.replace(w, " " * len(w))
        hits: list[tuple[int, str, str]] = []
        seen: set[str] = set()
        for alias, canonical, category, pat in self._entries:
            while True:
                if pat is not None:
                    m = pat.search(t)
                    pos = m.start() if m else -1
                else:
                    pos = t.find(alias)
                if pos < 0:
                    break
                t = t[:pos] + " " * len(alias) + t[pos + len(alias):]
                if canonical not in seen:
                    seen.add(canonical)
                    hits.append((pos, canonical, category))
        hits.sort()
        return [(c, cat) for _, c, cat in hits]


_MATCHER: Optional[ProductMatcher] = None


def matcher() -> ProductMatcher:
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = ProductMatcher(config.DRINKS_PRODUCT_LEXICON, config.DRINKS_PRODUCT_FALSE_FRIENDS)
    return _MATCHER


# ── 카페 화이트리스트 ──

def cafe_slug(cafeurl: Optional[str]) -> str:
    """검색 결과의 cafeurl('https://cafe.naver.com/whiskycognac' 또는 'whiskycognac')에서 슬러그."""
    s = (cafeurl or "").strip()
    if "://" in s or s.startswith("cafe.naver.com"):
        s = urlsplit(s if "://" in s else "https://" + s).path
    return s.strip("/").split("/")[0].lower()


def in_whitelist(cafeurl: Optional[str]) -> bool:
    return cafe_slug(cafeurl) in {k.lower() for k in config.DRINKS_COMMUNITY_CAFES}


# ── 반응 점수 ──

def sentiment_from_pair(p_good: float, p_bad: float) -> float:
    """p_good(좋게 평가할 확률) - p_bad(나쁘게 평가할 확률) → 점수 -1~1, 소수 둘째 자리. 둘 다 낮으면 0 근처(중립)."""
    return round(max(-1.0, min(1.0, float(p_good) - float(p_bad))), 2)


def sentiment_label(score: Optional[float]) -> str:
    if score is None:   # 판정 없음은 Jev 를 못 썼을 때만 - 의견 없는 글은 '중립'이다
        return "판정 없음"
    if score > config.DRINKS_TRENDS_POSITIVE_ABOVE:
        return "긍정"
    if score < config.DRINKS_TRENDS_NEGATIVE_BELOW:
        return "부정"
    return "중립"


_GOOD_Q = (
    "Does the author of this community post evaluate the PRODUCT favorably (praises it, recommends it, "
    "or reports a good experience with it)?",
    {"true": "the author expresses a positive opinion of the product: praise, recommendation, enjoyment, good value",
     "false": "the author expresses no positive opinion of the product (a question, a purchase or sale notice, "
              "a price, a stock check, neutral information, or a negative opinion)"},
)
_BAD_Q = (
    "Does the author of this community post evaluate the PRODUCT unfavorably (criticizes it, warns against it, "
    "or reports a bad experience or disappointment with it)?",
    {"true": "the author expresses a negative opinion of the product: complaint, warning, disappointment, regret",
     "false": "the author expresses no negative opinion of the product (a question, a purchase or sale notice, "
              "a price, a stock check, neutral information, or a positive opinion)"},
)


def jev_sentiment(product: str, title: str, summary: str) -> Optional[tuple[float, float, float]]:
    """Jev 에게 같은 글로 두 질문을 한 호출에 묻는다 - '좋게 평가하나'·'나쁘게 평가하나'. (점수, p_good, p_bad).

    못 물었으면(꺼짐·키 없음·실패·차단기·답 모양 이상) None - 점수를 지어내지 않는다."""
    from . import decide

    if not decide.enabled():
        return None
    state = f"PRODUCT: {product}\nPOST TITLE: {title}\nPOST TEXT: {(summary or '')[:config.DRINKS_TRENDS_SUMMARY_CHARS]}"
    got = decide.noul_many(state, {"good": _GOOD_Q, "bad": _BAD_Q}, site="drink_trend_sentiment", subject=product)
    if not got or "good" not in got or "bad" not in got:
        return None
    return sentiment_from_pair(got["good"], got["bad"]), round(float(got["good"]), 4), round(float(got["bad"]), 4)


# ── 검색 결과 → 글 ──

def _naver_get(f: SafeFetcher, endpoint: str, params: dict, hdr: dict) -> list[dict]:
    # API HUB 는 JSON 본문을 text/plain 으로 내려보낸다(2026-10-23 실측) - drinks_discover.naver 와 같은 처리.
    body = f.get(f"{config.DRINKS_NAVER_SEARCH_BASE}/{endpoint}", accept=JSON_TYPES + TEXT_TYPES, headers=hdr, params=params).body
    items = json.loads(body).get("items")
    return items if isinstance(items, list) else []


def _post_date(s: Optional[str]) -> Optional[str]:
    """postdate(YYYYMMDD)나 pubDate(RFC 822) → ISO. 못 읽으면 None."""
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}T00:00:00+09:00"
    if s:
        try:
            d = email.utils.parsedate_to_datetime(s)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
        except (TypeError, ValueError):
            return None
    return None


def collect_community(f: SafeFetcher, hdr: dict, limit: int) -> tuple[list[dict], dict[str, int]]:
    posts: dict[str, dict] = {}
    stat = {"requests_failed": 0, "api_items": 0, "off_whitelist": 0}
    for q in config.DRINKS_COMMUNITY_QUERIES:
        for page in range(config.DRINKS_TRENDS_PAGES):
            try:
                items = _naver_get(f, "cafearticle", {"query": q, "display": config.DRINKS_TRENDS_DISPLAY, "sort": "date",
                                                      "start": page * config.DRINKS_TRENDS_DISPLAY + 1}, hdr)
            except FetchError as exc:
                if exc.code == "request_cap":
                    log.warning("drinks-trends: 요청 상한에 닿아 커뮤니티 검색을 멈춥니다")
                    return list(posts.values()), stat
                stat["requests_failed"] += 1
                log.warning("drinks-trends: 카페 검색 실패(%s) — 이 검색어 쪽은 건너뜁니다", exc.code)
                break
            except (ValueError, AttributeError):
                stat["requests_failed"] += 1
                log.warning("drinks-trends: 카페 검색 응답을 읽지 못했습니다 — 건너뜁니다")
                break
            stat["api_items"] += len(items)
            for it in items:
                if not in_whitelist(it.get("cafeurl")):
                    stat["off_whitelist"] += 1
                    continue
                url = canonicalize(it.get("link") or "") if it.get("link") else ""
                title = html_text(it.get("title") or "")
                if not url.startswith("https://") or not title:
                    continue
                if url in posts or len(posts) >= limit:
                    continue
                cafe = cafe_slug(it.get("cafeurl"))
                posts[url] = {
                    "kind": "community", "platform": "naver_cafe", "canonical_url": url, "title": title[:500],
                    "summary": html_text(it.get("description") or "")[:config.DRINKS_TRENDS_SUMMARY_CHARS] or None,
                    "channel_name": it.get("cafename") or config.DRINKS_COMMUNITY_CAFES.get(cafe),
                    "channel_url": f"https://cafe.naver.com/{cafe}", "posted_at": _post_date(it.get("postdate")), "query": q,
                }
            if len(items) < config.DRINKS_TRENDS_DISPLAY:
                break   # 마지막 쪽 - 다음 쪽을 부르지 않는다
    return list(posts.values()), stat


def collect_issues(f: SafeFetcher, hdr: dict, limit: int) -> tuple[list[dict], dict[str, int]]:
    posts: dict[str, dict] = {}
    stat = {"requests_failed": 0, "api_items": 0, "irrelevant": 0}
    for q in config.DRINKS_ISSUE_QUERIES:
        try:
            items = _naver_get(f, "news", {"query": q, "display": config.DRINKS_TRENDS_ISSUE_DISPLAY, "sort": "date"}, hdr)
        except FetchError as exc:
            if exc.code == "request_cap":
                log.warning("drinks-trends: 요청 상한에 닿아 이슈 검색을 멈춥니다")
                break
            stat["requests_failed"] += 1
            log.warning("drinks-trends: 뉴스 검색 실패(%s) — 이 검색어는 건너뜁니다", exc.code)
            continue
        except (ValueError, AttributeError):
            stat["requests_failed"] += 1
            log.warning("drinks-trends: 뉴스 검색 응답을 읽지 못했습니다 — 건너뜁니다")
            continue
        stat["api_items"] += len(items)
        for it in items:
            title = html_text(it.get("title") or "")
            summary = html_text(it.get("description") or "")
            if not is_relevant(title, summary):
                stat["irrelevant"] += 1
                continue
            raw = it.get("originallink") or it.get("link") or ""
            url = canonicalize(raw) if raw else ""
            if not url.startswith("http") or not title or url in posts or len(posts) >= limit:
                continue
            host = (urlsplit(url).hostname or "")
            posts[url] = {
                "kind": "issue", "platform": "naver_news", "canonical_url": url, "title": title[:500],
                "summary": summary[:config.DRINKS_TRENDS_SUMMARY_CHARS] or None, "channel_name": host or None,
                "channel_url": None, "posted_at": _post_date(it.get("pubDate")), "query": q,
            }
    return list(posts.values()), stat


# ── 실행 ──

def run(rpc: Rpc, fetcher: SafeFetcher, *, judge: Judge = jev_sentiment, hdr: Optional[dict] = None) -> dict[str, int]:
    """수집 → 기록 → 판정. 건수 요약을 돌려준다(로그에도 이 건수만 남긴다)."""
    if hdr is None:
        cid, sec = config.SECRETS.naver_client_id, config.SECRETS.naver_client_secret
        if not (cid and sec):
            raise FetchError("api_key_missing", "NAVER_CLIENT_ID/SECRET 이 없습니다 — 동향 수집은 키를 넣기 전까지 멈춰 있습니다")
        hdr = {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec}
    out = {"community_posts": 0, "community_new": 0, "mentions": 0, "mentions_new": 0, "issues": 0, "issues_new": 0,
           "judged": 0, "judge_unavailable": 0, "requests_failed": 0, "records_failed": 0}
    budget = config.DRINKS_TRENDS_MAX_POSTS_PER_RUN

    def put(fn: str, payload: dict[str, Any]) -> dict[str, Any]:
        """DB 한 건 기록. 한 건이 거절돼도(이상한 값 등) 나머지는 계속한다 - 실패는 건수로 센다."""
        try:
            return rpc(fn, payload) or {}
        except Exception as exc:  # noqa: BLE001
            out["records_failed"] += 1
            log.warning("drinks-trends: 기록 실패(%s) — %s", fn, type(exc).__name__)
            return {}

    com, cs = collect_community(fetcher, hdr, budget)
    out["requests_failed"] += cs["requests_failed"]
    for post in com:
        r = put("drinks_trends_record_post", post)
        out["community_posts"] += 1
        out["community_new"] += 1 if r.get("created") else 0
        if not r.get("post_id"):
            continue
        for product, category in matcher().find(f"{post['title']} {post.get('summary') or ''}"):
            m = put("drinks_trends_record_mention", {"post_id": r["post_id"], "product": product, "category": category})
            out["mentions"] += 1
            out["mentions_new"] += 1 if m.get("created") else 0

    iss, ist = collect_issues(fetcher, hdr, min(config.DRINKS_TRENDS_MAX_ISSUES_PER_RUN, max(0, budget - len(com))))
    out["requests_failed"] += ist["requests_failed"]
    for post in iss:
        r = put("drinks_trends_record_post", post)
        out["issues"] += 1
        out["issues_new"] += 1 if r.get("created") else 0

    # 반응 판정 - 판정 없는 언급(이번에 새로 생긴 것 + 지난번에 못 물은 것)을 상한까지. 못 물으면 null 로 남는다.
    max_mentions = max(1, config.DRINKS_TRENDS_JEV_MAX_PER_RUN // config.DRINKS_TRENDS_JEV_QUESTIONS_PER_MENTION)   # 상한은 질문 수 기준
    try:
        pending = rpc("drinks_trends_pending_mentions", {"limit": max_mentions}) or []
    except Exception as exc:  # noqa: BLE001
        out["records_failed"] += 1
        log.warning("drinks-trends: 판정 대기 목록을 읽지 못했습니다 — %s", type(exc).__name__)
        pending = []
    for m in pending[:max_mentions]:
        got = judge(m["product"], m.get("title") or "", m.get("summary") or "")
        if got is None:
            out["judge_unavailable"] += 1
            continue
        score, p_good, p_bad = got
        r = put("drinks_trends_record_mention", {"post_id": m["post_id"], "product": m["product"], "category": m["category"],
                                                 "sentiment": score, "jev_p": p_good, "jev_p_bad": p_bad})
        out["judged"] += 1 if r.get("judged") else 0
    return out


def main(argv: Optional[list[str]] = None) -> int:
    from .drinks_collect import supabase_rpc

    try:
        fetcher = SafeFetcher([NAVER_HOST], interval_sec=config.DRINKS_TRENDS_INTERVAL_SEC,
                              max_requests=config.DRINKS_TRENDS_MAX_REQUESTS)
        try:
            out = run(supabase_rpc(), fetcher)
        finally:
            fetcher.close()
    except FetchError as exc:
        log.error("drinks-trends: 중단 — %s", exc.code)
        return 1
    log.info("drinks-trends: %s", json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
