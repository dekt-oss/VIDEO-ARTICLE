"""지시서 근거밀도·가변길이·비용 게이트 (수정명세 §4-4·§6·§10·§14).

핵심은 세 가지다:
1. "I2V 상한을 꽉 채우는" 습관이 실제로 막히는가(motion_value 게이트 → 모드 예산 → 전역 캡 순).
2. 비용·커버리지를 헤더가 아니라 컷에서 코드가 계산하는가.
3. 이 규칙들이 레거시 지시서와 범위 밖 금융 라인을 깨지 않는가.
"""

import pytest

from engine import config
from engine.directive import (
    directive_block_reasons,
    normalize_directive,
    validate_reuse_refs,
)
from engine.factsheet import normalize_factsheet


def _cut(no=1, **kw):
    base = {
        "cut_no": no, "narration_ko": "안녕", "narration_en": "hi", "estimated_sec": 5,
        "visual_prompt": "a cat", "effects": [], "transition": "cut",
        "source_facts": ["what_found[0]"], "novelty_event": "새 비교 공개",
    }
    base.update(kw)
    return base


def _video_cut(no, value="high", **kw):
    return _cut(no, motion_source="video", motion_value=value,
                motion_prompt="slow push-in", **kw)


def _ledger():
    return normalize_factsheet({
        "what_found": ["x"], "how": [], "numbers": [], "limitations": [], "claim_strength": "중",
        "claims": [
            {"claim_ko": "핵심 결과", "claim_kind": "main_result"},
            {"claim_ko": "연구 범위", "claim_kind": "scope"},
        ],
    })


def _plan(**over):
    base = {"primary_claim_id": "C01", "supporting_claim_ids": ["C02"],
            "selected_mode": "standard", "essential_evidence_units": ["E1", "E2", "E7"],
            "duration_reason": "범위와 한계를 함께 설명해야 함", "mode_warnings": []}
    base.update(over)
    return base


# ── motion_value 게이트 (§10-4) ──
def test_only_high_motion_value_survives_as_video():
    out = normalize_directive({"cuts": [
        _video_cut(1, "high"), _video_cut(2, "medium"), _video_cut(3, "low"),
    ]}, "comic")
    sources = [c["motion_source"] for c in out["cuts"]]
    assert sources == ["video", "still", "still"]


def test_motion_value_gate_skips_cuts_that_never_declared_it():
    # 금융 라인(engine/report_directive.py)은 motion_value 를 쓰지 않는다. 선언 안 한 컷을
    # 강등하면 범위 밖 라인의 영상이 조용히 사라진다.
    out = normalize_directive({"cuts": [
        _cut(1, motion_source="video"),          # motion_value 미선언 → 건드리지 않음
        _video_cut(2, "low"),                    # 선언했고 low → 강등
    ]}, "comic")
    assert out["cuts"][0]["motion_source"] == "video"
    assert out["cuts"][1]["motion_source"] == "still"


def test_motion_value_defaults_to_low():
    out = normalize_directive({"cuts": [_cut(1)]}, "comic")
    assert out["cuts"][0]["motion_value"] == config.DEFAULT_MOTION_VALUE == "low"


# ── 모드별 영상 예산 (D-E1) ──
@pytest.mark.parametrize(("mode", "expected"), [
    ("flash", 1), ("standard", 2), ("deep", 3), ("extended", 4),
])
def test_mode_video_clip_budget(mode, expected):
    cuts = [_video_cut(i, "high") for i in range(1, 6)]
    out = normalize_directive({"cuts": cuts}, "comic", content_plan=_plan(selected_mode=mode))
    kept = sum(1 for c in out["cuts"] if c["motion_source"] == "video")
    assert kept == expected


@pytest.mark.parametrize("mode", ["flash", "standard", "deep", "extended"])
def test_cost_plan_never_exceeds_mode_budget(mode):
    cuts = [_video_cut(i, "high") for i in range(1, 7)]
    out = normalize_directive({"cuts": cuts}, "comic", content_plan=_plan(selected_mode=mode))
    plan = out["header"]["cost_plan"]
    assert plan["video_generated_sec"] <= plan["max_video_generated_sec"]
    assert plan["estimated_video_cost_usd"] <= plan["max_video_cost_usd"] + 1e-9
    assert "video_budget_exceeded" not in out["header"]["block_reasons"]


def test_unknown_mode_falls_back_to_global_cap():
    cuts = [_video_cut(i, "high") for i in range(1, 6)]
    out = normalize_directive({"cuts": cuts}, "comic")  # content_plan 없음 → 기본 standard
    kept = sum(1 for c in out["cuts"] if c["motion_source"] == "video")
    assert kept == config.CONTENT_MODE_MAX_VIDEO_CLIPS[config.DEFAULT_CONTENT_MODE]


# ── 비용 계획은 컷에서 계산 ──
def test_cost_plan_computed_from_cuts_not_header():
    out = normalize_directive({
        "header": {"cost_plan": {"max_video_clips": 99, "unique_asset_count": 0}},
        "cuts": [_cut(1), _cut(2), _video_cut(3, "high")],
    }, "comic", content_plan=_plan(selected_mode="deep"))
    plan = out["header"]["cost_plan"]
    assert plan["max_video_clips"] == config.CONTENT_MODE_MAX_VIDEO_CLIPS["deep"]  # 헤더 값 폐기
    assert plan["unique_asset_count"] == 3       # 전부 new_asset 기본값
    assert plan["video_clip_count"] == 1


def test_reuse_cuts_do_not_count_as_unique_assets():
    """고유 에셋 = 렌더가 실제로 생성 API 를 부르는 컷.

    ★ code_viz 는 이론상 공짜지만 **아직 렌더 경로가 없어**(M-E4) 지금은 생성 이미지로 나간다.
      여기서 빼면 예상 비용이 실제보다 낮게 나온다 — M-E4 에서 코드 차트가 실제로 렌더되면
      그때 제외로 바꾼다.
    """
    out = normalize_directive({"cuts": [
        _cut(1, asset_strategy="new_asset"),
        _cut(2, asset_strategy="reuse_with_state_change", base_asset_ref="1",
             state_change="기관투자자 그룹만 강조"),
        _cut(3, asset_strategy="code_viz", scene_kind="data_viz"),
    ]}, "comic", content_plan=_plan())
    plan = out["header"]["cost_plan"]
    assert plan["unique_asset_count"] == 2      # new_asset + code_viz(아직 이미지로 생성)
    assert plan["reuse_count"] == 1
    assert plan["code_viz_count"] == 1          # 따로 세어 M-E4 진척을 볼 수 있게
    assert plan["asset_reuse_ratio"] == round(1 / 3, 3)


def test_estimated_cost_uses_pricing_table():
    out = normalize_directive({"cuts": [_cut(1), _video_cut(2, "high")]},
                              "comic", content_plan=_plan())
    plan = out["header"]["cost_plan"]
    expected_video = plan["video_generated_sec"] * config.VEO_COST_PER_SEC_USD
    assert plan["estimated_video_cost_usd"] == pytest.approx(expected_video)
    assert plan["estimated_total_generation_cost_usd"] == pytest.approx(
        plan["estimated_image_cost_usd"] + plan["estimated_video_cost_usd"])


# ── 에셋 재사용 참조 검증 ──
def test_reuse_ref_must_point_at_earlier_cut():
    cuts = [
        {"cut_no": 1, "asset_strategy": "new_asset"},
        {"cut_no": 2, "asset_strategy": "reuse_zoom", "base_asset_ref": "1"},
        {"cut_no": 3, "asset_strategy": "reuse_zoom", "base_asset_ref": "9"},   # 없는 컷
        {"cut_no": 4, "asset_strategy": "reuse_zoom", "base_asset_ref": "5"},   # 뒤 컷
    ]
    warnings = validate_reuse_refs(cuts)
    assert cuts[1]["asset_strategy"] == "reuse_zoom"          # 유효
    assert cuts[2]["asset_strategy"] == "new_asset"           # 강등
    assert cuts[3]["asset_strategy"] == "new_asset"
    assert "invalid_reuse_ref#3" in warnings and "invalid_reuse_ref#4" in warnings


def test_invalid_reuse_ref_surfaces_as_warning_in_header():
    out = normalize_directive({"cuts": [
        _cut(1), _cut(2, asset_strategy="reuse_crop", base_asset_ref="99"),
    ]}, "comic", content_plan=_plan())
    assert "invalid_reuse_ref#2" in out["header"]["mode_warnings"]


# ── 근거 커버리지·차단 ──
def test_evidence_coverage_recomputed_from_cuts():
    out = normalize_directive({
        "header": {"evidence_coverage": {"missing_claim_ids": []}},   # 모델이 "다 있다"고 주장
        "cuts": [_cut(1, claim_ids=["C01"], evidence_role="primary_result")],
    }, "comic", fact_sheet=_ledger(), content_plan=_plan())
    cov = out["header"]["evidence_coverage"]
    assert cov["missing_claim_ids"] == ["C02"]       # 보조 주장이 어느 컷에도 없다
    assert "missing_required_claims" in out["header"]["block_reasons"]
    assert out["header"]["approval_blocked"] is True


def test_mode_guidance_names_every_claim_the_gate_will_require():
    """프롬프트가 게이트와 같은 것을 요구하는가(2026-08-05 회귀).

    게이트(`missing_required_claims`)는 primary + supporting 이 **전부** 컷에 실렸는지를 본다.
    그런데 프롬프트는 "핵심 주장 하나만 지불한다"고만 했다 — 모델이 지시를 잘 따를수록 차단됐다.
    실측: 논문 9f6f2e8b 의 지시서가 C04 를 빠뜨려 차단, 운영자는 렌더로 갈 길이 없었다.
    """
    from engine.directive import _mode_guidance

    text = _mode_guidance(_plan(primary_claim_id="C03",
                                supporting_claim_ids=["C01", "C02", "C04"]))
    for claim in ("C03", "C01", "C02", "C04"):
        assert claim in text, f"프롬프트가 {claim} 을 요구하지 않는다 — 게이트만 막는다"
    assert "[반드시 지불할 주장]" in text


def test_full_coverage_is_not_blocked():
    out = normalize_directive({"cuts": [
        _cut(1, claim_ids=["C01"], evidence_role="primary_result"),
        _cut(2, claim_ids=["C02"], evidence_role="scope"),
    ]}, "comic", fact_sheet=_ledger(), content_plan=_plan())
    assert out["header"]["block_reasons"] == []
    assert out["header"]["approval_blocked"] is False


def test_dangling_claim_ids_dropped_from_cuts():
    out = normalize_directive({"cuts": [_cut(1, claim_ids=["C01", "C99"])]},
                              "comic", fact_sheet=_ledger(), content_plan=_plan())
    assert out["cuts"][0]["claim_ids"] == ["C01"]


def test_over_80_sec_blocks_approval():
    cuts = [_cut(i, estimated_sec=10, claim_ids=["C01"], evidence_role="primary_result")
            for i in range(1, 10)]
    out = normalize_directive({"cuts": cuts}, "comic",
                              fact_sheet=_ledger(), content_plan=_plan())
    assert out["header"]["total_estimated_sec"] == 90
    assert "over_max_duration" in out["header"]["block_reasons"]


def test_mode_duration_range_written_from_mode():
    out = normalize_directive({"cuts": [_cut(1)]}, "comic",
                              content_plan=_plan(selected_mode="deep"))
    h = out["header"]
    assert h["content_mode"] == "deep"
    assert (h["target_duration_min_sec"], h["target_duration_max_sec"]) == (51, 65)


# ── 경고 ──
def test_long_cut_without_state_change_warns():
    out = normalize_directive({"cuts": [
        _cut(1, estimated_sec=10, scene_kind="broll_stock"),
    ]}, "comic", content_plan=_plan())
    assert "long_cut_without_state_change#1" in out["header"]["mode_warnings"]


def test_long_cut_with_state_change_is_quiet():
    out = normalize_directive({"cuts": [
        _cut(1, estimated_sec=10, state_change="그래프가 비교 집단 아래로 내려간다"),
    ]}, "comic", content_plan=_plan())
    assert "long_cut_without_state_change#1" not in out["header"]["mode_warnings"]


def test_missing_novelty_event_warns():
    out = normalize_directive({"cuts": [_cut(1, novelty_event="")]}, "comic",
                              content_plan=_plan())
    assert "no_novelty_event#1" in out["header"]["mode_warnings"]


# ── 레거시 보호 ──
def test_legacy_directive_without_new_keys_normalizes_and_is_not_blocked():
    out = normalize_directive({"cuts": [
        {"cut_no": 1, "narration_ko": "a", "source_facts": ["what_found[0]"]},
    ]}, "image_sequence")
    cut = out["cuts"][0]
    assert cut["claim_ids"] == [] and cut["evidence_role"] == config.DEFAULT_EVIDENCE_ROLE
    assert cut["asset_strategy"] == config.DEFAULT_ASSET_STRATEGY
    assert out["header"]["approval_blocked"] is False
    assert out["header"]["block_reasons"] == []


def test_legacy_existing_fields_all_preserved():
    # 명세 §12-2 예시가 빠뜨린 필드들 — 교체가 아니라 추가여야 한다.
    out = normalize_directive({"cuts": [_cut(
        1, bgm_cue="riser", style_anchor_ref="컷1 참조", loop_safe=True,
        motion_prompt="drift", render_notes="[근거] ...",
    )]}, "comic")
    cut = out["cuts"][0]
    for key in ("bgm_cue", "style_anchor_ref", "loop_safe", "visual_type",
                "motion_prompt", "source_facts", "render_notes"):
        assert key in cut, f"{key} 가 사라졌다(하위호환 파괴)"
    assert cut["bgm_cue"] == "riser" and cut["loop_safe"] is True


def test_block_reasons_empty_without_content_plan():
    header = {"total_estimated_sec": 200, "cost_plan": {
        "video_generated_sec": 0, "max_video_generated_sec": 8,
        "estimated_video_cost_usd": 0.0, "max_video_cost_usd": 0.4}}
    # 계획이 없으면 길이 축도 돌지 않는다(레거시 지시서 보호).
    assert directive_block_reasons(header, [], None) == []


# ── 프롬프트 ──
def test_prompt_no_longer_tells_model_to_fill_clip_quota():
    from engine.directive import DIRECTIVE_SYSTEM_BASE, VERSION_GUIDANCE
    joined = DIRECTIVE_SYSTEM_BASE + "".join(VERSION_GUIDANCE.values())
    assert "꽉 채워 배정하라" not in joined
    assert "개수 상한을 의무적으로 채우지 마라" in joined
    assert "전체 길이를 먼저 고정하지 마라" in DIRECTIVE_SYSTEM_BASE
    assert config.EVIDENCE_RULES_SHARED in DIRECTIVE_SYSTEM_BASE


def test_mode_guidance_injects_only_selected_mode_skeleton():
    from engine.content_mode import MODE_SKELETONS
    from engine.directive import directive_user_prompt
    prompt = directive_user_prompt(
        {"fact_sheet": {}, "script_md": "", "video_prompts": [],
         "video_flow": {"content_plan": _plan(selected_mode="deep")}},
        "comic")
    assert MODE_SKELETONS["deep"] in prompt
    # 나머지 3개 골격은 들어가면 안 된다(프롬프트 비대 방지).
    for other in ("flash", "standard", "extended"):
        assert MODE_SKELETONS[other] not in prompt
