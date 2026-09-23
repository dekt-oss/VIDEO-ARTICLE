"""Jev 는 게이트를 **풀기만** 한다 (2026-09-22).

무엇을 푸는가. 이 저장소의 화면 게이트는 대부분 정규식인데, "따옴표가 그려 달라는
라벨인가 겁따옴표인가"는 **정규식으로 못 갈랐다.** 저장된 159건에 규칙을 대 봤더니
`bars for 'NASDAQ'`(라벨)과 `the 'cost' of`(겁따옴표)가 같은 형태였다 — 가설을 세우고
실측으로 기각한 자리다.

Jev(TypeSafe System One)는 그 자리에 맞는다: typed 판정만 내고 출력 토큰이 과금되지 않는다.
실측(저장된 photo 컷 492개): 차단 31 → 18, **오탐 13건 제거**, 컷당 52ms, 비용 $0.0004.

★★ **그런데 Jev 도 틀린다 — 하필 실측 사고를 낸 문장을.**
    `represents 'Calorie Restriction'` → 0.42 (라벨 아님으로 판정)
  그 문장은 2026-09-07 에 다섯 개가 그대로 그림에 영어 글자로 박힌 바로 그 문장이다.
  그래서 이 배선의 **모양**이 전부다:

      ① 명백한 라벨 동사(labeled/titled/represents…) → 정규식이 **무조건** 막는다
      ② 동사 없이 따옴표만 → 그때만 Jev 에게 묻고, 겁따옴표면 **푼다**

  Jev 가 틀려도, 죽어도, 꺼져도 게이트가 약해지지 않는다. 이 파일이 지키는 것이 그것이다.
"""

from __future__ import annotations

import pathlib

import pytest

from engine import config, decide, photo_contract as pc

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _cut(no, prompt):
    return {"cut_no": no, "visual_prompt": prompt}


# ── ① 배포 기본은 꺼짐 · 테스트는 **무조건** 네트워크 0 ────────────
#
# ★ 2026-09-22 에 여기가 한 번 깨졌다. 운영자가 Jev 를 켜라고 해서 `.env` 에
#   `JEV_ENABLED=1` 을 넣었더니 `config` 가 그걸 읽어 **테스트 스위트가 라이브 API 를
#   때리기 시작했다.** 그래서 둘을 갈랐다:
#     · 배포 기본값(코드에 적힌 값)은 여전히 꺼짐인가 → 소스를 읽어 확인한다
#     · 테스트가 실제로 부르지 않는가 → conftest 가 `decide.enabled` 를 막는다
def test_the_shipped_default_is_off_so_a_fresh_checkout_calls_nothing():
    src = (ROOT / "engine" / "config.py").read_text(encoding="utf-8")
    assert '_get_bool("JEV_ENABLED", False)' in src, \
        "배포 기본값이 켜짐이 되면, 키만 있으면 아무 데서나 호출이 나간다"


def test_tests_never_reach_the_live_judge(monkeypatch):
    """운영자가 .env 로 켜 두어도 테스트는 네트워크를 안 탄다(conftest 가 막는다)."""
    assert decide.enabled() is False


def test_with_it_off_the_gate_behaves_exactly_as_before():
    got = pc.quoted_label_cuts([_cut(1, "the camera avoids the 'bad weather' spots")])
    assert got == ["컷1.visual_prompt(bad weather)"], "꺼짐 상태에서 판정이 바뀌면 안 된다"


# ── ② 명백한 라벨 동사는 **묻지 않고** 막는다 ──────────────────────
@pytest.mark.parametrize("text", [
    "a dish labeled 'Control' beside another",
    "The left model represents 'Calorie Restriction'.",   # ← 실측 사고 문장
    "a satellite labeled 'Kepler' orbits Earth",
    "a report titled 'Analysis' on the desk",
    "a sign reading 'Exit' above the door",
])
def test_label_verbs_never_reach_the_judge(text, monkeypatch):
    """Jev 를 켜고 **틀린 답을 주도록** 해도 막혀 있어야 한다."""
    monkeypatch.setattr(config, "JEV_ENABLED", True)
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "quoted_label_is_scare_quote",
                        lambda _t: (_ for _ in ()).throw(
                            AssertionError("라벨 동사가 있는데 판정 모델을 불렀다")))
    assert pc.quoted_label_cuts([_cut(1, text)]), text


# ── ③ 애매한 구간만 풀린다 ─────────────────────────────────────────
def test_a_scare_quote_is_released_when_the_judge_says_so(monkeypatch):
    monkeypatch.setattr(config, "JEV_ENABLED", True)
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "quoted_label_is_scare_quote", lambda _t: True)
    assert pc.quoted_label_cuts([_cut(1, "the 'cost' of the model shrinks")]) == []


def test_it_stays_blocked_when_the_judge_says_it_is_a_label(monkeypatch):
    monkeypatch.setattr(config, "JEV_ENABLED", True)
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "quoted_label_is_scare_quote", lambda _t: False)
    assert pc.quoted_label_cuts([_cut(1, "a red bar for 'NASDAQ' rises")])


# ── ④ 판정을 못 하면 **막혀 있는다**(error-vs-empty) ───────────────
def test_an_unanswerable_judgement_keeps_the_block(monkeypatch):
    """Jev 가 죽는 날 게이트가 통째로 열리면 안 된다."""
    monkeypatch.setattr(config, "JEV_ENABLED", True)
    monkeypatch.setattr(decide, "enabled", lambda: True)       # 키는 건드리지 않는다
    monkeypatch.setattr(decide, "_post", lambda _b: None)      # 네트워크 실패
    assert decide.quoted_label_is_scare_quote("the 'cost' of it") is False


def test_a_malformed_response_is_not_read_as_a_release(monkeypatch):
    monkeypatch.setattr(config, "JEV_ENABLED", True)
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "_post", lambda _b: {"answers": {}})
    assert decide.noul("x", "y", {"true": "a", "false": "b"}) is None


# ── ⑤ 문턱과 비용이 기록돼 있다 ────────────────────────────────────
def test_the_threshold_sits_in_the_empty_gap_the_measurement_found(monkeypatch):
    """실측: 겁따옴표는 0.04~0.15, 사람이 봐도 라벨인 것은 0.62~0.93. 그 사이가 비어 있다."""
    assert 0.2 <= config.JEV_LABEL_RELEASE_BELOW <= 0.6
    monkeypatch.setattr(config, "JEV_ENABLED", True)
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "noul", lambda *a, **k: 0.42)
    assert decide.quoted_label_is_scare_quote("x") is False, "애매하면 막아 둔다"
    monkeypatch.setattr(decide, "noul", lambda *a, **k: 0.07)
    assert decide.quoted_label_is_scare_quote("x") is True


def test_the_call_is_priced_so_the_ledger_never_says_zero_by_accident():
    """단가표에 없으면 원장이 0원으로 적고, 그건 '안 불렀다'와 구별되지 않는다."""
    for m in ("jev-latest", "jev-1.13.0"):
        assert m in config.TEXT_PRICING, m
    # 출력 0 은 **확인한 값**이다(문장을 만들지 않는다) — 모르는 값이 아니다.
    assert config.TEXT_PRICING["jev-latest"]["text_output_per_token"] == 0.0
    assert config.TEXT_PRICING["jev-latest"]["text_input_per_token"] > 0


# ── ⑥ 같은 문장은 한 번만 묻는다 (2026-09-23 리뷰) ─────────────────
def test_one_field_with_several_quotes_is_asked_once(monkeypatch):
    """Jev 에게 가는 것은 따옴표가 아니라 **문장 전체**다 — 따옴표가 셋이면 같은 질문을
    세 번 보내고 있었다(같은 답에 요금·지연 세 배)."""
    calls = []
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "quoted_label_is_scare_quote",
                        lambda t: calls.append(t) or True)
    text = "the 'cost' and the 'speed' of the 'model' both shrink"
    assert pc.quoted_label_cuts([_cut(1, text)]) == []
    assert calls == [text], f"같은 문장을 {len(calls)}번 물었다"


def test_the_memo_does_not_leak_across_calls(monkeypatch):
    """기억은 **한 번의 검사 안에서만**. 전역 캐시면 다음 지시서가 옛 답을 받는다."""
    monkeypatch.setattr(decide, "enabled", lambda: True)
    text = "the 'cost' of the model shrinks"
    monkeypatch.setattr(decide, "quoted_label_is_scare_quote", lambda _t: True)
    assert pc.quoted_label_cuts([_cut(1, text)]) == []
    monkeypatch.setattr(decide, "quoted_label_is_scare_quote", lambda _t: False)
    assert pc.quoted_label_cuts([_cut(1, text)]), "앞 호출의 답이 새어 들어왔다"
