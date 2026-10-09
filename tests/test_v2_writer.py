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
    assert len(seen) == 2 and "검사에 걸린 것" in seen[1]
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
    # 2026-10-08: 검사를 통과한 V2 대사는 지시서에서 글자 그대로 고정된다(지시서가 다듬지 못하게).
    assert drafts[0]["narration_lock"]["source"] == "v2_writer"
    assert drafts[0]["script_md"] == "\n\n".join(
        ["소리로 세포가 더 빨리 아물까요?", "압력이 높아지면 구조가 바뀝니다.", "그래서 압력이 열쇠입니다."])


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


# ─── 2026-10-08: 쉬운 말 검사(Jev) — 되먹임만, 더 나쁜 다시 쓰기는 버린다 ─────────────────────────

def _plain_beats(hook="피질 장거리 억제 뉴런이 잠을 켤까요?", body=("Sst-Chodl 세포가 델타파를 키웁니다.",)):
    return [{"sentences": [hook]}, {"sentences": list(body)}]


def test_plain_check_flags_jargon_hook_spoiler_and_unexplained_terms():
    out = v2_writer.plain_check(_plain_beats(),
                                hook_judge=lambda line: {"jargon": 0.98, "spoiler": 0.83},
                                term_judge=lambda sentence, earlier: 0.9)
    assert out["findings"] == ["hook_jargon", "hook_spoiler", "term_unexplained"]
    assert any("일상어만으로" in f for f in out["feedback"]) and any("궁금증" in f for f in out["feedback"])
    easy = v2_writer.plain_check(_plain_beats("소리만 들려줘도 상처가 아물까요?", ("움직일 땐 꺼져요.",)),
                                 hook_judge=lambda line: {"jargon": 0.06, "spoiler": 0.12},
                                 term_judge=lambda sentence, earlier: 0.08)
    assert easy["findings"] == []


def test_plain_check_counts_silence_as_unchecked_not_passed():
    out = v2_writer.plain_check(_plain_beats(), hook_judge=lambda line: None, term_judge=lambda s, e: None)
    assert out["findings"] == [] and out["unchecked"] == 2


def _loop(monkeypatch, judges, scripts):
    from engine import evidence_pack, semantic_fidelity
    monkeypatch.setattr(config, "V2_NARRATION_RETRY", True)
    pack = evidence_pack.build(base._paper_fact_sheet(), "paper", content_id="paper-1")
    calls = iter(scripts)
    seen = []

    def writer(fs, instruction):
        seen.append(instruction)
        return next(calls)

    monkeypatch.setattr(semantic_fidelity, "review_scenes_jev",
                        lambda beats, *a, **k: {"qa_status": "PASSED", "clauses": [], "qa": {"errors": []}})
    out = v2_writer.write_and_check(writer, {}, _reasoning(), pack, domain="paper", content_id="paper-1",
                                    plain_judges=judges)
    return out, seen


def test_plain_findings_trigger_one_rewrite_with_the_feedback(monkeypatch):
    hard, easy = _script(("피질 장거리 억제 뉴런이 잠을 켤까요?", "b", "c")), _script(("깊은 잠의 스위치는 어디 있을까요?", "b", "c"))
    out, seen = _loop(monkeypatch, (lambda line: {"jargon": 0.98 if "피질" in line else 0.1, "spoiler": 0.1},
                                    lambda s, e: 0.1), [hard, easy])
    assert len(seen) == 2 and "일상어만으로" in seen[1]
    assert out["chosen_attempt"] == 2 and out["plain"]["findings"] == []


def test_a_worse_rewrite_is_not_chosen(monkeypatch):
    hard = _script(("피질 장거리 억제 뉴런이 잠을 켤까요?", "b", "c"))
    out, _ = _loop(monkeypatch, (lambda line: {"jargon": 0.98, "spoiler": 0.9}, lambda s, e: 0.1), [hard, hard])
    assert out["attempts"] == 2 and out["chosen_attempt"] == 2          # 같으면 나중 것

    from engine import semantic_fidelity
    calls = iter([{"qa_status": "PASSED"}, {"qa_status": "REJECTED"}])
    monkeypatch.setattr(semantic_fidelity, "review_scenes_jev",
                        lambda beats, *a, **k: {**next(calls), "clauses": [], "qa": {"errors": []}})
    from engine import evidence_pack
    pack = evidence_pack.build(base._paper_fact_sheet(), "paper", content_id="paper-1")
    out = v2_writer.write_and_check(lambda fs, ins: hard, {}, _reasoning(), pack, domain="paper",
                                    content_id="paper-1",
                                    plain_judges=(lambda line: {"jargon": 0.98, "spoiler": 0.1}, lambda s, e: 0.1))
    assert out["chosen_attempt"] == 1 and out["status"] == "PASSED"   # 사실 검사를 새로 놓친 다시 쓰기는 버린다


def test_compare_cli_reuses_a_saved_design(tmp_path):
    from scripts import compare_explanation_v2 as cli
    saved = {"domain": "paper", "content_id": "c1", "shadow": {"reasoning": {"reasoning": {"core_question": "q"}}}}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert cli._saved_reasoning(str(path), "paper", "c1")(model="x") == {"core_question": "q"}
    with pytest.raises(SystemExit):
        cli._saved_reasoning(str(path), "paper", "other")


def test_v2_starts_from_the_production_opening_line():
    draft = {"video_prompts": [{"narration_ko": "뇌세포의 단 1%만 건드렸는데, 깊은 잠에 빠질 수 있을까요?"}], "script_md": "x"}
    hook = v2_writer.legacy_hook(draft)
    assert hook.startswith("뇌세포의 단 1%")
    assert v2_writer.legacy_hook({"script_md": "씬 1\n주가는 반토막인데 이익은 두 배?\n"}) == "주가는 반토막인데 이익은 두 배?"
    text = v2_writer.design_instruction(_reasoning(), legacy_hook=hook)
    assert "그대로" in text and hook in text and "그 낱말만" in text
    assert "그대로" not in v2_writer.design_instruction(_reasoning()).split("검사 기준")[0]


def test_jev_cleared_line_without_numbers_or_evidence_counts_as_background():
    from engine import semantic_fidelity
    fs, pack = _paper_pack()
    scenes = [{"scene": 1, "narration_ko": "소리가 세포를 아물게 할까요?", "claim_ids": [], "source_facts": []},
              {"scene": 2, "narration_ko": "흔히 소리는 기분만 바꾼다고 생각하죠. 3배 빨라졌어요.",
               "claim_ids": [], "source_facts": ["source.authors"]},
              {"scene": 3, "narration_ko": "그래서 압력이 열쇠입니다.", "claim_ids": ["C01"], "source_facts": []}]
    out = semantic_fidelity.review_scenes_jev(v2_writer.scene_beats(scenes, pack), pack, fs, domain="paper",
                                              content_id="paper-1", core_question="", judge=lambda t, s: 0.1)
    kinds = {c["clause_text"]: c["clause_kind"] for c in out["clauses"]}
    assert kinds["흔히 소리는 기분만 바꾼다고 생각하죠."] == "BACKGROUND"
    assert kinds["3배 빨라졌어요."] == "FACTUAL"                      # 숫자는 여전히 근거가 필요하다
    assert out["qa_status"] == "REJECTED" and any("factual_evidence_missing" in e for e in out["qa"]["errors"])


def test_a_failed_rewrite_keeps_the_first_attempt(monkeypatch):
    from engine import evidence_pack, semantic_fidelity
    monkeypatch.setattr(config, "V2_NARRATION_RETRY", True)
    pack = evidence_pack.build(base._paper_fact_sheet(), "paper", content_id="paper-1")
    calls = []

    def writer(fs, instruction):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("출력이 max_tokens 에서 잘렸다")
        return _script(("피질 뉴런이 잠을 켤까요?", "b", "c"))

    monkeypatch.setattr(semantic_fidelity, "review_scenes_jev",
                        lambda beats, *a, **k: {"qa_status": "PASSED", "clauses": [], "qa": {"errors": []}})
    out = v2_writer.write_and_check(writer, {}, _reasoning(), pack, domain="paper", content_id="paper-1",
                                    plain_judges=(lambda line: {"jargon": 0.9, "spoiler": 0.1}, lambda s, e: 0.1))
    assert out["status"] == "PASSED" and out["attempts"] == 1 and "max_tokens" in out["retry_error"]


def test_crowded_scene_is_fed_back_and_the_rule_is_given_up_front():
    beats = [{"beat_id": "SC01", "sentences": ["인터넷이 하늘로 간다고요?"]},
             {"beat_id": "SC03", "sentences": ["케플러가 중계위성 10기와 단말 40기로, KSAT 도 시연했어요."]},
             {"beat_id": "SC05", "sentences": ["한 번은 변화가 없었는데, 두 번, 세 번 반복하자 줄었어요."]}]
    scores = {"SC03": 0.98, "SC05": 0.82, "SC01": 0.07}
    out = v2_writer.plain_check(beats, hook_judge=lambda line: {"jargon": 0.1, "spoiler": 0.1},
                                term_judge=lambda s, e: 0.1,
                                crowded_judge=lambda scene: next(v for k, v in scores.items()
                                                                 if any(scene.startswith(b["sentences"][0][:5])
                                                                        for b in beats if b["beat_id"] == k)))
    assert out["findings"] == ["scene_crowded"]                    # 0.82(운영자가 좋다고 한 장면)는 건드리지 않는다
    assert "SC03" in out["feedback"][0] and "이름 하나·숫자 하나" in out["feedback"][0]
    assert "이름(회사·기관·사람) 하나, 숫자 하나까지만" in v2_writer.design_instruction(_reasoning())


def test_v2_directive_locks_narration_and_passes_mechanism_hints():
    from engine import cut_skeleton, v2_directive_bridge
    seen = []
    script = {"script_md": "**Scene 1 (problem / HOOK)**\n소리가 세포를 아물게 할까요?", "video_flow": {},
              "scenes": [{"scene": 1, "narration_ko": "소리가 세포를 아물게 할까요?", "evidence_role": "connective"},
                         {"scene": 2, "narration_ko": "음파가 콜라겐을 흔들어 세포가 신호로 바꿔요.",
                          "evidence_role": "mechanism"}]}
    out = v2_directive_bridge.generate_from_script(
        "paper", script, {"fact_sheet": {}},
        generator=lambda draft: seen.append(draft) or {"header": {"narration_lock": {"status": "LOCKED"}}, "cuts": []})
    draft = seen[0]
    assert "Scene 1" not in draft["script_md"]                  # 머리표가 대사로 고정되면 안 된다
    assert cut_skeleton.lock_hints(draft) == [{"text": "음파가 콜라겐을 흔들어 세포가 신호로 바꿔요.", "hint": "MECHANISM"}]
    assert out["narration_lock"] == {"status": "LOCKED"}


def test_video_fallbacks_are_flagged_and_downgrade_done():
    from engine import render
    render.VIDEO_FALLBACKS[:] = [3, 3, 7]
    qa: dict = {}
    status, reasons = render.flag_video_fallbacks("done", [], qa)
    assert status == "degraded" and reasons == ["video_to_still_cuts:3,7"] and qa["video_to_still_cuts"] == [3, 7]
    assert render.flag_video_fallbacks("done", [], {}) == ("done", [])     # 비워졌다 — 다음 작업에 새지 않는다


def test_render_length_limit_is_the_shorts_cap_and_bgm_tone_is_off():
    assert config.RENDER_QA_MAX_SEC == 180 and config.RENDER_QA_MAX_SEC > config.V2_TARGET_MAX_SEC
    assert config.BGM_ENABLED is False
