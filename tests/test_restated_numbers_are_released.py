"""숫자 감사의 빨강 중 '원장 수치를 단위·표기만 바꿔 쓴 것'은 노랑으로 내린다 (2026-09-27).

감사(directive_audit)는 문자열 대조라 '631억 원' 과 영문 '63.1 billion' 을 다른 숫자로 본다.
실측(scripts/number_restated_shadow.py, 빨강 45건): p≥0.8 21건이 전부 환산·반올림이었다
(631억↔63.1 · 7조 6천억↔7.6 · +18.50%↔18.5% · 500만 노출↔nearly 5 million impressions).

★ 내리기만 한다. 판정 모델이 죽거나 "아니다"면 빨강 그대로 — 새로 막는 것은 없다.
★ 감사 모듈 자체는 LLM 없이 도는 순수 검사로 남는다.
"""

from __future__ import annotations

import inspect

from engine import config, decide, directive as dv, directive_audit

_FS = {"what": ["현대글로비스 2Q 631억원 추가 출자"]}


def _audit_with_red():
    cuts = [{"cut_no": 3, "narration_ko": "631억 원을 출자했습니다.",
             "narration_en": "Hyundai Glovis invested 63.1 billion won."}]
    header = {"hook_ko": ""}
    audit = directive_audit.audit(header, cuts, _FS)
    reds = [f for f in audit["findings"] if f["level"] == "red"]
    assert reds and reds[0]["number"] == "63.1", audit["findings"]
    return audit, header, cuts


def test_a_unit_conversion_is_released_to_yellow(monkeypatch):
    audit, header, cuts = _audit_with_red()
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "number_restated", lambda n, s, f: 0.97)
    dv._release_restated_numbers(audit, header, cuts, _FS)
    f = [x for x in audit["findings"] if x.get("number") == "63.1"][0]
    assert (f["level"], f["code"]) == ("yellow", "number_restated_from_source")
    assert audit["stats"]["red"] == 0 and audit["stats"]["yellow"] >= 1


def test_below_the_bar_stays_red(monkeypatch):
    audit, header, cuts = _audit_with_red()
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "number_restated", lambda n, s, f: config.JEV_NUMBER_RESTATED_MIN - 0.01)
    dv._release_restated_numbers(audit, header, cuts, _FS)
    assert audit["stats"]["red"] >= 1


def test_a_dead_judge_leaves_red_alone(monkeypatch):
    audit, header, cuts = _audit_with_red()
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "number_restated", lambda n, s, f: None)
    dv._release_restated_numbers(audit, header, cuts, _FS)
    assert audit["stats"]["red"] >= 1


def test_overlay_text_is_shown_to_the_judge(monkeypatch):
    """카드에만 나온 숫자('500만 노출')를 나레이션만 보여 주고 묻지 않는다."""
    cuts = [{"cut_no": 10, "narration_ko": "광고를 집행했더니", "narration_en": "",
             "overlay_plan": [{"type": "number_punch", "text": "500만 노출"}]}]
    fs = {"what": ["nearly 5 million impressions"]}
    audit = directive_audit.audit({"hook_ko": ""}, cuts, fs)
    seen = []
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "number_restated", lambda n, s, f: seen.append(s) or 0.9)
    dv._release_restated_numbers(audit, {"hook_ko": ""}, cuts, fs)
    assert seen and "500만 노출" in seen[0]


def test_the_audit_module_itself_stays_llm_free():
    assert "decide" not in inspect.getsource(directive_audit)
