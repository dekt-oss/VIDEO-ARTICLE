"""모션그래픽 장면 템플릿 — 칸(slots) + 큐 시각 → HyperFrames 컴포지션 HTML.

손으로 만든 3편(content_samsung_auto_2027/side_usedcar·side_china·main_video_white)의 장면을
칸을 받는 함수로 굳혔다. LLM 은 HTML 을 쓰지 않는다 — 템플릿 이름과 칸 글자만 고른다.

좌표계: 1080×1920 '무대'를 0.76 배로 줄여 위아래 레터박스(320px·1330px~) 사이에 놓는다.
무대 y 160~1200 이 보이는 영역이고, 1224 아래는 자막이 덮는다.

모든 함수: fn(slots, cue, dur) -> (css, body, js)
  cue(i) = i 번째 큐 낱말이 들리는 장면 안 시각(초). 없으면 고르게 나눈 시각.
"""

from __future__ import annotations

import html
import re
from typing import Any, Callable

Cue = Callable[[int], float]

INK, AMBER, YELLOW, RED, BLUE, GREEN = "#141a2a", "#c98a00", "#ffe000", "#e5303d", "#4da3ff", "#1f8a4c"

HEAD = """<template>
  <style>
    @font-face { font-family: "PretendardBlack"; src: url("assets/fonts/Pretendard-Black.otf"); }
    @font-face { font-family: "PretendardXB"; src: url("assets/fonts/Pretendard-ExtraBold.otf"); }
    @font-face { font-family: "PretendardB"; src: url("assets/fonts/Pretendard-Bold.otf"); }
    #root { position: absolute; inset: 0; color: #141a2a; font-family: "PretendardB", sans-serif; word-break: keep-all; }
    .stage { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; transform: translate(0px, 200px) scale(0.76); transform-origin: 540px 0; }
    .src { position: absolute; top: 1130px; left: 0; right: 0; text-align: center; font-size: 38px; color: #6b7385; }
    .chip { position: absolute; left: 0; right: 0; text-align: center; }
    .chip span { display: inline-block; font-family: "PretendardXB"; font-size: 50px; padding: 14px 36px; border-radius: 999px; background: #ffe000; color: #0a0f1c; }
    .card { background: #ffffff; box-shadow: 0 8px 28px rgba(20,26,42,0.12); border-radius: 30px; }
    .h { position: absolute; top: 190px; left: 60px; right: 60px; text-align: center; font-family: "PretendardBlack"; font-size: 62px; line-height: 1.2; }
    .h small { display: block; font-family: "PretendardXB"; font-size: 40px; color: #5b6475; }
"""


def esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=False)


def _num(s: Any) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)*", str(s or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def page(sid: str, css: str, body: str, js: str, src: str) -> str:
    src_html = f'\n    <div class="src" id="{sid}-src">{esc(src)}</div>' if src else ""
    src_js = (f'\n    tl.fromTo("#{sid}-src", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.6);'
              if src else "")
    return (f'{HEAD}{css}\n  </style>\n  <div id="root" data-composition-id="{sid}" data-width="1080" data-height="1920">\n'
            f'    <div class="stage">\n{body}{src_html}\n    </div>\n  </div>\n  <script>\n'
            f'    const tl = gsap.timeline({{ paused: true }});\n{js}{src_js}\n'
            f'    window.__timelines["{sid}"] = tl;\n  </script>\n</template>\n')


def _t(x: float) -> str:
    return f"{max(0.0, x):.2f}"


# ── 1. 큰 숫자 + 칩 + 도장 ────────────────────────────────────
def hook_number(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    stamp = s.get("stamp_title")
    css = f"""
    #{sid}-chip {{ top: 230px; }}
    #{sid}-num {{ position: absolute; top: 360px; left: 0; right: 0; text-align: center; white-space: nowrap; }}
    #{sid}-num b {{ font-family: "PretendardBlack"; font-size: 300px; line-height: 1; letter-spacing: -0.04em; text-shadow: 0 10px 0 rgba(20,26,42,0.12); }}
    #{sid}-num i {{ font-style: normal; font-family: "PretendardBlack"; font-size: 140px; color: {AMBER}; margin-left: 8px; }}
    #{sid}-stamp {{ position: absolute; top: 760px; left: 0; right: 0; text-align: center; }}
    #{sid}-stamp .box {{ display: inline-block; border: 10px solid {RED}; border-radius: 26px; padding: 18px 44px; color: {RED}; background: rgba(255,255,255,0.94); }}
    #{sid}-stamp .k {{ display: block; font-family: "PretendardBlack"; font-size: 110px; line-height: 1; }}
    #{sid}-stamp .t {{ display: block; font-family: "PretendardXB"; font-size: 46px; margin-top: 10px; }}"""
    body = (f'    <div class="chip" id="{sid}-chip"><span>{esc(s.get("chip"))}</span></div>\n'
            f'    <div id="{sid}-num"><b>{esc(s.get("number"))}</b><i>{esc(s.get("unit"))}</i></div>\n')
    if stamp:
        body += (f'    <div id="{sid}-stamp"><div class="box" id="{sid}-box"><span class="k">{esc(stamp)}</span>'
                 f'<span class="t">{esc(s.get("stamp_sub"))}</span></div></div>\n')
    js = (f'    tl.fromTo("#{sid}-chip span", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, 0.05);\n'
          f'    tl.fromTo("#{sid}-num", {{ opacity: 0, scale: 0.6 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)" }}, {_t(cue(0) - 0.15)});\n')
    if stamp:
        js += (f'    tl.to("#{sid}-num", {{ y: -60, scale: 0.82, duration: 0.4, ease: "power3.inOut" }}, {_t(cue(1) - 0.5)});\n'
               f'    tl.fromTo("#{sid}-box", {{ opacity: 0, scale: 2.4, rotation: -14 }}, {{ opacity: 1, scale: 1, rotation: -6, duration: 0.22, ease: "power4.in" }}, {_t(cue(1))});\n')
    return css, body, js


# ── 2. 막대 비교 (값 표기 or 상대 높이) ─────────────────────────
def bar_compare(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    items = [i for i in (s.get("items") or []) if isinstance(i, dict)][:4]
    n = max(1, len(items))
    base, max_h = 960, 560
    vals = [_num(i.get("value")) if i.get("value") else None for i in items]
    rels = [i.get("rel") for i in items]
    nums = [v if v is not None else (float(r) if isinstance(r, (int, float)) else None) for v, r in zip(vals, rels)]
    top = max([abs(v) for v in nums if v is not None] or [1.0]) or 1.0
    width = min(260, int(800 / n) - 40)
    gap = (900 - n * width) / (n + 1)
    hi = s.get("highlight")
    css = f"""
    .{sid}-bar {{ position: absolute; width: {width}px; background: #c5ccd8; border-radius: 18px 18px 0 0; transform-origin: 50% 100%; }}
    .{sid}-bar.y {{ background: {YELLOW}; }}
    .{sid}-lab {{ position: absolute; top: {base + 18}px; width: {width + 80}px; text-align: center; font-family: "PretendardXB"; font-size: 44px; color: #4a5263; }}
    .{sid}-val {{ position: absolute; width: {width + 80}px; text-align: center; font-family: "PretendardBlack"; font-size: 64px; }}
    #{sid}-base {{ position: absolute; top: {base}px; left: 90px; right: 90px; height: 5px; background: #c5ccd8; }}
    #{sid}-badge {{ position: absolute; top: 300px; left: 0; right: 0; text-align: center; }}
    #{sid}-badge span {{ display: inline-block; font-family: "PretendardBlack"; font-size: 80px; background: {YELLOW}; color: #0a0f1c; border-radius: 24px; padding: 6px 28px; transform: rotate(-4deg); }}"""
    body = f'    <div class="h" id="{sid}-h">{esc(s.get("title"))}<small>{esc(s.get("subtitle"))}</small></div>\n'
    for k, (it, v) in enumerate(zip(items, nums)):
        h = int(max_h * (abs(v) / top)) if v is not None else int(max_h * 0.5)
        h = max(h, 24)
        x = int(90 + gap + k * (width + gap))
        is_hi = (hi == k) or (hi is None and v == top and v is not None)
        body += (f'    <div class="{sid}-bar{" y" if is_hi else ""}" id="{sid}-b{k}" style="left:{x}px;top:{base - h}px;height:{h}px"></div>\n'
                 f'    <div class="{sid}-lab" style="left:{x - 40}px">{esc(it.get("label"))}</div>\n')
        if it.get("value"):
            body += f'    <div class="{sid}-val" id="{sid}-v{k}" style="left:{x - 40}px;top:{base - h - 86}px">{esc(it.get("value"))}</div>\n'
    body += f'    <div id="{sid}-base"></div>\n'
    if s.get("badge"):
        body += f'    <div id="{sid}-badge"><span>{esc(s.get("badge"))}</span></div>\n'
    js = (f'    tl.fromTo("#{sid}-h", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, 0.05);\n'
          f'    tl.fromTo([".{sid}-lab", "#{sid}-base"], {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.2);\n'
          f'    tl.fromTo(".{sid}-bar", {{ scaleY: 0 }}, {{ scaleY: 1, duration: 0.6, ease: "power3.out", stagger: 0.25 }}, {_t(cue(0) - 0.2)});\n'
          f'    tl.fromTo(".{sid}-val", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.25, stagger: 0.25 }}, {_t(cue(0) + 0.3)});\n')
    if s.get("badge"):
        js += (f'    tl.fromTo("#{sid}-badge span", {{ opacity: 0, scale: 0.3 }}, {{ opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2.2)" }}, {_t(cue(1))});\n')
    return css, body, js


# ── 3. 좌우 VS 카드 ─────────────────────────────────────────
def vs_split(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    L, R = s.get("left") or {}, s.get("right") or {}
    css = f"""
    .{sid}-c {{ position: absolute; top: 330px; width: 440px; height: 640px; padding: 40px 24px; text-align: center; display: flex; flex-direction: column; align-items: center; }}
    #{sid}-L {{ left: 70px; border-top: 14px solid {RED}; }} #{sid}-R {{ left: 570px; border-top: 14px solid {BLUE}; }}
    .{sid}-c .n {{ font-family: "PretendardXB"; font-size: 48px; color: #4a5263; }}
    .{sid}-c .v {{ font-family: "PretendardBlack"; font-size: 96px; line-height: 1.1; margin-top: 60px; }}
    #{sid}-L .v {{ color: {RED}; }} #{sid}-R .v {{ color: #1d5fd1; }}
    .{sid}-c .d {{ font-family: "PretendardXB"; font-size: 42px; color: #4a5263; margin-top: 40px; line-height: 1.3; }}
    #{sid}-vs {{ position: absolute; left: 470px; top: 560px; width: 140px; height: 140px; border-radius: 50%; background: {YELLOW}; display: flex; align-items: center; justify-content: center; font-family: "PretendardBlack"; font-size: 64px; border: 10px solid #fff; z-index: 2; }}"""
    body = f'    <div class="h" id="{sid}-h">{esc(s.get("title"))}</div>\n'
    for side, d in (("L", L), ("R", R)):
        body += (f'    <div class="card {sid}-c" id="{sid}-{side}"><div class="n">{esc(d.get("label"))}</div>'
                 f'<div class="v">{esc(d.get("value"))}</div><div class="d">{esc(d.get("sub"))}</div></div>\n')
    body += f'    <div id="{sid}-vs">VS</div>\n'
    js = (f'    tl.fromTo("#{sid}-h", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.05);\n'
          f'    tl.fromTo("#{sid}-L", {{ opacity: 0, x: -120 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "back.out(1.6)" }}, {_t(cue(0) - 0.15)});\n'
          f'    tl.fromTo("#{sid}-vs", {{ opacity: 0, scale: 0.3 }}, {{ opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)" }}, {_t(cue(1) - 0.3)});\n'
          f'    tl.fromTo("#{sid}-R", {{ opacity: 0, x: 120 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "back.out(1.6)" }}, {_t(cue(1) - 0.15)});\n')
    return css, body, js


# ── 4. 아이콘 N개 vs M개 ─────────────────────────────────────
_PERSON = ('<svg viewBox="0 0 60 90" class="{cls}"><circle cx="30" cy="18" r="16" fill="currentColor"/>'
           '<path d="M6 88 L6 56 Q6 38 30 38 Q54 38 54 56 L54 88 Z" fill="currentColor"/></svg>')
_CAR = ('<svg viewBox="0 0 120 70" class="{cls}"><path d="M14 44 L24 24 Q28 16 38 16 L80 16 Q90 16 96 24 L106 40 Q114 42 114 50 '
        'L114 56 L6 56 L6 50 Q6 44 14 44 Z" fill="currentColor"/><circle cx="32" cy="58" r="10" fill="#141a2a"/>'
        '<circle cx="90" cy="58" r="10" fill="#141a2a"/></svg>')
_COIN = ('<svg viewBox="0 0 80 80" class="{cls}"><circle cx="40" cy="40" r="34" fill="currentColor"/>'
         '<text x="40" y="54" text-anchor="middle" font-size="40" fill="#fff" font-family="sans-serif">₩</text></svg>')
ICONS = {"person": _PERSON, "car": _CAR, "coin": _COIN}


def icon_ratio(sid: str, s: dict, cue: Cue, dur: float, max_icons: int = 10) -> tuple[str, str, str]:
    icon = ICONS.get(str(s.get("icon") or "person"), _PERSON)
    a, b = s.get("a") or {}, s.get("b") or {}
    ca = max(1, min(max_icons, int(a.get("count") or 1)))
    cb = max(1, min(max_icons, int(b.get("count") or 1)))
    size = 130 if max(ca, cb) <= 5 else 80
    css = f"""
    .{sid}-row {{ position: absolute; left: 90px; right: 90px; }}
    .{sid}-row .n {{ font-family: "PretendardBlack"; font-size: 56px; }}
    .{sid}-row .n small {{ font-family: "PretendardXB"; font-size: 38px; color: #5b6475; margin-left: 12px; }}
    .{sid}-row .ic {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 14px; align-items: flex-end; }}
    .{sid}-i {{ width: {size}px; height: {int(size * 1.5) if icon is _PERSON else int(size * 0.6)}px; }}
    .{sid}-i.a {{ color: {RED}; }} .{sid}-i.b {{ color: #4a5263; }}
    .{sid}-row .v {{ font-family: "PretendardBlack"; font-size: 58px; margin-top: 8px; }}
    #{sid}-A {{ top: 180px; }} #{sid}-B {{ top: 640px; }}
    #{sid}-x {{ position: absolute; left: 560px; top: 820px; }}
    #{sid}-x span {{ display: inline-block; font-family: "PretendardBlack"; font-size: 110px; background: {YELLOW}; color: #0a0f1c; border-radius: 28px; padding: 4px 34px; transform: rotate(-4deg); }}"""
    body = ""
    for key, d, c, cls in (("A", a, ca, "a"), ("B", b, cb, "b")):
        icons = "".join(icon.format(cls=f"{sid}-i {cls}") for _ in range(c))
        body += (f'    <div class="{sid}-row" id="{sid}-{key}"><div class="n">{esc(d.get("label"))}<small>{esc(d.get("sub"))}</small></div>'
                 f'<div class="ic">{icons}</div><div class="v">{esc(d.get("value"))}</div></div>\n')
    if s.get("badge"):
        body += f'    <div id="{sid}-x"><span>{esc(s.get("badge"))}</span></div>\n'
    js = (f'    tl.fromTo("#{sid}-A .n", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.05);\n'
          f'    tl.fromTo("#{sid}-A .{sid}-i", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.22, stagger: 0.08, ease: "back.out(2)" }}, {_t(cue(0) - 0.3)});\n'
          f'    tl.fromTo("#{sid}-A .v", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, {_t(cue(0))});\n'
          f'    tl.fromTo(["#{sid}-B .n", "#{sid}-B .{sid}-i", "#{sid}-B .v"], {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.3, stagger: 0.12 }}, {_t(cue(1) - 0.2)});\n')
    if s.get("badge"):
        js += f'    tl.fromTo("#{sid}-x span", {{ opacity: 0, scale: 2.4 }}, {{ opacity: 1, scale: 1, duration: 0.22, ease: "power4.in" }}, {_t(cue(2))});\n'
    return css, body, js


# ── 5. 체크 카드 2~4장 ───────────────────────────────────────
def card_stack(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    items = [str(x) for x in (s.get("items") or []) if str(x).strip()][:4]
    css = f"""
    .{sid}-b {{ position: absolute; left: 150px; width: 780px; height: 160px; display: flex; align-items: center; gap: 30px; padding: 0 44px; }}
    .{sid}-b .i {{ width: 96px; height: 96px; flex: none; border-radius: 50%; background: #e6f0ff; color: {BLUE}; font-family: "PretendardBlack"; font-size: 60px; display: flex; align-items: center; justify-content: center; }}
    .{sid}-b .t {{ font-family: "PretendardBlack"; font-size: 66px; line-height: 1.1; }}
    #{sid}-b0 .t {{ color: {AMBER}; }}
    #{sid}-note {{ top: 1010px; }}
    #{sid}-note span {{ background: #141a2a; color: #fff; font-size: 42px; }}"""
    body = f'    <div class="h" id="{sid}-h" style="font-size:56px;color:#4a5263">{esc(s.get("title"))}</div>\n'
    for k, t in enumerate(items):
        body += f'    <div class="card {sid}-b" id="{sid}-b{k}" style="top:{320 + k * 185}px"><div class="i">✓</div><div class="t">{esc(t)}</div></div>\n'
    if s.get("note"):
        body += f'    <div class="chip" id="{sid}-note"><span>{esc(s.get("note"))}</span></div>\n'
    js = f'    tl.fromTo("#{sid}-h", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, 0.05);\n'
    for k in range(len(items)):
        js += f'    tl.fromTo("#{sid}-b{k}", {{ opacity: 0, x: -200 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "back.out(1.6)" }}, {_t(cue(k) - 0.15)});\n'
    if s.get("note"):
        js += f'    tl.fromTo("#{sid}-note span", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, {_t(cue(len(items)))});\n'
    return css, body, js


# ── 6. 줄 그은 오해 → 실제 ─────────────────────────────────────
def strike_vs_fact(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    css = f"""
    #{sid}-chip {{ top: 190px; }}
    .{sid}-c {{ position: absolute; left: 130px; right: 130px; padding: 40px; text-align: center; }}
    .{sid}-c .k {{ font-family: "PretendardXB"; font-size: 44px; color: #5b6475; }}
    .{sid}-c .v {{ font-family: "PretendardBlack"; font-size: 80px; line-height: 1.2; margin-top: 8px; position: relative; display: inline-block; }}
    #{sid}-no {{ top: 320px; }} #{sid}-no .v {{ color: #9aa0ad; }}
    #{sid}-line {{ position: absolute; left: -10px; right: -10px; top: 50%; height: 12px; background: {RED}; border-radius: 6px; transform-origin: 0 50%; }}
    #{sid}-yes {{ top: 650px; border: 6px solid {YELLOW}; }}"""
    body = (f'    <div class="chip" id="{sid}-chip"><span>{esc(s.get("chip"))}</span></div>\n'
            f'    <div class="card {sid}-c" id="{sid}-no"><div class="k">{esc(s.get("wrong_label") or "아니다")}</div>'
            f'<div class="v">{esc(s.get("wrong"))}<i id="{sid}-line"></i></div></div>\n'
            f'    <div class="card {sid}-c" id="{sid}-yes"><div class="k">{esc(s.get("right_label") or "이것이다")}</div>'
            f'<div class="v">{esc(s.get("right"))}</div></div>\n')
    js = (f'    tl.fromTo("#{sid}-chip span", {{ opacity: 0, scale: 0.6 }}, {{ opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)" }}, 0.1);\n'
          f'    tl.fromTo("#{sid}-no", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, {_t(cue(0) - 0.2)});\n'
          f'    tl.fromTo("#{sid}-line", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.3, ease: "power2.out" }}, {_t(cue(0) + 0.6)});\n'
          f'    tl.fromTo("#{sid}-yes", {{ opacity: 0, scale: 0.7 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)" }}, {_t(cue(1))});\n')
    return css, body, js


# ── 7. A → B → C 사슬 (세로로 쌓는다 — 가로 4칸은 글자가 너무 작아졌다, 실렌더 2026-11-24) ──
def flow_chain(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    steps = [str(x) for x in (s.get("steps") or []) if str(x).strip()][:4]
    n = max(1, len(steps))
    box_h, arrow_h = (130, 60) if n >= 4 else (150, 70)
    css = f"""
    .{sid}-l {{ position: absolute; left: 170px; width: 740px; height: {box_h}px; display: flex; align-items: center; justify-content: center; text-align: center; font-family: "PretendardBlack"; font-size: 60px; border: 6px solid {BLUE}; }}
    .{sid}-ar {{ position: absolute; left: 0; right: 0; text-align: center; font-family: "PretendardBlack"; font-size: 56px; line-height: {arrow_h}px; color: {BLUE}; }}
    .{sid}-l.last {{ border-color: {RED}; color: {RED}; }}
    #{sid}-tag {{ top: {300 + n * box_h + (n - 1) * arrow_h + 40}px; }}"""
    NL = "\n"
    body = f'    <div class="h" id="{sid}-h">{esc(s.get("title"))}</div>{NL}'
    y = 300
    for k, t in enumerate(steps):
        if k:
            body += f'    <div class="{sid}-ar" id="{sid}-ar{k}" style="top:{y}px">↓</div>{NL}'
            y += arrow_h
        last = " last" if k == n - 1 and n > 1 else ""
        body += f'    <div class="card {sid}-l{last}" id="{sid}-l{k}" style="top:{y}px">{esc(t)}</div>{NL}'
        y += box_h
    if s.get("tag"):
        body += f'    <div class="chip" id="{sid}-tag"><span>{esc(s.get("tag"))}</span></div>{NL}'
    js = f'    tl.fromTo("#{sid}-h", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.05);{NL}'
    # 칸은 첫 큐부터 태그 큐 사이에 고르게 하나씩 — 태그가 없으면 0.45초 간격
    step_gap = max(0.35, (cue(1) - cue(0)) / max(n, 1)) if s.get("tag") else 0.45
    for k in range(n):
        t = cue(0) - 0.2 + k * step_gap
        if k:
            js += f'    tl.fromTo("#{sid}-ar{k}", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.2 }}, {_t(t - 0.15)});{NL}'
        js += f'    tl.fromTo("#{sid}-l{k}", {{ opacity: 0, scale: 0.7 }}, {{ opacity: 1, scale: 1, duration: 0.3, ease: "back.out(1.8)" }}, {_t(t)});{NL}'
    if s.get("tag"):
        js += f'    tl.fromTo("#{sid}-tag span", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "back.out(2)" }}, {_t(cue(1))});{NL}'
    return css, body, js


# ── 8. 3단 순환(악순환) ──────────────────────────────────────
def cycle3(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    nodes = ([str(x) for x in (s.get("nodes") or [])] + ["", "", ""])[:3]
    chips = [str(x) for x in (s.get("chips") or []) if str(x).strip()][:4]
    css = f"""
    #{sid}-ring {{ position: absolute; top: 200px; left: 140px; width: 800px; height: 760px; }}
    .{sid}-n {{ position: absolute; width: 330px; height: 150px; display: flex; align-items: center; justify-content: center; text-align: center; font-family: "PretendardBlack"; font-size: 54px; line-height: 1.1; }}
    #{sid}-n0 {{ left: 235px; top: 0; }} #{sid}-n1 {{ left: 470px; top: 470px; }} #{sid}-n2 {{ left: 0; top: 470px; }}
    #{sid}-mid {{ position: absolute; left: 220px; top: 290px; width: 360px; text-align: center; font-family: "PretendardBlack"; font-size: 74px; color: {RED}; line-height: 1.05; }}
    #{sid}-mid small {{ display: block; font-family: "PretendardXB"; font-size: 38px; color: #5b6475; margin-top: 8px; }}
    #{sid}-fin {{ position: absolute; top: 1000px; left: 0; right: 0; display: flex; justify-content: center; gap: 14px; flex-wrap: wrap; }}
    #{sid}-fin .f {{ font-family: "PretendardXB"; font-size: 40px; padding: 12px 24px; border-radius: 999px; background: #141a2a; color: #fff; }}"""
    ah = (f'<marker id="{sid}-ah" markerUnits="userSpaceOnUse" markerWidth="44" markerHeight="44" refX="22" refY="22" orient="auto">'
          f'<path d="M0 0 L44 22 L0 44 Z" fill="{RED}"/></marker>')
    paths = ["M590 130 Q710 260 650 420", "M455 610 Q400 680 345 615", "M150 445 Q80 280 205 120"]
    svg = "".join(f'<path id="{sid}-a{k}" d="{p}" fill="none" stroke="{RED}" stroke-width="14" stroke-linecap="round" marker-end="url(#{sid}-ah)"/>'
                  for k, p in enumerate(paths))
    body = (f'    <div id="{sid}-ring"><svg viewBox="0 0 800 760" style="position:absolute;inset:0" data-layout-ignore><defs>{ah}</defs>{svg}</svg>\n'
            + "".join(f'      <div class="card {sid}-n" id="{sid}-n{k}">{esc(t)}</div>\n' for k, t in enumerate(nodes))
            + f'      <div id="{sid}-mid">{esc(s.get("center"))}<small>{esc(s.get("center_sub"))}</small></div>\n    </div>\n')
    if chips:
        body += f'    <div id="{sid}-fin">{"".join(f"<span class=f>{esc(c)}</span>" for c in chips)}</div>\n'
    js = ""
    for k in range(3):
        js += f'    tl.fromTo("#{sid}-n{k}", {{ opacity: 0, scale: 0.5 }}, {{ opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)" }}, {_t(cue(k) - 0.1)});\n'
        js += f'    tl.fromTo("#{sid}-a{k}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.2 }}, {_t(cue(k) + 0.3)});\n'
    js += (f'    tl.fromTo("#{sid}-mid", {{ opacity: 0, scale: 1.8 }}, {{ opacity: 1, scale: 1, duration: 0.25, ease: "power4.in" }}, {_t(cue(3))});\n'
           f'    tl.to("#{sid}-mid", {{ scale: 1.08, duration: 0.4, yoyo: true, repeat: 3, ease: "sine.inOut" }}, {_t(cue(3) + 0.3)});\n')
    if chips:
        js += f'    tl.fromTo("#{sid}-fin .f", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.25, stagger: 0.25, ease: "back.out(2)" }}, {_t(cue(4) - 0.1)});\n'
    return css, body, js


# ── 9. 저울 ─────────────────────────────────────────────────
def scale_tilt(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    css = f"""
    #{sid}-chip {{ top: 190px; }}
    #{sid}-sc {{ position: absolute; top: 330px; left: 90px; width: 900px; height: 700px; }}
    .{sid}-pan {{ position: absolute; width: 360px; height: 180px; display: flex; align-items: center; justify-content: center; text-align: center; font-family: "PretendardBlack"; font-size: 56px; line-height: 1.12; }}
    #{sid}-l {{ left: 0; top: 330px; color: #5b6475; }}
    #{sid}-r {{ left: 540px; top: 330px; color: #a87300; border: 6px solid {YELLOW}; }}"""
    body = (f'    <div class="chip" id="{sid}-chip"><span>{esc(s.get("chip"))}</span></div>\n'
            f'    <div id="{sid}-sc"><svg viewBox="0 0 900 700" style="position:absolute;inset:0" data-layout-ignore>'
            f'<path d="M450 250 L450 640 M330 640 L570 640" stroke="#c5ccd8" stroke-width="22" stroke-linecap="round"/>'
            f'<g id="{sid}-beam"><path d="M180 250 L720 250" stroke="#141a2a" stroke-width="18" stroke-linecap="round"/>'
            f'<circle cx="450" cy="250" r="26" fill="{YELLOW}"/></g></svg>\n'
            f'      <div class="card {sid}-pan" id="{sid}-l">{esc(s.get("left"))}</div>\n'
            f'      <div class="card {sid}-pan" id="{sid}-r">{esc(s.get("right"))}</div>\n    </div>\n')
    js = (f'    tl.fromTo("#{sid}-chip span", {{ opacity: 0, scale: 0.6 }}, {{ opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)" }}, 0.1);\n'
          f'    tl.set("#{sid}-beam", {{ svgOrigin: "450 250", rotation: -12 }}, 0);\n'
          f'    tl.set("#{sid}-l", {{ y: 70 }}, 0); tl.set("#{sid}-r", {{ y: -70 }}, 0);\n'
          f'    tl.fromTo(["#{sid}-l", "#{sid}-r"], {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.2);\n'
          f'    tl.to("#{sid}-beam", {{ rotation: 12, duration: 0.9, ease: "back.out(1.4)" }}, {_t(cue(0))});\n'
          f'    tl.to("#{sid}-l", {{ y: -70, duration: 0.9, ease: "back.out(1.4)" }}, {_t(cue(0))});\n'
          f'    tl.to("#{sid}-r", {{ y: 70, scale: 1.06, duration: 0.9, ease: "back.out(1.4)" }}, {_t(cue(0))});\n')
    return css, body, js


# ── 10. 도장 + 정보 카드 ─────────────────────────────────────
def stamp_card(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    css = f"""
    #{sid}-q {{ position: absolute; top: 210px; left: 40px; right: 40px; text-align: center; font-family: "PretendardBlack"; font-size: 76px; line-height: 1.15; }}
    #{sid}-st {{ position: absolute; top: 400px; left: 0; right: 0; text-align: center; }}
    #{sid}-st .box {{ display: inline-block; border: 10px solid {RED}; border-radius: 26px; padding: 18px 50px; color: {RED}; background: rgba(255,255,255,0.94); }}
    #{sid}-st .k {{ display: block; font-family: "PretendardBlack"; font-size: 120px; line-height: 1; }}
    #{sid}-st .t {{ display: block; font-family: "PretendardXB"; font-size: 44px; margin-top: 8px; }}
    #{sid}-cd {{ position: absolute; top: 740px; left: 110px; right: 110px; padding: 40px; text-align: center; }}
    #{sid}-cd .a {{ font-family: "PretendardXB"; font-size: 44px; color: #5b6475; }}
    #{sid}-cd .b {{ font-family: "PretendardBlack"; font-size: 60px; line-height: 1.25; margin-top: 10px; }}"""
    body = ""
    if s.get("headline"):
        body += f'    <div id="{sid}-q">{esc(s.get("headline"))}</div>\n'
    body += (f'    <div id="{sid}-st"><div class="box" id="{sid}-box"><span class="k">{esc(s.get("stamp"))}</span>'
             f'<span class="t">{esc(s.get("stamp_sub"))}</span></div></div>\n')
    if s.get("card_body"):
        body += (f'    <div class="card" id="{sid}-cd"><div class="a">{esc(s.get("card_title"))}</div>'
                 f'<div class="b">{esc(s.get("card_body"))}</div></div>\n')
    js = ""
    if s.get("headline"):
        js += f'    tl.fromTo("#{sid}-q", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.3 }}, 0.1);\n'
    js += f'    tl.fromTo("#{sid}-box", {{ opacity: 0, scale: 2.4, rotation: -14 }}, {{ opacity: 1, scale: 1, rotation: -6, duration: 0.22, ease: "power4.in" }}, {_t(cue(0) - 0.2)});\n'
    if s.get("card_body"):
        js += f'    tl.fromTo("#{sid}-cd", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "back.out(1.6)" }}, {_t(cue(1))});\n'
    return css, body, js


# ── 11. 설명 카드(폴백 — 숫자 검문 실패·모르는 템플릿) ─────────────
def text_card(sid: str, s: dict, cue: Cue, dur: float) -> tuple[str, str, str]:
    css = f"""
    #{sid}-cd {{ position: absolute; top: 330px; left: 90px; right: 90px; padding: 60px 50px; text-align: center; border-top: 14px solid {YELLOW}; }}
    #{sid}-cd .a {{ font-family: "PretendardXB"; font-size: 46px; color: #5b6475; }}
    #{sid}-cd .b {{ font-family: "PretendardBlack"; font-size: 68px; line-height: 1.3; margin-top: 20px; }}"""
    body = (f'    <div class="card" id="{sid}-cd"><div class="a">{esc(s.get("title"))}</div>'
            f'<div class="b">{esc(s.get("body"))}</div></div>\n')
    js = f'    tl.fromTo("#{sid}-cd", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "back.out(1.6)" }}, {_t(cue(0) - 0.2)});\n'
    return css, body, js


TEMPLATES: dict[str, Callable[..., tuple[str, str, str]]] = {
    "hook_number": hook_number, "bar_compare": bar_compare, "vs_split": vs_split,
    "icon_ratio": icon_ratio, "card_stack": card_stack, "strike_vs_fact": strike_vs_fact,
    "flow_chain": flow_chain, "cycle3": cycle3, "scale_tilt": scale_tilt,
    "stamp_card": stamp_card, "text_card": text_card,
}


def render_scene(sid: str, template: str, slots: dict, cue: Cue, dur: float, src: str) -> str:
    fn = TEMPLATES.get(template, text_card)
    css, body, js = fn(sid, slots or {}, cue, dur)
    return page(sid, css, body, js, src)


def end_card(sid: str, meta: dict) -> str:
    """출처 끝 카드 — 운영자 메타로 채우며, 생략하면 기존 리포트 문구를 쓴다."""
    lines = [esc(x) for x in (meta.get("date"), meta.get("broker"), meta.get("analyst")) if x]
    css = f"""
    #{sid}-card {{ position: absolute; top: 300px; left: 80px; right: 80px; padding: 50px 44px; text-align: center; }}
    #{sid}-card .h2 {{ font-family: "PretendardXB"; font-size: 40px; color: #5b6475; }}
    #{sid}-card .t {{ font-family: "PretendardBlack"; font-size: 54px; line-height: 1.3; margin-top: 14px; }}
    #{sid}-card .m {{ font-family: "PretendardB"; font-size: 40px; line-height: 1.45; color: #4a5263; margin-top: 22px; }}
    #{sid}-card .go {{ font-family: "PretendardXB"; font-size: 44px; margin-top: 34px; padding-top: 30px; border-top: 3px solid #c5ccd8; }}
    #{sid}-card .b {{ display: inline-block; margin-top: 30px; font-family: "PretendardBlack"; font-size: 58px; padding: 12px 40px; border-radius: 999px; background: {YELLOW}; color: #0a0f1c; }}"""
    body = (f'    <div class="card" id="{sid}-card"><div class="h2">출처 · {esc(meta.get("source_label") or "증권사 리포트")}</div>'
            f'<div class="t">{esc(meta.get("title"))}</div><div class="m">{"<br>".join(lines)}</div>'
            f'<div class="go" id="{sid}-go">{esc(meta.get("end_note") or "자세한 내용은 리포트 원문을 확인하세요")}</div>'
            f'<div class="b">{esc(meta.get("end_badge") or "투자 권유 아님")}</div></div>\n')
    js = (f'    tl.fromTo("#{sid}-card", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "power3.out" }}, 0.05);\n'
          f'    tl.fromTo("#{sid}-go", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 0.6);\n')
    return page(sid, css, body, js, "")
