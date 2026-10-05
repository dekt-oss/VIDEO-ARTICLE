"""Phase 8 shadow content-complexity action gate.

Warnings are not decisions.  This module turns validated V2 narration and the
existing content plan into explicit actions and constraints for the later visual
planner.  It is pure and is not imported by the Production generation path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import (
    config,
    narrative_planner,
    semantic_fidelity,
    spoken_narration,
)


CONTRACT_VERSION = "content-complexity-gate-v1"
GATE_STATUSES = frozenset({"READY", "ACTION_REQUIRED", "BLOCKED_UPSTREAM"})
_MODE_RANK = {"flash": 0, "standard": 1, "deep": 2, "extended": 3}
_MECHANISM_ROLES = {
    "paper": frozenset({"cause", "mechanism"}),
    "report": frozenset({"cause", "bridge"}),
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _source_policy(pack: dict[str, Any]) -> dict[str, Any]:
    domain = _text(pack.get("domain"))
    source = pack.get("source") if isinstance(pack.get("source"), dict) else {}
    depth = _text(source.get("source_depth")) or "none"
    table = config.SOURCE_ADEQUACY_POLICIES[domain]
    return deepcopy(table.get(depth) or table["__default__"])


def source_errors(pack: dict[str, Any], ir: dict[str, Any]) -> list[str]:
    """Source 깊이·모드가 Pack·IR·정책표에서 일치하는지. 대본 없이 검사할 수 있다.

    Phase 11 Shadow 실행은 이 검사를 **유료 모델 호출 전에** 먼저 돌린다 — 여기서 걸릴
    입력이면 대본·검증 호출에 돈을 쓴 뒤에 게이트에서 죽기 때문이다.
    """
    errors: list[str] = []
    source = pack.get("source") if isinstance(pack.get("source"), dict) else {}
    ir_source = ir.get("source") if isinstance(ir.get("source"), dict) else {}
    for field in ("source_depth", "source_mode"):
        if _text(ir_source.get(field)) != _text(source.get(field)):
            errors.append(f"source_{field}_mismatch")
    policy_mode = _text(_source_policy(pack).get("source_mode"))
    pack_mode = _text(source.get("source_mode"))
    # 레거시 Fact Sheet(출처 메타 없음)는 Phase 2 가 모드를 추정하지 않고 "" 로 둔다(Phase 2 §8).
    # 그 경우 깊이는 "none" 이고 위 정책도 가장 보수적인 "none" 행이다 — 위조로 얻을 것이 없다.
    # 이걸 불일치로 보면 레거시 콘텐츠가 유료 대본 호출 뒤 여기서 예외로 죽는다(Phase 11 리뷰).
    legacy_unknown = not pack_mode and (_text(source.get("source_depth")) or "none") == "none"
    if pack_mode != policy_mode and not legacy_unknown:
        errors.append(
            f"source_policy_mode_mismatch:{_text(source.get('source_mode')) or '?'}"
            f"!={policy_mode or '?'}"
        )
    return errors


def _upstream_errors(
    narration: dict[str, Any],
    fidelity: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
) -> list[str]:
    errors = [
        f"narrative_plan_invalid:{error}"
        for error in narrative_planner.validate(plan, ir, resolution, pack)
    ]
    errors.extend(
        f"spoken_narration_invalid:{error}"
        for error in spoken_narration.validate(narration, plan, ir, resolution, pack)
    )
    errors.extend(
        f"semantic_fidelity_invalid:{error}"
        for error in semantic_fidelity.validate(
            fidelity, narration, plan, ir, resolution, pack
        )
    )
    errors.extend(source_errors(pack, ir))
    return sorted(set(errors))


def _content_plan_errors(content_plan: Any) -> list[str]:
    if not isinstance(content_plan, dict):
        return ["content_plan_not_dict"]
    errors: list[str] = []
    mode = _text(content_plan.get("selected_mode"))
    if mode not in config.CONTENT_MODES:
        errors.append("selected_mode_invalid")
    duration = content_plan.get("target_duration_max_sec")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        errors.append("target_duration_max_sec_invalid")
    return errors


def _constraints(pack: dict[str, Any], ir: dict[str, Any]) -> dict[str, Any]:
    policy = _source_policy(pack)
    source = pack["source"]
    roles = _MECHANISM_ROLES[pack["domain"]]
    mechanism_ids = [
        unit["reasoning_id"]
        for unit in ir.get("reasoning_units") or []
        if isinstance(unit, dict) and unit.get("role") in roles
    ]
    return {
        "source_depth": _text(source.get("source_depth")),
        "source_mode": _text(policy.get("source_mode")),
        "max_duration_sec": int(policy.get("max_duration_sec") or 0),
        "max_content_mode": _text(policy.get("max_content_mode")),
        "mechanism_visual_allowed": bool(mechanism_ids),
        "mechanism_reasoning_ids": mechanism_ids,
    }


def _action(action: str, reason: str) -> dict[str, Any]:
    return {
        "action_id": "",
        "action": action,
        "blocking": True,
        "reason": reason,
    }


def _build(
    content_plan: dict[str, Any],
    narration: dict[str, Any],
    fidelity: dict[str, Any],
    ir: dict[str, Any],
    pack: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    constraints = _constraints(pack, ir)
    fidelity_status = _text(fidelity.get("qa_status"))
    if fidelity_status != "PASSED":
        constraints["mechanism_visual_allowed"] = False
        constraints["mechanism_reasoning_ids"] = []
        return {
            "contract_version": CONTRACT_VERSION,
            "domain": pack["domain"],
            "content_id": pack["content_id"],
            "gate_status": "BLOCKED_UPSTREAM",
            "required_actions": [],
            "applied_overrides": [],
            "constraints": constraints,
            "qa": {
                "errors": [f"semantic_fidelity_not_passed:{fidelity_status}"],
                "warnings": [],
                "metrics": {"action_count": 0, "spoken_number_count": 0},
            },
        }

    overrides = overrides if isinstance(overrides, dict) else {}
    actions: list[dict[str, Any]] = []
    applied_overrides: list[dict[str, str]] = []
    warnings: list[str] = []
    mode = _text(content_plan.get("selected_mode"))

    if mode == "series_split":
        override = overrides.get("series_split")
        override = override if isinstance(override, dict) else {}
        reason = _text(override.get("reason"))
        if override.get("approved") is True and reason:
            applied_overrides.append({"signal": "series_split", "reason": reason})
            warnings.append("series_split_overridden")
        else:
            actions.append(_action(
                "SPLIT_SERIES",
                _text(content_plan.get("series_split_reason"))
                or "content_plan selected series_split",
            ))

    metrics = narration.get("qa", {}).get("metrics", {})
    spoken_numbers = int(metrics.get("number_count") or 0)
    if spoken_numbers > config.MAX_SPOKEN_NUMBERS:
        actions.append(_action(
            "REGENERATE_NARRATION",
            f"spoken_numbers:{spoken_numbers}>{config.MAX_SPOKEN_NUMBERS}",
        ))

    max_mode = constraints["max_content_mode"]
    duration = float(content_plan["target_duration_max_sec"])
    max_duration = constraints["max_duration_sec"]
    source_exceeded = bool(max_duration) and duration > max_duration   # 0 = 상한 없음
    if mode in _MODE_RANK and max_mode in _MODE_RANK:
        source_exceeded = source_exceeded or _MODE_RANK[mode] > _MODE_RANK[max_mode]
    if source_exceeded:
        actions.append(_action(
            "DOWNGRADE_LENGTH",
            f"source_limit:{max_mode or 'domain-policy'}:{constraints['max_duration_sec']}s",
        ))

    if not constraints["mechanism_visual_allowed"]:
        warnings.append("mechanism_visual_forbidden")

    for position, action in enumerate(actions, 1):
        action["action_id"] = f"CA{position:02d}"
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": pack["domain"],
        "content_id": pack["content_id"],
        "gate_status": "ACTION_REQUIRED" if actions else "READY",
        "required_actions": actions,
        "applied_overrides": applied_overrides,
        "constraints": constraints,
        "qa": {
            "errors": [],
            "warnings": sorted(set(warnings)),
            "metrics": {
                "action_count": len(actions),
                "spoken_number_count": spoken_numbers,
            },
        },
    }


def evaluate(
    content_plan: dict[str, Any],
    narration: dict[str, Any],
    fidelity: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return canonical actions; invalid upstream artifacts never become decisions."""
    upstream_errors = _upstream_errors(narration, fidelity, plan, ir, resolution, pack)
    if upstream_errors:
        raise ValueError("upstream_invalid:" + ",".join(upstream_errors))
    plan_errors = _content_plan_errors(content_plan)
    if plan_errors:
        raise ValueError("content_plan_invalid:" + ",".join(plan_errors))
    return _build(content_plan, narration, fidelity, ir, pack, overrides)


def validate(
    result: Any,
    content_plan: dict[str, Any],
    narration: dict[str, Any],
    fidelity: dict[str, Any],
    plan: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    pack: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> list[str]:
    """Reject stored status, action, constraint, or override forgery."""
    if not isinstance(result, dict):
        return ["gate_not_dict"]
    errors: list[str] = []
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if result.get("gate_status") not in GATE_STATUSES:
        errors.append("gate_status_invalid")
    try:
        canonical = evaluate(
            content_plan,
            narration,
            fidelity,
            plan,
            ir,
            resolution,
            pack,
            overrides=overrides,
        )
    except ValueError as exc:
        errors.append(str(exc))
        return sorted(set(errors))
    if result != canonical:
        errors.append("gate_not_canonical")
    return sorted(set(errors))
