"""화살표는 권하는 도구가 아니다 (2026-09-19 운영자 지시).

원문: "화살표에 왜 목숨거냐. 화살표는 그냥 없어도 되는거야. 아주가끔 필요하면 쓰는 도구이지
그걸 무슨 목숨걸고 처 넣으려고 낑낑거리고 있냐."

★ 붙인 것은 모델이 아니라 **프롬프트**였다. 논문 쪽에 "원리를 설명하는 컷에는 되도록 붙여라",
  리포트 쪽에 "설명 대상은 화살표로 찍어라"라고 적혀 있었다. 최근 지시서 실측:
  논문 11/113 컷, 리포트 8/48 컷이 화살표를 달았다.

★ 화살표는 **그림이 이미 말하고 있는 것을 못 믿을 때** 쓰는 땜질이다. 설명 대상이 화면에서
  제일 크고 한가운데 오게 구도를 짜는 것이 먼저고, 그게 안 되면 화살표가 아니라 그림을 고친다.
"""

from __future__ import annotations

import pathlib

from engine import config

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "engine"


def test_the_arrow_is_off_by_default():
    assert config.OVERLAY_POINTER_ENABLED is False


def test_the_renderer_drops_arrows_while_it_is_off():
    """옛 지시서에 남아 있는 화살표도 화면에 안 나가야 한다 — 스위치가 지시서보다 세다."""
    src = (ENGINE / "render.py").read_text(encoding="utf-8")
    assert "if not config.OVERLAY_POINTER_ENABLED:" in src
    assert 'drop_types.add("pointer")' in src


def test_neither_factory_tells_the_model_to_add_arrows():
    """되도록 붙이라고 적어 두면 모델은 거의 매 컷에 붙인다 — 이 저장소가 실측한 그대로다."""
    for name in ("directive.py", "report_directive.py"):
        src = (ENGINE / name).read_text(encoding="utf-8")
        prompt = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        assert "되도록 붙여라" not in prompt, name
        assert "화살표로 찍어라" not in prompt, name
        assert "웬만하면 쓰지 마라" in prompt, name


def test_both_factories_tell_the_model_to_compose_instead():
    """'쓰지 마라'만 적으면 모델은 대안을 모른다 — 대신 할 일을 같이 준다."""
    for name in ("directive.py", "report_directive.py"):
        src = (ENGINE / name).read_text(encoding="utf-8")
        assert "제일 크고 한가운데" in src, name


# ── 검사가 **어느 칸인지** 말하지 않으면 고칠 수 없다 ──────────────
def test_the_quoted_label_gate_says_which_field_it_found_it_in():
    """★★ 2026-09-19 실측. 되먹임을 받은 모델이 `visual_prompt` 만 고치고 `motion_prompt` 의
    따옴표는 그대로 뒀다 — 재생성을 하고도 **같은 사유로 또 막혔다**
    (리포트 dfc74dec 컷9, `avoid the 'bad weather' spots`).
    사유가 "컷9(bad weather)" 라고만 말했기 때문이다. 어디인지 모르면 고칠 수 없다."""
    from engine import photo_contract as pc

    got = pc.quoted_label_cuts([
        {"cut_no": 9, "visual_prompt": "A clean wide shot of the Earth model.",
         "motion_prompt": "the camera avoids the 'bad weather' spots"}])
    assert got == ["컷9.motion_prompt(bad weather)"]


def test_it_names_every_field_that_carries_quotes():
    from engine import photo_contract as pc

    got = pc.quoted_label_cuts([
        {"cut_no": 3, "visual_prompt": "a dish labeled 'Control'",
         "motion_prompt": "the 'treated' dish grows"}])
    assert got[0].startswith("컷3.motion_prompt·visual_prompt(")


def test_the_prescription_names_all_three_fields():
    """처방이 칸을 말하지 않으면 모델은 눈에 띄는 칸만 고친다(실측된 실패 모드)."""
    from engine import photo_contract as pc

    fix = pc.feedback_prompt(["photo_quoted_label_in_prompt:컷9.motion_prompt(bad weather)"])
    for field in ("visual_prompt", "motion_prompt", "mechanism"):
        assert field in fix, field
    assert "겁따옴표" in fix, "이름 붙일 뜻이 없어도 글자로 그려진다는 것을 말해야 한다"
