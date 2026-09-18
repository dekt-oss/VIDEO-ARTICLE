"""저장된 지시서에서 **시퀀스 하나만** 잘라 렌더해 본다 (2026-09-18).

무엇을 푸는가: 기전 시퀀스를 고쳤는데 그것을 보려면 편당 $5~8 짜리 전체 렌더를 돌려야 했다.
보고 싶은 것은 3~4컷인데 13컷을 산다. `scripts/mini_render.py` 가 같은 일을 하지만 **파일로
보관된 골든 지시서**만 읽는다 — 운영 중인 지시서(Supabase)는 대상이 아니었다.

    python -m scripts.preview_sequence <directive_id>              # 계획·비용만 (생성 0)
    python -m scripts.preview_sequence <directive_id> --yes        # 실제로 만든다(유료)
    python -m scripts.preview_sequence <directive_id> --stills --yes   # 그림만(영상비 0)
    python -m scripts.preview_sequence <directive_id> --free --yes     # placeholder(비용 0, 배선 확인)

★ 기본 대상은 **기전 컷이 가장 많은 시퀀스**다(--sequence 로 지정 가능).
★ `--yes` 없이는 아무것도 만들지 않는다. 이 저장소는 승인 없이 1.7만원을 쓴 적이 있다.
★ 산출물은 `docs/preview-<날짜>/<directive 앞 8자>/` 에 남는다 — stage 시작 그림, 전·후 분할
  스틸, 완성 mp4, 컷별 최종 프레임(자막·범례가 구워진 화면), report.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config  # noqa: E402
from engine.util import log  # noqa: E402


def pick_sequence(directive: dict, wanted: str = "") -> str:
    """미리 볼 시퀀스. 지정이 없으면 **기전 컷이 가장 많은** 시퀀스.

    ★ sequence_role 라벨을 그대로 믿지 않는다 — 이 저장소는 완벽한 기전 진행에 모델이
      `RESULT_SEQUENCE` 를 붙인 실측을 갖고 있다(visual_sequence.sequence_is_progression 주석).
      그래서 **컷의 visual_role 을 세어** 고른다.
    """
    from engine import visual_sequence

    seqs = [s for s in (directive.get("header") or {}).get("visual_sequences") or []
            if isinstance(s, dict)]
    if not seqs:
        raise SystemExit("이 지시서에는 시각 시퀀스가 없다(옛 지시서). 지시서를 다시 만들어라.")
    ids = [str(s.get("sequence_id") or "") for s in seqs]
    if wanted:
        if wanted not in ids:
            raise SystemExit(f"시퀀스 없음: {wanted} (있는 것: {ids})")
        return wanted
    role_of = {int(c.get("cut_no") or 0): str(c.get("visual_role") or "")
               for c in directive.get("cuts") or []}

    def score(seq: dict) -> tuple[int, int]:
        mech = sum(1 for st in seq.get("stages") or []
                   for n in st.get("cut_refs") or []
                   if role_of.get(int(n)) == "MECHANISM")
        return (mech, 1 if visual_sequence.sequence_is_progression(seq) else 0)

    best = max(seqs, key=score)
    if score(best)[0] == 0:
        log.warning("기전 컷이 있는 시퀀스가 없다 — 첫 시퀀스로 간다")
    return str(best.get("sequence_id") or "")


def describe(mini: dict) -> None:
    """무엇을 만들 것인지 사람 말로. **발주 전에** 본다."""
    from engine import render

    header = mini["header"]
    print("\n[미리 볼 컷]")
    for c in mini["cuts"]:
        overlays = [str(o.get("type")) for o in c.get("overlay_plan") or []]
        # ★ --stills 는 stage 렌더를 끄므로 분할이 **일어나지 않는다.** 그런데도 "분할 스틸"이라고
        #   찍으면 도구가 거짓말을 한다 — 안 할 일을 할 것처럼 적으면 그게 가장 나쁜 표시다.
        will_split = render.split_before_after_applies(c, header) and config.STAGE_RENDER_ENABLED
        split = ("  ← 전·후 분할 스틸" if will_split
                 else ("  (분할 대상이지만 --stills 라 이번엔 안 함)"
                       if render.split_before_after_applies(c, header) else ""))
        print(f"  컷{c['cut_no']} (원본 {c['_origin_cut_no']}) {c.get('visual_role') or '-'} "
              f"{c.get('motion_source')} {c.get('estimated_sec')}초 "
              f"오버레이={overlays or '없음'}{split}")
        if c.get("mechanism_ko"):
            print(f"        원리: {c['mechanism_ko']}")
    print("\n[단계]")
    for st in header["visual_sequences"][0]["stages"]:
        ops = [m.get("operation") for m in st.get("mutations") or []]
        print(f"  {st.get('stage_id')} {st.get('continuity_mode')} "
              f"이어받기={st.get('continuity_from') or '-'} 변화={ops or '없음'}")


def grab_frames(mp4: str, cut_files: list[str], out_dir: pathlib.Path) -> None:
    """컷마다 **완성본의 중간 프레임**을 뽑는다 — 자막·범례가 구워진 진짜 화면.

    ★ 완성본은 조립 마지막에 속도 보정(setpts)이 들어가므로 컷 길이의 누적으로 시각을
      계산하면 어긋난다. 실측 길이 비율로 환산한다.
    """
    from engine import assemble

    raw = [assemble.probe_duration(p) for p in cut_files]
    total_raw = sum(raw) or 1.0
    final = assemble.probe_duration(mp4) or total_raw
    scale = final / total_raw
    t = 0.0
    for i, dur in enumerate(raw, 1):
        mid = (t + dur / 2) * scale
        t += dur
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{mid:.2f}",
                        "-i", mp4, "-frames:v", "1", str(out_dir / f"final_cut{i}.png")],
                       check=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="지시서의 시퀀스 하나만 렌더해 본다.")
    ap.add_argument("directive_id")
    ap.add_argument("--sequence", default="", help="시퀀스 id(기본: 기전 컷이 가장 많은 것)")
    ap.add_argument("--stages", type=int, default=4, help="앞에서 몇 단계까지(기본 4)")
    ap.add_argument("--stills", action="store_true", help="그림만 만든다(영상 생성 0)")
    ap.add_argument("--free", action="store_true",
                    help="placeholder 로 돌린다(비용 0). 그림은 회색 판이고 영상 stage 는 "
                         "스틸로 폴백된다 — 자막·범례·캡션·전후분할 **배선**만 확인하는 모드다")
    ap.add_argument("--yes", action="store_true", help="비용을 확인했고 진행한다")
    args = ap.parse_args()

    if args.stills:
        # ★★ 컷의 motion_source 를 still 로 바꾸는 것만으로는 **영상비가 안 줄어든다.**
        #   시퀀스 렌더(stage_render.enabled)는 motion_source 를 보지 않고 stage 단위로 Veo 를
        #   산다 — "그림만"이라고 해 놓고 영상을 사면 그게 가장 나쁜 거짓말이다. 그래서 여기서
        #   시퀀스 렌더 자체를 끈다. 참조 연쇄는 컷 경로에도 있으므로 그대로 이어진다
        #   (전·후 분할 스틸은 stage 경로에만 있으니 이 모드에서는 안 나온다).
        config.STAGE_RENDER_ENABLED = False
    if args.free:
        config.IMAGE_PROVIDER = "placeholder"
        config.VIDEO_PROVIDER = "placeholder"
    else:
        # ★ 기본이 placeholder 라(config), 유료로 돌리려면 여기서 켠다. 운영자가 환경변수를
        #   앞에 붙이는 것을 기억하지 않아도 되게 — 잊으면 "돌았는데 회색 화면"이 나온다.
        config.IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER") or "gemini"
        config.VIDEO_PROVIDER = os.getenv("VIDEO_PROVIDER") or "veo"

    from engine import assemble, db, render, render_qa, sequence_render, subtitles
    from scripts.mini_render import estimate, slice_directive

    directive = db.get_directive(args.directive_id)
    if not directive:
        raise SystemExit(f"지시서 없음: {args.directive_id}")
    seq_id = pick_sequence(directive, args.sequence)
    mini = slice_directive(directive, seq_id, args.stages, want_video=not args.stills)
    describe(mini)

    est = Decimal("0") if args.free else estimate(mini)
    print(f"\n시퀀스 {seq_id} · 컷 {len(mini['cuts'])}개")
    print(f"예상 비용(상한): ${est}   그림={config.IMAGE_PROVIDER} 영상={config.VIDEO_PROVIDER} "
          f"범례·캡션={config.MECHANISM_LABEL_OVERLAYS_ENABLED} 분할스틸={config.MECHANISM_SPLIT_BEFORE_AFTER}")
    if not args.free:
        # ★ 미리보기는 **에셋 캐시를 타지 않는다.** 컷 번호를 1..N 으로 다시 매기기 때문에
        #   (directive, cut_no) 키가 본 지시서의 것과 겹쳐서, 캐시에 넣으면 본 렌더가 미리보기
        #   그림을 물려받는다. 그래서 일부러 안 쓴다 — 대신 **돌릴 때마다 새로 산다**는 것을
        #   여기서 밝힌다(2026-09-18: 세 번 돌려 세 번 결제된 뒤에 알았다).
        print("  ※ 미리보기는 캐시를 쓰지 않는다 — **다시 돌리면 그림값이 또 나간다.**")
    if not args.yes:
        print("\n  --yes 를 붙이면 실제로 만든다. 지금은 아무것도 만들지 않았다.")
        return

    # ★ **절대 경로여야 한다.** 조립은 concat 목록 파일에 컷 경로를 적는데, ffmpeg 는 그 경로를
    #   목록 파일이 있는 디렉터리 기준으로 다시 푼다 — 상대 경로를 주면 `docs/…/_work/docs/…/_work/`
    #   처럼 두 번 이어 붙여 "Impossible to open" 으로 죽는다(2026-09-18 실측).
    out_dir = (pathlib.Path("docs") / f"preview-{dt.date.today().isoformat()}"
               / args.directive_id[:8]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    fit_log: list[dict] = []
    overlays: list[tuple[float, float, str, str]] = []
    seq_log: list[dict] = []
    cut_files, cues, total, duck = render._render_cut_clips(
        mini, str(work), lang="ko", fit_log=fit_log, overlay_out=overlays, seq_out=seq_log)
    if not cut_files:
        raise SystemExit("컷을 하나도 못 만들었다")

    header = mini["header"]
    ass = subtitles.build_ass(
        cues, header_title=config.SERIES_TITLE_BY_LANG.get("ko", config.SERIES_TITLE),
        header_hook=str(header.get("hook_ko") or ""), total_sec=total, lang="ko",
        platform=config.DEFAULT_PLATFORM, overlays=overlays)
    mp4 = str(out_dir / "preview_ko.mp4")
    assemble.assemble_full(cut_files, str(work), mp4, ass_text=ass, total_sec=total,
                           duck_spans=duck)

    for p in (sorted(work.glob("stage_*_start.png")) + sorted(work.glob("stage_*_split.png"))
              + sorted(work.glob("cut_*.png"))):
        shutil.copy(p, out_dir / p.name)
    grab_frames(mp4, cut_files, out_dir)

    report = {
        "directive_id": args.directive_id, "sequence_id": seq_id,
        "estimate_usd": float(est), "total_sec": round(total, 2), "cuts": len(cut_files),
        "overlays": [{"start": round(s, 2), "end": round(e, 2), "style": st, "text": tx}
                     for s, e, tx, st in overlays],
        "seq_decisions": [{k: v for k, v in d.items()
                           if k in ("cut_no", "kind", "ref_stage", "stage_id", "degraded",
                                    "split_before_after")} for d in seq_log],
        "clip_fit": render_qa.evaluate_clip_fit(fit_log)["strategy_counts"],
        "continuity": sequence_render.degraded_summary(seq_log),
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n완성: {mp4}")
    print(f"  stage_*_start.png  단계마다 만든 그림 (분할 스틸이면 stage_*_split.png)")
    print(f"  final_cut*.png     자막·범례가 구워진 최종 화면")
    print(f"  report.json        참조 연쇄·분할 여부·오버레이 목록")


if __name__ == "__main__":
    main()
