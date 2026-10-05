"""Phase 5 deterministic shadow narrative planner.

This module orders already validated explanation material. It does not write
narration, call a model, or infer missing prerequisite knowledge.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import config, explanation_ir, prerequisite_resolver, spoken_numbers


CONTRACT_VERSION = "narrative-plan-v1"
STAGES = frozenset({
    "HOOK", "SETUP", "CONFLICT", "EXPLANATION", "EVIDENCE", "PAYOFF", "BOUNDARY",
})
STATUSES = frozenset({"READY", "BLOCKED_PREREQUISITE", "BLOCKED_NO_REASONING"})
_STAGE_BY_ROLE = {
    "phenomenon": "CONFLICT",
    "prerequisite": "SETUP",
    "cause": "EXPLANATION",
    "mechanism": "EXPLANATION",
    "bridge": "EXPLANATION",
    "result": "EVIDENCE",
    "limitation": "BOUNDARY",
    "risk": "BOUNDARY",
    "payoff": "PAYOFF",
}


#: 시청자 순서(논문). 원문 순서는 근거가 쌓인 순서라 가장 흥미로운 결과가 뒤에 묻힌다(2026-10-05 실측).
#  선행 개념(SETUP)이 맨 앞, 한계(BOUNDARY)가 맨 끝 — Production 4막(문제 → 상황 → 반전·원리 → 결과)과 같은 흐름.
_AUDIENCE_STAGE_RANK = {
    "SETUP": 0, "CONFLICT": 1, "EVIDENCE": 2, "EXPLANATION": 3, "PAYOFF": 4, "BOUNDARY": 5,
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


_QUALIFYING_ROLES = frozenset({"limitation", "risk"})


def audience_order(ir: dict[str, Any], reasoning_ids: list[str]) -> list[str]:
    """비트로 놓을 논증 단위 순서. 논문은 시청자 순서, 리포트·스위치 꺼짐은 원문 순서 그대로.

    ★ 한계는 **자기가 꾸미는 결과 바로 뒤**에 남는다(결과 + 그 한계 = 한 묶음, 묶음 단위로 정렬). 한계만
      끝으로 모으면 "개별 수면 에피소드의 지속 시간 자체는 변하지 않았다"가 무엇의 한계인지 모르는 문장이 된다.
    """
    if ir.get("domain") != "paper" or not config.V2_AUDIENCE_ORDER:
        return list(reasoning_ids)
    roles = {unit.get("reasoning_id"): unit.get("role") for unit in ir.get("reasoning_units") or []}
    groups: list[list[str]] = []
    for rid in reasoning_ids:
        if groups and roles.get(rid) in _QUALIFYING_ROLES:
            groups[-1].append(rid)
        else:
            groups.append([rid])
    groups.sort(key=lambda group: _AUDIENCE_STAGE_RANK.get(
        _STAGE_BY_ROLE.get(roles.get(group[0]), ""), 9))           # 안정 정렬 — 같은 순위는 원문 순서
    return [rid for group in groups for rid in group]


def hook_units(ir: dict[str, Any], kept_ids: list[str]) -> list[dict[str, Any]]:
    """첫 질문의 재료 — 이 편에 실린 **주요 발견 전부**(한계·리스크 제외). 어느 것이 가장 흥미로운지는
    대본 모델이 고른다. 코드로 고르면 틀린다: 실측 신피질 논문은 주요 결과 7개가 모두 main_result 였고
    핵심 주장(thesis)은 Fact Sheet 첫 주장(해부학)이라, 제목의 요점인 '수면'을 못 골랐다(2026-10-05)."""
    if not config.V2_CONTENT_HOOK:
        return []
    return [unit for unit in ir.get("reasoning_units") or []
            if unit.get("reasoning_id") in kept_ids and unit.get("role") not in _QUALIFYING_ROLES]


def hook_fields(ir: dict[str, Any], kept_ids: list[str]) -> dict[str, Any]:
    """HOOK 비트에 얹는 재료와 근거. 재료 문장은 대본 숫자 검사·검증관 대조의 기준이 된다."""
    units = hook_units(ir, kept_ids)
    return {"hook_material": [_text(unit.get("text")) for unit in units],
            "evidence_ids": _unique_from_units(units, "evidence_ids"),
            "raw_refs": _unique_from_units(units, "raw_refs")}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _resolution_errors(resolution: Any, ir: dict[str, Any]) -> list[str]:
    if not isinstance(resolution, dict):
        return ["resolution_not_dict"]
    errors: list[str] = []
    if resolution.get("contract_version") != "prerequisite-resolution-v1":
        errors.append("contract_version_invalid")
    if resolution.get("domain") != ir.get("domain"):
        errors.append("domain_mismatch")
    if resolution.get("content_id") != ir.get("content_id"):
        errors.append("content_id_mismatch")
    concepts = resolution.get("concepts")
    if not isinstance(concepts, list):
        return sorted(set(errors + ["concepts_not_list"]))
    required_unresolved: list[str] = []
    all_unresolved: list[str] = []
    for position, concept in enumerate(concepts, 1):
        if not isinstance(concept, dict):
            errors.append(f"concept_invalid:{position}")
            continue
        concept_id = _text(concept.get("concept_id"))
        status = concept.get("status")
        if not concept_id:
            errors.append(f"concept_id_missing:{position}")
        if status not in {"RESOLVED_SOURCE", "RESOLVED_GLOSSARY", "UNRESOLVED"}:
            errors.append(f"concept_status_invalid:{concept_id or position}")
        if status == "UNRESOLVED":
            all_unresolved.append(concept_id)
            if concept.get("required") is not False:
                required_unresolved.append(concept_id)
        elif not _text(concept.get("simple_explanation")):
            errors.append(f"concept_explanation_missing:{concept_id}")
    if resolution.get("unresolved_concepts") != all_unresolved:
        errors.append("unresolved_concepts_invalid")
    expected_action = "NARROW_SCOPE" if required_unresolved else "KEEP"
    if resolution.get("scope_action") != expected_action:
        errors.append("scope_action_invalid")
    return sorted(set(errors))


def _unique_from_units(units: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    for unit in units:
        values.extend(_strings(unit.get(field)))
    return list(dict.fromkeys(values))


def _unique_from_concepts(concepts: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    for concept in concepts:
        values.extend(_strings(concept.get(field)))
    return list(dict.fromkeys(values))


def _beat(beat_id: str, stage: str, purpose: str, content_points: list[str], *,
          units: list[dict[str, Any]] | None = None,
          concepts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    units = units or []
    concepts = concepts or []
    return {
        "beat_id": beat_id,
        "stage": stage,
        "purpose": purpose,
        "content_points": content_points,
        "reasoning_ids": [_text(unit.get("reasoning_id")) for unit in units],
        "evidence_ids": list(dict.fromkeys(
            _unique_from_units(units, "evidence_ids")
            + _unique_from_concepts(concepts, "evidence_ids")
        )),
        "raw_refs": _unique_from_units(units, "raw_refs"),
        "concept_ids": [_text(concept.get("concept_id")) for concept in concepts],
        "knowledge_refs": list(dict.fromkeys(
            ref for concept in concepts for ref in _strings(concept.get("knowledge_refs"))
        )),
        "causal_levels": list(dict.fromkeys(
            value for unit in units if (value := _text(unit.get("causal_level")))
        )),
        "uncertainties": list(dict.fromkeys(
            value for unit in units if (value := _text(unit.get("uncertainty")))
        )),
        "attributions": list(dict.fromkeys(
            value for unit in units if (value := _text(unit.get("attribution")))
        )),
        "transition_relations": list(dict.fromkeys(
            value for unit in units if (value := _text(unit.get("transition_relation")))
        )),
    }


def _beat_points(beat: dict[str, Any]) -> list[tuple[str, str]]:
    """(근거 단위 ref, 그 단위의 문장) — 근거 비트는 reasoning_id, 선행개념 비트는 concept_id."""
    if beat.get("stage") == "HOOK":
        return []
    refs = _strings(beat.get("reasoning_ids")) or _strings(beat.get("concept_ids"))
    points = beat.get("content_points") if isinstance(beat.get("content_points"), list) else []
    return [(ref, _text(text)) for ref, text in zip(refs, points)]


def number_delivery(beats: list[dict[str, Any]], ir: dict[str, Any]) -> list[dict[str, Any]]:
    """비트마다 말로 읽을 숫자와 화면 카드로 보낼 문장(`spoken_numbers` 모듈 규칙).

    대본 재료(`content_points`)는 그대로 둔다(Phase 5 계약: IR 문장을 그대로 참조). 대신 어느
    숫자를 말하고 어느 문장을 화면에 띄울지만 정한다 — Phase 6 이 이것대로 말하게 하고, Phase 10
    이 화면 문장을 컷에 싣는다.
    """
    roles = {
        _text(unit.get("reasoning_id")): _text(unit.get("role"))
        for unit in ir.get("reasoning_units") or []
    }
    points = [
        {"ref": ref, "text": text, "role": roles.get(ref, "")}
        for beat in beats for ref, text in _beat_points(beat)
    ]
    decision = spoken_numbers.assign(points, thesis=_text(ir.get("thesis")))
    delivered: list[dict[str, Any]] = []
    for beat in beats:
        spoken: list[str] = []
        screen: list[dict[str, Any]] = []
        for ref, text in _beat_points(beat):
            row = decision.get(ref)
            if not row:
                continue
            if row["spoken"]:
                spoken.extend(row["numbers"])
            else:
                screen.append({"ref": ref, "text": text, "numbers": list(row["numbers"])})
        delivered.append({"spoken_numbers": sorted(spoken), "screen_facts": screen})
    return delivered


_CONSTRAINT_ROLES = frozenset({"risk", "limitation"})
_CONCLUSION_ROLES = frozenset({"payoff", "result"})


def select_for_length(ir: dict[str, Any], budget: int | None = None) -> tuple[list[str], list[str]]:
    """한 편에 담을 근거 단위를 고른다(설계 점검 D). 반환: (담을 reasoning_id, 뺄 reasoning_id) — 이야기 순서.

    우선순위(같은 등급 안에서는 이야기 순서):
      0) 핵심 흐름 — 리포트는 첫 단위와 같은 증권사 논리(R01…)의 단계들, 논문은 제약 아닌 앞쪽 3단위
      1) 결론 — payoff(목표가·밸류에이션) / result
      2) 리스크·한계 하나
      3) 나머지
    분량(`V2_NARRATION_TARGET_CHARS`)을 넘기는 단위는 건너뛰고 다음 단위를 본다. 첫 단위는 분량과 무관하게
    담는다(빈 대본 방지). 결정론적이며 모델 판단이 없다.
    """
    units = [u for u in ir.get("reasoning_units") or [] if isinstance(u, dict)]
    if not units:
        return [], []
    limit = config.V2_NARRATION_TARGET_CHARS if budget is None else budget
    first_chain = _text(units[0].get("source_reasoning_id"))
    first_constraint = next((u for u in units if u.get("role") in _CONSTRAINT_ROLES), {})
    # 리스크는 같은 논리의 단계를 묶어서 담는다 — "피크아웃 우려"만 담고 "그러나 매수 기회"를 빼면
    # 우려만 남고 결론이 없다(Samsung 실측).
    constraint_chain = _text(first_constraint.get("source_reasoning_id"))

    def tier(position: int, unit: dict[str, Any]) -> int:
        role = unit.get("role")
        if role in _CONSTRAINT_ROLES:
            same = (_text(unit.get("source_reasoning_id")) == constraint_chain if constraint_chain
                    else unit is first_constraint)
            return 2 if same else 3
        if first_chain and _text(unit.get("source_reasoning_id")) == first_chain:
            return 0
        if not first_chain and position < 3:
            return 0
        return 1 if role in _CONCLUSION_ROLES else 3

    ranked = sorted(enumerate(units), key=lambda item: (tier(*item), item[0]))
    kept: set[str] = set()
    used = 0
    for position, unit in ranked:
        size = len(_text(unit.get("text")))
        # 리스크 논리(등급 2)는 분량을 넘어도 끝까지 담는다 — 반론("그러나 매수 기회")이 잘리면 표현이 깨진다.
        if kept and used + size > limit and tier(position, unit) != 2:
            continue
        kept.add(_text(unit.get("reasoning_id")))
        used += size
    chain = [_text(u.get("reasoning_id")) for u in units]
    return [rid for rid in chain if rid in kept], [rid for rid in chain if rid not in kept]


def _build(ir: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    unresolved_required = [
        concept for concept in resolution["concepts"]
        if concept.get("status") == "UNRESOLVED" and concept.get("required") is not False
    ]
    warnings = _strings(ir.get("warnings")) + _strings(resolution.get("warnings"))
    if unresolved_required:
        warnings.extend(
            f"required_prerequisite_unresolved:{_text(concept.get('concept_id'))}"
            for concept in unresolved_required
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "domain": ir.get("domain"),
            "content_id": ir.get("content_id"),
            "planning_status": "BLOCKED_PREREQUISITE",
            "core_question": ir.get("core_question"),
            "thesis": ir.get("thesis"),
            "beats": [],
            "excluded_reasoning_ids": list(ir.get("explanation_chain") or []),
            "warnings": sorted(set(warnings)),
            "source": deepcopy(ir.get("source") or {}),
        }
    if not ir.get("reasoning_units"):
        warnings.append("reasoning_units_missing")
        return {
            "contract_version": CONTRACT_VERSION,
            "domain": ir.get("domain"),
            "content_id": ir.get("content_id"),
            "planning_status": "BLOCKED_NO_REASONING",
            "core_question": ir.get("core_question"),
            "thesis": ir.get("thesis"),
            "beats": [],
            "excluded_reasoning_ids": [],
            "warnings": sorted(set(warnings)),
            "source": deepcopy(ir.get("source") or {}),
        }

    beats: list[dict[str, Any]] = []
    kept_ids, excluded_ids = select_for_length(ir)
    hook = _beat("NB01", "HOOK", "open_core_question", [ir["core_question"]])
    hook.update(hook_fields(ir, kept_ids))
    beats.append(hook)
    resolved = [
        concept for concept in resolution["concepts"]
        if concept.get("status") in {"RESOLVED_SOURCE", "RESOLVED_GLOSSARY"}
    ]
    if resolved:
        beats.append(_beat(
            f"NB{len(beats) + 1:02d}", "SETUP", "establish_prerequisite",
            [_text(concept.get("simple_explanation")) for concept in resolved], concepts=resolved,
        ))

    if excluded_ids:
        warnings.extend(f"length_budget_excluded:{rid}" for rid in excluded_ids)
    grouped: list[tuple[str, list[dict[str, Any]]]] = []
    unit_by_id = {unit.get("reasoning_id"): unit for unit in ir.get("reasoning_units") or []}
    for rid in audience_order(ir, kept_ids):
        unit = unit_by_id[rid]
        stage = _STAGE_BY_ROLE[unit["role"]]
        # 한 비트에 발견 두 개까지 — 실측 비트 하나에 결과 다섯 개가 몰려 한 문단짜리 대사가 됐다.
        if grouped and grouped[-1][0] == stage and len(grouped[-1][1]) < config.V2_MAX_UNITS_PER_BEAT:
            grouped[-1][1].append(unit)
        else:
            grouped.append((stage, [unit]))
    for stage, units in grouped:
        beats.append(_beat(
            f"NB{len(beats) + 1:02d}", stage, f"carry_{stage.lower()}_logic",
            [_text(unit.get("text")) for unit in units], units=units,
        ))
    for beat, delivery in zip(beats, number_delivery(beats, ir)):
        beat["number_delivery"] = delivery

    return {
        "contract_version": CONTRACT_VERSION,
        "domain": ir.get("domain"),
        "content_id": ir.get("content_id"),
        "planning_status": "READY",
        "core_question": ir.get("core_question"),
        "thesis": ir.get("thesis"),
        "beats": beats,
        "excluded_reasoning_ids": excluded_ids,
        "warnings": sorted(set(warnings)),
        "source": deepcopy(ir.get("source") or {}),
    }


def build(ir: dict[str, Any], resolution: dict[str, Any],
          pack: dict[str, Any]) -> dict[str, Any]:
    """Build a narrative order without adding facts or rewriting explanation text."""
    ir_errors = explanation_ir.validate(ir, pack)
    if ir_errors:
        raise ValueError("explanation_ir_invalid:" + ",".join(ir_errors))
    resolution_errors = _resolution_errors(resolution, ir)
    resolution_errors.extend(prerequisite_resolver.validate(resolution, ir, pack))
    if resolution_errors:
        raise ValueError("prerequisite_resolution_invalid:" + ",".join(resolution_errors))
    plan = _build(ir, resolution)
    errors = validate(plan, ir, resolution, pack)
    if errors:
        raise ValueError("narrative_plan_invalid:" + ",".join(errors))
    return plan


def validate(plan: Any, ir: dict[str, Any], resolution: dict[str, Any],
             pack: dict[str, Any]) -> list[str]:
    """Validate stable references and exact, non-synthesized content points."""
    if not isinstance(plan, dict):
        return ["plan_not_dict"]
    upstream_errors = [
        f"explanation_ir_invalid:{error}" for error in explanation_ir.validate(ir, pack)
    ]
    upstream_errors.extend(
        f"prerequisite_resolution_invalid:{error}"
        for error in prerequisite_resolver.validate(resolution, ir, pack)
    )
    if upstream_errors:
        return sorted(set(upstream_errors))
    errors: list[str] = []
    if plan.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if plan.get("domain") != ir.get("domain"):
        errors.append("domain_mismatch")
    if plan.get("content_id") != ir.get("content_id"):
        errors.append("content_id_mismatch")
    if plan.get("planning_status") not in STATUSES:
        errors.append("planning_status_invalid")
    if plan.get("core_question") != ir.get("core_question"):
        errors.append("core_question_invalid")
    if plan.get("thesis") != ir.get("thesis"):
        errors.append("thesis_invalid")
    beats = plan.get("beats")
    if not isinstance(beats, list):
        return sorted(set(errors + ["beats_not_list"]))

    unit_index = {unit["reasoning_id"]: unit for unit in ir.get("reasoning_units") or []}
    blocked_plan = plan.get("planning_status") != "READY"
    concept_index = {concept["concept_id"]: concept for concept in resolution.get("concepts") or []}
    seen_reasoning: list[str] = []
    for position, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            errors.append(f"beat_invalid:{position}")
            continue
        beat_id = _text(beat.get("beat_id"))
        if beat_id != f"NB{position:02d}":
            errors.append(f"beat_id_invalid:{beat_id or position}")
        if beat.get("stage") not in STAGES:
            errors.append(f"beat_stage_invalid:{beat_id or position}")
        reasoning_ids = _strings(beat.get("reasoning_ids"))
        unknown = [rid for rid in reasoning_ids if rid not in unit_index]
        errors.extend(f"reasoning_ref_unknown:{beat_id}:{rid}" for rid in unknown)
        seen_reasoning.extend(rid for rid in reasoning_ids if rid in unit_index)
        concept_ids = _strings(beat.get("concept_ids"))
        if any(cid not in concept_index for cid in concept_ids):
            errors.append(f"concept_ref_unknown:{beat_id}")

        if beat.get("stage") == "HOOK":
            expected_points = [ir.get("core_question")]
            expected_hook = hook_fields(ir, select_for_length(ir)[0]) if not blocked_plan else {}
            if beat.get("hook_material", []) != expected_hook.get("hook_material", []):
                errors.append(f"hook_material_invalid:{beat_id or position}")
        elif concept_ids:
            expected_points = [concept_index[cid].get("simple_explanation") for cid in concept_ids]
        else:
            expected_points = [unit_index[rid].get("text") for rid in reasoning_ids if rid in unit_index]
        if beat.get("content_points") != expected_points:
            errors.append(f"content_points_invalid:{beat_id or position}")
        expected_units = [unit_index[rid] for rid in reasoning_ids if rid in unit_index]
        expected_concepts = [concept_index[cid] for cid in concept_ids if cid in concept_index]
        expected_evidence = list(dict.fromkeys(
            _unique_from_units(expected_units, "evidence_ids")
            + _unique_from_concepts(expected_concepts, "evidence_ids")
        ))
        if beat.get("stage") == "HOOK" and not blocked_plan:
            expected_evidence = hook_fields(ir, select_for_length(ir)[0])["evidence_ids"]
        if beat.get("evidence_ids") != expected_evidence:
            errors.append(f"evidence_refs_invalid:{beat_id or position}")
        expected_raw = (hook_fields(ir, select_for_length(ir)[0])["raw_refs"]
                        if beat.get("stage") == "HOOK" and not blocked_plan
                        else _unique_from_units(expected_units, "raw_refs"))
        if beat.get("raw_refs") != expected_raw:
            errors.append(f"raw_refs_invalid:{beat_id or position}")
        expected_knowledge = _unique_from_concepts(expected_concepts, "knowledge_refs")
        if beat.get("knowledge_refs") != expected_knowledge:
            errors.append(f"knowledge_refs_invalid:{beat_id or position}")
        expected_causal = list(dict.fromkeys(
            value for unit in expected_units if (value := _text(unit.get("causal_level")))
        ))
        if beat.get("causal_levels") != expected_causal:
            errors.append(f"causal_levels_invalid:{beat_id or position}")
        expected_uncertainties = list(dict.fromkeys(
            value for unit in expected_units if (value := _text(unit.get("uncertainty")))
        ))
        if beat.get("uncertainties") != expected_uncertainties:
            errors.append(f"uncertainties_invalid:{beat_id or position}")
        expected_attributions = list(dict.fromkeys(
            value for unit in expected_units if (value := _text(unit.get("attribution")))
        ))
        if beat.get("attributions") != expected_attributions:
            errors.append(f"attributions_invalid:{beat_id or position}")
        expected_transitions = list(dict.fromkeys(
            value for unit in expected_units if (value := _text(unit.get("transition_relation")))
        ))
        if beat.get("transition_relations") != expected_transitions:
            errors.append(f"transition_relations_invalid:{beat_id or position}")

    blocked_prerequisite = resolution.get("scope_action") == "NARROW_SCOPE"
    blocked_no_reasoning = not ir.get("reasoning_units") and not blocked_prerequisite
    blocked = blocked_prerequisite or blocked_no_reasoning
    expected_status = (
        "BLOCKED_PREREQUISITE" if blocked_prerequisite
        else "BLOCKED_NO_REASONING" if blocked_no_reasoning
        else "READY"
    )
    if plan.get("planning_status") != expected_status:
        errors.append("planning_status_scope_mismatch")
    expected_chain = list(ir.get("explanation_chain") or [])
    if blocked:
        if beats:
            errors.append("blocked_plan_has_beats")
        if plan.get("excluded_reasoning_ids") != expected_chain:
            errors.append("blocked_excluded_reasoning_invalid")
    else:
        kept_ids, excluded_ids = select_for_length(ir)
        if seen_reasoning != audience_order(ir, kept_ids):
            errors.append("reasoning_chain_coverage_invalid")
        valid_beats = [beat for beat in beats if isinstance(beat, dict)]
        for beat, expected in zip(valid_beats, number_delivery(valid_beats, ir)):
            if beat.get("number_delivery") != expected:
                errors.append(f"number_delivery_invalid:{_text(beat.get('beat_id'))}")
        if plan.get("excluded_reasoning_ids") != excluded_ids:
            errors.append("ready_excluded_reasoning_invalid")
        setup_positions = [i for i, beat in enumerate(beats) if beat.get("stage") == "SETUP"
                           and beat.get("concept_ids")]
        reasoning_positions = [i for i, beat in enumerate(beats) if beat.get("reasoning_ids")]
        if setup_positions and reasoning_positions and max(setup_positions) > min(reasoning_positions):
            errors.append("prerequisite_after_reasoning")
    return sorted(set(errors))
