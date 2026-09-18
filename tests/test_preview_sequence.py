"""시퀀스 미리보기 도구 (scripts/preview_sequence.py, 2026-09-18).

무엇을 지키는가: 이 도구의 약속은 둘이다 — **기전 시퀀스를 고른다**, **"그림만"이라고 하면
영상을 사지 않는다**. 둘 다 조용히 깨질 수 있는 종류라 테스트로 못박는다(유료 도구다).
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.preview_sequence import pick_sequence

SRC = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "preview_sequence.py"
       ).read_text(encoding="utf-8")


def _directive(*, roles: dict[int, str]) -> dict:
    """시퀀스 둘 — SEQ_REAL(컷 1·2), SEQ_MECH(컷 3·4)."""
    return {
        "header": {"visual_sequences": [
            {"sequence_id": "SEQ_REAL", "sequence_role": "MECHANISM_SEQUENCE",
             "stages": [{"stage_id": "A", "cut_refs": [1]}, {"stage_id": "B", "cut_refs": [2]}]},
            {"sequence_id": "SEQ_MECH", "sequence_role": "RESULT_SEQUENCE",
             "stages": [{"stage_id": "C", "cut_refs": [3]}, {"stage_id": "D", "cut_refs": [4]}]},
        ]},
        "cuts": [{"cut_no": n, "visual_role": r} for n, r in roles.items()],
    }


def test_it_picks_the_sequence_with_the_most_mechanism_cuts():
    """★ 라벨(sequence_role)을 믿지 않는다 — 이 저장소는 완벽한 기전 진행에 모델이
    RESULT_SEQUENCE 를 붙인 실측을 갖고 있다. 여기서도 라벨은 SEQ_REAL 쪽에 붙어 있다."""
    d = _directive(roles={1: "REALITY", 2: "REALITY", 3: "MECHANISM", 4: "MECHANISM"})
    assert pick_sequence(d) == "SEQ_MECH"


def test_an_explicit_sequence_wins_and_a_wrong_one_fails_loudly():
    d = _directive(roles={1: "REALITY", 2: "REALITY", 3: "MECHANISM", 4: "MECHANISM"})
    assert pick_sequence(d, "SEQ_REAL") == "SEQ_REAL"
    with pytest.raises(SystemExit):
        pick_sequence(d, "SEQ_NOPE")


def test_a_directive_without_sequences_says_so_instead_of_crashing():
    with pytest.raises(SystemExit):
        pick_sequence({"header": {}, "cuts": []})


def test_stills_mode_actually_turns_off_the_stage_renderer():
    """★★ 컷의 motion_source 를 still 로 바꾸는 것만으로는 영상비가 **안 줄어든다** —
    stage_render 는 motion_source 를 보지 않고 stage 단위로 Veo 를 산다. "그림만"이라고
    말하면서 영상을 사면 그게 가장 나쁜 거짓말이다(2026-09-18 실측으로 잡았다)."""
    assert "config.STAGE_RENDER_ENABLED = False" in SRC


def test_it_refuses_to_spend_without_yes():
    """이 저장소는 승인 없이 1.7만원을 쓴 적이 있다 — 생성 도구는 스스로 멈출 줄 알아야 한다."""
    assert "if not args.yes:" in SRC
    assert "지금은 아무것도 만들지 않았다" in SRC


def test_output_paths_are_absolute():
    """★ 상대 경로를 주면 ffmpeg 가 concat 목록의 경로를 두 번 이어 붙여 죽는다(실측)."""
    assert "/ args.directive_id[:8]).resolve()" in SRC
