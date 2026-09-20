"""리포트 지시서도 지시서 상한을 쓴다 (2026-09-20).

무엇이 문제였나: `report_directive._generate_once` 가 `LLM_SCRIPT_MAX_TOKENS`(16,384)를
썼다. **대본용 상한**이다. 그런데 이 호출이 만드는 것은 대본이 아니라 논문과 같은 종류의
**지시서**이고, 논문 쪽은 `LLM_DIRECTIVE_MAX_TOKENS`(49,152)를 쓴다. 같은 산출물에 상한이
3배 다른 것은 설계가 아니라 빠진 자리다.

★ 상한은 **안전장치이지 비용 조절 수단이 아니다** — 출력은 쓴 만큼만 과금된다. 낮게 잡아
  얻는 것은 없고, 잃는 것은 절단이다. 절단은 재시도가 소용없는 하드 에러라 라인이 선다.

★ 실측 근거(2026-09-19 DeepSeek 배선): 같은 프롬프트에서 출력량이 백엔드마다 2배 넘게 다르다.
    gemini-2.5-pro   12.6K~13.1K
    deepseek-v4-pro  28.4K~30.9K   ← 16,384 상한이면 확실히 절단
    deepseek-flash   32,768 ×3     ← 상한을 정확히 채워 3/3 실패
  이 한 줄이 없으면 리포트 지시서 모델 A/B 자체가 불가능하다.
"""

from __future__ import annotations

import pathlib

from engine import config

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"


def test_the_report_directive_uses_the_directive_ceiling_not_the_script_one():
    src = (ENGINE / "report_directive.py").read_text(encoding="utf-8")
    assert "max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS" in src
    assert "max_tokens=config.LLM_SCRIPT_MAX_TOKENS" not in src


def test_both_factories_ask_for_the_same_room():
    """두 공장이 같은 종류의 산출물을 만든다 — 상한이 갈리면 한쪽만 절단된다."""
    paper = (ENGINE / "directive.py").read_text(encoding="utf-8")
    report = (ENGINE / "report_directive.py").read_text(encoding="utf-8")
    assert "max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS" in paper
    assert "max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS" in report


def test_the_ceiling_leaves_room_for_the_measured_worst_case():
    """deepseek-v4-pro 실측 최대 30,928 토큰. 상한이 그보다 낮으면 바꾸는 순간 선다."""
    assert config.LLM_DIRECTIVE_MAX_TOKENS >= 40960, config.LLM_DIRECTIVE_MAX_TOKENS


def test_the_ab_harness_can_measure_this_path():
    """config.MODEL_REPORT_DIRECTIVE 주석이 "바꾸려면 model_ab 로 먼저 재라"고 적어 뒀다 —
    그 말이 참이려면 하네스에 그 자리가 있어야 한다."""
    src = (ENGINE.parent / "scripts" / "model_ab.py").read_text(encoding="utf-8")
    assert '"report_directive"' in src
    assert "_generate_report(" in src and "_score_report(" in src
    # 논문과 **같은 채점기** 위에 리포트 전용 계약만 더한다 — 두 자리를 같은 눈으로 읽는다.
    assert "sc = _score(run)" in src
    assert "equity_contract.block_reasons" in src
