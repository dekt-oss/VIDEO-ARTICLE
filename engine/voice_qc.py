"""목소리 이상(피치 튐·톤 들쭉날쭉) 숫자 검사 — 사람이 못 듣는 대신 잰다(0원). 자기상관 f0(16kHz, 40ms 창).
제미나이 TTS 가 문장마다 따로 합성돼 가끔 피치가 튄다(사케 1편 2026-11-28). 점수가 config.GEMINI_TTS_QC_LIMIT 를 넘으면 다시 받는다."""
import subprocess
import numpy as np

from . import config


def f0_track(path):
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 's16le', '-ac', '1', '-ar', '16000', '-'], capture_output=True).stdout
    x = np.frombuffer(pcm, np.int16).astype(float) / 32768
    out = []
    for i in range(0, len(x) - 640, 320):
        fr = x[i:i + 640] - x[i:i + 640].mean()
        if np.sqrt((fr ** 2).mean()) < config.VOICE_QC_SILENCE_RMS:
            out.append(0.0); continue
        ac = np.correlate(fr, fr, 'full')[639:]
        lo, hi = 16000 // config.VOICE_QC_F0_MAX_HZ, 16000 // config.VOICE_QC_F0_MIN_HZ
        k = lo + int(np.argmax(ac[lo:hi]))
        out.append(16000 / k if ac[k] > config.VOICE_QC_VOICED_CORR * ac[0] else 0.0)
    return np.array(out)


def stats(path, ref):
    """(중앙 f0, ref 대비 1.5배 넘게 높은 구간이 가장 길게 이어진 초)."""
    v = f0_track(path); vv = v[v > 0]
    med = float(np.median(vv)) if len(vv) else 0.0
    run = best = 0
    for f in v:
        run = run + 1 if f > ref * config.VOICE_QC_HIGH_RATIO else 0
        best = max(best, run)
    return med, best * 0.02


def score(path, ref):
    med, high = stats(path, ref)
    return high + abs(np.log(med / ref)) if med else 9.0


if __name__ == '__main__':
    import sys
    meds = [stats(p, 1)[0] for p in sys.argv[1:]]
    ref = float(np.median(meds))
    for p, m in zip(sys.argv[1:], meds):
        print(p.split('/')[-1], '중앙 %.0fHz' % m, '높게 튄 최장 %.2f초' % stats(p, ref)[1], '점수 %.2f' % score(p, ref))
    print('기준 %.0fHz' % ref)
