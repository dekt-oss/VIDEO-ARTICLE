"""스틸이 **찌그러지지 않는다** — 켄번스·팬 회귀 고정 (2026-09-18 재리뷰에서 실측으로 잡음).

무엇이 문제였나: `zoompan` 의 `s=` 는 출력 **크기**일 뿐 종횡비를 지켜 주지 않는다.
레이아웃이 `center_band`(1080×1300)인데 생성 그림은 9:16(1080×1920)이라, 켄번스·팬이 붙은
스틸은 **세로로 눌려** 나갔다. 실측(ffmpeg 실행): 지름 600px 원이 600×406 타원이 됐다(68%).

왜 오래 안 보였나: 효과가 **없는** 컷은 같은 함수의 마지막 줄에서 이미 cover-crop 을 하고
있었다. 켄번스·팬 branch 만 그 줄을 지나가지 않았다 — 즉 "대부분은 멀쩡한데 일부만" 이었다.
저장된 지시서 실측: 스틸 컷 70개 중 21개(30%), 13/40 편이 그 상태로 나갔다.

이 파일은 ffmpeg 을 돌리지 않는다(순수 문자열 검사) — 실측은 위에 기록으로 남기고,
여기서는 **모든 효과 branch 가 종횡비를 맞추고 시작하는지**만 고정한다.
"""

from __future__ import annotations

import pytest

from engine import assemble, config

EFFECT_BRANCHES = ["ken_burns_zoom_in", "ken_burns_zoom_out", "pan_left", "pan_right"]


def test_the_layout_actually_differs_from_the_frame():
    """★ 이 테스트가 지키는 위험이 실재하는지부터 본다 — 두 크기가 같으면 애초에 안 눌린다."""
    w, h = assemble.layout_content_dims()
    if (w, h) == (config.RENDER_WIDTH, config.RENDER_HEIGHT):
        pytest.skip("full_bleed 레이아웃 — 이 회귀는 center_band 에서만 생긴다")
    assert h != config.RENDER_HEIGHT


@pytest.mark.parametrize("effect", EFFECT_BRANCHES)
def test_every_effect_branch_fixes_the_aspect_first(effect: str):
    w, h = assemble.layout_content_dims()
    got = assemble.effect_filter([effect], 5.0)
    assert got.startswith(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"), got
    assert "zoompan" in got


def test_the_no_effect_branch_still_crops_the_same_way():
    """효과 없는 컷은 원래 맞았다 — 두 경로가 **같은 방식으로** 잘라야 컷 사이에 배율이 안 튄다."""
    w, h = assemble.layout_content_dims()
    got = assemble.effect_filter([], 5.0)
    assert f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" in got
    assert "zoompan" not in got


def test_unknown_effects_do_not_bypass_the_crop():
    w, h = assemble.layout_content_dims()
    got = assemble.effect_filter(["sparkle", "highlight"], 5.0)
    assert f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" in got
