"""Phase 10 deterministic projection from a validated Visual Plan to a directive shape.

This module is intentionally Shadow-only.  It does not write to the database, call a
model, select assets, render, or import itself into the Production directive path.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from . import config


CONTRACT_VERSION = "explanation-directive-shadow-v1"
SUPPORTED_VERSIONS = frozenset({"comic", "image_sequence", "photo"})

_BEAT_BY_MODE = {
    "QUESTION": "QUESTION",
    "PREREQUISITE": "SCOPE",
    "PHENOMENON": "EXPERIMENT_SETUP",
    "SCHEMATIC": "MECHANISM",
    "MECHANISM": "MECHANISM",
    "DATA": "RESULT",
    "RESULT": "CONCLUSION",
    "BOUNDARY": "LIMITATION",
}
_TRANSITION = {
    "GRAPHIC_MATCH": "crossfade",
    "PULL_OUT": "crossfade",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _evidence_rows(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(row.get("evidence_id")): row
        for field in ("claims", "numbers", "risks", "limitations", "background_context")
        for row in pack.get(field) or []
        if isinstance(row, dict) and _text(row.get("evidence_id"))
    }


def _claim_ids(raw_refs: list[str]) -> list[str]:
    return list(dict.fromkeys(ref.rsplit(":", 1)[-1] for ref in raw_refs if ref))


def _duration(text: str) -> int:
    visible = len("".join(text.split()))
    return max(3, min(8, math.ceil(visible / 12)))


def _narration_map(narration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(row.get("narration_id")): row
        for row in narration.get("narration_beats") or []
        if isinstance(row, dict) and _text(row.get("narration_id"))
    }


def _entity_ref(beat: dict[str, Any]) -> str:
    if ids := _strings(beat.get("reasoning_ids")):
        return f"reasoning:{ids[0]}"
    if ids := _strings(beat.get("concept_ids")):
        return f"concept:{ids[0]}"
    if ids := _strings(beat.get("evidence_ids")):
        return f"evidence:{ids[0]}"
    return f"narration:{_text(beat.get('narration_id'))}"


def _expected_constraints(pack: dict[str, Any], ir: dict[str, Any]) -> dict[str, Any]:
    domain = _text(pack.get("domain"))
    source = pack.get("source") if isinstance(pack.get("source"), dict) else {}
    depth = _text(source.get("source_depth")) or "none"
    policies = config.SOURCE_ADEQUACY_POLICIES.get(domain) or {}
    policy = policies.get(depth) or policies.get("__default__") or {}
    mechanism_roles = {"cause", "mechanism"} if domain == "paper" else {"cause", "bridge"}
    mechanism_ids = [
        _text(row.get("reasoning_id"))
        for row in ir.get("reasoning_units") or []
        if isinstance(row, dict) and _text(row.get("role")) in mechanism_roles
    ]
    return {
        "source_depth": depth,
        "source_mode": _text(policy.get("source_mode")),
        "max_duration_sec": int(policy.get("max_duration_sec") or 0),
        "max_content_mode": _text(policy.get("max_content_mode")),
        "mechanism_visual_allowed": bool(mechanism_ids),
        "mechanism_reasoning_ids": mechanism_ids,
    }


def _input_errors(
    visual_plan: Any,
    narration: Any,
    ir: Any,
    pack: Any,
    version_type: str,
) -> list[str]:
    if not all(isinstance(item, dict) for item in (visual_plan, narration, ir, pack)):
        return ["projection_input_not_dict"]
    errors: list[str] = []
    if visual_plan.get("contract_version") != "visual-plan-v1":
        errors.append("visual_plan_contract_invalid")
    if visual_plan.get("planner_status") != "READY":
        errors.append("visual_plan_not_ready")
    if version_type not in SUPPORTED_VERSIONS:
        errors.append("version_type_invalid")
    identities = {
        (_text(item.get("domain")), _text(item.get("content_id")))
        for item in (visual_plan, narration, ir, pack)
    }
    if len(identities) != 1:
        errors.append("projection_identity_mismatch")
    if (visual_plan.get("qa") or {}).get("errors"):
        errors.append("visual_plan_has_errors")
    if _text(visual_plan.get("core_question")) != _text(narration.get("core_question")):
        errors.append("core_question_mismatch")
    if visual_plan.get("constraints") != _expected_constraints(pack, ir):
        errors.append("source_constraints_mismatch")

    narration_rows = narration.get("narration_beats") or []
    narration_ids = [_text(row.get("narration_id")) for row in narration_rows if isinstance(row, dict)]
    if not narration_ids or any(not narration_id for narration_id in narration_ids):
        errors.append("narration_id_invalid")
    if len(narration_ids) != len(set(narration_ids)):
        errors.append("narration_id_duplicate")
    narration_by_id = _narration_map(narration)
    known_narration = set(narration_ids)
    known_reasoning = {
        _text(row.get("reasoning_id"))
        for row in ir.get("reasoning_units") or [] if isinstance(row, dict)
    }
    evidence = _evidence_rows(pack)
    known_evidence = set(evidence)

    beats = visual_plan.get("visual_beats")
    sequences = visual_plan.get("sequences")
    if not isinstance(beats, list) or not beats:
        errors.append("visual_beats_empty")
        beats = []
    if not isinstance(sequences, list) or not sequences:
        errors.append("visual_sequences_empty")
        sequences = []

    sequence_stages: dict[str, str] = {}
    for sequence in sequences:
        if not isinstance(sequence, dict):
            errors.append("visual_sequence_invalid")
            continue
        sequence_id = _text(sequence.get("sequence_id"))
        for stage_id in _strings(sequence.get("stage_ids")):
            if stage_id in sequence_stages:
                errors.append(f"stage_in_multiple_sequences:{stage_id}")
            sequence_stages[stage_id] = sequence_id

    seen_beats: set[str] = set()
    seen_stages: set[str] = set()
    seen_shots: set[str] = set()
    seen_mutations: set[str] = set()
    used_narration: list[str] = []
    for beat in beats:
        if not isinstance(beat, dict):
            errors.append("visual_beat_invalid")
            continue
        visual_beat_id = _text(beat.get("visual_beat_id"))
        if not visual_beat_id or visual_beat_id in seen_beats:
            errors.append(f"visual_beat_id_invalid:{visual_beat_id or 'missing'}")
        seen_beats.add(visual_beat_id)
        stage = beat.get("stage") if isinstance(beat.get("stage"), dict) else {}
        shot = beat.get("shot_directive") if isinstance(beat.get("shot_directive"), dict) else {}
        stage_id = _text(stage.get("stage_id"))
        shot_id = _text(shot.get("shot_id"))
        if not stage_id or stage_id in seen_stages:
            errors.append(f"stage_id_invalid:{stage_id or visual_beat_id}")
        if not shot_id or shot_id in seen_shots:
            errors.append(f"shot_id_invalid:{shot_id or visual_beat_id}")
        seen_stages.add(stage_id)
        seen_shots.add(shot_id)
        if stage.get("sequence_id") != sequence_stages.get(stage_id):
            errors.append(f"stage_sequence_mismatch:{stage_id}")
        if shot.get("stage_id") != stage_id:
            errors.append(f"shot_stage_mismatch:{shot_id}")

        narration_refs = _strings(shot.get("narration_refs"))
        narration_id = _text(beat.get("narration_id"))
        used_narration.append(narration_id)
        if len(narration_refs) != 1 or narration_refs[0] not in known_narration:
            errors.append(f"narration_ref_invalid:{visual_beat_id}")
        elif narration_refs[0] != narration_id:
            errors.append(f"narration_ref_mismatch:{visual_beat_id}")
        narration_row = narration_by_id.get(narration_id) or {}
        reasoning_ids = _strings(beat.get("reasoning_ids"))
        evidence_ids = _strings(beat.get("evidence_ids"))
        raw_refs = _strings(beat.get("raw_refs"))
        concept_ids = _strings(beat.get("concept_ids"))
        knowledge_refs = _strings(beat.get("knowledge_refs"))
        provenance_fields = {
            "reasoning_ids": reasoning_ids,
            "evidence_ids": evidence_ids,
            "raw_refs": raw_refs,
            "concept_ids": concept_ids,
            "knowledge_refs": knowledge_refs,
        }
        if any(
            values != _strings(narration_row.get(field))
            for field, values in provenance_fields.items()
        ):
            errors.append(f"narration_provenance_mismatch:{visual_beat_id}")
        if _text(beat.get("beat_id")) != _text(narration_row.get("beat_id")):
            errors.append(f"narration_beat_mismatch:{visual_beat_id}")
        if _text(narration_row.get("stage")) != "HOOK" and not any(provenance_fields.values()):
            errors.append(f"factual_trace_empty:{visual_beat_id}")
        semantic_fields = ("causal_levels", "uncertainties", "attributions")
        if any(
            _strings(beat.get(field)) != _strings(narration_row.get(field))
            for field in semantic_fields
        ):
            errors.append(f"semantic_calibration_mismatch:{visual_beat_id}")
        if any(
            _strings(shot.get(field)) != _strings(beat.get(field))
            for field in semantic_fields
        ):
            errors.append(f"shot_semantic_calibration_mismatch:{shot_id}")
        for reasoning_id in reasoning_ids:
            if reasoning_id not in known_reasoning:
                errors.append(f"unknown_reasoning_id:{reasoning_id}")
        for evidence_id in evidence_ids:
            if evidence_id not in known_evidence:
                errors.append(f"unknown_evidence_id:{evidence_id}")
            else:
                state = _text(evidence[evidence_id].get("verification_state"))
                if state != "SUPPORTED":
                    errors.append(f"evidence_not_supported:{evidence_id}#{state or 'missing'}")
        expected_raw = [_text(evidence[evidence_id].get("raw_ref")) for evidence_id in evidence_ids
                        if evidence_id in evidence]
        if raw_refs != expected_raw:
            errors.append(f"raw_ref_mismatch:{visual_beat_id}")
        if _strings(shot.get("reasoning_ids")) != reasoning_ids:
            errors.append(f"shot_reasoning_mismatch:{shot_id}")
        if _strings(shot.get("data_refs")) != evidence_ids:
            errors.append(f"shot_evidence_mismatch:{shot_id}")
        if _strings(shot.get("source_refs")) != raw_refs:
            errors.append(f"shot_source_mismatch:{shot_id}")

        mutations = stage.get("mutations") if isinstance(stage.get("mutations"), list) else []
        if not mutations:
            errors.append(f"stage_mutations_empty:{stage_id}")
        for mutation in mutations:
            mutation_id = _text(mutation.get("mutation_id")) if isinstance(mutation, dict) else ""
            if not mutation_id or mutation_id in seen_mutations:
                errors.append(f"mutation_id_invalid:{mutation_id or stage_id}")
            seen_mutations.add(mutation_id)
            if not _text(mutation.get("entity_ref")):
                errors.append(f"mutation_entity_ref_empty:{mutation_id or stage_id}")
            elif _text(mutation.get("entity_ref")) != _entity_ref(narration_row):
                errors.append(f"mutation_entity_ref_mismatch:{mutation_id or stage_id}")
            if _strings(mutation.get("reasoning_ids")) != reasoning_ids:
                errors.append(f"mutation_reasoning_mismatch:{mutation_id}")
            if _strings(mutation.get("evidence_ids")) != evidence_ids:
                errors.append(f"mutation_evidence_mismatch:{mutation_id}")

    missing_stages = set(sequence_stages) - seen_stages
    errors.extend(f"sequence_stage_missing:{stage_id}" for stage_id in sorted(missing_stages))
    if used_narration != narration_ids:
        errors.append("narration_coverage_mismatch")
    return sorted(set(errors))

def _prompt(narration_text: str, mode: str, action: str) -> str:
    return (
        "Vertical educational visual. Show only this source-backed statement: "
        f"{narration_text} Visual mode: {mode}. Visible action: {action}. "
        "Do not add labels, numbers, objects, or causal steps not stated here."
    )


def _sequence_projection(
    visual_plan: dict[str, Any],
    narration_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    beat_by_stage = {
        beat["stage"]["stage_id"]: beat for beat in visual_plan["visual_beats"]
    }
    projected: list[dict[str, Any]] = []
    for sequence in visual_plan["sequences"]:
        sequence_beats = [beat_by_stage[stage_id] for stage_id in sequence["stage_ids"]]
        entity_refs = list(dict.fromkeys(
            _text(mutation.get("entity_ref"))
            for beat in sequence_beats
            for mutation in beat["stage"]["mutations"]
            if _text(mutation.get("entity_ref"))
        ))
        stages: list[dict[str, Any]] = []
        previous_stage_id = ""
        for beat in sequence_beats:
            stage = beat["stage"]
            shot = beat["shot_directive"]
            narration_row = narration_by_id[shot["narration_refs"][0]]
            narration_text = " ".join(_strings(narration_row.get("sentences")))
            raw_refs = _strings(beat.get("raw_refs"))
            mutations = [{
                "entity_id": _text(mutation.get("entity_ref")),
                "property": "state",
                "operation": _text(mutation.get("operation")) or "TRANSFORM",
                "visible_change": True,
                "result_state": narration_text,
                "claim_ids": _claim_ids(raw_refs),
            } for mutation in stage["mutations"]]
            stages.append({
                "stage_id": stage["stage_id"],
                "cut_refs": [visual_plan["visual_beats"].index(beat) + 1],
                "representation_mode": beat["representation_mode"],
                "allow_connective": False,
                "mutations": mutations,
                "operation": stage["operation"],
                "camera_operation": stage["camera_operation"],
                "camera_base": "",
                "continuity_mode": stage["continuity_mode"],
                "continuity_from": previous_stage_id if stage["continuity_mode"] != "NEW_WORLD" else "",
                "entity_refs": [_text(mutation.get("entity_ref")) for mutation in stage["mutations"]],
                "state_before": {},
                "state_after": {},
                "observable_change": narration_text,
                "observable_change_ko": narration_text,
                "claim_ids": _claim_ids(raw_refs),
                "visual_prompt": _prompt(narration_text, beat["visual_mode"], shot["action"]),
            })
            previous_stage_id = stage["stage_id"]
        projected.append({
            "sequence_id": sequence["sequence_id"],
            "sequence_role": sequence["sequence_role"],
            "world": {
                "world_id": f"WORLD_{sequence['sequence_id']}",
                "style": "source-grounded educational visual",
                "lighting": "clear neutral lighting",
                "background": "uncluttered explanatory space",
                "style_ko": "근거에 묶인 교육용 시각화",
                "lighting_ko": "명확하고 중립적인 조명",
                "background_ko": "정보 변화가 잘 보이는 단순한 공간",
                "camera_base": "elevated_three_quarter",
                "identity_lock": True,
            },
            "entities": [{
                "entity_id": entity_ref,
                "entity_type": "source_backed_concept",
                "visual_identity": entity_ref,
                "visual_identity_ko": entity_ref,
                "continuity": "locked",
            } for entity_ref in entity_refs],
            "stages": stages,
        })
    return projected


def build(
    visual_plan: dict[str, Any],
    narration: dict[str, Any],
    ir: dict[str, Any],
    pack: dict[str, Any],
    *,
    version_type: str = "image_sequence",
) -> dict[str, Any]:
    """Build a canonical, Production-shaped Shadow directive."""
    errors = _input_errors(visual_plan, narration, ir, pack, version_type)
    if errors:
        if "visual_plan_not_ready" in errors:
            raise ValueError("visual_plan_not_ready")
        raise ValueError("directive_projection_invalid:" + ",".join(errors))

    narration_by_id = _narration_map(narration)
    cuts: list[dict[str, Any]] = []
    for cut_no, beat in enumerate(visual_plan["visual_beats"], 1):
        stage = beat["stage"]
        shot = beat["shot_directive"]
        narration_id = shot["narration_refs"][0]
        narration_text = " ".join(_strings(narration_by_id[narration_id].get("sentences")))
        raw_refs = _strings(beat.get("raw_refs"))
        reasoning_ids = _strings(beat.get("reasoning_ids"))
        evidence_ids = _strings(beat.get("evidence_ids"))
        mutation_ids = [_text(row.get("mutation_id")) for row in stage["mutations"]]
        trace = {
            "visual_beat_id": beat["visual_beat_id"],
            "narration_refs": [narration_id],
            "reasoning_ids": reasoning_ids,
            "evidence_ids": evidence_ids,
            "raw_refs": raw_refs,
            "stage_id": stage["stage_id"],
            "mutation_ids": mutation_ids,
            "shot_id": shot["shot_id"],
            "causal_levels": _strings(beat.get("causal_levels")),
            "uncertainties": _strings(beat.get("uncertainties")),
            "attributions": _strings(beat.get("attributions")),
            "concept_ids": _strings(beat.get("concept_ids")),
            "knowledge_refs": _strings(beat.get("knowledge_refs")),
        }
        cuts.append({
            "cut_no": cut_no,
            "scene_kind": "broll_stock",
            "narration_ko": narration_text,
            "narration_en": "",
            "estimated_sec": _duration(narration_text),
            "visual_type": "comic_panel" if version_type == "comic" else "image",
            "answers_ko": beat["purpose"],
            "staging_ko": f"{beat['visual_mode']} · {shot['action']} · {stage['camera_operation']}",
            "visual_prompt": _prompt(narration_text, beat["visual_mode"], shot["action"]),
            "visual_prompt_ko": narration_text,
            "motion_prompt": "",
            "motion_prompt_ko": "",
            "motion_source": "still",
            "effects": [],
            "transition": _TRANSITION.get(shot["transition_in"], "cut"),
            "source_facts": raw_refs,
            "claim_ids": _claim_ids(raw_refs),
            "reasoning_id": reasoning_ids[0] if reasoning_ids else "",
            "evidence_role": "primary_result" if evidence_ids else "connective",
            "beat": _BEAT_BY_MODE[beat["visual_mode"]],
            "beat_declared": True,
            "asset_strategy": "new_asset",
            "visual_role": "MECHANISM" if beat["visual_mode"] == "MECHANISM" else "REALITY",
            "visual_mode": beat["visual_mode"],
            "visual_beat_id": beat["visual_beat_id"],
            "narration_id": narration_id,
            "stage_id": stage["stage_id"],
            "mutation_ids": mutation_ids,
            "shot_id": shot["shot_id"],
            "causal_levels": deepcopy(trace["causal_levels"]),
            "uncertainties": deepcopy(trace["uncertainties"]),
            "attributions": deepcopy(trace["attributions"]),
            "explanation_trace": trace,
        })

    visual_sequences = _sequence_projection(visual_plan, narration_by_id)
    total = sum(cut["estimated_sec"] for cut in cuts)
    fully_traced = sum(
        bool(cut["explanation_trace"]["narration_refs"])
        and bool(cut["explanation_trace"]["stage_id"])
        and bool(cut["explanation_trace"]["mutation_ids"])
        and bool(cut["explanation_trace"]["shot_id"])
        for cut in cuts
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "projection_status": "READY",
        "domain": visual_plan["domain"],
        "content_id": visual_plan["content_id"],
        "version_type": version_type,
        "header": {
            "version_type": version_type,
            "aspect_ratio": "9:16",
            "global_style": "source-grounded visual explainer",
            "core_question": visual_plan["core_question"],
            "total_estimated_sec": total,
            "source_constraints": deepcopy(visual_plan.get("constraints") or {}),
            "explanation_trace_summary": {
                "visual_beat_count": len(cuts),
                "fully_traced_cut_count": fully_traced,
                "sequence_count": len(visual_sequences),
            },
            "visual_sequences": deepcopy(visual_sequences),
        },
        "cuts": cuts,
        "visual_sequences": visual_sequences,
        "qa": {
            "errors": [],
            "warnings": list((visual_plan.get("qa") or {}).get("warnings") or []),
            "metrics": {
                "cut_count": len(cuts),
                "fully_traced_cut_count": fully_traced,
                "reasoning_linked_cut_count": sum(bool(cut["explanation_trace"]["reasoning_ids"])
                                                   for cut in cuts),
                "evidence_linked_cut_count": sum(bool(cut["explanation_trace"]["evidence_ids"])
                                                  for cut in cuts),
            },
        },
    }


def validate(
    result: Any,
    visual_plan: dict[str, Any],
    narration: dict[str, Any],
    ir: dict[str, Any],
    pack: dict[str, Any],
    *,
    version_type: str = "image_sequence",
) -> list[str]:
    """Reject invalid inputs and any result that differs from the canonical build."""
    errors = _input_errors(visual_plan, narration, ir, pack, version_type)
    if not isinstance(result, dict):
        errors.append("directive_not_dict")
        return sorted(set(errors))
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("directive_contract_invalid")
    if result.get("projection_status") != "READY":
        errors.append("projection_status_invalid")
    if errors:
        return sorted(set(errors))
    try:
        canonical = build(visual_plan, narration, ir, pack, version_type=version_type)
    except ValueError as exc:
        return [str(exc)]
    if result != canonical:
        errors.append("directive_not_canonical")
    return sorted(set(errors))
