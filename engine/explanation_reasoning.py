"""Explanation Engine v2 Phase 3 — "생각하는 단계" (작업지시서 §5, 2026-10-05 재구현).

★ 왜 다시 만드나(2026-10-05 전체 재검토). 작업지시서는 Phase 3 을 "이번 프로젝트의 가장 중요한 단계",
  "대본을 만들기 전에 독립 실행하는 **생각하는 단계**"로 정했다. 시청자의 질문, 관심 이유, 시청자가 보통 아는 것,
  놀라운 반전, 단계별 질문과 답, 화면에 꼭 보여 줄 것, 이야기 틀을 콘텐츠마다 짜는 자리다(§5.1~5.3).
  종전 구현(`paper_reasoning_adapter`·`report_reasoning_adapter`)은 Fact Sheet 주장에 역할 이름표만 붙였고
  핵심 질문은 모든 논문에 같은 문장이었다 — 생각이 없었다. 그 결과 V2 대본이 작업지시서가 **금지**한
  "연구 소개 → 방법 → 숫자 → 숫자 → 한계" 나열이 됐다(신피질·조화 음파 실측).

★ 여기서는 모델이 생각하고 코드는 **근거 연결만** 본다(§20 "Source가 얕은데 LLM으로 내용 채우기" 금지):
  - 단계·의미·한계마다 근거 묶음(Evidence Pack)의 id 를 하나 이상 가리킨다(없는 id 금지).
  - 답에 나오는 숫자는 그 단계가 가리킨 근거에 있는 숫자여야 한다.
  - 단계 수는 원문 깊이(source_mode)가 정한 범위 안(§3 Source Adequacy).
  - 선행 개념은 원문에 설명이 있으면 그 근거를, 없으면 `glossary_needed` 로 표시한다(§6 — 일반상식을 근거처럼 쓰지 않는다).
  문장을 원문 그대로 쓰라고 강제하지 않는다 — 쉬운 말로 다시 말하는 것이 이 단계의 일이다.

★ 지금은 **미리보기 전용**이다(`scripts/explanation_think.py`). 운영자가 세 편의 생각 결과를 보고 "원한 설명 흐름"인지
  판정한 뒤에만 대본(Phase 5·6)을 이 결과로 다시 잇는다. 그 전에는 파이프라인에 연결하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from . import config, spoken_numbers
from .llm import call_json, set_text_purpose

CONTRACT_VERSION = "explanation-reasoning-v1"

PATTERNS: dict[str, dict[str, str]] = {
    "paper": {
        "WHY": "현상 → 왜? → 기존 설명 → 새 결과 → 원리 → 의미",
        "EXPERIMENT": "질문 → 어떻게 확인? → 결과 → 왜? → 한계",
        "TRADE_OFF": "장점 → 그런데 비용 → 왜 둘이 같이 생김? → 기능적 의미",
    },
    "report": {
        "DRIVER_CHAIN": "산업 변화 → 공급/수요 → 가격 → 매출/이익",
        "BOTTLENECK": "수요 증가 → 병목 → 공급 제약 → 가격/수주",
        "VALUATION": "실적 가정 → BPS/EPS/FCF → 배수 → 목표가",
        "CONTRARIAN": "시장 우려 → 리포트 반론 → 근거 → 깨지는 조건",
    },
}
STEP_KINDS = ("observation", "measurement", "interpretation", "author_interpretation", "hypothesis",
              "fact", "company_guidance", "analyst_estimate", "forecast", "scenario")
#: 모델이 한국어로 적은 종류(실측: "사실"·"전망"·"저자 해석") → 같은 뜻의 영문 종류.
_KIND_KO = {"관찰": "observation", "측정": "measurement", "해석": "interpretation", "저자 해석": "author_interpretation",
            "가설": "hypothesis", "사실": "fact", "회사 가이던스": "company_guidance", "가이던스": "company_guidance",
            "애널리스트 추정": "analyst_estimate", "추정": "analyst_estimate", "전망": "forecast", "시나리오": "scenario"}


def step_kind(value: Any) -> str:
    """종류 표기 → 표준 종류. "observation_and_interpretation" 처럼 둘을 이은 것은 해석 쪽으로 본다."""
    text = _text(value)
    kind = _KIND_KO.get(text, text.lower())
    if kind in STEP_KINDS:
        return kind
    return "interpretation" if "interpretation" in kind else ""
#: 원문 깊이 → 설명 단계 수 범위(작업지시서 §3 "설명 단위의 수와 깊이를 제한한다").
STEP_RANGE_BY_MODE: dict[str, tuple[int, int]] = {
    "FULL_EXPLAINER": (3, 6), "SOURCE_EXPLAINER": (3, 5),
    "BRIEF_EXPLAINER": (2, 3), "SUMMARY_ONLY": (1, 2),
}

_QUESTIONS = {
    "paper": """연구가 해결하려는 질문은 무엇인가? 기존에는 무엇을 알고 있었는가? 이번 연구에서 무엇이 달라졌는가?
시청자가 이해하려면 어떤 개념을 먼저 알아야 하는가? 실험/관찰은 무엇을 비교했는가? 핵심 결과는 무엇인가?
왜 이런 결과가 나왔는가? 논문이 실제 원리(mechanism)를 제공하는가? 어디까지가 관찰이고 어디부터 저자 해석인가?
어디까지 일반화할 수 있는가?""",
    "report": """애널리스트의 핵심 주장(thesis)은 무엇인가? 시장이 흔히 보는 반대 시각은 무엇인가? 실적/산업 변화의 동인은?
동인 → 매출 → 이익 연결은? 밸류에이션은 어떻게 이어지는가? 무엇이 사실이고 무엇이 전망인가?
어떤 가정이 깨지면 주장이 무너지는가? 질문이 둘 이상이면(예: '왜 사이클이 길다고 보나' vs '왜 목표가가 63만원인가')
하나만 이 편의 질문으로 고르고 나머지는 의미(payoff)나 뺀 것(excluded)으로 보낸다.""",
}

SYSTEM_PROMPT = """너는 과학 논문·증권 리포트를 일반 시청자에게 **이해시키는** 짧은 설명 영상의 기획자다.
대본을 쓰지 말고, 대본을 쓰기 전에 **설명의 논리**를 설계하라. 목표는 "내용은 전문적인데, 영상을 따라가다 보니
원리까지 이해됐다"이다. 요약 나열("연구 소개 → 방법 → 숫자 → 숫자 → 한계")은 실패다.

근거 규칙(어기면 코드가 오류로 표시한다):
- 사실은 입력의 근거(evidence_id)에서만 가져온다. 단계·의미·한계마다 evidence_ids 를 하나 이상 단다.
- 답에 숫자를 쓰면 그 숫자가 그 단계가 가리킨 근거에 있어야 한다. 없는 숫자를 만들지 마라.
- 근거에 없는 원리를 만들지 마라. 원리가 원문에 없으면 "원문은 원리를 직접 보이지 않았다"고 적는다.
- 관찰·측정과 저자 해석·가설을 구분해 kind 에 적는다. 리포트는 사실·회사 가이던스·애널리스트 추정·전망·시나리오를 구분한다.
- 선행 개념의 쉬운 설명이 원문 근거에 있으면 basis="source"+evidence_ids, 없으면 basis="glossary_needed"(설명은 짧게 쓰되
  사실 근거로 쓰지 않는다).
- 단계와 의미(payoff)마다 verification_state 가 SUPPORTED 인 근거를 **최소 하나** 단다. 그 밖의 근거는 보조로만 쓴다.

설계 규칙:
- core_question 은 **이 편만의** 질문 한 문장, **40자 안팎**(말로 한 번에 들리게). 시청자가 "정말?" 하고 따라오게.
  "이 연구는 무엇을 보여 주는가?" 같은 범용 질문 금지.
- viewer_reason_to_care: 시청자 삶·관심과 닿는 한 문장.
- starting_assumption: 시청자가 보통 그렇게 알고 있는 것(근거·상식으로 무리 없는 것). 지어낸 오해 금지 — 없으면 빈 문자열.
- surprising_conflict: 이 연구/리포트가 그 가정과 어긋나는 지점. 없으면 빈 문자열.
- story_pattern 은 주어진 후보 중 하나, 이유를 한 줄로.
- explanation_steps 는 시청자 순서다(원문 순서가 아니다). **핵심 결과를 예비·보조 결과보다 앞에** 둔다.
- answer 는 쉬운 말로. 숫자는 이해에 꼭 필요한 대표 숫자 한두 개만(통계값 p·±오차 등은 넣지 마라 — 화면 카드가 맡는다). 각 단계는 시청자가 품을 **질문 하나**와 그 **답**,
  앞 단계와의 관계(relation_to_previous: question_answer|cause_effect|whole_detail|phenomenon_data|contrast|process_next|micro_whole),
  그리고 must_visualize(이 단계에서 화면이 꼭 보여 줄 물체·변화 — 구체적인 사물로).
- 단계 수는 step_range 안. 원문이 얕으면 적게, 깊이를 억지로 늘리지 마라.
- excluded_details: 흥미롭지만 이 편에서 뺄 것과 이유(길이·초점).

JSON only:
{"core_question":"","viewer_reason_to_care":"","starting_assumption":"","surprising_conflict":"",
 "story_pattern":"","story_pattern_reason":"",
 "prerequisite_concepts":[{"concept":"","simple_explanation":"","basis":"source|glossary_needed","evidence_ids":[]}],
 "explanation_steps":[{"step_id":"S1","question":"","answer":"","relation_to_previous":"","kind":"","uncertainty":"",
   "evidence_ids":[],"must_visualize":""}],
 "payoff":{"text":"","evidence_ids":[]},
 "limitations":[{"text":"","evidence_ids":[]}],
 "excluded_details":[{"what":"","why":""}],
 "target_complexity":"brief|standard|deep"}
"""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def evidence_index(pack: dict[str, Any], financial_reasoning: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """모델이 가리킬 수 있는 근거 전부 — id → {text, section, state}."""
    out: dict[str, dict[str, Any]] = {}
    for section in ("claims", "limitations", "risks", "background_context"):
        for item in pack.get(section) or []:
            if isinstance(item, dict) and _text(item.get("evidence_id")) and _text(item.get("text")):
                out[item["evidence_id"]] = {
                    "section": section, "text": _text(item["text"]),
                    "type": _text(item.get("claim_type") or item.get("role")),
                    "state": _text(item.get("verification_state")),
                }
    for item in pack.get("numbers") or []:
        if isinstance(item, dict) and _text(item.get("evidence_id")) and _text(item.get("display")):
            out[item["evidence_id"]] = {"section": "numbers", "text": _text(item["display"]),
                                        "type": "number", "state": _text(item.get("verification_state"))}
    # ★ 증권사 논리 단계는 근거 묶음(evidence_pack)이 원문 인용으로 확인한 것만 claims 로 들어온다 — 여기서 따로
    #   더하지 않는다. 설명 설계(explanation_ir)가 보는 근거와 **같은 한 벌**이어야 단계가 근거를 잃지 않는다.
    return out


def prompt_payload(pack: dict[str, Any], *, title: str = "",
                   financial_reasoning: dict[str, Any] | None = None,
                   report_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    domain = pack.get("domain")
    source = pack.get("source") or {}
    mode = _text(source.get("source_mode")) or "SOURCE_EXPLAINER"
    lo, hi = STEP_RANGE_BY_MODE.get(mode, (2, 4))
    index = evidence_index(pack, financial_reasoning)
    return {
        "domain": domain,
        "title": title or _text((source.get("attribution") or {}).get("title")),
        "report": {k: (report_meta or {}).get(k) for k in ("broker", "company", "title", "opinion", "target_price")}
        if domain == "report" else None,
        "source_depth": source.get("source_depth"), "source_mode": mode,
        "step_range": [lo, hi],
        "questions_to_answer": _QUESTIONS.get(domain, ""),
        "story_pattern_candidates": PATTERNS.get(domain, {}),
        "evidence": [{"evidence_id": eid, **row} for eid, row in index.items()],
    }


def _numbers_in(texts: list[str]) -> list[str]:
    return [n for text in texts for n in spoken_numbers.value_tokens(text)]


def validate(result: dict[str, Any], pack: dict[str, Any],
             financial_reasoning: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """근거 연결 검사 — 오류(errors)와 참고(warnings). 문장 표현은 검사하지 않는다."""
    index = evidence_index(pack, financial_reasoning)
    domain = pack.get("domain")
    errors: list[str] = []
    warnings: list[str] = []
    core = _text(result.get("core_question"))
    if not core.endswith(("?", "？")):
        errors.append("core_question_not_a_question")
    if len(core) > 45:
        warnings.append(f"core_question_long:{len(core)}")
    if core.replace(" ", "") in {"이연구는무엇을보여주는가?", "왜이증권사는이런전망을하는가?"}:
        errors.append("core_question_generic")
    if _text(result.get("story_pattern")) not in PATTERNS.get(domain, {}):
        errors.append(f"story_pattern_invalid:{result.get('story_pattern')}")
    steps = [s for s in result.get("explanation_steps") or [] if isinstance(s, dict)]
    mode = _text((pack.get("source") or {}).get("source_mode")) or "SOURCE_EXPLAINER"
    lo, hi = STEP_RANGE_BY_MODE.get(mode, (2, 4))
    if not lo <= len(steps) <= hi:
        errors.append(f"step_count_out_of_range:{len(steps)}not_in_{lo}-{hi}")

    def check_refs(label: str, ids: list[str], text: str) -> None:
        if not ids:
            errors.append(f"no_evidence:{label}")
            return
        unknown = [i for i in ids if i not in index]
        if unknown:
            errors.append(f"unknown_evidence:{label}:{unknown[0]}")
        cited = [index[i]["text"] for i in ids if i in index]
        if label != "limitation" and not label.startswith("limitation") and cited and not any(
                index[i]["state"] == "SUPPORTED" for i in ids if i in index):
            errors.append(f"no_supported_evidence:{label}")
        extra = spoken_numbers.multiset_minus(spoken_numbers.value_tokens(text), _numbers_in(cited))
        if extra:
            errors.append(f"number_not_in_cited_evidence:{label}:{extra[0]}")
        if label.startswith("limitation") and cited and all(
                index[i]["state"] != "SUPPORTED" for i in ids if i in index):
            warnings.append(f"only_unverified_evidence:{label}")

    for step in steps:
        sid = _text(step.get("step_id")) or "?"
        check_refs(sid, _strings(step.get("evidence_ids")), _text(step.get("answer")))
        if not step_kind(step.get("kind")):
            warnings.append(f"step_kind_unknown:{sid}:{step.get('kind')}")
        if not _text(step.get("must_visualize")):
            warnings.append(f"must_visualize_empty:{sid}")
    payoff = result.get("payoff") if isinstance(result.get("payoff"), dict) else {}
    check_refs("payoff", _strings(payoff.get("evidence_ids")), _text(payoff.get("text")))
    for n, lim in enumerate(result.get("limitations") or [], 1):
        if isinstance(lim, dict):
            check_refs(f"limitation{n}", _strings(lim.get("evidence_ids")), _text(lim.get("text")))
    for concept in result.get("prerequisite_concepts") or []:
        if isinstance(concept, dict) and concept.get("basis") == "source":
            ids = _strings(concept.get("evidence_ids"))
            if not ids or any(i not in index for i in ids):
                errors.append(f"prerequisite_source_unlinked:{concept.get('concept')}")
        elif isinstance(concept, dict):
            warnings.append(f"glossary_needed:{concept.get('concept')}")
    return {"errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def think(pack: dict[str, Any], *, title: str = "", financial_reasoning: dict[str, Any] | None = None,
          report_meta: dict[str, Any] | None = None, model: str | None = None,
          caller: Any = None) -> dict[str, Any]:
    """모델 1회 호출 → 생각 결과 + 근거 연결 검사. 저장하지 않는다(비용 장부만 남는다)."""
    payload = prompt_payload(pack, title=title, financial_reasoning=financial_reasoning, report_meta=report_meta)
    set_text_purpose("explanation_reasoning_preview")
    raw = (caller or call_json)(model=model or config.MODEL_EXPLANATION_REASONING, system=SYSTEM_PROMPT,
                    user=json.dumps(payload, ensure_ascii=False),
                    # 추론형 모델은 답 전에 긴 생각을 쓴다 — 지시서와 같은 상한(절단 방지, 쓴 만큼만 과금).
                    max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS)
    result = raw if isinstance(raw, dict) else {}
    return {"contract_version": CONTRACT_VERSION, "model": model or config.MODEL_EXPLANATION_REASONING,
            "domain": pack.get("domain"), "content_id": pack.get("content_id"),
            "source": pack.get("source"), "reasoning": result,
            "qa": validate(result, pack, financial_reasoning)}


_REL_KO = {"question_answer": "질문→답", "cause_effect": "원인→결과", "whole_detail": "전체→부분",
           "phenomenon_data": "현상→데이터", "contrast": "대비", "process_next": "다음 과정", "micro_whole": "부분→전체"}


def markdown(out: dict[str, Any], *, title: str = "", evidence: dict[str, dict[str, Any]] | None = None) -> str:
    """사람이 읽는 생각 결과. 근거 id 옆에 근거 문장을 짧게 붙여 대조할 수 있게 한다."""
    r = out.get("reasoning") or {}
    ev = evidence or {}

    def refs(ids: Any) -> str:
        return "; ".join(f"`{i}` {ev.get(i, {}).get('text', '(없는 근거)')[:60]}" for i in _strings(ids)) or "(근거 없음)"

    lines = [f"# 생각 결과 — {title or out.get('content_id')}", "",
             f"- 모델: {out.get('model')} · 원문 깊이: {(out.get('source') or {}).get('source_depth')} / "
             f"{(out.get('source') or {}).get('source_mode')}", "",
             "## 이 편의 질문", f"**{r.get('core_question', '')}**", "",
             f"- 왜 관심을 가져야 하나: {r.get('viewer_reason_to_care', '')}",
             f"- 시청자가 보통 아는 것: {r.get('starting_assumption') or '(없음)'}",
             f"- 반전: {r.get('surprising_conflict') or '(없음)'}",
             f"- 이야기 틀: **{r.get('story_pattern', '')}** — {r.get('story_pattern_reason', '')}", ""]
    if r.get("prerequisite_concepts"):
        lines.append("## 먼저 풀어 줄 개념")
        for c in r["prerequisite_concepts"]:
            basis = "원문 근거" if c.get("basis") == "source" else "⚠ 원문에 설명 없음(용어집 필요)"
            lines.append(f"- **{c.get('concept')}** — {c.get('simple_explanation')} ({basis})")
        lines.append("")
    lines.append("## 설명 단계 (시청자 순서)")
    for s in r.get("explanation_steps") or []:
        rel = _REL_KO.get(_text(s.get("relation_to_previous")), s.get("relation_to_previous") or "")
        lines += [f"### {s.get('step_id')} · {rel} · {s.get('kind')}",
                  f"- 질문: {s.get('question')}", f"- 답: {s.get('answer')}",
                  f"- 화면: {s.get('must_visualize')}"]
        if _text(s.get("uncertainty")):
            lines.append(f"- 불확실성: {s.get('uncertainty')}")
        lines += [f"- 근거: {refs(s.get('evidence_ids'))}", ""]
    payoff = r.get("payoff") or {}
    lines += ["## 그래서 (의미)", f"{payoff.get('text', '')}", f"- 근거: {refs(payoff.get('evidence_ids'))}", ""]
    if r.get("limitations"):
        lines.append("## 한계")
        lines += [f"- {lim.get('text')} — 근거: {refs(lim.get('evidence_ids'))}" for lim in r["limitations"]]
        lines.append("")
    if r.get("excluded_details"):
        lines.append("## 이 편에서 뺀 것")
        lines += [f"- {x.get('what')} — {x.get('why')}" for x in r["excluded_details"]]
        lines.append("")
    qa = out.get("qa") or {}
    lines += ["## 코드 검사(근거 연결만)", f"- 오류: {', '.join(qa.get('errors') or []) or '없음'}",
              f"- 참고: {', '.join(qa.get('warnings') or []) or '없음'}"]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# 생각 결과 → 기존 설명 설계(explanation-ir-v1) 후보. Phase 4~10 은 이 IR 을 그대로 소비한다.
# ─────────────────────────────────────────────────────────────
_INTERPRETIVE_KINDS = frozenset({"interpretation", "author_interpretation", "hypothesis"})
_NO_UNCERTAINTY = {"", "없음", "none", "n/a", "-"}


def _role_for(step: dict[str, Any]) -> str:
    kind = step_kind(step.get("kind"))
    if kind in _INTERPRETIVE_KINDS:
        return "mechanism"
    if _text(step.get("relation_to_previous")) == "cause_effect":
        return "cause"
    return "result"


def _attribution(ids: list[str], index: dict[str, dict[str, Any]]) -> tuple[list[str], str]:
    """리포트 근거는 귀속(증권사·출처)이 하나여야 한다 — 첫 귀속과 다른 근거는 이 단계에서 뺀다."""
    first = next((_text(index[i].get("attribution")) for i in ids
                  if i in index and _text(index[i].get("attribution"))), "")
    if not first:
        return ids, ""
    return [i for i in ids if i in index and _text(index[i].get("attribution")) in {"", first}], first


def to_ir_candidate(reasoning: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """생각 결과 → `explanation_ir.normalize` 후보. 순서: 원문 근거가 있는 선행 개념 → 설명 단계 → 의미 → 한계.

    문장(text)은 모델이 쉬운 말로 쓴 답이다 — 원문 복사가 아니다. 근거 id·검증 상태 필터·원문 위치는
    `explanation_ir.normalize` 가 종전대로 강제한다(검증 안 된 근거만 단 단계는 거기서 빠진다).
    """
    from . import explanation_ir

    index = explanation_ir.build_index(pack)
    report = pack.get("domain") == "report"
    units: list[dict[str, Any]] = []

    def add(role: str, text: str, ids: list[str], *, uncertainty: str = "", causal: str = "",
            relation: str = "", step_id: str = "") -> None:
        ids, attribution = _attribution(ids, index) if report else (ids, "")
        unit = {"role": role, "text": text, "evidence_ids": ids, "uncertainty": uncertainty,
                "causal_level": causal, "transition_relation": relation, "attribution": attribution}
        if step_id:
            unit["source_reasoning_id"] = step_id          # 설명 단계 번호(S1…) — 화면 단계까지 따라간다
        units.append(unit)

    for concept in reasoning.get("prerequisite_concepts") or []:
        if isinstance(concept, dict) and concept.get("basis") == "source" and _strings(concept.get("evidence_ids")):
            add("prerequisite", f"{_text(concept.get('concept'))}: {_text(concept.get('simple_explanation'))}",
                _strings(concept.get("evidence_ids")))
    for step in reasoning.get("explanation_steps") or []:
        if not isinstance(step, dict):
            continue
        kind = step_kind(step.get("kind"))
        uncertainty = _text(step.get("uncertainty"))
        if uncertainty.lower() in _NO_UNCERTAINTY:
            uncertainty = "author_interpretation" if kind in _INTERPRETIVE_KINDS else ""
        add(_role_for(step), _text(step.get("answer")), _strings(step.get("evidence_ids")),
            uncertainty=uncertainty, causal="speculation" if kind in _INTERPRETIVE_KINDS else "",
            relation=_text(step.get("relation_to_previous")), step_id=_text(step.get("step_id")))
    payoff = reasoning.get("payoff") if isinstance(reasoning.get("payoff"), dict) else {}
    if _text(payoff.get("text")):
        add("payoff", _text(payoff["text"]), _strings(payoff.get("evidence_ids")), step_id="PAYOFF")
    for lim in reasoning.get("limitations") or []:
        if isinstance(lim, dict) and _text(lim.get("text")):
            add("limitation", _text(lim["text"]), _strings(lim.get("evidence_ids")))
    return {"domain": pack.get("domain"), "origin": "model_reasoning",
            "core_question": _text(reasoning.get("core_question")),
            "thesis": _text(payoff.get("text")), "reasoning_units": units}


def gloss_terms(reasoning: dict[str, Any]) -> list[dict[str, str]]:
    """원문에 설명이 없는 용어 — 대본은 쉬운 말로 **바꿔 부르기만** 하고 사실처럼 설명하지 않는다(§6)."""
    return [{"term": _text(c.get("concept")), "plain": _text(c.get("simple_explanation"))}
            for c in reasoning.get("prerequisite_concepts") or []
            if isinstance(c, dict) and c.get("basis") != "source" and _text(c.get("concept"))]
