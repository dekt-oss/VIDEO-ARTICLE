"""주류 공장 B단계 — 수집 워커. 2026-10-22. docs/deviation-drinks-phase-b.md

    python -m engine.drinks_collect             # 대기 중인 실행을 처리(대시보드 [지금 수집]·[검증 실행]·[재시도])
    python -m engine.drinks_collect --schedule  # 활성 수집원마다 오늘 예약 실행을 만든 뒤 처리(일일 크론)

규칙:
  · 실행은 DB 함수가 준다(drinks_start_run). 워커는 수집원 상태를 바꾸지 않는다 — 활성화·중지·종료는 운영자만.
  · 문서는 한 건씩 drinks_collect_item 으로 기록한다. 상태(성공·부분·실패·정상 0건)는 drinks_finish_run 이
    기록된 문서로 정한다. 워처마크도 거기서만 오른다(성공한 수집 실행만).
  · 외부 요청은 engine/drinks_fetch.SafeFetcher 만 쓴다. LLM·번역·OCR·유료 호출은 없다.
  · 실행 하나가 시간 예산(DRINKS_RUN_TIME_BUDGET_SEC)·요청 상한을 넘으면 '실행 중단(aborted)' 으로 닫는다.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import config
from .drinks_fetch import FEED_TYPES, HTML_TYPES, FetchError, Robots, SafeFetcher
from .drinks_parse import article_links, canonicalize, decode, parse_feed, parse_page
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]


class DbError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


_DB_CODE = re.compile(r"drinks:([a-z_]+):([^\"'}]*)")


def supabase_rpc() -> Rpc:
    from . import db

    cli = db.client()

    def call(fn: str, p: dict[str, Any]) -> Any:
        try:
            return cli.rpc(fn, {"p": p}).execute().data
        except Exception as exc:  # noqa: BLE001 — PostgREST 오류 문장에서 drinks 오류 코드를 꺼낸다
            m = _DB_CODE.search(str(exc))
            if m:
                raise DbError(m.group(1), m.group(2).strip()) from exc
            raise
    return call


@dataclass
class Candidate:
    url: str
    title: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[date] = None


FetcherFactory = Callable[[dict[str, Any]], SafeFetcher]


def default_fetcher(run: dict[str, Any]) -> SafeFetcher:
    lim = run["limits"]
    return SafeFetcher(run["source"]["allowed_hosts"], interval_sec=lim["interval_sec"], max_requests=lim["max_requests"])


class RunProcessor:
    """실행 하나를 처리한다. 외부 요청기와 DB 호출을 주입받아 테스트에서 네트워크 없이 돈다."""

    def __init__(self, run: dict[str, Any], rpc: Rpc, fetcher: SafeFetcher,
                 clock: Callable[[], float] = time.monotonic):
        self.run = run
        self.src = run["source"]
        self.lim = run["limits"]
        self.rpc = rpc
        self.fetcher = fetcher
        self.robots = Robots(fetcher)
        self.clock = clock
        self.deadline = clock() + config.DRINKS_RUN_TIME_BUDGET_SEC
        self.validate = run["mode"] == "validate"
        self.listed = 0
        self.parsed = 0          # 목록·피드에서 찾은 글 수(호스트 필터 전). 0 이면 사이트 개편 의심
        self.offhost = 0         # 승인 밖 호스트로 이어져 가져오지 않은 글
        self.incomplete = 0      # 상한 때문에 처음 보는 글을 못 가져온 수(→ 부분 성공, 워처마크 그대로)
        self.lease_lost = False

    # ── 목록 만들기 ──

    def candidates(self) -> list[Candidate]:
        retry = self.run.get("retry_urls") or []
        if retry:
            self.parsed = len(retry)
            return [Candidate(u) for u in retry]
        method = self.src["method"]
        cfg = self.src.get("parser_config") or {}
        for pat in (cfg.get("exclude_patterns") or []) + (cfg.get("strip_patterns") or []):
            try:
                re.compile(pat)
            except re.error as exc:
                raise FetchError("parser_config_invalid", f"파서 설정의 정규식이 잘못됐습니다: {pat}") from exc
        if method == "approved_page":
            self.parsed = len(self.src["entry_urls"])
            return [Candidate(canonicalize(u)) for u in self.src["entry_urls"]]
        entry = self.src["entry_urls"][0]
        if not self.robots.allowed(entry):
            raise FetchError("robots_disallowed", "robots.txt 가 목록 주소 수집을 막습니다")
        if method == "listing":
            res = self.fetcher.get(entry, accept=HTML_TYPES)
            page = parse_page(decode(res.body, res.charset), res.url, cfg)
            links = article_links(page, self.src["allowed_hosts"], cfg.get("link_prefix") or "/",
                                  cfg.get("exclude_patterns") or [])
            self.parsed = len(links)
            # 목록의 링크 글자는 날짜·요약·"Read more" 가 섞여 제목으로 쓰기 어렵다 — 요약으로만 남기고,
            # 제목은 글 페이지를 열었을 때 그 페이지에서 꺼낸다(본문 상한 밖의 글은 제목 없이 남는다).
            return [Candidate(u, None, t[:500] or None) for u, t in links]
        if method == "feed":
            res = self.fetcher.get(entry, accept=FEED_TYPES)
            since = self._feed_since()
            entries = parse_feed(res.body)
            self.parsed = len(entries)
            allowed = {h.lower() for h in self.src["allowed_hosts"]}
            out = []
            for e in entries:
                if since and e.published_at and e.published_at < since:
                    continue
                url = canonicalize(e.url)
                if (urlsplit(url).hostname or "").lower() not in allowed or not url.startswith("https://"):
                    self.offhost += 1  # 조용히 버리지 않는다 — 실행 결과에 센다
                    continue
                out.append(Candidate(url, e.title, e.summary, e.published_at))
            return out
        raise FetchError("method_unsupported", f"수집하지 않는 방법입니다: {method}")

    def _feed_since(self) -> Optional[date]:
        raw = self.run.get("cursor_from")
        if not raw:
            return None
        return (datetime.fromisoformat(str(raw).replace("Z", "+00:00")) - timedelta(days=config.DRINKS_FEED_OVERLAP_DAYS)).date()

    # ── 문서 하나 ──

    def item_for(self, c: Candidate, bodies_left: int) -> dict[str, Any]:
        base = {"canonical_url": c.url, "url_raw": c.url, "title": c.title, "summary": c.summary,
                "published_at": c.published_at.isoformat() if c.published_at else None}
        if self.robots.unavailable(c.url):
            return {**base, "status": "failed", "error_code": "robots_unavailable",
                    "error_message": "robots.txt 를 받지 못해 수집 허용 여부를 알 수 없습니다"}
        if not self.robots.allowed(c.url):
            return {**base, "status": "skipped", "error_code": "robots_disallowed",
                    "error_message": "robots.txt 가 이 주소 수집을 막습니다"}
        if bodies_left <= 0:
            return {**base, "status": "metadata_only"}
        try:
            res = self.fetcher.get(c.url, accept=HTML_TYPES)
        except FetchError as exc:
            if exc.code == "request_cap":
                raise  # 실행 전체 중단 — 문서 실패로 삼키지 않는다
            if exc.code == "unsupported_type":  # PDF·이미지 등: 본문을 꺼내지 않는다(OCR·추출로 대신하지 않음)
                return {**base, "status": "metadata_only", "http_status": exc.http_status,
                        "error_message": exc.message}
            return {**base, "status": "failed", "error_code": exc.code, "error_message": exc.message,
                    "http_status": exc.http_status}
        if canonicalize(res.url) != c.url:
            # 리다이렉트로 다른 주소에 닿았다 — 그 최종 주소로 기록한다(같은 호스트 안에서만 따라왔다).
            base["canonical_url"] = canonicalize(res.url)
        page = parse_page(decode(res.body, res.charset), res.url, self.src.get("parser_config") or {})
        base["title"] = page.title or c.title
        if page.published_at and not c.published_at:
            base["published_at"] = page.published_at.isoformat()
        if len(page.text) < config.DRINKS_MIN_BODY_CHARS:
            return {**base, "status": "metadata_only", "http_status": res.status}
        return {**base, "status": "fetched", "http_status": res.status, "body_text": page.text}

    # ── 실행 ──

    def process(self) -> dict[str, Any]:
        fatal: Optional[FetchError] = None
        aborted: Optional[tuple[str, str]] = None
        try:
            cands = self.candidates()
            self.listed = len(cands)
            # 목록 단계가 끝났음을 남기고 임대를 연장한다(목록 페이지가 느려도 실행이 만료되지 않게).
            self.rpc("drinks_heartbeat_run", self._lease({"listed_count": self.listed,
                                                          "request_count": self.fetcher.requests}))
            limit = config.DRINKS_VALIDATE_ITEMS if self.validate else int(self.lim["max_items"])
            bodies_left = config.DRINKS_VALIDATE_ITEMS if self.validate else int(self.lim["max_bodies"])
            known = set() if self.validate else self._known([c.url for c in cands])
            # 처음 보는 글에 문서·본문 예산을 먼저 쓴다. 이미 본문이 있는 글은 남는 예산으로 변경만 확인한다.
            cands = [c for c in cands if c.url not in known] + [c for c in cands if c.url in known]
            if not self.validate:
                self.incomplete += sum(1 for c in cands[limit:] if c.url not in known)
            for c in cands[:limit]:
                if self.clock() > self.deadline:
                    aborted = ("time_budget", "실행 시간 예산을 넘어 멈췄습니다 — 남은 문서는 다음 실행에서 가져옵니다")
                    break
                try:
                    item = self.item_for(c, bodies_left)
                except FetchError as exc:  # 요청 상한 등 실행 전체를 멈춰야 하는 오류
                    if exc.code == "request_cap":
                        aborted = (exc.code, exc.message)
                        break
                    raise
                if item["status"] in ("fetched", "failed") or item.get("http_status"):
                    bodies_left -= 1
                elif item["status"] == "metadata_only" and c.url not in known and not self.validate:
                    self.incomplete += 1  # 본문 상한 때문에 처음 보는 글의 본문을 못 가져옴
                try:
                    self.rpc("drinks_collect_item", self._lease({"item": item}))
                except DbError as exc:
                    if exc.code == "lease_lost":
                        self.lease_lost = True
                        log.warning("drinks: 실행 %s 임대를 잃어 중단합니다", self.run["run_id"])
                        return {"status": "lease_lost"}
                    if exc.code == "limit_exceeded":
                        aborted = (exc.code, exc.message)
                        break
                    if exc.code == "host_not_allowed":
                        continue
                    raise
        except FetchError as exc:
            if exc.code == "request_cap":
                aborted = (exc.code, exc.message)
            else:
                fatal = exc
        except DbError as exc:
            if exc.code == "lease_lost":
                return {"status": "lease_lost"}
            fatal = FetchError("db_error", exc.message)
        except Exception as exc:  # noqa: BLE001 — 어떤 예외도 실행을 running 에 남기지 않는다
            log.exception("drinks: 실행 %s 처리 중 예외", self.run["run_id"])
            fatal = FetchError("worker_error", f"워커 예외: {type(exc).__name__}")
        finally:
            self.fetcher.close()
        payload: dict[str, Any] = {"listed_count": self.listed, "request_count": self.fetcher.requests,
                                   "parsed_count": self.parsed, "offhost_count": self.offhost,
                                   "incomplete_count": self.incomplete}
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

    def _known(self, urls: list[str]) -> set[str]:
        out: set[str] = set()
        for i in range(0, len(urls), 500):
            out.update(self.rpc("drinks_known_urls", self._lease({"urls": urls[i:i + 500]})) or [])
        return out

    def _lease(self, p: dict[str, Any]) -> dict[str, Any]:
        return {"run_id": self.run["run_id"], "lease_token": self.run["lease_token"], **p}


def schedule_runs(rpc: Rpc, today: date) -> int:
    from . import db

    rows = db.select_all("drink_sources", "id,name", key=("id",), where=lambda q: q.eq("state", "active"))
    made = 0
    for s in rows:
        try:
            r = rpc("drinks_request_run", {"source_id": s["id"], "mode": "collect", "requested_by": "schedule",
                                           "scheduled_for": today.isoformat()})
            made += 1 if (r or {}).get("run_id") else 0
        except DbError as exc:  # 이미 실행 중·하루 상한 등 — 그 수집원만 건너뛴다
            log.warning("drinks: %s 예약 실행을 만들지 않음 (%s)", s["name"], exc)
    return made


def run_queue(rpc: Rpc, *, worker_id: str, fetcher_factory: FetcherFactory = default_fetcher,
              max_runs: int = config.DRINKS_MAX_RUNS_PER_INVOCATION) -> list[dict[str, Any]]:
    results = []
    for _ in range(max_runs):
        got = rpc("drinks_start_run", {"worker_id": worker_id}) or {}
        run = got.get("run")
        if not run:
            break
        log.info("drinks: 실행 %s 시작 (%s · %s)", run["run_id"], run["source"]["name"], run["mode"])
        try:
            if run["source"].get("purpose") == "discovery":
                from .drinks_discover import DiscoveryProcessor

                out = DiscoveryProcessor(run, rpc, fetcher_factory(run)).process()
            else:
                out = RunProcessor(run, rpc, fetcher_factory(run)).process()
        except Exception as exc:  # noqa: BLE001 — 끝내기 기록마저 실패: 임대 만료 뒤 다음 워커가 '중단'으로 닫는다
            log.exception("drinks: 실행 %s 를 끝내지 못했습니다", run["run_id"])
            out = {"status": "failed", "error": type(exc).__name__}
        log.info("drinks: 실행 %s → %s", run["run_id"], (out or {}).get("status"))
        results.append({"run_id": run["run_id"], **(out or {})})
    return results


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="주류 공장 수집 워커")
    ap.add_argument("--schedule", action="store_true", help="활성 수집원마다 오늘 예약 실행을 만든다")
    args = ap.parse_args(argv)
    rpc = supabase_rpc()
    if args.schedule:
        from .util import today_local

        log.info("drinks: 예약 실행 %d건 생성", schedule_runs(rpc, today_local()))
    results = run_queue(rpc, worker_id=config.WORKER_ID)
    try:
        from .drinks_discover import read_candidate_interests, suggest_candidates

        log.info("drinks: 소재 후보 묶기 %s", suggest_candidates(rpc, read_candidate_interests))  # 규칙만(LLM 0회). 승인·편성은 사람이 한다
    except Exception:  # noqa: BLE001 — 후보 묶기 실패가 수집 결과를 가리지 않게 따로 기록
        log.exception("drinks: 소재 후보 묶기 실패")
    bad = [r for r in results if r.get("status") in ("failed", "lease_lost")]
    log.info("drinks: 실행 %d건 처리 (실패·임대 상실 %d건)", len(results), len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
