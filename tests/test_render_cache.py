"""engine.assemble 멱등 캐시 키 테스트.

content_hash 는 컷의 '시각 산출 결정 요인'만 반영해야 한다:
- visual_prompt/effects/global_style/version/visual_type 이 바뀌면 해시 변경 → 재생성
- 나레이션 등 무관 필드는 해시 불변 → 캐시 재사용
"""

from engine.assemble import cache_hit, content_hash

_HEADER = {"version_type": "image_sequence", "global_style": "clean"}
_CUT = {"cut_no": 1, "visual_type": "image", "visual_prompt": "a cat", "effects": ["highlight"]}


def test_hash_is_deterministic():
    assert content_hash(_CUT, _HEADER) == content_hash(dict(_CUT), dict(_HEADER))


def test_hash_changes_on_visual_prompt():
    other = {**_CUT, "visual_prompt": "a dog"}
    assert content_hash(other, _HEADER) != content_hash(_CUT, _HEADER)


def test_hash_changes_on_effects_and_style():
    assert content_hash({**_CUT, "effects": ["pan_left"]}, _HEADER) != content_hash(_CUT, _HEADER)
    assert content_hash(_CUT, {**_HEADER, "global_style": "gritty"}) != content_hash(_CUT, _HEADER)


def test_hash_ignores_irrelevant_fields():
    # 나레이션·source_facts 는 시각 산출에 무관 → 해시 불변(오디오/자막은 별도).
    noisy = {**_CUT, "narration_ko": "완전히 다른 문장", "source_facts": ["x[9]"]}
    assert content_hash(noisy, _HEADER) == content_hash(_CUT, _HEADER)


def test_cache_hit_logic():
    h = content_hash(_CUT, _HEADER)
    assert cache_hit({"content_hash": h}, h) is True
    assert cache_hit({"content_hash": "other"}, h) is False
    assert cache_hit(None, h) is False
