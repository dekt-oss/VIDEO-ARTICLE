"""Phase 7 shadow semantic-fidelity boundary.

The independent critic may judge narration clauses, but this module owns the
validated input slice, identity, provenance, and final gate state.  Nothing in
the Production script/directive path imports this module.
"""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
import json
import re
from typing import Any, Callable

from . import (
    config,
    evidence_pack,
    explanation_ir,
    narrative_planner,
    prerequisite_resolver,
    spoken_narration,
    spoken_numbers,
)
from .llm import call_json, set_text_purpose


CONTRACT_VERSION = "semantic-fidelity-v1"
QA_STATUSES = frozenset({
    "PASSED", "REJECTED", "BLOCKED_UPSTREAM", "REJECTED_UPSTREAM", "CRITIC_ERROR",
})
#: 이해용 비교 절의 표지 — "마치 ~처럼", "~같은", "~듯". 숫자가 들어간 비교는 면제하지 않는다.
_COMPARISON_MARKER = re.compile(r"처럼|마치|같은|같이|듯")

VERDICTS = frozenset({
    "ENTAILED", "CONTRADICTED", "UNSUPPORTED", "UNVERIFIABLE", "RHETORICAL",
})
FINDING_CODES = frozenset({
    "contradiction", "scope_expansion", "causal_upgrade", "missing_qualifier",
    "unsupported_background", "attribution_loss", "unsupported_factual_hook",
})

_EVIDENCE_SECTIONS = (
    "claims", "numbers", "risks", "limitations", "background_context",
)

SYSTEM_PROMPT = """너는 작성 모델과 분리된 의미 충실도 검증관이다.
각 나레이션 문장을 빠짐없이 순서대로 의미 절로 나누고, 입력에 포함된 Evidence Pack 항목과
Explanation IR만 사용해 절별 판정을 내려라. source quote의 존재는 claim 전체의 의미 보증이
아니다. 범위 확대, 인과 강화, 수식어 누락, 모순, 근거 없는 배경, 귀속 손실을 각각 표시하라.
HOOK도 사실 주장이면 근거가 필요하다. 순수한 핵심 질문만 RHETORICAL로 분류할 수 있다.
"마치 ~처럼" 같은 이해용 비교 절은 COMPARISON(verdict RHETORICAL)으로 분류하라 — 비교 자체는 근거가 필요 없다.
단 그 비교가 새 사실·숫자·인과를 주장하면 FACTUAL 로 보고 근거와 대조하라.
절 텍스트는 원문 문장의 연속된 글자를 그대로 복사하며 어떤 내용도 생략하거나 추가하지 마라.
evidence_id는 해당 beat에 제공된 값만 사용하라. reasoning/raw ref/aggregate status는 만들지 마라.
JSON only: {"clauses":[{"narration_id":"SN01","sentence_index":1,
"clause_text":"...","clause_kind":"FACTUAL|RHETORICAL|COMPARISON",
"verdict":"ENTAILED|CONTRADICTED|UNSUPPORTED|UNVERIFIABLE|RHETORICAL",
"evidence_ids":[],"finding_codes":[],"rationale":"..."}]}
"""


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _require_valid_upstream(
    narration: Any,
    plan: Any,
    ir: Any,
    resolution: Any,
    pack: Any,
) -> None:
    if not isinstance(pack, dict):
        raise ValueError("evidence_pack_invalid:pack_not_dict")
    pack_errors = evidence_pack.validate(pack)
    if pack_errors:
        raise ValueError("evidence_pack_invalid:" + ",".join(pack_errors))
    ir_errors = explanation_ir.validate(ir, pack)
    if ir_errors:
        raise ValueError("explanation_ir_invalid:" + ",".join(ir_errors))
    resolution_errors = prerequisite_resolver.validate(resolution, ir, pack)
    if resolution_errors:
        raise ValueError("prerequisite_resolution_invalid:" + ",".join(resolution_errors))
    plan_errors = narrative_planner.validate(plan, ir, resolution, pack)
    if plan_errors:
        raise ValueError("narrative_plan_invalid:" + ",".join(plan_errors))
    if plan != narrative_planner.build(ir, resolution, pack):
        raise ValueError("narrative_plan_invalid:plan_not_canonical")
    if isinstance(narration, dict) and narration.get("generation_status") == "REJECTED_DRAFT":
        narration_errors = spoken_narration.validate(
            narration, plan, ir, resolution, pack
        )
        integrity_errors = [
            error for error in narration_errors
            if not error.startswith("sentences_empty:")
        ]
        if integrity_errors:
            raise ValueError("spoken_narration_invalid:" + ",".join(integrity_errors))
        return
    narration_errors = spoken_narration.validate(
        narration, plan, ir, resolution, pack
    )
    if narration_errors:
        raise ValueError("spoken_narration_invalid:" + ",".join(narration_errors))


def _ordered_references(narration: dict[str, Any], field: str) -> list[str]:
    return list(dict.fromkeys(
        value
        for beat in narration["narration_beats"]
        for value in _strings(beat.get(field))
    ))


def _evidence_rows(pack: dict[str, Any], wanted: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in _EVIDENCE_SECTIONS:
        for item in pack.get(section) or []:
            if not isinstance(item, dict) or item.get("evidence_id") not in wanted:
                continue
            row = deepcopy(item)
            row["section"] = section
            rows.append(row)
    return rows


def _evidence_sections(pack: dict[str, Any]) -> dict[str, str]:
    return {
        _text(item.get("evidence_id")): section
        for section in _EVIDENCE_SECTIONS
        for item in pack.get(section) or []
        if isinstance(item, dict) and _text(item.get("evidence_id"))
    }


def _eligible_support(item: dict[str, Any], section: str) -> bool:
    if item.get("verification_state") in {"UNSUPPORTED", "STALE"}:
        return False
    scope = item.get("verification_scope") or {}
    has_source_span = any(
        isinstance(ref, dict) and _text(ref.get("quote"))
        for ref in item.get("source_refs") or []
    )
    if has_source_span or scope.get("semantic_entailment") is True:
        return True
    if section != "numbers" or scope.get("numeric_value") is not True:
        return False
    return (
        (not _text(item.get("unit")) or scope.get("unit") is True)
        and (not _text(item.get("period")) or scope.get("period") is True)
    )


def prompt_payload(
    narration: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
) -> dict[str, Any]:
    """Return the complete, trace-limited payload visible to the critic."""
    _require_valid_upstream(narration, plan, ir, resolution, pack)
    if narration.get("generation_status") != "DRAFT_ACCEPTED":
        raise ValueError("spoken_narration_not_accepted")

    reasoning_ids = _ordered_references(narration, "reasoning_ids")
    concept_ids = _ordered_references(narration, "concept_ids")
    evidence_ids = _ordered_references(narration, "evidence_ids")
    reasoning_index = {
        unit.get("reasoning_id"): unit for unit in ir.get("reasoning_units") or []
        if isinstance(unit, dict)
    }
    concept_index = {
        concept.get("concept_id"): concept
        for concept in resolution.get("concepts") or []
        if isinstance(concept, dict)
    }

    return {
        "domain": narration["domain"],
        "content_id": narration["content_id"],
        "core_question": narration["core_question"],
        "narration_beats": [{
            field: deepcopy(beat.get(field))
            for field in (
                "narration_id", "beat_id", "stage", "sentences",
                "reasoning_ids", "evidence_ids", "concept_ids", "knowledge_refs",
                "causal_levels", "uncertainties", "attributions",
            )
        } for beat in narration["narration_beats"]],
        "reasoning_units": [
            deepcopy(reasoning_index[reasoning_id])
            for reasoning_id in reasoning_ids
            if reasoning_id in reasoning_index
        ],
        "concepts": [
            deepcopy(concept_index[concept_id])
            for concept_id in concept_ids
            if concept_id in concept_index
        ],
        "evidence": _evidence_rows(pack, set(evidence_ids)),
    }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _coverage_text(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value))


def _empty_result(
    narration: dict[str, Any],
    status: str,
    *,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": narration.get("domain"),
        "content_id": narration.get("content_id"),
        "qa_status": status,
        "critic": {
            "independence": "separate_call",
            "semantic_entailment": "NOT_CHECKED",
        },
        "clauses": [],
        "qa": {
            "errors": sorted(set(errors or [])),
            "warnings": [],
            "metrics": {"clause_count": 0, "sentence_count": 0, "verdict_counts": {}},
        },
    }


def _metrics(clauses: list[dict[str, Any]], sentence_count: int) -> dict[str, Any]:
    verdicts = Counter(row["verdict"] for row in clauses)
    return {
        "clause_count": len(clauses),
        "sentence_count": sentence_count,
        "verdict_counts": dict(sorted(verdicts.items())),
    }


def _semantic_findings(
    clauses: list[dict[str, Any]],
    beat_by_narration: dict[str, dict[str, Any]],
    evidence_index: dict[str, dict[str, Any]],
    evidence_sections: dict[str, str],
    core_question: str,
) -> tuple[bool, list[str]]:
    failed = False
    errors: list[str] = []
    for row in clauses:
        clause_id = _text(row.get("clause_id")) or "?"
        beat = beat_by_narration.get(_text(row.get("narration_id"))) or {}
        kind = row.get("clause_kind")
        verdict = row.get("verdict")
        evidence_ids = _strings(row.get("evidence_ids"))
        findings = _strings(row.get("finding_codes"))
        if kind == "COMPARISON":
            # 이해용 비교(작업지시서 §8 목표 문체 "지렛대처럼"). 비교 표지가 있고, 근거·지적 사항이 없을 때만 면제.
            text = _text(row.get("clause_text"))
            valid = (verdict == "RHETORICAL" and not evidence_ids and not findings
                     and bool(_COMPARISON_MARKER.search(text))
                     and not spoken_numbers.value_tokens(text))
            if not valid:
                failed = True
                errors.append(f"comparison_exemption_invalid:{clause_id}")
            continue
        if kind == "RHETORICAL":
            valid = (
                beat.get("stage") == "HOOK"
                and verdict == "RHETORICAL"
                and not evidence_ids
                and not findings
                and spoken_narration.hook_matches_core_question(
                    row.get("clause_text"), core_question
                )
            )
            if not valid:
                failed = True
                errors.append(f"rhetorical_exemption_invalid:{clause_id}")
            continue

        if verdict != "ENTAILED" or findings:
            failed = True
        prerequisite_trace = (
            beat.get("stage") == "SETUP"
            and bool(beat.get("concept_ids"))
            and bool(beat.get("knowledge_refs"))
        )
        if not evidence_ids and not prerequisite_trace:
            failed = True
            errors.append(f"factual_evidence_missing:{clause_id}")
        for evidence_id in evidence_ids:
            item = evidence_index.get(evidence_id)
            if item is None:
                continue
            if not _eligible_support(item, evidence_sections.get(evidence_id, "")):
                failed = True
                errors.append(f"support_surface_ineligible:{clause_id}:{evidence_id}")
    return failed, sorted(set(errors))


def normalize_review(
    payload: object,
    narration: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
) -> dict[str, Any]:
    """Normalize critic judgments while injecting canonical identity and trace."""
    _require_valid_upstream(narration, plan, ir, resolution, pack)
    if narration.get("generation_status") != "DRAFT_ACCEPTED":
        raise ValueError("spoken_narration_not_accepted")
    rows = payload.get("clauses") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return _empty_result(narration, "CRITIC_ERROR", errors=["critic_clauses_not_list"])

    beats = narration["narration_beats"]
    beat_by_narration = {beat["narration_id"]: beat for beat in beats}
    evidence_index = explanation_ir.build_index(pack)
    evidence_sections = _evidence_sections(pack)
    expected = [
        (beat, sentence_index, sentence)
        for beat in beats
        for sentence_index, sentence in enumerate(beat["sentences"], 1)
    ]
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    cursor = 0

    for beat, sentence_index, sentence in expected:
        key = (beat["narration_id"], sentence_index)
        sentence_rows: list[dict[str, Any]] = []
        while cursor < len(rows):
            candidate = rows[cursor]
            if not isinstance(candidate, dict):
                errors.append(f"critic_clause_invalid:{cursor + 1}")
                cursor += 1
                continue
            candidate_key = (candidate.get("narration_id"), candidate.get("sentence_index"))
            if candidate_key != key:
                break
            sentence_rows.append(candidate)
            cursor += 1
        covered = "".join(_coverage_text(row.get("clause_text")) for row in sentence_rows)
        if not sentence_rows or covered != _coverage_text(sentence):
            errors.append(f"clause_coverage_invalid:{key[0]}:{sentence_index}")
            continue

        for row in sentence_rows:
            clause_text = _text(row.get("clause_text"))
            clause_kind = _text(row.get("clause_kind"))
            verdict = _text(row.get("verdict"))
            if not isinstance(row.get("evidence_ids"), list) or not all(
                isinstance(value, str) and value.strip()
                for value in row.get("evidence_ids") or []
            ):
                errors.append(f"evidence_ids_invalid:{key[0]}:{sentence_index}")
            if not isinstance(row.get("finding_codes"), list) or not all(
                isinstance(value, str) and value.strip()
                for value in row.get("finding_codes") or []
            ):
                errors.append(f"finding_codes_invalid:{key[0]}:{sentence_index}")
            evidence_ids = _strings(row.get("evidence_ids"))
            finding_codes = _strings(row.get("finding_codes"))
            if clause_kind not in {"FACTUAL", "RHETORICAL", "COMPARISON"}:
                errors.append(f"clause_kind_invalid:{key[0]}:{sentence_index}")
            if verdict not in VERDICTS:
                errors.append(f"verdict_invalid:{key[0]}:{sentence_index}")
            if (
                verdict in {"CONTRADICTED", "UNSUPPORTED", "UNVERIFIABLE"}
                and not _text(row.get("rationale"))
            ):
                errors.append(f"rationale_missing:{key[0]}:{sentence_index}")
            invalid_findings = [code for code in finding_codes if code not in FINDING_CODES]
            if invalid_findings:
                errors.append(f"finding_code_invalid:{key[0]}:{invalid_findings[0]}")
            unknown = [evidence_id for evidence_id in evidence_ids
                       if evidence_id not in evidence_index]
            if unknown:
                errors.append(f"evidence_ref_unknown:{key[0]}:{unknown[0]}")
            outside = [evidence_id for evidence_id in evidence_ids
                       if evidence_id not in beat.get("evidence_ids", [])]
            if outside:
                errors.append(f"evidence_ref_outside_beat:{key[0]}:{outside[0]}")
            if (
                beat.get("stage") == "HOOK"
                and clause_kind == "FACTUAL"
                and not evidence_ids
                and "unsupported_factual_hook" not in finding_codes
            ):
                finding_codes.append("unsupported_factual_hook")
            raw_refs = list(dict.fromkeys(
                _text(evidence_index[evidence_id].get("raw_ref"))
                for evidence_id in evidence_ids if evidence_id in evidence_index
                and _text(evidence_index[evidence_id].get("raw_ref"))
            ))
            normalized.append({
                "clause_id": f"SC{len(normalized) + 1:02d}",
                "narration_id": beat["narration_id"],
                "beat_id": beat["beat_id"],
                "stage": beat["stage"],
                "sentence_index": sentence_index,
                "clause_text": clause_text,
                "clause_kind": clause_kind,
                "verdict": verdict,
                "evidence_ids": evidence_ids,
                "reasoning_ids": deepcopy(beat["reasoning_ids"]),
                "raw_refs": raw_refs,
                "concept_ids": deepcopy(beat["concept_ids"]),
                "knowledge_refs": deepcopy(beat["knowledge_refs"]),
                "finding_codes": finding_codes,
                "rationale": _text(row.get("rationale")),
            })

    if cursor != len(rows):
        errors.append("critic_clause_extra_or_reordered")
    if errors:
        return _empty_result(narration, "CRITIC_ERROR", errors=errors)

    rejected, semantic_errors = _semantic_findings(
        normalized,
        beat_by_narration,
        evidence_index,
        evidence_sections,
        narration["core_question"],
    )
    status = "REJECTED" if rejected else "PASSED"
    sentence_count = len(expected)
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": narration["domain"],
        "content_id": narration["content_id"],
        "qa_status": status,
        "critic": {
            "independence": "separate_call",
            "semantic_entailment": "FAILED" if rejected else "PASSED",
        },
        "clauses": normalized,
        "qa": {
            "errors": semantic_errors,
            "warnings": [],
            "metrics": _metrics(normalized, sentence_count),
        },
    }


def validate(
    result: object,
    narration: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
) -> list[str]:
    """Validate Phase 7 shape, coverage, and canonical trace."""
    _require_valid_upstream(narration, plan, ir, resolution, pack)
    if not isinstance(result, dict):
        return ["fidelity_not_dict"]
    errors: list[str] = []
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if result.get("domain") != narration.get("domain"):
        errors.append("domain_mismatch")
    if result.get("content_id") != narration.get("content_id"):
        errors.append("content_id_mismatch")
    if result.get("qa_status") not in QA_STATUSES:
        errors.append("qa_status_invalid")
    clauses = result.get("clauses")
    if not isinstance(clauses, list):
        return sorted(set(errors + ["clauses_not_list"]))
    narration_status = narration.get("generation_status")
    upstream_status = {
        "BLOCKED_UPSTREAM": "BLOCKED_UPSTREAM",
        "REJECTED_DRAFT": "REJECTED_UPSTREAM",
    }.get(narration_status)
    if upstream_status:
        if result.get("qa_status") != upstream_status:
            errors.append("qa_status_upstream_mismatch")
        if clauses:
            errors.append("upstream_result_has_clauses")
        critic = result.get("critic")
        if not isinstance(critic, dict) or critic.get("semantic_entailment") != "NOT_CHECKED":
            errors.append("semantic_entailment_stale")
        expected_metrics = {
            "clause_count": 0,
            "sentence_count": 0,
            "verdict_counts": {},
        }
        qa = result.get("qa") if isinstance(result.get("qa"), dict) else {}
        if qa.get("metrics") != expected_metrics:
            errors.append("qa_metrics_stale")
        if result != _empty_result(narration, upstream_status):
            errors.append("upstream_result_not_canonical")
        return sorted(set(errors))
    if result.get("qa_status") == "CRITIC_ERROR":
        if clauses:
            errors.append("critic_error_has_clauses")
        qa = result.get("qa") if isinstance(result.get("qa"), dict) else {}
        stored_errors = qa.get("errors")
        if not isinstance(stored_errors, list) or not stored_errors or not all(
            isinstance(error, str) and error for error in stored_errors
        ):
            errors.append("critic_errors_invalid")
            stored_errors = []
        if result != _empty_result(
            narration, "CRITIC_ERROR", errors=stored_errors
        ):
            errors.append("critic_error_not_canonical")
        return sorted(set(errors))
    expected_ids = [f"SC{position:02d}" for position in range(1, len(clauses) + 1)]
    if [row.get("clause_id") for row in clauses if isinstance(row, dict)] != expected_ids:
        errors.append("clause_ids_invalid")
    evidence_index = explanation_ir.build_index(pack)
    evidence_sections = _evidence_sections(pack)
    beat_index = {beat["narration_id"]: beat for beat in narration["narration_beats"]}
    grouped: dict[tuple[str, int], list[str]] = {}
    for row in clauses:
        if not isinstance(row, dict):
            errors.append("clause_invalid")
            continue
        narration_id = row.get("narration_id")
        beat = beat_index.get(narration_id)
        if beat is None:
            errors.append(f"narration_ref_unknown:{narration_id}")
            continue
        for field in ("beat_id", "stage", "reasoning_ids", "concept_ids", "knowledge_refs"):
            if row.get(field) != beat.get(field):
                errors.append(f"{field}_invalid:{row.get('clause_id')}")
        evidence_ids = _strings(row.get("evidence_ids"))
        unknown = [evidence_id for evidence_id in evidence_ids
                   if evidence_id not in evidence_index]
        errors.extend(
            f"evidence_ref_unknown:{row.get('clause_id')}:{evidence_id}"
            for evidence_id in unknown
        )
        outside = [evidence_id for evidence_id in evidence_ids
                   if evidence_id not in beat.get("evidence_ids", [])]
        errors.extend(
            f"evidence_ref_outside_beat:{row.get('clause_id')}:{evidence_id}"
            for evidence_id in outside
        )
        expected_refs = list(dict.fromkeys(
            _text(evidence_index[evidence_id].get("raw_ref"))
            for evidence_id in evidence_ids if evidence_id in evidence_index
            and _text(evidence_index[evidence_id].get("raw_ref"))
        ))
        if row.get("raw_refs") != expected_refs:
            errors.append(f"raw_refs_invalid:{row.get('clause_id')}")
        key = (narration_id, row.get("sentence_index"))
        grouped.setdefault(key, []).append(_text(row.get("clause_text")))
    for beat in narration["narration_beats"]:
        for sentence_index, sentence in enumerate(beat["sentences"], 1):
            covered = "".join(_coverage_text(text)
                              for text in grouped.get((beat["narration_id"], sentence_index), []))
            if covered != _coverage_text(sentence):
                errors.append(f"clause_coverage_invalid:{beat['narration_id']}:{sentence_index}")
    qa = result.get("qa") if isinstance(result.get("qa"), dict) else {}
    expected_metrics = _metrics(clauses, sum(len(beat["sentences"])
                                             for beat in narration["narration_beats"]))
    if qa.get("metrics") != expected_metrics:
        errors.append("qa_metrics_stale")
    rejected, semantic_errors = _semantic_findings(
        clauses,
        beat_index,
        evidence_index,
        evidence_sections,
        narration["core_question"],
    )
    expected_status = "REJECTED" if rejected else "PASSED"
    expected_entailment = "FAILED" if rejected else "PASSED"
    if result.get("qa_status") != expected_status:
        errors.append("qa_status_stale")
    critic = result.get("critic") if isinstance(result.get("critic"), dict) else {}
    if critic.get("independence") != "separate_call":
        errors.append("critic_independence_invalid")
    if critic.get("semantic_entailment") != expected_entailment:
        errors.append("semantic_entailment_stale")
    if sorted(_strings(qa.get("errors"))) != semantic_errors:
        errors.append("qa_errors_stale")
    critic_payload = {
        "clauses": [
            {
                field: row.get(field)
                for field in (
                    "narration_id",
                    "sentence_index",
                    "clause_text",
                    "clause_kind",
                    "verdict",
                    "evidence_ids",
                    "finding_codes",
                    "rationale",
                )
            }
            if isinstance(row, dict) else row
            for row in clauses
        ]
    }
    canonical = normalize_review(
        critic_payload, narration, plan, ir, resolution, pack
    )
    if result != canonical:
        errors.append("fidelity_not_canonical")
    return sorted(set(errors))


def review(
    narration: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
    *,
    caller: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one independent shadow critic call after validating all upstream data."""
    _require_valid_upstream(narration, plan, ir, resolution, pack)
    generation_status = narration.get("generation_status")
    if generation_status == "BLOCKED_UPSTREAM":
        return _empty_result(narration, "BLOCKED_UPSTREAM")
    if generation_status == "REJECTED_DRAFT":
        return _empty_result(narration, "REJECTED_UPSTREAM")
    if generation_status != "DRAFT_ACCEPTED":
        raise ValueError("spoken_narration_status_invalid")

    visible = prompt_payload(narration, plan, ir, resolution, pack)
    set_text_purpose("semantic_fidelity_shadow")
    invoke = caller or call_json
    try:
        payload = invoke(
            model=config.MODEL_V2_CRITIC,
            system=SYSTEM_PROMPT,
            user=json.dumps(visible, ensure_ascii=False, sort_keys=True),
            max_tokens=config.LLM_SELFCHECK_MAX_TOKENS,
        )
    except Exception as exc:
        return _empty_result(
            narration,
            "CRITIC_ERROR",
            errors=[f"critic_call_failed:{type(exc).__name__}"],
        )
    return normalize_review(payload, narration, plan, ir, resolution, pack)
