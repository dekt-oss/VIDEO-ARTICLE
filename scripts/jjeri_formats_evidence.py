"""Measure saved episode frames and compare the canonical timeline and sound."""
from array import array
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.run(args, capture_output=True, check=True)


def write_frame(mp4, at, out):
    run("ffmpeg","-y","-v","error","-ss",str(at),"-i",str(mp4),"-frames:v","1","-vf","scale=540:-2",str(out))


def pts(mp4, stream):
    result=run("ffprobe","-v","error","-select_streams",stream,"-show_entries","frame=best_effort_timestamp_time","-of","json",str(mp4))
    return [float(row["best_effort_timestamp_time"]) for row in json.loads(result.stdout)["frames"]
            if row.get("best_effort_timestamp_time") not in (None,"N/A")]


def collect(kind, mode, project, mp4, output):
    output.mkdir(parents=True,exist_ok=True)
    reference=Path("assets/templates")/f"jjeri-{kind}"
    truth=json.loads((reference/"timeline.json").read_text(encoding="utf8"))
    timeline=json.loads((project/"timeline.json").read_text(encoding="utf8"))
    key="worlds" if kind=="anatomy" else "scenes"
    starts=[]
    for expected,current in zip(truth[key],timeline[key],strict=True):
        spoken=[]
        for a,b in zip(expected["beats"],current["beats"],strict=True):
            spoken.append({"beat":b["k"],"difference":round(b["start_local"]-a["start_local"],6)})
        starts.append({"id":current["id"],"scene_start_difference":round(current["start"]-expected["start"],6),"beats":spoken})
    video_pts=pts(mp4,"v:0")
    audio_pts=pts(mp4,"a:0")
    pairs=[]
    if mode=="golden":
        for golden in sorted((reference/"golden").glob("t*.jpg")):
            at=float(golden.stem[1:])
            actual=output/golden.name
            write_frame(mp4,at,actual)
            score=run("ffmpeg","-hide_banner","-i",str(golden),"-i",str(actual),"-lavfi","ssim","-f","null","-")
            similarity=float(re.search(rb"All:([\d.]+)",score.stderr)[1])
            run("ffmpeg","-y","-v","error","-i",str(golden),"-i",str(actual),"-lavfi","hstack","-frames:v","1",str(output/f"pair-{golden.name}"))
            pairs.append({"time":at,"ssim":similarity})
    summary=run("ffmpeg","-hide_banner","-i",str(mp4),"-af","ebur128=peak=true","-f","null","-").stderr.decode("utf8","replace")
    pcm=array("h")
    pcm.frombytes(run("ffmpeg","-v","error","-i",str(mp4),"-vn","-f","s16le","pipe:1").stdout)
    accents=[]
    for i,row in enumerate(timeline.get("accents",[])):
        at=row["after"]
        actual=next(t for t in video_pts if t>=at-1e-6)
        if at>.035:
            write_frame(mp4,actual-.033333,output/f"accent-{i:02}-before.jpg")
        write_frame(mp4,actual,output/f"accent-{i:02}-at.jpg")
        write_frame(mp4,actual+.033333,output/f"accent-{i:02}-after.jpg")
        accents.append({**row,"decoded_frame_pts":actual,"pts_minus_measured_bed_peak":round(actual-row["measured_bass_peak"],6),
                        "visual_first_nonzero_opacity":None,"isolated_sfx_in_final_mix":None})
    result={"render":str(mp4.resolve()),"sha256":sha256(mp4.read_bytes()).hexdigest(),"starts":starts,"same_time_frames":pairs,
            "clipping_samples":pcm.count(32767)+pcm.count(-32768),
            "loudness_summary":summary.rsplit("Summary:",1)[-1].strip(),
            "video_pts_bounds":[video_pts[0],video_pts[-1]],"audio_pts_bounds":[audio_pts[0],audio_pts[-1]],
            "accents":accents,"music":timeline.get("music"),"source_sfx_layout":timeline.get("sfx",timeline.get("sounds"))}
    dest=output/"comparison.json"
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    print(dest, min((p["ssim"] for p in pairs),default=None),result["loudness_summary"])


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("kind",choices=("anatomy","class"))
    p.add_argument("mode",choices=("golden","owned"))
    for name in ("project","mp4","output"):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    collect(a.kind,a.mode,a.project,a.mp4,a.output)
