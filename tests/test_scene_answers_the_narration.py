"""실사 컷이 나레이션에 **답하는가** — 화면 구성 계약이 약속한 검사 (2026-09-27).

무엇이 있었나
------------
directive.STAGING_CONTRACT 는 모델에게 "판정 모델이 본다, 주제만 같은 사진은 되돌려 보낸다"고
말했는데 그 검사가 없었다. 업로드한 편(620e66be)의 약한 두 컷 — 밸류에이션 나레이션에 설계
사무실 책상, '영업이익 13.7조' 에 드라이독 전경 — 이 그대로 나갔다. 그림자 측정(596컷)에서
그 두 컷이 답함 0.04·0.03 으로 최하점이었다.

★ 경고(되묻기)이고 fail-open 이다. Jev 가 죽으면 종전 동작(경고 없음).
★ 연결 문장("바로 설명합니다")은 어떤 장면으로도 답할 수 없으니 벌하지 않는다(showable).
"""

from __future__ import annotations

from engine import config, decide, directive as dv, photo_contract as pc
from tests.test_photo_contract import _good_directive


def _real_cuts():
    header, cuts = _good_directive(10)
    real = [c for c in cuts if c.get("visual_role") == "REALITY"]
    assert real, "고정 지시서에 실사 컷이 있어야 한다"
    return header, cuts, real


def _judge(monkeypatch, fn):
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "scene_answers", fn)


def _flag(got):
    return [w for w in got["warnings"] if w.startswith("photo_scene_not_answering")]


def test_a_topic_photo_is_warned_with_its_cut_number(monkeypatch):
    header, cuts, real = _real_cuts()
    weak_no = real[0]["cut_no"]
    real[0]["narration_ko"] = "밸류에이션은 2023년 이후 최저다."
    _judge(monkeypatch, lambda n, v: {"answers": 0.04 if "최저" in n else 0.9, "showable": 0.7})
    got = pc.evaluate(header, cuts, None)
    assert _flag(got) == [f"photo_scene_not_answering:{weak_no}"], got["warnings"]
    assert not any(b.startswith("photo_scene_not_answering") for b in got["block_reasons"]), \
        "경고이지 차단이 아니다"


def test_a_transition_line_is_not_punished(monkeypatch):
    """'바로 설명합니다'에는 답할 장면이 없다 — 옳게 쓴 지시서를 벌하지 않는다."""
    header, cuts, _ = _real_cuts()
    _judge(monkeypatch, lambda n, v: {"answers": 0.02, "showable": 0.1})
    assert _flag(pc.evaluate(header, cuts, None)) == []


def test_a_dead_judge_means_no_warning(monkeypatch):
    header, cuts, _ = _real_cuts()
    _judge(monkeypatch, lambda n, v: None)
    assert _flag(pc.evaluate(header, cuts, None)) == []


def test_the_judge_is_not_called_when_off(monkeypatch):
    """conftest 가 Jev 를 끈다 — 테스트·로컬은 네트워크 0."""
    header, cuts, _ = _real_cuts()
    monkeypatch.setattr(decide, "scene_answers",
                        lambda n, v: (_ for _ in ()).throw(AssertionError("불렸다")))
    assert _flag(pc.evaluate(header, cuts, None)) == []


def test_mechanism_cuts_are_not_asked(monkeypatch):
    """도해는 구조로 이미 강제된다(답함 70~76%) — 이 질문은 실사 컷용이다."""
    header, cuts, real = _real_cuts()
    asked = []
    _judge(monkeypatch, lambda n, v: asked.append(v) or {"answers": 0.9, "showable": 0.9})
    pc.evaluate(header, cuts, None)
    assert sorted(asked) == sorted(str(c.get("visual_prompt") or "") for c in real)


def test_the_warning_is_retryable_and_has_a_prescription():
    assert "photo_scene_not_answering" in config.RETRYABLE_QUALITY_WARNINGS
    assert "photo_scene_not_answering" in pc.WARNING_REASONS
    fix = pc.feedback_prompt([], ["photo_scene_not_answering:2,3"])
    assert "staging_ko" in fix and "물건과 행위" in fix
    assert "개수로 바꾸지도 마라" in fix, "처방이 숫자를 물건 개수로 그리라고 시키면 안 된다(운영자 판정)"


def test_the_prompt_promise_names_the_real_check():
    """계약 문구가 약속한 검사가 실제 사유 코드로 존재한다(검사·고지·되먹임 셋)."""
    assert "photo_scene_not_answering" in dv.STAGING_CONTRACT


def test_scene_answers_asks_both_questions_in_one_call(monkeypatch):
    seen = {}

    def fake_post(body):
        seen.update(body)
        return {"answers": {k: {"noul": 0.2} for k in body["questions"]}, "usage": {}}
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "_post", fake_post)
    monkeypatch.setattr(decide, "_record", lambda *_a: None)
    assert decide.scene_answers("나레이션", "scene") == {"answers": 0.2, "showable": 0.2}
    assert set(seen["questions"]) == {"answers", "showable"}
    assert "NARRATION: 나레이션" in seen["state"] and "SCENE: scene" in seen["state"]
    assert decide.scene_answers("", "scene") is None
