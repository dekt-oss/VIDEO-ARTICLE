"""Slot-driven compositions in the Jjeri class visual style."""
from html import escape
import random
import re

from engine import config
from .art import (
    AMBER, AX, AY, CLEAR, CREAM, FONTS, GRAIN_D, GRAIN_L, INK, MAHO,
    NAVY, TOMATO, WOOD_D, WOOD_L, YEL, anise, arrow, barrel, bottle,
    caramel, cherries, glass, grapes, plum, smoke, vanilla,
)

COLORS = {"amber": AMBER, "mahogany": MAHO, "clear": CLEAR, "blend": "#C0612A", "deep": "#A8461B", "sherry": "#7A1F2B"}
NOTES = {"vanilla": vanilla, "caramel": caramel, "smoke": smoke, "star_anise": anise,
         "grapes": grapes, "plum": plum, "cherries": cherries}
TONES = {"tomato": "tom", "yellow": "yel", "grey": "grey", "amber": "amber", "mahogany": "maho"}


def safe(text):
    # Reserve @scene@ for composition-local IDs.
    return escape(text).replace("@", "&#64;")


def accent(text, colors, heading=False):
    words = sorted(colors, key=len, reverse=True)
    patterns = [re.escape(word) for word in words]
    if heading:
        patterns.append(r"\bvs\b")
    if not patterns:
        return safe(text)
    pattern = "(" + "|".join(patterns) + ")"
    return "".join(
        f'<b style="color:{colors[part]}">{safe(part)}</b>' if part in colors and not heading
        else f'<span style="color:{colors[part]}">{safe(part)}</span>' if part in colors
        else '<span class="vs">vs</span>' if heading and part == "vs"
        else safe(part)
        for part in re.split(pattern, text)
    )


def draw(spec, identifier, x, y, scale, *, level=0.5, line="#E8EEF8", tint=None):
    name = spec["icon"]
    if name == "glass":
        return glass(identifier, x, y, scale, COLORS[spec.get("liquid", "clear")], level, line)
    if name == "barrel":
        wood, grain = (WOOD_D, GRAIN_D) if spec.get("wood") == "dark" else (WOOD_L, GRAIN_L)
        return barrel(identifier, x, y, scale, wood, grain, tint)
    if name == "bottle":
        return bottle(identifier, x, y, scale, spec.get("label", ""))
    if name == "arrow":
        return arrow(identifier, x, y, x + 85 * scale, y, line)
    if name == "charred_plank":
        return plank(identifier)
    return NOTES[name](identifier, x, y, scale)


def lookup(spec):
    name, _, variant = spec.partition(":")
    if name in ("glass", "glass_small"):
        return {"icon": "glass", "liquid": variant or "clear"}
    if name == "barrel":
        return {"icon": name, "wood": variant or "light"}
    return {"icon": name}


def scene_tag(item):
    tag_data = item.get("tag")
    return tag("@scene@-tag", tag_data["text"], "t-" + TONES[tag_data["tone"]]) if tag_data else ""


def plank(identifier):
    crackle = "".join(f'<path d="M{x} 334 l10 12 l-8 10 l12 14" fill="none" stroke="#4A3A32" stroke-width="3"/>' for x in range(130, 840, 46))
    grain = "".join(f'<path d="M100 {y} C300 {y - 14} 500 {y + 14} 860 {y - 4}" fill="none" stroke="{GRAIN_L}" stroke-width="4"/>' for y in (395, 420, 445))
    return (f'<rect x="100" y="330" width="760" height="140" rx="12" fill="{WOOD_L}" stroke="#3B2412" stroke-width="6"/>{grain}'
            f'<rect x="103" y="333" width="754" height="40" fill="#1B1310"/>{crackle}'
            f'<rect id="{identifier}" x="103" y="370" width="754" height="6" fill="#F97316"/>')


# ---------- html 부품 ----------
def chip(i, text, cx, cy, cls='c-yel'):
    """화면 좌표 (cx, cy) 가운데에 칩. 바깥 상자는 고정, 안쪽 span 만 움직인다."""
    return f'<div class="chipbox" style="left:{cx - 300}px; top:{cy - 30}px;"><span id="{i}" class="chip {cls}">{safe(text)}</span></div>'


def tag(i, text, cls='t-yel'):
    return f'<div class="tagbox"><span id="{i}" class="tag {cls}">{safe(text)}</span></div>'


CSS = f"""
    {FONTS}
    #root {{ position: absolute; inset: 0; overflow: hidden; font-family: 'Pretendard'; color: {NAVY}; }}
    .art {{ position: absolute; left: {AX}px; top: {AY}px; width: 960px; height: 580px; overflow: visible; }}
    .capbox {{ position: absolute; left: 296px; width: 720px; top: 1052px; height: 176px; }}
    .captext {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center; font-weight: 800; font-size: 42px; line-height: 1.42; letter-spacing: -0.02em; color: {NAVY}; opacity: 0; }}
    .src {{ position: absolute; left: 84px; width: 912px; top: 996px; text-align: right; }}
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
    src_html = f'<div class="src"><span id="{sid}-src">{safe(src)}</span></div>' if src else ''
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
_scene_v2 = scene


def scene(sid, body, js, extra_css='', src=None):
    i = body.find('<div class="capbox">')
    stage, rest = (body[:i], body[i:]) if i >= 0 else (body, '')
    return _scene_v2(sid, f'<div class="stage">{stage}</div>' + rest, js, extra_css, src)


def type_js(prefix, text, t0, step=config.JJERI_TYPE_INTERVAL):
    return '\n    '.join(f'tl.set("#{prefix}{k}", {{ opacity: 1 }}, {round(t0 + k * step, 3)});' for k in range(len(text)))


def type_spans(prefix, text):
    return ''.join(f'<span id="{prefix}{k}">{"&nbsp;" if ch == " " else safe(ch)}</span>' for k, ch in enumerate(text))




def parts(body, events, extra_css=""):
    return body, events, extra_css


def composition(item, schedule, keywords, first, stamp_at=None):
    sid = "@scene@"
    render_scene = TEMPLATES[item["template"]]
    beats = [beat["start_local"] for beat in schedule["beats"]]
    options = {"stamp_at": stamp_at} if item["template"] == "truth_infuse_stamp" else {}
    body, events, selectors, extra_css, sounds, stamp = render_scene(item, beats, **options)
    if item.get("tag"):
        body = scene_tag(item) + body
        events.append(pop("#@scene@-tag", 0.05))
        selectors.append("#@scene@-tag")
    captions, caption_ids = [], []
    for index, (beat, timing) in enumerate(zip(item["beats"], schedule["beats"])):
        identifier = f"{sid}-cap{index}"
        text = accent(beat["text"], keywords).replace("\n", "<br>")
        captions.append(f'<div id="{identifier}" class="captext"><span>{text}</span></div>')
        caption_ids.append(f"#{identifier}")
        start = timing["start_local"]
        if first and index == 0:
            events.append(f'tl.set("#{identifier}", {{ opacity: 1 }}, 0);')
        else:
            events.append(f'tl.fromTo("#{identifier}", {{ opacity: 0, scale: 0.96, filter: "blur(8px)" }}, {{ opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.2, ease: "power4.out" }}, {start});')
        if index + 1 < len(schedule["beats"]):
            end = round(schedule["beats"][index + 1]["start_local"] - 0.12, 3)
            events.append(f'tl.to("#{identifier}", {{ opacity: 0, filter: "blur(6px)", duration: 0.12, ease: "power2.in" }}, {end});')
    source = item.get("source_chip")
    if source:
        selectors.append("#@scene@-src")
    if not first:
        events.insert(0, art_in(sid))
    if item["template"] != "vote_comment" or not item["slots"]["loop_to_first_frame"]:
        events.append(art_out(sid, schedule["dur"], selectors + caption_ids))
    content = scene(sid, body + '<div class="capbox">' + "".join(captions) + "</div>",
                    "\n    ".join(events), extra_css, source)
    identifier = item["id"]
    content = content.replace("@scene@-", f"jjeri-{identifier}--").replace("@scene@", identifier)
    return content, sounds, stamp


def slide(identifier, at):
    return f'tl.fromTo("#{identifier}", {{ opacity: 0, x: -20 }}, {{ opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }}, {at});'


def keys(query, at):
    return [("key-press", at + k * config.JJERI_TYPE_INTERVAL)
            for k, character in enumerate(query) if not character.isspace()]


def label_line(text, y, emphasis):
    font, weight, size, color = ("Wanted Sans", 800, 34, MAHO) if emphasis else ("Pretendard", 700, 30, NAVY)
    return f'<text x="170" y="{y}" text-anchor="middle" font-family="{font}" font-weight="{weight}" font-size="{size}" fill="{color}">{safe(text)}</text>'


def glass_pair_question(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    left, right = s["left"], s["right"]
    sounds = [("pop", 1.0), ("click-soft", 1.6)]
    body, events, extra_css = parts(
        art('@scene@', glass('@scene@-gA', 165, 50, 1.45, COLORS[left["liquid"]], 0.42) + glass('@scene@-gB', 505, 50, 1.45, COLORS[right["liquid"]], 0.42))
        + chip('@scene@-nA', left["label"], AX + 310, AY + 495, 'c-amber') + chip('@scene@-nB', right["label"], AX + 650, AY + 495, 'c-maho')
        + chip('@scene@-qA', left["question"], AX + 200, AY + 32, 'c-cream') + chip('@scene@-qB', right["question"], AX + 770, AY + 32, 'c-cream'),
        [
            pop('#@scene@-qA', 1.0, -4), pop('#@scene@-qB', 1.6, 4),
            'tl.fromTo("#@scene@-gA", { rotation: 0 }, { rotation: -4, duration: 0.3, ease: "power2.out", transformOrigin: "50% 100%" }, 1.0);',
            'tl.fromTo("#@scene@-gB", { rotation: 0 }, { rotation: 4, duration: 0.3, ease: "power2.out", transformOrigin: "50% 100%" }, 1.6);',
        ])
    return body, events, ['#@scene@-qA', '#@scene@-qB', '#@scene@-nA', '#@scene@-nB'], extra_css, sounds, stamp


def myth_question(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    body, events, extra_css = parts(
        art('@scene@', draw(s["from"], "@scene@-g", 110, 140, 1.15, level=0.45) + arrow('@scene@-ar', 370, 330, 480, 330)
              + draw(s["to"], "@scene@-b", 520, 70, 1.35)
              + f'<g transform="translate(895 150)"><text id="@scene@-q" font-family="Wanted Sans" font-weight="800" font-size="140" fill="{TOMATO}" text-anchor="middle" x="0" y="40">?</text></g>')
        + chip('@scene@-c1', s["from"]["label"], AX + 225, AY + 500, 'c-cream') + chip('@scene@-c2', s["to"]["label"], AX + 682, AY + 520, 'c-yel'),
        [
            'tl.fromTo("#@scene@-g", { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.5, ease: "expo.out" }, 0.1);',
            'tl.fromTo("#@scene@-ar", { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, 0.6);',
            'tl.fromTo("#@scene@-b", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.55, ease: "back.out(1.4)" }, 0.3);',
            pop('#@scene@-c1', 0.9), pop('#@scene@-q', 2.0, 8), pop('#@scene@-c2', 2.4),
        ])
    return body, events, ['#@scene@-c1', '#@scene@-c2'], extra_css, sounds, stamp


def truth_infuse_stamp(item, b, stamp_at=None):
    s = item["slots"]
    sounds, stamp = [], None
    rng = random.Random(7)
    particles = [
        (f"@scene@-p{k}", 300 if k % 2 == 0 else 660, 130 + k * 37 % 340,
         (1 if k % 2 == 0 else -1) * rng.randint(70, 150), round(0.6 + k * 0.13 % 2.0, 2))
        for k in range(18)
    ]
    grain = ''.join(f'<path d="M{x} 70 C{x - 8} 180 {x + 8} 300 {x} 520" fill="none" stroke="{GRAIN_L}" stroke-width="4"/>' for x in (248, 266, 694, 712))
    liquid_from = COLORS[s["from_color"]]
    liquid_to = "#E39B2F" if s["to_color"] == "amber" else COLORS[s["to_color"]]
    picture = (f'<rect x="230" y="50" width="500" height="490" rx="46" fill="{WOOD_L}" stroke="#3B2412" stroke-width="6"/>{grain}'
               f'<rect id="@scene@-liq" x="290" y="100" width="380" height="390" rx="24" fill="{liquid_from}"/>'
               '<rect x="290" y="100" width="380" height="390" rx="24" fill="none" stroke="#1B1310" stroke-width="12"/>'
               + ''.join(f'<circle id="{i}" cx="{x}" cy="{y}" r="8" fill="{COLORS[s["to_color"]]}" opacity="0"/>' for i, x, y, _, _ in particles))
    anchor = b[s["stamp_on_beat"]]
    stamp = round(anchor + 0.5, 2) if stamp_at is None else stamp_at
    sounds = [("impact-bass-1", stamp + 0.28)]
    js3 = [pop('#@scene@-c1', 0.4), pop('#@scene@-c2', 0.6),
           f'tl.fromTo("#@scene@-liq", {{ attr: {{ fill: "{liquid_from}" }} }}, {{ attr: {{ fill: "{liquid_to}" }}, duration: 2.6, ease: "power1.inOut" }}, {anchor - 0.6});']
    for i, x, y, dx, t in particles:
        t = round(anchor - 0.8 + t, 2)
        js3.append(f'tl.fromTo("#{i}", {{ x: 0, opacity: 0 }}, {{ x: {dx}, opacity: 1, duration: 0.5, ease: "power2.out" }}, {t});')
        js3.append(f'tl.to("#{i}", {{ opacity: 0, duration: 0.6, ease: "power1.in" }}, {t + 0.5});')
    js3 += [f'tl.fromTo("#@scene@-stamp", {{ scale: 2.2, opacity: 0, rotation: -14 }}, {{ scale: 1, opacity: 1, rotation: -8, duration: 0.28, ease: "power4.in" }}, {stamp});',
            ]
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-c1', s["wall_label"], AX + 120, AY + 160, 'c-cream') + chip('@scene@-c2', s["inside_label"], AX + 480, AY + 60, 'c-cream')
        + f'<div class="stampbox"><span id="@scene@-stamp">{safe(s["stamp"])}</span></div>',
        js3,
        extra_css=f"""
        .stampbox {{ position: absolute; left: 140px; width: 800px; top: 670px; height: 160px; display: flex; align-items: center; justify-content: center; }}
        #@scene@-stamp {{ display: inline-block; font-family: 'Wanted Sans'; font-weight: 800; font-size: 76px; color: {TOMATO}; background: rgba(255,248,238,0.94); border: 7px solid {TOMATO}; border-radius: 16px; padding: 4px 30px; }}""")
    return body, events, ['#@scene@-c1', '#@scene@-c2', '#@scene@-stamp'], extra_css, sounds, stamp


def journey_multiply(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    move, multiply = b[s["move_on_beat"]], b[s["multiply_on_beat"]]
    points = [(712, 250), (712, 62), (300, 250), (300, 62), (560, 62), (560, 250)][:s["multiply_count"]]
    picture = (draw(s["object"], "@scene@-b1", 70, 130, 1.0)
               + f'<path id="@scene@-arc" d="M330 250 Q480 60 640 210" fill="none" stroke="{CREAM}" stroke-width="7" stroke-dasharray="16 14" stroke-linecap="round" opacity="0"/>'
               + ''.join(draw(s["object"], f"@scene@-e{k}", x, y, 0.6) for k, (x, y) in enumerate(points, 1)))
    sounds = [("pop", move + 1.15)]
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-c1', s["from_label"], AX + 190, AY + 470, 'c-cream')
        + chip('@scene@-c2', s["to_label"], AX + 580, AY + 470, 'c-yel')
        + chip('@scene@-c3', s["benefit_chip"], AX + 430, AY + 40, 'c-amber'),
        [
            'tl.fromTo("#@scene@-b1", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.15);',
            pop('#@scene@-c1', 0.7),
            f'tl.fromTo("#@scene@-arc", {{ opacity: 0 }}, {{ opacity: 0.9, duration: 0.3, ease: "power2.out" }}, {move - 0.1});',
            f'tl.to("#@scene@-c1", {{ opacity: 0, duration: 0.15, ease: "power2.in" }}, {move});',
            f'tl.fromTo("#@scene@-b1", {{ x: 0 }}, {{ x: 390, duration: 1.0, ease: "power2.inOut" }}, {move + 0.1});',
            f'tl.to("#@scene@-b1", {{ keyframes: [{{ y: -110, duration: 0.5, ease: "power2.out" }}, {{ y: 0, duration: 0.5, ease: "power2.in" }}] }}, {move + 0.1});',
            f'tl.to("#@scene@-arc", {{ opacity: 0, duration: 0.2 }}, {move + 1.1});',
            pop('#@scene@-c2', move + 1.15),
            *[pop(f'#@scene@-e{k}', multiply + k * 0.2) for k in range(1, len(points) + 1)], pop('#@scene@-c3', multiply + 1.0),
        ])
    return body, events, ['#@scene@-c2', '#@scene@-c3'], extra_css, sounds, stamp


def flavor_rise(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    notes = s["notes"]
    points = [(210, 215, 0.9), (400, 205, 1), (590, 215, 1), (770, 210, 1)]
    picture = draw(s["base"], "@scene@-ember", 360, 330, 1)
    labels, note_events = [], []
    if s["base"]["icon"] == "charred_plank":
        note_events.append('tl.fromTo("#@scene@-ember", { opacity: 0.3 }, { opacity: 1, duration: 0.4, ease: "power1.inOut", yoyo: true, repeat: 7 }, 0.2);')
    for k, (note, (x, y, scale)) in enumerate(zip(notes, points)):
        icon = f"@scene@-i{k}"
        at = b[note["beat"]] + (1.45, 2.25, 1.0, 2.0)[k]
        picture += draw(note, icon, x, y, scale)
        labels.append(chip(f"@scene@-l{k}", note["label"], AX + x, AY + 292, "c-amber"))
        note_events.extend([rise(f"#{icon}", at), pop(f"#@scene@-l{k}", at + 0.25)])
        if note["icon"] == "smoke":
            note_events.append(f'tl.fromTo(".{icon}-w", {{ attr: {{ "stroke-dashoffset": 1 }} }}, {{ attr: {{ "stroke-dashoffset": 0 }}, duration: 0.9, ease: "power2.out", stagger: 0.12 }}, {at});')
        if note["icon"] == "star_anise":
            note_events.append(f'tl.fromTo("#{icon}", {{ rotation: -40 }}, {{ rotation: 0, duration: 0.6, ease: "expo.out", transformOrigin: "50% 50%" }}, {at});')
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-c0', s["base"]["label"], AX + 480, AY + 512, 'c-cream')
        + "".join(labels),
        [pop("#@scene@-c0", .3), *note_events])
    return body, events, ['#@scene@-c0'] + [f"#@scene@-l{k}" for k in range(len(notes))], extra_css, sounds, stamp


def pour_infuse(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    tint = COLORS[s["target"]["tint"]]
    picture = (draw(s["target"], "@scene@-b", 560, 260, 1.0, tint=tint)
               + draw(s["pour"], "@scene@-bt", 120, 60, 1.0)
               + f'<path id="@scene@-st" d="M700 192 C704 215 692 240 680 262" fill="none" stroke="{tint}" stroke-width="12" stroke-linecap="round" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1"/>')
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-c1', s["pour"]["chip"], AX + 180, AY + 470, 'c-cream')
        + chip('@scene@-c2', s["target"]["chip"], AX + 400, AY + 420, 'c-maho')
        + chip('@scene@-c3', s["result_chip"], AX + 680, AY + 410, 'c-yel'),
        [
            'tl.fromTo("#@scene@-b", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.1);',
            pop('#@scene@-c1', 0.4), pop('#@scene@-c2', 0.6),
            'tl.to("#@scene@-c1", { opacity: 0, duration: 0.15 }, 1.9);',
            'tl.fromTo("#@scene@-bt", { x: 0, y: 0, rotation: 0 }, { x: 358, y: -102, rotation: 108, duration: 0.9, ease: "power2.inOut", transformOrigin: "50% 50%" }, 1.0);',
            'tl.fromTo("#@scene@-st", { attr: { "stroke-dashoffset": 1.1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.25, ease: "power2.out" }, 1.85);',
            'tl.fromTo("#@scene@-b-tr", { attr: { y: 300, height: 0 } }, { attr: { y: 0, height: 300 }, duration: 1.6, ease: "power1.inOut" }, 2.0);',
            pop('#@scene@-c3', 2.5),
        ])
    return body, events, ['#@scene@-c2', '#@scene@-c3'], extra_css, sounds, stamp


def fill_and_notes(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    picture = (draw(s["source"], "@scene@-b", 80, 170, 1.0)
               + arrow("@scene@-ar", 345, 320, 445, 320) + glass("@scene@-g", 470, 80, 1.35, CLEAR, 0.45))
    note_events = []
    for k, (note, (x, y, scale, at, rot)) in enumerate(zip(s["notes"], [(840,150,1.05,1.4,-6), (850,360,0.95,1.7,6), (445,110,1,2,-4)])):
        icon = f"@scene@-f{k}"
        picture += draw(note, icon, x, y, scale)
        note_events.append(pop(f"#{icon}", b[note.get("beat", 0)] + at - 0.15, rot))
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-c1', s["chips"][0], AX + 820, AY + 520, 'c-maho') + chip('@scene@-c2', s["chips"][1], AX + 605, AY + 520, 'c-yel'),
        [
            'tl.fromTo("#@scene@-ar", { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, 0.3);',
            f'tl.fromTo("#@scene@-g-liq", {{ attr: {{ fill: "{CLEAR}" }} }}, {{ attr: {{ fill: "{COLORS[s["glass_to"]]}" }}, duration: 1.4, ease: "power1.inOut" }}, 0.5);',
            *note_events, pop('#@scene@-c1', 2.2), pop('#@scene@-c2', 2.9),
        ])
    return body, events, ['#@scene@-c1', '#@scene@-c2'], extra_css, sounds, stamp


def scarcity_compare(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    many, one = s["many"], s["one"]
    picture = (''.join(draw(many, f"@scene@-g{k}", 70 + k % 3 * 130, 110 + k // 3 * 170, 0.5) for k in range(many["count"]))
               + draw(one, "@scene@-sb", 580, 115, 1.15))
    sounds = [("pop", 1.6), ("pop", 2.1)]
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-c1', many["chip"], AX + 265, AY + 490, 'c-amber')
        + chip('@scene@-c2', one["chip"], AX + 718, AY + 490, 'c-maho')
        + chip('@scene@-p1', many["price_level"], AX + 265, AY + 62, 'c-cream') + chip('@scene@-p2', one["price_level"], AX + 718, AY + 62, 'c-tom'),
        [
            *[pop(f'#@scene@-g{k}', 0.1 + k * 0.06) for k in range(many["count"])],
            'tl.fromTo("#@scene@-sb", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.4)" }, 0.5);',
            pop('#@scene@-c1', 0.7), pop('#@scene@-c2', 0.9), pop('#@scene@-p1', 1.6, -4), pop('#@scene@-p2', 2.1, 4),
        ])
    return body, events, ['#@scene@-c1', '#@scene@-c2', '#@scene@-p1', '#@scene@-p2'], extra_css, sounds, stamp


def two_methods(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    rows = s["rows"]
    layouts = [
        [(280, 70, .75, .35), (480, 215, .55, .6), (520, 135, .75, .8), (625, 195, .76, 1.1), (710, 70, .75, 1.3)],
        [(280, 330, .75, 2.35), (445, 450, .71, 2.6), (520, 360, .6, 2.8), (675, 450, .65, 3.1), (745, 330, .75, 3.3)],
    ]
    picture, step_events = '', []
    for row_index, (row, positions) in enumerate(zip(rows, layouts)):
        for i, (step, (x, y, scale, at)) in enumerate(zip(row["steps"], positions)):
            sid = f"@scene@-row{row_index}-{i}"
            if step == "+":
                picture += f'<text id="{sid}" x="{x}" y="{y}" font-family="Wanted Sans" font-weight="800" font-size="72" fill="{CREAM}" text-anchor="middle">+</text>'
            elif step == "→":
                picture += arrow(sid, x, y, x + round(scale * 85), y)
            else:
                scale = 0.45 if step.startswith("glass_small:") else scale
                picture += draw(lookup(step), sid, x, y, scale, level=0.5 if i == 4 else 0.45)
            step_events.append(slide(sid, at) if step == "→" else pop(f"#{sid}", at))
    body, events, extra_css = parts(
        art('@scene@', picture)
        + chip('@scene@-l1', rows[0]["label"], AX + 130, AY + 195, 'c-cream') + chip('@scene@-l2', rows[1]["label"], AX + 130, AY + 450, 'c-cream'),
        [pop("#@scene@-l1", .2), pop("#@scene@-l2", 2.2), *step_events])
    return body, events, ['#@scene@-l1', '#@scene@-l2'], extra_css, sounds, stamp


def recap_board(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    picture = f'<rect x="20" y="20" width="920" height="560" rx="24" fill="{CREAM}" stroke="{INK}" stroke-width="5"/>'
    labels, note_events, extra_selectors = [], [], []
    positions = {
        1: [(530, 210, 0.8, 530, 210)],
        2: [(420, 210, 0.85, 420, 210), (645, 135, 0.45, 690, 210)],
        3: [(390, 215, .6, 390, 215), (560, 210, .65, 560, 210), (730, 230, .55, 730, 230)],
    }
    for row_index, row in enumerate(s["rows"]):
        y = row_index * 200
        at = row_index * 2.2
        sid = f"@scene@-row{row_index}"
        picture += draw(row["subject"], f"{sid}-subject", 90, 150+y, .42)
        picture += arrow(f"{sid}-arrow", 220, 212+y, 290, 212+y, NAVY)
        labels.append(chip(f"{sid}-label", row["subject"]["chip"], AX+140, AY+302+y, ("c-amber","c-maho")[row_index]))
        extra_selectors.append(f"#{sid}-label")
        note_events.extend([pop(f"#{sid}-subject", at+.4), pop(f"#{sid}-label", at+.5), slide(f"{sid}-arrow", at+.7)])
        for k, ((icon, label), (x, iy, scale, cx, _)) in enumerate(zip(row["items"], positions[len(row["items"])])):
            picture += draw(lookup(icon), f"{sid}-item{k}", x, iy+y, scale, line=NAVY)
            labels.append(chip(f"{sid}-note{k}", label, AX+cx, AY+302+y, "c-cream"))
            extra_selectors.append(f"#{sid}-note{k}")
            delta = k * (.25 if row_index == 0 else .3)
            note_events.extend([pop(f"#{sid}-item{k}", at+.9+delta), pop(f"#{sid}-note{k}", at+1+delta)])
    if s.get("exception_chip"):
        at = b[s["exception_on_beat"]] + .3
        labels.append(chip("@scene@-ex", s["exception_chip"], AX+760, AY+76, "c-tom"))
        note_events.append(pop("#@scene@-ex", at, 4))
        extra_selectors.append("#@scene@-ex")
        sounds = [("pop", at)]
    body, events, extra_css = parts(art("@scene@", picture) + "".join(labels), note_events)
    return body, events, extra_selectors, extra_css, sounds, stamp


def house_rule_search(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    query = s["search"]["query"]
    anchor = b[s["search"]["on_beat"]]
    type_at = round(anchor + config.JJERI_SEARCH_DELAY, 2)
    sounds = keys(query, type_at)
    label = s["label"]
    ys = (312, 370, 410)
    label_lines = ''.join(label_line(value, ys[i], i > 0) for i, value in enumerate(label["lines"]))
    circled = [ys[i] for i in label["circle_lines"]]
    ring_y = (min(circled) + max(circled)) / 2 - 10
    ring_ry = (max(circled) - min(circled)) / 2 + 34
    s11_art = (f'''<g transform="translate(70 20)"><g id="@scene@-bot">
          <rect x="130" y="0" width="80" height="44" rx="8" fill="#3B2412"/>
          <path d="M140 40 L200 40 L200 130 C200 150 260 160 260 200 L260 520 C260 540 246 552 226 552 L114 552 C94 552 80 540 80 520 L80 200 C80 160 140 150 140 130 Z" fill="#B8662A" fill-opacity="0.92" stroke="#3B2412" stroke-width="6"/>
          <path d="M102 220 L102 500" stroke="#fff" stroke-opacity="0.28" stroke-width="10" stroke-linecap="round"/>
          <rect x="96" y="270" width="148" height="200" rx="10" fill="{CREAM}" stroke="#3B2412" stroke-width="4"/>
          {label_lines}
          <ellipse id="@scene@-ring" cx="170" cy="{ring_y:g}" rx="92" ry="{ring_ry:g}" fill="none" stroke="{TOMATO}" stroke-width="8" pathLength="1" stroke-dasharray="1 1.2" stroke-dashoffset="1.1"/>
        </g></g>''')
    body, events, extra_css = parts(
        art('@scene@', s11_art)
        + chip('@scene@-c1', label["chip"], AX + 240, AY + 30, 'c-yel')
        + f'''<div class="search" id="@scene@-bar"><div class="hint">{safe(s["search"]["hint"])}</div>
          <svg width="52" height="52" viewBox="0 0 52 52"><circle cx="22" cy="22" r="15" fill="none" stroke="#C2410C" stroke-width="6"/><path d="M33 33 L46 46" stroke="#C2410C" stroke-width="7" stroke-linecap="round"/></svg>
          <div class="q">{type_spans("@scene@-k", query)}</div><div class="cur" id="@scene@-cur"></div></div>'''
        + chip('@scene@-c2', s["search"]["after_chip"], AX + 650, AY + 420, 'c-tom'),
        [
            'tl.fromTo("#@scene@-bot", { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: "expo.out" }, 0.1);',
            pop('#@scene@-c1', 0.5),
            'tl.fromTo("#@scene@-ring", { attr: { "stroke-dashoffset": 1.1 } }, { attr: { "stroke-dashoffset": 0 }, duration: 0.6, ease: "power2.out" }, 1.2);',
            f'tl.fromTo("#@scene@-bar", {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.5)" }}, {anchor + 0.2});',
            f'tl.fromTo("#@scene@-cur", {{ opacity: 1 }}, {{ opacity: 0, duration: 0.25, ease: "none", yoyo: true, repeat: 9 }}, {anchor + 0.5});',
            type_js('@scene@-k', query, type_at),
            pop('#@scene@-c2', round(type_at + len(query) * config.JJERI_TYPE_INTERVAL + config.JJERI_SEARCH_CHIP_DELAY, 2)),
        ])
    return body, events, ['#@scene@-c1', '#@scene@-bar', '#@scene@-c2'], extra_css, sounds, stamp


def vote_comment(item, b):
    s = item["slots"]
    sounds, stamp = [], None
    left, right = s["left"], s["right"]
    query = s["comment"]
    type_at = config.JJERI_VOTE_INPUT_AT
    sounds = [("pop", .5), ("click-soft", 1.0), *keys(query, type_at)]
    body, events, extra_css = parts(
        art('@scene@', glass('@scene@-gA', 205, 60, 1.2, COLORS[left["liquid"]], 0.42) + glass('@scene@-gB', 515, 60, 1.2, COLORS[right["liquid"]], 0.42))
        + chip('@scene@-nA', left["label"], AX + 325, AY + 40, 'c-amber') + chip('@scene@-nB', right["label"], AX + 635, AY + 40, 'c-maho')
        + f'<div class="cbox" id="@scene@-box"><div class="lab">댓글</div><div class="q">{type_spans("@scene@-k", query)}</div></div>',
        [
            pop('#@scene@-nA', 0.5, -4), pop('#@scene@-nB', 1.0, 4),
            f'tl.fromTo("#@scene@-box", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.4, ease: "expo.out" }}, {type_at - 0.5});',
            type_js('@scene@-k', query, type_at),
        ])
    return body, events, ['#@scene@-nA', '#@scene@-nB', '#@scene@-box'], extra_css, sounds, stamp


TEMPLATES = {
    "glass_pair_question": glass_pair_question,
    "myth_question": myth_question,
    "truth_infuse_stamp": truth_infuse_stamp,
    "journey_multiply": journey_multiply,
    "flavor_rise": flavor_rise,
    "pour_infuse": pour_infuse,
    "fill_and_notes": fill_and_notes,
    "scarcity_compare": scarcity_compare,
    "two_methods": two_methods,
    "recap_board": recap_board,
    "house_rule_search": house_rule_search,
    "vote_comment": vote_comment,
}
