"""(c) 자기검증 (명세 5-3 + 수정명세 §14).

생성된 대본의 각 문장을 Fact Sheet 와 대조 → 근거 없는 문장 = 환각 의심으로 빨간 깃발.
※ 자기검증도 LLM 단계라 매핑이 틀릴 수 있다 → 빨간 깃발은 '사람 검수 보조'다(리뷰 3-3, 5-3).

v2(수정명세 §14): "Fact Sheet 항목과 비슷한가"만 보던 것을 다섯 축으로 나눈다 —
범위 확대(scope_match) · 인과 과장(causal_calibration) · 숫자 불일치(numeric_match) ·
수식어 보존(qualifier_preserved) · 편집적 추론(editorial_inference).
그 위에 커버리지와 승인 차단(approval_blocked)을 **코드가** 계산한다. 기존 `all_grounded`
재계산과 같은 원칙이다: 모델의 자기 판정은 입력일 뿐 결론이 아니다.
"""

from __future__ import annotations

import json
from typing import Any

from . import config, content_mode, factsheet
from .llm import call_json, set_text_purpose

SELFCHECK_SYSTEM = f"""너는 엄격한 사실 검증관이다. 입력: Fact Sheet(JSON) + 생성된 대본 씬들(JSON).
대본의 각 문장이 Fact Sheet의 항목으로 뒷받침되는지 판정한다.
Fact Sheet에 근거가 없는 문장은 grounded=false 로 표시하고 그 문장을 그대로 적는다.
보수적으로 판단하라: 근거가 모호하면 grounded=false.

Fact Sheet 에 claims(주장 원장)가 있으면 씬마다 아래를 **따로** 판정한다. "비슷하다"로 뭉뚱그리지 마라.
- matched_claim_ids: 이 씬을 실제로 뒷받침하는 claim_id 들. 원장에 있는 id 만 쓴다.
- scope_match: 씬이 말하는 대상·지역·기간의 범위가 Claim 의 범위를 넘지 않으면 true.
  ★일부 기업·일부 지역 결과를 "기업들은"·"전 세계"로 넓혔으면 false.
- causal_calibration: 씬의 인과 표현이 Claim 의 causal_strength 를 넘지 않으면 "pass".
  ★association_only 인 Claim 을 "때문에·유발한다·낮췄다"로 말했으면 "fail".
  인과 표현이 아예 없으면 "not_applicable".
- numeric_match: 씬의 숫자·단위·증감 방향이 Claim 과 일치하면 "pass", 어긋나면 "fail",
  숫자가 없으면 "not_applicable".
- qualifier_preserved: Claim 의 조건·단서(일부·평균적으로·특정 조건에서)가 씬에서 지워지지
  않았으면 true.
- editorial_inference: 논문이 지지하지 않는 새 해석·교훈·사회적 주장을 씬이 덧붙였으면 true.
  ★특히 마지막 결론 문장을 엄격히 보라("결국 사람의 비전이 중요하다" 같은 일반 철학으로의 확대).

■■ 아래 한 축만은 **사실이 아니라 문장**을 본다(운영자 지시 2026-09-10).
   이 대본은 **소리 내어 읽히는 나레이션**이다. 눈으로 읽어 말이 되는 것으로는 부족하고,
   귀로 들어서 걸리는 데가 없어야 한다. 사실 판정과 **섞지 마라** — 여기서 내용이 틀렸는지는
   보지 않는다.
- korean_natural: 그 씬의 나레이션이 한국어로 자연스러우면 true, 어색하면 false.
- awkward_spans: 어색한 **구절을 원문 그대로** 옮겨 적는다(문장 전체가 아니라 걸리는 부분).
- fluency_issues: 무엇이 어색한지 아래 표에서 고른다(여러 개 가능).
  "translationese" 번역투 — "~에 대한", "~를 통해", "~에 있어서", "가지고 있다",
                    불필요한 피동("~되어진다"), 영어 어순을 그대로 옮긴 긴 주어.
  "particle"        조사가 어색하다 — 은/는·이/가·을/를 자리가 틀렸거나 겹친다.
  "register_mix"    문어체와 구어체가 한 대본 안에서 섞인다("~한다" ↔ "~합니다").
  "long_modifier"   수식이 겹겹이 쌓여 한 호흡에 못 읽는다(관형절 3개 이상, 60자 넘는 한 문장).
  "reading"         소리 내 읽을 때 걸린다 — 숫자·단위·영어 약어가 어떻게 읽히는지 불분명
                    ("NAD+" 를 뭐라고 읽나, "92일" 이 "구십이 일"인가 "구십 이일"인가).
★ 보수적으로 판단하라. 취향 문제(더 멋진 표현이 있다)는 어색함이 아니다 —
  **읽다가 걸리는 것만** false 로 한다. 애매하면 true.

JSON only. 설명·마크다운·코드펜스 금지.
{{
  "scenes": [
    {{ "scene": <int>, "grounded": <bool>,
      "unsupported": ["<근거 없는 문장 원문>"],
      "matched_facts": ["<뒷받침하는 Fact Sheet 키>"],
      "matched_claim_ids": ["<뒷받침하는 claim_id>"],
      "scope_match": <bool>,
      "causal_calibration": "<{'|'.join(config.SELFCHECK_TRISTATE)}>",
      "numeric_match": "<{'|'.join(config.SELFCHECK_TRISTATE)}>",
      "qualifier_preserved": <bool>,
      "editorial_inference": <bool>,
      "korean_natural": <bool>,
      "awkward_spans": ["<어색한 구절 원문 그대로>"],
      "fluency_issues": ["<{'|'.join(config.SELFCHECK_FLUENCY_KINDS)} 중>"],
      "issues": ["<사람이 읽을 문제 요약 한 줄>"] }}
  ],
  "all_grounded": <bool>
}}"""

# 씬 단위 판정 축 → 경고 코드.
# ★ 이 축들은 **LLM 의 판단**이라 차단이 아니라 경고다(운영자 결정, 2026-07-27).
#   같은 이유로 리포트 라인의 컴플라이언스 하드차단이 제거된 전례가 있다(커밋 6a28761 —
#   "검토 결과는 참고용으로 보여주되 승인 흐름을 막지 않는다"). 자기검증 LLM 이 오판하면
#   정상 지시서도 승인이 막히는데, 그 비용이 놓친 오류의 비용보다 크다는 판단이다.
#   차단은 코드가 데이터로 확정하는 사유(길이·예산·존재하지 않는 claim_id·커버리지)만 한다.
_WARNING_SCENE_FLAGS: tuple[tuple[str, str], ...] = (
    ("scope_match", "scope_expanded"),
    ("qualifier_preserved", "qualifier_dropped"),
)


def selfcheck_user_prompt(fact_sheet: dict[str, Any], scenes: list[dict[str, Any]]) -> str:
    return (
        "Fact Sheet:\n" + json.dumps(fact_sheet, ensure_ascii=False, indent=2)
        + "\n\n대본 씬들:\n" + json.dumps(scenes, ensure_ascii=False, indent=2)
    )


def _tristate(value: Any) -> str:
    tok = str(value or "").strip().lower()
    return tok if tok in config.SELFCHECK_TRISTATE else "not_applicable"


def _str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v] if v else []
    if not isinstance(v, list):
        return []
    return [str(x) for x in v]


def normalize_selfcheck(
    obj: dict[str, Any],
    fact_sheet: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    total_sec: int | float | None = None,
) -> dict[str, Any]:
    """LLM 검증 출력 → 코드가 재계산한 판정.

    `fact_sheet`·`content_plan` 을 주면 Claim 대조와 커버리지·승인 차단까지 한다.
    안 주면 기존 동작(grounded/all_grounded)만 하고 차단하지 않는다 — 레거시 초안 보호.
    """
    known = factsheet.claim_ids(fact_sheet) if fact_sheet else ()
    scenes_in = obj.get("scenes") or []
    scenes: list[dict[str, Any]] = []
    any_unsupported = False
    block: list[str] = []
    warnings: list[str] = []

    for s in scenes_in:
        if not isinstance(s, dict):
            continue
        unsupported = _str_list(s.get("unsupported"))
        grounded = bool(s.get("grounded", not unsupported))
        if unsupported:
            grounded = False
            any_unsupported = True

        claim_ids = [c.strip() for c in _str_list(s.get("matched_claim_ids")) if c.strip()]
        dangling = [c for c in claim_ids if known and c not in known]
        claim_ids = [c for c in claim_ids if not known or c in known]

        scene_no = int(s.get("scene") or 0)
        row = {
            "scene": scene_no,
            "grounded": grounded,
            "unsupported": unsupported,
            "matched_facts": _str_list(s.get("matched_facts")),
            "matched_claim_ids": claim_ids,
            "scope_match": bool(s.get("scope_match", True)),
            "causal_calibration": _tristate(s.get("causal_calibration")),
            "numeric_match": _tristate(s.get("numeric_match")),
            "qualifier_preserved": bool(s.get("qualifier_preserved", True)),
            "editorial_inference": bool(s.get("editorial_inference", False)),
            # ★ 한국어 문장 축(2026-09-10). **사실 축과 섞지 않는다** — 이것은 승인에도
            #   커버리지에도 영향을 주지 않고, 오직 경고와 다듬기 되먹임에만 쓰인다.
            "korean_natural": bool(s.get("korean_natural", True)),
            "awkward_spans": _str_list(s.get("awkward_spans")),
            "fluency_issues": [k for k in _str_list(s.get("fluency_issues"))
                               if k in config.SELFCHECK_FLUENCY_KINDS],
            "issues": _str_list(s.get("issues")),
        }

        # 원장이 없으면(레거시) 이 축은 아예 돌지 않는다 — 과거 초안이 새 규칙에 걸리지 않는다.
        if known:
            # 차단: 원장에 없는 id 는 코드가 대조해서 확정한 사실이다.
            for cid in dangling:
                block.append(f"claim_id_invalid:{cid}#{scene_no}")
            # 경고: 아래는 전부 자기검증 LLM 의 판단이라 승인을 막지 않는다(위 상수 주석 참조).
            for field, reason in _WARNING_SCENE_FLAGS:
                if not row[field]:
                    warnings.append(f"{reason}#{scene_no}")
            if row["causal_calibration"] == "fail":
                warnings.append(f"causal_overreach#{scene_no}")
            if row["numeric_match"] == "fail":
                warnings.append(f"numeric_mismatch#{scene_no}")
            if row["editorial_inference"]:
                warnings.append(f"editorial_inference#{scene_no}")
        # ★ 문장 축은 `known`(주장 원장) 바깥에 둔다 — 원장이 없는 옛 초안도 한국어는
        #   똑같이 어색할 수 있고, 이 축은 승인·커버리지 어디에도 닿지 않는다.
        if not row["korean_natural"]:
            warnings.append(f"korean_awkward#{scene_no}")
        scenes.append(row)

    # 검증 결과는 matched_claim_ids 를 쓴다(대본이 주장한 claim_ids 가 아니라 실제로 뒷받침된 것).
    # 커버리지 계산기는 claim_ids 키를 보므로 여기서 키를 맞춰 넘긴다.
    coverage = content_mode.compute_evidence_coverage(
        [{"claim_ids": s["matched_claim_ids"], "evidence_role": ""} for s in scenes],
        required_claim_ids=_required_claims(content_plan),
        primary_claim_id=str((content_plan or {}).get("primary_claim_id") or ""),
    )

    if content_plan:
        if coverage["required_claim_ids"] and coverage["missing_claim_ids"]:
            block.append("missing_required_claims")
        if coverage["required_claim_ids"] and not coverage["primary_claim_covered"]:
            block.append("primary_claim_not_covered")
        block.extend(content_mode.block_reasons(content_plan, total_sec))
        warnings.extend(content_mode.duration_warnings(content_plan, total_sec))
        warnings.extend(str(w) for w in (content_plan.get("mode_warnings") or []))
    elif known:
        warnings.append("no_content_plan")
    if not known:
        warnings.append("legacy_no_claim_ledger")

    # all_grounded 는 실제 unsupported 유무로 재계산(LLM 자기보고 신뢰하지 않음)
    return {
        "scenes": scenes,
        "all_grounded": not any_unsupported,
        "coverage": coverage,
        "block_reasons": sorted(set(block)),
        "warnings": sorted(set(warnings)),
        "approval_blocked": bool(block),
    }


def _required_claims(content_plan: dict[str, Any] | None) -> tuple[str, ...]:
    """계획이 "반드시 전달한다"고 선언한 주장들 = 핵심 + 보조."""
    if not isinstance(content_plan, dict):
        return ()
    primary = str(content_plan.get("primary_claim_id") or "").strip()
    supporting = [str(c).strip() for c in (content_plan.get("supporting_claim_ids") or [])
                  if str(c).strip()]
    return tuple([c for c in [primary, *supporting] if c])


def check(
    fact_sheet: dict[str, Any],
    scenes: list[dict[str, Any]],
    content_plan: dict[str, Any] | None = None,
    total_sec: int | float | None = None,
) -> dict[str, Any]:
    set_text_purpose("selfcheck")     # 비용 원장의 용도 라벨(engine/llm.py)
    obj = call_json(
        model=config.MODEL_SELFCHECK,
        system=SELFCHECK_SYSTEM,
        user=selfcheck_user_prompt(fact_sheet, scenes),
        # 씬마다 5개 축이 추가돼 출력이 늘었다(3072 는 씬 8개에서 잘릴 수 있다).
        # ★ 한국어 축(korean_natural·awkward_spans·fluency_issues)이 씬마다 더 붙었고
        #   awkward_spans 는 원문 구절을 **그대로 옮겨 적으므로** 길어진다 → 6144.
        #   잘리면 파싱 실패 → 재시도 1회 → 하드 에러라 소프트 저하가 아니다.
        max_tokens=6144,
    )
    return normalize_selfcheck(obj, fact_sheet, content_plan, total_sec)
