"""채점 축은 사람 판정을 예측하는가 — **호출 0원**의 사후 감사 (2026-09-22).

왜 이걸 재나
-----------
Jev 그림자 평가(`scripts/jev_shadow.py`)가 부수적으로 더 큰 것을 드러냈다:
**현행 채점이 사람 판정을 거의 못 가른다.** AUC 0.566~0.623 — 0.5 가 동전 던지기다.

그래서 모델을 바꾸기 전에 물어야 할 것이 있다. **축이 옳은 것을 재고 있는가.**
이 스크립트는 저장된 것만 읽어 그 질문에 답한다. LLM 을 한 번도 부르지 않는다(0원).

무엇을 읽나 (전부 읽기 전용)
--------------------------
    decisions   사람이 누른 것 — 정답지
    scores      현행 채점 4축 + 제작준비도 6축 + 지수
    daily_batch 그날 상위 N 에 **어떤 순위로** 올랐는가
    papers      게재처·출처·초록 길이 등 채점과 무관한 것들

세 가지를 잰다
------------
① **판별력(AUC)** — 축 하나하나가 낙점/탈락을 얼마나 가르는가.
   ★ 다변량 회귀를 쓰지 않는다. 표본이 256건이고 축이 열이 넘어 과적합이 쉽다.
     한 축씩 보는 것이 이 표본 크기에 맞고, 사람이 읽을 수 있다.

② **순위가 쓸모 있나** — 채점의 실제 쓰임은 절대 점수가 아니라 **그날 20편의 순서**다.
   ★★ 여기서 함정이 하나 있고, 이 스크립트를 쓰면서 걸렸다: `daily_batch.rank` 는
     **품질 순서가 아니다.** `batch.build_batch_rows` 가 재미·중요·황금 **세 정렬의
     1등을 번갈아 뽑아** 붙인 자리 번호라, 1위=재미 1등 / 2위=중요 1등 / 3위=황금 1등이다.
     대시보드는 그 번호 순으로 세로로 내려 보여 준다(`web/lib/queries.ts`).
     그래서 `rank` 로 잰 값은 "순서가 쓸모 있나"의 답이 아니다 —
     **그날 후보를 지수로 다시 줄세운 뒤** 낙점이 어디 있었는지를 따로 잰다.

③ **채점 밖의 것** — 게재처·출처·초록 길이처럼 채점이 안 보는 것이 낙점을 예측하면,
   그건 "사람은 다른 것을 보고 있다"는 증거다.

④ **축이 살아 있나** — 값이 안 퍼지거나(같은 숫자만 나온다) 늘 0이면, 그 축은 켜져
   있어도 판정에 기여하지 않는다. 채점 실패로 0점 처리된 행도 같은 자리에서 센다 —
   0점 행은 **영영 순위에 못 오르는데** 화면에서는 그냥 점수 낮은 논문처럼 보인다.

그리고 **눈으로 볼 표본**을 뽑는다 — 점수는 높은데 버린 것, 점수는 낮은데 고른 것.
숫자가 아니라 그 논문들을 봐야 축이 무엇을 놓치는지 보인다.

사용:
    python -m scripts.score_axis_audit            # 전부
    python -m scripts.score_axis_audit --examples 12
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config, db  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")

#: 낙점 쪽으로 세는 라벨. shortlisted 는 "버리지 않았다"이므로 낙점 쪽이다.
POSITIVE = ("picked", "shortlisted")


# ─────────────────────────────────────────────────────────────
# 읽기 — CLAUDE.md 의 두 상한을 둘 다 피한다
#   `.in_()` 은 id 350~400 개에서 죽고, `select()` 는 1,000 행에서 조용히 잘린다.
# ─────────────────────────────────────────────────────────────
def _all(table: str, cols: str, page: int = 1000) -> list[dict[str, Any]]:
    c, out, off = db.client(), [], 0
    while True:
        rows = (c.table(table).select(cols).range(off, off + page - 1).execute().data or [])
        out.extend(rows)
        if len(rows) < page:
            return out
        off += page


def _by_ids(table: str, cols: str, ids: list[str], key: str = "id") -> dict[str, dict]:
    c, out = db.client(), {}
    for i in range(0, len(ids), 150):
        for r in (c.table(table).select(cols).in_(key, ids[i:i + 150]).execute().data or []):
            out[r[key]] = r
    return out


def load() -> tuple[list[dict[str, Any]], dict[str, list[dict]], dict[str, str], dict[str, dict]]:
    """(판정된 논문들, 배치일→그날 목록, 전체 판정, 전체 채점). 전부 읽기 전용."""
    decs = _all("decisions", "paper_id,status,decided_at,note")
    ids = [d["paper_id"] for d in decs]
    papers = _by_ids("papers", "id,title,venue,abstract,source,published_date", ids)
    scores = _by_ids("scores", "paper_id,surprise,explainability,relatability,significance,"
                               "buzz,fun_index,importance_index,production,title_ko,"
                               "one_liner_ko,rationale,red_flag,model",
                     ids, key="paper_id")
    drafted = set()
    for i in range(0, len(ids), 150):
        for r in (db.client().table("drafts").select("paper_id")
                  .in_("paper_id", ids[i:i + 150]).execute().data or []):
            drafted.add(r["paper_id"])

    batch = _all("daily_batch", "batch_date,paper_id,rank,sort_mode")
    by_date: dict[str, list[dict]] = collections.defaultdict(list)
    rank_of: dict[str, tuple[str, int]] = {}
    for b in batch:
        by_date[b["batch_date"]].append(b)
        # 같은 논문이 여러 날 오르면 **가장 이른 날**을 쓴다(그날 결정이 그날 목록에서 났다).
        cur = rank_of.get(b["paper_id"])
        if cur is None or b["batch_date"] < cur[0]:
            rank_of[b["paper_id"]] = (b["batch_date"], int(b["rank"]))
    for d in by_date.values():
        d.sort(key=lambda r: int(r["rank"]))

    rows = []
    for d in decs:
        pid = d["paper_id"]
        p, s = papers.get(pid), scores.get(pid)
        if not p:
            continue
        rows.append({"id": pid, "label": d["status"], "note": d.get("note") or "",
                     "paper": p, "score": s, "drafted": pid in drafted,
                     "batch": rank_of.get(pid)})

    labels = {d["paper_id"]: d["status"] for d in decs}
    # ④ 는 판정된 256건이 아니라 **채점된 전부**를 봐야 한다 — 죽은 축은 거기서 보인다.
    all_scores = {r["paper_id"]: r for r in _all(
        "scores", "paper_id,surprise,explainability,relatability,significance,"
                  "buzz,fun_index,importance_index,red_flag,model")}
    return rows, by_date, labels, all_scores


# ─────────────────────────────────────────────────────────────
# 특징 추출 — 채점이 보는 것과 **안 보는 것**을 나란히 둔다
# ─────────────────────────────────────────────────────────────
_PROD = config.PRODUCTION_AXES


def features(r: dict[str, Any]) -> dict[str, float | None]:
    s, p = r["score"] or {}, r["paper"]
    f: dict[str, float | None] = {}
    for k in ("surprise", "explainability", "relatability", "significance",
              "buzz", "fun_index", "importance_index"):
        v = s.get(k)
        f[k] = float(v) if isinstance(v, (int, float)) else None
    f["golden_index"] = None
    if f["fun_index"] is not None and f["importance_index"] is not None:
        f["golden_index"] = f["fun_index"] * f["importance_index"]
    prod = s.get("production") if isinstance(s.get("production"), dict) else {}
    axes = prod.get("axes") if isinstance(prod.get("axes"), dict) else {}
    tot = 0.0
    for k in _PROD:
        v = (axes.get(k) or {}).get("score")
        f["제작." + k] = float(v) if isinstance(v, (int, float)) else None
        tot += float(v or 0)
    f["제작.총점"] = tot if axes else None
    # ── 채점이 **안 보는** 것들 ────────────────────────────────
    f["[밖]초록길이"] = float(len(p.get("abstract") or "")) or None
    f["[밖]제목길이"] = float(len(p.get("title") or "")) or None
    f["[밖]빨간깃발있음"] = 1.0 if str(s.get("red_flag") or "").strip() else 0.0
    f["[밖]배치순위(역)"] = None
    if r["batch"]:
        f["[밖]배치순위(역)"] = float(-r["batch"][1])   # 1위가 가장 큼
    return f


def auc(pairs: list[tuple[float, int]]) -> float | None:
    """확률적 우위. 0.5=동전. 동점은 0.5 로 센다(Mann–Whitney U 와 같다)."""
    pos = [v for v, y in pairs if y == 1]
    neg = [v for v, y in pairs if y == 0]
    if not pos or not neg:
        return None
    win = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
    return win / (len(pos) * len(neg))


def report_auc(rows: list[dict[str, Any]]) -> None:
    lab = {r["id"]: (1 if r["label"] in POSITIVE else 0) for r in rows}
    feats = {r["id"]: features(r) for r in rows}
    keys = list(next(iter(feats.values())))
    print("① 축 하나가 낙점/탈락을 얼마나 가르는가 (AUC · 0.5 = 동전 던지기)")
    print("   대상 %d건 · 낙점쪽 %d · 탈락 %d\n"
          % (len(rows), sum(lab.values()), len(rows) - sum(lab.values())))
    scored = []
    for k in keys:
        pairs = [(feats[i][k], lab[i]) for i in feats if feats[i].get(k) is not None]
        a = auc(pairs)
        if a is not None:
            scored.append((abs(a - 0.5), a, k, len(pairs)))
    scored.sort(reverse=True)
    print("   %-22s%8s  %5s   판별력" % ("축", "AUC", "표본"))
    for _, a, k, n in scored:
        bar = "█" * int(abs(a - 0.5) * 60)
        flip = " ←역방향" if a < 0.5 else ""
        print("   %-22s%8.3f  %5d   %s%s" % (k, a, n, bar, flip))
    print("\n   ※ 역방향 = 점수가 **낮을수록** 낙점된다는 뜻이다.")


def report_rank(rows: list[dict[str, Any]], by_date: dict[str, list[dict]],
                labels: dict[str, str], idx: dict[str, dict]) -> None:
    """② 순서가 실제로 쓰이는가 — **지수로 다시 줄세워** 잰다."""
    print("\n\n② 그날 후보를 지수로 다시 줄세우면 낙점은 어디에 있나")
    print("   (화면의 자리 번호는 세 정렬의 라운드로빈이라 품질 순서가 아니다)\n")

    # ── ②-1 선정 사유 모드별 낙점률: 세 정렬 중 어느 것이 일하는가
    tot, pick = collections.Counter(), collections.Counter()
    for day in by_date.values():
        for b in day:
            tot[b["sort_mode"]] += 1
            if labels.get(b["paper_id"]) == "picked":
                pick[b["sort_mode"]] += 1
    print("   [어느 정렬이 데려온 후보가 뽑히나]")
    for m in config.SORT_MODES:
        n = tot[m] or 1
        print("     %-11s %3d/%4d = %5.1f%%" % (m, pick[m], tot[m], 100 * pick[m] / n))

    # ── ②-2 그날 후보를 지수로 다시 정렬한 뒤 낙점의 백분위
    def golden(pid: str) -> float:
        s = idx.get(pid) or {}
        return float(s.get("fun_index") or 0) * float(s.get("importance_index") or 0)

    def fun(pid: str) -> float:
        return float((idx.get(pid) or {}).get("fun_index") or 0)

    print("\n   [낙점된 것이 그날 몇 번째였나]")
    for name, key in (("황금지수", golden), ("재미지수", fun)):
        pcts, top1 = [], 0
        for day in by_date.values():
            order = sorted(day, key=lambda b: -key(b["paper_id"]))
            for i, b in enumerate(order, 1):
                if labels.get(b["paper_id"]) == "picked":
                    pcts.append(i / len(order))
                    top1 += (i == 1)
        if pcts:
            print("     %-8s 낙점 %3d건 · 평균 상위 %2.0f%% (무작위 50%%) · 1위 적중 %d건(%.1f%%)"
                  % (name, len(pcts), 100 * sum(pcts) / len(pcts), top1, 100 * top1 / len(pcts)))

    # ── ②-3 동점: 같은 점수면 순서는 사실상 무작위다
    ties = []
    for day in by_date.values():
        g = [round(golden(b["paper_id"]), 4) for b in day]
        ties.append(len(g) - len(set(g)))
    if ties:
        print("\n   [동점] 하루 안에서 황금지수가 겹친 편수 평균 %.1f편 (최대 %d편)"
              % (sum(ties) / len(ties), max(ties)))
        print("     ※ 동점이면 화면 순서는 사실상 무작위다 — 채점이 갈라 주지 못한 것이다.")

    per_day = collections.defaultdict(int)
    for r in rows:
        if r["batch"] and r["label"] == "picked":
            per_day[r["batch"][0]] += 1
    multi = sum(1 for v in per_day.values() if v > 1)
    print("\n   하루에 2건 이상 낙점한 날 %d일 / 낙점이 있는 날 %d일" % (multi, len(per_day)))


def report_alive(idx: dict[str, dict]) -> None:
    """④ 축이 살아 있나 — 전 채점 행을 본다(판정된 256건만이 아니라)."""
    rows = list(idx.values())
    print("\n\n④ 축이 살아 있나 — 저장된 채점 %d행 전부" % len(rows))
    fails = [r for r in rows if "채점 실패" in str(r.get("red_flag") or "")]
    print("\n   [채점 실패로 0점이 된 행] %d행 (%.1f%%)"
          % (len(fails), 100 * len(fails) / max(1, len(rows))))
    if fails:
        why = collections.Counter(str(r.get("red_flag"))[:44] for r in fails)
        for k, v in why.most_common(4):
            print("     %-46s %d행" % (k, v))
        print("     ※ 0점 행은 **영영 후보에 못 오른다.** 화면에서는 그냥 점수 낮은 논문으로 보인다.")
    print("\n   [축별 분포 — 표준편차가 작으면 그 축은 갈라 주지 않는다]")
    for ax in ("surprise", "explainability", "relatability", "significance", "buzz"):
        v = [float(r[ax]) for r in rows if isinstance(r.get(ax), (int, float))]
        if not v:
            continue
        mean = sum(v) / len(v)
        sd = (sum((x - mean) ** 2 for x in v) / len(v)) ** 0.5
        zero = sum(1 for x in v if x == 0)
        hist = collections.Counter(int(round(x)) for x in v)
        top = " ".join("%d점:%d" % (k, hist[k]) for k, _ in hist.most_common(3))
        print("     %-15s 평균 %4.2f  표준편차 %4.2f  0점 %5.1f%%   가장 흔한 값 %s"
              % (ax, mean, sd, 100 * zero / len(v), top))
    g = [float(r.get("fun_index") or 0) * float(r.get("importance_index") or 0) for r in rows]
    print("\n   황금지수가 실제로 가지는 서로 다른 값 %d개 / %d행"
          % (len({round(x, 4) for x in g}), len(g)))


def report_examples(rows: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """③ 눈으로 볼 표본 — 숫자가 아니라 논문을 봐야 축이 뭘 놓치는지 보인다."""
    have = [r for r in rows if (r["score"] or {}).get("fun_index") is not None]
    for r in have:
        s = r["score"]
        r["_g"] = float(s["fun_index"]) * float(s["importance_index"] or 0)
    hi_rej = sorted([r for r in have if r["label"] == "rejected"],
                    key=lambda r: -r["_g"])[:k]
    lo_pick = sorted([r for r in have if r["label"] == "picked"],
                     key=lambda r: r["_g"])[:k]
    out = []
    for tag, group in (("점수는높은데_버림", hi_rej), ("점수는낮은데_고름", lo_pick)):
        for r in group:
            s = r["score"]
            prod = (s.get("production") or {}).get("axes") or {}
            out.append({
                "구분": tag,
                "제목": s.get("title_ko") or r["paper"].get("title"),
                "원제": r["paper"].get("title"),
                "한줄": s.get("one_liner_ko"),
                "게재처": r["paper"].get("venue"),
                "황금지수": round(r["_g"], 2),
                "축": {a: s.get(a) for a in
                       ("surprise", "explainability", "relatability", "significance")},
                "제작준비도": {a: (prod.get(a) or {}).get("score") for a in _PROD},
                "채점이유": s.get("rationale"),
                "빨간깃발": s.get("red_flag"),
                "그날순위": r["batch"][1] if r["batch"] else None,
                "대본까지감": r["drafted"],
                "운영자메모": r["note"],
                "id": r["id"],
            })
    return out


_AX_KO = {"surprise": "의외성", "explainability": "이해가능성",
          "relatability": "일상연결", "significance": "학술중요"}


def write_md(ex: list[dict[str, Any]], path: pathlib.Path) -> None:
    """눈으로 볼 표본을 **읽을 수 있는 형태로** 적는다. JSON 은 사람이 안 읽는다."""
    L = ["# 채점 축 감사 — 눈으로 볼 표본", "",
         "채점이 높게 본 것을 사람이 버렸고, 낮게 본 것을 사람이 골랐다.",
         "그 두 무더기를 나란히 둔다. **숫자가 아니라 논문을 봐야** 축이 뭘 놓치는지 보인다.",
         "", "생성: `python -m scripts.score_axis_audit` (읽기 전용·0원)", ""]
    for tag, title in (("점수는높은데_버림", "## ① 채점은 높게 봤는데 사장님이 버린 것"),
                       ("점수는낮은데_고름", "## ② 채점은 낮게 봤는데 사장님이 고른 것")):
        L += [title, ""]
        for e in [x for x in ex if x["구분"] == tag]:
            ax = " / ".join("%s %s" % (_AX_KO[k], e["축"].get(k))
                            for k in ("surprise", "explainability",
                                      "relatability", "significance"))
            L += ["### %s" % (e["제목"] or e["원제"]),
                  "",
                  "- **한 줄**: %s" % (e["한줄"] or "—"),
                  "- **황금지수 %.1f** · %s" % (e["황금지수"], ax),
                  "- 게재처: %s · 대본까지 감: %s" % (e["게재처"] or "—",
                                                "예" if e["대본까지감"] else "아니오"),
                  "- 채점 이유: %s" % (e["채점이유"] or "—"),
                  ]
            if e["빨간깃발"]:
                L.append("- 빨간깃발: %s" % e["빨간깃발"])
            if e["운영자메모"]:
                L.append("- 사장님 메모: %s" % e["운영자메모"])
            L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="채점 축 사후 감사 — 읽기 전용·0원")
    ap.add_argument("--examples", type=int, default=8, help="구분별 표본 수")
    args = ap.parse_args()

    rows, by_date, labels, all_scores = load()
    print("판정 %d건 · 라벨 %s" % (len(rows), dict(collections.Counter(r["label"] for r in rows))))
    missing = sum(1 for r in rows if not r["score"])
    if missing:
        print("※ 채점 행이 없는 것 %d건은 AUC 에서 빠진다." % missing)
    print()
    report_auc(rows)
    report_rank(rows, by_date, labels, all_scores)
    report_alive(all_scores)
    ex = report_examples(rows, args.examples)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "채점축_감사.json"
    p.write_text(json.dumps(ex, ensure_ascii=False, indent=2), encoding="utf-8")
    md = OUT / "채점축_감사.md"
    write_md(ex, md)
    print("\n\n③ 눈으로 볼 표본 %d건 → %s\n                        → %s" % (len(ex), md, p))


if __name__ == "__main__":
    main()
