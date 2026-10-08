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


def design_instruction(reasoning: dict[str, Any], *, fix_these: list[str] | None = None, legacy_hook: str = "") -> str:
    """생각 단계 결과 → 기존 작성기에게 주는 구성 지시. 사실은 여전히 Fact Sheet 범위 안에서만 쓴다.

    `legacy_hook` = 운영 대본의 첫 문장. 있으면 그대로 쓰게 한다(2026-10-08 운영자: 신피질 편에서 V2 가 다시 쓴 첫 질문
    여섯 개보다 운영 첫 질문 "뇌세포의 단 1%만 건드렸는데…"이 제일 낫다). 사실과 어긋나는 낱말만 고치게 한다.
    """
    lines = ["[설명 설계 — 이 순서와 질문으로 대본을 구성하라. 사실은 Fact Sheet 안에서만, 말투·후킹은 네 규칙대로]"]
    core = _text(reasoning.get("core_question"))
    if _text(legacy_hook):
        lines.append(f"- ★ 첫 장면은 이 문장을 **그대로** 써라(이미 검증된 후킹이다): «{_text(legacy_hook)}» — 단 Fact Sheet 와"
                     " 어긋나는 낱말(범위가 넓어진 숫자 등)이 있으면 그 낱말만 Fact Sheet 에 맞게 고쳐라. 아래 '이 편의 질문'은"
                     " 본문이 답할 질문으로 쓴다.")
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
    lines.append("- 귀로 듣는 대본이다: 한 장면에 이름(회사·기관·사람) 하나, 숫자 하나까지만. 더 있으면 빼거나"
                 " '여러 회사가'·'몇 배'처럼 묶어라. 화면 자막이 아니라 말이다.")
    lines.append("- ★ 검사 기준(이 대본은 쓴 뒤 문장마다 이 기준으로 검사된다 — 처음부터 맞춰 써라):")
    lines.extend(f"  · {x}" for x in semantic_fidelity.WRITER_CHECK_CRITERIA)
    if fix_these:
        lines.append("- ★ 지난 대본에서 검사에 걸린 것(반드시 고쳐라 — 사실은 빼거나 Fact Sheet 에 맞게, 말은 쉽게):")
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


def legacy_hook(legacy_draft: dict[str, Any] | None) -> str:
    """운영 대본의 첫 문장(첫 장면). 대본 장면이 있으면 첫 장면 나레이션, 없으면 script_md 첫 줄."""
    draft = legacy_draft or {}
    for key in ("video_prompts", "scenes"):
        scenes = draft.get(key)
        if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict) and _text(scenes[0].get("narration_ko")):
            return _text(scenes[0]["narration_ko"])
    for line in str(draft.get("script_md") or "").splitlines():
        if _text(line) and not _text(line).startswith(("#", "씬")):
            return _text(line)
    return ""


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


PlainJudge = Callable[[str, str], float | None]


def plain_check(beats: list[dict[str, Any]], *, hook_judge: Callable[[str], dict[str, float] | None] | None = None,
                term_judge: PlainJudge | None = None,
                crowded_judge: Callable[[str], float | None] | None = None) -> dict[str, Any]:
    """쉬운 말 검사(Jev): 첫 질문의 전문용어·답 노출, 본문의 풀지 않은 용어. **되먹임용 경고**다 — 차단하지 않는다.

    ★ 왜(2026-10-08): 사실 검사는 "맞나"만 본다. 운영자가 지적한 후킹 퇴화("피질 안 극소수 장거리 억제 뉴런이…")와
      풀지 않은 용어(델타파·Martinotti)는 사실은 맞아서 그대로 통과했다. 연구 §3 에서 Jev 가 이 둘을 갈랐다.
    Jev 가 답을 못 하면 그 문장은 검사하지 않은 것으로 남긴다(`unchecked`) — 통과로 세지 않는다.
    """
    from . import decide
    out: dict[str, Any] = {"findings": [], "feedback": [], "unchecked": 0, "scores": []}
    if not config.V2_PLAIN_CHECK:
        return out
    if hook_judge is None or term_judge is None:
        if not decide.enabled():
            out["unchecked"] = -1
            return out
    crowded_judge = crowded_judge or (decide.scene_crowded if decide.enabled() else (lambda scene: None))
    hook_judge = hook_judge or decide.hook_plainness
    term_judge = term_judge or (lambda sentence, earlier: decide.term_unexplained(sentence, earlier))
    sentences = [s for b in beats for s in b.get("sentences") or []]
    if not sentences:
        return out
    hook = hook_judge(sentences[0])
    if hook is None:
        out["unchecked"] += 1
    else:
        out["scores"].append({"sentence": sentences[0], **{k: round(v, 3) for k, v in hook.items()}})
        if hook.get("jargon", 0) >= config.V2_HOOK_JARGON_MIN:
            out["findings"].append("hook_jargon")
            out["feedback"].append(f"첫 질문 \"{sentences[0]}\" — 일반 시청자가 모르는 말이 있다. 일상어만으로 다시 써라"
                                   " (전문용어는 본문에서 풀어 주고, 첫 질문에는 넣지 마라).")
        if hook.get("spoiler", 0) >= config.V2_HOOK_SPOILER_MIN:
            out["findings"].append("hook_spoiler")
            out["feedback"].append(f"첫 질문 \"{sentences[0]}\" — 답(연구 결과)을 미리 말해 버린다. 결과는 숨기고"
                                   " '정말?' 하는 궁금증만 남겨라.")
    for i, sentence in enumerate(sentences[1:], 1):
        p = term_judge(sentence, " ".join(sentences[:i]))
        if p is None:
            out["unchecked"] += 1
            continue
        out["scores"].append({"sentence": sentence, "term": round(p, 3)})
        if p >= config.V2_TERM_UNEXPLAINED_MIN:
            out["findings"].append("term_unexplained")
            out["feedback"].append(f"\"{sentence}\" — 풀지 않은 전문용어가 있다. 처음 나올 때 쉬운 말로 한 번 풀거나"
                                   " 일상어로 바꿔라(사실은 바꾸지 마라).")
    # 장면 단위: 이름·숫자가 한 장면에 몰렸나(위성 레이저 편 3·6장면 — 회사·기관 넷과 숫자 셋이 한 장면에).
    for beat in beats:
        scene = " ".join(beat.get("sentences") or [])
        p = crowded_judge(scene)
        if p is None:
            continue
        out["scores"].append({"sentence": f"[장면 {beat.get('beat_id', '')}] {scene}", "crowded": round(p, 3)})
        if p >= config.V2_SCENE_CROWDED_MIN:
            out["findings"].append("scene_crowded")
            out["feedback"].append(f"장면 {beat.get('beat_id', '')} \"{scene[:60]}…\" — 이름·숫자가 한 장면에 몰려 귀로 못 따라간다."
                                   " 이 장면에는 이름 하나·숫자 하나만 남기고, 나머지는 빼거나 '여러 회사가'처럼 묶어라.")
    return out


def _better(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """두 회차 중 낫는 것: 사실 검사 통과가 먼저, 그다음 쉬운 말 지적이 적은 쪽. 같으면 나중 것."""
    def key(x: dict[str, Any]) -> tuple[int, int]:
        return (1 if x["fidelity"].get("qa_status") == "PASSED" else 0, -len(x["plain"]["findings"]))
    return a if key(a) > key(b) else b


def write_and_check(writer: Writer, fact_sheet: dict[str, Any], reasoning: dict[str, Any], pack: dict[str, Any], *,
                    domain: str, content_id: str, critic_caller: Callable[..., dict[str, Any]] | None = None,
                    plain_judges: tuple[Any, Any] | None = None, legacy_hook: str = "") -> dict[str, Any]:
    """설계 → 기존 작성기 → 사실 검사 + 쉬운 말 검사 → (지적이 있으면) 한 번 다시 쓰고 다시 검사. 저장하지 않는다.

    다시 쓴 쪽이 더 나쁘면(사실 검사를 새로 놓쳤으면) 앞 회차를 고른다 — 고쳐 쓰기가 멀쩡한 대본을 망치지 않게.
    """
    core = _text(reasoning.get("core_question"))
    attempts: list[dict[str, Any]] = []
    fix: list[str] | None = None
    hook_j, term_j, *rest = plain_judges or (None, None)
    crowd_j = rest[0] if rest else None
    for _ in range(2 if config.V2_NARRATION_RETRY else 1):
        instruction = design_instruction(reasoning, fix_these=fix, legacy_hook=legacy_hook)
        try:
            script = writer(fact_sheet, instruction)
        except Exception as exc:  # noqa: BLE001
            if not attempts:
                raise
            # 다시 쓰기가 죽어도 앞 회차는 살린다(2026-10-08 위성 레이저 편: 2회차가 출력 상한에서 잘려 멀쩡한 1회차까지 버렸다).
            attempts[-1]["retry_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            break
        beats = scene_beats(script.get("scenes") or [], pack)
        fidelity = _check(beats, pack, fact_sheet, domain=domain, content_id=content_id, core=core,
                          critic_caller=critic_caller)
        if fidelity.get("qa_status") == "CRITIC_ERROR":          # 검증관 형식 실수는 대본 탓이 아니다 — 검증만 한 번 더
            fidelity = _check(beats, pack, fact_sheet, domain=domain, content_id=content_id, core=core,
                              critic_caller=critic_caller)
        plain = plain_check(beats, hook_judge=hook_j, term_judge=term_j, crowded_judge=crowd_j)
        attempts.append({"instruction": instruction, "script": script, "beats": beats, "fidelity": fidelity,
                         "plain": plain})
        rejected = fidelity.get("qa_status") == "REJECTED"
        if not rejected and not plain["findings"]:
            break
        fix = [*(semantic_fidelity.fix_feedback(fidelity) if rejected else []), *plain["feedback"]]
    final = attempts[0]
    for later in attempts[1:]:
        final = _better(final, later)
    return {"status": final["fidelity"].get("qa_status"), "script": final["script"], "beats": final["beats"],
            "retry_error": attempts[-1].get("retry_error"),
            "fidelity": final["fidelity"], "plain": final["plain"], "instruction": final["instruction"],
            "attempts": len(attempts), "chosen_attempt": attempts.index(final) + 1,
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
