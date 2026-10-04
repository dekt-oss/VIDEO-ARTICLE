"""Phase 9 deterministic Shadow visual planner.

The planner converts validated narration beats into traceable visual stages,
mutations, and shot directives.  It does not call a model, select assets, render,
or enter the Production directive path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import content_complexity_gate


CONTRACT_VERSION = "visual-plan-v1"
PLANNER_STATUSES = frozenset({"READY", "BLOCKED_GATE"})

_VISUAL_MODE_BY_STAGE = {
    "HOOK": "QUESTION",
    "SETUP": "PREREQUISITE",
    "CONFLICT": "PHENOMENON",
    "EXPLANATION": "SCHEMATIC",
    "EVIDENCE": "DATA",
    "PAYOFF": "RESULT",
    "BOUNDARY": "BOUNDARY",
}
_SEQUENCE_ROLE_BY_MODE = {
    "QUESTION": "FRAMING",
    "PREREQUISITE": "FRAMING",
    "PHENOMENON": "REALITY_ANCHOR",
    "SCHEMATIC": "RESULT_SEQUENCE",
    "MECHANISM": "MECHANISM_SEQUENCE",
    "DATA": "RESULT_SEQUENCE",
    "RESULT": "RESULT_SEQUENCE",
    "BOUNDARY": "FRAMING",
}
_OPERATION_BY_MODE = {
    "QUESTION": "REVEAL",
    "PREREQUISITE": "REVEAL",
    "PHENOMENON": "ISOLATE",
    "SCHEMATIC": "FLOW",
    "MECHANISM": "FLOW",
    "DATA": "ACCUMULATE",
    "RESULT": "REVEAL",
    "BOUNDARY": "ISOLATE",
}
_MUTATION_BY_MODE = {
    "QUESTION": "APPEAR",
    "PREREQUISITE": "APPEAR",
    "PHENOMENON": "HIGHLIGHT",
    "SCHEMATIC": "HIGHLIGHT",
    "MECHANISM": "TRANSFORM",
    "DATA": "GROW",
    "RESULT": "HIGHLIGHT",
    "BOUNDARY": "DIM",
}
_DEFAULT_RELATION_BY_STAGE = {
    "HOOK": "QUESTION_TO_CONTEXT",
    "SETUP": "WHOLE_TO_PART",
    "CONFLICT": "PHENOMENON_TO_CAUSE",
    "EXPLANATION": "PROCESS_NEXT",
    "EVIDENCE": "MECHANISM_TO_RESULT",
    "PAYOFF": "RESULT_TO_PAYOFF",
    "BOUNDARY": "RESULT_TO_LIMIT",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _transition(relation: str) -> str:
    relation = relation.upper()
    if relation == "SUPPORTS":
        return "GRAPHIC_MATCH"
    if relation == "CONTINUES":
        return "OBJECT_FOLLOW"
    if relation == "QUALIFIES":
        return "CUTAWAY"
    if "WHOLE_TO_PART" in relation:
        return "PUSH_IN"
    if "PART_TO_WHOLE" in relation or "PAYOFF" in relation:
        return "PULL_OUT"
    if "PROCESS" in relation:
        return "OBJECT_FOLLOW"
    if "RESULT" in relation and "LIMIT" not in relation:
        return "GRAPHIC_MATCH"
    if "CAUSE" in relation or "LIMIT" in relation:
        return "CUTAWAY"
    return "HARD_CUT"


def _camera(transition: str) -> str:
    return {
        "PUSH_IN": "DOLLY_IN",
        "PULL_OUT": "DOLLY_OUT",
        "OBJECT_FOLLOW": "FOLLOW_OBJECT",
        "CUTAWAY": "HOLD",
        "GRAPHIC_MATCH": "HOLD",
        "HARD_CUT": "HOLD",
    }[transition]


def _entity_ref(beat: dict[str, Any]) -> str:
    if ids := _strings(beat.get("reasoning_ids")):
        return f"reasoning:{ids[0]}"
    if ids := _strings(beat.get("concept_ids")):
        return f"concept:{ids[0]}"
    if ids := _strings(beat.get("evidence_ids")):
        return f"evidence:{ids[0]}"
    return f"narration:{_text(beat.get('narration_id'))}"


def blocked_from_gate(gate: dict[str, Any], content_id: str, domain: str) -> dict[str, Any]:
    """Create the only legal Phase 9 output for a non-ready Phase 8 gate."""
    status = _text(gate.get("gate_status")) or "UNKNOWN"
    if status not in {"ACTION_REQUIRED", "BLOCKED_UPSTREAM"}:
        raise ValueError("gate_is_ready" if status == "READY" else "gate_status_invalid")
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": domain,
        "content_id": content_id,
        "planner_status": "BLOCKED_GATE",
        "core_question": "",
        "sequences": [],
        "visual_beats": [],
        "constraints": deepcopy(gate.get("constraints") or {}),
        "qa": {
            "errors": [f"content_complexity_gate_not_ready:{status}"],
            "warnings": [],
            "metrics": {
                "visual_beat_count": 0,
                "traced_stage_count": 0,
                "mechanism_stage_count": 0,
            },
        },
    }


def _build_ready(
    gate: dict[str, Any],
    narration: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    plan_by_id = {row["beat_id"]: row for row in plan["beats"]}
    mechanism_ids = set(_strings(gate["constraints"].get("mechanism_reasoning_ids")))
    mechanism_allowed = gate["constraints"].get("mechanism_visual_allowed") is True
    visual_beats: list[dict[str, Any]] = []
    previous_transition = "HARD_CUT"

    for position, narration_beat in enumerate(narration["narration_beats"], 1):
        beat_id = narration_beat["beat_id"]
        source_beat = plan_by_id[beat_id]
        reasoning_ids = _strings(narration_beat.get("reasoning_ids"))
        stage_name = narration_beat["stage"]
        visual_mode = _VISUAL_MODE_BY_STAGE[stage_name]
        if (
            stage_name == "EXPLANATION"
            and mechanism_allowed
            and any(reasoning_id in mechanism_ids for reasoning_id in reasoning_ids)
        ):
            visual_mode = "MECHANISM"
        relation = (
            _strings(source_beat.get("transition_relations")) or
            [_DEFAULT_RELATION_BY_STAGE[stage_name]]
        )[0]
        transition_out = _transition(relation)
        entity_ref = _entity_ref(narration_beat)
        evidence_ids = _strings(narration_beat.get("evidence_ids"))
        raw_refs = _strings(narration_beat.get("raw_refs"))
        causal_levels = _strings(narration_beat.get("causal_levels"))
        uncertainties = _strings(narration_beat.get("uncertainties"))
        attributions = _strings(narration_beat.get("attributions"))
        stage_id = f"VS{position:02d}"
        mutation = {
            "mutation_id": f"VM{position:02d}",
            "entity_ref": entity_ref,
            "operation": _MUTATION_BY_MODE[visual_mode],
            "result_state_ref": entity_ref,
            "reasoning_ids": reasoning_ids,
            "evidence_ids": evidence_ids,
        }
        visual_beats.append({
            "visual_beat_id": f"VB{position:02d}",
            "beat_id": beat_id,
            "narration_id": narration_beat["narration_id"],
            "purpose": source_beat["purpose"],
            "visual_mode": visual_mode,
            "representation_mode": "SCHEMATIC_PRINCIPLE",
            "reasoning_ids": reasoning_ids,
            "evidence_ids": evidence_ids,
            "raw_refs": raw_refs,
            "concept_ids": _strings(narration_beat.get("concept_ids")),
            "knowledge_refs": _strings(narration_beat.get("knowledge_refs")),
            "causal_levels": causal_levels,
            "uncertainties": uncertainties,
            "attributions": attributions,
            "transition_relation": relation,
            "stage": {
                "stage_id": stage_id,
                "sequence_id": "",
                "operation": _OPERATION_BY_MODE[visual_mode],
                "camera_operation": _camera(transition_out),
                "continuity_mode": "NEW_WORLD" if position == 1 else "CONTINUE_WORLD",
                "mutations": [mutation],
            },
            "shot_directive": {
                "shot_id": f"SHOT{position:02d}",
                "stage_id": stage_id,
                "camera_operation": _camera(transition_out),
                "action": _OPERATION_BY_MODE[visual_mode],
                "transition_in": previous_transition,
                "transition_out": transition_out,
                "narration_refs": [narration_beat["narration_id"]],
                "reasoning_ids": reasoning_ids,
                "data_refs": evidence_ids,
                "source_refs": raw_refs,
                "causal_levels": causal_levels,
                "uncertainties": uncertainties,
                "attributions": attributions,
            },
        })
        previous_transition = transition_out

    sequences: list[dict[str, Any]] = []
    for visual_beat in visual_beats:
        role = _SEQUENCE_ROLE_BY_MODE[visual_beat["visual_mode"]]
        if not sequences or sequences[-1]["sequence_role"] != role:
            sequences.append({
                "sequence_id": f"VSEQ{len(sequences) + 1:02d}",
                "sequence_role": role,
                "stage_ids": [],
            })
        sequence = sequences[-1]
        stage_id = visual_beat["stage"]["stage_id"]
        sequence["stage_ids"].append(stage_id)
        visual_beat["stage"]["sequence_id"] = sequence["sequence_id"]

    for sequence in sequences:
        if sequence["sequence_role"] == "MECHANISM_SEQUENCE" and len(sequence["stage_ids"]) < 2:
            sequence["sequence_role"] = "RESULT_SEQUENCE"
    first_stages = {sequence["stage_ids"][0] for sequence in sequences}
    for visual_beat in visual_beats:
        visual_beat["stage"]["continuity_mode"] = (
            "NEW_WORLD" if visual_beat["stage"]["stage_id"] in first_stages
            else "CONTINUE_WORLD"
        )

    traced = sum(
        1 for row in visual_beats
        if any((row["reasoning_ids"], row["evidence_ids"], row["concept_ids"], row["knowledge_refs"]))
    )
    mechanism_count = sum(row["visual_mode"] == "MECHANISM" for row in visual_beats)
    warnings = []
    if not mechanism_allowed:
        warnings.append("mechanism_visual_forbidden")
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": narration["domain"],
        "content_id": narration["content_id"],
        "planner_status": "READY",
        "core_question": narration["core_question"],
        "sequences": sequences,
        "visual_beats": visual_beats,
        "constraints": deepcopy(gate["constraints"]),
        "qa": {
            "errors": [],
            "warnings": warnings,
            "metrics": {
                "visual_beat_count": len(visual_beats),
                "traced_stage_count": traced,
                "mechanism_stage_count": mechanism_count,
            },
        },
    }


def build(
    content_plan: dict[str, Any],
    gate: dict[str, Any],
    narration: dict[str, Any],
    fidelity: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical Phase 9 plan; only a canonical READY gate may emit stages."""
    gate_errors = content_complexity_gate.validate(
        gate, content_plan, narration, fidelity, plan, ir, resolution, pack,
        overrides=overrides,
    )
    if gate_errors:
        raise ValueError("content_complexity_gate_invalid:" + ",".join(gate_errors))
    if gate["gate_status"] != "READY":
        return blocked_from_gate(gate, pack["content_id"], pack["domain"])
    result = _build_ready(gate, narration, plan)
    errors = _reference_errors(result, ir, pack)
    if errors:
        raise ValueError("visual_plan_invalid:" + ",".join(errors))
    return result


def _reference_errors(result: dict[str, Any], ir: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    known_reasoning = {
        _text(row.get("reasoning_id")) for row in ir.get("reasoning_units") or []
        if isinstance(row, dict)
    }
    known_evidence = {
        _text(row.get("evidence_id"))
        for field in ("claims", "numbers", "risks", "limitations", "background_context")
        for row in pack.get(field) or [] if isinstance(row, dict)
    }
    errors: list[str] = []
    for visual_beat in result.get("visual_beats") or []:
        containers = [visual_beat, visual_beat.get("shot_directive") or {}]
        containers.extend((visual_beat.get("stage") or {}).get("mutations") or [])
        for container in containers:
            for reasoning_id in _strings(container.get("reasoning_ids")):
                if reasoning_id not in known_reasoning:
                    errors.append(f"unknown_reasoning_id:{reasoning_id}")
            for evidence_id in _strings(container.get("evidence_ids")) + _strings(container.get("data_refs")):
                if evidence_id not in known_evidence:
                    errors.append(f"unknown_evidence_id:{evidence_id}")
    return sorted(set(errors))


def validate(
    result: Any,
    content_plan: dict[str, Any],
    gate: dict[str, Any],
    narration: dict[str, Any],
    fidelity: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> list[str]:
    """Reject foreign refs and any stored result that differs from canonical output."""
    if not isinstance(result, dict):
        return ["visual_plan_not_dict"]
    errors: list[str] = []
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if result.get("planner_status") not in PLANNER_STATUSES:
        errors.append("planner_status_invalid")
    errors.extend(_reference_errors(result, ir, pack))
    try:
        canonical = build(
            content_plan, gate, narration, fidelity, plan, ir, resolution, pack,
            overrides=overrides,
        )
    except ValueError as exc:
        errors.append(str(exc))
        return sorted(set(errors))
    if result != canonical:
        errors.append("visual_plan_not_canonical")
    return sorted(set(errors))
