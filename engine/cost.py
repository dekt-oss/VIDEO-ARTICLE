"""비용 원장(작업 C, 명세 §6) — 경량 버전.

모든 외부 생성 호출(image/video/tts/llm)을 `generation_attempts` 원장에 **1건 = 1행** 기록한다.
잡당 누적 float 한 개로는 Batch/Realtime·Lite/Fast·재생성 혼합 비용을 담을 수 없기 때문(§6.1).

설계 원칙:
- **단가 스냅샷:** 단가는 `config.PRICING` 에서 읽어 호출 시점 값을 행(`unit_price_usd`)에 박는다.
  → 무거운 `pricing_versions` 테이블 없이 과거 비용을 재현(경량 경로, §6.2).
- **Decimal:** 비용은 `Decimal` 로 계산해 부동소수 합산 오차를 막는다(§12.7). DB numeric 컬럼에 문자열로
  실어 정밀도를 보존한다.
- **공유 중복 계상 방지(§6.3):** 시각 에셋(이미지·영상)은 언어 무관 캐시라 **생성이 일어난 1회만** 기록한다
  (캐시 재사용은 기록하지 않음). 그래서 원장 합계 = 실제 총지출이 되고, KO·EN 에 이중 계상되지 않는다.
- **예상 vs 실제(§6.4):** requested_units 기반이 estimated, billed_units 기반이 actual. 실패한 호출은
  actual=0(대개 과금 안 됨)으로 기록해 재시도 낭비를 가시화한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import config, db
from .util import log

_CENTS = Decimal("0.000001")  # 원장 저장 정밀도(6자리) — 이미지 입력토큰 등 소액도 담게.


def unit_price(model_id: str, unit_type: str) -> Decimal:
    """config.PRICING 스냅샷 단가(USD). 미등록 모델/단위는 0(무료 또는 미과금)으로 본다."""
    val = config.PRICING.get(model_id, {}).get(unit_type)
    return Decimal(str(val)) if val is not None else Decimal("0")


def compute_cost(model_id: str, unit_type: str, units: float) -> Decimal:
    """단가 × 사용량 = 비용(Decimal). 부동소수 대신 Decimal 로 정확히."""
    return (unit_price(model_id, unit_type) * Decimal(str(units))).quantize(_CENTS)


def build_attempt(
    *,
    asset_type: str,               # image | video | tts | llm
    provider: str,
    model_id: str,
    generation_mode: str,          # standard | batch | realtime
    unit_type: str,                # image_standard | image_batch | video_720p_per_sec | tts_per_char
    requested_units: float,
    billed_units: float | None = None,
    directive_id: str | None = None,
    render_job_id: str | None = None,
    render_job_kind: str = "paper",   # paper=render_jobs · report=report_render_jobs (0039)
    cut_no: int | None = None,
    attempt_no: int = 1,
    status: str = "succeeded",
    error_class: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """원장 1행(dict). 비용은 Decimal 로 계산 후 문자열로 실어 numeric 정밀도 보존.

    estimated = 요청 사용량 × 스냅샷 단가. actual = 청구 사용량(billed_units) × 단가.
    billed_units 를 안 주면 성공 시 requested 전량, 실패 시 0(대부분의 실패는 미과금)을 기본값으로
    쓴다. ★ 예외: Veo 처럼 "생성은 완료(과금)됐으나 산출물을 못 쓴" 실패는 호출측이 billed_units 를
    명시로 넘겨 실효 비용을 보존한다(status="failed" 라도 actual>0, §8.5 "미채택 영상비도 실효비용에 포함").
    """
    if billed_units is not None:
        billed = billed_units
    else:
        billed = requested_units if status == "succeeded" else 0.0
    # ★★ FK 경계 (2026-09-19). `generation_attempts.directive_id` 는 **논문 `directives`
    #   하나만** 참조한다(0016). 리포트 지시서 id 를 실으면 insert 가 통째로 거부돼 원장이
    #   끊긴다 — 이 저장소가 이미 겪은 실패다(0039 주석: "$1.47 을 쓰고 원장은 0행").
    #   리포트 에셋 캐시를 배선하면서 렌더가 리포트 지시서 id 를 들고 다니게 됐으므로,
    #   원장에 들어가기 직전인 **여기서** 떨군다. 리포트 행은 render_job_id 로 묶인다.
    if str(render_job_kind) != "paper":
        directive_id = None
    price = unit_price(model_id, unit_type)
    estimated = compute_cost(model_id, unit_type, requested_units)
    actual = compute_cost(model_id, unit_type, billed)
    return {
        "directive_id": directive_id,
        "render_job_id": render_job_id,
        # ★ 어느 테이블의 잡 번호인지. 외래키를 뗀 대신 이 컬럼이 구분한다(0039).
        #   이게 없던 동안 리포트 렌더의 원장 기록이 **전부 거부**됐다 — 실사형 시험 렌더에서
        #   $1.47 을 쓰고 원장은 0행이었다.
        "render_job_kind": render_job_kind,
        "cut_no": cut_no,
        "asset_type": asset_type,
        "provider": provider,
        "model_id": model_id,
        "generation_mode": generation_mode,
        "unit_type": unit_type,
        "requested_units": str(Decimal(str(requested_units))),
        "billed_units": str(Decimal(str(billed))),
        "unit_price_usd": str(price),
        "estimated_cost_usd": str(estimated),
        "actual_cost_usd": str(actual),
        "attempt_no": attempt_no,
        "status": status,
        "error_class": error_class,
        "idempotency_key": idempotency_key,
    }


def record(attempt: dict[str, Any]) -> None:
    """원장에 1행 기록. 기록 실패는 렌더를 막지 않는다(로그만) — 캐시 기록과 동일 정책."""
    try:
        db.insert_generation_attempt(attempt)
    except Exception as exc:  # noqa: BLE001 — 원장 기록 실패가 렌더 전체를 막으면 안 됨
        log.warning("비용 원장 기록 실패(무시): %s", exc)

def _text_provider(model_id: str) -> str:
    """모델 ID → 원장에 적을 공급자 이름. engine/llm._backend_for 와 **같은 규칙**이다.

    ★ 여기가 틀리면 "공급자별 지출"이 조용히 거짓말을 한다 — 호출은 DeepSeek 으로 나갔는데
      원장은 anthropic 으로 집계되는 식이다.
    """
    m = (model_id or "").lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("deepseek"):
        return "deepseek"
    return "anthropic"


def text_attempt(*, model_id: str, purpose: str, input_tokens: int, output_tokens: int,
                 status: str = "succeeded", error_class: str | None = None,
                 directive_id: str | None = None, render_job_id: str | None = None,
                 render_job_kind: str = "paper") -> dict[str, Any]:
    """텍스트 LLM 호출 1건 → 원장 행.

    ★ 왜 필요한가(2026-08-29 사고): 원장에 **텍스트 호출이 한 줄도 없었다.** 이미지·영상만
      기록돼서, 운영자가 "어제 1.7만원을 뭐에 썼냐"고 물었을 때 코드가 답하지 못했다.
      실제로 그날 돈을 쓴 것은 이미지($2.79)가 아니라 텍스트였다 — 논문 16편 × 3안 = 48벌을
      만들고 그것을 두 번 채점했다. 비용 원장의 존재 이유가 그 질문에 답하는 것인데
      정작 가장 큰 항목이 빠져 있었다.

    ★ 입력·출력 단가가 달라 한 행에 담을 수 없다. **출력 토큰을 단위로 잡고** 실효 비용에
      입력분을 더한다 — 원장 한 행이 "이 호출이 얼마였나"를 정확히 말하게 한다.
    ★ 단가를 모르는 모델이면 비용 0 으로 남긴다. 기록 자체를 건너뛰면 "호출이 없었다"와
      구별되지 않는다 — 그게 이번 사고의 본질이다.
    """
    price = config.TEXT_PRICING.get(model_id, {})
    cin = Decimal(str(price.get("text_input_per_token", 0.0))) * Decimal(int(input_tokens))
    cout = Decimal(str(price.get("text_output_per_token", 0.0))) * Decimal(int(output_tokens))
    total = (cin + cout).quantize(_CENTS)
    billed = total if status == "succeeded" else total   # 잘린 응답도 과금된다(실측)
    return {
        "directive_id": directive_id,
        "render_job_id": render_job_id,
        "render_job_kind": render_job_kind,
        "cut_no": None,
        "asset_type": "llm",
        "provider": _text_provider(model_id),
        "model_id": model_id,
        "generation_mode": purpose,          # factsheet | script | selfcheck | directive | judge
        "unit_type": "text_output_per_token",
        "requested_units": float(output_tokens),
        "billed_units": float(output_tokens),
        "unit_price_usd": str(price.get("text_output_per_token", 0.0)),
        "estimated_cost_usd": str(total),
        "actual_cost_usd": str(billed),
        "attempt_no": 1,
        "status": status,
        "error_class": error_class,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
    }
