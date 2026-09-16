"""시퀀스(stage) 단위 렌더 계획 — **컷이 아니라 시퀀스가 렌더 단위다**.

운영자 지시(2026-09-03, 재확인 2026-09-05): "컷 단위 하지 말고 시퀀스로 풀 영상으로
만들어라. 전체가 영상 시퀀스로 흐름으로 흘러가야 한다."

무엇을 푸는가 — 실측(세마글루타이드 렌더 c43d87a4, 14컷 86초, $5.59):
  · `render.py` 가 `for cut in cuts` 로 돌며 **컷마다 클립 1개**를 만들고, 나레이션이
    클립보다 길면 **마지막 프레임을 정지**(clip_fit hold)시켰다. hold 5컷,
    최악은 컷8 이 12.7초 나레이션에 8초 클립 → **4.7초 얼음**.
  · 컷 경계마다 화면이 끊겨 "사진 띄워놓고 나레이션 읽는" 느낌이 됐다.

이 모듈이 하는 일: 컷들을 stage 로 묶고, stage 하나를 **연속 영상 한 덩어리**로 채우는
클립 계획을 세운다. 컷은 자막·오버레이 경계로만 남는다.

★ 물리 제약(바꿀 수 없다):
    Veo 최대 8초(config.VEO_CLIP_SEC_TIERS)  ·  연쇄 깊이 상한(config.MAX_CHAIN_DEPTH)
  그래서 "시퀀스 = 한 클립"은 불가능하다. 가능한 것은 **연쇄**다 —
  앞 클립의 마지막 프레임을 다음 클립의 첫 프레임으로 넘긴다.

★ 순수 모듈이다. 네트워크·파일·LLM 없음. 계획만 세운다.
"""

from __future__ import annotations

import math
from typing import Any

from . import config


def stage_of(cut: dict[str, Any]) -> str:
    """이 컷이 속한 stage_id. 라우터가 정한 값(resolved_visual_plan)이 정본이다."""
    plan = cut.get("resolved_visual_plan")
    if isinstance(plan, dict):
        sid = str(plan.get("stage_ref") or "").strip()
        if sid:
            return sid
    return ""


def group_cuts(cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """컷 목록 → stage 묶음. 반환: [{stage_id, indexes:[컷 인덱스…]}].

    ★ stage 를 모르는 컷(훅·CTA)은 **앞 stage 를 물려받는다** — 새 stage 를 만들지 않는다.
      새로 만들면 그 컷 하나가 독립 영상이 되어 지금과 똑같이 끊긴다.
    ★ 맨 앞 컷이 stage 를 모르면 그 컷들은 아직 stage 가 없다 — 뒤에 처음 나오는 stage 에
      **붙이지 않는다.** 훅이 본문 세계로 끌려들어가면 화면이 어긋난다. 자기들끼리 묶는다.
    ★ 같은 stage 라도 **떨어져 있으면 따로 묶는다**(A A B A). 중간에 다른 세계가 끼었는데
      이어 붙이면 없던 연속성을 주장하는 것이다.
    ★★ [혼자 서는 컷] 2026-09-14 운영자 실측("결론이나 마무리가 좀 이상한데?").
      ① **연결 컷**(라우터가 connective_in_world 로 본, 기전이 아닌 컷)은 묶음에 끼우지 않는다.
         sequence_render.reference_decision 은 이미 "연결 컷의 내용은 다른 장면"이라며 앞 그림
         참조를 **거부**하는데, 여기서는 그 컷을 앞 컷 영상의 한 구간으로 **잘라 썼다** —
         같은 판단을 두 곳이 반대로 하고 있었다. 실측: 결론 컷(도서관)이 한계 stage 의 지도
         영상에 묶여 **자기 그림이 한 번도 안 그려졌고**, 19초 연쇄가 흘러 깨진 글자가 박힌
         유럽 지도 위에서 "더 많은 연구가 필요합니다"가 나왔다.
      ② **마지막 컷**(결론·마무리)은 늘 자기 클립을 갖는다. 실측: 최근 16편 중 13편이
         마지막 컷을 앞 묶음 영상에서 잘라 쓰고 있었다.
      비용: 16편 기준 연결 컷 18개 → 편당 클립 약 1개 증가(약 $0.2~0.4).
    """
    groups: list[dict[str, Any]] = []
    prev_sid = ""
    last = len(cuts) - 1
    for i, cut in enumerate(cuts):
        sid = stage_of(cut) or prev_sid
        alone = _rides_alone(cut, is_last=(i == last))
        if groups and not alone and not groups[-1].get("solo") and sid == groups[-1]["stage_id"]:
            groups[-1]["indexes"].append(i)
        else:
            groups.append({"stage_id": sid, "indexes": [i], **({"solo": True} if alone else {})})
        prev_sid = sid
    for g in groups:
        g.pop("solo", None)                  # 호출측 계약은 {stage_id, indexes} 그대로
    return groups


def _rides_alone(cut: dict[str, Any], *, is_last: bool) -> bool:
    """이 컷은 앞 묶음 영상에 끼우지 않고 **자기 클립**을 가져야 하는가(group_cuts 주석)."""
    if is_last and config.STAGE_FINAL_CUT_OWN_CLIP:
        return True
    plan = cut.get("resolved_visual_plan")
    if not isinstance(plan, dict) or not config.STAGE_CONNECTIVE_OWN_CLIP:
        return False
    reasons = plan.get("reasons") or []
    return ("connective_in_world" in reasons
            and str(plan.get("base") or "") != "MECHANISM_SEQUENCE")


def plan_clips(total_sec: float,
               max_clip_sec: int | None = None,
               max_chain_depth: int | None = None) -> list[float]:
    """stage 길이 → 그 stage 를 덮는 **연쇄 클립들의 초수**.

    ★ 왜 나눠 담나: Veo 가 한 번에 8초까지만 만든다. 20초 stage 는 8+8+4 다.
    ★ 왜 마지막을 짧게 두지 않고 티어에 맞추나: Veo 는 4·6·8초만 받는다(VEO_CLIP_SEC_TIERS).
      남은 3초를 위해 4초를 만들고 **1초를 잘라낸다** — 자르는 것은 얼지 않는다.
    ★ 연쇄 깊이 상한을 넘기면 거기서 끊고 **원본 그림으로 다시 시작**한다. 깊이가 깊어질수록
      인물·재질이 흐려지기 때문이다(MAX_CHAIN_DEPTH 의 존재 이유). 이 함수는 초수만 정하고,
      어디서 끊는지는 chain_breaks() 가 알려 준다.
    """
    all_tiers = sorted(config.VEO_CLIP_SEC_TIERS)
    cap = int(max_clip_sec or all_tiers[-1])
    tiers = [t for t in all_tiers if t <= cap] or [all_tiers[0]]
    need = max(0.0, float(total_sec))
    if need <= 0.05:
        return [float(tiers[0])]

    # ★★ [자투리를 사지 않는다] 2026-09-13 운영자 지시("자투리도 지금 잡아줘").
    #   종전에는 상한부터 채우고 남은 것을 올렸다 — 9.4초 stage 가 8+4=**12초**였다.
    #   6+4=10 이면 되는데 2초를 더 산다. 영상은 **초당 과금**이라 그 2초가 그대로 돈이다.
    #   실측(첫 실물 렌더 전반부): 나레이션 55.6초에 62초를 사서 6.4초($0.32)를 버렸다.
    #   이제 **덮을 수 있는 가장 작은 합**을 고르고, 같은 합이면 클립 수가 적은 쪽을 쓴다
    #   (클립이 많을수록 연쇄가 깊어져 정체성이 흐려진다 — MAX_CHAIN_DEPTH 의 근거).
    target = need - 0.05
    limit = int(math.ceil(target)) + max(tiers)
    INF = float("inf")
    best_count = [INF] * (limit + 1)      # 그 합을 만드는 최소 클립 수
    pick = [0] * (limit + 1)              # 그 합에서 마지막에 고른 티어
    best_count[0] = 0
    for s in range(1, limit + 1):
        for t in tiers:
            if s - t >= 0 and best_count[s - t] + 1 < best_count[s]:
                best_count[s] = best_count[s - t] + 1
                pick[s] = t
    total = next((s for s in range(int(math.ceil(target)), limit + 1)
                  if best_count[s] < INF), 0)
    if not total:                          # 도달 가능한 합이 없다(있을 수 없지만 방어)
        return [float(tiers[-1])]
    out: list[float] = []
    while total > 0:
        out.append(float(pick[total]))
        total -= pick[total]
    out.sort(reverse=True)                 # 큰 클립을 앞에 — 연쇄 시작을 길게 잡는다
    return out or [float(tiers[0])]


def chain_breaks(clip_count: int, max_chain_depth: int | None = None) -> list[bool]:
    """클립마다 "앞 클립에서 이어받는가". 첫 클립은 항상 False(원본 그림에서 시작).

    ★ 깊이 상한에 닿으면 다시 False — 거기서 원본으로 되돌아간다. 이 값을 **안 재고
      올리지 마라**: 깊이가 깊을수록 정체성이 흐려진다는 것이 상한의 근거이고,
      깊이 3이 견디는지 실측한 적이 없다(설계안 §4 ①).
    """
    depth_cap = int(max_chain_depth or config.MAX_CHAIN_DEPTH)
    out: list[bool] = []
    depth = 0
    for i in range(max(0, clip_count)):
        if i == 0 or depth >= depth_cap:
            out.append(False)
            depth = 0
        else:
            out.append(True)
            depth += 1
    return out


def slice_windows(durations: list[float]) -> list[tuple[float, float]]:
    """stage 안 컷들의 길이 → 각 컷이 stage 영상에서 가져갈 (시작, 길이).

    ★ 컷은 화면을 자르지 않는다 — **연속 영상의 서로 다른 구간**을 볼 뿐이다.
      그래서 컷 경계에서 화면이 끊기지 않는다. 이것이 이 작업의 핵심이다.
    """
    out: list[tuple[float, float]] = []
    t = 0.0
    for d in durations:
        out.append((round(t, 3), round(float(d), 3)))
        t += float(d)
    return out


def plan_stage(cuts: list[dict[str, Any]], durations: list[float]) -> list[dict[str, Any]]:
    """컷 + 컷별 길이 → stage 별 렌더 계획(정본).

    반환 각 항목:
      stage_id, indexes(컷 인덱스), total_sec, clips(초수 목록),
      chained(클립별 이어받기 여부), windows(컷별 (시작,길이))
    """
    plans: list[dict[str, Any]] = []
    for g in group_cuts(cuts):
        durs = [float(durations[i]) for i in g["indexes"] if i < len(durations)]
        total = round(sum(durs), 3)
        clips = plan_clips(total)
        plans.append({
            "stage_id": g["stage_id"],
            "indexes": list(g["indexes"]),
            "total_sec": total,
            "clips": clips,
            "chained": chain_breaks(len(clips)),
            "windows": slice_windows(durs),
            "generated_sec": round(sum(clips), 3),
        })
    return plans


def enabled(header: dict[str, Any]) -> bool:
    """이 지시서를 stage 단위로 렌더할 것인가.

    ★ stage 가 없는 지시서(옛 지시서·다른 버전)는 **기존 컷 경로를 그대로 탄다.**
      새 경로가 옛 산출물을 조용히 바꾸면 안 된다.
    """
    if not config.STAGE_RENDER_ENABLED:
        return False
    if str(header.get("version_type") or "") not in config.I2V_CHAIN_VERSIONS:
        return False
    seqs = header.get("visual_sequences")
    if not isinstance(seqs, list):
        return False
    return any((s or {}).get("stages") for s in seqs if isinstance(s, dict))


def savings(plans: list[dict[str, Any]], cut_count: int) -> dict[str, Any]:
    """계획이 컷 단위 대비 무엇을 바꾸는가 — 로그·QA 에 남길 요약."""
    clips = sum(len(p["clips"]) for p in plans)
    return {
        "stages": len(plans),
        "clips": clips,
        "clips_if_per_cut": cut_count,
        "generated_sec": round(sum(p["generated_sec"] for p in plans), 3),
        "narration_sec": round(sum(p["total_sec"] for p in plans), 3),
    }
