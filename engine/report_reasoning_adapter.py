"""Existing financial reasoning to Explanation IR shadow adapter."""

from __future__ import annotations

from typing import Any

from . import config, explanation_ir

_ROLE_BY_UNIT_TYPE: dict[str, str] = {
    "DRIVER_CHAIN": "cause",
    "EARNINGS_BRIDGE": "bridge",
    "VALUATION_LOGIC": "payoff",
    "CATALYST_PATH": "cause",
    "RISK_PATH": "risk",
    "SCENARIO": "result",
    "COMPARISON": "result",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _source_limits(pack: dict[str, Any]) -> tuple[int, int]:
    source = pack.get("source") if isinstance(pack.get("source"), dict) else {}
    depth = _text(source.get("source_depth")) or "none"
    table = config.SOURCE_ADEQUACY_POLICIES["report"]
    policy = table.get(depth) or table["__default__"]
    return int(policy.get("max_reasoning_units") or 0), int(
        policy.get("max_reasoning_steps") or 0)


def _thesis(units: list[Any]) -> str:
    for unit in units if isinstance(units, list) else []:
        if isinstance(unit, dict) and unit.get("carries_thesis"):
            title = _text(unit.get("title"))
            if title:
                return title
            for step in unit.get("steps") or []:
                if isinstance(step, dict) and _text(step.get("text")):
                    return _text(step.get("text"))
    return ""


def build(pack: dict[str, Any], financial_reasoning: dict[str, Any] | None,
          *, core_question: str = "", thesis: str = "") -> dict[str, Any]:
    """Translate normalized report reasoning without inventing missing links."""
    if not isinstance(pack, dict) or pack.get("domain") != "report":
        raise ValueError("report_reasoning_adapter_requires_report_pack")

    reasoning = financial_reasoning if isinstance(financial_reasoning, dict) else {}
    raw_units = reasoning.get("units")
    raw_units = raw_units if isinstance(raw_units, list) else []
    max_units, max_steps = _source_limits(pack)
    eligible_units = raw_units[:max_units]
    evidence_index = explanation_ir.build_index(pack)
    warnings: list[str] = []
    if _text(core_question):
        warnings.append("caller_core_question_semantics_unverified")
    if _text(thesis):
        warnings.append("caller_thesis_semantics_unverified")
    if len(raw_units) > max_units:
        warnings.append(f"source_reasoning_units_capped:{len(raw_units)}>{max_units}")

    units: list[dict[str, Any]] = []
    for unit_position, unit in enumerate(eligible_units, 1):
        if not isinstance(unit, dict):
            continue
        source_reasoning_id = _text(unit.get("reasoning_id")) or f"R{unit_position:02d}"
        raw_steps = unit.get("steps")
        raw_steps = raw_steps if isinstance(raw_steps, list) else []
        if len(raw_steps) > max_steps:
            warnings.append(
                f"source_reasoning_steps_capped:{source_reasoning_id}:{len(raw_steps)}>{max_steps}")
        unit_type = _text(unit.get("unit_type")).upper()
        role = _ROLE_BY_UNIT_TYPE.get(unit_type, "bridge")
        attribution = _text(unit.get("attributed_to"))
        assumption = _text(unit.get("assumption"))
        breaks_if = _text(unit.get("breaks_if"))
        uncertainty = "; ".join(
            part for part in (
                f"assumption={assumption}" if assumption else "",
                f"breaks_if={breaks_if}" if breaks_if else "",
            ) if part
        )
        for step_position, step in enumerate(raw_steps[:max_steps], 1):
            if not isinstance(step, dict) or not _text(step.get("text")):
                continue
            step_no = step.get("step") if step.get("step") is not None else step_position
            fact_ids = step.get("fact_ids")
            if isinstance(fact_ids, str):
                fact_ids = [fact_ids]
            fact_ids = [
                _text(fact_id) for fact_id in (fact_ids if isinstance(fact_ids, list) else [])
                if _text(fact_id)
            ]
            # 숫자 근거 번호가 없으면 **원문 인용이 확인된 단계 자체**를 근거로 쓴다(evidence_pack
            # `_report_step_claims`). 둘 다 없을 때만 근거 없는 단계다.
            step_evidence = f"report:step:{source_reasoning_id}#{step_no}"
            evidence_ids = (
                [f"report:{fact_id}" for fact_id in fact_ids] if fact_ids
                else ([step_evidence] if step_evidence in evidence_index else [])
            )
            if not evidence_ids:
                warnings.append(
                    f"report_step_without_evidence_id:{source_reasoning_id}#{step_no}")
            step_attribution = attribution
            evidence_attributions = sorted({
                _text(evidence_index.get(f"report:{fact_id}", {}).get("attribution"))
                for fact_id in fact_ids
                if _text(evidence_index.get(f"report:{fact_id}", {}).get("attribution"))
            })
            if len(evidence_attributions) == 1:
                evidence_attribution = evidence_attributions[0]
                if step_attribution and step_attribution != evidence_attribution:
                    warnings.append(
                        f"report_attribution_corrected:{source_reasoning_id}#{step_no}:"
                        f"{step_attribution}!={evidence_attribution}")
                    step_attribution = evidence_attribution
                elif not step_attribution:
                    step_attribution = evidence_attribution
                    warnings.append(
                        f"report_attribution_derived:{source_reasoning_id}#{step_no}:"
                        f"{step_attribution}")
            elif fact_ids and not step_attribution:
                if len(evidence_attributions) > 1:
                    warnings.append(
                        f"report_attribution_ambiguous:{source_reasoning_id}#{step_no}")
                else:
                    warnings.append(
                        f"report_attribution_missing:{source_reasoning_id}#{step_no}")
            units.append({
                "role": role,
                "text": _text(step.get("text")),
                "evidence_ids": evidence_ids,
                "causal_level": "broker_projection",
                "uncertainty": uncertainty,
                "attribution": step_attribution,
                "transition_relation": "supports" if step_position == 1 else "continues",
                # 기존 지시서 생성기는 증권사 논리 번호(R01)만 컷의 reasoning_id 로 인정한다
                # (`report_directive._filter_reasoning_ids`). V2 번호(XR01)와 함께 보관한다.
                "source_reasoning_id": source_reasoning_id,
            })

    candidate = {
        "domain": "report",
        "core_question": _text(core_question) or "왜 이 증권사는 이런 전망을 하는가?",
        "thesis": _text(thesis) or _thesis(eligible_units),
        "reasoning_units": units,
        "warnings": warnings,
    }
    return explanation_ir.normalize(candidate, pack)
