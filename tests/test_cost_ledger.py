"""비용 원장(작업 C, 명세 §6) 단위 테스트 — DB·네트워크 없음.

- 단가 스냅샷은 config.PRICING 에서 읽는다.
- 비용은 Decimal 로 계산해 부동소수 합산 오차가 없다(§12.7).
- 예상(requested) vs 실제(billed) 구분. 실패 호출은 actual=0.
- Batch/Realtime·Lite/Fast 혼합이 각각 다른 단가로 기록된다.
"""

from __future__ import annotations

from decimal import Decimal

from engine import config, cost


def test_unit_price_from_pricing_table():
    assert cost.unit_price("gemini-2.5-flash-image", "image_standard") == Decimal("0.039")
    assert cost.unit_price("gemini-2.5-flash-image", "image_batch") == Decimal("0.0195")
    assert cost.unit_price("veo-3.1-lite-generate-preview", "video_720p_per_sec") == Decimal("0.05")
    # 미등록 모델/단위 → 0(무료 또는 미과금).
    assert cost.unit_price("manim", "video_720p_per_sec") == Decimal("0")
    assert cost.unit_price("edge-tts", "tts_per_char") == Decimal("0")


def test_compute_cost_is_decimal_exact():
    # 0.05 × 4초 = 0.20 (부동소수라면 0.2 근사 오차가 날 수 있는 값을 정확히).
    assert cost.compute_cost("veo-3.1-lite-generate-preview", "video_720p_per_sec", 4) == Decimal("0.200000")
    # Batch 10장: 0.0195 × 10 = 0.195 (정확).
    assert cost.compute_cost("gemini-2.5-flash-image", "image_batch", 10) == Decimal("0.195000")


def test_no_float_drift_on_sum():
    # 0.0195 를 10번 더해도 원장 합계는 정확히 0.195 (float 이면 0.19500000000000003 드리프트).
    total = sum((cost.compute_cost("gemini-2.5-flash-image", "image_batch", 1) for _ in range(10)),
                Decimal("0"))
    assert total == Decimal("0.195000")


def test_build_attempt_image_realtime():
    a = cost.build_attempt(
        asset_type="image", provider="gemini", model_id="gemini-2.5-flash-image",
        generation_mode="realtime", unit_type="image_standard", requested_units=1,
        directive_id="dir1", cut_no=3)
    assert a["asset_type"] == "image" and a["generation_mode"] == "realtime"
    assert a["unit_price_usd"] == "0.039"
    assert a["estimated_cost_usd"] == "0.039000"
    assert a["actual_cost_usd"] == "0.039000"      # 성공 → actual = estimated
    assert a["directive_id"] == "dir1" and a["cut_no"] == 3


def test_build_attempt_batch_vs_realtime_differ():
    rt = cost.build_attempt(asset_type="image", provider="gemini", model_id="gemini-2.5-flash-image",
                            generation_mode="realtime", unit_type="image_standard", requested_units=1)
    bt = cost.build_attempt(asset_type="image", provider="gemini", model_id="gemini-2.5-flash-image",
                            generation_mode="batch", unit_type="image_batch", requested_units=1)
    # Batch 는 표준의 50%.
    assert Decimal(bt["actual_cost_usd"]) == (Decimal(rt["actual_cost_usd"]) / 2).quantize(Decimal("0.000001"))


def test_build_attempt_failed_has_zero_actual():
    a = cost.build_attempt(
        asset_type="video", provider="veo", model_id="veo-3.1-lite-generate-preview",
        generation_mode="standard", unit_type="video_720p_per_sec", requested_units=4,
        status="failed", error_class="safety")
    assert a["estimated_cost_usd"] == "0.200000"   # 예상은 남긴다(재시도 낭비 가시화)
    assert a["actual_cost_usd"] == "0.000000"      # 실패는 과금 안 됨(다른 비용 필드와 동일 정밀도)
    assert a["status"] == "failed"


def test_build_attempt_billed_units_override_bills_despite_failure():
    # 작업 B §8.5: Veo 처럼 "생성은 됐으나(과금) 산출물을 못 쓴" 실패는 billed_units 를 명시해
    # 실효 비용을 보존한다 — status=failed 라도 actual_cost 는 0 이 아니어야 한다.
    a = cost.build_attempt(
        asset_type="video", provider="veo", model_id="veo-3.1-lite-generate-preview",
        generation_mode="standard", unit_type="video_720p_per_sec", requested_units=4,
        billed_units=4, status="failed", error_class="billed_rejection")
    assert a["actual_cost_usd"] == "0.200000"
    assert a["status"] == "failed"


def test_veo_tier_prices_track_config():
    # Lite/Fast/Standard 티어가 각각 다른 단가로 기록된다(작업 B 통제 대상).
    lite = cost.compute_cost("veo-3.1-lite-generate-preview", "video_720p_per_sec", 4)
    std = cost.compute_cost("veo-3.1-generate-preview", "video_720p_per_sec", 4)
    assert lite == Decimal("0.200000") and std == Decimal("1.600000")
    assert std > lite


def test_pricing_table_has_current_models():
    # config 의 현행 모델 ID 가 단가표에 있어야 원장이 단가 0 으로 새지 않는다.
    assert config.IMAGE_MODEL in config.PRICING
    assert config.VEO_MODEL in config.PRICING
