"""Edge TTS(무료)로 문장별 내레이션을 만들고 길이를 vo.json 에 적는다. 다시: python tools/tts.py"""
import asyncio, json, subprocess, sys
from pathlib import Path
import edge_tts
sys.path.insert(0, str(Path(__file__).parent))
from script import BEATS, VOICE, RATE, SPEED, spoken

root = Path(__file__).resolve().parent.parent
vo = root / 'assets' / 'vo'


def speech_span(f, dur):
    """앞뒤 무음을 잰다(-40dB). 파일은 그대로 두고 배치 때 건너뛴다."""
    log = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(f), '-af', 'silencedetect=noise=-40dB:d=0.05', '-f', 'null', '-'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    starts = [float(x.split(': ')[1]) for x in log.splitlines() for x in [x[x.find('silence_start'):]] if x.startswith('silence_start')]
    ends = [float(x.split(' |')[0].split(': ')[1]) for x in log.splitlines() for x in [x[x.find('silence_end'):]] if x.startswith('silence_end')]
    head = ends[0] if starts and starts[0] < 0.01 and ends else 0.0
    end = starts[-1] if starts and starts[-1] > head + 0.3 else dur
    assert 0 <= head < end <= dur + 0.01, (f, head, end, dur)
    return round(max(0.0, head - 0.05), 3), round(min(dur, end + 0.08), 3)


async def main():
    out = []
    for k, (sid, text) in enumerate(BEATS):
        f = vo / f'b{k:02d}.mp3'
        raw = vo / f'_raw{k:02d}.mp3'
        await edge_tts.Communicate(spoken(text), VOICE, rate=RATE).save(str(raw))
        assert raw.stat().st_size > 1000, f'TTS 빈 파일: {k}'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(raw), '-filter:a', f'atempo={SPEED}', '-b:a', '96k', str(f)], check=True)
        raw.unlink()
        d = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(f)]).decode().strip())
        head, end = speech_span(f, d)
        out.append({'k': k, 'sid': sid, 'file': f'assets/vo/b{k:02d}.mp3', 'sec': round(d, 3), 'head': head, 'end': end})
        print(k, sid, round(d, 2), spoken(text))
    (vo / 'vo.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

asyncio.run(main())
