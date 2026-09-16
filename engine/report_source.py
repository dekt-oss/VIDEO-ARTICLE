"""Source Contract — 리포트 원문 확보 (작업지시서 영상엔진품질 v3 §4).

무엇을 푸는가: Fact Sheet 추출이 지금까지 **미리보기 366자**만 보고 돌았다. ARIA 는 같은
리포트의 전문을 갖고 있었지만 engine/aria/client.py 가 그 도구를 부르지 않았다
(근거·실측: docs/phase0-영상엔진품질_v3.md §1-3).

방침(§8-1 결정 (가) — 운영자 결정 2026-08-02):
- 전문을 `report_sources`(0033)에 **보관한다.** 인용 검증(§5-2)이 대조할 원문을 요구하고,
  Phase 4 전후 비교가 같은 입력을 요구하며, 보관하면 재생성 때 ARIA 호출이 0 이 된다.
  보관 범위는 우리가 영상으로 만든 리포트로 한정되고 배포하지 않는다(0033 헤더 주석).
- `source_depth` 는 **코드가 글자 수로 판정**한다. 모델이나 지시서가 스스로 신고하는 값을
  믿지 않는다(engine/explainer.py 의 source_mode 와 같은 자세).
- 페이지 번호는 만들지 않는다. PDF 를 우리가 파싱하지 않으므로 chunk 는 문자 길이로 나누고
  page_start/page_end 를 두지 않는다 — 없는 페이지 번호가 화면에 나가는 것이 §21 K1 사고다.

순수 함수(네트워크·DB 없음): parse_external_id · classify_depth · chunk_text · doc_hash ·
build_packet · fulltext_block. I/O 는 fetch_fulltext(ARIA)·resolve(보관 조회·저장)뿐이다.
"""

from __future__ import annotations

import hashlib
from typing import Any

from . import config, report_db
from .aria import get_client
from .util import log


def parse_external_id(external_id: str | None) -> tuple[str, int] | None:
    """`reports.external_id` → (종류, ARIA id). 형식이 아니면 None.

    'aria_signal:2871' → ("signal", 2871) / 'aria_research:4902' → ("research", 4902)
    """
    if not external_id or ":" not in external_id:
        return None
    prefix, _, raw = external_id.partition(":")
    kind = {"aria_signal": "signal", "aria_research": "research"}.get(prefix.strip())
    if not kind:
        return None
    try:
        return kind, int(raw.strip())
    except ValueError:
        return None


def classify_depth(text: str) -> str:
    """확보한 원문 길이 → source_depth(§4-1). 코드 판정 — 자기보고 불신.

    full_text 는 "우리가 전문을 손에 들고 있다"는 뜻이지 "PDF 를 파싱했다"는 뜻이 아니다.
    ARIA 가 이미 PDF 에서 뽑아준 본문이 그 자리를 대신한다.
    """
    n = len(text or "")
    if n == 0:
        return "summary_only"
    if n >= config.SOURCE_FULLTEXT_MIN_CHARS:
        return "full_text"
    return "partial_text"


def chunk_text(text: str, size: int | None = None) -> list[dict[str, Any]]:
    """전문을 문자 길이로 나눈다. ★ 페이지 번호를 붙이지 않는다(§4-1 주석 참조)."""
    size = size or config.SOURCE_CHUNK_CHARS
    body = (text or "").strip()
    if not body:
        return []
    out: list[dict[str, Any]] = []
    for i in range(0, len(body), size):
        out.append({
            "chunk_id": f"C{len(out) + 1:03d}",
            "char_start": i,
            "char_end": min(i + size, len(body)),
            "text": body[i:i + size],
        })
    return out


def doc_hash(text: str) -> str:
    """원문 지문. 보관 중복 방지 키이자 인용 대조 앵커(§5-2). 순수 함수."""
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def fetch_fulltext(report: dict[str, Any], client: Any = None) -> tuple[str, str]:
    """ARIA 에서 이 리포트의 원문을 불러온다. 반환: (전문, 원문 링크).

    research → get_research(id).content_raw (증권사 정식 리포트 PDF 추출 전문)
    signal   → get_signal(id).raw_content   (텔레그램 메시지 전문 — 미리보기보다 길다)

    실패는 예외로 올리지 않는다. 원문을 못 구하면 요약 기반으로 내려가고 그 사실이
    source_depth 에 남는다 — 여기서 죽으면 파이프라인 전체가 멈춘다.
    """
    parsed = parse_external_id(report.get("external_id"))
    if not parsed:
        return "", str(report.get("report_url") or "")
    kind, aria_id = parsed
    cli = client or get_client()
    try:
        if kind == "research":
            detail = cli.get_research(aria_id) or {}
            return str(detail.get("content_raw") or ""), str(detail.get("source_url") or "")
        detail = cli.get_signal(aria_id) or {}
        return str(detail.get("raw_content") or ""), str(detail.get("source_url") or "")
    except Exception as exc:  # noqa: BLE001 — 원문 확보 실패가 추출 전체를 막지 않는다
        log.warning("원문 확보 실패(요약으로 진행) external_id=%s: %s",
                    report.get("external_id"), exc)
        return "", str(report.get("report_url") or "")


def build_packet(report: dict[str, Any], full_text: str, source_url: str = "") -> dict[str, Any]:
    """원문 → source packet(§4-1 스키마에서 bbox·page 제거 — YAGNI + 페이지 날조 금지).

    truncated 는 숨기지 않는다. 상한에 걸려 잘렸다면 그 사실이 하류(게이트·승인 화면)에
    보여야 "리포트 뒷부분 근거가 왜 없나"를 설명할 수 있다.
    """
    text = (full_text or "").strip()
    cap = config.SOURCE_FULLTEXT_MAX_CHARS
    truncated = len(text) > cap
    if truncated:
        text = text[:cap]
    return {
        "source_id": str(report.get("external_id") or ""),
        "source_type": "research" if (parse_external_id(report.get("external_id")) or ("", 0))[0]
                       == "research" else "signal",
        "source_depth": classify_depth(text),
        "source_url": source_url or str(report.get("report_url") or ""),
        "doc_hash": doc_hash(text) if text else "",
        "char_count": len(text),
        "truncated": truncated,
        "text": text,
        "chunks": chunk_text(text),
    }


def packet_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """보관된 report_sources 행 → packet. 저장 형태와 사용 형태를 한 곳에서 잇는다."""
    return {
        "source_id": str(row.get("external_id") or ""),
        "source_type": str(row.get("source_type") or "signal"),
        "source_depth": str(row.get("source_depth") or "summary_only"),
        "source_url": str(row.get("source_url") or ""),
        "doc_hash": str(row.get("doc_hash") or ""),
        "char_count": int(row.get("char_count") or 0),
        "truncated": bool(row.get("truncated")),
        "text": str(row.get("text") or ""),
        "chunks": row.get("chunks") or [],
    }


def store_packet(packet: dict[str, Any], report: dict[str, Any]) -> None:
    """packet 을 report_sources 에 보관(0033). 전문이 없으면 아무것도 남기지 않는다."""
    if not packet.get("text"):
        return
    report_db.insert_report_source({
        "report_id": report.get("id"),
        "external_id": packet["source_id"],
        "source_type": packet["source_type"],
        "source_depth": packet["source_depth"],
        "source_url": packet["source_url"],
        "doc_hash": packet["doc_hash"],
        "char_count": packet["char_count"],
        "truncated": packet["truncated"],
        "text": packet["text"],
        "chunks": packet["chunks"],
    })


def resolve(report: dict[str, Any], client: Any = None, *, store: bool = True) -> dict[str, Any]:
    """리포트 1건 → source packet. 추출 직전에 부른다.

    순서: 보관된 원문 조회 → 없으면 ARIA 호출 → 보관. 초안 재생성·[재검사]에서 ARIA 호출이
    0 이 되는 것이 보관의 즉효다(§8-1 ③).

    store=False 는 테스트·미리보기용 — 조회는 하되 새로 저장하지 않는다.
    """
    if not config.SOURCE_INJECT_FULLTEXT:
        return build_packet(report, "")

    external_id = str(report.get("external_id") or "")
    if external_id:
        try:
            row = report_db.get_report_source(external_id)
        except Exception as exc:  # noqa: BLE001 — 보관 조회 실패는 ARIA 재호출로 흡수된다
            log.warning("원문 보관 조회 실패(ARIA 로 진행) %s: %s", external_id, exc)
            row = None
        if row and row.get("text"):
            packet = packet_from_row(row)
            log.info("원문 재사용(보관): %s depth=%s chars=%d",
                     packet["source_id"], packet["source_depth"], packet["char_count"])
            return packet

    text, url = fetch_fulltext(report, client)
    packet = build_packet(report, text, url)
    log.info("원문 확보(ARIA): %s depth=%s chars=%d%s", packet["source_id"],
             packet["source_depth"], packet["char_count"],
             " (상한에서 잘림)" if packet["truncated"] else "")
    if store:
        store_packet(packet, report)
    return packet


def fulltext_block(packet: dict[str, Any]) -> str:
    """프롬프트에 박을 전문 구간. 마커가 있어야 §11-1 CI 가드를 통과한다.

    전문이 없으면 **빈 문자열**이다 — 마커만 남기고 속을 비우면 "전문을 줬다"고 착각하게 된다.
    """
    text = (packet or {}).get("text") or ""
    if not text:
        return ""
    head = f"{config.SOURCE_FULLTEXT_MARKER}\n"
    if packet.get("truncated"):
        head += f"(원문이 {config.SOURCE_FULLTEXT_MAX_CHARS}자 상한에서 잘렸다 — 뒷부분 없음)\n"
    return f"{head}{text}\n{config.SOURCE_FULLTEXT_END_MARKER}"
