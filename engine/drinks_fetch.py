"""주류 공장 B단계 — 외부 페이지를 여는 **유일한** 경로(안전 요청기). 2026-10-22.

수집기는 운영자가 승인한 수집원의 주소만 연다. 그래도 서버가 외부 URL 을 여는 것이라서, 아래를
**요청할 때마다** 검사한다(등록 시점 검사만으로는 리다이렉트·DNS 로 우회된다):

  · https 만, 기본 포트(443)만, URL 안의 계정 정보 금지, IP 리터럴·내부 이름(localhost·.local 등) 금지
  · 호스트는 수집원 등록부의 allowed_hosts 안에 있어야 한다 — 리다이렉트로 다른 호스트로 못 나간다
  · DNS 해석 결과가 전부 공개 주소여야 한다(사설·루프백·링크로컬·CGNAT·멀티캐스트·예약 → 거부)
  · 연결은 **검사를 통과한 그 IP 로** 맺는다(PinnedBackend — httpx 가 이름을 다시 해석하지 않는다. DNS 재바인딩 대비).
    TLS 인증서·SNI 는 원래 호스트 이름으로 확인한다. 연결된 상대 주소(server_addr)도 한 번 더 본다
  · 리다이렉트는 자동으로 따르지 않고 최대 DRINKS_MAX_REDIRECTS 번, 매 단계 위 검사를 다시 한다
  · 응답 크기 상한(스트리밍으로 읽으며 넘으면 중단)·연결/읽기/전체 시간 상한
  · 허용한 콘텐츠 종류(HTML·XML 피드·robots 용 text/plain)만 본문으로 읽는다
  · 실행 1회 요청 수 상한, 수집원별 요청 간격, 재시도는 DRINKS_FETCH_RETRIES 번까지(무한 재시도 없음)

받은 본문은 **신뢰하지 않는 데이터**다. 여기서는 바이트를 돌려줄 뿐 해석·실행하지 않는다.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx

from . import config

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml")
HTML_TYPES = ("text/html", "application/xhtml+xml")
TEXT_TYPES = ("text/plain",)

_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".arpa")


class FetchError(Exception):
    """요청을 하지 않았거나 실패했다. code 는 실행 기록(drink_collection_items.error_code)에 그대로 남는다."""

    def __init__(self, code: str, message: str, http_status: Optional[int] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass
class FetchResult:
    url: str                      # 리다이렉트를 따라간 최종 주소
    status: int
    content_type: str
    charset: Optional[str]
    body: bytes
    redirects: list[str] = field(default_factory=list)


def user_agent() -> str:
    contact = config.SECRETS.arxiv_contact or config.SECRETS.openalex_mailto or "unknown"
    return f"{config.DRINKS_USER_AGENT_TOKEN}/0.1 (+mailto:{contact})"


def ip_is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified:
        return False
    if isinstance(a, ipaddress.IPv4Address) and a in ipaddress.ip_network("100.64.0.0/10"):
        return False  # CGNAT
    return a.is_global


def check_url(url: str, allowed_hosts: Iterable[str]) -> tuple[str, str]:
    """요청해도 되는 주소인지 본다. (host, url) 을 돌려주거나 FetchError."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise FetchError("url_invalid", f"주소를 해석하지 못했습니다: {exc}") from exc
    if parts.scheme != "https":
        raise FetchError("url_scheme", "https 주소만 엽니다")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise FetchError("url_credentials", "계정 정보가 든 주소는 열지 않습니다")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise FetchError("url_invalid", "호스트가 없습니다")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchError("url_port", "포트를 해석하지 못했습니다") from exc
    if port not in (None, 443):
        raise FetchError("url_port", "기본 포트(443) 외에는 열지 않습니다")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise FetchError("url_ip_literal", "IP 주소로 된 주소는 열지 않습니다")
    except ValueError:
        pass
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
        raise FetchError("url_internal_name", "내부 이름은 열지 않습니다")
    allowed = {h.lower() for h in allowed_hosts}
    if host not in allowed:
        raise FetchError("host_not_allowed", f"수집원에 승인되지 않은 호스트입니다: {host}")
    return host, url


Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("dns_failed", f"주소를 찾지 못했습니다: {host}") from exc
    return sorted({i[4][0] for i in infos})


class PinnedBackend(httpcore.SyncBackend):
    """TCP 연결 직전에 이름을 직접 해석·검사하고, 검사한 IP 로만 연결한다.

    httpx 가 스스로 이름을 다시 해석하면 검사와 연결 사이에 DNS 답이 바뀔 수 있다(재바인딩).
    TLS 는 httpcore 가 원래 호스트 이름(SNI·인증서 확인)으로 시작한다 — 여기서는 소켓 목적지만 바꾼다.
    """

    def __init__(self, resolver: "Resolver"):
        super().__init__()
        self._resolver = resolver

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # noqa: ANN001
        ips = self._resolver(host, port)
        if not ips or not all(ip_is_public(ip) for ip in ips):
            raise FetchError("private_address", f"{host} 가 공개 주소가 아닌 곳을 가리킵니다(연결 직전 확인)")
        return super().connect_tcp(ips[0], port, timeout=timeout, local_address=local_address, socket_options=socket_options)


class SafeFetcher:
    """수집 실행 하나가 쓰는 요청기. 요청 수·간격을 실행 단위로 센다."""

    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        interval_sec: float,
        max_requests: int,
        transport: Optional[httpx.BaseTransport] = None,
        resolver: Resolver = system_resolver,
        verify_peer: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.allowed_hosts = [h.lower() for h in allowed_hosts]
        self.interval_sec = max(float(interval_sec), float(config.DRINKS_MIN_INTERVAL_SEC))
        self.max_requests = max_requests
        self.requests = 0
        self._resolver = resolver
        self._verify_peer = verify_peer
        self._clock = clock
        self._sleep = sleep
        self._last: Optional[float] = None
        if transport is None:
            transport = httpx.HTTPTransport(retries=0)
            # httpx 0.28 은 network_backend 인자를 받지 않는다 — 연결 풀의 백엔드를 바꿔 끼운다(tests 가 감시).
            transport._pool._network_backend = PinnedBackend(resolver)
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(config.DRINKS_READ_TIMEOUT_SEC, connect=config.DRINKS_CONNECT_TIMEOUT_SEC),
            headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"},
            trust_env=False,  # 환경의 프록시 설정으로 요청이 새지 않게
        )

    def close(self) -> None:
        self._client.close()

    def _wait_turn(self) -> None:
        if self._last is not None:
            gap = self.interval_sec - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = self._clock()

    def get(self, url: str, accept: tuple[str, ...] = HTML_TYPES) -> FetchResult:
        attempt = 0
        while True:
            try:
                return self._get_once(url, accept)
            except FetchError as exc:
                retryable = exc.code in ("timeout", "transport") or (exc.code == "http_error" and (exc.http_status or 0) >= 500)
                if not retryable or attempt >= config.DRINKS_FETCH_RETRIES:
                    raise
                attempt += 1

    def _get_once(self, url: str, accept: tuple[str, ...]) -> FetchResult:
        redirects: list[str] = []
        current = url
        for _ in range(config.DRINKS_MAX_REDIRECTS + 1):
            host, current = check_url(current, self.allowed_hosts)
            ips = self._resolver(host, 443)
            if not ips or not all(ip_is_public(ip) for ip in ips):
                raise FetchError("private_address", f"{host} 가 공개 주소가 아닌 곳을 가리킵니다")
            if self.requests >= self.max_requests:
                raise FetchError("request_cap", f"이 실행의 요청 상한({self.max_requests}회)에 닿았습니다")
            self._wait_turn()
            self.requests += 1
            started = self._clock()
            try:
                with self._client.stream("GET", current) as resp:
                    self._check_peer(resp, ips)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchError("redirect_invalid", "이동할 주소가 없는 리다이렉트입니다", resp.status_code)
                        redirects.append(current)
                        current = urljoin(current, loc)
                        continue
                    if resp.status_code >= 400:
                        raise FetchError("http_error", f"HTTP {resp.status_code}", resp.status_code)
                    ctype, charset = _content_type(resp.headers.get("content-type", ""))
                    if ctype not in accept:
                        raise FetchError("unsupported_type", f"본문으로 읽지 않는 형식입니다: {ctype or '없음'}", resp.status_code)
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > config.DRINKS_MAX_RESPONSE_BYTES:
                        raise FetchError("too_large", "응답이 크기 상한보다 큽니다", resp.status_code)
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > config.DRINKS_MAX_RESPONSE_BYTES:
                            raise FetchError("too_large", "응답이 크기 상한보다 큽니다", resp.status_code)
                        if self._clock() - started > config.DRINKS_TOTAL_TIMEOUT_SEC:
                            raise FetchError("timeout", "응답이 시간 상한 안에 끝나지 않았습니다", resp.status_code)
                        chunks.append(chunk)
                    return FetchResult(url=current, status=resp.status_code, content_type=ctype, charset=charset,
                                       body=b"".join(chunks), redirects=redirects)
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", "응답이 시간 상한 안에 오지 않았습니다") from exc
            except httpx.HTTPError as exc:
                # 연결 직전 검사(PinnedBackend)가 막은 경우는 그 코드 그대로 올린다.
                cause = exc.__cause__ or exc.__context__
                if isinstance(cause, FetchError):
                    raise cause from exc
                raise FetchError("transport", f"연결하지 못했습니다: {type(exc).__name__}") from exc
        raise FetchError("too_many_redirects", f"리다이렉트가 {config.DRINKS_MAX_REDIRECTS}번을 넘었습니다")

    def _check_peer(self, resp: httpx.Response, ips: list[str]) -> None:
        if not self._verify_peer:
            return
        stream = resp.extensions.get("network_stream")
        addr = stream.get_extra_info("server_addr") if stream is not None else None
        if not addr:
            raise FetchError("peer_unknown", "연결된 상대 주소를 확인하지 못했습니다")
        if not ip_is_public(str(addr[0])):
            raise FetchError("private_address", "연결된 상대가 공개 주소가 아닙니다")


def _content_type(raw: str) -> tuple[str, Optional[str]]:
    parts = [p.strip() for p in raw.split(";")]
    ctype = parts[0].lower() if parts else ""
    charset = None
    for p in parts[1:]:
        if p.lower().startswith("charset="):
            charset = p.split("=", 1)[1].strip("\"' ").lower() or None
    return ctype, charset


class Robots:
    """robots.txt 판정(RFC 9309). 수집원 호스트마다 한 번 받아 실행 동안 기억한다.

    404 등 4xx → 제한 없음, 5xx·연결 실패 → 전부 금지(보수적으로), 리다이렉트는 요청기 규칙을 그대로 탄다.
    """

    def __init__(self, fetcher: SafeFetcher):
        self._fetcher = fetcher
        self._cache: dict[str, Optional[RobotFileParser]] = {}
        self.denied_all: set[str] = set()

    def unavailable(self, url: str) -> bool:
        """robots.txt 를 받지 못해(5xx·연결 실패) 판정할 수 없는 호스트. '금지'와 다르게 실패로 기록한다."""
        host = (urlsplit(url).hostname or "").lower()
        if host not in self._cache:
            self._cache[host] = self._load(host)
        return host in self.denied_all

    def allowed(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        if host not in self._cache:
            self._cache[host] = self._load(host)
        rp = self._cache[host]
        if rp is None:
            return host not in self.denied_all
        return rp.can_fetch(config.DRINKS_USER_AGENT_TOKEN, url)

    def _load(self, host: str) -> Optional[RobotFileParser]:
        try:
            res = self._fetcher.get(f"https://{host}/robots.txt", accept=TEXT_TYPES + HTML_TYPES)
        except FetchError as exc:
            if exc.code == "request_cap":
                raise  # 실행 전체를 멈춰야 하는 오류 — robots 판정 실패로 삼키지 않는다
            if exc.code in ("http_error", "unsupported_type") and exc.http_status and 400 <= exc.http_status < 500:
                return None  # 없음 → 제한 없음
            self.denied_all.add(host)
            return None
        rp = RobotFileParser()
        rp.parse(res.body.decode("utf-8", "replace").splitlines())
        return rp
