"""Build the registered Jjeri anatomy layouts from an episode and measured speech."""
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import shutil

from engine import config, hf_render
from engine.motion.jjeri_class.build import _host, _synthesize
from .layout import render_world, overlay

ROOT = Path(hf_render.ROOT)
TEMPLATE = Path(hf_render.TEMPLATE_DIR) / "jjeri-anatomy"
REFERENCE = ROOT / "assets/templates/jjeri-anatomy"
LAYOUT = {"vessel_cutaway": "jar", "barrel_cutaway": "jar", "strain": "sieve", "serve": "glass", "vessel_closed": "quiz"}
EVENTS = {
    "jar": ("lid_off", "shell_away", "drop_tokens", "drop_part", "pour", "hud_ramp", "camera",
            "legend", "token_morph", "token_morph", "bubbles_rise", "boom", "hud", "camera",
            "settle", "ladle_scoop", "brace", "camera"),
    "sieve": ("camera", "pour", "hands_rub", "boom", "token_break", "camera", "fill"),
    "glass": ("bubbles_rise", "boom", "chips", "tokens_merge", "camera_pan", "dial_needle"),
    "quiz": ("quiz", "loop_return"),
}
# Explicit compatibility for the captured episode. The export labeled these as
# speech-relative, but the authoring builder placed them relative to screen entry.
SAMPLE_WORLD_ORIGIN = {"jar": {0, 1}, "sieve": set(range(7)), "glass": {0, 1}, "quiz": {0}}


def load_sample():
    return json.loads((REFERENCE / "episode.example.json").read_text(encoding="utf8"))


def read_manifest():
    return json.loads((TEMPLATE / "sample-voice.json").read_text(encoding="utf8"))


def validate_structure(episode):
    if episode.get("format") != "jjeri_anatomy" or episode.get("version") != 1:
        raise ValueError("format_invalid")
    ws = episode["worlds"]
    kinds = [LAYOUT.get(w["world"]) for w in ws]
    if not 2 <= len(kinds) <= 5 or kinds[0] != 'jar' or kinds[-1] != 'quiz' or any(k not in ('sieve','glass') for k in kinds[1:-1]):
        raise ValueError("layout_sequence_invalid")
    ids = [w["id"] for w in ws]
    if len(set(ids)) != len(ids) or not all(re.fullmatch(r"[a-z][a-z0-9_-]{0,35}", i) for i in ids):
        raise ValueError("world_id_invalid")
    if any(i in ("frame","main","root","bgm") or re.fullmatch(r"(?:vo|sfx)\d+",i) for i in ids):
        raise ValueError("world_id_reserved")
    for key, w in zip(kinds, ws):
        required_slots = {"jar":5,"sieve":1,"glass":3,"quiz":1}[key]
        if len(w["beats"]) != required_slots or [e["do"] for e in w["events"]] != list(EVENTS[key]):
            raise ValueError(f"event_sequence_invalid: {key}")
        for e in w["events"]:
            if type(e["beat"]) is not int or not 0 <= e["beat"] < len(w["beats"]):
                raise ValueError("beat_reference_invalid")
            if type(e["at"]) not in (float, int) or not -30 <= e["at"] <= 30:
                raise ValueError("event_offset_invalid")
            if e["do"] == "camera":
                if not 0.1 <= e["scale"] <= 3 or not 0.01 <= e["dur"] <= 5:
                    raise ValueError("camera_invalid")
                if "focus" in e and (len(e["focus"]) != 2 or not all(type(x) in (float, int) and 0 <= x <= 1920 for x in e["focus"])):
                    raise ValueError("focus_invalid")
    for c in episode["chapters"]:
        if c["world"] not in ids or type(c["beat"]) is not int or not 0 <= c["beat"] < len(ws[ids.index(c["world"])]["beats"]):
            raise ValueError("chapter_reference_invalid")
    clip = episode["window"]
    if not 424 <= clip["clip_top"] < clip["clip_bottom"] <= 1036 or any(type(clip[k]) is not int for k in ("clip_top","clip_bottom")):
        raise ValueError("window_invalid")
    for keyword in episode["keywords"]:
        if not keyword["word"] or not re.fullmatch(r"#[0-9a-fA-F]{6}", keyword["color"]):
            raise ValueError("keyword_invalid")
    jar = ws[0]
    expected_vessel = "oak_barrel" if jar["world"] == "barrel_cutaway" else "onggi"
    if jar["vessel"] != expected_vessel or type(jar["tokens"]["count"]) is not int or not 1 <= jar["tokens"]["count"] <= 48:
        raise ValueError("vessel_or_count_invalid")
    if len(jar["tokens"]["chain"]) != 4 or not all(re.fullmatch(r"(grain|sugar|drop|bubble):[^:\n]{1,12}", t) for t in jar["tokens"]["chain"]):
        raise ValueError("token_invalid")
    if [layer["id"] for layer in jar["layers"]] != ["water","mash","top","lees"]:
        raise ValueError("layer_invalid")
    parts = [
        {"plate","shell","cutaway","lid","ladle","cup"},
        {"plate","bowl","sieve","small_jar","hands"},
        {"plate","tumbler","dial"},
    ]
    for w, key in zip(ws,kinds):
        if key == "quiz":
            continue
        expected = parts[("jar","sieve","glass").index(key)]
        names = [part.split("(",1)[0] for part in w["parts"]]
        if set(names) != expected or len(names) != len(expected):
            raise ValueError("part_invalid")
    layer_ids = {layer["id"]: layer for layer in jar["layers"]}
    for layer in layer_ids.values():
        y,bottom=layer["top"],layer.get("bottom", 962)
        if type(y) is not int or type(bottom) is not int or not 560<=y<bottom<=962:
            raise ValueError("layer_range_invalid")
    if layer_ids["top"]["bottom"] != layer_ids["lees"]["top"]:
        raise ValueError("layer_boundary_invalid")
    hud=jar["hud"]
    if len(hud["steps"]) != 5 or not all(isinstance(t,str) and 0<len(t)<=24 for t in hud["steps"]):
        raise ValueError("hud_steps_invalid")
    for e in (item for w in ws for item in w["events"]):
        action=e["do"]
        if action=="dial_needle":
            v=e["value"]
            lo,hi=e["range"]
            a,b=e["band"]
            if any(type(n) is not int for n in (v,lo,hi,a,b)) or not 0<=lo<=a<=v<=b<=hi<=15 or len(e["chips"])!=2:
                raise ValueError("dial_invalid")
        if action in ("chips","tokens_merge") and len(e["items"])!=(2 if action=="chips" else 3):
            raise ValueError("event_items_invalid")
        if action=="hands_rub" and (type(e["times"]) is not int or not 1<=e["times"]<=10):
            raise ValueError("hands_rub_invalid")
        if action=="camera_pan" and (type(e["dx"]) not in (int,float) or not -1080<=e["dx"]<=0 or not .1<=e["dur"]<=3):
            raise ValueError("camera_pan_invalid")
        if action=="bubbles_rise" and "repeat" in e and (type(e["repeat"]) is not int or not 0<=e["repeat"]<=5):
            raise ValueError("bubbles_invalid")
    quiz = ws[-1]["quiz"]
    if not 1 <= quiz["answer"] <= len(quiz["options"]) == 3:
        raise ValueError("quiz_invalid")


def schedule(episode, voice, *, sample=False):
    starts, captions, bt, dur, ev, chapters = {}, {}, {}, {}, {}, []
    total = 0
    k = 0
    for i, world in enumerate(episode["worlds"]):
        key = world["id"]
        role = LAYOUT[world["world"]]
        starts[key] = round(total, 2)
        t = config.JJERI_FIRST_LEAD if i == 0 else config.JJERI_LEAD
        captions[key] = []
        for b, beat in enumerate(world["beats"]):
            row = voice[k]
            speech = round(row["end"] - row["head"], 3)
            if not speech > 0:
                raise ValueError("empty_voice")
            captions[key].append([beat["text"], round(t,3), None, row])
            t += round(speech + config.JJERI_GAP + (config.JJERI_ANATOMY_JAR_BEAT_GAP if role == "jar" and b == 2 else 0), 3)
            k += 1
        for a,b in zip(captions[key],captions[key][1:]):
            a[2] = b[1]
        dur[key] = round(max(config.JJERI_ANATOMY_MIN_WORLD.get(role,0), t + (config.JJERI_ANATOMY_QUIZ_TAIL if role == "quiz" else config.JJERI_TAIL)),2)
        bt[key] = [c[1] for c in captions[key]]
        total += dur[key]
        rules = defaultdict(list)
        for n,event in enumerate(world["events"]):
            origin = event.get("origin","beat")
            if sample and n in SAMPLE_WORLD_ORIGIN.get(role,()):
                origin = "world"
            if origin not in ("world", "beat") or event.get("from_end") not in (None, True, False):
                raise ValueError("origin_invalid")
            base = dur[key] if event.get("from_end") else (0 if origin == "world" else bt[key][event["beat"]])
            position = round(base + event["at"], 3)
            if not 0 <= position < dur[key]:
                raise ValueError("event_out_of_world")
            rules[event["do"]].append(dict(event, time=position))
        ev[key] = rules
    for c in episode["chapters"]:
        key = c["world"]
        start = 0 if not chapters else starts[key] + (0 if sample and c["beat"] == 0 else bt[key][c["beat"]])
        chapters.append((round(start,2),c["title"]))
    return starts, captions, bt, dur, ev, chapters, round(total,2)


def _voice(episode, project, mode):
    saved = read_manifest() if mode in ("golden", "owned_sample") else None
    voice = []
    directory = project / "assets/vo"
    directory.mkdir(parents=True)
    for k, beat in enumerate(b for w in episode["worlds"] for b in w["beats"]):
        path = directory / f"b{k:02}.mp3"
        if saved:
            row = saved[k]
            clip = REFERENCE / "assets/vo" / path.name
            if row["k"] != k or row["text"] != beat["text"] or sha256(clip.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("sample_voice_mismatch")
            shutil.copy2(clip, path)
        else:
            try:
                sec, head, end = _synthesize(beat["text"], path)
            except Exception as exc:
                raise ValueError("anatomy_voice_failed") from exc
            row = {"sec":sec,"head":head,"end":end,"k":k}
        voice.append(dict(row, file=f"assets/vo/{path.name}"))
    if saved and len(saved) != len(voice):
        raise ValueError("sample_voice_count")
    return voice


def sfx_cues(start, bt, events, roles):
    result = []
    for world,role in roles.items():
        base=start[world]
        def event(verb, n=0):
            return base+events[world][verb][n]["time"]
        boom = events[world].get("boom", [{}])[0]
        audio_boom = boom.get("sfx_peak_target")
        def boom_sound(name):
            return (name,event("boom")) if audio_boom is None else (name,audio_boom,True)
        if role=="jar":
            result.extend([
                ("whoosh-short",event("lid_off")+.1),("click-soft",event("drop_tokens")+.5),
                ("click-soft",event("drop_part")+.5),("riser",event("hud_ramp")+.1),
                ("whoosh",event("camera")),boom_sound("pop"),("sparkle",base+bt[world][3]+.1),
                ("whoosh-short",event("camera",1)),("pop",event("ladle_scoop")+.8),
            ])
        elif role=="sieve":
            result.extend([("whoosh",base),boom_sound("click")])
        elif role=="glass":
            result.extend([boom_sound("pop"),("whoosh-short",event("camera_pan")),("impact-bass-1",event("dial_needle")+.8)])
        else:
            result.extend([("pop",event("quiz")),("click-soft",event("quiz")+.5)])
    return result


def _assets(project):
    for name in ("fonts","img","sfx"):
        shutil.copytree(REFERENCE/"assets"/name, project/"assets"/name)
    lib = project/"assets/lib"
    lib.mkdir()
    shutil.copy2(Path(hf_render.TEMPLATE_DIR)/"meme-beat/assets/lib/gsap.min.js", lib)
    shutil.copy2(TEMPLATE/"hyperframes.json", project)


def build(episode, project, *, mode="production", evidence=None):
    if mode not in ("production", "golden", "owned_sample"):
        raise ValueError("mode_invalid")
    validate_structure(episode)
    qa = {}
    if mode == "production":
        from .evidence import audit
        qa = audit(episode, evidence)
    project = Path(project)
    project.mkdir(parents=True, exist_ok=False)
    _assets(project)
    voice = _voice(episode,project,mode)
    return assemble(episode,project,voice,mode,qa=qa)


def assemble(episode, project, voice, mode, *, qa=None):
    starts, captions, bt, durations, events, chapters, total = schedule(episode,voice,sample=mode!="production")
    specs = {w["id"]:w for w in episode["worlds"]}
    roles = {wid:LAYOUT[w["world"]] for wid,w in specs.items()}
    opening_id = next(iter(specs))
    original_events = {w:{v:[r["time"] for r in rows] for v,rows in vs.items()} for w,vs in events.items()}
    hud_step = events[opening_id]["hud_ramp"][0].get("step_sec", config.JJERI_HUD_REPLAY_STEP)
    music = None
    accents = []
    if mode != "golden":
        from engine import jjeri_music
        music = jjeri_music.render_bed(project,total)
        accents = jjeri_music.align_anatomy(events, starts, bt, durations, music, roles)
    clip = episode["window"]
    keywords=[(k["word"],k["color"]) for k in episode["keywords"]]
    scenes={
        wid:render_world(roles[wid], spec, events[wid], bt[wid], durations[wid], captions[wid],
                         keywords, (clip["clip_top"],clip["clip_bottom"]), wid==opening_id,
                         hud_step,2 if mode=="golden" else 6,specs[opening_id])
        for wid,spec in specs.items()
    }
    scenes["frame"] = overlay(chapters,starts,captions,list(starts),total,episode["topic"])
    comps = project/"compositions"
    comps.mkdir()
    labels = (qa or {}).get("source_labels_by_world", {})
    for key, html in scenes.items():
        names = list(dict.fromkeys(labels.get(specs.get(key, {}).get("id"), {}).values()))
        if names:
            label = " · ".join(names)
            if len(label) > 33:
                raise ValueError("source_chip_overflow")
            chip = ('<span style="position:absolute;left:86px;top:995px;padding:4px 12px;color:#fff;'
                    'background:#1F2A44;border-radius:12px;font-size:30px">'
                    f'{escape(label)}</span>')
            html = html.replace('<div class="capbox">', chip + '<div class="capbox">', 1)
        (comps/f"{key}.html").write_text(html,encoding="utf8")
    stage = [f'<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">',
             _host("frame",0,total).replace('data-track-index="1"','data-track-index="0"').replace('z-index:2','z-index:1')]
    for key,start in starts.items():
        stage.append(_host(key,start,durations[key]))
        for _,at,_,row in captions[key]:
            stage.append(f'<audio id="vo{row["k"]:02}" class="clip" src="{row["file"]}" data-start="{round(start+at,3)}" '
                         f'data-duration="{round(row["end"]-row["head"],3)}" data-media-start="{row["head"]}" data-track-index="3" data-volume="1"></audio>')
    cues = []
    for i,cue in enumerate(sfx_cues(starts,bt,events,roles)):
        name,at,*aligned=cue
        peak, length, volume = (config.JJERI_GOLDEN_ANATOMY_SFX if mode=="golden" else config.JJERI_SFX)[name]
        start = max(0,round(at-peak+(0 if aligned else 1/config.JJERI_VIDEO_FPS),3))
        length = min(length,round(total-start,3))
        stage.append(f'<audio id="sfx{i:02}" class="clip" src="assets/sfx/{name}.mp3" data-start="{start}" '
                     f'data-duration="{length}" data-track-index="{10+i}" data-volume="{volume}"></audio>')
        cues.append({"sound":name,"event":round(at,6),"clip_start":start,"reference_peak":peak})
    if music:
        from engine.jjeri_music import audio_tag
        stage.append(audio_tag(music))
    stage.append("</div>")
    html=(TEMPLATE/"index.template.html").read_text(encoding="utf8").replace("{{STAGE}}","\n".join(stage))
    (project/"index.html").write_text(html,encoding="utf8")
    result = {"total":total,"worlds":[{"id":specs[w]["id"],"start":starts[w],"dur":durations[w],
                         "beats":[{"k":c[3]["k"],"start_local":c[1],"speech":round(c[3]["end"]-c[3]["head"],3),
                                   "media_start":c[3]["head"]} for c in captions[w]]} for w in starts],
              "events_original":original_events,"events":events,"chapters":chapters,"sfx":cues,"music":music,
              "accents":accents,"evidence":qa or {}}
    (project/"timeline.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    return result


def render(episode, work, evidence):
    """Audited queue entry. It cannot select an offline fixture mode."""
    folder = Path(work)
    project = folder / "anatomy-project"
    timeline = build(episode, project, evidence=evidence)
    (folder / "check.log").write_text(hf_render.check_project(project), encoding="utf8")
    output = folder / "jjeri-anatomy.mp4"
    hf_render.render_project(project, output, timeline["total"], loudnorm=config.JJERI_LOUDNORM)
    return {"mp4":str(output), "duration":timeline["total"], "timeline":timeline,
            "warnings":[], "evidence":timeline["evidence"], "caption_draft":""}
