"""Local owned music and conservative accent alignment for Jjeri."""
from array import array
import math
from pathlib import Path
import wave

from . import config, hf_render

TRACK = config.JJERI_OWNED_TRACK
RATE, CHANNELS = config.JJERI_OWNED_RATE, config.JJERI_OWNED_CHANNELS
FPS = config.JJERI_VIDEO_FPS
SOURCE_FIRST, SOURCE_LAST = config.JJERI_OWNED_SEGMENT
SEAM_SECONDS = config.JJERI_OWNED_SEAM_SECONDS


def _read_wave(path):
    with wave.open(str(path),"rb") as f:
        samples = array("h")
        samples.frombytes(f.readframes(f.getnframes()))
        return samples


def render_bed(project, duration):
    """Cut at PCM frame boundaries, taper joins, and end on a full bar."""
    track = hf_render.load_track(TRACK)
    period = track.beat_period_sec
    bar = 4 * period
    end = math.floor(duration / bar) * bar
    folder = Path(project)/"assets/music"
    folder.mkdir(parents=True, exist_ok=True)
    src = folder/"__source.wav"
    hf_render._run(["ffmpeg","-v","error","-y","-i",track.path,"-ar",str(RATE),"-ac",str(CHANNELS),"-c:a","pcm_s16le",str(src)])
    source = _read_wave(src)
    src.unlink()
    a,b = round(SOURCE_FIRST*RATE),round(SOURCE_LAST*RATE)
    segment = source[a*CHANNELS:b*CHANNELS]
    length = len(segment)//CHANNELS
    if length <= 0 or abs(length/RATE - config.JJERI_OWNED_LOOP_BEATS*period) > 0.001:
        raise ValueError("owned_track_segment_invalid")
    seam = round(SEAM_SECONDS * RATE)
    seam_before = max(abs(segment[c] - segment[-CHANNELS+c]) for c in range(CHANNELS))/32768
    total_frames=round(end*RATE)
    output=array("h")
    for base in range(0,total_frames,length):
        output.extend(segment[:min(length,total_frames-base)*CHANNELS])
    for i in range(total_frames):
        j=i%length
        near=min(j,length-1-j)
        gain=min(1,near/seam,max(0,(total_frames-1-i)/(RATE*hf_render.config.HF_MUSIC_FADE_OUT_SEC)))
        if gain != 1:
            for c in range(CHANNELS):
                index=i*CHANNELS+c
                output[index]=round(output[index]*gain)
    dest=folder/"owned-bed.wav"
    with wave.open(str(dest),"wb") as f:
        f.setparams((CHANNELS,2,RATE,0,"NONE","not compressed"))
        f.writeframes(output.tobytes())
    low=folder/"__low.wav"
    hf_render._run(["ffmpeg","-v","error","-y","-i",str(dest),"-ac","1","-af",
                    config.JJERI_BASS_FILTER,"-c:a","pcm_s16le",str(low)])
    bass=_read_wave(low)
    low.unlink()
    peaks=[]
    grid=[]
    width=round(config.JJERI_ENERGY_WINDOW*RATE)
    hop=round(config.JJERI_ENERGY_HOP*RATE)
    for k in range(math.floor(end/period)):
        nominal=k*period
        i=round(nominal*RATE)
        if end-nominal < config.HF_MUSIC_FADE_OUT_SEC:
            break
        windows=range(max(0,i+round(config.JJERI_BASS_SEARCH[0]*RATE)),
                      min(len(bass)-width,i+round(config.JJERI_BASS_SEARCH[1]*RATE)),hop)
        winner=max(windows,key=lambda j:sum(x*x for x in bass[j:j+width]))
        peaks.append(round((winner+width/2)/RATE,6))
        grid.append(round(nominal,6))
    return {"track":track.key,"rights":"owned_code_synth","period":period,"source_start":SOURCE_FIRST,
            "source_end":SOURCE_LAST,"cut_start_frame":a,"cut_end_frame":b,"sample_rate":RATE,
            "music_duration":total_frames/RATE,"fade_start":max(0,end-config.HF_MUSIC_FADE_OUT_SEC),"loop_seconds":length/RATE,
            "seam_taper_sec":SEAM_SECONDS,"source_seam_step":seam_before,"rendered_seam_step":0,
            "detected_bass_peaks":peaks,"authored_beat_grid":grid,"visual_duration":duration}


def audio_tag(info):
    return (f'<audio id="bgm" class="clip" src="assets/music/owned-bed.wav" data-start="0" '
            f'data-duration="{info["music_duration"]}" data-track-index="9" data-volume="{config.JJERI_BGM_VOLUME}"></audio>')


def nearest(time, peaks):
    if not peaks:
        return time
    return min(peaks,key=lambda point:abs(point-time))


def beat_frame(peak, onset):
    """Minimize the larger distance to the source peak and the authored onset."""
    return round((peak + onset) * FPS / 2) / FPS


def hud_frames(time, peaks, onsets):
    if len(peaks) != len(onsets) or len(peaks) < 4:
        return ()
    first = min(range(len(peaks)), key=lambda i: abs(peaks[i]-time))
    points = list(zip(peaks[first:first+4], onsets[first:first+4]))
    frames = tuple(beat_frame(peak, onset) for peak, onset in points)
    if len(frames) != 4 or any(max(abs(f-p), abs(f-o)) > 1/FPS for f,(p,o) in zip(frames,points)):
        return ()
    return frames


def accent(time, start, end, peaks, *, reveal_lag=0, onsets=()):
    if not peaks:
        return time,time,"no_measured_beat"
    beat = nearest(time+reveal_lag,peaks)
    visible = beat_frame(beat,onsets[peaks.index(beat)]) if onsets else beat
    trigger = visible - reveal_lag
    if abs(trigger-time) > config.JJERI_ACCENT_MAX_SHIFT:
        return time,beat,"outside_shift_limit"
    if not (start + config.JJERI_ACCENT_HEADROOM <= trigger and visible < end - config.JJERI_ACCENT_TAILROOM):
        return time,beat,"outside_same_caption_or_world"
    return trigger,beat,"shifted"


def align_anatomy(events, starts, beat_starts, durations, music, roles):
    rows=[]
    peaks=music["detected_bass_peaks"]
    onsets=music["authored_beat_grid"]
    verbs={"jar":("hud_ramp","hud","boom"),"sieve":("boom",),"glass":("boom","chips"),"quiz":()}
    for world,verb in ((wid,verb) for wid,role in roles.items() for verb in verbs[role]):
        event=events[world][verb][0]
        base=starts[world]
        local=event["time"]
        offsets=[0,*beat_starts[world],durations[world]]
        previous=max(t for t in offsets if t<=local)
        later=min(t for t in offsets if t>local)
        if verb=="hud_ramp":
            frames=hud_frames(base+local,peaks,onsets)
            step=event.get("step_sec",config.JJERI_HUD_REPLAY_STEP)
            limit=base+events[world]["hud"][0]["time"]-config.JJERI_ACCENT_TAILROOM
            if (not frames or abs(frames[0]-(base+local))>config.JJERI_ACCENT_MAX_SHIFT
                    or not base+previous <= frames[0] < base+later or frames[-1]>=limit):
                if base+local+3*step>=limit:
                    raise ValueError("owned_hud_time_insufficient")
                frames=()
            if frames:
                event["owned_stage_times"]=[round(t-base-config.JJERI_HUD_FRAME_LEAD,6) for t in frames]
                event["time"]=event["owned_stage_times"][0]
            for k in range(4):
                source=base+local+k*step
                frame=frames[k] if frames else math.ceil(source*FPS)/FPS
                peak=nearest(frame,peaks)
                rows.append({"world":world,"event":f"hud_stage_{k}","before":source,"after":frame,
                             "measured_bass_peak":peak,"authored_beat_onset":onsets[peaks.index(peak)],
                             "candidate_video_pts":frame,"decision":"per_beat_frame" if frames else "hud_timing_preserved"})
            continue
        if verb=="hud":
            peak=nearest(base+local,peaks)
            onset=onsets[peaks.index(peak)]
            frame=beat_frame(peak,onset)
            lead=config.JJERI_HUD_FRAME_LEAD
            if (abs(frame-(base+local))<=config.JJERI_ACCENT_MAX_SHIFT
                    and base+previous <= frame-lead < base+later-config.JJERI_ACCENT_TAILROOM
                    and max(abs(frame-peak),abs(frame-onset))<=1/FPS):
                event["time"]=round(frame-base-lead,6)
                reason="per_beat_frame"
            else:
                frame=math.ceil((base+local)*FPS)/FPS
                reason="hud_timing_preserved"
            rows.append({"world":world,"event":"hud_stage_4","before":base+local,"after":frame,
                         "measured_bass_peak":peak,"authored_beat_onset":onset,
                         "candidate_video_pts":frame,"decision":reason})
            continue
        lag=config.JJERI_BOOM_VISIBLE_LAG[roles[world]] if verb=="boom" else 0
        duration_margin=1.8 if verb=="chips" else 0
        target,beat,reason=accent(base+local,base+previous,base+later-duration_margin,peaks,reveal_lag=lag,onsets=onsets)
        onset=onsets[peaks.index(beat)]
        if verb=="boom" and reason=="shifted":
            event["sfx_peak_target"]=beat_frame(beat,onset)
        event["time"]=round(target-base,6)
        rows.append({"world":world,"event":verb,"before":base+local,"after":target,
                     "measured_bass_peak":beat,"authored_beat_onset":onset,"reveal_lag":lag,
                     "candidate_video_pts":math.ceil((target+lag)*FPS-1e-9)/FPS,"decision":reason})
    return rows
