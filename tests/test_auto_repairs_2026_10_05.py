"""막힘 자동 교정(2026-10-05 운영자 "막힘 자동 교정만 작업해") — 모양이 정해진 실수는 막지 않고 고친 뒤 경고로 남긴다."""

from __future__ import annotations

from engine import config, report_reasoning, spoken_narration, visual_sequence


# ── 한자어 부정(불필요 ↔ 필요 없다) ───────────────────────────
def test_sino_korean_negation_matches_its_plain_paraphrase():
    before = spoken_narration._meaning_classes("주파수 허가도 불필요하여 수요를 충족시킬 수 있다.")
    after = spoken_narration._meaning_classes("주파수 허가도 필요 없어 이러한 수요를 충족할 수 있습니다.")
    assert "negation" in before and "negation" in after


def test_dropping_a_sino_korean_negation_is_still_caught():
    before = spoken_narration._meaning_classes("허가가 불필요하다.")
    after = spoken_narration._meaning_classes("허가가 필요하다.")
    assert "negation" in before and "negation" not in after


# ── stage 하나뿐인 MECHANISM_SEQUENCE ─────────────────────────
def _seq(role, stages):
    return {"sequence_id": "SEQ2", "sequence_role": role,
            "stages": [{"stage_id": f"S{i}"} for i in range(stages)]}


def test_single_stage_mechanism_sequence_is_relabeled():
    seqs = [_seq("MECHANISM_SEQUENCE", 1), _seq("MECHANISM_SEQUENCE", 2)]
    seqs[1]["sequence_id"] = "SEQ3"
    assert visual_sequence.relabel_single_stage_mechanism(seqs) == ["SEQ2"]
    assert [s["sequence_role"] for s in seqs] == ["REALITY_ANCHOR", "MECHANISM_SEQUENCE"]


def test_relabel_switch_off_keeps_the_block(monkeypatch):
    monkeypatch.setattr(config, "VSEQ_SINGLE_STAGE_RELABEL", False)
    seqs = [_seq("MECHANISM_SEQUENCE", 1)]
    assert visual_sequence.relabel_single_stage_mechanism(seqs) == []
    assert seqs[0]["sequence_role"] == "MECHANISM_SEQUENCE"


def test_normalize_warns_instead_of_blocking_a_single_stage_mechanism():
    from engine import directive
    obj = {"header": {}, "cuts": [{"cut_no": 1, "narration_ko": "가", "estimated_sec": 4},
                                  {"cut_no": 2, "narration_ko": "나", "estimated_sec": 4}],
           "visual_sequences": [{"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
                                 "stages": [{"stage_id": "S1", "cut_refs": [1, 2]}]}]}
    d = directive.normalize_directive(obj, "photo")
    assert "vseq_single_stage_relabeled:SEQ1" in d["header"]["mode_warnings"]
    blocks = (d["header"].get("visual_sequence_gate") or {}).get("block_reasons") or []
    assert not any(b.startswith("vseq_too_few_stages") for b in blocks)


# ── 리포트: 숫자 단계를 옮기는 도해 컷 → 실사 ──────────────────
_REASONING = {"units": [{"reasoning_id": "R01", "unit_type": "DRIVER",
                         "steps": [{"step": 1, "text": "병목이 우회로를 만든다"},
                                   {"step": 4, "text": "DS부문의 실적 개선이 전사 실적을 견인", "fact_ids": ["numbers[6]"]}]}]}


def test_mechanism_cut_on_a_number_step_is_demoted_to_reality():
    cuts = [{"cut_no": 2, "visual_role": "MECHANISM", "reasoning_id": "R01", "reasoning_step": 1},
            {"cut_no": 6, "visual_role": "MECHANISM", "reasoning_id": "R01", "reasoning_step": 4,
             "mechanism": {"subject": "blocks"}, "resolved_visual_plan": {"visual_role": "MECHANISM"}}]
    misuse = report_reasoning.mechanism_step_misuse(cuts, _REASONING)
    assert misuse == ["photo_mechanism_on_number:6"]
    assert report_reasoning.demote_misused_mechanism(cuts, misuse) == ["6"]
    assert cuts[1]["visual_role"] == "REALITY" and "mechanism" not in cuts[1]
    assert cuts[1]["resolved_visual_plan"]["visual_role"] == "REALITY"
    assert cuts[0]["visual_role"] == "MECHANISM", "과정 단계 도해는 그대로"
    assert report_reasoning.mechanism_step_misuse(cuts, _REASONING) == []
