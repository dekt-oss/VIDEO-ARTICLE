"""Phase 3 "생각하는 단계" — 모델은 생각하고 코드는 근거 연결만 본다(2026-10-05 재구현)."""

from __future__ import annotations

import json

from engine import explanation_reasoning as er

PACK = {
    "domain": "paper", "content_id": "p1",
    "source": {"source_depth": "full_body", "source_mode": "FULL_EXPLAINER",
               "attribution": {"title": "Sound and fibroblasts"}},
    "claims": [
        {"evidence_id": "paper:C01", "text": "조화 음향 처리는 재생을 평균 26.8% 높였다.",
         "claim_type": "main_result", "verification_state": "SUPPORTED"},
        {"evidence_id": "paper:C02", "text": "노출 시간이 늘수록 재생이 커졌다.",
         "claim_type": "main_result", "verification_state": "SUPPORTED"},
    ],
    "limitations": [{"evidence_id": "paper:limitation:01", "text": "시험관 세포 실험이다.",
                     "verification_state": "SUPPORTED"}],
    "numbers": [], "risks": [], "background_context": [],
}


def _good():
    step = lambda n, ids, answer: {"step_id": f"S{n}", "question": "왜?", "answer": answer,
                                   "relation_to_previous": "question_answer", "kind": "observation",
                                   "evidence_ids": ids, "must_visualize": "배양 접시의 빈틈이 메워진다"}
    return {
        "core_question": "소리가 상처 난 세포를 더 빨리 아물게 할 수 있을까?",
        "viewer_reason_to_care": "상처 치료", "starting_assumption": "", "surprising_conflict": "",
        "story_pattern": "EXPERIMENT", "story_pattern_reason": "실험 하나가 중심",
        "explanation_steps": [step(1, ["paper:C01"], "재생이 26.8% 높아졌다"),
                              step(2, ["paper:C02"], "오래 들려줄수록 더 컸다"),
                              step(3, ["paper:limitation:01"], "다만 접시 위 세포다")],
        "payoff": {"text": "소리로 세포를 자극할 가능성", "evidence_ids": ["paper:C01"]},
        "limitations": [{"text": "시험관 실험", "evidence_ids": ["paper:limitation:01"]}],
        "prerequisite_concepts": [{"concept": "섬유아세포", "simple_explanation": "상처를 메우는 세포",
                                   "basis": "glossary_needed", "evidence_ids": []}],
    }


def test_good_reasoning_has_no_errors():
    qa = er.validate(_good(), PACK)
    assert qa["errors"] == []
    assert "glossary_needed:섬유아세포" in qa["warnings"]


def test_generic_question_and_bad_pattern_are_errors():
    bad = {**_good(), "core_question": "이 연구는 무엇을 보여 주는가?", "story_pattern": "DRIVER_CHAIN"}
    errors = er.validate(bad, PACK)["errors"]
    assert "core_question_generic" in errors and "story_pattern_invalid:DRIVER_CHAIN" in errors


def test_evidence_link_errors():
    bad = _good()
    bad["explanation_steps"][0]["evidence_ids"] = []
    bad["explanation_steps"][1]["evidence_ids"] = ["paper:C99"]
    bad["explanation_steps"][2]["answer"] = "세포가 40% 늘었다"            # 근거에 없는 숫자
    errors = er.validate(bad, PACK)["errors"]
    assert "no_evidence:S1" in errors
    assert "unknown_evidence:S2:paper:C99" in errors
    assert "number_not_in_cited_evidence:S3:40%" in errors


def test_step_count_follows_source_depth():
    brief = {**PACK, "source": {**PACK["source"], "source_mode": "BRIEF_EXPLAINER"}}
    assert "step_count_out_of_range:3not_in_2-3" not in er.validate(_good(), brief)["errors"]
    summary = {**PACK, "source": {**PACK["source"], "source_mode": "SUMMARY_ONLY"}}
    assert "step_count_out_of_range:3not_in_1-2" in er.validate(_good(), summary)["errors"]


def test_think_sends_evidence_and_records_purpose(monkeypatch):
    seen = {}

    def fake_call(**kw):
        seen.update(kw)
        return _good()

    monkeypatch.setattr(er, "call_json", fake_call)
    out = er.think(PACK, title="소리와 세포")
    payload = json.loads(seen["user"])
    assert {e["evidence_id"] for e in payload["evidence"]} == {"paper:C01", "paper:C02", "paper:limitation:01"}
    assert payload["step_range"] == [3, 6] and "EXPERIMENT" in payload["story_pattern_candidates"]
    assert out["qa"]["errors"] == []
    md = er.markdown(out, title="소리와 세포", evidence=er.evidence_index(PACK))
    assert "소리가 상처 난 세포를" in md and "`paper:C01` 조화 음향" in md


def test_step_kind_accepts_korean_and_combined_labels():
    assert er.step_kind("전망") == "forecast" and er.step_kind("저자 해석") == "author_interpretation"
    assert er.step_kind("observation_and_interpretation") == "interpretation"
    assert er.step_kind("모름") == ""
