"""Explanation Engine v2 Phase 3 common shadow reasoning IR.

This module is deliberately pure: it does not call a model, database, or network.
Domain adapters propose reasoning units; this module owns IDs, evidence lookup,
raw references, filtering, warnings, and structural validation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import evidence_pack

CONTRACT_VERSION = "explanation-ir-v1"

ROLES: tuple[str, ...] = (
    "phenomenon", "prerequisite", "cause", "mechanism", "bridge",
    "result", "limitation", "risk", "payoff",
)
CONSTRAINT_ROLES = frozenset({"limitation", "risk"})
# 근거(인과·결과·기전)로 쓸 수 없는 상태. 한계·리스크 같은 제약 역할은 예외로 남긴다.
# ★ NOT_CHECKED 추가(2026-10-05 설계 점검 B): 종전에는 "한 번도 검증 안 된 근거"가 경고만 붙고 통과했고
#   "옛 규칙으로 검증된 근거(STALE)"는 막혔다 — 안전 쪽으로 거꾸로였다. 실데이터에서 retinotopic 논문의
#   근거 6/6 이 NOT_CHECKED 로 V2 근거가 됐다(골드셋이 "청각→시각 전이 발명"을 지적한 그 논문).
#   둘 다 Fact Sheet 를 다시 검증해야 쓸 수 있다.
DISALLOWED_POSITIVE_STATES = frozenset({"UNSUPPORTED", "STALE", "NOT_CHECKED"})
REVALIDATION_STATES = frozenset({"STALE", "NOT_CHECKED"})
_EVIDENCE_SECTIONS = ("claims", "numbers", "risks", "limitations", "background_context")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def build_index(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a detached evidence_id index across every Evidence Pack section."""
    out: dict[str, dict[str, Any]] = {}
    for section in _EVIDENCE_SECTIONS:
        for item in pack.get(section) or []:
            if not isinstance(item, dict):
                continue
            evidence_id = _text(item.get("evidence_id"))
            if evidence_id and evidence_id not in out:
                out[evidence_id] = deepcopy(item)
    return out


def _pack_errors(pack: dict[str, Any]) -> list[str]:
    return evidence_pack.validate(pack) if isinstance(pack, dict) else ["pack_not_dict"]


def normalize(candidate: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Normalize an adapter candidate into deterministic explanation-ir-v1."""
    errors = _pack_errors(pack)
    if errors:
        raise ValueError("evidence_pack_invalid:" + ",".join(errors))

    source = deepcopy(pack.get("source") or {})
    index = build_index(pack)
    warnings = _strings((candidate or {}).get("warnings"))
    units: list[dict[str, Any]] = []

    raw_units = (candidate or {}).get("reasoning_units")
    for position, raw in enumerate(raw_units if isinstance(raw_units, list) else [], 1):
        if not isinstance(raw, dict):
            warnings.append(f"reasoning_unit_invalid:{position}")
            continue
        text = _text(raw.get("text"))
        if not text:
            warnings.append(f"reasoning_unit_text_missing:{position}")
            continue
        role = _text(raw.get("role")).lower()
        if role not in ROLES:
            role = "result"

        kept_ids: list[str] = []
        for evidence_id in _unique(_strings(raw.get("evidence_ids"))):
            item = index.get(evidence_id)
            if item is None:
                warnings.append(f"evidence_ref_unknown:{evidence_id}")
                continue
            state = _text(item.get("verification_state"))
            if state in DISALLOWED_POSITIVE_STATES and role not in CONSTRAINT_ROLES:
                warnings.append(f"evidence_state_disallowed:{evidence_id}:{state}")
                continue
            if state in DISALLOWED_POSITIVE_STATES:
                warnings.append(f"constraint_evidence_state:{evidence_id}:{state}")
            elif state == "UNVERIFIABLE_AT_CURRENT_DEPTH":
                warnings.append(f"evidence_unverifiable:{evidence_id}")

            scope = item.get("verification_scope")
            if isinstance(scope, dict) and scope.get("semantic_entailment") is False:
                warnings.append(f"semantic_entailment_unverified:{evidence_id}")
            kept_ids.append(evidence_id)

        if not kept_ids:
            warnings.append(f"reasoning_unit_without_evidence:{position}")
            continue
        raw_refs = _unique([
            _text(index[evidence_id].get("raw_ref"))
            for evidence_id in kept_ids
            if _text(index[evidence_id].get("raw_ref"))
        ])
        units.append({
            "reasoning_id": f"XR{len(units) + 1:02d}",
            "role": role,
            "text": text,
            "evidence_ids": kept_ids,
            "raw_refs": raw_refs,
            "causal_level": _text(raw.get("causal_level")),
            "uncertainty": _text(raw.get("uncertainty")),
            "attribution": _text(raw.get("attribution")),
            "transition_relation": _text(raw.get("transition_relation")),
        })

    return {
        "contract_version": CONTRACT_VERSION,
        "domain": _text((candidate or {}).get("domain")) or _text(pack.get("domain")),
        "content_id": _text(pack.get("content_id")),
        "core_question": _text((candidate or {}).get("core_question")),
        "thesis": _text((candidate or {}).get("thesis")),
        "reasoning_units": units,
        "explanation_chain": [unit["reasoning_id"] for unit in units],
        "warnings": sorted(set(warnings)),
        "source": {
            "source_depth": _text(source.get("source_depth")),
            "source_mode": _text(source.get("source_mode")),
        },
    }


def validate(ir: dict[str, Any], pack: dict[str, Any] | None = None) -> list[str]:
    """Return deterministic contract violations; empty means structurally usable."""
    errors: list[str] = []
    if not isinstance(ir, dict):
        return ["ir_not_dict"]
    if ir.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if ir.get("domain") not in ("paper", "report"):
        errors.append("domain_invalid")
    if not _text(ir.get("core_question")):
        errors.append("core_question_missing")
    if not isinstance(ir.get("reasoning_units"), list):
        errors.append("reasoning_units_not_list")
        units: list[Any] = []
    else:
        units = ir["reasoning_units"]

    pack_errors = _pack_errors(pack) if pack is not None else []
    errors.extend(f"evidence_pack_invalid:{error}" for error in pack_errors)
    index = build_index(pack) if isinstance(pack, dict) and not pack_errors else {}
    expected_chain: list[str] = []
    for position, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            errors.append(f"reasoning_unit_invalid:{position}")
            continue
        expected_id = f"XR{position:02d}"
        reasoning_id = _text(unit.get("reasoning_id"))
        expected_chain.append(reasoning_id)
        if reasoning_id != expected_id:
            errors.append(f"reasoning_id_invalid:{reasoning_id or '?'}")
        if unit.get("role") not in ROLES:
            errors.append(f"reasoning_role_invalid:{reasoning_id or '?'}")
        evidence_ids = _strings(unit.get("evidence_ids"))
        if not evidence_ids:
            errors.append(f"reasoning_evidence_missing:{reasoning_id or '?'}")
        if index:
            unknown = [eid for eid in evidence_ids if eid not in index]
            errors.extend(f"evidence_ref_unknown:{eid}" for eid in unknown)
            for evidence_id in evidence_ids:
                item = index.get(evidence_id)
                if item is None:
                    continue
                state = _text(item.get("verification_state"))
                if state in DISALLOWED_POSITIVE_STATES and unit.get("role") not in CONSTRAINT_ROLES:
                    errors.append(f"evidence_state_disallowed:{evidence_id}:{state}")
            expected_refs = _unique([
                _text(index[eid].get("raw_ref"))
                for eid in evidence_ids if eid in index and _text(index[eid].get("raw_ref"))
            ])
            if unit.get("raw_refs") != expected_refs:
                errors.append(f"raw_refs_invalid:{reasoning_id or '?'}")
            if ir.get("domain") == "report":
                evidence_attributions = sorted({
                    _text(index[eid].get("attribution"))
                    for eid in evidence_ids
                    if eid in index and _text(index[eid].get("attribution"))
                })
                if len(evidence_attributions) == 1:
                    expected_attribution = evidence_attributions[0]
                    actual_attribution = _text(unit.get("attribution"))
                    if actual_attribution != expected_attribution:
                        errors.append(
                            f"attribution_mismatch:{reasoning_id or '?'}:"
                            f"{actual_attribution or '?'}!={expected_attribution}")
                elif len(evidence_attributions) > 1:
                    errors.append(f"attribution_ambiguous:{reasoning_id or '?'}")
    if ir.get("explanation_chain") != expected_chain:
        errors.append("explanation_chain_invalid")
    if isinstance(pack, dict) and ir.get("domain") != pack.get("domain"):
        errors.append(f"domain_mismatch:{ir.get('domain')}!={pack.get('domain')}")
    return sorted(set(errors))
