"""저장된 지시서에서 **시퀀스 하나만** 잘라 렌더해 본다 (2026-09-18).

무엇을 푸는가: 기전 시퀀스를 고쳤는데 그것을 보려면 편당 $5~8 짜리 전체 렌더를 돌려야 했다.
보고 싶은 것은 3~4컷인데 13컷을 산다. `scripts/mini_render.py` 가 같은 일을 하지만 **파일로
보관된 골든 지시서**만 읽는다 — 운영 중인 지시서(Supabase)는 대상이 아니었다.

    python -m scripts.preview_sequence <directive_id>              # 계획·비용만 (생성 0)
    python -m scripts.preview_sequence <directive_id> --yes        # 실제로 만든다(유료)
    python -m scripts.preview_sequence <directive_id> --stills --yes   # 그림만(영상비 0)
    python -m scripts.preview_sequence <directive_id> --free --yes     # placeholder(비용 0, 배선 확인)
    python -m scripts.preview_sequence <directive_id> --keep --yes     # 캐시에 남긴다(최종본이 물려받음)

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


def slice_keep(directive: dict, sequence_id: str, n_stages: int,
               want_video: bool) -> dict:
    """원본 컷 번호를 **그대로 둔** 미니 지시서 — 만든 그림이 최종본에 그대로 들어간다.

    `mini_render.slice_directive` 와의 차이는 셋뿐이고, 셋 다 **캐시 키를 본 렌더와 같게**
    만들기 위한 것이다(캐시 키 = `(directive_id, cut_no)` + `content_hash` + `reference_key`):

      ① **컷 번호를 다시 매기지 않는다.** 1..N 으로 바꾸면 같은 지시서의 다른 컷과 키가
         겹쳐서, 캐시에 넣는 순간 본 렌더가 엉뚱한 그림을 물려받는다. 그래서 종전 미리보기는
         일부러 캐시를 껐고, 그 대가로 **돌릴 때마다 다시 샀다**.
      ② **stage 의 cut_refs 를 건드리지 않는다.** 번호를 그대로 두므로 고칠 이유가 없다.
      ③ **정규화하지 않는다.** `sequence_render.stage_index` 는 지시서의 **날것** stage 를
         읽는다. 여기서 `normalize_all` 을 태우면 `state_after_computed` 같은 필드가 붙어
         `reference_key` 가 달라지고, 본 렌더가 캐시를 **못 맞힌다** — 돈을 두 번 내고도
         "캐시를 켰는데 왜 또 사지"가 된다.

    stage 대표 컷 하나만 남기는 축약도 하지 않는다. 최종본에 들어갈 컷을 사는 것이므로
    그 stage 가 맡은 컷을 **전부** 만든다.
    """
    header = dict(directive["header"])
    raw = [s for s in (header.get("visual_sequences") or []) if isinstance(s, dict)]
    seq = next((s for s in raw if str(s.get("sequence_id") or "") == sequence_id), None)
    if seq is None:
        raise SystemExit(f"시퀀스 없음: {sequence_id} "
                         f"(있는 것: {[s.get('sequence_id') for s in raw]})")
    stages = (seq.get("stages") or [])[:n_stages]
    keep: list[int] = []
    for st in stages:
        for n in st.get("cut_refs") or []:
            if int(n) not in keep:
                keep.append(int(n))
    by_no = {int(c.get("cut_no") or 0): c for c in directive.get("cuts") or []}
    cuts = []
    for no in keep:
        if no not in by_no:
            log.warning("컷 %s 가 지시서에 없다 — 건너뛴다", no)
            continue
        c = dict(by_no[no])
        c["_origin_cut_no"] = no          # 번호를 안 바꾸므로 원본과 같다(표시용)
        if not want_video:
            c["motion_source"] = "still"
        cuts.append(c)
    if not cuts:
        raise SystemExit(f"시퀀스 {sequence_id} 의 앞 {n_stages}단계에 컷이 없다")
    header["visual_sequences"] = [{**seq, "stages": stages}]
    header["hook_ko"] = header.get("hook_ko") or ""
    return {"version_type": directive.get("version_type", "photo"),
            "header": header, "cuts": cuts}


def estimate_plan(mini: dict) -> tuple[Decimal, list[str]]:
    """이 미리보기가 **실제로 사게 될 것**의 추정 + 줄 단위 내역.

    ★ 왜 `mini_render.estimate` 를 그대로 쓰지 않나(2026-09-19): 그것은 **컷 단위**로 센다 —
      `motion_source == "video"` 인 컷마다 Veo 를 한 번씩. 그런데 실사형 렌더는 **stage 단위**다:
        · `motion_source` 는 읽히지 않는다 — stage 가 통째로 영상 하나를 산다(스틸 컷이 그
          stage 에 있어도 산다)
        · 전·후 분할 스틸로 나가는 stage 는 **영상을 아예 안 산다**
      실측(리포트 SEQ_R01): 옛 셈은 $0.902 를 찍었는데 실제로 살 것은 그 구성이 아니었다 —
      컷 영상 2개($0.50)를 있다고 세고 stage 영상 1개를 없다고 셌다. 두 오차가 서로 반대라
      총액이 우연히 가까웠을 뿐이다. **틀린 값이 맞는 값과 가까운 것은 고칠 이유가 없다는
      뜻이 아니다** — 다음 지시서에서는 안 가깝다.

    ★ stage 길이는 나레이션 실측의 합인데 그것은 TTS 를 돌려야 안다. 여기서는 지시서의
      `estimated_sec` 으로 대신하고, 렌더가 쓰는 것과 **같은 함수**(`stage_render.plan_stage`)
      로 티어를 나눈다 — 셈을 두 벌로 만들면 한쪽만 고쳐지는 날이 온다.

    ★ 그림은 컷당 1장으로 센다(상한). 참조 파생·재사용으로 실제 생성이 줄어들 수 있지만
      그것은 렌더 중에 정해진다 — 비용은 **넉넉히** 말하는 쪽이 안전하다.
    """
    from engine import cost, generation_spec, render, stage_render

    header = mini["header"]
    total = Decimal("0")
    lines: list[str] = []
    for c in mini["cuts"]:
        spec = generation_spec.image_spec(c, header, generation_mode="realtime")
        ci = cost.compute_cost(spec.model, spec.unit_type, 1)
        total += ci
        lines.append(f"  컷{c['cut_no']} 그림 ${ci}  ({spec.model.split('/')[-1]})")

    if not stage_render.enabled(header):
        for c in mini["cuts"]:
            if c.get("motion_source") != "video":
                continue
            sec = min(int(c.get("estimated_sec") or config.VEO_CLIP_SEC),
                      config.clip_tier_max(mini["version_type"]))
            cv = cost.compute_cost(config.VEO_MODEL,
                                   f"video_{config.VEO_RESOLUTION}_per_sec", sec)
            total += cv
            lines.append(f"  컷{c['cut_no']} 영상 ${cv}  ({sec}초)")
        return total, lines

    durs = [float(c.get("estimated_sec") or 0) for c in mini["cuts"]]
    for g in stage_render.plan_stage(mini["cuts"], durs):
        lead = mini["cuts"][g["indexes"][0]]
        nos = [mini["cuts"][i]["cut_no"] for i in g["indexes"]]
        if render.split_before_after_applies(lead, header):
            lines.append(f"  {g['stage_id']} 영상 $0  (전·후 분할 스틸 — 생성 0회, 컷 {nos})")
            continue
        sec = sum(g["clips"])
        cv = cost.compute_cost(config.VEO_MODEL,
                               f"video_{config.VEO_RESOLUTION}_per_sec", sec)
        total += cv
        lines.append(f"  {g['stage_id']} 영상 ${cv}  ({sec:g}초, 컷 {nos})")
    return total, lines


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
    ap.add_argument("--reuse", default="", metavar="폴더",
                    help="그 폴더의 PNG 를 그림으로 **재사용**한다(생성 호출 0·비용 0). "
                         "자막·범례·화살표·전후분할·조립을 진짜 그림 위에서 확인하는 모드다 — "
                         "새 프롬프트가 그리는 그림 자체는 이걸로 알 수 없다")
    ap.add_argument("--free", action="store_true",
                    help="placeholder 로 돌린다(비용 0). 그림은 회색 판이고 영상 stage 는 "
                         "스틸로 폴백된다 — 자막·범례·캡션·전후분할 **배선**만 확인하는 모드다")
    ap.add_argument("--keep", action="store_true",
                    help="만든 그림·클립을 **에셋 캐시에 남긴다**(컷 번호를 그대로 둔다). "
                         "나중에 편 전체를 렌더하면 이 시퀀스는 다시 사지 않고 그대로 들어간다. "
                         "--free/--reuse 와는 같이 못 쓴다 — 가짜 그림이 캐시에 앉는다")
    ap.add_argument("--yes", action="store_true", help="비용을 확인했고 진행한다")
    args = ap.parse_args()

    if args.keep and (args.free or args.reuse):
        # ★ 캐시는 "이 그림이 이 컷의 정본"이라는 선언이다. placeholder 회색 판이나 다른
        #   지시서에서 빌려 온 그림을 그 자리에 앉히면, 나중에 편 전체를 렌더할 때 **아무도
        #   모르게** 그 그림이 최종본에 들어간다. 도구가 막는다.
        raise SystemExit("--keep 은 --free·--reuse 와 같이 쓸 수 없다 "
                         "(가짜·빌려온 그림이 캐시에 남아 최종본에 들어간다)")
    if args.stills:
        # ★★ 컷의 motion_source 를 still 로 바꾸는 것만으로는 **영상비가 안 줄어든다.**
        #   시퀀스 렌더(stage_render.enabled)는 motion_source 를 보지 않고 stage 단위로 Veo 를
        #   산다 — "그림만"이라고 해 놓고 영상을 사면 그게 가장 나쁜 거짓말이다. 그래서 여기서
        #   시퀀스 렌더 자체를 끈다. 참조 연쇄는 컷 경로에도 있으므로 그대로 이어진다
        #   (전·후 분할 스틸은 stage 경로에만 있으니 이 모드에서는 안 나온다).
        config.STAGE_RENDER_ENABLED = False
    if args.reuse:
        config.IMAGE_PROVIDER = "reuse"
        config.IMAGE_REUSE_DIR = args.reuse
        config.VIDEO_PROVIDER = "placeholder"   # 영상도 안 산다(stage 는 스틸로 폴백)
    elif args.free:
        config.IMAGE_PROVIDER = "placeholder"
        config.VIDEO_PROVIDER = "placeholder"
    else:
        # ★ 기본이 placeholder 라(config), 유료로 돌리려면 여기서 켠다. 운영자가 환경변수를
        #   앞에 붙이는 것을 기억하지 않아도 되게 — 잊으면 "돌았는데 회색 화면"이 나온다.
        config.IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER") or "gemini"
        config.VIDEO_PROVIDER = os.getenv("VIDEO_PROVIDER") or "veo"

    from engine import assemble, db, render, render_qa, sequence_render, subtitles
    from scripts.mini_render import slice_directive

    # ★ 두 공장을 **둘 다** 찾는다(2026-09-19). 운영자가 리포트 지시서를 미리 보려 했는데
    #   이 도구가 논문 테이블만 읽어서 "지시서 없음"이 났다 — 화면 계약·렌더 경로는 공용인데
    #   도구만 한쪽을 못 보고 있었다.
    from engine import report_db

    directive = db.get_directive(args.directive_id)
    # ★ 어느 공장의 지시서인가. 에셋 캐시 표가 갈리므로(render_assets vs report_render_assets)
    #   이것을 틀리면 FK 위반으로 캐시가 통째로 실패한다.
    kind = "paper"
    if not directive:
        directive = report_db.get_report_directive(args.directive_id)
        kind = "report"
    if not directive:
        raise SystemExit(f"지시서 없음(논문·리포트 양쪽에서 못 찾음): {args.directive_id}")
    seq_id = pick_sequence(directive, args.sequence)
    slicer = slice_keep if args.keep else slice_directive
    mini = slicer(directive, seq_id, args.stages, want_video=not args.stills)
    describe(mini)

    est, est_lines = ((Decimal("0"), []) if (args.free or args.reuse) else estimate_plan(mini))
    print(f"\n시퀀스 {seq_id} · 컷 {len(mini['cuts'])}개")
    for ln in est_lines:
        print(ln)
    print(f"예상 비용: ${est}   그림={config.IMAGE_PROVIDER} 영상={config.VIDEO_PROVIDER} "
          f"범례·캡션={config.MECHANISM_LABEL_OVERLAYS_ENABLED} 분할스틸={config.MECHANISM_SPLIT_BEFORE_AFTER}")
    if args.keep:
        print(f"  ※ --keep: 컷 번호를 그대로 두고 **{kind} 에셋 캐시에 남긴다** — "
              f"편 전체를 렌더하면 이 컷들은 다시 사지 않는다.")
    elif not (args.free or args.reuse):
        # ★ 미리보기는 기본적으로 **에셋 캐시를 타지 않는다.** 컷 번호를 1..N 으로 다시 매기기
        #   때문에 (directive, cut_no) 키가 본 지시서의 것과 겹쳐서, 캐시에 넣으면 본 렌더가
        #   미리보기 그림을 물려받는다. 그래서 일부러 안 쓴다 — 대신 **돌릴 때마다 새로 산다**는
        #   것을 여기서 밝힌다(2026-09-18: 세 번 돌려 세 번 결제된 뒤에 알았다).
        #   번호를 지키면서 캐시에 남기고 싶으면 `--keep` 이다.
        print("  ※ 미리보기는 캐시를 쓰지 않는다 — **다시 돌리면 그림값이 또 나간다.**")
        print("     한 번만 사서 최종본에 그대로 쓰려면 --keep 을 붙인다.")
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
        mini, str(work), lang="ko", fit_log=fit_log, overlay_out=overlays, seq_out=seq_log,
        # ★ --keep 일 때만 directive_id 를 넘긴다. 이 인자 하나가 캐시 스위치다
        #   (render._gen_still: `use_cache = bool(directive_id) and paid`).
        directive_id=(args.directive_id if args.keep else None),
        render_job_kind=kind)
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
        "factory": kind, "cached": bool(args.keep),
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
