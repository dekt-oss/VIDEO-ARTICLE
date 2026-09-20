"""묻지 않은 것은 검사하지 않는다 (2026-09-20).

무엇이 문제였나. 리포트 지시서 프롬프트는 `hook_type`·`science_reliability`·
`hook_promise_check` 를 **아예 묻지 않는다.** 그런데 정규화는 빠진 자리를 기본값으로 메우고
(hook_type=H1=대담 훅, science_reliability=medium/medium,
hook_promise_check={"pass": false, "promise": ""}), 공용 경고기가 그 기본값을 **모델의
선언으로 읽었다.**

결과: `bold_hook_on_weak_evidence` 와 `hook_promise_unpaid` 가 photo 리포트 **8편 전부**에서
떴다(8/8). 같은 자리에서 `asset_reuse_below_target`·`unique_assets_over_budget` 도 8/8 이었다 —
2026-09-05 에 실사형의 스틸 복사 재사용을 코드가 막으면서 재사용 비율이 **구조적으로 0** 이
됐는데 목표는 만화식 표의 0.2 로 남아 있었기 때문이다.

**100% 뜨는 경고는 정보가 0이다.** 그리고 더 나쁜 것은, 운영자가 그 목록을 읽지 않게 되어
**진짜 문제를 놓친다**는 점이다. 이 저장소는 이미 같은 사고를 겪었다(series_split 이 100%).
"""

from __future__ import annotations

from engine import config, directive as dv


def _header(**kw):
    base = {
        "hook_type": "H1",
        "science_reliability": {"evidence_strength": "medium",
                                "generalization_risk": "medium"},
        "hook_promise_check": {"pass": False, "promise": "", "reason": ""},
        "backfilled_fields": [],
    }
    base.update(kw)
    return base


# ── ① 우리가 채운 값으로는 판정하지 않는다 ─────────────────────────
def test_a_backfilled_hook_type_is_not_read_as_a_bold_hook_declaration():
    h = _header(backfilled_fields=["hook_type", "science_reliability"])
    assert dv.bold_hook_gate_violation(h) is False


def test_a_backfilled_promise_check_is_not_read_as_an_unpaid_promise():
    h = _header(backfilled_fields=["hook_promise_check"])
    assert "hook_promise_unpaid" not in dv.directive_warnings(h, [])


# ── ② 모델이 **직접 선언한** 것은 그대로 잡는다 ────────────────────
def test_a_real_bold_hook_on_weak_evidence_is_still_caught():
    """이 완화가 게이트를 죽이면 안 된다 — 안 묻는 라인만 조용해져야 한다."""
    h = _header(science_reliability={"evidence_strength": "medium",
                                     "generalization_risk": "high"})
    assert dv.bold_hook_gate_violation(h) is True


def test_a_real_unpaid_promise_is_still_caught():
    h = _header(hook_promise_check={"pass": False, "promise": "수명 2배",
                                    "reason": "본문이 안 지불"})
    assert "hook_promise_unpaid" in dv.directive_warnings(h, [])


def test_a_declared_safe_hook_stays_quiet():
    h = _header(science_reliability={"evidence_strength": "high",
                                     "generalization_risk": "low"})
    assert dv.bold_hook_gate_violation(h) is False


# ── ③ 정규화가 **무엇을 채웠는지 기록**한다 ────────────────────────
def test_normalisation_records_which_fields_it_had_to_invent():
    """기록이 없으면 위 판정을 할 수 없다 — error-vs-empty 를 구분하는 자리다."""
    src = (dv.__file__)
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert '"backfilled_fields"' in text
    assert 'if not header_in.get(f)' in text


# ── ④ 실사형은 재사용 목표가 0 이다 ────────────────────────────────
def test_photo_gets_no_reuse_target_because_code_forbids_reuse():
    """★ 2026-09-05 에 실사형의 스틸 복사 재사용을 코드가 막았다. 비율은 늘 0 인데 목표가
    0.2 로 남아 있어 **지킬 방법이 없는 요구**가 됐다(photo 리포트 8/8).
    통일성은 참조 조건 생성이 담당한다 — 그 장치가 일하는데 "복사를 안 했다"고 경고하는
    것은 앞뒤가 안 맞는다."""
    src = (dv.__file__)
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert 'if version_type == "photo":' in text
    assert 'plan["asset_reuse_target"] = 0.0' in text


def test_photo_may_draw_one_new_picture_per_cut():
    """컷마다 다른 것을 보여주는 것이 실사형의 정의다. 상한이 컷 수보다 작으면
    **모든 편이** 초과로 뜬다(실측 8/8)."""
    assert config.PHOTO_UNIQUE_ASSET_RATIO == 1.0
    for cuts in (10, 11, 13):
        assert config.unique_assets_max("photo", 8, cuts) >= cuts, cuts


def test_other_versions_keep_their_comic_era_limits():
    """만화식은 재사용이 품질 장치다(같은 인물을 다시 그리면 얼굴이 바뀐다) — 손대지 않는다."""
    assert config.unique_assets_max("comic", 6, 10) == 6
    assert config.CONTENT_MODE_ASSET_REUSE_TARGET["standard"] == 0.2


# ── ⑤ 리포트는 이제 훅 약속을 **묻는다** ───────────────────────────
def test_the_report_prompt_now_asks_for_the_promise_check():
    """끄는 것으로만 끝내지 않는다 — 훅 약속 검증은 리포트에도 옳은 질문이고,
    실제로 이 편의 알려진 문제였다(hook_promise_unpaid)."""
    from engine import report_directive as rd

    assert "hook_promise_check" in rd.PHOTO_CONTRACT
    assert "payoff_cut_no" in rd.PHOTO_CONTRACT
