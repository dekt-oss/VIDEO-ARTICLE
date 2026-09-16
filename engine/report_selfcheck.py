"""(c) 자기검증 — 리포트용 (명세 5-3, 층3).

생성된 대본의 각 나레이션 문장을 Fact Sheet 와 대조 → 근거 없는 문장 = 환각 의심 빨간 깃발.
논문 selfcheck.py 미러. all_grounded 는 코드에서 재계산(LLM 자기보고 불신).
"""

from __future__ import annotations

import json
from typing import Any

from . import config, report_evidence
from .llm import call_json

SELFCHECK_SYSTEM = """너는 엄격한 사실 검증관이다. 입력: Fact Sheet(JSON) + 생성된 대본 씬들(JSON).
대본의 각 문장이 Fact Sheet의 항목으로 뒷받침되는지 판정한다.
Fact Sheet에 근거가 없는 문장은 grounded=false 로 표시하고 그 문장을 그대로 적는다.
보수적으로 판단하라: 근거가 모호하면 grounded=false.

■■ 아래 한 축만은 **사실이 아니라 문장**을 본다(운영자 지시 2026-09-10).
   이 대본은 **소리 내어 읽히는 나레이션**이다. 귀로 들어서 걸리는 데가 없어야 한다.
   사실 판정과 **섞지 마라** — 여기서 내용이 틀렸는지는 보지 않는다.
- korean_natural: 그 씬의 나레이션이 한국어로 자연스러우면 true, 어색하면 false.
- awkward_spans: 어색한 **구절을 원문 그대로** 옮겨 적는다(문장 전체가 아니라 걸리는 부분).
- fluency_issues: translationese(번역투 — "~에 대한", "~를 통해", 피동 남용) / particle(조사) /
  register_mix(문어체·구어체 혼용) / long_modifier(수식 중첩, 60자 넘는 한 문장) /
  reading(소리 내 읽을 때 걸림 — 숫자·단위·영어 약어) 중에서 고른다(여러 개 가능).
★ 보수적으로 판단하라. 취향 문제는 어색함이 아니다 — **읽다가 걸리는 것만** false. 애매하면 true.

JSON only. 설명·마크다운·코드펜스 금지.
{
  "scenes": [
    { "scene": <int>, "grounded": <bool>,
      "unsupported": ["<근거 없는 문장 원문>"],
      "matched_facts": ["<뒷받침하는 Fact Sheet 키>"],
      "korean_natural": <bool>,
      "awkward_spans": ["<어색한 구절 원문 그대로>"],
      "fluency_issues": ["<translationese|particle|register_mix|long_modifier|reading>"] }
  ],
  "all_grounded": <bool>
}"""


def selfcheck_user_prompt(fact_sheet: dict[str, Any], scenes: list[dict[str, Any]]) -> str:
    return (
        "Fact Sheet:\n" + json.dumps(fact_sheet, ensure_ascii=False, indent=2)
        + "\n\n대본 씬들:\n" + json.dumps(scenes, ensure_ascii=False, indent=2)
    )


def exempt_scenes(scenes: list[dict[str, Any]]) -> set[int]:
    """면제받을 씬 번호. **역할만으로 정하지 않는다**(v3 §5-4 · 적대적 리뷰).

    ★ 왜 코드 판정이 필요한가: 모델이 전 씬에 HOOK 을 붙이면 진짜 환각 7건에도
      all_grounded=True 가 나왔다(재현). 프롬프트로만 말리는 것은 이 저장소 자세가 아니다.

    두 겹으로 막는다:
      ① **수치를 말하는 씬은 면제하지 않는다.** 훅이라도 숫자를 말했으면 그 숫자는 근거가
         있어야 한다 — 면제의 근거는 "사실 주장이 아니라서"이지 "역할 이름표" 가 아니다.
      ② 면제 씬 수에 상한을 둔다. 전부 면제되는 대본은 자기검증이 없는 대본이다.
    """
    eligible: list[int] = []
    for s in (scenes or []):
        if not isinstance(s, dict):
            continue
        if str(s.get("scene_role") or "") not in config.SCENE_ROLES_EVIDENCE_EXEMPT:
            continue
        if report_evidence.spoken_numbers(str(s.get("narration_ko") or "")):
            continue          # ① 수치를 말하면 면제 취소
        eligible.append(int(s.get("scene") or 0))
    cap = max(1, int(len(scenes or []) * config.SELFCHECK_EXEMPT_MAX_RATIO))
    if len(eligible) > cap:
        # ② 상한 초과 — 앞뒤(훅·마무리)를 우선 남기되 **cap 을 넘지 않는다.**
        #    ★ 예전 코드는 cap 을 계산해 놓고 `[:1] + [-1:]` 로 잘라 늘 2개를 남겼다. 그래서
        #      씬이 2개인 대본은 두 씬 모두 면제되어 자기검증이 통째로 꺼졌다(cap=1인데 2개).
        #      "전 씬에 HOOK 을 붙이면 우회된다"는 원래 결함이 씬 수만 줄이면 그대로 재현됐다.
        ordered = sorted(eligible)
        kept = [ordered[0]] if cap == 1 else [ordered[0], ordered[-1]] + ordered[1:-1]
        eligible = kept[:cap]
    return set(eligible)


def normalize_selfcheck(obj: dict[str, Any],
                        roles_by_scene: dict[int, str] | None = None,
                        exempt: set[int] | None = None) -> dict[str, Any]:
    """LLM 판정 정규화 + **역할 면제**(v3 §5-4).

    ★ 왜 면제가 필요한가: 훅("정말 이제 시작일까요?")과 마무리("댓글로 알려주세요")는 사실
      주장이 아닌데 검증관은 근거를 못 찾아 빨간 깃발을 세웠다. 실측으로 최근 초안 6건 전부가
      첫 씬과 마지막 씬에서 오탐을 받았고(docs/phase0-영상엔진품질_v3.md §4), 그 결과 깃발이
      상시 켜져 **진짜 환각을 가리키는 신호로서 죽어 있었다.**
    ★ 면제된 씬은 grounded=True 로 두되 exempt=True 를 남긴다 — "검사해서 통과"와
      "검사 대상이 아님"을 화면에서 구분할 수 있어야 한다.
    """
    roles_by_scene = roles_by_scene or {}
    scenes_in = obj.get("scenes") or []
    scenes: list[dict[str, Any]] = []
    for s in scenes_in:
        if not isinstance(s, dict):
            continue
        unsupported = s.get("unsupported") or []
        if isinstance(unsupported, str):
            unsupported = [unsupported] if unsupported else []
        unsupported = [str(x) for x in unsupported]
        grounded = bool(s.get("grounded", not unsupported)) and not unsupported

        scene_no = int(s.get("scene") or 0)
        # exempt 집합이 주어지면 그것이 정본이다(수치·상한 판정을 이미 거친 결과).
        # 없을 때만 역할로 판정한다 — 하위호환용 경로.
        is_exempt = (scene_no in exempt) if exempt is not None else (
            str(roles_by_scene.get(scene_no) or "") in config.SCENE_ROLES_EVIDENCE_EXEMPT)
        if is_exempt:
            grounded, unsupported = True, []

        matched = s.get("matched_facts") or []
        if isinstance(matched, str):
            matched = [matched]
        fluency = s.get("fluency_issues") or []
        if isinstance(fluency, str):
            fluency = [fluency]
        spans = s.get("awkward_spans") or []
        if isinstance(spans, str):
            spans = [spans]
        scenes.append({
            "scene": scene_no,
            "grounded": grounded,
            "exempt": is_exempt,
            "unsupported": unsupported,
            "matched_facts": [str(x) for x in matched],
            # ★ 한국어 문장 축(2026-09-11, 논문 라인과 같은 계약). **면제와 무관하다** —
            #   훅·마무리도 소리 내어 읽히므로 어색하면 어색한 것이다. 승인·컴플라이언스에
            #   닿지 않고, 다듬기(script_polish)의 대상 선정에만 쓰인다.
            "korean_natural": bool(s.get("korean_natural", True)),
            "awkward_spans": [str(x) for x in spans],
            "fluency_issues": [str(k) for k in fluency
                               if str(k) in config.SELFCHECK_FLUENCY_KINDS],
        })
    # all_grounded 는 최종 씬 목록에서 재계산한다(LLM 자기보고 불신 + 면제 반영).
    return {"scenes": scenes, "all_grounded": all(s["grounded"] for s in scenes)}


def check(fact_sheet: dict[str, Any], scenes: list[dict[str, Any]]) -> dict[str, Any]:
    obj = call_json(
        model=config.MODEL_REPORT_SELFCHECK,
        system=SELFCHECK_SYSTEM,
        user=selfcheck_user_prompt(fact_sheet, scenes),
        # 한국어 축(awkward_spans 는 원문 구절을 그대로 옮긴다)이 붙어 3072 → 4096.
        max_tokens=4096,
    )
    # 역할은 **호출측이 넘긴 씬**에서 읽는다 — LLM 이 역할을 되돌려주길 기대하지 않는다.
    roles = {int(s.get("scene") or 0): str(s.get("scene_role") or "")
             for s in (scenes or []) if isinstance(s, dict)}
    return normalize_selfcheck(obj, roles, exempt_scenes(scenes))
