"""시퀀스 코드 폴백은 **조용히** 일어나면 안 된다 (2026-09-21).

무엇이 문제였나. 2026-09-19 에 리포트 시퀀스를 모델이 쓰게 바꾸면서, 모델이 아예 안 쓰면
옛 코드 경로(`equity_visual.build_for_directive`)로 물러서게 두었다. 시퀀스 0개보다 낫다는
판단이었고 그건 맞다 — 그런데 **로그만 찍었다.**

그 폴백 경로는 컷이 무엇을 그리든 2번째 stage 부터 무조건 `CONTINUE_WORLD` 를 찍는다.
운영자가 통째로 폐기한 편이 거기서 나왔다: "좁은 파이프의 3D 단면"이라고 적힌 컷에 앞 컷의
위성 그림이 참조로 붙어 **파이프가 화면에 아예 안 나왔고**, 세 컷이 사실상 같은 그림이 됐다.

실측(2026-09-21): A/B 9벌에서 세 모델이 **모두 3/3** 으로 시퀀스를 썼다 — 어려운 요구가
아니다. 그런데 운영 경로의 재생성 한 회차가 빠뜨렸고, 승인 화면에는 아무것도 안 떴다.
운영자는 로그를 읽지 않는다.

**되물으면 되는 종류다.** 그래서 경고로 띄우고, 재생성 대상에 넣고, 처방과 라벨을 붙인다.
"""

from __future__ import annotations

import pathlib

from engine import config, photo_contract as pc

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE = "report_sequences_from_code_fallback"


def test_the_fallback_raises_a_warning_the_approval_screen_can_see():
    src = (ROOT / "engine" / "report_directive.py").read_text(encoding="utf-8")
    assert f'warns.append("{CODE}")' in src
    assert "fell_back" in src


def test_it_is_retryable_so_the_model_gets_asked_again():
    """A/B 9벌에서 3/3·3/3·3/3 이었다 — 한 번 더 물으면 거의 언제나 쓴다."""
    assert CODE in config.RETRYABLE_QUALITY_WARNINGS


def test_the_report_generator_retries_on_that_warning_even_without_a_block():
    """★ 폴백은 **차단을 만들지 않는다** — 멀쩡한 지시서가 나오기 때문이다.
    차단만 보고 재생성하면 이 경우가 영영 안 잡힌다."""
    src = (ROOT / "engine" / "report_directive.py").read_text(encoding="utf-8")
    assert "RETRYABLE_QUALITY_WARNINGS" in src
    assert "and (blocks or retryable)" in src


def test_the_prescription_tells_the_model_what_to_do_and_why():
    fix = pc.feedback_prompt([], [CODE])
    assert "visual_sequences" in fix
    assert "파이프" in fix, "왜 나쁜지를 실측으로 말해야 모델이 따른다"


def test_the_operator_sees_korean_not_a_code():
    labels = (ROOT / "web" / "lib" / "blockLabels.ts").read_text(encoding="utf-8")
    assert CODE in labels
    assert "코드가 대신 만듦" in labels


def test_the_old_path_still_exists_because_zero_sequences_is_worse():
    """폴백을 없애자는 것이 아니다 — 보이게 하자는 것이다."""
    src = (ROOT / "engine" / "report_directive.py").read_text(encoding="utf-8")
    assert "equity_visual.build_for_directive(" in src
