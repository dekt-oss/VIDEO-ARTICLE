"""째리의 술 해부 · 막걸리(2판: 2.5D 단면) — 세계 4개(항아리·체·잔·퀴즈) 안에서 카메라가 움직이는 모션그래픽.
다시: python tools/tts.py (대본 바꿀 때) → python tools/build.py → npx hyperframes@0.9.72 check --safe-zone reels
그림 좌표는 화면 좌표(1080×1920) 그대로. 카메라는 각 세계의 #<id>-cam 묶음에 x·y·scale 로 건다(기준점 0,0)."""
import json, random, re, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
comp = root / 'compositions'
sys.path.insert(0, str(Path(__file__).parent))
from script import BEATS

NAVY, INK, CREAM, TOMATO, YEL = '#1F2A44', '#0E1525', '#FFF8EE', '#C2410C', '#FDE68A'
GLAZE_D, GLAZE_M, GLAZE_L = '#2E1B10', '#5B3A23', '#8A5A35'
MASH, MILK, CLEAR_TOP, WATER = '#E9DFC8', '#F4EFE4', '#E8C873', '#8EC5E8'
FONTS = """@font-face { font-family: 'Wanted Sans'; src: url('assets/fonts/WantedSans-ExtraBold.otf'); font-weight: 800; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-Bold.woff2'); font-weight: 700; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-SemiBold.woff2'); font-weight: 600; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-ExtraBold.woff2'); font-weight: 800; }"""

# ---------- 시간표: 내레이션이 시계 ----------
VO = json.loads((root / 'assets' / 'vo' / 'vo.json').read_text(encoding='utf-8'))
GAP, LEAD, TAIL = 0.27, {'jar': 0.2}, {'quiz': 2.2}
MIN = {'sieve': 5.2}
EXTRA = {('jar', 2): 0.6}          # 발효 장면은 빨리 감기를 볼 시간을 조금 더 준다
ORDER = ['jar', 'sieve', 'glass', 'quiz']
BT, CAP, SCN = {}, {}, {}
for w in ORDER:
    t = LEAD.get(w, 0.15); BT[w] = []; CAP[w] = []; i = 0
    for v, (bw, text) in zip(VO, BEATS):
        if bw != w:
            continue
        slot = round(v['end'] - v['head'] + GAP + EXTRA.get((w, i), 0), 3)
        BT[w].append(round(t, 3)); CAP[w].append([text, round(t, 3), None, v]); t += slot; i += 1
    for a, b in zip(CAP[w], CAP[w][1:]):
        a[2] = b[1]
    SCN[w] = round(max(MIN.get(w, 0), t + TAIL.get(w, 0.1)), 2)
STARTS, _t = {}, 0.0
for w in ORDER:
    STARTS[w] = round(_t, 2); _t += SCN[w]
TOTAL = round(_t, 2)

KW = [('막걸리', '#C2410C'), ('청주', '#B45309'), ('누룩', '#8A5A35'), ('탄산', '#2563EB')]


def color_kw(text):
    for w, c in KW:
        text = re.sub(w, f'<b style="color:{c}">{w}</b>', text)
    return text.replace('\n', '<br>')


def caps(w):
    return '<div class="capbox">' + ''.join(f'<div id="{w}-cap{k}" class="captext"><span>{color_kw(c[0])}</span></div>' for k, c in enumerate(CAP[w])) + '</div>'


def caps_js(w):
    js = []
    for k, (t, a, b, v) in enumerate(CAP[w]):
        e = f'#{w}-cap{k}'
        js.append(f'tl.set("{e}", {{ opacity: 1 }}, 0);' if (w == 'jar' and k == 0) else
                  f'tl.fromTo("{e}", {{ opacity: 0, scale: 0.96, filter: "blur(8px)" }}, {{ opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }}, {a});')
        if b is not None:
            js.append(f'tl.to("{e}", {{ opacity: 0, filter: "blur(6px)", duration: 0.12, ease: "power2.in" }}, {round(b - 0.12, 3)});')
    return '\n    '.join(js)


def cam(sel, t, s, fx, fy, dur=0.9, cx=540, cy=730, ease='power2.inOut'):
    """초점 (fx,fy) 를 화면 (cx,cy) 에 배율 s 로 — 카메라 묶음의 x·y·scale(기준점 0,0)."""
    return f'tl.to("{sel}", {{ x: {round(cx - s * fx, 1)}, y: {round(cy - s * fy, 1)}, scale: {s}, duration: {dur}, ease: "{ease}" }}, {t});'


def pop(sel, t, rot=0):
    return (f'tl.fromTo("{sel}", {{ scale: 0.5, opacity: 0, rotation: {rot - 6} }}, '
            f'{{ scale: 1, opacity: 1, rotation: {rot}, duration: 0.38, ease: "back.out(1.7)", transformOrigin: "50% 50%" }}, {t});')


def fade(sel, t, to=1, dur=0.3):
    return f'tl.to("{sel}", {{ opacity: {to}, duration: {dur}, ease: "power2.out" }}, {t});'


def label(i, text, x, y, lx, ly, anchor='start'):
    """그림 안 이름표 + 가리키는 선(x,y 글자 기준점 → lx,ly 부품)."""
    w = 28 * len(text) + 36
    bx = x if anchor == 'start' else x - w
    return (f'<g id="{i}" opacity="0"><path d="M{lx} {ly} L{x if anchor == "start" else x} {y}" stroke="{CREAM}" stroke-width="4"/>'
            f'<circle cx="{lx}" cy="{ly}" r="8" fill="{CREAM}"/>'
            f'<rect x="{bx}" y="{y - 30}" width="{w}" height="56" rx="12" fill="{CREAM}" stroke="{INK}" stroke-width="3"/>'
            f'<text x="{bx + w / 2}" y="{y + 10}" text-anchor="middle" font-family="Pretendard" font-weight="700" font-size="32" fill="{NAVY}">{text}</text></g>')


def boom(i, text, x, y, size=64, color=YEL):
    """의성어 글자(효과음과 같은 순간)."""
    return (f'<div class="boombox" style="left:{x - 300}px; top:{y - 60}px;"><span id="{i}" class="boom" style="font-size:{size}px; color:{color};">{text}</span></div>')


CSS = f"""
    {FONTS}
    #root {{ position: absolute; inset: 0; overflow: hidden; font-family: 'Pretendard'; color: {NAVY}; }}
    .world {{ position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; overflow: visible; clip-path: inset(424px 0 884px 0 round 0); }}
    .capbox {{ position: absolute; left: 296px; width: 720px; top: 1052px; height: 176px; }}
    .captext {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center; font-weight: 800; font-size: 42px; line-height: 1.42; letter-spacing: -0.02em; color: {NAVY}; opacity: 0; }}
    .captext b {{ font-weight: 800; }}
    .boombox {{ position: absolute; width: 600px; height: 120px; display: flex; align-items: center; justify-content: center; }}
    .boom {{ display: inline-block; font-family: 'Wanted Sans'; font-weight: 800; letter-spacing: -0.03em; -webkit-text-stroke: 6px {INK}; paint-order: stroke fill; opacity: 0; }}
    .hud {{ position: absolute; left: 84px; top: 446px; }}
    .hud span {{ position: absolute; left: 0; top: 0; white-space: nowrap; font-weight: 800; font-size: 34px; color: #fff; background: {INK}; border: 3px solid {YEL}; border-radius: 12px; padding: 4px 16px; opacity: 0; }}
    .chiprow {{ position: absolute; left: 84px; width: 912px; top: 950px; display: flex; justify-content: center; gap: 12px; }}
    .chip {{ display: inline-flex; align-items: center; gap: 8px; font-weight: 700; font-size: 32px; padding: 6px 16px; border-radius: 14px; border: 3px solid {INK}; background: {CREAM}; color: {NAVY}; white-space: nowrap; opacity: 0; }}
    .arrow {{ font-weight: 800; font-size: 34px; color: {CREAM}; opacity: 0; }}
"""


def scene(w, body, js, extra_css=''):
    return f"""<template>
  <style>{CSS}{extra_css}
  </style>
  <div id="root" data-composition-id="{w}" data-width="1080" data-height="1920">
    {body}
    {caps(w)}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {js}
    {caps_js(w)}
    window.__timelines["{w}"] = tl;
  </script>
</template>
"""


# ---------- 공용 그림: 2.5D 부품은 tools/art25.py ----------
import math
import art25 as A


def icon(kind):
    """범례 칩 안 작은 그림(28px)."""
    s = {'grain': '<ellipse cx="14" cy="14" rx="12" ry="7" fill="#FFFDF5" stroke="#8A7F68" stroke-width="2"/>',
         'sugar': '<path d="M14 2 L25 14 L14 26 L3 14 Z" fill="#F5C542" stroke="#8A6A12" stroke-width="2"/>',
         'drop': '<path d="M14 2 C22 12 23 20 14 26 C5 20 6 12 14 2 Z" fill="#9FD3F2" stroke="#2F6F9A" stroke-width="2"/>',
         'bubble': '<circle cx="14" cy="14" r="10" fill="none" stroke="#2563EB" stroke-width="3"/>'}[kind]
    return f'<svg width="28" height="28" viewBox="0 0 28 28">{s}</svg>'


rng = random.Random(11)
LIQ, BOUND = 740, 815                      # 술 표면 · 맑은 윗술/술밑 경계
GRAINS = []
while len(GRAINS) < 22:
    y = rng.randint(835, 942)
    x = rng.randint(int(540 - A.jar_w(y) + 40), int(540 + A.jar_w(y) - 40))
    if not (575 < x < 690 and y > 880):     # 누룩 자리 비움
        GRAINS.append((x, y))
out = {}

# ===================== 세계 1: 항아리 (문장 0~4) =====================
b = BT['jar']; D = SCN['jar']
tokens = (''.join(A.grain(f'jar-g{k}', x, y, 'jar', True) for k, (x, y) in enumerate(GRAINS))
          + ''.join(A.sugar(f'jar-s{k}', x, y) for k, (x, y) in enumerate(GRAINS))
          + ''.join(A.drop(f'jar-d{k}', x, y) for k, (x, y) in enumerate(GRAINS))
          + A.nuruk('jar-nuruk', 632, 905))
bubbles = ''.join(A.bubble(f'jar-b{k}', 380 + (k * 53) % 320, 935 - (k * 37) % 80, 7 + k % 3 * 3) for k in range(14))
contents = (A.layer('jar-water', LIQ, 962, 'url(#jar-water)', surf='#BFE3F7', hidden=True)
            + A.layer('jar-mash', LIQ, 962, 'url(#jar-mash)', surf='#F4EDDD', hidden=True)
            + A.layer('jar-top', LIQ, BOUND, 'url(#jar-clear)', surf='#F6E2A0', hidden=True)
            + A.layer('jar-lees', BOUND, 962, '#EDE4D0', surf='#F3ECDD', hidden=True)
            + f'<g id="jar-tokens">{tokens}</g>{bubbles}')
jar_world = f'''<svg class="world" viewBox="0 0 1080 1920" xmlns="http://www.w3.org/2000/svg">{A.defs('jar')}
  <g id="jar-cam">
    {A.plate('jar')}
    {A.jar_cutaway('jar', contents, 'jar-cut')}
    {A.jar_closed('jar', 'jar-shell')}
    {A.lid('jar-lid')}
    {A.ladle('jar-ladle', 'jar')}
    <path id="jar-pour" d="M560 250 C566 400 560 560 556 {LIQ}" stroke="#A9D6F0" stroke-width="20" stroke-linecap="round" fill="none" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1"/>
    {label('jar-l1', '전분 든 곡물', 100, 640, 430, 880)}
    {label('jar-l2', '누룩(곰팡이)', 985, 640, 640, 900, 'end')}
    {label('jar-l3', '물', 985, 560, 700, 742, 'end')}
    {label('jar-l4', '맑은 윗술', 100, 640, 420, 778)}
    {label('jar-l5', '술밑', 100, 880, 420, 890)}
    {A.cup('jar-cup', 'jar', 190, 905)}
    {label('jar-l6', '청주 = 윗술만', 84, 1008, 190, 930)}
    <g id="jar-brace" opacity="0"><path d="M830 {LIQ} L872 {LIQ} L872 962 L830 962" fill="none" stroke="{TOMATO}" stroke-width="9" stroke-linejoin="round"/></g>
    {label('jar-l7', '막걸리 = 통째로', 996, 1008, 872, 850, 'end')}
  </g>
</svg>'''
ff = ['▶ 실제 시간', '⏩ 빨리 감기 ×10', '⏩ 빨리 감기 ×1,000', '⏩ 빨리 감기 ×20,000', '⏸ 다 익음']
hud = '<div class="hud">' + ''.join(f'<span id="jar-h{k}">{t}</span>' for k, t in enumerate(ff)) + '</div>'
gauge = f'''<svg id="jar-gauge" style="position:absolute; left:860px; top:430px; width:136px; height:160px; opacity:0" viewBox="0 0 136 160">
  <circle cx="68" cy="62" r="56" fill="#2E3D62"/><circle cx="68" cy="62" r="50" fill="{INK}" stroke="{CREAM}" stroke-width="4"/>
  <circle id="jar-gbar" cx="68" cy="62" r="38" fill="none" stroke="{YEL}" stroke-width="12" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1" transform="rotate(-90 68 62)"/>
  <rect x="30" y="118" width="76" height="38" rx="10" fill="{INK}"/><text x="68" y="146" text-anchor="middle" font-family="Pretendard" font-weight="800" font-size="30" fill="{CREAM}">발효</text></svg>'''
legend = ('<div class="chiprow">'
          f'<span id="jar-c0" class="chip">{icon("grain")}전분</span><span id="jar-a0" class="arrow">→</span>'
          f'<span id="jar-c1" class="chip">{icon("sugar")}단맛</span><span id="jar-a1" class="arrow">→</span>'
          f'<span id="jar-c2" class="chip">{icon("drop")}술</span><span id="jar-a2" class="arrow">+</span>'
          f'<span id="jar-c3" class="chip">{icon("bubble")}탄산</span></div>')
G = range(len(GRAINS))
js = ['tl.set("#jar-cam", { x: 0, y: 0, scale: 1, svgOrigin: "0 0" }, 0);',
      # 0 훅: 뚜껑이 들리고, 앞 절반이 떨어져 단면이 드러난다
      'tl.to("#jar-lid", { y: -260, x: 160, rotation: 18, opacity: 0, duration: 0.7, ease: "power3.in", transformOrigin: "50% 50%" }, 1.1);',
      'tl.to("#jar-shell", { x: -70, opacity: 0, duration: 0.6, ease: "power2.in" }, 1.6);',
      # 1 재료
      *[f'tl.fromTo("#jar-g{k}", {{ opacity: 0, y: -420 }}, {{ opacity: 1, y: 0, duration: 0.55, ease: "power2.in" }}, {round(b[1] + 0.1 + k * 0.04, 2)});' for k in G],
      f'tl.to("#jar-l1", {{ opacity: 1, duration: 0.25 }}, {b[1] + 0.6});',
      f'tl.fromTo("#jar-nuruk", {{ opacity: 0, y: -380 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.in" }}, {b[1] + 1.4});',
      f'tl.to("#jar-l2", {{ opacity: 1, duration: 0.25 }}, {b[1] + 1.9});',
      f'tl.fromTo("#jar-pour", {{ attr: {{ "stroke-dashoffset": 1.1 }} }}, {{ attr: {{ "stroke-dashoffset": 0 }}, duration: 0.4, ease: "power2.in" }}, {b[1] + 2.6});',
      f'tl.fromTo("#jar-water", {{ opacity: 0, y: 200 }}, {{ opacity: 1, y: 0, duration: 1.2, ease: "power1.out" }}, {b[1] + 2.9});',
      f'tl.to("#jar-pour", {{ opacity: 0, duration: 0.3 }}, {b[1] + 4.0});',
      f'tl.to("#jar-l3", {{ opacity: 1, duration: 0.25 }}, {b[1] + 3.0});',
      f'tl.to(["#jar-l1", "#jar-l2", "#jar-l3"], {{ opacity: 0, duration: 0.2 }}, {b[2] - 0.1});',
      # 2 발효: 시간 조절 HUD + 카메라 다이브 + 토큰 변신
      f'tl.set("#jar-h0", {{ opacity: 1 }}, {b[2]});', f'tl.to("#jar-gauge", {{ opacity: 1, duration: 0.25 }}, {b[2]});',
      *[f'tl.set("#jar-h{k}", {{ opacity: 0 }}, {round(b[2] + 0.35 * k + 0.35, 2)}); tl.set("#jar-h{k + 1}", {{ opacity: 1 }}, {round(b[2] + 0.35 * k + 0.35, 2)});' for k in range(3)],
      f'tl.fromTo("#jar-gbar", {{ attr: {{ "stroke-dashoffset": 1.1 }} }}, {{ attr: {{ "stroke-dashoffset": 0 }}, duration: {round(b[3] - b[2] - 0.4, 2)}, ease: "none" }}, {b[2] + 0.3});',
      f'tl.to("#jar-mash", {{ opacity: 1, duration: 1.0 }}, {b[2] + 0.4}); tl.to("#jar-water", {{ opacity: 0, duration: 1.0 }}, {b[2] + 0.6});',
      cam('#jar-cam', b[2] + 0.4, 2.2, 540, 880, 1.0),
      *[f'tl.to("#jar-g{k}", {{ opacity: 0, duration: 0.25 }}, {round(b[2] + 1.5 + (k % 6) * 0.06, 2)}); tl.to("#jar-s{k}", {{ opacity: 1, duration: 0.25 }}, {round(b[2] + 1.5 + (k % 6) * 0.06, 2)});' for k in G],
      *[f'tl.to("#jar-s{k}", {{ opacity: 0, duration: 0.25 }}, {round(b[2] + 2.7 + (k % 6) * 0.06, 2)}); tl.to("#jar-d{k}", {{ opacity: 1, duration: 0.25 }}, {round(b[2] + 2.7 + (k % 6) * 0.06, 2)});' for k in G],
      *[f'tl.fromTo("#jar-b{k}", {{ opacity: 0, y: 0 }}, {{ opacity: 0.9, y: -150, duration: 1.1, ease: "power1.in" }}, {round(b[2] + 2.8 + (k % 7) * 0.18, 2)}); tl.to("#jar-b{k}", {{ opacity: 0, duration: 0.2 }}, {round(b[2] + 3.9 + (k % 7) * 0.18, 2)});' for k in range(14)],
      pop('#jar-c0', b[2] + 1.0), f'tl.to("#jar-a0", {{ opacity: 1, duration: 0.2 }}, {b[2] + 1.4});', pop('#jar-c1', b[2] + 1.5),
      f'tl.to("#jar-a1", {{ opacity: 1, duration: 0.2 }}, {b[2] + 2.6});', pop('#jar-c2', b[2] + 2.7),
      f'tl.to("#jar-a2", {{ opacity: 1, duration: 0.2 }}, {b[2] + 2.9});', pop('#jar-c3', b[2] + 3.0),
      pop('#jar-boom1', b[2] + 3.0, -6), f'tl.to("#jar-boom1", {{ opacity: 0, duration: 0.2 }}, {b[2] + 3.9});',
      # 3 다 익음: 카메라 빠짐 + 층 나뉨(술 방울 → 가라앉은 쌀알)
      f'tl.set("#jar-h3", {{ opacity: 0 }}, {b[3]}); tl.set("#jar-h4", {{ opacity: 1 }}, {b[3]});',
      f'tl.to(["#jar-c0", "#jar-c1", "#jar-c2", "#jar-c3", "#jar-a0", "#jar-a1", "#jar-a2"], {{ opacity: 0, duration: 0.2 }}, {b[3]});',
      cam('#jar-cam', b[3], 1, 0, 0, 0.8, 0, 0),
      *[f'tl.to("#jar-d{k}", {{ opacity: 0, duration: 0.3 }}, {b[3] + 0.3}); tl.set("#jar-g{k}", {{ y: -20 }}, {b[3] + 0.39}); tl.to("#jar-g{k}", {{ opacity: 1, y: 6, duration: 0.6, ease: "power2.out" }}, {b[3] + 0.4});' for k in G],
      f'tl.to("#jar-mash", {{ opacity: 0, duration: 0.6 }}, {b[3] + 0.4});',
      f'tl.to("#jar-lees", {{ opacity: 1, duration: 0.6 }}, {b[3] + 0.4}); tl.to("#jar-top", {{ opacity: 0.92, duration: 0.8 }}, {b[3] + 0.6});',
      f'tl.to("#jar-l4", {{ opacity: 1, duration: 0.25 }}, {b[3] + 1.0}); tl.to("#jar-l5", {{ opacity: 1, duration: 0.25 }}, {b[3] + 1.6});',
      f'tl.to("#jar-gauge", {{ opacity: 0, duration: 0.2 }}, {b[4] - 0.2}); tl.to("#jar-h4", {{ opacity: 0, duration: 0.2 }}, {b[4] - 0.2});',
      # 4 갈림길: 국자로 윗술 → 청주 잔 / 통째로 → 막걸리
      f'tl.to(["#jar-l4", "#jar-l5"], {{ opacity: 0, duration: 0.2 }}, {b[4]});',
      f'tl.fromTo("#jar-ladle", {{ opacity: 0, x: -60, y: -80 }}, {{ opacity: 1, x: 0, y: 0, duration: 0.45, ease: "power2.out" }}, {b[4] + 0.1});',
      f'tl.to("#jar-ladle", {{ x: -30, y: -90, duration: 0.45, ease: "power2.inOut" }}, {b[4] + 0.7});',
      pop('#jar-cup', b[4] + 0.9), f'tl.to("#jar-l6", {{ opacity: 1, duration: 0.25 }}, {b[4] + 1.0});',
      f'tl.fromTo("#jar-brace", {{ opacity: 0, x: 30 }}, {{ opacity: 1, x: 0, duration: 0.3 }}, {b[4] + 1.9});',
      f'tl.to("#jar-l7", {{ opacity: 1, duration: 0.25 }}, {b[4] + 2.0});',
      cam('#jar-cam', round(D - 0.9, 2), 1.15, 640, 820, 0.8, 540, 760, 'power2.in'),
      f'tl.to("#jar-world-wrap", {{ opacity: 0, filter: "blur(8px)", duration: 0.2, ease: "power2.in" }}, {round(D - 0.2, 2)});',
      ]
out['jar'] = scene('jar', f'<div id="jar-world-wrap">{jar_world}{hud}{gauge}{legend}{boom("jar-boom1", "보글보글", 760, 560)}</div>', '\n    '.join(js))

# ===================== 세계 2: 체 (문장 5) =====================
b = BT['sieve']; D = SCN['sieve']
crumbs = ''.join(f'<circle id="sv-c{k}" cx="{400 + (k * 41) % 280}" cy="{735 + (k * 13) % 14}" r="{4 + k % 3}" fill="#FFFDF5" stroke="#CFC6B2" stroke-width="1" opacity="0"/>' for k in range(20))
sv_grains = ''.join(A.grain(f'sv-g{k}', 430 + (k * 37) % 220, 668 + (k * 11) % 26, 'sv') for k in range(14))
small_jar = (f'<g id="sv-jar"><g transform="translate(905 455) rotate(-58) scale(0.42) translate(-540 -740)">'
             f'{A.jar_closed("sv", "sv-jarbody")}</g></g>')
sieve_world = f'''<svg class="world" viewBox="0 0 1080 1920" xmlns="http://www.w3.org/2000/svg">{A.defs('sv')}
  <g id="sv-cam">
    {A.plate('sv', 540, 990, 320)}
    {A.bowl('sv', 'sv-milk', 540, 862, 236, 112)}
    {A.sieve('sv', 540, 720, 206, 48)}
    <ellipse cx="540" cy="684" rx="120" ry="24" fill="url(#sv-mash)" stroke="#CFC3A8" stroke-width="2"/>
    {sv_grains}{crumbs}
    <path id="sv-stream" d="M770 470 C710 520 620 600 560 676" stroke="#EFE6D2" stroke-width="24" stroke-linecap="round" fill="none" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1"/>
    {small_jar}
    <g id="sv-hands">{A.hand(462, 650)}{A.hand(618, 650, -1)}</g>
    {label('sv-l1', '대나무 체', 100, 600, 360, 720)}
    {label('sv-l2', '뽀얀 술', 985, 930, 720, 900, 'end')}
  </g>
</svg>'''
js = ['tl.set("#sv-cam", { x: 0, y: 0, scale: 1, svgOrigin: "0 0" }, 0);',
      'tl.fromTo("#sv-world-wrap", { opacity: 0, filter: "blur(8px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }, 0);',
      cam('#sv-cam', 0, 1.45, 560, 690, 0.01),
      'tl.fromTo("#sv-stream", { attr: { "stroke-dashoffset": 1.1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.4, ease: "power2.in" }, 0.2);',
      'tl.to(["#sv-stream", "#sv-jar"], { opacity: 0, duration: 0.3 }, 1.2);',
      'tl.set("#sv-hands", { opacity: 0 }, 0); tl.to("#sv-hands", { opacity: 1, duration: 0.2 }, 1.1);',
      'tl.fromTo("#sv-hands", { x: -30 }, { x: 30, duration: 0.18, ease: "sine.inOut", yoyo: true, repeat: 9 }, 1.3);',
      pop('#sv-boom', 1.4, -4), 'tl.to("#sv-boom", { opacity: 0, duration: 0.2 }, 3.0);',
      *[f'tl.to("#sv-g{k}", {{ opacity: 0, duration: 0.2 }}, {round(1.6 + k * 0.08, 2)});' for k in range(14)],
      *[f'tl.fromTo("#sv-c{k}", {{ opacity: 0, y: 0 }}, {{ opacity: 1, y: 150, duration: 0.7, ease: "power2.in" }}, {round(1.7 + k * 0.07, 2)}); tl.to("#sv-c{k}", {{ opacity: 0, duration: 0.15 }}, {round(2.4 + k * 0.07, 2)});' for k in range(20)],
      cam('#sv-cam', 2.1, 1.2, 540, 800, 0.9, 540, 745),
      'tl.fromTo("#sv-milk", { attr: { cy: 950, rx: 60, ry: 10 } }, { attr: { cy: 884, rx: 214, ry: 34 }, duration: 1.6, ease: "power1.out" }, 2.3);',
      'tl.to("#sv-l1", { opacity: 1, duration: 0.25 }, 3.1); tl.to("#sv-l2", { opacity: 1, duration: 0.25 }, 3.4);',
      f'tl.to("#sv-world-wrap", {{ opacity: 0, filter: "blur(8px)", duration: 0.15, ease: "power2.in" }}, {round(D - 0.15, 2)});']
out['sieve'] = scene('sieve', f'<div id="sv-world-wrap">{sieve_world}{boom("sv-boom", "싹싹", 790, 540, 72)}</div>', '\n    '.join(js))

# ===================== 세계 3: 잔 (문장 6~8) =====================
b = BT['glass']; D = SCN['glass']


def _pt(v, r, cy=1000):
    a = math.pi * (1 - v / 15)
    return 540 + r * math.cos(a), cy - r * math.sin(a)


def arc(v0, v1, r):
    (x0, y0), (x1, y1) = _pt(v0, r), _pt(v1, r)
    return f'M{x0:.1f} {y0:.1f} A{r} {r} 0 0 1 {x1:.1f} {y1:.1f}'


def tick_label(v, text):
    x, y = _pt(v, 236)
    return f'<text x="{x:.1f}" y="{y + 10:.1f}" text-anchor="middle" font-family="Pretendard" font-weight="800" font-size="32" fill="{CREAM}">{text}</text>'


ticks = ''.join(f'<path d="M{_pt(v, 192)[0]:.1f} {_pt(v, 192)[1]:.1f} L{_pt(v, 166)[0]:.1f} {_pt(v, 166)[1]:.1f}" stroke="{CREAM}" stroke-width="{6 if v % 3 == 0 else 3}"/>' for v in range(16))
dial = f'''<g id="gl-dial" opacity="0" transform="translate(1080 -40)">
      <path d="M270 1000 A270 270 0 0 1 810 1000 L810 1076 L270 1076 Z" fill="#141C30" stroke="#0E1525" stroke-width="6"/>
      <path d="M290 1000 A250 250 0 0 1 790 1000" fill="none" stroke="#3A4C78" stroke-width="10"/>
      <path d="{arc(0, 15, 190)}" fill="none" stroke="#2E3D62" stroke-width="34"/>
      <path id="gl-band" d="{arc(6, 8, 190)}" fill="none" stroke="{TOMATO}" stroke-width="34" opacity="0"/>
      <path d="{arc(3, 12, 150)}" fill="none" stroke="{YEL}" stroke-width="8" opacity="0.9"/>
      {ticks}{tick_label(0, '0')}{tick_label(3, '3')}{tick_label(6, '6')}{tick_label(8, '8')}{tick_label(12, '12')}{tick_label(15, '15')}
      <path id="gl-needle" d="M540 1000 L370 1000" stroke="{YEL}" stroke-width="10" stroke-linecap="round"/>
      <circle cx="540" cy="1000" r="22" fill="#2E3D62" stroke="{YEL}" stroke-width="6"/>
      <text x="540" y="1066" text-anchor="middle" font-family="Wanted Sans" font-weight="800" font-size="40" fill="{CREAM}">도수</text>
    </g>'''
glass_world = f'''<svg class="world" viewBox="0 0 1080 1920" xmlns="http://www.w3.org/2000/svg">{A.defs('gl')}
  <g id="gl-cam">
    {A.plate('gl')}
    {A.tumbler('gl', 'gl-b', 16)}
    {dial}
  </g>
</svg>'''
flav = ''.join(f'<span id="gl-f{k}" class="chip" style="position:absolute; left:{x}px; top:{y}px; background:{c};">{t}</span>'
               for k, (t, c, x, y) in enumerate([('단맛', '#F5C542', 170, 640), ('신맛', '#A7D46F', 770, 640), ('떫은맛', '#C9A3D9', 450, 470)]))
cmp_chips = ('<div class="chiprow" style="top:470px;">'
             '<span id="gl-k0" class="chip">맥주 = 보리 + 탄산</span><span id="gl-k1" class="chip" style="background:#FFE4D6;">막걸리 = 쌀 + 탄산</span></div>')
dial_chips = ('<div class="chiprow" style="top:470px;">'
              f'<span id="gl-d0" class="chip" style="background:{TOMATO}; color:#fff;">6~8도 흔함</span><span id="gl-d1" class="chip" style="background:{YEL};">3~12도까지</span></div>')
js = ['tl.set("#gl-cam", { x: 0, y: 0, scale: 1, svgOrigin: "0 0" }, 0);',
      'tl.fromTo("#gl-world-wrap", { opacity: 0, filter: "blur(8px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }, 0);',
      *[f'tl.fromTo("#gl-b{k}", {{ opacity: 0, y: 0 }}, {{ opacity: 0.95, y: -230, duration: 1.4, ease: "power1.in", repeat: 3 }}, {round(0.2 + k * 0.17, 2)});' for k in range(16)],
      pop('#gl-boom', 0.6, 5), 'tl.to("#gl-boom", { opacity: 0, duration: 0.2 }, 1.8);',
      pop('#gl-k0', b[0] + 0.6), pop('#gl-k1', b[0] + 2.4),
      f'tl.to(["#gl-k0", "#gl-k1"], {{ opacity: 0, duration: 0.2 }}, {b[1] - 0.1});',
      *[pop(f'#gl-f{k}', round(b[1] + 0.2 + k * 0.35, 2)) for k in range(3)],
      *[f'tl.to("#gl-f{k}", {{ x: {dx}, y: {dy}, scale: 0.6, opacity: 0, duration: 0.6, ease: "power2.in" }}, {round(b[2] - 0.9 + k * 0.1, 2)});'
        for k, (dx, dy) in enumerate([(300, 160), (-300, 160), (0, 240)])],
      f'tl.set("#gl-dial", {{ opacity: 1 }}, {b[2]});',
      f'tl.to("#gl-cam", {{ x: -1080, duration: 0.8, ease: "power2.inOut" }}, {b[2]});',
      f'tl.fromTo("#gl-needle", {{ rotation: 0 }}, {{ rotation: {round(180 * 7 / 15, 1)}, duration: 1.0, ease: "back.out(1.4)", transformOrigin: "100% 50%" }}, {b[2] + 0.6});',
      f'tl.to("#gl-band", {{ opacity: 1, duration: 0.3 }}, {b[2] + 1.4});',
      pop('#gl-d0', b[2] + 1.5), pop('#gl-d1', b[2] + 2.5),
      f'tl.to("#gl-world-wrap", {{ opacity: 0, filter: "blur(8px)", duration: 0.15, ease: "power2.in" }}, {round(D - 0.15, 2)});']
out['glass'] = scene('glass', f'<div id="gl-world-wrap">{glass_world}{cmp_chips}{flav}{dial_chips}{boom("gl-boom", "톡톡", 790, 640, 72)}</div>', '\n    '.join(js))

# ===================== 세계 4: 퀴즈 → 첫 장면(닫힌 항아리)으로 돌아와 반복 재생 =====================
b = BT['quiz']; D = SCN['quiz']
quiz_world = f'''<svg class="world" viewBox="0 0 1080 1920" xmlns="http://www.w3.org/2000/svg">{A.defs('qz')}
  <g id="qz-jar">{A.plate('qz')}{A.jar_closed('qz', 'qz-body')}{A.lid('qz-lid')}</g>
</svg>'''
quiz = ('<div class="chiprow" style="top:470px; flex-wrap: wrap;">'
        '<span id="qz-q" class="chip" style="font-size:38px; background:' + YEL + ';">퀴즈! 윗술만 떠내면?</span></div>'
        '<div class="chiprow" style="top:550px;">'
        + ''.join(f'<span id="qz-o{k}" class="chip">{t}</span>' for k, t in enumerate(['1 막걸리', '2 청주', '3 소주'])) + '</div>')
js = ['tl.fromTo("#qz-world-wrap", { opacity: 0, filter: "blur(8px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.25, ease: "power4.out" }, 0);',
      'tl.set("#qz-jar", { x: 92, y: 200, scale: 0.83, svgOrigin: "0 0" }, 0);',
      f'tl.to("#qz-jar", {{ x: 0, y: 0, scale: 1, duration: 0.7, ease: "power2.inOut" }}, {round(D - 0.9, 2)});',
      pop('#qz-q', 0.3), *[pop(f'#qz-o{k}', round(0.8 + k * 0.25, 2)) for k in range(3)],
      f'tl.to(["#qz-q", "#qz-o0", "#qz-o1", "#qz-o2"], {{ opacity: 0, duration: 0.25 }}, {round(D - 0.9, 2)});']
out['quiz'] = scene('quiz', f'<div id="qz-world-wrap">{quiz_world}{quiz}</div>', '\n    '.join(js))

for w, html in out.items():
    (comp / f'{w}.html').write_text(html, encoding='utf-8')

# ---------- 고정 틀: 1교시와 같은 바·째리·말풍선, 장 제목은 세계마다 ----------
CHAPTERS = [(0.0, '막걸리 해부'), (STARTS['jar'] + BT['jar'][2], '항아리 속 발효'), (STARTS['jar'] + BT['jar'][4], '떠내기 vs 통째로'),
            (STARTS['sieve'], '통째로 거르기'), (STARTS['glass'], '한 잔에 담긴 것'), (STARTS['quiz'], '퀴즈 타임')]
ch_html = ''.join(f'<div id="fr-ch{k}" class="ch">{t}</div>' for k, (s, t) in enumerate(CHAPTERS))
ch_js = []
for k, (s, t) in enumerate(CHAPTERS):
    if k > 0:
        ch_js.append(f'tl.fromTo("#fr-ch{k}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.22, ease: "power4.out" }}, {s + 0.05:.2f});')
    if k + 1 < len(CHAPTERS):
        ch_js.append(f'tl.to("#fr-ch{k}", {{ opacity: 0, filter: "blur(6px)", duration: 0.14, ease: "power2.in" }}, {CHAPTERS[k + 1][0] - 0.14:.2f});')
HOPS = sorted({round(STARTS[w] + c[1], 2) for w in ORDER for c in CAP[w]} - {round(STARTS['jar'] + CAP['jar'][0][1], 2)} | {0.3})
hop_js = '\n    '.join(f'tl.to("#fr-jjeri", {{ keyframes: [{{ y: -22, duration: 0.14, ease: "power2.out" }}, {{ y: 0, duration: 0.2, ease: "power2.in" }}] }}, {t:.2f});' for t in HOPS)
grain_lines = ''.join(f'<path d="M0 {y} C300 {y - 10} 700 {y + 12} 1080 {y - 4}" fill="none" stroke="#6E3A1C" stroke-width="5"/>' for y in (90, 170, 260, 360, 470))
frame = f"""<template>
  <style>
    {FONTS}
    #root {{ position: absolute; inset: 0; overflow: hidden; font-family: 'Pretendard'; color: {CREAM};
             background: radial-gradient(circle at 50% 45%, #33456D 0%, {NAVY} 55%, #141C30 100%); }}
    #fr-badgebox {{ position: absolute; left: 0; right: 0; top: 274px; text-align: center; }}
    #fr-badge {{ display: inline-block; font-weight: 700; font-size: 30px; color: #fff; background: {TOMATO}; border-radius: 999px; padding: 6px 24px; }}
    .ch {{ position: absolute; left: 0; right: 0; top: 326px; text-align: center; font-family: 'Wanted Sans'; font-weight: 800; font-size: 80px; line-height: 1.1; letter-spacing: -0.035em; color: {CREAM}; opacity: 0; }}
    #fr-ch0 {{ opacity: 1; }}
    #fr-jjeri {{ position: absolute; left: 34px; top: 1084px; width: 218px; }}
    #fr-bubble {{ position: absolute; left: 262px; top: 1040px; width: 754px; height: 200px; background: {CREAM}; border: 5px solid {INK}; border-radius: 30px; box-shadow: 0 8px 0 rgba(0,0,0,0.25); }}
    #fr-tail {{ position: absolute; left: 224px; top: 1114px; width: 44px; height: 52px; }}
    #fr-counter {{ position: absolute; left: 0; top: 1330px; width: 1080px; height: 590px; }}
    #fr-handle {{ position: absolute; left: 0; right: 0; top: 1376px; text-align: center; font-weight: 700; font-size: 32px; color: #F6D9B8; opacity: 0.85; }}
  </style>
  <div id="root" data-composition-id="frame" data-width="1080" data-height="1920">
    <div id="fr-badgebox"><span id="fr-badge">째리의 술 해부 · 막걸리</span></div>
    {ch_html}
    <img id="fr-jjeri" src="assets/img/jjeri.svg" alt="째리">
    <svg id="fr-counter" viewBox="0 0 1080 590" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="1080" height="590" fill="#8A4A26"/><rect x="0" y="0" width="1080" height="30" fill="#A8693A"/><rect x="0" y="30" width="1080" height="8" fill="#5A2E14"/>{grain_lines}
    </svg>
    <div id="fr-handle" data-layout-ignore>술째리고 &nbsp;@sooljjerigo</div>
    <div id="fr-bubble"></div>
    <svg id="fr-tail" viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><polygon points="44,4 4,26 44,48" fill="{CREAM}"/><polyline points="40,6 4,26 40,46" fill="none" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/></svg>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.set("#fr-jjeri", {{ y: 0 }}, 0);
    {hop_js}
    {chr(10).join('    ' + j for j in ch_js)}
    tl.set({{}}, {{}}, {TOTAL});
    window.__timelines["frame"] = tl;
  </script>
</template>
"""
(comp / 'frame.html').write_text(frame, encoding='utf-8')

# ---------- 소리 ----------
S, J = STARTS, BT['jar']
SFX = [('whoosh-short', S['jar'] + 1.2), ('click-soft', S['jar'] + J[1] + 0.6), ('click-soft', S['jar'] + J[1] + 1.9),
       ('riser', S['jar'] + J[2] + 0.1), ('whoosh', S['jar'] + J[2] + 0.4), ('pop', S['jar'] + J[2] + 3.0),
       ('sparkle', S['jar'] + J[3] + 0.1), ('whoosh-short', S['jar'] + J[3]), ('pop', S['jar'] + J[4] + 0.9),
       ('whoosh', S['sieve']), ('click', S['sieve'] + 1.4), ('pop', S['glass'] + 0.6), ('whoosh-short', S['glass'] + BT['glass'][2]),
       ('impact-bass-1', S['glass'] + BT['glass'][2] + 1.4), ('pop', S['quiz'] + 0.3), ('click-soft', S['quiz'] + 0.8)]
PEAK = {'pop': 0.12, 'click-soft': 0.073, 'click': 0.05, 'impact-bass-1': 0.073, 'whoosh': 0.162, 'whoosh-short': 0.162, 'riser': 1.0, 'sparkle': 0.05}
LEN = {'pop': 0.72, 'click-soft': 0.36, 'click': 0.3, 'impact-bass-1': 2.1, 'whoosh': 0.57, 'whoosh-short': 0.57, 'riser': 1.5, 'sparkle': 1.0}
VOL = {'pop': 0.45, 'click-soft': 0.5, 'click': 0.4, 'impact-bass-1': 0.3, 'whoosh': 0.4, 'whoosh-short': 0.4, 'riser': 0.3, 'sparkle': 0.35}
hosts = '\n      '.join(f'<div id="{w}" data-composition-id="{w}" data-composition-src="compositions/{w}.html" data-start="{S[w]}" data-duration="{SCN[w]}" data-track-index="1" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:2"></div>' for w in ORDER)
vo_tags = '\n      '.join(f'<audio id="vo{c[3]["k"]:02d}" class="clip" src="{c[3]["file"]}" data-start="{round(S[w] + c[1], 3)}" data-duration="{round(c[3]["end"] - c[3]["head"], 3)}" data-media-start="{c[3]["head"]}" data-track-index="3" data-volume="1"></audio>' for w in ORDER for c in CAP[w])
sfx_tags = '\n      '.join(f'<audio id="sfx{k:02d}" class="clip" src="assets/sfx/{f}.mp3" data-start="{max(0, round(t - PEAK[f] + 1 / 30, 3))}" data-duration="{LEN[f]}" data-track-index="{10 + k}" data-volume="{VOL[f]}"></audio>' for k, (f, t) in enumerate(SFX))
(root / 'index.html').write_text(f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" /><meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>* {{ margin: 0; padding: 0; box-sizing: border-box; }} html, body {{ margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: {NAVY}; }}</style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL}" data-width="1080" data-height="1920">
      <div id="frame" data-composition-id="frame" data-composition-src="compositions/frame.html" data-start="0" data-duration="{TOTAL}" data-track-index="0" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:1"></div>
      {hosts}
      {vo_tags}
      <audio id="bgm" class="clip" src="assets/bgm/bed.mp3" data-start="0" data-duration="{TOTAL}" data-media-start="0" data-track-index="9" data-volume="0.16" data-fade-in="0.3" data-fade-out="2.0"></audio>
      {sfx_tags}
    </div>
    <script>window.__timelines = window.__timelines || {{}}; window.__timelines["main"] = gsap.timeline({{ paused: true }});</script>
  </body>
</html>
""", encoding='utf-8')
print('total', TOTAL, {w: (STARTS[w], SCN[w]) for w in ORDER})

# 엔진 비교용 정답 시간표(같은 대본·음성이면 엔진도 같은 시각을 내야 한다)
(root / 'timeline.json').write_text(json.dumps({
    'total': TOTAL, 'gap': GAP, 'lead': LEAD, 'tail': TAIL, 'min': MIN, 'extra': {f'{w}:{i}': v for (w, i), v in EXTRA.items()},
    'worlds': [{'id': w, 'start': STARTS[w], 'dur': SCN[w],
                'beats': [{'k': c[3]['k'], 'start_local': c[1], 'speech': round(c[3]['end'] - c[3]['head'], 3), 'media_start': c[3]['head']} for c in CAP[w]]}
               for w in ORDER],
    'chapters': [{'start': round(s, 2), 'title': t} for s, t in CHAPTERS]}, ensure_ascii=False, indent=1), encoding='utf-8')
