"""Explanation Engine v2 Phase 1 — source adequacy contract.

Source acquisition already classifies depth.  This module turns that descriptive
metadata into a production contract shared by paper/report draft and directive
paths.  It is deterministic and performs no I/O.

The contract is deliberately conservative only for shallow sources.  Full
sources keep the existing production envelope; partial/summary sources cannot
silently expand into a deep explainer later in the directive stage.
"""

from __future__ import annotations

from typing import Any

from . import config


_MODE_RANK = {"flash": 0, "standard": 1, "deep": 2, "extended": 3}


def _source_meta(fact_sheet: dict[str, Any], domain: str) -> tuple[str, int]:
    if domain == "paper":
        prov = fact_sheet.get("source_provenance")
        if isinstance(prov, dict):
            return (str(prov.get("source_depth") or "none"),
                    int(prov.get("char_count") or 0))
        return "none", 0
    return (str(fact_sheet.get("source_depth") or "summary_only"),
            int(fact_sheet.get("source_chars") or 0))


def build_policy(fact_sheet: dict[str, Any], domain: str) -> dict[str, Any]:
    """Resolve code-classified source depth into a production policy."""
    if domain not in ("paper", "report"):
        raise ValueError(f"unknown source-adequacy domain: {domain}")
    depth, chars = _source_meta(fact_sheet or {}, domain)
    table = config.SOURCE_ADEQUACY_POLICIES[domain]
    spec = table.get(depth) or table["__default__"]
    warnings: list[str] = []
    if depth not in table:
        warnings.append(f"source_depth_unknown:{depth}")
    if chars <= 0:
        warnings.append("source_body_unavailable")
    return {
        "contract_version": config.SOURCE_ADEQUACY_CONTRACT_VERSION,
        "domain": domain,
        "source_depth": depth,
        "source_chars": chars,
        "source_mode": spec["source_mode"],
        "max_duration_sec": int(spec.get("max_duration_sec") or 0),
        "max_content_mode": str(spec.get("max_content_mode") or ""),
        "max_reasoning_units": int(spec.get("max_reasoning_units") or 0),
        "max_reasoning_steps": int(spec.get("max_reasoning_steps") or 0),
        "warnings": warnings,
    }


def attach(fact_sheet: dict[str, Any], domain: str) -> dict[str, Any]:
    """Persist the policy inside the existing Fact Sheet JSON (no migration)."""
    fact_sheet["source_adequacy"] = build_policy(fact_sheet, domain)
    return fact_sheet


def from_fact_sheet(fact_sheet: dict[str, Any] | None,
                    domain: str | None = None) -> dict[str, Any] | None:
    """Read current policy, recomputing stale contracts from raw source metadata.

    Legacy Fact Sheets without enough domain/source metadata return None so this
    Phase 1 gate does not retroactively block old directives.
    """
    fs = fact_sheet or {}
    stored = fs.get("source_adequacy")
    if isinstance(stored, dict):
        dom = str(stored.get("domain") or domain or "")
        if (dom in ("paper", "report")
                and stored.get("contract_version") == config.SOURCE_ADEQUACY_CONTRACT_VERSION):
            return dict(stored)
        if dom in ("paper", "report"):
            return build_policy(fs, dom)

    dom = domain
    if dom is None:
        if isinstance(fs.get("source_provenance"), dict):
            dom = "paper"
        elif fs.get("source_depth") is not None:
            dom = "report"
    if dom not in ("paper", "report"):
        return None
    return build_policy(fs, dom)


def guidance(fact_sheet: dict[str, Any] | None,
             domain: str | None = None) -> str:
    """Prompt block that says exactly what the deterministic gate will enforce."""
    policy = from_fact_sheet(fact_sheet, domain)
    if not policy:
        return ""
    bits = [
        f"[Source Adequacy] depth={policy['source_depth']} / mode={policy['source_mode']}.",
        "원문에 없는 빈칸을 일반상식이나 추정으로 채우지 마라.",
    ]
    if policy["max_duration_sec"]:
        bits.append(f"최종 영상은 {policy['max_duration_sec']}초를 넘기지 마라.")
    if policy["max_content_mode"]:
        bits.append(f"논문 content_mode 상한은 {policy['max_content_mode']}다.")
    if policy["domain"] == "report":
        if policy["max_reasoning_units"] <= 0:
            bits.append("독립적인 인과 논증을 새로 만들지 말고, 확인된 핵심 사실/전망만 짧게 전달하라.")
        elif policy["max_reasoning_units"] < config.REASONING_MAX_UNITS:
            bits.append(
                f"논증은 최대 {policy['max_reasoning_units']}개, 단위당 "
                f"{policy['max_reasoning_steps']}단계까지만 사용하라."
            )
    if policy["source_mode"] in ("BRIEF_EXPLAINER", "SUMMARY_ONLY"):
        bits.append("자료가 얕으므로 길이를 채우기 위해 배경·기전·시장 맥락을 창작하지 마라.")
    return "\n" + " ".join(bits)


def apply_content_plan(plan: dict[str, Any],
                       fact_sheet: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the paper source ceiling after content_mode normalization."""
    policy = from_fact_sheet(fact_sheet, "paper")
    if not policy:
        return plan
    out = dict(plan)
    warnings = list(out.get("mode_warnings") or [])
    current = str(out.get("selected_mode") or "")
    ceiling = str(policy.get("max_content_mode") or "")
    if current in _MODE_RANK and ceiling in _MODE_RANK and _MODE_RANK[current] > _MODE_RANK[ceiling]:
        out["selected_mode"] = ceiling
        lo, hi = config.CONTENT_MODE_DURATION[ceiling]
        out["target_duration_min_sec"] = lo
        out["target_duration_max_sec"] = hi
        warnings.append(f"source_mode_capped:{current}->{ceiling}")
    out["source_mode"] = policy["source_mode"]
    out["source_depth"] = policy["source_depth"]
    out["source_max_duration_sec"] = policy["max_duration_sec"]
    out["mode_warnings"] = sorted(set(warnings))
    return out


def output_block_reasons(fact_sheet: dict[str, Any] | None,
                         total_sec: int | float | None,
                         domain: str | None = None) -> list[str]:
    """Hard limits checked again at the final directive, where expansion occurs."""
    policy = from_fact_sheet(fact_sheet, domain)
    if not policy:
        return []
    out: list[str] = []
    max_sec = int(policy.get("max_duration_sec") or 0)
    if max_sec and total_sec is not None and float(total_sec) > max_sec:
        out.append(f"source_depth_duration_exceeded:{int(round(float(total_sec)))}>{max_sec}")
    return out


def reasoning_limits(fact_sheet: dict[str, Any] | None) -> tuple[int, int]:
    """Report reasoning limits for the current source depth."""
    policy = from_fact_sheet(fact_sheet, "report")
    if not policy:
        return config.REASONING_MAX_UNITS, config.REASONING_MAX_STEPS
    return int(policy["max_reasoning_units"]), int(policy["max_reasoning_steps"])
