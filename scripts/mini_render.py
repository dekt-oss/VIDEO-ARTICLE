"""Mini Render — 시퀀스 연속성만 재는 최소 렌더 (v3 Phase 4, 코덱스 리뷰 §19).

무엇을 푸는가: Phase 3 배선이 끝났지만 **화면에서 실제로 이어지는지는 아무도 모른다.**
그렇다고 11~15컷 전체를 바로 만들면, 첫 stage 에서 이미 틀렸어도 끝까지 다 만든 뒤에야
안다. 리뷰 §19 가 "full video 가 아니라 Mini Render 2개"를 요구한 이유다.

이 스크립트는 **이미 만들어진 지시서에서 시퀀스 하나를 잘라** 3~4컷만 렌더한다.
LLM 호출은 0이다 — 지시서를 다시 만들지 않는다.

    python -m scripts.mini_render A --stages 3            # 이미지만
    python -m scripts.mini_render B --stages 4 --video    # 영상까지

★ 기본은 **이미지만**이다. Phase 0 에서 영상은 별도의 실패(글자 번인)를 냈고 단가도
  다르다. 먼저 스틸로 연속성·identity·구도를 보고, 통과하면 영상을 붙인다.

★ 비용은 실행 전에 계산해 출력하고 `--yes` 없이는 멈춘다. 이 저장소는 8/29 에 승인 없이
  1.7만원을 쓴 적이 있다 — 생성 스크립트는 스스로 멈출 줄 알아야 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config, cost, generation_spec, sequence_render, visual_sequence  # noqa: E402
from engine.util import log  # noqa: E402

GOLDEN = pathlib.Path("docs/review-2026-08-29")
OUT = pathlib.Path("docs/review-2026-08-30")


def slice_directive(directive: dict, sequence_id: str, n_stages: int,
                    want_video: bool) -> dict:
    """지시서 → **시퀀스 하나의 앞 n_stages** 만 담은 미니 지시서.

    ★ stage 당 컷 하나만 남긴다. 같은 stage 를 여러 컷이 나눠 맡으면 그림은 하나이므로
      연속성 측정에는 첫 컷이면 충분하다(비용을 배로 쓸 이유가 없다).
    """
    header = dict(directive["header"])
    seqs = visual_sequence.normalize_all(header.get("visual_sequences"))
    seq = next((s for s in seqs if s["sequence_id"] == sequence_id), None)
    if seq is None:
        raise SystemExit(f"시퀀스 없음: {sequence_id} (있는 것: "
                         f"{[s['sequence_id'] for s in seqs]})")

    stages = seq["stages"][:n_stages]
    by_no_all = {int(c.get("cut_no") or 0): c for c in directive["cuts"]}

    def _pick(st: dict) -> int | None:
        """이 stage 를 대표할 컷. **기전 컷을 우선한다.**

        ★ 첫 컷을 무조건 쓰면 안 된다(2026-08-30 실측): 골든B 의 stage 대표 컷 셋이
          `connective_in_world` 였다 — 세계 배경만 물려받는 컷이라 참조를 걸지 않는다.
          그것들로 Mini Render 를 짜면 **측정하려던 연속성이 애초에 일어나지 않는다.**
        """
        refs = [int(x) for x in (st.get("cut_refs") or [])]
        mech = [n for n in refs
                if (by_no_all.get(n, {}).get("resolved_visual_plan") or {}).get("base")
                == "MECHANISM_SEQUENCE"]
        return (mech or refs or [None])[0]

    keep = [n for n in (_pick(st) for st in stages) if n is not None]
    by_no = {int(c.get("cut_no") or 0): c for c in directive["cuts"]}
    cuts = []
    for new_no, old_no in enumerate(keep, 1):
        c = dict(by_no[old_no])
        c["_origin_cut_no"] = old_no
        # ★ stage 의 cut_refs 를 새 번호로 다시 쓴다 — 안 하면 렌더가 stage 를 못 찾는다.
        c["cut_no"] = new_no
        if not want_video:
            c["motion_source"] = "still"           # 영상 생성 경로를 막는다
        cuts.append(c)

    remapped = []
    for i, st in enumerate(st for st in stages if _pick(st) is not None):
        st = dict(st)
        st["cut_refs"] = [i + 1]
        remapped.append(st)
    header["visual_sequences"] = [{**seq, "stages": remapped}]
    header["hook_ko"] = header.get("hook_ko") or ""
    return {"version_type": directive.get("version_type", "photo"),
            "header": header, "cuts": cuts}


def estimate(mini: dict) -> Decimal:
    """이 미니 렌더의 예상 생성비. **실행 전에 반드시 출력한다.**"""
    total = Decimal("0")
    for c in mini["cuts"]:
        spec = generation_spec.image_spec(c, mini["header"], generation_mode="realtime")
        total += cost.compute_cost(spec.model, spec.unit_type, 1)
        if c.get("motion_source") == "video":
            sec = min(int(c.get("estimated_sec") or config.VEO_CLIP_SEC),
                      config.clip_tier_max(mini["version_type"]))
            total += cost.compute_cost(config.VEO_MODEL,
                                       f"video_{config.VEO_RESOLUTION}_per_sec", sec)
    return total


def render_stills(mini: dict, out_dir: pathlib.Path) -> dict:
    """스틸만 만든다 — TTS·클립·조립을 건너뛴다.

    ★ 왜 별도 경로인가(2026-08-30 실측): 전체 렌더는 TTS 를 **가장 먼저** 부르고, 그것이
      ffmpeg 로 무음 오디오를 만든다. 로컬에 ffmpeg 가 없으면 **유료 이미지 생성에 닿기도
      전에** 죽는다. 그런데 Mini Render 가 재려는 것은 조립이 아니라 **스틸의 연속성**이다.
      측정 대상이 아닌 의존성 때문에 측정을 못 하는 것은 도구 문제이지 설계 문제가 아니다.

    ★ 여기서 도는 것이 Phase 3 배선 그 자체다: stage 색인 → 참조 판정 → _gen_still(ref_path).
      전체 렌더와 **같은 함수**를 부른다 — 우회로를 새로 만들면 측정이 프로덕션을 대변하지 못한다.
    """
    from engine import render                       # 지연 import

    header = mini["header"]
    stage_assets: dict[str, str] = {}
    decisions: list[dict] = []
    spent = 0.0
    out_dir.mkdir(parents=True, exist_ok=True)

    for cut in mini["cuts"]:
        no = int(cut["cut_no"])
        decision = sequence_render.reference_decision(cut, header, stage_assets)
        decision["cut_no"] = no
        decisions.append(decision)
        img = str(out_dir / f"cut{no}.png")

        if decision["kind"] == "derive" and render._derive_from_stage(cut, img, decision):
            log.info("컷 %s 파생(생성 호출 0) ← stage %s", no, decision["ref_stage"])
        else:
            ref = decision.get("ref_asset") or None
            spent += render._gen_still(
                cut, header, img,
                ref_path=ref if decision["kind"] == "reference" else None,
                reference_key=str(decision.get("reference_key") or ""))
        sid = str(decision.get("stage_id") or "")
        if sid and sid not in stage_assets and os.path.exists(img):
            stage_assets[sid] = img
        log.info("컷 %s → %s (kind=%s, ref=%s, degraded=%s)",
                 no, img, decision["kind"], decision["ref_stage"], decision["degraded"])

    return {"decisions": decisions, "cost_usd": round(spent, 4),
            "summary": sequence_render.degraded_summary(decisions),
            "stage_assets": stage_assets}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", choices=["A", "B"])
    ap.add_argument("--sequence", default="")
    ap.add_argument("--stages", type=int, default=4)
    ap.add_argument("--video", action="store_true", help="영상까지 만든다(기본은 이미지만)")
    ap.add_argument("--assemble", action="store_true",
                    help="mp4 로 조립까지 한다(ffmpeg 필요). 기본은 스틸만.")
    ap.add_argument("--yes", action="store_true", help="비용을 확인했고 진행한다")
    args = ap.parse_args()

    src = GOLDEN / f"golden_{args.tag}_v3_regen.json"
    directive = json.loads(src.read_text(encoding="utf-8"))
    seq_id = args.sequence or directive["header"]["visual_sequences"][0]["sequence_id"]
    mini = slice_directive(directive, seq_id, args.stages, args.video)

    est = estimate(mini)
    print(f"=== Mini Render {args.tag} — {seq_id}")
    print(f"    stage {len(mini['header']['visual_sequences'][0]['stages'])}개 · "
          f"컷 {len(mini['cuts'])}개 · 영상 {'포함' if args.video else '없음'}")
    for c in mini["cuts"]:
        spec = generation_spec.image_spec(c, mini["header"], generation_mode="realtime")
        print(f"    컷{c['cut_no']} (원본 {c['_origin_cut_no']}) "
              f"role={spec.visual_role}(라벨 {c.get('visual_role')}) "
              f"model={spec.model} ${spec.unit_price_usd}")
    print(f"    예상 생성비: ${est}")
    if not args.yes:
        print("\n    --yes 없이는 실행하지 않는다. 비용을 확인하고 다시 부르라.")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    log.info("Mini Render 시작: %s (IMAGE_PROVIDER=%s)", args.tag, config.IMAGE_PROVIDER)

    if args.assemble:
        out_path = str(OUT / f"mini_{args.tag}.mp4")
        from engine import render
        render.render_directive_local(mini, out_path)
        print(f"\n=== 완료: {out_path}")
        return

    result = render_stills(mini, OUT / f"mini_{args.tag}")
    report = OUT / f"mini_{args.tag}_report.json"
    report.write_text(json.dumps(
        {"tag": args.tag, "sequence_id": seq_id, "estimate_usd": float(est), **result},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== 완료 — 스틸 {len(result['decisions'])}장")
    print(f"    실제 비용 : ${result['cost_usd']}")
    print(f"    요약      : {json.dumps(result['summary'], ensure_ascii=False)}")
    for d in result["decisions"]:
        print(f"    컷{d['cut_no']} kind={d['kind']:<10} ref={d['ref_stage'] or '-':<20}"
              f" degraded={d['degraded'] or '-'}")
    print(f"    보고서    : {report}")
    # ★ 최종 판정은 사람 눈이다(리뷰 §14). 숫자는 방향만 말한다.
    print(f"    → {OUT / f'mini_{args.tag}'} 의 png 를 눈으로 확인하라.")


if __name__ == "__main__":
    main()
