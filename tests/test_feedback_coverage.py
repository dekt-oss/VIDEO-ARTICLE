"""차단 사유마다 **고치는 법**이 있는지 본다 (2026-08-31).

★ 무엇이 문제였나: 재생성 되먹임(`feedback_prompt`)에 빈칸이 있었다.

  - `visual_sequence_contract` — 차단 사유 10개 중 **9개**에만 처방이 있었다.
    빠진 하나가 하필 재생성 실측에서 실제로 막힌 `vseq_literal_without_source` 였다.
  - `photo_contract` — 14개 중 **8개**. 빠진 것 중 하나가 역시 실측 차단 사유였던
    `photo_text_request_conflict` 다.

  차단만 하고 고치는 법을 안 주면 재시도는 같은 결함을 반복한다. 게이트의 목적은
  막는 것이 아니라 **통과시키는 것**이다 — 아무것도 통과 못 하는 게이트는 없는 게이트와
  같다(핸드오프 §3-①에서 예산으로 한 번 겪었다).

★ 그래서 이 파일은 문구를 검사하지 않는다. **완결성**을 검사한다 — 사유 목록에 새 코드를
  넣으면 처방도 같이 쓰게 만드는 것이 목적이다.
"""

from __future__ import annotations

import pytest

from engine import photo_contract as pc, visual_sequence_contract as vc

# 처방이 하나도 맞지 않았을 때 나오는 일반 문장. 이것이 나오면 "빈칸"이다.
_PHOTO_FALLBACK = "- 계약 위반을 고쳐라."


@pytest.mark.parametrize("reason", pc.BLOCK_REASONS)
def test_photo_every_block_reason_has_a_prescription(reason: str):
    got = pc.feedback_prompt([f"{reason}:1"])
    assert got, reason
    assert _PHOTO_FALLBACK not in got, (
        f"{reason} 에 처방이 없다 — 모델은 무엇을 고쳐야 하는지 듣지 못한다")


@pytest.mark.parametrize("reason", vc.BLOCK_REASONS)
def test_vseq_every_block_reason_has_a_prescription(reason: str):
    got = vc.feedback_prompt([f"{reason}:SEQ1/S1"])
    assert got, f"{reason} 에 처방이 없다 — 되먹임이 통째로 빈다"


def test_prescriptions_say_how_not_just_what():
    """★ "틀렸다"만 말하는 처방은 처방이 아니다. 고치는 **동작**이 있어야 한다.

    느슨한 검사다(어휘 몇 개). 목적은 완벽한 판정이 아니라, 새 사유를 넣는 사람이
    한 줄짜리 반복 문장으로 때우지 못하게 하는 것이다.
    """
    verbs = ("바꿔", "적어", "지워", "빼", "넣어", "옮겨", "채워", "쪼개", "나눠",
             "선언", "삭제", "늘려", "만들어", "고쳐라", "포기")
    for mod, reasons, sep in ((pc, pc.BLOCK_REASONS, ":1"),
                              (vc, vc.BLOCK_REASONS, ":SEQ1/S1")):
        for reason in reasons:
            got = mod.feedback_prompt([f"{reason}{sep}"])
            assert any(v in got for v in verbs), (reason, got)


def test_the_two_reasons_that_actually_blocked_the_regen_now_have_prescriptions():
    """★ 회귀 고정 — 2026-08-31 재생성 실측에서 막았는데 처방이 없던 둘."""
    p = pc.feedback_prompt(["photo_text_request_conflict:6"])
    assert _PHOTO_FALLBACK not in p and "overlay_plan" in p

    v = vc.feedback_prompt(["vseq_literal_without_source:SEQ2/S4"])
    assert "SCHEMATIC_PRINCIPLE" in v


def test_block_labels_mirror_every_reason():
    """★ 운영자 화면도 같은 목록을 미러해야 한다 — 사유 코드가 그대로 나가면 못 읽는다."""
    import pathlib
    src = pathlib.Path("web/lib/blockLabels.ts").read_text(encoding="utf-8")
    for reason in (*pc.BLOCK_REASONS, *vc.BLOCK_REASONS):
        assert reason in src, f"{reason} 의 표시 문자열이 web/lib/blockLabels.ts 에 없다"
