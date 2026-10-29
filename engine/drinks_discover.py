"""주류 공장 B 보완 — 커뮤니티·SNS 소재 발견(2026-10-22). docs/deviation-drinks-discovery.md

발견 자료는 **사실 근거가 아니다** — 사람들이 무엇을 궁금해하는지의 신호다. 여기서 하는 일:
  1) 공식 API 로 공개 글·영상의 제목·요약·공개 지표·질문 문장을 모은다(커넥터 3개, 아래)
  2) 규칙으로 질문·논쟁·오해·선택/보관·신제품/행사 신호를 붙인다(LLM 0회)
  3) 비슷한 자료를 소재 후보로 묶는다(provisional, 기준 discovery-v1). 승인·편성은 사람이 A단계 흐름에서 한다

커넥터(공식 API 만, 로그인·차단 우회·비공개 수집 없음):
  · stackexchange — Beer, Wine & Spirits(alcohol.stackexchange.com). 키 없이 하루 300회. 글은 CC BY-SA 4.0
  · youtube       — YouTube Data API v3(search·videos·commentThreads). YOUTUBE_DATA_API_KEY 필요 — 없으면 실행 실패(api_key_missing)
  · naver         — 네이버 검색 API(카페글·블로그). NAVER_CLIENT_ID/SECRET 필요. 검색 결과 요약만 — 회원 전용 본문은 받지 않는다
  인스타그램·레딧 등은 자동 수집하지 않는다(공식 API 조건 미충족) — 운영자 수동 링크로만 들어온다.

지표는 **제공된 것만** 저장한다. 미제공 지표를 0 으로 채우지 않고, 플랫폼끼리 더하지 않는다.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Callable, Optional

from . import config, decide
from .drinks_fetch import JSON_TYPES, TEXT_TYPES, FetchError, SafeFetcher
from .drinks_parse import canonicalize, clean_text
from .util import log

# ── 신호(규칙) ── 한국어·일본어·영어. 판정이 아니라 후보 카드의 단서다.
SIGNAL_PATTERNS: dict[str, re.Pattern] = {
    "question": re.compile(r"[?？]|왜|어떻게|무엇|뭐가|뭔가요|궁금|なぜ|どう|ですか|\b(why|how|what|which|is it|should i|can i)\b", re.I),
    "debate": re.compile(r"\bvs\.?\b|대\s|논쟁|호불호|갑론|どっち|派|\b(versus|debate|overrated|controversial)\b", re.I),
    "misconception": re.compile(r"오해|사실은|잘못 알|속설|誤解|本当は|\b(myth|misconception|actually|is it true)\b", re.I),
    "selection": re.compile(r"추천|고르|입문|선택|차이|おすすめ|選び|違い|\b(recommend|choose|which one|difference|beginner|best)\b", re.I),
    "storage": re.compile(r"보관|냉장|개봉|유통기한|상했|숙성|保存|開栓|冷蔵|賞味|\b(store|storage|shelf|expire|freez|fridge|old bottle|opened|open bottle|how long[^.?!]*\blasts?)\b", re.I),
    "new_product": re.compile(r"신제품|출시|한정판|리뉴얼|新発売|限定|発売|\b(new release|launch|limited edition)\b", re.I),
    "event": re.compile(r"행사|페스티벌|축제|시음회|박람회|イベント|祭|試飲会|\b(festival|tasting event|expo|fair)\b", re.I),
}

_URL = re.compile(r"https?://\S+|www\.\S+")
_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[。？！])|\n+")   # 일본어·중국어 문장부호 뒤에는 띄어쓰기가 없다
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    for w in config.DRINKS_RELEVANCE_FALSE_FRIENDS:
        t = t.replace(w, " ")
    return any(x in t for x in terms)


def is_relevant(title: Optional[str], summary: Optional[str]) -> bool:
    """술 이야기인가(규칙). 제목+요약에 술 낱말이 하나라도 있고, **제목에** 상거래·여행 잡음 낱말이 없어야 한다."""
    if any(n in (title or "") for n in config.DRINKS_NOISE_TERMS):
        return False
    return _has_term(f"{title or ''} {summary or ''}", tuple(x.lower() for x in config.DRINKS_RELEVANCE_TERMS))


_RELEVANCE_TERMS_LOWER = tuple(x.lower() for x in config.DRINKS_RELEVANCE_TERMS)


def question_max_chars(q: str) -> int:
    """질문 문장 길이 상한. 한글·한자·가나 문장은 짧게(네이버 요약은 문장부호가 없어 문단 전체가 한 문장이 된다), 그 밖은 넉넉히."""
    return config.DRINKS_QUESTION_MAX_CHARS if _CJK.search(q) else config.DRINKS_QUESTION_MAX_CHARS_LATIN


def question_ok(q: Optional[str]) -> bool:
    """후보가 될 자격이 있는 질문인가(규칙): 길이 상한 안이고, **질문 문장 자체에** 술 낱말(오탈자 낱말 '기술' 같은 것은 제외)이 있다."""
    q = clean_text(q or "")
    return bool(q) and len(q) <= question_max_chars(q) and _has_term(q, _RELEVANCE_TERMS_LOWER)


def good_questions(it: dict) -> list[str]:
    return [q for q in (it.get("questions") or []) if question_ok(q)]


def extract_signals(text: str) -> list[str]:
    clean = _URL.sub(" ", text or "")
    out = [k for k, p in SIGNAL_PATTERNS.items() if p.search(clean)]
    if "storage" in out and not _has_term(clean, tuple(x.lower() for x in (*config.DRINKS_RELEVANCE_TERMS, *config.DRINKS_STORAGE_EXTRA_TERMS))):
        out.remove("storage")   # 호텔 '짐 보관' 처럼 술 이야기가 아닌 보관은 보관 신호가 아니다
    return out


_TRAILING_PUNCT = " .,!…·~)]}\"'”’。"
_HANGUL = re.compile(r"[가-힯]")


def _is_question(sent: str) -> bool:
    if not sent.endswith(("?", "？")):
        return _is_korean_question_ending(sent)
    body = sent.rstrip("?？ ")
    if _CJK.search(body):
        return len(body) >= 6
    return len(re.findall(r"[A-Za-z]{2,}", body)) >= 3   # "(?)" 같은 조각·한두 단어는 질문으로 치지 않는다


def _is_korean_question_ending(sent: str) -> bool:
    """물음표 없이 끝말로 질문을 알아본다(네이버 요약은 물음표가 잘린다). 한글 6자 이상 + 끝말 + 뒤에는 문장부호만."""
    body = sent.rstrip(_TRAILING_PUNCT)
    if len(_HANGUL.findall(body)) < 6:
        return False
    return body.endswith(config.DRINKS_QUESTION_ENDINGS_KO)


def extract_questions(*texts: str, limit: int = 5) -> list[str]:
    """원문의 질문 문장(물음표로 끝나거나, 한글 문장이 질문 끝말로 끝나는 것)만. 주소는 먼저 지운다. 번역·요약하지 않는다.
    길이 상한(DRINKS_QUESTION_MAX_CHARS)을 넘는 문장은 질문으로 치지 않는다 — 문장부호 없는 요약 전체가 질문이 되던 것을 막는다."""
    out: list[str] = []
    for t in texts:
        for sent in _SPLIT.split(_URL.sub(" ", t or "")):
            q = clean_text(sent).lstrip(")]}>-–·,;: ")
            if q and len(q) <= question_max_chars(q) and _is_question(q) and q not in out:
                out.append(q)
            if len(out) >= limit:
                return out
    return out


def html_text(raw: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", html_mod.unescape(raw or "")))


# ── 커넥터 ──

@dataclass
class Found:
    url: str
    platform: str
    title: Optional[str]
    summary: Optional[str]
    channel_name: Optional[str] = None
    external_id: Optional[str] = None
    posted_at: Optional[str] = None
    metrics: dict[str, int] = field(default_factory=dict)
    coverage: str = "title_summary"
    comments: list[str] = field(default_factory=list)

    def item(self) -> dict[str, Any]:
        text = " ".join(x for x in [self.title, self.summary, *self.comments] if x)
        return {
            "status": "fetched", "platform": self.platform, "canonical_url": canonicalize(self.url), "external_id": self.external_id,
            "channel_name": self.channel_name, "title": self.title,
            "summary": (self.summary or "")[: config.DRINKS_DISCOVERY_SUMMARY_CHARS] or None,
            "posted_at": self.posted_at, "metrics": self.metrics, "coverage": self.coverage,
            "questions": extract_questions(self.title or "", self.summary or "", *self.comments),
            "signals": extract_signals(text),
        }


@dataclass
class Batch:
    found: list[Found]
    parsed: int            # API 가 돌려준 결과 수(필터 전)
    incomplete: int = 0    # 상한·백오프 때문에 더 있는데 못 가져온 것
    # 오래된 것부터 받은 경우 "여기까지는 빠짐없이 봤다"는 시각(상한에 걸려도 워처마크를 거기까지 옮긴다)
    advance_to: Optional[str] = None


def _epoch_iso(v: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _metric(d: dict, key: str, allow_negative: bool = False) -> Optional[int]:
    v = d.get(key)
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 or allow_negative else None   # 비추천 점수(음수)는 제공된 값이다


def _metrics(pairs: dict[str, Optional[int]]) -> dict[str, int]:
    return {k: v for k, v in pairs.items() if v is not None}  # 없는 지표는 키 자체를 빼고 0 을 만들지 않는다


def first_run_start(cfg: dict, now: Optional[datetime] = None) -> datetime:
    """첫 실행의 시작 시각. 수집원 설정의 lookback_days(1~3650)가 있으면 그것을, 없으면 전역 기본값(365일)을 쓴다.
    (DB 가 등록 때 이미 막지만 여기서도 범위를 지킨다 — 손으로 바꾼 설정이 천장을 넘지 못하게.)"""
    days = config.DRINKS_DISCOVERY_BACKFILL_DAYS
    v = cfg.get("lookback_days")
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= config.DRINKS_DISCOVERY_LOOKBACK_MAX_DAYS:
        days = v
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def stackexchange(f: SafeFetcher, cfg: dict, since: Optional[datetime], limit: int) -> Batch:
    """오래된 것부터(생성 시각 오름차순) 받는다 — 상한에 걸리면 "빠짐없이 본 데까지"만 워처마크가 전진한다.
    태그는 따로 묻는다(tagged 는 AND). 더 남은 태그가 있으면, 그 태그가 이번에 받은 마지막 글 시각을 넘어 전진하지 않는다
    (넘으면 그 태그의 사이 글을 건너뛴다). 첫 실행은 수집원별 lookback_days, 없으면 최근 DRINKS_DISCOVERY_BACKFILL_DAYS 일부터."""
    found: list[Found] = []
    parsed = incomplete = 0
    tags = [t for t in (cfg.get("queries") or []) if t]
    start = since or first_run_start(cfg)
    page, has_more, last_ts = 1, True, None
    safe_ts: Optional[int] = None   # 더 남은 태그들이 이번에 받은 마지막 글 시각 중 가장 이른 것
    backoff = False
    while has_more and len(found) < limit and not backoff:
        # Stack Exchange 의 tagged 는 AND 다 — 태그마다 따로 묻되, 같은 시작 시각에서 오름차순으로.
        items_all = []
        more_any = False
        for tag in tags:
            params = {"site": cfg.get("site") or "alcohol", "tagged": tag, "order": "asc", "sort": "creation",
                      "pagesize": min(50, limit), "page": page, "filter": "withbody", "fromdate": int(start.timestamp())}
            res = f.get("https://api.stackexchange.com/2.3/questions", accept=JSON_TYPES, params=params)
            data = json.loads(res.body.decode("utf-8"))
            if "error_id" in data:
                raise FetchError("api_error", f"Stack Exchange 오류 {data.get('error_id')}: {data.get('error_name')}")
            got = data.get("items") or []
            items_all += [(tag, it) for it in got]
            more_any = more_any or bool(data.get("has_more"))
            if data.get("has_more") and got:
                t_last = max(int(it.get("creation_date") or 0) for it in got)
                safe_ts = t_last if safe_ts is None else min(safe_ts, t_last)
            if data.get("backoff"):   # API 가 기다리라고 했다 — 이 실행에서는 더 묻지 않는다(쪽 넘김도 멈춤)
                more_any = True
                backoff = True
                break
        items_all.sort(key=lambda x: x[1].get("creation_date") or 0)
        seen = {fd.external_id for fd in found}
        items = []
        for tag, it in items_all:
            if str(it.get("question_id") or "") in seen:
                continue
            seen.add(str(it.get("question_id") or ""))
            items.append((tag, it))
        parsed += len(items)
        for tag, it in items:
            if len(found) >= limit:
                more_any = True
                break
            last_ts = it.get("creation_date")
            found.append(Found(
                url=it.get("link") or "", platform="stackexchange", title=html_text(it.get("title") or "") or None,
                summary=html_text(it.get("body") or "")[: config.DRINKS_DISCOVERY_SUMMARY_CHARS] or None,
                channel_name=f"Beer, Wine & Spirits SE · {tag}", external_id=str(it.get("question_id") or ""),
                posted_at=_epoch_iso(it.get("creation_date")),
                metrics=_metrics({"views": _metric(it, "view_count"), "score": _metric(it, "score", allow_negative=True),
                                  "answers": _metric(it, "answer_count")})))
        has_more = more_any
        page += 1
        if page > 5:   # 실행당 쪽 상한(요청 수 상한과 별개 안전장치)
            break
    if has_more:
        incomplete += 1
    advance = None
    if has_more and last_ts:
        advance = _epoch_iso(min(int(last_ts), safe_ts) if safe_ts is not None else int(last_ts))
    return Batch(found, parsed, incomplete, advance)


def youtube(f: SafeFetcher, cfg: dict, since: Optional[datetime], limit: int) -> Batch:
    key = config.SECRETS.youtube_data_api_key
    if not key:
        raise FetchError("api_key_missing", "YOUTUBE_DATA_API_KEY 가 없습니다 — 유튜브 발견은 키를 넣기 전까지 멈춰 있습니다")
    hdr = {"X-Goog-Api-Key": key}
    found: list[Found] = []
    parsed = incomplete = dropped = 0
    queries = (cfg.get("queries") or [])[: config.DRINKS_YT_SEARCH_MAX_QUERIES]   # 등록 때 3개로 막는다(0052)
    for q in queries:
        params = {"part": "snippet", "q": q, "type": "video", "order": "date", "maxResults": min(25, max(1, limit - len(found)))}
        if since:
            params["publishedAfter"] = since.isoformat().replace("+00:00", "Z")
        s = json.loads(f.get("https://www.googleapis.com/youtube/v3/search", accept=JSON_TYPES, params=params, headers=hdr).body)
        vids = [x for x in s.get("items") or [] if (x.get("id") or {}).get("videoId")]
        parsed += len(vids)
        # 최신순이라 상한 밖의 글은 '받은 데까지 전진'을 할 수 없다 — 워처마크 이후 새 영상이 상한을 넘을 때만 다 못 봤다고 센다.
        if s.get("nextPageToken") and since is not None:
            incomplete += 1
        if not vids:
            continue
        ids = ",".join(x["id"]["videoId"] for x in vids)
        v = json.loads(f.get("https://www.googleapis.com/youtube/v3/videos", accept=JSON_TYPES,
                             params={"part": "statistics,snippet", "id": ids}, headers=hdr).body)
        by_id = {x["id"]: x for x in v.get("items") or []}
        for x in vids:
            vid = x["id"]["videoId"]
            meta = by_id.get(vid, {})
            sn = meta.get("snippet") or x.get("snippet") or {}
            if not is_relevant(sn.get("title"), clean_text(sn.get("description") or "")):
                dropped += 1
                continue
            st = meta.get("statistics") or {}
            comments: list[str] = []
            coverage = "title_summary"
            try:
                c = json.loads(f.get("https://www.googleapis.com/youtube/v3/commentThreads", accept=JSON_TYPES,
                                     params={"part": "snippet", "videoId": vid, "maxResults": config.DRINKS_YT_COMMENTS_PER_VIDEO,
                                             "textFormat": "plainText", "order": "relevance"}, headers=hdr).body)
                comments = [((t.get("snippet") or {}).get("topLevelComment") or {}).get("snippet", {}).get("textDisplay", "")
                            for t in c.get("items") or []]
                comments = [clean_text(t)[:300] for t in comments if t]
                coverage = "title_summary_comments"
            except FetchError as exc:
                if exc.code == "request_cap":
                    raise
                # 댓글 사용 중지(403) 등 — 댓글 없이 제목·설명만. 실패로 숨기지 않고 확보 범위로 드러낸다.
            found.append(Found(
                url=f"https://www.youtube.com/watch?v={vid}", platform="youtube", title=sn.get("title"),
                summary=clean_text(sn.get("description") or "")[: config.DRINKS_DISCOVERY_SUMMARY_CHARS] or None,
                channel_name=sn.get("channelTitle"), external_id=vid, posted_at=sn.get("publishedAt"),
                metrics=_metrics({"views": _metric(st, "viewCount"), "likes": _metric(st, "likeCount"),
                                  "comments": _metric(st, "commentCount")}),
                coverage=coverage, comments=[t for t in comments if extract_questions(t)][:5]))
            if len(found) >= limit:
                break
    if dropped:
        log.info("drinks: 유튜브 발견 — 술과 무관·잡음으로 %d건 제외(API 결과 %d건)", dropped, parsed)
    return Batch(found, parsed, incomplete)


def kst_day_ordinal() -> int:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date().toordinal()


def naver_start(per_call: int, day_ordinal: Optional[int] = None) -> int:
    """정확도순 검색의 시작 위치: 날짜 순번 % 회전 수 만큼 한 쪽씩 민다(네이버 상한 1000)."""
    n = kst_day_ordinal() if day_ordinal is None else day_ordinal
    return min(config.DRINKS_NAVER_MAX_START, 1 + (n % max(1, config.DRINKS_NAVER_PAGE_ROTATION)) * per_call)


def naver(f: SafeFetcher, cfg: dict, since: Optional[datetime], limit: int) -> Batch:
    cid, sec = config.SECRETS.naver_client_id, config.SECRETS.naver_client_secret
    if not (cid and sec):
        raise FetchError("api_key_missing", "NAVER_CLIENT_ID/SECRET(네이버 클라우드 API HUB 키)이 없습니다 — 네이버 발견은 키를 넣기 전까지 멈춰 있습니다")
    hdr = {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec}
    found: list[Found] = []
    parsed = incomplete = dropped = 0
    hub = config.DRINKS_NAVER_SEARCH_BASE
    kinds = [(k, p, b) for k, p, b in [("cafearticle", "naver_cafe", f"{hub}/cafearticle"), ("blog", "naver_blog", f"{hub}/blog")]
             if k in (cfg.get("kinds") or ["cafearticle", "blog"])]
    queries = list(cfg.get("queries") or [])
    sim = config.DRINKS_NAVER_SORT == "sim"
    # 검색어 × 종류를 **한 번씩 모두** 부른다 — 앞의 검색어가 한도를 다 채워 뒤의 검색어가 굶던 것(첫 운영 실행: 6개 중 2개)을 막는다.
    per_call = max(1, min(config.DRINKS_NAVER_MAX_DISPLAY, limit // max(1, len(kinds) * len(queries))))
    # 정확도순(sim)은 시간순이 아니다 — 워처마크·날짜 필터·"꽉 찬 쪽" 판정이 모두 의미가 없고(URL 중복 제거가 반복을 막는다),
    #   매일 같은 상위 결과만 보지 않게 날짜 순번으로 시작 위치를 돌린다.
    start = naver_start(per_call) if sim else None
    for kind, platform, base in kinds:
        for q in queries:
            # API HUB 는 JSON 본문을 text/plain 으로 내려보낸다(2026-10-23 실측) — 이 커넥터만 그 형식을 받는다.
            #   본문은 아래 json.loads 가 읽으므로 JSON 이 아니면 그대로 실패한다.
            d = json.loads(f.get(base, accept=JSON_TYPES + TEXT_TYPES, headers=hdr,
                                 params={"query": q, "display": per_call, "sort": config.DRINKS_NAVER_SORT,
                                         **({"start": start} if sim else {})}).body)
            items = d.get("items") or []
            parsed += len(items)
            # 한 쪽을 꽉 채웠고 가장 오래된 글도 워처마크 날짜 이후면 더 있을 수 있다 — 다 못 봤다고 센다(조용히 자르지 않게).
            if since and not sim and items and len(items) >= per_call:
                oldest = min((it.get("postdate") or "99999999") for it in items)
                if oldest >= since.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d"):
                    incomplete += 1
            for it in items:
                title = html_text(it.get("title") or "") or None
                summary = html_text(it.get("description") or "") or None
                if not is_relevant(title, summary):
                    dropped += 1
                    continue
                posted = None
                pd = it.get("postdate")
                if pd and re.fullmatch(r"\d{8}", pd):
                    posted = f"{pd[:4]}-{pd[4:6]}-{pd[6:]}T00:00:00+09:00"
                found.append(Found(
                    url=it.get("link") or "", platform=platform, title=title, summary=summary,
                    channel_name=it.get("cafename") or it.get("bloggername"), posted_at=posted,
                    coverage="title_summary"))  # 회원 전용 카페 본문은 받지 않는다 — 검색 결과 요약만
    if dropped:
        log.info("drinks: 네이버 발견 — 술과 무관·잡음으로 %d건 제외(API 결과 %d건, 호출당 %d건)", dropped, parsed, per_call)
    if since and not sim:
        # 네이버 게시일은 '날짜'뿐이다(시각 없음) — 워처마크와 시각으로 비교하면 같은 날 늦게 올라온 글을 잃는다(검토 지적).
        # 한국 날짜로 비교하고, 같은 날 글은 다시 받아 URL 로 중복을 거른다.
        since_day = since.astimezone(ZoneInfo("Asia/Seoul")).date()
        found = [x for x in found if not x.posted_at or datetime.fromisoformat(x.posted_at).date() >= since_day]
    return Batch(found, parsed, incomplete)


CONNECTORS: dict[str, Callable[[SafeFetcher, dict, Optional[datetime], int], Batch]] = {
    "stackexchange": stackexchange, "youtube": youtube, "naver": naver,
}


# ── 실행 처리(발견용 수집원) ──

QUESTION_REQUIRED_PLATFORMS = ("naver_cafe", "naver_blog", "youtube")


class DiscoveryProcessor:
    def __init__(self, run: dict[str, Any], rpc, fetcher: SafeFetcher):
        self.run, self.rpc, self.fetcher = run, rpc, fetcher
        self.src = run["source"]

    def _lease(self, p: dict) -> dict:
        return {"run_id": self.run["run_id"], "lease_token": self.run["lease_token"], **p}

    def process(self) -> dict[str, Any]:
        from .drinks_collect import DbError

        validate = self.run["mode"] == "validate"
        limit = config.DRINKS_VALIDATE_ITEMS if validate else int(self.run["limits"]["max_items"])
        since = None
        if self.run.get("cursor_from") and not validate:
            since = datetime.fromisoformat(str(self.run["cursor_from"]).replace("Z", "+00:00"))
        fatal: Optional[FetchError] = None
        aborted: Optional[tuple[str, str]] = None
        batch = Batch([], 0)
        try:
            conn = CONNECTORS.get(self.src.get("platform") or "")
            if conn is None:
                raise FetchError("method_unsupported", f"발견 채널이 아닙니다: {self.src.get('platform')}")
            batch = conn(self.fetcher, self.src.get("parser_config") or {}, since, limit)
            self.rpc("drinks_heartbeat_run", self._lease({"listed_count": len(batch.found), "request_count": self.fetcher.requests}))
            no_question = 0
            for fd in batch.found[:limit]:
                item = fd.item()
                # 네이버·유튜브는 질문 문장이 후보 자격(술 낱말 + 길이 상한)을 갖춘 글만 저장한다 — 안 그러면 후보가 될 수 없는 자료가
                #   발견함 조회 창(오래된 순 500건)을 채워 새 자료를 밀어낸다. Stack Exchange 는 종전대로 다 저장한다.
                if fd.platform in QUESTION_REQUIRED_PLATFORMS and not good_questions(item):
                    no_question += 1
                    continue
                try:
                    self.rpc("drinks_collect_discovery", self._lease({"item": item}))
                except DbError as exc:
                    if exc.code == "lease_lost":
                        return {"status": "lease_lost"}
                    if exc.code == "host_not_allowed":
                        batch.incomplete += 1  # 채널 밖 주소로 이어진 결과 — 세어서 부분 성공으로
                        continue
                    if exc.code == "limit_exceeded":
                        aborted = (exc.code, exc.message)
                        break
                    raise
            batch.incomplete += max(0, len(batch.found) - limit)
            if no_question:
                log.info("drinks: 질문 없음 제외 %d건(받은 글 %d건 중) — 질문 문장에 술 낱말이 없거나 너무 길어 저장하지 않았다",
                         no_question, len(batch.found))
        except FetchError as exc:
            if exc.code == "request_cap":
                aborted = (exc.code, exc.message)
            else:
                fatal = exc
        except DbError as exc:
            if exc.code == "lease_lost":
                return {"status": "lease_lost"}
            fatal = FetchError("db_error", exc.message)
        except Exception as exc:  # noqa: BLE001
            log.exception("drinks: 발견 실행 %s 예외", self.run["run_id"])
            fatal = FetchError("worker_error", f"워커 예외: {type(exc).__name__}")
        finally:
            self.fetcher.close()
        payload: dict[str, Any] = {"listed_count": len(batch.found), "request_count": self.fetcher.requests,
                                   "parsed_count": batch.parsed, "incomplete_count": 0 if validate else batch.incomplete}
        if batch.advance_to and not validate:
            payload["advance_to"] = batch.advance_to
        if aborted:
            payload.update(aborted=True, error_code=aborted[0], error_message=aborted[1])
        elif fatal:
            payload.update(error_code=fatal.code, error_message=fatal.message)
        try:
            return self.rpc("drinks_finish_run", self._lease(payload))
        except DbError as exc:
            if exc.code == "lease_lost":
                return {"status": "lease_lost"}
            raise


# ── 후보 묶기(규칙, discovery-v1) ──

# 묶기용 낱말: 흔한 낱말·주종 이름은 뺀다("sake" 가 겹친다고 같은 질문이 아니다). 한·중·일 글자는 두 글자 조각.
_STOP = set("""a an the is are was were be been do does did of to in on for with and or but it its this that these those
i you we they my your our can could should would will how what why which when where who whom there here as at by from
about into than then so if not no yes any some much many more most very really just also get got have has had""".split()) | {
    "sake", "whisky", "whiskey", "scotch", "bottle", "bottles", "drink", "drinks", "alcohol", "liquor",
    "사케", "위스키", "전통주", "막걸리", "소주", "술", "酒", "日本酒", "ウイスキー"}


def _tokens(s: str) -> set[str]:
    s = _URL.sub(" ", (s or "").lower())
    words = {w for w in re.findall(r"[a-z0-9]{3,}", s) if w not in _STOP}
    for run in re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", s):
        if run in _STOP:
            continue
        words |= {run[i:i + 2] for i in range(len(run) - 1)} if len(run) > 1 else set()
    return words - _STOP


def similarity(a: str, b: str) -> float:
    """낱말 Jaccard. 겹친 낱말이 2개 미만이면 0(짧은 제목끼리 우연히 묶이지 않게)."""
    x, y = _tokens(a), _tokens(b)
    both = x & y
    if len(both) < 2:
        return 0.0
    return len(both) / len(x | y)


# ── 질문 지도 칸 이름표(규칙, 0원) ──

_KIND_KO = {kind: ko for _, kind, ko, _ in config.DRINKS_QUESTION_MAP}


def question_cell(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """질문 문장 → (주종 키, 질문 유형 키). 낱말로만 정한다. 못 정하면 None. 주종은 먼저 나온 술 낱말, 유형은 DRINKS_CELL_KIND_KEYWORDS 앞 순서가 이긴다."""
    t = (text or "").lower()
    for w in config.DRINKS_RELEVANCE_FALSE_FRIENDS:
        t = t.replace(w, " ")
    category, best = None, None
    for cat, terms in config.DRINKS_CELL_CATEGORY_TERMS.items():
        at = [t.find(x.lower()) for x in terms if x.lower() in t]
        if at and (best is None or min(at) < best):
            category, best = cat, min(at)
    kind = next((k for k, words in config.DRINKS_CELL_KIND_KEYWORDS.items() if any(w in t for w in words)), None)
    return category, kind


def item_cell(it: dict) -> tuple[Optional[str], Optional[str]]:
    """자료의 칸. 후보 자격이 있는 질문 중 칸이 가장 또렷한(주종·유형이 다 잡히는) 것으로 정한다. 질문이 없으면 제목으로."""
    qs = good_questions(it) or [it.get("title") or ""]
    return max((question_cell(q) for q in qs), key=lambda c: (c[0] is not None) + (c[1] is not None))


def group_cell(items: list[dict]) -> tuple[Optional[str], Optional[str]]:
    cells = Counter(item_cell(it) for it in items)
    return cells.most_common(1)[0][0] if cells else (None, None)


def cell_card(cell: tuple[Optional[str], Optional[str]]) -> dict[str, Optional[str]]:
    cat, kind = cell
    return {"category": cat, "category_ko": config.DRINKS_CATEGORY_KO.get(cat or ""), "kind": kind, "kind_ko": _KIND_KO.get(kind or "")}


READER_VALUE = {
    "storage": "개봉 후·보관 방법처럼 집에서 바로 쓰는 답", "selection": "고를 때 무엇을 보면 되는지 기준",
    "misconception": "흔한 오해를 근거로 바로잡기", "debate": "엇갈리는 주장을 근거로 정리",
    "new_product": "새 제품 소식을 사실 위주로 정리", "event": "행사 정보를 한눈에", "question": "사람들이 직접 묻는 질문에 답",
}
FIRST_SCENE = {
    "storage": "냉장고 문을 열자 반쯤 남은 병 — '이거 아직 마셔도 될까?'(실사 연출, 실제 제품 아님 표기)",
    "selection": "진열대 앞에서 두 병을 들고 망설이는 손(연출 장면)",
    "misconception": "'다들 이렇게 알고 있죠?' 자막 + 흔한 말 한 줄, 곧바로 3D 도해로 반전",
    "debate": "화면을 반으로 나눠 두 주장을 나란히",
    "new_product": "제품 이미지 대신 '새로 나온 것' 카드 + 확인된 사실 한 줄(공식 자료 확인 후)",
    "event": "행사 일정 카드(공식 공지 확인 후)",
    "question": "질문을 크게 띄우고 잔 하나에 초점(연출 장면)",
}


def _fit(signals: set[str]) -> tuple[int, int]:
    video = 2 + (1 if signals & {"misconception", "storage", "debate"} else 0) + (1 if "question" in signals else 0)
    card = 2 + (1 if signals & {"selection", "storage", "event"} else 0) + (1 if signals & {"debate", "new_product"} else 0)
    return min(video, 4), min(card, 4)


def _independent(items: list[dict]) -> int:
    """독립 출처 수: 운영자가 정한 원출처 묶음은 하나로, 같은 본문(보도자료 전재)은 처음 본 출처로, 같은 채널은 하나로."""
    by_hash: dict[str, str] = {}
    keys: set[str] = set()
    for it in items:
        h = it.get("summary_hash")
        k = it.get("origin_group") or (by_hash.get(h) if h else None) or f"{it.get('platform')}:{it.get('channel_name')}"
        if h:
            by_hash.setdefault(h, k)
        keys.add(k)
    return len(keys)


def build_card(items: list[dict], topics: list[dict]) -> dict[str, Any]:
    sig = Counter(s for it in items for s in (it.get("signals") or []))
    signals = set(sig)
    # 대표 질문: 질문 꼴 제목을 먼저(글쓴이가 직접 던진 질문), 없으면 본문·댓글에서 뽑은 질문, 그것도 없으면 제목.
    titles = [it.get("title") for it in items if it.get("title") and _is_question(clean_text(it["title"])) and question_ok(it["title"])]
    qs = [q for it in items for q in good_questions(it)]
    key_q = (titles or qs or [items[0].get("title") or items[0].get("canonical_url")])[0]
    dominant = next((s for s in ["storage", "misconception", "selection", "debate", "new_product", "event", "question"] if s in signals), "question")
    fit_v, fit_c = _fit(signals)
    indep = _independent(items)
    per_platform: dict[str, dict[str, Any]] = defaultdict(lambda: {"items": 0})
    for it in items:
        pp = per_platform[it.get("platform")]
        pp["items"] += 1
        for k, v in (it.get("latest_metrics") or {}).items():  # 플랫폼 안에서만 최댓값 — 플랫폼끼리 더하지 않는다
            pp[f"max_{k}"] = max(pp.get(f"max_{k}", 0), v)
    nums = sorted({m for it in items for m in re.findall(r"\d+(?:\.\d+)?\s*(?:%|도|年|년|ml|mL|℃|°C|ppm)", f"{it.get('title')} {it.get('summary')}")})[:5]
    facts = ["공식·전문 원자료로 핵심 사실 확인(발견 자료는 근거가 아님)"] + [f"수치 '{n}' 원출처 확인" for n in nums]
    if signals & {"new_product", "event"}:
        facts.append("제조사·주최 측 공식 공지로 날짜·이름 확인")
    dups = [t["id"] for t in topics if max(similarity(key_q, t.get("title") or ""), similarity(key_q, t.get("question") or "")) >= 0.5]
    score_q = 25 if "question" in signals else 0
    score_i = min(indep, 4) * 10
    score_s = min(len(signals - {"question"}), 3) * 5
    score_f = max(fit_v, fit_c) * 5
    # 수요 가점: 같은 칸에서 서로 다른 글(주소가 다른 자료)이 같은 것을 물을수록 조금 오른다. 상한이 있고 총점은 100 을 넘지 않는다.
    distinct = len({it.get("canonical_url") or it.get("id") or id(it) for it in items})
    score_d = min(config.DRINKS_DEMAND_BONUS_MAX, max(0, distinct - 1) * config.DRINKS_DEMAND_BONUS_PER_ITEM)
    total = min(100, score_q + score_i + score_s + score_f + score_d)
    cell = group_cell(items)
    return {
        "key_question": key_q[:500], "reader_value": READER_VALUE[dominant],
        "discovery_path": " · ".join(sorted({f"{it.get('platform')}:{it.get('channel_name') or '-'}" for it in items}))[:500],
        "signals": sorted(signals), "first_scene": "[규칙 제안] " + FIRST_SCENE[dominant],
        "fit_video": fit_v, "fit_carousel": fit_c, "facts_to_check": facts, "duplicate_topic_ids": dups,
        "interest": {"independent_sources": indep, "items": len(items), "by_platform": dict(per_platform),
                     **({"cell": cell_card(cell)} if any(cell) else {}),
                     "note": "플랫폼별 지표는 합산하지 않는다 · 미제공 지표는 없음으로 둔다"},
        "provisional_score": total, "rubric": config.DRINKS_DISCOVERY_RUBRIC,
        "score_reason": f"질문 신호 {score_q} + 독립 출처 {indep}곳 {score_i} + 신호 종류 {score_s} + 형식 적합 {score_f} + 수요 {score_d} = {total}/100 (임시)",
    }


def cluster(items: list[dict], threshold: float = config.DRINKS_DISCOVERY_SIMILAR_MIN) -> list[list[dict]]:
    """비슷한 자료를 묶는다. **같은 칸 안에서만** 묶는다 — 다른 칸의 비슷한 질문(사케 보관 ↔ 위스키 보관)은 따로 둔다."""
    groups: list[list[dict]] = []
    cells: list[tuple[Optional[str], Optional[str]]] = []
    for it in items:
        text = " ".join([it.get("title") or "", *(it.get("questions") or [])])
        cell = item_cell(it)
        for g, gc in zip(groups, cells):
            if gc != cell:
                continue
            if any(it.get("summary_hash") and it.get("summary_hash") == o.get("summary_hash") for o in g) or \
                    max(similarity(text, " ".join([o.get("title") or "", *(o.get("questions") or [])])) for o in g) >= threshold:
                g.append(it)
                break
        else:
            groups.append([it])
            cells.append(cell)
    return groups


# ── Jev 최종 판정(fail-open) ──
JEV_QUESTION = (
    "Is QUESTION a question about an alcoholic drink (sake, Korean traditional liquor such as makgeolli or soju, or whisky) "
    "whose answer an ordinary Instagram viewer would be curious to learn?",
    {"true": "a genuine question about such a drink that a general viewer would want answered",
     "false": "not about alcoholic drinks (shopping, travel, ads, chatter) or too narrow or personal for a general audience"},
)


def _jev_ask(question: str) -> Optional[float]:
    """'예'일 확률. 못 물었으면 None — 어떤 오류도 수집을 막지 않는다."""
    try:
        return decide.noul(f"QUESTION (Korean): {question}", JEV_QUESTION[0], JEV_QUESTION[1],
                           site="drinks_discovery", subject=question[:40])
    except Exception as exc:  # noqa: BLE001
        log.warning("drinks: Jev 판정 실패(무시): %s", exc)
        return None


class JevJudge:
    """실행당 호출 상한·같은 질문 재사용을 가진 판정기. verdict → ('ok'|'rejected'|'unavailable'|'capped', p)."""

    def __init__(self) -> None:
        self.calls = 0
        self.memo: dict[str, tuple[str, Optional[float]]] = {}

    def verdict(self, question: str) -> tuple[str, Optional[float]]:
        if question in self.memo:
            return self.memo[question]
        try:
            on = decide.enabled()
        except Exception:  # noqa: BLE001
            on = False
        if not on:
            v: tuple[str, Optional[float]] = ("unavailable", None)
        elif self.calls >= config.DRINKS_DISCOVERY_JEV_MAX_PER_RUN:
            v = ("capped", None)   # 비용 상한 — 못 물은 것은 막지 않고 만든다(fail-open)
        else:
            self.calls += 1
            p = _jev_ask(question)
            v = ("unavailable", None) if p is None else (("rejected" if p < config.DRINKS_DISCOVERY_JEV_MIN_P else "ok"), p)
        self.memo[question] = v
        return v


def _cand_cell(c: dict) -> tuple[Optional[str], Optional[str]]:
    return group_cell(c["items"]) if c.get("items") else question_cell(c.get("key_question"))


def read_candidate_interests() -> dict[str, dict]:
    """열린 후보의 interest(jsonb) - 점수를 다시 계산해도 Jev 기록을 잇기 위해 읽는다. 못 읽으면 빈 dict(기록만 잃고 수집은 계속)."""
    try:
        from . import db
        rows = db.select_all("drink_discovery_candidates", "id,interest", key=("id",), where=lambda q: q.eq("status", "suggested"))
        return {r["id"]: r.get("interest") or {} for r in rows}
    except Exception as exc:  # noqa: BLE001
        log.warning("drinks: 후보 interest 조회 실패(Jev 기록은 이번 갱신에서 이어지지 않는다): %s", exc)
        return {}


def _keep_jev(card: dict, old: Optional[dict]) -> None:
    """다시 만든 카드의 interest 에 기존 후보의 Jev 기록(jev·jev_p)을 합친다 - 덮어쓰지 않는다."""
    for k in ("jev", "jev_p"):
        if old and k in old:
            card["interest"][k] = old[k]


def suggest_candidates(rpc, read_interests: Optional[Callable[[], dict[str, dict]]] = None) -> dict[str, int]:
    back = rpc("drinks_discovery_backlog", {}) or {}
    items, cands, topics = back.get("items") or [], back.get("candidates") or [], back.get("topics") or []
    made = added = jev_rejected = jev_unavailable = 0
    # 질문 문장 자체가 후보 자격(길이 상한 + 술 낱말)을 갖춘 자료만 후보가 된다. 나머지는 그대로 발견함에 남는다.
    eligible = [it for it in items if good_questions(it)]
    skipped = len(items) - len(eligible)
    judge = JevJudge()
    old_interest: dict[str, dict] = {}
    if read_interests is not None:
        try:
            old_interest = read_interests() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("drinks: 후보 interest 조회 실패(무시): %s", exc)

    fresh: dict[str, dict] = {}   # 이번 실행에 만든 후보의 Jev 기록(아래 다시 계산 때 잇는다)

    def prior(c: dict) -> Optional[dict]:
        return c.get("interest") or old_interest.get(c["id"]) or fresh.get(c["id"])

    for g in cluster(eligible):
        first = build_card(g, topics)
        cell = group_cell(g)
        target = next((c for c in cands if _cand_cell(c) == cell and similarity(first["key_question"], c["key_question"]) >= 0.5), None)
        # 열린 후보에 더할 때는 그 후보의 **자료 전체**로 카드를 다시 만든다(새 묶음만으로 점수를 덮지 않게 — 검토 지적).
        card = build_card((target.get("items") or []) + g, topics) if target else first
        park: Optional[float] = None
        if target:
            card["key_question"] = target["key_question"]
            _keep_jev(card, prior(target))
        else:
            status, p = judge.verdict(card["key_question"])
            card["interest"]["jev"] = "ok" if status == "rejected" else status   # 기각돼도 판정은 '했다'
            if p is not None:
                card["interest"]["jev_p"] = round(p, 4)
            if status == "rejected":
                jev_rejected += 1
                log.info("drinks: Jev 기각(p=%.2f) %s", p or 0.0, card["key_question"][:60])
                if not config.DRINKS_DISCOVERY_JEV_PARK_REJECTED:
                    continue   # 후보를 만들지 않는다 — 자료는 발견함에 그대로 남는다
                park = p or 0.0
            elif status != "ok":
                jev_unavailable += 1
        r = rpc("drinks_suggest_candidate", {"item_ids": [it["id"] for it in g], **card,
                                             **({"candidate_id": target["id"]} if target else {})}) or {}
        if r.get("candidate_id"):
            if park is not None:   # 기각된 묶음은 열린 후보가 아니라 '기각' 상태로 남겨 자료를 다음 실행의 앞줄에서 치운다
                rpc("drinks_candidate_action", {"candidate_id": r["candidate_id"], "expected_version": 1, "action": "dismiss",
                                                "reason": f"Jev 판정 미달 p={park:.2f} (질문 지도 2026-10-29)"})
            elif target:
                added += 1
                target["items"] = (target.get("items") or []) + g
            else:
                made += 1
                fresh[r["candidate_id"]] = {k: card["interest"][k] for k in ("jev", "jev_p") if k in card["interest"]}
                cands.append({"id": r["candidate_id"], "key_question": card["key_question"], "items": list(g)})
    # 합치기(운영자)로 자료가 옮겨진 후보도 다음 묶기 때 자료 전체로 다시 계산한다.
    refreshed = 0
    for c in (rpc("drinks_discovery_backlog", {}) or {}).get("candidates") or []:
        if c.get("items"):
            card = build_card(c["items"], topics)
            card.pop("key_question", None)   # 대표 질문은 운영자가 고친 것일 수 있다 — 유지
            _keep_jev(card, prior(c))
            rpc("drinks_suggest_candidate", {"item_ids": [], "candidate_id": c["id"], **card})
            refreshed += 1
    return {"new": made, "added": added, "skipped_items": skipped, "refreshed": refreshed,
            "jev_rejected": jev_rejected, "jev_unavailable": jev_unavailable}
