"""Spoken-number contract shared by Phase 5, 6 and 8 (Phase 12 pilot follow-up)."""

from __future__ import annotations

import json

import pytest

from engine import config, explanation_shadow_pipeline, spoken_numbers

import test_explanation_shadow_pipeline as fixtures


@pytest.mark.parametrize("text, values, periods", [
    ("2026년 3분기 DRAM 가격은 18.0%, NAND는 16.0% 상승", ["16.0%", "18.0%"], ["2026년", "3분기"]),
    ("3Q26E 영업이익 99,860", ["99,860"], ["3Q26E"]),
    ("2026F 영업이익 358,485", ["358,485"], ["2026F"]),
    ("인간 12명과 침팬지 3마리를 4년간 관찰", ["12명", "3마리", "4년"], []),
    ("인간보다 2.4배에서 8.6배 더 넓다", ["2.4배", "8.6배"], []),
    ("목표주가 630,000원", ["630,000원"], []),
    ("2027년 BPS에 PBR 3.5배", ["3.5배"], ["2027년"]),
    ("영업이익은 100.0조원", ["100.0조원"], []),
    ("숫자가 없는 문장", [], []),
    ("HBM4 판매 본격화와 DDR5 전환", [], []),
    ("A100 GPU 8개", ["8개"], []),
    ("COVID-19 이후 5G 가입자 30%", ["30%"], []),
    ("GPT-4o 와 4K 영상", [], []),
])
def test_values_and_periods_are_counted_separately(text, values, periods):
    assert spoken_numbers.value_tokens(text) == values
    assert spoken_numbers.period_tokens(text) == periods


def test_assign_prefers_thesis_then_results_and_keeps_units_whole():
    points = [
        {"ref": "A", "text": "원인 1% 와 2% 와 3%", "role": "cause"},
        {"ref": "B", "text": "다리 10명", "role": "bridge"},
        {"ref": "C", "text": "결과 20%", "role": "result"},
        {"ref": "D", "text": "숫자 없음", "role": "cause"},
    ]

    decision = spoken_numbers.assign(points, thesis="다리 10명", budget=2)

    assert decision == {
        "B": {"spoken": True, "numbers": ["10명"]},
        "C": {"spoken": True, "numbers": ["20%"]},
        "A": {"spoken": False, "numbers": ["1%", "2%", "3%"]},
    }


def test_a_range_is_never_split_in_half():
    decision = spoken_numbers.assign(
        [{"ref": "A", "text": "26%에서 41%", "role": "result"},
         {"ref": "B", "text": "3배", "role": "result"}],
        budget=2,
    )
    assert decision["A"]["spoken"] is True
    assert decision["B"]["spoken"] is False


# ─── end to end: 숫자 많은 리포트가 끝까지 간다 ─────────────────────────

def _fact(fid: str, display: str, quote: str) -> dict:
    return {
        "fact_id": fid, "value": 1, "unit": "%", "unit_norm": "%", "period": "2026F",
        "metric": fid, "basis": "broker_estimate", "attribution": "테스트증권",
        "display": display, "interpretation": "projection",
        "validation": {"number_match": True, "unit_match": True, "period_match": True,
                       "quote_supports_claim": True},
        "source_refs": [{"quote": quote}],
    }


MEMORY = "테스트증권은 2026년 3분기 DRAM 가격이 18.0%, NAND 가격이 16.0% 오를 것으로 전망했다."
PROFIT = "테스트증권은 2026년 3분기 영업이익이 100.0조원에 이를 것으로 전망했다."
TARGET = "테스트증권은 목표주가를 630,000원으로 제시했다."


def _number_heavy_report() -> tuple[dict, dict]:
    sheet = {
        "source": {"broker": "테스트증권", "company": "테스트기업"},
        "source_depth": "full_text", "source_chars": 12000,
        "number_facts": [
            _fact("num_mem", MEMORY, "DRAM 18.0%, NAND 16.0%"),
            _fact("num_op", PROFIT, "영업이익 100.0조원"),
            _fact("num_tp", TARGET, "목표주가 630,000원"),
        ],
    }

    def unit(rid: str, unit_type: str, text: str, fid: str, thesis: bool) -> dict:
        return {"reasoning_id": rid, "unit_type": unit_type, "title": rid,
                "carries_thesis": thesis, "attributed_to": "테스트증권",
                "assumption": "", "breaks_if": "",
                "steps": [{"step": 1, "text": text, "fact_ids": [fid], "source_refs": []}]}

    reasoning = {"units": [
        unit("R01", "DRIVER_CHAIN", MEMORY, "num_mem", True),
        unit("R02", "EARNINGS_BRIDGE", PROFIT, "num_op", False),
        unit("R03", "VALUATION_LOGIC", TARGET, "num_tp", False),
    ]}
    return sheet, reasoning


def _narrator(*, keep_screen: bool = False, drop_period: bool = False,
              drop_spoken: bool = False):
    def caller(**kwargs):
        payload = json.loads(kwargs["user"])
        beats = []
        for beat in payload["beats"]:
            sentences = []
            for text in beat["content_points"]:
                if not keep_screen:
                    for token in beat["screen_numbers"]:
                        text = text.replace(token, "")
                if drop_period:
                    text = text.replace("2026년 ", "")
                if drop_spoken:
                    for token in beat["spoken_numbers"]:
                        text = text.replace(token, "")
                sentences.append(text)
            beats.append({"beat_id": beat["beat_id"], "sentences": sentences})
        return {"beats": beats}
    return caller


def _run(**caller_options) -> dict:
    sheet, reasoning = _number_heavy_report()
    return explanation_shadow_pipeline.run(
        domain="report", content_id="report-numbers", fact_sheet=sheet,
        financial_reasoning=reasoning, legacy_draft={}, legacy_directive={},
        allow_model_calls=True, narration_caller=_narrator(**caller_options),
        critic_caller=fixtures._critic_caller,
    )


def test_number_heavy_report_reaches_a_directive_within_the_spoken_budget():
    result = _run()

    assert result["run_status"] == "READY"
    narration = result["shadow"]["narration"]
    assert narration["qa"]["metrics"]["number_count"] <= config.MAX_SPOKEN_NUMBERS
    deliveries = [b["number_delivery"] for b in result["shadow"]["narrative_plan"]["beats"]]
    spoken = sorted(n for d in deliveries for n in d["spoken_numbers"])
    assert spoken == ["100.0조원", "630,000원"]          # 결과(목표가)가 먼저, 남은 예산 1
    screen = [f for d in deliveries for f in d["screen_facts"]]
    assert screen == [{"ref": "XR01", "text": MEMORY, "numbers": ["16.0%", "18.0%"]}]

    cards = [f for cut in result["shadow"]["directive"]["cuts"] for f in cut["screen_facts"]]
    assert cards == screen                                # 말에서 뺀 숫자는 화면에 남는다
    markdown = explanation_shadow_pipeline.render_markdown(result)
    assert f"화면 숫자 카드(XR01): {MEMORY} [16.0%, 18.0%]" in markdown
    assert "말한 숫자: 100.0조원 · 화면으로 보낸 근거: XR01" in markdown


def test_speaking_a_screen_number_is_rejected():
    result = _run(keep_screen=True)

    errors = result["shadow"]["narration"]["qa"]["errors"]
    assert result["phase_status"]["phase6"] == "REJECTED_DRAFT"
    assert any(e.startswith("screen_number_spoken:NB02:") for e in errors)
    assert result["shadow"]["directive"] is None


def test_dropping_a_chosen_spoken_number_is_rejected():
    result = _run(drop_spoken=True)

    assert result["phase_status"]["phase6"] == "REJECTED_DRAFT"
    assert any(e.startswith("numbers_changed:") for e in result["shadow"]["narration"]["qa"]["errors"])


def test_dropping_a_period_is_rejected():
    result = _run(drop_period=True)

    assert result["phase_status"]["phase6"] == "REJECTED_DRAFT"
    assert any(e.startswith("period_changed:") for e in result["shadow"]["narration"]["qa"]["errors"])


def test_model_sees_which_numbers_to_say_and_which_go_to_screen():
    from engine import spoken_narration

    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return _narrator()(**kwargs)

    sheet, reasoning = _number_heavy_report()
    explanation_shadow_pipeline.run(
        domain="report", content_id="report-numbers", fact_sheet=sheet,
        financial_reasoning=reasoning, legacy_draft={}, legacy_directive={},
        allow_model_calls=True, narration_caller=capture, critic_caller=fixtures._critic_caller,
    )

    beat = json.loads(seen["user"])["beats"][1]
    assert beat["spoken_numbers"] == ["100.0조원"]
    assert beat["screen_numbers"] == ["16.0%", "18.0%"]
    assert "screen_numbers" in spoken_narration.SYSTEM_PROMPT
    assert "spoken_numbers" in spoken_narration.SYSTEM_PROMPT


def test_tampered_number_delivery_is_rejected_by_the_planner():
    from engine import narrative_planner

    result = _run()
    shadow = result["shadow"]
    plan = json.loads(json.dumps(shadow["narrative_plan"]))
    plan["beats"][1]["number_delivery"]["spoken_numbers"] = ["16.0%", "18.0%", "100.0조원"]

    errors = narrative_planner.validate(plan, shadow["ir"], shadow["resolution"],
                                        shadow["evidence_pack"])
    assert "number_delivery_invalid:NB02" in errors
