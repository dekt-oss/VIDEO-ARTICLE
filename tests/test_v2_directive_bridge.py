"""V2 narration → existing Production directive generator (design review A). Zero cost: stubbed generator."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from engine import explanation_shadow_pipeline, script_revision, v2_directive_bridge

import test_explanation_shadow_pipeline as fixtures
import test_explanation_v2_realistic_model as realistic
import test_spoken_numbers as number_fixtures


def _ready(domain: str = "report") -> dict:
    if domain == "paper":
        return explanation_shadow_pipeline.run(
            domain="paper", content_id="paper-1", fact_sheet=fixtures._paper_fact_sheet(),
            legacy_draft={"paper_id": "paper-1", "fact_sheet": fixtures._paper_fact_sheet()},
            legacy_directive={}, allow_model_calls=True,
            narration_caller=realistic.realistic_narrator(), critic_caller=fixtures._critic_caller)
    sheet, reasoning = number_fixtures._number_heavy_report()
    return explanation_shadow_pipeline.run(
        domain="report", content_id="report-numbers", fact_sheet=sheet,
        financial_reasoning=reasoning,
        legacy_draft={"report_id": "report-numbers", "fact_sheet": sheet},
        legacy_directive={}, allow_model_calls=True,
        narration_caller=realistic.realistic_narrator(), critic_caller=fixtures._critic_caller)


def _echo_generator(seen: list):
    """기존 생성기 대역: 대본 문장마다 컷 하나(실제 cut_skeleton 처럼) + 받은 초안을 기록."""
    def generate(draft: dict) -> dict:
        seen.append(deepcopy(draft))
        cuts = []
        for paragraph in draft["script_md"].split("\n\n"):
            for sentence in [s for s in paragraph.replace("? ", "?\n").replace(". ", ".\n").split("\n") if s]:
                cuts.append({"cut_no": len(cuts) + 1, "narration_ko": sentence,
                             "staging_ko": "장면", "visual_prompt": "scene"})
        return {"version_type": "photo",
                "header": {"approval_blocked": False, "block_reasons": [], "total_estimated_sec": 40},
                "cuts": cuts}
    return generate


# ─── 1단계: 초안 모양 ─────────────────────────────────────────

def test_report_draft_keeps_scenes_aligned_and_maps_reasoning_to_broker_ids():
    result = _ready("report")
    assert result["run_status"] == "READY"

    draft = v2_directive_bridge.report_draft(result["shadow"], {"report_id": "r"},
                                             number_fixtures._number_heavy_report()[1])

    # 장면이 대본 문단과 1:1 이어야 기존 생성기가 장면을 프롬프트에 싣는다.
    assert script_revision.scenes_match_script(draft["scenes"], draft["script_md"])
    rids = [scene["reasoning_id"] for scene in draft["scenes"] if scene["reasoning_id"]]
    assert rids and all(rid.startswith("R") and not rid.startswith("XR") for rid in rids)
    cards = [card for scene in draft["scenes"] for card in scene["screen_facts"]]
    assert cards == [number_fixtures.MEMORY]


def test_paper_draft_builds_its_own_plan_from_claims_actually_used():
    result = _ready("paper")
    assert result["run_status"] == "READY"

    draft = v2_directive_bridge.paper_draft(result["shadow"], {"paper_id": "p", "fact_sheet": {}})

    plan = draft["video_flow"]["content_plan"]
    assert plan["primary_claim_id"] == "C01"          # V2 대본이 실제로 쓴 근거
    assert plan["supporting_claim_ids"] == []
    assert plan["selected_mode"] in ("flash", "standard", "deep", "extended")
    assert plan["selected_mode"] != "series_split"
    assert [scene["claim_ids"] for scene in draft["video_prompts"]][1] == ["C01"]


def test_bridge_refuses_unaccepted_narration():
    result = _ready("report")
    shadow = deepcopy(result["shadow"])
    shadow["narration"]["generation_status"] = "REJECTED_DRAFT"

    with pytest.raises(ValueError, match="v2_narration_not_accepted"):
        v2_directive_bridge.report_draft(shadow, {}, {})


# ─── 2단계: 추적 정보 재부착 ─────────────────────────────────

def test_trace_is_reattached_to_every_generated_cut():
    seen: list = []
    result = _ready("report")

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {"report_id": "r"},
        financial_reasoning=number_fixtures._number_heavy_report()[1],
        generator=_echo_generator(seen))

    assert generated["trace"]["untraced_cuts"] == 0
    traced = [cut["v2_trace"] for cut in generated["directive"]["cuts"]]
    assert all(t["matched"] for t in traced)
    assert any("report:num_tp" in t["evidence_ids"] for t in traced)
    assert any(t["screen_facts"] == [number_fixtures.MEMORY] for t in traced)


def test_untraceable_cut_is_marked_not_dropped():
    result = _ready("report")

    def rewriting(draft):
        return {"header": {}, "cuts": [{"cut_no": 1, "narration_ko": "대본에 없는 새 문장"}]}

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {}, financial_reasoning={}, generator=rewriting)

    assert generated["directive"]["cuts"][0]["v2_trace"] == {"matched": False}
    assert generated["trace"]["untraced_cuts"] == 1


# ─── 3단계: 비교 도구 연결 ───────────────────────────────────

def _pipeline(**overrides) -> dict:
    sheet, reasoning = number_fixtures._number_heavy_report()
    kwargs = dict(
        domain="report", content_id="report-numbers", fact_sheet=sheet,
        financial_reasoning=reasoning, legacy_draft={"report_id": "report-numbers"},
        legacy_directive={}, allow_model_calls=True,
        narration_caller=realistic.realistic_narrator(), critic_caller=fixtures._critic_caller,
        with_directive=True, directive_generator=_echo_generator([]),
    )
    kwargs.update(overrides)
    return explanation_shadow_pipeline.run(**kwargs)


def test_pipeline_generates_directive_only_when_asked_and_ready():
    assert _pipeline()["phase_status"]["production_generator"] == "READY"
    assert "production_generator" not in _pipeline(with_directive=False)["phase_status"]

    calls = []
    blocked = _pipeline(
        narration_caller=realistic.realistic_narrator(realistic._read_screen_numbers),
        directive_generator=lambda draft: calls.append(draft) or {"header": {}, "cuts": []})
    assert blocked["phase_status"]["production_generator"] == "NOT_RUN"
    assert calls == []                                   # 막힌 대본은 생성기에 가지 않는다


def test_generator_failure_is_recorded_without_hiding_the_script_verdict():
    def boom(draft):
        raise TimeoutError("directive model timeout")

    result = _pipeline(directive_generator=boom)

    assert result["run_status"] == "READY"
    assert result["phase_status"]["production_generator"] == "ERROR"
    assert result["shadow"]["generated_error"]["type"] == "TimeoutError"
    markdown = explanation_shadow_pipeline.render_markdown(result)
    assert "생성 실패: TimeoutError" in markdown


def test_markdown_shows_generated_directive_next_to_production():
    result = _pipeline()
    markdown = explanation_shadow_pipeline.render_markdown(result)

    assert "## V2 지시서 (기존 생성기로 만든 것)" in markdown
    assert "같은 생성기" in markdown
    assert "승인 가능 여부: 통과" in markdown
    assert "출처) V2 NB" in markdown
    assert "## V2 추적 골격 (간이 화면 계획 — 렌더용 아님)" in markdown


def test_cli_rejects_with_directive_without_with_model(tmp_path):
    from scripts import compare_explanation_v2

    with pytest.raises(SystemExit):
        compare_explanation_v2.main(["report", "11111111-2222-3333-4444-555555555555",
                                     "--with-directive", "--output-dir", str(tmp_path)])
