"""engine.render 규격 v2 순수 로직 테스트 (ffmpeg 실행 없음).

- ③ scene_kind → 렌더 방식(고효율=클립, 그 외=스틸).
- ⑤ 데모 지시서가 이중언어(narration_en)·scene_kind 를 갖춰 렌더 경로가 언어별로 갈리는지.
"""

from engine import config
from engine.render import _demo_anim_directive, _demo_directive, render_kind_for_scene


def test_render_kind_animation_is_clip():
    # 애니메이션 버전은 전 컷 Manim 클립.
    for k in list(config.SCENE_KINDS) + [None]:
        assert render_kind_for_scene(k, "animation") == "clip"


def test_render_kind_nonanimation_is_still():
    # 만화/이미지 버전은 성긴 텍스트 클립을 섞지 않고 전부 스틸(빈 화면처럼 보이는 문제 회피).
    for v in ("comic", "image_sequence"):
        for k in list(config.SCENE_HIGH_EFFORT_KINDS) + ["comic_panel", None]:
            assert render_kind_for_scene(k, v) == "image"


def test_demo_directives_have_bilingual_and_scene_kind():
    for d in (_demo_directive(), _demo_anim_directive()):
        for c in d["cuts"]:
            assert c["scene_kind"] in config.SCENE_KINDS
            assert c["narration_ko"] and c["narration_en"]  # 이중언어 나레이션
        # 훅 트랜스크리에이션(있는 데모).
    h = _demo_directive()["header"]
    assert h["hook_ko"] and h["hook_en"]


def test_anim_demo_uses_high_effort_scenes():
    # 애니 데모는 전부 고효율 씬 → 전 컷 클립 경로.
    for c in _demo_anim_directive()["cuts"]:
        assert render_kind_for_scene(c["scene_kind"]) == "clip"
