"""Phase 11 read-only orchestration for Explanation Engine v2 shadow artifacts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
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
    v2_directive_bridge,
    visual_planner,
)


CONTRACT_VERSION = "explanation-shadow-run-v2"
_PHASES = tuple(f"phase{number}" for number in range(2, 11))
# 실행 결과 상태. ERROR 는 "차단"과 다르다 — 판정이 아니라 실행이 끝까지 못 간 것이다.
RUN_STATUSES = frozenset({"MODEL_CALL_REQUIRED", "READY", "BLOCKED", "ERROR"})


def _legacy(draft: Any, directive: Any) -> dict[str, Any]:
    draft = draft if isinstance(draft, dict) else {}
    directive = directive if isinstance(directive, dict) else {}
    return {
        "script_md": str(draft.get("script_md") or ""),
        "directive_id": str(directive.get("id") or ""),
        "version_type": str(directive.get("version_type") or ""),
        "status": str(directive.get("status") or ""),
        "created_at": str(directive.get("created_at") or ""),
        "header": deepcopy(directive.get("header") or {}),
        "cuts": deepcopy(directive.get("cuts") or []),
    }


def snapshot_hash(fact_sheet: Any, financial_reasoning: Any = None) -> str:
    """현재 저장 입력의 지문. 과거 Production 생성 입력과 같다는 증명은 아니다."""
    canonical = json.dumps(
        {"fact_sheet": fact_sheet, "financial_reasoning": financial_reasoning},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _production_plan(raw: Any) -> dict[str, Any] | None:
    """Production 이 저장한 normalized content_plan 중 게이트가 받는 모양만 통과시킨다."""
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("selected_mode") or "").strip()
    duration = raw.get("target_duration_max_sec")
    if mode not in config.CONTENT_MODES:
        return None
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return None
    return {
        "selected_mode": mode,
        "target_duration_max_sec": duration,
        "series_split_reason": str(raw.get("series_split_reason") or ""),
    }


def _content_plan(pack: dict[str, Any], production: Any) -> tuple[dict[str, Any], str]:
    """Phase 8 입력 계획과 그 출처.

    소스 정책 상한으로 만든 계획은 게이트가 같은 상한과 비교하므로 길이 초과를 절대
    잡지 못한다 — 그래서 출처를 함께 돌려주고, 그 경우를 결과에 "미평가"로 남긴다.
    """
    stored = _production_plan(production)
    if stored is not None:
        return stored, "production_draft"
    domain = pack["domain"]
    depth = str((pack.get("source") or {}).get("source_depth") or "none")
    policies = config.SOURCE_ADEQUACY_POLICIES[domain]
    policy = policies.get(depth) or policies["__default__"]
    return {
        "selected_mode": str(policy.get("max_content_mode") or "flash"),
        "target_duration_max_sec": int(policy.get("max_duration_sec") or 30),
        "series_split_reason": "",
    }, "source_policy_ceiling"


def _empty_result(
    *, domain: str, content_id: str, legacy: dict[str, Any], allow_model_calls: bool,
    snapshot: str, requested_concepts: list[Any], requests_supplied: bool,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "comparison_basis": "same_content_id_current_stored_state",
        "same_content_id": True,
        "same_fact_sheet_revision": "UNVERIFIED",
        "domain": domain,
        "content_id": content_id,
        "run": {
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_calls_allowed": allow_model_calls,
            "narration_model": config.MODEL_SCRIPT if allow_model_calls else "",
            "critic_model": config.MODEL_SELFCHECK if allow_model_calls else "",
            "fact_sheet_snapshot_sha256": snapshot,
            "content_plan_source": "",
            "prerequisite_requests": {
                "source": "explicit" if requests_supplied else "none_supplied",
                "count": len(requested_concepts),
            },
        },
        "legacy": legacy,
        "phase_status": {phase: "NOT_RUN" for phase in _PHASES},
        "shadow": {
            "evidence_pack": None,
            "ir": None,
            "resolution": None,
            "narrative_plan": None,
            "content_plan": None,
            "narration": None,
            "fidelity": None,
            "gate": None,
            "visual_plan": None,
            "directive": None,
            "generated": None,
        },
        "error": None,
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
    production_content_plan: dict[str, Any] | None = None,
    requested_concepts: list[dict[str, Any]] | None = None,
    series_split_override_reason: str = "",
    allow_model_calls: bool = False,
    narration_caller: Callable[..., dict[str, Any]] | None = None,
    critic_caller: Callable[..., dict[str, Any]] | None = None,
    with_directive: bool = False,
    directive_generator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build shadow artifacts without any database write or render side effect.

    Stage failures are recorded as ``run_status=ERROR`` instead of raised, so a paid
    model call or a malformed stored source still leaves an inspectable dossier.
    Inputs that would certainly fail the Phase 8 source check are refused *before* any
    model call (``phase6_preflight``).

    ``series_split_override_reason`` is the Phase 8 explicit override (작업지시서 §10
    "한 편 발행 금지 또는 명시적 override"). Empty means no override.
    """
    if domain not in {"paper", "report"}:
        raise ValueError(f"domain_invalid:{domain}")
    if not str(content_id).strip():
        raise ValueError("content_id_required")
    requests = list(requested_concepts) if isinstance(requested_concepts, list) else []
    result = _empty_result(
        domain=domain, content_id=content_id,
        legacy=_legacy(legacy_draft, legacy_directive),
        allow_model_calls=allow_model_calls,
        snapshot=snapshot_hash(fact_sheet, financial_reasoning if domain == "report" else None),
        requested_concepts=requests,
        requests_supplied=requested_concepts is not None,
    )
    if requested_concepts is None:
        result["non_claims"].append("prerequisite_explanation_not_evaluated")
    override_reason = str(series_split_override_reason or "").strip()
    overrides = (
        {"series_split": {"approved": True, "reason": override_reason}}
        if override_reason else None
    )
    result["run"]["series_split_override_reason"] = override_reason
    shadow = result["shadow"]
    phases = result["phase_status"]
    phase = "phase2"
    try:
        pack = evidence_pack.build(fact_sheet, domain, content_id=content_id)
        pack_errors = evidence_pack.validate(pack)
        if pack_errors:
            raise ValueError("evidence_pack_invalid:" + ",".join(pack_errors))
        shadow["evidence_pack"] = pack
        phases["phase2"] = "READY"

        phase = "phase3"
        ir = (
            paper_reasoning_adapter.build(pack)
            if domain == "paper"
            else report_reasoning_adapter.build(pack, financial_reasoning)
        )
        shadow["ir"] = ir
        phases["phase3"] = "READY" if ir.get("reasoning_units") else "EMPTY"

        phase = "phase4"
        resolution = prerequisite_resolver.resolve(ir, pack, requests)
        shadow["resolution"] = resolution
        phases["phase4"] = resolution.get("scope_action")

        phase = "phase5"
        plan = narrative_planner.build(ir, resolution, pack)
        shadow["narrative_plan"] = plan
        phases["phase5"] = plan.get("planning_status")

        if plan.get("planning_status") == "READY" and not allow_model_calls:
            result["run_status"] = "MODEL_CALL_REQUIRED"
            return result

        if allow_model_calls:
            phase = "phase6_preflight"
            preflight = content_complexity_gate.source_errors(pack, ir)
            if preflight:
                raise ValueError("preflight_failed_before_model_call:" + ",".join(preflight))

        phase = "phase6"
        narration = spoken_narration.generate(
            plan, ir, resolution, pack,
            caller=narration_caller if allow_model_calls else None,
        )
        shadow["narration"] = narration
        phases["phase6"] = narration.get("generation_status")

        phase = "phase7"
        fidelity = semantic_fidelity.review(
            narration, plan, ir, resolution, pack,
            caller=critic_caller if allow_model_calls else None,
        )
        shadow["fidelity"] = fidelity
        phases["phase7"] = fidelity.get("qa_status")

        phase = "phase8"
        content_plan, plan_source = _content_plan(pack, production_content_plan)
        shadow["content_plan"] = content_plan
        result["run"]["content_plan_source"] = plan_source
        if plan_source != "production_draft":
            result["non_claims"].append("complexity_source_limit_not_evaluated")
        gate = content_complexity_gate.evaluate(
            content_plan, narration, fidelity, plan, ir, resolution, pack,
            overrides=overrides,
        )
        shadow["gate"] = gate
        phases["phase8"] = gate.get("gate_status")

        phase = "phase9"
        visual_plan = visual_planner.build(
            content_plan, gate, narration, fidelity, plan, ir, resolution, pack,
            overrides=overrides,
        )
        shadow["visual_plan"] = visual_plan
        phases["phase9"] = visual_plan.get("planner_status")

        phase = "phase10"
        directive = None
        if visual_plan.get("planner_status") == "READY":
            directive = explanation_directive.build(visual_plan, narration, ir, pack)
        shadow["directive"] = directive
        phases["phase10"] = "READY" if directive else "BLOCKED"
    except Exception as exc:  # noqa: BLE001 — 실패를 성공처럼 숨기지 않고 결과에 남긴다
        shadow["directive"] = None
        phases["phase6" if phase == "phase6_preflight" else phase] = "ERROR"
        result["error"] = {
            "phase": phase,
            "type": type(exc).__name__,
            "message": str(exc)[:500],
        }
        result["run_status"] = "ERROR"
        return result
    result["run_status"] = "READY" if shadow["directive"] else "BLOCKED"
    if with_directive and allow_model_calls:
        _bridge(result, legacy_draft, financial_reasoning, report, directive_generator)
    return result


def _bridge(result: dict[str, Any], legacy_draft: Any, financial_reasoning: Any,
            report: Any, generator: Any) -> None:
    """V2 대본 → 기존 지시서 생성기(설계 점검 A). V2 대본이 모든 게이트를 통과했을 때만 부른다.

    실패해도 V2 대본 판정(run_status)은 그대로 두고 이 단계의 상태만 남긴다.
    """
    shadow = result["shadow"]
    if result["run_status"] != "READY":
        result["phase_status"]["production_generator"] = "NOT_RUN"
        return
    try:
        shadow["generated"] = v2_directive_bridge.generate(
            result["domain"], shadow, legacy_draft if isinstance(legacy_draft, dict) else {},
            financial_reasoning=financial_reasoning,
            report=report if isinstance(report, dict) else None,
            generator=generator,
        )
    except Exception as exc:  # noqa: BLE001 — 실패를 성공처럼 숨기지 않는다
        shadow["generated"] = None
        shadow["generated_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        result["phase_status"]["production_generator"] = "ERROR"
        return
    generated = shadow["generated"]
    result["phase_status"]["production_generator"] = (
        "APPROVAL_BLOCKED" if generated["approval_blocked"] else "READY"
    )


# ─────────────────────────────────────────────────────────────
# Markdown — 사람이 읽는 비교 자료. JSON 에 있는 판정·사유를 숨기지 않는다.
# ─────────────────────────────────────────────────────────────

def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join(values: Any) -> str:
    rows = values if isinstance(values, list) else []
    text = ", ".join(str(item) for item in rows if str(item).strip())
    return text or "-"


def _legacy_cut_lines(cuts: Any) -> list[str]:
    rows = cuts if isinstance(cuts, list) else []
    lines: list[str] = []
    for position, raw in enumerate(rows, 1):
        cut = _dict(raw)
        narration = str(cut.get("narration_ko") or "").strip() or "(대사 없음)"
        lines.append(f"- 컷 {cut.get('cut_no') or position}: {narration}")
        staging = str(cut.get("staging_ko") or "").strip()
        prompt = str(cut.get("visual_prompt_ko") or cut.get("visual_prompt") or "").strip()
        if staging:
            lines.append(f"  - 연출: {staging}")
        if prompt and prompt != staging:
            lines.append(f"  - 시각 프롬프트: {prompt}")
        if not staging and not prompt:
            lines.append("  - 화면: (시각 지시 없음)")
        refs = cut.get("source_facts") or cut.get("claim_ids")
        if refs:
            lines.append(f"  - 근거 참조: {_join(refs if isinstance(refs, list) else [refs])}")
    return lines or ["- (지시서 컷 없음)"]


def _shadow_cut_lines(directive: dict[str, Any], visual_plan: Any) -> list[str]:
    beats = {
        str(_dict(beat).get("visual_beat_id")): _dict(beat)
        for beat in (_dict(visual_plan).get("visual_beats") or [])
    }
    rows = directive.get("cuts") if isinstance(directive.get("cuts"), list) else []
    lines: list[str] = []
    for position, raw in enumerate(rows, 1):
        cut = _dict(raw)
        trace = _dict(cut.get("explanation_trace"))
        beat = beats.get(str(cut.get("visual_beat_id")), {})
        stage = _dict(beat.get("stage"))
        narration = str(cut.get("narration_ko") or "").strip() or "(대사 없음)"
        changes = [
            f"{_dict(m).get('operation')}({_dict(m).get('entity_ref')}→{_dict(m).get('result_state_ref')})"
            for m in (stage.get("mutations") or [])
        ]
        lines.extend([
            f"- 컷 {cut.get('cut_no') or position}: {narration}",
            f"  - 시각 모드: {cut.get('visual_mode') or '-'}"
            f" · 표현: {beat.get('representation_mode') or '-'}",
            f"  - 시각 상태: {stage.get('stage_id') or '-'}"
            f" ({stage.get('operation') or '-'}, 카메라 {stage.get('camera_operation') or '-'},"
            f" 연속성 {stage.get('continuity_mode') or '-'})",
            f"  - 상태 변화: {_join(changes)}",
            f"  - 전환: {cut.get('transition') or '-'} · 관계 {beat.get('transition_relation') or '-'}",
            f"  - reasoning: {_join(trace.get('reasoning_ids'))}",
            f"  - evidence: {_join(trace.get('evidence_ids'))}",
            f"  - raw ref: {_join(trace.get('raw_refs'))}",
        ])
        for fact in cut.get("screen_facts") or []:
            fact = _dict(fact)
            lines.append(
                f"  - 화면 숫자 카드({fact.get('ref')}): {fact.get('text')}"
                f" [{_join(fact.get('numbers'))}]"
            )
        if trace.get("attributions") or trace.get("causal_levels"):
            lines.append(
                f"  - 귀속·인과 수준: {_join(trace.get('attributions'))}"
                f" / {_join(trace.get('causal_levels'))}"
            )
    return lines or ["- (지시서 컷 없음)"]


def _generated_lines(result: dict[str, Any]) -> list[str]:
    shadow = result["shadow"]
    status = result["phase_status"].get("production_generator")
    generated = shadow.get("generated")
    if not isinstance(generated, dict):
        error = _dict(shadow.get("generated_error"))
        if error:
            return [f"- ❌ 생성 실패: {error.get('type')}: {error.get('message')}"]
        if status == "NOT_RUN":
            return ["- 만들지 않음: V2 대본이 아직 모든 검사를 통과하지 못했습니다."]
        return ["- 만들지 않음: `--with-directive` 로 실행하면 만듭니다(추가 비용)."]
    directive = _dict(generated.get("directive"))
    trace = _dict(generated.get("trace"))
    header = _dict(directive.get("header"))
    lines = [
        "> 기존 Production 지시서와 **같은 생성기**로 만들었다 — 차이는 대본에서만 난다.",
        "",
        f"- 승인 가능 여부: {'막힘' if generated.get('approval_blocked') else '통과'}"
        f" · 막힌 이유: {_join(generated.get('block_reasons'))}",
        f"- 컷 {trace.get('cuts', 0)}개 · V2 대본과 연결된 컷 {trace.get('traced_cuts', 0)}개",
        f"- 예상 길이: {header.get('total_estimated_sec') or '-'}초",
    ]
    for line in _legacy_cut_lines(directive.get("cuts")):
        lines.append(line)
    for cut in directive.get("cuts") or []:
        v2 = _dict(_dict(cut).get("v2_trace"))
        if v2.get("matched"):
            lines.append(
                f"  - (컷 {_dict(cut).get('cut_no')} 출처) V2 {v2.get('beat_id')}"
                f" · evidence {_join(v2.get('evidence_ids'))} · raw ref {_join(v2.get('raw_refs'))}"
            )
    return lines


def _narration_lines(narration: Any) -> list[str]:
    beats = _dict(narration).get("narration_beats")
    rows = beats if isinstance(beats, list) else []
    lines: list[str] = []
    for position, raw in enumerate(rows, 1):
        beat = _dict(raw)
        sentences = beat.get("sentences")
        sentence_rows = sentences if isinstance(sentences, list) else []
        text = " ".join(str(item).strip() for item in sentence_rows if str(item).strip())
        if text:
            lines.append(f"- 비트 {beat.get('beat_id') or position}: {text}")
            delivery = _dict(beat.get("number_delivery"))
            screen = [_dict(fact).get("ref") for fact in delivery.get("screen_facts") or []]
            if delivery.get("spoken_numbers") or screen:
                lines.append(
                    f"  - 말한 숫자: {_join(delivery.get('spoken_numbers'))}"
                    f" · 화면으로 보낸 근거: {_join(screen)}"
                )
    return lines


def _finding_lines(result: dict[str, Any]) -> list[str]:
    shadow = result["shadow"]
    lines: list[str] = []
    error = result.get("error")
    if error:
        lines.append(
            f"- ❌ 실행 오류({error.get('phase')}): {error.get('type')}: {error.get('message')}"
        )
    for repair in _dict(shadow.get("narration")).get("repairs") or []:
        repair = _dict(repair)
        lines.append(
            f"- phase6 코드 교정({repair.get('beat_id')}): {repair.get('repair')}"
            f" — 모델 원문: {' '.join(str(x) for x in repair.get('model_sentences') or [])}"
        )
    plan = _dict(shadow.get("narrative_plan"))
    revalidate: dict[str, int] = {}
    for warning in _dict(shadow.get("ir")).get("warnings") or []:
        parts = str(warning).split(":")
        if parts[0] == "evidence_state_disallowed" and parts[-1] in {"STALE", "NOT_CHECKED"}:
            revalidate[parts[-1]] = revalidate.get(parts[-1], 0) + 1
    if revalidate:
        counts = ", ".join(f"{state} {count}건" for state, count in sorted(revalidate.items()))
        lines.append(
            f"- 조치 필요: Fact Sheet 재검증({counts}) — 검증되지 않았거나 옛 규칙으로 검증된 근거는"
            " V2 의 근거로 쓰지 않는다"
        )
    if plan.get("warnings"):
        lines.append(f"- phase5 서사 계획 경고: {_join(plan.get('warnings'))}")
    for phase, key in (
        ("phase6 대본", "narration"),
        ("phase7 의미 충실도", "fidelity"),
        ("phase8 복잡도 게이트", "gate"),
        ("phase9 시각 계획", "visual_plan"),
        ("phase10 지시서", "directive"),
    ):
        qa = _dict(_dict(shadow.get(key)).get("qa"))
        if qa.get("errors"):
            lines.append(f"- {phase} 오류: {_join(qa.get('errors'))}")
        if qa.get("warnings"):
            lines.append(f"- {phase} 경고: {_join(qa.get('warnings'))}")
    for action in _dict(shadow.get("gate")).get("required_actions") or []:
        action = _dict(action)
        lines.append(f"- phase8 필요 조치: {action.get('action')} — {action.get('reason')}")
    for applied in _dict(shadow.get("gate")).get("applied_overrides") or []:
        applied = _dict(applied)
        lines.append(f"- phase8 적용된 override: {applied.get('signal')} — {applied.get('reason')}")
    resolution = _dict(shadow.get("resolution"))
    if resolution.get("unresolved_concepts"):
        lines.append(f"- phase4 미해결 선행 개념: {_join(resolution.get('unresolved_concepts'))}")
    lines.append(f"- 한계(미검증·미평가): {_join(result.get('non_claims'))}")
    return lines


def render_markdown(result: dict[str, Any]) -> str:
    """Render the local, human-readable comparison dossier."""
    legacy = result["legacy"]
    shadow = result["shadow"]
    run_meta = _dict(result.get("run"))
    source = _dict(_dict(shadow.get("evidence_pack")).get("source"))
    requests = _dict(run_meta.get("prerequisite_requests"))
    side_effects = _dict(result.get("side_effects"))
    run_status = result.get("run_status")
    lines = [
        "# Explanation Engine v2 — 기존 Production 과 V2 Shadow 비교", "",
        "> 동일 content ID의 **현재 저장 상태** 기반 비교다. 같은 입력으로 통제한 A/B 가 아니다.",
        "",
        "## 콘텐츠 정보", "",
        f"- 도메인: {result['domain']}",
        f"- 콘텐츠 ID: {result['content_id']}",
        f"- source depth / mode: {source.get('source_depth') or '-'} / {source.get('source_mode') or '-'}",
        f"- 현재 Fact Sheet 스냅샷 sha256: {run_meta.get('fact_sheet_snapshot_sha256') or '-'}",
        "- 동일 Fact Sheet revision: 미검증",
        f"- 실행 시각(UTC): {run_meta.get('run_at') or '-'}",
        f"- 외부 모델 호출: {'허용' if run_meta.get('model_calls_allowed') else '안 함'}"
        f" (대본 {run_meta.get('narration_model') or '-'}, 검증 {run_meta.get('critic_model') or '-'})",
        f"- run status: {run_status}",
        f"- phase8 계획 출처: {run_meta.get('content_plan_source') or '-'}",
        f"- 선행 개념 요청: {requests.get('source') or '-'} ({requests.get('count', 0)}건)",
        f"- series_split override: {run_meta.get('series_split_override_reason') or '없음'}",
    ]
    if side_effects:
        lines.append(f"- DB 기록: {json.dumps(side_effects, ensure_ascii=False)}")
    lines.extend([
        "- 렌더 영상 품질: 미검증", "- 시청자 이해도: 미검증", "",
        "## 기존 Production 대본", "",
        str(legacy.get("script_md") or "(저장 대본 없음)"), "",
        "## 기존 Production 지시서", "",
        f"- 지시서 ID: {legacy.get('directive_id') or '(없음)'}"
        f" · 버전 {legacy.get('version_type') or '-'} · 상태 {legacy.get('status') or '-'}"
        f" · 생성 {legacy.get('created_at') or '-'}",
        f"- 선택 기준: {result.get('legacy_selection') or '이 콘텐츠의 가장 최근 지시서'}",
        *_legacy_cut_lines(legacy.get("cuts")), "",
    ])

    narration = _dict(shadow.get("narration"))
    status = narration.get("generation_status") or result["phase_status"].get("phase6")
    lines.extend([f"## V2 Shadow 대본 (phase6: {status})", ""])
    narration_lines = _narration_lines(narration)
    if narration_lines and status != "DRAFT_ACCEPTED":
        lines.append("> ⚠ 엔진이 **거절한** 대본이다. V2 결과물로 쓰이지 않는다 — 사유는 아래 '차단·경고'.")
        lines.append("")
    if narration_lines:
        lines.extend(narration_lines)
    elif run_status == "MODEL_CALL_REQUIRED":
        lines.append("- 외부 모델 호출 전 중단: `--with-model`이 필요합니다.")
    else:
        lines.append("- 생성된 V2 대본 없음")

    lines.extend(["", "## V2 추적 골격 (간이 화면 계획 — 렌더용 아님)", ""])
    directive = shadow.get("directive")
    if isinstance(directive, dict):
        lines.extend(_shadow_cut_lines(directive, shadow.get("visual_plan")))
    elif run_status == "MODEL_CALL_REQUIRED":
        lines.append("- 외부 모델 호출 전 중단으로 새 지시서를 만들지 않았습니다.")
    elif run_status == "ERROR":
        lines.append("- 새 지시서 미발행: 실행 오류로 중단했습니다.")
    else:
        lines.append("- 새 지시서 미발행: 안전 게이트가 차단했습니다.")

    lines.extend(["", "## V2 지시서 (기존 생성기로 만든 것)", ""])
    lines.extend(_generated_lines(result))

    lines.extend(["", "## 차단·경고", "", *_finding_lines(result)])
    lines.extend(["", "## 단계 판정", ""])
    lines.extend(f"- {phase}: {value}" for phase, value in result["phase_status"].items())
    return "\n".join(lines).rstrip() + "\n"
