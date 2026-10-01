from pathlib import Path

from engine.explanation_quality import (
    QUALITY_AXES,
    load_gold_set,
    markdown_report,
    summarize,
)


ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "fixtures" / "explanation_quality_gold_set.json"


def _cases():
    return load_gold_set(GOLD)


def test_gold_set_has_both_domains_and_all_quality_axes():
    cases = _cases()
    assert {case["domain"] for case in cases} == {"paper", "report"}
    assert len(cases) == 3
    for case in cases:
        assert set(case["ratings"]) == set(QUALITY_AXES)


def test_gold_set_keeps_the_three_phase0_regression_anchors():
    by_id = {case["case_id"]: case for case in _cases()}
    codes = lambda case: {finding["code"] for finding in case["findings"]}

    assert "scope_expansion_exclusivity" in codes(by_id["heel-strike-2026-09"])
    assert "reasoning_link_lost_before_visual" in codes(by_id["samsung-memory-cycle-2026-09"])
    assert "source_depth_overexpanded" in codes(by_id["nh-ai-mid-cycle-2026-09"])


def test_summary_is_deterministic_and_exposes_failure_origin():
    summary = summarize(_cases())
    assert summary["cases"] == 3
    assert summary["findings"] == 11
    assert summary["by_domain"] == {"paper": 1, "report": 2}
    assert summary["by_severity"]["p0"] == 5
    assert summary["by_stage"]["visual"] == 3
    assert summary["by_stage"]["source"] == 1


def test_markdown_report_is_reviewable_without_production_access():
    report = markdown_report(_cases())
    assert "heel-strike-2026-09" in report
    assert "samsung-memory-cycle-2026-09" in report
    assert "nh-ai-mid-cycle-2026-09" in report
    assert "p0:scope_expansion_exclusivity" in report
