"""샘플(막걸리 해부)을 엔진 입력 모양(편 지시서 JSON)으로 내보낸다 → episode.example.json.
사건 시각은 모두 '문장 시작 + 초'(beat, at). 카메라는 초점(focus)·배율(scale)·걸리는 시간(dur).
값은 tools/build.py 의 장면과 같다 — 한쪽을 바꾸면 다른 쪽도 바꾼다."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from script import BEATS, VOICE, RATE, SPEED

root = Path(__file__).resolve().parent.parent
W = {
    'jar': {
        'world': 'vessel_cutaway', 'vessel': 'onggi',
        'parts': ['plate', 'shell(닫힌 바깥)', 'cutaway(안쪽 벽·잘린 벽 두께)', 'lid', 'ladle', 'cup'],
        'layers': [{'id': 'water', 'top': 740, 'fill': 'water'}, {'id': 'mash', 'top': 740, 'fill': 'mash'},
                   {'id': 'top', 'top': 740, 'bottom': 815, 'fill': 'clear', 'label': '맑은 윗술'},
                   {'id': 'lees', 'top': 815, 'fill': 'lees', 'label': '술밑'}],
        'tokens': {'chain': ['grain:전분', 'sugar:단맛', 'drop:술', 'bubble:탄산'], 'count': 22, 'zone': 'lees'},
        'hud': {'kind': 'time_control', 'steps': ['▶ 실제 시간', '⏩ 빨리 감기 ×10', '⏩ 빨리 감기 ×1,000', '⏩ 빨리 감기 ×20,000', '⏸ 다 익음'], 'gauge': '발효'},
        'events': [
            {'beat': 0, 'at': 1.1, 'do': 'lid_off'}, {'beat': 0, 'at': 1.6, 'do': 'shell_away', 'note': '앞 절반이 떨어져 단면'},
            {'beat': 1, 'at': 0.1, 'do': 'drop_tokens', 'token': 'grain', 'label': '전분 든 곡물'},
            {'beat': 1, 'at': 1.4, 'do': 'drop_part', 'part': 'nuruk', 'label': '누룩(곰팡이)'},
            {'beat': 1, 'at': 2.6, 'do': 'pour', 'into': 'water', 'label': '물'},
            {'beat': 2, 'at': 0.0, 'do': 'hud_ramp', 'step_sec': 0.35}, {'beat': 2, 'at': 0.4, 'do': 'camera', 'focus': [540, 880], 'scale': 2.2, 'dur': 1.0},
            {'beat': 2, 'at': 1.0, 'do': 'legend', 'chain': True}, {'beat': 2, 'at': 1.5, 'do': 'token_morph', 'from': 'grain', 'to': 'sugar'},
            {'beat': 2, 'at': 2.7, 'do': 'token_morph', 'from': 'sugar', 'to': 'drop'}, {'beat': 2, 'at': 2.8, 'do': 'bubbles_rise'},
            {'beat': 2, 'at': 3.0, 'do': 'boom', 'text': '보글보글'},
            {'beat': 3, 'at': 0.0, 'do': 'hud', 'step': '⏸ 다 익음'}, {'beat': 3, 'at': 0.0, 'do': 'camera', 'scale': 1, 'dur': 0.8},
            {'beat': 3, 'at': 0.4, 'do': 'settle', 'show_layers': ['top', 'lees']},
            {'beat': 4, 'at': 0.1, 'do': 'ladle_scoop', 'from': 'top', 'to': 'cup', 'label': '청주 = 윗술만'},
            {'beat': 4, 'at': 1.9, 'do': 'brace', 'span': ['top', 'lees'], 'label': '막걸리 = 통째로'},
            {'beat': 4, 'at': -0.9, 'from_end': True, 'do': 'camera', 'focus': [640, 820], 'scale': 1.15, 'dur': 0.8},
        ]},
    'sieve': {
        'world': 'strain', 'parts': ['plate', 'bowl(흰 사발)', 'sieve(대나무 체)', 'small_jar(기운 옹기)', 'hands'],
        'events': [
            {'beat': 0, 'at': 0.0, 'do': 'camera', 'focus': [560, 690], 'scale': 1.45, 'dur': 0.01},
            {'beat': 0, 'at': 0.2, 'do': 'pour', 'into': 'sieve'}, {'beat': 0, 'at': 1.3, 'do': 'hands_rub', 'times': 10},
            {'beat': 0, 'at': 1.4, 'do': 'boom', 'text': '싹싹'}, {'beat': 0, 'at': 1.6, 'do': 'token_break', 'token': 'grain', 'through': 'mesh'},
            {'beat': 0, 'at': 2.1, 'do': 'camera', 'focus': [540, 800], 'scale': 1.2, 'dur': 0.9},
            {'beat': 0, 'at': 2.3, 'do': 'fill', 'target': 'bowl', 'with': 'milk', 'label': '뽀얀 술'},
        ]},
    'glass': {
        'world': 'serve', 'parts': ['plate', 'tumbler(뽀얀 술·거품·기포)', 'dial(도수 0~15)'],
        'events': [
            {'beat': 0, 'at': 0.2, 'do': 'bubbles_rise', 'repeat': 3}, {'beat': 0, 'at': 0.6, 'do': 'boom', 'text': '톡톡'},
            {'beat': 0, 'at': 0.6, 'do': 'chips', 'items': ['맥주 = 보리 + 탄산', '막걸리 = 쌀 + 탄산']},
            {'beat': 1, 'at': 0.2, 'do': 'tokens_merge', 'items': ['단맛', '신맛', '떫은맛'], 'into': 'tumbler'},
            {'beat': 2, 'at': 0.0, 'do': 'camera_pan', 'to': 'dial', 'dx': -1080, 'dur': 0.8},
            {'beat': 2, 'at': 0.6, 'do': 'dial_needle', 'value': 7, 'band': [6, 8], 'range': [3, 12], 'chips': ['6~8도 흔함', '3~12도까지']},
        ]},
    'quiz': {
        'world': 'vessel_closed', 'quiz': {'question': '퀴즈! 윗술만 떠내면?', 'options': ['1 막걸리', '2 청주', '3 소주'], 'answer': 2},
        'events': [{'beat': 0, 'at': 0.3, 'do': 'quiz'}, {'beat': 0, 'at': -0.9, 'from_end': True, 'do': 'loop_return', 'note': '첫 프레임과 같은 닫힌 항아리로'}]},
}
CHAPTERS = [('jar', 0, '막걸리 해부'), ('jar', 2, '항아리 속 발효'), ('jar', 4, '떠내기 vs 통째로'),
            ('sieve', 0, '통째로 거르기'), ('glass', 0, '한 잔에 담긴 것'), ('quiz', 0, '퀴즈 타임')]
ep = {'format': 'jjeri_anatomy', 'version': 1, 'series': '째리의 술 해부', 'topic': '막걸리',
      'voice': {'provider': 'edge', 'voice': VOICE, 'rate': RATE, 'atempo': SPEED},
      'keywords': [{'word': '막걸리', 'color': '#C2410C'}, {'word': '청주', 'color': '#B45309'}, {'word': '누룩', 'color': '#8A5A35'}, {'word': '탄산', 'color': '#2563EB'}],
      'chapters': [{'world': w, 'beat': i, 'title': t} for w, i, t in CHAPTERS],
      'window': {'clip_top': 424, 'clip_bottom': 1036, 'note': '그림 칸 = 창문. 카메라가 밀어도 제목·말풍선을 덮지 않는다'},
      'art': 'tools/art25.py 규칙 — 빛 왼쪽 위, 윗면 타원 ×0.17, 회전체는 profile(y) 하나, 단면 = 앞 절반 제거',
      'worlds': []}
for w, spec in W.items():
    ep['worlds'].append({'id': w, **spec, 'beats': [{'text': t, 'claim_ids': []} for bw, t in BEATS if bw == w]})
assert sum(len(x['beats']) for x in ep['worlds']) == len(BEATS)
(root / 'episode.example.json').write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding='utf-8')
print('worlds', len(ep['worlds']), 'beats', len(BEATS))
