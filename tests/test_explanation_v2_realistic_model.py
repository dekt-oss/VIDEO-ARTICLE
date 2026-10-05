"""Cross-phase contract tests with a model double that behaves like the real one.

★ 왜 이 파일이 있나(Phase 12 파일럿, 2026-10-04). Phase 2~10 테스트는 전부 "입력 문장을 그대로
  복사하는" 가짜 모델을 썼다. 그래서 단계 사이 규칙 충돌 — 도입 질문 어미(Phase 6 vs 7), 숫자
  (Phase 5·6·8), 완곡 표현(Phase 6) — 이 실제 모델을 처음 돌린 날에야 하나씩 드러났다(유료 5회).
  여기의 `realistic_narrator` 는 실제 모델이 파일럿에서 **실제로 한 일**만 흉내 낸다:
    ① 도입 질문 어미를 말투로 ("…는가?" → "…는 걸까요?")
    ② 문장 끝을 존댓말로 ("…했다." → "…했습니다.")
    ③ 화면용 숫자를 말로 풀기 ("1.1% 낮거나" → "약간 낮거나")
    ④ 추정 문장에 완곡 표현 ("…것이다." → "…것으로 보입니다.")
    ⑤ 문장에 없는 증권사 귀속을 앞에 붙이기 ("유안타증권은 …")
  이 변형은 **뜻을 바꾸지 않으므로** 어느 단계도 거절하면 안 된다. 반대로 뜻을 바꾸는 변형
  (연관 → 결정, 귀속 삭제, "모든" 추가, 화면 숫자 읽기, 숫자 값 변경)은 계속 거절돼야 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from engine import evidence_pack, explanation_shadow_pipeline, spoken_numbers

import test_content_complexity_gate as gate_fixtures
import test_explanation_shadow_pipeline as fixtures
import test_spoken_numbers as number_fixtures

_POLITE = (
    ("했다.", "했습니다."), ("였다.", "였습니다."), ("었다.", "었습니다."), ("았다.", "았습니다."),
    ("이다.", "입니다."), ("한다.", "합니다."), ("된다.", "됩니다."), ("있다.", "있습니다."),
    ("없다.", "없습니다."),
)


def _spoken_hook(question: str) -> str:
    for plain, spoken in (("는가?", "는 걸까요?"), ("인가?", "일까요?"), ("은가?", "을까요?")):
        if question.endswith(plain):
            return question[: -len(plain)] + spoken
    return question


def _speak(text: str, beat: dict[str, Any]) -> str:
    # 시점 표현("2023년 4월")은 건드리지 않는다 — 실제 모델도 화면 숫자를 지우며 날짜를 바꾸지 않는다.
    pieces = spoken_numbers._PERIOD.split(text)
    periods = spoken_numbers._PERIOD.findall(text)
    for index, token in enumerate(beat.get("screen_numbers") or []):
        # 숫자 자리에서만 바꾼다 — "2" 를 지우려다 "2028년" 의 2 를 지우면 안 된다.
        pattern = rf"(?:약\s*)?(?<![\d.]){re.escape(token)}(?!\d)(?!\.\d)(?:\s*(?:가량|정도))?"
        for at, piece in enumerate(pieces):
            replaced = re.sub(pattern, "약간" if index == 0 else "", piece, count=1)
            if replaced != piece:
                pieces[at] = replaced
                break
    text = "".join(piece + (periods[at] if at < len(periods) else "") for at, piece in enumerate(pieces))
    text = re.sub(r"\s{2,}", " ", text).replace(" ,", ",").strip()
    text = text.replace("것이다.", "것으로 보입니다.")
    for plain, polite in _POLITE:
        if text.endswith(plain):
            text = text[: -len(plain)] + polite
    for attribution in beat.get("attributions") or []:
        if attribution and attribution not in text:
            text = f"{attribution}은 {text}"
    return text


def realistic_narrator(mutate: Callable[[str, dict[str, Any]], str] | None = None):
    """실제 모델 행동 ①~⑤ 를 흉내 내는 대본 모델. `mutate` 로 뜻을 바꾸는 변형을 덧씌운다."""
    def caller(**kwargs):
        payload = json.loads(kwargs["user"])
        beats = []
        for beat in payload["beats"]:
            if beat["stage"] == "HOOK":
                sentences = [_spoken_hook(payload["core_question"])]
            else:
                sentences = [_speak(text, beat) for text in beat["content_points"]]
                if mutate:
                    sentences = [mutate(sentence, beat) for sentence in sentences]
            beats.append({"beat_id": beat["beat_id"], "sentences": sentences})
        return {"beats": beats}
    return caller


def _gold_cases() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "fixtures" / "explanation_ir_gold_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _run_gold(case: dict[str, Any], monkeypatch, narrator) -> dict[str, Any]:
    pack = gate_fixtures._gold_pack(case)
    monkeypatch.setattr(evidence_pack, "build", lambda *args, **kwargs: pack)
    return explanation_shadow_pipeline.run(
        domain=case["domain"], content_id=case["case_id"], fact_sheet={},
        financial_reasoning=case.get("financial_reasoning"),
        legacy_draft={}, legacy_directive={}, allow_model_calls=True,
        narration_caller=narrator, critic_caller=fixtures._critic_caller,
    )


def _fixture_runs() -> dict[str, Callable[..., dict[str, Any]]]:
    def paper(narrator):
        return explanation_shadow_pipeline.run(
            domain="paper", content_id="paper-1", fact_sheet=fixtures._paper_fact_sheet(),
            legacy_draft={}, legacy_directive={}, allow_model_calls=True,
            narration_caller=narrator, critic_caller=fixtures._critic_caller)

    def report(narrator):
        return explanation_shadow_pipeline.run(
            domain="report", content_id="report-1", fact_sheet=fixtures._report_fact_sheet(),
            financial_reasoning=fixtures._financial_reasoning(), legacy_draft={},
            legacy_directive={}, allow_model_calls=True,
            narration_caller=narrator, critic_caller=fixtures._critic_caller)

    def numbers(narrator):
        sheet, reasoning = number_fixtures._number_heavy_report()
        return explanation_shadow_pipeline.run(
            domain="report", content_id="report-numbers", fact_sheet=sheet,
            financial_reasoning=reasoning, legacy_draft={}, legacy_directive={},
            allow_model_calls=True, narration_caller=narrator,
            critic_caller=fixtures._critic_caller)

    return {"paper": paper, "report": report, "number_heavy_report": numbers}


# ─── 뜻이 그대로인 실제 모델 행동은 어느 단계도 막지 않는다 ─────────────────────────

@pytest.mark.parametrize("name", sorted(_fixture_runs()))
def test_realistic_paraphrase_reaches_a_directive(name):
    result = _fixture_runs()[name](realistic_narrator())

    narration = result["shadow"]["narration"]
    assert narration["generation_status"] == "DRAFT_ACCEPTED", narration["qa"]["errors"]
    assert narration.get("repairs", []) == []                      # 도입 질문 어미 변형은 교정 대상이 아니다
    assert result["phase_status"]["phase7"] == "PASSED"
    assert result["run_status"] == "READY", (result["phase_status"], result.get("error"))


@pytest.mark.parametrize("case", _gold_cases(), ids=lambda case: case["case_id"])
def test_realistic_paraphrase_never_fails_phase6_on_gold_cases(case, monkeypatch):
    result = _run_gold(case, monkeypatch, realistic_narrator())

    narration = result["shadow"]["narration"]
    assert result["error"] is None
    assert narration["generation_status"] == "DRAFT_ACCEPTED", narration["qa"]["errors"]
    fidelity_errors = result["shadow"]["fidelity"]["qa"]["errors"]
    # 골드 픽스처는 원문 인용을 싣지 않아(basis: "Minimal excerpts only") support_surface 만 남을 수 있다.
    assert all(e.startswith("support_surface_ineligible:") for e in fidelity_errors), fidelity_errors


# ─── 뜻이 바뀌는 변형은 여전히 막힌다 ──────────────────────────────────────

def _to_determination(sentence: str, beat: dict[str, Any]) -> str:
    return sentence.replace("연관", "결정").replace("관련", "결정")


def _drop_attribution(sentence: str, beat: dict[str, Any]) -> str:
    for attribution in beat.get("attributions") or []:
        sentence = sentence.replace(f"{attribution}은 ", "").replace(attribution, "")
    return sentence


def _add_universal(sentence: str, beat: dict[str, Any]) -> str:
    return "모든 경우에 " + sentence


def _read_screen_numbers(sentence: str, beat: dict[str, Any]) -> str:
    screen = beat.get("screen_numbers") or []
    return sentence + " " + " ".join(screen) if screen else sentence


def _change_spoken_value(sentence: str, beat: dict[str, Any]) -> str:
    for token in beat.get("spoken_numbers") or []:
        digits = re.match(r"[\d.,]+", token)
        if digits:
            return sentence.replace(token, token.replace(digits.group(0), "999"), 1)
    return sentence


@pytest.mark.parametrize("name, mutate, expected", [
    ("paper", _add_universal, "scope_intensifier_added:"),
    ("report", _drop_attribution, "attribution_dropped:"),
    ("number_heavy_report", _read_screen_numbers, "screen_number_spoken:"),
    ("number_heavy_report", _change_spoken_value, "numbers_changed:"),
])
def test_meaning_changes_are_still_rejected_after_realistic_paraphrase(name, mutate, expected):
    result = _fixture_runs()[name](realistic_narrator(mutate))

    narration = result["shadow"]["narration"]
    assert narration["generation_status"] == "REJECTED_DRAFT"
    assert any(e.startswith(expected) for e in narration["qa"]["errors"]), narration["qa"]["errors"]
    assert result["shadow"]["directive"] is None


def test_association_upgrade_is_rejected_after_realistic_paraphrase(monkeypatch):
    gwas = next(case for case in _gold_cases() if case["case_id"] == "personality-gwas-2026-09")

    result = _run_gold(gwas, monkeypatch, realistic_narrator(_to_determination))

    errors = result["shadow"]["narration"]["qa"]["errors"]
    assert result["shadow"]["narration"]["generation_status"] == "REJECTED_DRAFT"
    assert any(e.startswith(("association_upgraded:", "protected_meaning_changed:",
                             "causal_language_added:")) for e in errors), errors


# ─── 설계 점검 C (가)(2026-10-05): 원문 구절이 있는 논문 한계는 한계 장면이 된다 ──────────────

def _paper_with_limitation(quoted: bool) -> dict:
    sheet = fixtures._paper_fact_sheet()
    sheet["limitations"] = ["침팬지 연구는 3마리에서만 수집됐다."]
    sheet["limitation_quotes"] = ([{"limitation": "침팬지 연구는 3마리에서만 수집됐다.",
                                    "quote": "data from three chimpanzees", "verified": True}]
                                  if quoted else [])
    return sheet


@pytest.mark.parametrize("quoted", [True, False])
def test_quoted_paper_limitation_becomes_a_boundary_beat(quoted):
    result = explanation_shadow_pipeline.run(
        domain="paper", content_id="paper-lim", fact_sheet=_paper_with_limitation(quoted),
        legacy_draft={}, legacy_directive={}, allow_model_calls=True,
        narration_caller=realistic_narrator(), critic_caller=fixtures._critic_caller)

    stages = [beat["stage"] for beat in result["shadow"]["narrative_plan"]["beats"]]
    assert result["run_status"] == "READY", (result["phase_status"], result.get("error"))
    assert ("BOUNDARY" in stages) is quoted          # 구절 없는 옛 Fact Sheet 는 종전처럼 한계를 뺀다
