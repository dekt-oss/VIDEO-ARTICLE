"""주류 공장 ⑤ 전략 제안 — 성과 → 다음 편성 가중치 제안(0원, LLM 없음). 2026-10-27. docs/deviation-drinks-publish-loop.md

    python -m engine.drinks_strategy           # 지금 성과로 제안 1건을 만든다(운영자가 /drinks/analytics 에서 반영·기각)

무엇을 재나: 비교 칸(72h) 스냅샷의 **(저장 + 공유) ÷ 도달**. 저장·공유는 "나중에 다시 볼 만했다"는 신호라 카드뉴스의
목적(정보)에 가장 가깝다. 도달이 없거나 0, 저장·공유 중 하나라도 못 받았으면 그 게시물은 표본에서 뺀다(0 으로 치지 않는다).

어떻게 제안하나: 묶음(주종·결과물 형식·소재 갈래·게시 시간대)마다 평균 ÷ 전체 평균 − 1 을 목표 가중치로 보고,
지금 가중치에서 한 번에 ±max_step 만 움직인다. 묶음 표본이 min_group 미만이면 그 묶음은 그대로, 전체 표본이
min_total 미만이면 **아무것도 바꾸지 않는 '표본 부족' 제안**만 낸다 — 몇 편 안 될 때의 차이는 우연이다.
자동 반영하지 않는다. 운영자가 [반영]해야 새 전략 버전이 된다(drinks_strategy_action).
"""

from __future__ import annotations

import argparse
import copy
from typing import Any, Callable, Optional

from .drinks_collect import supabase_rpc
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]
DIMENSIONS = ("category", "post_type", "lane", "slot")
DIM_KO = {"category": "주종", "post_type": "형식", "lane": "소재 갈래", "slot": "게시 시간대"}
VALUE_KO = {"sake": "사케", "traditional": "전통주", "whisky": "위스키", "carousel": "카드뉴스", "reel": "릴스",
            "evergreen": "상시", "timely": "시의성", "reader_question": "독자 질문", "morning": "아침", "afternoon": "낮",
            "evening": "저녁", "night": "밤"}


def save_rate(values: dict[str, Any]) -> Optional[float]:
    reach = values.get("reach")
    if not isinstance(reach, (int, float)) or reach <= 0:
        return None
    if not all(isinstance(values.get(k), (int, float)) for k in ("saved", "shares")):
        return None
    return (values["saved"] + values["shares"]) / reach


def _groups(post: dict[str, Any]) -> dict[str, list[str]]:
    return {"category": list(post.get("categories") or []), "post_type": [post.get("post_type")],
            "lane": [post.get("lane")], "slot": [post.get("slot")]}


def propose(inputs: dict[str, Any]) -> dict[str, Any]:
    lim = inputs["limits"]
    min_group, min_total = int(lim["strategy_min_group"]), int(lim["strategy_min_total"])
    step, cap = float(lim["strategy_max_step"]), float(lim["strategy_max_lift"])
    active = inputs["active"]
    current = active["weights"]
    rated, excluded = [], 0
    for p in inputs.get("posts") or []:
        r = save_rate(p.get("values") or {})
        if r is None:
            excluded += 1
        else:
            rated.append((p, r))
    total = len(rated)
    overall = sum(r for _, r in rated) / total if total else None
    basis: dict[str, Any] = {"metric": "(saved+shares)/reach", "bucket": lim["strategy_bucket"], "overall": overall,
                             "sample_total": total, "excluded": excluded, "groups": {}}
    weights = copy.deepcopy({d: dict(current.get(d) or {}) for d in DIMENSIONS})
    sufficient = total >= min_total and bool(overall)
    changes = []
    for d in DIMENSIONS:
        acc: dict[str, list[float]] = {}
        for p, r in rated:
            for v in _groups(p)[d]:
                if v:
                    acc.setdefault(v, []).append(r)
        basis["groups"][d] = {}
        for v, rs in sorted(acc.items()):
            mean = sum(rs) / len(rs)
            target = max(-cap, min(cap, mean / overall - 1)) if overall else 0.0
            g = {"n": len(rs), "mean": round(mean, 6), "target": round(target, 4), "enough": len(rs) >= min_group}
            basis["groups"][d][v] = g
            if not (sufficient and g["enough"]):
                continue
            cur = float(weights[d].get(v, 0.0))
            new = round(max(-cap, min(cap, cur + max(-step, min(step, target - cur)))), 4)
            if new != cur:
                weights[d][v] = new
                changes.append((d, v, cur, new, len(rs)))
    if not sufficient:
        summary = (f"표본 부족 — 72시간 성과가 잡힌 게시물이 {total}편이라(최소 {min_total}편) 가중치를 바꾸지 않습니다."
                   + (f" 지표가 모자라 뺀 게시물 {excluded}편." if excluded else ""))
    elif not changes:
        summary = f"게시물 {total}편을 봤지만 표본 {min_group}편 이상인 묶음에서 바꿀 만한 차이가 없습니다."
    else:
        summary = f"게시물 {total}편(전체 저장·공유율 {overall:.1%}) 기준 제안: " + "; ".join(
            f"{DIM_KO[d]} {VALUE_KO.get(v, v)} {cur:+.2f}→{new:+.2f}(표본 {n}편)" for d, v, cur, new, n in changes)
    return {"base_version_id": active["id"], "weights": weights, "basis": basis, "sample_total": total,
            "sufficient": sufficient, "summary_ko": summary}


def run(rpc: Rpc) -> dict[str, Any]:
    prop = propose(rpc("drinks_strategy_inputs", {}))
    res = rpc("drinks_save_strategy_proposal", prop)
    log.info("drinks: 전략 제안 %s — %s", res.get("proposal_id"), prop["summary_ko"])
    return {**res, "summary_ko": prop["summary_ko"]}


def main(argv: Optional[list[str]] = None) -> int:
    argparse.ArgumentParser(description="주류 공장 전략 제안(성과 → 다음 편성 가중치)").parse_args(argv)
    run(supabase_rpc())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
