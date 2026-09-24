"""증권 리포트의 원리는 논증 단위다 — 단계의 종류가 화면을 정한다 (2026-09-24, 운영자 승인).

무엇이 있었나
------------
운영자 질문: "증권 리포트는 메커니즘 없이 어떻게 보여줄 건데? 시장의 작동 원리나 산업 이슈의
과정 설명은 어떻게 할 건데?"

답은 이미 저장소에 있었다. 리포트 초안은 대본보다 먼저 **논증 단위**(driver → 실적 →
밸류에이션)를 뽑고, 단계마다 원문 인용으로 근거를 대조한다(report_reasoning). 그것이
이 라인의 "왜 그런가"다. 문제는 쓰는 법이었다:

    · 프롬프트가 단계의 종류를 안 가르고 "기전 5~7컷"만 요구했다
      → 모델이 숫자("13.7조원")를 **블록 막대그래프**로, 규제를 **쇠쐐기 은유**로 그렸다
      (실측 저장 11편·기전 컷 48개: 과정 28 · 숫자 10 · 리스크 10)
    · 게이트는 논문 방식(Fact Sheet 의 claim)으로만 "소재에 원리가 있나"를 재서
      리포트에는 **늘 "원리 없음"** 이라고 경고했다 — 과정 단계가 28개인데도

무엇을 고쳤나
------------
    ① 코드가 단계를 셋으로 가른다: 과정 / 숫자 / 리스크 (fact_ids·수치·unit_type 으로)
    ② 원리 공급량 = 과정 단계 수 (게이트가 Fact Sheet 대신 이것을 본다)
    ③ 프롬프트가 단계마다 kind 를 적어 주고, 숫자·리스크 단계의 MECHANISM 을 금지한다
    ④ 새 게이트: MECHANISM 컷이 숫자·리스크 단계를 옮기면 차단 + 처방 되먹임 + 재생성
"""

from __future__ import annotations

import copy

from engine import config, photo_contract as pc, report_directive as rd, report_reasoning as rr
from tests.test_directive_code_repairs import _with_sequences
from tests.test_photo_contract import _raw


def _unit(rid, ut, steps):
    return {"reasoning_id": rid, "unit_type": ut, "title": rid, "carries_thesis": False,
            "attributed_to": "SK증권", "assumption": "", "breaks_if": "",
            "steps": [{"step": i + 1, "text": t, "fact_ids": f, "source_refs": []}
                      for i, (t, f) in enumerate(steps)]}


def _reasoning():
    return {"units": [
        _unit("R01", "DRIVER_CHAIN", [
            ("조선주 주가가 급락해 12M Fwd P/E 가 최저 수준까지 낮아졌다.", []),      # 수치 → 숫자
            ("고수익 선종 중심의 선별 수주로 이익 체력이 강해지고 있다.", []),           # 과정
            ("합산 영업이익이 2028년 13.7조원으로 2배가 된다.", ["num_op_2028"]),      # 원장 → 숫자
        ]),
        _unit("R02", "CATALYST_PATH", [
            ("AI 데이터센터 확대로 전력망 병목이 심화돼 중속 엔진 수요가 늘고 있다.", []),  # 과정
            ("부지·전력망 병목을 우회하는 부유식 데이터센터가 대안으로 부상했다.", []),     # 과정
        ]),
        _unit("R04", "RISK_PATH", [
            ("미 의회가 수상전투함 해외 건조에 반대해 불확실성이 크다.", []),           # 리스크
            ("중국 캐파 확대가 선가에 10% 하방 압력으로 작용한다.", []),              # 리스크(수치 있어도)
        ]),
    ]}


# ── ① 단계의 종류는 코드가 정한다 ────────────────────────────────
def test_steps_are_classified_by_data_not_by_the_model():
    kinds = rr.step_kinds(_reasoning())
    assert kinds[("R01", 1)] == rr.STEP_KIND_NUMBER, "P/E 수치"
    assert kinds[("R01", 2)] == rr.STEP_KIND_PROCESS
    assert kinds[("R01", 3)] == rr.STEP_KIND_NUMBER, "원장 참조"
    assert kinds[("R02", 1)] == rr.STEP_KIND_PROCESS
    assert kinds[("R02", 2)] == rr.STEP_KIND_PROCESS
    assert kinds[("R04", 1)] == rr.STEP_KIND_RISK
    assert kinds[("R04", 2)] == rr.STEP_KIND_RISK, "리스크 단위 안의 숫자는 리스크다"


def test_valuation_and_bridge_units_are_numbers_even_without_digits():
    u = _unit("R09", "VALUATION_LOGIC", [("목표 멀티플을 과거 평균에 둔다.", [])])
    assert rr.step_kind(u, u["steps"][0]) == rr.STEP_KIND_NUMBER


# ── ② 공급량 = 과정 단계 수 ─────────────────────────────────────
def test_mechanism_supply_is_the_process_step_count():
    assert rr.process_step_count(_reasoning()) == 3
    assert rr.process_step_count(None) == 0
    assert rr.process_step_count({"units": []}) == 0


def test_the_gate_stops_calling_a_report_with_process_steps_sourceless():
    """리포트는 Fact Sheet 에 claims 가 없다 — 공급량을 넘기면 '원리 없는 소재' 경고가 꺼진다."""
    raw = _with_sequences(_raw("좋은 훅"))
    header, cuts = {"visual_sequences": raw["visual_sequences"], "hook_ko": "좋은 훅"}, raw["cuts"]
    without = pc.evaluate(header, cuts, None)
    with_supply = pc.evaluate(header, cuts, None, mechanism_supply=3)
    assert "photo_source_has_no_mechanism" in without["warnings"]
    assert "photo_source_has_no_mechanism" not in with_supply["warnings"]


# ── ③ 프롬프트가 종류를 말한다 ─────────────────────────────────
def test_the_units_block_labels_every_step_with_its_kind():
    block = rr.units_block(_reasoning())
    assert "숫자 → REALITY + 숫자 카드 (MECHANISM 금지)" in block
    assert "리스크 → REALITY + 한 줄 카드 (MECHANISM 금지)" in block
    assert "과정 → MECHANISM 도해 가능" in block


def test_the_directive_prompt_forbids_mechanism_on_numbers_and_risks():
    row = {"script_md": "문장.", "fact_sheet": {}, "scenes": [],
           "financial_reasoning": _reasoning()}
    user = rd.report_directive_user_prompt(row, "photo")
    assert "kind 가 **숫자** 인 단계" in user and "MECHANISM 금지" in user
    assert "블록·막대·높이 차이로 수치를 보이는 것은 그래프다" in user
    assert "원가·마진 구조" not in user, "그래프를 부르는 소재를 목록에서 뺐다"


# ── ④ 게이트 · 처방 · 재생성 ───────────────────────────────────
def _cut(no, role, rid, step):
    return {"cut_no": no, "visual_role": role, "reasoning_id": rid, "reasoning_step": step}


def test_mechanism_on_a_number_step_is_blocked_and_named():
    cuts = [_cut(3, "MECHANISM", "R01", 3), _cut(4, "MECHANISM", "R02", 1),
            _cut(7, "MECHANISM", "R04", 1), _cut(8, "REALITY", "R01", 3)]
    got = rr.mechanism_step_misuse(cuts, _reasoning())
    assert got == ["photo_mechanism_on_number:3", "photo_mechanism_on_risk:7"], got


def test_a_process_step_drawn_as_mechanism_is_fine():
    assert rr.mechanism_step_misuse([_cut(4, "MECHANISM", "R02", 2)], _reasoning()) == []


def test_unlinked_or_unknown_steps_are_not_judged():
    """논증을 옮기지 않는 컷(훅·마무리)과 없는 id 는 다른 게이트의 일이다."""
    cuts = [_cut(1, "MECHANISM", "", 0), _cut(2, "MECHANISM", "R99", 1)]
    assert rr.mechanism_step_misuse(cuts, _reasoning()) == []


def test_the_codes_are_registered_and_have_prescriptions():
    for code in ("photo_mechanism_on_number", "photo_mechanism_on_risk"):
        assert code in pc.BLOCK_REASONS
        assert "REALITY" in pc.feedback_prompt([f"{code}:3"]), code


def test_the_report_path_blocks_and_feeds_back_then_retries(monkeypatch):
    """검사·고지·되먹임 셋이 한 배선에 있다(gate-prompt-feedback parity)."""
    base = _with_sequences(_raw("좋은 훅"))
    for c in base["cuts"]:
        c["reasoning_id"], c["reasoning_step"] = "", 0
    bad = copy.deepcopy(base)
    mech = [c for c in bad["cuts"] if str(c.get("visual_role") or "").upper() == "MECHANISM"]
    assert mech, "fixture 에 MECHANISM 컷이 있어야 한다"
    mech[0]["reasoning_id"], mech[0]["reasoning_step"] = "R01", 3      # 13.7조 단계를 도해로
    calls = []

    def fake(**kw):
        calls.append(kw["user"])
        return copy.deepcopy(bad if len(calls) == 1 else base)

    monkeypatch.setattr(rd, "call_json", fake)
    row = {"script_md": "문장.", "fact_sheet": {"source_depth": "full_text"}, "scenes": [],
           "financial_reasoning": _reasoning()}
    out = rd.generate(row, "photo")
    assert len(calls) == 2, "차단이면 한 번 되묻는다"
    assert "숫자·전망치 단계" in calls[1], "처방이 되먹임에 실려야 한다"
    assert not any(r.startswith("photo_mechanism_on_number")
                   for r in out["header"].get("block_reasons") or [])
