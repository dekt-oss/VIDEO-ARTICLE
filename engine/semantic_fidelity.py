"""Phase 7 shadow semantic-fidelity boundary.

The independent critic may judge narration clauses, but this module owns the
validated input slice, identity, provenance, and final gate state.  Nothing in
the Production script/directive path imports this module.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import (
    evidence_pack,
    explanation_ir,
    narrative_planner,
    prerequisite_resolver,
    spoken_narration,
)


CONTRACT_VERSION = "semantic-fidelity-v1"
QA_STATUSES = frozenset({
    "PASSED", "REJECTED", "BLOCKED_UPSTREAM", "REJECTED_UPSTREAM", "CRITIC_ERROR",
})
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
