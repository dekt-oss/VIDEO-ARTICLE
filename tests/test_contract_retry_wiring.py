"""재생성 되먹임이 **계약 두 벌 모두**를 보는지 본다 (2026-08-31).

★ 무엇이 문제였나: `generate()` 의 재생성 루프가 `header.photo_gate` 만 읽었다.
  그런데 승인 차단은 세 곳에서 나온다(normalize_directive):

      directive_block_reasons + photo_gate + visual_sequence_gate

  결과가 둘이었다.
    ① 시각 시퀀스 계약**만** 위반한 지시서는 `first_reasons` 가 비어
       **재생성이 아예 돌지 않았다** — 되먹임 없이 그대로 사람 검수로 갔다.
    ② 둘 다 위반해도 모델은 시퀀스 쪽 처방을 못 들었다.

  실제로 `visual_sequence_contract.feedback_prompt` 는 **저장소 어디에서도 불리지
  않았다**(grep 0건). 만들어 놓고 한쪽만 연결한 것이 이 저장소에서 또 나온 것이다.

★ 그래서 이 파일이 보는 것은 문구가 아니라 **배선**이다.
"""

from __future__ import annotations

from engine import directive as dv


def _directive(photo: list[str], vseq: list[str]) -> dict:
    return {"header": {"photo_gate": {"block_reasons": photo, "warnings": []},
                       "visual_sequence_gate": {"block_reasons": vseq}}}


def test_vseq_only_violation_triggers_the_retry():
    """★ 이것이 종전에 **재생성 없이** 사람 검수로 가던 경우다."""
    assert dv._contract_reasons(_directive([], ["vseq_no_progression:SEQ1/S1"]))


def test_both_families_reach_the_model():
    fb = dv._contract_feedback(_directive(["photo_hook_missing"],
                                          ["vseq_literal_without_source:SEQ2/S4"]))
    assert "hook_ko" in fb, "photo 처방이 빠졌다"
    assert "SCHEMATIC_PRINCIPLE" in fb, "시각 시퀀스 처방이 빠졌다"


def test_clean_directive_does_not_trigger_a_paid_retry():
    """★ 반대 방향 — 통과한 지시서로 유료 호출을 한 번 더 하면 안 된다."""
    assert dv._contract_reasons(_directive([], [])) == []
    assert dv._contract_feedback(_directive([], [])) == ""


def test_unfeedbackable_reasons_are_deliberately_excluded():
    """★ `directive_block_reasons`(예산 초과·원문 미확보 등)는 **일부러** 안 넣는다.

    다시 물어봐도 고쳐지지 않는 사유로 재생성을 돌리면 유료 호출만 한 번 더 나간다.
    차단은 그대로 유지된다 — 승인은 `header.block_reasons` 가 막는다.
    """
    d = _directive([], [])
    d["header"]["block_reasons"] = ["video_budget_exceeded", "cut_claim_not_in_source:3"]
    assert dv._contract_reasons(d) == []


def test_the_sequence_feedback_function_is_actually_called():
    """★★ 이 파일의 핵심. grep 으로는 놓치니 호출을 가로채서 확인한다.

    "만들어 놓고 한쪽만 연결"을 구조로 막는다.
    """
    from engine import visual_sequence_contract as vc
    called: list[list[str]] = []
    original = vc.feedback_prompt
    vc.feedback_prompt = lambda rs: called.append(list(rs)) or original(rs)  # type: ignore
    try:
        dv._contract_feedback(_directive([], ["vseq_missing_entity:SEQ1/S1"]))
    finally:
        vc.feedback_prompt = original  # type: ignore
    assert called == [["vseq_missing_entity:SEQ1/S1"]], called


def test_a_passing_contract_does_not_dilute_the_other_ones_prescription():
    """★ photo 는 통과하고 시각 시퀀스만 위반한 경우.

    종전에는 photo_contract 가 빈 입력에도 일반문("계약 위반을 고쳐라")을 뱉어서,
    그 문장이 시퀀스 처방 위에 얹혀 **무엇을 고칠지를 흐렸다.** 처방이 하나면
    화면에 그 하나만 나가야 한다.
    """
    fb = dv._contract_feedback(_directive([], ["vseq_missing_entity:SEQ1/S1"]))
    assert "계약 위반을 고쳐라" not in fb
    assert "entities" in fb
