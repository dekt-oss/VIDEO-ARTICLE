"""4차 렌더(2026-09-24)에서 남은 둘 — 원인이 화면에 없다 · 부품이 정체불명이다.

    ① "막힌 육상 부지를 벗어나 바다 위에" 를 한 stage 에 적자 결과(바다 위 바지선)만 남았다.
       → 원인 stage 와 결과 stage 를 나눈다(화면 구성 계약 ⑨). 두 공장 공용 문자열이라 둘 다 받는다.
    ② "seawater cooling channels" 가 황금색 코일 덩어리로 그려졌다.
       → 도해 부품이 알아볼 물건인지 판정 모델이 되묻는다(경고, 되묻기). 차단이 아니다 —
         Jev 가 틀리거나 죽어도 승인은 안 막힌다(경고는 fail-open).
"""

from __future__ import annotations

from engine import config, decide, directive as dv, photo_contract as pc, report_directive as rd
from tests.test_directive_code_repairs import _with_sequences
from tests.test_photo_contract import _raw


def test_the_cause_effect_rule_reaches_both_factories():
    assert "두 stage 로 나눠라" in dv.STAGING_CONTRACT
    paper = dv.directive_user_prompt({"script_md": "문장.", "fact_sheet": {}, "scenes": []}, "photo")
    report = rd.report_directive_user_prompt(
        {"script_md": "문장.", "fact_sheet": {}, "scenes": [], "financial_reasoning": None}, "photo")
    for prompt in (paper, report):
        assert "원인 stage" in prompt and "결과 stage" in prompt
        assert "photo_component_unrecognizable" in prompt


def _mech_directive():
    raw = _with_sequences(_raw("좋은 훅"))
    return {"visual_sequences": raw["visual_sequences"], "hook_ko": "좋은 훅"}, raw["cuts"]


def test_abstract_components_are_warned_when_the_judge_says_so(monkeypatch):
    header, cuts = _mech_directive()
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "components_recognizable", lambda _c: 0.1)
    got = pc.evaluate(header, cuts, None)
    assert any(w.startswith("photo_component_unrecognizable") for w in got["warnings"]), got["warnings"]
    assert not any(b.startswith("photo_component_unrecognizable") for b in got["block_reasons"]), \
        "경고이지 차단이 아니다"


def test_recognizable_components_are_left_alone(monkeypatch):
    header, cuts = _mech_directive()
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "components_recognizable", lambda _c: 0.9)
    got = pc.evaluate(header, cuts, None)
    assert not any(w.startswith("photo_component_unrecognizable") for w in got["warnings"])


def test_a_dead_judge_means_no_warning_not_a_false_warning(monkeypatch):
    """경고는 fail-open — 못 물으면 종전 동작이다."""
    header, cuts = _mech_directive()
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "components_recognizable", lambda _c: None)
    got = pc.evaluate(header, cuts, None)
    assert not any(w.startswith("photo_component_unrecognizable") for w in got["warnings"])


def test_the_judge_is_not_called_when_off():
    """conftest 가 decide.enabled 를 막는다 — 테스트·로컬은 네트워크 0."""
    header, cuts = _mech_directive()
    got = pc.evaluate(header, cuts, None)
    assert not any(w.startswith("photo_component_unrecognizable") for w in got["warnings"])


def test_the_same_component_list_is_asked_once(monkeypatch):
    header, cuts = _mech_directive()
    for c in cuts:
        if str(c.get("visual_role") or "").upper() == "MECHANISM":
            c["mechanism"]["components"] = ["a cooling channel", "a coupling block"]
    calls = []
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "components_recognizable", lambda c: calls.append(tuple(c)) or 0.1)
    pc.evaluate(header, cuts, None)
    assert len(calls) == 1, calls


def test_the_warning_is_retryable_and_has_a_prescription():
    assert "photo_component_unrecognizable" in config.RETRYABLE_QUALITY_WARNINGS
    assert "photo_component_unrecognizable" in pc.WARNING_REASONS
    fix = pc.feedback_prompt([], ["photo_component_unrecognizable:6"])
    assert "한눈에 알아볼" in fix and "components" in fix


def test_components_recognizable_asks_with_the_items_in_the_state(monkeypatch):
    seen = {}
    monkeypatch.setattr(decide, "noul", lambda state, q, crit: (seen.setdefault("state", state), 0.8)[1])
    assert decide.components_recognizable(["a barge", "a server rack"]) == 0.8
    assert "a barge" in seen["state"] and "a server rack" in seen["state"]
    assert decide.components_recognizable([]) is None
