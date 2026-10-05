"""Phase 6 shadow spoken-narration contract.

The model may write Korean sentences only. Stable identity and provenance are
copied from the validated Narrative Plan, and no Production script path imports
this module.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Callable

from . import config, narrative_planner, script_polish, spoken_numbers
from .llm import call_json, set_text_purpose


CONTRACT_VERSION = "spoken-narration-v1"
STATUSES = frozenset({"DRAFT_ACCEPTED", "REJECTED_DRAFT", "BLOCKED_UPSTREAM"})
MAX_TOKENS = 8192
SPOKEN_SENTENCE_MAX_CHARS = 60

_SCOPE_INTENSIFIERS = frozenset({
    "모든", "유일", "항상", "절대", "오직", "최초", "전부", "완전히", "반드시",
})
_DETERMINATION_TERMS = ("결정", "원인", "때문", "초래", "야기")
_PROJECTION_TERMS = ("전망", "예상", "추정", "가능성", "시사", "본다", "봤다")
_PROTECTED_MEANING_CLASSES = frozenset({"hedge", "uncertain", "assoc", "negation"})
_SCOPE_QUALIFIERS = frozenset({"평균", "일부", "약", "가량", "정도", "경향", "특정", "대체로"})
# "약" 은 수 앞("약 30%")일 때만 '대략'이라는 범위 단서다. "약간·약물·요약" 의 약은 아니다 — 파일럿에서
# 화면용 숫자를 "약간 낮다"로 풀자 범위 단서가 새로 생긴 것으로 잘못 잡혔다(2026-10-04).
# `script_polish.meaning_classes` 는 Production 다듬기도 쓰므로 고치지 않고 여기서만 가린다.
_NON_HEDGE_YAK = re.compile(r"약(?!\s*[\d.])")
# 한자어 부정("불필요·불가능·무관…")도 부정이다. 원문 "허가도 불필요"를 모델이 "허가도 필요 없어"로 풀자 "없"만
# 부정으로 세져 뜻이 바뀐 것으로 거절됐다(2026-10-05 위성 레이저 광통신 실측). 양쪽 모두 이 낱말을 부정으로 센다.
_SINO_NEGATION = re.compile(r"불(?:필요|가능|가|충분|충족|명확|분명|일치)|무(?:관|의미|효)|미(?:달|흡|확인|정)")
# 덧붙이면 주장이 약해질 뿐인 갈래 — **빼는 것만** 막는다. 연관·부정은 양방향 모두 막는다.
_WEAKENING_CLASSES = frozenset({"hedge", "uncertain"})
_ABBREVIATION = re.compile(r"(?<![A-Za-z])[A-Z][A-Z0-9+.-]{1,}(?![A-Za-z])")
_ACADEMIC_REGISTER = ("본 연구", "관찰되었다", "확인되었다", "시사한다", "할 수 있습니다")

def _meaning_classes(text: str) -> set[str]:
    classes = script_polish.meaning_classes(text) & _PROTECTED_MEANING_CLASSES
    return classes | {"negation"} if _SINO_NEGATION.search(text) else classes


SYSTEM_PROMPT = """너는 짧은 한국어 설명 영상의 나레이션 작성자다.
입력의 비트 순서와 의미를 그대로 유지해 말하기 쉬운 문장으로 바꿔라.
부정, 불확실성, 연관성, 범위 단서(평균·일부·약 등), 출처 귀속을 바꾸거나 빼지 마라.
숫자: 각 비트의 spoken_numbers 에 있는 수만 값·단위 그대로 말한다. screen_numbers 의 수는 말하지 말고
크기와 방향을 말로 풀어라(예: "2.4배에서 8.6배 더 넓다" → "훨씬 넓다") — 그 수는 화면 카드로 나간다.
연도·분기 같은 시점 표현은 그대로 둔다. 입력에 없는 숫자를 만들지 마라.
새 사실, 비유, 인과, 근거, ID를 추가하지 마라.
stage 가 HOOK 인 비트는 core_question 을 한 문장 그대로 쓴다. 바꿔도 되는 것은 문장 끝 어미뿐이다
(예: "…하는가?" → "…하는 걸까요?"). 낱말을 바꾸거나 다른 문장을 덧붙이면 코드가 core_question 으로 되돌린다.
각 beat_id를 한 번씩 같은 순서로 반환하라.
JSON only: {"beats":[{"beat_id":"NB01","sentences":["..."]}]}
"""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


# 도입 질문에서 말투로 바꿔도 되는 문장 끝 어미(긴 것부터 떼어 낸다). 어간·낱말은 못 바꾼다.
_QUESTION_ENDINGS = tuple(sorted({
    "는걸까요", "은걸까요", "인걸까요", "는건가요", "은건가요", "인건가요",
    "는가요", "은가요", "인가요", "는지요", "을까요", "일까요",
    "는가", "은가", "인가", "나요", "까요", "가요", "는지", "을까", "일까",
}, key=len, reverse=True))


def _question_core(text: Any) -> str:
    body = re.sub(r"\s+", "", _text(text)).rstrip("?？.!…")
    for ending in _QUESTION_ENDINGS:
        if body.endswith(ending) and len(body) > len(ending):
            return body[: -len(ending)]
    return body


def hook_matches_core_question(text: Any, core_question: Any) -> bool:
    """도입 질문이 승인된 핵심 질문과 같은가 — 문장 끝 어미만 다를 수 있다.

    Phase 6(대본)과 Phase 7(수사적 예외)이 **같은 판정**을 쓴다. 종전에는 Phase 6 이 어간 60% 만
    남으면 통과시키고 Phase 7 은 글자 그대로를 요구해서, 실제 모델이 "…보여 주는가?" 를 "…보여
    주는 걸까요?" 로 다듬기만 해도 Phase 7 에서 막혔다(Phase 12 파일럿 2/2건, 2026-10-04).
    근거 없이 허용되는 수사 절은 핵심 질문 그 자체뿐이다(작업지시서 §9.3, Phase 7 문서) —
    낱말을 바꾸거나 문장을 덧붙이면 사실 주장이 섞일 수 있으므로 같다고 보지 않는다.
    """
    sentence = _text(text)
    if not sentence or not _text(core_question):
        return False
    if sentence.count("?") + sentence.count("？") != 1 or not sentence.endswith(("?", "？")):
        return False
    return _question_core(sentence) == _question_core(core_question)


def _restore_hook(sentences: list[str], core_question: str) -> tuple[list[str], bool]:
    """도입 질문이 핵심 질문과 다르면 승인된 핵심 질문으로 되돌린다(대본 전체를 버리지 않는다)."""
    if len(sentences) == 1 and hook_matches_core_question(sentences[0], core_question):
        return sentences, False
    return [core_question], True


def _joined_sentences(beat: dict[str, Any]) -> str:
    return " ".join(_strings(beat.get("sentences")))


def _draft_guard_findings(
    narration_beats: list[dict[str, Any]], plan: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    plan_by_id = {beat["beat_id"]: beat for beat in plan["beats"]}
    question_count = 0
    total_numbers = 0

    for beat in narration_beats:
        beat_id = _text(beat.get("beat_id"))
        source = plan_by_id.get(beat_id)
        if not source:
            continue
        before = " ".join(_strings(source.get("content_points")))
        after = _joined_sentences(beat)
        # 숫자 계약(spoken_numbers 모듈): 말하기로 고른 값만 그대로, 화면용 값은 말하지 않고,
        # 시점 표현은 그대로. 입력에 없는 값은 어느 쪽이든 numbers_changed.
        delivery = source.get("number_delivery") if isinstance(
            source.get("number_delivery"), dict) else {}
        expected_spoken = sorted(_strings(delivery.get("spoken_numbers")))
        screen_numbers = sorted(
            number for fact in delivery.get("screen_facts") or [] if isinstance(fact, dict)
            for number in _strings(fact.get("numbers"))
        )
        after_numbers = spoken_numbers.value_tokens(after)
        total_numbers += len(after_numbers)
        if after_numbers != expected_spoken:
            extra = spoken_numbers.multiset_minus(after_numbers, expected_spoken)
            missing = spoken_numbers.multiset_minus(expected_spoken, after_numbers)
            spoken_screen = [n for n in extra if n in screen_numbers]
            if spoken_screen:
                errors.append(f"screen_number_spoken:{beat_id}:{spoken_screen[0]}")
            if missing or len(spoken_screen) != len(extra):
                errors.append(f"numbers_changed:{beat_id}")
        if spoken_numbers.period_tokens(before) != spoken_numbers.period_tokens(after):
            errors.append(f"period_changed:{beat_id}")

        added_scope = sorted(
            term for term in _SCOPE_INTENSIFIERS if term in after and term not in before
        )
        if added_scope:
            errors.append(f"scope_intensifier_added:{beat_id}:{added_scope[0]}")

        # 화면으로 보낸 숫자에 붙은 "약 N"·"N 가량/정도" 는 숫자와 함께 말에서 빠진다 — 그 단서는 화면 카드의
        # 숫자에 남는다. 이걸 "범위 단서를 뺐다"로 보면 숫자를 화면으로 보낼 때마다 거절된다(Shipbuilding 실측).
        before_meaning = before
        for number in screen_numbers:
            escaped = re.escape(number)
            before_meaning = re.sub(rf"약\s*{escaped}", number, before_meaning)
            before_meaning = re.sub(rf"{escaped}\s*(?:가량|정도)", number, before_meaning)
        before_meaning = _NON_HEDGE_YAK.sub("□", before_meaning)
        after_meaning = _NON_HEDGE_YAK.sub("□", after)
        before_classes = _meaning_classes(before_meaning)
        after_classes = _meaning_classes(after_meaning)
        changed_classes = (before_classes - after_classes) | (
            (after_classes - before_classes) - _WEAKENING_CLASSES
        )
        if changed_classes:
            changed = ",".join(sorted(changed_classes))
            errors.append(f"protected_meaning_changed:{beat_id}:{changed}")
        for qualifier in sorted(_SCOPE_QUALIFIERS):
            if before_meaning.count(qualifier) > after_meaning.count(qualifier):
                errors.append(f"qualifier_dropped:{beat_id}:{qualifier}")
        if (
            "broker_projection" in (source.get("causal_levels") or [])
            and any(term in before for term in _PROJECTION_TERMS)
            and not any(term in after for term in _PROJECTION_TERMS)
        ):
            errors.append(f"protected_meaning_changed:{beat_id}:projection")
        if (
            "assoc" in before_classes
            and "assoc" not in after_classes
            and any(term in after for term in _DETERMINATION_TERMS)
        ):
            errors.append(f"association_upgraded:{beat_id}")
        added_causal = sorted(
            term for term in _DETERMINATION_TERMS
            if after.count(term) > before.count(term)
        )
        if added_causal and source.get("stage") != "HOOK":
            errors.append(f"causal_language_added:{beat_id}:{added_causal[0]}")

        for attribution in source.get("attributions") or []:
            if attribution and attribution not in after:
                errors.append(f"attribution_dropped:{beat_id}:{attribution}")

        if source.get("stage") == "HOOK":
            question_count += after.count(plan["core_question"])
            if "?" not in after:
                errors.append(f"hook_not_question:{beat_id}")
                errors.append(f"hook_not_grounded:{beat_id}")
            elif not hook_matches_core_question(after, plan["core_question"]):
                errors.append(f"hook_not_grounded:{beat_id}")
            if "?" in after and after.rsplit("?", 1)[1].strip():
                errors.append(f"hook_factual_assertion_added:{beat_id}")

        if source.get("stage") != "HOOK" and not any((
            beat.get("reasoning_ids"), beat.get("evidence_ids"), beat.get("knowledge_refs"),
        )):
            errors.append(f"factual_trace_missing:{beat_id}")

        for sentence in _strings(beat.get("sentences")):
            if len(sentence) > SPOKEN_SENTENCE_MAX_CHARS:
                warnings.append(f"sentence_too_long:{beat_id}")
            if any(term in sentence for term in _ACADEMIC_REGISTER):
                warnings.append(f"academic_register:{beat_id}")
        if len(after_numbers) > config.STORY_MAX_NUMBERS_PER_SCENE:
            warnings.append(f"too_many_numbers:{beat_id}")
        for abbreviation in sorted(set(_ABBREVIATION.findall(after))):
            warnings.append(f"unexplained_abbreviation:{beat_id}:{abbreviation}")

    full_text = " ".join(_joined_sentences(beat) for beat in narration_beats)
    question_count = max(question_count, full_text.count(plan["core_question"]))
    if question_count > 1:
        warnings.append("core_question_repeated")
    return (
        sorted(set(errors)),
        sorted(set(warnings)),
        {
            "beat_count": len(narration_beats),
            "sentence_count": sum(len(_strings(beat.get("sentences")))
                                  for beat in narration_beats),
            "number_count": total_numbers,
            "warning_count": len(set(warnings)),
        },
    )


def _upstream_errors(plan: Any, ir: dict[str, Any], resolution: dict[str, Any],
                     pack: dict[str, Any]) -> list[str]:
    errors = narrative_planner.validate(plan, ir, resolution, pack)
    if errors:
        return errors
    canonical = narrative_planner.build(ir, resolution, pack)
    if plan != canonical:
        errors.append("plan_not_canonical")
    return errors


def _require_valid_upstream(plan: Any, ir: dict[str, Any], resolution: dict[str, Any],
                            pack: dict[str, Any]) -> None:
    errors = _upstream_errors(plan, ir, resolution, pack)
    if errors:
        raise ValueError("narrative_plan_invalid:" + ",".join(errors))


def prompt_payload(plan: dict[str, Any], ir: dict[str, Any],
                   resolution: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Return the complete and intentionally narrow model-visible payload."""
    _require_valid_upstream(plan, ir, resolution, pack)
    return {
        "domain": plan["domain"],
        "core_question": plan["core_question"],
        "thesis": plan["thesis"],
        "beats": [{
            "beat_id": beat["beat_id"],
            "stage": beat["stage"],
            "purpose": beat["purpose"],
            "content_points": deepcopy(beat["content_points"]),
            "spoken_numbers": deepcopy(beat["number_delivery"]["spoken_numbers"]),
            "screen_numbers": sorted(
                number for fact in beat["number_delivery"]["screen_facts"]
                for number in fact["numbers"]
            ),
            "causal_levels": deepcopy(beat["causal_levels"]),
            "uncertainties": deepcopy(beat["uncertainties"]),
            "attributions": deepcopy(beat["attributions"]),
            "transition_relations": deepcopy(beat["transition_relations"]),
        } for beat in plan["beats"]],
        "guardrails": [{
            "concept_id": concept["concept_id"],
            "simple_explanation": concept["simple_explanation"],
            "guardrails": deepcopy(concept.get("guardrails") or []),
        } for concept in resolution.get("concepts") or []
            if concept.get("status") in {"RESOLVED_SOURCE", "RESOLVED_GLOSSARY"}],
    }


def _empty_result(plan: dict[str, Any], status: str, *,
                  errors: list[str] | None = None,
                  warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": plan.get("domain"),
        "content_id": plan.get("content_id"),
        "generation_status": status,
        "core_question": plan.get("core_question"),
        "narration_beats": [],
        "qa": {
            "semantic_entailment": "NOT_CHECKED",
            "errors": sorted(set(errors or [])),
            "warnings": sorted(set(warnings or [])),
            "metrics": {"beat_count": 0, "sentence_count": 0},
        },
        "polish": {},
    }


def normalize_draft(payload: Any, plan: dict[str, Any], ir: dict[str, Any],
                    resolution: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Normalize model sentences while injecting immutable plan provenance."""
    _require_valid_upstream(plan, ir, resolution, pack)
    if plan["planning_status"] != "READY":
        return _empty_result(
            plan,
            "BLOCKED_UPSTREAM",
            warnings=[f"upstream_{plan['planning_status'].lower()}"] + list(plan["warnings"]),
        )
    rows = payload.get("beats") if isinstance(payload, dict) else None
    errors: list[str] = []
    if not isinstance(rows, list):
        rows = []
        errors.append("draft_beats_not_list")

    expected_ids = [beat["beat_id"] for beat in plan["beats"]]
    actual_ids = [_text(row.get("beat_id")) if isinstance(row, dict) else "" for row in rows]
    if actual_ids != expected_ids:
        errors.append("draft_beat_coverage_invalid")

    normalized: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    for position, beat in enumerate(plan["beats"], 1):
        row = rows[position - 1] if position <= len(rows) else None
        if not isinstance(row, dict) or _text(row.get("beat_id")) != beat["beat_id"]:
            continue
        sentences = _strings(row.get("sentences"))
        if not sentences:
            errors.append(f"draft_sentences_empty:{beat['beat_id']}")
        elif beat["stage"] == "HOOK":
            restored, changed = _restore_hook(sentences, plan["core_question"])
            if changed:
                repairs.append({
                    "beat_id": beat["beat_id"],
                    "repair": "hook_restored_to_core_question",
                    "model_sentences": sentences,
                })
                sentences = restored
        normalized.append({
            "narration_id": f"SN{position:02d}",
            "beat_id": beat["beat_id"],
            "stage": beat["stage"],
            "sentences": sentences,
            "reasoning_ids": deepcopy(beat["reasoning_ids"]),
            "evidence_ids": deepcopy(beat["evidence_ids"]),
            "raw_refs": deepcopy(beat["raw_refs"]),
            "concept_ids": deepcopy(beat["concept_ids"]),
            "knowledge_refs": deepcopy(beat["knowledge_refs"]),
            "causal_levels": deepcopy(beat["causal_levels"]),
            "uncertainties": deepcopy(beat["uncertainties"]),
            "attributions": deepcopy(beat["attributions"]),
            "number_delivery": deepcopy(beat["number_delivery"]),
        })

    guard_errors, guard_warnings, metrics = _draft_guard_findings(normalized, plan)
    errors.extend(guard_errors)
    result = {
        "contract_version": CONTRACT_VERSION,
        "domain": plan["domain"],
        "content_id": plan["content_id"],
        "generation_status": "REJECTED_DRAFT" if errors else "DRAFT_ACCEPTED",
        "core_question": plan["core_question"],
        "narration_beats": normalized,
        "qa": {
            "semantic_entailment": "NOT_CHECKED",
            "errors": sorted(set(errors)),
            "warnings": guard_warnings,
            "metrics": metrics,
        },
        "polish": {},
        "repairs": repairs,
    }
    validation_errors = validate(result, plan, ir, resolution, pack)
    contract_errors = [error for error in validation_errors if error not in errors]
    if contract_errors:
        result["qa"]["errors"] = sorted(set(result["qa"]["errors"] + contract_errors))
        result["generation_status"] = "REJECTED_DRAFT"
    return result


def validate(result: Any, plan: dict[str, Any], ir: dict[str, Any],
             resolution: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    """Validate the normalized Phase 6 shape and plan-owned provenance."""
    upstream = _upstream_errors(plan, ir, resolution, pack)
    if upstream:
        return [f"narrative_plan_invalid:{error}" for error in upstream]
    if not isinstance(result, dict):
        return ["narration_not_dict"]
    errors: list[str] = []
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if result.get("domain") != plan.get("domain"):
        errors.append("domain_mismatch")
    if result.get("content_id") != plan.get("content_id"):
        errors.append("content_id_mismatch")
    status = result.get("generation_status")
    if status not in STATUSES:
        errors.append("generation_status_invalid")
    expected_blocked = plan.get("planning_status") != "READY"
    if (status == "BLOCKED_UPSTREAM") != expected_blocked:
        errors.append("generation_status_upstream_mismatch")
    if result.get("core_question") != plan.get("core_question"):
        errors.append("core_question_invalid")
    qa = result.get("qa")
    if not isinstance(qa, dict) or qa.get("semantic_entailment") != "NOT_CHECKED":
        errors.append("semantic_entailment_invalid")
    beats = result.get("narration_beats")
    if not isinstance(beats, list):
        return sorted(set(errors + ["narration_beats_not_list"]))
    if status == "BLOCKED_UPSTREAM":
        if beats:
            errors.append("blocked_narration_has_beats")
        return sorted(set(errors))
    expected_ids = [beat["beat_id"] for beat in plan["beats"]]
    actual_ids = [beat.get("beat_id") for beat in beats]
    if status == "DRAFT_ACCEPTED" and actual_ids != expected_ids:
        errors.append("accepted_beat_coverage_invalid")
    for position, row in enumerate(beats, 1):
        if position > len(plan["beats"]):
            errors.append("narration_beat_extra")
            continue
        source = plan["beats"][position - 1]
        if row.get("narration_id") != f"SN{position:02d}":
            errors.append(f"narration_id_invalid:{position}")
        if row.get("beat_id") != source["beat_id"]:
            errors.append(f"beat_id_invalid:{position}")
        for field in (
            "stage", "reasoning_ids", "evidence_ids", "raw_refs", "concept_ids",
            "knowledge_refs", "causal_levels", "uncertainties", "attributions",
            "number_delivery",
        ):
            if row.get(field) != source.get(field):
                errors.append(f"{field}_invalid:{source['beat_id']}")
        if not _strings(row.get("sentences")):
            errors.append(f"sentences_empty:{source['beat_id']}")
        if source.get("stage") != "HOOK" and not any((
            row.get("reasoning_ids"), row.get("evidence_ids"), row.get("knowledge_refs"),
        )):
            errors.append(f"factual_trace_missing:{source['beat_id']}")
    guard_errors, guard_warnings, guard_metrics = _draft_guard_findings(beats, plan)
    stored_errors = _strings(qa.get("errors")) if isinstance(qa, dict) else []
    stored_warnings = _strings(qa.get("warnings")) if isinstance(qa, dict) else []
    if not set(guard_errors).issubset(stored_errors):
        errors.append("qa_errors_stale")
    if stored_warnings != guard_warnings:
        errors.append("qa_warnings_stale")
    if isinstance(qa, dict) and qa.get("metrics") != guard_metrics:
        errors.append("qa_metrics_stale")
    if status == "DRAFT_ACCEPTED":
        if guard_errors:
            errors.append("accepted_draft_has_guard_errors")
        if stored_errors:
            errors.append("accepted_draft_has_qa_errors")
    elif status == "REJECTED_DRAFT" and not stored_errors:
        errors.append("rejected_draft_without_errors")
    return sorted(set(errors))


def generate(plan: dict[str, Any], ir: dict[str, Any], resolution: dict[str, Any],
             pack: dict[str, Any], *, caller: Callable[..., dict[str, Any]] | None = None
             ) -> dict[str, Any]:
    """Generate a shadow draft; blocked upstream plans never resolve the caller."""
    _require_valid_upstream(plan, ir, resolution, pack)
    if plan["planning_status"] != "READY":
        return _empty_result(
            plan,
            "BLOCKED_UPSTREAM",
            warnings=[f"upstream_{plan['planning_status'].lower()}"] + list(plan["warnings"]),
        )
    visible = prompt_payload(plan, ir, resolution, pack)
    set_text_purpose("spoken_narration_shadow")
    invoke = caller or call_json
    payload = invoke(
        model=config.MODEL_SCRIPT,
        system=SYSTEM_PROMPT,
        user=json.dumps(visible, ensure_ascii=False, sort_keys=True),
        max_tokens=MAX_TOKENS,
    )
    return normalize_draft(payload, plan, ir, resolution, pack)


def apply_polish(narration: dict[str, Any], payload: Any, plan: dict[str, Any],
                 ir: dict[str, Any], resolution: dict[str, Any],
                 pack: dict[str, Any]) -> dict[str, Any]:
    """Apply safe expression-only changes without mutating the accepted draft."""
    if not isinstance(narration, dict) or narration.get("generation_status") != "DRAFT_ACCEPTED":
        raise ValueError("narration_not_accepted")
    contract_errors = validate(narration, plan, ir, resolution, pack)
    if contract_errors:
        raise ValueError("narration_invalid:" + ",".join(contract_errors))

    result = deepcopy(narration)
    rows = payload.get("beats") if isinstance(payload, dict) else None
    expected_ids = [beat["beat_id"] for beat in result["narration_beats"]]
    actual_ids = (
        [_text(row.get("beat_id")) if isinstance(row, dict) else "" for row in rows]
        if isinstance(rows, list) else []
    )
    if actual_ids != expected_ids:
        result["polish"] = {
            "applied": [],
            "rejected": [{"beat_id": "*", "reason": "polish_beat_coverage_invalid"}],
            "unchanged": [],
        }
        return result

    applied: list[str] = []
    rejected: list[dict[str, str]] = []
    unchanged: list[str] = []
    for position, row in enumerate(rows):
        target = result["narration_beats"][position]
        beat_id = target["beat_id"]
        before = _joined_sentences(target)
        sentences = _strings(row.get("sentences")) if isinstance(row, dict) else []
        after = " ".join(sentences)
        if after == before:
            unchanged.append(beat_id)
            continue

        polish_reason = script_polish.rejection_reason(before, after)
        candidate = deepcopy(result)
        candidate["narration_beats"][position]["sentences"] = sentences
        guard_errors, _, _ = _draft_guard_findings(candidate["narration_beats"], plan)
        relevant_guards = [error for error in guard_errors if f":{beat_id}" in error]
        attribution_error = next(
            (error for error in relevant_guards if error.startswith("attribution_dropped:")), ""
        )
        reason = (
            attribution_error
            or polish_reason
            or ("semantic_guard:" + relevant_guards[0] if relevant_guards else "")
        )
        if reason:
            rejected.append({"beat_id": beat_id, "reason": reason})
            continue
        target["sentences"] = sentences
        applied.append(beat_id)

    _, warnings, metrics = _draft_guard_findings(result["narration_beats"], plan)
    result["qa"]["warnings"] = warnings
    result["qa"]["metrics"] = metrics
    result["polish"] = {
        "applied": applied,
        "rejected": rejected,
        "unchanged": unchanged,
    }
    return result
