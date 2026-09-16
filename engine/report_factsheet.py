"""(a) Fact Sheet 추출 — 금융용 (명세 5-1).

증권사 리포트에서 "검증 가능한 사실"만 추출한다. 이후 대본 생성의 유일한 입력이 되므로
환각 방지의 1차 방어선(논문 factsheet.py 미러 + 금융 필드).

★ 입력 변경(작업지시서 영상엔진품질 v3 §4-2, Phase 0 결정 §8-1): 예전에는 요약 한 줄만 넣었다.
  지금은 ARIA 에서 **원문 전문**을 런타임에 불러 `<<FULL_SOURCE>>` 구간으로 함께 넣는다
  (engine/report_source.py). 저장하지 않고 프롬프트에만 들어간다.
  tests/test_fulltext_injection.py 가 그 마커의 존재를 검사한다 — 조용히 빠질 수 없다.
"""

from __future__ import annotations

import re
from typing import Any

from . import config, report_evidence, report_source
from . import llm as llm_mod
from .llm import JSONParseError, call_json
from .util import log

FACTSHEET_SYSTEM = """너는 사실 검증관이다. 아래 증권사 리포트에서 "검증 가능한 사실"만 추출한다.
추측·전망 창작·원문에 없는 내용 금지. 항목별로 근거가 없으면 빈 배열로 둔다.
★ 원문 전문이 <<FULL_SOURCE>> … <</FULL_SOURCE>> 구간으로 주어지면 **그 전문을 근거로 삼아라.**
  요약만 보고 답하지 마라. 전문에 표·재무제표가 있으면 그 수치를 우선한다.
JSON only. 설명 문장·마크다운·코드펜스 금지.
★ 아래 키 순서를 **그대로 지켜 출력하라.** number_facts 가 맨 뒤인 것이 중요하다 —
  길어져서 잘리더라도 opinion·basis·risks 는 이미 나온 뒤여야 한다(리스크가 빠진 영상은 사고다).
{
  "company": "<종목/테마>",
  "what": ["<리포트의 핵심 주장/근거 사실들>"],
  "opinion": "<투자의견 원문 그대로 (예: 'OO증권 매수, 목표가 9만원'). 없으면 ''>",
  "basis": ["<증권사가 제시한 논리/촉매>"],
  "risks": ["<리포트가 언급한 리스크·전제·불확실성>"],
  "source": "<증권사명 + 애널리스트 + 발행일 (있는 것만)>",
  "number_facts": [
    { "fact_id": "<snake_case 식별자 (예: num_target_price, num_per_2026). 비우면 코드가 부여>",
      "value": <숫자만 (단위 제외, 예: 48.6). 수치 아니면 null>,
      "unit": "<단위 (예: 'x','%','원','억','조'). 없으면 ''>",
      "period": "<시점 (예: '2026F','1Q26','TTM'). 없으면 ''>",
      "metric": "<지표명 (예: 'PER','영업이익','목표주가'). 없으면 ''>",
      "scope": "<company|segment|market. 기본 company>",
      "basis": "<broker_estimate|actual|consensus|company_guidance. 없으면 ''>",
      "attribution": "<이 수치의 출처 증권사. 없으면 ''>",
      "interpretation": "<valuation_risk|growth|neutral. ★리포트가 실제로 그렇게 규정했을 때만. 근거 없으면 neutral>",
      "source_page": <리포트 페이지 정수. 없으면 null>,
      "comparator": { "basis": "<비교 기준 (예: 컨센서스·전년 동기·직전 분기·가이던스). 없으면 ''>",
                      "value": "<비교 대상 값 (예: '860억원', '+2.6%'). 없으면 ''>" },
      "source_refs": [ { "chunk_id": "<주어진 원문 청크 id. 모르면 ''>",
                         "quote": "<이 수치가 나온 **원문 문장을 그대로** 옮긴다. 요약·바꿔쓰기 금지>" } ],
      "display": "<사람이 읽는 한 줄 (예: '2026년 추정 PER 48.6배'). 필수>" }
  ]
}
※ ★ number_facts 는 **최대 {MAX_FACTS}개**다. 리포트에 수치가 더 많아도 그 안에서 골라라 —
  25초 영상에 실을 수 있는 수치는 몇 개뿐이고, 고르는 일을 미루면 하류가 대신 못 한다.
  목표주가·투자의견·핵심 실적·밸류에이션처럼 **이 리포트의 주장을 지불하는 수치**를 우선한다.
  같은 수치를 표현만 바꿔 반복하지 마라(예: '영업이익 860억' 과 '860억원 영업이익').
※ 각 구체 수치는 number_facts 항목 하나로. value 는 숫자만(단위는 unit 에 분리). ★interpretation 은
  리포트가 명시적으로 규정했을 때만(PER 이 있다고 자동 risk 아님) — 근거 없으면 neutral.
※ ★ source_refs 의 quote 는 **원문에 있는 문장 그대로**여야 한다. 코드가 원문과 대조해서
  없는 인용은 버리고 경고를 남긴다(engine/report_evidence.py) — 지어내면 반드시 걸린다.
  원문 전문이 주어지지 않았으면 source_refs 를 빈 배열로 둬라. 요약을 인용문인 척 넣지 마라.
※ risks 는 **리포트가 실제로 말한 것만** 적는다. 리포트에 리스크 언급이 없으면 빈 배열로 둬라.
  ★ 예전에는 여기서 일반적 리스크를 지어내 넣으라고 시켰다 — 그건 환각을 명령한 것이었다."""

# ★ 개수 상한을 프롬프트 문자열에 박는다. f-string 을 쓰지 않는 이유는 위 프롬프트에 JSON
#   중괄호가 가득해서다 — 전부 이스케이프해야 하고, 한 번 어긋나면 조용히 깨진다.
FACTSHEET_SYSTEM = FACTSHEET_SYSTEM.replace("{MAX_FACTS}", str(config.FACTSHEET_MAX_NUMBER_FACTS))

_LIST_KEYS = ("what", "basis", "risks")
# number_facts 항목의 정규화 대상 필드(스칼라).
_NUMBER_FACT_SCALARS = ("unit", "period", "metric", "basis", "attribution", "interpretation")


def factsheet_user_prompt(report: dict[str, Any],
                          packet: dict[str, Any] | None = None) -> str:
    """추출 입력. packet 이 주어지고 전문이 있으면 <<FULL_SOURCE>> 구간을 덧붙인다(§4-2)."""
    lines = [
        f"종목/테마: {report.get('company') or report.get('theme') or '(미상)'}",
        f"제목: {report.get('title') or ''}",
        f"증권사: {report.get('broker') or '(미상)'}",
    ]
    if report.get("target_price"):
        lines.append(f"목표가: {report.get('target_price')}")
    if report.get("opinion"):
        lines.append(f"투자의견: {report.get('opinion')}")
    lines.append(f"요약: {report.get('summary') or ''}")
    block = report_source.fulltext_block(packet or {})
    if block:
        lines.append("")
        lines.append(block)
    return "\n".join(lines)


def _coerce_number(val: Any) -> float | None:
    """value 를 float 로. 숫자 아니면 None(수치 없는 사실도 허용)."""
    if isinstance(val, bool):  # bool 은 int 하위형 — 수치로 오인 방지
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _normalize_number_fact(item: Any, index: int) -> dict[str, Any]:
    """number_facts 항목 1개 → 구조화 dict. fact_id 는 결정론적(LLM 값 없으면 num_{index})."""
    if not isinstance(item, dict):
        # 레거시/방어: 문자열 등은 display 만 채운 최소 사실로.
        return {
            "fact_id": f"num_{index}", "value": None, "unit": "", "period": "", "metric": "",
            "scope": "company", "basis": "", "attribution": "", "interpretation": "neutral",
            "source_page": None, "display": str(item),
        }
    fid = str(item.get("fact_id") or "").strip() or f"num_{index}"
    out: dict[str, Any] = {"fact_id": fid, "value": _coerce_number(item.get("value"))}
    # v3 §5-1 — 비교 기준을 Fact Sheet 로 내린다. 지금까지는 지시서 헤더(explainer.number_claims)
    # 에만 있어서, 대본 단계에서는 "숫자를 비교 기준 없이 크게 내지 마라"를 검사할 수 없었다.
    comp = item.get("comparator") if isinstance(item.get("comparator"), dict) else {}
    out["comparator"] = {
        "basis": str((comp or {}).get("basis") or ""),
        "value": str((comp or {}).get("value") or ""),
    }
    # source_refs 는 여기서 형태만 보존하고, 원문 대조·정규화는 report_evidence 가 한다
    # (원문 청크가 필요해서 — 이 함수는 원문을 모른다).
    out["source_refs"] = item.get("source_refs") if isinstance(item.get("source_refs"), list) else []
    for k in _NUMBER_FACT_SCALARS:
        out[k] = str(item.get(k) or "")
    out["scope"] = str(item.get("scope") or "company")
    out["interpretation"] = str(item.get("interpretation") or "neutral")
    sp = item.get("source_page")
    out["source_page"] = int(sp) if isinstance(sp, (int, float)) and not isinstance(sp, bool) else None
    # display: LLM 값 우선, 없으면 metric/value/unit 로 합성, 그것도 없으면 fact_id.
    display = str(item.get("display") or "").strip()
    if not display:
        parts = [p for p in (out["metric"], _fmt_value(out["value"], out["unit"]), out["period"]) if p]
        display = " ".join(parts) or fid
    out["display"] = display
    return out


def _fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return ""
    num = f"{value:g}"
    return f"{num}{unit}" if unit else num


def _dedupe_fact_ids(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """fact_id 유일성 보장(참조 dangling 방지). 중복이면 접미 부여."""
    seen: dict[str, int] = {}
    for f in facts:
        fid = f["fact_id"]
        if fid in seen:
            seen[fid] += 1
            f["fact_id"] = f"{fid}_{seen[fid]}"
        else:
            seen[fid] = 0
    return facts


# 잘림 판정에 쓰는 필수 절. **키의 존재**를 본다 — 빈 배열은 "리포트에 없다"는 정보지만,
# 키 자체가 없으면 "잘려서 안 나왔다"는 뜻이라 의미가 정반대다.
_REQUIRED_SECTIONS = ("opinion", "basis", "risks")


def _require_complete(obj: dict[str, Any], salvaged: bool = False) -> None:
    """★ 살린 Fact Sheet 가 뒷절을 통째로 잃었으면 **실패시킨다**.

    number_facts 중간에서 잘리면 그 뒤 키들이 없는 채로 파싱된다. 그대로 두면
    normalize 가 risks 를 빈 배열로 채우고, 대본 프롬프트는 "risks 가 비면 리스크 씬을
    건너뛰라"는 규칙에 따라 **리스크 없는 금융 영상**을 만든다. 리포트에는 리스크가
    적혀 있는데도. 조용한 품질 저하가 아니라 시끄러운 실패여야 한다.
    (스키마에서 number_facts 를 맨 뒤로 옮겼으므로 정상 절단에서는 여기 걸리지 않는다.)
    """
    missing = [k for k in _REQUIRED_SECTIONS if k not in obj]
    if missing:
        # ★ 온전한 응답에도 **일부러** 건다. "빈 배열로 정규화하면 되지 않나"는 안 된다 —
        #   risks 키가 없는 것을 [] 로 채우면 "리포트가 리스크를 말하지 않았다"는 **없는 주장**을
        #   우리가 지어내는 것이고, 그대로 리스크 없는 금융 영상이 나간다(리뷰 지적에 대한 답).
        #   다만 처방이 정반대라 문구는 갈라 쓴다: 잘린 것이면 상한/원문 문제이고, 온전한데
        #   빠진 것이면 모델이 스키마를 어긴 것이라 재요청이 처방이다.
        why = ("잘린 Fact Sheet 에 필수 절이 없다 — 살려 쓰면 리스크 없는 영상이 나간다. "
               "상한을 올리거나 원문을 줄여야 한다"
               if salvaged else
               "온전한 응답인데 필수 절이 빠졌다 — 모델이 스키마를 어겼다. 빈 값으로 채우면 "
               "'리포트가 말하지 않았다'는 없는 주장이 되므로 채우지 않는다. 다시 요청해야 한다")
        raise JSONParseError(f"{why}: {', '.join(missing)}")
    # ★ 살린 시트만 추가로 본다. what/basis 가 길어 **첫 fact 안에서** 잘리면 살리기가
    #   risks 뒤까지 물러나 number_facts 자체가 없는 객체를 돌려줄 수 있다. 그러면 수치 0개로
    #   정규화되고, report_evidence.hard_blocks 는 빈 목록에 아무 차단도 걸지 않아 **숫자 근거가
    #   하나도 없는 초안**이 그대로 진행된다.
    #   ※ 온전한 응답에는 이 검사를 걸지 않는다 — 수치가 원래 없는 리포트(시황 메시지 등)가
    #     정상적으로 존재하기 때문이다. 잘린 경우에만 "못 받은 것"으로 본다.
    if salvaged and not obj.get("number_facts"):
        raise JSONParseError(
            "잘린 Fact Sheet 에 number_facts 가 하나도 없다 — 숫자 근거 없는 초안이 된다")


def _is_salvage_stub(fact: dict[str, Any]) -> bool:
    """살릴 때 남은 껍데기인가 — 값도 지표도 없고 display 가 fact_id 그대로인 것."""
    return (fact.get("value") is None
            and not fact.get("metric")
            and str(fact.get("display") or "") == fact.get("fact_id"))


_PURE_YEAR_RE = re.compile(r"^(\d{2,4})\s*년$")


def _canon_period(period: Any) -> str:
    """중복 판정 **전용** 기간 정규화 — 표기 별칭만 접고 **구분은 지킨다.**

    ★ report_evidence.normalize_period 를 쓰면 안 된다. 그 함수는 *근거 대조*용이라
      1H26·2H26 을 둘 다 '26' 으로, 2026.07·2026.12 를 둘 다 '2026' 으로 접는다.
      대조에는 그게 맞지만 **중복 판정에 쓰면 상·하반기 실적이 같은 값일 때 하나가
      근거째 사라진다**(실측으로 확인한 회귀). 여기서는 '2026년'과 '2026' 처럼
      같은 것을 다르게 쓴 경우만 접는다.
    """
    raw = str(period or "").strip().lower().replace(" ", "")
    m = _PURE_YEAR_RE.match(str(period or "").strip())
    return m.group(1) if m else raw


_NUM_PREFIX_RE = re.compile(r"^([+-]?[\d.]+)(.*)$")


def _canon_comp_value(value: Any) -> str:
    """비교값 표기 정규화 — '860억' 과 '860억원' 을 같은 것으로 본다.

    ★ 최상위 unit·period 는 정본으로 접는데 comparator.value 만 날문자열로 두면, 같은 비교를
      단위 표기만 바꿔 반복한 응답이 서로 다른 키가 되어 20개 상한을 잡아먹는다(리뷰 지적).
      숫자 접두부와 나머지를 갈라 뒷부분만 normalize_unit 에 태운다.
    """
    raw = str(value or "").strip().lower().replace(",", "").replace(" ", "")
    m = _NUM_PREFIX_RE.match(raw)
    if not m:
        return raw
    return m.group(1) + report_evidence.normalize_unit(m.group(2)).lower()


def _semantic_key(fact: dict[str, Any]) -> tuple:
    """같은 사실인지 판정하는 키. 표현(display)이 아니라 **의미 필드**로 본다 —
    '영업이익 860억' 과 '860억원 영업이익' 은 display 가 다르지만 같은 사실이다.

    ★ scope·basis·comparator 도 넣는다. 전사 실적 100억과 사업부 컨센서스 100억은 **다른 사실**이고,
      귀속·인용도 다르다. report_evidence.conflict_groups 도 같은 이유로 scope 를 구분한다.
    """
    comp = fact.get("comparator") if isinstance(fact.get("comparator"), dict) else {}
    # ★ 별칭을 정본으로 접고 비교한다. '억' 과 '억원', '2026년' 과 '2026F' 가 다른 키가 되면
    #   표현만 바꾼 반복이 그대로 살아남아 20개 상한을 잡아먹는다 — 프롬프트가 금지한 바로
    #   그 반복이다. report_evidence 가 이미 정본 형태를 정의해 뒀으니 그것을 쓴다.
    metric = str(fact.get("metric") or "").strip().lower()
    value = fact.get("value")
    scope = str(fact.get("scope") or "").strip().lower()
    base = (metric, value,
            report_evidence.normalize_unit(fact.get("unit")).lower(),
            _canon_period(fact.get("period")),
            scope,
            str(fact.get("basis") or "").strip().lower(),
            # ★ 비교 기준까지 본다. 같은 PER 19배라도 "컨센서스 대비"와 "전년 대비"는 다른
            #   주장이고 인용도 다르다. report_evidence.conflict_groups 도 comparator.basis 를
            #   유효 basis 로 취급한다 — 여기서만 무시하면 판정이 갈린다.
            str(comp.get("basis") or "").strip().lower(),
            _canon_comp_value(comp.get("value")))
    # ★★ 수치 식별력이 약하면 **서술까지 본다.**
    #   · metric 이 비고 값이 같은 두 사실(둘 다 10%)은 base 만으로 같아진다 — 서로 다른 비율인데도.
    #   · value 가 없는 서술형(계약 두 건)도 마찬가지다.
    #   · scope 가 company 가 아니면(segment·market) **주체를 담을 필드가 스키마에 없다** —
    #     사업부 A 매출 100억과 사업부 B 매출 100억이 base 만으로 같아진다(리뷰 지적).
    #   예전에는 이런 경우를 통째로 "중복 아님"으로 넘겼는데, 그러면 **똑같은 서술이 20개**
    #   들어와 상한을 채우고 뒤의 목표주가·실적을 밀어낸다. 서술이 다르면 남기고 같으면 지운다 —
    #   이게 두 문제를 동시에 푸는 유일한 지점이다.
    if not metric or value is None or (scope and scope != "company"):
        return base + (report_evidence._squash(str(fact.get("display") or "")).lower(),)
    return base + ("",)


def _usable_refs(fact: dict[str, Any], source_text: str = "") -> int:
    """이 사실이 가진 **쓸 만한** 인용 수.

    ★ 리스트가 비었는지만 보면 안 된다. 인용이 있긴 한데 너무 짧아 대조가 무의미한 경우
      (EVIDENCE_QUOTE_MIN_CHARS 미만)를 "근거 있음"으로 세면, 진짜 인용을 가진 뒤엣것을
      버리게 된다.
    ★★ 길이만 보면 **원문에 없는 긴 인용**이 "근거 있음"으로 통과한다. 그러면 지어낸 인용을
      가진 앞엣것 때문에 진짜 근거를 가진 뒤엣것이 버려지고, attach_evidence 가 나중에
      quote_not_in_source 로 편을 막는다 — 살릴 수 있었던 편이다(리뷰 지적).
      source_text 를 주면 **하류 게이트가 쓰는 바로 그 판정**(report_evidence.quote_found_in_source)
      으로 원문 대조까지 한다. 안 주면 종전대로 길이만 본다(원문을 못 구한 경로도 살아야 한다).
    ★★★ locate_chunk 를 쓰지 않는다. 그 함수는 청크 경계에 걸친 인용을 구제하려고 **앞머리
      8자만 맞아도** 청크 id 를 돌려준다 — 진짜 문장의 앞 8자를 베낀 지어낸 인용이 "근거 있음"
      으로 통과한다(리뷰 지적). 순위를 매기는 판정은 나중에 편을 막을 판정과 같아야 한다.
    """
    refs = fact.get("source_refs")
    if not isinstance(refs, list):
        return 0
    kept: list[str] = []
    for r in refs:
        if not isinstance(r, dict):
            continue
        quote = str(r.get("quote") or "").strip()
        if len(quote) < config.EVIDENCE_QUOTE_MIN_CHARS:
            continue
        if source_text and not report_evidence.quote_found_in_source(quote, source_text):
            continue
        kept.append(quote)
    if not kept:
        return 0
    # ★★★★ 인용이 원문에 있다고 끝이 아니다. **그 인용이 이 수치를 말하는가**까지 봐야 한다.
    #   원문의 진짜 문장이지만 다른 숫자를 말하는 인용을 "근거 있음"으로 세면, 정작 그 값을
    #   인용한 뒤엣것을 버리고 나중에 validate_fact 가 number_not_in_quote 로 편을 막는다
    #   (리뷰 지적). validate_fact 와 **같은 방식**으로 본다 — 인용들을 이어 붙여 대조한다.
    #   수치 없는 서술형 사실에는 걸지 않는다(대조할 값이 없다).
    if source_text and fact.get("value") is not None:
        if not report_evidence.value_supported_by_quote(fact["value"], " ".join(kept)):
            return 0
    return len(kept)


def _dedupe_semantic(facts: list[dict[str, Any]],
                     source_text: str = "") -> list[dict[str, Any]]:
    """의미가 같은 사실을 하나만 남긴다(먼저 나온 것 우선).

    ★ 개수 상한보다 **먼저** 돌아야 한다. 순서가 뒤바뀌면 중복 20개로 상한을 채우고
      정작 필요한 목표주가·실적이 잘려 나간다.
    ★ metric·value 가 둘 다 비면 판정 불가라 중복으로 보지 않는다(서술형 사실 보존).
    """
    at: dict[tuple, int] = {}          # 키 → out 안의 위치
    out: list[dict[str, Any]] = []
    dropped = 0
    for f in facts:
        # ★ 값이 없어도 이제 건너뛰지 않는다 — _semantic_key 가 서술까지 보므로 서로 다른
        #   서술은 다른 키가 되고, **글자 그대로 같은 반복만** 지워진다. 예전처럼 통째로
        #   넘기면 똑같은 서술 20개가 상한을 채워 뒤의 수치를 밀어낸다.
        key = _semantic_key(f)
        prev = at.get(key)
        if prev is None:
            at[key] = len(out)
            out.append(f)
            continue
        dropped += 1
        # ★ 먼저 온 것을 무조건 남기지 않는다. 앞엣것에 쓸 만한 인용이 없고 뒤엣것에 있으면,
        #   **유일하게 근거 있는 판본**을 버리는 셈이다. 더 잘 뒷받침된 쪽을 남긴다.
        if _usable_refs(out[prev], source_text) == 0 and _usable_refs(f, source_text) > 0:
            f["fact_id"] = out[prev]["fact_id"]      # 참조 dangling 방지
            out[prev] = f
    if dropped:
        log.info("number_facts 의미 중복 %d건 제거", dropped)
    return out


def normalize_factsheet(obj: dict[str, Any],
                        *, packet: dict[str, Any] | None = None) -> dict[str, Any]:
    """LLM 출력 정규화.

    number_facts 는 구조화 사실(fact_id + value + display …). numbers(문자열 리스트)는
    number_facts 의 display 에서 **파생**해 back-compat 유지(scriptgen/selfcheck/web/엣지트윈 불변).
    레거시로 number_facts 없이 numbers 문자열만 오면 그걸로 number_facts 를 합성한다.
    """
    out: dict[str, Any] = {}
    out["company"] = str(obj.get("company") or "")
    for k in _LIST_KEYS:
        val = obj.get(k, [])
        if isinstance(val, str):
            val = [val] if val else []
        out[k] = [str(x) for x in (val or [])]

    # number_facts: 구조화 우선, 없으면 레거시 numbers(문자열) 에서 합성.
    raw_facts = obj.get("number_facts")
    if not isinstance(raw_facts, list) or not raw_facts:
        legacy = obj.get("numbers", [])
        if isinstance(legacy, str):
            legacy = [legacy] if legacy else []
        raw_facts = list(legacy or [])
    facts = [_normalize_number_fact(item, i) for i, item in enumerate(raw_facts)]
    # ① 살리기 잔해 제거. 잘린 응답을 살리면 마지막에 `{"fact_id":"c"}` 같은 **쓸 수 없는
    #    껍데기**가 남을 수 있다(llm.salvage_json 실측). display 가 fact_id 로 폴백된 것뿐이라
    #    화면에 "c" 라는 사실이 나갈 수 있다 — 근거 없는 것은 애초에 들이지 않는다.
    facts = [f for f in facts if not _is_salvage_stub(f)]
    # ② 의미 중복 제거 **후에** 개수를 자른다. 앞에서부터 자르기만 하면, 같은 수치를 표현만
    #    바꿔 반복한 응답에서 앞 20개가 전부 같은 사실이 되고 뒤쪽의 목표주가·실적이 버려진다.
    #    _dedupe_fact_ids 는 id 중복만 개명할 뿐 의미 중복을 걸러 주지 않는다(리뷰 지적).
    # ★ 원문이 있으면 인용의 **실재 여부**까지 보고 고른다. 없으면 길이만 본다.
    source_text = str((packet or {}).get("text") or "")
    facts = _dedupe_semantic(facts, source_text)
    # ③ 프롬프트의 개수 지시를 코드가 다시 강제한다.
    if len(facts) > config.FACTSHEET_MAX_NUMBER_FACTS:
        log.warning("number_facts %d개 → 상한 %d개로 자른다", len(facts),
                    config.FACTSHEET_MAX_NUMBER_FACTS)
        kept, cut = (facts[:config.FACTSHEET_MAX_NUMBER_FACTS],
                     facts[config.FACTSHEET_MAX_NUMBER_FACTS:])
        # ★ 앞에서부터 자르는 원칙은 지킨다(모델이 중요한 것부터 쓰도록 프롬프트가 지시한다).
        #   단 **한 가지 경우만 예외다**: 남긴 20개에 쓸 만한 인용이 하나도 없는데 잘려 나갈
        #   쪽에는 있는 경우. 그대로 두면 attach_evidence 가 no_fact_has_source_ref 로 시트를
        #   통째로 막는다 — 근거가 있었는데 우리가 버려서 막히는 것이다(리뷰 지적).
        #   순서를 흔들지 않게 **맨 뒤 한 자리만** 인용 있는 첫 사실로 바꾼다.
        if kept and not any(_usable_refs(f, source_text) for f in kept):
            rescue = next((f for f in cut if _usable_refs(f, source_text)), None)
            if rescue is not None:
                log.warning("상한 안에 인용이 하나도 없어 %s 를 살려 넣는다",
                            rescue.get("fact_id"))
                kept[-1] = rescue
        facts = kept
    out["number_facts"] = _dedupe_fact_ids(facts)
    # numbers 는 display 에서 파생(기존 소비자 계약 유지: list[str]).
    out["numbers"] = [f["display"] for f in out["number_facts"]]

    out["opinion"] = str(obj.get("opinion") or "")
    # source 는 문자열 또는 dict(부착) 모두 허용 — build_source 가 이후 dict 로 덮는다.
    src = obj.get("source")
    if isinstance(src, dict):
        out["source"] = src
    else:
        out["source"] = str(src or "")
    return out


def extract(report: dict[str, Any], client: Any = None,
            *, packet_out: dict[str, Any] | None = None) -> dict[str, Any]:
    """리포트 → Fact Sheet. ★ 추출 직전에 원문을 확보해 프롬프트에 넣는다(저장하지 않음).

    확보 결과는 Fact Sheet 에 `source_depth` 로 남긴다 — 하류 게이트가 "요약만 보고 만든
    편"인지 판정할 수 있어야 한다(지시서 §4-3).

    packet_out: 확보한 원문 packet 을 호출자에게 넘긴다(집 관례인 out-param — overlay_out ·
      cut_map_out · board_qa_out 과 같은 모양). ★ 왜 반환값이 아니라 out-param 인가: 초안
      단계도 전문을 받아야 하는데(§4-2), 반환 서명을 튜플로 바꾸면 이 함수를 부르는 모든
      자리와 테스트가 함께 깨진다. 무엇보다 **초안이 원문을 다시 부르면 안 된다** — resolve 가
      보관본을 재사용하긴 하지만 그건 DB 왕복이고, 같은 편의 추출과 초안이 서로 다른 원문을
      볼 여지를 남긴다.
    """
    packet = report_source.resolve(report, client)
    if packet_out is not None:
        packet_out.clear()
        packet_out.update(packet)
    obj = call_json(
        model=config.MODEL_REPORT_FACTSHEET,
        system=FACTSHEET_SYSTEM,
        user=factsheet_user_prompt(report, packet),
        max_tokens=config.LLM_FACTSHEET_MAX_TOKENS,
        # ★ 잘려도 앞부분을 살린다. 리포트에 숫자가 1,194개 들어 있어 모델이 100개를 뽑다
        #   잘리더라도 우리가 쓰는 건 앞 20개뿐이고, 그 20개는 이미 온전히 들어와 있다.
        #   이 플래그가 없으면 아래 개수 상한이 **도달조차 못 한다**(절단이 파싱보다 먼저다).
        salvage_truncated=True,
    )
    _require_complete(obj, salvaged=bool(obj.pop(llm_mod.SALVAGED_MARK, False)))
    fact_sheet = normalize_factsheet(obj, packet=packet)
    fact_sheet["source_depth"] = packet["source_depth"]
    fact_sheet["source_chars"] = packet["char_count"]
    # v3 §5 — 수치마다 원문 인용을 붙이고 **코드가 원문과 대조**한다. 모델의 자기보고를 덮어쓴다.
    report_evidence.attach_evidence(fact_sheet, packet)
    return fact_sheet
