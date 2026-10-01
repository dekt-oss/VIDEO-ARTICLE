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
    assert len(cases) == 6
    assert sum(case["domain"] == "paper" for case in cases) == 3
    assert sum(case["domain"] == "report" for case in cases) == 3
    for case in cases:
        assert set(case["ratings"]) == set(QUALITY_AXES)


def test_gold_set_keeps_phase0_regression_anchors():
    by_id = {case["case_id"]: case for case in _cases()}
    codes = lambda case: {finding["code"] for finding in case["findings"]}

    assert "scope_expansion_exclusivity" in codes(by_id["heel-strike-2026-09"])
    assert "reasoning_link_lost_before_visual" in codes(by_id["samsung-memory-cycle-2026-09"])
    assert "source_depth_overexpanded" in codes(by_id["nh-ai-mid-cycle-2026-09"])
    assert "cross_sensory_transfer_invented" in codes(by_id["deaf-retinotopic-remap-2026-09"])
    assert "association_to_determination_hook" in codes(by_id["personality-gwas-2026-09"])
    assert "unsupported_replacement_claim" in codes(by_id["shipbuilding-rerating-2026-09"])


def test_summary_is_deterministic_and_exposes_failure_origin():
    summary = summarize(_cases())
    assert summary["cases"] == 6
    assert summary["findings"] == 23
    assert summary["by_domain"] == {"paper": 3, "report": 3}
    assert summary["by_severity"] == {"p0": 11, "p1": 12}
    assert summary["by_stage"] == {
        "narration": 1,
        "reasoning": 6,
        "render": 1,
        "script": 10,
        "source": 1,
        "visual": 4,
    }


def test_markdown_report_is_reviewable_without_production_access():
    report = markdown_report(_cases())
    for case_id in (
        "heel-strike-2026-09",
        "samsung-memory-cycle-2026-09",
        "nh-ai-mid-cycle-2026-09",
        "deaf-retinotopic-remap-2026-09",
        "personality-gwas-2026-09",
        "shipbuilding-rerating-2026-09",
    ):
        assert case_id in report
    assert "p0:scope_expansion_exclusivity" in report
    assert "p0:association_to_determination_hook" in report


def test_gold_set_rejects_empty_finding_evidence():
    import json
    import tempfile

    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    payload["cases"][0]["findings"][0]["evidence"] = []
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as fh:
        json.dump(payload, fh, ensure_ascii=False)
        path = fh.name
    try:
        import pytest
        from engine.explanation_quality import GoldSetError
        with pytest.raises(GoldSetError):
            load_gold_set(path)
    finally:
        Path(path).unlink(missing_ok=True)
