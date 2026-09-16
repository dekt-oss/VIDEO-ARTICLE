"""생성 사양 단일 출처 + 캐시 키 정합 (2026-08-29 리뷰 필수 테스트).

여기서 지키는 것은 하나다: **실제로 호출하는 모델 · 원장에 남는 모델 · 캐시 키가 만드는 모델이
전부 같은 값이어야 한다.** 셋이 갈라지면 다음이 조용히 일어난다 —
  ① Batch 가 프리미엄 모델을 우회한다(도해가 flash 로 생성돼 캐시에 굳는다)
  ② 원장이 실제와 다른 단가를 기록한다(비용을 못 믿게 된다)
  ③ 과거 flash 캐시가 MECHANISM 컷에 재사용된다(모델 상향이 화면에 도달하지 못한다)
"""

from __future__ import annotations

import pytest

from engine import assemble, config, generation_spec as gs
from engine import directive as dv
from engine.providers import image as image_provider

MECH = {"cut_no": 1, "visual_role": "MECHANISM", "visual_prompt": "cross-section of a valve",
        "asset_strategy": "new_asset", "motion_source": "still", "estimated_sec": 6}
REAL = {"cut_no": 2, "visual_role": "REALITY", "visual_prompt": "cross-section of a valve",
        "asset_strategy": "new_asset", "motion_source": "still", "estimated_sec": 4}
HEADER = {"version_type": "photo", "global_style": "documentary"}


# ── 사양 자체 ──
def test_spec_picks_premium_model_for_mechanism_only():
    assert gs.image_spec(MECH, HEADER).model == config.IMAGE_MODEL_BY_ROLE["MECHANISM"]
    assert gs.image_spec(REAL, HEADER).model == config.IMAGE_MODEL
    # 역할이 없는 레거시·만화식 컷은 전역 모델
    assert gs.image_spec({"visual_prompt": "x"}, HEADER).model == config.IMAGE_MODEL


def test_spec_price_follows_the_effective_model():
    mech, real = gs.image_spec(MECH, HEADER), gs.image_spec(REAL, HEADER)
    assert mech.unit_price_usd > real.unit_price_usd, "프리미엄 모델이 더 비싸야 한다"
    assert mech.unit_price_usd == config.PRICING[mech.model][mech.unit_type]


def test_spec_carries_the_fields_the_review_required():
    spec = gs.image_spec(MECH, HEADER)
    for field in ("provider", "model", "visual_role", "generation_mode", "unit_type",
                  "unit_price_usd", "aspect_ratio", "output_resolution", "style_version"):
        assert hasattr(spec, field), f"사양에 {field} 가 없다"


# ── 캐시 키 ──
def test_mechanism_and_reality_do_not_share_image_cache():
    """리뷰 필수: 같은 프롬프트라도 역할이 다르면 다른 그림이 나온다(다른 모델이 그린다)."""
    assert assemble.content_hash(MECH, HEADER) != assemble.content_hash(REAL, HEADER)


def test_image_cache_is_invalidated_when_effective_model_changes(monkeypatch):
    before = assemble.content_hash(MECH, HEADER)
    monkeypatch.setattr(config, "IMAGE_MODEL_BY_ROLE", {"MECHANISM": "gemini-3.1-flash-image"})
    assert assemble.content_hash(MECH, HEADER) != before


def test_image_cache_is_invalidated_when_style_contract_changes(monkeypatch):
    """화풍·계약 문구를 고치면 그림이 달라진다 — 옛 그림이 새 계약 컷에 재사용되면 안 된다."""
    before = assemble.content_hash(MECH, HEADER)
    monkeypatch.setattr(config, "PROMPT_CONTRACT_VERSION", "9999-01-01")
    assert assemble.content_hash(MECH, HEADER) != before


def test_language_is_still_absent_from_image_cache_key():
    """KO/EN 이 같은 이미지를 공유하는 근거는 그대로 살아 있어야 한다."""
    ko = dict(MECH, narration_ko="한국어", narration_en="")
    en = dict(MECH, narration_ko="", narration_en="English")
    assert assemble.content_hash(ko, HEADER) == assemble.content_hash(en, HEADER)


# ── 클립 캐시 ──
def _clip_key(cut=MECH, *, clip_sec=8, start="A"):
    return assemble.clip_content_hash(cut, HEADER, clip_sec=clip_sec, start_asset_hash=start)


def test_clip_cache_depends_on_start_asset():
    """리뷰 필수: 앞 연쇄 컷의 시작 에셋이 바뀌면 뒤 I2V 캐시가 무효화된다."""
    assert _clip_key(start="A") != _clip_key(start="B")


def test_clip_cache_depends_on_model_and_tier(monkeypatch):
    base = _clip_key()
    assert _clip_key(clip_sec=6) != base
    monkeypatch.setattr(config, "VEO_MODEL", "veo-3.1-fast-generate-preview")
    assert _clip_key() != base


def test_clip_cache_still_ignores_language():
    ko = dict(MECH, narration_ko="한국어")
    en = dict(MECH, narration_ko="", narration_en="English")
    assert _clip_key(ko) == _clip_key(en)


def test_clip_key_differs_from_image_key():
    """예전엔 클립과 이미지가 **같은 키 함수**를 썼다 — 그래서 Veo 설정 변경이 무시됐다."""
    assert _clip_key() != assemble.content_hash(MECH, HEADER)


# ── Batch ──
def test_batch_groups_requests_by_effective_model():
    """리뷰 필수: Batch 가 역할별 실제 모델을 쓴다(엔드포인트가 모델별로 갈린다)."""
    grouped = image_provider.group_batch_requests("dir1", [MECH, REAL], HEADER)
    assert set(grouped) == {config.IMAGE_MODEL_BY_ROLE["MECHANISM"], config.IMAGE_MODEL}
    assert len(grouped[config.IMAGE_MODEL_BY_ROLE["MECHANISM"]]) == 1
    assert len(grouped[config.IMAGE_MODEL]) == 1


def test_submit_batch_requires_an_explicit_model():
    """기본값을 두면 '역할 상향이 Batch 에서 무시되는' 버그가 조용히 돌아온다."""
    with pytest.raises(TypeError):
        image_provider.submit_batch([], "display")        # model 누락


def test_batch_submits_one_job_per_model(monkeypatch):
    from engine import db, image_batch

    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(db, "get_directive",
                        lambda _id: {"header": HEADER, "cuts": [MECH, REAL]})
    monkeypatch.setattr(db, "get_render_asset", lambda *a, **k: None)
    monkeypatch.setattr(db, "find_active_batch_job", lambda *a, **k: None)
    monkeypatch.setattr(db, "insert_image_batch_job", lambda row: None)
    monkeypatch.setattr(image_batch.image_provider, "submit_batch",
                        lambda requests, display_name, model: (
                            seen.append((model, len(requests))) or f"batches/{model}"))
    jobs = image_batch.submit_for_directive("dir1")
    assert len(jobs) == 2, "모델이 둘인데 잡이 하나면 한쪽 모델로 뭉쳐 나간 것이다"
    assert dict(seen) == {config.IMAGE_MODEL_BY_ROLE["MECHANISM"]: 1, config.IMAGE_MODEL: 1}


# ── 비용 계획 · 원장 ──
def test_cost_plan_prices_each_cut_with_its_real_model():
    plan = dv.compute_cost_plan([MECH, REAL], "standard", "photo")
    mech_spec, real_spec = gs.image_spec(MECH), gs.image_spec(REAL)
    expected = mech_spec.unit_price_usd + real_spec.unit_price_usd
    assert plan["estimated_image_cost_usd"] == pytest.approx(expected)
    assert set(plan["image_models"]) == {mech_spec.model, real_spec.model}


def test_cost_plan_is_not_flattened_to_one_model():
    """전 컷을 config.IMAGE_MODEL 로 계산하던 회귀를 막는다(도해가 싸게 보였다)."""
    plan = dv.compute_cost_plan([MECH, REAL], "standard", "photo")
    flat = config.PRICING[config.IMAGE_MODEL][gs.image_spec(MECH).unit_type] * 2
    assert plan["estimated_image_cost_usd"] > flat
