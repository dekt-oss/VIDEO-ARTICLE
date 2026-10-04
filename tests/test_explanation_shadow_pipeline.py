from __future__ import annotations

import json

from engine import config, explanation_shadow_pipeline


def _paper_fact_sheet() -> dict:
    return {
        "source": {"title": "압력과 구조"},
        "source_provenance": {
            "source_depth": "full_body",
            "char_count": 5000,
            "provider": "publisher",
        },
        "claims": [{
            "claim_id": "C01",
            "claim_ko": "압력이 높아지면 구조가 변한다.",
            "claim_kind": "mechanism",
            "causal_strength": "causal",
            "source_quote": "Higher pressure changes the structure.",
            "validation": {
                "evidence_state": "SUPPORTED",
                "quote_verified": True,
                "contract_version": config.EVIDENCE_CONTRACT_VERSION,
            },
        }],
    }


def _narration_caller(**kwargs) -> dict:
    payload = json.loads(kwargs["user"])
    return {"beats": [{
        "beat_id": beat["beat_id"],
        "sentences": list(beat["content_points"]),
    } for beat in payload["beats"]]}


def _critic_caller(**kwargs) -> dict:
    payload = json.loads(kwargs["user"])
    clauses = []
    for beat in payload["narration_beats"]:
        for position, sentence in enumerate(beat["sentences"], 1):
            hook = beat["stage"] == "HOOK"
            clauses.append({
                "narration_id": beat["narration_id"],
                "sentence_index": position,
                "clause_text": sentence,
                "clause_kind": "RHETORICAL" if hook else "FACTUAL",
                "verdict": "RHETORICAL" if hook else "ENTAILED",
                "evidence_ids": [] if hook else list(beat["evidence_ids"]),
                "finding_codes": [],
                "rationale": "질문" if hook else "인용 근거",
            })
    return {"clauses": clauses}


def _rejecting_critic_caller(**kwargs) -> dict:
    payload = json.loads(kwargs["user"])
    clauses = []
    for beat in payload["narration_beats"]:
        for position, sentence in enumerate(beat["sentences"], 1):
            hook = beat["stage"] == "HOOK"
            clauses.append({
                "narration_id": beat["narration_id"],
                "sentence_index": position,
                "clause_text": sentence,
                "clause_kind": "RHETORICAL" if hook else "FACTUAL",
                "verdict": "RHETORICAL" if hook else "UNSUPPORTED",
                "evidence_ids": [],
                "finding_codes": [] if hook else ["unsupported_background"],
                "rationale": "질문" if hook else "의도적 회귀 입력",
            })
    return {"clauses": clauses}


def _report_fact_sheet() -> dict:
    return {
        "source": {"broker": "테스트증권", "company": "테스트기업"},
        "source_depth": "partial_text",
        "source_chars": 1072,
        "number_facts": [{
            "fact_id": "num_price",
            "value": 1,
            "unit": "%",
            "unit_norm": "%",
            "period": "2026F",
            "metric": "가격",
            "basis": "broker_estimate",
            "attribution": "테스트증권",
            "display": "테스트증권은 2026년 가격이 1% 상승할 것으로 전망했다.",
            "interpretation": "projection",
            "validation": {
                "number_match": True,
                "unit_match": True,
                "period_match": True,
                "quote_supports_claim": True,
            },
            "source_refs": [{"quote": "2026년 가격은 1% 상승할 전망"}],
        }],
    }


def _financial_reasoning() -> dict:
    return {"units": [{
        "reasoning_id": "R01",
        "unit_type": "EARNINGS_BRIDGE",
        "title": "가격 전망이 실적으로 이어지는 경로",
        "carries_thesis": True,
        "attributed_to": "테스트증권",
        "assumption": "가격 상승 유지",
        "breaks_if": "가격 하락",
        "steps": [{
            "step": 1,
            "text": "테스트증권은 2026년 가격이 1% 상승할 것으로 전망했다.",
            "fact_ids": ["num_price"],
            "source_refs": [],
        }],
    }]}


def test_default_run_stops_before_external_model_calls():
    result = explanation_shadow_pipeline.run(
        domain="paper",
        content_id="paper-1",
        fact_sheet=_paper_fact_sheet(),
        legacy_draft={"script_md": "기존 대본"},
        legacy_directive={"id": "dir-1", "cuts": []},
    )

    assert result["run_status"] == "MODEL_CALL_REQUIRED"
    assert result["phase_status"]["phase5"] == "READY"
    assert result["phase_status"]["phase6"] == "NOT_RUN"
    assert result["shadow"]["directive"] is None


def test_opted_in_run_emits_a_fully_traced_shadow_directive():
    result = explanation_shadow_pipeline.run(
        domain="paper",
        content_id="paper-1",
        fact_sheet=_paper_fact_sheet(),
        legacy_draft={"script_md": "기존 대본"},
        legacy_directive={"id": "dir-1", "cuts": []},
        allow_model_calls=True,
        narration_caller=_narration_caller,
        critic_caller=_critic_caller,
    )

    assert result["run_status"] == "READY"
    assert result["phase_status"]["phase10"] == "READY"
    assert result["shadow"]["directive"]["qa"]["metrics"]["fully_traced_cut_count"] == 2
    assert result["shadow"]["directive"]["cuts"][1]["explanation_trace"]["evidence_ids"] == [
        "paper:C01"
    ]


def test_empty_source_is_blocked_without_emitting_a_directive():
    result = explanation_shadow_pipeline.run(
        domain="paper",
        content_id="paper-empty",
        fact_sheet={"source_provenance": {"source_depth": "none", "char_count": 0}},
        legacy_draft={"script_md": "근거 없는 기존 대본"},
        legacy_directive={"id": "dir-empty", "cuts": []},
        allow_model_calls=True,
        narration_caller=_narration_caller,
        critic_caller=_critic_caller,
    )

    assert result["run_status"] == "BLOCKED"
    assert result["phase_status"]["phase5"] == "BLOCKED_NO_REASONING"
    assert result["phase_status"]["phase10"] == "BLOCKED"
    assert result["shadow"]["directive"] is None


def test_report_run_preserves_broker_projection_and_attribution_to_the_directive():
    result = explanation_shadow_pipeline.run(
        domain="report",
        content_id="report-1",
        fact_sheet=_report_fact_sheet(),
        financial_reasoning=_financial_reasoning(),
        legacy_draft={"script_md": "기존 리포트 대본"},
        legacy_directive={"id": "report-dir-1", "cuts": []},
        allow_model_calls=True,
        narration_caller=_narration_caller,
        critic_caller=_critic_caller,
    )

    assert result["run_status"] == "READY"
    linked = next(
        cut for cut in result["shadow"]["directive"]["cuts"]
        if cut["explanation_trace"]["reasoning_ids"]
    )
    assert linked["causal_levels"] == ["broker_projection"]
    assert linked["attributions"] == ["테스트증권"]


def test_markdown_keeps_before_after_and_unverified_boundaries_visible():
    result = explanation_shadow_pipeline.run(
        domain="paper",
        content_id="paper-1",
        fact_sheet=_paper_fact_sheet(),
        legacy_draft={"script_md": "기존 운영 대본"},
        legacy_directive={
            "id": "dir-1",
            "cuts": [{"cut_no": 1, "narration_ko": "기존 운영 대본", "visual_prompt": "관련 이미지"}],
        },
    )

    markdown = explanation_shadow_pipeline.render_markdown(result)

    assert "기존 운영 대본" in markdown
    assert "외부 모델 호출 전 중단" in markdown
    assert "동일 Fact Sheet revision: 미검증" in markdown
    assert "렌더 영상 품질: 미검증" in markdown


def test_markdown_keeps_generated_shadow_script_visible_when_directive_is_blocked():
    result = explanation_shadow_pipeline.run(
        domain="paper",
        content_id="paper-blocked",
        fact_sheet=_paper_fact_sheet(),
        legacy_draft={"script_md": "기존 운영 대본"},
        legacy_directive={"id": "dir-1", "cuts": []},
        allow_model_calls=True,
        narration_caller=_narration_caller,
        critic_caller=_rejecting_critic_caller,
    )

    assert result["run_status"] == "BLOCKED"
    assert result["phase_status"]["phase7"] == "REJECTED"
    assert result["shadow"]["narration"]["narration_beats"]

    markdown = explanation_shadow_pipeline.render_markdown(result)

    assert "## 후 — V2 Shadow 대본" in markdown
    assert "압력이 높아지면 구조가 변한다." in markdown
    assert "새 지시서 미발행: 안전 게이트가 차단했습니다." in markdown
