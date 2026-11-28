"""Build and render a local Jjeri HyperFrames project."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import re
import shutil
import subprocess

from engine import config, hf_render, jjeri_music
from .compositions import composition
from .schema import validate_episode
from .stage import frame_html, index_html
from .timeline import build_timeline

TEMPLATE = Path(hf_render.TEMPLATE_DIR) / 'jjeri-class'

ASSETS = Path(__file__).resolve().parents[3] / "assets" / "templates" / "jjeri-class" / "assets"


def run(*args, cwd=None, timeout=None, env=None):
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)
    if proc.returncode:
        raise RuntimeError(f"{args[0]} failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-3500:]}")
    return proc


def spoken(text):
    return " ".join(text.replace("·", ", ").split())


def voice_span(path):
    duration = float(run("ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(path)).stdout.strip())
    log = run("ffmpeg", "-hide_banner", "-i", str(path), "-af",
              f"silencedetect=noise={config.JJERI_SILENCE_DB}:d={config.JJERI_SILENCE_SEC}",
              "-f", "null", "-").stderr
    spans = [(kind, float(value)) for kind, value in
             re.findall(r"silence_(start|end):\s*(-?[\d.]+)", log)]
    head = 0.0
    end = duration
    if len(spans) >= 2 and spans[0][1] <= config.JJERI_AUDIO_SPAN_TOLERANCE:
        head = spans[1][1]
    if len(spans) >= 2 and spans[-1][0] == "end" and spans[-1][1] >= duration - config.JJERI_SILENCE_TAIL_TOLERANCE:
        end = spans[-2][1]
    if end <= head or duration <= 0:
        raise ValueError("voice contains no audible speech")
    return round(duration, 3), round(max(0, head - config.JJERI_VOICE_HEAD_PAD), 3), round(min(duration, end + config.JJERI_VOICE_TAIL_PAD), 3)


def _synthesize(text, path):
    import edge_tts

    raw = path.with_suffix(".raw.mp3")
    for attempt in range(config.JJERI_TTS_RETRIES + 1):
        try:
            asyncio.run(edge_tts.Communicate(spoken(text), config.JJERI_VOICE,
                                             rate=config.JJERI_RATE).save(str(raw)))
            if not raw.is_file() or raw.stat().st_size == 0:
                raise ValueError("TTS returned an empty file")
            break
        except Exception as exc:
            if attempt == config.JJERI_TTS_RETRIES:
                raise RuntimeError("Jjeri TTS failed after retries") from exc
        finally:
            if raw.is_file() and raw.stat().st_size == 0:
                raw.unlink()
    run("ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af",
        f"atempo={config.JJERI_ATEMPO}", "-b:a", config.JJERI_VOICE_MP3_BITRATE, str(path))
    raw.unlink()
    return voice_span(path)


def _prepare_voices(episode, project, fixture):
    directory = project / "assets" / "vo"
    directory.mkdir()
    manifest = None
    fixture = Path(fixture).resolve() if fixture else None
    if fixture:
        manifest = json.loads((fixture / "vo.json").read_text(encoding="utf-8"))
    lines = [(scene["id"], beat["text"]) for scene in episode["scenes"] for beat in scene["beats"]]
    if manifest is not None and len(manifest) != len(lines):
        raise ValueError("voice fixture count does not match beats")
    rows = []
    for k, (sid, text) in enumerate(lines):
        path = directory / f"b{k:02d}.mp3"
        if manifest is None:
            sec, head, end = _synthesize(text, path)
        else:
            voice = manifest[k]
            file = PurePosixPath(voice["file"])
            if (voice.get("sid") != sid or voice.get("k") != k
                    or file.parts != ("assets", "vo", path.name)):
                raise ValueError(f"invalid voice fixture at beat {k}")
            shutil.copyfile(fixture / path.name, path)
            measured, _, _ = voice_span(path)
            sec, head, end = (voice[key] for key in ("sec", "head", "end"))
            if abs(measured - sec) > config.JJERI_AUDIO_SPAN_TOLERANCE:
                raise ValueError(f"voice fixture duration mismatch at beat {k}")
        rows.append({"k": k, "sid": sid, "head": head, "end": end, "sec": sec})
    return rows


def _host(identifier, start, duration):
    return (f'<div id="{identifier}" data-composition-id="{identifier}" '
            f'data-composition-src="compositions/{identifier}.html" data-start="{start}" '
            f'data-duration="{duration}" data-track-index="1" data-track-kind="graphics" '
            f'data-width="1080" data-height="1920" style="z-index:2"></div>')


def _sound_tag(index, sound, at, total, *, golden=False):
    peak, duration, volume = (config.JJERI_GOLDEN_CLASS_SFX if golden else config.JJERI_SFX)[sound]
    start = max(0, round(at - peak + 1 / config.JJERI_VIDEO_FPS, 3))
    duration = min(duration, round(total - start, 3))
    if duration <= 0:
        return ""
    return (f'<audio id="sfx{index:02d}" class="clip" src="assets/sfx/{sound}.mp3" '
            f'data-start="{start}" data-duration="{duration}" data-track-index="{10 + index}" '
            f'data-volume="{volume}"></audio>')


def build_project(episode, project, *, voice_assets=None, evidence=None, own_bed=False):
    audit = {}
    if voice_assets is None:
        from .evidence import audit_episode
        from .evidence import MUSIC_CREDIT

        credit = f"음악: 술째리고 자체곡 ({jjeri_music.TRACK})" if own_bed else MUSIC_CREDIT
        episode, audit = audit_episode(episode, evidence, music_credit=credit)
    else:
        errors = validate_episode(episode, replay=True)
        if errors:
            raise ValueError(", ".join(errors))
    project = Path(project)
    compositions = project / "compositions"
    compositions.mkdir(parents=True)
    for name in ("fonts", "img", "sfx") + (() if own_bed else ("bgm",)):
        shutil.copytree(ASSETS / name, project / "assets" / name)
    lib = project / "assets/lib"
    lib.mkdir()
    shutil.copy2(Path(hf_render.TEMPLATE_DIR) / "meme-beat/assets/lib/gsap.min.js", lib)
    shutil.copy2(TEMPLATE / "hyperframes.json", project)
    voices = _prepare_voices(episode, project, voice_assets)
    timeline = build_timeline(episode, voices)
    total = timeline["total"]
    music = jjeri_music.render_bed(project,total) if own_bed else None
    accents = []
    if not config.JJERI_MIN_RUNTIME <= total <= config.JJERI_MAX_RUNTIME:
        raise ValueError(f"duration_invalid: {total}s")

    keywords = {item["word"]: item["color"] for item in episode["keywords"]}
    hosts, vocals, sounds, stamps, warnings = [], [], [], [], []
    chapter_ids = {c["from_scene"] for c in episode["chapters"]}
    transition = 0
    for i, (item, scene) in enumerate(zip(episode["scenes"], timeline["scenes"])):
        sid, start = scene["id"], scene["start"]
        stamp_at = None
        if music and item["template"] == "truth_infuse_stamp":
            beat_index = item["slots"]["stamp_on_beat"]
            beats = [b["start_local"] for b in scene["beats"]]
            before = start + round(beats[beat_index] + config.JJERI_STAMP_OFFSET, 2)
            boundary = start + (beats[beat_index + 1] if beat_index+1 < len(beats) else scene["dur"])
            target, peak, reason = jjeri_music.accent(before, start+beats[beat_index], boundary, music["detected_bass_peaks"], reveal_lag=config.JJERI_STAMP_VISIBLE_LAG)
            stamp_at = round(target-start,6)
            accents.append({"scene":sid,"event":"stamp","before":before,"after":target,
                            "measured_bass_peak":peak,"decision":reason})
        html, local_sounds, stamp = composition(item, scene, keywords, first=i == 0, stamp_at=stamp_at)
        (compositions / f"{sid}.html").write_text(html, encoding="utf-8")
        hosts.append(_host(sid, start, scene["dur"]))
        if i and sid in chapter_ids and item["template"] not in {"myth_question", "scarcity_compare", "house_rule_search", "vote_comment"}:
            sounds.append(("whoosh-short" if transition % 2 else "whoosh", start))
            transition += 1
        sounds.extend((name, start + offset) for name, offset in local_sounds)
        if stamp is not None:
            stamps.append(start + stamp)
        if item["template"] == "recap_board" and not item["slots"].get("exception_chip"):
            warnings.append(f"{sid}: recap_exception_missing")
        for beat in scene["beats"]:
            k = beat["k"]
            vocals.append(f'<audio id="vo{k:02d}" class="clip" src="assets/vo/b{k:02d}.mp3" '
                          f'data-start="{round(start + beat["start_local"], 3)}" data-duration="{beat["speech"]}" '
                          f'data-media-start="{beat["media_start"]}" data-track-index="3" data-volume="1"></audio>')

    (compositions / "frame.html").write_text(frame_html(episode, timeline, stamps), encoding="utf-8")
    effects = [_sound_tag(i, name, at, total, golden=not own_bed) for i, (name, at) in enumerate(sounds)]
    bgm = jjeri_music.audio_tag(music) if music else (
        f'<audio id="bgm" class="clip" src="assets/bgm/bed.mp3" data-start="0" data-duration="{total}" '
        f'data-track-index="9" data-volume="{config.JJERI_BGM_VOLUME}" data-fade-in="{config.JJERI_BGM_FADE_IN}" '
        f'data-fade-out="{config.JJERI_BGM_FADE_OUT}"></audio>')
    (project / "index.html").write_text(index_html(total, "\n".join(hosts), "\n".join(vocals),
                                                  "\n".join(effects), bgm), encoding="utf-8")
    timeline["music"] = music
    timeline["accents"] = accents
    timeline["sounds"] = sounds
    (project / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    return {"duration": total, "timeline": timeline, "warnings": warnings, "evidence": audit, "caption_draft": episode["caption_draft"]}


def build_replay(project, *, own_bed=False):
    from hashlib import sha256

    sample=ASSETS.parent
    episode=json.loads((sample/"episode.example.json").read_text(encoding="utf8"))
    manifest=json.loads((TEMPLATE/"sample-voice.json").read_text(encoding="utf8"))
    lines=[beat["text"] for scene in episode["scenes"] for beat in scene["beats"]]
    if len(lines)!=len(manifest):
        raise ValueError("sample_voice_count")
    for line,row in zip(lines,manifest):
        if row["text"]!=line or sha256((sample/row["file"]).read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError("sample_voice_mismatch")
    return build_project(episode,project,voice_assets=ASSETS/"vo",own_bed=own_bed)["timeline"]


def render(episode, work_dir, *, voice_assets=None, evidence=None):
    """Render audited queued work or replay local fixture audio."""
    work=Path(work_dir).resolve()
    work.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix="jjeri-",dir=work,ignore_cleanup_errors=True) as scratch:
        project=Path(scratch)/"project"
        info=build_project(episode,project,voice_assets=voice_assets,evidence=evidence,
                           own_bed=voice_assets is None)
        (work/"check.log").write_text(hf_render.check_project(project),encoding="utf8")
        output=work/"jjeri-class.mp4"
        probe=hf_render.render_project(project,output,info["duration"], loudnorm=config.JJERI_LOUDNORM)
        (work/"render.log").write_text(json.dumps(probe),encoding="utf8")
    return {"mp4":str(output),**info}
