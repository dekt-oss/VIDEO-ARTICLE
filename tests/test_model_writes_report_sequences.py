"""리포트 시퀀스를 모델이 쓴다 + 화면 분할 금지 (2026-09-19 운영자 지시).

무엇이 문제였나. 리포트 시퀀스는 코드(`equity_visual`)가 통째로 만들었고, 그 코드는
**컷이 무엇을 그리는지 한 번도 보지 않았다** — `_stage_of` 와 `project_to_screen` 이 둘 다
"2번째 stage 부터 무조건 CONTINUE_WORLD" 를 찍었다.

실물 렌더로 대가가 드러났다(리포트 da1a6b96): 컷3 지시서는 "좁은 투명 파이프의 3D 단면,
데이터 입자가 입구에서 막힘"을 그리라고 했는데 **화면에 파이프가 없었다.** 코드가 찍은
이어받기 때문에 렌더가 앞 컷(위성)의 그림을 참조로 물려줬기 때문이다. 세 컷이 사실상 같은
그림이 됐고 설명이 진행되지 않았다. 운영자는 그 편을 폐기했다.

거기에 지시서가 그림 한 장 안에서 또 비교를 시켰다(`"Split screen."`). 코드가 전·후를
위아래로 다시 나누므로 화면이 **네 칸**이 됐다.
"""

from __future__ import annotations

import pathlib

from engine import equity_visual, photo_contract as pc

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"


def _reasoning():
    return {"units": [{"reasoning_id": "R01", "unit_type": "DRIVER_CHAIN",
                       "attributed_to": "유진투자증권", "carries_thesis": True,
                       "steps": [{"step": 1, "text": "데이터 전송량이 늘어난다", "fact_ids": []},
                                 {"step": 2, "text": "전파 대역이 포화된다",
                                  "fact_ids": ["numbers[0]"]},
                                 {"step": 3, "text": "레이저로 옮겨간다", "fact_ids": []}]}]}


def _model_written():
    """모델이 쓴 시퀀스 — 컷3 에서 **세계를 새로 세운다**(파이프 단면은 위성이 아니다)."""
    return [{"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
             "stages": [
                 {"stage_id": "S1", "cut_refs": [2], "continuity_mode": "NEW_WORLD",
                  "continuity_from": ""},
                 {"stage_id": "S2", "cut_refs": [3], "continuity_mode": "NEW_WORLD",
                  "continuity_from": ""},
                 {"stage_id": "S3", "cut_refs": [4], "continuity_mode": "MUTATE_STATE",
                  "continuity_from": "S2"}]}]


def _cuts():
    return [{"cut_no": 2, "reasoning_id": "R01", "reasoning_step": 1},
            {"cut_no": 3, "reasoning_id": "R01", "reasoning_step": 2},
            {"cut_no": 4, "reasoning_id": "R01", "reasoning_step": 3}]


# ── ① 모델이 쓴 이어받기를 코드가 덮어쓰지 않는다 ──────────────────
def test_annotate_never_rewrites_the_continuity_the_model_chose():
    """★★ 이것이 이 변경의 전부다. 여기서 다시 찍으면 모델에게 시퀀스를 쓰게 한 의미가 없다."""
    seqs = equity_visual.annotate(_model_written(), _cuts(), _reasoning())
    modes = [st["continuity_mode"] for st in seqs[0]["stages"]]
    froms = [st["continuity_from"] for st in seqs[0]["stages"]]
    assert modes == ["NEW_WORLD", "NEW_WORLD", "MUTATE_STATE"]
    assert froms == ["", "", "S2"]


def test_the_old_code_path_did_force_it_which_is_the_bug_we_fixed():
    """옛 경로를 나무라는 것이 아니라 **왜 바꿨는지**를 기록해 둔다."""
    seqs = equity_visual.build_for_directive(_cuts(), _reasoning())
    modes = [st["continuity_mode"] for st in seqs[0]["stages"]]
    assert modes[0] == "NEW_WORLD"
    assert set(modes[1:]) == {"CONTINUE_WORLD"}, "컷 내용과 무관하게 무조건 이어받는다"


# ── ② 원장 꼬리표는 그대로 붙는다(게이트가 계속 돈다) ──────────────
def test_annotate_attaches_the_ledger_tags_so_the_equity_gates_still_work():
    seqs = equity_visual.annotate(_model_written(), _cuts(), _reasoning())
    stages = seqs[0]["stages"]
    assert [s["reasoning_id"] for s in stages] == ["R01", "R01", "R01"]
    assert [s["reasoning_step"] for s in stages] == [1, 2, 3]
    assert stages[1]["reasoning_text"] == "전파 대역이 포화된다"
    # 수치를 든 단계만 정밀 레이어를 얹는다(R1).
    assert stages[1]["precision_layer"] == "CODE_OVERLAY"
    assert stages[0]["precision_layer"] == ""
    assert stages[1]["claim_ids"] == ["numbers[0]"]
    assert seqs[0]["reasoning_id"] == "R01"
    assert seqs[0]["attributed_to"] == "유진투자증권"
    assert seqs[0]["carries_thesis"] is True


def test_it_does_not_invent_tags_for_steps_the_ledger_never_had():
    """지어내면 EQ-V1 이 못 잡는다 — 원장에 없으면 빈 채로 두고 게이트가 막게 한다."""
    seqs = equity_visual.annotate(_model_written(), _cuts(), {"units": []})
    assert all(not s["reasoning_id"] for s in seqs[0]["stages"])


def test_coverage_still_says_how_many_steps_never_reached_the_screen():
    seqs = equity_visual.annotate(
        [{"sequence_id": "SEQ1", "stages": [{"stage_id": "S1", "cut_refs": [2]}]}],
        _cuts(), _reasoning())
    cov = seqs[0]["coverage"]
    assert cov["steps_total"] == 3 and cov["steps_on_screen"] == 1
    assert cov["steps_skipped"] == 2


def test_the_report_generator_prefers_the_model_and_falls_back_to_code():
    src = (ENGINE / "report_directive.py").read_text(encoding="utf-8")
    assert "equity_visual.annotate(" in src
    assert "모델이 visual_sequences 를 안 썼다" in src, "폴백이 조용하면 안 된다"


def test_the_report_prompt_now_asks_for_sequences():
    from engine import directive as dv
    from engine import report_directive as rd

    assert "continuity_mode" in rd.PHOTO_CONTRACT
    # 스키마는 논문 라인과 **같은 한 벌**이어야 한다(두 벌이면 한쪽만 낡는다).
    assert dv.SEQUENCE_SCHEMA in rd.PHOTO_CONTRACT
    assert dv.SEQUENCE_SCHEMA in dv.DIRECTIVE_SYSTEM_BASE


def test_sequence_blocks_are_now_fed_back_because_the_model_wrote_them():
    src = (ENGINE / "report_directive.py").read_text(encoding="utf-8")
    assert "visual_sequence_gate" in src
    assert "dv._contract_feedback(first)" in src


# ── ③ 화면 분할 금지 ───────────────────────────────────────────────
def test_the_frame_splitting_devices_are_blocked():
    blocked, warned = pc.split_composition_cuts([
        {"cut_no": 1, "visual_prompt": "Split screen. On the left, a satellite."},
        {"cut_no": 2, "visual_prompt": "Side-by-side comparison. A pipe and a channel."},
        {"cut_no": 3, "visual_prompt": "Left side: a crowded band. Right side: a clear beam."},
        {"cut_no": 4, "visual_prompt": "A diptych of two machines."},
        {"cut_no": 5, "visual_prompt": "Two panels showing the flow."}])
    assert blocked == [1, 2, 3, 4, 5]
    assert warned == []


def test_placing_two_objects_in_one_scene_is_not_a_split():
    """★ 오탐 확인(실측 11컷). 탁자 위에 모형 둘을 나란히 놓는 것은 **한 장면**이다 —
    이걸 막으면 정상인 도해가 통째로 막힌다."""
    blocked, warned = pc.split_composition_cuts([
        {"cut_no": 1, "visual_prompt":
         "On a dark studio tabletop, two anatomical models are placed side-by-side."},
        {"cut_no": 2, "visual_prompt":
         "A pair of hands places two differently colored folders on a bench."}])
    assert blocked == [] and warned == []


def test_left_right_placement_is_a_warning_not_a_block():
    """한 장면 안의 좌·우 배치는 정상인 것이 섞인다(밤의 지구, 두 도시) — 보이게만 한다."""
    blocked, warned = pc.split_composition_cuts([
        {"cut_no": 1, "visual_prompt":
         "A view of Earth from space at night. On the left, a wide cone of radio waves "
         "emanates from a city. On the right, a tight beam shoots up from another city."}])
    assert blocked == [] and warned == [1]


def test_the_gate_blocks_and_says_why_and_tells_the_model_how_to_fix_it():
    """검사·고지·되먹임 세 다리가 다 있어야 한다(gate-prompt-feedback-parity)."""
    got = pc.evaluate({"hook_ko": "훅"}, [
        {"cut_no": 1, "visual_role": "REALITY", "scene_kind": "photo",
         "visual_prompt": "Split screen. On the left, a satellite. No on-screen text."}])
    assert any(b.startswith("photo_split_composition") for b in got["block_reasons"])
    fix = pc.feedback_prompt(["photo_split_composition:1"])
    assert "컷과 컷 사이" in fix and "Split screen" in fix
    labels = (ENGINE.parent / "web" / "lib" / "blockLabels.ts").read_text(encoding="utf-8")
    assert "photo_split_composition" in labels
    assert "photo_side_by_side_layout" in labels


def test_the_report_prompt_no_longer_invites_a_split():
    """프롬프트가 '전과 후를 나란히'라고 시키면 게이트가 막는 것을 프롬프트가 부추기는 셈이다."""
    from engine import report_directive as rd

    assert "전과 후를 나란히" not in rd.PHOTO_CONTRACT
    assert "한 장에 둘을 넣지 마라" in rd.PHOTO_CONTRACT
    assert "Split screen" in rd.PHOTO_CONTRACT, "무엇이 막히는지 미리 말해 줘야 한다"
