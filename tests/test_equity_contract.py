"""EQ-V 계약 — 리포트(주식) 라인의 시각 시퀀스 게이트 (작업지시서 §11).

★ 무엇을 지키는가: 논문 라인에는 차단 게이트가 26개인데 리포트 라인에는 **하나도
  없었다.** 같은 엔진의 두 라인이 비대칭이었다는 것이 이 게이트가 메우는 구멍이다.

★★ 그리고 **차단과 경고의 경계**를 박는다: 코드가 만든 데이터의 모양을 보는 검사는
  오탐이 없으므로 차단하고, 리포트 문장을 어휘로 읽는 검사는 경고로 둔다. 이 경계가
  흐려지면 어휘 오탐이 승인을 막고, 그러면 운영자가 게이트를 무시하기 시작한다.
"""

from __future__ import annotations

from engine import equity_contract as ec


def stage(sid: str, **f):
    base = {"stage_id": sid, "reasoning_id": "R1", "entity_refs": ["ORDER"],
            "observable_change": "흐름이 굵어진다", "reasoning_text": "수주가 늘었다",
            "claim_ids": ["F1"], "precision_layer": "CODE_OVERLAY",
            "mutations": [{"result_state": "flow thickens"}]}
    base.update(f)
    return base


def seqs(*stages):
    return [{"sequence_id": "SEQ1", "stages": list(stages)}]


# ── 정상 시퀀스는 아무것도 내지 않는다 ────────────────────────

def test_a_clean_sequence_passes_both_checks():
    s = seqs(stage("S1"), stage("S2", observable_change="흐름이 더 굵어진다"))
    assert ec.block_reasons(s) == []
    assert ec.warnings(s) == []


def test_empty_input_is_handled():
    assert ec.block_reasons(None) == [] and ec.block_reasons([]) == []
    assert ec.warnings(None) == [] and ec.warnings([]) == []


# ── 차단: 구조 판정 ───────────────────────────────────────────

def test_eq_v1_blocks_a_stage_with_no_reasoning_link():
    """연결이 끊기면 '리포트가 말한 것'과 '화면이 말하는 것'을 대조할 방법이 사라진다."""
    out = ec.block_reasons(seqs(stage("S1", reasoning_id="")))
    assert out == ["eq_v1_reasoning_link_missing:S1"]


def test_eq_v4_blocks_an_exact_number_pushed_into_the_generated_screen():
    """수치는 코드가 그리는 정밀 레이어가 담당한다 — 생성 이미지에 개수로 근사하지 않는다."""
    s = seqs(stage("S1", reasoning_text="지분 49.99% 를 확보했다",
                   observable_change="지분 49.99% 만큼 채워진다"))
    assert ec.block_reasons(s) == ["eq_v4_number_in_generated_screen:S1"]


def test_eq_v4_allows_a_number_that_stays_in_the_ledger_layer():
    """★ 정상 설계를 벌하지 않는다 — reasoning_text 에만 있는 수치는 화면에 안 간다."""
    s = seqs(stage("S1", reasoning_text="지분 49.99% 를 확보했다",
                   observable_change="지분이 늘어난다"))
    assert ec.block_reasons(s) == []


def test_eq_v6_blocks_the_same_entity_repeating_the_same_state():
    """같은 화면이 두 번이면 진행이 아니다 — `_stage_of` 의 '앞보다 한 번 더'와 짝이다."""
    s = seqs(stage("S1"), stage("S2"))          # entity·observable_change 동일
    assert ec.block_reasons(s) == ["eq_v6_no_progression:S2"]


def test_eq_v6_allows_the_same_entity_with_real_progression():
    s = seqs(stage("S1"), stage("S2", observable_change="흐름이 앞보다 한 번 더 굵어진다"))
    assert ec.block_reasons(s) == []


# ── 경고: 어휘 판정 ───────────────────────────────────────────

def test_eq_v2_warns_when_an_estimate_loses_its_attribution():
    s = seqs(stage("S1", reasoning_text="애널리스트 추정 기준 매출이 늘어난다",
                   claim_ids=[]))
    assert "eq_v2_attribution_lost:S1" in ec.warnings(s)


def test_eq_v3_warns_when_a_forecast_is_not_on_the_code_layer():
    """전망은 코드가 그리는 층에 둬야 '이건 전망이다' 표시를 얹을 수 있다."""
    s = seqs(stage("S1", reasoning_text="2027년 매출 가이던스", precision_layer=""))
    assert "eq_v3_forecast_as_actual:S1" in ec.warnings(s)


def test_eq_v7_warns_when_a_metaphor_carries_a_factual_claim():
    s = seqs(stage("S1", observable_change="스노우볼처럼 불어난다", claim_ids=["F1"]))
    assert "eq_v7_metaphor_on_factual_claim:S1" in ec.warnings(s)


def test_eq_v7_allows_a_metaphor_with_no_claim_attached():
    """은유 자체는 금지가 아니다 — 사실 주장과 **한 화면에 섞이는 것**이 문제다."""
    s = seqs(stage("S1", observable_change="스노우볼처럼 불어난다", claim_ids=[]))
    assert not any(w.startswith("eq_v7") for w in ec.warnings(s))


# ── 설계 계약 ─────────────────────────────────────────────────

def test_vocabulary_checks_never_block():
    """★ 경계가 흐려지면 어휘 오탐이 승인을 막고, 게이트가 무시당하기 시작한다."""
    for code in ec.WARNING_REASONS:
        assert code not in ec.BLOCK_REASONS
    s = seqs(stage("S1", reasoning_text="애널리스트 추정", claim_ids=[],
                   precision_layer=""))
    assert ec.block_reasons(s) == []            # 어휘 위반만으로는 안 막힌다
    assert ec.warnings(s)                       # 경고로는 보인다


def test_eq_v5_is_held_by_structure_not_by_a_gate():
    """EQ-V5(사업 인과)는 stage 가 step 에서 1:1 로 나오는 구조가 막는다.

    ★ 검사해서 잡는 것이 아니라 **만들 수 없게** 한 것이다
      (docs/deviation-equity-visual-phase5.md). 그 1:1 이 유지되는지만 확인한다.
    """
    from engine import equity_visual

    # ★ unit_type 이 필요하다 — compile_unit 은 사업 기전 논증만 시퀀스로 만든다
    #   (밸류에이션·비교는 code viz 가 맞다, §6.2). 처음 픽스처가 이걸 빠뜨려
    #   None 이 나왔고 테스트가 잡았다.
    unit = {"reasoning_id": "R1", "unit_type": "DRIVER_CHAIN", "steps": [
        {"step": 1, "text": "수주가 늘었다", "fact_ids": ["F1"]},
        {"step": 2, "text": "매출이 늘었다", "fact_ids": ["F2"]}]}
    compiled = equity_visual.compile_unit(unit, 1)
    assert compiled is not None
    assert len(compiled["stages"]) == len(unit["steps"]), "단계가 생기거나 합쳐졌다"


def test_the_gates_reach_the_report_directive():
    """만들어 놓고 한쪽만 연결하지 않는다 — 이 저장소의 상습 실패다."""
    import inspect

    from engine import report_directive

    src = inspect.getsource(report_directive)
    assert "equity_contract.block_reasons(seqs)" in src
    assert "equity_contract.warnings(seqs)" in src
    assert 'd["header"]["approval_blocked"] = True' in src


def test_the_terms_live_in_config():
    import inspect

    from engine import config

    src = inspect.getsource(ec)
    for name in ("EQUITY_ESTIMATE_TERMS", "EQUITY_FORECAST_TERMS", "EQUITY_METAPHOR_TERMS"):
        assert f"config.{name}" in src
        assert len(getattr(config, name)) >= 5
