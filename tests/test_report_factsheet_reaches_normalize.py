"""리포트 지시서 정규화에 Fact Sheet **전체**가 닿는가 (2026-09-25 그림자 측정 뒤).

무엇이 있었나
------------
#52 는 깊이 하나만 넘겼다(`source_depth=`). 그래서 정규화기 안의 숫자 감사는 **빈 원장**에
대고 돌았고, 리포트 지시서의 수치는 전부 "Fact Sheet 에 없다"(빨강)였다 — 저장 지시서 39건에서
378건. 오버레이 연도 대조도 꺼져 있어, 2026-09 리포트에 모델이 지어 붙인 출처 카드
"SK증권 리포트 (2024)" 가 통과했다(지시서 620e66be 컷2).

scripts/report_factsheet_shadow.py 로 두 방식을 같은 저장본에 대 봤다:
    빨강 숫자 경고 378 → 28 · 새 차단 1건(위 연도, 진짜 결함) · 사라진 차단 0
리포트 Fact Sheet 에는 claims 가 없어 Claim 대조·자기검증·역할 라벨 검사는 스스로 꺼진다.
"""

from __future__ import annotations

import copy

from engine import directive_audit, report_directive as rd, selfcheck
from tests.test_directive_code_repairs import _with_sequences
from tests.test_photo_contract import _raw

_FS = {
    "source_depth": "full_text",
    "what": ["조선 3사의 합산 영업이익은 '28E 13.7조원으로 과거 고점의 약 2배가 예상된다.",
             "SK증권 리포트 2026.09"],
    "number_facts": [{"metric": "목표주가", "value": 9000.0, "unit": "원"}],
}


def _row(fs=_FS):
    return {"script_md": "문장 하나.", "fact_sheet": copy.deepcopy(fs), "scenes": [],
            "financial_reasoning": None}


def _response(narration: str, overlay: str | None = None):
    obj = _with_sequences(_raw("좋은 훅"))
    obj["cuts"][1]["narration_ko"] = narration
    obj["cuts"][1]["narration_en"] = ""
    if overlay is not None:
        obj["cuts"][1]["overlay_plan"] = [{"type": "source_card", "text": overlay}]
    return obj


def _run(monkeypatch, obj, fs=_FS):
    monkeypatch.setattr(rd, "call_json", lambda **kw: copy.deepcopy(obj))
    return rd._generate_once(_row(fs), "photo", "user")["header"]


def _red(header, cut_no):
    return [f for f in (header.get("directive_audit") or {}).get("findings", [])
            if f["cut_no"] == cut_no and f["code"] == "number_not_in_source"]


# ── 숫자 감사가 원장을 본다 ─────────────────────────────────────────
def test_a_number_the_fact_sheet_pays_for_is_not_red(monkeypatch):
    cut_no = _response("x")["cuts"][1]["cut_no"]
    h = _run(monkeypatch, _response("3사 영업이익은 13.7조원으로 예상됩니다."))
    assert _red(h, cut_no) == [], "원장에 있는 수치를 빨강으로 부르면 Fact Sheet 가 안 닿은 것이다"


def test_a_made_up_number_is_still_red(monkeypatch):
    """반대편 — 감사가 꺼진 것이 아니다."""
    cut_no = _response("x")["cuts"][1]["cut_no"]
    h = _run(monkeypatch, _response("영업이익은 42.9조원으로 예상됩니다."))
    assert _red(h, cut_no), h.get("directive_audit")


def test_numeric_values_in_number_facts_count_as_paid():
    """리포트 원장은 수치를 float 로 둔다 — 영문 나레이션 '9,000' 이 거기서 지불된다."""
    nums = directive_audit.source_numbers({"number_facts": [
        {"value": 9000.0}, {"value": 7.6}, {"value": 3}, {"flag": True}]})
    assert {"9000", "7.6", "3"} <= nums
    assert "1" not in nums and "True" not in nums, "bool 은 숫자가 아니다"


# ── 오버레이 연도 대조가 켜진다 ─────────────────────────────────────
def test_a_made_up_year_on_a_source_card_blocks(monkeypatch):
    """★ 실측 그 자리: 2026-09 리포트인데 카드가 (2024)."""
    h = _run(monkeypatch, _response("SK증권 리포트입니다.", "SK증권 리포트 (2024)"))
    assert any(b.startswith("photo_overlay_year_unverified") for b in h["block_reasons"]), \
        h["block_reasons"]


def test_the_real_year_on_a_source_card_passes(monkeypatch):
    h = _run(monkeypatch, _response("SK증권 리포트입니다.", "SK증권 리포트 (2026.09)"))
    assert not any(b.startswith("photo_overlay_year_unverified") for b in h["block_reasons"])


# ── 논문 모양 검사는 리포트 모양에서 스스로 꺼진다 ─────────────────────
def test_claim_gates_stay_off_for_the_report_shape(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("claims 가 없는 원장에 자기검증(LLM)을 부르면 안 된다")
    monkeypatch.setattr(selfcheck, "check", boom)
    h = _run(monkeypatch, _response("3사 영업이익은 13.7조원으로 예상됩니다."))
    codes = {w.split(":", 1)[0] for w in [*h["mode_warnings"], *h["block_reasons"]]}
    assert not codes & {"claim_evidence_not_run", "directive_selfcheck_failed",
                        "directive_ungrounded", "cut_claim_not_in_source",
                        "missing_required_claims"}, codes
