"""논문 원문 확보 (작업명세서_설명엔진_v2 §3 Phase 1).

무엇을 푸는가: 논문 라인은 지금까지 **초록만** 보고 Fact Sheet 를 뽑고 대본을 썼다. 초록은
"무엇을 발견했다"만 담고 "왜·어떻게"는 본문에 있다. 원리를 설명하는 영상을 만들려면 본문이
필요하다. 리포트 라인은 이미 같은 전환을 했다(engine/report_source.py).

리포트와 다른 점 — 그래서 상수도 모듈도 분리한다(D1):
- 리포트 원문은 ARIA 한 곳에서 온다. 논문은 **확보처가 4곳**이고 아예 못 구하는 논문이 많다.
- 그래서 이 모듈의 절반은 "어디서 구했고 왜 실패했나"를 기록하는 일이다. provider·license·
  content_format·parse_error 가 전부 산출물에 남는다. 실패를 숨기면 Phase 0 실측이 거짓이 된다.

같은 자세(리포트에서 그대로 가져온 것):
- `source_depth` 는 **코드가 글자 수로 판정**한다. 모델·API 자기보고를 믿지 않는다.
- **페이지 번호를 만들지 않는다.** PDF 를 파싱할 때조차 chunk 는 문자 길이로 나눈다 —
  없는 페이지 번호가 화면에 나가는 것이 §21 K1 사고다.

순수 함수(네트워크 없음): parse_arxiv_id · normalize_doi · classify_depth · html_to_text ·
jats_to_text · pdf_to_text · drop_references · chunk_text · doc_hash · build_packet ·
fulltext_block. I/O 는 fetch_* 와 acquire 뿐이다.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import re
from typing import Any

import httpx

from . import config, db
from .util import RateLimiter, log

# arXiv 는 요청 간 3초 규약(CLAUDE.md 레이트리밋). export API 와 같은 호스트 정책을 따른다.
_arxiv_limiter = RateLimiter(config.ARXIV_REQUEST_INTERVAL_SEC)


# ─────────────────────────────────────────────────────────────
# 식별자 (순수)
# ─────────────────────────────────────────────────────────────
_ARXIV_IN_DOI = re.compile(r"10\.48550/arxiv\.(?P<id>[\w.\-/]+)", re.I)
_ARXIV_IN_URL = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(?P<id>[\w.\-/]+)", re.I)


def parse_arxiv_id(external_id: str | None, url: str | None = None) -> str | None:
    """`papers.external_id`/url → arXiv id(버전 접미사 제거). 아니면 None.

    'arxiv:2606.03136' → '2606.03136' / '10.48550/arXiv.2401.00001' → '2401.00001'
    'http://arxiv.org/abs/2606.03136v1' → '2606.03136'
    """
    for cand in (external_id or "", url or ""):
        tok = cand.strip()
        if not tok:
            continue
        if tok.lower().startswith("arxiv:"):
            return _strip_version(tok.split(":", 1)[1])
        m = _ARXIV_IN_DOI.search(tok) or _ARXIV_IN_URL.search(tok)
        if m:
            return _strip_version(m.group("id"))
    return None


def _strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id.strip().strip("/"))


def normalize_doi(external_id: str | None, url: str | None = None) -> str | None:
    """DOI 정규화(소문자, 접두 URL 제거). arXiv 전용 id 면 None."""
    for cand in (external_id or "", url or ""):
        tok = cand.strip().lower()
        if not tok:
            continue
        tok = re.sub(r"^https?://(dx\.)?doi\.org/", "", tok)
        if tok.startswith("doi:"):
            tok = tok[4:]
        if tok.startswith("10."):
            return tok.rstrip("/")
    return None


# ─────────────────────────────────────────────────────────────
# 본문 파싱 (순수)
# ─────────────────────────────────────────────────────────────
_DROP_TAGS = re.compile(
    r"<(script|style|noscript|svg|nav|footer|header)\b[^>]*>.*?</\1>", re.I | re.S)
# LaTeXML(arXiv HTML)은 수식을 <math alttext="..."> 로 낸다. alttext 를 살리면 수식이
# "무엇에 관한 식인지"가 남는다 — 통째로 버리면 메커니즘 설명의 핵심이 사라진다.
_MATH = re.compile(r"<math\b[^>]*?alttext=\"(?P<alt>[^\"]*)\"[^>]*>.*?</math>", re.I | re.S)
_MATH_BARE = re.compile(r"<math\b[^>]*>.*?</math>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")
_BLOCK_END = re.compile(
    r"</(p|div|section|h1|h2|h3|h4|h5|h6|li|tr|table|figure|figcaption|blockquote)>", re.I)

# 참고문헌 시작 지점. 본문 끝에서만 찾는다(앞부분의 "References" 언급에 걸리지 않도록).
_REFS_HEAD = re.compile(
    r"\n\s*(references|bibliography|works cited|literature cited|참고문헌)\s*\n", re.I)


def html_to_text(raw: str) -> str:
    """HTML → 본문 텍스트. 태그·스크립트를 걷어내고 문단 경계만 남긴다."""
    s = raw or ""
    s = _DROP_TAGS.sub(" ", s)
    s = _MATH.sub(lambda m: f" {html_mod.unescape(m.group('alt'))} ", s)
    s = _MATH_BARE.sub(" ", s)
    s = _BLOCK_END.sub("\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAG.sub(" ", s)
    s = html_mod.unescape(s)
    return _tidy(s)


# JATS(PMC fullTextXML)에서 본문에 해당하는 구간만. front(메타)·back(참고문헌)은 버린다.
_JATS_BODY = re.compile(r"<body\b[^>]*>(?P<body>.*?)</body>", re.I | re.S)
_JATS_ABSTRACT = re.compile(r"<abstract\b[^>]*>(?P<abs>.*?)</abstract>", re.I | re.S)


def jats_to_text(raw: str) -> str:
    """PMC JATS XML → 본문 텍스트. <body> 가 없으면 <abstract> 라도 건진다."""
    s = raw or ""
    m = _JATS_BODY.search(s)
    if m:
        return html_to_text(m.group("body"))
    m = _JATS_ABSTRACT.search(s)
    if m:
        return html_to_text(m.group("abs"))
    return ""


def pdf_to_text(data: bytes) -> str:
    """PDF 바이트 → 텍스트. pypdf 미설치·파싱 실패는 빈 문자열(호출부가 parse_error 로 기록).

    ★ 페이지 번호를 반환하지 않는다. 페이지를 알 수 있는 유일한 경로가 여기지만, 추출 텍스트의
      페이지 경계는 실제 인쇄 페이지 번호와 다르다(표지·부록 오프셋). 어긋난 번호를 화면에
      내보내느니 아예 갖지 않는다 — report_source.py 와 같은 결정.
    """
    try:
        import io

        from pypdf import PdfReader  # 지연 임포트: 미설치 환경에서도 순수 로직 임포트 가능
    except Exception:  # noqa: BLE001
        log.warning("pypdf 미설치 — PDF 원문은 건너뛴다(pip install pypdf)")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        return _tidy("\n".join((page.extract_text() or "") for page in reader.pages))
    except Exception as exc:  # noqa: BLE001 — 파싱 실패가 파이프라인을 멈추지 않는다
        log.warning("PDF 파싱 실패: %s", exc)
        return ""


def drop_references(text: str) -> str:
    """참고문헌 이후를 버린다. 인용 대조 대상이 아니고 상한만 잡아먹는다.

    본문의 60% 지점 이후에 나오는 헤딩만 참고문헌으로 본다 — 서론에서 "References" 라는
    단어가 나왔다고 논문을 앞에서 잘라 버리면 본문이 통째로 날아간다.
    """
    if not config.PAPER_SOURCE_DROP_REFERENCES:
        return text
    body = text or ""
    floor = int(len(body) * 0.6)
    last = None
    for m in _REFS_HEAD.finditer(body):
        if m.start() >= floor:
            last = m
            break
    return body[:last.start()].rstrip() if last else body


def _tidy(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS.sub(" ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    return _BLANKS.sub("\n\n", s).strip()


# ─────────────────────────────────────────────────────────────
# depth / chunk / hash (순수)
# ─────────────────────────────────────────────────────────────
def classify_depth(text: str) -> str:
    """확보한 본문 길이 → source_depth. ★ 코드 판정 — 확보처 자기보고 불신.

    full_body 는 "본문을 손에 들고 있다"는 뜻이지 "완전무결하게 파싱했다"는 뜻이 아니다.
    """
    n = len(text or "")
    if n == 0:
        return "abstract_only"
    if n >= config.PAPER_SOURCE_FULLBODY_MIN_CHARS:
        return "full_body"
    if n >= config.PAPER_SOURCE_MIN_BODY_CHARS:
        return "partial_body"
    return "abstract_only"


def chunk_text(text: str, size: int | None = None) -> list[dict[str, Any]]:
    """본문을 문자 길이로 나눈다. chunk_id 가 인용 검증(Phase 2)의 주소가 된다."""
    size = size or config.PAPER_SOURCE_CHUNK_CHARS
    body = (text or "").strip()
    if not body:
        return []
    out: list[dict[str, Any]] = []
    for i in range(0, len(body), size):
        out.append({
            "chunk_id": f"P{len(out) + 1:03d}",
            "char_start": i,
            "char_end": min(i + size, len(body)),
            "text": body[i:i + size],
        })
    return out


def doc_hash(text: str) -> str:
    """원문 지문. 멱등 보관 키이자 인용 대조 앵커."""
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_packet(paper: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    """확보 결과 → source packet. truncated·parse_error 를 숨기지 않는다."""
    text = drop_references((found.get("text") or "").strip())
    cap = config.PAPER_SOURCE_MAX_CHARS
    truncated = len(text) > cap
    if truncated:
        text = text[:cap]
    return {
        "paper_id": paper.get("id"),
        "external_id": str(paper.get("external_id") or ""),
        "provider": str(found.get("provider") or "none"),
        "source_url": str(found.get("source_url") or paper.get("url") or ""),
        "version": str(found.get("version") or ""),
        "license": str(found.get("license") or ""),
        "content_format": str(found.get("content_format") or "none"),
        "source_depth": classify_depth(text),
        "doc_hash": doc_hash(text) if text else "",
        "char_count": len(text),
        "truncated": truncated,
        "parse_error": str(found.get("parse_error") or ""),
        "text": text,
        "chunks": chunk_text(text),
    }


def fulltext_block(packet: dict[str, Any]) -> str:
    """프롬프트에 박을 본문 구간. 본문이 없으면 **빈 문자열**이다.

    마커만 남기고 속을 비우면 "원문을 줬다"고 착각하게 된다(report_source 와 같은 이유).
    """
    text = (packet or {}).get("text") or ""
    if not text:
        return ""
    head = f"{config.PAPER_SOURCE_MARKER}\n"
    if packet.get("truncated"):
        head += f"(원문이 {config.PAPER_SOURCE_MAX_CHARS}자 상한에서 잘렸다 — 뒷부분 없음)\n"
    return f"{head}{text}\n{config.PAPER_SOURCE_END_MARKER}"


# ─────────────────────────────────────────────────────────────
# 확보 (I/O)
# ─────────────────────────────────────────────────────────────
def _ua() -> dict[str, str]:
    contact = config.SECRETS.arxiv_contact or config.SECRETS.openalex_mailto or "unknown"
    return {"User-Agent": f"video-article/0.1 (mailto:{contact})"}


def _get(url: str, *, params: dict[str, Any] | None = None,
         accept: str | None = None) -> httpx.Response | None:
    """단발 GET. 4xx/5xx 는 예외 대신 None — 확보 체인은 실패를 다음 확보처로 넘긴다."""
    headers = _ua()
    if accept:
        headers["Accept"] = accept
    try:
        with httpx.Client(timeout=config.PAPER_SOURCE_TIMEOUT_SEC,
                          follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=headers)
    except Exception as exc:  # noqa: BLE001
        log.info("확보 실패(요청) %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        log.info("확보 실패(%s) %s", resp.status_code, url)
        return None
    if len(resp.content) > config.PAPER_SOURCE_MAX_BYTES:
        log.info("확보 실패(용량 %d bytes) %s", len(resp.content), url)
        return None
    return resp


def fetch_arxiv(arxiv_id: str) -> dict[str, Any] | None:
    """arXiv: 네이티브 HTML → ar5iv HTML → PDF 순.

    HTML 을 먼저 보는 이유는 PDF 파싱이 단 조각·수식에서 문장을 뭉개기 때문이다.
    arXiv 네이티브 HTML 은 2023-12 이후 LaTeX 투고분만 있어, 없으면 404 로 떨어진다.
    """
    for base, fmt in ((config.ARXIV_HTML_BASE, "html"), (config.AR5IV_HTML_BASE, "html")):
        _arxiv_limiter.wait()
        resp = _get(f"{base}/{arxiv_id}", accept="text/html")
        if resp is None:
            continue
        text = html_to_text(resp.text)
        # ar5iv 는 변환본이 없으면 abs 페이지로 리다이렉트한다 — 짧으면 본문이 아니다.
        if len(text) >= config.PAPER_SOURCE_MIN_BODY_CHARS:
            return {"provider": f"arxiv_{fmt}", "content_format": fmt, "text": text,
                    "source_url": str(resp.url), "version": "submittedVersion",
                    "license": "arxiv"}
    _arxiv_limiter.wait()
    resp = _get(f"{config.ARXIV_PDF_BASE}/{arxiv_id}", accept="application/pdf")
    if resp is None:
        return None
    text = pdf_to_text(resp.content)
    if not text:
        return {"provider": "arxiv_pdf", "content_format": "pdf", "text": "",
                "source_url": str(resp.url), "parse_error": "pdf_parse_failed"}
    return {"provider": "arxiv_pdf", "content_format": "pdf", "text": text,
            "source_url": str(resp.url), "version": "submittedVersion", "license": "arxiv"}


def openalex_record(doi: str) -> dict[str, Any] | None:
    """OpenAlex work 조회(polite pool). OA 위치·PMCID 를 한 번에 얻는 지점."""
    mailto = config.SECRETS.openalex_mailto
    resp = _get(f"{config.OPENALEX_BASE}/doi:{doi}",
                params={"mailto": mailto} if mailto else None,
                accept="application/json")
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _from_location(loc: dict[str, Any] | None) -> dict[str, Any] | None:
    """OA location(OpenAlex/Unpaywall 공통 모양) → 본문. pdf 우선, 없으면 landing HTML."""
    if not loc:
        return None
    lic = str(loc.get("license") or "")
    version = str(loc.get("version") or "")
    pdf_url = loc.get("pdf_url") or loc.get("url_for_pdf")
    if pdf_url:
        resp = _get(str(pdf_url), accept="application/pdf")
        if resp is not None:
            text = pdf_to_text(resp.content)
            if text:
                return {"content_format": "pdf", "text": text, "source_url": str(resp.url),
                        "license": lic, "version": version}
            return {"content_format": "pdf", "text": "", "source_url": str(resp.url),
                    "license": lic, "version": version, "parse_error": "pdf_parse_failed"}
    landing = loc.get("landing_page_url") or loc.get("url_for_landing_page") or loc.get("url")
    if landing:
        resp = _get(str(landing), accept="text/html")
        if resp is not None and "html" in resp.headers.get("content-type", ""):
            text = html_to_text(resp.text)
            if len(text) >= config.PAPER_SOURCE_MIN_BODY_CHARS:
                return {"content_format": "html", "text": text, "source_url": str(resp.url),
                        "license": lic, "version": version}
    return None


def _locations(record: dict[str, Any]) -> list[dict[str, Any]]:
    """OpenAlex 의 모든 OA 위치를 우선순위대로, URL 중복 없이.

    best/primary 만 보면 **기관 리포지터리 사본을 통째로 놓친다** — 출판사 landing 은 대개
    403(Cloudflare)이고, 실제로 열리는 것은 locations[] 뒤쪽의 리포지터리 PDF 인 경우가 많다.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for loc in ([record.get("best_oa_location"), record.get("primary_location")]
                + list(record.get("locations") or [])):
        if not isinstance(loc, dict):
            continue
        key = str(loc.get("pdf_url") or loc.get("landing_page_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(loc)
    return out


def fetch_openalex_oa(record: dict[str, Any]) -> dict[str, Any] | None:
    """OpenAlex OA 위치 → 본문. 출판사 landing 은 대개 페이월이라 pdf 가 주력이다."""
    for loc in _locations(record)[:config.PAPER_SOURCE_MAX_LOCATIONS]:
        got = _from_location(loc)
        if got and got.get("text"):
            return {"provider": "openalex_oa", **got}
    return None


def arxiv_id_from_record(record: dict[str, Any] | None) -> str | None:
    """OpenAlex 위치들 중 arXiv 사본. DOI 논문이라도 arXiv 판이 있으면 그쪽이 훨씬 깨끗하다."""
    for loc in _locations(record or {}):
        for url in (loc.get("pdf_url"), loc.get("landing_page_url")):
            got = parse_arxiv_id(None, str(url or ""))
            if got:
                return got
    return None


def fetch_pmc(pmcid: str) -> dict[str, Any] | None:
    """Europe PMC fullTextXML(JATS). OA 논문에서 가장 깨끗한 본문 경로다."""
    pmcid = pmcid.strip().upper()
    if not pmcid.startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    resp = _get(f"{config.EUROPEPMC_REST_BASE}/{pmcid}/fullTextXML", accept="application/xml")
    if resp is None:
        return None
    text = jats_to_text(resp.text)
    if not text:
        return {"provider": "pmc_xml", "content_format": "xml", "text": "",
                "source_url": str(resp.url), "parse_error": "jats_body_missing"}
    return {"provider": "pmc_xml", "content_format": "xml", "text": text,
            "source_url": str(resp.url), "version": "publishedVersion", "license": "pmc_oa"}


def find_pmcid(doi: str, record: dict[str, Any] | None = None) -> str | None:
    """PMCID 찾기: OpenAlex ids → Europe PMC 검색 순."""
    ids = ((record or {}).get("ids") or {})
    pmcid = ids.get("pmcid")
    if pmcid:
        return str(pmcid).rsplit("/", 1)[-1]
    resp = _get(f"{config.EUROPEPMC_REST_BASE}/search",
                params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 1},
                accept="application/json")
    if resp is None:
        return None
    try:
        hits = (resp.json().get("resultList") or {}).get("result") or []
    except Exception:  # noqa: BLE001
        return None
    for h in hits:
        # isOpenAccess 로 거르지 않는다 — lite 응답에 그 필드가 없을 때가 있고, 열람 가능
        # 여부는 fullTextXML 이 404 로 답해준다. 여기서 미리 걸면 열리는 논문을 버린다.
        if h.get("pmcid"):
            return str(h["pmcid"])
    return None


def fetch_unpaywall(doi: str) -> dict[str, Any] | None:
    """Unpaywall best_oa_location. OpenAlex 가 놓친 저자 셀프아카이브를 줍는 마지막 그물."""
    email = config.SECRETS.openalex_mailto
    if not email:
        log.info("Unpaywall 건너뜀 — OPENALEX_MAILTO 없음(이메일이 필수 파라미터)")
        return None
    resp = _get(f"{config.UNPAYWALL_BASE}/{doi}", params={"email": email},
                accept="application/json")
    if resp is None:
        return None
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    got = _from_location(data.get("best_oa_location"))
    if got and got.get("text"):
        return {"provider": "unpaywall", **got}
    for loc in (data.get("oa_locations") or [])[:3]:
        got = _from_location(loc)
        if got and got.get("text"):
            return {"provider": "unpaywall", **got}
    return None


def acquire(paper: dict[str, Any], *, chain: tuple[str, ...] | None = None) -> dict[str, Any]:
    """논문 1편 → source packet. 확보 실패도 packet 으로 돌려준다(depth=abstract_only).

    체인 순서는 config.PAPER_SOURCE_CHAIN. 앞에서 본문이 잡히면 뒤는 부르지 않는다.
    """
    external_id = str(paper.get("external_id") or "")
    url = str(paper.get("url") or "")
    arxiv_id = parse_arxiv_id(external_id, url)
    doi = normalize_doi(external_id, url)
    record: dict[str, Any] | None = None
    errors: list[str] = []

    def _try(name: str) -> dict[str, Any] | None:
        nonlocal record
        if name == "arxiv":
            return fetch_arxiv(arxiv_id) if arxiv_id else None
        if not doi:
            return None
        if name == "openalex":
            record = openalex_record(doi)
            if not record:
                return None
            # arXiv 사본이 있으면 그쪽을 먼저 — HTML 본문이 PDF 파싱보다 깨끗하다.
            alt = arxiv_id_from_record(record)
            if alt:
                got = fetch_arxiv(alt)
                if got and got.get("text"):
                    return got
            return fetch_openalex_oa(record)
        if name == "pmc":
            pmcid = find_pmcid(doi, record)
            return fetch_pmc(pmcid) if pmcid else None
        if name == "unpaywall":
            return fetch_unpaywall(doi)
        return None

    for name in (chain or config.PAPER_SOURCE_CHAIN):
        try:
            got = _try(name)
        except Exception as exc:  # noqa: BLE001 — 한 확보처의 사고가 체인을 끊지 않는다
            log.warning("확보처 %s 예외 %s: %s", name, external_id, exc)
            errors.append(f"{name}:{type(exc).__name__}")
            continue
        if got and got.get("text"):
            packet = build_packet(paper, got)
            log.info("원문 확보: %s provider=%s depth=%s chars=%d",
                     external_id, packet["provider"], packet["source_depth"],
                     packet["char_count"])
            return packet
        if got and got.get("parse_error"):
            errors.append(f"{name}:{got['parse_error']}")

    # ★ 실패 이유를 packet 에 남긴다. 빈 문자열로 두면 "아직 안 해 봤다"와 "해 봤는데 없다"가
    #   구별되지 않는다 — 확보율 실측이 거짓이 되는 지점이다.
    reason = "; ".join(errors) or "no_oa_location"
    log.info("원문 미확보: %s (%s)", external_id, reason)
    return build_packet(paper, {"provider": "none", "content_format": "none", "text": "",
                                "parse_error": reason})


# ─────────────────────────────────────────────────────────────
# 보관 · 조회 (0041 paper_sources)
# ─────────────────────────────────────────────────────────────
def packet_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """보관된 paper_sources 행 → packet. 저장 형태와 사용 형태를 한 곳에서 잇는다."""
    return {
        "paper_id": row.get("paper_id"),
        "external_id": str(row.get("external_id") or ""),
        "provider": str(row.get("provider") or "none"),
        "source_url": str(row.get("source_url") or ""),
        "version": str(row.get("version") or ""),
        "license": str(row.get("license") or ""),
        "content_format": str(row.get("content_format") or "none"),
        "source_depth": str(row.get("source_depth") or "abstract_only"),
        "doc_hash": str(row.get("doc_hash") or ""),
        "char_count": int(row.get("char_count") or 0),
        "truncated": bool(row.get("truncated")),
        "parse_error": str(row.get("parse_error") or ""),
        "text": str(row.get("text") or ""),
        "chunks": row.get("chunks") or [],
    }


def store_packet(packet: dict[str, Any]) -> None:
    """packet 을 paper_sources 에 보관(0041). 본문이 없으면 아무것도 남기지 않는다.

    ★ 확보 실패를 행으로 남기지 않는 이유: 다음 실행이 다시 시도해야 한다. 논문은 시간이
      지나면 OA 로 풀리는 일이 흔하다(엠바고). 실패를 박제하면 그 논문은 영영 초록만 보게 된다.
    """
    if not packet.get("text"):
        return
    db.insert_paper_source({
        "paper_id": packet.get("paper_id"),
        "external_id": packet["external_id"],
        "provider": packet["provider"],
        "content_format": packet["content_format"],
        "source_url": packet["source_url"],
        "version": packet["version"],
        "license": packet["license"],
        "source_depth": packet["source_depth"],
        "doc_hash": packet["doc_hash"],
        "char_count": packet["char_count"],
        "truncated": packet["truncated"],
        "parse_error": packet["parse_error"],
        "text": packet["text"],
        "chunks": packet["chunks"],
    })


def resolve(paper: dict[str, Any], *, store: bool = True) -> dict[str, Any]:
    """논문 1편 → source packet. **낙점 이후** 초안 생성 직전에 부른다.

    순서: 보관된 원문 조회 → 없으면 확보 체인 → 보관. 초안 재생성에서 외부 호출이 0 이 되는
    것이 보관의 즉효다. 수집(engine/collect.py)에서는 부르지 않는다 — 전 논문 원문 확보는
    저장소·시간 낭비다(명세 §3 "확보 시점").

    store=False 는 테스트·미리보기용 — 조회는 하되 새로 저장하지 않는다.
    """
    if not config.PAPER_SOURCE_ENABLED:
        return build_packet(paper, {"provider": "none", "content_format": "none", "text": ""})

    external_id = str(paper.get("external_id") or "")
    if external_id:
        try:
            row = db.get_paper_source(external_id)
        except Exception as exc:  # noqa: BLE001 — 보관 조회 실패는 재확보로 흡수된다
            log.warning("원문 보관 조회 실패(확보 체인으로 진행) %s: %s", external_id, exc)
            row = None
        if row and row.get("text"):
            packet = packet_from_row(row)
            log.info("원문 재사용(보관): %s provider=%s depth=%s chars=%d",
                     packet["external_id"], packet["provider"], packet["source_depth"],
                     packet["char_count"])
            return packet

    packet = acquire(paper)
    if store:
        store_packet(packet)
    return packet


def main(argv: list[str]) -> int:
    """`python -m engine.paper_source <paper_id>` — 낙점 논문 1편의 원문을 확보·보관한다."""
    if not argv:
        print("사용: python -m engine.paper_source <paper_id>")
        return 2
    paper = db.get_paper(argv[0])
    if not paper:
        print(f"paper 없음: {argv[0]}")
        return 1
    packet = resolve(paper)
    print(f"{packet['external_id']}: provider={packet['provider']} "
          f"depth={packet['source_depth']} chars={packet['char_count']} "
          f"license={packet['license'] or '(미상)'} "
          f"{'(상한에서 잘림)' if packet['truncated'] else ''}")
    return 0 if packet["text"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
