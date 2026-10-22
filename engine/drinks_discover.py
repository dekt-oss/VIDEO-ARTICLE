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
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import config
from .drinks_fetch import JSON_TYPES, FetchError, SafeFetcher
from .drinks_parse import canonicalize, clean_text
from .util import log

# ── 신호(규칙) ── 한국어·일본어·영어. 판정이 아니라 후보 카드의 단서다.
SIGNAL_PATTERNS: dict[str, re.Pattern] = {
    "question": re.compile(r"[?？]|왜|어떻게|무엇|뭐가|뭔가요|궁금|なぜ|どう|ですか|\b(why|how|what|which|is it|should i|can i)\b", re.I),
    "debate": re.compile(r"\bvs\.?\b|대\s|논쟁|호불호|갑론|どっち|派|\b(versus|debate|overrated|controversial)\b", re.I),
    "misconception": re.compile(r"오해|사실은|잘못 알|속설|誤解|本当は|\b(myth|misconception|actually|is it true)\b", re.I),
    "selection": re.compile(r"추천|고르|입문|선택|차이|おすすめ|選び|違い|\b(recommend|choose|which one|difference|beginner|best)\b", re.I),
    "storage": re.compile(r"보관|냉장|개봉|유통기한|상했|숙성|保存|開栓|冷蔵|賞味|\b(store|storage|shelf|expire|freez|fridge|old bottle|opened)\b", re.I),
    "new_product": re.compile(r"신제품|출시|한정판|리뉴얼|新発売|限定|発売|\b(new release|launch|limited edition)\b", re.I),
    "event": re.compile(r"행사|페스티벌|축제|시음회|박람회|イベント|祭|試飲会|\b(festival|tasting event|expo|fair)\b", re.I),
}

_URL = re.compile(r"https?://\S+|www\.\S+")
_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[。？！])|\n+")   # 일본어·중국어 문장부호 뒤에는 띄어쓰기가 없다
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def extract_signals(text: str) -> list[str]:
    return [k for k, p in SIGNAL_PATTERNS.items() if p.search(_URL.sub(" ", text or ""))]


def _is_question(sent: str) -> bool:
    if not sent.endswith(("?", "？")):
        return False
    body = sent.rstrip("?？ ")
    if _CJK.search(body):
        return len(body) >= 6
    return len(re.findall(r"[A-Za-z]{2,}", body)) >= 3   # "(?)" 같은 조각·한두 단어는 질문으로 치지 않는다


def extract_questions(*texts: str, limit: int = 5) -> list[str]:
    """원문의 질문 문장(물음표로 끝나는 완전한 문장)만. 주소는 먼저 지운다. 번역·요약하지 않는다."""
    out: list[str] = []
    for t in texts:
        for sent in _SPLIT.split(_URL.sub(" ", t or "")):
            q = clean_text(sent).lstrip(")]}>-–·,;: ")
            if q and _is_question(q) and q not in out:
                out.append(q[:300])
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


def _epoch_iso(v: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _metric(d: dict, key: str) -> Optional[int]:
    v = d.get(key)
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _metrics(pairs: dict[str, Optional[int]]) -> dict[str, int]:
    return {k: v for k, v in pairs.items() if v is not None}  # 없는 지표는 키 자체를 빼고 0 을 만들지 않는다


def stackexchange(f: SafeFetcher, cfg: dict, since: Optional[datetime], limit: int) -> Batch:
    found: list[Found] = []
    parsed = incomplete = 0
    for tag in cfg.get("queries") or []:
        if len(found) >= limit:
            incomplete += 1
            break
        params = {"site": cfg.get("site") or "alcohol", "tagged": tag, "order": "desc", "sort": "creation",
                  "pagesize": min(50, limit - len(found)), "filter": "withbody"}
        if since:
            params["fromdate"] = int(since.timestamp())
        res = f.get("https://api.stackexchange.com/2.3/questions", accept=JSON_TYPES, params=params)
        data = json.loads(res.body.decode("utf-8"))
        if "error_id" in data:
            raise FetchError("api_error", f"Stack Exchange 오류 {data.get('error_id')}: {data.get('error_name')}")
        items = data.get("items") or []
        parsed += len(items)
        for it in items:
            found.append(Found(
                url=it.get("link") or "", platform="stackexchange", title=html_text(it.get("title") or "") or None,
                summary=html_text(it.get("body") or "")[: config.DRINKS_DISCOVERY_SUMMARY_CHARS] or None,
                channel_name=f"Beer, Wine & Spirits SE · {tag}", external_id=str(it.get("question_id") or ""),
                posted_at=_epoch_iso(it.get("creation_date")),
                metrics=_metrics({"views": _metric(it, "view_count"), "score": _metric(it, "score"),
                                  "answers": _metric(it, "answer_count")})))
        if data.get("has_more"):
            incomplete += 1
        if data.get("backoff"):  # API 가 기다리라고 했다 — 이 실행에서는 더 묻지 않는다
            incomplete += 1
            break
    return Batch(found, parsed, incomplete)


def youtube(f: SafeFetcher, cfg: dict, since: Optional[datetime], limit: int) -> Batch:
    key = config.SECRETS.youtube_data_api_key
    if not key:
        raise FetchError("api_key_missing", "YOUTUBE_DATA_API_KEY 가 없습니다 — 유튜브 발견은 키를 넣기 전까지 멈춰 있습니다")
    hdr = {"X-Goog-Api-Key": key}
    found: list[Found] = []
    parsed = incomplete = 0
    queries = (cfg.get("queries") or [])[: config.DRINKS_YT_SEARCH_MAX_QUERIES]
    incomplete += max(0, len(cfg.get("queries") or []) - len(queries))
    for q in queries:
        params = {"part": "snippet", "q": q, "type": "video", "order": "date", "maxResults": min(25, max(1, limit - len(found)))}
        if since:
            params["publishedAfter"] = since.isoformat().replace("+00:00", "Z")
        s = json.loads(f.get("https://www.googleapis.com/youtube/v3/search", accept=JSON_TYPES, params=params, headers=hdr).body)
        vids = [x for x in s.get("items") or [] if (x.get("id") or {}).get("videoId")]
        parsed += len(vids)
        if s.get("nextPageToken"):
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
    return Batch(found, parsed, incomplete)


def naver(f: SafeFetcher, cfg: dict, since: Optional[datetime], limit: int) -> Batch:
    cid, sec = config.SECRETS.naver_client_id, config.SECRETS.naver_client_secret
    if not (cid and sec):
        raise FetchError("api_key_missing", "NAVER_CLIENT_ID/SECRET 이 없습니다 — 네이버 발견은 키를 넣기 전까지 멈춰 있습니다")
    hdr = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec}
    found: list[Found] = []
    parsed = incomplete = 0
    for kind, platform, base in [("cafearticle", "naver_cafe", "https://openapi.naver.com/v1/search/cafearticle.json"),
                                 ("blog", "naver_blog", "https://openapi.naver.com/v1/search/blog.json")]:
        if kind not in (cfg.get("kinds") or ["cafearticle", "blog"]):
            continue
        for q in cfg.get("queries") or []:
            if len(found) >= limit:
                incomplete += 1
                break
            d = json.loads(f.get(base, accept=JSON_TYPES, headers=hdr,
                                 params={"query": q, "display": min(30, limit - len(found)), "sort": "date"}).body)
            items = d.get("items") or []
            parsed += len(items)  # 검색 결과는 최신순 상위만 본다 — 전체 건수(total)를 미수집으로 세지 않는다
            for it in items:
                posted = None
                pd = it.get("postdate")
                if pd and re.fullmatch(r"\d{8}", pd):
                    posted = f"{pd[:4]}-{pd[4:6]}-{pd[6:]}T00:00:00+09:00"
                found.append(Found(
                    url=it.get("link") or "", platform=platform, title=html_text(it.get("title") or "") or None,
                    summary=html_text(it.get("description") or "") or None,
                    channel_name=it.get("cafename") or it.get("bloggername"), posted_at=posted,
                    coverage="title_summary"))  # 회원 전용 카페 본문은 받지 않는다 — 검색 결과 요약만
    if since:
        found = [x for x in found if not x.posted_at or datetime.fromisoformat(x.posted_at) >= since]
    return Batch(found, parsed, incomplete)


CONNECTORS: dict[str, Callable[[SafeFetcher, dict, Optional[datetime], int], Batch]] = {
    "stackexchange": stackexchange, "youtube": youtube, "naver": naver,
}


# ── 실행 처리(발견용 수집원) ──

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
            for fd in batch.found[:limit]:
                try:
                    self.rpc("drinks_collect_discovery", self._lease({"item": fd.item()}))
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
    titles = [it.get("title") for it in items if it.get("title") and _is_question(clean_text(it["title"]))]
    qs = [q for it in items for q in (it.get("questions") or [])]
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
    total = score_q + score_i + score_s + score_f
    return {
        "key_question": key_q[:500], "reader_value": READER_VALUE[dominant],
        "discovery_path": " · ".join(sorted({f"{it.get('platform')}:{it.get('channel_name') or '-'}" for it in items}))[:500],
        "signals": sorted(signals), "first_scene": "[규칙 제안] " + FIRST_SCENE[dominant],
        "fit_video": fit_v, "fit_carousel": fit_c, "facts_to_check": facts, "duplicate_topic_ids": dups,
        "interest": {"independent_sources": indep, "items": len(items), "by_platform": dict(per_platform),
                     "note": "플랫폼별 지표는 합산하지 않는다 · 미제공 지표는 없음으로 둔다"},
        "provisional_score": total, "rubric": config.DRINKS_DISCOVERY_RUBRIC,
        "score_reason": f"질문 신호 {score_q} + 독립 출처 {indep}곳 {score_i} + 신호 종류 {score_s} + 형식 적합 {score_f} = {total}/100 (임시)",
    }


def cluster(items: list[dict], threshold: float = config.DRINKS_DISCOVERY_SIMILAR_MIN) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for it in items:
        text = " ".join([it.get("title") or "", *(it.get("questions") or [])])
        for g in groups:
            if any(it.get("summary_hash") and it.get("summary_hash") == o.get("summary_hash") for o in g) or \
                    max(similarity(text, " ".join([o.get("title") or "", *(o.get("questions") or [])])) for o in g) >= threshold:
                g.append(it)
                break
        else:
            groups.append([it])
    return groups


def suggest_candidates(rpc) -> dict[str, int]:
    back = rpc("drinks_discovery_backlog", {}) or {}
    items, cands, topics = back.get("items") or [], back.get("candidates") or [], back.get("topics") or []
    made = added = skipped = 0
    for g in cluster(items):
        if not any((it.get("signals") or []) or (it.get("questions") or []) for it in g):
            skipped += len(g)  # 질문·신호가 하나도 없는 자료는 후보로 만들지 않는다(그대로 발견함에 남는다)
            continue
        card = build_card(g, topics)
        target = next((c for c in cands if similarity(card["key_question"], c["key_question"]) >= 0.5), None)
        r = rpc("drinks_suggest_candidate", {"item_ids": [it["id"] for it in g], **card,
                                             **({"candidate_id": target["id"]} if target else {})}) or {}
        if r.get("candidate_id"):
            if target:
                added += 1
            else:
                made += 1
                cands.append({"id": r["candidate_id"], "key_question": card["key_question"]})
    return {"new": made, "added": added, "skipped_items": skipped}
