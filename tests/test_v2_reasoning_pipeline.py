"""V2 새 경로 — 생각 단계 → 설명 설계 → 이야기 → 대본 → 2차 다듬기 → 사실 검증 (2026-10-06, 가짜 모델만)."""

from __future__ import annotations

import json

import pytest

from engine import config, semantic_fidelity
import test_explanation_shadow_pipeline as base

STEPS = [
    ("S1", "압력이 높아지면 구조가 바뀝니다.", "question_answer", "observation"),
    ("S2", "눌리면 모양이 달라지는 것입니다.", "cause_effect", "author_interpretation"),
    ("S3", "그래서 압력이 구조를 바꾸는 열쇠입니다.", "process_next", "observation"),
]


def _reasoning(**_kw):
    return {
        "core_question": "누르면 물질의 모양이 바뀔까?",
        "viewer_reason_to_care": "생활 속 물건", "starting_assumption": "", "surprising_conflict": "",
        "story_pattern": "WHY", "story_pattern_reason": "원리 중심",
        "prerequisite_concepts": [{"concept": "결정 구조", "simple_explanation": "원자가 줄지어 선 모양",
                                   "basis": "glossary_needed", "evidence_ids": []}],
        "explanation_steps": [{"step_id": sid, "question": "왜?", "answer": answer, "relation_to_previous": rel,
                               "kind": kind, "uncertainty": "", "evidence_ids": ["paper:C01"],
                               "must_visualize": "눌리는 결정"} for sid, answer, rel, kind in STEPS],
        "payoff": {"text": "압력이 구조를 바꾼다.", "evidence_ids": ["paper:C01"]},
        "limitations": [], "excluded_details": [], "target_complexity": "standard",
    }


@pytest.fixture
def v2_on(monkeypatch):
    monkeypatch.setattr(config, "V2_EXPLANATION_REASONING", True)


def test_thinking_result_becomes_the_explanation_and_each_step_its_own_beat(v2_on):
    seen = {}

    def narration(**kw):
        seen.update(json.loads(kw["user"]))
        return base._narration_caller(**kw)

    result = base._run(reasoning_caller=_reasoning, narration_caller=narration)

    assert result["run_status"] == "READY", (result["phase_status"], result.get("error"))
    ir = result["shadow"]["ir"]
    assert ir["origin"] == "model_reasoning" and ir["core_question"] == "누르면 물질의 모양이 바뀔까?"
    assert [u.get("source_reasoning_id") for u in ir["reasoning_units"]] == ["S1", "S2", "S3", "PAYOFF"]
    beats = result["shadow"]["narrative_plan"]["beats"]
    assert beats[0]["content_points"] == ["누르면 물질의 모양이 바뀔까?"]       # 범용 질문이 아니다
    assert [b["content_points"] for b in beats[1:]] == [[a] for _, a, _, _ in STEPS] + [["압력이 구조를 바꾼다."]]
    assert seen["terms_to_gloss"] == [{"term": "결정 구조", "plain": "원자가 줄지어 선 모양"}]
    assert result["shadow"]["reasoning"]["qa"]["errors"] == []


def test_dry_run_keeps_the_old_path_and_never_calls_the_thinking_model(v2_on):
    def must_not_run(**_kw):
        raise AssertionError("dry run 에서 생각 단계를 불렀다")

    result = base._run(allow_model_calls=False, reasoning_caller=must_not_run)
    assert result["run_status"] == "MODEL_CALL_REQUIRED"
    assert result["shadow"]["ir"]["origin"] == "adapter"


def test_source_check_runs_before_paying_for_thinking(v2_on, monkeypatch):
    """원문 깊이·모드 기록이 어긋난 입력은 생각 단계 모델을 부르기 **전에** 멈춘다(돈을 쓴 뒤 죽지 않게)."""
    from engine import content_complexity_gate
    monkeypatch.setattr(content_complexity_gate, "source_errors", lambda pack, ir: ["source_depth_mismatch"])

    def must_not_run(**_kw):
        raise AssertionError("원문 검사 전에 생각 단계 모델을 불렀다")

    result = base._run(reasoning_caller=must_not_run)
    assert result["run_status"] == "ERROR"
    assert result["error"]["phase"] == "phase3_preflight"
    assert result["phase_status"]["phase3"] == "ERROR"


def test_thinking_step_count_follows_source_depth():
    """얕은 원문은 단계 수 범위가 좁아진다 — 깊이를 억지로 늘리지 않는다(작업지시서 §3)."""
    from engine import explanation_reasoning as er
    assert er.STEP_RANGE_BY_MODE["SUMMARY_ONLY"] == (1, 2)
    assert er.STEP_RANGE_BY_MODE["BRIEF_EXPLAINER"] == (2, 3)


def test_polish_applies_safe_rewrites_and_drops_unsafe_ones(v2_on, monkeypatch):
    monkeypatch.setattr(config, "V2_SPOKEN_POLISH", True)

    def polisher(**kw):
        beats = json.loads(kw["user"])["beats"]
        out = []
        for b in beats:
            sentences = list(b["sentences"])
            if b["beat_id"] == "NB02":
                sentences = ["압력이 높아지면 구조가 바뀌어요."]               # 말투만 — 적용
            if b["beat_id"] == "NB03":
                sentences = ["눌리면 모든 모양이 달라집니다."]                 # 범위 강화 — 버린다
            out.append({"beat_id": b["beat_id"], "sentences": sentences})
        return {"beats": out}

    result = base._run(reasoning_caller=_reasoning, polish_caller=polisher)

    polish = result["shadow"]["narration"]["polish"]
    assert polish["applied"] == ["NB02"]
    assert [r["beat_id"] for r in polish["rejected"]] == ["NB03"]
    sentences = {b["beat_id"]: b["sentences"] for b in result["shadow"]["narration"]["narration_beats"]}
    assert sentences["NB02"] == ["압력이 높아지면 구조가 바뀌어요."]
    assert sentences["NB03"] == ["눌리면 모양이 달라지는 것입니다."]


def test_polish_failure_keeps_the_accepted_draft(v2_on, monkeypatch):
    monkeypatch.setattr(config, "V2_SPOKEN_POLISH", True)

    def broken(**_kw):
        raise TimeoutError("polish timeout")

    result = base._run(reasoning_caller=_reasoning, polish_caller=broken)
    assert result["phase_status"]["phase6"] == "DRAFT_ACCEPTED"
    assert result["shadow"]["polish_error"]["type"] == "TimeoutError"


def _critic_with_comparison(text: str):
    def critic(**kw):
        payload = base._critic_caller(**kw)
        for clause in payload["clauses"]:
            if clause["clause_text"] == "그래서 압력이 구조를 바꾸는 열쇠입니다.":
                clause.update(clause_text=text, clause_kind="COMPARISON", verdict="RHETORICAL",
                              evidence_ids=[], rationale="비교")
        return payload
    return critic


def _narration_with(text: str):
    def narration(**kw):
        payload = base._narration_caller(**kw)
        for beat in payload["beats"]:
            if beat["sentences"] == ["그래서 압력이 구조를 바꾸는 열쇠입니다."]:
                beat["sentences"] = [text]
        return payload
    return narration


def test_marked_comparison_is_allowed_but_not_with_numbers(v2_on):
    ok = "마치 열쇠처럼 압력이 구조를 엽니다."
    result = base._run(reasoning_caller=_reasoning, narration_caller=_narration_with(ok),
                       critic_caller=_critic_with_comparison(ok))
    assert result["phase_status"]["phase7"] == "PASSED", result["shadow"]["fidelity"]["qa"]

    bad = "마치 3배 단단한 열쇠처럼 바뀝니다."
    review = semantic_fidelity._semantic_findings(
        [{"clause_id": "SC1", "narration_id": "SN04", "clause_kind": "COMPARISON", "verdict": "RHETORICAL",
          "clause_text": bad, "evidence_ids": [], "finding_codes": []}],
        {"SN04": {"stage": "EVIDENCE", "sentences": [bad]}}, {}, {}, "q?")
    assert review[0] is True and "comparison_exemption_invalid:SC1" in review[1]


def test_rejected_script_is_rewritten_once_with_plain_feedback(v2_on):
    calls = []

    def narration(**kw):
        payload = json.loads(kw["user"])
        calls.append(payload.get("fix_these_from_previous_attempt"))
        out = base._narration_caller(**kw)
        if len(calls) == 1:                                     # 첫 시도: 재료에 없는 숫자를 지어낸다
            out["beats"][1]["sentences"] = [out["beats"][1]["sentences"][0] + " 30% 바뀝니다."]
        return out

    result = base._run(reasoning_caller=_reasoning, narration_caller=narration)

    assert len(calls) == 2 and calls[0] is None
    assert any("숫자" in line for line in calls[1]), calls[1]
    assert result["shadow"]["narration_first_attempt"]["generation_status"] == "REJECTED_DRAFT"
    assert result["phase_status"]["phase6"] == "DRAFT_ACCEPTED"


def test_critic_format_mistake_is_retried_once(v2_on):
    calls = []

    def critic(**kw):
        calls.append(1)
        payload = base._critic_caller(**kw)
        if len(calls) == 1:
            payload["clauses"][1]["evidence_ids"] = ["paper:C99"]          # 검증관이 없는 근거를 댔다
        return payload

    result = base._run(reasoning_caller=_reasoning, critic_caller=critic)
    assert len(calls) == 2
    assert result["shadow"]["fidelity_first_attempt"]["qa_status"] == "CRITIC_ERROR"
    assert result["phase_status"]["phase7"] == "PASSED"


def test_keyword_meaning_checks_are_handed_to_the_critic_on_the_reasoning_path(v2_on):
    def narration(**kw):
        out = base._narration_caller(**kw)
        out["beats"][1]["sentences"] = [out["beats"][1]["sentences"][0] + " 이것이 원인입니다."]
        return out

    result = base._run(reasoning_caller=_reasoning, narration_caller=narration)
    qa = result["shadow"]["narration"]["qa"]
    assert result["phase_status"]["phase6"] == "DRAFT_ACCEPTED"
    assert any(w.startswith("critic_judges:causal_language_added") for w in qa["warnings"])


def test_critic_slips_are_tolerated_not_fatal(v2_on):
    def critic(**kw):
        payload = base._critic_caller(**kw)
        payload["clauses"][1]["finding_codes"] = []
        payload["clauses"][2]["finding_codes"] = []
        payload["clauses"][2]["evidence_ids"] = list(payload["clauses"][2]["evidence_ids"]) + ["paper:C01"]
        return payload

    result = base._run(reasoning_caller=_reasoning, critic_caller=critic)
    assert result["phase_status"]["phase7"] == "PASSED"


def test_critic_alias_finding_still_rejects():
    from engine import semantic_fidelity as sf
    assert sf._FINDING_ALIASES["scope_overextension"] == "scope_expansion"
    assert sf._FINDING_ALIASES["unjustified_causal_link"] == "causal_upgrade"
