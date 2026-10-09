"""첫 질문만 다시 쓴다 — 나머지 대본은 건드리지 않는다 (2026-10-08 운영자 "첫 질문만 수정해봐. 괜히 손댔다가 나빠질까봐").

★ 나빠지지 않게 하는 장치 셋
  1. 대본 전체를 다시 쓰지 않는다 — 첫 장면 나레이션 후보 5개만 쓴다(짧은 호출 한 번).
  2. 지금 질문과 후보를 **같은 Jev 검사**(전문용어·답 노출·근거)로 잰다(docs/연구_Jev배치확대_2026-10-08.md §3).
  3. 모든 검사에서 지금 질문보다 나은 후보만 바꿀 자격이 있다. 하나도 없으면 지금 질문을 그대로 둔다.
     최종 선택은 사람이 한다 — 이 모듈은 후보와 점수를 보여 주기만 한다(저장하지 않는다).

★ 후킹 규칙의 근거: 운영 첫 질문 "뇌세포의 단 1%만 건드렸는데, 한밤중처럼 깊은 잠에 빠질 수 있을까요?"(전문용어 0.23·
  답 노출 0.20)는 **구체적 숫자로 놀라게 하고 답은 숨겼다.** V2 최종 "잠은 뇌 깊은 곳이 시킨다고요? 그런데 뇌 겉면의
  아주 적은 세포가 스스로 잠을 켠다면요?"(답 노출 0.72)는 결과를 미리 말했다. 업로드 제목 실측(2026-09-28)도 같은 방향 —
  수수께끼형("A인데 B?")이 설명형보다 잘 됐다.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from . import config, grounding
from .llm import call_json, set_text_purpose

HOOK_SYSTEM = """너는 과학 숏폼의 **첫 장면 한마디**만 다시 쓰는 작가다. 나머지 대본은 이미 확정됐다.
입력: Fact Sheet(사실 원천), 지금 첫 장면, 바로 다음 장면(첫 장면 뒤에 그대로 이어진다), 이 편의 질문.

[좋은 첫 장면]
- 일반 시청자가 1.5초 안에 "정말?" 하고 멈춘다. 구체적인 숫자·대비·역설로 놀라게 하라
  (예: "뇌세포의 단 1%만 건드렸는데, 한밤중처럼 깊은 잠에 빠질 수 있을까요?" — 숫자로 놀라게 하고 답은 숨겼다).
- **답(연구 결과·원리)은 숨겨라.** "~가 ~해서 ~한다고요?"처럼 결론을 질문 안에 다 말하지 마라. 궁금증만 남긴다.
- 전문용어 금지: 피질·뉴런·억제·축삭·델타파·세포 이름·약어를 쓰지 마라. 일상어만(뇌 겉면, 뇌세포, 잠, 스위치 …).
- 짧게: 한두 문장, 합쳐서 40자 안팎. 소리 내 읽기 쉽게, 숫자는 한 개까지.
- 다음 장면으로 자연스럽게 이어져야 한다(다음 장면 첫 문장과 같은 말을 반복하지 마라).

[사실 — 반드시 지켜라]
- 숫자·주장은 Fact Sheet 에 있는 것만. 범위를 넓히지 마라(쥐 → 사람, 피질 억제 뉴런의 1% → 뇌세포 전체의 1% 금지).
- 질문의 형태라도 사실을 단정하면 근거가 있어야 한다.

서로 다른 각도로 후보 **정확히 5개**. JSON only:
{"candidates":[{"text":"<첫 장면 나레이션>","angle":"<숫자 충격|역설|상식 충돌|일상 연결|미스터리>",
"fact_refs":["<기대는 Fact Sheet 항목 키, 예: numbers[0]>"]}]}"""


def user_prompt(fact_sheet: dict[str, Any], current: str, next_scene: str, core_question: str) -> str:
    return (f"Fact Sheet:\n{json.dumps(fact_sheet, ensure_ascii=False)}\n\n"
            f"이 편의 질문: {core_question}\n지금 첫 장면: {current}\n다음 장면(그대로 이어짐): {next_scene}")


def propose(fact_sheet: dict[str, Any], current: str, next_scene: str, core_question: str, *,
            caller: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """후보 5개(모델 1회). 형식이 틀린 후보는 버린다."""
    set_text_purpose("v2_hook_rewrite")
    raw = (caller or call_json)(model=config.MODEL_V2_HOOK, system=HOOK_SYSTEM,
                                user=user_prompt(fact_sheet, current, next_scene, core_question),
                                max_tokens=config.LLM_SELFCHECK_MAX_TOKENS)
    rows = raw.get("candidates") if isinstance(raw, dict) else None
    out = []
    for row in rows or []:
        text = str((row or {}).get("text") or "").strip() if isinstance(row, dict) else ""
        if text and text != current.strip():
            out.append({"text": text, "angle": str(row.get("angle") or ""),
                        "fact_refs": [str(x) for x in row.get("fact_refs") or []]})
    return out


def _source(fact_sheet: dict[str, Any]) -> str:
    src = fact_sheet.get("source") if isinstance(fact_sheet.get("source"), dict) else {}
    meta = " | ".join(f"{k}: {v if isinstance(v, str) else ', '.join(map(str, v))}"
                      for k, v in src.items() if v and k != "url")
    return f"SOURCE META: {meta}\nFACT SHEET:\n{grounding.facts_text(fact_sheet)}"


def score(texts: list[str], fact_sheet: dict[str, Any], *,
          hook_judge: Callable[[str], dict[str, float] | None] | None = None,
          fact_judge: Callable[[str, str], float | None] | None = None) -> list[dict[str, Any]]:
    """문장마다 {jargon, spoiler, unsupported}. Jev 가 답을 못 하면 그 값은 None(통과로 세지 않는다)."""
    from . import decide
    hook_judge = hook_judge or decide.hook_plainness
    fact_judge = fact_judge or decide.unsupported_claim_p
    source = _source(fact_sheet)
    out = []
    for text in texts:
        plain = hook_judge(text) or {}
        out.append({"text": text, "jargon": plain.get("jargon"), "spoiler": plain.get("spoiler"),
                    "unsupported": fact_judge(text, source)})
    return out


def _ok(row: dict[str, Any]) -> bool:
    return (all(row.get(k) is not None for k in ("jargon", "spoiler", "unsupported"))
            and row["jargon"] < config.V2_HOOK_JARGON_MIN and row["spoiler"] < config.V2_HOOK_SPOILER_MIN
            and row["unsupported"] < config.V2_JEV_UNSUPPORTED_MIN)


def choose(current: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """바꿀 자격: 세 검사 모두 문턱 안 + 지금 질문보다 어느 검사에서도 나쁘지 않고 하나는 확실히(0.1) 낫다.
    자격 있는 후보 중 답 노출+전문용어 합이 가장 낮은 것. 없으면 지금 질문(`changed`=False)."""
    def no_worse(c: dict[str, Any]) -> bool:
        return all(current.get(k) is None or c[k] <= current[k] + 0.05 for k in ("jargon", "spoiler", "unsupported"))

    def clearly_better(c: dict[str, Any]) -> bool:
        return any(current.get(k) is not None and c[k] <= current[k] - 0.1 for k in ("jargon", "spoiler"))

    eligible = [c for c in candidates if _ok(c) and no_worse(c) and clearly_better(c)]
    if not eligible:
        return {**current, "changed": False}
    best = min(eligible, key=lambda c: (c["spoiler"] + c["jargon"], c["unsupported"]))
    return {**best, "changed": True}
