"""주류 공장 B단계 — 받은 페이지·피드를 글자로 바꾸는 파서(parser_version drinks-html-v1). 2026-10-22.

★ 입력은 신뢰하지 않는 데이터다. 표준 라이브러리 html.parser 로 **글자만** 꺼낸다 — 스크립트를 실행하거나
  외부 자원을 불러오지 않는다. 피드는 feedparser 에 **이미 받은 바이트**만 넘긴다(feedparser 가 네트워크를 쓰지 않게).
★ 번역·OCR·요약으로 본문을 대신하지 않는다. 본문이 짧거나 없으면 "제목·요약만(metadata_only)"으로 남긴다.
"""

from __future__ import annotations

import html as html_mod
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

from . import config

PARSER_VERSION = "drinks-html-v1"

# web/lib/drinks/actions.ts::TRACKING_PARAM 과 같은 목록이어야 한다(tests/test_drinks_phase_b.py 가 대조).
TRACKING_PARAM = re.compile(
    r"^(utm_[a-z_]+|fbclid|gclid|dclid|msclkid|igshid|igsh|mc_cid|mc_eid|_hsenc|_hsmi|yclid|si)$", re.I)

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "object", "form", "button", "select"}
_CHROME_TAGS = {"nav", "header", "footer", "aside"}
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "table", "tr", "h1", "h2", "h3", "h4",
               "h5", "h6", "dl", "dt", "dd", "blockquote", "pre", "br", "hr", "td", "th", "caption", "figcaption"}
_VOID_TAGS = {"br", "hr", "img", "meta", "link", "input", "area", "base", "col", "embed", "source", "track", "wbr"}
_CTRL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏‪-‮⁦-⁩]")


def canonicalize(url: str) -> str:
    """수집 URL 정규화 — 추적 파라미터·조각만 지우고 의미 있는 파라미터와 순서는 남긴다(§5.4-1)."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port in (None, 443 if parts.scheme == "https" else 80) else f"{host}:{port}"
    # 남기는 파라미터는 원래 글자 그대로 둔다(다시 인코딩하면 수동 등록 URL 과 달라져 중복 판별이 깨진다).
    query = [q for q in parts.query.split("&") if q and not TRACKING_PARAM.match(unquote_plus(q.split("=", 1)[0]))]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, "&".join(query), ""))


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n")
    s = _CTRL.sub("", s)
    s = re.sub(r"[ \t 　]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def decode(body: bytes, header_charset: Optional[str]) -> str:
    """응답 바이트 → 글자. 헤더 charset → 문서 안 meta charset → UTF-8 순. 국세청 페이지는 Shift_JIS 다."""
    tried: list[str] = []
    for cand in (header_charset, _meta_charset(body)):
        if cand and cand not in tried:
            tried.append(cand)
            try:
                return body.decode(_codec(cand))
            except (LookupError, UnicodeDecodeError):
                continue
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("utf-8", "replace")


def _codec(name: str) -> str:
    n = name.lower().replace("_", "-")
    return {"shift-jis": "cp932", "sjis": "cp932", "x-sjis": "cp932", "euc-kr": "cp949", "ks-c-5601-1987": "cp949"}.get(n, n)


def _meta_charset(body: bytes) -> Optional[str]:
    head = body[:4096]
    m = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9_\-]+)", head, re.I)
    if m:
        return m.group(1).decode("ascii", "ignore").lower()
    m = re.search(rb"<\?xml[^>]+encoding\s*=\s*[\"']([A-Za-z0-9_\-]+)", head, re.I)
    return m.group(1).decode("ascii", "ignore").lower() if m else None


@dataclass
class Page:
    title: Optional[str]
    text: str
    published_at: Optional[date]
    links: list[tuple[str, str]] = field(default_factory=list)   # (절대 URL, 링크 글자)


class _Extractor(HTMLParser):
    def __init__(self, content_ids: Iterable[str]):
        super().__init__(convert_charrefs=True)
        self.content_ids = set(content_ids)
        self.stack: list[tuple[str, bool]] = []       # (tag, 이 태그가 본문 루트인가)
        self.skip = 0
        self.chrome = 0
        self.in_root = 0
        self.root_seen = False
        self.all_parts: list[str] = []
        self.root_parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.h1_parts: list[str] = []
        self.in_h1 = 0
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, list[str]]] = []
        self._link: Optional[tuple[str, list[str]]] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
            return
        if tag in _VOID_TAGS:
            if tag in ("br", "hr"):
                self._emit("\n")
            return
        is_root = bool(self.content_ids) and (a.get("id") in self.content_ids
                                               or any(c in self.content_ids for c in a.get("class", "").split()))
        self.stack.append((tag, is_root))
        if is_root:
            self.in_root += 1
            self.root_seen = True
        if tag in _SKIP_TAGS:
            self.skip += 1
        elif tag in _CHROME_TAGS:
            self.chrome += 1
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.in_h1 += 1
        if tag == "a" and a.get("href") and not self.skip:
            self._link = (a["href"], [])
        if tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        # 닫는 태그가 어긋난 HTML 도 버티도록, 같은 태그를 만날 때까지 스택을 걷는다.
        while self.stack:
            t, is_root = self.stack.pop()
            if t in _SKIP_TAGS:
                self.skip -= 1
            elif t in _CHROME_TAGS:
                self.chrome -= 1
            if is_root:
                self.in_root -= 1
            if t == "title":
                self.in_title = False
            if t == "h1":
                self.in_h1 -= 1
            if t == "a" and self._link is not None:
                self.links.append(self._link)
                self._link = None
            if t in _BLOCK_TAGS:
                self._emit("\n")
            if t == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.skip:
            return
        if self._link is not None:
            self._link[1].append(data)
        if self.in_h1:
            self.h1_parts.append(data)
        if not self.chrome:
            self._emit(data)

    def _emit(self, s: str) -> None:
        if self.skip or self.chrome:
            return
        self.all_parts.append(s)
        if self.in_root:
            self.root_parts.append(s)


def parse_page(text_html: str, base_url: str, parser_config: Optional[dict[str, Any]] = None) -> Page:
    cfg = parser_config or {}
    ex = _Extractor(cfg.get("content_ids") or [])
    try:
        ex.feed(text_html)
        ex.close()
    except Exception:  # noqa: BLE001 — 깨진 HTML 이어도 꺼낸 데까지 쓴다
        pass
    body = clean_text("".join(ex.root_parts if ex.root_seen else ex.all_parts))
    for pat in cfg.get("strip_patterns") or []:
        body = clean_text(re.sub(pat, "", body))
    body = body[: config.DRINKS_MAX_BODY_CHARS]
    title = clean_text(ex.meta.get("og:title") or "".join(ex.h1_parts) or "".join(ex.title_parts)) or None
    if title:
        title = title[:500]
    published = _parse_date(ex.meta.get("article:published_time") or ex.meta.get("date") or ex.meta.get("dc.date"))
    links = [(urljoin(base_url, html_mod.unescape(h)), clean_text("".join(t))) for h, t in ex.links]
    return Page(title=title, text=body, published_at=published, links=links)


def article_links(page: Page, allowed_hosts: Iterable[str], prefix: str, exclude: Iterable[str] = ()) -> list[tuple[str, str]]:
    """목록 페이지에서 같은 경로 아래 글 링크만 고른다(순서 유지, 중복 제거). prefix 자체(목록)는 뺀다."""
    allowed = {h.lower() for h in allowed_hosts}
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    pats = [re.compile(x) for x in exclude]
    for url, text in page.links:
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "").lower() not in allowed:
            continue
        path = parts.path or "/"
        if not path.startswith(prefix) or path.rstrip("/") == prefix.rstrip("/"):
            continue
        if any(p.search(path) for p in pats):
            continue
        c = canonicalize(url)
        if c in seen:
            continue
        seen.add(c)
        out.append((c, text))
    return out


@dataclass
class FeedEntry:
    url: str
    title: Optional[str]
    summary: Optional[str]
    published_at: Optional[date]


def parse_feed(body: bytes) -> list[FeedEntry]:
    import feedparser  # 피드 수집원에서만 필요하다

    parsed = feedparser.parse(body)  # 바이트를 넘긴다 — URL 을 넘기면 feedparser 가 직접 요청한다
    out: list[FeedEntry] = []
    for e in parsed.entries:
        link = e.get("link")
        if not link:
            continue
        pub = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                pub = date(*e[k][:3])
                break
        summary = clean_text(re.sub(r"<[^>]+>", " ", html_mod.unescape(e.get("summary") or ""))) or None
        out.append(FeedEntry(url=link, title=clean_text(e.get("title") or "") or None,
                             summary=summary[:2000] if summary else None, published_at=pub))
    return out


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).date()
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
