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
# ★ 2026-09-24 **의도한 변경**(운영자: "색이 왜 이렇게 단조로워?? 회색 주황색 위주인데??").
#   2차 렌더(docs/preview-2026-09-24/620e66be)가 회색+앰버 일색이었다 — "desaturated palette" 와
#   "no other saturated color" 가 원인이었다. 참고 영상은 사물 본래 색을 쓴다. 팔레트 문구만
#   바꾸고 재질(무광)·조명(균일)·아웃라인 없음은 그대로다. 실사 컷이 회색 사진 톤으로 튀던 것도
#   같은 렌더에서 봤으므로 "도해와 같은 탁상 모형 룩"을 REALITY 문장에 못박았다.
LOCKED_REALITY = (
    "stylized 3D render, simplified geometric forms with clean silhouettes, "
    "matte surfaces with minimal micro-texture, even studio lighting, "
    "the same tabletop scale-model look as the cutaway cuts, "
    "objects keep their natural material colors at medium saturation, "
    "amber only on the part being explained, neutral studio backdrop"
)
# ★ 2026-09-18 **의도한 변경**(운영자 승인 "T5 색까지 승인", 연구_기전시퀀스_교육력 T5).
#   앰버 1색으로는 두 집단·전후를 구별할 수 없어(두 뇌가 같은 색) 비교용 두 색을 뜻과 함께
#   더했다(config.MECHANISM_COLOR_CODE). 재질·조명·배경은 2026-09-08 고정 그대로다 —
#   아래 `test_the_two_roles_still_share_one_visual_language` 가 그것을 계속 지킨다.
#   REALITY 는 손대지 않았다. 실측 판정은 docs/핸드오프_기전교육력_2026-09-18.md 에 기록한다.
LOCKED_MECHANISM = (
    "stylized 3D render, simplified geometric forms with clean silhouettes, "
    "matte surfaces with minimal micro-texture, "
    "isometric cutaway with crisp layer separation, "
    "even studio lighting, "
    "objects keep their natural material colors at medium saturation, "
    "amber only on the part being explained, "
    "muted blue and muted coral reserved for the two compared groups or before and after, "
    "neutral studio backdrop"
)
LOCKED_GLOBAL = (
    "One consistent look across every cut: the same matte materials, the same even studio light, "
    "and objects in their natural colors"
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
                   "neutral studio backdrop"):
        assert shared in real and shared in mech, shared
    # 다른 것은 시점 하나 — 그리고 2026-09-18 부터 **비교용 두 색**(도해에만 필요하다).
    assert "isometric cutaway" in mech and "isometric cutaway" not in real
    assert "muted blue and muted coral" in mech and "muted blue and muted coral" not in real
    # 색 규약의 세 색이 프롬프트 문자열에 **뜻 그대로** 살아 있어야 범례가 거짓이 안 된다.
    for color in config.MECHANISM_COLOR_CODE:
        assert color in mech, color


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


def test_the_video_prompt_carries_the_same_negative_as_the_image():
    """★ 2026-09-24 2차 렌더: 시작 프레임은 무광이었는데 클립 끝에서 피스톤이 **빛났다.**
    발광 금지는 이미지 경로에만 있었다. 클립에도 같은 안전망이 있어야 한 작품이다."""
    from engine.providers import video as vp
    cut = {"visual_role": "MECHANISM", "visual_prompt": "x", "motion_prompt": "pistons cycle"}
    got = vp.build_motion_prompt(cut, {"version_type": "photo"})
    assert "no glowing effects" in got and "no neon" in got


def test_natural_colors_are_allowed_and_the_codes_are_reserved_for_marking():
    """운영자(2026-09-24): "색이 왜 이렇게 단조로워?? 회색 주황색 위주인데??"
    사물 본래 색은 허용하고, 앰버·파랑·산호는 표시할 부분에만 쓴다."""
    for role in ("REALITY", "MECHANISM"):
        style = config.VISUAL_ROLE_STYLE[role]
        assert "natural material colors" in style, role
        assert "desaturated" not in style and "no other saturated color" not in style, role
    assert "restrained palette" not in config.PHOTO_GLOBAL_STYLE


def test_changing_the_style_bumps_the_cache_contract_version():
    """★ 3차 렌더 실측(2026-09-24): 팔레트를 바꿨는데 캐시가 옛 그림을 돌려줬다 — 화풍 문자열은
    캐시 키에 없고 PROMPT_CONTRACT_VERSION 만 들어간다. 문자열을 바꾼 날짜 ≤ 버전 날짜여야 한다."""
    assert config.PROMPT_CONTRACT_VERSION >= "2026-09-24", config.PROMPT_CONTRACT_VERSION
