"""V2 = 생각 단계 설계 + 기존 작성기 + V2 검증관 (2026-10-07 운영자 "추천대로"). 가짜 모델만."""

from __future__ import annotations

import json

import pytest

from engine import config, v2_writer
import test_explanation_shadow_pipeline as base
from test_v2_reasoning_pipeline import _reasoning


def _script(narrations=("소리로 세포가 더 빨리 아물까요?", "압력이 높아지면 구조가 바뀝니다.", "그래서 압력이 열쇠입니다.")):
    return {"script_md": "\n\n".join(narrations), "upload_title_ko": "t", "upload_title_en": "t",
            "video_flow": {}, "scenes": [
                {"scene": n, "narration_ko": text, "claim_ids": ["C01"] if n > 1 else [],
                 "source_facts": [], "evidence_role": "primary_result"} for n, text in enumerate(narrations, 1)]}


@pytest.fixture
def writer_on(monkeypatch):
    monkeypatch.setattr(config, "V2_EXPLANATION_REASONING", True)
    monkeypatch.setattr(config, "V2_WRITER", "production")


def test_design_instruction_carries_the_thinking_design():
    text = v2_writer.design_instruction(_reasoning(), fix_these=["SC02: 근거 없는 문장"])
    assert "누르면 물질의 모양이 바뀔까?" in text and "설명 단계" in text
    assert "압력이 높아지면 구조가 바뀝니다." in text           # 단계의 답 요지
    assert "결정 구조(원자가 줄지어 선 모양)" in text              # 풀어 줄 용어
    assert "SC02: 근거 없는 문장" in text and f"{config.V2_TARGET_MAX_SEC}초" in text


def test_scene_beats_map_scene_citations_to_evidence():
    from engine import evidence_pack
    pack = evidence_pack.build(base._paper_fact_sheet(), "paper", content_id="paper-1")
    beats = v2_writer.scene_beats(_script()["scenes"], pack)
    assert [b["stage"] for b in beats] == ["HOOK", "EVIDENCE", "PAYOFF"]
    assert beats[0]["evidence_ids"] == [] and beats[1]["evidence_ids"] == ["paper:C01"]


def test_existing_writer_path_end_to_end(writer_on):
    seen = []

    def writer(fact_sheet, instruction):
        seen.append(instruction)
        return _script()

    result = base._run(reasoning_caller=_reasoning, writer_caller=writer)
    assert result["run_status"] == "READY", (result["phase_status"], result.get("error"))
    assert result["phase_status"]["phase7"] == "PASSED"
    assert "누르면 물질의 모양이 바뀔까?" in seen[0]
    stages = {s["stage"]: s["status"] for s in result["publish_gate"]["stages"]}
    assert stages["narration"] == "PASS"
    from engine import explanation_shadow_pipeline as p
    md = p.render_markdown(result)
    assert "V2 대본 (설계: 생각 단계 · 말: 기존 작성기" in md and "소리로 세포가 더 빨리 아물까요?" in md
    assert "## V2 Shadow 대본" not in md


def test_critic_rejection_rewrites_once_with_its_findings(writer_on):
    seen = []

    def writer(fact_sheet, instruction):
        seen.append(instruction)
        return _script()

    calls = []

    def critic(**kw):
        calls.append(1)
        payload = base._critic_caller(**kw)
        if len(calls) == 1:
            payload["clauses"][1].update(verdict="UNSUPPORTED", rationale="근거에 없는 단정")
        return payload

    result = base._run(reasoning_caller=_reasoning, writer_caller=writer, critic_caller=critic)
    assert len(seen) == 2 and "사실 검증에 걸린 것" in seen[1]
    assert result["shadow"]["writer"]["first_attempt"]["fidelity"]["qa_status"] == "REJECTED"
    assert result["phase_status"]["phase7"] == "PASSED"


def test_directive_is_made_by_the_existing_generator_from_the_v2_script(writer_on):
    drafts = []

    def generator(draft):
        drafts.append(draft)
        return {"version_type": "photo", "header": {}, "cuts": [{"cut_no": 1, "narration_ko": "x"}]}

    result = base._run(reasoning_caller=_reasoning, writer_caller=lambda fs, ins: _script(),
                       with_directive=True, directive_generator=generator)
    assert result["phase_status"]["production_generator"] == "READY"
    assert drafts[0]["script_md"].startswith("소리로 세포가") and len(drafts[0]["video_prompts"]) == 3
    assert "narration_lock" not in drafts[0]
