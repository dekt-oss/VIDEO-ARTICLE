"""출력 상한은 config 에 있고, 제일 말이 긴 공급자에 맞춘다 (2026-09-22).

무엇이 문제였나. 상한 둘이 코드에 박혀 있었다 — `scriptgen.py` 의 8192, `selfcheck.py` 의
6144. 그리고 Fact Sheet 는 **원문이 있을 때만** 제 상한을 쓰고 없으면 기본 8,192 로
떨어졌다. 셋 다 `gemini-2.5-flash` 의 씀씀이에 맞춰져 있었다.

★★ 그래서 **DeepSeek 을 두 번 잘못 판정했다.** 원장에 그 순간이 그대로 남아 있다:

    지시서     deepseek-flash  출력 32,768 · 32,768 · 32,768   ← 상한 정각, 3/3
    Fact Sheet deepseek-flash  출력  8,192                      ← 상한 정각

그때 "deepseek-flash 는 절단으로 죽고 claim_id 를 빠뜨린다"고 적었다. 빠뜨린 게 아니라
**말을 하다 끊긴** 것이다. 공급자를 우리 천장으로 떨어뜨려 놓고 그 모델이 못한다고 적으면
측정이 거짓말을 한다.

★ 상한은 **안전장치이지 비용 조절 수단이 아니다** — 출력은 쓴 만큼만 과금된다. 낮게 잡아
  얻는 것은 없고, 잃는 것은 절단이다. 절단은 재시도가 소용없는 하드 에러다.

★ 값의 근거(원장 실측): 제미나이 실측 최대 × 딥시크 배수 2.4 × 여유.
    논문 대본   5,955(옛 상한의 73%) × 2.4 ≈ 14,300 → 32,768
    자기검증    3,016(49%)           × 2.4 ≈  7,240 → 16,384
"""

from __future__ import annotations

import pathlib
import re

from engine import config

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"

# 이 파일들에서 `max_tokens=<숫자>` 는 금지다 — config 상수를 가리켜야 한다.
_CALLERS = ("scriptgen.py", "selfcheck.py", "factsheet.py", "report_factsheet.py",
            "report_scriptgen.py", "directive.py", "report_directive.py")
_LITERAL = re.compile(r"max_tokens\s*=\s*\d+")


def test_no_output_ceiling_is_hardcoded_in_a_caller():
    """코드에 박히면 env 로 못 바꾸고, 왜 그 값인지도 안 남는다."""
    bad = []
    for name in _CALLERS:
        src = (ENGINE / name).read_text(encoding="utf-8")
        for line in src.splitlines():
            if line.lstrip().startswith("#"):
                continue          # 주석 속 설명은 괜찮다
            if _LITERAL.search(line):
                bad.append(f"{name}: {line.strip()}")
    assert not bad, "출력 상한이 코드에 박혀 있다(config 로 빼라):\n  " + "\n  ".join(bad)


def test_the_factsheet_ceiling_does_not_depend_on_whether_a_source_was_attached():
    """★ 출력 크기를 정하는 것은 **입력에 원문이 있느냐**가 아니라 **모델이 얼마나 길게
    쓰느냐**다. 조건을 걸어 두면 초록만 있는 논문에서 기본 8,192 로 떨어지고, 말이 긴
    공급자가 거기서 잘린다(deepseek-flash 실측 8,192 정각)."""
    src = (ENGINE / "factsheet.py").read_text(encoding="utf-8")
    assert "max_tokens=config.LLM_FACTSHEET_MAX_TOKENS," in src
    assert 'if (packet or {}).get("text") else None' not in src


def test_every_ceiling_leaves_room_for_the_most_verbose_provider():
    """실측: 같은 일에 딥시크가 제미나이의 2.4배를 쓴다. 제미나이 최대에 그 배수를 곱해도
    상한 안이어야 한다 — 아니면 그 공급자를 붙이는 순간 잘린다."""
    VERBOSE = 2.4      # 지시서 실측: 제미나이 12,738 → 딥시크 30,085
    measured_gemini_max = {           # 원장 실측 (generation_attempts)
        config.LLM_PAPER_SCRIPT_MAX_TOKENS: 5_955,    # 논문 대본
        config.LLM_SELFCHECK_MAX_TOKENS: 3_016,       # 자기검증
        config.LLM_FACTSHEET_MAX_TOKENS: 5_291,       # Fact Sheet
        config.LLM_DIRECTIVE_MAX_TOKENS: 18_167,      # 지시서
    }
    for cap, gem_max in measured_gemini_max.items():
        assert cap >= gem_max * VERBOSE, (
            f"상한 {cap:,} < 제미나이 최대 {gem_max:,} × {VERBOSE} "
            f"= {gem_max * VERBOSE:,.0f} — 말이 긴 공급자가 잘린다")


def test_the_ceilings_are_env_overridable():
    """운영 중에 잘리면 배포 없이 올릴 수 있어야 한다."""
    src = (ENGINE / "config.py").read_text(encoding="utf-8")
    for name in ("LLM_PAPER_SCRIPT_MAX_TOKENS", "LLM_SELFCHECK_MAX_TOKENS",
                 "LLM_FACTSHEET_MAX_TOKENS", "LLM_DIRECTIVE_MAX_TOKENS"):
        assert f'_get_int("{name}"' in src, name


def test_the_default_ceiling_is_not_what_the_long_stages_fall_back_to():
    """`LLM_MAX_TOKENS`(8,192)는 짧은 호출용 기본값이다. 대본·검증·추출이 여기로
    떨어지면 그 순간 제일 말 긴 공급자가 죽는다."""
    assert config.LLM_MAX_TOKENS == 8192
    for cap in (config.LLM_PAPER_SCRIPT_MAX_TOKENS, config.LLM_SELFCHECK_MAX_TOKENS,
                config.LLM_FACTSHEET_MAX_TOKENS):
        assert cap > config.LLM_MAX_TOKENS
