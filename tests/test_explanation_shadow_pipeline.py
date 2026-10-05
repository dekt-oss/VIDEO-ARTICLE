from __future__ import annotations

import json

import pytest

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

    assert "## V2 Shadow 대본 (phase6: DRAFT_ACCEPTED)" in markdown
    assert "압력이 높아지면 구조가 변한다." in markdown
    assert "새 지시서 미발행: 안전 게이트가 차단했습니다." in markdown


# ─── Phase 11 리뷰 후속(P2-1~P2-5, P3) ───────────────────────────────

def _association_fact_sheet() -> dict:
    sheet = _paper_fact_sheet()
    sheet["claims"][0].update(
        claim_kind="association",
        causal_strength="association",
        claim_ko="성격 특성과 특정 유전 변이가 연관되어 있다.",
        source_quote="Personality traits were associated with variants.",
    )
    return sheet


def _strengthening_caller(**kwargs) -> dict:
    payload = json.loads(kwargs["user"])
    return {"beats": [{
        "beat_id": beat["beat_id"],
        "sentences": [s.replace("연관되어 있다", "성격을 결정한다") for s in beat["content_points"]],
    } for beat in payload["beats"]]}


def _raise_timeout(**kwargs):
    raise TimeoutError("provider timeout")


def _run(**overrides):
    kwargs = dict(
        domain="paper", content_id="paper-1", fact_sheet=_paper_fact_sheet(),
        legacy_draft={"script_md": "기존 운영 대본"}, legacy_directive={"id": "dir-1", "cuts": []},
        allow_model_calls=True, narration_caller=_narration_caller, critic_caller=_critic_caller,
    )
    kwargs.update(overrides)
    return explanation_shadow_pipeline.run(**kwargs)


def test_markdown_shows_root_cause_and_marks_rejected_narration():
    result = _run(fact_sheet=_association_fact_sheet(), narration_caller=_strengthening_caller)

    assert result["phase_status"]["phase6"] == "REJECTED_DRAFT"
    assert result["shadow"]["directive"] is None
    markdown = explanation_shadow_pipeline.render_markdown(result)

    assert "## V2 Shadow 대본 (phase6: REJECTED_DRAFT)" in markdown
    assert "엔진이 **거절한** 대본" in markdown
    assert "association_upgraded:NB02" in markdown
    assert "semantic_fidelity_not_passed:REJECTED_UPSTREAM" in markdown


def test_markdown_shows_critic_failure_cause():
    result = _run(critic_caller=_raise_timeout)

    assert result["run_status"] == "BLOCKED"
    assert "critic_call_failed:TimeoutError" in explanation_shadow_pipeline.render_markdown(result)


def test_narration_caller_exception_is_recorded_not_raised():
    result = _run(narration_caller=_raise_timeout)

    assert result["run_status"] == "ERROR"
    assert result["error"]["phase"] == "phase6"
    assert result["error"]["type"] == "TimeoutError"
    assert result["phase_status"]["phase6"] == "ERROR"
    assert result["phase_status"]["phase10"] == "NOT_RUN"
    assert result["shadow"]["directive"] is None
    assert result["shadow"]["narrative_plan"]["planning_status"] == "READY"
    markdown = explanation_shadow_pipeline.render_markdown(result)
    assert "실행 오류(phase6): TimeoutError" in markdown
    assert "새 지시서 미발행: 실행 오류로 중단했습니다." in markdown


@pytest.mark.parametrize("sheet", [{}, None])
@pytest.mark.parametrize("allow", [False, True])
def test_empty_or_missing_source_never_raises_and_never_emits_directive(sheet, allow):
    result = _run(fact_sheet=sheet, allow_model_calls=allow)

    assert result["run_status"] == "BLOCKED"
    assert result["error"] is None
    assert result["shadow"]["directive"] is None
    assert result["phase_status"]["phase10"] != "READY"
    explanation_shadow_pipeline.render_markdown(result)


def test_stored_production_content_plan_feeds_the_complexity_gate():
    result = _run(
        domain="report", content_id="report-1", fact_sheet=_report_fact_sheet(),
        financial_reasoning=_financial_reasoning(),
        production_content_plan={"selected_mode": "extended", "target_duration_max_sec": 90},
    )

    assert result["run"]["content_plan_source"] == "production_draft"
    assert result["phase_status"]["phase8"] == "ACTION_REQUIRED"
    actions = [row["action"] for row in result["shadow"]["gate"]["required_actions"]]
    assert "DOWNGRADE_LENGTH" in actions
    assert result["shadow"]["directive"] is None
    assert "DOWNGRADE_LENGTH" in explanation_shadow_pipeline.render_markdown(result)


def test_policy_ceiling_plan_is_disclosed_as_not_evaluated():
    result = _run(production_content_plan={"selected_mode": "bogus"})

    assert result["run"]["content_plan_source"] == "source_policy_ceiling"
    assert "complexity_source_limit_not_evaluated" in result["non_claims"]


def test_prerequisite_requests_are_explicit_or_disclosed_as_not_evaluated():
    none = _run()
    assert none["run"]["prerequisite_requests"] == {"source": "none_supplied", "count": 0}
    assert "prerequisite_explanation_not_evaluated" in none["non_claims"]

    explicit = _run(requested_concepts=[{
        "concept_id": "gwas_association", "reason": "연관을 결정으로 읽지 않게",
        "evidence_ids": ["paper:C01"], "required": False,
    }])
    assert explicit["run"]["prerequisite_requests"] == {"source": "explicit", "count": 1}
    assert "prerequisite_explanation_not_evaluated" not in explicit["non_claims"]
    concepts = explicit["shadow"]["resolution"]["concepts"]
    assert [row["concept_id"] for row in concepts] == ["gwas_association"]


def test_run_records_snapshot_hash_and_model_metadata():
    first = _run(allow_model_calls=False)
    second = _run(allow_model_calls=False)

    digest = first["run"]["fact_sheet_snapshot_sha256"]
    assert len(digest) == 64 and digest == second["run"]["fact_sheet_snapshot_sha256"]
    assert first["same_fact_sheet_revision"] == "UNVERIFIED"
    assert first["run"]["model_calls_allowed"] is False
    assert first["run"]["narration_model"] == ""
    assert _run()["run"]["narration_model"] == config.MODEL_SCRIPT


def test_markdown_shows_shadow_trace_and_legacy_directive_identity():
    result = _run(
        domain="report", content_id="report-1", fact_sheet=_report_fact_sheet(),
        financial_reasoning=_financial_reasoning(),
        legacy_directive={
            "id": "dir-9", "version_type": "photo", "status": "approved",
            "created_at": "2026-10-01T00:00:00Z",
            "cuts": [{"cut_no": 1, "narration_ko": "기존 컷", "staging_ko": "손이 병을 든다",
                      "visual_prompt": "hand holding a bottle", "source_facts": ["num_price"]}],
        },
    )
    markdown = explanation_shadow_pipeline.render_markdown(result)

    assert "지시서 ID: dir-9 · 버전 photo · 상태 approved" in markdown
    assert "연출: 손이 병을 든다" in markdown
    assert "시각 프롬프트: hand holding a bottle" in markdown
    assert "근거 참조: num_price" in markdown
    assert "evidence: report:num_price" in markdown
    assert "raw ref: number_facts:num_price" in markdown
    assert "reasoning: XR01" in markdown
    assert "관계 supports" in markdown
    assert "상태 변화: TRANSFORM(reasoning:XR01→reasoning:XR01)" in markdown
    assert "귀속·인과 수준: 테스트증권 / broker_projection" in markdown
    assert "같은 입력으로 통제한 A/B 가 아니다" in markdown


def test_markdown_section_order_is_stable():
    markdown = explanation_shadow_pipeline.render_markdown(_run())
    order = ["## 콘텐츠 정보", "## 기존 Production 대본", "## 기존 Production 지시서",
             "## V2 Shadow 대본", "## V2 추적 골격", "## V2 지시서 (기존 생성기로 만든 것)",
             "## 차단·경고", "## 단계 판정"]
    positions = [markdown.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_legacy_fact_sheet_without_provenance_runs_to_a_verdict():
    """retinotopic 실데이터 형태: claims 는 있는데 source_provenance 가 없다."""
    sheet = _paper_fact_sheet()
    del sheet["source_provenance"]

    result = _run(fact_sheet=sheet)

    assert result["error"] is None
    assert result["run_status"] in {"READY", "BLOCKED"}
    assert result["shadow"]["evidence_pack"]["source"]["source_mode"] == ""
    assert result["shadow"]["gate"]["constraints"]["source_mode"] == "BRIEF_EXPLAINER"


def test_preflight_refuses_inconsistent_source_before_any_model_call(monkeypatch):
    from engine import evidence_pack

    original = evidence_pack.build

    def forged(*args, **kwargs):
        pack = original(*args, **kwargs)
        pack["source"]["source_mode"] = "FULL_EXPLAINER"
        pack["source"]["source_depth"] = "abstract_only"
        return pack

    monkeypatch.setattr(evidence_pack, "build", forged)
    calls = []

    def counting(**kwargs):
        calls.append(kwargs)
        return _narration_caller(**kwargs)

    result = _run(narration_caller=counting, critic_caller=counting)

    assert calls == []
    assert result["run_status"] == "ERROR"
    assert result["error"]["phase"] == "phase6_preflight"
    assert "preflight_failed_before_model_call" in result["error"]["message"]
    assert result["phase_status"]["phase6"] == "ERROR"
    assert result["shadow"]["directive"] is None


SERIES_SPLIT_PLAN = {"selected_mode": "series_split", "target_duration_max_sec": 50}


def test_series_split_without_override_blocks_the_directive():
    result = _run(production_content_plan=SERIES_SPLIT_PLAN)

    assert result["phase_status"]["phase8"] == "ACTION_REQUIRED"
    assert "SPLIT_SERIES" in [a["action"] for a in result["shadow"]["gate"]["required_actions"]]
    assert result["shadow"]["directive"] is None
    assert result["run"]["series_split_override_reason"] == ""


def test_blank_override_reason_is_not_an_override():
    result = _run(production_content_plan=SERIES_SPLIT_PLAN, series_split_override_reason="   ")

    assert result["phase_status"]["phase8"] == "ACTION_REQUIRED"
    assert result["shadow"]["directive"] is None


def test_explicit_series_split_override_is_applied_and_recorded():
    reason = "비교용: 첫 편만 V2 로 만들어 본다"
    result = _run(production_content_plan=SERIES_SPLIT_PLAN, series_split_override_reason=reason)

    assert result["phase_status"]["phase8"] == "READY"
    assert result["shadow"]["gate"]["applied_overrides"] == [
        {"signal": "series_split", "reason": reason}
    ]
    assert result["run_status"] == "READY"
    markdown = explanation_shadow_pipeline.render_markdown(result)
    assert f"series_split override: {reason}" in markdown
    assert f"phase8 적용된 override: series_split — {reason}" in markdown


def test_override_cannot_lift_a_length_overrun():
    plan = {"selected_mode": "series_split", "target_duration_max_sec": 90}
    result = _run(production_content_plan=plan, series_split_override_reason="비교용")

    actions = [a["action"] for a in result["shadow"]["gate"]["required_actions"]]
    assert actions == ["DOWNGRADE_LENGTH"]
    assert result["shadow"]["directive"] is None


def test_markdown_discloses_hook_restoration():
    def rewriting_caller(**kwargs):
        payload = json.loads(kwargs["user"])
        return {"beats": [{
            "beat_id": beat["beat_id"],
            "sentences": ["발뒤꿈치 보행은 위험하다?"] if beat["stage"] == "HOOK"
            else list(beat["content_points"]),
        } for beat in payload["beats"]]}

    result = _run(narration_caller=rewriting_caller)

    assert result["shadow"]["narration"]["repairs"][0]["repair"] == "hook_restored_to_core_question"
    markdown = explanation_shadow_pipeline.render_markdown(result)
    assert "phase6 코드 교정(NB01): hook_restored_to_core_question" in markdown
    assert "모델 원문: 발뒤꿈치 보행은 위험하다?" in markdown
