"""Financial Reasoning Model 순수 로직 (작업명세서_설명엔진_v2 §7 Phase 5 DoD).

네트워크 없이 돈다. 여기가 지키는 것은 **코드가 판정하는 자리**다:
원장에 없는 fact_id 는 버리는가 · id 를 코드가 매기는가 · 인용을 원문과 대조하는가 ·
"검증 못 함"과 "검증했더니 틀림"을 섞지 않는가.
"""

from __future__ import annotations

from engine import config, report_reasoning as rr, report_scriptgen


FACT_SHEET = {"number_facts": [{"fact_id": "num_op", "value": 860, "unit": "억"},
                               {"fact_id": "num_tp", "value": 90000, "unit": "원"}]}

SOURCE = "전력망 투자가 늘며 변압기 수주잔고가 사상 최대를 기록했다. 목표주가를 9만원으로 올린다."
PACKET = {"text": SOURCE, "source_depth": "full_text",
          "chunks": [{"chunk_id": "C001", "char_start": 0, "char_end": len(SOURCE),
                      "text": SOURCE}]}


def _raw(**over):
    unit = {
        "unit_type": "DRIVER_CHAIN", "title": "수주가 실적으로",
        "carries_thesis": True, "attributed_to": "하나증권",
        "steps": [
            {"step": 1, "text": "전력망 투자가 늘면 수주잔고가 찬다",
             "fact_ids": ["num_op"],
             "source_refs": [{"chunk_id": "", "quote": "변압기 수주잔고가 사상 최대를 기록했다"}]},
            {"step": 2, "text": "잔고가 매출로 인식되며 이익률이 오른다", "fact_ids": ["num_tp"]},
        ],
    }
    unit.update(over)
    return {"reasoning_units": [unit]}


# ─ 정규화: 코드가 판정한다 ─
def test_ids_are_assigned_by_code_and_dangling_facts_dropped():
    raw = _raw()
    raw["reasoning_units"][0]["reasoning_id"] = "모델이_지어낸_id"
    raw["reasoning_units"][0]["steps"][0]["fact_ids"] = ["num_op", "num_ghost"]
    units = rr.normalize_units(raw, FACT_SHEET, PACKET)
    assert units[0]["reasoning_id"] == "R01"           # 모델 값 폐기
    assert units[0]["steps"][0]["fact_ids"] == ["num_op"]   # 원장에 없는 참조는 버린다


def test_unknown_unit_type_falls_back_to_default():
    units = rr.normalize_units(_raw(unit_type="아무거나"), FACT_SHEET, PACKET)
    assert units[0]["unit_type"] == config.DEFAULT_REASONING_UNIT_TYPE


def test_unit_without_steps_is_dropped():
    """단계 없는 단위는 제목뿐이다 — 논증이 아니라 목차다."""
    assert rr.normalize_units({"reasoning_units": [{"title": "제목만", "steps": []}]},
                              FACT_SHEET, PACKET) == []


def test_units_and_steps_are_capped():
    many = {"reasoning_units": [
        {"unit_type": "DRIVER_CHAIN", "title": f"u{i}",
         "steps": [{"step": j, "text": f"s{j}", "fact_ids": ["num_op"]}
                   for j in range(config.REASONING_MAX_STEPS + 3)]}
        for i in range(config.REASONING_MAX_UNITS + 3)]}
    units = rr.normalize_units(many, FACT_SHEET, PACKET)
    assert len(units) == config.REASONING_MAX_UNITS
    assert all(len(u["steps"]) == config.REASONING_MAX_STEPS for u in units)


def test_thesis_is_forced_when_model_marks_none():
    """하류가 '무엇을 반드시 화면에 옮겨야 하는지'를 잃지 않게 코드가 보정한다."""
    units = rr.normalize_units(_raw(carries_thesis=False), FACT_SHEET, PACKET)
    assert units[0]["carries_thesis"] is True


def test_chunk_id_is_relocated_from_quote_position():
    """모델이 붙인 chunk 라벨을 믿지 않는다(report_evidence 와 같은 자세)."""
    raw = _raw()
    raw["reasoning_units"][0]["steps"][0]["source_refs"][0]["chunk_id"] = "C999"
    units = rr.normalize_units(raw, FACT_SHEET, PACKET)
    assert units[0]["steps"][0]["source_refs"][0]["chunk_id"] == "C001"


# ─ 인용 대조 ─
def test_audit_verifies_quotes_against_source():
    units = rr.normalize_units(_raw(), FACT_SHEET, PACKET)
    a = rr.audit(units, PACKET)
    assert a["quotes"] == 1 and a["quotes_verified"] == 1
    assert a["quote_verify_rate"] == 1.0
    assert a["step_ground_rate"] == 1.0


def test_audit_marks_invented_quote_as_unverified():
    raw = _raw()
    raw["reasoning_units"][0]["steps"][0]["source_refs"] = [
        {"chunk_id": "", "quote": "원문에 없는 그럴듯한 문장이다"}]
    units = rr.normalize_units(raw, FACT_SHEET, PACKET)
    rr.audit(units, PACKET)
    assert units[0]["steps"][0]["source_refs"][0]["verified"] is False
    assert any(r.startswith("reasoning_quote_not_in_source")
               for r in rr.block_reasons(units))


def test_unverifiable_is_not_the_same_as_wrong():
    """원문이 없으면 통과율은 0.0 이 아니라 None 이다 — 섞으면 게이트가 거짓말을 한다."""
    units = rr.normalize_units(_raw(), FACT_SHEET, None)
    a = rr.audit(units, None)
    assert a["quote_verify_rate"] is None


# ─ 게이트 ─
def test_step_without_any_evidence_is_flagged():
    raw = {"reasoning_units": [{"unit_type": "RISK_PATH", "title": "t", "carries_thesis": True,
                                "steps": [{"step": 1, "text": "근거 없는 인과"}]}]}
    units = rr.normalize_units(raw, FACT_SHEET, PACKET)
    assert any(r.startswith("reasoning_step_without_evidence") for r in rr.block_reasons(units))


def test_no_units_is_not_a_gate_violation():
    """요약 기반 재고가 통째로 막히면 안 된다 — 단위 없음은 이 게이트의 대상이 아니다."""
    assert rr.block_reasons([]) == []


# ─ 프롬프트 구간 ─
def test_units_block_is_empty_without_units():
    assert rr.units_block({"units": []}) == ""
    assert rr.units_block(None) == ""


def test_units_block_has_markers_and_hides_quotes():
    """프롬프트에는 인용 원문을 싣지 않는다 — 전문은 이미 따로 들어가고, 두 번 실으면 낭비다."""
    units = rr.normalize_units(_raw(), FACT_SHEET, PACKET)
    block = rr.units_block({"units": units})
    assert block.startswith(config.REASONING_MARKER)
    assert block.endswith(config.REASONING_END_MARKER)
    assert "사상 최대를 기록했다" not in block


def test_reasoning_marker_differs_from_fulltext_markers():
    """마커가 겹치면 tests/test_prompt_sync.py 의 앵커가 서로를 오탐한다."""
    assert config.REASONING_MARKER not in (config.SOURCE_FULLTEXT_MARKER,
                                           config.PAPER_SOURCE_MARKER,
                                           config.DRAFT_EVIDENCE_MARKER)


# ─ 대본이 논증을 소비하는가 ─
def test_script_scene_keeps_only_existing_reasoning_id():
    units = rr.normalize_units(_raw(), FACT_SHEET, PACKET)
    reasoning = {"units": units}
    obj = {"scenes": [
        {"scene": 1, "narration_ko": "가", "reasoning_id": "R01"},
        {"scene": 2, "narration_ko": "나", "reasoning_id": "R99"},   # 없는 단위
    ]}
    out = report_scriptgen.normalize_script(obj, reasoning)
    assert out["scenes"][0]["reasoning_id"] == "R01"
    assert out["scenes"][1]["reasoning_id"] == ""
    assert out["reasoning_coverage"]["used"] == ["R01"]
    assert out["reasoning_coverage"]["uncovered"] == []


def test_script_prompt_includes_units_only_when_present():
    units = rr.normalize_units(_raw(), FACT_SHEET, PACKET)
    with_units = report_scriptgen.script_user_prompt(FACT_SHEET, "", None, {"units": units})
    without = report_scriptgen.script_user_prompt(FACT_SHEET, "", None, None)
    assert config.REASONING_MARKER in with_units
    assert config.REASONING_MARKER not in without   # 빈 마커를 남기지 않는다


def test_empty_block_has_stable_shape():
    """호출부가 None 분기를 만들지 않게 모양이 항상 같아야 한다."""
    e = rr.empty()
    assert e["units"] == [] and e["block_reasons"] == []
    assert e["schema_version"] == config.REASONING_SCHEMA_VERSION


# ─ 지시서: 컷이 reasoning_id 를 갖는다 (Phase 5 DoD) ─
def test_directive_cut_keeps_reasoning_id_through_normalization():
    """공용 정규화(directive.normalize_directive)는 화이트리스트로 컷을 재구성한다 —
    필드를 거기 넣지 않으면 리포트 라인의 reasoning_id 가 조용히 사라진다."""
    from engine import directive as dv

    raw = {"header": {}, "cuts": [
        {"cut_no": 1, "scene_kind": "establish", "narration_ko": "가", "narration_en": "a",
         "estimated_sec": 4, "visual_prompt": "p", "source_facts": ["numbers[0]"],
         "reasoning_id": "R01"}]}
    out = dv.normalize_directive(raw, config.DEFAULT_VERSION, cut_max_sec=config.CUT_MAX_SEC)
    assert out["cuts"][0]["reasoning_id"] == "R01"


def test_directive_drops_reasoning_id_that_does_not_exist():
    """지시서는 대본과 별개의 LLM 호출이라, 대본에서 걸러도 여기서 다시 생길 수 있다."""
    from engine import report_directive

    units = rr.normalize_units(_raw(), FACT_SHEET, PACKET)
    directive = {"cuts": [{"cut_no": 1, "reasoning_id": "R01"},
                          {"cut_no": 2, "reasoning_id": "R42"}]}
    out = report_directive._filter_reasoning_ids(
        directive, {"financial_reasoning": {"units": units}})
    assert out["cuts"][0]["reasoning_id"] == "R01"
    assert out["cuts"][1]["reasoning_id"] == ""
