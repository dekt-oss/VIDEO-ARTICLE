"""실사형 화풍 **고정** 계약 (2026-09-08, 운영자 지시).

운영자 판정: "저 화풍이 마음에 들어. 저 화풍으로 이제 고정해서 유지해주세요."

★ 왜 테스트로 고정하나: 이 저장소는 화풍을 **네 번** 바꿨고 그때마다 실측 렌더로 판정했다
  (`docs/핸드오프_화풍전환_2026-09-07.md`). 마음에 드는 화면이 나온 지금, 다음 사람이
  "조금만 다듬자"로 문자열을 건드리면 그 네 번을 다시 하게 된다. 그래서 **주석이 아니라
  테스트로** 못박는다(skill: enforce-by-type-or-test).

★★ **이 파일이 깨지는 것은 버그가 아니다.** 화풍을 의도적으로 바꾸는 날에는 이 파일도 같이
  고친다. 이 테스트의 일은 그 변경이 **의도적이었는지 묻는 것**이다 — 딴 작업의 곁가지로
  조용히 바뀌는 것을 막는다. 바꾼다면 실측 렌더로 판정하고 핸드오프에 기록을 남긴다.

고정된 화면(2026-09-07 실측, 지시서 f7dcb61e 로 5장 + 영상 1개):
  · 무광 CG. 아웃라인 없음, 발광 없음, 렌즈 흐림 없음
  · 실사(REALITY)와 도해(MECHANISM)가 재질·조명·색을 **공유**하고 단면 시점만 다르다
  · 그래서 실험실 컷과 세포 컷이 한 작품으로 보인다(이 작업의 출발점이 그것이었다)
"""

from __future__ import annotations

from engine import config
from engine.providers import image as image_provider


# ── 고정된 문자열. 바꾸려면 실측 렌더로 판정하고 핸드오프에 남긴다 ──
LOCKED_REALITY = (
    "stylized 3D render, simplified geometric forms with clean silhouettes, "
    "matte surfaces with minimal micro-texture, even studio lighting, "
    "limited desaturated palette with a single amber accent, neutral background"
)
LOCKED_MECHANISM = (
    "stylized 3D render, simplified geometric forms with clean silhouettes, "
    "matte surfaces with minimal micro-texture, "
    "isometric cutaway with crisp layer separation, "
    "even studio lighting, "
    "single amber accent color on the part being explained, neutral background"
)
LOCKED_GLOBAL = (
    "One consistent look across every cut: the same materials, the same even studio light, "
    "and the same restrained palette"
)


def test_the_reality_style_is_locked():
    assert config.VISUAL_ROLE_STYLE["REALITY"] == LOCKED_REALITY


def test_the_mechanism_style_is_locked():
    assert config.VISUAL_ROLE_STYLE["MECHANISM"] == LOCKED_MECHANISM


def test_the_global_anchor_is_locked():
    assert config.PHOTO_GLOBAL_STYLE == LOCKED_GLOBAL


def test_the_two_roles_still_share_one_visual_language():
    """★ 이것이 고정의 **뜻**이다 — 문자열이 같은지가 아니라 두 역할이 한 언어인지.

    "컷7(실사 쥐) → 컷8(3D 세포)에서 화면이 튄다"가 이 작업의 출발점이었다.
    누가 한쪽만 손대면 그 증상이 돌아온다.
    """
    real, mech = config.VISUAL_ROLE_STYLE["REALITY"], config.VISUAL_ROLE_STYLE["MECHANISM"]
    for shared in ("stylized 3D render",
                   "simplified geometric forms with clean silhouettes",
                   "matte surfaces with minimal micro-texture",
                   "even studio lighting",
                   "neutral background"):
        assert shared in real and shared in mech, shared
    # 다른 것은 시점 하나뿐이다.
    assert "isometric cutaway" in mech and "isometric cutaway" not in real


def test_neither_role_asks_for_a_photograph_or_an_illustration():
    """★ 양쪽 실패 모드를 다 막는다. 사진으로 가면 쥐가 못 볼 화면이 되고,
    삽화로 가면 만화가 된다 — 실측에서 둘 다 겪었다."""
    for role in ("REALITY", "MECHANISM"):
        style = config.VISUAL_ROLE_STYLE[role]
        neg = config.VISUAL_ROLE_NEGATIVE[role]
        assert "photorealistic" not in style and "cinematic still" not in style
        assert "not a photograph" in neg
        assert "no cartoon outlines" in neg and "no line art" in neg


def test_the_locked_style_actually_reaches_the_image_prompt():
    """★ 상수만 고정하고 배선이 끊기면 고정한 것이 아니다 — 실제 프롬프트로 확인한다."""
    for role in ("REALITY", "MECHANISM"):
        got = image_provider._build_image_prompt(
            {"cut_no": 1, "visual_role": role, "visual_prompt": "a cage on a bench"},
            {"version_type": "photo"})
        assert config.VISUAL_ROLE_STYLE[role] in got, role


def test_the_engine_sets_the_global_anchor_not_the_model():
    """★★ `global_style` 은 프롬프트 **맨 앞**에 붙는다. LLM 이 쓰면 편마다 화풍이 달라진다.

    실측: 모델이 "Scientific realism, clean laboratory aesthetic, natural light" 를 썼고
    그것이 역할 화풍보다 앞에 왔다. 실사형에서는 코드가 덮어쓴다.
    """
    src = open(__import__("engine.directive", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert 'header["global_style"] = config.PHOTO_GLOBAL_STYLE' in src


def test_other_versions_are_untouched():
    """★ 고정은 실사형에만. 만화식·웹툰은 자기 화풍을 그대로 쓴다."""
    assert "REALITY" in config.VISUAL_ROLE_STYLE and "MECHANISM" in config.VISUAL_ROLE_STYLE
    assert set(config.VISUAL_ROLE_STYLE) == {"REALITY", "MECHANISM"}
    got = image_provider._build_image_prompt(
        {"cut_no": 1, "visual_prompt": "a red sphere"}, {"version_type": "comic"})
    assert config.VISUAL_ROLE_STYLE["REALITY"] not in got
