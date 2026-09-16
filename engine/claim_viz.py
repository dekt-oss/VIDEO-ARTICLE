"""코드 차트에 들어갈 수치를 Claim Ledger 에서 **해소**한다 (수정명세 §M-E4).

★ 왜 이 모듈이 필요한가 — 구현 중 발견한 결함:
  `engine/manim_templates.select_template` 의 `number_compare` 분기가 수치를 하드코딩하고 있었다
  (`items: [("전", 40), ("후", 75)]`). 지금까지는 `render_kind_for_scene` 이 `animation` 버전
  에서만 클립을 내주는데 `animation` 이 VIDEO_VERSIONS 에서 빠져 **도달 불가 코드**라 드러나지
  않았다. editorial 의 data_viz 를 코드 차트로 살리는 순간 그 40/75 가 화면에 그려진다 —
  논문에 없는 수치가 영상에 박히는 것이고, 이 저장소의 제1 불변식(환각 방지) 위반이다.

★ 그래서 이 모듈은 `engine/fin_charts/types.py` 의 계약 형태를 따른다: 값은 원시 숫자가 아니라
  **claim_id 로만** 주입되고, 해소에 실패하면 차트를 그리지 않는다(스틸로 폴백). 금융 라인의
  `resolve_fact(fact_sheet, fact_id)` 와 같은 사상이며, Codex 소유 파일은 건드리지 않는다.

★ 순수 모듈: manim·네트워크·파일을 모른다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# "3.2%p", "1,240", "-12.5 percent" 같은 문자열에서 첫 수치를 뽑는다.
_NUM_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass(frozen=True)
class ClaimNumber:
    """차트가 그릴 수 있는, 원장에서 확인된 수치 1건."""

    claim_id: str
    value: float
    unit: str
    label: str


def _to_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_RE.search(str(v or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def resolve_claim(fact_sheet: dict[str, Any] | None, claim_id: str) -> dict[str, Any] | None:
    """원장에서 claim_id 로 주장을 찾는다. 없으면 None(추정 금지)."""
    for c in ((fact_sheet or {}).get("claims") or []):
        if isinstance(c, dict) and str(c.get("claim_id")) == str(claim_id):
            return c
    return None


def claim_number(fact_sheet: dict[str, Any] | None, claim_id: str) -> ClaimNumber | None:
    """주장에서 그릴 수 있는 수치를 뽑는다. **effect_size 가 없으면 None** — 지어내지 않는다."""
    claim = resolve_claim(fact_sheet, claim_id)
    if not claim:
        return None
    value = _to_float(claim.get("effect_size"))
    if value is None:
        return None
    return ClaimNumber(
        claim_id=str(claim.get("claim_id")),
        value=value,
        unit=str(claim.get("effect_unit") or ""),
        label=str(claim.get("outcome") or claim.get("claim_ko") or "")[:14],
    )


def number_compare_params(
    cut: dict[str, Any], fact_sheet: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """data_viz 컷 → number_compare 파라미터. 원장에서 값이 안 나오면 **None**.

    None 이면 호출측이 코드 차트를 포기하고 스틸로 간다. "그럴듯한 기본값"을 그리는 것보다
    이미지 한 장이 낫다 — 화면에 박힌 숫자는 시청자가 논문의 수치로 읽는다.
    """
    numbers: list[ClaimNumber] = []
    for cid in (cut.get("claim_ids") or []):
        n = claim_number(fact_sheet, str(cid))
        if n:
            numbers.append(n)
    if not numbers:
        return None
    if len(numbers) == 1:
        # 비교 상대가 없으면 단일 값 막대 하나. 없는 비교군을 만들어 붙이지 않는다.
        n = numbers[0]
        return {"title": f"{n.label} {n.value:g}{n.unit}".strip(),
                "items": [(n.label or n.claim_id, n.value)]}
    return {
        "title": "",
        "items": [(n.label or n.claim_id, n.value) for n in numbers[:3]],
    }


def can_render_code_chart(cut: dict[str, Any], fact_sheet: dict[str, Any] | None) -> bool:
    """이 컷을 코드 차트로 그릴 근거가 실제로 있는가."""
    return number_compare_params(cut, fact_sheet) is not None
