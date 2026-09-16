"""연속성 멀티모달 QA — stage 전후 그림이 같은 세계인가 (계획서 Phase 3 D2).

★ 무엇을 지키는가: 이 판정은 **틀렸을 때 유료 재생성을 부른다.** 그래서 여기서 박는 것은
  "잡는가"보다 **"판정 불가를 실패로 읽지 않는가"** 다 — 키가 없거나 호출이 실패했을 때
  재생성이 돌면 돈이 조용히 새고, 원인은 로그 한 줄로만 남는다.
"""

from __future__ import annotations

import dataclasses

from engine import continuity_qa as cq


def _with_key(monkeypatch, key: str) -> None:
    """SECRETS 는 frozen dataclass 라 필드만 바꿀 수 없다 — 통째로 갈아 끼운다."""
    monkeypatch.setattr(cq.config, "SECRETS",
                        dataclasses.replace(cq.config.SECRETS, gemini_api_key=key))


# ── 판정 계약 (순수 함수) ─────────────────────────────────────

def test_a_changed_world_is_a_failure():
    assert cq.failed({"measured": True, "same_world": False}) is True


def test_a_continuous_world_is_not_a_failure():
    assert cq.failed({"measured": True, "same_world": True}) is False


def test_unmeasured_is_never_a_failure():
    """★ 판정 불가와 실패를 섞지 않는다. 섞으면 키가 없을 때 매 컷이 재생성된다."""
    assert cq.failed({"measured": False, "same_world": None}) is False
    assert cq.failed({"measured": False, "same_world": False}) is False


def test_missing_verdict_is_not_a_failure():
    assert cq.failed(None) is False
    assert cq.failed({}) is False


# ── 언제 도는가 ───────────────────────────────────────────────

def test_it_does_not_run_on_the_free_placeholder_path(monkeypatch):
    """placeholder 렌더는 그림이 회색 사각형이라 판정할 것이 없다 — 돈만 나간다."""
    monkeypatch.setattr(cq.config, "IMAGE_PROVIDER", "placeholder")
    monkeypatch.setattr(cq.config, "CONTINUITY_QA_ENABLED", True)
    assert cq.enabled() is False


def test_it_does_not_run_without_a_key(monkeypatch):
    monkeypatch.setattr(cq.config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(cq.config, "CONTINUITY_QA_ENABLED", True)
    _with_key(monkeypatch, "")
    assert cq.enabled() is False


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(cq.config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(cq.config, "CONTINUITY_QA_ENABLED", False)
    _with_key(monkeypatch, "k")
    assert cq.enabled() is False


def test_it_runs_on_the_paid_path_with_a_key(monkeypatch):
    monkeypatch.setattr(cq.config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(cq.config, "CONTINUITY_QA_ENABLED", True)
    _with_key(monkeypatch, "k")
    assert cq.enabled() is True


# ── 호출 실패 처리 ────────────────────────────────────────────

def test_a_missing_file_returns_unmeasured_not_an_exception():
    """판정이 렌더를 죽이지 않는다 — 화면이 비는 것이 가장 나쁜 결말이다."""
    out = cq.judge("/does/not/exist.png", "/nope.png")
    assert out["measured"] is False


# ── 배선 ──────────────────────────────────────────────────────

def test_the_verdict_reaches_the_existing_degraded_channel():
    """새 표면을 만들지 않는다 — degraded_summary 가 이미 세는 그릇에 넣는다."""
    import inspect

    from engine import render, sequence_render

    src = inspect.getsource(render._obtain_still)
    assert "continuity_qa.failed(continuity_qa.judge(ref_path, img_path))" in src
    assert 'dec.setdefault("degraded", []).append(' in src
    # 그릇이 실제로 그 코드를 센다.
    summary = sequence_render.degraded_summary(
        [{"stage_id": "S1", "kind": "reference",
          "degraded": [cq.DEGRADED_WORLD_CHANGED]}])
    assert summary["degraded_continuity"][cq.DEGRADED_WORLD_CHANGED] == 1


def test_it_regenerates_once_and_then_gives_up():
    """계획서 D2 그대로 — 재생성은 1회다. 무한 재시도는 비용이 상한 없이 늘어난다."""
    import inspect

    from engine import render

    src = inspect.getsource(render._obtain_still)
    # 판정 2회(최초 + 재생성 뒤), 재생성 1회.
    assert src.count("continuity_qa.judge(ref_path, img_path)") == 2
    body = src.split("if ref_path and continuity_qa.enabled():")[1]
    assert body.count("_gen_still(") == 1


def test_the_check_only_runs_when_there_is_a_reference():
    """참조가 없으면 '이어졌는가'라는 질문 자체가 성립하지 않는다."""
    import inspect

    from engine import render

    src = inspect.getsource(render._obtain_still)
    assert "if ref_path and continuity_qa.enabled():" in src


def test_the_regeneration_cost_is_counted():
    """재생성도 돈이 나간다 — 원장이 절반으로 거짓말하지 않게 cost 에 더한다."""
    import inspect

    from engine import render

    src = inspect.getsource(render._obtain_still)
    assert "cost += _gen_still(" in src
