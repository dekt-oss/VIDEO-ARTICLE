"""수정지시서 v2 순수 로직 테스트 — 지시서 훅 필드(①) · 제작 루브릭(②) · 렌더 QA(③).

네트워크·DB·LLM 없이 순수 함수만 검증한다.
"""

from engine import config
from engine.directive import (
    bold_hook_gate_violation,
    normalize_directive,
    normalize_hook_promise_check,
    normalize_science_reliability,
)
from engine.render_qa import evaluate_qa
from engine.scoring import parse_axes, parse_production, production_gate


# ── ① 지시서 훅·리텐션 필드 ──
def _directive(**header):
    return {"header": header, "cuts": [{"cut_no": 1, "narration_ko": "a", "source_facts": ["numbers[0]"]}]}


def test_directive_hook_enums_and_fallback():
    h = normalize_directive(_directive(
        hook_type="H2", hook_reframe_angle="competition", cta_type="next_episode_bridge",
        loop_match=True, series_id="C"), "comic")["header"]
    assert h["hook_type"] == "H2"
    assert h["hook_reframe_angle"] == "competition"
    assert h["cta_type"] == "next_episode_bridge"
    assert h["loop_match"] is True
    assert h["series_id"] == "C"
    # enum 밖 값 → 기본값 폴백
    bad = normalize_directive(_directive(hook_type="ZZ", hook_reframe_angle="bogus", cta_type="nope"), "comic")["header"]
    assert bad["hook_type"] == config.DEFAULT_HOOK_TYPE
    assert bad["hook_reframe_angle"] == config.DEFAULT_HOOK_ANGLE
    assert bad["cta_type"] == config.DEFAULT_CTA_TYPE


def test_hook_promise_check_payoff_parsing():
    pc = normalize_hook_promise_check({"pass": True, "promise": "x", "payoff_cut_no": ["3", 4, "bad"], "reason": "r"})
    assert pc["pass"] is True
    assert pc["payoff_cut_no"] == [3, 4]  # 문자열 int 변환 + 비정수 드롭
    assert normalize_hook_promise_check(None)["payoff_cut_no"] == []


def test_science_reliability_enum_enforced():
    sr = normalize_science_reliability({"claim_type": "measured_result", "evidence_strength": "high",
                                        "generalization_risk": "low", "required_caveat": "c"})
    assert sr["claim_type"] == "measured_result" and sr["evidence_strength"] == "high"
    bad = normalize_science_reliability({"evidence_strength": "??"})
    assert bad["evidence_strength"] == config.DEFAULT_EVIDENCE_STRENGTH


def test_bold_hook_gate():
    # H2 + high/low → 통과(위반 아님)
    ok = normalize_directive(_directive(hook_type="H2",
        science_reliability={"evidence_strength": "high", "generalization_risk": "low"}), "comic")["header"]
    assert bold_hook_gate_violation(ok) is False
    # H1 + 근거 약함 → 위반
    bad = normalize_directive(_directive(hook_type="H1",
        science_reliability={"evidence_strength": "low", "generalization_risk": "high"}), "comic")["header"]
    assert bold_hook_gate_violation(bad) is True
    # H3(대담 아님) → 게이트 무관
    mild = normalize_directive(_directive(hook_type="H3",
        science_reliability={"evidence_strength": "low", "generalization_risk": "high"}), "comic")["header"]
    assert bold_hook_gate_violation(mild) is False


# ── ② 제작 준비도 루브릭 ──
# ★★ 2026-09-04 에 축이 5개 → 6개가 됐다(mechanism 추가, 만점 10 → 12). 게이트 눈금도
#   같은 비율로 옮겼다(8/6/4 → 10/7/5). 아래 경계값은 **새 자에 맞춘 것**이고, 검사하는
#   성질은 그대로다: 등급이 총점에 대해 단조롭고, 경계에서 정확히 갈린다.
def test_production_gate_thresholds():
    # 만점 12 기준: make ≥9.6 / redesign ≥7.2 / backlog ≥4.8
    assert [production_gate(t) for t in (12, 10, 9, 8, 7, 5, 4, 0)] == [
        "make", "make", "redesign", "redesign", "backlog", "backlog", "hold", "hold"]
    # ★ 옛 5축 행(만점 10)은 옛 등급을 그대로 유지한다.
    assert [production_gate(t, 10) for t in (10, 8, 7, 6, 5, 4, 3)] == [
        "make", "make", "redesign", "redesign", "backlog", "backlog", "hold"]


def test_parse_production_total_and_clamp():
    p = parse_production({
        "novelty": {"score": 2, "why": "a"}, "audience_value": {"score": 2, "why": "b"},
        "hook_fit": {"score": 1, "why": "c"}, "explain_60s": {"score": 2, "why": "d"},
        "visualizable": {"score": 9, "why": "e"},          # 9 → clamp 2
        "mechanism": {"score": 2, "why": "f"}})
    assert p["axes"]["visualizable"]["score"] == 2
    assert p["total"] == 2 + 2 + 1 + 2 + 2 + 2  # = 11
    assert p["gate"] == "make"
    # ★ 빠진 축은 0 으로 센다 — 옛 채점 행(mechanism 없음)이 그대로 읽혀도 죽지 않는다.
    #   다만 총점이 그만큼 낮게 나오므로 **재채점 전까지는 등급이 보수적**이다.
    legacy = parse_production({
        "novelty": {"score": 2, "why": "a"}, "audience_value": {"score": 2, "why": "b"},
        "hook_fit": {"score": 2, "why": "c"}, "explain_60s": {"score": 2, "why": "d"},
        "visualizable": {"score": 2, "why": "e"}})
    assert legacy["total"] == 10 and legacy["axes"]["mechanism"]["score"] == 0
    empty = parse_production(None)
    assert empty["total"] == 0 and empty["gate"] == "hold"


def test_parse_axes_includes_production():
    axes = parse_axes({"surprise": 8, "production": {"novelty": {"score": 2}}})
    assert "production" in axes and axes["production"]["axes"]["novelty"]["score"] == 2


# ── ③ 렌더 QA ──
def test_render_qa_clean_passes():
    r = evaluate_qa({"duration_sec": 52, "has_audio": True, "frame_decodable": True,
                     "max_silence_ms": 120, "end_black_sec": 0.1, "audio_peak_db": -1.2})
    assert r["passed"] is True and not r["hard_fail"] and not r["warnings"]


def test_render_qa_hard_fails_and_warnings():
    r = evaluate_qa({"duration_sec": 8, "has_audio": False, "frame_decodable": True,
                     "max_silence_ms": 600, "end_black_sec": 1.5, "audio_peak_db": 0.4})
    assert r["passed"] is False
    assert any("길이" in x for x in r["hard_fail"])
    assert any("오디오 트랙 없음" == x for x in r["hard_fail"])
    assert any("끝 검은" in x for x in r["hard_fail"])
    assert any("무음" in x for x in r["warnings"])
    assert any("피크" in x for x in r["warnings"])
