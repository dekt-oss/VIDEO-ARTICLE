"""Feed an accepted V2 narration into the EXISTING Production directive generator (shadow only).

★ 왜 이 모듈이 있나(2026-10-05 설계 점검 A, 운영자 승인 "A는 추천대로").
  원 작업지시서 Phase 9 는 "새 Visual Beat Schema 를 만들지 않는다 — 기존 장면 설계를 정본으로"였다.
  구현은 새 간이 시각 계획(`visual_planner` → `explanation_directive`)을 만들었고, 그 지시서는
  장면 대신 틀 문장("Show only this statement: <대본>")을 써서 렌더에 쓸 수 없었다.
  이제 V2 가 검증한 **대본**을 기존 생성기(`directive.generate` / `report_directive.generate`)에
  초안 모양으로 넣는다. 화풍·실사형 계약·화면 구성 계약이 그대로 적용되고, 기존 지시서와
  **같은 생성기**로 만들어지므로 비교가 공정해진다(차이는 대본에서만 난다).

경계: `generate()` 만 부른다 — 지시서 표에 저장(`insert_directive`)·승인·렌더는 하지 않는다.
모델·판정 호출은 비용 장부(`generation_attempts`)에 기록되며 호출자가 센다.

1단계 `paper_draft` / `report_draft` — V2 대본 → 기존 생성기가 읽는 초안 모양.
  ⓐ 리포트 컷 `reasoning_id` 는 증권사 논리 번호(R01)만 살아남는다 → IR 의 `source_reasoning_id`.
  ⓑ 기존 생성기는 계획의 핵심 근거가 컷에 없으면 승인을 막는다 → 계획을 Production 이 아니라
     **V2 대본에 실제로 쓰인 근거**로 만든다.
  ⓒ 리포트 장면은 대본 문단과 1:1 이어야 프롬프트에 실린다(`script_revision.scenes_match_script`).
2단계 `attach_trace` — 생성기는 정해진 칸 밖의 정보를 지운다. 지시서가 나온 뒤 컷 ↔ V2 문장을
  대응시켜 근거·원문 위치를 다시 붙인다(`v2_trace`). 비교 자료 전용.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Callable

from . import config, cut_skeleton
from .llm import set_text_purpose

CONTRACT_VERSION = "v2-directive-bridge-v1"
_PUNCT = re.compile(r"[\s.,!?·'\"“”‘’()\[\]…~\-]+")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] \
        if isinstance(value, list) else []


def _beats(shadow: dict[str, Any]) -> list[dict[str, Any]]:
    narration = shadow.get("narration") or {}
    if narration.get("generation_status") != "DRAFT_ACCEPTED":
        raise ValueError("v2_narration_not_accepted")
    gate = shadow.get("gate") or {}
    if gate.get("gate_status") != "READY":
        raise ValueError(f"v2_gate_not_ready:{gate.get('gate_status')}")
    return [beat for beat in narration.get("narration_beats") or [] if isinstance(beat, dict)]


def _lock_value(shadow: dict[str, Any], beats: list[dict[str, Any]],
                paragraphs: list[str]) -> dict[str, Any]:
    """대사 고정 표시 + 화면 제안. V2 간이 화면 계획이 단락마다 정한 시각 모드에서 MECHANISM 만 넘긴다.

    ★ 실측(Samsung, 대사 고정 1차): 실사형 게이트가 원리 도해 컷을 요구하는데 모델이 7컷을 전부
      실사로 만들었다(`photo_mechanism_missing`). V2 는 "가격 상승 → 실적 개선" 단락이 과정이라는 것을
      이미 알고 있었다 — 그 정보를 생성기에 안 넘긴 것이 빈자리였다.
    """
    modes = {
        _text(row.get("beat_id")): _text(row.get("visual_mode"))
        for row in (shadow.get("visual_plan") or {}).get("visual_beats") or []
        if isinstance(row, dict)
    }
    hints = [
        {"text": text, "hint": "MECHANISM"}
        for beat, text in zip(beats, paragraphs)
        if modes.get(_text(beat.get("beat_id"))) == "MECHANISM" and text
    ]
    return {"visual_hints": hints}


def _beat_text(beat: dict[str, Any]) -> str:
    return " ".join(_strings(beat.get("sentences")))


def _screen_texts(beat: dict[str, Any]) -> list[str]:
    delivery = beat.get("number_delivery") if isinstance(beat.get("number_delivery"), dict) else {}
    return [_text(fact.get("text")) for fact in delivery.get("screen_facts") or []
            if isinstance(fact, dict) and _text(fact.get("text"))]


def _mode_for(script: str) -> tuple[str, int]:
    """V2 대본 길이로 고른 모드 — Production 계획(예: series_split)에 묶이지 않는다."""
    seconds = math.ceil(len("".join(script.split())) / config.SPEECH_CHARS_PER_SEC)
    for mode, (_, upper) in config.CONTENT_MODE_DURATION.items():
        if seconds <= upper:
            return mode, seconds
    return "extended", seconds


def _claim_ids(raw_refs: list[str]) -> list[str]:
    return [ref.split(":", 1)[1] for ref in raw_refs if ref.startswith("claims:")]


def _content_plan(beats: list[dict[str, Any]], claim_ids_by_beat: list[list[str]],
                  script: str) -> dict[str, Any]:
    used = list(dict.fromkeys(cid for ids in claim_ids_by_beat for cid in ids))
    mode, seconds = _mode_for(script)
    return {
        "selected_mode": mode,
        "primary_claim_id": used[0] if used else "",
        "supporting_claim_ids": used[1:],
        "essential_evidence_units": [],
        "duration_reason": f"V2 대본 길이 기준 약 {seconds}초",
        "mode_warnings": [],
        "source": CONTRACT_VERSION,
    }


def paper_draft(shadow: dict[str, Any], legacy_draft: dict[str, Any]) -> dict[str, Any]:
    beats = _beats(shadow)
    paragraphs = [_beat_text(beat) for beat in beats]
    script = "\n\n".join(p for p in paragraphs if p)
    claim_ids = [_claim_ids(_strings(beat.get("raw_refs"))) for beat in beats]
    scenes = []
    for position, (beat, text) in enumerate(zip(beats, paragraphs), 1):
        scenes.append({
            "scene": position,
            "title": _text(beat.get("stage")),
            "narration_ko": text,
            "source_facts": _strings(beat.get("raw_refs")),
            "claim_ids": claim_ids[position - 1],
            "evidence_role": "primary_result" if beat.get("evidence_ids") else "connective",
            "screen_facts": _screen_texts(beat),
        })
    return {
        "paper_id": _text(legacy_draft.get("paper_id")) or _text(shadow_content_id(shadow)),
        "fact_sheet": deepcopy(legacy_draft.get("fact_sheet") or {}),
        "script_md": script,
        cut_skeleton.NARRATION_LOCK_KEY: _lock_value(shadow, beats, paragraphs),
        "video_prompts": scenes,
        "video_flow": {"content_plan": _content_plan(beats, claim_ids, script)},
    }


def shadow_content_id(shadow: dict[str, Any]) -> str:
    return _text((shadow.get("narration") or {}).get("content_id"))


def _source_reasoning(shadow: dict[str, Any]) -> dict[str, str]:
    return {
        _text(unit.get("reasoning_id")): _text(unit.get("source_reasoning_id"))
        for unit in (shadow.get("ir") or {}).get("reasoning_units") or []
        if _text(unit.get("source_reasoning_id"))
    }


def report_draft(shadow: dict[str, Any], legacy_draft: dict[str, Any],
                 financial_reasoning: dict[str, Any] | None) -> dict[str, Any]:
    beats = _beats(shadow)
    source_rid = _source_reasoning(shadow)
    paragraphs = [" ".join(_beat_text(beat).split()) for beat in beats]
    script = "\n\n".join(p for p in paragraphs if p)
    scenes = []
    for position, (beat, text) in enumerate(zip(beats, paragraphs), 1):
        rids = [source_rid[rid] for rid in _strings(beat.get("reasoning_ids")) if rid in source_rid]
        scenes.append({
            "scene": position,
            "scene_role": _text(beat.get("stage")).lower(),
            "title": _text(beat.get("stage")),
            "narration_ko": text,
            "source_facts": _strings(beat.get("raw_refs")),
            "reasoning_id": rids[0] if rids else "",
            "screen_facts": _screen_texts(beat),
        })
    return {
        "report_id": _text(legacy_draft.get("report_id")) or shadow_content_id(shadow),
        "fact_sheet": deepcopy(legacy_draft.get("fact_sheet") or {}),
        "script_md": script,
        cut_skeleton.NARRATION_LOCK_KEY: _lock_value(shadow, beats, paragraphs),
        "scenes": scenes,
        "financial_reasoning": deepcopy(financial_reasoning or {}),
    }


def _norm(text: Any) -> str:
    return _PUNCT.sub("", str(text or ""))


def attach_trace(directive: dict[str, Any], shadow: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """컷마다 어느 V2 비트에서 왔는지 다시 붙인다. 생성기가 칸 밖 정보를 지우기 때문이다."""
    beats = _beats(shadow)
    beat_texts = [(_norm(_beat_text(beat)), beat) for beat in beats]
    result = deepcopy(directive)
    matched = 0
    for cut in result.get("cuts") or []:
        narration = _norm(cut.get("narration_ko"))
        source = next((beat for text, beat in beat_texts if narration and narration in text), None)
        if source is None:
            cut["v2_trace"] = {"matched": False}
            continue
        matched += 1
        cut["v2_trace"] = {
            "matched": True,
            "beat_id": _text(source.get("beat_id")),
            "reasoning_ids": _strings(source.get("reasoning_ids")),
            "evidence_ids": _strings(source.get("evidence_ids")),
            "raw_refs": _strings(source.get("raw_refs")),
            "screen_facts": _screen_texts(source),
        }
    cuts = len(result.get("cuts") or [])
    return result, {"cuts": cuts, "traced_cuts": matched, "untraced_cuts": cuts - matched}


Generator = Callable[[dict[str, Any]], dict[str, Any]]


def _default_generator(domain: str, report: dict[str, Any] | None) -> Generator:
    if domain == "paper":
        from . import directive

        return lambda draft: directive.generate(draft, "photo")
    from . import report_directive

    return lambda draft: report_directive.generate(draft, "photo", report)


def generate(domain: str, shadow: dict[str, Any], legacy_draft: dict[str, Any], *,
             financial_reasoning: dict[str, Any] | None = None,
             report: dict[str, Any] | None = None,
             generator: Generator | None = None) -> dict[str, Any]:
    """V2 대본 → 기존 생성기 지시서(+ 추적). DB 에 저장하지 않는다."""
    draft = (paper_draft(shadow, legacy_draft) if domain == "paper"
             else report_draft(shadow, legacy_draft, financial_reasoning))
    # 비용 장부 용도 라벨. 리포트 생성기는 스스로 라벨을 붙이지 않아(`report_directive`), 앞 단계의
    # "semantic_fidelity_shadow" 가 그대로 찍혔다(2026-10-05 실측: 지시서 2회 $0.29 가 '검증'으로 기록).
    set_text_purpose("v2_directive_bridge")
    produced = (generator or _default_generator(domain, report))(draft)
    if domain == "report" and report and isinstance(produced.get("header"), dict):
        produced["header"].setdefault("broker", report.get("broker"))
    directive, trace = attach_trace(produced, shadow)
    header = directive.get("header") if isinstance(directive.get("header"), dict) else {}
    return {
        "contract_version": CONTRACT_VERSION,
        "input_draft": draft,
        "directive": directive,
        "trace": trace,
        "narration_lock": header.get("narration_lock"),
        "approval_blocked": bool(header.get("approval_blocked")),
        "block_reasons": list(header.get("block_reasons") or []),
    }
