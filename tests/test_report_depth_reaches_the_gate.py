"""리포트의 원문 확보 수준이 **게이트까지 닿는가** (2026-09-23 라이브 실측).

무엇이 있었나
------------
#46 은 `visual_router.source_depth_of` 가 리포트 Fact Sheet 모양(`source_depth` 최상위)을
읽게 고쳤고, 저장된 지시서에 대고 재 보니 17 → 0 이었다. 그런데 **운영 경로는 그 함수에
닿지 않았다**: `report_directive._generate_once` 가 `normalize_directive` 에 Fact Sheet 를
안 넘기므로 정규화기 안에서는 `source_depth_of(None)` = "none" 이었다.

라이브 실행(리포트 e881669d, 원문 전문 11,911자)의 첫 시도가 그것을 보여 줬다:
    vseq_literal_without_source ×3
되먹임은 모델에게 "실제 장면을 그리지 마라"고 시켰고, 두 번째 시도는 도해로만 남았다.

★ Fact Sheet 전체를 넘기지 않는 이유: 그 인자는 Claim 대조·자기검증·숫자 감사 등 논문
  모양의 검사 6개를 함께 켠다. 리포트 Fact Sheet(`numbers`·`basis`)에 그것이 맞는지는
  아직 안 쟀다. 그래서 **깊이 하나만** 넘긴다 — 잰 뒤에 넓힌다.
"""

from __future__ import annotations

import copy

import pytest

from engine import report_directive as rd
from tests.test_directive_code_repairs import _with_sequences
from tests.test_photo_contract import _raw


def _literal_response():
    """모델이 두 stage 모두 '실제 장면'이라고 선언한 응답."""
    obj = _with_sequences(_raw("좋은 훅"))
    for st in obj["visual_sequences"][0]["stages"]:
        st["representation_mode"] = "LITERAL_OBSERVATION"
    return obj


def _row(depth):
    fs = {"source_depth": depth} if depth else {}
    return {"script_md": "문장 하나.", "fact_sheet": fs, "scenes": [], "financial_reasoning": None}


def _literal_blocks(out):
    return [r for r in (out["header"].get("block_reasons") or [])
            if r.startswith("vseq_literal_without_source")]


def test_full_text_reaches_the_gate_so_literal_scenes_are_allowed(monkeypatch):
    monkeypatch.setattr(rd, "call_json", lambda **kw: copy.deepcopy(_literal_response()))
    out = rd._generate_once(_row("full_text"), "photo", "user")
    assert _literal_blocks(out) == [], \
        "원문 전문이 있는데 실제 장면을 막으면 #46 이 운영 경로에 닿지 않은 것이다"


def test_no_source_still_blocks_literal_scenes(monkeypatch):
    """반대편 — 근거가 없으면 종전대로 막는다. 게이트가 통째로 풀린 것이 아니다."""
    monkeypatch.setattr(rd, "call_json", lambda **kw: copy.deepcopy(_literal_response()))
    out = rd._generate_once(_row(None), "photo", "user")
    assert len(_literal_blocks(out)) == 2, out["header"].get("block_reasons")


@pytest.mark.parametrize("depth", ["abstract_only", "parse_failed"])
def test_shallow_sources_still_block(monkeypatch, depth):
    monkeypatch.setattr(rd, "call_json", lambda **kw: copy.deepcopy(_literal_response()))
    out = rd._generate_once(_row(depth), "photo", "user")
    assert _literal_blocks(out), depth
