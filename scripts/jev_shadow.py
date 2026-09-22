"""Jev Shadow — **운영을 건드리지 않고** 판단 모델이 쓸 만한지 잰다 (2026-09-22).

무엇을 푸는가
------------
Jev 를 채점 자리에 넣자는 제안이 있다. 그런데 새 모델을 운영에 바로 꽂으면 "좋아진 것
같다"는 인상평만 남는다. 이 저장소는 그 함정을 이미 겪었다(모델 교체를 인상으로 결정하면
나중에 무엇이 나아졌는지 아무도 말할 수 없다 — `scripts/model_ab.py` 머리말).

그래서 **먼저 그림자로만 돌린다.** 이 스크립트는:
  · `scores`(현행 제미나이 채점)를 **읽기만** 한다 — 쓰지 않는다
  · `decisions`(사람이 직접 낙점·보류·탈락시킨 것)를 **정답지**로 쓴다
  · 같은 논문에 Jev 를 물어 둘을 대조한다
운영 경로는 한 줄도 타지 않는다.

정답지가 실재한다
----------------
실측(2026-09-22): `decisions` 256행 — picked 160 · shortlisted 22 · rejected 74.
그중 64건이 실제로 대본까지 갔다. **사람이 직접 누른 기록**이라 이보다 나은 라벨이 없다.

기준선이 낮다
------------
현행 제미나이 채점이 그 판정을 얼마나 가르는가(AUC, 0.5 = 동전 던지기):

    fun_index 0.623 · importance 0.609 · relatability 0.611
    surprise 0.594 · significance 0.585 · explainability **0.566**

**거의 못 가른다.** 이건 Jev 를 깎는 말이 아니라 **넘어야 할 막대가 낮다**는 뜻이고,
동시에 "지금 축이 옳은 것을 재고 있는가"라는 더 큰 질문을 남긴다.

무엇이 가장 중요한가 — **false negative**
----------------------------------------
이 저장소에서는 "별로인 후보를 하나 더 통과시키는 것"보다 **"좋은 후보를 초기에 버리는
것"** 이 훨씬 위험하다. 하루 20건을 사람이 훑는 구조라 통과가 하나 늘어도 비용이 거의 없고,
버려진 것은 **다시 안 본다**. 그래서 `낙점을_버림`(high-value false negative)을 따로 센다.

사용:
    python -m scripts.jev_shadow                 # 라벨 전수(256건), 비용 ~$0.02
    python -m scripts.jev_shadow --limit 40      # 표본만
    python -m scripts.jev_shadow --dry-run       # 호출 0 — 질문지와 대상만 본다
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config, db, decide  # noqa: E402
from engine.util import log  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")

# ★★ **한 번에 묻는다.** Jev 는 질문을 병렬로 받는다 — 축마다 호출을 나누면 입력(논문 초록)을
#   축 수만큼 다시 보내게 되고, 입력 토큰이 곧 비용인 모델에서 그건 그대로 낭비다.
#   현행 채점이 한 호출에 10개 숫자를 받는 것과 같은 모양을 유지한다.
#
# ★ 문구는 `engine/scoring.py` 의 루브릭을 그대로 옮긴다 — 다르게 물으면 현행과의 일치율이
#   "모델 차이"가 아니라 "질문 차이"를 재게 된다.
# ★ `score` 의 `criteria` 는 **낮은 것부터 높은 것 순의 배열**이다(2~10단계). dict 로 주면
#   422 `list_type` 이 난다 — 실측으로 확인했다. 답은 레벨 인덱스의 확률가중 평균이라
#   0..(len-1) 범위다. 현행 0~10 과 견주려면 `_to_ten()` 으로 환산한다.
QUESTIONS: dict[str, dict[str, Any]] = {
    "surprise": {
        "type": "score",
        "instructions": "이 연구 결과가 일반인에게 의외이거나 놀라운가?",
        "criteria": ["널리 알려진 상식이다", "조금 새롭다", "어느 정도 의외다",
                     "꽤 놀랍다", "통념을 뒤집는다"],
    },
    "explainability": {
        "type": "score",
        "instructions": "60초 숏폼으로 핵심을 설명할 수 있는가?",
        "criteria": ["배경 지식이 너무 많이 필요하다", "많이 덜어내야 한다",
                     "압축하면 가능하다", "무리 없이 설명된다",
                     "한두 장면으로 보여줄 수 있다"],
    },
    "relatability": {
        "type": "score",
        "instructions": "일반 시청자가 자기 일로 느낄 만한가?",
        "criteria": ["완전히 남의 일이다", "먼 이야기다", "관심은 간다",
                     "가까운 이야기다", "내 일상과 직결된다"],
    },
    "significance": {
        "type": "score",
        "instructions": "학술적·사회적으로 다룰 만한 무게가 있는가?",
        "criteria": ["사소하다", "작은 진전이다", "의미 있다",
                     "중요하다", "분야를 바꾼다"],
    },
    "visualizable": {
        "type": "noul",
        "instructions": "이 내용을 3D 도해나 실사 장면으로 **그려서** 설명할 수 있는가?",
        "criteria": {"true": "눈에 보이는 물체·과정이 있다",
                     "false": "추상적 수치·개념뿐이라 그림이 안 나온다"},
    },
    # ★ 대표 판단 — 최초 구상의 next-route 에 해당한다. 지금은 **측정만** 한다.
    "route": {
        "type": "choice",
        "instructions": "이 후보를 다음에 어디로 보낼 것인가?",
        "criteria": {
            "strong": "바로 제작 후보로 올릴 만하다",
            "candidate": "후보로 둘 만하다",
            "backlog": "지금은 아니지만 버리지는 않는다",
            "drop": "제작 가치가 없다",
        },
    },
}


def ask_all(title: str, venue: str | None, abstract: str) -> dict[str, Any] | None:
    """축 전부를 **한 호출**로. 못 물었으면 None."""
    state = f"제목: {title}\n게재처: {venue or '-'}\n초록: {abstract}"
    data = decide._post({
        "model": config.JEV_MODEL,
        "state": state[:config.JEV_STATE_MAX_CHARS],
        "questions": QUESTIONS,
    })
    if not data:
        return None
    decide._record(data.get("usage") or {}, str(data.get("model") or config.JEV_MODEL))
    return {"answers": data.get("answers") or {}, "usage": data.get("usage") or {}}


def _fmt(v: float | None) -> str:
    """판별력 표시. **None 은 0.5 로 속이지 않는다** — 못 잰 것과 동전 던지기는 다르다."""
    return "—" if v is None else f"{v:.3f}"


def _auc(pos: list[float], neg: list[float]) -> float | None:
    """순위 판별력. 0.5 = 동전 던지기. 표본이 한쪽뿐이면 None(0.5 로 속이지 않는다)."""
    if not pos or not neg:
        return None
    wins = sum((1 if a > b else 0.5 if a == b else 0) for a in pos for b in neg)
    return wins / (len(pos) * len(neg))


def load_labeled(limit: int) -> list[dict[str, Any]]:
    """사람이 판정한 논문 + 현행 채점 + 대본 여부. **읽기만 한다.**"""
    c = db.client()
    dec = {r["paper_id"]: r["status"]
           for r in (c.table("decisions").select("paper_id,status").execute().data or [])}
    ids = list(dec)[:limit] if limit else list(dec)
    papers, scores, drafted = {}, {}, set()
    for i in range(0, len(ids), 150):        # ★ `.in_()` 은 350~400개에서 죽는다(CLAUDE.md)
        chunk = ids[i:i + 150]
        for r in (c.table("papers").select("id,title,venue,abstract")
                  .in_("id", chunk).execute().data or []):
            papers[r["id"]] = r
        for r in (c.table("scores").select(
                "paper_id,fun_index,importance_index,surprise,explainability,"
                "relatability,significance").in_("paper_id", chunk).execute().data or []):
            scores[r["paper_id"]] = r
        for r in (c.table("drafts").select("paper_id")
                  .in_("paper_id", chunk).execute().data or []):
            drafted.add(r["paper_id"])
    out = []
    for pid in ids:
        p = papers.get(pid)
        if not p or not (p.get("abstract") or "").strip():
            continue
        out.append({"paper": p, "label": dec[pid], "score": scores.get(pid),
                    "drafted": pid in drafted})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Jev 그림자 평가 — 운영 무변경, 읽기 전용")
    ap.add_argument("--limit", type=int, default=0, help="대상 수(0=라벨 전수)")
    ap.add_argument("--dry-run", action="store_true", help="호출 0 — 질문지와 대상만 본다")
    args = ap.parse_args()

    rows = load_labeled(args.limit)
    lab = collections.Counter(r["label"] for r in rows)
    print(f"대상 {len(rows)}건 · 라벨 {dict(lab)} · 대본까지 간 것 "
          f"{sum(1 for r in rows if r['drafted'])}건")
    est = len(rows) * 1700 * config.TEXT_PRICING["jev-latest"]["text_input_per_token"]
    print(f"예상 비용 ${est:.4f} (입력만 과금 · 출력 0)\n")
    print("묻는 것:", ", ".join(f"{k}({v['type']})" for k, v in QUESTIONS.items()))
    if args.dry_run:
        print("\n--dry-run — 아무것도 호출하지 않았다.")
        return
    if not decide.enabled():
        raise SystemExit("JEV 가 꺼져 있다. JEV_ENABLED=1 로 이 스크립트만 켜라 "
                         "(운영 기본값은 꺼짐 그대로 둔다).")

    got: list[dict[str, Any]] = []
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        p = r["paper"]
        res = ask_all(p.get("title") or "", p.get("venue"), p.get("abstract") or "")
        if res is None:
            log.warning("판정 실패(건너뜀): %s", p["id"][:8])
            continue
        got.append({**r, "jev": res["answers"], "usage": res["usage"]})
        if i % 25 == 0:
            print(f"  {i}/{len(rows)} … {time.time() - t0:.0f}초")
        time.sleep(0.08)
    el = time.time() - t0
    if not got:
        raise SystemExit("판정을 하나도 못 받았다 — 배선을 먼저 확인하라")

    # ── 대조 ────────────────────────────────────────────────────
    pos = [g for g in got if g["label"] in ("picked", "shortlisted")]
    neg = [g for g in got if g["label"] == "rejected"]
    if not (pos and neg):
        # ★ 한쪽만 있으면 판별력은 **정의되지 않는다.** 0.5 를 찍어 "동전 던지기"처럼
        #   보이게 하면 그게 거짓말이다 — 표본이 없다는 사실을 그대로 말한다.
        print(f"\n⚠ 낙점·보류 {len(pos)}건 · 탈락 {len(neg)}건 — 한쪽이 비어 AUC 를 낼 수 없다."
              f" --limit 를 키우거나 빼라(라벨 전수 256건).")

    def jv(g: dict[str, Any], axis: str) -> float:
        """Jev 답 → 비교용 숫자.

        ★ `score` 는 **레벨 인덱스의 확률가중 평균**이라 0..(단계수-1) 범위다. 현행 0~10 과
          같은 자로 재려면 환산해야 한다 — 안 하면 AUC 는 순위만 보니 같지만, 값을 눈으로
          비교할 때 "Jev 가 늘 낮다"는 착시가 생긴다.
        """
        a = (g["jev"] or {}).get(axis) or {}
        if isinstance(a.get("score"), (int, float)):
            levels = len(QUESTIONS[axis]["criteria"])
            return float(a["score"]) / max(levels - 1, 1) * 10.0
        for k in ("noul", "confidence"):
            if isinstance(a.get(k), (int, float)):
                return float(a[k])
        return 0.0

    print(f"\n{'축':16} {'Jev AUC':>9} {'현행 AUC':>9}  판정")
    print("-" * 52)
    report: dict[str, Any] = {"n": len(got), "elapsed_sec": round(el, 1)}
    for axis in ("surprise", "explainability", "relatability", "significance"):
        j = _auc([jv(g, axis) for g in pos], [jv(g, axis) for g in neg])
        cur = _auc([float((g["score"] or {}).get(axis) or 0) for g in pos if g["score"]],
                   [float((g["score"] or {}).get(axis) or 0) for g in neg if g["score"]])
        verdict = ("Jev 우세" if j and cur and j > cur + 0.03 else
                   "현행 우세" if j and cur and cur > j + 0.03 else "차이 없음")
        print(f"{axis:16} {_fmt(j):>9} {_fmt(cur):>9}  {verdict}")
        report[f"auc_{axis}"] = {"jev": j, "current": cur}
    jvis = _auc([jv(g, "visualizable") for g in pos], [jv(g, "visualizable") for g in neg])
    print(f"{'visualizable':16} {_fmt(jvis):>9} {'—':>9}  (현행에 대응 축 없음)")
    report["auc_visualizable"] = jvis

    # ── ★ 제일 중요한 것: 좋은 후보를 버리는가 ──────────────────
    def route(g: dict[str, Any]) -> str:
        a = (g["jev"] or {}).get("route") or {}
        return str(a.get("choice") or "?")

    rt = collections.Counter((g["label"], route(g)) for g in got)
    print("\n사람 판정 × Jev route")
    print(f"   {'':12} {'strong':>7} {'candidate':>10} {'backlog':>8} {'drop':>6}")
    for lb in ("picked", "shortlisted", "rejected"):
        cells = [rt[(lb, r)] for r in ("strong", "candidate", "backlog", "drop")]
        print(f"   {lb:12} {cells[0]:>7} {cells[1]:>10} {cells[2]:>8} {cells[3]:>6}")

    dropped_good = [g for g in got if g["label"] == "picked" and route(g) == "drop"]
    dropped_made = [g for g in dropped_good if g["drafted"]]
    print(f"\n★ 낙점을 Jev 가 drop 으로 본 것: {len(dropped_good)}건"
          f" (그중 실제로 대본까지 간 것 **{len(dropped_made)}건**)")
    print("   ↑ 이 숫자가 0 에 가깝지 않으면 **hard drop 을 허용하면 안 된다.**")
    report["high_value_false_negative"] = len(dropped_good)
    report["false_negative_that_shipped"] = len(dropped_made)

    tin = sum(int((g["usage"] or {}).get("input_tokens") or 0) for g in got)
    cost = tin * config.TEXT_PRICING["jev-latest"]["text_input_per_token"]
    print(f"\n{len(got)}건 · {el:.0f}초 (건당 {el / len(got) * 1000:.0f}ms) · "
          f"입력 {tin:,} 토큰 = ${cost:.4f}")
    report.update({"input_tokens": tin, "cost_usd": round(cost, 6),
                   "ms_per_item": round(el / len(got) * 1000)})

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"jev-shadow-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(
        {"report": report,
         "rows": [{"paper_id": g["paper"]["id"], "label": g["label"],
                   "drafted": g["drafted"], "route": route(g),
                   "jev": g["jev"], "current": g["score"]} for g in got]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
