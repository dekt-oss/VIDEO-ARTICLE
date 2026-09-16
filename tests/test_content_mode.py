"""콘텐츠 모드 순수 로직 — 가변 길이·비용계획·근거커버리지 (수정명세 §6·§10-3·§12-1).

네트워크·DB·LLM 없이 순수 함수만 검증한다. 핵심 관심사는 "모델 자기보고를 코드가 덮어쓰는가".
"""

import pytest

from engine import config, content_mode as cm


# ── 모드 자동선택 (§6-4) ──
@pytest.mark.parametrize(("units", "expected"), [
    (3, "flash"),        # 필수 3개(E1·E2·E7)만 → 단일 결과
    (4, "standard"),
    (5, "standard"),
    (6, "deep"),
])
def test_select_mode_by_unit_count(units, expected):
    assert cm.select_mode(units) == expected


def test_select_mode_moderator_forces_deep():
    # 단위 수가 적어도 조절효과·메커니즘이 필수면 deep (생략하면 인과 오해)
    assert cm.select_mode(4, deep_forcing=True) == "deep"


def test_select_mode_extended_only_with_high_compression_risk():
    assert cm.select_mode(7, compression_risk="high") == "extended"
    # 압축 위험 근거가 없으면 extended 를 쓰지 않는다 — 예외 모드다
    assert cm.select_mode(7, compression_risk="medium") == "deep"
    assert cm.select_mode(8, compression_risk="low") == "deep"


def test_select_mode_two_main_claims_splits():
    assert cm.select_mode(4, independent_main_claims=2) == "series_split"
    # 분할은 다른 모든 규칙을 이긴다
    assert cm.select_mode(8, compression_risk="high", independent_main_claims=3) == "series_split"


# ── 길이 범위는 코드가 모드에서 재유도 (모델 값 폐기) ──
def test_duration_always_derived_from_mode_not_llm():
    plan = cm.normalize_content_plan({
        "selected_mode": "flash",
        "target_duration_min_sec": 52,   # LLM 이 deep 길이를 주장
        "target_duration_max_sec": 62,
        "essential_evidence_units": ["E1", "E2", "E7"],
    })
    assert plan["selected_mode"] == "flash"
    assert (plan["target_duration_min_sec"], plan["target_duration_max_sec"]) == (25, 35)


def test_extended_demoted_when_compression_risk_not_high():
    plan = cm.normalize_content_plan({
        "selected_mode": "extended",
        "compression_risk": "low",
        "essential_evidence_units": ["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
    })
    assert plan["selected_mode"] == "deep"
    assert (plan["target_duration_min_sec"], plan["target_duration_max_sec"]) == (51, 65)
    assert "extended_demoted_no_compression_risk" in plan["mode_warnings"]


def test_extended_kept_when_compression_risk_high():
    plan = cm.normalize_content_plan({
        "selected_mode": "extended",
        "compression_risk": "high",
        "essential_evidence_units": ["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
        "duration_reason": "조절효과와 메커니즘을 함께 설명해야 함",
    })
    assert plan["selected_mode"] == "extended"
    assert (plan["target_duration_min_sec"], plan["target_duration_max_sec"]) == (66, 80)


def test_flash_with_many_units_warns_but_keeps_mode():
    plan = cm.normalize_content_plan({
        "selected_mode": "flash",
        "essential_evidence_units": ["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
    })
    assert plan["selected_mode"] == "flash"
    assert "flash_with_many_evidence_units" in plan["mode_warnings"]


def test_required_evidence_units_always_present():
    plan = cm.normalize_content_plan({"essential_evidence_units": ["E4"]})
    for required in config.EVIDENCE_UNITS_REQUIRED:
        assert required in plan["essential_evidence_units"]
    # 미지 단위는 드롭
    plan2 = cm.normalize_content_plan({"essential_evidence_units": ["E4", "E99", "쓰레기"]})
    assert "E99" not in plan2["essential_evidence_units"]


def test_dangling_claim_ids_dropped():
    plan = cm.normalize_content_plan(
        {"primary_claim_id": "C99", "supporting_claim_ids": ["C01", "C77"]},
        claim_ids=("C01", "C02"),
    )
    assert plan["primary_claim_id"] == ""          # 원장에 없는 id
    assert plan["supporting_claim_ids"] == ["C01"]  # C77 드롭


def test_primary_not_duplicated_in_supporting():
    plan = cm.normalize_content_plan(
        {"primary_claim_id": "C01", "supporting_claim_ids": ["C01", "C02"]},
        claim_ids=("C01", "C02"),
    )
    assert plan["supporting_claim_ids"] == ["C02"]


def test_mode_differs_from_rule_is_flagged_not_silently_kept():
    # 규칙상 deep(6단위)인데 모델이 standard 를 골랐다 → 유지하되 경고
    plan = cm.normalize_content_plan({
        "selected_mode": "standard",
        "essential_evidence_units": ["E1", "E2", "E3", "E4", "E6", "E7"],
    })
    assert plan["selected_mode"] == "standard"
    assert any(w.startswith("mode_differs_from_rule") for w in plan["mode_warnings"])


def test_garbage_input_yields_usable_plan():
    plan = cm.normalize_content_plan(None)
    assert plan["selected_mode"] in config.CONTENT_MODES
    assert plan["essential_evidence_units"] == sorted(config.EVIDENCE_UNITS_REQUIRED)
    assert plan["compression_risk"] == "medium"


# ── 차단 / 경고 ──
def test_over_80_sec_blocks_approval():
    plan = cm.normalize_content_plan({"selected_mode": "extended", "compression_risk": "high"})
    assert "over_max_duration" in cm.block_reasons(plan, 85)
    assert cm.block_reasons(plan, 78) == []


def test_series_split_recommends_but_does_not_block():
    """★★ 되돌림(2026-09-03). 명세는 "코드는 **분할 권고까지만** 낸다"이다
    (수정명세서_근거밀도_가변길이_v1 §8 열린질문 2 — 2편 분할 UI 는 범위 밖).
    그런데 코드가 승인 차단으로 만들어 놨고, **원장 있는 초안 10건이 100% 걸렸다**
    (main_result 개수 분포 2·2·3·3·3·3·3·4·4·9 — 하한 2를 안 넘는 논문이 없다).
    화면에 푸는 길도 없어 운영자는 매번 강제 승인을 눌러야 했고, 그러면 **진짜 차단도
    같이 통과한다.** 신호는 남기고(헤더의 content_mode) 승인만 막지 않는다.
    """
    plan = cm.normalize_content_plan({"selected_mode": "series_split"}, independent_main_claims=2)
    assert cm.block_reasons(plan, 45) == []
    # 신호 자체는 사라지지 않는다 — 운영자가 화면에서 계속 본다.
    assert plan["selected_mode"] == "series_split"


def test_the_length_block_still_works():
    """★ 분할만 내렸다. 길이 하드 상한은 그대로 막아야 한다(같이 풀리지 않았는지)."""
    plan = cm.normalize_content_plan({"selected_mode": "series_split"}, independent_main_claims=2)
    assert "over_max_duration" in cm.block_reasons(plan, cm.config.CONTENT_MODE_HARD_MAX_SEC + 1)


def test_short_video_warns_only_and_still_passes_render_qa():
    plan = cm.normalize_content_plan({"selected_mode": "flash"})
    assert cm.block_reasons(plan, 28) == []
    assert "below_soft_min_duration" not in cm.duration_warnings(plan, 28)
    # 25초 미만만 경고. 그리고 flash 최소값도 렌더 QA 하한을 넘는다.
    assert "below_soft_min_duration" in cm.duration_warnings(plan, 22)
    assert config.CONTENT_MODE_SOFT_MIN_SEC >= config.RENDER_QA_MIN_SEC


def test_outside_mode_range_warns():
    plan = cm.normalize_content_plan({"selected_mode": "flash"})
    assert "outside_mode_duration_range" in cm.duration_warnings(plan, 60)


# ── 컷 길이 상한 (§10-2) ──
def test_cut_max_sec_by_kind_and_motion():
    assert cm.cut_max_sec() == config.PAPER_CUT_MAX_SEC == 10
    assert cm.cut_max_sec("data_viz") == config.DATA_VIZ_CUT_MAX_SEC == 12
    # 영상 컷은 clip_fit 보호를 위해 8초 — scene_kind 보다 우선한다
    assert cm.cut_max_sec("data_viz", "video") == config.VIDEO_CUT_MAX_SEC == 8


def test_shared_cut_constant_untouched_for_finance_mirror():
    # engine/report_directive.py 가 같은 상수를 읽는다 — 올리면 범위 밖 프롬프트가 바뀐다.
    assert config.CUT_MAX_SEC == 8
    assert config.TARGET_TOTAL_SEC == 60


# ── 비용 계획 (D-E1) ──
@pytest.mark.parametrize("mode", ["flash", "standard", "deep", "extended"])
def test_cost_plan_video_budget_is_derived_not_duplicated(mode):
    plan = cm.resolve_cost_plan(mode)
    # 금액은 초수에서 파생돼야 한다 — 따로 적으면 단가 변경 때 조용히 어긋난다.
    assert plan["max_video_cost_usd"] == pytest.approx(
        plan["max_video_generated_sec"] * config.VEO_COST_PER_SEC_USD)
    assert plan["max_video_clips"] == max(
        1, plan["max_video_generated_sec"] // config.VEO_CLIP_MAX_TIER_SEC)


def test_cost_plan_mode_ladder():
    seconds = [cm.resolve_cost_plan(m)["max_video_generated_sec"]
               for m in ("flash", "standard", "deep", "extended")]
    assert seconds == [4, 8, 12, 16]
    clips = [cm.resolve_cost_plan(m)["max_video_clips"]
             for m in ("flash", "standard", "deep", "extended")]
    assert clips == [1, 2, 3, 4]


def test_cost_plan_unknown_mode_falls_back_to_global_caps():
    plan = cm.resolve_cost_plan("series_split")
    assert plan["max_video_generated_sec"] == config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC
    assert plan["max_video_cost_usd"] == config.VIDEO_MAX_COST_USD_PER_TOPIC
    assert plan["max_video_clips"] == config.VEO_MAX_CLIPS_PER_DRAFT


def test_worst_case_mode_fits_render_budget_cap():
    # 명세 §3 의 편당 총예산 점검을 코드로 고정한다(캡 상향이 필요 없음의 근거).
    worst = cm.resolve_cost_plan("extended")
    total = (worst["max_unique_assets"] * config.GEMINI_IMAGE_COST_USD
             + worst["max_video_cost_usd"])
    assert total < config.RENDER_BUDGET_CAP_USD


# ── 근거 커버리지 (§12-1) ──
def test_coverage_counts_visual_separately_from_spoken():
    cov = cm.compute_evidence_coverage(
        [
            {"claim_ids": ["C01"], "evidence_role": "primary_result"},
            {"claim_ids": ["C02"], "evidence_role": "scope", "evidence_delivery": "visual"},
            {"claim_ids": ["C03"], "evidence_role": "caveat", "evidence_delivery": "caption"},
        ],
        required_claim_ids=("C01", "C02", "C03"),
        primary_claim_id="C01",
    )
    assert cov["spoken_claim_ids"] == ["C01"]
    assert cov["visual_claim_ids"] == ["C02", "C03"]
    assert cov["missing_claim_ids"] == []
    assert cov["primary_claim_covered"] is True
    assert cov["scope_present"] is True and cov["caveat_present"] is True
    assert cov["method_present"] is False and cov["magnitude_present"] is False


def test_coverage_reports_missing_required_claims():
    cov = cm.compute_evidence_coverage(
        [{"claim_ids": ["C01"], "evidence_role": "primary_result"}],
        required_claim_ids=("C01", "C02"),
        primary_claim_id="C02",
    )
    assert cov["missing_claim_ids"] == ["C02"]
    assert cov["primary_claim_covered"] is False


def test_coverage_handles_empty_and_garbage():
    cov = cm.compute_evidence_coverage(None, required_claim_ids=(), primary_claim_id="")
    assert cov["missing_claim_ids"] == [] and cov["primary_claim_covered"] is False
    assert cm.compute_evidence_coverage([None, "x", 3])["spoken_claim_ids"] == []
