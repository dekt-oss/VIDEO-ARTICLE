"""화면이 나레이션에 **답하고** 있는가 — 저장된 지시서에 Jev 를 그림자로 대 본다 (2026-09-24).

무엇을 재나
----------
참고 영상(시화호·고기 핏물)의 핵심은 "장면 자체가 설명"이라는 것이다: "물이 얼마나
더러운지" → 손이 유리병으로 물을 뜬다 → 흙탕이 가라앉는다. 우리 지시서는 같은 자리에
"조선소 부감" 같은 **주제 사진**을 놓는다. 그 차이를 세려면 컷마다 두 가지를 물어야 한다:

    ① 화면이 나레이션이 말하는 **바로 그것**을 보여주나 (주제만 같은 게 아니라)
    ② 화면에 **하나의 주인공**이 있나 (부감·터미널·나열이 아니라)

둘 다 "문장 안에 답이 있는" 질문이다 — Jev 가 잘 맞는 종류(따옴표 게이트와 같은 성격).
채점 축(취향)에는 못 썼지만 이건 텍스트 대조다.

읽기 전용. 운영 표에 쓰지 않는다. 비용은 컷당 $0.00003 수준.

사용:
    python -m scripts.staging_shadow             # 리포트·논문 실사형 지시서 전부
    python -m scripts.staging_shadow --limit 60
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config, db, decide  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")

QUESTIONS: dict[str, dict[str, Any]] = {
    "answers": {
        "type": "noul",
        "instructions": ("Does the SCENE show the specific thing the NARRATION asserts — "
                         "the action, change or comparison itself — rather than merely a "
                         "place or object related to the topic?"),
        "criteria": {"true": "the scene stages what the narration says (a hand scoops muddy "
                             "water; rocks are dumped into a pit; a line grows longer)",
                     "false": "the scene is a generic establishing shot of the topic (a wide "
                              "shipyard, a port, a factory floor) that would fit many "
                              "different narrations"},
    },
    "one_subject": {
        "type": "noul",
        "instructions": "Does the scene have ONE clear subject placed as the focus?",
        "criteria": {"true": "a single object or action dominates; the rest is background",
                     "false": "an array, a panorama, several equal objects, or a crowded scene"},
    },
}


def ask(narration: str, visual: str) -> dict[str, float] | None:
    state = f"NARRATION: {narration}\nSCENE: {visual}"
    data = decide._post({"model": config.JEV_MODEL, "state": state[:config.JEV_STATE_MAX_CHARS],
                         "questions": QUESTIONS})
    if not data:
        return None
    decide._record(data.get("usage") or {}, str(data.get("model") or config.JEV_MODEL))
    try:
        ans = data["answers"]
        return {k: float(ans[k]["noul"]) for k in QUESTIONS}
    except (KeyError, TypeError, ValueError):
        return None


def load(limit: int) -> list[dict[str, Any]]:
    c = db.client()
    rows: list[dict[str, Any]] = []
    for table, key in (("report_directives", "report_id"), ("directives", "paper_id")):
        for d in (c.table(table).select("id,cuts,created_at").eq("version_type", "photo")
                  .order("created_at", desc=True).limit(40).execute().data or []):
            for cu in d.get("cuts") or []:
                if not isinstance(cu, dict):
                    continue
                nar, vis = str(cu.get("narration_ko") or ""), str(cu.get("visual_prompt") or "")
                if nar.strip() and vis.strip():
                    rows.append({"factory": "report" if table.startswith("report") else "paper",
                                 "directive": d["id"][:8], "cut": cu.get("cut_no"),
                                 "role": cu.get("visual_role"), "narration": nar, "visual": vis})
    return rows[:limit] if limit else rows


def main() -> None:
    ap = argparse.ArgumentParser(description="화면-나레이션 정합 그림자 — 읽기 전용")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not decide.enabled():
        raise SystemExit("JEV 가 꺼져 있다.")
    rows = load(args.limit)
    print(f"대상 컷 {len(rows)}개 · 예상 비용 ${len(rows) * 350 * config.TEXT_PRICING['jev-latest']['text_input_per_token']:.4f}")
    got = []
    for i, r in enumerate(rows, 1):
        a = ask(r["narration"], r["visual"])
        if a:
            got.append({**r, **a})
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}")
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "staging_shadow.json"
    p.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")

    def share(xs, k, th=0.5):
        return (sum(1 for x in xs if x[k] >= th) / len(xs)) if xs else 0.0
    print("\n[화면이 나레이션에 답하나 / 주인공이 하나인가]  (Jev 확률 ≥ 0.5 비율)")
    for fac in ("report", "paper"):
        for role in ("REALITY", "MECHANISM"):
            xs = [g for g in got if g["factory"] == fac and g["role"] == role]
            if xs:
                print("  %-6s %-9s %3d컷 · 답한다 %4.0f%% · 주인공 하나 %4.0f%%"
                      % (fac, role, len(xs), 100 * share(xs, "answers"), 100 * share(xs, "one_subject")))
    worst = sorted(got, key=lambda g: g["answers"])[:6]
    print("\n[가장 안 답하는 컷 — 눈으로 볼 것]")
    for g in worst:
        print("  %s 컷%s p=%.2f | %s\n      화면: %s" % (g["directive"], g["cut"], g["answers"],
                                                    g["narration"][:60], g["visual"][:110]))
    print(f"\n저장: {p}")


if __name__ == "__main__":
    main()
