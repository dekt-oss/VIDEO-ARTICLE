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


# ── 화면으로 보낸 "평균 N" ──────────────────────────────────────
def test_average_qualifier_leaves_with_its_screen_number():
    """조화 음파 논문 실측: 26.8% 를 화면 카드로 보내자 '평균'도 같이 빠졌고, 그게 거절 사유가 됐다."""
    point = ("조화 음향 파일 처리는 5회의 독립된 실험에서 결합조직 섬유아세포의 재생을 비처리 대조군 대비 "
             "평균 26.8 ± 7.4% 유의하게 향상시켰다.")
    plan = {"core_question": "이 연구는 무엇을 보여 주는가?", "beats": [{
        "beat_id": "NB02", "stage": "RESULT", "content_points": [point], "causal_levels": [],
        "number_delivery": {"spoken_numbers": [], "screen_facts": [
            {"ref": "XR01", "text": point, "numbers": ["26.8", "5회", "7.4%"]}]},
    }]}
    spoken = [{"beat_id": "NB02", "sentences": [
        "조화 음향 파일 처리는 여러 차례의 독립된 실험에서 결합조직 섬유아세포의 재생을 "
        "비처리 대조군 대비 유의하게 향상시켰습니다."]}]
    errors, _warnings, _ = spoken_narration._draft_guard_findings(spoken, plan)
    assert not [e for e in errors if "평균" in e or e.endswith(":hedge")], errors


def test_average_qualifier_on_a_spoken_number_is_still_protected():
    point = "참가자의 반응 시간은 평균 12% 줄었다."
    plan = {"core_question": "이 연구는 무엇을 보여 주는가?", "beats": [{
        "beat_id": "NB02", "stage": "RESULT", "content_points": [point], "causal_levels": [],
        "number_delivery": {"spoken_numbers": ["12%"], "screen_facts": []},
    }]}
    spoken = [{"beat_id": "NB02", "sentences": ["참가자의 반응 시간은 12% 줄었습니다."]}]
    errors, _warnings, _ = spoken_narration._draft_guard_findings(spoken, plan)
    assert "qualifier_dropped:NB02:평균" in errors


# ── "관련 기업" 은 연관 주장이 아니다 ─────────────────────────────
def test_gwanryeon_as_a_modifier_is_not_an_association_claim():
    assert "assoc" not in spoken_narration._meaning_classes("관련 기업의 연구비 지원을 받았습니다.")
    assert "assoc" not in spoken_narration._meaning_classes("관련 자료를 제공받았습니다.")


def test_gwanryeon_as_a_claim_is_still_association():
    for text in ("수면 시간은 기억력과 관련이 있다.", "두 변수는 관련된다.", "관련성이 보고됐다.",
                 "운동과 관련해 차이가 컸다.", "우울증과 연관된다."):
        assert "assoc" in spoken_narration._meaning_classes(text), text
