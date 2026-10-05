"""Paper Evidence Pack to Explanation IR shadow adapter."""

from __future__ import annotations

from typing import Any

from . import explanation_ir

_ROLE_BY_CLAIM_TYPE: dict[str, str] = {
    "main_result": "result",
    "mechanism": "mechanism",
    "author_interpretation": "mechanism",
    "method": "prerequisite",
    "limitation": "limitation",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_usable_claim(pack: dict[str, Any]) -> dict[str, Any] | None:
    for claim in pack.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        if claim.get("verification_state") in explanation_ir.DISALLOWED_POSITIVE_STATES:
            continue
        if _text(claim.get("text")) and _text(claim.get("evidence_id")):
            return claim
    return None


def build(pack: dict[str, Any], *, core_question: str = "",
          thesis: str = "") -> dict[str, Any]:
    """Create a deterministic Paper IR without synthesizing missing reasoning."""
    if not isinstance(pack, dict) or pack.get("domain") != "paper":
        raise ValueError("paper_reasoning_adapter_requires_paper_pack")

    warnings: list[str] = []
    if _text(core_question):
        warnings.append("caller_core_question_semantics_unverified")
    if _text(thesis):
        warnings.append("caller_thesis_semantics_unverified")
    units: list[dict[str, Any]] = []
    for claim in pack.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        evidence_id = _text(claim.get("evidence_id"))
        text = _text(claim.get("text"))
        if not evidence_id or not text:
            continue
        claim_type = _text(claim.get("claim_type"))
        role = _ROLE_BY_CLAIM_TYPE.get(claim_type, "result")
        uncertainty = _text(claim.get("uncertainty"))
        if claim_type == "author_interpretation":
            uncertainty = uncertainty or "author_interpretation"
            warnings.append(f"author_interpretation:{evidence_id}")
        units.append({
            "role": role,
            "text": text,
            "evidence_ids": [evidence_id],
            "causal_level": _text(claim.get("causal_strength")),
            "uncertainty": uncertainty,
            "attribution": _text(claim.get("attribution")),
            "transition_relation": "supports",
        })
        limitations = claim.get("limitations")
        if isinstance(limitations, str):
            limitations = [limitations]
        for limitation in limitations if isinstance(limitations, list) else []:
            limitation_text = _text(limitation)
            if not limitation_text:
                continue
            units.append({
                "role": "limitation",
                "text": limitation_text,
                "evidence_ids": [evidence_id],
                "causal_level": _text(claim.get("causal_strength")),
                "uncertainty": uncertainty,
                "attribution": _text(claim.get("attribution")),
                "transition_relation": "qualifies",
            })

    # 논문 전체에 걸린 연구 한계(Fact Sheet `limitations`) — **원문 구절이 있는 것만** 한계 장면으로 넣는다
    # (설계 점검 C, 운영자 결정 (가)). 구절이 없는 옛 Fact Sheet 의 한계는 코드로 대조할 수 없어 종전처럼 뺀다.
    for item in pack.get("limitations") or []:
        if not isinstance(item, dict) or not _text(item.get("text")):
            continue
        if not any(isinstance(ref, dict) and _text(ref.get("quote")) for ref in item.get("source_refs") or []):
            continue
        units.append({
            "role": "limitation",
            "text": _text(item.get("text")),
            "evidence_ids": [_text(item.get("evidence_id"))],
            "causal_level": "",
            "uncertainty": "",
            "attribution": "",
            "transition_relation": "qualifies",
        })

    anchor = _first_usable_claim(pack)
    candidate = {
        "domain": "paper",
        "core_question": _text(core_question) or "이 연구는 무엇을 보여 주는가?",
        "thesis": _text(thesis) or (_text(anchor.get("text")) if anchor else ""),
        "reasoning_units": units,
        "warnings": warnings,
    }
    return explanation_ir.normalize(candidate, pack)
