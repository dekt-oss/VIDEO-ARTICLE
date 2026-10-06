"""Feed an accepted V2 narration into the EXISTING Production directive generator (shadow only).

★ 왜 이 모듈이 있나(2026-10-05 설계 점검 A, 운영자 승인 "A는 추천대로").
  원 작업지시서 Phase 9 는 "새 Visual Beat Schema 를 만들지 않는다 — 기존 장면 설계를 정본으로"였다.
  구현은 새 간이 시각 계획(`visual_planner` → `explanation_directive`)을 만들었고, 그 지시서는
  장면 대신 틀 문장("Show only this statement: <대본>")을 써서 렌더에 쓸 수 없었다.
  이제 V2 가 검증한 **대본**을 기존 생성기(`directive.generate` / `report_directive.generate`)에
  초안 모양으로 넣는다. 화풍·실사형 계약·화면 구성 계약이 그대로 적용되고, 기존 지시서와
  **같은 생성기**로 만들어지므로 비교가 공정해진다(차이는 대본에서만 난다).

경계: `generate()` 는 저장하지 않는다. 저장은 `save()` 한 곳뿐이고 운영자가 `--save-directive` 로 부를 때만
돈다(2026-10-05 운영자 결정 "가로 진행", 저장 코드 추가 허락 — V2 영상을 렌더하려면 지시서가 지시서 표에
있어야 한다). 승인·렌더는 여전히 하지 않는다 — 대시보드에서 사람이 한다.
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

from . import config, cut_skeleton, overlay_motion, script_polish, spoken_numbers
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


_LABEL_PARTICLE = re.compile(r"(?:으로|에서|이|가|은|는|을|를|의|도|과|와|에|로)$")
_LABEL_WORD = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9·]*")


def screen_card_text(text: str, max_items: int = 3) -> str:
    """말에서 뺀 숫자 문장 → 화면 카드 한 줄("DRAM 가격 18.0% · NAND 가격 16.0%").

    숫자 바로 앞의 낱말 두 개(조사 떼고)를 이름표로 쓴다. 이름표를 못 찾으면 숫자만 쓴다.
    """
    masked = spoken_numbers.mask_non_values(text)
    parts: list[str] = []
    previous_end = -100
    for start, end, _ in spoken_numbers.value_spans(text):
        value = text[start:end].strip()
        if parts and start - previous_end <= 4:          # "26%에서 41%" — 범위는 한 항목
            parts[-1] = f"{parts[-1]}~{value}"
            previous_end = end
            continue
        if len(parts) >= max_items:
            break
        words = [_LABEL_PARTICLE.sub("", word) or word
                 for word in _LABEL_WORD.findall(masked[max(0, start - 16):start])[-2:]]
        parts.append(f"{' '.join(words)} {value}".strip())
        previous_end = end
    return " · ".join(parts)


def _stem_overlap(a: str, b: str) -> int:
    return len(script_polish._stems(a) & script_polish._stems(b))


def attach_screen_cards(directive: dict[str, Any], shadow: dict[str, Any], domain: str = "paper") -> int:
    """V2 가 말에서 뺀 숫자 문장을 그 내용을 말하는 컷의 화면 숫자 카드로 단다. 반환: 붙인 카드 수.

    ★ 지시서 생성기는 정해진 칸 밖의 정보를 지운다 — 그래서 생성 **뒤에** 추적 정보(v2_trace)로 컷을 찾아
      `overlay_plan` 에 `screen_fact` 를 더한다. 같은 비트의 컷이 여럿이면 낱말이 가장 많이 겹치는 컷.
    ★ S5(2026-10-05): 카드마다 종류(`kind`)를 단다 — 리포트는 실적/전망/가이던스/시나리오, 논문은
      관측/모델 추정/가설. 렌더가 이름표와 상자 모양으로 구분한다(`overlay_motion.fact_kind`).
    """
    attached = 0
    cuts = [cut for cut in directive.get("cuts") or [] if isinstance(cut, dict)]
    for beat in _beats(shadow):
        delivery = beat.get("number_delivery") if isinstance(beat.get("number_delivery"), dict) else {}
        candidates = [cut for cut in cuts
                      if (cut.get("v2_trace") or {}).get("beat_id") == _text(beat.get("beat_id"))]
        for fact in delivery.get("screen_facts") or []:
            card = screen_card_text(_text((fact or {}).get("text")))
            if not card or not candidates:
                continue
            target = max(candidates, key=lambda cut: _stem_overlap(
                _text(cut.get("narration_ko")), _text(fact.get("text"))))
            plan = target.get("overlay_plan") if isinstance(target.get("overlay_plan"), list) else []
            if any(item.get("type") == "screen_fact" for item in plan if isinstance(item, dict)):
                continue                       # 컷당 한 장 — 같은 컷 후보에 이미 붙었다
            plan.append({"type": "screen_fact", "text": card, "priority": "primary",
                         "claim_ids": [], "ref": _text(fact.get("ref")),
                         "kind": overlay_motion.fact_kind(_text(fact.get("text")), domain)})
            target["overlay_plan"] = plan
            attached += 1
    return attached


Generator = Callable[[dict[str, Any]], dict[str, Any]]


def _default_generator(domain: str, report: dict[str, Any] | None) -> Generator:
    if domain == "paper":
        from . import directive

        return lambda draft: directive.generate(draft, "photo")
    from . import report_directive

    return lambda draft: report_directive.generate(draft, "photo", report)


def generate_from_script(domain: str, script: dict[str, Any], legacy_draft: dict[str, Any], *,
                         report: dict[str, Any] | None = None,
                         generator: Generator | None = None) -> dict[str, Any]:
    """기존 작성기가 쓴 V2 대본(기존 초안과 같은 모양) → 기존 지시서 생성기. 대사 고정은 쓰지 않는다 —
    대본이 이미 기존 작성기의 장면 단위라 생성기가 원래 하던 대로 컷을 나눈다."""
    draft = {**legacy_draft, "script_md": script.get("script_md") or "",
             "video_flow": script.get("video_flow") or {}}
    draft["video_prompts" if domain == "paper" else "scenes"] = script.get("scenes") or []
    set_text_purpose("v2_directive_bridge")
    directive = (generator or _default_generator(domain, report))(draft)
    header = directive.get("header") if isinstance(directive.get("header"), dict) else {}
    if domain == "report" and report:
        header.setdefault("broker", report.get("broker"))
    return {"contract_version": CONTRACT_VERSION, "input_draft": draft, "directive": directive,
            "trace": {"cuts": len(directive.get("cuts") or []), "writer": "production"},
            "narration_lock": None, "approval_blocked": bool(header.get("approval_blocked")),
            "block_reasons": list(header.get("block_reasons") or [])}


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
    trace["screen_cards"] = attach_screen_cards(directive, shadow, domain)
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


#: 저장된 V2 지시서 표시(header 안). 대시보드가 이것을 보고 "V2 설명 엔진" 안내를 띄운다.
V2_HEADER_KEY = "explanation_v2"


def save_refusal(result: dict[str, Any]) -> str:
    """저장하면 안 되는 이유. 빈 문자열이면 저장해도 된다.

    승인이 막힌 지시서는 저장하지 않는다 — 대시보드가 **가장 최근 지시서**를 보여 주므로, 렌더할 수 없는
    지시서가 멀쩡한 Production 지시서를 화면에서 밀어낸다.
    """
    if result.get("run_status") != "READY":
        return f"v2_not_ready:{result.get('run_status')}"
    generated = (result.get("shadow") or {}).get("generated")
    if not isinstance(generated, dict) or not isinstance(generated.get("directive"), dict):
        return "no_generated_directive(--with-directive 필요)"
    if generated.get("approval_blocked"):
        return "approval_blocked:" + ",".join(str(r) for r in generated.get("block_reasons") or [])
    return ""


def saved_row(result: dict[str, Any]) -> dict[str, Any]:
    """지시서 표에 넣을 행 — 기존 워커(`process_paper`/`process_report`)와 같은 모양 + V2 표시."""
    domain, content_id = result["domain"], result["content_id"]
    directive = deepcopy(result["shadow"]["generated"]["directive"])
    header = directive.get("header") if isinstance(directive.get("header"), dict) else {}
    run = result.get("run") or {}
    gate = result.get("publish_gate") or {}
    header[V2_HEADER_KEY] = {
        "bridge": CONTRACT_VERSION,
        "run_at": run.get("run_at"),
        "fact_sheet_snapshot_sha256": run.get("fact_sheet_snapshot_sha256"),
        "narration_model": run.get("narration_model"),
        "publish_gate_verdict": gate.get("verdict"),
        "script": "v2_narration",           # 컷 나레이션은 V2 대본이다(초안 표의 Production 대본과 다르다)
    }
    return {
        ("paper_id" if domain == "paper" else "report_id"): content_id,
        "version_type": directive.get("version_type") or "photo",
        "header": header,
        "cuts": directive.get("cuts") or [],
        "status": "draft",
    }


def save(result: dict[str, Any]) -> str:
    """V2 지시서를 지시서 표에 draft 로 넣는다. 반환: 새 지시서 id. 거절 사유가 있으면 ValueError."""
    refusal = save_refusal(result)
    if refusal:
        raise ValueError(f"v2_directive_not_saved:{refusal}")
    row = saved_row(result)
    if result["domain"] == "paper":
        from . import db
        return db.insert_directive(row)
    from . import report_db
    return report_db.insert_report_directive(row)
