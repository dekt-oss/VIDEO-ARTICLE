"""(a) Fact Sheet 추출 (명세 5-1).

논문 초록에서 "검증 가능한 사실"만 추출한다. 이후 대본 생성의 유일한 입력이 되므로
환각 방지의 1차 방어선이다. 추측·일반상식·초록에 없는 내용 금지.
"""

from __future__ import annotations

from typing import Any

from . import config
from .llm import call_json, set_text_purpose
from .util import log

FACTSHEET_SYSTEM = f"""너는 사실 검증관이다. **아래 주어진 자료 전체**에서 "검증 가능한 사실"만 추출한다.
원문 전문이 함께 주어지면 **초록이 아니라 원문을 근거로** 삼아라(초록은 요약일 뿐이다).
추측·일반상식·자료에 없는 내용 금지. 항목별로 근거가 없으면 빈 배열로 둔다.

★★ [원리(왜 그런가)를 반드시 찾아라] 이 저장소의 영상은 **원리를 설명하는 것**이 목적인데,
   Fact Sheet 가 결과·방법·수치만 뽑아 오면 대본에 원리가 없고 화면도 원리를 못 그린다.
   실측(2026-09-04): 세마글루타이드 논문 원문에 calorie restriction 41회·NAD 15회·
   IGF1 10회·sirtuin 5회가 있는데 **대본에는 0회**였다. 초록만 보라는 이 지시문 때문이었다.
   그래서 자료가 "왜/어떻게"를 말하면 반드시 claim 으로 남겨라:
     · 저자가 기전·경로·인과를 제시하면        claim_kind="mechanism"
     · 저자가 추정·해석으로 제시하면(증명 아님)  claim_kind="author_interpretation"
   ★ 없으면 지어내지 마라. 결과만 보고하는 논문은 그대로 두면 된다 — 코드가 그 사실을
     보고 영상 판형을 바꾼다. **없는 것을 만들어 내는 것이 훨씬 나쁘다.**
JSON only. 설명 문장·마크다운·코드펜스 금지.
{{
  "what_found": ["<핵심 발견들>"],
  "how": ["<방법 요약>"],
  "numbers": ["<구체 수치와 그 의미>"],
  "limitations": ["<한계·표본·조건>"],
  "claim_strength": "<저자 주장의 강도: 강/중/약 + 근거>",
  "claims": [
    {{ "claim_id": "<비우면 코드가 C01, C02 … 로 부여>",
       "claim_kind": "<{'|'.join(config.CLAIM_KINDS)}>",
       "claim_ko": "<이 주장 한 문장(한국어)>",
       "population": "<연구 대상. 없으면 null>",
       "sample_size": "<표본 수. 없으면 null>",
       "geography": "<지역. 없으면 null>",
       "study_period": "<분석 기간. 없으면 null>",
       "study_design": "<연구 설계. 없으면 null>",
       "treatment_or_exposure": "<개입·노출. 없으면 null>",
       "comparison": "<비교군. 없으면 null>",
       "outcome": "<결과 지표. 없으면 null>",
       "outcome_definition": "<결과 지표 정의. 없으면 null>",
       "effect_direction": "<{'|'.join(config.EFFECT_DIRECTIONS)}>",
       "effect_size": "<효과 크기. 없으면 null>",
       "effect_unit": "<효과 크기 단위. 없으면 null>",
       "uncertainty": "<신뢰구간·표준오차. 없으면 null>",
       "statistical_significance": "<유의성 서술. 없으면 null>",
       "causal_strength": "<{'|'.join(config.CAUSAL_STRENGTHS)}>",
       "source_section": "<abstract|body|table|figure>",
       "source_page": <정수. 없으면 null>,
       "table_or_figure": "<표/그림 번호. 없으면 null>",
       "source_quote": "<이 주장을 지지하는 원문 한 구절(검증용). 없으면 null>",
       "limitations": ["<이 주장에 붙는 한계>"],
       "evidence_grade": "<{'|'.join(config.EVIDENCE_GRADES)}>" }}
  ]
}}
※ claims 규칙(★환각 방지의 핵심):
- 찾지 못한 값은 **추정하지 말고 null**. 빈 문자열도 쓰지 마라. 없는 표본 수·기간·효과 크기를 지어내면 안 된다.
- 상관과 인과를 구조적으로 구분하라. 논문이 인과 설계를 쓰지 않았으면 causal_strength 는 association_only 이하다.
- evidence_grade: A 는 본문·표·그림과 효과 크기를 실제로 확인한 경우만. **초록만 주어졌으면 A 를 쓰지 마라**
  (초록의 포괄적 결론만 확인되면 C). B 는 초록에서 명확히 확인되는 결과.
- 효과 크기가 없으면 "얼마나"를 임의로 보충하지 마라.
- 각 claim 은 하나의 주장만 담는다. 여러 결과를 한 claim 에 몰아넣지 마라.
- **claims 는 최대 {config.FACTSHEET_MAX_CLAIMS}개다.** 영상 한 편이 지불할 수 있는 주장은 대여섯 개뿐이니,
  핵심 결과·범위·방법·크기·한계 순으로 중요한 것부터 담고 나머지는 버려라.
  많이 뽑는 것이 아니라 **고르는 것**이 이 단계의 일이다."""

_LIST_KEYS = ("what_found", "how", "numbers", "limitations")
# claim 항목 중 "논문에 없으면 null" 인 필드 — missing_fields 재계산의 기준(config 단일 출처).
_CLAIM_NULLABLE = config.CLAIM_NULLABLE_FIELDS
_SOURCE_SECTIONS = ("abstract", "body", "table", "figure")


def factsheet_user_prompt(title: str, venue: str | None, abstract: str,
                          packet: dict[str, Any] | None = None) -> str:
    """추출 입력. 원문을 확보했으면 **초록 뒤에 전문을 붙인다**(설명엔진 v2 §3).

    ★ 왜 필요한가: 지금까지 논문 라인은 초록만 보고 Fact Sheet 를 뽑았다. 초록은 "무엇을
      발견했다"만 담고 "왜·어떻게"는 본문에 있다. 그리고 더 중요한 것 — 초록만 있으면
      `source_quote` 를 대조할 대상이 없어 **주장의 진위를 코드가 판정할 수 없다.**

    ★ 원문이 없으면 마커도 붙이지 않는다. 빈 마커를 남기면 모델이 "원문을 받았다"고 오독한다
      (engine/paper_source.fulltext_block 과 같은 이유).
    """
    from . import paper_source  # noqa: PLC0415 — 순환 import 회피(paper_source 가 config 만 본다)

    base = f"제목: {title}\n게재처: {venue or '(미상)'}\n초록: {abstract}"
    block = paper_source.fulltext_block(packet or {})
    if not block:
        return base
    return (
        f"{base}\n\n{block}\n\n"
        "※ 원문을 함께 준다. 초록에 없는 방법·설계·한계는 원문에서 확인해 채워라.\n"
        "※ 다만 **각 claim 의 source_quote 에는 위 원문에 있는 구절을 그대로 옮겨라** —\n"
        "  코드가 원문과 문자열 대조해 검증하고, 없는 구절이면 그 주장은 폐기된다.\n"
        "  기억으로 쓰지 말고 눈앞의 원문에서 복사하라. 요약·의역한 인용은 대조에 실패한다."
    )


def _nullable(val: Any) -> Any:
    """빈 값·"null"·"없음" 류는 전부 None 으로. ★빈 문자열을 남기면 "확인됨"으로 오독된다."""
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "n/a", "na", "미상", "없음", "불명"):
        return None
    return s


def _enum(val: Any, allowed: tuple[str, ...], default: str) -> str:
    tok = str(val or "").strip().lower()
    return tok if tok in allowed else default


def _normalize_claim(item: Any, index: int) -> dict[str, Any]:
    """claims 항목 1개 → 구조화 dict.

    ★ 코드가 덮어쓰는 것(LLM 값 폐기):
    - `claim_id` — 비었으면 결정론적 C01, C02 …
    - `missing_fields` — 실제로 null 인 필드에서 재계산
    - `evidence_grade` — source_section 이 abstract 면 A 를 쓸 수 없다(§4-6)
    """
    src = item if isinstance(item, dict) else {}
    out: dict[str, Any] = {
        "claim_id": str(src.get("claim_id") or "").strip() or config.CLAIM_ID_FORMAT.format(index + 1),
        "claim_kind": _enum(src.get("claim_kind"), config.CLAIM_KINDS, config.DEFAULT_CLAIM_KIND),
        # 레거시·방어: 문자열이 그대로 오면 주장 문장으로만 받는다(나머지 필드는 null).
        "claim_ko": str(src.get("claim_ko") or "").strip() if isinstance(item, dict)
        else str(item or "").strip(),
    }

    for field in _CLAIM_NULLABLE:
        out[field] = _nullable(src.get(field))
    # source_page 만 정수형으로 좁힌다(표·그림 추적용).
    page = out.get("source_page")
    out["source_page"] = int(page) if isinstance(page, (int, float)) and not isinstance(page, bool) else None

    out["effect_direction"] = _enum(
        src.get("effect_direction"), config.EFFECT_DIRECTIONS, config.DEFAULT_EFFECT_DIRECTION)
    out["causal_strength"] = _enum(
        src.get("causal_strength"), config.CAUSAL_STRENGTHS, config.DEFAULT_CAUSAL_STRENGTH)
    out["source_section"] = _enum(src.get("source_section"), _SOURCE_SECTIONS, "abstract")

    lim = src.get("limitations", [])
    if isinstance(lim, str):
        lim = [lim] if lim.strip() else []
    out["limitations"] = [str(x).strip() for x in (lim or []) if str(x).strip()]

    grade = str(src.get("evidence_grade") or "").strip().upper()
    grade = grade if grade in config.EVIDENCE_GRADES else config.DEFAULT_EVIDENCE_GRADE
    # A 는 원문 본문을 실제로 읽은 경우만. 초록만이면 강등한다 — 근거 등급이 훅 강도를 좌우하므로
    # 여기서 새면 "C등급 수치에 단정형 훅" 게이트가 무력해진다.
    # EVIDENCE_GRADES 는 강한 순(A→D)이라 인덱스가 작을수록 강하다.
    ceiling = config.EVIDENCE_GRADES.index(config.ABSTRACT_ONLY_MAX_GRADE)
    if out["source_section"] == "abstract" and config.EVIDENCE_GRADES.index(grade) < ceiling:
        grade = config.ABSTRACT_ONLY_MAX_GRADE
    out["evidence_grade"] = grade

    out["missing_fields"] = [f for f in _CLAIM_NULLABLE if out.get(f) is None]
    return out


def _dedupe_claim_ids(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """claim_id 유일성 보장 — 중복이면 대본·지시서 참조가 어느 주장인지 알 수 없어진다."""
    seen: dict[str, int] = {}
    for c in claims:
        cid = c["claim_id"]
        if cid in seen:
            seen[cid] += 1
            c["claim_id"] = f"{cid}_{seen[cid]}"
        else:
            seen[cid] = 0
    return claims


def claim_ids(fact_sheet: dict[str, Any] | None) -> tuple[str, ...]:
    """원장에 실제로 존재하는 claim_id 들. 다운스트림의 dangling 참조 검사 기준."""
    claims = (fact_sheet or {}).get("claims")
    if not isinstance(claims, list):
        return ()
    return tuple(str(c.get("claim_id")) for c in claims
                 if isinstance(c, dict) and c.get("claim_id"))


def primary_claim_candidates(fact_sheet: dict[str, Any] | None) -> tuple[str, ...]:
    """핵심 결과(main_result) 주장들. 2개 이상이면 시리즈 분할 신호(§6-2)."""
    claims = (fact_sheet or {}).get("claims")
    if not isinstance(claims, list):
        return ()
    return tuple(str(c.get("claim_id")) for c in claims
                 if isinstance(c, dict) and c.get("claim_kind") == "main_result" and c.get("claim_id"))


def normalize_factsheet(obj: dict[str, Any]) -> dict[str, Any]:
    """LLM 출력 정규화: 리스트 항목은 문자열 리스트로, claim_strength 는 문자열.

    `claims`(Claim Ledger)는 기존 5키 **위에 병렬 추가**한다 — 기존 키를 대체하지 않으므로
    원장 없는 과거 초안도 그대로 동작한다(report_factsheet.number_facts 와 같은 패턴).
    """
    out: dict[str, Any] = {}
    for k in _LIST_KEYS:
        val = obj.get(k, [])
        if isinstance(val, str):
            val = [val] if val else []
        out[k] = [str(x) for x in (val or [])]
    out["claim_strength"] = str(obj.get("claim_strength") or "")

    raw_claims = obj.get("claims")
    claims = [_normalize_claim(c, i) for i, c in enumerate(raw_claims)] \
        if isinstance(raw_claims, list) else []
    # ★ 코드가 개수를 자른다(2026-08-29). 프롬프트로 "최대 N개"라고 말만 하면 지켜지지 않고,
    #   그러면 출력이 상한에서 잘려 **JSON 파싱 자체가 실패**한다(원문 34,835자 논문에서 실측).
    #   리포트 라인이 같은 자리에서 배운 답이다 — 상한을 올리지 말고 계약을 묶는다.
    #   앞에서부터 남긴다: 프롬프트가 "중요한 것부터"라고 지시했고, 뒤쪽은 부차적 주장이다.
    if len(claims) > config.FACTSHEET_MAX_CLAIMS:
        log.info("claims %d개 → 상한 %d개로 자른다", len(claims), config.FACTSHEET_MAX_CLAIMS)
        claims = claims[:config.FACTSHEET_MAX_CLAIMS]
    out["claims"] = _dedupe_claim_ids(claims)

    # 출처 블록은 메타데이터라 이후 단계(draft.generate_draft)에서 부착·보존한다.
    if isinstance(obj.get("source"), dict):
        out["source"] = obj["source"]
    return out


def extract(title: str, venue: str | None, abstract: str,
            packet: dict[str, Any] | None = None) -> dict[str, Any]:
    """논문 → Fact Sheet. packet 이 있으면 원문 전문을 함께 준다.

    ★ 원문을 주면 claim 이 늘고 source_quote 가 붙어 출력이 눈에 띄게 커진다. 기본 상한
      그대로 두면 잘려서 JSON 파싱이 실패한다 — 리포트 라인이 2026-08-03 에 정확히 그
      자리에서 죽었고(config.LLM_FACTSHEET_MAX_TOKENS 주석) 그때 올려 둔 상한을 재사용한다.
      상수를 새로 만들지 않는다: 같은 문제에 두 개의 노브가 생기면 한쪽만 조정되는 날이 온다.
    """
    set_text_purpose("factsheet")     # 비용 원장의 용도 라벨(engine/llm.py)
    obj = call_json(
        model=config.MODEL_FACTSHEET,
        system=FACTSHEET_SYSTEM,
        user=factsheet_user_prompt(title, venue, abstract, packet),
        # ★★ **조건을 뗀다**(2026-09-22 실측). 예전엔 원문이 있을 때만 이 상한을 썼고
        #   없으면 `None` → 기본 8,192 로 떨어졌다. 그런데 출력 크기를 정하는 것은 **입력에
        #   원문이 있느냐**가 아니라 **모델이 얼마나 길게 쓰느냐**다.
        #   실측: 같은 초록만 주고 뽑은 Fact Sheet 가 gemini-2.5-flash 는 최대 5,291 토큰인데
        #   deepseek-flash 는 **8,192 에서 정확히 잘렸다**(3회 중 1회). 그걸 보고 "deepseek-flash
        #   가 claim_id 를 빠뜨린다"고 판정했는데, 빠뜨린 게 아니라 **말을 하다 끊긴** 것이었다.
        #   공급자를 우리 천장으로 떨어뜨려 놓고 그 모델이 못한다고 적으면 측정이 거짓말을 한다.
        #   상한은 안전장치이지 비용 조절 수단이 아니다 — 출력은 쓴 만큼만 과금된다.
        max_tokens=config.LLM_FACTSHEET_MAX_TOKENS,
    )
    return normalize_factsheet(obj)
