"""HyperFrames markup for the fixed stage, chapter header, and audio tracks."""
from pathlib import Path

from engine import config
from .art import CREAM, FONTS, INK, NAVY, TOMATO, WOOD_D
from .compositions import accent, safe


def frame_html(episode, timeline, stamps):
    starts = {scene["id"]: scene["start"] for scene in timeline["scenes"]}
    chapters = episode["chapters"]
    colors = episode["title_accents"]
    titles = [accent(chapter["title"], colors, heading=True) for chapter in chapters]
    ch_html = "".join(f'<div id="fr-ch{i}" class="ch">{title}</div>' for i, title in enumerate(titles))
    ch_js = []
    for k, chapter in enumerate(chapters):
        at = starts[chapter["from_scene"]]
        if k:
            ch_js.append(f'tl.fromTo("#fr-ch{k}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.22, ease: "power4.out" }}, {at + 0.05:.2f});')
        if k + 1 < len(chapters):
            end = starts[chapters[k + 1]["from_scene"]] - 0.14
            ch_js.append(f'tl.to("#fr-ch{k}", {{ opacity: 0, filter: "blur(6px)", duration: 0.14, ease: "power2.in" }}, {end:.2f});')
    hops = sorted({0.3, *(round(scene["start"] + beat["start_local"], 2)
                           for scene in timeline["scenes"] for beat in scene["beats"] if beat["k"])})
    hop_js = "\n    ".join(
        f'tl.to("#fr-jjeri", {{ keyframes: [{{ y: -22, duration: 0.14, ease: "power2.out" }}, {{ y: 0, duration: 0.2, ease: "power2.in" }}] }}, {at:.2f});'
        for at in hops)
    stamp_js = "\n    ".join(
        f'tl.to("#fr-jjeri", {{ keyframes: [{{ rotation: -10, duration: 0.12, ease: "power2.out" }}, {{ rotation: 0, duration: 0.5, ease: "back.out(2)" }}], transformOrigin: "50% 100%" }}, {at:.2f});'
        for at in stamps)
    counter_grain = "".join(f'<path d="M0 {y} C300 {y - 10} 700 {y + 12} 1080 {y - 4}" fill="none" stroke="#6E3A1C" stroke-width="5"/>' for y in (90, 170, 260, 360, 470))
    series, lesson, topic = (safe(episode[key]) for key in ("series", "episode", "topic"))
    total = timeline["total"]
    return f"""<template>
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
    <div id="fr-badgebox"><span id="fr-badge">{series} {lesson} <small>· {topic}</small></span></div>
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
    {stamp_js}
    {chr(10).join('    ' + j for j in ch_js)}
    tl.set({{}}, {{}}, {total});
    window.__timelines["frame"] = tl;
  </script>
</template>
"""


def index_html(total, hosts, vo_tags, sfx_tags, music=""):
    template = Path(__file__).resolve().parents[3] / "hf_templates/jjeri-class/index.template.html"
    html = template.read_text(encoding="utf8")
    for key, value in (("TOTAL", total), ("HOSTS", hosts), ("VO_TAGS", vo_tags), ("SFX_TAGS", sfx_tags), ("MUSIC", music)):
        html = html.replace("{{" + key + "}}", str(value))
    return html
