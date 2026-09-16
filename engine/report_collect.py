"""리포트 수집 오케스트레이터 (명세 §2). 로컬 수동 실행: ``python -m engine.report_collect``.

ARIA list_signals 상위 N → get_signal 상세 → list_briefings 맥락 → reports 멱등 적재.
논문의 수집→병합→중복제거→1차필터가 통째로 사라진다(ARIA 가 이미 선별·정렬).

★ 정규화(normalize_signal)는 순수 함수 — 네트워크 없이 테스트 가능(tests/test_report_scoring.py).
★ 저작권 안전장치: 원문 전문(raw_content)은 저장하지 않고 요약만 REPORT_SUMMARY_MAX_CHARS 로 자른다.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from . import config, report_db, report_source
from .aria import get_client
from .models import Report
from .util import log

_URL_RE = re.compile(r"https?://[^\s)]+")
_MD_RE = re.compile(r"[*#`]+")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """마크다운 강조·과잉 공백 제거."""
    return _WS_RE.sub(" ", _MD_RE.sub("", text or "")).strip()


def _headline(text: str, max_chars: int = 80) -> str:
    """message_text 첫 의미 구간을 헤드라인 제목으로. 채점이 title_ko 를 덮어쓰기 전 폴백."""
    cleaned = _clean(text)
    # 첫 문장 경계(마침표/구두점) 또는 max_chars.
    for sep in (". ", " : ", " - ", "▶️", " · "):
        idx = cleaned.find(sep)
        if 10 < idx < max_chars:
            return cleaned[:idx].strip()
    return cleaned[:max_chars].strip()


def _extract_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    return m.group(0) if m else None


def _guess_broker(text: str) -> str | None:
    """메시지 앞부분에서 알려진 증권사명을 찾아 출처 폴백으로 쓴다(상세 channel 부재 시).

    '신한' 같은 축약 표기는 오탐 위험이 있어 전체 명칭만 매칭한다.
    """
    head = _clean(text)[:200]
    for broker in config.REPORT_KNOWN_BROKERS:
        if broker in head:
            return broker
    return None


def dedup_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 원문이 여러 테마에 매칭돼 복제된 신호를 문서 단위로 접는다(순수 함수).

    키 = 정리된 message_text 앞 REPORT_DEDUP_PREFIX_CHARS 자.
    같은 문서면 total_score 가 가장 높은 신호(가장 강한 테마 매칭)만 남긴다.
    """
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []  # 입력(우선순위) 순서 보존
    for item in signals:
        key = _clean(item.get("message_text") or "")[: config.REPORT_DEDUP_PREFIX_CHARS]
        if not key:
            key = f"__empty__{item.get('id')}"
        if key not in best:
            best[key] = item
            order.append(key)
        elif float(item.get("total_score") or 0) > float(best[key].get("total_score") or 0):
            best[key] = item
    return [best[k] for k in order]


def normalize_signal(
    item: dict[str, Any],
    detail: dict[str, Any] | None = None,
    macro_context: str | None = None,
) -> Report:
    """ARIA 신호(+상세) → reports 행(Report). 순수 함수.

    원문 전문은 저장하지 않는다 — summary 는 요약만 REPORT_SUMMARY_MAX_CHARS 로 제한.
    """
    detail = detail or {}
    sig_id = item.get("id")
    message = item.get("message_text") or detail.get("raw_content") or ""
    summary = _clean(message)[: config.REPORT_SUMMARY_MAX_CHARS]

    return Report(
        external_id=f"aria_signal:{sig_id}",
        source="aria_signal",
        title=_headline(message) or (item.get("theme_name") or "리포트"),
        summary=summary,
        theme=item.get("theme_name"),
        company=None,   # 테마 단위 신호가 많아 종목 특정은 선택(PF1 broker_targets 매칭에서 보강)
        ticker=None,
        broker=detail.get("channel") or _guess_broker(message),
        analyst=None,
        target_price=None,
        opinion=None,
        report_url=detail.get("source_url") or _extract_url(message),
        aria_priority=float(item.get("total_score") or 0),
        signal_level=item.get("signal_level"),
        is_risk=bool(item.get("is_risk")),
        matched_keywords=item.get("matched_keywords") or None,
        macro_context=macro_context,
    )


def normalize_research(item: dict[str, Any], detail: dict[str, Any] | None = None,
                       macro_context: str | None = None) -> Report:
    """ARIA 포털 리포트(research_reports 항목 + 상세) → reports 행. 순수 함수.

    ★ 전문은 여기서도 저장하지 않는다. `summary` 는 content_raw 앞부분을 잘라 만든 **요약**이고
      (REPORT_SUMMARY_MAX_CHARS), 전문은 추출 직전에 다시 불러 프롬프트에만 들어간다
      (engine/report_source.py). 저작권 자세는 0018 주석 그대로다.
    ★ 왜 요약을 content_raw 에서 만드나: search_research 의 preview 는
      "[하나증권] [LG전자] … (company)" 수준이라 4축 채점이 읽을 것이 없다. 제목만 보고
      시의성·스토리성을 매기면 채점이 제목 맞히기 게임이 된다.
    """
    detail = detail or {}
    rid = item.get("id")
    body = _clean(detail.get("content_raw") or item.get("preview") or "")
    return Report(
        external_id=f"aria_research:{rid}",
        source="aria_research",
        title=_clean(item.get("report_title") or "") or _headline(body) or "리포트",
        summary=body[: config.REPORT_SUMMARY_MAX_CHARS],
        theme=item.get("theme_name"),
        company=None,   # 종목 특정은 PF1 broker_targets 매칭에서 보강(신호 경로와 동일)
        ticker=None,
        broker=_clean(item.get("broker") or "") or _guess_broker(body),
        analyst=None,
        target_price=None,
        opinion=None,
        # ★ 여기 URL 은 채널 링크가 아니라 리포트 PDF 다 — 이 경로가 (가) 결정의 핵심이다.
        report_url=detail.get("source_url") or None,
        # 포털 리포트에는 신호 강도(total_score)가 없다. 0.0 은 "점수 없음"이고, 이 값은
        # 정렬 **동점 보정**에만 쓰이므로(report_batch.py) 4축 채점 결과가 순위를 정한다.
        aria_priority=0.0,
        signal_level=item.get("signal_level"),
        is_risk=False,
        matched_keywords=None,
        macro_context=macro_context,
    )


def portal_only(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """포털 계열(제목 있는 정식 리포트)만 남긴다.

    제목이 null 인 항목은 텔레그램 채널 메시지이고 같은 문서가 이미 aria_signal 로 들어온다 —
    두 경로로 받으면 같은 리포트가 external_id 만 다른 두 행이 된다(중복 배치).
    """
    if not config.REPORT_RESEARCH_REQUIRE_TITLE:
        return list(items)
    return [r for r in items if (r.get("report_title") or "").strip()]


def _macro_one_liner(client: Any) -> str | None:
    """list_briefings 최신 1건의 preview 를 '맥락 한 줄'로."""
    try:
        briefings = client.list_briefings(limit=1).get("items", [])
    except Exception as exc:  # noqa: BLE001 — 맥락은 부수 재료라 실패해도 수집은 계속
        log.warning("list_briefings 실패(맥락 생략): %s", exc)
        return None
    if not briefings:
        return None
    return _clean(briefings[0].get("preview") or briefings[0].get("title") or "") or None


def collect_research(client: Any, macro: str | None = None,
                     sources_out: list[dict[str, Any]] | None = None) -> list[Report]:
    """ARIA 포털 리포트 수집(§8-1 (가)). 실패해도 신호 수집을 막지 않는다.

    상세(get_research)를 항목마다 1회 부른다 — 채점이 읽을 요약과 PDF 링크가 거기에만 있다.

    ★ 원문 전문은 여기서 **보관 대상으로 넘긴다**(sources_out). 왜 수집 시점인가:
      대시보드 [초안 생성] 버튼은 Edge Function 을 부르고 Edge 에는 ARIA 접속이 없다. 수집 때
      보관해 두면 워커든 Edge 든 DB 에서 같은 전문을 읽는다 — Edge 에 ARIA 의존을 새로 만들지
      않고도 두 경로가 같은 근거를 본다. 게다가 여기선 이미 content_raw 를 손에 들고 있다.
    """
    if not config.REPORT_COLLECT_RESEARCH:
        return []
    try:
        items = client.search_research(
            status=config.ARIA_RESEARCH_STATUS, limit=config.ARIA_RESEARCH_LIMIT,
        ).get("items", [])
    except Exception as exc:  # noqa: BLE001 — 새 경로가 기존 수집을 죽이지 않는다
        log.warning("search_research 실패(포털 리포트 생략): %s", exc)
        return []

    portal = portal_only(items)
    log.info("ARIA 포털 리포트 %d건 → 정식 리포트 %d건", len(items), len(portal))

    out: list[Report] = []
    for item in portal:
        rid = item.get("id")
        detail: dict[str, Any] = {}
        try:
            detail = client.get_research(int(rid)) if rid is not None else {}
        except Exception as exc:  # noqa: BLE001 — 상세 실패면 목록 항목만으로 적재
            log.warning("get_research(%s) 실패, 목록 항목만 사용: %s", rid, exc)
        report = normalize_research(item, detail, macro)
        out.append(report)
        if sources_out is not None and detail.get("content_raw"):
            sources_out.append(report_source.build_packet(
                {"external_id": report.external_id, "report_url": report.report_url},
                str(detail.get("content_raw") or ""),
                str(detail.get("source_url") or ""),
            ))
    return out


def run() -> list[str]:
    """ARIA 신호 + 포털 리포트 수집 → reports 적재. 반환: 적재한 external_id 목록."""
    log.info("=== report_collect: 시작 ===")
    client = get_client()

    signals = client.list_signals(
        limit=config.ARIA_SIGNAL_LIMIT,
        pass_only=config.ARIA_PASS_ONLY,
        today=config.ARIA_TODAY_ONLY,
    ).get("items", [])
    raw_count = len(signals)
    signals = dedup_signals(signals)  # 같은 원문의 다중 테마 매칭 → 문서 1건으로
    log.info("ARIA 신호 %d건 → 중복 제거 후 %d건 (상위 %d)", raw_count, len(signals), config.ARIA_SIGNAL_LIMIT)

    macro = _macro_one_liner(client)

    reports: list[Report] = []
    for item in signals:
        sig_id = item.get("id")
        detail: dict[str, Any] = {}
        try:
            detail = client.get_signal(int(sig_id)) if sig_id is not None else {}
        except Exception as exc:  # noqa: BLE001 — 상세 실패해도 list 항목만으로 수집 가능
            log.warning("get_signal(%s) 실패, 목록 항목만 사용: %s", sig_id, exc)
        reports.append(normalize_signal(item, detail, macro))

    sources: list[dict[str, Any]] = []
    reports.extend(collect_research(client, macro, sources_out=sources))

    rows = [r.to_row() for r in reports]
    report_db.upsert_reports(rows)  # external_id unique → 멱등(재실행 중복 0)

    ids = [r.external_id for r in reports]
    store_sources(sources)
    log.info("=== report_collect 완료: %d reports 적재 ===", len(ids))
    return ids


def store_sources(packets: list[dict[str, Any]]) -> int:
    """수집한 원문을 report_sources 에 보관(0033). reports upsert **뒤에** 부른다 — FK 때문.

    보관 실패는 수집을 막지 않는다(report_db.insert_report_source 가 삼킨다). 실패하면 초안
    생성 때 report_source.resolve 가 ARIA 를 다시 부를 뿐이다.
    """
    if not packets or not config.SOURCE_PERSIST_FULLTEXT:
        return 0
    id_by_external = report_db.fetch_report_ids_by_external(
        [p.get("source_id") for p in packets])
    stored = 0
    for packet in packets:
        report_source.store_packet(
            packet, {"id": id_by_external.get(packet.get("source_id") or "")})
        stored += 1
    log.info("원문 보관: %d건", stored)
    return stored


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        log.exception("report_collect 실패: %s", exc)
        sys.exit(1)
