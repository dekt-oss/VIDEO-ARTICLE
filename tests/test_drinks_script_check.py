"""주류 대본·화면 계획 코드 검사 — 2026-10-24~26 시험에서 나온 실제 대본들로 회귀를 묶는다.

운영자가 잡은 문제(원문에 없는 처방·양·권고)가 코드에서 막히는지, 고친 v5 는 통과하는지.
★ 코드가 못 보는 것(문장 뜻의 비약 — v1 의 "한두 방울 → 45% 아래로")은 이 테스트의 범위가 아니다(Jev·사람 대조표).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import drinks_script_check as sc
from engine import drinks_produce as dp

FIX = Path(__file__).resolve().parent / "fixtures" / "drinks_scripts"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def blocks(name):
    return {(f.code, f.scene) for f in sc.check(load(name)).blocks}


def test_v5_script_passes_but_its_screen_plan_is_blocked_by_engine_rules():
    """v5 대본(문장)은 원문 대조를 통과하지만, 그 화면 계획으로 산 그림 3장은 실패했다(운영자 "세 화면이 너무 떡같은데").
    엔진 실사형 규칙을 들이자 원인이 그대로 걸린다 — 3D 도해 장면에 구조(무엇이 보이고 무엇이 바뀌나)가 없었다."""
    rep = sc.check(load("whisky-v5"))
    assert {c for c in rep.codes() if not c.startswith("photo_")} == set()
    assert {(f.code, f.scene) for f in rep.blocks} == {("photo_mechanism_spec_missing", n) for n in (3, 4, 5)}


def test_v6_engine_screen_plan_passes():
    rep = sc.check(load("whisky-v6"))
    assert rep.ok, sc.summary_ko(rep)
    assert not [w for w in rep.warns if w.code in ("conclusion_missing", "formal_style", "photo_hook_cut_too_long")]


def test_v4_invented_dosing_is_blocked():
    """'60도 안팎 위스키라면, 30ml에 물 세 티스푼쯤 타 보세요. 40도 정도가 돼요.' — 원문에 없는 처방."""
    b = blocks("whisky-v4")
    assert ("derived_claim_cited", 7) in b, "계산 근거(c6)를 화면 문장에 썼다"
    assert ("quantity_unsupported", 7) in b, "'세 티스푼'·'30ml' 은 원문에 없다"
    assert ("advice_unsupported", 7) in b, "'타 보세요' 권고의 근거가 실제 습관을 말한 원문이 아니다"
    assert ("number_unsupported", 7) in b


@pytest.mark.parametrize("name", ["whisky-v1", "whisky-v2", "whisky-v3", "whisky-v4", "whisky-v5", "sake-v2"])
def test_every_rejected_version_is_blocked(name):
    assert not sc.check(load(name)).ok, name


def test_v1_drops_claim_cited_a_quote_without_drops():
    """v1 의 c1 인용은 'slight dilution' 뿐이었다 — '한두 방울'을 받쳐 주지 못한다(사람이 놓쳤던 것)."""
    assert ("quantity_unsupported", 7) in blocks("whisky-v1")


def test_sake_converted_years_need_the_source_number():
    """원문은 平成6年·平成27年 — 1994·2015 는 환산값이라 원문 숫자가 아니다."""
    b = blocks("sake-v2")
    assert ("number_unsupported", 4) in b and ("number_unsupported", 5) in b
    assert ("advice_unsupported", 7) in b


def test_rules_on_small_cases():
    claims = [{"claim_id": "a", "text": "x", "original_quote": "Whisky enthusiasts often also add a few drops of water", "kind": "practice"},
              {"claim_id": "b", "text": "y", "original_quote": "diluted to around 40 vol-%"},
              {"claim_id": "calc", "text": "z", "original_quote": "(계산 — 원문 아님)"}]
    ok = {"claims": claims, "viewer_conclusion": {"text": "t", "claim_ids": ["b"]}, "scenes": [
        {"narration": "왜 그럴까요?", "content_kind": "transition", "visual_role": "text_card"},
        {"narration": "물을 한두 방울 넣어 보세요.", "claim_ids": ["a"], "visual_role": "text_card"},
        {"narration": "병에 담기 전 40도로 맞춰요.", "claim_ids": ["b"], "visual_role": "text_card"}]}
    assert sc.check(ok).ok, sc.summary_ko(sc.check(ok))
    bad = json.loads(json.dumps(ok))
    bad["scenes"][2]["narration"] = "병에 담기 전 45도로 맞춰요."
    bad["scenes"][1]["claim_ids"] = ["b"]
    bad["scenes"].append({"narration": "사실이에요.", "visual_role": "text_card"})
    bad["scenes"].append({"narration": "물 두 스푼을 넣으세요.", "claim_ids": ["calc"], "visual_role": "text_card"})
    got = {(f.code, f.scene) for f in sc.check(bad).blocks}
    assert {("number_unsupported", 3), ("advice_unsupported", 2), ("fact_scene_no_claim", 4),
            ("derived_claim_cited", 5), ("quantity_unsupported", 5), ("advice_unsupported", 5)} <= got


def test_visual_rules():
    claims = [{"claim_id": "a", "text": "x", "original_quote": "q"}]
    spec = {"claims": claims, "viewer_conclusion": {"text": "t", "claim_ids": ["a"]}, "scenes": [
        {"narration": "가?", "claim_ids": ["a"], "visual_role": "reality"},
        {"narration": "나.", "claim_ids": ["a"], "visual_role": "mechanism", "visual_prompt": "a glass with the word 'SMOKE' written"},
        {"narration": "다.", "claim_ids": ["a"], "visual_role": "reality", "visual_prompt": "a hand", "continuity": "ref:3"}]}
    got = {(f.code, f.scene) for f in sc.check(spec).blocks}
    assert {("visual_prompt_missing", 1), ("text_in_image", 2), ("continuity_invalid", 3)} <= got


def test_formal_style_and_missing_conclusion_are_warnings_only():
    spec = {"claims": [{"claim_id": "a", "text": "x", "original_quote": "q"}], "scenes": [
        {"narration": "그렇습니다.", "claim_ids": ["a"], "visual_role": "text_card"}]}
    rep = sc.check(spec)
    assert rep.ok
    assert {"formal_style", "conclusion_missing", "hook_missing"} <= {w.code for w in rep.warns}


def test_db_evidence_pack_shape_is_understood():
    """DB 근거 묶음은 claim 마다 source_refs[].original_quote — 같은 규칙이 그 꼴에도 붙는다."""
    plan = {"scenes": [{"narration": "정미율 50% 이하예요.", "claim_ids": ["c1"], "visual_role": "text_card"},
                       {"narration": "정미율 40% 예요.", "claim_ids": ["c1"], "visual_role": "text_card"}]}
    claims = [{"claim_id": "c1", "text": "정미율 50% 이하", "claim_type": "process",
               "source_refs": [{"snapshot_id": "s", "original_quote": "정미율 50% 이하의 백미"}]}]
    got = {(f.code, f.scene) for f in sc.check(sc.plan_spec(plan, claims)).blocks}
    assert got == {("number_unsupported", 2)}


def test_engine_rules_reach_the_image_prompt_and_shorts_skip_length_rules():
    from engine import config
    from engine import drinks_paid as dpaid
    from engine import drinks_screen

    s = load("whisky-v6")
    items = dpaid.build_image_items(s["scenes"], [3, 4, 5])
    mech = items[1].prompt
    assert "showing tulip whisky glass, amber aroma beads and blue alcohol beads all visible together" in mech
    assert "amber aroma beads is the part being explained" in mech
    assert "The change to show:" in items[2].prompt, "이어 그리는 도해 컷은 바뀌는 것만 말한다(엔진 참조 규칙)"
    assert "label" not in config.DRINKS_PRODUCT_CLAUSE, "부정어로 라벨을 부르지 않는다(1단계 실측: 잔에 빈 라벨·빈 상자)"
    g = drinks_screen.gate(s["scenes"])
    assert not any(c in drinks_screen.NOT_FOR_SHORTS for c, _ in g["blocks"] + g["warns"])
    assert sc._first_scene("28자") is None and sc._first_scene("3,4") == 3


def test_paid_worker_refuses_before_spending_when_script_check_fails(tmp_path):
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        return {"status": p.get("outcome")} if fn == "drinks_finish_render" else {}
    job = {"job_id": "j1", "lease_token": "t", "format": "video", "renderer": "paid", "spend_approval_id": "ap",
           "plan": {"scenes": [{"narration": "30ml에 물 세 티스푼 타 보세요.", "claim_ids": ["c1"], "visual_role": "reality",
                                "visual_prompt": "a glass"}]},
           "claims": [{"claim_id": "c1", "text": "희석", "claim_type": "process",
                       "source_refs": [{"original_quote": "diluted to around 40 vol-%"}]}],
           "topic": {"title": "t", "question": "q"}}
    res = dp.process_job(job, rpc, dp.Storage("local", str(tmp_path)))
    assert res["status"] == "failed"
    fin = [p for fn, p in calls if fn == "drinks_finish_render"][0]
    assert fin["error_code"] == "script_check_failed"
    assert not any(fn in ("drinks_hold_spend", "drinks_find_generated") for fn, _ in calls)
