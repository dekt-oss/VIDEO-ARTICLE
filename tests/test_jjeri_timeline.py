import json
import unittest
from pathlib import Path

from engine.motion.jjeri_class.timeline import build_timeline

ROOT = Path(__file__).resolve().parents[1] / 'assets/templates/jjeri-class'

class TimelineTest(unittest.TestCase):
    def test_sample_scene_starts(self):
        episode = json.loads((ROOT / 'episode.example.json').read_text(encoding='utf-8'))
        voice = json.loads((ROOT / 'assets/vo/vo.json').read_text(encoding='utf-8'))
        expected = json.loads((ROOT / 'timeline.json').read_text(encoding='utf-8'))
        result = build_timeline(episode, voice)
        for actual, golden in zip(result['scenes'], expected['scenes'], strict=True):
            self.assertEqual(actual['id'], golden['id'])
            self.assertLessEqual(abs(actual['start'] - golden['start']), .05)
        self.assertLessEqual(abs(result['total'] - expected['total']), .05)

    def test_reject_wrong_voice_scene_and_silent_audio(self):
        episode = {'scenes': [{'id': 's1', 'template': 'glass_pair_question', 'beats': [{'text': '질문?'}]}]}
        for voice in ([{'sid': 's2', 'head': 0, 'end': 1}], [{'sid': 's1', 'head': 0, 'end': 0}]):
            with self.assertRaises(ValueError):
                build_timeline(episode, voice)

    def test_timing_depends_on_voice(self):
        episode = {'scenes': [{'id': 's1', 'template': 'glass_pair_question', 'beats': [{'text': '질문?'}]}, {'id': 's2', 'template': 'vote_comment', 'beats': [{'text': '투표'}]}]}
        voice = [{'sid': 's1', 'head': 0, 'end': 1, 'sec': 2}, {'sid': 's2', 'head': 0, 'end': 1, 'sec': 1}]
        original = build_timeline(episode, voice)
        voice[0]['end'] = 2
        self.assertAlmostEqual(build_timeline(episode, voice)['scenes'][1]['start'] - original['scenes'][1]['start'], 1)

    def test_empty_scene_rejected(self):
        with self.assertRaises(ValueError):
            build_timeline({'scenes': [{'id': 's1', 'beats': []}]}, [])

    def test_voice_span_cannot_exceed_file(self):
        episode = {'scenes': [{'id': 's1', 'beats': [{'text': '질문'}]}]}
        with self.assertRaises(ValueError):
            build_timeline(episode, [{'sid': 's1', 'head': 0, 'end': 20, 'sec': 1}])

    def test_long_search_query_has_time_to_type_and_read(self):
        query = '긴검색어' * 50
        episode = {'scenes': [{'id': 's1', 'template': 'house_rule_search', 'slots': {'search': {'query': query, 'on_beat': 0}}, 'beats': [{'text': '검색'}]}]}
        voice = [{'sid': 's1', 'head': 0, 'end': 1, 'sec': 1}]
        scene = build_timeline(episode, voice)['scenes'][0]
        self.assertGreaterEqual(scene['dur'] + 1e-9, .2 + .9 + len(query) * .12 + .8)


    def test_voice_requires_measured_file_duration(self):
        episode = {'scenes': [{'id': 's1', 'beats': [{'text': '질문'}]}]}
        with self.assertRaises(ValueError):
            build_timeline(episode, [{'sid': 's1', 'head': 0, 'end': 1}])
