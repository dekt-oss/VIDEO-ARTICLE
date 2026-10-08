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


# ─── 2026-10-07 실측 후속: 맞는 사실이 막히지 않게, 검증은 Jev 로 ───────────────────────────────────

def _paper_pack():
    from engine import evidence_pack
    fs = base._paper_fact_sheet()
    fs["numbers"] = ["세포의 1% 미만이 반응 (less than 1% of cells)"]
    return fs, evidence_pack.build(fs, "paper", content_id="paper-1")


def _beats(pack, hook="세포의 1% 미만이 반응한다고요?"):
    scenes = [{"scene": 1, "narration_ko": hook, "claim_ids": [], "source_facts": []},
              {"scene": 2, "narration_ko": "세포의 1% 미만이 반응합니다.", "claim_ids": [],
               "source_facts": ["numbers[0]"], "evidence_role": "primary_result"},
              {"scene": 3, "narration_ko": "그래서 압력이 열쇠입니다.", "claim_ids": ["C01"], "source_facts": []}]
    return v2_writer.scene_beats(scenes, pack)


def test_paper_fact_sheet_number_counts_as_evidence():
    """Fact Sheet 수치 칸에는 원문 인용 칸이 없다 — 그래도 검증이 맞다고 한 문장은 통과해야 한다(신피질 1% 사례)."""
    from engine import semantic_fidelity
    fs, pack = _paper_pack()
    out = semantic_fidelity.review_scenes_jev(_beats(pack), pack, fs, domain="paper", content_id="paper-1",
                                              core_question="", judge=lambda text, source: 0.1)
    assert out["qa_status"] == "PASSED", out["qa"]["errors"]


def test_factual_hook_may_cite_a_later_scene():
    """첫 질문이 본문 수치를 당겨 말해도(숫자가 있어 수사가 아니다) 그 수치를 근거로 댈 수 있다."""
    from engine import semantic_fidelity
    fs, pack = _paper_pack()
    out = semantic_fidelity.review_scenes_jev(_beats(pack, "세포 1% 미만이 반응합니다."), pack, fs,
                                              domain="paper", content_id="paper-1", core_question="",
                                              judge=lambda text, source: 0.1)
    assert out["qa_status"] == "PASSED", out["qa"]["errors"]
    assert "paper:number:01" in out["clauses"][0]["evidence_ids"]


def test_jev_rejects_a_sentence_beyond_the_source_and_feeds_it_back():
    from engine import semantic_fidelity
    fs, pack = _paper_pack()
    seen = []

    def judge(text, source):
        seen.append(source)
        return 0.9 if "열쇠" in text else 0.1

    out = semantic_fidelity.review_scenes_jev(_beats(pack), pack, fs, domain="paper", content_id="paper-1",
                                              core_question="", judge=judge)
    assert out["qa_status"] == "REJECTED"
    assert "FACT SHEET" in seen[0] and "less than 1% of cells" in seen[0]
    assert any("그래서 압력이 열쇠입니다." in line for line in semantic_fidelity.fix_feedback(out))


def test_jev_silence_is_a_checker_error_not_a_pass():
    from engine import semantic_fidelity
    fs, pack = _paper_pack()
    out = semantic_fidelity.review_scenes_jev(_beats(pack), pack, fs, domain="paper", content_id="paper-1",
                                              core_question="", judge=lambda text, source: None)
    assert out["qa_status"] == "CRITIC_ERROR"


def test_default_checker_is_jev_unless_a_fake_llm_critic_is_passed():
    assert config.V2_CRITIC_BACKEND == "jev"
    assert v2_writer.critic_backend() == "jev"
    assert v2_writer.critic_backend(lambda **kw: {}) == "llm"


# ─── 2026-10-08: 검사 기준을 미리 주고, V2 대본은 나레이션만 ─────────────────────────────────────

def test_writer_gets_the_check_criteria_up_front():
    from engine import semantic_fidelity
    text = v2_writer.design_instruction(_reasoning())
    assert "검사 기준" in text
    for line in semantic_fidelity.WRITER_CHECK_CRITERIA:
        assert line in text


def test_v2_writer_prompts_skip_scene_picture_prompts():
    from engine import report_scriptgen, scriptgen
    paper = scriptgen._narration_only(scriptgen.SCRIPT_SYSTEM)
    report = report_scriptgen._narration_only(report_scriptgen.SCRIPT_SYSTEM)
    for text in (paper, report):
        assert '"image_prompt"' not in text and '"video_prompt"' not in text
        assert '"narration_ko"' in text and '"source_facts"' in text
    assert "hook_candidates" in paper                       # 후킹 장치는 그대로
    assert len(paper) < len(scriptgen.SCRIPT_SYSTEM) * 0.85


def test_default_writer_asks_for_narration_only(monkeypatch):
    from engine import report_scriptgen, scriptgen
    seen = {}
    monkeypatch.setattr(scriptgen, "generate", lambda fs, ins, **kw: seen.setdefault("paper", kw) or {})
    monkeypatch.setattr(report_scriptgen, "generate", lambda fs, ins, **kw: seen.setdefault("report", kw) or {})
    v2_writer.default_writer("paper")({}, "")
    v2_writer.default_writer("report")({}, "")
    assert seen["paper"]["narration_only"] is True and seen["report"]["narration_only"] is True
