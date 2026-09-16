"""웹 발주서 + 조립 — 유료 API 없이 **완성 영상 한 편**을 만든다 (2026-08-30).

무엇을 푸는가: Phase 4(골든 검증)가 요구하는 것은 "완성된 영상을 눈으로 본다"인데,
생성 API 를 돌리면 편당 ~$2.5 가 나간다. 그런데 운영자가 Gemini 웹 채팅에서 **무료로**
같은 것을 만들 수 있다. 그러면 남는 일은 둘뿐이다:

    ① 파이프라인이 보낼 프롬프트를 **그대로** 뽑아 발주서로 준다   (order)
    ② 받아온 파일을 **진짜 파이프라인에 꽂아** 영상으로 조립한다   (build)

★★ ②가 이 도구의 핵심이다. 생성 함수만 "이미 있는 파일을 쓴다"로 바꾸고 **나머지는 전부
  진짜로 돈다** — TTS·길이보정(clip_fit)·자막·오버레이·켄번스·concat·라우드니스.
  즉 유료 호출만 뺀 **end-to-end 실측**이다. 지금까지 한 번도 못 해 본 그것이다.

★ 프롬프트는 내가 지어내지 않는다. `providers/image._build_image_prompt` 와
  `providers/video.build_motion_prompt` 를 그대로 부른다 — 여기서 잘 나오면 코드도 잘 나오고,
  여기서 깨지면 코드도 깨진다.

사용:
    python -m scripts.web_order order A                # 발주서 만들기
    python -m scripts.web_order order B --cuts 6
    (→ docs/발주_B/발주서.md 를 보고 웹에서 만들어 docs/발주_B/입력/ 에 넣는다)
    python -m scripts.web_order build B                # 받은 파일로 영상 조립
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config, sequence_tier, temporal_plan, visual_sequence  # noqa: E402
from engine.providers import image as image_provider  # noqa: E402
from engine.providers import video as video_provider  # noqa: E402
from engine.util import log  # noqa: E402
from scripts.mini_render import slice_directive  # noqa: E402

GOLDEN = pathlib.Path("docs/review-2026-08-29")
ROOT = pathlib.Path("docs")


def _ensure_ffmpeg() -> None:
    """로컬에 ffmpeg 가 없으면 imageio-ffmpeg 번들 바이너리를 PATH 에 얹는다.

    ★ 프로덕션 코드는 건드리지 않는다 — `engine/assemble.py` 는 계속 "ffmpeg" 를 부르고,
      여기서 그 이름으로 찾을 수 있게만 해 준다. 조립을 못 해서 실측을 못 하는 것은
      도구 문제이지 파이프라인 문제가 아니다.
    """
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("ffmpeg 가 없다. `pip install imageio-ffmpeg` 로 번들 바이너리를 넣어라.")
    exe = pathlib.Path(imageio_ffmpeg.get_ffmpeg_exe())
    shim = exe.parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not shim.exists():
        shutil.copyfile(exe, shim)
        shim.chmod(0o755)
    os.environ["PATH"] = f"{exe.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    log.info("ffmpeg 번들 사용: %s", shim)


def _mp4_duration(path: str) -> float:
    """mvhd 박스에서 길이(초)를 직접 읽는다. ffprobe 가 없을 때만 쓰는 **도구용** 대체.

    ★ 왜 필요한가: imageio-ffmpeg 는 ffmpeg 만 번들하고 **ffprobe 는 없다.** 그래서 로컬
      조립에서 `assemble.probe_duration` 이 전부 0.0 을 돌려주고, 길이 보정이 클립 길이를
      "못 쟀다"로 보아 **전 컷 flagged** 가 된다. 그러면 clip_fit 판정 분포를 볼 수 없는데,
      그건 파이프라인의 답이 아니라 **측정 실패**다(실측: 5/5 flagged, clip=0.00s).
      CI·운영에는 ffprobe 가 있으므로 프로덕션 코드는 건드리지 않는다.
    """
    data = pathlib.Path(path).read_bytes()
    i = data.find(b"mvhd")
    if i < 0:
        return 0.0
    box = data[i + 4:]
    version = box[0]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", box[20:32])
    else:
        timescale, duration = struct.unpack(">II", box[12:20])
    return round(duration / timescale, 3) if timescale else 0.0


def _ensure_ffprobe() -> None:
    """ffprobe 가 없으면 길이 측정만 순수 파이썬으로 갈아끼운다(도구 한정)."""
    if shutil.which("ffprobe"):
        return
    from engine import assemble

    def probe(path: str) -> float:
        try:
            return _mp4_duration(path)
        except (OSError, ValueError, IndexError, struct.error) as exc:
            log.warning("mvhd 길이 측정 실패(%s): %s", path, exc)
            return 0.0

    assemble.probe_duration = probe  # type: ignore[assignment]
    log.info("ffprobe 없음 → mvhd 길이 측정으로 대체(도구 한정)")


def _load(tag: str, n_cuts: int, want_video: bool) -> dict:
    src = GOLDEN / f"golden_{tag}_v3_regen.json"
    if not src.exists():
        raise SystemExit(f"지시서 없음: {src}")
    directive = json.loads(src.read_text(encoding="utf-8"))
    seq_id = directive["header"]["visual_sequences"][0]["sequence_id"]
    return slice_directive(directive, seq_id, n_cuts, want_video)


# ─────────────────────────────────────────────────────────────
# ① 발주서
# ─────────────────────────────────────────────────────────────
def cmd_order(tag: str, n_cuts: int, want_video: bool) -> None:
    mini = _load(tag, n_cuts, want_video)
    header = mini["header"]
    stage_by_cut = visual_sequence.cut_to_stage(header["visual_sequences"])
    out = ROOT / f"발주_{tag}"
    (out / "입력").mkdir(parents=True, exist_ok=True)

    L: list[str] = []
    L.append(f"# 웹 발주서 — 골든 {tag}")
    L.append("")
    L.append("> 아래 프롬프트는 **파이프라인이 실제로 보내는 문자열**입니다.")
    L.append("> 여기서 잘 나오면 코드도 잘 나오고, 여기서 깨지면 코드도 깨집니다.")
    L.append("")
    L.append("## 만드는 법")
    L.append("")
    L.append("- 모델 **Gemini 3 Pro Image**, 비율 **9:16 세로**")
    L.append("- **1번은 그냥**, 2번부터는 **바로 앞에서 나온 그림을 첨부**하고 붙여넣기")
    L.append(f"- 나온 파일을 `docs/발주_{tag}/입력/` 에 **`cut01.png`, `cut02.png` …** 로 저장")
    if want_video:
        L.append("- 영상까지 만들면 같은 폴더에 **`cut01.mp4`** 로 저장(없으면 스틸로 조립됩니다)")
    L.append("")
    L.append("다 넣으신 뒤 저에게 알려주시면 조립합니다.")
    L.append("")
    n_vid = sum(1 for c in mini["cuts"] if c.get("motion_source") == "video")
    n_still = len(mini["cuts"]) - n_vid
    L.append(f"**이번 발주: 그림 {len(mini['cuts'])}장" +
             (f" · 영상 {n_vid}개 (스틸 컷 {n_still}개는 영상 없음)**" if want_video else "**"))
    L.append("")
    L.append("---")
    L.append("")

    for i, cut in enumerate(mini["cuts"], 1):
        stage = stage_by_cut.get(int(cut["cut_no"])) or {}
        referenced = i > 1
        prompt = image_provider._build_image_prompt(cut, header, referenced=referenced)
        L.append(f"## {i}번 → `cut{i:02d}.png`")
        L.append("")
        L.append(f"- 나레이션: {cut.get('narration_ko')}")
        L.append(f"- 이 단계의 변화: {stage.get('observable_change') or '(없음)'}")
        # ★ 등급제(v2): 이 컷이 몇 초짜리인지·몇 번 뽑는지를 발주서에 적는다.
        #   웹에서 만들 때 길이를 알아야 같은 조건이 되고, 그래야 실측이 성립한다.
        tier = sequence_tier.effective_tier(cut, header)
        if tier["tier"]:
            sec = sequence_tier.clip_sec_for(cut, header)
            n = sequence_tier.candidates_for(cut, header)
            label = {"invest": "투자", "standard": "표준", "economy": "절약"}[tier["tier"]]
            line = f"- 등급: **{label}** · 클립 **{sec}초**"
            if n > 1:
                line += f" · **{n}번 뽑아 좋은 것 채택**"
            if tier["reasons"]:
                line += f"  (투자 아님: {', '.join(tier['reasons'])})"
            L.append(line)
        beats = cut.get("temporal_plan") or []
        if beats:
            L.append("- 연출(이 클립 안의 편집 시퀀스):")
            for b in beats:
                cam = config.CAMERA_PROSE.get(b["camera"], b["camera"])
                chg = config.MUTATION_PROSE.get(b.get("mutation") or "", "")
                tail = f" — {b.get('entity_id','')} {chg}" if chg else ""
                L.append(f"    · {b['t0']:.1f}–{b['t1']:.1f}s  {cam}{tail}")
        L.append(f"- 첨부: **{'앞 그림(cut%02d.png)' % (i - 1) if referenced else '없음'}**")
        L.append("")
        L.append("```")
        L.append(prompt)
        L.append("```")
        L.append("")
        if want_video and cut.get("motion_source") != "video":
            # ★ 스틸 컷은 영상이 없는 것이 **정상**이다. 말해 주지 않으면 빠뜨린 것처럼 보인다
            #   (실제로 그렇게 보였다 — 운영자가 "6번은 사진만 있는데?" 라고 물었다).
            why = ("지시서가 영상을 원했지만 원본 편에서 **영상 클립 상한**에 걸려 스틸로"
                   " 내려간 컷입니다" if str(cut.get("motion_value") or "") in ("high", "medium")
                   else "움직임이 필요 없다고 판정된 컷입니다")
            L.append(f"> **이 컷은 스틸입니다 — 영상은 만들지 않습니다.** {why}.")
            L.append("")
        if want_video and cut.get("motion_source") == "video":
            L.append(f"### {i}번 영상 → `cut{i:02d}.mp4`  (방금 만든 `cut{i:02d}.png` 를 첨부)")
            L.append("")
            L.append("```")
            L.append(video_provider.build_motion_prompt(cut, header))
            L.append("```")
            L.append("")
        L.append("---")
        L.append("")

    path = out / "발주서.md"
    path.write_text("\n".join(L), encoding="utf-8")
    (out / "지시서.json").write_text(json.dumps(mini, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"발주서: {path}")
    print(f"받은 파일 넣을 곳: {out / '입력'}")
    print(f"컷 {len(mini['cuts'])}개 · 영상 {'포함' if want_video else '없음'}")


# ─────────────────────────────────────────────────────────────
# ② 조립 — 생성만 파일로 갈아끼우고 나머지는 진짜로 돈다
# ─────────────────────────────────────────────────────────────
def cmd_build(tag: str, lang: str) -> None:
    _ensure_ffmpeg()
    _ensure_ffprobe()
    out = ROOT / f"발주_{tag}"
    mini = json.loads((out / "지시서.json").read_text(encoding="utf-8"))
    inbox = out / "입력"

    missing = [c["cut_no"] for i, c in enumerate(mini["cuts"], 1)
               if not (inbox / f"cut{i:02d}.png").exists()]
    if missing:
        raise SystemExit(f"입력 그림이 없다: cut{missing[0]:02d}.png … "
                         f"({inbox} 에 cut01.png 부터 넣어라)")

    # ★ 생성 함수만 갈아끼운다. 컷 번호 → 준비된 파일.
    def fake_image(cut, header, out_path, model="", ref_path=None):
        idx = [c["cut_no"] for c in mini["cuts"]].index(int(cut["cut_no"])) + 1
        shutil.copyfile(inbox / f"cut{idx:02d}.png", out_path)
        return out_path, 0.0

    def fake_clip(cut, header, out_path, duration, lang="ko", start_image=None):
        idx = [c["cut_no"] for c in mini["cuts"]].index(int(cut["cut_no"])) + 1
        src = inbox / f"cut{idx:02d}.mp4"
        if not src.exists():
            raise RuntimeError(f"cut{idx:02d}.mp4 없음 → 스틸로 폴백")
        shutil.copyfile(src, out_path)
        return out_path, 0.0

    from engine import render
    render.image_provider.generate_image = fake_image      # type: ignore[assignment]
    render.video_provider.generate_clip = fake_clip        # type: ignore[assignment]
    # ★ provider 가 'placeholder' 면 _gen_still 이 generate_image 를 **아예 부르지 않고**
    #   회색 판때기를 그린다 — 가짜를 꽂아도 소용이 없다(실측으로 걸렸다).
    #   유료 경로로 들여보내되 네트워크는 위 fake 가 가로챈다.
    render.config.IMAGE_PROVIDER = "gemini"                # type: ignore[attr-defined]
    render.config.VIDEO_PROVIDER = "veo"                   # type: ignore[attr-defined]
    # ★ 원장은 건드리지 않는다. 유료 호출이 없었으므로 기록할 비용도 없다 —
    #   $0 행을 쌓으면 원장이 또 거짓말을 한다(2026-08-29 에 테스트가 468행을 쌓았다).
    render.cost_ledger.record = lambda *a, **k: None        # type: ignore[assignment]

    final = out / f"완성_{tag}_{lang}.mp4"
    print(f"조립 시작 — 유료 호출 0, 나머지는 진짜 파이프라인")
    render.render_directive_local(mini, str(final), lang=lang)
    print(f"\n=== 완성: {final}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("order"); o.add_argument("tag", choices=["A", "B"])
    o.add_argument("--cuts", type=int, default=6)
    o.add_argument("--video", action="store_true")
    b = sub.add_parser("build"); b.add_argument("tag", choices=["A", "B"])
    b.add_argument("--lang", default="ko")
    a = ap.parse_args()
    if a.cmd == "order":
        cmd_order(a.tag, a.cuts, a.video)
    else:
        cmd_build(a.tag, a.lang)


if __name__ == "__main__":
    main()
