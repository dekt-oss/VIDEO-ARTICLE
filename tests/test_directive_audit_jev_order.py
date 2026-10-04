"""근거 대조(directive_audit) ↔ Jev 기록(jev_trace) 블록이 서로를 전제하지 않는다.

#76 이 `if jev_calls:` 를 근거 대조 블록 **한가운데** 끼워 넣어 두 결함이 생겼다.
  ① DIRECTIVE_AUDIT_ENABLED=False 인데 Jev 가 돌면 `audit` 이 정의되지 않아 NameError —
     지시서 생성(논문·리포트 공용 normalize_directive)이 통째로 죽는다.
  ② Jev 가 꺼져 있거나 판정이 한 번도 안 나가면 근거 대조 발견이 mode_warnings
     (경고 분류의 정본 표면)에 안 올라간다 — 빨강 숫자가 화면 요약에서 조용히 사라진다.
LLM·네트워크·DB 호출 없음 — Jev 는 가짜 전송, 근거 대조는 고정 결과로 바꾼다.
"""

from __future__ import annotations

from engine import config, directive, directive_audit
from engine.directive import normalize_directive
from tests.test_jev_monitor import _fake_post, _on
from tests.test_photo_contract import _good_directive

_FINDING = {"level": "red", "code": "number_not_in_source", "cut_no": 2, "detail": "x"}


def _fixed_audit(monkeypatch):
    monkeypatch.setattr(directive_audit, "audit", lambda *a, **k: {
        "findings": [dict(_FINDING)], "stats": {"cuts": 0, "red": 1, "yellow": 0}})
    monkeypatch.setattr(directive, "_release_restated_numbers", lambda *a, **k: None)


def _run():
    header, cuts = _good_directive()
    return normalize_directive({"header": header, "cuts": cuts}, "photo")["header"]


def test_audit_off_with_jev_on_still_writes_the_directive(monkeypatch):
    monkeypatch.setattr(config, "DIRECTIVE_AUDIT_ENABLED", False)
    _on(monkeypatch, _fake_post(lambda k, s: 0.5))
    h = _run()
    assert h["jev_trace"]["stats"]["calls"] > 0, "전제: Jev 판정이 실제로 나갔다"
    assert "directive_audit" not in h
    assert not any(w.startswith("audit_") for w in h["mode_warnings"])


def test_audit_findings_reach_warnings_even_when_jev_is_off(monkeypatch):
    _fixed_audit(monkeypatch)
    h = _run()
    assert "jev_trace" not in h, "전제: Jev 판정이 하나도 안 나갔다"
    assert "audit_number_not_in_source:2" in h["mode_warnings"]


def test_audit_findings_reach_warnings_when_jev_is_on(monkeypatch):
    _fixed_audit(monkeypatch)
    _on(monkeypatch, _fake_post(lambda k, s: 0.5))
    h = _run()
    assert h["jev_trace"]["stats"]["calls"] > 0
    assert "audit_number_not_in_source:2" in h["mode_warnings"]
