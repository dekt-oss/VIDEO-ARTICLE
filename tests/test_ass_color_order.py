"""ASS 색상 자릿수 계약 (2026-09-08, 첫 실물 렌더에서 운영자가 잡았다).

★ 무엇이 문제였나: ASS 색은 `&HAABBGGRR` — **RGB 가 아니라 BGR** 이다. 그런데
  `OVERLAY_COLOR_ASS` 가 노랑을 적으려다 RGB 순으로 `&H00FFE000` 이라고 쓰여 있었고,
  실제로는 R=0 G=224 B=255 인 **하늘색**으로 나갔다.
  운영자 지적: "가운데 파란색 자막은뭐야?"

★★ 같은 파일의 헤더 훅은 인라인 태그 `\\c&H00E0FF&` 로 **올바르게** 적혀 있어 노랑이었다.
  그래서 한 화면에 노랑 훅과 하늘색 근거 카드가 섞여 나왔다 — 색이 둘로 갈리는 것이
  단서였는데, 색을 검사하는 테스트가 하나도 없어 아무도 못 봤다.

이 파일은 **자릿수 순서**를 못박는다. 색을 바꾸고 싶으면 여기 기대값도 같이 바꾼다.
"""

from __future__ import annotations

from engine import config, subtitles


def _rgb(ass: str) -> tuple[int, int, int]:
    """`&HAABBGGRR` → (R, G, B). ASS 는 BGR 순이다."""
    h = ass.replace("&H", "").replace("&", "").zfill(8)
    return int(h[6:8], 16), int(h[4:6], 16), int(h[2:4], 16)


def test_the_overlay_accent_is_yellow_not_blue():
    """★ 노랑은 R 이 높고 B 가 0 이다. 파랑이 나오면 자릿수가 뒤집힌 것이다."""
    r, g, b = _rgb(config.OVERLAY_COLOR_ASS)
    assert (r, g, b) == (255, 224, 0), f"강조색이 노랑이 아니다: R{r} G{g} B{b}"


def test_the_caveat_grey_is_actually_grey():
    """한계·단서는 회색 — 세 채널이 같아야 한다(순서가 틀려도 회색은 티가 안 나므로 함께 본다)."""
    r, g, b = _rgb(config.OVERLAY_CAVEAT_COLOR_ASS)
    assert r == g == b, f"회색이 아니다: R{r} G{g} B{b}"


def test_the_hook_and_the_evidence_card_use_the_same_accent():
    """★★ 이것이 실측에서 색이 갈린 이유다 — 훅은 노랑, 근거 카드는 하늘색이었다.

    한 화면의 강조색은 하나여야 한다. 훅은 인라인 태그로, 카드는 스타일로 색을 받으므로
    두 자리를 각각 고치기 쉽고, 그래서 어긋난다.
    """
    ass = subtitles.build_ass(
        [(0.0, 2.0, "본문")], header_title="시리즈", header_hook="훅 문장",
        total_sec=5.0, overlays=[(0.0, 2.0, "근거 카드", "Evidence")])
    # 헤더 훅의 인라인 색 태그를 찾아 스타일 강조색과 같은 RGB 인지 본다.
    import re
    inline = re.search(r"\\c(&H[0-9A-Fa-f]{6}&)", ass)
    assert inline, "헤더 훅에 색 태그가 없다"
    assert _rgb(inline.group(1)) == _rgb(config.OVERLAY_COLOR_ASS), (
        f"훅 {_rgb(inline.group(1))} vs 근거카드 {_rgb(config.OVERLAY_COLOR_ASS)}")


def test_the_overlay_style_line_carries_that_colour():
    """상수만 고치고 배선이 끊기면 화면은 안 바뀐다 — 실제 ASS 문서로 확인한다."""
    ass = subtitles.build_ass(
        [(0.0, 2.0, "본문")], total_sec=5.0,
        overlays=[(0.0, 2.0, "근거 카드", "Evidence")])
    assert f"Style: Evidence," in ass
    line = next(x for x in ass.splitlines() if x.startswith("Style: Evidence,"))
    assert config.OVERLAY_COLOR_ASS in line, line


# ─────────────────────────────────────────────────────────────
# 근거 카드 끄기 (2026-09-08 운영자 지시)
# ─────────────────────────────────────────────────────────────
def test_evidence_overlays_are_off_by_default():
    """운영자 지시: "근거카드는 색깔이 문제가아니라 그냥 들어간다는게 문제입니다. 빼세요."

    숫자와 출처는 나레이션·자막이 이미 말한다 — 같은 정보를 화면에 두 번 얹지 않는다.
    """
    assert config.EVIDENCE_OVERLAY_ENABLED is False


def test_the_render_does_not_build_overlay_cues_when_off():
    """★ 상수만 두고 배선이 그대로면 화면은 안 바뀐다."""
    src = open(__import__("engine.render", fromlist=["x"]).__file__, encoding="utf-8").read()
    # ★ 2026-09-18 부터 스위치가 둘이다 — 수치·출처 카드(EVIDENCE_OVERLAY_ENABLED, 9/8 지시로 꺼짐)와
    #   범례·캡션(MECHANISM_LABEL_OVERLAYS_ENABLED). 전자가 꺼져 있으면 렌더는 **구조형만** 내보낸다.
    #   9/8 의 뜻("수치·출처 카드가 화면에 안 나간다")은 그대로다.
    assert "only_types = (None if config.EVIDENCE_OVERLAY_ENABLED" in src
    assert "else set(config.OVERLAY_STRUCTURED_TYPES))" in src
    from engine import config
    assert config.EVIDENCE_OVERLAY_ENABLED is False


def test_the_number_card_gate_is_off_too():
    """★★ 이게 빠지면 **통과할 수 없는 함정**이 된다 — 렌더가 안 그리는 카드를 요구하며 막는다.

    게이트는 검사·고지·되먹임 셋이 함께 있어야 하고, 렌더가 그리지 않으면 셋 다 무의미하다.
    """
    from engine import photo_contract as pc

    cut = {"cut_no": 1, "visual_role": "REALITY", "estimated_sec": 5,
           "narration_ko": "수명을 92일 연장했습니다", "visual_prompt": "a cage"}
    res = pc.evaluate({"visual_sequences": []}, [cut], None)
    assert not any(r.startswith("photo_number_without_overlay") for r in res["block_reasons"]), \
        res["block_reasons"]
