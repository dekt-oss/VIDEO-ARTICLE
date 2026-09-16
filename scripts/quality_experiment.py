"""품질 실측 발주서 — 유료 API 없이 **웹에서 직접** 돌린다 (v2 Phase G).

무엇을 푸는가: 작업명세서의 G2·G3·G4 는 "8초가 실제로 좋은가", "후보 2발이 실제로
나은가"를 **비교로** 판정한다. 그런데 그건 유료 렌더이고, 운영자는 Gemini/Veo 웹에서
같은 것을 **무료로** 만들 수 있다. 그러면 남는 일은 둘뿐이다(web_order 와 같은 구조):

    ① 파이프라인이 보낼 프롬프트를 **그대로** 뽑아 짝지어 준다   (order)
    ② 받아온 파일을 **코드가 채점**한다                          (judge)

★★ ②가 핵심이다. 눈으로 "좋아 보인다"는 인상평이고, 리뷰 §16 이 그것을 경계했다:
  "이 지표가 없으면 '8초라서 좋아 보인다'는 인상평 수준을 벗어나기 어렵다."
  그래서 채점은 렌더 파이프라인이 쓰는 **바로 그 함수**(`clip_candidates`)로 한다 —
  후보 선택에 쓰는 잣대와 최종 평가의 잣대가 다르면 서로를 반박한다.

★ 실험은 **한 가지만 바꾼다**(paired). G2 는 길이만, G4 는 후보 수만.
  프롬프트·시작 이미지·모델이 같아야 차이가 그 하나에서 왔다고 말할 수 있다.

사용:
    python -m scripts.quality_experiment order G2   # 4초 vs 8초 발주서
    python -m scripts.quality_experiment order G4   # 1발 vs 2발 발주서
    python -m scripts.quality_experiment judge G2   # 받은 파일 채점
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import clip_candidates, config, temporal_plan  # noqa: E402
from engine.providers import video as video_provider  # noqa: E402
from scripts.web_order import _load, _ensure_ffmpeg, _mp4_duration  # noqa: E402

ROOT = pathlib.Path("docs/실측_품질")

# 실험 정의. **한 번에 한 축만** 바꾼다 — 두 개를 같이 바꾸면 원인을 못 가른다.
EXPERIMENTS: dict[str, dict] = {
    "G2": {
        "title": "길이 실측 — 4초 vs 8초",
        "question": "같은 장면·같은 프롬프트에서 **8초가 4초보다 실제로 나은가?**",
        "arms": [{"key": "A_4s", "clip_sec": 4, "label": "4초"},
                 {"key": "B_8s", "clip_sec": 8, "label": "8초"}],
        "note": ("★ 8초 쪽에만 연출 계약(비트)이 붙는다 — 그것이 invest 등급의 내용이다.\n"
                 "  4초 쪽은 지금 파이프라인이 보내는 문장 그대로다."),
    },
    "G4": {
        "title": "후보 실측 — 1발 vs 2발 선택",
        "question": "같은 8초에서 **두 번 뽑아 고르는 것**이 한 번 뽑는 것보다 나은가?",
        "arms": [{"key": "A_take1", "clip_sec": 8, "label": "1번째"},
                 {"key": "B_take2", "clip_sec": 8, "label": "2번째(같은 프롬프트 재생성)"}],
        "note": ("★ 두 팔의 프롬프트가 **완전히 같다.** 생성이 확률적이라는 것을 재는 실험이라\n"
                 "  같아야 한다. 벤치마크의 '8초를 뽑아 좋은 3초만 쓴다'가 이 가정 위에 있다."),
    },
}

# 8초 팔에 붙일 연출 계약. 벤치마크 문법(전체 → 따라가기 → 급속 푸시인) 그대로.
DEMO_BEATS = [
    {"t0": 0.0, "t1": 2.5, "entity_id": "ROCKET_STAGE", "mutation": "APPEAR", "camera": "DOLLY_OUT"},
    {"t0": 2.5, "t1": 5.5, "entity_id": "ROCKET_STAGE", "mutation": "MOVE", "camera": "TRACK"},
    {"t0": 5.5, "t1": 8.0, "entity_id": "CRATER", "mutation": "IMPACT", "camera": "DOLLY_IN"},
]


def _cut_for(arm: dict, base_cut: dict) -> dict:
    """이 팔의 컷. 바꾸는 것은 **연출 계약 유무**뿐이고 나머지는 원본 그대로다."""
    cut = dict(base_cut)
    if arm["clip_sec"] >= 8:
        cut["temporal_plan"] = temporal_plan.normalize(DEMO_BEATS, arm["clip_sec"])
    else:
        cut["temporal_plan"] = []
    return cut


def cmd_order(exp_key: str, tag: str, cut_no: int) -> None:
    spec = EXPERIMENTS[exp_key]
    mini = _load(tag, 6, True)
    header = mini["header"]
    base = next((c for c in mini["cuts"] if int(c["cut_no"]) == cut_no), mini["cuts"][0])
    out = ROOT / exp_key
    (out / "입력").mkdir(parents=True, exist_ok=True)

    L = [f"# 품질 실측 발주서 — {exp_key}: {spec['title']}", "",
         f"> **묻는 것:** {spec['question']}", "",
         spec["note"], "",
         "## 만드는 법", "",
         "- 도구: **Veo(Gemini 웹)**, 비율 **9:16 세로**",
         "- **시작 이미지는 두 팔이 같아야 한다.** 아래 `시작.png` 하나를 만들어 **양쪽에 같이** 쓴다.",
         "- 각 팔의 프롬프트를 그대로 붙여넣고, 지정된 **길이**로 생성한다.",
         f"- 나온 파일을 `{out / '입력'}` 에 아래 이름으로 저장:", ""]
    for arm in spec["arms"]:
        L.append(f"    - {arm['label']} → **`{arm['key']}.mp4`**")
    L += ["", "다 넣으신 뒤 알려주시면 **코드가 채점**합니다:", "",
          "```bash", f"python -m scripts.quality_experiment judge {exp_key}", "```", "",
          "---", "", "## 0번 → `시작.png` (두 팔 공용 시작 이미지)", "",
          "```", base.get("visual_prompt") or "", ", vertical 9:16 portrait, no text, no numbers", "```", "",
          "---", ""]

    for arm in spec["arms"]:
        cut = _cut_for(arm, base)
        prompt = video_provider.build_motion_prompt(cut, header)
        L += [f"## {arm['label']} → `{arm['key']}.mp4`  (시작.png 첨부)", "",
              f"- 길이: **{arm['clip_sec']}초**",
              f"- 연출 계약: {'있음 (비트 %d개)' % len(cut['temporal_plan'])
                              if cut['temporal_plan'] else '없음'}", "",
              "```", prompt, "```", "", "---", ""]

    path = out / "발주서.md"
    path.write_text("\n".join(L), encoding="utf-8")
    (out / "실험.json").write_text(json.dumps(
        {"experiment": exp_key, "tag": tag, "cut_no": int(base["cut_no"]),
         "arms": spec["arms"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"발주서: {path}")
    print(f"받은 파일 넣을 곳: {out / '입력'}")


def cmd_judge(exp_key: str) -> None:
    """받은 클립을 **코드가** 채점한다. 인상평이 아니라 숫자로 답한다."""
    _ensure_ffmpeg()
    out = ROOT / exp_key
    meta = json.loads((out / "실험.json").read_text(encoding="utf-8"))
    rows = []
    for arm in meta["arms"]:
        path = out / "입력" / f"{arm['key']}.mp4"
        if not path.exists():
            print(f"  ✗ 없음: {path}")
            continue
        # ★★ **길이를 실제로 잰다.** 라벨을 믿고 채점하면 도구가 거짓말을 한다 —
        #   2026-08-31 실측: Gemini 웹이 요청 길이를 무시하고 **양쪽 다 10.01초**를 냈다.
        #   그 상태로 "4초 vs 8초" 라고 적으면 없는 실험을 했다고 기록하는 것이다.
        actual = _mp4_duration(str(path))
        mismatch = abs(actual - float(arm["clip_sec"])) > 0.6
        sig = clip_candidates.probe_motion(str(path), actual or arm["clip_sec"])
        sc = clip_candidates.score(sig, min_beats=config.tier_profile("invest")["min_beats"])
        # ★ 스프레드를 **먼저** 놓는다. `sig` 안에도 `clip_sec` 키가 있어서 뒤에 두면
        #   요청값이 실측값으로 덮여, "요청 10초인데 실제 10초"라는 무의미한 경고가 뜬다
        #   (실제로 그렇게 나왔다 — 도구가 자기 경고를 스스로 무력화한 셈이다).
        rows.append({**sig, **sc,
                     "arm": arm["key"], "label": arm["label"],
                     "requested_sec": arm["clip_sec"], "actual_sec": actual,
                     "length_not_controlled": mismatch})

    if not rows:
        raise SystemExit("채점할 파일이 없다. 발주서대로 입력/ 에 넣어라.")
    print(f"\n=== {exp_key}: {EXPERIMENTS[exp_key]['title']}")
    print(f"    {EXPERIMENTS[exp_key]['question']}\n")
    for r in rows:
        if not r["measured"]:
            print(f"  {r['label']:<22} 측정 실패(ffmpeg) — 판정 불가")
            continue
        warn = (f"  ⚠ 요청 {r['requested_sec']}초인데 실제 {r['actual_sec']:.2f}초"
                if r["length_not_controlled"] else "")
        drift = r.get("world_drift", -1.0)
        dtxt = "판정불가" if drift < 0 else f"{drift:.3f}"
        med = r.get("motion_median", -1.0)
        mtxt = "판정불가" if med < 0 else f"{med:.5f}"
        print(f"  {r['label']:<22} 움직임(중앙) {mtxt:>9}  정지 {r['freeze_ratio']*100:4.1f}%  "
              f"전환 {r['scene_changes']:>2}  세계이탈 {dtxt:>6}  점수 {r['score']:.4f}{warn}")
    # ★ 조작 변인이 실제로 달라졌는지 먼저 확인한다. 안 달라졌으면 **이 실험은
    #   그 질문에 답하지 못한다** — 다른 숫자가 나와도 원인을 그것이라 말할 수 없다.
    #
    # ★ 두 가지를 갈라야 한다. "요청과 다르다"와 "**팔끼리 달라야 하는데 같다**"는
    #   전혀 다른 문제다:
    #     · 팔마다 다른 길이를 요청했는데 실제가 같다 → 조작 변인이 무너졌다(답 못 함)
    #     · 팔이 원래 같은 길이인데 요청값과만 다르다 → 두 팔이 **똑같이** 벗어난 것이라
    #       짝비교는 그대로 성립한다(공통 편차는 상쇄된다)
    if any(r["length_not_controlled"] for r in rows):
        actuals = {round(r["actual_sec"], 2) for r in rows}
        requested = {r["requested_sec"] for r in rows}
        print(f"\n  ⚠ 요청 {sorted(requested)}초 → 실제 {sorted(actuals)}초 "
              "(웹 도구가 길이를 고정한다)")
        if len(requested) > 1 and len(actuals) == 1:
            print("  ★★ **조작 변인이 무너졌다** — 팔마다 다른 길이를 요청했는데 실제가 같다.")
            print("     이 실험은 길이 질문에 답하지 못한다. 아래 점수차는 프롬프트 차이다.")
        elif len(actuals) == 1:
            print("  ★ 두 팔이 **똑같이** 벗어났다 — 공통 편차라 짝비교는 그대로 성립한다.")

    measured = [r for r in rows if r["measured"]]
    if len(measured) >= 2:
        best = max(measured, key=lambda r: r["score"])
        gap = best["score"] - min(r["score"] for r in measured)
        print(f"\n  → 우세: **{best['label']}** (점수차 {gap:.4f})")
        # ★ 표본 1로 크기를 말하지 않는다(작업명세서 §2 Phase G).
        print("  ★ 표본 1이다. 방향만 읽고 크기는 말하지 않는다.")
        if gap < config.CANDIDATE_MEANINGFUL_GAP:
            print(f"  ★ 점수차가 {config.CANDIDATE_MEANINGFUL_GAP} 미만 — **차이 없음**으로 읽는다.")
    drifts = [r.get("world_drift", -1.0) for r in rows if r.get("world_drift", -1.0) >= 0]
    if drifts and max(drifts) >= config.WORLD_DRIFT_NOTICE:
        print(f"\n  ⚠ 세계이탈 신호가 크다(최대 {max(drifts):.3f}).")
        print("     시작 프레임의 세계를 끝까지 유지하지 못했을 수 있다"
              " — **점수에는 안 들어간다**(표본 부족).")
    (out / "채점.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    print(f"\n기록: {out / '채점.json'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("order"); o.add_argument("exp", choices=sorted(EXPERIMENTS))
    o.add_argument("--tag", default="B"); o.add_argument("--cut", type=int, default=5)
    j = sub.add_parser("judge"); j.add_argument("exp", choices=sorted(EXPERIMENTS))
    a = ap.parse_args()
    if a.cmd == "order":
        cmd_order(a.exp, a.tag, a.cut)
    else:
        cmd_judge(a.exp)


if __name__ == "__main__":
    main()
