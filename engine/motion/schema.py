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

# 숫자 토큰 = 부호 + 숫자 + 붙은 단위. **토큰째 정확히** 대조한다(코덱스 코드 리뷰: 부분문자열 비교는
# 근거 "15조"에 화면 "5조", 근거 "-15.9%"에 화면 "15.9%"를 통과시켰다). "20~30%" 는 20 과 30% 로 나뉜다.
# 단위는 긴 것부터(조원 > 조). 앞에 숫자·소수점이 붙어 있으면 토큰 중간이라 잡지 않는다.
_UNITS = ("%p", "%", "bp", "배", "조원", "조", "억원", "억", "만원", "만km", "만명", "만대", "만", "천억원", "천억",
          "천원", "천", "원", "달러", "명", "대", "개", "년", "월", "일", "분기", "x", "X")
# ★ 앞 글자가 무엇이든(한글·영문) 숫자는 전부 검문한다. 영문 뒤 숫자를 모델명(EV6·HBM4)으로 보고
#   건너뛰었더니 'PER12 배'·'PBR0.8'·'ROE99퍼센트' 가 근거 없이 나갔다(독립 재검사 ❌C, 두 번).
#   모델명은 보통 그 컷의 근거 문장에 같은 글자로 있어 그대로 통과하고, 없으면 문장이 빠진다(덜 나가는 쪽).
# 소수 중간('1.5'의 5)만 건너뛴다 — 문장 마침표 뒤('늘었다.999조')는 숫자다(독립 재검사 ❌, 2026-11-26).
_NUM_RE = re.compile(r"(?<!\d)(?<!\d\.)([-+−]?)(\d+(?:[.,]\d+)*)")
_UNIT_RE = re.compile(r"\s*(" + "|".join(re.escape(u) for u in _UNITS) + r")")


# 화면 글자가 아니라 배치 값인 칸(강조 위치·아이콘 모양). ★ rel(막대 높이)·count(아이콘 수)는 **여기 없다** —
#   양을 전달하므로 숫자처럼 검문한다(rel) 또는 코드가 값에서 다시 계산한다(count). 코덱스 코드 리뷰.
LAYOUT_KEYS = frozenset({"highlight", "icon", "count"})


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


_RANGE_RE = re.compile(r"(\d[\d.,]*)\s*[~∼\-–]\s*(\d[\d.,]*)\s*(" + "|".join(re.escape(u) for u in _UNITS) + r")")
_WON_UNIT = {"조원": "조", "억원": "억", "만원": "만", "천억원": "천억", "천원": "천"}


def _korean_amounts(text: str) -> str:
    """말로 쓴 금액을 Fact Sheet 표기로 맞춘다: '1조 1천억' → '1.1조', '2027~2028년' → '2027년 2028년'."""
    t = re.sub(r"(\d)\s*(?:%|％|퍼센트)\s*포인트", r"\1%p", str(text or ""))  # 15%p ≠ 15%
    t = re.sub(r"(\d)\s*(?:％|퍼센트)", r"\1%", t)  # 전각·말로 쓴 % 도 같은 토큰
    t = re.sub(r"(\d+)\s*조\s*(\d)\s*천\s*억", lambda m: f"{m.group(1)}.{m.group(2)}조", t)
    t = re.sub(r"(\d+)\s*조\s*(\d{1,4})\s*억", lambda m: f"{int(m.group(1)) + int(m.group(2)) / 10000:g}조", t)
    return _RANGE_RE.sub(lambda m: f"{m.group(1)}{m.group(3)} {m.group(2)}{m.group(3)}", t)


# 목록에 없는 단위: 바로 붙은 한글 한 글자('곳'·'위'·'차') 또는 영문 1~4자('GWh'·'E').
_TAIL_RE = re.compile(r"[가-힣]|[A-Za-z]{1,4}")
# 말에서 숫자 뒤에 흔히 붙는 조사 — 단위로 보지 않는다.
_PARTICLES = frozenset("은는이가을를에의도와과로만")


def token_spans(text: str) -> tuple[str, list[tuple[int, int, tuple[str, str, str]]]]:
    """(정규화한 글, [(시작, 끝, (부호, 숫자, 단위))]). **화면 칸·나레이션·근거가 같은 규칙**으로 나뉜다 —
    한쪽만 미등록 단위를 잡으면 근거와 똑같은 글자('12곳')도 어긋났다(독립 재검사 ⚠️1).
    '+' 는 부호 없음(+18.0% = 18.0%), '−' 는 '-'. '조원'·'억원' 은 '조'·'억'('100조 원' = '100조원')."""
    src = _korean_amounts(text)
    out = []
    for m in _NUM_RE.finditer(src):
        sign = "-" if m.group(1) in ("-", "−") else ""
        num = m.group(2).replace(",", "")
        try:
            num = repr(float(num)).rstrip("0").rstrip(".") if "." in num else str(int(num))
        except ValueError:
            pass
        end, unit = m.end(), ""
        u = _UNIT_RE.match(src, end)
        if u:
            unit, end = u.group(1), u.end()
        else:
            t = _TAIL_RE.match(src, end)
            if t and t.group(0)[0] not in _PARTICLES:
                unit, end = t.group(0), t.end()
        out.append((m.start(), end, (sign, num, _WON_UNIT.get(unit, unit))))
    return src, out


def tokens_in(text: str, strict_units: bool = False) -> list[tuple[str, str, str]]:
    """(부호, 숫자, 단위) 목록. strict_units 는 예전 호출 호환용(이제 항상 같은 규칙)."""
    return [t for _, _, t in token_spans(text)[1]]


def numbers_in(text: str) -> list[str]:
    return ["".join(t) for t in tokens_in(text)]


# 근거 풀에서 빼는 키 — 값이 아니라 위치·기간·검증 메타다. 넣으면 쪽수 9 가 '9조'의 근거가 됐다(독립 검사).
_NON_VALUE_KEYS = frozenset({"fact_id", "scope", "interpretation", "source_page", "period", "validation",
                             "chunk_id", "table_or_figure", "basis", "attribution"})


def _fact_texts(fact: Any) -> list[str]:
    if isinstance(fact, dict):
        out = _strings({k: v for k, v in fact.items() if k not in _NON_VALUE_KEYS})
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


def _ok(tok: tuple[str, str, str], pool: set[tuple[str, str, str]], strict_sign: bool) -> bool:
    """숫자·단위가 근거에 있나. 단위가 없으면 숫자만 같으면 된다(칸 number="100" + unit="조원" 처럼
    숫자와 단위를 다른 칸에 나눠 쓰는 템플릿). strict_sign 이면 부호도 같아야 한다 — **화면 숫자**는
    그렇다(근거 '-15.9%' 에 화면 '15.9%' 금지, 코덱스). **말**은 '적자 1조 1천억'·'15.9% 줄었다'처럼
    부호 대신 낱말로 방향을 말하므로 나레이션 검사에선 부호를 안 본다."""
    for p in pool:
        if p[1] == tok[1] and (not tok[2] or p[2] == tok[2]) and (not strict_sign or p[0] == tok[0]):
            return True
    return False


def number_gate(slots: Any, facts: list[Any], strict_sign: bool = True) -> list[str]:
    """칸(또는 문장) 숫자 중 근거 사실에 (부호·숫자·단위)째 없는 것들(빈 목록이면 통과).
    ★ 토큰 정확 대조 — 근거 '15조' 에 화면 '5조' 는 통과하지 못한다(코덱스 코드 리뷰)."""
    pool = {t for f in facts for s in _fact_texts(f) for t in tokens_in(s)}
    screen = strict_sign   # 화면 칸 검사(=부호 엄격)는 단위도 엄격하게
    bad = ["".join(t) for s in _strings(_joined(slots)) for t in tokens_in(s, strict_units=screen)
           if not _ok(t, pool, strict_sign)]
    return sorted(set(bad))


def _joined(slots: Any) -> Any:
    """숫자와 단위를 다른 칸에 쓰는 템플릿(hook_number: number + unit)은 **붙여서** 검문한다 —
    따로 두면 단위 없는 숫자로 보여 단위 대조가 빠졌다(독립 검사: 근거 74.5조에 74.5+억 통과)."""
    if isinstance(slots, dict) and "number" in slots and "unit" in slots:
        s = {k: v for k, v in slots.items() if k not in ("number", "unit")}
        s["number"] = f"{slots.get('number') or ''}{slots.get('unit') or ''}"
        return s
    return slots


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.?!])\s+", str(text or "").strip()) if x.strip()]


def scrub_narration(narr: str, facts: list[Any]) -> tuple[str, list[str]]:
    """근거에 없는 숫자가 든 **문장을 뺀다**(코덱스: 화면에서 지운 숫자가 음성·자막으로 다시 나갔다).
    반환: (남은 나레이션, 뺀 숫자들). 다 빠지면 빈 문자열 — 호출자가 그 컷을 버린다."""
    keep, bad = [], []
    for s in _sentences(narr):
        b = number_gate(s, facts, strict_sign=False)
        if b:
            bad += b
        else:
            keep.append(s)
    return " ".join(keep), sorted(set(bad))


def _fallback_slots(narr: str) -> dict:
    first = _sentences(narr)[0] if narr else ""
    # 폴백 카드에도 숫자를 싣지 않는다 — 검문을 통과 못 한 숫자가 문장째 되살아나면 안 된다.
    body = re.sub(r"\d", "", first)
    return {"title": "리포트 요약", "body": body[:60]}


def _icon_counts(slots: dict, max_icons: int) -> bool:
    """icon_ratio 의 아이콘 수를 **값에서 코드가 계산**한다(LLM count 무시). 비율을 못 내면 False."""
    a, b = slots.get("a") or {}, slots.get("b") or {}
    va, vb = templates._num(a.get("value")), templates._num(b.get("value"))
    ua = (tokens_in(str(a.get("value") or "")) or [("", "", "")])[0][2]
    ub = (tokens_in(str(b.get("value") or "")) or [("", "", "")])[0][2]
    if not va or not vb or va <= 0 or vb <= 0 or ua != ub:
        return False
    big, small = max(va, vb), min(va, vb)
    n = max(1, min(max_icons, round(big / small)))
    a["count"], b["count"] = (n, 1) if va >= vb else (1, n)
    return True


def _bar_units_match(slots: dict) -> bool:
    """막대는 **모든 칸에 단위 있는 값**이 있고 단위가 같아야 높이를 잰다(조 vs % 를 한 축에 세우면 거짓 그림).
    ★ 값 없이 상대 높이(rel)만 주는 막대는 받지 않는다 — 단위 없는 숫자는 근거의 아무 숫자와나 맞아
      검문이 무력했다(독립 검사: 근거 쪽수·검증 횟수로 rel 3·9 통과)."""
    items = [i for i in (slots.get("items") or []) if isinstance(i, dict)]
    toks = [(tokens_in(str(i.get("value") or ""), strict_units=True) or [("", "", "")])[0] for i in items]
    if not items or any(not t[1] or not t[2] for t in toks):
        return False
    for i in items:
        i.pop("rel", None)
    return len({t[2] for t in toks}) == 1


def _scrub_title(text: str, facts: list[Any], warns: list[str]) -> str:
    """근거 없는 숫자 토큰을 **그 자리(단위 포함)째** 지운다(재검사 ❌B: 미등록 단위가 남았다)."""
    bad = set(number_gate(text, facts))
    if not bad:
        return text.strip()
    warns.append(f"motion_title_number_dropped:{','.join(sorted(bad))[:40]}")
    src, spans = token_spans(text)
    for a, b, tok in reversed(spans):
        if "".join(tok) in bad:
            src = src[:a] + src[b:]
    return re.sub(r"\s{2,}", " ", src).strip(" ,·")


TEMPLATE_LABEL_KO: dict[str, str] = {
    "hook_number": "큰 숫자", "bar_compare": "막대 비교", "vs_split": "좌우 비교", "icon_ratio": "아이콘 비율",
    "card_stack": "카드 목록", "strike_vs_fact": "오해→실제", "flow_chain": "흐름도", "cycle3": "순환 고리",
    "scale_tilt": "저울", "stamp_card": "도장 카드", "text_card": "설명 카드",
}


def screen_summary(tpl: str, slots: dict) -> str:
    """승인 화면용 한 줄: [템플릿] 화면에 찍힐 글자들."""
    words = [s for s in _strings(slots) if s.strip()]
    return f"[{TEMPLATE_LABEL_KO.get(tpl, tpl)}] " + " · ".join(words)[:200]


def normalize_motion_directive(obj: dict, fact_sheet: dict | None, broker: str = "") -> dict[str, Any]:
    """LLM 출력 → 저장 모양 지시서. 경고는 header.mode_warnings(승인 화면이 이미 보는 자리)."""
    header_in = obj.get("header") if isinstance(obj.get("header"), dict) else {}
    warns: list[str] = []
    cuts: list[dict[str, Any]] = []
    all_facts: list[Any] = []
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
        all_facts += facts
        if missing:
            warns.append(f"motion_fact_key_unresolved:{i}:{','.join(missing)[:60]}")
        narr, nbad = scrub_narration(narr, facts)
        if nbad:
            warns.append(f"motion_narration_number_dropped:{i}:{','.join(nbad)[:60]}")
        if not narr:
            warns.append(f"motion_cut_dropped_no_grounded_narration:{i}")
            continue
        if tpl not in templates.TEMPLATES:
            warns.append(f"motion_unknown_template:{i}:{tpl[:20]}")
            tpl, slots = "text_card", _fallback_slots(narr)
        bad = number_gate(slots, facts)
        if bad:
            warns.append(f"motion_number_ungrounded:{i}:{','.join(bad)[:60]}")
            tpl, slots = "text_card", _fallback_slots(narr)
        if tpl == "icon_ratio" and not _icon_counts(slots, config.MOTION_MAX_ICONS):
            warns.append(f"motion_icon_ratio_without_values:{i}")
            tpl, slots = "text_card", _fallback_slots(narr)
        if tpl == "bar_compare" and not _bar_units_match(slots):
            warns.append(f"motion_bar_needs_same_unit_values:{i}")
            tpl, slots = "text_card", _fallback_slots(narr)
        cue_words = [str(w) for w in (m.get("cue_words") or []) if str(w).strip()]
        lost = [w for w in cue_words if w not in narr]
        if lost:
            warns.append(f"motion_cue_not_in_narration:{i}:{','.join(lost)[:40]}")
        cue_words = [w for w in cue_words if w in narr][:TEMPLATE_CUES.get(tpl, 2)]
        cuts.append({
            "cut_no": len(cuts) + 1, "scene_kind": "motion_graphic",
            "narration_ko": narr, "narration_en": str(c.get("narration_en") or ""),
            "estimated_sec": int(c.get("estimated_sec") or config.CUT_MIN_SEC),
            "answers_ko": str(c.get("answers_ko") or ""), "staging_ko": f"[모션] {tpl}",
            # 승인 화면 '화면' 칸(SequenceEditor KoBox)이 이 글을 보여준다 — 영상에 나갈 글자·숫자를 승인 전에 본다.
            "visual_prompt": "", "visual_prompt_ko": screen_summary(tpl, slots),
            "novelty_event": str(c.get("novelty_event") or ""),
            "style_anchor_ref": "", "effects": [], "transition": "cut", "bgm_cue": "",
            "source_facts": keys, "render_notes": str(c.get("render_notes") or ""),
            "motion_source": "still",
            "motion": {"template": tpl, "slots": slots, "cue_words": cue_words,
                       "source": source_line(facts, broker)},
        })
    # 상단 제목 띠는 영상 내내 떠 있다 — 숫자 검문을 거친다(독립 검사: '999조 시장' 통과).
    #   근거는 모든 컷이 가리킨 사실의 합. 어긋난 숫자 토큰은 지우고 경고한다.
    title = [_scrub_title(str(x), all_facts, warns) for x in (header_in.get("title_lines") or []) if str(x).strip()][:2]
    title = [t for t in title if t]
    hook = _scrub_title(str(header_in.get("hook_ko") or ""), all_facts, warns)
    header = {
        "aspect_ratio": "9:16",
        "hook_ko": hook or (title[0] if title else ""),
        "hook_en": str(header_in.get("hook_en") or ""),
        "title_lines": title or [hook or "오늘의 리포트"],
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
