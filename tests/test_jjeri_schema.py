import json
from pathlib import Path
import pytest
from engine.motion.jjeri_class.schema import validate_episode

ROOT = Path(__file__).resolve().parents[1] / 'assets/templates/jjeri-class'

@pytest.fixture
def episode():
    return json.loads((ROOT / 'episode.example.json').read_text(encoding='utf-8'))

def test_example_exposes_known_subtitle_overflow(episode):
    assert validate_episode(episode) == ['subtitle_overflow']

def test_long_subtitle_rejected(episode):
    episode['scenes'][0]['beats'][0]['text'] = '가' * 18
    assert 'subtitle_overflow' in validate_episode(episode)

def test_unknown_icon_rejected(episode):
    episode['scenes'][1]['slots']['from']['icon'] = 'alien'
    assert 'icon_unknown' in validate_episode(episode)

def test_bad_ending_rejected(episode):
    episode['scenes'][-1]['template'] = 'myth_question'
    assert 'ending_invalid' in validate_episode(episode)

def test_price_flag_rejected(episode):
    episode['scenes'][-2]['slots']['show_prices'] = True
    assert 'price_forbidden' in validate_episode(episode)

def test_price_field_required(episode):
    del episode['scenes'][-2]['slots']['show_prices']
    assert 'price_forbidden' in validate_episode(episode)

def test_missing_template_slot_rejected(episode):
    del episode['scenes'][0]['slots']['left']
    assert 'slot_missing' in validate_episode(episode)

def test_chapter_scene_reference_rejected(episode):
    episode['chapters'][0]['from_scene'] = 'missing'
    assert 'chapters_invalid' in validate_episode(episode)

def test_price_text_in_any_screen_slot_is_rejected(episode):
    episode['scenes'][0]['slots']['left']['label'] = '49,000원'
    assert 'price_forbidden' in validate_episode(episode)

def test_invalid_scene_ids_are_rejected_without_crash(episode):
    episode['scenes'][0]['id'] = []
    assert 'scene_id_invalid' in validate_episode(episode)


@pytest.mark.parametrize("price", ["￥１，２００", "2만 원", "오천원", "KRW 15000"])
def test_price_rejected_in_title_and_subtitle(episode, price):
    episode["chapters"][0]["title"] = price
    episode["scenes"][0]["beats"][0]["text"] = price
    assert "price_forbidden" in validate_episode(episode, replay=True)


def test_schema_accepts_sample_replay_and_production_caption_boundary(episode):
    assert validate_episode(episode, replay=True) == []
    beat = episode["scenes"][8]["beats"][0]
    beat["text"] = "가" * 17 + "\n" + "나" * 17
    assert validate_episode(episode) == []
    beat["text"] += "\n다"
    assert "subtitle_overflow" in validate_episode(episode)


def test_schema_rejects_bad_nested_types_and_beat_refs(episode):
    episode["scenes"][2]["slots"]["stamp_on_beat"] = True
    episode["scenes"][4]["slots"]["notes"] = [{"icon": "smoke", "label": "향", "beat": 4}]
    episode["scenes"][-2]["slots"]["label"]["circle_lines"] = [2]
    episode["scenes"][-2]["slots"]["label"]["lines"] = ["BARREL"]
    episode["scenes"][-1]["slots"]["left"]["liquid"] = []
    errors = validate_episode(episode, replay=True)
    assert {"beat_reference_invalid", "slot_reference_invalid", "slots_invalid"} <= set(errors)


REVIEW_PRICES = ("만원", "만 원대", "천원", "수만 원", "몇만 원", "30,000₩",
                 "30€", "30불", "3만 5천", "가격 30000", "3萬원")


@pytest.mark.parametrize("field", ["title", "beat", "slot", "source"])
@pytest.mark.parametrize("price", REVIEW_PRICES)
def test_review_price_forms_blocked_on_each_screen_surface(episode, field, price):
    scene = episode["scenes"][0]
    if field == "title":
        episode["chapters"][0]["title"] = price
    elif field == "beat":
        scene["beats"][0]["text"] = price
    elif field == "slot":
        scene["slots"]["left"]["label"] = price
    else:
        scene["source_chip"] = price
    assert "price_forbidden" in validate_episode(episode, replay=True)


@pytest.mark.parametrize("text", ["투명한 원액", "여러 원료", "수입 원산지", "1교시", "12년 숙성",
                                  "원액 40도", "3만 5천 명", "30불꽃", "이만원료"])
def test_normal_words_and_quantities_are_not_prices(episode, text):
    episode["scenes"][0]["beats"][0]["text"] = text
    assert "price_forbidden" not in validate_episode(episode, replay=True)
