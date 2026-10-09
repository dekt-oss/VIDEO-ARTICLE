"""Explanation Engine v2 Phase 13 — 최종 발행 관문(QA 통합). 원 작업지시서 §15.

흩어져 있던 검사를 **원문 → 논리 → 대본 → 화면 → 렌더** 순서의 다섯 질문으로 묶는다.

  Source     이 깊이의 원문으로 이 정도 설명을 해도 되는가?          (Phase 2·8 원문 검사)
  Reasoning  질문에 답하는 논리가 실제 근거로 이어지는가?             (Phase 3·4·5)
  Narration  사실이 맞고, 사람이 들어도 쉬운가?                       (Phase 6·7)
  Visual     화면이 같은 내용을 설명하는가?                            (Phase 8·9·10 + 기존 생성기 지시서 + 화면 움직임 계획)
  Render     선언된 변화가 실제 픽셀 변화로 나타났는가?                (렌더 QA — 렌더 뒤에만)

★ 새 차단을 만들지 않는다(2026-10-05 운영자: "먼저 완성, 영상 표현 우선"). 각 단계가 이미 낸 판정을 읽어
  한 장의 성적표로 모을 뿐이다. 유일하게 새로 보는 것은 S2~S5 로 생긴 **화면 움직임이 읽을 시간 안에
  끝나는가**인데, 이것도 경고다.
★ 앞 단계가 FAIL 이면 뒤 단계는 판정하지 않는다(NOT_RUN) — 대본이 거절됐는데 화면을 "통과"라고 적으면
  성적표가 거짓말을 한다.
★ 순수 모듈: 비교 결과 dict(와 선택적으로 렌더 QA dict)만 읽는다. DB·모델·ffmpeg 를 모른다.
"""

from __future__ import annotations

from typing import Any

from . import config, content_complexity_gate, evidence_overlay, overlay_motion, sequence_render

CONTRACT_VERSION = "publish-gate-v2.0"

STAGES: tuple[tuple[str, str], ...] = (
    ("source", "이 깊이의 원문으로 이 정도 설명을 해도 되는가?"),
    ("reasoning", "질문에 답하는 논리가 실제 근거로 이어지는가?"),
    ("narration", "사실이 맞고, 사람이 들어도 쉬운가?"),
    ("visual", "화면이 같은 내용을 설명하는가?"),
    ("render", "선언된 변화가 실제 픽셀 변화로 나타났는가?"),
)
STAGE_LABEL_KO = {"source": "원문", "reasoning": "논리", "narration": "대본",
                  "visual": "화면", "render": "렌더"}
STATUSES = ("PASS", "WARN", "FAIL", "NOT_RUN")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _stage(fails: list[str], warns: list[str], *, not_run: str = "") -> dict[str, Any]:
    if not_run:
        return {"status": "NOT_RUN", "fails": [], "warnings": [], "note": not_run}
    return {"status": "FAIL" if fails else ("WARN" if warns else "PASS"),
            "fails": fails, "warnings": warns, "note": ""}


def _qa(shadow: dict[str, Any], key: str) -> tuple[list[str], list[str]]:
    qa = _dict(_dict(shadow.get(key)).get("qa"))
    return [str(x) for x in _list(qa.get("errors"))], [str(x) for x in _list(qa.get("warnings"))]


def _error_in(result: dict[str, Any], phases: set[str]) -> list[str]:
    error = _dict(result.get("error"))
    if error and str(error.get("phase")) in phases:
        return [f"실행 오류({error.get('phase')}): {error.get('type')}: {error.get('message')}"]
    return []


# ── 다섯 단계 ────────────────────────────────────────────────
def _source(result: dict[str, Any]) -> dict[str, Any]:
    shadow = _dict(result.get("shadow"))
    fails = _error_in(result, {"phase2", "phase6_preflight"})
    pack, ir = shadow.get("evidence_pack"), shadow.get("ir")
    if not fails and _dict(result.get("phase_status")).get("phase2") != "READY":
        return _stage([], [], not_run="근거 묶음(Phase 2)이 만들어지지 않았다")
    if isinstance(pack, dict) and isinstance(ir, dict):
        fails += [f"원문 검사: {e}" for e in content_complexity_gate.source_errors(pack, ir)]
    warns: list[str] = []
    stale: dict[str, int] = {}
    for warning in _list(_dict(ir).get("warnings")):
        parts = str(warning).split(":")
        if parts[0] == "evidence_state_disallowed" and parts[-1] in {"STALE", "NOT_CHECKED"}:
            stale[parts[-1]] = stale.get(parts[-1], 0) + 1
    if stale:
        warns.append("Fact Sheet 재검증 필요(" + ", ".join(f"{k} {v}건" for k, v in sorted(stale.items()))
                     + ") — 그 근거는 설명에 쓰지 않았다")
    return _stage(fails, warns)


def _reasoning(result: dict[str, Any]) -> dict[str, Any]:
    shadow, phases = _dict(result.get("shadow")), _dict(result.get("phase_status"))
    if shadow.get("writer"):
        # 기존 작성기 경로(2026-10-07): 논리는 생각 단계가 설계했다 — 그 근거 연결 검사가 이 단계다.
        qa = _dict(_dict(shadow.get("reasoning")).get("qa"))
        return _stage([], [f"생각 단계 근거 연결: {e}" for e in _list(qa.get("errors"))]
                      + [f"생각 단계 참고: {w}" for w in _list(qa.get("warnings"))])
    fails = _error_in(result, {"phase3", "phase4", "phase5"})
    if not fails and shadow.get("narrative_plan") is None:
        return _stage([], [], not_run="서사 계획(Phase 5)까지 가지 못했다")
    if phases.get("phase3") == "EMPTY":
        fails.append("논증 단위가 하나도 없다(Phase 3)")
    plan_status = phases.get("phase5")
    if plan_status and plan_status != "READY":
        fails.append(f"서사 계획 판정 {plan_status}(Phase 5)")
    warns = [f"서사 계획 경고: {w}" for w in _list(_dict(shadow.get("narrative_plan")).get("warnings"))]
    unresolved = _list(_dict(shadow.get("resolution")).get("unresolved_concepts"))
    if unresolved:
        warns.append("풀지 못한 선행 개념: " + ", ".join(str(x) for x in unresolved))
    return _stage(fails, warns)


def _narration(result: dict[str, Any]) -> dict[str, Any]:
    shadow, phases = _dict(result.get("shadow")), _dict(result.get("phase_status"))
    writer = _dict(shadow.get("writer"))
    if writer:
        qa = _dict(_dict(writer.get("fidelity")).get("qa"))
        fails = [] if writer.get("status") == "PASSED" else (
            [f"사실 검증 판정 {writer.get('status')}"] + [str(e) for e in _list(qa.get("errors"))])
        warns = [str(w) for w in _list(qa.get("warnings"))]
        first = _dict(writer.get("first_attempt"))
        if first:
            why = [n for n, hit in (("사실 검증", _dict(first.get("fidelity")).get("qa_status") == "REJECTED"),
                                    ("쉬운 말 검사", bool(_dict(first.get("plain")).get("findings")))) if hit]
            warns.append(f"{'·'.join(why) or '검사'} 지적으로 한 번 다시 썼다")
        plain = _dict(writer.get("plain"))
        if plain.get("findings"):
            warns.append("쉬운 말 검사 남은 지적: " + ", ".join(str(x) for x in _list(plain.get("findings"))))
        return _stage(fails, warns)
    fails = _error_in(result, {"phase6", "phase7"})
    if not fails and shadow.get("narration") is None:
        note = ("외부 모델 호출 전 중단(--with-model 필요)"
                if result.get("run_status") == "MODEL_CALL_REQUIRED" else "대본(Phase 6)이 없다")
        return _stage([], [], not_run=note)
    if phases.get("phase6") and phases.get("phase6") != "DRAFT_ACCEPTED":
        fails.append(f"대본 판정 {phases.get('phase6')}(Phase 6)")
    if phases.get("phase7") and phases.get("phase7") != "PASSED":
        fails.append(f"의미 충실도 판정 {phases.get('phase7')}(Phase 7)")
    warns: list[str] = []
    for key in ("narration", "fidelity"):
        errors, warnings = _qa(shadow, key)
        fails += errors
        warns += warnings
    for repair in _list(_dict(shadow.get("narration")).get("repairs")):
        warns.append(f"코드가 고친 문장({_dict(repair).get('beat_id')}): {_dict(repair).get('repair')}")
    return _stage(fails, warns)


def _cut_windows(cuts: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    starts, durations, t = [], [], 0.0
    for cut in cuts:
        try:
            sec = float(cut.get("estimated_sec") or config.CUT_MIN_SEC)
        except (TypeError, ValueError):
            sec = float(config.CUT_MIN_SEC)
        starts.append(t)
        durations.append(sec)
        t += sec
    return starts, durations


def motion_plan_warnings(directive: dict[str, Any]) -> list[str]:
    """S2~S5 화면 움직임이 **컷의 예상 길이 안에서 읽힐 시간이 남는가**(렌더 전, 지시서 기준).

    카운트업 프레임(1/15초)과 드러내기 막은 원래 짧으므로 빼고, 사람이 읽어야 하는 카드만 본다.
    컷 길이는 지시서의 `estimated_sec` 이라 실제 나레이션 길이와 다를 수 있다 — 그래서 경고다.
    """
    cuts = [c for c in _list(directive.get("cuts")) if isinstance(c, dict)]
    if not cuts:
        return []
    starts, durations = _cut_windows(cuts)
    cues = evidence_overlay.build_overlay_cues(
        cuts, starts, durations, only_types=set(config.OVERLAY_ANNOTATION_TYPES))
    readable = [cue for cue in cues if not (cue[2].startswith("{") and "\\alpha" in cue[2].split("}", 1)[0])]
    out = [f"화면 글자 {w}" for w in evidence_overlay.cue_visibility_warnings(readable)]
    header = _dict(directive.get("header"))
    stage_cues = overlay_motion.stage_motion_cues(
        cuts, starts, durations, sequence_render.stage_index(header), evidence_overlay.content_band())
    for start, end, _text, _style in stage_cues:
        if end - start < config.STAGE_REVEAL_WIPE_SEC:
            out.append(f"장면 막이 컷보다 길다({end - start:.1f}s<{config.STAGE_REVEAL_WIPE_SEC}s)")
    return out


def _visual(result: dict[str, Any]) -> dict[str, Any]:
    shadow, phases = _dict(result.get("shadow")), _dict(result.get("phase_status"))
    if shadow.get("writer"):
        generated = _dict(shadow.get("generated"))
        if phases.get("production_generator") == "ERROR":
            error = _dict(shadow.get("generated_error"))
            return _stage([f"지시서 생성 오류: {error.get('type')}: {error.get('message')}"], [])
        if not generated:
            return _stage([], [], not_run="지시서를 아직 만들지 않았다(--with-directive)")
        fails = ([f"지시서 승인 차단: {r}" for r in _list(generated.get("block_reasons"))] or ["지시서 승인 차단"]
                 if generated.get("approval_blocked") else [])
        return _stage(fails, motion_plan_warnings(_dict(generated.get("directive"))))
    fails = _error_in(result, {"phase8", "phase9", "phase10"})
    if not fails and shadow.get("gate") is None:
        return _stage([], [], not_run="복잡도 게이트(Phase 8)까지 가지 못했다")
    for phase, label in (("phase8", "복잡도 게이트"), ("phase9", "시각 계획"), ("phase10", "추적 골격")):
        status = phases.get(phase)
        if status and status != "READY":
            fails.append(f"{label} 판정 {status}({phase})")
    warns: list[str] = []
    for key in ("gate", "visual_plan", "directive"):
        errors, warnings = _qa(shadow, key)
        fails += errors
        warns += warnings
    for action in _list(_dict(shadow.get("gate")).get("required_actions")):
        fails.append(f"필요 조치: {_dict(action).get('action')} — {_dict(action).get('reason')}")
    generated = _dict(shadow.get("generated"))
    bridge_status = phases.get("production_generator")
    if bridge_status == "ERROR":
        error = _dict(shadow.get("generated_error"))
        fails.append(f"기존 생성기 지시서 오류: {error.get('type')}: {error.get('message')}")
    elif not generated:
        warns.append("기존 생성기 지시서를 만들지 않았다(--with-directive) — 렌더용 화면은 아직 없다")
    else:
        if generated.get("approval_blocked"):
            fails += [f"지시서 승인 차단: {r}" for r in _list(generated.get("block_reasons"))] or ["지시서 승인 차단"]
        trace = _dict(generated.get("trace"))
        if trace.get("untraced_cuts"):
            warns.append(f"V2 대본과 이어지지 않은 컷 {trace.get('untraced_cuts')}개")
        warns += motion_plan_warnings(_dict(generated.get("directive")))
    return _stage(fails, warns)


def _render(render_qa: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(render_qa, dict) or render_qa.get("skipped"):
        return _stage([], [], not_run="렌더 전 — 최종 렌더 뒤 렌더 QA 결과를 붙이면 판정한다(--render-qa)")
    fails = [str(x) for x in _list(render_qa.get("hard_fail"))]
    warns = [str(x) for x in _list(render_qa.get("warnings"))]
    for key in ("clip_motion", "clip_fit"):
        warns += [f"{key}: {w}" for w in _list(_dict(render_qa.get(key)).get("warnings"))]
    return _stage(fails, warns)


# ── 묶기 ─────────────────────────────────────────────────────
def evaluate(result: dict[str, Any], render_qa: dict[str, Any] | None = None) -> dict[str, Any]:
    """비교 결과 → 다섯 단계 성적표 + 최종 판정.

    verdict:
      PUBLISHABLE   다섯 단계 모두 PASS
      NEEDS_REVIEW  FAIL 은 없고 경고가 있다(사람이 보고 결정)
      BLOCKED       어느 단계가 FAIL — 그 뒤 단계는 판정하지 않는다
      INCOMPLETE    FAIL 은 없지만 아직 판정 못 한 단계가 있다(대개 렌더 전)
    """
    builders = {
        "source": lambda: _source(result),
        "reasoning": lambda: _reasoning(result),
        "narration": lambda: _narration(result),
        "visual": lambda: _visual(result),
        "render": lambda: _render(render_qa),
    }
    stages: list[dict[str, Any]] = []
    stopped_at = ""
    for name, question in STAGES:
        if stopped_at:
            stage = _stage([], [], not_run=f"앞 단계({STAGE_LABEL_KO[stopped_at]}) 실패로 판정하지 않음")
        else:
            stage = builders[name]()
            if stage["status"] == "FAIL":
                stopped_at = name
        stages.append({"stage": name, "label_ko": STAGE_LABEL_KO[name], "question": question, **stage})
    statuses = [s["status"] for s in stages]
    if "FAIL" in statuses:
        verdict = "BLOCKED"
    elif "NOT_RUN" in statuses:
        verdict = "INCOMPLETE"
    elif "WARN" in statuses:
        verdict = "NEEDS_REVIEW"
    else:
        verdict = "PUBLISHABLE"
    return {"contract_version": CONTRACT_VERSION, "verdict": verdict,
            "blocked_at": stopped_at, "stages": stages}


_ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "NOT_RUN": "⏸"}
VERDICT_KO = {"PUBLISHABLE": "발행 가능", "NEEDS_REVIEW": "사람 확인 필요",
              "BLOCKED": "차단", "INCOMPLETE": "판정 미완(렌더 전 등)"}


#: 자주 나오는 경고 코드 → 쉬운 말. 성적표에서는 같은 코드를 한 줄로 묶어 개수와 함께 보인다(JSON 은 원본 그대로).
_PLAIN: dict[str, str] = {
    "length_budget_excluded": "영상 길이 때문에 뺀 논증",
    "semantic_entailment_unverified": "근거 문장이 주장을 뒷받침하는지 코드가 확인 못 한 항목",
    "author_interpretation": "저자 해석(사실이 아니라 해석으로 말해야 함)",
    "report_attribution_corrected": "증권사 귀속을 코드가 바로잡은 항목",
    "sentence_too_long": "너무 긴 문장",
    "unexplained_abbreviation": "풀이 없이 나온 약어",
    "overlay_too_brief": "너무 짧게 지나가는 화면 글자",
}


def _group(items: list[str]) -> list[str]:
    """`code:세부` 꼴은 코드별로 묶고(개수 + 예시 3개), 나머지는 그대로."""
    order: list[str] = []
    groups: dict[str, list[str]] = {}
    for item in items:
        head = item.split(": ", 1)[-1] if item.startswith(("서사 계획 경고: ", "화면 글자 ")) else item
        code, _, detail = head.partition(":")
        key = code if code in _PLAIN else item
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(detail if key == code else "")
    out: list[str] = []
    for key in order:
        if key in _PLAIN:
            details = [d.split(":")[-1] for d in groups[key] if d]
            sample = ", ".join(dict.fromkeys(details))
            sample = sample if len(sample) <= 60 else sample[:57] + "…"
            out.append(f"{_PLAIN[key]} {len(groups[key])}건" + (f" ({sample})" if sample else ""))
        else:
            out.append(key)
    return out


def markdown_lines(gate: dict[str, Any]) -> list[str]:
    """비교 자료 맨 위에 붙일 성적표(쉬운 말, 같은 종류는 묶어서)."""
    lines = [f"- **최종 판정: {VERDICT_KO.get(gate['verdict'], gate['verdict'])}** ({gate['verdict']})", ""]
    for stage in gate["stages"]:
        lines.append(f"{_ICON[stage['status']]} **{stage['label_ko']}** — {stage['question']} → {stage['status']}")
        if stage.get("note"):
            lines.append(f"  - {stage['note']}")
        fails, warns = _group(stage["fails"]), _group(stage["warnings"])
        lines += [f"  - ❌ {item}" for item in fails[:8]]
        lines += [f"  - ⚠ {item}" for item in warns[:8]]
        hidden = max(0, len(fails) - 8) + max(0, len(warns) - 8)
        if hidden:
            lines.append(f"  - … 외 {hidden}건(JSON 참조)")
    return lines
