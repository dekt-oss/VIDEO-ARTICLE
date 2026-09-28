"""대본 4막 구조 — 논문·리포트 공통 (2026-09-28 운영자 지시).

원문: "흔한 오해로 확정짓기보다 문제 제기 → 오해 또는 문제 상황 설명 → 반전 또는 원리 세부 설명 →
결과/결론 이렇게 가야지 논문이랑 레포트 통합으로 사용되는 거 아니야??"

왜 필요했나
----------
벤치마크(고기 핏물)는 "피일까요?"(문제 제기) → "끓고 1984년… 40~60%가"(문제 상황) → "그 색의 정체는
미오글로빈이라는 단백질"(반전·원리) → "75%가 물이라 세포 밖으로 흘러나온 것"(결과)으로 끌고 간다.
우리 리포트 대본은 "유안타증권은 …분석했습니다 / …추정했습니다"가 이어지는 요약문이었고(삼성전자 편),
논문 대본은 "강한 결과 → 연구 범위 공개" 틀이라 두 공장이 서로 다른 뼈대를 썼다.

★ 한 문자열을 두 공장이 같이 쓴다(STAGING_CONTRACT·HOOK_CUT_RULE 와 같은 이유 — 두 벌이면 한쪽만 낡는다).
★ 엣지 쌍둥이(generate-draft · generate-report-draft)에도 같은 문장이 있고 tests/test_prompt_sync.py 가
  앵커로 감시한다.
"""

from __future__ import annotations

from typing import Any

#: 씬이 4막 중 어디에 있나. 순서가 곧 서사 순서다.
ARC_STAGES: tuple[str, ...] = ("problem", "situation", "turn", "result")

#: 프롬프트에 붙는 공통 구조. 파이썬·엣지 양쪽에 같은 앵커 문구가 있어야 한다(test_prompt_sync).
NARRATIVE_ARC: str = """
[★ 대본 구조 — 4막(논문·리포트 공통)] 문제 제기 → 오해 또는 문제 상황 → 반전 또는 원리 → 결과/결론
  ① 문제 제기(problem) 1~2씬: 시청자가 "왜?"를 품게 하는 질문·역설. 첫 씬은 짧은 한마디다.
  ② 오해 또는 문제 상황(situation) 1~2씬: 흔히 그렇게 여기는 이유, 또는 지금 무엇이 막혀·어긋나 있는지.
     ★ 오해를 지어내지 마라 — 소재에 오해가 없으면 문제 상황만 설명한다.
  ③ 반전 또는 원리(turn) 2~4씬: 실제로는 어떻게 되는가. 원리·과정을 **한 씬에 한 단계씩**,
     "그래서·하지만·즉"으로 잇는다(논문: 연구 결과·기전 / 리포트: 논증 단위 driver → 실적 → 밸류).
  ④ 결과/결론(result) 1~2씬: 그래서 무엇이 달라지나 + ①의 질문에 답한다. 한계·리스크는 여기서 한 줄.
  ★ 출처(기관·증권사)는 한두 번이면 된다 — 매 씬 "OO은 …했습니다"로 시작하지 마라.
    두 번째부터는 주어를 사물·현상으로 둔다("HBM 이 웨이퍼를 더 먹습니다").
  ★ 각 씬에 arc_stage 를 적는다: problem|situation|turn|result. 차례대로 가고 되돌아가지 않는다.
"""


def arc_stage(value: Any) -> str:
    """모델 값 → 4막 enum. 모르면 빈 문자열(판정 불가를 지어내지 않는다)."""
    v = str(value or "").strip().lower()
    return v if v in ARC_STAGES else ""


def arc_problems(scenes: list[dict[str, Any]]) -> list[str]:
    """4막이 지켜졌나 → 문제 코드 목록(빈 목록 = 통과). 순수 함수. 경고용 — 막지 않는다.

    arc_stage 를 하나도 안 적은 옛 초안은 판정하지 않는다(빈 목록).
    """
    stages = [arc_stage(s.get("arc_stage")) for s in scenes if isinstance(s, dict)]
    marked = [x for x in stages if x]
    if not marked:
        return []
    out: list[str] = []
    for need in ("problem", "turn", "result"):
        if need not in marked:
            out.append(f"script_arc_missing:{need}")
    order = [ARC_STAGES.index(x) for x in marked]
    if any(b < a for a, b in zip(order, order[1:])):
        out.append("script_arc_out_of_order")
    return out
