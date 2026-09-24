"""화면 구성 계약 — "장면 자체가 설명이다" (2026-09-24, 운영자 지시).

운영자가 참고 영상을 주고 말한 것: 화살표·게이지 같은 장치가 아니라 **전체적으로 이해를
돕는 화면 구성**. 그 영상들은 나레이션이 던진 질문에 장면이 물건과 행위로 답한다
("물이 얼마나 더러운지" → 손이 유리병으로 물을 뜬다 → 흙탕이 가라앉는다).

실측(scripts/staging_shadow.py, 565컷): 실사 컷이 나레이션에 답하는 비율 리포트 41% ·
논문 31%. 도해 컷은 75~77% — 구조를 강제하니 답한다. 실사에도 그 강제를 준다.

이 파일이 지키는 것: 두 공장이 **같은** 계약을 받고, 정규화가 그 칸을 버리지 않는다.
"""

from __future__ import annotations

from engine import directive as dv, report_directive as rd


def test_both_factories_carry_the_same_staging_contract():
    """두 벌이면 한쪽만 낡는다(SEQUENCE_SCHEMA 와 같은 규율)."""
    paper = dv.directive_user_prompt(
        {"script_md": "문장.", "fact_sheet": {}, "scenes": []}, "photo")
    report = rd.report_directive_user_prompt(
        {"script_md": "문장.", "fact_sheet": {}, "scenes": [], "financial_reasoning": None}, "photo")
    assert dv.STAGING_CONTRACT in paper
    assert dv.STAGING_CONTRACT in report


def test_the_contract_is_photo_only():
    """만화식은 컷마다 새 장면이라 '주인공 하나·이어받기'가 맞지 않는다."""
    comic = dv.directive_user_prompt(
        {"script_md": "문장.", "fact_sheet": {}, "scenes": []}, "comic")
    assert dv.STAGING_CONTRACT not in comic


def test_the_contract_says_what_the_reference_videos_do():
    c = dv.STAGING_CONTRACT
    assert "answers_ko" in c and "staging_ko" in c
    assert "주인공 하나" in c
    assert "행위" in c and "숫자·글자는 그리지 않는다" in c
    assert "이어받거나 그 안으로 들어간다" in c


def test_normalize_keeps_the_two_fields():
    """정규화가 모르는 키를 버리므로, 여기 없으면 승인 화면에 영영 안 보인다."""
    from tests.test_photo_contract import _raw
    raw = _raw("좋은 훅")
    raw["cuts"][0]["answers_ko"] = "물이 얼마나 더러운가"
    raw["cuts"][0]["staging_ko"] = "손이 유리병으로 물을 뜨고 흙탕이 가라앉는다"
    d = dv.normalize_directive(raw, "photo")
    assert d["cuts"][0]["answers_ko"] == "물이 얼마나 더러운가"
    assert d["cuts"][0]["staging_ko"].startswith("손이 유리병")
    assert d["cuts"][1]["answers_ko"] == "", "없는 칸은 빈 문자열 — None 이 아니다"


# ── 범례는 기본 꺼짐 (2026-09-24 운영자: "무슨 의미야?? 없애도 될듯") ──────────
def test_the_legend_is_off_by_default_everywhere():
    """스위치 하나가 렌더·프롬프트·게이트 셋을 같이 끈다 — 한 곳만 켜져 있으면 함정이 된다."""
    from engine import config, photo_contract as pc
    assert config.OVERLAY_LEGEND_ENABLED is False
    # 프롬프트가 범례를 요구하지 않는다
    paper = dv.directive_user_prompt({"script_md": "문장.", "fact_sheet": {}, "scenes": []}, "photo")
    report = rd.report_directive_user_prompt(
        {"script_md": "문장.", "fact_sheet": {}, "scenes": [], "financial_reasoning": None}, "photo")
    assert "기전 시퀀스마다 legend 하나는 있어야 한다" not in paper
    assert "legend 를 넣어 무슨 색이 무엇인지 말하라" not in report
    assert "범례(legend)는 쓰지 않는다" in dv.STAGING_CONTRACT
    # 게이트가 범례를 요구하지 않는다(label_pair 요구는 그대로다)
    from tests.test_mechanism_teaching import _cut, _header, _stage
    got = pc.evaluate(_header([_stage("S1", 3), _stage("S2", 4)]), [_cut(3), _cut(4)])
    assert not any(w.startswith("photo_mechanism_unlabeled") for w in got["warnings"])


def test_the_render_drops_the_legend_when_the_switch_is_off():
    import inspect
    from engine import render
    src = inspect.getsource(render)
    assert "if not config.OVERLAY_LEGEND_ENABLED:" in src
    assert 'drop_types | {"legend"}' in src


def test_the_operator_feedback_is_in_the_contract():
    c = dv.STAGING_CONTRACT
    assert "한눈에 알아볼 사물" in c and "바지선에 얹힌 각진 데이터센터 건물" in c
    assert "원인이 화면에 있어야 한다" in c and "꽉 찬 해안" in c
    assert "화면에는 이번 컷의 주인공만" in c
