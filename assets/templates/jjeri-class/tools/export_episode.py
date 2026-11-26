"""샘플 1교시를 엔진이 받을 '편 지시서(episode JSON)' 모양으로 내보낸다. 엔진 구현의 정답 입력.
다시: python tools/export_episode.py  → episode.example.json
문장은 tools/script.py, 칸 값은 tools/build.py 의 장면과 같다(값을 바꾸면 둘 다 바꾼다)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from script import BEATS, VOICE, RATE, SPEED

root = Path(__file__).resolve().parent.parent
WA, BOTH, US = 'Whisky Advocate', 'Whisky Advocate · Frontiers in Chemistry(2018)', 'Whisky Advocate · 미국 버번 규정'

SCENES = [
    ('s1', 'glass_pair_question', None, None, {
        'left': {'label': '버번 캐스크', 'liquid': 'amber', 'question': '바닐라?'},
        'right': {'label': '셰리 캐스크', 'liquid': 'mahogany', 'question': '진한 과일?'}}),
    ('s2', 'myth_question', {'text': '흔히 하는 생각', 'tone': 'grey'}, None, {
        'from': {'icon': 'glass', 'liquid': 'clear', 'label': '투명한 원액'},
        'to': {'icon': 'barrel', 'wood': 'light', 'label': '그냥 그릇?'}}),
    ('s3', 'truth_infuse_stamp', {'text': '실제로는', 'tone': 'tomato'}, WA, {
        'wall_label': '오크 나무', 'inside_label': '원액', 'from_color': 'clear', 'to_color': 'amber',
        'stamp': '오크통 = 티백', 'stamp_on_beat': 1}),
    ('s4', 'journey_multiply', None, US, {
        'object': {'icon': 'barrel', 'wood': 'light'},
        'from_label': '미국 · 새 통만', 'to_label': '스코틀랜드 · 한 번 쓴 통',
        'move_on_beat': 1, 'multiply_on_beat': 2, 'multiply_count': 3, 'benefit_chip': '구하기 쉽고 비교적 저렴'}),
    ('s5', 'flavor_rise', None, BOTH, {
        'base': {'icon': 'charred_plank', 'label': '속을 그을린 새 미국산 오크'},
        'notes': [{'icon': 'vanilla', 'label': '바닐라', 'beat': 0}, {'icon': 'caramel', 'label': '캐러멜', 'beat': 0},
                  {'icon': 'smoke', 'label': '스모크', 'beat': 1}, {'icon': 'star_anise', 'label': '스파이스', 'beat': 1}]}),
    ('s6', 'pour_infuse', None, None, {
        'pour': {'icon': 'bottle', 'label': '셰리', 'chip': '강화 와인 셰리'},
        'target': {'icon': 'barrel', 'wood': 'dark', 'chip': '유럽산 오크통', 'tint': 'sherry'}, 'result_chip': '셰리가 스며듦'}),
    ('s7', 'fill_and_notes', None, BOTH, {
        'source': {'icon': 'barrel', 'wood': 'dark'}, 'glass_to': 'mahogany',
        'notes': [{'icon': 'grapes'}, {'icon': 'plum'}, {'icon': 'cherries'}], 'chips': ['어두운 과일 향', '풍부함']}),
    ('s8', 'scarcity_compare', None, None, {
        'many': {'icon': 'barrel', 'wood': 'light', 'count': 6, 'chip': '버번 캐스크 · 흔해요', 'price_level': '₩ 저렴'},
        'one': {'icon': 'barrel', 'wood': 'dark', 'chip': '셰리 캐스크 · 귀해요', 'price_level': '₩₩₩ 비쌈'}}),
    ('s9', 'two_methods', {'text': '블렌더의 방법', 'tone': 'yellow'}, None, {
        'rows': [{'label': '① 섞기', 'steps': ['glass:amber', '+', 'glass_small:mahogany', '→', 'glass:blend']},
                 {'label': '② 추가 숙성', 'steps': ['glass:amber', '→', 'barrel:dark', '→', 'glass:deep']}]}),
    ('s10', 'recap_board', None, BOTH, {
        'rows': [{'subject': {'icon': 'barrel', 'wood': 'light', 'chip': '버번'}, 'items': [['vanilla', '바닐라'], ['caramel', '캐러멜'], ['smoke', '스모크']]},
                 {'subject': {'icon': 'barrel', 'wood': 'dark', 'chip': '셰리'}, 'items': [['grapes', '어두운 과일'], ['glass:mahogany', '풍부함']]}],
        'exception_chip': '예외도 많아요', 'exception_on_beat': 1}),
    ('s11', 'house_rule_search', None, None, {
        'label': {'lines': ['WHISKY', 'SHERRY', 'CASK'], 'circle_lines': [1, 2], 'chip': '캐스크 이름 찾기'},
        'search': {'hint': '술째리고에서 검색', 'query': '셰리 캐스크', 'on_beat': 1, 'after_chip': '가격 비교까지 한 번에'},
        'show_prices': False}),
    ('s12', 'vote_comment', None, None, {
        'left': {'label': '버번파', 'liquid': 'amber'}, 'right': {'label': '셰리파', 'liquid': 'mahogany'},
        'comment': '저는 ○○파예요', 'loop_to_first_frame': True}),
]
CHAPTERS = [('s1', '버번 vs 셰리 캐스크'), ('s2', '통이 뭐길래?'), ('s4', '버번 캐스크'), ('s6', '셰리 캐스크'),
            ('s8', '셰리 통은 귀해서'), ('s10', '한눈에 보기'), ('s11', '집 규칙'), ('s12', '당신은 어느 쪽?')]

ep = {
    'format': 'jjeri_class', 'version': 1,
    'series': '째리의 술 수업', 'episode': '1교시', 'topic': '버번 vs 셰리 캐스크',
    'voice': {'provider': 'edge', 'voice': VOICE, 'rate': RATE, 'atempo': SPEED},
    'keywords': [{'word': '술째리고', 'color': '#C2410C'}, {'word': '버번', 'color': '#B45309'}, {'word': '셰리', 'color': '#A61B1B'}],
    'title_accents': {'버번': '#F0A93B', '셰리': '#F2836B'},
    'chapters': [{'from_scene': s, 'title': t} for s, t in CHAPTERS],
    'scenes': [],
    'caption_draft': (root / '릴스_설명란.txt').read_text(encoding='utf-8'),
}
for sid, tpl, tag, src, slots in SCENES:
    ep['scenes'].append({'id': sid, 'template': tpl, 'tag': tag, 'source_chip': src, 'slots': slots,
                         'beats': [{'text': t, 'claim_ids': []} for s, t in BEATS if s == sid]})
assert sum(len(s['beats']) for s in ep['scenes']) == len(BEATS)
(root / 'episode.example.json').write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding='utf-8')
print('scenes', len(ep['scenes']), 'beats', len(BEATS))
