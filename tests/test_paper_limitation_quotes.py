"""Fact Sheet 연구 한계 원문 구절(설계 점검 C (가), 2026-10-05)."""

from engine import factsheet, paper_evidence


def test_normalize_keeps_limitation_quotes_and_nulls_missing_quotes():
    out = factsheet.normalize_factsheet({
        "limitations": ["표본이 작다."],
        "limitation_quotes": [
            {"limitation": "표본이 작다.", "quote": "small sample"},
            {"limitation": "기간이 짧다.", "quote": "없음"},
            {"limitation": "", "quote": "ignored"},
            "bad",
        ],
    })
    assert out["limitation_quotes"] == [
        {"limitation": "표본이 작다.", "quote": "small sample"},
        {"limitation": "기간이 짧다.", "quote": None},
    ]


def test_attach_evidence_verifies_limitation_quotes_against_source():
    sheet = {"claims": [], "limitation_quotes": [
        {"limitation": "a", "quote": "only three chimpanzees"},
        {"limitation": "b", "quote": "not in the paper"},
        {"limitation": "c", "quote": None},
    ]}
    paper_evidence.attach_evidence(sheet, {"text": "We studied only three chimpanzees over four years."})

    assert [row["verified"] for row in sheet["limitation_quotes"]] == [True, False, None]
