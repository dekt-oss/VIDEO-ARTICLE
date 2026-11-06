"""설명형 릴스 S1 무료 조립 리허설(기획 v2 §3-10). 돈·네트워크·공급자 호출 0.

    python -m scripts.explainer_rehearsal              # 가짜 클립 9개(64초) + 시험음 나레이션 → 48초 조립 → 자동 검사 → 강제 시험
    python -m scripts.explainer_rehearsal --tts edge   # 나레이션만 무료 TTS(edge)로. 네트워크를 쓴다 — 기본은 안 쓴다

★ 화면은 ffmpeg testsrc2(움직이는 시험 영상)이고 말은 자리 표시 문장이다. 술에 관한 사실을 한 줄도 말하지 않는다.
★ 합격해도 "돌아간다"일 뿐이다. 길이·속도가 설명으로 충분한지는 운영자가 화면으로 본다(§3-10 S1).
산출물: docs/preview-<날짜>/explainer-rehearsal/ (gitignore)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from engine import config
from engine import drinks_explainer as dx
from engine.drinks_render import FONT_DIR, sha256_file
from engine.util import today_local

ROOT = Path(__file__).resolve().parents[1]
FAKE_FPS = 24      # 공급자 영상과 다른 프레임 수 — 렌더가 맞추는지까지 본다
FAKE_SIZE = "720x1280"
HOOK = "(리허설) 훅 자막 자리"
PLACEHOLDER = "자리 표시 문장이에요."

# (자산, 역할, 원본 길이 ms) — 기획 v2 §3-6-2 표. 도해 3 + 실사 6 = 64초.
ASSET_PLAN: tuple[tuple[str, str, int], ...] = (
    ("M1", "mechanism", 8000), ("M2", "mechanism", 8000), ("M3", "mechanism", 8000),
    ("R1", "reality", 4000), ("R2", "reality", 6000), ("R3", "reality", 6000),
    ("R4", "reality", 8000), ("R5", "reality", 8000), ("R6", "reality", 8000),
)


def plan_beats() -> list[dx.Beat]:
    """§3-6-2 의 비트 9개(배속 전 ms). 나레이션은 자리 표시 — 근거가 있는 문장이 아니다."""
    def beat(i: int, tts: int, shots: tuple[dx.Shot, ...], **kw: Any) -> dx.Beat:
        sentences = max(1, tts // 2400)
        return dx.Beat(beat_id=f"B{i}", tts_ms=tts, shots=shots, narration=" ".join([f"리허설 {i}번."] + [PLACEHOLDER] * sentences), keyword="자리 표시", **kw)

    return [
        beat(1, 3600, (dx.Shot("M1", "loop", raw_ms=1800, src_start_ms=5400), dx.Shot("R1", "flash_forward"))),
        beat(2, 7500, (dx.Shot("M1", "cut_to_mechanism"),)),
        beat(3, 7500, (dx.Shot("M2", "match"),)),
        beat(4, 5400, (dx.Shot("R2", "cut_to_mechanism"),)),
        beat(5, 5400, (dx.Shot("R3", "match"),)),
        beat(6, 6600, (dx.Shot("R4", "match"),), card_text="(리허설) 코드 글자 카드 자리"),
        beat(7, 7500, (dx.Shot("M3", "cut_to_mechanism"),)),
        beat(8, 7500, (dx.Shot("R5", "cut_to_mechanism"),)),
        beat(9, 6000, (dx.Shot("R6", "match"),), tail_ms=600, tail_text="(리허설) 보낼 이유 한 줄 자리"),
    ]


def _run(argv: list[str], cwd: Optional[str] = None) -> None:
    proc = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패({proc.returncode}): {proc.stderr[-400:]}")


def make_fake_clip(path: str, ms: int, *, label: str = "", hue: int = 0, frozen: bool = False) -> None:
    """움직이는 시험 영상. 소리도 넣는다 — 렌더가 원본 소리를 버리는지 보려고. frozen=True 면 멈춘 영상(정지 검사 시험용).
    ★ 글꼴은 상대 경로로 쓴다 — 한글 경로의 글꼴을 필터가 열면 ffmpeg 가 죽는다(drinks_explainer.prepare_burn_dir)."""
    sec = ms / 1000.0
    folder, name = os.path.split(os.path.abspath(path))
    src = f"color=c=gray:s={FAKE_SIZE}:r={FAKE_FPS}:d={sec:.3f}" if frozen else f"testsrc2=s={FAKE_SIZE}:r={FAKE_FPS}:d={sec:.3f}"
    vf = f"hue=h={hue}"
    if label:
        shutil.copyfile(os.path.join(FONT_DIR, config.DRINKS_EXPLAINER_FONT_FILE), os.path.join(folder, "_label_font.otf"))
        vf += f",drawtext=fontfile=_label_font.otf:text='{label}':fontsize=96:fontcolor=white:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=h*0.4"
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"sine=frequency=880:duration={sec:.3f}",
          "-vf", vf, "-t", f"{sec:.3f}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", name], cwd=folder)
    if label:
        os.remove(os.path.join(folder, "_label_font.otf"))


def make_tone(path: str, ms: int, *, silent: bool = False) -> None:
    """자리 표시 나레이션(시험음). 정확한 길이가 필요해 wav 로 만든다(aac 는 앞뒤가 늘어난다)."""
    sec = ms / 1000.0
    src = f"anullsrc=r=48000:cl=mono:d={sec:.3f}" if silent else f"sine=frequency=220:sample_rate=48000:duration={sec:.3f}"
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src, "-t", f"{sec:.3f}", "-af", "volume=0.25", "-c:a", "pcm_s16le", path])


def make_assets(clip_dir: Path) -> dict[str, dx.Asset]:
    clip_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dx.Asset] = {}
    for i, (name, role, ms) in enumerate(ASSET_PLAN):
        p = clip_dir / f"{name}.mp4"
        make_fake_clip(str(p), ms, label=name, hue=i * 40)
        out[name] = dx.Asset(asset_id=name, path=str(p), sha256=sha256_file(str(p)), role=role, planned_ms=ms)
    return out


def make_narration(beats: list[dx.Beat], audio_dir: Path, tts: str) -> list[dx.Beat]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for b in beats:
        if tts == "edge":   # 선택 사항: 네트워크를 쓴다. 기본 실행에서는 닿지 않는다. 길이는 실측이 되므로 계획과 달라진다.
            from engine.providers import tts as tts_provider

            p = str(audio_dir / f"{b.beat_id}.m4a")
            tts_provider._edge_synthesize(b.narration, p, config.EDGE_TTS_VOICE)
        else:
            p = str(audio_dir / f"{b.beat_id}.wav")
            make_tone(p, b.tts_ms)
        out.append(dataclasses.replace(b, narration_path=p))
    return out


class Tripwire:
    """유료·네트워크 경로에 걸어 두는 줄 — 닿으면 세고 예외를 던진다. '0회'를 말이 아니라 숫자로 남기려고 있다."""

    def __init__(self, *, allow_network: bool = False):
        self.hits: list[str] = []
        self.allow_network = allow_network
        self._saved: list[tuple[Any, str, Any]] = []

    def _wire(self, obj: Any, name: str, label: str) -> None:
        self._saved.append((obj, name, getattr(obj, name)))

        def tripped(*_a: Any, **_k: Any) -> Any:
            self.hits.append(label)
            raise RuntimeError(f"줄에 걸렸습니다: {label}")
        setattr(obj, name, tripped)

    def __enter__(self) -> "Tripwire":
        from engine import drinks_paid
        from engine.providers import image, video

        self._wire(video, "generate_clip", "video.generate_clip")
        self._wire(video, "_veo_i2v", "video._veo_i2v")
        self._wire(video, "send_explainer_request", "video.send_explainer_request")
        self._wire(image, "generate_image", "image.generate_image")
        self._wire(image, "gemini_image_once", "image.gemini_image_once")
        self._wire(drinks_paid, "buy", "drinks_paid.buy")
        if not self.allow_network:
            self._wire(socket.socket, "connect", "socket.connect")
            self._wire(socket, "create_connection", "socket.create_connection")
        return self

    def __exit__(self, *_exc: Any) -> None:
        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)


def _copy_assets(assets: dict[str, dx.Asset], dest: Path) -> dict[str, dx.Asset]:
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, a in assets.items():
        p = dest / os.path.basename(a.path)
        shutil.copyfile(a.path, p)
        out[name] = dataclasses.replace(a, path=str(p))
    return out


def _case_delete(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    os.remove(assets["M2"].path)
    return assets


def _case_truncate(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    p = assets["R3"].path
    with open(p, "r+b") as f:
        f.truncate(os.path.getsize(p) // 2)
    return assets


def _case_truncate_reregistered(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    """해시도 다시 적어 해시 검사를 지나가게 한 뒤 — ffprobe 가 잡는지."""
    p = assets["R3"].path
    with open(p, "r+b") as f:
        f.truncate(os.path.getsize(p) // 2)
    return {**assets, "R3": dataclasses.replace(assets["R3"], sha256=sha256_file(p))}


def _case_short(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    """필요한 길이(M1 7,500ms)보다 0.3초 짧은 정상 파일. 해시도 맞다 — 실측만이 잡는다."""
    p = assets["M1"].path
    make_fake_clip(p, 7200, label="M1", hue=0)
    return {**assets, "M1": dataclasses.replace(assets["M1"], sha256=sha256_file(p))}


def _case_hash_swap(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    shutil.copyfile(assets["R5"].path, assets["M3"].path)
    return assets


def _case_audio_only(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    p = assets["R2"].path
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "aac", "-f", "mp4", p])
    return {**assets, "R2": dataclasses.replace(assets["R2"], sha256=sha256_file(p))}


def _case_image(assets: dict[str, dx.Asset], d: Path) -> dict[str, dx.Asset]:
    from PIL import Image

    p = str(d / "still.png")
    Image.new("RGB", (720, 1280), (40, 40, 40)).save(p)
    return {**assets, "R4": dataclasses.replace(assets["R4"], path=p, sha256=sha256_file(p))}


FORCED: tuple[tuple[str, str, Any, bool], ...] = (
    ("1", "클립 하나 삭제", _case_delete, True),
    ("2", "파일 끝을 잘라 손상", _case_truncate, True),
    ("3", "필요보다 0.3초 짧은 클립", _case_short, True),
    ("4", "해시가 다른 파일로 바꿔치기", _case_hash_swap, True),
    ("+a", "손상 + 해시까지 다시 적음", _case_truncate_reregistered, False),
    ("+b", "영상 스트림 없는 파일", _case_audio_only, False),
    ("+c", "영상 목록에 그림 파일", _case_image, False),
)
EXPECTED = {"1": "clip_missing", "2": "clip_corrupt", "3": "clip_short", "4": "clip_corrupt", "+a": "clip_corrupt", "+b": "clip_corrupt", "+c": "clip_corrupt"}


def run_forced(assets: dict[str, dx.Asset], beats: list[dx.Beat], base: Path) -> list[dict[str, Any]]:
    """강제 시험. 지난번 출력이 남아 있어도 지워지는지까지 본다(옛 파일 = 통과로 읽히면 안 된다)."""
    rows = []
    for key, title, mutate, _core in FORCED:
        d = base / f"forced-{key.replace('+', 'x')}"
        if d.exists():
            shutil.rmtree(d)
        case_assets = mutate(_copy_assets(assets, d / "clips"), d)
        work = d / "work"
        out = d / "final.mp4"
        out.write_bytes(b"stale output from an earlier run")
        with Tripwire() as wire:
            code, state, problems = "", "", []
            try:
                dx.render_explainer(beats, case_assets, hook_text=HOOK, out_path=str(out), work_dir=str(work))
            except dx.ExplainerStop as exc:
                code, state, problems = exc.code, exc.state, exc.problems
        made = sorted(p.name for p in work.glob("*")) if work.exists() else []
        rows.append({"case": key, "title": title, "stopped": bool(code), "code": code, "state": state, "expected": EXPECTED[key],
                     "paid_calls": len(wire.hits), "stills_used": 0 if not made else len([m for m in made if m.lower().endswith((".png", ".jpg"))]),
                     "output_exists": out.exists(), "cuts_rendered": len([m for m in made if m.startswith("cut_")]), "problems": problems})
    return rows


def print_table(rows: list[dict[str, Any]]) -> None:
    head = ["시험", "내용", "멈춤", "코드", "상태", "유료호출", "사진대체", "출력파일", "자른컷"]
    print("  ".join(head))
    for r in rows:
        print("  ".join([r["case"], r["title"], "예" if r["stopped"] else "아니오", r["code"] or "-", r["state"] or "-", str(r["paid_calls"]), str(r["stills_used"]),
                         "있음" if r["output_exists"] else "없음", str(r["cuts_rendered"])]))


def run(out_root: Path, *, tts: str = "") -> dict[str, Any]:
    """전체 리허설. 반환: 보고용 dict. 합격 기준을 어기면 passed=False."""
    assets = make_assets(out_root / "clips")
    beats = make_narration(plan_beats(), out_root / "narration", tts)
    planned = {a: ms for a, _, ms in ASSET_PLAN}
    with Tripwire(allow_network=tts == "edge") as wire:
        rendered = dx.render_explainer(beats, assets, hook_text=HOOK, out_path=str(out_root / "final.mp4"), work_dir=str(out_root / "work"))
        qa = dx.run_auto_qa(rendered.out_path, rendered.manifest)
    paid = list(wire.hits)
    tl_cuts = rendered.manifest["cuts"]
    last: dict[str, int] = {}
    for c in tl_cuts:
        last[c["asset_id"]] = max(last.get(c["asset_id"], 0), c["src_end_ms"])
    print(f"자산 {len(assets)}개 · 원본 합계 {sum(planned.values()) / 1000:g}초 · 도해 {sum(1 for _, r, _m in ASSET_PLAN if r == 'mechanism')}개")
    print(f"타임라인 배속 전 {rendered.manifest['raw_ms']}ms → 최종 계획 {rendered.manifest['final_ms']}ms · 재생 속도 {rendered.manifest['playback_speed']}배 · 편집 컷 {len(tl_cuts)}개")
    print(f"자산 여유(ms): " + " ".join(f"{a}={planned[a] - last[a]}" for a in planned))
    print(f"자동 검사: {qa.state} · 막는 코드 {qa.blocks or '없음'} · 알림 {qa.warns or '없음'}")
    print(f"실측: 길이 {qa.signals['duration_sec']:.3f}s · {qa.signals['width']}x{qa.signals['height']} · {qa.signals['fps']}fps · 소리 크기 {qa.signals['lufs']} LUFS · "
          f"정지 {qa.signals['freeze']} · 검은 화면 {qa.signals['black']} · 파일 {qa.signals['bytes'] / 1e6:.1f}MB")
    print(f"유료·네트워크 줄에 걸린 횟수: {len(paid)} · 렌더 기록의 사진 대체: {rendered.manifest['video_fallbacks']} · 모든 컷 kind=clip: {all(c['kind'] == 'clip' for c in tl_cuts)}")
    print()
    forced = run_forced(assets, beats, out_root)
    print_table(forced)
    forced_ok = all(r["stopped"] and r["code"] == r["expected"] and r["state"] == "blocked_assets" and r["paid_calls"] == 0 and r["stills_used"] == 0
                    and not r["output_exists"] and r["cuts_rendered"] == 0 for r in forced)
    report = {"final": rendered.out_path, "manifest": rendered.manifest_path, "qa": {"state": qa.state, "blocks": qa.blocks, "warns": qa.warns, "signals": qa.signals},
              "paid_or_network_hits": paid, "forced": forced, "forced_ok": forced_ok, "passed": qa.ok and forced_ok and not paid}
    with open(out_root / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print()
    print(f"결과물: {rendered.out_path}")
    print(f"합격(자동 항목만): {report['passed']}  ★ 길이·속도가 설명으로 충분한지는 운영자가 화면으로 판정한다(미판정)")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="설명형 S1 무료 조립 리허설")
    ap.add_argument("--tts", choices=["edge"], default="", help="나레이션을 무료 TTS 로(네트워크 사용). 없으면 시험음")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out_root = ROOT / "docs" / f"preview-{today_local().isoformat()}" / "explainer-rehearsal"
    out_root.mkdir(parents=True, exist_ok=True)
    report = run(out_root, tts=args.tts)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
