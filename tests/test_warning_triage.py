"""경고 분류 — 56개 중 위 3개만 보이고, 같은 발견을 두 번 세지 않는다 (2026-09-28).

★ 근거: docs/규칙통합_분석_2026-09-28.md §1-2. 저장 지시서 36장의 경고 중앙값 56, 진짜 고칠 것 5~8.
  삼성전자 편은 경고 22개를 달고 승인됐다 — 많을수록 안 읽힌다.
★ 여기서는 새 판정을 만들지 않는다. 있는 코드를 넷으로 가르고 **정렬**만 한다.
"""

from __future__ import annotations

from engine import config, warning_triage as wt


def test_heads_and_cut_numbers_are_parsed_from_every_suffix_shape():
    assert wt.head("photo_world_churn:3.38/분") == "photo_world_churn"
    assert wt.head("no_novelty_event#4") == "no_novelty_event"
    assert wt.head("vseq_cut_claim_mismatch:SEQ1#3") == "vseq_cut_claim_mismatch"
    assert wt.cuts_of("vseq_cut_claim_mismatch:SEQ1#3") == [3]
    assert wt.cuts_of("photo_mechanism_unlabeled:2,5") == [2, 5]
    assert wt.cuts_of("photo_world_churn:3.38/분") == []
    assert wt.cuts_of("audit_number_not_in_source:7") == [7]


def test_every_category_is_one_of_four_and_unknown_codes_are_not_hidden():
    """★ 모르는 경고를 조용히 info 로 떨어뜨리면 새 게이트가 화면에서 사라진다."""
    assert wt.category("mode_overridden") == "info"
    assert wt.category("photo_source_has_no_mechanism") == "source"
    assert wt.category("audit_number_not_in_source") == "fact"
    assert wt.category("photo_world_churn") == "action"
    assert wt.category("some_brand_new_gate") == "action"


def test_fact_reds_come_first_then_retryable_then_the_rest():
    """승인 전에 사람이 봐야 하는 것부터: 근거 빨강 → 되묻기 가능 → 나머지 → 소재 한계 → 알림."""
    warns = [
        "mode_overridden:deep->standard",                 # info
        "photo_source_has_no_mechanism",                  # source
        "photo_world_churn:3.38/분",                       # action
        "photo_lead_cut_missing_entity:seal, pipe",       # action, retryable
        "audit_number_not_in_source:4",                   # fact red
        "no_novelty_event#2", "no_novelty_event#3", "no_novelty_event#5",   # info ×3
    ]
    assert "photo_lead_cut_missing_entity" in config.RETRYABLE_QUALITY_WARNINGS
    s = wt.summarize(warns)
    order = [g["code"] for g in s["groups"]]
    assert order[:3] == ["audit_number_not_in_source", "photo_lead_cut_missing_entity", "photo_world_churn"]
    assert order[-1] in ("mode_overridden", "no_novelty_event")
    assert s["counts"] == {"fact": 1, "action": 2, "source": 1, "info": 4}
    assert s["total"] == 8 and len(s["top"]) == config.WARNING_SUMMARY_TOP_N
    assert s["hidden"] == 8 - sum(g["count"] for g in s["top"])


def test_the_same_code_over_many_cuts_is_one_line_with_the_cut_list():
    s = wt.summarize(["vseq_cut_claim_mismatch:SEQ1#3", "vseq_cut_claim_mismatch:SEQ1#5",
                      "vseq_cut_claim_mismatch:SEQ2#7"])
    assert len(s["groups"]) == 1
    assert s["groups"][0]["cuts"] == [3, 5, 7] and s["groups"][0]["count"] == 3


def test_attach_is_idempotent_and_recomputes_after_more_warnings_arrive():
    """리포트 라인은 정규화 뒤에 EQ-V 경고를 더 붙인다 — 요약이 그것을 놓치면 안 된다."""
    header = {"mode_warnings": ["photo_world_churn:2/분"]}
    wt.attach(header)
    assert header["warning_summary"]["total"] == 1
    header["mode_warnings"].append("equity_steps_off_screen:SEQ_R01#2/5")
    wt.attach(header)
    assert header["warning_summary"]["total"] == 2
    assert wt.attach(header)["warning_summary"] == header["warning_summary"]


def test_empty_warnings_give_an_empty_summary_not_a_crash():
    s = wt.summarize(None)
    assert s["total"] == 0 and s["top"] == [] and s["hidden"] == 0


def test_the_two_noise_codes_are_no_longer_warnings():
    """★ 20장에 188건(`vseq_route_contract_conflict`)·108건(`photo_mechanism_structured`) — 둘 다
    "코드가 이미 정했다/면제했다"는 알림이었다. 경고 목록에서 뺀다(전자는 지표로 남는다)."""
    from engine import photo_contract, visual_sequence_contract as vc

    assert "vseq_route_contract_conflict" not in vc.WARNING_REASONS
    assert "photo_mechanism_structured" not in photo_contract.WARNING_REASONS
