"""Phase 11 read-only orchestration for Explanation Engine v2 shadow artifacts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from . import (
    config,
    content_complexity_gate,
    evidence_pack,
    explanation_directive,
    narrative_planner,
    paper_reasoning_adapter,
    prerequisite_resolver,
    report_reasoning_adapter,
    semantic_fidelity,
    spoken_narration,
    visual_planner,
)


CONTRACT_VERSION = "explanation-shadow-run-v1"


def _legacy(draft: Any, directive: Any) -> dict[str, Any]:
    draft = draft if isinstance(draft, dict) else {}
    directive = directive if isinstance(directive, dict) else {}
    return {
        "script_md": str(draft.get("script_md") or ""),
        "directive_id": str(directive.get("id") or ""),
        "version_type": str(directive.get("version_type") or ""),
        "status": str(directive.get("status") or ""),
        "header": deepcopy(directive.get("header") or {}),
        "cuts": deepcopy(directive.get("cuts") or []),
    }


def _content_plan(pack: dict[str, Any]) -> dict[str, Any]:
    domain = pack["domain"]
    depth = str((pack.get("source") or {}).get("source_depth") or "none")
    policies = config.SOURCE_ADEQUACY_POLICIES[domain]
    policy = policies.get(depth) or policies["__default__"]
    return {
        "selected_mode": str(policy.get("max_content_mode") or "flash"),
        "target_duration_max_sec": int(policy.get("max_duration_sec") or 30),
        "series_split_reason": "",
    }


def _base_result(
    domain: str,
    content_id: str,
    legacy: dict[str, Any],
    pack: dict[str, Any],
    ir: dict[str, Any],
    resolution: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "comparison_basis": "production_content_id_read_only",
        "same_content_id": True,
        "same_fact_sheet_revision": "UNVERIFIED",
        "domain": domain,
        "content_id": content_id,
        "legacy": legacy,
        "phase_status": {
            "phase2": "READY",
            "phase3": "READY" if ir.get("reasoning_units") else "EMPTY",
            "phase4": resolution.get("scope_action"),
            "phase5": plan.get("planning_status"),
            "phase6": "NOT_RUN",
            "phase7": "NOT_RUN",
            "phase8": "NOT_RUN",
            "phase9": "NOT_RUN",
            "phase10": "NOT_RUN",
        },
        "shadow": {
            "evidence_pack": pack,
            "ir": ir,
            "resolution": resolution,
            "narrative_plan": plan,
            "narration": None,
            "fidelity": None,
            "gate": None,
            "visual_plan": None,
            "directive": None,
        },
        "non_claims": [
            "same_fact_sheet_revision_unverified",
            "rendered_video_quality_not_measured",
            "audience_comprehension_not_measured",
        ],
    }


def run(
    *,
    domain: str,
    content_id: str,
    fact_sheet: dict[str, Any] | None,
    legacy_draft: dict[str, Any] | None,
    legacy_directive: dict[str, Any] | None,
    financial_reasoning: dict[str, Any] | None = None,
    allow_model_calls: bool = False,
    narration_caller: Callable[..., dict[str, Any]] | None = None,
    critic_caller: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build shadow artifacts without any database write or render side effect."""
    if domain not in {"paper", "report"}:
        raise ValueError(f"domain_invalid:{domain}")
    if not str(content_id).strip():
        raise ValueError("content_id_required")

    pack = evidence_pack.build(fact_sheet, domain, content_id=content_id)
    pack_errors = evidence_pack.validate(pack)
    if pack_errors:
        raise ValueError("evidence_pack_invalid:" + ",".join(pack_errors))
    ir = (
        paper_reasoning_adapter.build(pack)
        if domain == "paper"
        else report_reasoning_adapter.build(pack, financial_reasoning)
    )
    resolution = prerequisite_resolver.resolve(ir, pack, [])
    plan = narrative_planner.build(ir, resolution, pack)
    result = _base_result(
        domain, content_id, _legacy(legacy_draft, legacy_directive),
        pack, ir, resolution, plan,
    )

    if plan.get("planning_status") == "READY" and not allow_model_calls:
        result["run_status"] = "MODEL_CALL_REQUIRED"
        return result

    narration = spoken_narration.generate(
        plan, ir, resolution, pack,
        caller=narration_caller if allow_model_calls else None,
    )
    fidelity = semantic_fidelity.review(
        narration, plan, ir, resolution, pack,
        caller=critic_caller if allow_model_calls else None,
    )
    content_plan = _content_plan(pack)
    gate = content_complexity_gate.evaluate(
        content_plan, narration, fidelity, plan, ir, resolution, pack
    )
    visual_plan = visual_planner.build(
        content_plan, gate, narration, fidelity, plan, ir, resolution, pack
    )
    directive = None
    if visual_plan.get("planner_status") == "READY":
        directive = explanation_directive.build(visual_plan, narration, ir, pack)

    result["shadow"].update({
        "narration": narration,
        "fidelity": fidelity,
        "gate": gate,
        "visual_plan": visual_plan,
        "directive": directive,
    })
    result["phase_status"].update({
        "phase6": narration.get("generation_status"),
        "phase7": fidelity.get("qa_status"),
        "phase8": gate.get("gate_status"),
        "phase9": visual_plan.get("planner_status"),
        "phase10": "READY" if directive else "BLOCKED",
    })
    result["run_status"] = "READY" if directive else "BLOCKED"
    return result


def _cut_lines(cuts: Any) -> list[str]:
    rows = cuts if isinstance(cuts, list) else []
    lines: list[str] = []
    for position, raw in enumerate(rows, 1):
        cut = raw if isinstance(raw, dict) else {}
        narration = str(cut.get("narration_ko") or "").strip() or "(대사 없음)"
        visual = str(
            cut.get("staging_ko") or cut.get("visual_prompt_ko")
            or cut.get("visual_prompt") or ""
        ).strip() or "(시각 지시 없음)"
        lines.append(f"- 컷 {cut.get('cut_no') or position}: {narration}\n  - 화면: {visual}")
    return lines or ["- (지시서 컷 없음)"]


def _narration_lines(narration: Any) -> list[str]:
    payload = narration if isinstance(narration, dict) else {}
    beats = payload.get("narration_beats")
    rows = beats if isinstance(beats, list) else []
    lines: list[str] = []
    for position, raw in enumerate(rows, 1):
        beat = raw if isinstance(raw, dict) else {}
        sentences = beat.get("sentences")
        sentence_rows = sentences if isinstance(sentences, list) else []
        text = " ".join(str(item).strip() for item in sentence_rows if str(item).strip())
        if text:
            lines.append(f"- 비트 {beat.get('beat_id') or position}: {text}")
    return lines


def render_markdown(result: dict[str, Any]) -> str:
    """Render the local, human-readable comparison dossier."""
    legacy = result["legacy"]
    shadow = result["shadow"]
    lines = [
        "# Explanation Engine v2 Phase 11 전후 비교", "",
        f"- 도메인: {result['domain']}",
        f"- 콘텐츠 ID: {result['content_id']}",
        "- 동일 Fact Sheet revision: 미검증", "- 렌더 영상 품질: 미검증", "",
        "## 전 — 현재 Production", "",
        str(legacy.get("script_md") or "(저장 대본 없음)"), "",
        *_cut_lines(legacy.get("cuts")), "",
        "## 후 — V2 Shadow 대본", "",
    ]
    narration_lines = _narration_lines(shadow.get("narration"))
    if narration_lines:
        lines.extend(narration_lines)
    elif result.get("run_status") == "MODEL_CALL_REQUIRED":
        lines.append("- 외부 모델 호출 전 중단: `--with-model`이 필요합니다.")
    else:
        lines.append("- 생성된 V2 대본 없음")
    lines.extend(["", "## 후 — V2 Shadow 지시서", ""])
    directive = shadow.get("directive")
    if isinstance(directive, dict):
        lines.extend(_cut_lines(directive.get("cuts")))
    elif result.get("run_status") == "MODEL_CALL_REQUIRED":
        lines.append("- 외부 모델 호출 전 중단으로 새 지시서를 만들지 않았습니다.")
    else:
        lines.append("- 새 지시서 미발행: 안전 게이트가 차단했습니다.")
        gate = shadow.get("gate") or {}
        errors = (gate.get("qa") or {}).get("errors") or []
        if errors:
            lines.append("- 차단 사유: " + ", ".join(str(item) for item in errors))
    lines.extend(["", "## 단계 판정", ""])
    lines.extend(f"- {phase}: {status}" for phase, status in result["phase_status"].items())
    return "\n".join(lines).rstrip() + "\n"
