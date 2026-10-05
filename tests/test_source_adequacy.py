"""Explanation Engine v2 Phase 1 — source adequacy contract tests."""

from __future__ import annotations

from pathlib import Path

from engine import config, directive, report_directive, report_reasoning, source_adequacy


ROOT = Path(__file__).resolve().parents[1]


def paper_fs(depth: str, chars: int = 1000) -> dict:
    return {
        "source_provenance": {
            "source_depth": depth,
            "char_count": chars,
            "provider": "test",
            "doc_hash": "",
            "parse_error": "",
        },
        "claims": [],
    }


def report_fs(depth: str, chars: int = 1000) -> dict:
    return {
        "source_depth": depth,
        "source_chars": chars,
        "number_facts": [
            {"fact_id": "F01", "metric": "x", "value": 1, "unit_norm": "개", "period": "2026"}
        ],
    }


def test_paper_source_modes_follow_existing_depth_classifier():
    abstract = source_adequacy.build_policy(paper_fs("abstract_only", 900), "paper")
    partial = source_adequacy.build_policy(paper_fs("partial_body", 4000), "paper")
    full = source_adequacy.build_policy(paper_fs("full_body", 12000), "paper")

    assert (abstract["source_mode"], abstract["max_duration_sec"],
            abstract["max_content_mode"]) == ("BRIEF_EXPLAINER", 35, "flash")
    assert (partial["source_mode"], partial["max_duration_sec"],
            partial["max_content_mode"]) == ("SOURCE_EXPLAINER", 50, "standard")
    assert (full["source_mode"], full["max_duration_sec"], full["max_content_mode"]) == (
        "FULL_EXPLAINER", 0, "extended"   # 0 = 길이 상한 없음(2026-10-05)
    )


def test_legacy_report_without_source_metadata_keeps_existing_reasoning_limits():
    # Phase 1은 새 source metadata가 있는 콘텐츠부터 적용한다. 옛 Fact Sheet를
    # summary_only로 추정해 소급 차단하면 안 된다.
    legacy = {"number_facts": [{"fact_id": "F01", "value": 1}]}
    assert source_adequacy.from_fact_sheet(legacy, "report") is None
    assert source_adequacy.reasoning_limits(legacy) == (
        config.REASONING_MAX_UNITS,
        config.REASONING_MAX_STEPS,
    )


def test_report_partial_source_is_brief_not_full_explainer():
    p = source_adequacy.build_policy(report_fs("partial_text", 1072), "report")
    assert p["source_mode"] == "BRIEF_EXPLAINER"
    assert p["max_duration_sec"] == 35
    assert (p["max_reasoning_units"], p["max_reasoning_steps"]) == (1, 3)


def test_report_summary_source_disables_causal_reasoning_units():
    fs = report_fs("summary_only", 0)
    source_adequacy.attach(fs, "report")
    assert source_adequacy.reasoning_limits(fs) == (0, 0)
    out = report_reasoning.build(fs, packet=None)
    assert out["units"] == []
    assert out["source_adequacy"]["source_mode"] == "SUMMARY_ONLY"


def test_paper_content_mode_is_capped_by_source_depth():
    fs = paper_fs("abstract_only", 1200)
    source_adequacy.attach(fs, "paper")
    plan = {
        "selected_mode": "deep",
        "target_duration_min_sec": 51,
        "target_duration_max_sec": 65,
        "mode_warnings": [],
    }
    out = source_adequacy.apply_content_plan(plan, fs)
    assert out["selected_mode"] == "flash"
    assert (out["target_duration_min_sec"], out["target_duration_max_sec"]) == (25, 35)
    assert "source_mode_capped:deep->flash" in out["mode_warnings"]


def test_final_directive_blocks_the_nh_style_re_expansion():
    fs = report_fs("partial_text", 1072)
    source_adequacy.attach(fs, "report")

    assert source_adequacy.output_block_reasons(fs, 24, "report") == []
    assert source_adequacy.output_block_reasons(fs, 50, "report") == [
        "source_depth_duration_exceeded:50>35",
    ]

    # 12컷 자체는 금지하지 않는다. 35초 안에서 컷을 자주 바꾸는 것은 정보 과장이 아니라
    # 편집 리듬일 수 있다. Source gate는 증거 깊이/설명 길이를 제한한다.
    header = {"total_estimated_sec": 50, "cost_plan": {}}
    cuts = [{"cut_no": i + 1, "estimated_sec": 4} for i in range(12)]
    reasons = directive.directive_block_reasons(header, cuts, fact_sheet=fs)
    assert "source_depth_duration_exceeded:50>35" in reasons
    assert not any(r.startswith("source_depth_cut_count") for r in reasons)


def test_full_report_keeps_existing_envelope():
    fs = report_fs("full_text", 11997)
    source_adequacy.attach(fs, "report")
    assert source_adequacy.output_block_reasons(fs, 64, "report") == []
    assert source_adequacy.reasoning_limits(fs) == (5, 5)


def test_report_reasoning_normalizer_respects_partial_source_limit():
    fs = report_fs("partial_text", 1072)
    source_adequacy.attach(fs, "report")
    raw = {
        "reasoning_units": [
            {
                "unit_type": "DRIVER_CHAIN",
                "title": "one",
                "carries_thesis": True,
                "steps": [
                    {"step": 1, "text": "a", "fact_ids": ["F01"], "source_refs": []},
                    {"step": 2, "text": "b", "fact_ids": ["F01"], "source_refs": []},
                    {"step": 3, "text": "c", "fact_ids": ["F01"], "source_refs": []},
                    {"step": 4, "text": "d", "fact_ids": ["F01"], "source_refs": []},
                ],
            },
            {
                "unit_type": "RISK_PATH",
                "title": "two",
                "carries_thesis": False,
                "steps": [{"step": 1, "text": "e", "fact_ids": ["F01"], "source_refs": []}],
            },
        ]
    }
    units = report_reasoning.normalize_units(raw, fs, packet=None)
    assert len(units) == 1
    assert len(units[0]["steps"]) == 3


def test_report_directive_prompt_uses_source_target_not_global_60_seconds():
    fs = report_fs("partial_text", 1072)
    source_adequacy.attach(fs, "report")
    prompt = report_directive.report_directive_user_prompt(
        {"fact_sheet": fs, "script_md": "짧은 대본", "scenes": [], "financial_reasoning": {}},
        "photo",
    )
    assert "전체 약 35초 이내" in prompt
    assert "[Source Adequacy]" in prompt
    assert "BRIEF_EXPLAINER" in prompt


def test_edge_fallback_declares_abstract_only_and_same_ceiling():
    src = (ROOT / "supabase/functions/generate-draft/index.ts").read_text(encoding="utf-8")
    assert 'SOURCE_ADEQUACY_CONTRACT_VERSION = "source-adequacy-v1"' in src
    assert "EDGE_SOURCE_MAX_DURATION_SEC = 35" in src
    assert 'source_depth: "abstract_only"' in src
    assert "applySourceAdequacyPlan" in src
    assert "source_depth_duration_exceeded" in src
