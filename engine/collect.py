"""수집 오케스트레이터 (명세 9-2). 로컬 수동 실행: ``python -m engine.collect``.

OpenAlex(주 수집 + 플래그십 created_date 워터마크) + arXiv → buzz 부착 → 병합·중복제거 → 1차 필터
→ papers upsert(멱등) → 발견 이벤트 기록 → 워터마크 전진.

수집 커버리지 v2(docs/deviation-collection-coverage-v2.md): 게재일 창만으로는 등록 지연된 플래그십
본지를 항상 놓친다 → 플래그십은 created_date 워터마크로 "새로 등록된" 것을 지연 폭 무관하게 잡는다.

실행:
  python -m engine.collect              # 주 수집 + 플래그십 워터마크 증분
  python -m engine.collect backfill     # 플래그십 초기 백필(과거 누락 구제, 1회)
"""

from __future__ import annotations

import sys
from datetime import timedelta

from . import config, db
from .pipeline import attach_buzz, dedupe, primary_filter
from .sources import arxiv, buzz, openalex, press
from .util import collection_window, log, today_local


def _route_of(p) -> str:
    """Paper → 발견 경로(주 수집/플래그십/arXiv/buzz)."""
    if p.source == "openalex":
        return "flagship_openalex" if getattr(p, "is_flagship", False) else "main_openalex"
    if p.source == "arxiv":
        return "arxiv"
    return "buzz"


def _record_discovery(papers: list) -> None:
    """upsert 된 논문의 발견 경로를 이벤트로 기록(§7). buzz 동반 시 추가 이벤트."""
    ext_to_id = db.get_paper_ids_by_external([p.external_id for p in papers])
    events: list[dict] = []
    for p in papers:
        pid = ext_to_id.get(p.external_id)
        if not pid:
            continue
        events.append({"paper_id": pid, "external_id": p.external_id, "route": _route_of(p),
                       "source_name": p.venue, "match_method": "doi_direct"})
        if p.buzz_raw and _route_of(p) != "buzz":  # 다른 경로로 들어왔지만 화제성도 있음
            events.append({"paper_id": pid, "external_id": p.external_id, "route": "buzz",
                           "match_method": "doi_direct"})
    try:
        db.record_discovery_events(events)  # 발견 이벤트 기록 실패가 papers 적재를 무효화하지 않게
    except Exception as exc:  # noqa: BLE001
        log.warning("발견 이벤트 기록 실패(무시): %s", exc)


def _press_signal(bm: dict, ext: str, route: str) -> None:
    """언론 언급을 buzz_map 에 화제성 신호로 합류(품질 아님, 가중 작게)."""
    a = bm.setdefault(ext, {"hn_points": 0, "hn_comments": 0, "reddit_score": 0,
                            "reddit_comments": 0, "total": 0, "links": [], "press_mentions": 0})
    a["press_mentions"] = a.get("press_mentions", 0) + 1
    a["total"] = a.get("total", 0) + config.PRESS_SIGNAL_WEIGHT


def _merge_press(buzz_map: dict, papers: list) -> None:
    """과학 언론 RSS(§6): 해결된 DOI 는 buzz_map 합류, 미해결은 제목매칭→실패 시 큐로."""
    try:
        items = press.collect()
    except Exception as exc:  # noqa: BLE001 — 언론 실패가 수집 전체를 막지 않게(§6)
        log.exception("언론 RSS 수집 실패(무시): %s", exc)
        return
    unresolved: list[dict] = []
    resolved = 0
    for it in items:
        ext = it.get("external_id")
        method = it.get("method")
        if not ext:  # ④⑤ 제목 유사도로 기수집 논문과 대조
            ext, sim = press.match_to_paper(it, papers)
            method = "title_match"
            if not ext:
                unresolved.append({"route": it.get("route"), "title": it.get("title"),
                                   "source_item_url": it.get("url"), "best_similarity": sim})
                continue
        _press_signal(buzz_map, ext, it.get("route") or "press")
        resolved += 1
    try:
        db.upsert_unresolved_buzz(unresolved)  # 큐 적재 실패가 수집 전체를 막지 않게(보조 산출물)
    except Exception as exc:  # noqa: BLE001
        log.warning("미매칭 큐 적재 실패(무시): %s", exc)
    log.info("언론 매칭: %d 해결 / %d 미해결", resolved, len(unresolved))


def _safe_collect(name: str, fn, *args) -> list:
    """소스 수집 1건을 격리 실행. 한 소스의 일시 오류(예: arXiv 429)가 전체 배치를 죽이지 않게 한다.

    ★ 근거: 과거 arXiv 429 가 openalex+arxiv 이어붙이기를 통째로 크래시시켜 그날 daily_batch 가 통째로
      사라졌다(engine.yml #23). 소스별 try/except 로 격리하면 한 소스가 죽어도 다른 소스로 배치가 유지된다.
      (플래그십·buzz 수집은 이미 try/except 로 보호돼 있었고, 주 수집 두 소스만 무방비였다.)
    """
    try:
        out = fn(*args) or []
        log.info("%s 수집: %d papers", name, len(out))
        return out
    except Exception as exc:  # noqa: BLE001
        log.exception("%s 수집 실패(다른 소스로 계속): %s", name, exc)
        return []


def run() -> list[str]:
    start, end = collection_window()
    log.info("=== collect: window %s ~ %s ===", start, end)

    papers = _safe_collect("OpenAlex", openalex.collect, start, end) + \
        _safe_collect("arXiv", arxiv.collect, start, end)
    log.info("수집 합계(OpenAlex/arXiv): %d papers", len(papers))

    # 플래그십 전용 넓은 게재일 롤링 수집(지연 색인분 포착). 실패해도 주 수집은 유지.
    try:
        pub_from = today_local() - timedelta(days=config.FLAGSHIP_PUB_LOOKBACK_DAYS)
        flagship = openalex.collect_flagship(pub_from)
        papers += flagship
        log.info("플래그십 수집: %d papers (게재일 ≥ %s)", len(flagship), pub_from)
    except Exception as exc:  # noqa: BLE001
        log.exception("플래그십 수집 실패(주 수집은 계속): %s", exc)

    # buzz 신호 수집 + 과학 언론 RSS(P2) 합류 → HN-우선 인테이크(화제 논문 메타 fetch)
    buzz_map = buzz.collect()
    _merge_press(buzz_map, papers)
    papers += buzz.fetch_buzz_papers(buzz_map)
    attach_buzz(papers, buzz_map)
    log.info("HN·언론 인테이크 포함 합계: %d papers", len(papers))

    papers = dedupe(papers)
    papers = primary_filter(papers)

    rows = [p.to_row() for p in papers]
    db.upsert_papers(rows)
    _record_discovery(papers)

    external_ids = [p.external_id for p in papers]
    log.info("=== collect 완료: %d papers 적재 ===", len(external_ids))
    return external_ids


def run_flagship_backfill(days: int | None = None) -> list[str]:
    """플래그십 초기 백필(§3-3): 게재일 오늘−days 이후 플래그십 논문 1회 수집(과거 누락 구제)."""
    days = days if days is not None else config.FLAGSHIP_BACKFILL_DAYS
    pub_from = today_local() - timedelta(days=days)
    log.info("=== flagship backfill: pub ≥ %s ===", pub_from)
    papers = openalex.collect_flagship(pub_from)
    papers = dedupe(papers)
    papers = primary_filter(papers)
    rows = [p.to_row() for p in papers]
    db.upsert_papers(rows)
    _record_discovery(papers)
    log.info("=== flagship backfill 완료: %d papers ===", len(papers))
    return [p.external_id for p in papers]


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "backfill":
            run_flagship_backfill()
        else:
            run()
    except Exception as exc:  # 운영 가시성
        log.exception("collect 실패: %s", exc)
        sys.exit(1)
