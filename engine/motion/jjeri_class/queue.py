"""Adapter for the approved drinks production queue."""
from pathlib import Path
import json
import re
import subprocess

from engine import config
from engine.drinks_render import RenderError, Rendered
from .build import render, run
from .evidence import EvidenceError


def render_job(job, work, *, tts):
    renderer = job.get("renderer")
    episode = (job.get("plan") or {}).get(renderer)
    anatomy = renderer == "jjeri_anatomy"
    if job.get("format") != "video" or not isinstance(episode, dict):
        raise RenderError("jjeri_directive_missing", "승인된 영상 제작안에 선택한 째리 형식의 지시서가 없습니다")
    if tts != "edge" or job.get("spend_approval_id"):
        raise RenderError("jjeri_free_voice_required", "째리 모션에는 무료 Edge 음성이 필요합니다")
    evidence = {
        "approved": True,  # drinks_start_render and the worker heartbeat check the approved immutable revision
        "selected_claim_ids": (job.get("brief") or {}).get("selected_claim_ids"),
        "claims": job.get("claims"),
        "sources": job.get("sources"),
    }
    try:
        if anatomy:
            from engine.jjeri_anatomy.build import render as render_anatomy

            result = render_anatomy(episode, work, evidence)
        else:
            result = render(episode, work, evidence=evidence)
    except EvidenceError as exc:
        raise RenderError(exc.code, str(exc)) from exc
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RenderError("jjeri_render_failed", str(exc)[-1200:]) from exc

    mp4 = result["mp4"]
    meta = json.loads(run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", mp4).stdout)
    width, height, fps = (meta["streams"][0][key] for key in ("width", "height", "r_frame_rate"))
    duration = float(meta["format"]["duration"])
    audio = run("ffmpeg", "-hide_banner", "-i", mp4, "-af", "ebur128=peak=true", "-f", "null", "-").stderr
    summary = audio.rsplit("Summary:", 1)[-1]
    integrated, peak = (float(re.search(pattern, summary)[1])
                        for pattern in (r"I:\s*(-?[\d.]+) LUFS", r"Peak:\s*(-?[\d.]+) dBFS"))
    if ((width, height, fps) != (config.JJERI_VIDEO_WIDTH, config.JJERI_VIDEO_HEIGHT, f"{config.JJERI_VIDEO_FPS}/1")
            or not (config.JJERI_ANATOMY_MIN_RUNTIME if anatomy else config.JJERI_MIN_RUNTIME) <= result["duration"] <= config.JJERI_MAX_RUNTIME
            or abs(duration - result["duration"]) > config.JJERI_MEDIA_DURATION_TOLERANCE
            or not config.JJERI_AUDIO_TARGET_RANGE[0] <= integrated <= config.JJERI_AUDIO_TARGET_RANGE[1]
            or peak > config.JJERI_AUDIO_MAX_TRUE_PEAK):
        raise RenderError("jjeri_media_qa_failed", f"{width}×{height} {fps}, {duration:.3f}s, {integrated} LUFS, {peak} dBTP")
    cover = str(Path(work) / "jjeri-cover.jpg")
    run("ffmpeg", "-y", "-v", "error", "-i", mp4, "-frames:v", "1", cover)
    return Rendered(
        [
            {"path": mp4, "role": "final_video", "position": 1, "mime": "video/mp4",
             "width": width, "height": height, "duration_ms": round(duration * 1000)},
            {"path": cover, "role": "cover", "position": 1, "mime": "image/jpeg", "width": width, "height": height},
        ],
        {
            "renderer": renderer, "warnings": [*result["warnings"], "jjeri_human_source_review_required"],
            "duration_sec": duration, "width": width, "height": height, "fps": config.JJERI_VIDEO_FPS,
            "audio": {"lufs": integrated, "true_peak_dbtp": peak},
            "evidence": result["evidence"], "timeline": result["timeline"],
            "caption_draft": result["caption_draft"],
            "rights": {"art": "Sooljjerigo SVG", "bgm": "owned_code_synth", "sfx": "Pixabay Content License",
                       "track": config.JJERI_OWNED_TRACK},
        },
        [
            {"kind": "tts", "provider": "edge", "model": config.JJERI_VOICE, "cost_usd": 0,
             "units": sum(len(scene["beats"]) for scene in episode["worlds" if anatomy else "scenes"])},
            {"kind": "render", "provider": "local_hyperframes", "model": config.MOTION_HYPERFRAMES_PKG,
             "cost_usd": 0, "note": renderer},
        ],
    )
