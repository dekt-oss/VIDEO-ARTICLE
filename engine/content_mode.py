"""콘텐츠 모드 — 가변 길이·근거 계획의 단일 출처 (수정명세서_근거밀도_가변길이_v1.md §4-2·§6).

논문 복잡도가 영상 길이를 정하고, 제작비는 별도 예산이 정한다. 그 판정 로직이 여기 한 곳에만 있다.
`engine/scriptgen.py`(대본에서 계획 수립)와 `engine/directive.py`(지시서에서 재검증)가 **둘 다** 이 모듈을
쓴다 — 임계값이 두 프롬프트와 TS 사본까지 4벌로 흩어지는 걸 막는 장치다.

★ 순수 모듈: LLM·네트워크·DB 를 모른다. 임계값은 전부 `engine/config.py` 에서 읽는다.
★ 모델 자기보고 불신: LLM 이 준 `selected_mode`·`target_duration_*` 을 그대로 믿지 않고, 필수 근거 단위
  개수와 압축 위험으로 코드가 재판정한다(`normalize_content_plan`).
"""

from __future__ import annotations

from typing import Any

from . import config

# 【§7-2~7-5】 모드별 리텐션 골격. 프롬프트에는 **선택된 모드 것 하나만** 주입한다
# (4개를 다 나열하면 시스템 프롬프트가 비대해져 기존 훅·리텐션 규칙이 희석된다).
MODE_SKELETONS: dict[str, str] = {
    "flash": (
        "0.0~1.5s 증거 선공개 훅 / 1.5~4s 실제 연구 대상 공개 / 4~12s 핵심 비교·대표 수치 / "
        "12~22s 왜 그런지 또는 중요한 조건 / 22~30s 한계 포함 정확한 결론 / 30~35s 루프 또는 짧은 질문"
    ),
    "standard": (
        "0.0~1.5s 증거 선공개 / 1.5~4s 질문·의미 / 4~10s 연구 범위와 방법 / 10~25s 핵심 결과와 대표 수치 / "
        "25~38s 메커니즘 또는 예외 / 38~47s 한계와 정확한 해석 / 47~50s payoff·루프"
    ),
    "deep": (
        "0.0~1.5s 가장 강한 결과 / 1.5~5s 통념과 실제 연구 범위의 충돌 / 5~13s 비교 방식·표본·기간 중 핵심 / "
        "13~30s 주효과 / 30~45s 조절효과·예외 조건 / 45~56s 왜 이런 차이가 생기는지 / "
        "56~63s 한계와 정확한 결론 / 63~65s 의미 루프"
    ),
    "extended": (
        "Deep 골격을 늘리지 말고 10~15초짜리 미니 챕터 4~5개로 구성한다. 각 챕터는 질문→증거→해석 구조를 "
        "갖고, 챕터 전환마다 시각 스타일은 유지하되 레이아웃 상태를 바꾼다. 80초를 넘기지 않는다."
    ),
}

_COMPRESSION_RISKS: tuple[str, ...] = ("low", "medium", "high")
_COMPLEXITY_LEVELS: tuple[str, ...] = ("low", "medium", "high")
# E5 메커니즘 / E6 조절효과가 필수면 최소 deep — 생략하면 인과 오해가 생기는 단위들(§6-1 C).
_DEEP_FORCING_UNITS: frozenset[str] = frozenset({"E5", "E6"})


# ─────────────────────────────────────────────────────────────
# 모드 선택
# ─────────────────────────────────────────────────────────────
def select_mode(
    unit_count: int,
    *,
    deep_forcing: bool = False,
    compression_risk: str = "medium",
    independent_main_claims: int = 1,
) -> str:
    """필수 Evidence Unit 수·압축 위험으로 모드를 고른다(명세 §6-4).

    독립 핵심 주장 2개 이상 → series_split(한 편으로 만들지 않는다).
    7개 이상이어도 압축 위험이 high 가 아니면 extended 를 쓰지 않는다(extended 는 예외 모드).
    """
    if independent_main_claims >= 2:
        return "series_split"
    if unit_count > config.MODE_UNITS_DEEP_MAX:
        return "extended" if compression_risk == "high" else "deep"
    if unit_count >= config.MODE_UNITS_DEEP_MAX or deep_forcing:
        return "deep"
    if unit_count <= config.MODE_UNITS_FLASH_MAX:
        return "flash"
    if unit_count <= config.MODE_UNITS_STANDARD_MAX:
        return "standard"
    return "deep"


def duration_range(mode: str) -> tuple[int, int]:
    """모드의 목표 길이(초). 모드를 모르면 기존 전역 범위로 폴백(레거시 지시서)."""
    return config.CONTENT_MODE_DURATION.get(mode, (config.TOTAL_SEC_MIN, config.TOTAL_SEC_MAX))


def cut_max_sec(scene_kind: str | None = None, motion_source: str | None = None) -> int:
    """컷 길이 상한(§10-2). data_viz 는 길게, 영상(I2V) 컷은 짧게.

    ★ 영상 컷을 8초로 묶는 이유: 4초 Veo 클립을 12초 컷에 넣으면 clip_fit ratio 가 0.67 을 넘어
      핑퐁 구간(≤0.60) 밖으로 나가고 홀드만 남는다. 길이 보정이 감당할 수 있는 범위 안에 둔다.
    """
    if motion_source == "video":
        return config.VIDEO_CUT_MAX_SEC
    if scene_kind == "data_viz":
        return config.DATA_VIZ_CUT_MAX_SEC
    return config.PAPER_CUT_MAX_SEC


# ─────────────────────────────────────────────────────────────
# 비용 계획
# ─────────────────────────────────────────────────────────────
def resolve_cost_plan(mode: str) -> dict[str, Any]:
    """모드별 제작비 예산(결정 D-E1). 길이가 아니라 이 표가 이미지·영상비를 정한다.

    모드를 모르면(레거시·series_split) 기존 전역 캡으로 폴백한다 — 불변식이 퇴행하지 않게.
    """
    if mode in config.CONTENT_MODE_MAX_VIDEO_SEC:
        video_sec = config.CONTENT_MODE_MAX_VIDEO_SEC[mode]
        clips = config.CONTENT_MODE_MAX_VIDEO_CLIPS[mode]
        cost = config.CONTENT_MODE_MAX_VIDEO_COST_USD[mode]
    else:
        video_sec = config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC
        clips = config.VEO_MAX_CLIPS_PER_DRAFT
        cost = config.VIDEO_MAX_COST_USD_PER_TOPIC
    return {
        "content_mode": mode,
        "max_unique_assets": config.CONTENT_MODE_MAX_UNIQUE_ASSETS.get(
            mode, config.SERIES_SPLIT_MAX_UNIQUE_ASSETS),
        "max_video_clips": clips,
        "max_video_generated_sec": video_sec,
        "max_video_cost_usd": cost,
        "preferred_code_viz_count": config.CONTENT_MODE_PREFERRED_CODE_VIZ.get(mode, 0),
        "asset_reuse_target": config.CONTENT_MODE_ASSET_REUSE_TARGET.get(mode, 0.0),
        "cost_priority": config.DEFAULT_COST_PRIORITY,
    }


# ─────────────────────────────────────────────────────────────
# content_plan 정규화 (모델 자기보고 불신)
# ─────────────────────────────────────────────────────────────
def _enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    tok = str(value or "").strip().lower()
    return tok if tok in allowed else default


def _str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def normalize_content_plan(
    obj: Any,
    *,
    claim_ids: tuple[str, ...] | list[str] = (),
    independent_main_claims: int = 1,
) -> dict[str, Any]:
    """LLM 이 준 content_plan → 코드가 재판정한 계획.

    코드가 덮어쓰는 것(LLM 값 폐기):
    - `essential_evidence_units` 에 E1·E2·E7 을 항상 포함(§5-2 모든 영상 필수)
    - `selected_mode` — 필수 단위 수·압축 위험으로 재선택. extended 는 압축 위험 high 일 때만 유지
    - `target_duration_min/max_sec` — 항상 모드에서 재유도
    - 원장에 없는 claim_id 는 드롭
    """
    src = obj if isinstance(obj, dict) else {}
    known = set(claim_ids)

    units = [u for u in _str_list(src.get("essential_evidence_units")) if u in config.EVIDENCE_UNITS]
    for required in config.EVIDENCE_UNITS_REQUIRED:
        if required not in units:
            units.append(required)
    units.sort()

    primary = str(src.get("primary_claim_id") or "").strip()
    if known and primary not in known:
        primary = ""
    supporting = [c for c in _str_list(src.get("supporting_claim_ids"))
                  if (not known or c in known) and c != primary]

    delivery_in = src.get("evidence_delivery")
    delivery = {}
    if isinstance(delivery_in, dict):
        for unit, mode_ in delivery_in.items():
            if str(unit).strip() in config.EVIDENCE_UNITS:
                delivery[str(unit).strip()] = _enum(
                    mode_, config.EVIDENCE_DELIVERY, config.DEFAULT_EVIDENCE_DELIVERY)

    compression_risk = _enum(src.get("compression_risk"), _COMPRESSION_RISKS, "medium")
    deep_forcing = bool(_DEEP_FORCING_UNITS & set(units))
    warnings: list[str] = []

    proposed = _enum(src.get("selected_mode"), config.CONTENT_MODES, "")
    derived = select_mode(
        len(units),
        deep_forcing=deep_forcing,
        compression_risk=compression_risk,
        independent_main_claims=independent_main_claims,
    )
    mode = proposed or derived

    # extended 는 예외 모드다 — 압축 위험 근거가 없으면 deep 으로 강등(§6-4).
    if mode == "extended" and compression_risk != "high":
        mode = "deep"
        warnings.append("extended_demoted_no_compression_risk")
    # flash 인데 근거가 많으면 모드는 유지하되 경고(운영자가 판단).
    if mode == "flash" and len(units) >= config.MODE_FLASH_WARN_UNITS:
        warnings.append("flash_with_many_evidence_units")
    if independent_main_claims >= 2 and mode != "series_split":
        mode = "series_split"
        warnings.append("forced_series_split_multiple_main_claims")
    if proposed and proposed != mode:
        warnings.append(f"mode_overridden:{proposed}->{mode}")
    elif proposed and proposed != derived:
        # 규칙과 다른 모드를 모델이 골랐고 강등 사유도 없다 → 유지하되 운영자에게 알린다.
        warnings.append(f"mode_differs_from_rule:{derived}")

    lo, hi = duration_range(mode)
    return {
        "primary_claim_id": primary,
        "supporting_claim_ids": supporting,
        "essential_evidence_units": units,
        "evidence_delivery": delivery,
        "complexity": _enum(src.get("complexity"), _COMPLEXITY_LEVELS, "medium"),
        "visualizability": _enum(src.get("visualizability"), _COMPLEXITY_LEVELS, "medium"),
        "compression_risk": compression_risk,
        "selected_mode": mode,
        "target_duration_min_sec": lo,
        "target_duration_max_sec": hi,
        "duration_reason": str(src.get("duration_reason") or "").strip(),
        "series_split_reason": str(src.get("series_split_reason") or "").strip(),
        "mode_warnings": warnings,
    }


def block_reasons(plan: dict[str, Any] | None, total_sec: int | float | None) -> list[str]:
    """승인 차단 사유(§14-3 중 길이·분할 축). 경고와 달리 사람이 승인할 수 없게 만든다.

    ★★ `series_split` 은 **차단이 아니라 권고다**(2026-09-03 실측으로 되돌림).

      ① 명세가 그렇게 정했다 — 수정명세서_근거밀도_가변길이_v1 §8 열린질문 2:
         "코드는 **분할 권고까지만** 낸다. 2편으로 실제 쪼개는 UI·데이터 모델은 범위 밖이다."
         그런데 코드는 승인 차단으로 만들어 놓았다. **없는 기능을 요구하는 차단**이었다.
      ② 화면에 푸는 길이 없다. 저장소 주석 두 곳이 이미 그걸 인정한다
         (web/app/api/directive-approve/route.ts · VersionOrderBar.tsx):
         "series_split_required 처럼 **운영자가 화면에서 풀 방법이 없는 사유**".
      ③ **실측: 원장이 있는 초안 10건이 100% 여기 걸린다.** 신호가 `main_result` 로 찍힌
         claim 개수인데(factsheet.primary_claim_candidates), 논문은 원래 결과를 여러 개
         보고한다 — 실측 분포가 2·2·3·3·3·3·3·4·4·9 로 **하한 2를 안 넘는 논문이 없다.**
         명세가 말한 "**독립** 핵심 주장 2개"와 "main_result 로 찍힌 주장 2개"는 다른 것이고,
         코드는 뒤엣것을 세고 있었다.

      모든 것을 막는 게이트는 없는 게이트와 같다 — 운영자가 매번 강제 승인을 누르게 되고,
      그러면 그 뒤로는 **진짜 차단도 같이 통과한다**(강제 승인 경로가 이미 있다).
      그래서 신호는 유지하되(운영자는 계속 본다) 승인은 막지 않는다.
      되돌리려면 이 줄을 reasons 로 옮기면 된다 — 그때는 2편 분할 UI 를 같이 만들어야 한다.
    """
    reasons: list[str] = []
    if total_sec is not None and total_sec > config.CONTENT_MODE_HARD_MAX_SEC:
        reasons.append("over_max_duration")
    return reasons


def duration_warnings(plan: dict[str, Any] | None, total_sec: int | float | None) -> list[str]:
    """차단은 아니지만 운영자가 봐야 하는 길이 신호."""
    out: list[str] = []
    if total_sec is None:
        return out
    if total_sec < config.CONTENT_MODE_SOFT_MIN_SEC:
        out.append("below_soft_min_duration")
    if isinstance(plan, dict):
        lo = plan.get("target_duration_min_sec")
        hi = plan.get("target_duration_max_sec")
        if isinstance(lo, int) and isinstance(hi, int) and not (lo <= total_sec <= hi):
            out.append("outside_mode_duration_range")
    return out


# ─────────────────────────────────────────────────────────────
# 근거 커버리지
# ─────────────────────────────────────────────────────────────
# 커버리지 축 → 그 축을 채우는 evidence_role 들(§12-1 evidence_coverage).
_COVERAGE_ROLES: dict[str, frozenset[str]] = {
    "scope_present": frozenset({"scope"}),
    "method_present": frozenset({"method"}),
    "magnitude_present": frozenset({"magnitude"}),
    "caveat_present": frozenset({"caveat"}),
}


def compute_evidence_coverage(
    items: list[dict[str, Any]] | None,
    *,
    required_claim_ids: tuple[str, ...] | list[str] = (),
    primary_claim_id: str = "",
) -> dict[str, Any]:
    """씬·컷 목록에서 근거 커버리지를 **코드가 계산**한다(LLM 자기보고 대체).

    `evidence_delivery` 가 visual/caption 인 항목은 화면으로만 전달되므로 spoken 에 세지 않는다.
    """
    rows = [i for i in (items or []) if isinstance(i, dict)]
    spoken: list[str] = []
    visual: list[str] = []
    roles: set[str] = set()
    for item in rows:
        ids = _str_list(item.get("claim_ids"))
        role = str(item.get("evidence_role") or "").strip()
        if role:
            roles.add(role)
        delivery = str(item.get("evidence_delivery") or config.DEFAULT_EVIDENCE_DELIVERY).strip()
        target = visual if delivery in ("visual", "caption") else spoken
        for cid in ids:
            if cid not in target:
                target.append(cid)

    covered = set(spoken) | set(visual)
    required = list(dict.fromkeys([c for c in required_claim_ids if c]))
    out: dict[str, Any] = {
        "required_claim_ids": required,
        "spoken_claim_ids": spoken,
        "visual_claim_ids": visual,
        "missing_claim_ids": [c for c in required if c not in covered],
        "primary_claim_covered": bool(primary_claim_id) and primary_claim_id in covered,
    }
    for key, accepted in _COVERAGE_ROLES.items():
        out[key] = bool(roles & accepted)
    return out
