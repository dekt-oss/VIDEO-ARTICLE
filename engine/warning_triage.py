"""경고 분류 — 지시서 한 장에 56개가 뜨면 아무도 안 읽는다 (2026-09-28, 운영자 결정 "규칙 통합·정리").

실측(docs/규칙통합_분석_2026-09-28.md §1-2): 저장 지시서 36장의 경고 중앙값 56. 그중 **진짜 고칠 것은
5~8개**고 나머지는 ① 같은 발견을 두 표면이 센 것 ② 코드가 이미 처리했다는 알림 ③ 소재 한계다.
삼성전자 편은 경고 22개를 달고 그대로 승인됐다 — 많을수록 안 읽힌다.

여기서는 **새 검사를 만들지 않는다.** 이미 있는 코드를 넷으로 가르고 위 몇 개만 고른다:
  fact    근거 대조가 빨강·노랑을 낸 것 — 사람이 원문과 대조해야 한다
  action  모델이 다시 만들면 고쳐지는 것(config.RETRYABLE_QUALITY_WARNINGS 가 먼저)
  source  소재·대본의 한계 — 지시서 단계에서 못 고친다
  info    코드가 이미 처리했다 — 고칠 것이 없다(기록용)
분류표에 없는 코드는 action 으로 본다 — 모르는 경고를 조용히 숨기지 않는다.

`mode_warnings` 가 정본 표면이다. photo_gate·vseq·directive_audit 이 전부 여기로 미러되므로
(audit 은 `audit_` 접두로) 이것 하나만 세면 같은 발견을 두 번 세지 않는다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from . import config

# ── 코드가 이미 처리했다. 화면에서 고칠 것이 없다 ───────────────────────────
INFO: frozenset[str] = frozenset({
    "mode_overridden", "mode_differs_from_rule", "extended_demoted_no_compression_risk",
    "flash_with_many_evidence_units", "forced_series_split_multiple_main_claims",
    "video_budget_not_enforced_by_demotion", "motion_gate_would_demote", "video_cap_exceeded",
    "photo_temporal_beats_backfilled", "photo_color_code_assigned", "photo_optics_normalized",
    "photo_glow_normalized", "photo_style_word_normalized", "photo_prompt_number_removed",
    "photo_mechanism_spec_inherited", "photo_visual_role_backfilled", "photo_video_camera_repaired",
    "vseq_lineage_appear_inserted", "narration_repeat_removed", "asset_reuse_below_target",
    "directive_selfcheck_failed", "report_sequences_from_code_fallback",
    # novelty_event 는 엔진 소비자가 없는 칸이다(분석 §1-3) — 3단계에서 스키마에서 뺀다.
    "no_novelty_event",
    # 2026-09-28 에 경고에서 뺀 둘 — 그 전에 저장된 지시서에는 아직 남아 있다.
    "vseq_route_contract_conflict", "photo_mechanism_structured",
})
# ── 소재·대본의 한계. 지시서를 다시 만들어도 안 바뀐다 ────────────────────
SOURCE: frozenset[str] = frozenset({
    "photo_source_has_no_mechanism", "too_many_spoken_numbers", "bold_hook_on_weak_evidence",
})
# ── 근거 대조. 사람이 원문과 대조해야 한다 ────────────────────────────────
FACT_RED: frozenset[str] = frozenset({
    "audit_number_not_in_source", "audit_hook_number_not_in_source", "audit_claim_id_unknown",
    "directive_ungrounded", "cut_relation_not_in_source", "hook_promise_unpaid",
    "eq_v2_attribution_lost", "eq_v3_forecast_as_actual",
})
FACT_SOFT: frozenset[str] = frozenset({
    "audit_number_derived_from_source", "audit_number_restated_from_source",
    "qualifier_dropped", "scope_expanded", "editorial_inference",
    # 판정 모델(Jev)의 확률 판정이라 빨강이 아니라 노랑이다 — 사람이 원문과 대조한다(engine/grounding.py).
    "report_claim_unsupported", "paper_claim_unsupported",
})

CATEGORIES: tuple[str, ...] = ("fact", "action", "source", "info")

_CUT_TAIL = re.compile(r"(?:#|:)(\d{1,3})$")
_CUT_LIST = re.compile(r":(\d{1,3}(?:,\d{1,3})+)$")


def head(code: str) -> str:
    """`photo_world_churn:3.38/분` → `photo_world_churn`, `no_novelty_event#4` → `no_novelty_event`."""
    return re.split(r"[:#]", str(code or ""), maxsplit=1)[0].strip()


def cuts_of(code: str) -> list[int]:
    """코드 꼬리의 컷 번호. `vseq_cut_claim_mismatch:SEQ1#3` → [3], `photo_mechanism_unlabeled:2,5` → [2, 5]."""
    s = str(code or "")
    m = _CUT_LIST.search(s)
    if m:
        return [int(x) for x in m.group(1).split(",")]
    m = _CUT_TAIL.search(s)
    return [int(m.group(1))] if m else []


def category(h: str) -> str:
    if h in INFO:
        return "info"
    if h in SOURCE:
        return "source"
    if h in FACT_RED or h in FACT_SOFT:
        return "fact"
    return "action"


def _tier(h: str) -> int:
    """위에 올릴 순서. 작을수록 먼저 — 승인 전에 사람이 봐야 하는 것부터."""
    if h in FACT_RED:
        return 0
    if h in config.RETRYABLE_QUALITY_WARNINGS:
        return 1
    cat = category(h)
    if cat == "action":
        return 2
    if h in FACT_SOFT:
        return 3
    if cat == "source":
        return 4
    return 5


def summarize(mode_warnings: list[str] | None) -> dict[str, Any]:
    """{groups(순위순), top(≤N), counts(분류별), total, hidden} — 새 판정은 없고 정렬만 한다."""
    by_head: dict[str, list[str]] = defaultdict(list)
    for w in mode_warnings or []:
        h = head(w)
        if h:
            by_head[h].append(str(w))
    groups: list[dict[str, Any]] = []
    for h, items in by_head.items():
        cuts = sorted({n for w in items for n in cuts_of(w)})
        groups.append({"code": h, "category": category(h), "count": len(items), "cuts": cuts})
    groups.sort(key=lambda g: (_tier(g["code"]), -g["count"], g["code"]))
    counts = {c: 0 for c in CATEGORIES}
    for g in groups:
        counts[g["category"]] += g["count"]
    n = config.WARNING_SUMMARY_TOP_N
    return {
        "groups": groups,
        "top": groups[:n],
        "counts": counts,
        "total": sum(counts.values()),
        "hidden": sum(g["count"] for g in groups[n:]),
    }


def attach(header: dict[str, Any]) -> dict[str, Any]:
    """헤더에 `warning_summary` 를 (다시) 계산해 얹는다. 경고가 더 붙은 뒤 다시 불러도 된다."""
    header["warning_summary"] = summarize(header.get("mode_warnings"))
    return header
