"""2.5D 그림 부품 — 원통 음영(가로 그라데이션) · 윗면 타원 · 잘린 면(벽 두께) · 바닥 그림자.
규칙: 빛은 왼쪽 위. 윗면 타원의 세로 반지름 = 가로 반지름 × PERSP. 모든 회전체는 profile(y) 로 같은 모양을 공유한다."""
import math

PERSP = 0.17
INK = '#1A0F08'
CX = 540
JAR_TOP, JAR_BOT, WALL = 520, 962, 16


def jar_w(y):
    """옹기 반폭(옆모습). 목 140 → 어깨 252 → 바닥 157."""
    t = max(0.0, min(1.0, (y - JAR_TOP) / (JAR_BOT - JAR_TOP)))
    return 140 + 112 * math.sin(math.pi * t * 0.95) ** 0.9


def _profile_path(wfn, y0, y1, inset=0.0, step=8):
    ys = list(range(int(y0), int(y1) + 1, step)) + [y1]
    left = [(CX - (wfn(y) - inset), y) for y in ys]
    right = [(CX + (wfn(y) - inset), y) for y in reversed(ys)]
    pts = left + right
    return 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in pts) + ' Z'


def jar_body_path(inset=0.0, y0=JAR_TOP, y1=JAR_BOT, *, profile=jar_w):
    return _profile_path(profile, y0, y1, inset)


def defs(p, profile=jar_w):
    """세계마다 접두 p 로 한 벌(아이디 충돌 방지)."""
    return f'''<defs>
  <linearGradient id="{p}-glaze" x1="0" x2="1"><stop offset="0" stop-color="#24150C"/><stop offset="0.22" stop-color="#7A4A2A"/><stop offset="0.36" stop-color="#9A6238"/><stop offset="0.6" stop-color="#5B3A23"/><stop offset="1" stop-color="#1E120A"/></linearGradient>
  <linearGradient id="{p}-shade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="0.7" stop-color="#000" stop-opacity="0.1"/><stop offset="1" stop-color="#000" stop-opacity="0.45"/></linearGradient>
  <linearGradient id="{p}-inner" x1="0" x2="1"><stop offset="0" stop-color="#1E120A"/><stop offset="0.5" stop-color="#4A2E1A"/><stop offset="1" stop-color="#1A0F08"/></linearGradient>
  <linearGradient id="{p}-cut" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#C98A5A"/><stop offset="1" stop-color="#9A6238"/></linearGradient>
  <linearGradient id="{p}-wood" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#C08250"/><stop offset="1" stop-color="#7A4A26"/></linearGradient>
  <linearGradient id="{p}-woodside" x1="0" x2="1"><stop offset="0" stop-color="#5A3317"/><stop offset="0.35" stop-color="#9A6238"/><stop offset="1" stop-color="#4A2A14"/></linearGradient>
  <linearGradient id="{p}-porc" x1="0" x2="1"><stop offset="0" stop-color="#C9C3B6"/><stop offset="0.3" stop-color="#FFFFFF"/><stop offset="0.7" stop-color="#EDE8DE"/><stop offset="1" stop-color="#B9B2A3"/></linearGradient>
  <linearGradient id="{p}-bamboo" x1="0" x2="1"><stop offset="0" stop-color="#8A6A3C"/><stop offset="0.35" stop-color="#E2C38E"/><stop offset="1" stop-color="#7A5A2E"/></linearGradient>
  <linearGradient id="{p}-mash" x1="0" x2="1"><stop offset="0" stop-color="#CFC3A8"/><stop offset="0.4" stop-color="#EFE6D2"/><stop offset="1" stop-color="#C2B596"/></linearGradient>
  <linearGradient id="{p}-milk" x1="0" x2="1"><stop offset="0" stop-color="#DDD5C4"/><stop offset="0.4" stop-color="#FBF8F1"/><stop offset="1" stop-color="#D3C9B4"/></linearGradient>
  <linearGradient id="{p}-clear" x1="0" x2="1"><stop offset="0" stop-color="#C9A24C"/><stop offset="0.4" stop-color="#F3D88A"/><stop offset="1" stop-color="#B8903C"/></linearGradient>
  <linearGradient id="{p}-water" x1="0" x2="1"><stop offset="0" stop-color="#5E9CC4"/><stop offset="0.4" stop-color="#A9D6F0"/><stop offset="1" stop-color="#4F8AB2"/></linearGradient>
  <radialGradient id="{p}-shadow"><stop offset="0" stop-color="#000" stop-opacity="0.55"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
  <radialGradient id="{p}-grain" cx="0.35" cy="0.35"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#D8CFBC"/></radialGradient>
  <clipPath id="{p}-in"><path d="{jar_body_path(WALL, JAR_TOP + 14, JAR_BOT - 10, profile=profile)}"/></clipPath>
  <clipPath id="{p}-outer"><path d="{jar_body_path(profile=profile)}"/></clipPath>
</defs>'''


def plate(p, cx=540, cy=980, rx=310):
    """나무 받침(두께가 보이는 원판)."""
    ry, h = rx * PERSP, 26
    return (f'<ellipse cx="{cx}" cy="{cy + h + 18}" rx="{rx * 1.05:.0f}" ry="{ry * 1.4:.0f}" fill="url(#{p}-shadow)"/>'
            f'<path d="M{cx - rx} {cy} L{cx - rx} {cy + h} A{rx} {ry:.1f} 0 0 0 {cx + rx} {cy + h} L{cx + rx} {cy} Z" fill="url(#{p}-woodside)" stroke="{INK}" stroke-width="4"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry:.1f}" fill="url(#{p}-wood)" stroke="{INK}" stroke-width="4"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="{rx - 46}" ry="{(rx - 46) * PERSP:.1f}" fill="none" stroke="#E2B07E" stroke-opacity="0.45" stroke-width="3"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="{rx - 110}" ry="{(rx - 110) * PERSP:.1f}" fill="none" stroke="#E2B07E" stroke-opacity="0.3" stroke-width="3"/>')


def _band(y, w, color, width=5, op=0.55):
    """몸통을 감는 띠(앞쪽으로 휘는 반타원)."""
    return f'<path d="M{CX - w:.1f} {y} A{w:.1f} {w * PERSP:.1f} 0 0 0 {CX + w:.1f} {y}" fill="none" stroke="{color}" stroke-opacity="{op}" stroke-width="{width}"/>'


def jar_closed(p, gid):
    """닫힌(바깥) 옹기 — 훅·반복 재생 장면. gid 묶음을 통째로 치우면 단면이 드러난다."""
    body = jar_body_path()
    bands = ''.join(_band(y, jar_w(y), '#C99A6A') for y in (650, 690))
    wave = ''.join(f'<path d="M{CX - jar_w(735) + 8 + k * 46:.1f} {735 + 14 * math.sin(k):.1f} q 12 -14 23 0 t 23 0" fill="none" stroke="#D9AA78" stroke-opacity="0.5" stroke-width="4"/>' for k in range(10))
    rw = jar_w(JAR_TOP) + 10
    return (f'<g id="{gid}"><path d="{body}" fill="url(#{p}-glaze)" stroke="{INK}" stroke-width="6"/>'
            f'<path d="{body}" fill="url(#{p}-shade)"/>{bands}{wave}'
            f'<path d="M{CX - 190} 600 C{CX - 215} 700 {CX - 200} 820 {CX - 150} 920" fill="none" stroke="#fff" stroke-opacity="0.16" stroke-width="18" stroke-linecap="round"/>'
            f'<path d="M{CX - 160} 620 C{CX - 175} 690 {CX - 172} 760 {CX - 150} 820" fill="none" stroke="#fff" stroke-opacity="0.22" stroke-width="6" stroke-linecap="round"/>'
            f'<ellipse cx="{CX}" cy="{JAR_TOP}" rx="{rw:.0f}" ry="{rw * PERSP:.0f}" fill="#6B4429" stroke="{INK}" stroke-width="6"/>'
            f'<ellipse cx="{CX}" cy="{JAR_TOP + 2}" rx="{rw - 26:.0f}" ry="{(rw - 26) * PERSP:.0f}" fill="#140B06"/></g>')


def jar_cutaway(p, contents, cut_id, profile=jar_w):
    """앞 절반을 떼어 낸 옹기: 안쪽 벽(뒤) → 내용물(contents) → 잘린 면(벽 두께) → 뒤쪽 입술."""
    outer, inner = jar_body_path(profile=profile), jar_body_path(WALL, JAR_TOP + 14, JAR_BOT - 10, profile=profile)
    rw = profile(JAR_TOP) + 10
    floor_w = profile(JAR_BOT - 10) - WALL
    back_lip = f'<path d="M{CX - rw:.0f} {JAR_TOP} A{rw:.0f} {rw * PERSP:.0f} 0 0 1 {CX + rw:.0f} {JAR_TOP}" fill="none" stroke="#6B4429" stroke-width="22"/>'
    return (f'<path d="{outer}" fill="url(#{p}-inner)"/>'
            f'<path d="{inner}" fill="#2A190E"/>'
            f'<ellipse cx="{CX}" cy="{JAR_BOT - 10}" rx="{floor_w:.0f}" ry="{floor_w * PERSP:.0f}" fill="#3A2416"/>'
            f'{back_lip}'
            f'<g clip-path="url(#{p}-in)">{contents}</g>'
            f'<g id="{cut_id}"><path d="{outer}" fill="none" stroke="url(#{p}-cut)" stroke-width="{WALL * 2}" clip-path="url(#{p}-outer)"/>'
            f'<path d="{outer}" fill="none" stroke="{INK}" stroke-width="6"/><path d="{inner}" fill="none" stroke="{INK}" stroke-opacity="0.6" stroke-width="3"/>'
            + ''.join(f'<circle cx="{CX + s * (profile(y) - WALL / 2):.1f}" cy="{y}" r="2.5" fill="#7A4A2A"/>' for y in range(560, 950, 34) for s in (-1, 1)) + '</g>')


def layer(i, y_top, y_bot, fill, op=1.0, surf=None, hidden=False, profile=jar_w):
    """단면 안 한 층: 앞면(사각, 단면 clip 으로 잘림) + 윗면 타원(표면). 표면 색 surf."""
    w = profile(y_top) - WALL
    o = ' opacity="0"' if hidden else (f' opacity="{op}"' if op != 1 else '')
    s = surf or fill
    return (f'<g id="{i}"{o}><rect x="{CX - 260}" y="{y_top}" width="520" height="{y_bot - y_top}" fill="{fill}"/>'
            f'<ellipse cx="{CX}" cy="{y_top}" rx="{w:.0f}" ry="{w * PERSP:.0f}" fill="{s}" stroke="#fff" stroke-opacity="0.35" stroke-width="2"/></g>')


def lid(i):
    rw = jar_w(JAR_TOP) + 22
    return (f'<g id="{i}"><ellipse cx="{CX}" cy="{JAR_TOP + 4}" rx="{rw:.0f}" ry="{rw * PERSP:.0f}" fill="#3A2416"/>'
            f'<path d="M{CX - rw:.0f} {JAR_TOP - 6} C{CX - rw + 20:.0f} {JAR_TOP - 90} {CX + rw - 20:.0f} {JAR_TOP - 90} {CX + rw:.0f} {JAR_TOP - 6} A{rw:.0f} {rw * PERSP:.0f} 0 0 1 {CX - rw:.0f} {JAR_TOP - 6} Z" fill="#7A4A2A" stroke="{INK}" stroke-width="6"/>'
            f'<path d="M{CX - 90} {JAR_TOP - 54} C{CX - 40} {JAR_TOP - 74} {CX + 10} {JAR_TOP - 76} {CX + 40} {JAR_TOP - 70}" fill="none" stroke="#fff" stroke-opacity="0.25" stroke-width="8" stroke-linecap="round"/>'
            f'<ellipse cx="{CX}" cy="{JAR_TOP - 72}" rx="36" ry="13" fill="#5B3A23" stroke="{INK}" stroke-width="5"/>'
            f'<path d="M{CX - 36} {JAR_TOP - 72} L{CX - 30} {JAR_TOP - 92} A30 10 0 0 1 {CX + 30} {JAR_TOP - 92} L{CX + 36} {JAR_TOP - 72}" fill="#6B4429" stroke="{INK}" stroke-width="5"/></g>')


# ---------- 토큰(작은 입체 조각) ----------
def grain(i, x, y, p, hidden=False):
    o = ' opacity="0"' if hidden else ''
    r = (x * 7) % 60 - 30
    return (f'<g id="{i}"{o}><ellipse cx="{x}" cy="{y + 3}" rx="14" ry="6" fill="#000" opacity="0.18"/>'
            f'<ellipse cx="{x}" cy="{y}" rx="14" ry="8.5" fill="url(#{p}-grain)" stroke="#9E937C" stroke-width="2" transform="rotate({r} {x} {y})"/></g>')


def sugar(i, x, y):
    return (f'<g id="{i}" opacity="0"><path d="M{x} {y - 15} L{x + 13} {y - 2} L{x} {y + 14} L{x - 13} {y - 2} Z" fill="#E9B530" stroke="#7A5A0E" stroke-width="2"/>'
            f'<path d="M{x} {y - 15} L{x + 13} {y - 2} L{x} {y + 1} L{x - 13} {y - 2} Z" fill="#FFE08A"/></g>')


def drop(i, x, y):
    return (f'<g id="{i}" opacity="0"><path d="M{x} {y - 16} C{x + 11} {y - 2} {x + 12} {y + 10} {x} {y + 12} C{x - 12} {y + 10} {x - 11} {y - 2} {x} {y - 16} Z" fill="#8FC6EA" stroke="#2F6F9A" stroke-width="2"/>'
            f'<path d="M{x - 4} {y - 4} C{x - 6} {y + 2} {x - 5} {y + 6} {x - 2} {y + 8}" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/></g>')


def bubble(i, x, y, r=9):
    return (f'<g id="{i}" opacity="0"><circle cx="{x}" cy="{y}" r="{r}" fill="#fff" fill-opacity="0.12" stroke="#FFFFFF" stroke-width="2.5"/>'
            f'<path d="M{x - r * 0.5:.1f} {y - r * 0.3:.1f} A{r * 0.6:.1f} {r * 0.6:.1f} 0 0 1 {x:.1f} {y - r * 0.7:.1f}" fill="none" stroke="#fff" stroke-width="2"/></g>')


def nuruk(i, x, y):
    """누룩 덩이: 윗면·옆면이 보이는 납작한 원판 + 흰 곰팡이 점."""
    return (f'<g id="{i}" opacity="0"><ellipse cx="{x}" cy="{y + 26}" rx="58" ry="12" fill="#000" opacity="0.25"/>'
            f'<path d="M{x - 52} {y} L{x - 52} {y + 20} A52 11 0 0 0 {x + 52} {y + 20} L{x + 52} {y} Z" fill="#8A5A2A" stroke="#3B2412" stroke-width="3"/>'
            f'<ellipse cx="{x}" cy="{y}" rx="52" ry="11" fill="#C08A4A" stroke="#3B2412" stroke-width="3"/>'
            + ''.join(f'<circle cx="{x - 38 + (k * 19) % 76}" cy="{y - 5 + (k * 7) % 10}" r="3.5" fill="#EEF4E2"/>' for k in range(9)) + '</g>')


# ---------- 도구 ----------
def bowl(p, i_milk, cx=540, rim_y=860, rx=230, depth=120):
    """흰 사발: 바깥 옆면 → 안쪽 면 → 우유빛 술 표면(i_milk, 처음엔 바닥) → 입술."""
    ry = rx * PERSP
    side = f'M{cx - rx} {rim_y} C{cx - rx + 10} {rim_y + depth * 0.9} {cx - 70} {rim_y + depth} {cx} {rim_y + depth} C{cx + 70} {rim_y + depth} {cx + rx - 10} {rim_y + depth * 0.9} {cx + rx} {rim_y} Z'
    return (f'<ellipse cx="{cx}" cy="{rim_y + depth + 10}" rx="{rx * 0.7:.0f}" ry="{rx * 0.12:.0f}" fill="url(#{p}-shadow)"/>'
            f'<path d="{side}" fill="url(#{p}-porc)" stroke="{INK}" stroke-width="5"/>'
            f'<path d="M{cx - 70} {rim_y + depth - 4} L{cx + 70} {rim_y + depth - 4} L{cx + 60} {rim_y + depth + 12} L{cx - 60} {rim_y + depth + 12} Z" fill="#D9D2C3" stroke="{INK}" stroke-width="4"/>'
            f'<ellipse cx="{cx}" cy="{rim_y}" rx="{rx - 6}" ry="{ry - 1:.0f}" fill="#E4DED2"/>'
            f'<ellipse id="{i_milk}" cx="{cx}" cy="{rim_y + 34}" rx="60" ry="10" fill="url(#{p}-milk)" stroke="#fff" stroke-opacity="0.5" stroke-width="2"/>'
            f'<ellipse cx="{cx}" cy="{rim_y}" rx="{rx}" ry="{ry:.0f}" fill="none" stroke="{INK}" stroke-width="5"/>'
            f'<ellipse cx="{cx}" cy="{rim_y}" rx="{rx - 10}" ry="{ry - 2:.0f}" fill="none" stroke="#fff" stroke-width="3"/>')


def sieve(p, cx=540, y=720, rx=200, h=46):
    """대나무 체: 테(두께) + 원근 격자 + 앞쪽 테."""
    ry = rx * PERSP
    mesh = ''.join(f'<path d="M{cx - rx + 10 + k * 22} {y - ry} L{cx - rx + 10 + k * 22} {y + ry}" stroke="#B8956A" stroke-width="2"/>' for k in range(19))
    mesh += ''.join(f'<path d="M{cx - rx} {y - ry + k * 8:.1f} L{cx + rx} {y - ry + k * 8:.1f}" stroke="#B8956A" stroke-width="2"/>' for k in range(9))
    return (f'<clipPath id="{p}-mesh"><ellipse cx="{cx}" cy="{y}" rx="{rx - 8}" ry="{ry - 2:.1f}"/></clipPath>'
            f'<ellipse cx="{cx}" cy="{y - h}" rx="{rx}" ry="{ry:.1f}" fill="#6A4A22"/>'
            f'<path d="M{cx - rx} {y - h} L{cx - rx} {y} A{rx} {ry:.1f} 0 0 0 {cx + rx} {y} L{cx + rx} {y - h} Z" fill="url(#{p}-bamboo)" fill-opacity="0.35"/>'
            f'<g clip-path="url(#{p}-mesh)">{mesh}</g>'
            f'<path d="M{cx - rx} {y - h} L{cx - rx} {y} A{rx} {ry:.1f} 0 0 0 {cx + rx} {y} L{cx + rx} {y - h} A{rx} {ry:.1f} 0 0 1 {cx - rx} {y - h} Z" fill="none" stroke="{INK}" stroke-width="5"/>'
            f'<path d="M{cx - rx} {y - h} A{rx} {ry:.1f} 0 0 0 {cx + rx} {y - h} L{cx + rx} {y - h + 16} A{rx} {ry:.1f} 0 0 1 {cx - rx} {y - h + 16} Z" fill="url(#{p}-bamboo)" stroke="{INK}" stroke-width="4"/>'
            f'<path d="M{cx - rx} {y} A{rx} {ry:.1f} 0 0 0 {cx + rx} {y} L{cx + rx} {y - 14} A{rx} {ry:.1f} 0 0 1 {cx - rx} {y - 14} Z" fill="url(#{p}-bamboo)" stroke="{INK}" stroke-width="4"/>')


def hand(x, y, flip=1):
    """위에서 본 손등(손가락 넷 + 엄지), 살색 음영."""
    s = flip
    return (f'<g transform="translate({x} {y}) scale({s} 1)">'
            f'<path d="M-44 10 C-50 -20 -30 -36 0 -36 C30 -36 48 -22 46 6 C44 30 26 40 0 40 C-26 40 -40 30 -44 10 Z" fill="#F0C29A" stroke="#7A4A2A" stroke-width="4"/>'
            + ''.join(f'<path d="M{fx} -30 C{fx - 2} -56 {fx + 14} -58 {fx + 14} -32" fill="#F0C29A" stroke="#7A4A2A" stroke-width="4"/>' for fx in (-36, -16, 4, 22))
            + '<path d="M40 4 C64 -6 72 14 52 24" fill="#F0C29A" stroke="#7A4A2A" stroke-width="4"/>'
            '<path d="M-30 -10 C-16 -18 10 -18 26 -8" fill="none" stroke="#C98E66" stroke-width="3"/>'
            '<path d="M-24 6 C-10 0 10 0 24 8" fill="none" stroke="#fff" stroke-opacity="0.35" stroke-width="5" stroke-linecap="round"/></g>')


def ladle(i, p, bx=470, by=752):
    """나무 국자(긴 자루 + 오목한 머리, 맑은 술이 담김). (bx,by) = 머리 가운데."""
    hx, hy = bx - 175, by - 290
    return (f'<g id="{i}" opacity="0"><path d="M{hx} {hy} L{bx - 15} {by}" stroke="#6E4422" stroke-width="18" stroke-linecap="round"/>'
            f'<path d="M{hx} {hy} L{bx - 15} {by}" stroke="#C08A56" stroke-width="9" stroke-linecap="round"/>'
            f'<path d="M{bx - 56} {by} C{bx - 56} {by + 58} {bx + 56} {by + 58} {bx + 56} {by} Z" fill="#A8703F" stroke="{INK}" stroke-width="4"/>'
            f'<ellipse cx="{bx}" cy="{by}" rx="56" ry="11" fill="url(#{p}-clear)" stroke="{INK}" stroke-width="3"/></g>')


def cup(i, p, cx, y_rim, rx=70, h=74):
    """흰 청주 잔(굽 있는 작은 잔) + 맑은 술 표면."""
    ry = rx * PERSP
    return (f'<g id="{i}" opacity="0"><ellipse cx="{cx}" cy="{y_rim + h + 12}" rx="{rx * 0.8:.0f}" ry="{rx * 0.14:.0f}" fill="url(#{p}-shadow)"/>'
            f'<path d="M{cx - rx} {y_rim} C{cx - rx + 6} {y_rim + h * 0.8} {cx - 26} {y_rim + h} {cx} {y_rim + h} C{cx + 26} {y_rim + h} {cx + rx - 6} {y_rim + h * 0.8} {cx + rx} {y_rim} Z" fill="url(#{p}-porc)" stroke="{INK}" stroke-width="4"/>'
            f'<path d="M{cx - 24} {y_rim + h - 2} L{cx + 24} {y_rim + h - 2} L{cx + 20} {y_rim + h + 10} L{cx - 20} {y_rim + h + 10} Z" fill="#DCD5C7" stroke="{INK}" stroke-width="3"/>'
            f'<ellipse cx="{cx}" cy="{y_rim + 6}" rx="{rx - 8}" ry="{ry - 1:.0f}" fill="url(#{p}-clear)"/>'
            f'<ellipse cx="{cx}" cy="{y_rim}" rx="{rx}" ry="{ry:.0f}" fill="none" stroke="{INK}" stroke-width="4"/></g>')


def tumbler(p, i_bub_prefix, n_bub, cx=540, top=600, bot=962, rt=118, rb=92):
    """두꺼운 유리잔 + 뽀얀 술(표면 타원·거품 띠) + 안쪽 기포."""
    level = top + 46
    def w(y):
        return rb + (rt - rb) * (bot - y) / (bot - top)
    body = f'M{cx - rt} {top} L{cx - rb} {bot} A{rb} {rb * PERSP:.1f} 0 0 0 {cx + rb} {bot} L{cx + rt} {top}'
    liq = f'M{cx - w(level) + 6:.1f} {level} L{cx - rb + 8} {bot - 26} A{rb - 8} {(rb - 8) * PERSP:.1f} 0 0 0 {cx + rb - 8} {bot - 26} L{cx + w(level) - 6:.1f} {level} Z'
    bubs = ''.join(bubble(f'{i_bub_prefix}{k}', cx - 60 + (k * 29) % 120, bot - 50 - (k * 23) % 60, 4 + k % 3 * 2) for k in range(n_bub))
    return (f'<ellipse cx="{cx}" cy="{bot + 8}" rx="{rb * 1.25:.0f}" ry="{rb * 0.22:.0f}" fill="url(#{p}-shadow)"/>'
            f'<clipPath id="{p}-liq"><path d="{liq}"/></clipPath>'
            f'<path d="{liq}" fill="url(#{p}-milk)"/>'
            f'<g clip-path="url(#{p}-liq)">{bubs}</g>'
            f'<ellipse cx="{cx}" cy="{level}" rx="{w(level) - 6:.0f}" ry="{(w(level) - 6) * PERSP:.0f}" fill="#FFFDF7" stroke="#E2D8C2" stroke-width="3"/>'
            + ''.join(f'<circle cx="{cx - w(level) + 26 + k * 28:.0f}" cy="{level + (k % 2) * 5 - 2}" r="{5 + k % 2 * 2}" fill="#fff" stroke="#E2D8C2" stroke-width="1.5"/>' for k in range(int(2 * w(level) / 28) - 1))
            + f'<path d="{body}" fill="rgba(220,235,250,0.10)" stroke="#E8EEF8" stroke-width="6" stroke-linejoin="round"/>'
            f'<ellipse cx="{cx}" cy="{bot - 14}" rx="{rb - 4}" ry="{(rb - 4) * PERSP:.0f}" fill="none" stroke="#E8EEF8" stroke-opacity="0.6" stroke-width="5"/>'
            f'<ellipse cx="{cx}" cy="{top}" rx="{rt}" ry="{rt * PERSP:.0f}" fill="rgba(255,255,255,0.06)" stroke="#E8EEF8" stroke-width="6"/>'
            f'<path d="M{cx - rt + 22} {top + 30} L{cx - rb + 18} {bot - 40}" stroke="#fff" stroke-opacity="0.45" stroke-width="10" stroke-linecap="round"/>'
            f'<path d="M{cx + rt - 30} {top + 40} L{cx + rb - 24} {bot - 60}" stroke="#fff" stroke-opacity="0.18" stroke-width="6" stroke-linecap="round"/>')

def barrel_width(y):
    fraction = max(0.0, min(1.0, (y-JAR_TOP)/(JAR_BOT-JAR_TOP)))
    return 180 + 66 * math.sin(math.pi*fraction)


def barrel_closed(prefix, identifier):
    body = jar_body_path(profile=barrel_width)
    seams = ''.join(
        f'<path d="M{CX + f*barrel_width(JAR_TOP):.1f} {JAR_TOP} Q{CX + f*barrel_width(740):.1f} 740 {CX + f*barrel_width(JAR_BOT):.1f} {JAR_BOT}" '
        f'fill="none" stroke="#362315" stroke-width="3" opacity=".7"/>' for f in (-.8,-.6,-.4,-.2,0,.2,.4,.6,.8)
    )
    hoops = ''.join(_band(y, barrel_width(y)+3, "#9A9A91", 19, .95) for y in (560,666,837,921))
    rx = barrel_width(JAR_TOP)
    return (f'<g id="{identifier}"><path d="{body}" fill="url(#{prefix}-glaze)" stroke="{INK}" stroke-width="6"/>'
            f'{seams}{hoops}<path d="{body}" fill="url(#{prefix}-shade)"/>'
            f'<ellipse cx="{CX}" cy="{JAR_TOP}" rx="{rx}" ry="{rx*PERSP:.1f}" fill="#6D482E" stroke="{INK}" stroke-width="6"/></g>')


def barrel_lid(identifier):
    rx = barrel_width(JAR_TOP)
    return (f'<g id="{identifier}"><ellipse cx="{CX}" cy="{JAR_TOP-7}" rx="{rx}" ry="{rx*PERSP:.1f}" '
            f'fill="#AE7749" stroke="{INK}" stroke-width="6"/>'
            f'<path d="M390 508h300 M420 492h240" stroke="#68442C" stroke-width="4"/></g>')
