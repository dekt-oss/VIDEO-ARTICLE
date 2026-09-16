"""선별에 원리 축(A) + 소재가 원리를 못 대면 판형 교체(B) — 운영자 지시 2026-09-04.

지시: "a로 해줘. 그리고 a와 b 둘다 진행가능한거아니야??" — 맞다. 둘은 짝이다.
  A) 채점이 "이 논문이 왜인지를 설명하는가"를 묻는다 → 기전 있는 논문이 위로 온다.
  B) 그래도 기전 없는 논문은 들어온다 → 버리지 않고 **관측 앵커 판형**으로 보낸다.

★ 왜 이 둘이 필요했나(실측): 고정 대상 논문의 원문 전문 46,952자에
  mechanism 0회 · we argue 0회 · driven by 0회 · the reason 0회 · why 0회.
  그 논문으로 "3D 도해로 원리를 설명하는 영상"을 만들려다 화면이 겉돌았고,
  프롬프트를 고치고 또 겉돌기를 반복했다. 화면 엔진이 풀 수 있는 문제가 아니었다.
"""

from __future__ import annotations

import pathlib

from engine import config, directive, scoring
from engine import photo_contract as pc


# ── A. 선별 축 ───────────────────────────────────────────────
def test_the_axis_exists_and_is_not_the_same_as_explain_60s():
    """★ 둘은 다르다: '60초에 설명 가능한가' vs '논문이 설명을 제공하는가'.
    결과만 있는 논문도 explain_60s 는 높다('이 조합이 나빴다'는 쉽다)."""
    assert "mechanism" in config.PRODUCTION_AXES
    assert "explain_60s" in config.PRODUCTION_AXES


def test_the_rubric_warns_against_confusing_the_two():
    assert "explain_60s 와 헷갈리지 마라" in scoring.SCORING_SYSTEM
    assert '"mechanism": {"score"' in scoring.SCORING_SYSTEM


def test_the_gate_is_a_ratio_so_adding_an_axis_cannot_move_anyone():
    """★★ 축을 늘리면 만점이 커진다. 정수 문턱이면 **같은 논문의 등급이 저절로 움직인다.**

    실측(2026-09-04): 정수 문턱을 그대로 두면 저장된 3,976행 중 1,284행이 움직였고
    (make→redesign 681행), 비율에 맞춰 정수를 옮겨도 0.8×12=9.6 이라 정확히 옮길 수가 없어
    508행이 여전히 움직였다. 그 논문들은 아무것도 나빠지지 않았다 — 자만 바뀌었다.
    """
    assert config.PRODUCTION_SCORE_MAX == 2 * len(config.PRODUCTION_AXES)
    assert (config.PRODUCTION_GATE_MAKE_RATIO,
            config.PRODUCTION_GATE_REDESIGN_RATIO,
            config.PRODUCTION_GATE_BACKLOG_RATIO) == (0.8, 0.6, 0.4)


def test_an_old_five_axis_row_keeps_the_exact_grade_it_had():
    """★★ 이 검사가 회귀의 핵심이다 — 옛 채점 행은 **옛 자로** 재야 한다."""
    for total, expected in ((10, "make"), (8, "make"), (7, "redesign"), (6, "redesign"),
                            (5, "backlog"), (4, "backlog"), (3, "hold"), (0, "hold")):
        assert scoring.production_gate(total, 10) == expected, (total, expected)


def test_a_new_six_axis_row_uses_the_same_ratios():
    for total, expected in ((12, "make"), (10, "make"), (9, "redesign"), (8, "redesign"),
                            (7, "backlog"), (5, "backlog"), (4, "hold")):
        assert scoring.production_gate(total, 12) == expected, (total, expected)


def test_stored_scale_recognises_a_legacy_row_by_its_axes():
    legacy = {"axes": {k: {"score": 2} for k in config.PRODUCTION_AXES if k != "mechanism"}}
    assert scoring.stored_scale(legacy) == 10
    assert scoring.stored_scale({"max": 12}) == 12
    assert scoring.stored_scale(None) == config.PRODUCTION_SCORE_MAX


def test_a_perfect_score_still_reaches_make():
    assert scoring.production_gate(config.PRODUCTION_SCORE_MAX) == "make"


def test_the_new_axis_is_parsed_and_counted():
    got = scoring.parse_production(
        {a: {"score": 2, "why": "x"} for a in config.PRODUCTION_AXES})
    assert got["total"] == config.PRODUCTION_SCORE_MAX
    assert "mechanism" in got["axes"]


def test_a_results_only_paper_is_penalised_but_not_banned():
    """★★ 이 축은 **막는 장치가 아니라 고르는 장치**다 — 의도를 여기 박아 둔다.

    원리가 0인 논문도 좋은 영상이 될 수 있다(선택지 B 의 관측 앵커 판형). 그래서 다른 축이
    전부 만점이면 여전히 make 다. 이 축이 하는 일은 **같은 조건에서 원리 있는 논문을 위로
    올리는 것**이고, 경계에 있는 논문을 한 등급 내리는 것이다.

    ★ 처음 이 테스트를 "원리 0이면 make 를 못 받아야 한다"로 썼다가 실패했고,
      **게이트를 조여서 통과시키지 않았다.** 그건 검사에 맞춰 설계를 비트는 것이다.
    """
    full = {a: {"score": 2, "why": "x"} for a in config.PRODUCTION_AXES}
    no_mech = dict(full, mechanism={"score": 0, "why": "결과만 보고한다"})
    a, b = scoring.parse_production(full), scoring.parse_production(no_mech)
    assert a["total"] - b["total"] == 2 * 1          # 축 하나만큼 정확히 깎인다
    assert b["gate"] == "make"                        # 다른 축이 완벽하면 여전히 만든다
    # 경계에 있던 논문은 이 축 때문에 한 등급 내려간다 — 그것이 "고르는" 효과다.
    edge = {a2: {"score": 2, "why": "x"} for a2 in config.PRODUCTION_AXES}
    edge["novelty"] = {"score": 0, "why": "뻔하다"}
    edge["mechanism"] = {"score": 0, "why": "결과만"}
    assert scoring.parse_production(edge)["gate"] != "make"


def test_the_web_shows_each_row_on_its_own_scale():
    """★ 화면에 10 이 하드코딩돼 있었다. 그렇다고 12 를 박으면 옛 행이 '8/12' 로 보여
    등급이 내려간 것처럼 읽힌다 — **행마다 자기 만점**을 쓴다."""
    ts = (pathlib.Path("web") / "lib" / "blockLabels.ts").read_text(encoding="utf-8")
    assert f"PRODUCTION_SCORE_MAX = {config.PRODUCTION_SCORE_MAX}" in ts
    assert "PRODUCTION_LEGACY_SCORE_MAX = 10" in ts
    tbl = (pathlib.Path("web") / "components" / "ScoredTable.tsx").read_text(encoding="utf-8")
    assert "/10" not in tbl, "만점이 하드코딩돼 있다"
    assert "r.production_max" in tbl, "행별 만점을 쓰지 않는다"
    q = (pathlib.Path("web") / "lib" / "queries.ts").read_text(encoding="utf-8")
    assert "production_max" in q and "PRODUCTION_LEGACY_SCORE_MAX" in q


# ── B. 판형 교체 ─────────────────────────────────────────────
def _prompt(claims):
    row = {"script_md": "한 문장.", "fact_sheet": {"claims": claims},
           "video_flow": {}, "video_prompts": {}}
    return directive.directive_user_prompt(row, "photo")


def test_a_paper_without_mechanism_gets_the_observation_playbook():
    p = _prompt([{"claim_kind": "main_result"}])
    assert "판형을 바꿔라" in p
    assert "규모 실감" in p and "조건 대비" in p


def test_a_paper_with_mechanism_does_not_get_it():
    """★ 원리가 있는 논문에까지 '도해를 줄여라'가 가면 좋은 소재를 망친다."""
    assert "판형을 바꿔라" not in _prompt([{"claim_kind": "mechanism"}])
    assert "판형을 바꿔라" not in _prompt([{"claim_kind": "author_interpretation"}])


def test_the_playbook_forbids_inventing_causality():
    """★ 제1 불변식 — 없는 인과를 만들면 안 된다."""
    p = _prompt([{"claim_kind": "main_result"}])
    assert "지어내는 것이다" in p and "지어내지 말고" in p


def test_the_gate_and_the_playbook_agree_on_the_same_source():
    """★★ 게이트가 '요구 0'인데 프롬프트는 '도해 5~7개'를 요구하면 둘이 싸운다 —
    이 저장소가 네 번 겪은 '프롬프트와 코드가 다른 말을 한다'의 재발 방지."""
    claims = [{"claim_kind": "main_result"}]
    fs = {"claims": claims}
    cuts = [{"cut_no": i, "estimated_sec": 6, "evidence_role": "primary_result",
             "visual_role": "REALITY", "visual_prompt": "a photo", "motion_prompt": "hold",
             "narration_ko": "결과", "narration_en": "r"} for i in range(1, 13)]
    r = pc.evaluate({"version_type": "photo", "hook_ko": "훅",
                     "total_estimated_sec": 72}, cuts, fs)
    assert r["stats"]["mechanism_evidence_required"] == 0
    assert "판형을 바꿔라" in _prompt(claims)
