"""V2 = 설계는 생각 단계, 말은 **기존 작성기**, 검사는 V2 검증관 (2026-10-07 운영자 결정 "추천대로").

★ 왜(2026-10-07): V2 가 따로 만든 대본 작성기(Phase 5·6)는 기존 작성기(`scriptgen`·`report_scriptgen`)가 몇 달간
  운영자 피드백으로 다듬은 후킹 장치(첫 질문 규칙·4막·벤치마크 기준)를 다시 만들지 않았고, 그 자리에 원문 이탈 검사만
  늘렸다. 결과: 사실은 덜 틀리지만 일반 시청자 후킹이 퇴화했다("뇌세포의 단 1%만 건드렸는데…" → "피질 안 극소수 장거리
  억제 뉴런이…"). 그래서 말 쓰기는 기존 작성기에 맡기고, V2 는 앞(생각 단계 설계)과 뒤(근거 대조 검증)만 맡는다.

흐름: 생각 단계 결과 → 설계 지시문(`design_instruction`) → 기존 작성기 `instruction` 칸(운영자 수정 요청 칸과 같은 자리 —
  "Fact Sheet 사실 범위 안에서 표현·구성만") → 장면 → 근거가 붙은 비트(`scene_beats`) → V2 검증관(`review_scenes`) →
  진짜 지적이 있으면 그 지적을 붙여 **한 번** 다시 쓰고 다시 검증.

출력은 기존 초안과 같은 모양(script_md·scenes·video_flow …)이라 기존 지시서 생성기에 그대로 들어간다.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from . import config, explanation_ir, semantic_fidelity

Writer = Callable[[dict[str, Any], str], dict[str, Any]]

_SENTENCE_END = re.compile(r"(?<=[.?!。？！])\s+")
_REL_KO = {"question_answer": "질문에 답", "cause_effect": "원인→결과", "whole_detail": "전체→부분",
           "phenomenon_data": "현상→근거", "contrast": "대비", "process_next": "다음 과정", "micro_whole": "부분→전체"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def design_instruction(reasoning: dict[str, Any], *, fix_these: list[str] | None = None) -> str:
    """생각 단계 결과 → 기존 작성기에게 주는 구성 지시. 사실은 여전히 Fact Sheet 범위 안에서만 쓴다."""
    lines = ["[설명 설계 — 이 순서와 질문으로 대본을 구성하라. 사실은 Fact Sheet 안에서만, 말투·후킹은 네 규칙대로]"]
    core = _text(reasoning.get("core_question"))
    if core:
        lines.append(f"- 이 편의 질문(첫 장면은 이 질문을 시청자가 '정말?' 하게 짧고 강하게 던져라): {core}")
    for label, key in (("왜 관심을 가져야 하나", "viewer_reason_to_care"), ("사람들이 보통 아는 것", "starting_assumption"),
                       ("반전", "surprising_conflict")):
        if _text(reasoning.get(key)):
            lines.append(f"- {label}: {_text(reasoning[key])}")
    if _text(reasoning.get("story_pattern")):
        lines.append(f"- 이야기 틀: {reasoning['story_pattern']} — {_text(reasoning.get('story_pattern_reason'))}")
    steps = [s for s in reasoning.get("explanation_steps") or [] if isinstance(s, dict)]
    if steps:
        lines.append("- 설명 단계(이 순서로, 한 장면에 한 단계씩. 단계의 질문을 시청자 대신 던지고 쉬운 말로 답하라):")
        for n, s in enumerate(steps, 1):
            rel = _REL_KO.get(_text(s.get("relation_to_previous")), "")
            lines.append(f"  {n}. ({rel}) 질문: {_text(s.get('question'))} / 답 요지: {_text(s.get('answer'))}"
                         + (f" / 화면: {_text(s.get('must_visualize'))}" if _text(s.get("must_visualize")) else ""))
    payoff = reasoning.get("payoff") if isinstance(reasoning.get("payoff"), dict) else {}
    if _text(payoff.get("text")):
        lines.append(f"- 그래서(마무리): {_text(payoff['text'])}")
    limits = [_text(x.get("text")) for x in reasoning.get("limitations") or [] if isinstance(x, dict) and _text(x.get("text"))]
    if limits:
        lines.append("- 한계(마무리에서 한두 문장으로 묶어서): " + " / ".join(limits))
    gloss = [c for c in reasoning.get("prerequisite_concepts") or [] if isinstance(c, dict) and _text(c.get("concept"))]
    if gloss:
        lines.append("- 처음 한 번 쉬운 말로 풀 용어: " + ", ".join(
            f"{_text(c['concept'])}({_text(c.get('simple_explanation'))})" for c in gloss))
    lines.append(f"- 길이: {config.V2_TARGET_MIN_SEC}~{config.V2_TARGET_MAX_SEC}초 안에서 이해에 필요한 만큼. 억지로 늘리지 마라.")
    lines.append("- ★ 검사 기준(이 대본은 쓴 뒤 문장마다 이 기준으로 검사된다 — 처음부터 맞춰 써라):")
    lines.extend(f"  · {x}" for x in semantic_fidelity.WRITER_CHECK_CRITERIA)
    if fix_these:
        lines.append("- ★ 지난 대본에서 사실 검증에 걸린 것(반드시 고쳐라 — 빼거나 Fact Sheet 에 맞게):")
        lines.extend(f"  · {x}" for x in fix_these)
    return "\n".join(lines)


def _scene_evidence(scene: dict[str, Any], pack: dict[str, Any], by_ref: dict[str, str]) -> list[str]:
    """장면이 가리킨 근거 → 근거 묶음 id. 주장 번호(C01)·출처 키(numbers[3])·리포트 논증 번호(R01)."""
    ids: list[str] = []
    for cid in scene.get("claim_ids") or []:
        ref = f"claims:{_text(cid)}"
        if ref in by_ref:
            ids.append(by_ref[ref])
    for fact in scene.get("source_facts") or []:
        if _text(fact) in by_ref:
            ids.append(by_ref[_text(fact)])
    rid = _text(scene.get("reasoning_id"))
    if rid:
        ids.extend(e for e in by_ref.values() if e.startswith(f"report:step:{rid}#"))
    return list(dict.fromkeys(ids))


def scene_beats(scenes: list[dict[str, Any]], pack: dict[str, Any]) -> list[dict[str, Any]]:
    """기존 작성기 장면 → 검증관이 보는 비트. 첫 장면은 질문(HOOK), 한계 장면은 BOUNDARY, 마지막은 정리(PAYOFF)."""
    index = explanation_ir.build_index(pack)
    by_ref = {_text(item.get("raw_ref")): eid for eid, item in index.items() if _text(item.get("raw_ref"))}
    beats: list[dict[str, Any]] = []
    for n, scene in enumerate(scenes, 1):
        text = _text(scene.get("narration_ko"))
        if not text:
            continue
        if n == 1:
            stage = "HOOK"
        elif _text(scene.get("evidence_role")) == "caveat":
            stage = "BOUNDARY"
        elif n == len(scenes):
            stage = "PAYOFF"
        else:
            stage = "EVIDENCE"
        beats.append({
            "narration_id": f"SN{len(beats) + 1:02d}", "beat_id": f"SC{int(scene.get('scene') or n):02d}",
            "stage": stage, "sentences": [s for s in _SENTENCE_END.split(text) if s.strip()],
            "reasoning_ids": [], "evidence_ids": _scene_evidence(scene, pack, by_ref), "concept_ids": [],
            "knowledge_refs": [], "causal_levels": [], "uncertainties": [], "attributions": [],
        })
    return beats


def critic_backend(critic_caller: Callable[..., dict[str, Any]] | None = None) -> str:
    """가짜 LLM 검증관을 넘기면(테스트) 그 모양 그대로 llm, 아니면 설정(V2_CRITIC_BACKEND, 기본 jev)."""
    return "llm" if critic_caller is not None else config.V2_CRITIC_BACKEND


def _check(beats: list[dict[str, Any]], pack: dict[str, Any], fact_sheet: dict[str, Any], *, domain: str,
           content_id: str, core: str, critic_caller: Callable[..., dict[str, Any]] | None) -> dict[str, Any]:
    if critic_backend(critic_caller) == "jev":
        return semantic_fidelity.review_scenes_jev(beats, pack, fact_sheet, domain=domain, content_id=content_id,
                                                   core_question=core)
    return semantic_fidelity.review_scenes(beats, pack, domain=domain, content_id=content_id,
                                           core_question=core, caller=critic_caller)


def write_and_check(writer: Writer, fact_sheet: dict[str, Any], reasoning: dict[str, Any], pack: dict[str, Any], *,
                    domain: str, content_id: str, critic_caller: Callable[..., dict[str, Any]] | None = None
                    ) -> dict[str, Any]:
    """설계 → 기존 작성기 → V2 검증관 → (진짜 지적이면) 한 번 다시 쓰고 다시 검증. 저장하지 않는다."""
    core = _text(reasoning.get("core_question"))
    attempts: list[dict[str, Any]] = []
    fix: list[str] | None = None
    for _ in range(2 if config.V2_NARRATION_RETRY else 1):
        instruction = design_instruction(reasoning, fix_these=fix)
        script = writer(fact_sheet, instruction)
        beats = scene_beats(script.get("scenes") or [], pack)
        fidelity = _check(beats, pack, fact_sheet, domain=domain, content_id=content_id, core=core,
                          critic_caller=critic_caller)
        if fidelity.get("qa_status") == "CRITIC_ERROR":          # 검증관 형식 실수는 대본 탓이 아니다 — 검증만 한 번 더
            fidelity = _check(beats, pack, fact_sheet, domain=domain, content_id=content_id, core=core,
                              critic_caller=critic_caller)
        attempts.append({"instruction": instruction, "script": script, "beats": beats, "fidelity": fidelity})
        if fidelity.get("qa_status") != "REJECTED":
            break
        fix = semantic_fidelity.fix_feedback(fidelity)
    final = attempts[-1]
    return {"status": final["fidelity"].get("qa_status"), "script": final["script"], "beats": final["beats"],
            "fidelity": final["fidelity"], "instruction": final["instruction"], "attempts": len(attempts),
            "first_attempt": attempts[0] if len(attempts) > 1 else None}


def default_writer(domain: str, *, packet: dict[str, Any] | None = None,
                   financial_reasoning: dict[str, Any] | None = None) -> Writer:
    """기존 운영 작성기. 논문 `scriptgen.generate`, 리포트 `report_scriptgen.generate`(원문·논증 단위 포함).

    V2 에서는 나레이션만 쓴다(narration_only) — 장면 그림·영상 프롬프트는 지시서가 다시 정한다(2026-10-08).
    """
    if domain == "paper":
        from . import scriptgen
        return lambda fact_sheet, instruction: scriptgen.generate(fact_sheet, instruction, narration_only=True)
    from . import report_scriptgen
    return lambda fact_sheet, instruction: report_scriptgen.generate(
        fact_sheet, instruction, packet=packet, reasoning=financial_reasoning, narration_only=True)
