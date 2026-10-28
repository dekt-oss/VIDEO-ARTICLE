"""주류 화면 계획 → 엔진 실사형 화면 규칙·검사. 2026-10-27. docs/deviation-drinks-script-engine.md

운영자: "세 화면이 너무 떡같은데?? 기존 엔진에서 보고 배운 게 이런 거니??" → "응 기존 엔진 규칙 도입해줘".
위스키 1단계 3장은 제작자 손 지시문으로 샀다 — 엔진이 실측으로 쌓은 화면 규칙(장면이 나레이션에 답한다·알아볼 사물·
도해 구조와 3색·주인공 하나·긍정 묘사)을 하나도 타지 않았다. 이 모듈은 주류 장면을 엔진 컷 꼴로 바꿔
**엔진 게이트(`photo_contract.evaluate`)와 자동 보정(`normalize_*`)을 그대로** 태운다.

★ 길이 규칙은 뺀다: 엔진 기준은 2분 안팎 논문 영상(컷 8개 이상·영상 컷 수)이고 주류는 30~40초 쇼츠다.
★ Jev 판정(장면이 답하나·부품을 알아보나·흥미로운가…)은 `jev=True` 일 때만 묻는다(돈이 든다 — 한 편 1센트 미만).
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

ROLE = {"mechanism": "MECHANISM", "reality": "REALITY", "other": "REALITY"}
# 쇼츠 길이와 맞지 않는 엔진 규칙(논문 2분 영상 기준) — 주류에서는 판정하지 않는다.
NOT_FOR_SHORTS = ("photo_cut_count_low", "photo_video_cut_count_off", "photo_video_cuts_not_adjacent",
                  "photo_role_balance_off", "photo_worlds_per_minute", "photo_mechanism_thin",
                  # 근거 묶음(Fact Sheet)의 원리 공급량으로 재는 규칙 — 주류는 Fact Sheet 를 넘기지 않아 늘 0 으로 나온다
                  "photo_narrative_no_mechanism", "photo_source_has_no_mechanism")
# 엔진 게이트 코드 → 사람이 읽는 설명(주류 화면에 자주 걸리는 것만. 나머지는 코드를 그대로 보인다).
CODE_KO = {
    "photo_mechanism_spec_missing": "3D 도해 장면에 구조(무엇이 보이고 무엇이 바뀌나)가 없습니다 — mechanism 을 채우세요",
    "photo_mechanism_prompt_detached": "그림 지시문이 도해 구조의 부품 이름을 쓰지 않습니다",
    "photo_mechanism_missing": "3D 도해 장면이 하나도 없습니다",
    "photo_split_composition": "한 그림을 칸으로 나누라고 합니다(분할 금지)",
    "photo_style_word_in_prompt": "화풍 어휘가 지시문에 있습니다(화풍은 코드가 붙인다)",
    "photo_quoted_label_in_prompt": "따옴표 친 이름 — 그림에 글자로 박힙니다",
    "photo_forbidden_screen_request": "화면 그래픽·글자를 그려 달라고 합니다",
    "photo_text_request_conflict": "글자 요구가 지시문에 있습니다",
    "photo_hook_missing": "첫 질문(훅)이 없습니다",
    "photo_reuse_without_state_change": "앞 그림을 이어 그리는데 바뀌는 것이 없습니다",
    "photo_scene_not_answering": "장면이 나레이션에 답하지 않고 주제 사진에 머뭅니다(Jev)",
    "photo_component_unrecognizable": "도해 부품을 시청자가 알아보기 어렵습니다(Jev)",
    "photo_scene_dull": "장면이 밋밋합니다 — 무언가 일어나야 합니다(Jev)",
    "photo_scene_unclear": "장면이 나레이션 이해를 돕지 않습니다(Jev)",
    "photo_cause_not_shown": "'~해서'의 원인이 화면에 없습니다(Jev)",
    "photo_undrawable_difference": "그릴 수 없는 판단어(healthier·improved…) — 셀 수 있는 사물로",
    "photo_color_code_reused": "비교 색(파랑·산호)을 부품 색으로 다시 씁니다",
    "photo_hook_cut_too_long": "첫 장면 나레이션이 깁니다",
}


def to_cut(sc: dict[str, Any], i: int) -> dict[str, Any]:
    """주류 장면 → 엔진 컷. 그림을 사지 않는 정리 카드는 None 이 아니라 호출 측이 거른다."""
    return {"cut_no": i, "narration_ko": sc.get("narration") or "", "narration_en": "",
            "estimated_sec": float(sc.get("timing_sec") or 4), "visual_role": ROLE.get(sc.get("visual_role") or "reality", "REALITY"),
            "visual_prompt": sc.get("visual_prompt") or "", "motion_prompt": sc.get("motion_prompt") or "",
            "answers_ko": sc.get("answers_ko") or "", "staging_ko": sc.get("staging_ko") or "",
            "mechanism": copy.deepcopy(sc.get("mechanism")) if isinstance(sc.get("mechanism"), dict) else {},
            "overlay_plan": [], "temporal_plan": [], "evidence_role": "core", "source_facts": list(sc.get("claim_ids") or [])}


def to_engine(scenes: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cuts = [to_cut(sc, i) for i, sc in enumerate(scenes, 1) if (sc.get("visual_role") or "reality") != "text_card"]
    header = {"version_type": "photo", "hook_ko": (scenes[0].get("narration") if scenes else "") or "",
              "global_style": config.PHOTO_GLOBAL_STYLE, "total_estimated_sec": sum(c["estimated_sec"] for c in cuts)}
    return header, cuts


def normalize(header: dict[str, Any], cuts: list[dict[str, Any]]) -> list[str]:
    """엔진 자동 보정(지시문의 화풍·발광·렌즈 어휘, 숫자·따옴표 라벨)을 컷 사본에 그대로 건다 — 주문 전 지시문이 이것이다."""
    from . import photo_contract as pc

    notes: list[str] = []
    for fn in (pc.normalize_optics, pc.normalize_style_words, pc.normalize_glow):
        notes += fn(header, cuts) or []
    notes += pc.normalize_prompt_labels(cuts) or []
    notes += pc.normalize_prompt_numbers(cuts) or []
    return notes


@contextmanager
def _jev(on: bool) -> Iterator[None]:
    prev = config.JEV_ENABLED
    config.JEV_ENABLED = bool(on) and prev
    try:
        yield
    finally:
        config.JEV_ENABLED = prev


def gate(scenes: list[dict[str, Any]], *, jev: bool = False) -> dict[str, Any]:
    """엔진 실사형 게이트. 반환: {blocks:[(code, cut_nos)], warns:[…], notes:[자동 보정]} — 쇼츠에 안 맞는 길이 규칙은 뺀다."""
    from . import photo_contract as pc

    header, cuts = to_engine(scenes)
    if not cuts:
        return {"blocks": [], "warns": [], "notes": []}
    notes = normalize(header, cuts)
    n_mech = sum(1 for c in cuts if c["visual_role"] == "MECHANISM")
    with _jev(jev):
        r = pc.evaluate(header, cuts, None, mechanism_supply=max(1, n_mech))

    def split(items: list[str]) -> list[tuple[str, str]]:
        out = []
        for it in items or []:
            code, _, where = str(it).partition(":")
            if code not in NOT_FOR_SHORTS:
                out.append((code, where))
        return out
    return {"blocks": split(r.get("block_reasons")), "warns": split(r.get("warnings")), "notes": notes}


def engine_cut_for_image(sc: dict[str, Any], i: int) -> dict[str, Any]:
    """그림 주문용 컷 — 엔진 보정을 거친 지시문과 도해 구조(부품·강조)를 싣는다(엔진 그림 프롬프트가 그대로 읽는다)."""
    header, cuts = to_engine([dict(sc, visual_role=sc.get("visual_role") or "reality")])
    c = cuts[0]
    c["cut_no"] = i
    normalize(header, cuts)
    return c
