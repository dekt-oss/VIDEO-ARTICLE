"""Compare legacy Gold Set findings with the Phase 8 shadow gate contract."""

from __future__ import annotations

from typing import Any

from . import content_complexity_gate


CONTRACT_VERSION = "content-complexity-shadow-comparison-v1"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def compare(legacy_case: Any, gate_result: Any) -> dict[str, Any]:
    """Report contract-level action differences without claiming final quality."""
    if not isinstance(legacy_case, dict):
        raise ValueError("legacy_case_not_dict")
    if not isinstance(gate_result, dict):
        raise ValueError("gate_result_not_dict")
    if gate_result.get("contract_version") != content_complexity_gate.CONTRACT_VERSION:
        raise ValueError("gate_contract_invalid")
    if (
        gate_result.get("gate_status") not in content_complexity_gate.GATE_STATUSES
        or not isinstance(gate_result.get("required_actions"), list)
        or not all(isinstance(row, dict) for row in gate_result["required_actions"])
        or not isinstance(gate_result.get("applied_overrides"), list)
        or not all(isinstance(row, dict) for row in gate_result["applied_overrides"])
        or not isinstance(gate_result.get("constraints"), dict)
        or not isinstance(gate_result.get("qa"), dict)
    ):
        raise ValueError("gate_result_invalid")
    case_id = _text(legacy_case.get("case_id"))
    domain = _text(legacy_case.get("domain"))
    if case_id != _text(gate_result.get("content_id")) or domain != _text(
        gate_result.get("domain")
    ):
        raise ValueError("legacy_identity_mismatch")

    findings = legacy_case.get("findings")
    findings = findings if isinstance(findings, list) else []
    finding_codes = sorted({
        _text(row.get("code"))
        for row in findings if isinstance(row, dict) and _text(row.get("code"))
    })
    actions = {
        _text(row.get("action"))
        for row in gate_result.get("required_actions") or []
        if isinstance(row, dict)
    }
    overrides = {
        _text(row.get("signal"))
        for row in gate_result.get("applied_overrides") or []
        if isinstance(row, dict)
    }
    if gate_result.get("gate_status") == "BLOCKED_UPSTREAM":
        axes = {
            "series_split": "BLOCKED_UPSTREAM",
            "spoken_numbers": "BLOCKED_UPSTREAM",
            "source_depth": "BLOCKED_UPSTREAM",
            "mechanism_visual": "BLOCKED_UPSTREAM",
        }
    else:
        axes = {
            "series_split": (
                "ACTION_REQUIRED" if "SPLIT_SERIES" in actions
                else "OVERRIDDEN" if "series_split" in overrides
                else "CLEAR"
            ),
            "spoken_numbers": (
                "ACTION_REQUIRED" if "REGENERATE_NARRATION" in actions else "CLEAR"
            ),
            "source_depth": (
                "ACTION_REQUIRED"
                if actions & {"DOWNGRADE_LENGTH", "FETCH_SOURCE", "NARROW_REASONING"}
                else "CLEAR"
            ),
            "mechanism_visual": (
                "ALLOWED"
                if bool((gate_result.get("constraints") or {}).get(
                    "mechanism_visual_allowed"
                ))
                else "FORBIDDEN"
            ),
        }
    return {
        "contract_version": CONTRACT_VERSION,
        "case_id": case_id,
        "domain": domain,
        "legacy_finding_codes": finding_codes,
        "v2_gate_status": gate_result.get("gate_status"),
        "axes": axes,
        "final_directive_quality": "not_measured",
        "rendered_video_quality": "not_measured",
    }
