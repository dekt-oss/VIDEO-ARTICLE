"""하이퍼프레임(HTML→영상) 렌더 + 음악 박자 싱크. 2026-11-26. docs/plans/2026-11-26-hyperframes-engine.md (S1~S2)

    python -m engine.hf_render --demo out.mp4                 # 밈 박자 데모 1편(0원, 로컬 또는 러너)
    python -m engine.hf_render --check-beats sooljjerigo-groove-117   # 박자표 ↔ 자동 검출 대조

흐름: 글 + 우리 음원(assets/music/ledger.json) → 박자표에 글을 맞춘 계획 → 템플릿(hf_templates/)을 임시 폴더에 채움
     → `npx hyperframes@고정버전 render --strict` → 길이·화면·소리 확인 → loudnorm(−14 LUFS) → mp4.

규칙:
  · 음원은 ledger 에 권리가 적힌 곡만. 박자표(bpm·첫 박)는 ledger 가 정본 — 자동 검출(`beats`)은 대조용이다.
  · 실패는 전부 HfRenderError. 빈 파일·짧은 파일·소리 없는 파일을 성공으로 넘기지 않는다.
  · 렌더는 네트워크에 기대지 않는다: gsap 은 템플릿 assets/lib, 글꼴은 저장소 assets/fonts 를 복사해 쓴다.
  · 돈을 쓰지 않는다. 주류 워커 연결(DRINKS_HF_ENABLED)은 S3 별도 승인 전까지 꺼져 있다.
"""

from __future__ import annotations

import html
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

from . import assemble, config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(ROOT, "assets", "music")
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
TEMPLATE_DIR = os.path.join(ROOT, "hf_templates")
FONT_FILES = ("Pretendard-Black.otf", "Pretendard-Bold.otf")


class HfRenderError(RuntimeError):
    """하이퍼프레임 렌더 실패. 메시지는 운영자가 읽는 한국어."""


@dataclass(frozen=True)
class Track:
    key: str
    path: str
    beat_period_sec: float
    first_beat_sec: float
    duration_sec: float


@dataclass(frozen=True)
class Slot:
    text: str
    start: float
    end: float
    key: bool = False


def load_track(key: str, ledger_path: Optional[str] = None) -> Track:
    ledger_path = ledger_path or os.path.join(MUSIC_DIR, "ledger.json")
    with open(ledger_path, encoding="utf-8") as f:
        tracks = json.load(f).get("tracks") or {}
    t = tracks.get(key)
    if not t:
        raise HfRenderError(f"음원 목록에 없는 곡입니다: {key} — assets/music/ledger.json 에 권리와 함께 올려야 씁니다")
    if not str(t.get("rights") or "").startswith("owned"):
        raise HfRenderError(f"권리가 확인되지 않은 곡입니다: {key}")
    return Track(key, os.path.join(os.path.dirname(ledger_path), t["file"]), float(t["beat_period_sec"]),
                 float(t["first_beat_sec"]), float(t["duration_sec"]))


def beat_grid(track: Track) -> list[float]:
    """박자표 → 박자 시각들(곡 길이 안)."""
    out, k = [], 0
    while (t := track.first_beat_sec + k * track.beat_period_sec) < track.duration_sec:
        out.append(round(t, 4))
        k += 1
    return out


def plan_slots(items: list[dict[str, Any]], grid: list[float], period: float) -> tuple[list[Slot], float]:
    """글마다 박자 하나에 떨어지게. 각 글은 ms 를 박자 수로 반올림(최소 1박)만큼 머문다.
    마지막 글은 HF_CLOSING_HOLD_SEC 이상 머물도록 박자를 더 잡는다. 반환: (칸들, 영상 길이)."""
    if not items:
        raise HfRenderError("글이 없습니다")
    if not grid:
        raise HfRenderError("박자가 0개입니다 — 음원 박자표를 확인하세요")
    slots, i = [], 0
    for n, it in enumerate(items):
        text = str(it.get("text") or "").strip()
        if not text:
            raise HfRenderError(f"{n + 1}번째 글이 비어 있습니다")
        beats = max(1, round(int(it.get("ms") or 0) / 1000 / period))
        if n == len(items) - 1:
            beats = max(beats, math.ceil(config.HF_CLOSING_HOLD_SEC / period - 1e-9))
        if i + beats >= len(grid):
            raise HfRenderError(f"음원이 짧습니다 — 글 {len(items)}개에 박자 {i + beats + 1}개가 필요한데 {len(grid)}개뿐입니다")
        slots.append(Slot(text, grid[i], grid[i + beats], bool(it.get("key"))))
        i += beats
    return slots, slots[-1].end


def build_html(template: str, *, top_line: str, slots: list[Slot], duration: float, pulses: list[float],
               brand: str = "술째리고", accent: str = config.HF_DEFAULT_ACCENT) -> str:
    """템플릿 칸 채우기. 글은 전부 escape. 첫 글은 0초부터 보여 0프레임이 비지 않게 한다."""
    words, hits = [], []
    for n, s in enumerate(slots):
        start = 0.0 if n == 0 else s.start
        cls = "word key clip" if s.key else "word clip"
        words.append(f'      <h1 id="w{n}" class="{cls}" data-start="{start:.3f}" data-duration="{s.end - start:.3f}" '
                     f'data-track-index="2">{html.escape(s.text)}</h1>')
        hits.append([f"#w{n}", round(s.start, 3)])
    fill = {
        "__WORDS__": "\n".join(words),
        "__HITS__": json.dumps(hits),
        "__PULSES__": json.dumps([round(p, 3) for p in pulses if p < duration]),
        "__TOP_LINE__": html.escape(top_line),
        "__BRAND__": html.escape(brand),
        "__ACCENT__": accent,
        "__DURATION__": f"{duration:.3f}",
    }
    for k, v in fill.items():
        template = template.replace(k, v)
    if any(k in template for k in fill):
        raise HfRenderError("템플릿 칸이 남았습니다")
    return template


def render_command(out_path: str) -> list[str]:
    npx = shutil.which("npx") or "npx"
    return [npx, "--yes", f"hyperframes@{config.HF_CLI_VERSION}", "render", "--strict", "-o", out_path]


def beats_command(audio_path: str) -> list[str]:
    npx = shutil.which("npx") or "npx"
    return [npx, "--yes", f"hyperframes@{config.HF_CLI_VERSION}", "beats", audio_path, "--json"]


def _env() -> dict[str, str]:
    return {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1"}


def parse_beats_json(stdout: str) -> list[float]:
    """`hyperframes beats --json` 출력 → 박자 시각. 앞에 로그가 섞여도 첫 '{' 부터 읽는다."""
    i = stdout.find("{")
    if i < 0:
        raise HfRenderError("박자 검출 출력이 JSON 이 아닙니다")
    data = json.loads(stdout[i:])
    if not data.get("ok", True):
        raise HfRenderError(f"박자 검출 실패: {data.get('error') or data}")
    beats = [float(b) for b in data.get("beatTimes") or []]
    if not beats:
        raise HfRenderError("박자를 하나도 찾지 못했습니다")
    return beats


def match_ratio(detected: list[float], grid: list[float], tol: float = config.HF_BEAT_MATCH_TOLERANCE_SEC) -> float:
    """검출 박자 중 박자표에 tol 안으로 맞는 비율."""
    if not detected or not grid:
        return 0.0
    hit = sum(1 for d in detected if min(abs(d - g) for g in grid) <= tol)
    return hit / len(detected)


def check_beats(track: Track) -> dict[str, Any]:
    out = subprocess.run(beats_command(track.path), capture_output=True, text=True, encoding="utf-8",
                         timeout=config.HF_RENDER_TIMEOUT_SEC, env=_env())
    if out.returncode != 0:
        raise HfRenderError(f"박자 검출 명령 실패(코드 {out.returncode}): {out.stderr[-400:]}")
    detected = parse_beats_json(out.stdout)
    ratio = match_ratio(detected, beat_grid(track))
    return {"track": track.key, "detected": len(detected), "ratio": round(ratio, 3),
            "ok": ratio >= config.HF_BEAT_MATCH_MIN_RATIO}


def _run(cmd: list[str], cwd: Optional[str] = None) -> None:
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=config.HF_RENDER_TIMEOUT_SEC, env=_env())
    if out.returncode != 0:
        raise HfRenderError(f"명령 실패(코드 {out.returncode}): {' '.join(cmd[:4])} … {(out.stderr or out.stdout)[-600:]}")


def verify_output(probe: dict[str, Any], expected_sec: float) -> None:
    """렌더 결과가 계획과 맞는가. 하나라도 어긋나면 실패."""
    if (probe.get("width"), probe.get("height")) != (config.RENDER_WIDTH, config.RENDER_HEIGHT):
        raise HfRenderError(f"화면 크기가 다릅니다: {probe.get('width')}×{probe.get('height')}")
    if not probe.get("audio_streams"):
        raise HfRenderError("소리가 없습니다")
    if abs(float(probe.get("duration_sec") or 0) - expected_sec) > config.HF_DURATION_TOLERANCE_SEC:
        raise HfRenderError(f"길이가 계획({expected_sec:.2f}초)과 다릅니다: {probe.get('duration_sec')}초")


def render_meme(*, top_line: str, items: list[dict[str, Any]], out_path: str,
                track_key: str = "sooljjerigo-groove-117", template: str = "meme-beat") -> dict[str, Any]:
    """밈 박자 영상 1편. 반환: 계획(칸·박자)·결과 정보. 실패는 HfRenderError."""
    from .drinks_render import _probe  # 무거운 Pillow 모듈 — 실제 렌더 때만

    track = load_track(track_key)
    grid = beat_grid(track)
    slots, duration = plan_slots(items, grid, track.beat_period_sec)
    src = os.path.join(TEMPLATE_DIR, template)
    with tempfile.TemporaryDirectory(prefix="hf-") as work:
        proj = os.path.join(work, "p")
        shutil.copytree(src, proj, ignore=shutil.ignore_patterns("index.template.html"))
        os.makedirs(os.path.join(proj, "assets", "fonts"), exist_ok=True)
        for f in FONT_FILES:
            shutil.copy(os.path.join(FONT_DIR, f), os.path.join(proj, "assets", "fonts", f))
        with open(os.path.join(src, "index.template.html"), encoding="utf-8") as f:
            page = build_html(f.read(), top_line=top_line, slots=slots, duration=duration, pulses=grid)
        with open(os.path.join(proj, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        fade_at = max(0.0, duration - config.HF_MUSIC_FADE_OUT_SEC)
        _run(["ffmpeg", "-v", "error", "-y", "-i", track.path, "-t", f"{duration:.3f}",
              "-af", f"afade=t=out:st={fade_at:.3f}:d={config.HF_MUSIC_FADE_OUT_SEC}",
              os.path.join(proj, "assets", "music.wav")])
        raw = os.path.join(work, "raw.mp4")
        _run(render_command(raw), cwd=proj)
        if not os.path.exists(raw) or os.path.getsize(raw) == 0:
            raise HfRenderError("렌더가 끝났다는데 파일이 없습니다")
        final = os.path.join(work, "final.mp4")
        _run(assemble.build_loudnorm_command(raw, final))
        try:
            probe = _probe(final)
        except subprocess.CalledProcessError as e:
            raise HfRenderError(f"결과 파일을 읽을 수 없습니다(깨진 mp4): {e}") from e
        verify_output(probe, duration)
        # 검증을 통과한 뒤에만 최종 위치로 — 중간에 죽어도 깨진 파일이 out_path 에 남지 않는다(2026-11-26 실제 발생)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.move(final, out_path)
    return {"out": out_path, "duration_sec": duration, "track": track.key,
            "slots": [s.__dict__ for s in slots], "probe": probe}


DEMO = {
    # 사실 주장 없는 데모 문구(원문 밖 주장 금지 규칙 — 데모도 지킨다)
    "top_line": "하이퍼프레임 박자 싱크 데모",
    "items": [{"text": "글자가", "ms": 500}, {"text": "박자에", "ms": 500, "key": True}, {"text": "맞춰", "ms": 1000},
              {"text": "떨어진다", "ms": 1000, "key": True}, {"text": "술째리고", "ms": 2000}],
}


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--demo":
        info = render_meme(out_path=argv[1], **DEMO)
        print(json.dumps({k: v for k, v in info.items() if k != "slots"}, ensure_ascii=False))
        return 0
    if len(argv) == 2 and argv[0] == "--check-beats":
        res = check_beats(load_track(argv[1]))
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["ok"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
