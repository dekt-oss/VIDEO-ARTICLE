"""버전 정규화 + motion_prompt 배선 순수 로직 테스트 (명세 B1 §3-2).

원래 editorial 을 대상으로 쓰던 파일인데 그 버전이 폐기(2026-07-28)돼 webtoon 으로 옮겼고,
webtoon 도 폐기(2026-08-28, docs/deviation-drop-explainer-webtoon.md)돼 comic 으로 옮겼다.
검증하는 성질은 세 번 다 같다:

- normalize_directive 가 버전을 인식하고 motion_prompt 를 보존하는지
- content_hash 가 motion_prompt 를 조건부로만 포함(빈값이면 기존 해시 불변 = 캐시 무효화 없음)하는지
"""

from engine import config
from engine.assemble import content_hash
from engine.directive import normalize_directive


def _obj(cuts):
    return {"header": {"global_style": "korean webtoon illustration"}, "cuts": cuts}


def test_comic_is_recognized_version():
    assert "comic" in config.VIDEO_VERSIONS
    out = normalize_directive(_obj([
        {"cut_no": 1, "visual_prompt": "a red sphere", "source_facts": ["numbers[0]"]},
    ]), "comic")
    assert out["version_type"] == "comic"
    assert out["header"]["version_type"] == "comic"
    # webtoon → visual_type "comic_panel"(버전 강제) — comic 과 같은 화풍 계열이다.
    assert out["cuts"][0]["visual_type"] == config.VERSION_VISUAL_TYPE["comic"] == "comic_panel"


def test_unknown_version_falls_back_to_default():
    """폐기된 editorial 로 들어와도 정규화가 죽지 않고 기본 버전으로 떨어진다.

    저장된 옛 지시서를 다시 정규화하는 경로가 있어서(편집·재렌더) 방어가 필요하다.
    """
    out = normalize_directive(_obj([{"cut_no": 1, "visual_prompt": "x"}]), "editorial")
    assert out["version_type"] == config.DEFAULT_VERSION


def test_motion_prompt_preserved_through_normalize():
    out = normalize_directive(_obj([
        {"cut_no": 1, "visual_prompt": "hero shot", "motion_source": "video",
         "motion_prompt": "slow push-in, elements drift", "source_facts": ["what_found[0]"]},
    ]), "comic")
    cut = out["cuts"][0]
    assert cut["motion_prompt"] == "slow push-in, elements drift"
    assert cut["motion_source"] == "video"


def test_content_hash_includes_motion_prompt_for_video_cut():
    header = {"version_type": "comic", "global_style": "g"}
    base = {"visual_type": "comic_panel", "scene_kind": "data_viz",
            "visual_prompt": "vp", "effects": []}
    a = content_hash({**base, "motion_prompt": "slow push-in"}, header)
    b = content_hash({**base, "motion_prompt": "fast orbit"}, header)
    assert a != b, "다른 모션은 다른 캐시 키여야 한다(클립 산출이 달라짐)"


def test_empty_motion_prompt_does_not_change_hash():
    # 하위호환: motion_prompt 빈값/부재는 기존(필드 도입 전) 해시와 동일해야 캐시 무효화가 없다.
    header = {"version_type": "comic", "global_style": "g"}
    cut = {"visual_type": "comic_panel", "scene_kind": "comic_panel",
           "visual_prompt": "vp", "effects": []}
    legacy = content_hash(cut, header)
    with_empty = content_hash({**cut, "motion_prompt": ""}, header)
    assert legacy == with_empty


def test_versions_do_not_share_asset_cache():
    """같은 컷이라도 버전이 다르면 다른 캐시 키여야 한다 — 나란히 비교하는데 같은 그림을
    돌려쓰면 비교가 무의미해진다. (짝은 원래 comic↔webtoon 이었고, webtoon 폐기 후 comic↔photo.)"""
    cut = {"visual_type": "comic_panel", "scene_kind": "comic_panel",
           "visual_prompt": "vp", "effects": []}
    comic = content_hash(cut, {"version_type": "comic", "global_style": "g"})
    photo = content_hash(cut, {"version_type": "photo", "global_style": "g"})
    assert comic != photo
