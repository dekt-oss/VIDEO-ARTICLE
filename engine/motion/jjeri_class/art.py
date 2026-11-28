"""SVG drawing primitives for the Jjeri stage."""

from html import escape

NAVY, INK, CREAM, BG, TOMATO, YEL = '#1F2A44', '#0E1525', '#FFF8EE', '#F7F3EC', '#C2410C', '#FDE68A'
AMBER, MAHO, CLEAR = '#F0A93B', '#8E2A14', '#DCE7F0'
WOOD_L, GRAIN_L, WOOD_D, GRAIN_D, HOOP = '#C68A4E', '#9A6334', '#8A4A26', '#63331A', '#2B2B33'
AX, AY = 60, 410  # 그림 칸의 화면 위치

FONTS = """@font-face { font-family: 'Wanted Sans'; src: url('assets/fonts/WantedSans-ExtraBold.otf'); font-weight: 800; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-Bold.woff2'); font-weight: 700; }
    @font-face { font-family: 'Pretendard'; src: url('assets/fonts/Pretendard-SemiBold.woff2'); font-weight: 600; }"""
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


def barrel(i, x, y, s, wood=WOOD_L, grain=GRAIN_L, tint=None):
    body = "M40 0 L200 0 Q240 150 200 300 L40 300 Q0 150 40 0 Z"
    tint_svg = ''
    if tint:  # 셰리가 스며드는 붉은 기운 — 아래에서 위로 차오른다
        tint_svg = (f'<clipPath id="{i}-tc"><rect id="{i}-tr" x="0" y="300" width="240" height="0"/></clipPath>'
                    f'<path d="{body}" fill="{tint}" fill-opacity="0.62" clip-path="url(#{i}-tc)"/>')
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


def bottle(i, x, y, s=1.0, label=""):
    label = escape(label).replace("@", "&#64;")
    return f'''<g transform="translate({x} {y}) scale({s})"><g id="{i}">
      <path d="M44 20 L76 20 L76 96 C76 112 110 116 110 146 L110 330 C110 338 104 342 96 342 L24 342 C16 342 10 338 10 330 L10 146 C10 116 44 112 44 96 Z" fill="#1F3B2C" stroke="#0E1F16" stroke-width="5"/>
      <rect x="40" y="6" width="40" height="18" rx="4" fill="#7A1F2B"/>
      <rect x="18" y="196" width="84" height="84" rx="8" fill="{CREAM}"/>
      <text x="60" y="250" text-anchor="middle" font-family="Pretendard" font-weight="700" font-size="30" fill="{NAVY}">{label}</text>
      <path d="M24 150 L24 320" stroke="#fff" stroke-opacity="0.25" stroke-width="8" stroke-linecap="round"/>
    </g></g>'''


def arrow(i, x1, y1, x2, y2, color=CREAM, dash=False):
    d = ' stroke-dasharray="14 12"' if dash else ''
    return (f'<g id="{i}"><path d="M{x1} {y1} L{x2 - 18} {y2}" stroke="{color}" stroke-width="8" stroke-linecap="round"{d}/>'
            f'<path d="M{x2 - 30} {y2 - 18} L{x2} {y2} L{x2 - 30} {y2 + 18}" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></g>')

