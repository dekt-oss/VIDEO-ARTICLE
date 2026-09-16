"""Financial Reasoning Model — 리포트 논증 단위 (작업명세서_설명엔진_v2 §7 Phase 5).

무엇을 푸는가: 리포트 초안은 "무엇을 전망했다"(number_facts)와 "어떤 순서로 말한다"
(story_plan.claim_chain)는 갖고 있지만, **그 전망이 딛는 인과 단계**는 어디에도 없다.
"목표가 9만원"과 "수주가 늘어서"가 같은 평면에 놓여 있어서, 화면이 숫자 카드 나열이 된다.
이 모듈은 그 사이에 논증 단위를 넣는다 — driver 가 실적을 거쳐 밸류에이션에 닿는 경로.

**대본보다 먼저 돈다**(D2). 대본 뒤에 논리를 끼워 맞추지 않는다.

논문 라인과 스키마를 합치지 않는다(D1). 논문은 "왜 그렇게 되는가"를, 리포트는 "왜 그렇게
전망하는가"를 설명한다 — 겹치는 것은 근거·인용 검증 인프라뿐이고 그건 report_evidence 를
그대로 쓴다.

★ 코드가 판정하는 것(모델 자기보고 폐기):
  - `reasoning_id` — 코드가 R01, R02 … 로 부여한다.
  - `fact_ids` — 원장(number_facts)에 실제로 있는 것만 남는다. dangling 참조 금지.
  - `source_refs.chunk_id` — 모델 라벨이 아니라 **인용문의 실제 위치**로 다시 매긴다
    (report_evidence.normalize_source_refs — 프로덕션에서 라벨 19개가 전부 빈 값이던 전례).
  - `grounded` — 각 단계가 근거(fact_id 또는 원문 인용)를 갖는지. 여기가 환각 방어선이다.

순수 함수(네트워크 없음): normalize_units · audit · block_reasons · reasoning_ids ·
units_block. I/O 는 build() 의 LLM 호출 하나뿐이다.
"""

from __future__ import annotations

from typing import Any

from . import config, report_evidence
from .llm import call_json
from .util import log

REASONING_SYSTEM = """너는 증권 리포트의 **논증 설계자**다. 대본을 쓰는 것이 아니다.
"무엇을 전망했다"가 아니라 **무엇이 무엇을 거쳐 그 전망에 닿는가**를 단계로 쪼개는 것이 네 일이다.

입력: Fact Sheet(JSON, number_facts 가 원장이다) + 리포트 원문 전문(있으면).
출력: JSON only. 설명 문장·마크다운·코드펜스 금지.

{
  "reasoning_units": [
    { "reasoning_id": "<비우면 코드가 R01, R02 … 로 부여>",
      "unit_type": "<DRIVER_CHAIN|EARNINGS_BRIDGE|VALUATION_LOGIC|CATALYST_PATH|RISK_PATH|SCENARIO|COMPARISON>",
      "title": "<이 논증이 설명하는 것 한 줄(한국어)>",
      "carries_thesis": <true/false — 이 영상의 핵심 주장을 지불하는 단위인가>,
      "attributed_to": "<이 논증을 편 증권사. 리포트에 없으면 ''>",
      "steps": [
        { "step": <정수 1..N>,
          "text": "<이 단계에서 실제로 일어나는 일 한 문장. 앞 단계의 결과를 받아라>",
          "fact_ids": ["<이 단계를 지불하는 number_facts 의 fact_id. 없으면 빈 배열>"],
          "source_refs": [ { "chunk_id": "", "quote": "<원문 문장 그대로. 요약·바꿔쓰기 금지>" } ] }
      ],
      "assumption": "<이 논증이 참이려면 유지돼야 하는 전제 한 줄. 없으면 ''>",
      "breaks_if": "<이 논증이 깨지는 조건 한 줄. 없으면 ''>" }
  ]
}

규칙(★ 어기면 논증이 아니라 숫자 나열이 된다):
- **단계는 상태 변화를 담아야 한다.** "실적이 좋다 → 목표가를 올렸다"는 결론 두 개를 이어 붙인
  것이지 논증이 아니다. "전력망 투자가 늘면 변압기 수주잔고가 차고, 그것이 2~3분기 뒤 매출로
  인식되며, 고마진 제품 비중이 올라 영업이익률이 개선된다"처럼 **경로**를 써라.
- 각 단계는 `fact_ids` 또는 `source_refs` 중 **최소 하나**를 반드시 갖는다. 둘 다 없는 단계는
  만들지 마라 — 근거 없는 인과는 환각이다.
- **원장에 없는 수치를 만들지 마라.** 새 숫자가 필요하면 그 단계를 쓰지 마라.
- `source_refs.quote` 는 **원문에 그대로 있는 문자열**이다. 코드가 원문과 대조한다.
- 증권사의 전망을 **사실로 쓰지 마라.** "매출이 늘어난다"가 아니라 "OO증권은 매출이 늘 것으로
  봤다". 논증의 주체가 누구인지 attributed_to 에 남긴다.
- RISK_PATH 는 리포트가 실제로 말한 리스크만. 일반적 우려를 지어내지 마라.
- 단위는 **최대 {MAX_UNITS}개**, 단계는 단위당 **최대 {MAX_STEPS}개**. 리포트에 논리가 더 많아도
  그 안에서 골라라 — 25초 영상이 담는 논증은 몇 개뿐이고, 고르는 일을 미루면 하류가 대신 못 한다.
- 핵심 주장을 지불하는 단위(carries_thesis=true)가 **최소 1개** 있어야 한다."""

REASONING_SYSTEM = (REASONING_SYSTEM
                    .replace("{MAX_UNITS}", str(config.REASONING_MAX_UNITS))
                    .replace("{MAX_STEPS}", str(config.REASONING_MAX_STEPS)))


def reasoning_user_prompt(fact_sheet: dict[str, Any], packet: dict[str, Any] | None) -> str:
    """입력: Fact Sheet + 원문 전문. 전문이 없으면 그 사실을 명시한다.

    ★ 빈 마커만 남기지 않는다 — 마커가 있으면 모델은 원문을 받았다고 여기고 인용을 지어낸다
      (report_source.fulltext_block 과 같은 자세).
    """
    import json

    from . import report_source

    body = "Fact Sheet:\n" + json.dumps(fact_sheet, ensure_ascii=False, indent=2)
    block = report_source.fulltext_block(packet or {})
    if block:
        return f"{body}\n\n{block}"
    return (f"{body}\n\n(원문 전문이 없다 — 요약 수준 정보뿐이다. source_refs 는 빈 배열로 두고 "
            f"fact_ids 로만 근거를 달아라. 인용문을 지어내지 마라.)")


# ─────────────────────────────────────────────────────────────
# 정규화 (순수)
# ─────────────────────────────────────────────────────────────
def _fact_ids(fact_sheet: dict[str, Any] | None) -> tuple[str, ...]:
    facts = (fact_sheet or {}).get("number_facts")
    if not isinstance(facts, list):
        return ()
    return tuple(str(f.get("fact_id")) for f in facts
                 if isinstance(f, dict) and f.get("fact_id"))


def _enum(val: Any, allowed: tuple[str, ...], default: str) -> str:
    tok = str(val or "").strip().upper()
    return tok if tok in allowed else default


def normalize_units(obj: dict[str, Any], fact_sheet: dict[str, Any] | None,
                    packet: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """LLM 출력 → 논증 단위 목록. 코드가 id 를 부여하고 dangling 참조를 버린다."""
    known = _fact_ids(fact_sheet)
    chunks = (packet or {}).get("chunks") or []
    raw = obj.get("reasoning_units")
    out: list[dict[str, Any]] = []
    for i, u in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(u, dict):
            continue
        steps: list[dict[str, Any]] = []
        for j, s in enumerate(u.get("steps") or []):
            if not isinstance(s, dict):
                continue
            text = str(s.get("text") or "").strip()
            if not text:
                continue
            ids = s.get("fact_ids") or []
            if isinstance(ids, str):
                ids = [ids]
            ids = [str(x).strip() for x in ids if str(x).strip() in known]
            refs = report_evidence.normalize_source_refs(s.get("source_refs"), chunks)
            steps.append({"step": int(s.get("step") or (j + 1)), "text": text,
                          "fact_ids": ids, "source_refs": refs})
            if len(steps) >= config.REASONING_MAX_STEPS:
                break
        if not steps:
            continue                       # 단계 없는 단위는 제목뿐이다 — 논증이 아니다
        out.append({
            "reasoning_id": config.REASONING_ID_FORMAT.format(len(out) + 1),
            "unit_type": _enum(u.get("unit_type"), config.REASONING_UNIT_TYPES,
                               config.DEFAULT_REASONING_UNIT_TYPE),
            "title": str(u.get("title") or "").strip(),
            "carries_thesis": bool(u.get("carries_thesis")),
            "attributed_to": str(u.get("attributed_to") or "").strip(),
            "assumption": str(u.get("assumption") or "").strip(),
            "breaks_if": str(u.get("breaks_if") or "").strip(),
            "steps": steps,
        })
        if len(out) >= config.REASONING_MAX_UNITS:
            break
    # 아무 단위도 핵심 주장을 안 든다면 첫 단위에 지운다 — 하류(대본·지시서)가 "무엇을 화면에
    # 반드시 옮겨야 하는지"를 잃지 않게. 모델의 자기보고를 코드가 보정하는 자리다.
    if out and not any(u["carries_thesis"] for u in out):
        out[0]["carries_thesis"] = True
    return out


def audit(units: list[dict[str, Any]], packet: dict[str, Any] | None) -> dict[str, Any]:
    """인용 대조 + 근거 부착률. **코드 판정** — 모델이 "인용했다"고 해도 원문과 맞춰 본다.

    ★ 판정 불가와 실패를 섞지 않는다: 원문이 없으면 quote_verify_rate 는 0.0 이 아니라 None 이다
      (report_evidence.validate_fact 와 같은 자세).
    """
    source_text = str((packet or {}).get("text") or "")
    steps = [s for u in units for s in u["steps"]]
    quotes = [r for s in steps for r in s["source_refs"]]
    verified = 0
    for r in quotes:
        ok = bool(source_text) and report_evidence.quote_found_in_source(r["quote"], source_text)
        r["verified"] = ok
        verified += int(ok)
    grounded = sum(1 for s in steps if s["fact_ids"] or s["source_refs"])
    return {
        "units": len(units),
        "steps": len(steps),
        "steps_grounded": grounded,
        "step_ground_rate": round(grounded / len(steps), 3) if steps else 0.0,
        "quotes": len(quotes),
        "quotes_verified": verified,
        # 원문이 없으면 "대조하지 않았다"이지 "전부 틀렸다"가 아니다.
        "quote_verify_rate": (round(verified / len(quotes), 3)
                              if (quotes and source_text) else None),
        "source_depth": str((packet or {}).get("source_depth") or "summary_only"),
    }


def block_reasons(units: list[dict[str, Any]]) -> list[str]:
    """승인 차단 사유. ★ 지금은 **경고로만** 쓴다(하류가 warning 으로 합류시킨다).

    명세 §6 의 게이트 E1(근거 없는 단계 금지)·E3(핵심 주장에 설명 존재)의 리포트판이다.
    차단으로 올릴지는 운영 데이터를 보고 정한다 — 지금 잠그면 요약 기반 재고가 통째로 막힌다.
    """
    reasons: list[str] = []
    if not units:
        return reasons                     # 단위가 없는 것은 이 게이트의 대상이 아니다
    if not any(u["carries_thesis"] for u in units):
        reasons.append("reasoning_no_thesis_unit")
    ungrounded = [f"{u['reasoning_id']}#{s['step']}"
                  for u in units for s in u["steps"]
                  if not s["fact_ids"] and not s["source_refs"]]
    if ungrounded:
        reasons.append("reasoning_step_without_evidence:" + ",".join(ungrounded[:5]))
    unverified = [f"{u['reasoning_id']}#{s['step']}"
                  for u in units for s in u["steps"]
                  for r in s["source_refs"] if r.get("verified") is False]
    if unverified:
        reasons.append("reasoning_quote_not_in_source:" + ",".join(sorted(set(unverified))[:5]))
    return reasons


def reasoning_ids(reasoning: dict[str, Any] | None) -> tuple[str, ...]:
    """실제로 존재하는 reasoning_id 들. 하류(대본·지시서)의 dangling 참조 검사 기준."""
    units = (reasoning or {}).get("units")
    if not isinstance(units, list):
        return ()
    return tuple(str(u.get("reasoning_id")) for u in units
                 if isinstance(u, dict) and u.get("reasoning_id"))


def units_block(reasoning: dict[str, Any] | None) -> str:
    """대본·지시서 프롬프트에 박을 논증 구간. 단위가 없으면 **빈 문자열**이다.

    마커만 남기고 속을 비우면 "논증을 줬다"고 착각하게 된다(report_source.fulltext_block 과 같은 이유).
    """
    import json

    units = (reasoning or {}).get("units") or []
    if not units:
        return ""
    slim = [{k: u[k] for k in ("reasoning_id", "unit_type", "title", "carries_thesis",
                               "attributed_to", "assumption", "breaks_if")}
            | {"steps": [{"step": s["step"], "text": s["text"], "fact_ids": s["fact_ids"]}
                         for s in u["steps"]]}
            for u in units]
    return (f"{config.REASONING_MARKER}\n"
            + json.dumps(slim, ensure_ascii=False, indent=2)
            + f"\n{config.REASONING_END_MARKER}")


def empty() -> dict[str, Any]:
    """단위 없는 빈 논증 블록. 호출부가 None 분기를 만들지 않게 모양을 항상 같게 준다."""
    return {"schema_version": config.REASONING_SCHEMA_VERSION, "units": [],
            "audit": audit([], None), "block_reasons": [], "model": ""}


# ─────────────────────────────────────────────────────────────
# 생성 (I/O 1회)
# ─────────────────────────────────────────────────────────────
def build(fact_sheet: dict[str, Any], packet: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fact Sheet(+원문) → 논증 단위 블록. 실패해도 예외를 올리지 않는다.

    ★ 여기서 죽으면 초안 생성 전체가 멈춘다. 논증은 **품질 향상 계층**이지 필수 경로가 아니다 —
      실패하면 빈 블록으로 내려가고 그 사실이 audit 에 남는다.
    """
    if not config.REPORT_REASONING_ENABLED:
        return empty()
    if not _fact_ids(fact_sheet):
        log.info("논증 단위 건너뜀 — 원장(number_facts)이 비었다")
        return empty()
    try:
        obj = call_json(model=config.MODEL_REPORT_REASONING, system=REASONING_SYSTEM,
                        user=reasoning_user_prompt(fact_sheet, packet))
    except Exception as exc:  # noqa: BLE001 — 논증 실패가 초안 전체를 막지 않는다
        log.warning("논증 단위 생성 실패(빈 블록으로 진행): %s", exc)
        out = empty()
        out["error"] = str(exc)[:200]
        return out
    units = normalize_units(obj, fact_sheet, packet)
    result = {
        "schema_version": config.REASONING_SCHEMA_VERSION,
        "units": units,
        "audit": audit(units, packet),
        "model": config.MODEL_REPORT_REASONING,
    }
    result["block_reasons"] = block_reasons(units)
    log.info("논증 단위: %d개 / 단계 %d개 근거부착 %s 인용대조 %s",
             result["audit"]["units"], result["audit"]["steps"],
             result["audit"]["step_ground_rate"], result["audit"]["quote_verify_rate"])
    return result
