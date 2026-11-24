"""모션그래픽 지시서 → HyperFrames 프로젝트 → mp4. 그림·영상 생성 API 를 부르지 않는다.

흐름: 컷별 Edge TTS(+1.2배속) → 길이·큐 시각 → 장면 HTML·자막·효과음 → index.html
      → `npx hyperframes render` → 음량 정규화(-14 LUFS).
손작업 원본: content_samsung_auto_2027/side_usedcar/_build/{tts,gen,scenes}.py.

반환 계약(report_render 가 소비): {"mp4", "total_sec", "cut_map", "warnings"}.
★ TTS 는 실패하면 **잡을 실패시킨다**(공용 tts.synthesize 는 무음으로 폴백한다 — 소리 없는
  모션그래픽은 쓸모가 없고, 조용히 done 이 되면 아무도 모른다. 메모리: 로컬 렌더 env 사고).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .. import config, speech_text
from ..util import log
from . import schema, templates

ROOT = Path(__file__).resolve().parents[2]
FONTS = ("Pretendard-Black.otf", "Pretendard-ExtraBold.otf", "Pretendard-Bold.otf")
ASSET_DIR = ROOT / "assets" / "motion"
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"

# 효과음: 장면 전환 3종을 돌려 쓰고, 큐마다 템플릿별 소리.
_CUT_SFX = ("whoosh-short", "whoosh", "whoosh-cinematic")
_CUE_SFX = {"hook_number": ("pop", "impact-bass-1"), "bar_compare": ("pop", "pop"),
            "vs_split": ("click-soft", "click-soft"), "icon_ratio": ("pop", "pop", "impact-bass-1"),
            "card_stack": ("click-soft",) * 5, "strike_vs_fact": ("click-soft", "impact-bass-2"),
            "flow_chain": ("click-soft", "pop"), "cycle3": ("click-soft",) * 3 + ("impact-bass-2", "pop"),
            "scale_tilt": ("impact-bass-2",), "stamp_card": ("impact-bass-1", "pop"), "text_card": ("pop",)}
_SFX_VOL = {"pop": 0.4, "click-soft": 0.45, "impact-bass-1": 0.45, "impact-bass-2": 0.4, "riser": 0.25,
            "whoosh": 0.3, "whoosh-short": 0.35, "whoosh-cinematic": 0.3}


def _run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _dur(path: str) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout
    return float(out.strip() or 0.0)


def _tts(text: str, out_mp3: str) -> float:
    """Edge 현수 → 1.2배속 mp3. 실패하면 재시도 후 예외(잡 실패)."""
    import asyncio
    import edge_tts

    raw = out_mp3 + ".raw.mp3"
    last: Exception | None = None
    for _ in range(config.MOTION_TTS_RETRIES + 1):
        try:
            async def go() -> None:
                await edge_tts.Communicate(text, config.EDGE_TTS_VOICE, rate=config.EDGE_TTS_RATE).save(raw)
            asyncio.run(asyncio.wait_for(go(), timeout=config.TTS_TIMEOUT_SEC))
            if os.path.getsize(raw) > 0:
                break
        except Exception as exc:  # noqa: BLE001 — 일시 오류(NoAudioReceived)는 재시도
            last = exc
    else:
        raise RuntimeError(f"모션 TTS 실패: {last}")
    p = _run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-filter:a", f"atempo={config.MOTION_TTS_SPEED}",
              "-ar", "48000", out_mp3])
    if p.returncode != 0:
        raise RuntimeError(f"모션 TTS 변환 실패: {p.stderr[-200:]}")
    os.remove(raw)
    return _dur(out_mp3)


def speech_spans(path: str, total: float) -> list[tuple[float, float]]:
    err = _run(["ffmpeg", "-i", path, "-af",
                f"silencedetect=noise={config.MOTION_SILENCE_DB}:d={config.MOTION_SILENCE_MIN_SEC}",
                "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    sil = list(zip(starts, ends + [total] * (len(starts) - len(ends))))
    spans, t = [], 0.0
    for a, b in sil:
        if a > t + 0.05:
            spans.append((t, a))
        t = max(t, b)
    if t < total - 0.05:
        spans.append((t, total))
    return spans or [(0.0, total)]


def char_to_time(spans: list[tuple[float, float]], frac: float) -> float:
    """말하는 구간 합에서 글자 비율 위치의 시각.

    shortcut: Edge 한국어는 단어 시각을 안 준다(config EDGE_TTS 주석) — 글자 수 비례라 ±0.2~0.3초
    어긋날 수 있다. 숫자를 풀어 읽는 문장(15.9% → 십오 점 구)에서 더 어긋난다. 단어 시각이 오면 교체.
    """
    need = max(0.0, min(1.0, frac)) * sum(b - a for a, b in spans)
    for a, b in spans:
        if need <= b - a:
            return a + need
        need -= b - a
    return spans[-1][1]


def caption_chunks(text: str, keep: str = "") -> list[str]:
    """뜻 단위 자막: 문장부호에서 끊고 공백 제외 12자를 넘으면 어절에서 끊는다. keep 은 안 쪼갠다."""
    nb = " "
    if keep:
        text = text.replace(keep, keep.replace(" ", nb))
    out: list[str] = []
    for clause in re.split(r"(?<=[.,?!])\s+", text.strip()):
        cur: list[str] = []
        for w in clause.split(" "):
            if cur and len("".join(cur + [w])) > config.MOTION_CAPTION_MAX_CHARS:
                out.append(" ".join(cur)); cur = []
            cur.append(w)
        if cur:
            out.append(" ".join(cur))
    return [c for c in out if c.strip()]


def _index_html(total: float, hosts: str, vos: str, sfx: str, title: list[str]) -> str:
    l1 = templates.esc(title[0] if title else "")
    l2 = templates.esc(title[1] if len(title) > 1 else "")
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="{GSAP}"></script>
    <style>
      @font-face {{ font-family: "PretendardBlack"; src: url("assets/fonts/Pretendard-Black.otf"); }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: #eef1f6; }}
      #root {{ width: 100%; height: 100%; position: relative; }}
      #bg {{ position: absolute; inset: 0; background: radial-gradient(120% 60% at 50% 38%, #ffffff 0%, #eef1f6 75%); }}
      .lb {{ position: absolute; left: 0; right: 0; background: #04060b; z-index: 4; }}
      #lb-top {{ top: 0; height: 320px; border-bottom: 6px solid #ffe000; }}
      #lb-bot {{ top: 1330px; bottom: 0; border-top: 6px solid #1d2842; }}
      #lb-title {{ position: absolute; left: 40px; right: 40px; top: 150px; text-align: center; font-family: "PretendardBlack"; line-height: 1.08; letter-spacing: -0.02em; word-break: keep-all; }}
      #lb-title .l1 {{ display: block; font-size: 62px; color: #ffffff; }}
      #lb-title .l2 {{ display: block; font-size: 74px; color: #ffe000; }}
    </style>
  </head>
  <body>
    <!-- engine/motion/build.py 가 생성 — 직접 고치지 말 것 -->
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
      <div id="bg"></div>
{hosts}
      <div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html"
        data-start="0" data-duration="{total}" data-track-index="2" data-track-kind="captions"
        data-width="1080" data-height="1920" style="z-index:5"></div>
      <div class="lb" id="lb-top" data-layout-allow-safe-zone>
        <div id="lb-title" data-layout-allow-safe-zone><span class="l1">{l1}</span><span class="l2">{l2}</span></div>
      </div>
      <div class="lb" id="lb-bot" data-layout-ignore></div>
{vos}
      <audio id="bgm" class="clip" src="assets/bgm.m4a" data-start="0" data-duration="{total}" data-track-index="20" data-volume="{config.MOTION_BGM_VOLUME}" data-fade-in="0.3" data-fade-out="1.2"></audio>
{sfx}
    </div>
    <script>window.__timelines["main"] = gsap.timeline({{ paused: true }});</script>
  </body>
</html>
"""


_CAPTIONS = """<template>
  <style>
    #root { position: absolute; inset: 0; }
    @font-face { font-family: "PretendardXB"; src: url("assets/fonts/Pretendard-ExtraBold.otf"); }
    .cap { position: absolute; left: 60px; right: 60px; top: 1130px; text-align: center; opacity: 0; }
    .cap-t { display: inline-block; font-family: "PretendardXB", sans-serif; font-size: 62px; line-height: 1.15; color: #fff;
             padding: 6px 26px; border-radius: 18px; background: rgba(20,26,42,0.82); max-width: 900px; word-break: keep-all; }
    .hl { color: #FFE000; }
  </style>
  <div id="root" data-composition-id="captions" data-width="1080" data-height="1920">
{CAPS}
  </div>
  <script>
    const tl = gsap.timeline({ paused: true });
    function show(sel, a, b) {
      tl.fromTo(sel, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.12, ease: "power2.out" }, a);
      tl.to(sel, { opacity: 0, duration: 0.08, ease: "power2.in" }, b - 0.08);
      tl.set(sel, { opacity: 0, visibility: "hidden" }, b);
    }
{SHOW}
    window.__timelines["captions"] = tl;
  </script>
</template>
"""


def build_project(directive: dict, proj: Path, meta: dict) -> dict[str, Any]:
    """프로젝트 폴더를 만든다(렌더는 안 함). 반환: total_sec·cut_map·warnings."""
    header = directive.get("header") or {}
    cuts = [c for c in (directive.get("cuts") or []) if isinstance(c, dict)]
    if not cuts:
        raise ValueError("모션 지시서에 컷이 없다")
    (proj / "compositions").mkdir(parents=True, exist_ok=True)
    (proj / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    (proj / "assets" / "voice").mkdir(parents=True, exist_ok=True)
    (proj / "assets" / "sfx").mkdir(parents=True, exist_ok=True)
    for f in FONTS:
        shutil.copy(ROOT / "assets" / "fonts" / f, proj / "assets" / "fonts" / f)
    for f in (ASSET_DIR / "sfx").glob("*.mp3"):
        shutil.copy(f, proj / "assets" / "sfx" / f.name)
    shutil.copy(ASSET_DIR / "bgm.m4a", proj / "assets" / "bgm.m4a")
    (proj / "hyperframes.json").write_text(json.dumps({"paths": {"blocks": "compositions", "assets": "assets"}}), encoding="utf-8")
    (proj / "meta.json").write_text(json.dumps({"id": "motion", "name": "motion"}), encoding="utf-8")

    warnings: list[str] = []
    t0, hosts, vos, caps, shows, sfx_rows, cut_map = 0.0, [], [], [], [], [], []
    for i, c in enumerate(cuts, 1):
        sid = f"s{i}"
        narr = str(c.get("narration_ko") or "").strip()
        mp3 = proj / "assets" / "voice" / f"vo{i:02d}.mp3"
        vo = _tts(speech_text.for_speech(narr) or narr, str(mp3))
        spans = speech_spans(str(mp3), vo)
        dur = round(vo + config.MOTION_SCENE_PAD_SEC, 2)
        nos = len(re.sub(r"\s", "", narr)) or 1
        m = c.get("motion") or {}
        tpl = str(m.get("template") or "text_card")
        cue_words = [str(w) for w in (m.get("cue_words") or [])]
        need = schema.TEMPLATE_CUES.get(tpl, 2)
        times: list[float] = []
        for w in cue_words:
            k = narr.find(w)
            if k < 0:
                warnings.append(f"motion_cue_missing:{i}:{w}")
                continue
            times.append(round(config.MOTION_VO_LEAD_SEC
                               + char_to_time(spans, len(re.sub(r"\s", "", narr[:k])) / nos), 2))

        def cue(n: int, _t: list[float] = times, _d: float = dur, _need: int = need) -> float:
            # 큐 낱말이 모자라면 장면을 고르게 나눈 시각(코덱스: 누락 시 비례 폴백)
            return _t[n] if n < len(_t) else round(_d * (n + 1) / (_need + 1), 2)

        html = templates.render_scene(sid, tpl, m.get("slots") or {}, cue, dur, str(m.get("source") or ""))
        (proj / "compositions" / f"{sid}.html").write_text(html, encoding="utf-8")
        hosts.append(f'      <div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" '
                     f'data-start="{round(t0, 2)}" data-duration="{dur}" data-track-index="1" data-track-kind="graphics" '
                     f'data-width="1080" data-height="1920" style="z-index:2"></div>')
        vos.append(f'      <audio id="vo-{sid}" class="clip" src="assets/voice/vo{i:02d}.mp3" '
                   f'data-start="{round(t0 + config.MOTION_VO_LEAD_SEC, 2)}" data-duration="{round(vo - 0.01, 2)}" '
                   f'data-track-index="3" data-volume="1"></audio>')
        # 자막 — 컷마다 한 벌(뜻 단위 덩어리)
        keep = cue_words[0] if cue_words else ""
        pos = 0
        for j, ch in enumerate(caption_chunks(narr, keep)):
            n = len(re.sub(r"\s", "", ch))
            a = t0 + config.MOTION_VO_LEAD_SEC + char_to_time(spans, pos / nos)
            pos += n
            b = t0 + config.MOTION_VO_LEAD_SEC + char_to_time(spans, pos / nos)
            body = templates.esc(ch.rstrip(".,")).replace(" ", " ")
            if keep and keep in body:
                body = body.replace(keep, f'<span class="hl">{templates.esc(keep)}</span>', 1)
            cid = f"cap-{i}-{j + 1}"
            caps.append(f'    <div id="{cid}" class="cap"><span class="cap-t">{body}</span></div>')
            shows.append(f'    show("#{cid}", {round(a - 0.05, 2)}, {round(b + 0.05, 2)});')
        if i > 1:
            sfx_rows.append((_CUT_SFX[i % 3], t0 - 0.1))
        for n, name in enumerate(_CUE_SFX.get(tpl, ())[:max(len(times), 1)]):
            sfx_rows.append((name, t0 + cue(n)))
        cut_map.append({"cut_no": i, "start_sec": round(t0, 2), "end_sec": round(t0 + dur, 2), "template": tpl})
        t0 += dur

    # 출처 끝 카드(고정)
    sid = f"s{len(cuts) + 1}"
    (proj / "compositions" / f"{sid}.html").write_text(templates.end_card(sid, meta), encoding="utf-8")
    hosts.append(f'      <div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" '
                 f'data-start="{round(t0, 2)}" data-duration="{config.MOTION_END_CARD_SEC}" data-track-index="1" '
                 f'data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:2"></div>')
    sfx_rows.append(("whoosh-short", t0 - 0.1))
    cut_map.append({"cut_no": len(cuts) + 1, "start_sec": round(t0, 2),
                    "end_sec": round(t0 + config.MOTION_END_CARD_SEC, 2), "template": "end_card"})
    total = round(t0 + config.MOTION_END_CARD_SEC, 2)

    lanes: dict[int, float] = {}
    sfx_tags = []
    for k, (name, at) in enumerate(sfx_rows):
        a = round(max(0.0, at), 2)
        d = round(_dur(str(proj / "assets" / "sfx" / f"{name}.mp3")) - 0.01, 2)
        lane = next((ln for ln in range(4, 12) if lanes.get(ln, -1.0) <= a), 11)
        lanes[lane] = a + d
        sfx_tags.append(f'      <audio id="sfx-{k}" class="clip" src="assets/sfx/{name}.mp3" data-start="{a}" '
                        f'data-duration="{d}" data-track-index="{lane}" data-volume="{_SFX_VOL.get(name, 0.35)}"></audio>')
    (proj / "compositions" / "captions.html").write_text(
        _CAPTIONS.replace("{CAPS}", "\n".join(caps)).replace("{SHOW}", "\n".join(shows)), encoding="utf-8")
    title = [str(x) for x in (header.get("title_lines") or [])][:2]
    (proj / "index.html").write_text(_index_html(total, "\n".join(hosts), "\n".join(vos), "\n".join(sfx_tags), title),
                                     encoding="utf-8")
    return {"total_sec": total, "cut_map": cut_map, "warnings": warnings}


def render(directive: dict, work_dir: str, meta: dict, lang: str = "ko") -> dict[str, Any]:
    """지시서 → 최종 mp4. 반환: {"mp4", "total_sec", "cut_map", "warnings"}."""
    if lang not in config.MOTION_LANGS:
        raise ValueError(f"모션그래픽은 {config.MOTION_LANGS} 만 지원한다(요청 {lang}) — 장면 글자가 한국어다")
    work = Path(work_dir).resolve()   # hyperframes 는 proj 에서 돈다 — 상대경로면 출력이 proj 안쪽에 생긴다
    proj = work / "motion_proj"
    info = build_project(directive, proj, meta)
    raw = proj / "raw.mp4"
    npx = shutil.which("npx") or "npx"
    p = _run([npx, "--yes", config.MOTION_HYPERFRAMES_PKG, "render", "-o", str(raw)], cwd=str(proj),
             timeout=config.MOTION_RENDER_TIMEOUT_SEC)
    if p.returncode != 0 or not raw.exists():
        raise RuntimeError(f"hyperframes 렌더 실패(rc={p.returncode}): {(p.stderr or p.stdout)[-600:]}")
    out = work / "final.mp4"
    q = _run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-c:v", "copy", "-af", config.MOTION_LOUDNORM,
              "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(out)])
    if q.returncode != 0:
        raise RuntimeError(f"음량 정규화 실패: {q.stderr[-300:]}")
    log.info("모션 렌더 완료: %.1f초 · 컷 %d · 경고 %d", info["total_sec"], len(info["cut_map"]), len(info["warnings"]))
    return {"mp4": str(out), **info}
