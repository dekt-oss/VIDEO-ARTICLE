"""모션그래픽 지시서 — 정규화 · 숫자 검문 · 쪽수 확인.

공용 정규화(directive.normalize_directive)를 쓰지 않는다. 그쪽은 그림 버전용 게이트(화면 계약·
시퀀스·visual_prompt)를 돌리고 미허용 버전을 기본 버전으로 갈아치운다. motion 은 그림을
그리지 않으므로 여기서 **같은 저장 모양**(version_type·header·cuts)만 맞춘다.

★ 숫자 검문(코덱스 계획 리뷰 반영): 칸에 들어간 숫자는 그 컷 `source_facts` 가 가리키는 사실
  문장 안에 **단위째**("74.5조", "2.2배") 있어야 한다. 하나라도 어긋나면 그 컷을 숫자 없는
  설명 카드(text_card)로 바꾸고 경고를 남긴다 — 차단하지 않는다(fail-open, 기존 원칙).
★ 출처 줄(자료: 증권사 pN)은 LLM 이 쓰지 않는다. 가리킨 사실의 `source_page` 로 코드가 만든다
  — 지어낸 쪽수 금지(CLAUDE.md).
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import config
from . import templates

# 템플릿별 큐 낱말 개수(애니메이션이 터지는 순간 수). 모자라면 고르게 나눈 시각으로 채운다.
TEMPLATE_CUES: dict[str, int] = {
    "hook_number": 2, "bar_compare": 2, "vs_split": 2, "icon_ratio": 3, "card_stack": 5,
    "strike_vs_fact": 2, "flow_chain": 2, "cycle3": 5, "scale_tilt": 1, "stamp_card": 2, "text_card": 1,
}

# 숫자 + 붙은 단위(한글 1~2자·%·배·x 등). "20~30%" 는 20 과 30% 로 나뉜다.
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|배|조|억|만|천|원|달러|명|대|개|년|월|일|분기|x|X|p|bp)?")


# 화면 글자가 아니라 배치 값인 칸(막대 상대 높이·강조 위치·아이콘 개수) — 숫자 검문 대상이 아니다.
LAYOUT_KEYS = frozenset({"rel", "highlight", "count", "icon"})


def _strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for k, x in v.items() if k not in LAYOUT_KEYS for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [str(v)]
    return []


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s)).replace(",", "")


def numbers_in(text: str) -> list[str]:
    return [_norm(m.group(0)) for m in _NUM_RE.finditer(str(text or ""))]


def _fact_texts(fact: Any) -> list[str]:
    if isinstance(fact, dict):
        out = _strings({k: v for k, v in fact.items() if k not in ("fact_id", "scope", "interpretation")})
        v, u = fact.get("value"), fact.get("unit")
        if v is not None and u:
            num = float(v)
            out.append(f"{int(num) if num.is_integer() else num}{u}")
        return out
    return _strings(fact)


def resolve_facts(keys: list[str], fact_sheet: dict | None) -> tuple[list[Any], list[str]]:
    """source_facts 키 → 사실 항목들. 반환: (항목들, 못 찾은 키들).

    허용 모양: number_facts 의 fact_id / "numbers[0]"·"number_facts[0]" / "basis[1]"·"what[0]"·"risks[0]" / "opinion"·"source".
    """
    fs = fact_sheet or {}
    nfs = [f for f in (fs.get("number_facts") or []) if isinstance(f, dict)]
    by_id = {str(f.get("fact_id")): f for f in nfs if f.get("fact_id")}
    found, missing = [], []
    for k in keys or []:
        key = str(k or "").strip()
        if key in by_id:
            found.append(by_id[key]); continue
        m = re.fullmatch(r"([a-z_]+)\[(\d+)\]", key)
        if m:
            name, idx = m.group(1), int(m.group(2))
            arr = nfs if name in ("numbers", "number_facts") else fs.get(name)
            if isinstance(arr, list) and 0 <= idx < len(arr):
                found.append(arr[idx]); continue
        elif key in fs and key != "number_facts":
            found.append(fs[key]); continue
        missing.append(key)
    return found, missing


def source_line(facts: list[Any], broker: str) -> str:
    pages = sorted({int(f["source_page"]) for f in facts
                    if isinstance(f, dict) and isinstance(f.get("source_page"), (int, float))
                    and not isinstance(f.get("source_page"), bool)})
    who = broker or "증권사 리포트"
    return f"자료: {who}" + (" " + "·".join(f"p{p}" for p in pages) if pages else "")


def number_gate(slots: dict, facts: list[Any]) -> list[str]:
    """칸 숫자 중 근거 사실에 단위째 없는 것들(빈 목록이면 통과)."""
    pool = _norm(" ".join(s for f in facts for s in _fact_texts(f)))
    bad = []
    for s in _strings(slots):
        for n in numbers_in(s):
            if n and n not in pool:
                bad.append(n)
    return sorted(set(bad))


def _fallback_slots(cut: dict) -> dict:
    narr = str(cut.get("narration_ko") or "").strip()
    first = re.split(r"(?<=[.?!])\s+", narr)[0] if narr else ""
    # 폴백 카드에도 숫자를 싣지 않는다 — 검문을 통과 못 한 숫자가 문장째 되살아나면 안 된다.
    body = re.sub(r"\d", "", first)
    return {"title": "리포트 요약", "body": body[:60]}


def normalize_motion_directive(obj: dict, fact_sheet: dict | None, broker: str = "") -> dict[str, Any]:
    """LLM 출력 → 저장 모양 지시서. 경고는 header.mode_warnings(승인 화면이 이미 보는 자리)."""
    header_in = obj.get("header") if isinstance(obj.get("header"), dict) else {}
    warns: list[str] = []
    cuts: list[dict[str, Any]] = []
    raw = [c for c in (obj.get("cuts") or []) if isinstance(c, dict)]
    if len(raw) > config.MOTION_MAX_CUTS:
        warns.append(f"motion_cuts_trimmed:{len(raw)}")
        raw = raw[:config.MOTION_MAX_CUTS]
    if len(raw) < config.MOTION_MIN_CUTS:
        warns.append(f"motion_too_few_cuts:{len(raw)}")
    for i, c in enumerate(raw, 1):
        narr = str(c.get("narration_ko") or "").strip()
        m = c.get("motion") if isinstance(c.get("motion"), dict) else {}
        tpl = str(m.get("template") or "")
        slots = m.get("slots") if isinstance(m.get("slots"), dict) else {}
        keys = [str(k) for k in (c.get("source_facts") or []) if str(k).strip()]
        facts, missing = resolve_facts(keys, fact_sheet)
        if missing:
            warns.append(f"motion_fact_key_unresolved:{i}:{','.join(missing)[:60]}")
        if tpl not in templates.TEMPLATES:
            warns.append(f"motion_unknown_template:{i}:{tpl[:20]}")
            tpl, slots = "text_card", _fallback_slots(c)
        bad = number_gate(slots, facts)
        if bad:
            warns.append(f"motion_number_ungrounded:{i}:{','.join(bad)[:60]}")
            tpl, slots = "text_card", _fallback_slots(c)
        cue_words = [str(w) for w in (m.get("cue_words") or []) if str(w).strip()]
        lost = [w for w in cue_words if w not in narr]
        if lost:
            warns.append(f"motion_cue_not_in_narration:{i}:{','.join(lost)[:40]}")
        cue_words = [w for w in cue_words if w in narr][:TEMPLATE_CUES.get(tpl, 2)]
        cuts.append({
            "cut_no": i, "scene_kind": "motion_graphic",
            "narration_ko": narr, "narration_en": str(c.get("narration_en") or ""),
            "estimated_sec": int(c.get("estimated_sec") or config.CUT_MIN_SEC),
            "answers_ko": str(c.get("answers_ko") or ""), "staging_ko": f"[모션] {tpl}",
            "visual_prompt": "", "novelty_event": str(c.get("novelty_event") or ""),
            "style_anchor_ref": "", "effects": [], "transition": "cut", "bgm_cue": "",
            "source_facts": keys, "render_notes": str(c.get("render_notes") or ""),
            "motion_source": "still",
            "motion": {"template": tpl, "slots": slots, "cue_words": cue_words,
                       "source": source_line(facts, broker)},
        })
    title = [str(x) for x in (header_in.get("title_lines") or []) if str(x).strip()][:2]
    header = {
        "aspect_ratio": "9:16",
        "hook_ko": str(header_in.get("hook_ko") or (title[0] if title else "")),
        "hook_en": str(header_in.get("hook_en") or ""),
        "title_lines": title or [str(header_in.get("hook_ko") or "오늘의 리포트")],
        "cta_ko": str(header_in.get("cta_ko") or ""), "cta_en": str(header_in.get("cta_en") or ""),
        "total_estimated_sec": int(sum(c["estimated_sec"] for c in cuts)),
        "version_type": config.MOTION_VERSION, "broker": broker,
        "mode_warnings": sorted(set(warns)), "block_reasons": [], "approval_blocked": False,
        # 발주 확인 모달(web/lib/orderCost.ts)이 읽는 자리 — 그림·영상 생성이 없으니 0원.
        "cost_plan": {"estimated_total_generation_cost_usd": 0.0, "unique_asset_count": 0,
                      "video_clip_count": 0, "video_generated_sec": 0},
    }
    if not cuts:
        header["block_reasons"] = ["motion_no_cuts"]
        header["approval_blocked"] = True
    return {"version_type": config.MOTION_VERSION, "header": header, "cuts": cuts}


def dumps(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)
