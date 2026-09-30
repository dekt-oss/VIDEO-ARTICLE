"""나레이션이 원문을 넘었나 — Jev 근거 판정 (2026-09-30, 운영자 승인 "1~3 진행해").

무엇을 잡나
----------
환각 방지 불변식은 "화면에 나가는 주장은 원문에 있는 것만"이다. 숫자는 감사(directive_audit)가
문자열로 대조하지만, **말의 세기**는 문자열로 못 잰다: "감소"를 "멈춘다"로, "파이프라인 보유"를
"대체하고 있다"로, "일부 대륙의 상당 부분"을 "전 세계 주요 원인"으로. 원문 대조 감사(상위 20건,
docs/jev_감사_2026-09-30.md §4)에서 Jev 가 이런 것을 잡았다.

★ 판정 입력은 Fact Sheet **만이 아니다.** Fact Sheet 에는 방법·기관명이 자주 빠져서(초록·저자 소속에는
  있다) 멀쩡한 문장이 걸렸다 — 20건 중 오탐 4건이 그 탓이었다. 그래서 원문 메타데이터와 초록(리포트는
  요약)을 같이 넣는다. 원문 전문은 넣지 않는다 — 판정 한 번에 수만 자를 보내는 것은 비용·지연에 비해
  이득이 확인되지 않았다.

★ **경고만 낸다**(차단·재생성 없음). Jev 가 꺼졌거나 죽으면 아무 경고도 없다(fail-open).
  "원문을 사람이 대조하라"는 종류라 경고 분류는 근거 확인(fact)이다.
★ 두 라인 모두에 붙어 있다. 리포트(2026-09-30 첫 적용)는 Fact Sheet 에 claims 가 없어 LLM 자기검증이
  스스로 꺼지던 자리이고, 논문(같은 날 운영자 "논문에도 당연히")은 자기검증과 겹치지 않는 사례를 잡는다.
"""

from __future__ import annotations

import json
from typing import Any

from . import config, decide


def facts_text(fs: dict[str, Any], limit: int = 0) -> str:
    """Fact Sheet → 판정용 근거 문자열. 논문 claim 에는 종류·인과 강도·등급·한계를 붙인다."""
    parts: list[str] = []
    for c in (fs or {}).get("claims") or []:
        if not isinstance(c, dict):
            continue
        lim = "; ".join(str(x) for x in (c.get("limitations") or [])[:2])
        parts.append(f"[{c.get('claim_id')} {c.get('claim_kind')} causal={c.get('causal_strength')} "
                     f"grade={c.get('evidence_grade')}] {c.get('claim_ko')}"
                     + (f" (population: {c['population']})" if c.get("population") else "")
                     + (f" (effect: {c['effect_size']} {c.get('effect_unit') or ''})"
                        if c.get("effect_size") else "")
                     + (f" (limits: {lim})" if lim else ""))
    for key in ("what", "basis", "numbers", "risks", "what_found", "limitations"):
        for x in (fs or {}).get(key) or []:
            parts.append(f"[{key}] {x if not isinstance(x, dict) else json.dumps(x, ensure_ascii=False)}")
    for key in ("claim_strength", "opinion"):
        if (fs or {}).get(key):
            parts.append(f"[{key}] {fs[key]}")
    text = "\n".join(parts)
    return text[:limit] if limit else text


def paper_context(paper: dict[str, Any]) -> str:
    """논문 메타 + 초록. 저자 소속은 OpenAlex `authors[].institution` 에서."""
    authors = [a for a in (paper.get("authors") or []) if isinstance(a, dict)]
    names = ", ".join(str(a.get("name")) for a in authors[:3] if a.get("name"))
    inst = ", ".join(sorted({str(a["institution"]) for a in authors if a.get("institution")}))
    return (f"PAPER: {paper.get('title') or ''} | venue: {paper.get('venue') or ''}"
            f" | authors: {names} | institutions: {inst}\n"
            f"ABSTRACT: {str(paper.get('abstract') or '')[:config.JEV_GROUNDING_ABSTRACT_CHARS]}")


def report_context(report: dict[str, Any]) -> str:
    """리포트 메타 + 요약."""
    return (f"REPORT: {report.get('title') or ''} | broker: {report.get('broker') or ''}"
            f" | company: {report.get('company') or report.get('theme') or ''}\n"
            f"SUMMARY: {str(report.get('summary') or '')[:config.JEV_GROUNDING_ABSTRACT_CHARS]}")


def source_state(context: str, fact_sheet: dict[str, Any]) -> str:
    """판정에 보낼 근거 묶음. 메타·초록이 앞, Fact Sheet 가 뒤 — 상한에 걸리면 Fact Sheet 끝이 잘린다."""
    return f"{context}\nFACT SHEET:\n{facts_text(fact_sheet)}"


def unsupported_cuts(cuts: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """컷별 판정 → 문턱을 넘은 컷 [{cut_no, p}]. 못 물은 컷은 조용히 빠진다(fail-open)."""
    out: list[dict[str, Any]] = []
    if not (decide.enabled() and str(source or "").strip()):
        return out
    for c in cuts:
        nar = str((c or {}).get("narration_ko") or "").strip()
        if not nar:
            continue
        with decide.about(f"cut{c.get('cut_no')}"):
            p = decide.unsupported_claim_p(nar, source)
        if p is not None and p >= config.JEV_UNSUPPORTED_CLAIM_MIN:
            out.append({"cut_no": c.get("cut_no"), "p": round(p, 3)})
    return out


def _attach(directive: dict[str, Any], source: str, code: str) -> None:
    header = directive["header"]
    with decide.tracing() as calls:
        n0 = len(calls)
        flagged = unsupported_cuts(directive.get("cuts") or [], source)
        mine = list(calls[n0:])
    if mine:
        prev = header.get("jev_trace") or {}
        header["jev_trace"] = decide.trace_summary([*(prev.get("calls") or []), *mine])
    header["grounding_check"] = {"threshold": config.JEV_UNSUPPORTED_CLAIM_MIN, "flagged": flagged}
    if flagged:
        header["mode_warnings"] = sorted(set([
            *(header.get("mode_warnings") or []),
            f"{code}:" + ",".join(str(f["cut_no"]) for f in flagged[:6])]))


def attach_report_warning(directive: dict[str, Any], draft_row: dict[str, Any],
                          report: dict[str, Any] | None) -> None:
    """리포트 지시서 헤더에 `report_claim_unsupported:컷,컷` 경고와 판정 기록을 붙인다(제자리 수정)."""
    if not (config.JEV_GROUNDING_REPORT_ENABLED and decide.enabled()):
        return
    _attach(directive, source_state(report_context(report or {}), draft_row.get("fact_sheet") or {}),
            "report_claim_unsupported")


def attach_paper_warning(directive: dict[str, Any], draft_row: dict[str, Any],
                         paper: dict[str, Any] | None = None) -> None:
    """논문 지시서 헤더에 `paper_claim_unsupported:컷,컷` 경고(2026-09-30 운영자: "논문에도 당연히 근거 켜야지").

    논문 라인에는 LLM 자기검증(directive_ungrounded)도 있다 — 둘은 겹치지 않았다(같은 컷에서 자기검증 0건,
    Jev 6건, docs/jev_감사_2026-09-30.md §4). 입력은 제목·저자·소속·초록 + Fact Sheet 전체.
    """
    if not (config.JEV_GROUNDING_PAPER_ENABLED and decide.enabled()):
        return
    if paper is None:
        paper = draft_row.get("paper")
    if paper is None:
        from . import db
        paper = db.get_paper(str(draft_row.get("paper_id") or "")) or {}
    _attach(directive, source_state(paper_context(paper), draft_row.get("fact_sheet") or {}),
            "paper_claim_unsupported")
