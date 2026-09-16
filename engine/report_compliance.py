"""컴플라이언스 게이트 — 3층 방어 (명세 5-3, PF1 심장).

생성된 대본을 발행 전 자동 검사해 drafts.compliance 에 기록. **참고용 표시 전용**(사용자 요청으로 하드 차단 제거) →
대시보드에서 [승인] 잠금(하드블록). 사람이 대본을 고쳐 재검사 통과해야 발행 가능.

층 1 — 룰베이스 금지패턴 스캔(순수 정규식) : scan_rules
층 2 — LLM 심사관(2차 판정)                 : _llm_judge
층 3 — 자기검증 접합(근거 없는 문장 = 이중 플래그)

★ blocked 는 증거에서 재계산한다(selfcheck 의 all_grounded 재계산 패턴 — LLM boolean 불신).
★ 층1·compute_blocked 는 순수 함수 → 네트워크 없이 단위 테스트(tests/test_report_p1.py).
★ 이중관리 지점: supabase/functions/generate-report-draft 와 동기화.
"""

from __future__ import annotations

import re
from typing import Any

from . import config
from .llm import JSONParseError, call_json


def script_text(script: dict[str, Any]) -> str:
    """검사 대상 텍스트 = 대본 마크다운 + 모든 나레이션(ko)."""
    parts = [str(script.get("script_md") or "")]
    for s in script.get("scenes") or []:
        if isinstance(s, dict):
            parts.append(str(s.get("narration_ko") or ""))
    return "\n".join(parts)


def scan_rules(text: str, broker: str = "") -> list[dict[str, Any]]:
    """층 1 — 금지/경고 패턴 정규식 스캔 + 출처·면책 누락 검사. 순수 함수.

    반환: [{category, severity('block'|'warn'), hit}]. severity=block 이면 발행 차단 사유.
    """
    flags: list[dict[str, Any]] = []
    for category, patterns in config.COMPLIANCE_BLOCK_PATTERNS.items():
        for p in patterns:
            for m in re.finditer(p, text):
                flags.append({"category": category, "severity": "block", "hit": m.group(0)})
    for category, patterns in config.COMPLIANCE_WARN_PATTERNS.items():
        for p in patterns:
            for m in re.finditer(p, text):
                flags.append({"category": category, "severity": "warn", "hit": m.group(0)})
    # 출처 누락(필수): 증권사명이 알려졌는데 대본에 없으면 차단.
    if broker and broker not in text:
        flags.append({"category": "출처누락", "severity": "block", "hit": broker})
    # 면책 누락(필수): 면책 핵심 어구가 하나도 없으면 차단.
    if not any(marker in text for marker in config.COMPLIANCE_DISCLAIMER_MARKERS):
        flags.append({"category": "면책누락", "severity": "block", "hit": ""})
    return flags


_JUDGE_SYSTEM = """너는 자본시장법 컴플라이언스 심사관이다. 아래 숏폼 대본을 검사한다.
JSON only. 설명·마크다운·코드펜스 금지. 애매하면 위반(yes)으로 본다(보수적).
{
  "권유": "yes|no",        // 투자행동 권유(매수/매도/보유)가 있는가
  "수익률광고": "yes|no",  // 미실현 수익률·상승여력% 광고가 있는가
  "단정": "yes|no",        // 단정적 미래 예측이 있는가
  "출처": "ok|missing",    // 증권사 출처 귀속이 있는가
  "면책": "ok|missing",    // 엔딩 면책 문구가 있는가
  "근거": "<판정 근거 한두 문장>"
}"""


def _normalize_verdict(obj: dict[str, Any]) -> dict[str, Any]:
    def yn(v: Any) -> str:
        return "yes" if str(v).strip().lower() in ("yes", "y", "true", "1") else "no"

    def okmiss(v: Any) -> str:
        return "ok" if str(v).strip().lower() in ("ok", "yes", "true", "1") else "missing"

    return {
        "권유": yn(obj.get("권유")),
        "수익률광고": yn(obj.get("수익률광고")),
        "단정": yn(obj.get("단정")),
        "출처": okmiss(obj.get("출처")),
        "면책": okmiss(obj.get("면책")),
        "근거": str(obj.get("근거") or ""),
    }


def _llm_judge(text: str) -> dict[str, Any]:
    """층 2 — LLM 심사관. 실패 시 보수적으로 전부 위반 처리(안전측)."""
    try:
        obj = call_json(model=config.MODEL_REPORT_COMPLIANCE, system=_JUDGE_SYSTEM,
                        user=text, max_tokens=1024)
        return _normalize_verdict(obj)
    except (JSONParseError, Exception):  # noqa: BLE001 — 심사 실패 = 통과시키지 않는다(보수적 차단)
        return {"권유": "yes", "수익률광고": "yes", "단정": "yes",
                "출처": "missing", "면책": "missing", "근거": "[심사관 호출 실패 — 보수적 차단]"}


def check(fact_sheet: dict[str, Any], script: dict[str, Any],
          self_check: dict[str, Any], broker: str = "") -> dict[str, Any]:
    """3층 검토 실행 → drafts.compliance 값. **참고용 표시 전용** — 승인은 잠그지 않는다.

    규칙 스캔·LLM 심사·자기검증 결과를 패널에 보여주되(사람이 참고), 흐름을 막지 않는다.
    (하드 차단은 사용자 요청으로 제거 — blocked 는 항상 False.)
    """
    text = script_text(script)
    rule_flags = scan_rules(text, broker)
    verdict = _llm_judge(text)
    # 층 3 — 자기검증 접합: 근거 없는 씬을 참고 표시(후크/페이오프 등 수사적 문장 포함 가능).
    hallucination_flags = [
        {"scene": s.get("scene"), "unsupported": s.get("unsupported")}
        for s in (self_check.get("scenes") or [])
        if not s.get("grounded")
    ]
    return {
        "rule_flags": rule_flags,
        "llm_verdict": verdict,
        "hallucination_flags": hallucination_flags,
        "blocked": False,   # 하드 차단 제거 — 참고용 플래그만 남김
    }
