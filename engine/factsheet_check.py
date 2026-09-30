"""Fact Sheet 요약 객관화 — 원문이 뒷받침하지 않는 요약 줄을 거른다 (2026-09-30).

운영자: "팩트 시트에서는 최대한 객관화해서 수집합시다."

무엇이 있었나
------------
Fact Sheet 는 대본·지시서·근거 판정이 모두 믿는 **원장**이다. claims 는 source_quote 를 원문과 문자열 대조해
검증하지만, 요약 칸(`what_found`)은 대조가 없었다. 그래서 추출 단계에서 과장이 들어가면(예: 원문 "호주 제외
비극지 대륙에서 공간 변동의 상당 부분" → what_found "인간 활동이 전 세계 물 저장량 변화의 **주요 원인**")
그 뒤의 모든 검사가 그 과장을 "근거가 있다"고 본다 — 원리상 못 잡는 자리였다(docs/jev_감사_2026-09-30.md §4).

무엇을 하나
----------
요약 줄마다 판정 모델(Jev)에게 "초록 + 검증된 claim 인용문이 이 줄을 뒷받침하나"를 묻고, 문턱 이상이면
그 줄을 **요약에서 뺀다**(지우지 않고 `summary_check.dropped` 에 남긴다 — 사람이 볼 수 있게).
claims 는 건드리지 않는다(이미 원문 대조를 거쳤다).

★ fail-open: Jev 가 꺼졌거나 죽으면 아무것도 빼지 않는다(종전 동작).
★ 순수 함수가 아니다(판정 모델 호출). 테스트는 decide 를 흉내 낸다.
"""

from __future__ import annotations

from typing import Any

from . import config, decide


_WINDOW = 700


def fulltext_passages(item: str, fulltext: str, k: int = 4) -> list[str]:
    """요약 줄 하나에 관련된 원문 구절 k 개 — 줄의 **숫자·영문 용어**가 많이 나오는 창을 고른다.

    ★ 왜 필요한가(2026-09-30 실측): 초록 + claim 만 근거로 주면 원문 본문에만 있는 사실이 "근거 없음"으로
      걸렸다("해상도 5~10배 향상" — 본문 "5 to 10 times"). 요약은 한국어, 원문은 영어라 낱말 겹침은 약하고
      숫자·고유 용어(GRACE, ICL, Sst-Chodl…)가 가장 믿을 만한 연결고리다.
    """
    text = str(fulltext or "")
    if not text:
        return []
    import re
    toks = set(re.findall(r"\d+(?:\.\d+)?", item)) | {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", item)}
    if not toks:
        return []
    low = text.lower()
    scored: list[tuple[int, int]] = []
    for start in range(0, max(1, len(text) - _WINDOW), _WINDOW // 2):
        w = low[start:start + _WINDOW]
        score = sum(w.count(t) for t in toks)
        if score:
            scored.append((score, start))
    picked: list[int] = []
    for _, start in sorted(scored, reverse=True):
        if all(abs(start - p) >= _WINDOW for p in picked):
            picked.append(start)
        if len(picked) >= k:
            break
    return [text[s:s + _WINDOW].replace("\n", " ") for s in sorted(picked)]


def reference_text(abstract: str, fact_sheet: dict[str, Any], item: str = "", fulltext: str = "") -> str:
    """판정 근거: 초록 + 원문 대조를 통과한 claim 인용문 + (있으면) 이 줄에 관련된 원문 구절."""
    lines = [f"ABSTRACT: {str(abstract or '')[:config.JEV_GROUNDING_ABSTRACT_CHARS * 2]}"]
    for p in fulltext_passages(item, fulltext):
        lines.append(f"FULL TEXT EXCERPT: …{p}…")
    for c in fact_sheet.get("claims") or []:
        if not isinstance(c, dict):
            continue
        q = str(c.get("source_quote") or "").strip()
        lines.append(f"[{c.get('claim_id')} causal={c.get('causal_strength')}] {c.get('claim_ko') or ''}"
                     + (f' — quote: "{q}"' if q else ""))
    return "\n".join(lines)


def objectify_summaries(fact_sheet: dict[str, Any], abstract: str, fulltext: str = "") -> dict[str, Any]:
    """`what_found` 에서 근거가 원문보다 센 줄을 빼고 `summary_check` 를 붙인다(제자리 수정 후 반환)."""
    if not (config.FACTSHEET_OBJECTIFY_ENABLED and decide.enabled()):
        return fact_sheet
    items = [str(x) for x in (fact_sheet.get("what_found") or []) if str(x).strip()]
    if not items:
        return fact_sheet
    kept: list[str] = []
    dropped: list[dict[str, Any]] = []
    asked = 0
    for s in items:
        ref = reference_text(abstract, fact_sheet, item=s, fulltext=fulltext)
        with decide.about("what_found"):
            p = decide.unsupported_claim_p(s, ref)
        if p is not None:
            asked += 1
        if p is not None and p >= config.FACTSHEET_SUMMARY_DROP_MIN:
            dropped.append({"text": s, "p": round(p, 3)})
        else:
            kept.append(s)
    fact_sheet["what_found"] = kept
    fact_sheet["summary_check"] = {"threshold": config.FACTSHEET_SUMMARY_DROP_MIN,
                                   "checked": asked, "dropped": dropped}
    return fact_sheet
