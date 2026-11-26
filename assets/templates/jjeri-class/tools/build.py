"""3판: 2판 장면 부품(이 파일 앞부분) 위에 내레이션 시계·장 제목·집 규칙·댓글 유도를 얹는다. 대본은 tools/script.py, 음성은 tools/tts.py.
"""
"""버번 vs 셰리 캐스크 — '1분 술 상식' 틀(벤치마크: @1min.biscuit EP03 구조) 장면 생성기.
다시 만들려면: python tools/build.py   (compositions/*.html 과 index.html 을 덮어쓴다)
좌표: 그림(svg)은 무대 안 960x580 칸(화면 left 60, top 530 기준), 칩(html)은 화면 좌표."""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
comp = root / 'compositions'

NAVY, INK, CREAM, BG, TOMATO, YEL = '#1F2A44', '#0E1525', '#FFF8EE', '#F7F3EC', '#C2410C', '#FDE68A'
AMBER, MAHO, CLEAR = '#F0A93B', '#8E2A14', '#DCE7F0'
WOOD_L, GRAIN_L, WOOD_D, GRAIN_D, HOOP = '#C68A4E', '#9A6334', '#8A4A26', '#63331A', '#2B2B33'
AX, AY = 60, 410  # 그림 칸의 화면 위치

FONTS = """@font-face { font-family: 'Wanted Sans'; src: url('assets/fonts/WantedSans-ExtraBold.otf'); font-weight: 800; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-Bold.woff2'); font-weight: 700; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-SemiBold.woff2'); font-weight: 600; }"""

# 장면: id, 길이(초)
SCENES = [('s1', 4.5), ('s2', 5.0), ('s3', 6.0), ('s4', 8.0), ('s5', 7.0), ('s6', 6.0),
          ('s7', 5.5), ('s8', 4.5), ('s9', 5.5), ('s10', 6.0), ('s11', 5.0)]
STARTS = {}
_t = 0.0
for _i, _d in SCENES:
    STARTS[_i] = round(_t, 2)
    _t += _d
TOTAL = round(_t, 2)

# ---------- 그림 부품 (svg) ----------
GLASS = ("M44 10 C40 60 30 100 34 150 C38 205 62 236 88 246 L90 262 C90 270 60 276 52 282 "
         "L52 292 L148 292 L148 282 C140 276 110 270 110 262 L112 246 C138 236 162 205 166 150 C170 100 160 60 156 10 Z")
BOWL = "M44 10 C40 60 30 100 34 150 C38 205 62 236 88 246 L112 246 C138 236 162 205 166 150 C170 100 160 60 156 10 Z"


def glass(i, x, y, s, color, level=0.5, line='#E8EEF8'):
    top = round(246 - level * 236)
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <clipPath id="{i}-cp"><path d="{BOWL}"/></clipPath>
      <path d="{GLASS}" fill="rgba(255,255,255,0.10)"/>
      <rect id="{i}-liq" x="0" y="{top}" width="200" height="{250 - top}" fill="{color}" clip-path="url(#{i}-cp)"/>
      <path d="{GLASS}" fill="none" stroke="{line}" stroke-width="5" stroke-linejoin="round"/>
      <path d="M58 40 C52 90 50 140 60 190" fill="none" stroke="#fff" stroke-opacity="0.45" stroke-width="7" stroke-linecap="round"/>
    </g></g>'''


def barrel(i, x, y, s, wood=WOOD_L, grain=GRAIN_L, tint=False):
    body = "M40 0 L200 0 Q240 150 200 300 L40 300 Q0 150 40 0 Z"
    tint_svg = ''
    if tint:  # 셰리가 스며드는 붉은 기운 — 아래에서 위로 차오른다
        tint_svg = (f'<clipPath id="{i}-tc"><rect id="{i}-tr" x="0" y="300" width="240" height="0"/></clipPath>'
                    f'<path d="{body}" fill="#7A1F2B" fill-opacity="0.62" clip-path="url(#{i}-tc)"/>')
    hoops = ''.join(f'<path d="M{a} {yy} Q120 {yy + 12} {240 - a} {yy}" fill="none" stroke="{HOOP}" stroke-width="13" stroke-linecap="round"/>'
                    for a, yy in [(31, 40), (22, 100), (22, 200), (31, 260)])
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <path d="{body}" fill="{wood}" stroke="#3B2412" stroke-width="6" stroke-linejoin="round"/>
      {tint_svg}
      <path d="M80 0 Q64 150 80 300 M120 0 L120 300 M160 0 Q176 150 160 300" fill="none" stroke="{grain}" stroke-width="4"/>
      {hoops}
      <ellipse cx="120" cy="0" rx="80" ry="13" fill="{grain}" stroke="#3B2412" stroke-width="5"/>
      <circle cx="120" cy="150" r="9" fill="#3B2412"/>
    </g></g>'''


def vanilla(i, x, y, s=1.0):
    pod = '<path d="M-84 0 C-44 -16 44 -16 84 0 C44 12 -44 12 -84 0 Z" fill="#3B2412" stroke="#1E120A" stroke-width="4"/><path d="M-70 0 L70 0" stroke="#6B4423" stroke-width="3"/>'
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <g transform="rotate(-14)">{pod}</g><g transform="rotate(12) translate(0 18)">{pod}</g>
      <circle cx="-70" cy="-18" r="16" fill="#FFF1C9" stroke="#D9A066" stroke-width="3"/><circle cx="-70" cy="-18" r="6" fill="#F0A93B"/>
    </g></g>'''


def caramel(i, x, y, s=1.0):
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <rect x="-48" y="-44" width="96" height="88" rx="18" fill="#D98A2B" stroke="#7A4A14" stroke-width="5"/>
      <path d="M-30 -26 L10 -26" stroke="#F6C77A" stroke-width="9" stroke-linecap="round"/>
      <path d="M-12 44 C-12 64 4 66 4 50 C4 66 18 64 18 44" fill="#D98A2B" stroke="#7A4A14" stroke-width="4"/>
    </g></g>'''


def smoke(i, x, y, s=1.0):
    p = ["M-40 60 C-70 20 -10 0 -40 -40 C-60 -66 -30 -80 -36 -96",
         "M0 60 C-30 20 30 0 0 -40 C-20 -66 10 -80 4 -100",
         "M40 60 C10 20 70 0 40 -40 C20 -66 50 -80 44 -92"]
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">''' + ''.join(
        f'<path class="{i}-w" d="{d}" fill="none" stroke="#CBD5E1" stroke-opacity="0.9" stroke-width="11" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="0"/>'
        for d in p) + '</g></g>'


def anise(i, x, y, s=1.0):
    import math
    pts = []
    for k in range(16):
        r = 58 if k % 2 == 0 else 20
        a = math.pi * 2 * k / 16 - math.pi / 2
        pts.append(f'{r * math.cos(a):.1f},{r * math.sin(a):.1f}')
    seeds = ''.join(f'<circle cx="{38 * math.cos(math.pi * 2 * k / 8 - math.pi / 2):.1f}" cy="{38 * math.sin(math.pi * 2 * k / 8 - math.pi / 2):.1f}" r="7" fill="#D9A066"/>' for k in range(8))
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <polygon points="{' '.join(pts)}" fill="#6B3A1E" stroke="#3B2412" stroke-width="5" stroke-linejoin="round"/>
      {seeds}<circle r="10" fill="#3B2412"/>
    </g></g>'''


def grapes(i, x, y, s=1.0):
    cs = [(-26, -20), (0, -24), (26, -20), (-14, 4), (14, 4), (0, 28), (-28, 22), (28, 22)]
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <path d="M0 -40 C4 -56 14 -62 24 -64" fill="none" stroke="#5B3A1E" stroke-width="6" stroke-linecap="round"/>
      <path d="M8 -50 C30 -70 50 -54 40 -42 C28 -50 18 -48 8 -50 Z" fill="#4D7C3A"/>''' + ''.join(
        f'<circle cx="{a}" cy="{b}" r="17" fill="#4A1D3F" stroke="#2A0F23" stroke-width="3"/><circle cx="{a - 5}" cy="{b - 6}" r="4" fill="#B07AA0"/>'
        for a, b in cs) + '</g></g>'


def plum(i, x, y, s=1.0):
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <circle r="44" fill="#5E1F3D" stroke="#2A0F23" stroke-width="4"/>
      <path d="M0 -44 C-6 -10 -6 20 0 44" fill="none" stroke="#3F1029" stroke-width="3"/>
      <ellipse cx="-16" cy="-16" rx="9" ry="14" fill="#A05A7E" fill-opacity="0.7"/>
      <path d="M2 -44 C16 -66 40 -62 44 -50 C30 -44 14 -44 2 -44 Z" fill="#4D7C3A"/>
    </g></g>'''


def cherries(i, x, y, s=1.0):
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <path d="M-22 10 C-14 -30 0 -50 10 -60 M22 14 C18 -24 14 -44 10 -60" fill="none" stroke="#4D3A1E" stroke-width="5" stroke-linecap="round"/>
      <circle cx="-22" cy="22" r="24" fill="#7E1426" stroke="#3E0912" stroke-width="3"/>
      <circle cx="22" cy="26" r="24" fill="#7E1426" stroke="#3E0912" stroke-width="3"/>
      <circle cx="-30" cy="14" r="6" fill="#D0707F"/><circle cx="14" cy="18" r="6" fill="#D0707F"/>
    </g></g>'''


def bottle(i, x, y, s=1.0):
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <path d="M44 20 L76 20 L76 96 C76 112 110 116 110 146 L110 330 C110 338 104 342 96 342 L24 342 C16 342 10 338 10 330 L10 146 C10 116 44 112 44 96 Z" fill="#1F3B2C" stroke="#0E1F16" stroke-width="5"/>
      <rect x="40" y="6" width="40" height="18" rx="4" fill="#7A1F2B"/>
      <rect x="18" y="196" width="84" height="84" rx="8" fill="{CREAM}"/>
      <text x="60" y="250" text-anchor="middle" font-family="Pretendard" font-weight="700" font-size="30" fill="{NAVY}">셰리</text>
      <path d="M24 150 L24 320" stroke="#fff" stroke-opacity="0.25" stroke-width="8" stroke-linecap="round"/>
    </g></g>'''


def arrow(i, x1, y1, x2, y2, color=CREAM, dash=False):
    d = ' stroke-dasharray="14 12"' if dash else ''
    return (f'<g id="{i}"><path d="M{x1} {y1} L{x2 - 18} {y2}" stroke="{color}" stroke-width="8" stroke-linecap="round"{d}/>'
            f'<path d="M{x2 - 30} {y2 - 18} L{x2} {y2} L{x2 - 30} {y2 + 18}" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></g>')


# ---------- html 부품 ----------
def chip(i, text, cx, cy, cls='c-yel'):
    """화면 좌표 (cx, cy) 가운데에 칩. 바깥 상자는 고정, 안쪽 span 만 움직인다."""
    return f'<div class="chipbox" style="left:{cx - 300}px; top:{cy - 30}px;"><span id="{i}" class="chip {cls}">{text}</span></div>'


def tag(i, text, cls='t-yel'):
    return f'<div class="tagbox"><span id="{i}" class="tag {cls}">{text}</span></div>'


def caps(sid, lines):
    """lines: [(text, start, end)] — 같은 자리의 자막 상자 안 글자만 바뀐다."""
    html = ''.join(f'<div id="{sid}-cap{k}" class="captext">{t.replace(chr(10), "<br>")}</div>' for k, (t, a, b) in enumerate(lines))
    return f'<div class="capbox">{html}</div>'


def caps_js(sid, lines, last=False):
    js = []
    for k, (t, a, b) in enumerate(lines):
        e = f'#{sid}-cap{k}'
        js.append(f'tl.fromTo("{e}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.18, ease: "power4.out" }}, {a});')
        if b is not None:
            js.append(f'tl.to("{e}", {{ opacity: 0, filter: "blur(6px)", duration: 0.14, ease: "power2.in" }}, {b - 0.14});')
    return '\n    '.join(js)


CSS = f"""
    {FONTS}
    #root {{ position: absolute; inset: 0; overflow: hidden; font-family: 'Pretendard'; color: {NAVY}; }}
    .art {{ position: absolute; left: {AX}px; top: {AY}px; width: 960px; height: 580px; overflow: visible; }}
    .capbox {{ position: absolute; left: 296px; width: 720px; top: 1044px; height: 184px; }}
    .captext {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center; font-weight: 700; font-size: 38px; line-height: 1.4; letter-spacing: -0.02em; color: {NAVY}; opacity: 0; }}
    .src {{ position: absolute; left: 270px; width: 770px; top: 1248px; text-align: right; }}
    .src span {{ display: inline-block; background: {YEL}; color: {NAVY}; font-weight: 600; font-size: 28px; padding: 2px 16px; border-radius: 8px; }}
    .chipbox {{ position: absolute; width: 600px; height: 60px; display: flex; align-items: center; justify-content: center; }}
    .chip {{ display: inline-block; font-weight: 700; font-size: 34px; padding: 6px 20px; border-radius: 14px; border: 3px solid {INK}; white-space: nowrap; }}
    .c-yel {{ background: {YEL}; color: {NAVY}; }}
    .c-cream {{ background: {CREAM}; color: {NAVY}; }}
    .c-amber {{ background: {AMBER}; color: {NAVY}; }}
    .c-maho {{ background: {MAHO}; color: #fff; }}
    .c-tom {{ background: {TOMATO}; color: #fff; }}
    .tagbox {{ position: absolute; left: 70px; top: 418px; }}
    .tag {{ display: inline-block; font-weight: 700; font-size: 32px; padding: 4px 18px; border-radius: 12px; border: 3px solid {INK}; }}
    .t-yel {{ background: {YEL}; color: {NAVY}; }}
    .t-grey {{ background: #E5E7EB; color: {NAVY}; }}
    .t-tom {{ background: {TOMATO}; color: #fff; }}
    .t-amber {{ background: {AMBER}; color: {NAVY}; }}
    .t-maho {{ background: {MAHO}; color: #fff; }}
"""


def scene(sid, body, js, extra_css='', src=None):
    src_html = f'<div class="src"><span id="{sid}-src">{src}</span></div>' if src else ''
    return f"""<template>
  <style>{CSS}{extra_css}
  </style>
  <div id="root" data-composition-id="{sid}" data-width="1080" data-height="1920">
    {body}
    {src_html}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {js}
    window.__timelines["{sid}"] = tl;
  </script>
</template>
"""


def art(sid, inner):
    return f'<svg id="{sid}-art" class="art" viewBox="0 0 960 580" xmlns="http://www.w3.org/2000/svg">{inner}</svg>'


def pop(sel, t, rot=0):
    return (f'tl.fromTo("{sel}", {{ scale: 0.5, opacity: 0, rotation: {rot - 6} }}, '
            f'{{ scale: 1, opacity: 1, rotation: {rot}, duration: 0.38, ease: "back.out(1.7)", transformOrigin: "50% 50%" }}, {t});')


def art_in(sid):
    return f'tl.fromTo("#{sid}-art", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }}, 0);'


def art_out(sid, dur, extra=()):
    sels = ', '.join([f'"#{sid}-art"'] + [f'"{e}"' for e in extra])
    return f'tl.to([{sels}], {{ opacity: 0, filter: "blur(8px)", duration: 0.15, ease: "power2.in" }}, {dur - 0.15});'


def rise(sel, t):
    return (f'tl.fromTo("{sel}", {{ y: 70, opacity: 0 }}, '
            f'{{ y: 0, opacity: 1, duration: 0.55, ease: "expo.out" }}, {t});')


SRC_WA = 'Whisky Advocate'
SRC_BOTH = 'Whisky Advocate · Frontiers in Chemistry(2018)'

# ---------- 장면 ----------
out = {}

# s1 질문으로 시작 (프레임 0 = 썸네일: 잔·이름·자막이 이미 떠 있다)
L1 = [('버번 캐스크 vs 셰리 캐스크,\n맛이 어떻게 다를까?', 0, None)]
out['s1'] = scene('s1',
    art('s1', glass('s1-gA', 165, 50, 1.45, AMBER, 0.42) + glass('s1-gB', 505, 50, 1.45, MAHO, 0.42))
    + chip('s1-nA', '버번 캐스크', AX + 310, AY + 495, 'c-amber') + chip('s1-nB', '셰리 캐스크', AX + 650, AY + 495, 'c-maho')
    + chip('s1-qA', '바닐라?', AX + 200, AY + 32, 'c-cream') + chip('s1-qB', '진한 과일?', AX + 770, AY + 32, 'c-cream')
    + caps('s1', L1),
    '\n    '.join([
        'tl.set("#s1-cap0", { opacity: 1 }, 0);',
        pop('#s1-qA', 1.0, -4), pop('#s1-qB', 1.5, 4),
        'tl.fromTo("#s1-gA", { rotation: 0 }, { rotation: -4, duration: 0.3, ease: "power2.out", transformOrigin: "50% 100%" }, 1.0);',
        'tl.fromTo("#s1-gB", { rotation: 0 }, { rotation: 4, duration: 0.3, ease: "power2.out", transformOrigin: "50% 100%" }, 1.5);',
        art_out('s1', 4.5, ['#s1-qA', '#s1-qB', '#s1-nA', '#s1-nB', '#s1-cap0']),
    ]))

# s2 흔한 생각
L2 = [('오크통은 그냥\n술을 담아 두는 그릇이다?', 0.15, None)]
out['s2'] = scene('s2',
    tag('s2-tag', '흔히 하는 생각', 't-grey')
    + art('s2', glass('s2-g', 110, 140, 1.15, CLEAR, 0.45) + arrow('s2-ar', 370, 330, 480, 330)
          + barrel('s2-b', 520, 70, 1.35)
          + f'<g transform="translate(895 150)"><text id="s2-q" font-family="Wanted Sans" font-weight="800" font-size="140" fill="{TOMATO}" text-anchor="middle" x="0" y="40">?</text></g>')
    + chip('s2-c1', '투명한 원액', AX + 225, AY + 500, 'c-cream') + chip('s2-c2', '그냥 그릇?', AX + 682, AY + 520, 'c-yel')
    + caps('s2', L2),
    '\n    '.join([
        art_in('s2'), pop('#s2-tag', 0.05),
        'tl.fromTo("#s2-g", { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.5, ease: "expo.out" }, 0.1);',
        'tl.fromTo("#s2-ar", { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, 0.6);',
        'tl.fromTo("#s2-b", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.55, ease: "back.out(1.4)" }, 0.3);',
        pop('#s2-c1', 0.9), pop('#s2-q', 2.0, 8), pop('#s2-c2', 2.4),
        caps_js('s2', L2),
        art_out('s2', 5.0, ['#s2-tag', '#s2-c1', '#s2-c2', '#s2-cap0']),
    ]))

# s3 실제로는 — 통 단면, 나무 성분이 원액으로 번지며 호박색이 된다 + 도장
import random
rng = random.Random(7)
parts = []
for k in range(18):
    side = k % 2
    y = 130 + (k * 37) % 340
    x0 = 300 if side == 0 else 660
    dx = (1 if side == 0 else -1) * rng.randint(70, 150)
    parts.append((f's3-p{k}', x0, y, dx, round(0.6 + (k * 0.13) % 2.0, 2)))
grain = ''.join(f'<path d="M{x} 70 C{x - 8} 180 {x + 8} 300 {x} 520" fill="none" stroke="{GRAIN_L}" stroke-width="4"/>' for x in (248, 266, 694, 712))
s3_art = (f'<rect x="230" y="50" width="500" height="490" rx="46" fill="{WOOD_L}" stroke="#3B2412" stroke-width="6"/>{grain}'
          f'<rect id="s3-liq" x="290" y="100" width="380" height="390" rx="24" fill="{CLEAR}"/>'
          f'<rect x="290" y="100" width="380" height="390" rx="24" fill="none" stroke="#1B1310" stroke-width="12"/>'
          + ''.join(f'<circle id="{i}" cx="{x}" cy="{y}" r="8" fill="{AMBER}" opacity="0"/>' for i, x, y, dx, t in parts))
L3 = [('투명한 원액이 나무를 우려내며\n색과 향을 입어요.', 0.15, None)]
js3 = [art_in('s3'), pop('#s3-tag', 0.05), pop('#s3-c1', 0.4), pop('#s3-c2', 0.6),
       f'tl.fromTo("#s3-liq", {{ attr: {{ fill: "{CLEAR}" }} }}, {{ attr: {{ fill: "#E39B2F" }}, duration: 2.6, ease: "power1.inOut" }}, 0.6);']
for i, x, y, dx, t in parts:
    js3.append(f'tl.fromTo("#{i}", {{ x: 0, opacity: 0 }}, {{ x: {dx}, opacity: 1, duration: 0.5, ease: "power2.out" }}, {t});')
    js3.append(f'tl.to("#{i}", {{ opacity: 0, duration: 0.6, ease: "power1.in" }}, {t + 0.5});')
js3 += ['tl.fromTo("#s3-stamp", { scale: 2.2, opacity: 0, rotation: -14 }, { scale: 1, opacity: 1, rotation: -8, duration: 0.28, ease: "power4.in" }, 3.4);',
        caps_js('s3', L3), art_out('s3', 6.0, ['#s3-tag', '#s3-c1', '#s3-c2', '#s3-stamp', '#s3-cap0', '#s3-src'])]
out['s3'] = scene('s3',
    tag('s3-tag', '실제로는', 't-tom') + art('s3', s3_art)
    + chip('s3-c1', '오크 나무', AX + 120, AY + 160, 'c-cream') + chip('s3-c2', '원액', AX + 480, AY + 60, 'c-cream')
    + '<div class="stampbox"><span id="s3-stamp">오크통 = 티백</span></div>'
    + caps('s3', L3),
    '\n    '.join(js3),
    extra_css=f"""
    .stampbox {{ position: absolute; left: 140px; width: 800px; top: 670px; height: 160px; display: flex; align-items: center; justify-content: center; }}
    #s3-stamp {{ display: inline-block; font-family: 'Wanted Sans'; font-weight: 800; font-size: 76px; color: {TOMATO}; background: rgba(255,248,238,0.94); border: 7px solid {TOMATO}; border-radius: 16px; padding: 4px 30px; }}""",
    src=SRC_WA)

# s4 버번 캐스크의 출신 — 새 통 규칙, 한 번 쓴 통이 스코틀랜드로
L4 = [('버번은 새 오크통에만 담아야 해서,\n한 번 쓴 통이 스코틀랜드로 와요.', 0.15, 4.4),
      ('그래서 스카치 대부분은\n버번 캐스크에서 익어요.', 4.4, None)]
s4_art = (barrel('s4-b1', 70, 130, 1.0)
          + f'<path id="s4-arc" d="M330 250 Q480 60 640 210" fill="none" stroke="{CREAM}" stroke-width="7" stroke-dasharray="16 14" stroke-linecap="round" opacity="0"/>'
          + barrel('s4-e1', 712, 250, 0.6) + barrel('s4-e2', 712, 62, 0.6) + barrel('s4-e3', 300, 250, 0.6))
out['s4'] = scene('s4',
    tag('s4-tag', '버번 캐스크', 't-amber') + art('s4', s4_art)
    + chip('s4-c1', '미국 · 새 통만', AX + 190, AY + 470, 'c-cream')
    + chip('s4-c2', '스코틀랜드 · 한 번 쓴 통', AX + 580, AY + 470, 'c-yel')
    + chip('s4-c3', '구하기 쉽고 비교적 저렴', AX + 430, AY + 40, 'c-amber')
    + caps('s4', L4),
    '\n    '.join([
        art_in('s4'), pop('#s4-tag', 0.05),
        'tl.fromTo("#s4-b1", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.15);',
        pop('#s4-c1', 0.7),
        'tl.fromTo("#s4-arc", { opacity: 0 }, { opacity: 0.9, duration: 0.3, ease: "power2.out" }, 1.6);',
        'tl.to("#s4-c1", { opacity: 0, duration: 0.15, ease: "power2.in" }, 1.7);',
        'tl.fromTo("#s4-b1", { x: 0 }, { x: 390, duration: 1.0, ease: "power2.inOut" }, 1.8);',
        'tl.to("#s4-b1", { keyframes: [{ y: -110, duration: 0.5, ease: "power2.out" }, { y: 0, duration: 0.5, ease: "power2.in" }] }, 1.8);',
        'tl.to("#s4-arc", { opacity: 0, duration: 0.2 }, 2.8);',
        pop('#s4-c2', 2.85),
        pop('#s4-e1', 4.6), pop('#s4-e2', 4.8), pop('#s4-e3', 5.0), pop('#s4-c3', 5.4),
        caps_js('s4', L4),
        art_out('s4', 8.0, ['#s4-c2', '#s4-c3', '#s4-cap1', '#s4-src']),
    ]),
    src='Whisky Advocate · 미국 버번 규정')

# s5 버번 캐스크의 맛 — 그을린 미국산 오크 판자에서 향이 피어오른다
crackle = ''.join(f'<path d="M{x} 334 l10 12 l-8 10 l12 14" fill="none" stroke="#4A3A32" stroke-width="3"/>' for x in range(130, 840, 46))
wgrain = ''.join(f'<path d="M100 {y} C300 {y - 14} 500 {y + 14} 860 {y - 4}" fill="none" stroke="{GRAIN_L}" stroke-width="4"/>' for y in (395, 420, 445))
s5_art = (f'<rect x="100" y="330" width="760" height="140" rx="12" fill="{WOOD_L}" stroke="#3B2412" stroke-width="6"/>{wgrain}'
          f'<rect x="103" y="333" width="754" height="40" fill="#1B1310"/>{crackle}'
          f'<rect id="s5-ember" x="103" y="370" width="754" height="6" fill="#F97316"/>'
          + vanilla('s5-i1', 210, 215, 0.9) + caramel('s5-i2', 400, 205) + smoke('s5-i3', 590, 215) + anise('s5-i4', 770, 210))
L5 = [('그을린 미국산 오크가\n바닐라·캐러멜 향을 녹여 줘요.', 0.15, 3.5), ('여기에 은은한 스모크와\n톡 쏘는 스파이스까지.', 3.5, None)]
out['s5'] = scene('s5',
    tag('s5-tag', '버번 캐스크', 't-amber') + art('s5', s5_art)
    + chip('s5-c0', '속을 그을린 새 미국산 오크', AX + 480, AY + 512, 'c-cream')
    + chip('s5-l1', '바닐라', AX + 210, AY + 292, 'c-amber') + chip('s5-l2', '캐러멜', AX + 400, AY + 292, 'c-amber')
    + chip('s5-l3', '스모크', AX + 590, AY + 292, 'c-amber') + chip('s5-l4', '스파이스', AX + 770, AY + 292, 'c-amber')
    + caps('s5', L5),
    '\n    '.join([
        art_in('s5'), 'tl.set("#s5-tag", { opacity: 1 }, 0);',
        'tl.set(["#s5-i1", "#s5-i2", "#s5-i3", "#s5-i4"], { opacity: 0 }, 0);',
        'tl.fromTo("#s5-ember", { opacity: 0.3 }, { opacity: 1, duration: 0.4, ease: "power1.inOut", yoyo: true, repeat: 7 }, 0.2);',
        pop('#s5-c0', 0.3),
        rise('#s5-i1', 0.7), pop('#s5-l1', 0.95), rise('#s5-i2', 1.3), pop('#s5-l2', 1.55),
        rise('#s5-i3', 3.7), 'tl.fromTo(".s5-i3-w", { attr: { "stroke-dashoffset": 1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.9, ease: "power2.out", stagger: 0.12 }, 3.7);',
        pop('#s5-l3', 3.95), rise('#s5-i4', 4.3), pop('#s5-l4', 4.55),
        'tl.fromTo("#s5-i4", { rotation: -40 }, { rotation: 0, duration: 0.6, ease: "expo.out", transformOrigin: "50% 50%" }, 4.3);',
        caps_js('s5', L5),
        art_out('s5', 7.0, ['#s5-tag', '#s5-c0', '#s5-l1', '#s5-l2', '#s5-l3', '#s5-l4', '#s5-cap1', '#s5-src']),
    ]),
    src=SRC_BOTH)

# s6 셰리 캐스크 — 셰리를 머금었던 유럽산 오크통
L6 = [('셰리 캐스크는 강화 와인 셰리를\n머금었던 유럽산 오크통이에요.', 0.15, None)]
s6_art = (barrel('s6-b', 560, 260, 1.0, WOOD_D, GRAIN_D, tint=True)
          + bottle('s6-bt', 120, 60, 1.0)
          + '<path id="s6-st" d="M700 192 C704 215 692 240 680 262" fill="none" stroke="#7A1F2B" stroke-width="12" stroke-linecap="round" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1"/>')
out['s6'] = scene('s6',
    tag('s6-tag', '셰리 캐스크', 't-maho') + art('s6', s6_art)
    + chip('s6-c1', '강화 와인 셰리', AX + 180, AY + 470, 'c-cream')
    + chip('s6-c2', '유럽산 오크통', AX + 400, AY + 420, 'c-maho')
    + chip('s6-c3', '셰리가 스며듦', AX + 680, AY + 410, 'c-yel')
    + caps('s6', L6),
    '\n    '.join([
        art_in('s6'), pop('#s6-tag', 0.05),
        'tl.fromTo("#s6-b", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.1);',
        pop('#s6-c2', 0.5), pop('#s6-c1', 0.6),
        'tl.to("#s6-c1", { opacity: 0, duration: 0.15 }, 2.2);',
        'tl.fromTo("#s6-bt", { x: 0, y: 0, rotation: 0 }, { x: 358, y: -102, rotation: 108, duration: 0.9, ease: "power2.inOut", transformOrigin: "50% 50%" }, 1.1);',
        'tl.fromTo("#s6-st", { attr: { "stroke-dashoffset": 1.1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.25, ease: "power2.out" }, 1.95);',
        'tl.fromTo("#s6-b-tr", { attr: { y: 300, height: 0 } }, { attr: { y: 0, height: 300 }, duration: 1.8, ease: "power1.inOut" }, 2.1);',
        pop('#s6-c3', 2.6),
        'tl.to(["#s6-bt", "#s6-st"], { opacity: 0, duration: 0.3, ease: "power2.in" }, 3.9);',
        caps_js('s6', L6),
        art_out('s6', 6.0, ['#s6-c2', '#s6-c3', '#s6-cap0']),
    ]))

# s7 셰리 캐스크의 맛 — 잔이 짙어지며 어두운 과일이 떠오른다
s7_art = (barrel('s7-b', 80, 170, 1.0, WOOD_D, GRAIN_D)
          + arrow('s7-ar', 345, 320, 445, 320)
          + glass('s7-g', 470, 80, 1.35, CLEAR, 0.45)
          + cherries('s7-f1', 445, 110, 1.0) + grapes('s7-f2', 840, 150, 1.05) + plum('s7-f3', 850, 360, 0.95))
L7 = [('그래서 깊고 어두운 과일 향과\n풍부함을 끌어내요.', 0.15, None)]
out['s7'] = scene('s7',
    tag('s7-tag', '셰리 캐스크', 't-maho') + art('s7', s7_art)
    + chip('s7-c1', '어두운 과일 향', AX + 820, AY + 520, 'c-maho') + chip('s7-c2', '풍부함', AX + 605, AY + 520, 'c-yel')
    + caps('s7', L7),
    '\n    '.join([
        art_in('s7'), 'tl.set("#s7-tag", { opacity: 1 }, 0);',
        'tl.set(["#s7-f1", "#s7-f2", "#s7-f3"], { opacity: 0 }, 0);',
        'tl.fromTo("#s7-ar", { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, 0.3);',
        f'tl.fromTo("#s7-g-liq", {{ attr: {{ fill: "{CLEAR}" }} }}, {{ attr: {{ fill: "{MAHO}" }}, duration: 1.4, ease: "power1.inOut" }}, 0.5);',
        pop('#s7-f2', 1.6, -6), pop('#s7-f3', 1.9, 6), pop('#s7-f1', 2.2, -4), pop('#s7-c1', 2.5), pop('#s7-c2', 2.9),
        caps_js('s7', L7),
        art_out('s7', 5.5, ['#s7-tag', '#s7-c1', '#s7-c2', '#s7-cap0', '#s7-src']),
    ]),
    src=SRC_BOTH)

# s8 귀하고 비싸다
grid = ''.join(barrel(f's8-g{k}', 70 + (k % 3) * 130, 110 + (k // 3) * 170, 0.5) for k in range(6))
s8_art = (grid + ''
          + barrel('s8-sb', 580, 115, 1.15, WOOD_D, GRAIN_D))
L8 = [('셰리 캐스크는 구하기 어렵고\n값도 훨씬 비싸요.', 0.15, None)]
out['s8'] = scene('s8',
    tag('s8-tag', '현실', 't-yel') + art('s8', s8_art)
    + chip('s8-c1', '버번 캐스크 · 흔해요', AX + 265, AY + 490, 'c-amber')
    + chip('s8-c2', '셰리 캐스크 · 귀해요', AX + 718, AY + 490, 'c-maho')
    + chip('s8-p1', '₩ 저렴', AX + 265, AY + 62, 'c-cream') + chip('s8-p2', '₩₩₩ 비쌈', AX + 718, AY + 62, 'c-tom')
    + caps('s8', L8),
    '\n    '.join([
        art_in('s8'), pop('#s8-tag', 0.05),
        *[pop(f'#s8-g{k}', 0.1 + k * 0.06) for k in range(6)],
        'tl.fromTo("#s8-sb", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.5);',
        pop('#s8-c1', 0.7), pop('#s8-c2', 0.9), pop('#s8-p1', 1.6, -4), pop('#s8-p2', 2.1, 4),
        caps_js('s8', L8),
        art_out('s8', 4.5, ['#s8-tag', '#s8-c1', '#s8-c2', '#s8-p1', '#s8-p2', '#s8-cap0']),
    ]))

# s9 블렌더의 두 가지 방법
s9_art = (glass('s9-a1', 280, 70, 0.75, AMBER, 0.45)
          + f'<text id="s9-plus" x="480" y="215" font-family="Wanted Sans" font-weight="800" font-size="72" fill="{CREAM}" text-anchor="middle">+</text>'
          + glass('s9-a2', 520, 135, 0.45, MAHO, 0.45) + arrow('s9-ar1', 625, 195, 690, 195)
          + glass('s9-a3', 710, 70, 0.75, '#C0612A', 0.5)
          + glass('s9-b1', 280, 330, 0.75, AMBER, 0.45) + arrow('s9-ar2', 445, 450, 505, 450)
          + barrel('s9-bb', 520, 360, 0.6, WOOD_D, GRAIN_D) + arrow('s9-ar3', 675, 450, 730, 450)
          + glass('s9-b2', 745, 330, 0.75, '#A8461B', 0.5))
L9 = [('그래서 조금만 섞거나,\n마지막에 셰리 통에서 더 익혀요.', 0.15, None)]
out['s9'] = scene('s9',
    tag('s9-tag', '블렌더의 방법', 't-yel') + art('s9', s9_art)
    + chip('s9-l1', '① 섞기', AX + 130, AY + 195, 'c-cream') + chip('s9-l2', '② 추가 숙성', AX + 130, AY + 450, 'c-cream')
    + caps('s9', L9),
    '\n    '.join([
        art_in('s9'), pop('#s9-tag', 0.05),
        'tl.set(["#s9-a1","#s9-plus","#s9-a2","#s9-ar1","#s9-a3","#s9-b1","#s9-ar2","#s9-bb","#s9-ar3","#s9-b2"], { opacity: 0 }, 0);',
        pop('#s9-l1', 0.2), pop('#s9-a1', 0.35), pop('#s9-plus', 0.6), pop('#s9-a2', 0.8),
        'tl.fromTo("#s9-ar1", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 1.1);', pop('#s9-a3', 1.3),
        pop('#s9-l2', 2.4), pop('#s9-b1', 2.55),
        'tl.fromTo("#s9-ar2", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 2.8);', pop('#s9-bb', 3.0),
        'tl.fromTo("#s9-ar3", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 3.3);', pop('#s9-b2', 3.5),
        caps_js('s9', L9),
        art_out('s9', 5.5, ['#s9-tag', '#s9-l1', '#s9-l2', '#s9-cap0']),
    ]))

# s10 한눈에 보기 — 한 줄씩 쌓이는 요약판
s10_art = (f'<rect x="20" y="20" width="920" height="560" rx="24" fill="{CREAM}" stroke="{INK}" stroke-width="5"/>'
           + barrel('s10-b1', 90, 150, 0.42) + arrow('s10-ar1', 220, 212, 290, 212, NAVY)
           + vanilla('s10-i1', 390, 215, 0.6) + caramel('s10-i2', 560, 210, 0.65) + smoke('s10-i3', 730, 230, 0.55)
           + barrel('s10-b2', 90, 350, 0.42, WOOD_D, GRAIN_D) + arrow('s10-ar2', 220, 412, 290, 412, NAVY)
           + grapes('s10-i4', 420, 410, 0.85) + glass('s10-i5', 645, 335, 0.45, MAHO, 0.5, NAVY))
out['s10'] = scene('s10',
    art('s10', s10_art)
    + chip('s10-n1', '버번', AX + 140, AY + 302, 'c-amber') + chip('s10-n2', '셰리', AX + 140, AY + 502, 'c-maho')
    + chip('s10-t1', '바닐라', AX + 390, AY + 302, 'c-cream') + chip('s10-t2', '캐러멜', AX + 560, AY + 302, 'c-cream') + chip('s10-t3', '스모크', AX + 730, AY + 302, 'c-cream')
    + chip('s10-t4', '어두운 과일', AX + 420, AY + 502, 'c-cream') + chip('s10-t5', '풍부함', AX + 690, AY + 502, 'c-cream')
    + caps('s10', [('버번 캐스크는 바닐라·캐러멜,\n셰리 캐스크는 어두운 과일.', 0.15, None)]),
    '\n    '.join([
        art_in('s10'),
        'tl.set(["#s10-b1","#s10-ar1","#s10-i1","#s10-i2","#s10-i3","#s10-b2","#s10-ar2","#s10-i4","#s10-i5"], { opacity: 0 }, 0);',
        pop('#s10-b1', 0.4), pop('#s10-n1', 0.5),
        'tl.fromTo("#s10-ar1", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 0.7);',
        pop('#s10-i1', 0.9), pop('#s10-t1', 1.0), pop('#s10-i2', 1.15), pop('#s10-t2', 1.25), pop('#s10-i3', 1.4), pop('#s10-t3', 1.5),
        pop('#s10-b2', 2.3), pop('#s10-n2', 2.4),
        'tl.fromTo("#s10-ar2", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 2.6);',
        pop('#s10-i4', 2.8), pop('#s10-t4', 2.9), pop('#s10-i5', 3.1), pop('#s10-t5', 3.2),
        caps_js('s10', [('', 0.15, None)]),
        art_out('s10', 6.0, ['#s10-n1','#s10-n2','#s10-t1','#s10-t2','#s10-t3','#s10-t4','#s10-t5','#s10-cap0','#s10-src']),
    ]),
    src=SRC_BOTH)

# s11 마무리 한 줄 — 첫 장면과 같은 잔으로 돌아와 반복 재생에 이어진다
L11 = [("라벨에 '셰리 캐스크'가 보이면\n진한 과일 향을 떠올려 보세요.", 0.15, None)]
out['s11'] = scene('s11',
    art('s11', glass('s11-gA', 165, 50, 1.45, AMBER, 0.42) + glass('s11-gB', 505, 50, 1.45, MAHO, 0.42))
    + chip('s11-nA', '버번 캐스크', AX + 310, AY + 495, 'c-amber') + chip('s11-nB', '셰리 캐스크', AX + 650, AY + 495, 'c-maho')
    + chip('s11-aA', '바닐라·캐러멜', AX + 230, AY + 32, 'c-cream') + chip('s11-aB', '어두운 과일', AX + 760, AY + 32, 'c-cream')
    + caps('s11', L11),
    '\n    '.join([
        art_in('s11'),
        pop('#s11-aA', 0.4, -4), pop('#s11-aB', 0.7, 4),
        caps_js('s11', L11),
        'tl.to(["#s11-aA", "#s11-aB"], { opacity: 0, filter: "blur(6px)", duration: 0.2, ease: "power2.in" }, 3.6);',
    ]))

for sid, html in out.items():
    (comp / f'{sid}.html').write_text(html, encoding='utf-8')

# ---------- 고정 틀: 남색 바 + 한국어 제목 + 카운터 뒤 째리 + 말풍선 ----------
SERIES, EPISODE = '째리의 술 수업', '1교시'
TITLE = '<span style="color:#F0A93B">버번</span> <span class="vs">vs</span> <span style="color:#F2836B">셰리</span> 캐스크'
HOPS = [0.25] + [STARTS[sid] + 0.15 for sid, _ in SCENES[1:]] + [STARTS['s4'] + 4.4, STARTS['s5'] + 3.5]
BIG_HOP = STARTS['s3'] + 3.4  # 도장 찍힐 때 째리가 놀란다
hop_js = '\n    '.join(
    f'tl.to("#fr-jjeri", {{ keyframes: [{{ y: -22, duration: 0.14, ease: "power2.out" }}, {{ y: 0, duration: 0.2, ease: "power2.in" }}] }}, {t:.2f});'
    for t in sorted(HOPS))
counter_grain = ''.join(f'<path d="M0 {y} C300 {y - 10} 700 {y + 12} 1080 {y - 4}" fill="none" stroke="#6E3A1C" stroke-width="5"/>' for y in (90, 170, 260, 360, 470))
frame = f"""<template>
  <style>
    {FONTS}
    #root {{ position: absolute; inset: 0; overflow: hidden; font-family: 'Pretendard'; color: {CREAM};
             background: radial-gradient(circle at 50% 38%, #2E3D62 0%, {NAVY} 58%, #172036 100%); }}
    #fr-badgebox {{ position: absolute; left: 0; right: 0; top: 184px; text-align: center; }}
    #fr-badge {{ display: inline-block; font-weight: 700; font-size: 32px; color: #fff; background: {TOMATO}; border-radius: 999px; padding: 6px 26px; }}
    #fr-title {{ position: absolute; left: 0; right: 0; top: 248px; text-align: center; font-family: 'Wanted Sans'; font-weight: 800; font-size: 84px; letter-spacing: -0.035em; color: {CREAM}; }}
    #fr-title .vs {{ font-size: 56px; color: #9AA6BF; }}
    #fr-jjeri {{ position: absolute; left: 34px; top: 1076px; width: 218px; }}
    #fr-bubble {{ position: absolute; left: 270px; top: 1034px; width: 770px; height: 204px; background: {CREAM}; border: 4px solid {INK}; border-radius: 30px; }}
    #fr-tail {{ position: absolute; left: 232px; top: 1112px; width: 44px; height: 52px; }}
    #fr-counter {{ position: absolute; left: 0; top: 1330px; width: 1080px; height: 590px; }}
    #fr-handle {{ position: absolute; left: 0; right: 0; top: 1376px; text-align: center; font-weight: 700; font-size: 32px; color: #F6D9B8; opacity: 0.85; }}
  </style>
  <div id="root" data-composition-id="frame" data-width="1080" data-height="1920">
    <div id="fr-badgebox"><span id="fr-badge">{SERIES} · {EPISODE}</span></div>
    <div id="fr-title">{TITLE}</div>
    <img id="fr-jjeri" src="assets/img/jjeri.svg" alt="째리">
    <svg id="fr-counter" viewBox="0 0 1080 590" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="1080" height="590" fill="{WOOD_D}"/>
      <rect x="0" y="0" width="1080" height="30" fill="#A8693A"/><rect x="0" y="30" width="1080" height="8" fill="#5A2E14"/>
      {counter_grain}
    </svg>
    <div id="fr-handle">술째리고 &nbsp;@sooljjerigo</div>
    <div id="fr-bubble"></div>
    <svg id="fr-tail" viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg">
      <polygon points="44,4 4,26 44,48" fill="{CREAM}"/>
      <polyline points="40,6 4,26 40,46" fill="none" stroke="{INK}" stroke-width="4" stroke-linejoin="round"/>
    </svg>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.set("#fr-jjeri", {{ y: 0, rotation: 0 }}, 0);
    {hop_js}
    tl.to("#fr-jjeri", {{ keyframes: [{{ rotation: -10, duration: 0.12, ease: "power2.out" }}, {{ rotation: 0, duration: 0.5, ease: "back.out(2)" }}], transformOrigin: "50% 100%" }}, {BIG_HOP:.2f});
    tl.set({{}}, {{}}, {TOTAL});
    window.__timelines["frame"] = tl;
  </script>
</template>
"""
(comp / 'frame.html').write_text(frame, encoding='utf-8')

# ---------- 소리 ----------
S = STARTS
SFX = [  # (파일, 화면 사건 시각) — 실제 배치 시각은 파일의 첫 피크에 맞춰 아래 PEAK 만큼 앞당긴다
    ('pop', S['s1'] + 1.0), ('click-soft', S['s1'] + 1.5),
    ('impact-bass-1', S['s3'] + 3.4 + 0.28),
    ('whoosh', S['s4']), ('pop', S['s4'] + 2.85), ('click-soft', S['s4'] + 4.6),
    ('pop', S['s5'] + 0.7), ('click-soft', S['s5'] + 1.3), ('pop', S['s5'] + 3.7), ('click-soft', S['s5'] + 4.3),
    ('whoosh-short', S['s6']),
    ('pop', S['s7'] + 1.6), ('click-soft', S['s7'] + 2.2),
    ('pop', S['s8'] + 1.6), ('pop', S['s8'] + 2.1),
    ('whoosh', S['s10']),
    ('click-soft', S['s11'] + 0.4), ('pop', S['s11'] + 0.7),
]
PEAK = {'pop': 0.12, 'click-soft': 0.073, 'impact-bass-1': 0.073, 'whoosh': 0.162, 'whoosh-short': 0.162}
LEN = {'pop': 0.72, 'click-soft': 0.36, 'impact-bass-1': 2.1, 'whoosh': 0.57, 'whoosh-short': 0.57}
VOL = {'pop': 0.85, 'click-soft': 0.95, 'impact-bass-1': 0.6, 'whoosh': 0.75, 'whoosh-short': 0.75}

hosts = '\n      '.join(
    f'<div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" data-start="{S[sid]}" data-duration="{d}" '
    f'data-track-index="1" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:2"></div>'
    for sid, d in SCENES)
audio = '\n      '.join(
    f'<audio id="sfx{k:02d}" class="clip" src="assets/sfx/{f}.mp3" data-start="{max(0, round(t - PEAK[f] + 1 / 30, 3))}" data-duration="{LEN[f]}" data-track-index="{10 + k}" data-volume="{VOL[f]}"></audio>'
    for k, (f, t) in enumerate(SFX))
index = f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: {BG}; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL}" data-width="1080" data-height="1920">
      <div id="frame" data-composition-id="frame" data-composition-src="compositions/frame.html" data-start="0" data-duration="{TOTAL}" data-track-index="0" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:1"></div>
      {hosts}
      <audio id="bgm" class="clip" src="assets/bgm/bed.mp3" data-start="0" data-duration="{TOTAL}" data-media-start="0" data-track-index="9" data-volume="0.62" data-fade-in="0.3" data-fade-out="2.0"></audio>
      {audio}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""
(root / 'index.html').write_text(index, encoding='utf-8')
print('scenes', len(SCENES), 'total', TOTAL)

# ===================== v3: 내레이션이 시계 =====================
import json, re, sys
sys.path.insert(0, str(Path(__file__).parent))
from script import BEATS

VO = json.loads((root / 'assets' / 'vo' / 'vo.json').read_text(encoding='utf-8'))
GAP = 0.27                                    # 문장 사이 숨
LEAD = {'s1': 0.2}                            # 장면 첫 문장 전 여백(기본 0.15)
TAIL = {'s11': 1.3, 's12': 2.0}               # 장면 끝 여백(기본 0.1) — 마지막은 반복 재생 전 머묾
MIN = {'s6': 4.6, 's7': 4.3, 's8': 3.8, 's9': 4.4}
ORDER = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10', 's11', 's12']

BT, CAP, SCN = {}, {}, {}                     # 장면별 문장 시작(지역), 자막 목록, 길이
for sid in ORDER:
    t = LEAD.get(sid, 0.15)
    BT[sid], CAP[sid] = [], []
    for v, (bs, text) in zip(VO, BEATS):
        if bs != sid:
            continue
        slot = round(v['end'] - v['head'] + GAP, 3)
        BT[sid].append(round(t, 3))
        CAP[sid].append([text, round(t, 3), None, v, slot])
        t += slot
    for a, b in zip(CAP[sid], CAP[sid][1:]):
        a[2] = b[1]
    SCN[sid] = round(max(MIN.get(sid, 0), t + TAIL.get(sid, 0.1)), 2)
SCENES = [(s, SCN[s]) for s in ORDER]
STARTS, _t = {}, 0.0
for s, d in SCENES:
    STARTS[s] = round(_t, 2)
    _t += d
TOTAL = round(_t, 2)

KW = [('술째리고', '#C2410C'), ('버번', '#B45309'), ('셰리', '#A61B1B')]


def color_kw(text):
    for w, c in KW:
        text = re.sub(w, f'<b style="color:{c}">{w}</b>', text)
    return text.replace('\n', '<br>')


def caps(sid):
    html = ''.join(f'<div id="{sid}-cap{k}" class="captext"><span>{color_kw(c[0])}</span></div>' for k, c in enumerate(CAP[sid]))
    return f'<div class="capbox">{html}</div>'


def caps_js(sid):
    js = []
    for k, (t, a, b, v, slot) in enumerate(CAP[sid]):
        e = f'#{sid}-cap{k}'
        if sid == 's1' and k == 0:
            js.append(f'tl.set("{e}", {{ opacity: 1 }}, 0);')  # 썸네일에 자막이 이미 있다
        else:
            js.append(f'tl.fromTo("{e}", {{ opacity: 0, scale: 0.96, filter: "blur(8px)" }}, {{ opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }}, {a});')
        if b is not None:
            js.append(f'tl.to("{e}", {{ opacity: 0, filter: "blur(6px)", duration: 0.12, ease: "power2.in" }}, {round(b - 0.12, 3)});')
    return '\n    '.join(js)


def caps_ids(sid):
    return [f'#{sid}-cap{k}' for k in range(len(CAP[sid]))]


CSS = CSS.replace("font-weight: 700; font-size: 38px; line-height: 1.4;", "font-weight: 800; font-size: 42px; line-height: 1.42;")
CSS = CSS.replace(FONTS, FONTS + "\n    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-ExtraBold.woff2'); font-weight: 800; }")
CSS += """
    .captext b { font-weight: 800; }
    .search { position: absolute; left: 400px; top: 640px; width: 620px; height: 104px; background: #fff; border: 6px solid #C2410C; border-radius: 52px; display: flex; align-items: center; padding: 0 30px; gap: 18px; }
    .search .q { font-weight: 800; font-size: 44px; color: #1F2A44; letter-spacing: -0.02em; }
    .search .q span { opacity: 0; }
    .search .cur { width: 4px; height: 48px; background: #C2410C; }
    .search .hint { position: absolute; left: 0; right: 0; top: -54px; text-align: center; font-weight: 700; font-size: 32px; color: #F6D9B8; }
    .cbox { position: absolute; left: 170px; width: 740px; top: 880px; height: 120px; background: #fff; border: 4px solid #0E1525; border-radius: 22px; padding: 14px 28px; }
    .cbox .lab { font-weight: 600; font-size: 30px; color: #6B7583; }
    .cbox .q { font-weight: 800; font-size: 44px; color: #1F2A44; }
    .cbox .q span { opacity: 0; }
"""


# 인스타 릴스 안전 영역(위 269 · 아래 1248 · 좌우 65~1015, HyperFrames 0.9.72 기준)에 맞춰 그림 칸 전체를 95% 로 줄여 30px 내린다.
# 자막·출처는 줄이지 않는다 — 장면 본문에서 자막 상자 앞까지만 .stage 로 감싼다.
CSS += """
    .stage { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; transform-origin: 540px 410px; transform: translate(0px, 30px) scale(0.95); }
"""
CSS = CSS.replace(".capbox { position: absolute; left: 296px; width: 720px; top: 1044px; height: 184px; }",
                  ".capbox { position: absolute; left: 296px; width: 720px; top: 1052px; height: 176px; }")
CSS = CSS.replace(".src { position: absolute; left: 270px; width: 770px; top: 1248px; text-align: right; }",
                  ".src { position: absolute; left: 84px; width: 912px; top: 996px; text-align: right; }")
assert 'top: 1052px' in CSS and 'top: 996px' in CSS
_scene_v2 = scene


def scene(sid, body, js, extra_css='', src=None):
    i = body.find('<div class="capbox">')
    stage, rest = (body[:i], body[i:]) if i >= 0 else (body, '')
    return _scene_v2(sid, f'<div class="stage">{stage}</div>' + rest, js, extra_css, src)


def type_js(prefix, text, t0, step=0.12):
    return '\n    '.join(f'tl.set("#{prefix}{k}", {{ opacity: 1 }}, {round(t0 + k * step, 3)});' for k in range(len(text)))


def type_spans(prefix, text):
    return ''.join(f'<span id="{prefix}{k}">{"&nbsp;" if ch == " " else ch}</span>' for k, ch in enumerate(text))


SRC_WA = 'Whisky Advocate'
SRC_BOTH = 'Whisky Advocate · Frontiers in Chemistry(2018)'
out = {}
B = BT

# s1 질문 — 프레임 0 = 썸네일(잔·이름·자막이 이미 떠 있다)
D = SCN['s1']
out['s1'] = scene('s1',
    art('s1', glass('s1-gA', 165, 50, 1.45, AMBER, 0.42) + glass('s1-gB', 505, 50, 1.45, MAHO, 0.42))
    + chip('s1-nA', '버번 캐스크', AX + 310, AY + 495, 'c-amber') + chip('s1-nB', '셰리 캐스크', AX + 650, AY + 495, 'c-maho')
    + chip('s1-qA', '바닐라?', AX + 200, AY + 32, 'c-cream') + chip('s1-qB', '진한 과일?', AX + 770, AY + 32, 'c-cream')
    + caps('s1'),
    '\n    '.join([
        caps_js('s1'),
        pop('#s1-qA', 1.0, -4), pop('#s1-qB', 1.6, 4),
        'tl.fromTo("#s1-gA", { rotation: 0 }, { rotation: -4, duration: 0.3, ease: "power2.out", transformOrigin: "50% 100%" }, 1.0);',
        'tl.fromTo("#s1-gB", { rotation: 0 }, { rotation: 4, duration: 0.3, ease: "power2.out", transformOrigin: "50% 100%" }, 1.6);',
        art_out('s1', D, ['#s1-qA', '#s1-qB', '#s1-nA', '#s1-nB'] + caps_ids('s1')),
    ]))

# s2 흔한 생각
D = SCN['s2']
out['s2'] = scene('s2',
    tag('s2-tag', '흔히 하는 생각', 't-grey')
    + art('s2', glass('s2-g', 110, 140, 1.15, CLEAR, 0.45) + arrow('s2-ar', 370, 330, 480, 330)
          + barrel('s2-b', 520, 70, 1.35)
          + f'<g transform="translate(895 150)"><text id="s2-q" font-family="Wanted Sans" font-weight="800" font-size="140" fill="{TOMATO}" text-anchor="middle" x="0" y="40">?</text></g>')
    + chip('s2-c1', '투명한 원액', AX + 225, AY + 500, 'c-cream') + chip('s2-c2', '그냥 그릇?', AX + 682, AY + 520, 'c-yel')
    + caps('s2'),
    '\n    '.join([
        art_in('s2'), pop('#s2-tag', 0.05),
        'tl.fromTo("#s2-g", { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.5, ease: "expo.out" }, 0.1);',
        'tl.fromTo("#s2-ar", { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, 0.6);',
        'tl.fromTo("#s2-b", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.55, ease: "back.out(1.4)" }, 0.3);',
        pop('#s2-c1', 0.9), pop('#s2-q', 2.0, 8), pop('#s2-c2', 2.4),
        caps_js('s2'),
        art_out('s2', D, ['#s2-tag', '#s2-c1', '#s2-c2'] + caps_ids('s2')),
    ]))

# s3 실제로는 — 통 단면 + 도장(둘째 문장 "티백처럼" 에 맞춤)
D = SCN['s3']
STAMP_T = round(B['s3'][1] + 0.5, 2)
js3 = [art_in('s3'), pop('#s3-tag', 0.05), pop('#s3-c1', 0.4), pop('#s3-c2', 0.6),
       f'tl.fromTo("#s3-liq", {{ attr: {{ fill: "{CLEAR}" }} }}, {{ attr: {{ fill: "#E39B2F" }}, duration: 2.6, ease: "power1.inOut" }}, {B["s3"][1] - 0.6});']
for i, x, y, dx, t in parts:
    t = round(B['s3'][1] - 0.8 + t, 2)
    js3.append(f'tl.fromTo("#{i}", {{ x: 0, opacity: 0 }}, {{ x: {dx}, opacity: 1, duration: 0.5, ease: "power2.out" }}, {t});')
    js3.append(f'tl.to("#{i}", {{ opacity: 0, duration: 0.6, ease: "power1.in" }}, {t + 0.5});')
js3 += [f'tl.fromTo("#s3-stamp", {{ scale: 2.2, opacity: 0, rotation: -14 }}, {{ scale: 1, opacity: 1, rotation: -8, duration: 0.28, ease: "power4.in" }}, {STAMP_T});',
        caps_js('s3'), art_out('s3', D, ['#s3-tag', '#s3-c1', '#s3-c2', '#s3-stamp', '#s3-src'] + caps_ids('s3'))]
out['s3'] = scene('s3',
    tag('s3-tag', '실제로는', 't-tom') + art('s3', s3_art)
    + chip('s3-c1', '오크 나무', AX + 120, AY + 160, 'c-cream') + chip('s3-c2', '원액', AX + 480, AY + 60, 'c-cream')
    + '<div class="stampbox"><span id="s3-stamp">오크통 = 티백</span></div>'
    + caps('s3'),
    '\n    '.join(js3),
    extra_css=f"""
    .stampbox {{ position: absolute; left: 140px; width: 800px; top: 670px; height: 160px; display: flex; align-items: center; justify-content: center; }}
    #s3-stamp {{ display: inline-block; font-family: 'Wanted Sans'; font-weight: 800; font-size: 76px; color: {TOMATO}; background: rgba(255,248,238,0.94); border: 7px solid {TOMATO}; border-radius: 16px; padding: 4px 30px; }}""",
    src=SRC_WA)

# s4 버번 통의 출신 — 문장 1: 새 통 / 2: 스코틀랜드로 / 3: 대부분이 이 통
D = SCN['s4']; b = B['s4']
out['s4'] = scene('s4',
    art('s4', s4_art)
    + chip('s4-c1', '미국 · 새 통만', AX + 190, AY + 470, 'c-cream')
    + chip('s4-c2', '스코틀랜드 · 한 번 쓴 통', AX + 580, AY + 470, 'c-yel')
    + chip('s4-c3', '구하기 쉽고 비교적 저렴', AX + 430, AY + 40, 'c-amber')
    + caps('s4'),
    '\n    '.join([
        art_in('s4'),
        'tl.fromTo("#s4-b1", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.15);',
        pop('#s4-c1', 0.7),
        f'tl.fromTo("#s4-arc", {{ opacity: 0 }}, {{ opacity: 0.9, duration: 0.3, ease: "power2.out" }}, {b[1] - 0.1});',
        f'tl.to("#s4-c1", {{ opacity: 0, duration: 0.15, ease: "power2.in" }}, {b[1]});',
        f'tl.fromTo("#s4-b1", {{ x: 0 }}, {{ x: 390, duration: 1.0, ease: "power2.inOut" }}, {b[1] + 0.1});',
        f'tl.to("#s4-b1", {{ keyframes: [{{ y: -110, duration: 0.5, ease: "power2.out" }}, {{ y: 0, duration: 0.5, ease: "power2.in" }}] }}, {b[1] + 0.1});',
        f'tl.to("#s4-arc", {{ opacity: 0, duration: 0.2 }}, {b[1] + 1.1});',
        pop('#s4-c2', b[1] + 1.15),
        pop('#s4-e1', b[2] + 0.2), pop('#s4-e2', b[2] + 0.4), pop('#s4-e3', b[2] + 0.6), pop('#s4-c3', b[2] + 1.0),
        caps_js('s4'),
        art_out('s4', D, ['#s4-c2', '#s4-c3', '#s4-src'] + caps_ids('s4')),
    ]),
    src='Whisky Advocate · 미국 버번 규정')

# s5 버번 맛
D = SCN['s5']; b = B['s5']
out['s5'] = scene('s5',
    art('s5', s5_art)
    + chip('s5-c0', '속을 그을린 새 미국산 오크', AX + 480, AY + 512, 'c-cream')
    + chip('s5-l1', '바닐라', AX + 210, AY + 292, 'c-amber') + chip('s5-l2', '캐러멜', AX + 400, AY + 292, 'c-amber')
    + chip('s5-l3', '스모크', AX + 590, AY + 292, 'c-amber') + chip('s5-l4', '스파이스', AX + 770, AY + 292, 'c-amber')
    + caps('s5'),
    '\n    '.join([
        art_in('s5'),
        'tl.set(["#s5-i1", "#s5-i2", "#s5-i3", "#s5-i4"], { opacity: 0 }, 0);',
        'tl.fromTo("#s5-ember", { opacity: 0.3 }, { opacity: 1, duration: 0.4, ease: "power1.inOut", yoyo: true, repeat: 7 }, 0.2);',
        pop('#s5-c0', 0.3),
        rise('#s5-i1', 1.6), pop('#s5-l1', 1.85), rise('#s5-i2', 2.4), pop('#s5-l2', 2.65),
        rise('#s5-i3', b[1] + 1.0), f'tl.fromTo(".s5-i3-w", {{ attr: {{ "stroke-dashoffset": 1 }} }}, {{ attr: {{ "stroke-dashoffset": 0 }}, duration: 0.9, ease: "power2.out", stagger: 0.12 }}, {b[1] + 1.0});',
        pop('#s5-l3', b[1] + 1.25), rise('#s5-i4', b[1] + 2.0), pop('#s5-l4', b[1] + 2.25),
        f'tl.fromTo("#s5-i4", {{ rotation: -40 }}, {{ rotation: 0, duration: 0.6, ease: "expo.out", transformOrigin: "50% 50%" }}, {b[1] + 2.0});',
        caps_js('s5'),
        art_out('s5', D, ['#s5-c0', '#s5-l1', '#s5-l2', '#s5-l3', '#s5-l4', '#s5-src'] + caps_ids('s5')),
    ]),
    src=SRC_BOTH)

# s6 셰리 통
D = SCN['s6']
out['s6'] = scene('s6',
    art('s6', s6_art)
    + chip('s6-c1', '강화 와인 셰리', AX + 180, AY + 470, 'c-cream')
    + chip('s6-c2', '유럽산 오크통', AX + 400, AY + 420, 'c-maho')
    + chip('s6-c3', '셰리가 스며듦', AX + 680, AY + 410, 'c-yel')
    + caps('s6'),
    '\n    '.join([
        art_in('s6'),
        'tl.fromTo("#s6-b", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.1);',
        pop('#s6-c1', 0.4), pop('#s6-c2', 0.6),
        'tl.to("#s6-c1", { opacity: 0, duration: 0.15 }, 1.9);',
        'tl.fromTo("#s6-bt", { x: 0, y: 0, rotation: 0 }, { x: 358, y: -102, rotation: 108, duration: 0.9, ease: "power2.inOut", transformOrigin: "50% 50%" }, 1.0);',
        'tl.fromTo("#s6-st", { attr: { "stroke-dashoffset": 1.1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.25, ease: "power2.out" }, 1.85);',
        'tl.fromTo("#s6-b-tr", { attr: { y: 300, height: 0 } }, { attr: { y: 0, height: 300 }, duration: 1.6, ease: "power1.inOut" }, 2.0);',
        pop('#s6-c3', 2.5),
        caps_js('s6'),
        art_out('s6', D, ['#s6-c2', '#s6-c3'] + caps_ids('s6')),
    ]))

# s7 셰리 맛
D = SCN['s7']
out['s7'] = scene('s7',
    art('s7', s7_art)
    + chip('s7-c1', '어두운 과일 향', AX + 820, AY + 520, 'c-maho') + chip('s7-c2', '풍부함', AX + 605, AY + 520, 'c-yel')
    + caps('s7'),
    '\n    '.join([
        art_in('s7'),
        'tl.set(["#s7-f1", "#s7-f2", "#s7-f3"], { opacity: 0 }, 0);',
        'tl.fromTo("#s7-ar", { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, 0.3);',
        f'tl.fromTo("#s7-g-liq", {{ attr: {{ fill: "{CLEAR}" }} }}, {{ attr: {{ fill: "{MAHO}" }}, duration: 1.4, ease: "power1.inOut" }}, 0.5);',
        pop('#s7-f2', 1.4, -6), pop('#s7-f3', 1.7, 6), pop('#s7-f1', 2.0, -4), pop('#s7-c1', 2.2), pop('#s7-c2', 2.9),
        caps_js('s7'),
        art_out('s7', D, ['#s7-c1', '#s7-c2', '#s7-src'] + caps_ids('s7')),
    ]),
    src=SRC_BOTH)

# s8 귀하고 비싸다
D = SCN['s8']
out['s8'] = scene('s8',
    art('s8', s8_art)
    + chip('s8-c1', '버번 캐스크 · 흔해요', AX + 265, AY + 490, 'c-amber')
    + chip('s8-c2', '셰리 캐스크 · 귀해요', AX + 718, AY + 490, 'c-maho')
    + chip('s8-p1', '₩ 저렴', AX + 265, AY + 62, 'c-cream') + chip('s8-p2', '₩₩₩ 비쌈', AX + 718, AY + 62, 'c-tom')
    + caps('s8'),
    '\n    '.join([
        art_in('s8'),
        *[pop(f'#s8-g{k}', 0.1 + k * 0.06) for k in range(6)],
        'tl.fromTo("#s8-sb", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.5);',
        pop('#s8-c1', 0.7), pop('#s8-c2', 0.9), pop('#s8-p1', 1.6, -4), pop('#s8-p2', 2.1, 4),
        caps_js('s8'),
        art_out('s8', D, ['#s8-c1', '#s8-c2', '#s8-p1', '#s8-p2'] + caps_ids('s8')),
    ]))

# s9 블렌더의 두 가지 방법
D = SCN['s9']
out['s9'] = scene('s9',
    tag('s9-tag', '블렌더의 방법', 't-yel') + art('s9', s9_art)
    + chip('s9-l1', '① 섞기', AX + 130, AY + 195, 'c-cream') + chip('s9-l2', '② 추가 숙성', AX + 130, AY + 450, 'c-cream')
    + caps('s9'),
    '\n    '.join([
        art_in('s9'), pop('#s9-tag', 0.05),
        'tl.set(["#s9-a1","#s9-plus","#s9-a2","#s9-ar1","#s9-a3","#s9-b1","#s9-ar2","#s9-bb","#s9-ar3","#s9-b2"], { opacity: 0 }, 0);',
        pop('#s9-l1', 0.2), pop('#s9-a1', 0.35), pop('#s9-plus', 0.6), pop('#s9-a2', 0.8),
        'tl.fromTo("#s9-ar1", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 1.1);', pop('#s9-a3', 1.3),
        pop('#s9-l2', 2.2), pop('#s9-b1', 2.35),
        'tl.fromTo("#s9-ar2", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 2.6);', pop('#s9-bb', 2.8),
        'tl.fromTo("#s9-ar3", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 3.1);', pop('#s9-b2', 3.3),
        caps_js('s9'),
        art_out('s9', D, ['#s9-tag', '#s9-l1', '#s9-l2'] + caps_ids('s9')),
    ]))

# s10 한눈에 보기 + 예외 칩
D = SCN['s10']; b = B['s10']
out['s10'] = scene('s10',
    art('s10', s10_art)
    + chip('s10-n1', '버번', AX + 140, AY + 302, 'c-amber') + chip('s10-n2', '셰리', AX + 140, AY + 502, 'c-maho')
    + chip('s10-t1', '바닐라', AX + 390, AY + 302, 'c-cream') + chip('s10-t2', '캐러멜', AX + 560, AY + 302, 'c-cream') + chip('s10-t3', '스모크', AX + 730, AY + 302, 'c-cream')
    + chip('s10-t4', '어두운 과일', AX + 420, AY + 502, 'c-cream') + chip('s10-t5', '풍부함', AX + 690, AY + 502, 'c-cream')
    + chip('s10-ex', '예외도 많아요', AX + 760, AY + 76, 'c-tom')
    + caps('s10'),
    '\n    '.join([
        art_in('s10'),
        'tl.set(["#s10-b1","#s10-ar1","#s10-i1","#s10-i2","#s10-i3","#s10-b2","#s10-ar2","#s10-i4","#s10-i5"], { opacity: 0 }, 0);',
        pop('#s10-b1', 0.4), pop('#s10-n1', 0.5),
        'tl.fromTo("#s10-ar1", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 0.7);',
        pop('#s10-i1', 0.9), pop('#s10-t1', 1.0), pop('#s10-i2', 1.15), pop('#s10-t2', 1.25), pop('#s10-i3', 1.4), pop('#s10-t3', 1.5),
        pop('#s10-b2', 2.6), pop('#s10-n2', 2.7),
        'tl.fromTo("#s10-ar2", { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, 2.9);',
        pop('#s10-i4', 3.1), pop('#s10-t4', 3.2), pop('#s10-i5', 3.4), pop('#s10-t5', 3.5),
        pop('#s10-ex', b[1] + 0.3, 4),
        caps_js('s10'),
        art_out('s10', D, ['#s10-n1','#s10-n2','#s10-t1','#s10-t2','#s10-t3','#s10-t4','#s10-t5','#s10-ex','#s10-src'] + caps_ids('s10')),
    ]),
    src=SRC_BOTH)

# s11 집 규칙 — 라벨에서 캐스크 찾기 → 술째리고 검색창에 입력(검색어만, 가격은 보이지 않는다)
D = SCN['s11']; b = B['s11']
Q11 = '셰리 캐스크'
TYPE11 = round(b[1] + 0.9, 2)
s11_art = (f'''<g transform="translate(70 20)"><g id="s11-bot">
      <rect x="130" y="0" width="80" height="44" rx="8" fill="#3B2412"/>
      <path d="M140 40 L200 40 L200 130 C200 150 260 160 260 200 L260 520 C260 540 246 552 226 552 L114 552 C94 552 80 540 80 520 L80 200 C80 160 140 150 140 130 Z" fill="#B8662A" fill-opacity="0.92" stroke="#3B2412" stroke-width="6"/>
      <path d="M102 220 L102 500" stroke="#fff" stroke-opacity="0.28" stroke-width="10" stroke-linecap="round"/>
      <rect x="96" y="270" width="148" height="200" rx="10" fill="{CREAM}" stroke="#3B2412" stroke-width="4"/>
      <text x="170" y="312" text-anchor="middle" font-family="Pretendard" font-weight="700" font-size="30" fill="{NAVY}">WHISKY</text>
      <text x="170" y="370" text-anchor="middle" font-family="Wanted Sans" font-weight="800" font-size="34" fill="{MAHO}">SHERRY</text>
      <text x="170" y="410" text-anchor="middle" font-family="Wanted Sans" font-weight="800" font-size="34" fill="{MAHO}">CASK</text>
      <ellipse id="s11-ring" cx="170" cy="380" rx="92" ry="54" fill="none" stroke="{TOMATO}" stroke-width="8" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1"/>
    </g></g>''')
out['s11'] = scene('s11',
    art('s11', s11_art)
    + chip('s11-c1', '캐스크 이름 찾기', AX + 240, AY + 30, 'c-yel')
    + f'''<div class="search" id="s11-bar"><div class="hint">술째리고에서 검색</div>
      <svg width="52" height="52" viewBox="0 0 52 52"><circle cx="22" cy="22" r="15" fill="none" stroke="#C2410C" stroke-width="6"/><path d="M33 33 L46 46" stroke="#C2410C" stroke-width="7" stroke-linecap="round"/></svg>
      <div class="q">{type_spans("s11-k", Q11)}</div><div class="cur" id="s11-cur"></div></div>'''
    + chip('s11-c2', '가격 비교까지 한 번에', AX + 650, AY + 420, 'c-tom')
    + caps('s11'),
    '\n    '.join([
        art_in('s11'),
        'tl.fromTo("#s11-bot", { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "expo.out" }, 0.1);',
        pop('#s11-c1', 0.5),
        'tl.fromTo("#s11-ring", { attr: { "stroke-dashoffset": 1.1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.6, ease: "power2.out" }, 1.2);',
        f'tl.fromTo("#s11-bar", {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.5)" }}, {b[1] + 0.2});',
        f'tl.fromTo("#s11-cur", {{ opacity: 1 }}, {{ opacity: 0, duration: 0.25, ease: "none", yoyo: true, repeat: 9 }}, {b[1] + 0.5});',
        type_js('s11-k', Q11, TYPE11),
        pop('#s11-c2', round(TYPE11 + len(Q11) * 0.12 + 0.3, 2)),
        caps_js('s11'),
        art_out('s11', D, ['#s11-c1', '#s11-bar', '#s11-c2'] + caps_ids('s11')),
    ]))

# s12 당신은 어느 쪽? — 댓글 유도, 첫 장면과 같은 잔으로 끝나 반복 재생에 이어진다
D = SCN['s12']
Q12 = '저는 ○○파예요'
TYPE12 = 2.4
out['s12'] = scene('s12',
    art('s12', glass('s12-gA', 205, 60, 1.2, AMBER, 0.42) + glass('s12-gB', 515, 60, 1.2, MAHO, 0.42))
    + chip('s12-nA', '버번파', AX + 325, AY + 40, 'c-amber') + chip('s12-nB', '셰리파', AX + 635, AY + 40, 'c-maho')
    + f'<div class="cbox" id="s12-box"><div class="lab">댓글</div><div class="q">{type_spans("s12-k", Q12)}</div></div>'
    + caps('s12'),
    '\n    '.join([
        art_in('s12'),
        pop('#s12-nA', 0.5, -4), pop('#s12-nB', 1.0, 4),
        f'tl.fromTo("#s12-box", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "expo.out" }}, {TYPE12 - 0.5});',
        type_js('s12-k', Q12, TYPE12),
    ] + [caps_js('s12')]))

for sid, html in out.items():
    (comp / f'{sid}.html').write_text(html, encoding='utf-8')
for old in ['s11.html']:
    pass

# ---------- 고정 틀: 남색 바 + 장 제목(장마다 바뀜) + 카운터 뒤 째리 + 말풍선 ----------
SERIES, EPISODE, TOPIC = '째리의 술 수업', '1교시', '버번 vs 셰리 캐스크'
AMB_T, SAL_T = '#F0A93B', '#F2836B'
CHAPTERS = [  # (첫 장면, 제목 html)
    ('s1', f'<span style="color:{AMB_T}">버번</span> <span class="vs">vs</span> <span style="color:{SAL_T}">셰리</span> 캐스크'),
    ('s2', '통이 뭐길래?'),
    ('s4', f'<span style="color:{AMB_T}">버번</span> 캐스크'),
    ('s6', f'<span style="color:{SAL_T}">셰리</span> 캐스크'),
    ('s8', f'<span style="color:{SAL_T}">셰리</span> 통은 귀해서'),
    ('s10', '한눈에 보기'),
    ('s11', '집 규칙'),
    ('s12', '당신은 어느 쪽?'),
]
ch_html = ''.join(f'<div id="fr-ch{k}" class="ch">{h}</div>' for k, (s, h) in enumerate(CHAPTERS))
ch_js = []
for k, (s, h) in enumerate(CHAPTERS):
    t = STARTS[s]
    if k > 0:
        ch_js.append(f'tl.fromTo("#fr-ch{k}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.22, ease: "power4.out" }}, {t + 0.05:.2f});')
    if k + 1 < len(CHAPTERS):
        ch_js.append(f'tl.to("#fr-ch{k}", {{ opacity: 0, filter: "blur(6px)", duration: 0.14, ease: "power2.in" }}, {STARTS[CHAPTERS[k + 1][0]] - 0.14:.2f});')
HOPS = sorted({round(STARTS[s] + c[1], 2) for s in ORDER for c in CAP[s]} - {round(STARTS['s1'] + CAP['s1'][0][1], 2)} | {0.3})
BIG_HOP = STARTS['s3'] + STAMP_T
hop_js = '\n    '.join(
    f'tl.to("#fr-jjeri", {{ keyframes: [{{ y: -22, duration: 0.14, ease: "power2.out" }}, {{ y: 0, duration: 0.2, ease: "power2.in" }}] }}, {t:.2f});' for t in HOPS)
counter_grain = ''.join(f'<path d="M0 {y} C300 {y - 10} 700 {y + 12} 1080 {y - 4}" fill="none" stroke="#6E3A1C" stroke-width="5"/>' for y in (90, 170, 260, 360, 470))
frame = f"""<template>
  <style>
    {FONTS}
    #root {{ position: absolute; inset: 0; overflow: hidden; font-family: 'Pretendard'; color: {CREAM};
             background: radial-gradient(circle at 50% 38%, #2E3D62 0%, {NAVY} 58%, #172036 100%); }}
    #fr-badgebox {{ position: absolute; left: 0; right: 0; top: 274px; text-align: center; }}
    #fr-badge {{ display: inline-block; font-weight: 700; font-size: 30px; color: #fff; background: {TOMATO}; border-radius: 999px; padding: 6px 24px; }}
    #fr-badge small {{ font-size: 30px; opacity: 0.85; }}
    .ch {{ position: absolute; left: 0; right: 0; top: 326px; text-align: center; font-family: 'Wanted Sans'; font-weight: 800; font-size: 80px; line-height: 1.1; letter-spacing: -0.035em; color: {CREAM}; opacity: 0; }}
    #fr-ch0 {{ opacity: 1; }}
    .ch .vs {{ font-size: 56px; color: #C3CCDD; }}
    #fr-jjeri {{ position: absolute; left: 34px; top: 1084px; width: 218px; }}
    #fr-bubble {{ position: absolute; left: 262px; top: 1040px; width: 754px; height: 200px; background: {CREAM}; border: 5px solid {INK}; border-radius: 30px; box-shadow: 0 8px 0 rgba(0,0,0,0.25); }}
    #fr-tail {{ position: absolute; left: 224px; top: 1114px; width: 44px; height: 52px; }}
    #fr-counter {{ position: absolute; left: 0; top: 1330px; width: 1080px; height: 590px; }}
    #fr-handle {{ position: absolute; left: 0; right: 0; top: 1376px; text-align: center; font-weight: 700; font-size: 32px; color: #F6D9B8; opacity: 0.85; }}
  </style>
  <div id="root" data-composition-id="frame" data-width="1080" data-height="1920">
    <div id="fr-badgebox"><span id="fr-badge">{SERIES} {EPISODE} <small>· {TOPIC}</small></span></div>
    {ch_html}
    <img id="fr-jjeri" src="assets/img/jjeri.svg" alt="째리">
    <svg id="fr-counter" viewBox="0 0 1080 590" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="1080" height="590" fill="{WOOD_D}"/>
      <rect x="0" y="0" width="1080" height="30" fill="#A8693A"/><rect x="0" y="30" width="1080" height="8" fill="#5A2E14"/>
      {counter_grain}
    </svg>
    <div id="fr-handle" data-layout-ignore>술째리고 &nbsp;@sooljjerigo</div>
    <div id="fr-bubble"></div>
    <svg id="fr-tail" viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg">
      <polygon points="44,4 4,26 44,48" fill="{CREAM}"/>
      <polyline points="40,6 4,26 40,46" fill="none" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>
    </svg>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.set("#fr-jjeri", {{ y: 0, rotation: 0 }}, 0);
    {hop_js}
    tl.to("#fr-jjeri", {{ keyframes: [{{ rotation: -10, duration: 0.12, ease: "power2.out" }}, {{ rotation: 0, duration: 0.5, ease: "back.out(2)" }}], transformOrigin: "50% 100%" }}, {BIG_HOP:.2f});
    {chr(10).join('    ' + j for j in ch_js)}
    tl.set({{}}, {{}}, {TOTAL});
    window.__timelines["frame"] = tl;
  </script>
</template>
"""
(comp / 'frame.html').write_text(frame, encoding='utf-8')

# ---------- 소리: 내레이션(시계) + 낮춘 배경음 + 화면 사건 효과음 ----------
S = STARTS
SFX = [
    ('pop', S['s1'] + 1.0), ('click-soft', S['s1'] + 1.6),
    ('impact-bass-1', S['s3'] + STAMP_T + 0.28),
    ('whoosh', S['s4']), ('pop', S['s4'] + B['s4'][1] + 1.15),
    ('whoosh-short', S['s6']),
    ('pop', S['s8'] + 1.6), ('pop', S['s8'] + 2.1),
    ('whoosh', S['s10']), ('pop', S['s10'] + B['s10'][1] + 0.3),
    ('pop', S['s12'] + 0.5), ('click-soft', S['s12'] + 1.0),
] + [('key-press', S['s11'] + TYPE11 + k * 0.12) for k in range(len(Q11)) if Q11[k] != ' '] \
  + [('key-press', S['s12'] + TYPE12 + k * 0.12) for k in range(len(Q12)) if Q12[k] != ' ']
PEAK = {'pop': 0.12, 'click-soft': 0.073, 'impact-bass-1': 0.073, 'whoosh': 0.162, 'whoosh-short': 0.162, 'key-press': 0.02}
LEN = {'pop': 0.72, 'click-soft': 0.36, 'impact-bass-1': 2.1, 'whoosh': 0.57, 'whoosh-short': 0.57, 'key-press': 0.2}
VOL = {'pop': 0.45, 'click-soft': 0.5, 'impact-bass-1': 0.35, 'whoosh': 0.4, 'whoosh-short': 0.4, 'key-press': 0.25}

hosts = '\n      '.join(
    f'<div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" data-start="{S[sid]}" data-duration="{d}" '
    f'data-track-index="1" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:2"></div>'
    for sid, d in SCENES)
vo_tags = '\n      '.join(
    f'<audio id="vo{c[3]["k"]:02d}" class="clip" src="{c[3]["file"]}" data-start="{round(S[sid] + c[1], 3)}" data-duration="{round(c[3]["end"] - c[3]["head"], 3)}" '
    f'data-media-start="{c[3]["head"]}" data-track-index="3" data-volume="1"></audio>'
    for sid in ORDER for c in CAP[sid])
sfx_tags = '\n      '.join(
    f'<audio id="sfx{k:02d}" class="clip" src="assets/sfx/{f}.mp3" data-start="{max(0, round(t - PEAK[f] + 1 / 30, 3))}" data-duration="{LEN[f]}" data-track-index="{10 + k}" data-volume="{VOL[f]}"></audio>'
    for k, (f, t) in enumerate(SFX))
index = f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: {NAVY}; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL}" data-width="1080" data-height="1920">
      <div id="frame" data-composition-id="frame" data-composition-src="compositions/frame.html" data-start="0" data-duration="{TOTAL}" data-track-index="0" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:1"></div>
      {hosts}
      {vo_tags}
      <audio id="bgm" class="clip" src="assets/bgm/bed.mp3" data-start="0" data-duration="{TOTAL}" data-media-start="0" data-track-index="9" data-volume="0.16" data-fade-in="0.3" data-fade-out="2.0"></audio>
      {sfx_tags}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""
(root / 'index.html').write_text(index, encoding='utf-8')
print('scenes', len(SCENES), 'total', TOTAL, {s: SCN[s] for s in ORDER})

# 엔진 비교용 정답 시간표(엔진이 같은 episode JSON 으로 같은 시각을 내야 한다)
(root / 'timeline.json').write_text(json.dumps({
    'total': TOTAL, 'gap': GAP, 'lead': LEAD, 'tail': TAIL, 'min': MIN,
    'scenes': [{'id': s, 'start': STARTS[s], 'dur': SCN[s],
                'beats': [{'k': c[3]['k'], 'start_local': c[1], 'speech': round(c[3]['end'] - c[3]['head'], 3), 'media_start': c[3]['head']} for c in CAP[s]]}
               for s in ORDER],
    'chapters': [{'from_scene': s, 'start': STARTS[s]} for s, _ in CHAPTERS],
    'stamp_s3_local': STAMP_T}, ensure_ascii=False, indent=1), encoding='utf-8')
