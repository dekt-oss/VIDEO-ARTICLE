"""클립을 사기 전에 그림을 본다 + '다시 그리기'가 캐시를 타지 않는다 (2026-09-27).

① 그림($0.04~0.13) 위에 클립($0.2~0.4)을 산다. 글자가 박혔거나 주인공이 없는 그림이면 그림만
   다시 그린다. 업로드 편 실측(10장): 선체의 주황 문양(3컷)·바닥의 큰 글자(10컷)를 잡았다.
② 발견: 판정 뒤 "재생성 1회"가 _gen_still 을 그냥 다시 불러 **캐시의 같은 그림**을 받았다.
   연속성 QA 의 재생성은 캐시가 켜진 렌더에서 한 번도 실제로 일어나지 않았다.
"""

from __future__ import annotations

import inspect

from engine import config, render, still_check

CUT = {"cut_no": 3, "visual_role": "REALITY",
       "visual_prompt": "Red hull blocks move along a gantry hall. Workers guide them."}
PHOTO = {"version_type": "photo"}


def _asker(*answers):
    it = iter(answers)
    return lambda system, user, paths: next(it)


BAD = {"text_in_image": True, "subject_present": True, "reason": "glyph on hull"}
GOOD = {"text_in_image": False, "subject_present": True, "reason": "ok"}


def test_subject_is_the_first_sentence_of_what_we_asked_for():
    assert still_check.subject_of(CUT) == "Red hull blocks move along a gantry hall."


def test_two_failing_votes_fail():
    assert still_check.failed(still_check.check("x.png", CUT, _asker(BAD, BAD)))


def test_a_wobbling_verdict_does_not_spend_money():
    """같은 그림에 답이 갈리면 불합격으로 보지 않는다(실측 10장 중 1장이 흔들렸다)."""
    assert not still_check.failed(still_check.check("x.png", CUT, _asker(BAD, GOOD)))


def test_a_pass_is_asked_once():
    calls = []
    still_check.check("x.png", CUT, lambda s, u, p: calls.append(1) or GOOD)
    assert len(calls) == 1


def test_unmeasured_is_a_pass():
    assert not still_check.failed(still_check.check("x.png", CUT, _asker(None)))
    assert not still_check.failed(still_check.check("x.png", CUT, _asker({"reason": "?"})))


def test_missing_subject_fails():
    miss = {"text_in_image": False, "subject_present": False, "reason": "no hull"}
    assert still_check.failed(still_check.check("x.png", CUT, _asker(miss, miss)))


def test_only_photo_with_paid_images(monkeypatch):
    monkeypatch.setattr(still_check.continuity_qa, "enabled", lambda: True)
    monkeypatch.setattr(config, "STILL_CHECK_ENABLED", True)   # conftest 가 끈다
    assert still_check.applies(CUT, PHOTO)
    assert not still_check.applies(CUT, {"version_type": "comic"})
    monkeypatch.setattr(config, "STILL_CHECK_ENABLED", False)
    assert not still_check.applies(CUT, PHOTO)


def test_a_failed_still_is_redrawn_once_bypassing_the_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(render, "_gen_still",
                        lambda *a, **k: calls.append(k.get("force", False)) or 0.04)
    monkeypatch.setattr(still_check, "applies", lambda c, h: True)
    verdicts = iter([{"measured": True, "text_in_image": True, "subject_present": True},
                     {"measured": True, "text_in_image": False, "subject_present": True}])
    monkeypatch.setattr(still_check, "check", lambda p, c: next(verdicts))
    cost = render._obtain_still(dict(CUT), PHOTO, "img.png", asset_index=None, seq_decision=None,
                                directive_id="d", render_job_id="j", render_job_kind="report")
    assert calls == [False, True], "두 번째 그리기는 캐시를 건너뛰어야 한다"
    assert abs(cost - 0.08) < 1e-9


def test_the_continuity_retry_also_bypasses_the_cache():
    src = inspect.getsource(render._obtain_still)
    block = src[src.index("연속성 실패 → 재생성 1회"):src.index("클립을 사기 전에 그림을 본다")]
    assert "force=True" in block
