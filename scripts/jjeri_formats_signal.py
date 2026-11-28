"""Compare candidate event PTS to decoded video and filtered audio evidence."""
from array import array
from html.parser import HTMLParser
from io import BytesIO
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageStat
from statistics import mean

from engine import config

from scripts.jjeri_formats_evidence import run, pts

RATE=config.JJERI_SFX_ANALYSIS_RATE
HUD=(20,112,103,124)  # Text box only, at the diagnostic scale (270×480).
FPS=config.JJERI_VIDEO_FPS
BOXES={"jar":(120,122,247,167),"sieve":(120,117,250,160),"glass":(120,142,253,185),
       "s3":(40,148,235,220)}
SFX={"jar":"pop","sieve":"click","glass":"pop"}


class Tags(HTMLParser):
    def __init__(self,page):
        super().__init__()
        self.sounds=[]
        self.feed(page)

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="audio" and attrs["id"].startswith("sfx"):
            self.sounds.append(attrs)


def samples(path, filters):
    values=array("h")
    values.frombytes(run("ffmpeg","-v","error","-i",str(path),"-vn","-ar",str(RATE),"-ac","1",
                         "-af",filters,"-f","s16le","pipe:1").stdout)
    return values


def match(reference, tracked, at, expected, half_width=.035):
    center=round(at*RATE)
    width=round(half_width*RATE)
    lo=max(0,center-width)
    hi=min(len(reference),center+width)
    template=reference[lo:hi]
    if not template or not any(template):
        return None
    power=sum(x*x for x in template)
    origin=round(expected*RATE)-(center-lo)
    options=[]
    for delay in range(-round(.06*RATE),round(.06*RATE)+1,4):
        offset=origin+delay
        if offset<0 or offset+len(template)>len(tracked):
            continue
        target=tracked[offset:offset+len(template)]
        denom=math.sqrt(power*sum(x*x for x in target))
        if denom:
            options.append((sum(x*y for x,y in zip(template,target))/denom,delay))
    if not options:
        return None
    confidence,shift=max(options)
    zero=dict((d,c) for c,d in options).get(0)
    rivals=[c for c,d in options if abs(d-shift)>round(.012*RATE)]
    contrast=confidence-max(rivals,default=-1)
    return {"center":round(expected+shift/RATE,6),"correlation":round(confidence,4),
            "zero_shift_correlation":round(zero,4) if zero is not None else None,
            "contrast":round(contrast,4), "shift_ms":shift/RATE*1000,
            "reliable_candidate":confidence>=.8 and contrast>=.08}


def energy_peak(clip, length=None):
    end = min(len(clip), round(length*RATE)) if length is not None else len(clip)
    width = round(config.JJERI_ENERGY_WINDOW*RATE)
    hop = round(config.JJERI_ENERGY_HOP*RATE)
    peak = max(range(0,end-width,hop), key=lambda i: sum(x*x for x in clip[i:i+width]))
    return (peak+width/2)/RATE


def onset_proxy(clip, grid):
    """Largest 2 ms rise in the 100 Hz high-passed waveform within ±12 ms.

    Record a source transient and an authored grid separately. Listening is
    still required to judge which transient sounds like the start of the beat.
    """
    center=round(grid*RATE)
    hop=round(.001*RATE)
    width=2*hop
    def energy(i):
        return sum(x*x for x in clip[max(0,i):max(0,i+width)])
    best=max(range(center-12*hop,center+13*hop,hop),key=lambda i:energy(i)-energy(i-width))
    return best/RATE


def frame(mp4,at,box):
    f=run("ffmpeg","-v","error","-ss",f"{max(0,at-.00002):.6f}","-i",str(mp4),"-frames:v","1","-vf","scale=270:-2",
          "-f","image2pipe","-vcodec","png","pipe:1")
    return Image.open(BytesIO(f.stdout)).convert("L").crop(box)


def distance(a,b):
    return ImageStat.Stat(ImageChops.difference(a,b)).mean[0]


def visual(mp4,at,box,video_pts):
    near=[p for p in video_pts if at-.075<=p<=at+.18]
    imgs=[frame(mp4,p,box) for p in near]
    if len(imgs)<4:
        return None
    baseline,settled=imgs[0],imgs[-1]
    change=distance(baseline,settled)
    first=next((p for p,img in zip(near,imgs) if distance(img,baseline)>max(3,change*.25)
                and distance(img,settled)<change*.8),None)
    return {"roi_delta":round(change,2),"first_detectable_roi_change_pts":first}


def hud_visual(mp4, at, video_pts):
    # The next HUD stage is at least 0.45 seconds away. Use an interior
    # exemplar of this stage and the preceding text box as the control.
    near=[p for p in video_pts if at-.11<=p<=at+.18]
    if len(near)<5:
        return None
    imgs=[frame(mp4,p,HUD) for p in near]
    baseline,settled=imgs[0],imgs[-1]
    separation=distance(baseline,settled)
    first=next((p for p,img in zip(near,imgs)
                if distance(img,settled)<max(1.5,separation*.3)
                and distance(img,baseline)>separation*.65),None)
    return {"roi_delta":round(separation,2),"first_detectable_roi_change_pts":first}


def summary(values):
    return {"n":len(values),"min_ms":round(min(values)*1000,3),
            "mean_ms":round(mean(values)*1000,3),"max_ms":round(max(values)*1000,3)}


def main():
    project,video,dest=map(Path,sys.argv[1:])
    timeline=json.loads((project/"timeline.json").read_text(encoding="utf8"))
    stems=Tags((project/"index.html").read_text(encoding="utf8")).sounds
    source=project/"assets/music/owned-bed.wav"
    music=samples(source,config.JJERI_BASS_FILTER)
    onset_stem=samples(source,"highpass=f=100")
    actual_bass=samples(video,config.JJERI_BASS_FILTER)
    actual_percussion=samples(video,config.JJERI_SFX_FILTER)
    video_pts=pts(video,"v:0")
    records=[]
    all_peaks=timeline["music"]["detected_bass_peaks"]
    all_grid=timeline["music"]["authored_beat_grid"]
    onsets=[onset_proxy(onset_stem, t) for t in all_grid]
    controls=[]
    for grille,peak in zip(all_grid,all_peaks):
        result=match(music,actual_bass,peak,peak,.042)
        if result and result["reliable_candidate"] and (result["zero_shift_correlation"] or 0)>=.94:
            controls.append({"grid":grille,"source_peak":peak,**result})
    for cue in timeline["accents"]:
        event=cue["event"]
        target=cue["after"]
        peak=cue["measured_bass_peak"]
        index=all_peaks.index(peak)
        grid,onset=all_grid[index],onsets[index]
        world=cue.get("world") or cue["scene"]
        is_hud=event.startswith("hud")
        box=BOXES.get(world)
        sound=SFX.get(world) if event=="boom" else "impact-bass-1" if event=="stamp" else None
        percussion=None
        if sound:
            stem=min((t for t in stems if Path(t["src"]).stem==sound),
                     key=lambda t:abs(float(t["data-start"])-target))
            clip=samples(project/stem["src"],config.JJERI_SFX_FILTER)
            source_peak=energy_peak(clip,float(stem["data-duration"]))
            scheduled=float(stem["data-start"])+source_peak
            percussion={"file":stem["src"],"source_peak":source_peak,
                        "config_peak":config.JJERI_SFX[sound][0],
                        "scheduled_peak":scheduled,
                        "decoded_mix_candidate":match(clip,actual_percussion,source_peak,scheduled)}
        mix=match(music,actual_bass,peak,peak,.042)
        roi=hud_visual(video,target,video_pts) if is_hud else visual(video,target,box,video_pts) if box else None
        vp=roi["first_detectable_roi_change_pts"] if roi else None
        delta=vp-peak if vp is not None else None
        onset_delta=vp-onset if vp is not None else None
        nominal_delta=vp-grid if vp is not None else None
        sfx_candidate=percussion["decoded_mix_candidate"] if percussion else None
        records.append({**cue,"source_bass_peak":peak,"source_onset_proxy":onset,"authored_grid":grid,
                        "decoded_mix_beat_candidate":mix,"visual_roi":roi,
                        "visual_minus_source_peak_sec":delta,"visual_minus_onset_proxy_sec":onset_delta,
                        "visual_minus_grid_sec":nominal_delta,
                        "within_one_frame":max(abs(delta),abs(onset_delta),abs(nominal_delta))<=1/FPS if vp is not None else None,
                        "sfx_minus_visual_sec":sfx_candidate["center"]-vp if sfx_candidate and vp is not None else None,
                        "sfx_minus_source_peak_sec":sfx_candidate["center"]-peak if sfx_candidate else None,
                        "sfx_minus_onset_proxy_sec":sfx_candidate["center"]-onset if sfx_candidate else None,
                        "percussion":percussion})
    data={"reference_stats":{"bass_peak_minus_grid":summary([p-g for p,g in zip(all_peaks,all_grid)]),
                             "onset_proxy_minus_grid":summary([o-g for o,g in zip(onsets,all_grid)]),
                             "clean_mix_controls":controls},
          "records":records}
    dest.write_text(json.dumps(data,indent=2),encoding="utf8")
    print(dest,[(r["event"],r["within_one_frame"]) for r in records])


if __name__=="__main__":
    main()
