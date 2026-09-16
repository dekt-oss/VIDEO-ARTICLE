"""engine.manim_templates.select_template 순수 로직 테스트 (manim 미필요).

씬 선택 매핑만 검증한다(실제 Manim 렌더는 CI/로컬에서 별도). manim 을 import 하지 않으므로
manim 미설치 환경에서도 동작한다(모듈 상단은 순수 로직).
"""

from engine import config
from engine.manim_templates import TEMPLATE_NAMES, _steps_from, select_template


def _cut(cut_no, visual_prompt="", narration_ko="설명 문장"):
    return {"cut_no": cut_no, "visual_prompt": visual_prompt, "narration_ko": narration_ko}


def test_first_cut_is_title():
    name, params = select_template(_cut(1, "anything"), 0)
    assert name == "title"
    assert params.get("title")


def test_arrow_flow_keyword():
    name, params = select_template(_cut(2, "arrow flow: input to processing to output"), 1)
    assert name == "arrow_flow"
    assert params["nodes"] == ["입력", "처리", "출력"]


def test_number_compare_needs_ledger_values():
    """★ 수치 차트는 원장에서 값이 나올 때만 만든다.

    개정 전에는 여기서 하드코딩 [("전",40),("후",75)] 를 돌려줬다. `animation` 버전이
    VIDEO_VERSIONS 에서 빠져 도달 불가라 드러나지 않았을 뿐, editorial 의 data_viz 를 코드
    차트로 살리는 순간 논문에 없는 40/75 가 화면에 박힌다(환각 방지 불변식 위반).
    """
    cut = _cut(2, "compare 비교 before and after")
    name, params = select_template(cut, 1)          # 원장 없음
    assert name == "step_reveal", "값 없이 수치 차트를 만들면 안 된다"
    assert "items" not in params


def test_number_compare_uses_resolved_claim_values():
    cut = _cut(2, "compare 비교 before and after")
    cut["claim_ids"] = ["C01", "C02"]
    fs = {"claims": [
        {"claim_id": "C01", "effect_size": "3.2", "effect_unit": "%p", "outcome": "환경 성과"},
        {"claim_id": "C02", "effect_size": "5.8", "effect_unit": "%p", "outcome": "비교 집단"},
    ]}
    name, params = select_template(cut, 1, "ko", fs)
    assert name == "number_compare"
    assert [v for _label, v in params["items"]] == [3.2, 5.8]


def test_claim_without_effect_size_does_not_become_a_chart():
    cut = _cut(2, "compare 비교")
    cut["claim_ids"] = ["C01"]
    fs = {"claims": [{"claim_id": "C01", "effect_size": None, "outcome": "환경 성과"}]}
    name, _params = select_template(cut, 1, "ko", fs)
    assert name == "step_reveal"


def test_step_reveal_keyword():
    name, params = select_template(_cut(2, "step by step 단계", narration_ko="첫째. 둘째. 셋째."), 1)
    assert name == "step_reveal"
    assert len(params["steps"]) >= 1


def test_default_is_step_reveal():
    name, _ = select_template(_cut(2, "some unrelated visual"), 1)
    assert name == "step_reveal"


def test_all_selected_names_are_known():
    for i, vp in enumerate(["title", "arrow flow", "단계", "비교", "그냥"]):
        name, _ = select_template(_cut(i + 1, vp), i)
        assert name in TEMPLATE_NAMES


def test_steps_from_does_not_split_decimals():
    # 소수점·천단위 쉼표로는 쪼개지지 않아야 한다(문장부호로만 분할). 짧은 입력으로 절단 영향 배제.
    assert _steps_from("정확도는 40.5%") == ["정확도는 40.5%"]   # 소수점 보존, 1조각
    assert _steps_from("표본 1,000명") == ["표본 1,000명"]        # 천단위 쉼표 보존
    # 문장 종결/중점으로는 분할된다.
    assert len(_steps_from("첫째. 둘째")) == 2


def test_labels_never_invent_are_short():
    # 긴 나레이션도 라벨은 짧게 자른다(도해 가독성).
    long = "가" * 100
    _, params = select_template(_cut(1, "", narration_ko=long), 0)
    assert len(params["title"]) <= 21


# ── 코드차트 폐기 후 (docs/deviation-webtoon-b1-removal.md) ──
# M-E4 는 editorial + data_viz 만 Manim 클립으로 되살렸었다. 그 분기를 없앴으므로
# **제공 버전에서는 어떤 씬이든 스틸**이다. Manim 은 `animation`(데모 전용)에만 남는다.
def test_offered_versions_never_produce_code_chart_clips():
    from engine.render import render_kind_for_scene

    cut = {"cut_no": 2, "scene_kind": "data_viz", "claim_ids": ["C01"]}
    fs = {"claims": [{"claim_id": "C01", "effect_size": "3.2", "effect_unit": "%p"}]}
    for version in config.VIDEO_VERSIONS:
        # 원장에 값이 있어도 스틸이다 — 화면의 숫자는 overlay_plan 이 담당한다.
        assert render_kind_for_scene("data_viz", version, cut, fs) == "image", version
        assert render_kind_for_scene("comic_panel", version, cut, fs) == "image", version
        # 인자를 안 주는 기존 호출부도 동작 불변.
        assert render_kind_for_scene("data_viz", version) == "image", version


def test_demo_animation_path_still_uses_manim():
    """`--demo-anim` 관통 검증 경로는 남는다 — 이게 manim_templates 의 유일한 소비처다."""
    from engine.render import render_kind_for_scene

    assert render_kind_for_scene("data_viz", "animation") == "clip"
    assert "animation" not in config.VIDEO_VERSIONS   # 제공 버전은 아니다
