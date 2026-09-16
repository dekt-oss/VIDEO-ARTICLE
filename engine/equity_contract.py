"""EQ-V 계약 — 리포트(주식) 라인의 시각 시퀀스 게이트 (작업지시서 §11, 2026-09-02).

무엇이 비어 있었나
------------------
논문 라인에는 차단 게이트가 26개 있는데 **리포트 라인에는 하나도 없었다.**
`equity_visual` 은 컴파일·변환·화면 투영까지 하고 판정 계열 함수는 `screen_warnings`
하나뿐이었다 — 이름 그대로 **경고만** 낸다. 같은 엔진의 두 라인이 비대칭이었다.

무엇을 차단하고 무엇을 경고하나
-------------------------------
★★ **구조 판정은 차단, 어휘 판정은 경고.** 이 저장소가 반복해 배운 것이다 —
  어휘 목록은 유한하고 오탐이 크다. 코드가 직접 만든 데이터의 모양을 보는 검사
  (연결이 있는가·수치가 화면 계약에 실렸는가·상태가 진행하는가)는 오탐이 없으므로
  차단한다. 리포트 **문장**을 어휘로 읽는 검사는 경고로 두고 오탐률을 보고 올린다.

  차단  EQ-V1 논증 연결 · EQ-V4 수치 무결성 · EQ-V6 세계 진행
  경고  EQ-V2 귀속 · EQ-V3 전망 표시 · EQ-V7 은유 경계

EQ-V5(사업 인과 충실성)는 **게이트가 아니라 구조로** 막혀 있다 — stage 가 step 에서
1:1 로 나오므로 리포트가 말하지 않은 단계는 생길 자리가 없다
(`docs/deviation-equity-visual-phase5.md`). 여기서는 그 1:1 이 유지되는지만 확인한다.
"""

from __future__ import annotations

import re
from typing import Any

from . import config

BLOCK_REASONS: tuple[str, ...] = (
    "eq_v1_reasoning_link_missing",   # 논증 단계에 연결된 reasoning_id 가 없다
    "eq_v4_number_in_generated_screen",  # 정확한 수치를 생성 이미지에 그리라고 요구한다
    "eq_v6_no_progression",           # 같은 개체가 같은 상태로 다시 나온다
)
WARNING_REASONS: tuple[str, ...] = (
    "eq_v2_attribution_lost",         # 애널리스트 추정인데 귀속이 끊겼다
    "eq_v3_forecast_as_actual",       # 전망을 실적처럼 그린다
    "eq_v7_metaphor_on_factual_claim",  # 은유와 사실 주장이 한 화면에 섞였다
)

#: 숫자로 읽히는 것. "49.99%", "1,200억", "3.5배" 를 모두 잡는다.
_NUMBER = re.compile(r"\d[\d,.]*\s*(?:%|배|억|조|만|원|달러|bp|pt)?")


def _stages(sequences: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seq in sequences or []:
        out.extend(seq.get("stages") or [])
    return out


def _screen_text(stage: dict[str, Any]) -> str:
    """**생성 이미지에게 그리라고 넘어가는** 문자열만 모은다.

    ★ `reasoning_text` 는 넣지 않는다 — 그것은 운영자·원장이 읽는 층이고 화면에 안 간다.
      층을 섞으면 정상 설계(수치를 원장에만 남기는 것)를 벌하게 된다.
    """
    parts = [str(stage.get("observable_change") or ""), str(stage.get("visual_prompt") or "")]
    for m in stage.get("mutations") or []:
        if isinstance(m, dict):
            parts.append(str(m.get("result_state") or ""))
    return " ".join(parts)


def _numbers(text: str) -> set[str]:
    return {m.group(0).strip() for m in _NUMBER.finditer(text or "")
            if any(ch.isdigit() for ch in m.group(0))}


def block_reasons(sequences: list[dict[str, Any]] | None) -> list[str]:
    """차단 사유. **코드가 만든 데이터의 모양만** 본다 — 오탐이 없다."""
    stages = _stages(sequences)
    if not stages:
        return []
    out: list[str] = []

    # EQ-V1 — 각 stage 는 자기가 나온 논증 단계를 가리킨다.
    #   ★ 연결이 끊기면 "리포트가 말한 것"과 "화면이 말하는 것"을 대조할 방법이 사라진다.
    miss = [s.get("stage_id") for s in stages if not str(s.get("reasoning_id") or "").strip()]
    if miss:
        out.append(f"eq_v1_reasoning_link_missing:{','.join(str(m) for m in miss[:6])}")

    # EQ-V4 — 정확한 수치를 생성 이미지의 개수·크기로 근사하지 않는다.
    #   ★ 리포트 문장에 있던 숫자가 **화면 계약**에 실렸으면 위반이다. 수치는 코드가
    #     그리는 정밀 레이어(CODE_OVERLAY)와 claim_ids 가 담당한다(리뷰 R1).
    bad_num = [s.get("stage_id") for s in stages
               if _numbers(_screen_text(s)) & _numbers(str(s.get("reasoning_text") or ""))]
    if bad_num:
        out.append(f"eq_v4_number_in_generated_screen:"
                   f"{','.join(str(m) for m in bad_num[:6])}")

    # EQ-V6 — 같은 개체가 **같은 상태로** 다시 나오면 진행이 아니다.
    #   ★ `_stage_of` 가 2회차부터 "앞 단계보다 한 번 더"를 붙이는 것이 이 규칙의 짝이다.
    #     그 장치가 꺼지거나 깨지면 여기서 드러난다.
    seen: dict[tuple[str, str], str] = {}
    dupes: list[str] = []
    for s in stages:
        key = (",".join(str(e) for e in (s.get("entity_refs") or [])),
               str(s.get("observable_change") or ""))
        if key in seen:
            dupes.append(str(s.get("stage_id")))
        else:
            seen[key] = str(s.get("stage_id"))
    if dupes:
        out.append(f"eq_v6_no_progression:{','.join(dupes[:6])}")
    return out


def warnings(sequences: list[dict[str, Any]] | None) -> list[str]:
    """경고 사유. 리포트 문장을 **어휘로** 읽는 검사라 오탐이 있을 수 있다."""
    stages = _stages(sequences)
    if not stages:
        return []
    out: list[str] = []

    # EQ-V2 — 애널리스트 추정·의견을 그리는 stage 는 귀속을 잃지 않는다.
    #   귀속은 claim_ids(number_facts) 가 들고 있다 — 그것이 비면 화면만 남고 출처가 없다.
    v2 = [s.get("stage_id") for s in stages
          if any(t in str(s.get("reasoning_text") or "") for t in config.EQUITY_ESTIMATE_TERMS)
          and not (s.get("claim_ids") or [])]
    if v2:
        out.append(f"eq_v2_attribution_lost:{','.join(str(m) for m in v2[:6])}")

    # EQ-V3 — 전망을 실적처럼 그리지 않는다.
    #   전망 문장에서 나온 stage 는 수치를 코드가 그리는 층(CODE_OVERLAY)에 둬야
    #   "이건 전망이다"라는 표시를 함께 얹을 수 있다. 생성 이미지에는 그 표시를 못 건다.
    v3 = [s.get("stage_id") for s in stages
          if any(t in str(s.get("reasoning_text") or "") for t in config.EQUITY_FORECAST_TERMS)
          and str(s.get("precision_layer") or "") != "CODE_OVERLAY"]
    if v3:
        out.append(f"eq_v3_forecast_as_actual:{','.join(str(m) for m in v3[:6])}")

    # EQ-V7 — 은유는 사실 주장과 분리한다.
    #   같은 stage 가 은유를 그리면서 claim 을 들고 있으면, 시청자는 그 은유를 회사의
    #   실제 사업구조로 읽는다.
    v7 = [s.get("stage_id") for s in stages
          if any(t in _screen_text(s) for t in config.EQUITY_METAPHOR_TERMS)
          and (s.get("claim_ids") or [])]
    if v7:
        out.append(f"eq_v7_metaphor_on_factual_claim:{','.join(str(m) for m in v7[:6])}")
    return out
