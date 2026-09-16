"""기전 컷 수는 **고정이 아니라 영상 길이에서 파생**된다(운영자 지시 2026-09-04).

지시 원문: "영상 길이나 원래 소스내용에 따라서 길이조절이들어갈꺼니까 기전은 유동적으로
조절되도록 하는게 좋은거같긴하네"

간격의 근거는 실측이다 — 발행 벤치마크(신비한 건축사전 시화호 편)가 **105초에 기전 3회**였다:
원인(방조제가 물길을 끊었다) · 재정의(오염이 아니라 호수 자체) · 해법(구멍+터빈).
105 / 3 = 35초당 1회.

★ 이 파일이 지키는 것 둘:
  ① 벤치마크 재현 — 105초를 넣으면 3이 나와야 한다(간격의 근거가 살아 있는가).
  ② **프롬프트와 게이트가 같은 숫자를 말하는가** — 이 저장소가 세 번 겪은 사고다
    (영상 상한·에셋 상한·컷 수). 프롬프트가 고정값을 말하고 게이트가 역산하면
    모델은 자기가 몇 개를 내야 하는지 알 수가 없다.
"""

from __future__ import annotations

import re

from engine import config, content_mode, directive
from engine import photo_contract as pc


def test_the_benchmark_reproduces_its_own_measurement():
    """105초 → 3개. 이게 안 나오면 간격(35초)의 근거가 끊긴 것이다."""
    assert pc.min_mechanism_cuts(105) == 3


def test_it_scales_with_length_and_is_not_a_constant():
    got = [pc.min_mechanism_cuts(s) for s in (30, 60, 105, 140)]
    assert got == sorted(got), got
    assert len(set(got)) > 1, f"길이가 4배 늘었는데 요구가 그대로다: {got}"


def test_short_videos_still_need_one_principle():
    """★ 0개를 허용하면 '설명 영상'이 '소식'으로 되돌아간다 — 그게 원래 결함이었다."""
    for sec in (0, 5, 20, 35):
        assert pc.min_mechanism_cuts(sec) >= 1


def test_long_videos_are_capped_so_the_model_does_not_invent_causality():
    """★ 상한은 비용이 아니라 **환각 방지**다. 기전이 얇은 소스에 더 요구하면 지어낸다."""
    assert pc.min_mechanism_cuts(10_000) == config.PHOTO_MIN_MECHANISM_CUTS_CAP


def test_our_real_directive_needs_two():
    """실측 지시서(71초, 13컷)는 2개가 필요하다 — 실제로는 0개였다."""
    assert pc.min_mechanism_cuts(71) == 2


def test_prompt_and_gate_quote_the_same_number_for_every_mode():
    """★★ 이 저장소가 세 번 겪은 '프롬프트와 코드가 다른 숫자를 말한다'의 재발 방지.

    각 모드의 길이 범위 양끝에서, 프롬프트가 보여주는 수와 게이트가 요구하는 수가 같아야 한다.
    """
    for mode in config.CONTENT_MODE_DURATION:
        lo, hi = content_mode.duration_range(mode)
        text = directive._mode_guidance({"selected_mode": mode}, "photo", 13)
        block = re.search(r"\[기전 컷 수\][^\[]*", text)
        assert block, f"{mode}: [기전 컷 수] 블록이 없다"
        head = block.group(0).split("이상이다")[0]
        shown = {int(x) for x in re.findall(r"\d+", head)}
        expected = {pc.min_mechanism_cuts(lo), pc.min_mechanism_cuts(hi)}
        assert shown == expected, f"{mode}: 프롬프트 {shown} vs 게이트 {expected}"


def test_the_prompt_also_states_the_formula_not_only_the_number():
    """범위 밖 초수를 적으면 숫자만으로는 어긋난다 — 공식을 함께 줘야 모델이 맞출 수 있다."""
    text = directive._mode_guidance({"selected_mode": "standard"}, "photo", 13)
    assert "전체 초수 ÷" in text and str(config.PHOTO_MECHANISM_SEC_PER_CUT) in text


def test_the_arc_no_longer_hardcodes_a_count():
    """골격 문장이 고정 개수를 말하면 주입된 값과 싸운다."""
    assert "최소 2개" not in directive.PHOTO_NARRATIVE_ARC


def test_the_warning_reports_the_length_derived_requirement():
    """경고 문자열이 '지금 몇 개 < 필요한 몇 개'를 보여줘야 고칠 수 있다."""
    cuts = [{"cut_no": i, "estimated_sec": 6, "evidence_role": "primary_result",
             "visual_role": "REALITY", "visual_prompt": "a photo", "motion_prompt": "hold",
             "narration_ko": "결과입니다", "narration_en": "a result"} for i in range(1, 13)]
    # ★ 소재가 기전을 **2개 이상** 대야 길이 역산값(2)이 그대로 요구가 된다.
    #   출처가 대는 것보다 많이 설명할 수는 없다(2026-09-04 실측 교훈).
    fs = {"claims": [{"claim_kind": "mechanism"}, {"claim_kind": "author_interpretation"}]}
    out = pc.evaluate({"version_type": "photo", "hook_ko": "훅",
                       "total_estimated_sec": 72}, cuts, fs)
    hits = [w for w in out["warnings"] if w.startswith("photo_narrative_no_mechanism")]
    assert hits == ["photo_narrative_no_mechanism:0<2"], out["warnings"]
    assert out["stats"]["mechanism_evidence_required"] == 2


def test_the_requirement_never_exceeds_what_the_source_supplies():
    """★★ 오늘의 핵심 교훈: 원문에 'why' 가 0회인 논문에 원리 2개를 요구하면 지어내라는 말이다.

    실측(고정 대상 논문): 전문 46,952자에 mechanism 0회·we argue 0회·driven by 0회,
    Fact Sheet 의 기전급 주장은 author_interpretation 1건. 길이 역산은 2를 요구했다.
    """
    cuts = [{"cut_no": i, "estimated_sec": 6, "evidence_role": "primary_result",
             "visual_role": "REALITY", "visual_prompt": "a photo", "motion_prompt": "hold",
             "narration_ko": "결과입니다", "narration_en": "a result"} for i in range(1, 13)]
    h = {"version_type": "photo", "hook_ko": "훅", "total_estimated_sec": 72}
    one = pc.evaluate(h, cuts, {"claims": [{"claim_kind": "author_interpretation"}]})
    assert one["stats"]["mechanism_evidence_required"] == 1

    none = pc.evaluate(h, cuts, {"claims": [{"claim_kind": "main_result"}]})
    assert none["stats"]["mechanism_evidence_required"] == 0
    assert "photo_source_has_no_mechanism" in none["warnings"]
    # ★ 소재가 없으면 "기전이 모자라다"고 벌하지 않는다 — 그건 선별 단계의 문제다.
    assert not any(w.startswith("photo_narrative_no_mechanism") for w in none["warnings"])
