"""Replay the canonical episode with local voice assets and compare its golden frames."""
from argparse import ArgumentParser
from array import array
import json
from pathlib import Path
import re
import runpy
import subprocess

from engine.motion.jjeri_class import render
from engine.motion.jjeri_class.build import run, spoken

SAMPLE = Path(__file__).resolve().parents[1] / "assets" / "templates" / "jjeri-class"


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    episode = json.loads((SAMPLE / "episode.example.json").read_text(encoding="utf-8"))
    reference_beats = runpy.run_path(str(SAMPLE / "tools" / "script.py"))["BEATS"]
    directive_beats = [(scene["id"], spoken(beat["text"])) for scene in episode["scenes"] for beat in scene["beats"]]
    if directive_beats != [(sid, spoken(text)) for sid, text in reference_beats]:
        raise ValueError("fixture narration and subtitle text differ")
    truth = json.loads((SAMPLE / "timeline.json").read_text(encoding="utf-8"))
    info = render(episode, args.output, voice_assets=SAMPLE / "assets" / "vo")
    compare(info, args.output, truth)


def compare(info, output, truth):
    mp4 = info["mp4"]
    differences = []
    for expected, actual in zip(truth["scenes"], info["timeline"]["scenes"], strict=True):
        delta = round(actual["start"] - expected["start"], 3)
        differences.append({"scene": actual["id"], "start_delta": delta})
        if actual["id"] != expected["id"] or abs(delta) > 0.05:
            raise ValueError(f"timeline mismatch: {actual['id']} {delta:+.3f}s")
    pairs = output / "golden-comparison"
    pairs.mkdir(exist_ok=True)
    run("ffmpeg", "-y", "-v", "error", "-i", mp4, "-frames:v", "1",
        "-vf", "scale=540:-2", str(pairs / "first-frame.jpg"))
    frames = []
    for golden in sorted((SAMPLE / "golden").glob("t*.jpg")):
        at = float(golden.stem[1:])
        actual = pairs / golden.name
        run("ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", mp4, "-frames:v", "1",
            "-vf", "scale=540:-2", str(actual))
        compare = run("ffmpeg", "-hide_banner", "-i", str(golden), "-i", str(actual),
                      "-lavfi", "ssim", "-f", "null", "-")
        similarity = float(re.search(r"All:([\d.]+)", compare.stderr)[1])
        run("ffmpeg", "-y", "-v", "error", "-i", str(golden), "-i", str(actual),
            "-lavfi", "hstack", "-frames:v", "1", str(pairs / f"pair-{golden.name}"))
        frames.append({"time": at, "ssim": similarity})
    audio = run("ffmpeg", "-hide_banner", "-i", mp4, "-af", "ebur128=peak=true", "-f", "null", "-").stderr
    audio_summary = audio.rsplit("Summary:", 1)[-1].strip()
    probe = run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=width,height,r_frame_rate:format=duration", "-of", "json", mp4)
    pcm = subprocess.check_output(["ffmpeg", "-v", "error", "-i", mp4, "-vn", "-f", "s16le", "pipe:1"])
    samples = array("h")
    samples.frombytes(pcm)
    if not samples:
        raise ValueError("no audio samples")
    clipped = samples.count(32767) + samples.count(-32768)
    evidence = {"clipped_pcm_samples": clipped, "video": json.loads(probe.stdout), "starts": differences, "goldens": frames,
                "audio": audio_summary}
    (output / "comparison.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    if clipped:
        raise ValueError(f"audio clipping: {clipped} PCM samples")
    return evidence


if __name__ == "__main__":
    main()

