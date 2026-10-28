"""주류 대본·화면 계획 검사(코드, 0원). 2026-10-26. docs/deviation-drinks-script-engine.md

왜 있나: 2026-10-24~26 위스키 시험에서 대본이 원문을 넘었다 — 원문에 없는 처방("30ml에 물 세 티스푼"),
계산으로 이어 붙인 결론, 근거 없는 "~해 보세요". 운영자: "애초에 이렇게 할루시네이션으로 정보를 만들면 어떡하니",
"대본을 단순 수정하기보다 … 엔진 자체를 개선해야". 사람(제작자)의 눈대중 대신 **코드가 먼저 막는다**.

막는 것(block — 이것이 하나라도 있으면 그림을 사지 않는다)
  fact_scene_no_claim     사실 장면에 근거(claim_ids)가 없다
  claim_unknown           근거 목록에 없는 claim_id 를 쓴다
  derived_claim_cited     계산·추론으로 만든 근거(원문 인용이 아닌 것)를 화면 문장의 근거로 쓴다
  number_unsupported      나레이션의 숫자가 인용한 원문(또는 출처 표기)에 없다
  quantity_unsupported    양(티스푼·ml·방울·잔…)을 말하는데 인용한 원문에 그 단위가 없다
  advice_unsupported      "~해 보세요"류 권고인데 근거가 '실제 습관·권고'를 말한 원문이 아니다
  visual_prompt_missing   그림을 사야 하는 장면에 영어 그림 지시문이 없다
  continuity_invalid      이어 그리기(ref:N)가 앞 장면을 가리키지 않거나 그 장면이 그림이 아니다
  text_in_image           그림 지시문이 글자·라벨·오버레이를 그려 달라고 한다(언어 공유가 깨진다)
  conclusion_unsupported  '시청자가 내릴 결론' 한 줄에 근거가 없다
알리는 것(warn — 사람이 본다)
  formal_style            문어체 끝맺음(-습니다·-입니다) — 말하듯이 쓴다
  hook_missing            처음 두 장면 안에 질문이 없다
  conclusion_missing      '시청자가 내릴 결론'이 적혀 있지 않다
  long_sentence           한 장면 나레이션이 길다(한 번에 알아듣기 어렵다)
  subtitle_line_long      뜻 단위로 끊어도 한 줄이 길다
  style_word              잠긴 화풍과 싸우는 화풍 어휘가 그림 지시문에 있다
★ 한계(정직하게): 문장의 **뜻**이 원문을 넘었는지는 코드가 못 본다("한두 방울 → 45% 아래로" 같은 인과 비약).
  그것은 Jev 근거 판정과 사람 대조표가 본다. 이 검사는 숫자·양·권고·근거 표시처럼 기계가 확실히 할 수 있는 것만 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import config

# 숫자(쉼표·소수 포함). 2017년·45%·70도·30ml 의 숫자 부분.
# ★ 앞 글자 검사는 영문·숫자만 본다(2026-10-27). 전엔 \w 라 한자·한글 바로 뒤의 숫자(精米歩合50%·약50)를 못 읽어,
#   원문의 숫자는 빠지고(→ 근거 있는 숫자를 막음) 나레이션의 붙은 숫자는 검사를 빠져나갔다.
_NUM = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:[.,]\d+)?)")
# 한국어 양: (수사) + 단위. 단위 → 원문에서 찾을 영어·일본어 낱말.
_UNITS = {
    "티스푼": ("teaspoon", "spoon", "tsp"), "스푼": ("spoon", "tsp", "tablespoon"), "숟가락": ("spoon",),
    "ml": ("ml", "millilit"), "밀리리터": ("ml", "millilit"), "방울": ("drop",), "잔": ("glass", "dram", "shot"),
    "컵": ("cup",), "병": ("bottle",), "리터": ("litre", "liter", " l "),
}
_KO_NUMERALS = r"(?:한두|두세|서너|한|두|세|네|다섯|여섯|몇|\d+(?:[.,]\d+)?)"
_QUANTITY = re.compile(rf"{_KO_NUMERALS}\s*({'|'.join(sorted(map(re.escape, _UNITS), key=len, reverse=True))})", re.I)
# 권고(명령·청유) 끝맺음 — "~해 보세요", "~하세요", "~드세요", "~마세요", "~해요"(청유는 애매해 뺀다)
_ADVICE = re.compile(r"(?:보세요|하세요|드세요|마세요|넣으세요|타세요|고르세요|해\s?봐요|해\s?보자)[.!?…]*$")
_FORMAL = re.compile(r"(?:습니다|입니다|됩니다|ㅂ니다)[.!?…]*$")
_SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")
ADVICE_KINDS = {"practice", "recommendation", "advice", "howto"}
DERIVED_KINDS = {"calc", "derived", "inference"}
LONG_SENTENCE_CHARS = 48   # 공백 빼고. 실측: v5 장면 최장 31자, v4 의 문제 장면 46~52자


@dataclass
class Finding:
    code: str
    scene: Optional[int]
    message: str


@dataclass
class Report:
    blocks: list[Finding] = field(default_factory=list)
    warns: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocks

    def codes(self) -> list[str]:
        return [f.code for f in self.blocks]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "blocks": [f.__dict__ for f in self.blocks], "warns": [f.__dict__ for f in self.warns]}


def _quotes(claim: dict[str, Any]) -> list[str]:
    """claim 의 원문 인용들(시험 소재 형식 original_quote, DB 근거 묶음 형식 source_refs[].original_quote)."""
    out = [str(claim.get("original_quote") or "")]
    for r in claim.get("source_refs") or []:
        if isinstance(r, dict):
            out.append(str(r.get("original_quote") or ""))
    return [q for q in out if q.strip()]


def _kind(claim: dict[str, Any]) -> str:
    return str(claim.get("kind") or claim.get("claim_type") or "").strip().lower()


def _is_derived(claim: dict[str, Any]) -> bool:
    qs = _quotes(claim)
    return _kind(claim) in DERIVED_KINDS or not qs or all(q.lstrip().startswith(("(계산", "(추론", "(원문 아님")) for q in qs)


def _nums(text: str) -> set[str]:
    return {m.group(1).replace(",", "") for m in _NUM.finditer(text or "")}


def _source_text(spec: dict[str, Any]) -> str:
    src = spec.get("source") or {}
    if isinstance(src, dict):
        return " ".join(str(v) for v in src.values())
    return " ".join(str(s) for s in (spec.get("sources") or []))


def check(spec: dict[str, Any]) -> Report:
    """spec = {scenes:[…], claims:[…], source?, hook_question?, viewer_conclusion?:{text, claim_ids}}."""
    rep = Report()
    claims = {str(c.get("claim_id")): c for c in spec.get("claims") or [] if isinstance(c, dict)}
    scenes = spec.get("scenes") or []
    source_meta = _source_text(spec)

    def block(code: str, i: Optional[int], msg: str) -> None:
        rep.blocks.append(Finding(code, i, msg))

    def warn(code: str, i: Optional[int], msg: str) -> None:
        rep.warns.append(Finding(code, i, msg))

    image_scenes: set[int] = set()
    for i, sc in enumerate(scenes, 1):
        nar = str(sc.get("narration") or "").strip()
        role = sc.get("visual_role") or "reality"
        cids = [str(x) for x in (sc.get("claim_ids") or [])]
        if role != "text_card":
            image_scenes.add(i)
        if (sc.get("content_kind") or "fact") == "fact" and not cids:
            block("fact_scene_no_claim", i, "사실을 말하는 장면인데 근거(claim_ids)가 없습니다")
        unknown = [c for c in cids if c not in claims]
        if unknown:
            block("claim_unknown", i, f"근거 목록에 없는 주장: {', '.join(unknown)}")
        cited = [claims[c] for c in cids if c in claims]
        derived = [c for c in cids if c in claims and _is_derived(claims[c])]
        if derived:
            block("derived_claim_cited", i, f"원문 인용이 아닌 근거(계산·추론)를 화면 문장에 씁니다: {', '.join(derived)}")
        quotes = " ".join(q for c in cited if not _is_derived(c) for q in _quotes(c))
        allowed_nums = _nums(quotes) | _nums(source_meta)
        missing = sorted(n for n in _nums(nar) if n not in allowed_nums)
        if missing:
            block("number_unsupported", i, f"인용한 원문에 없는 숫자: {', '.join(missing)}")
        low = f" {quotes.lower()} "
        for m in _QUANTITY.finditer(nar):
            unit = m.group(1).lower()
            if not any(w in low for w in _UNITS.get(unit, _UNITS.get(m.group(1), ()))):
                block("quantity_unsupported", i, f"'{m.group(0)}' — 인용한 원문에 이 단위(양)가 없습니다")
        sentences = [s for s in _SENT_SPLIT.split(nar) if s.strip()]
        if any(_ADVICE.search(s.strip()) for s in sentences):
            if not any(_kind(c) in ADVICE_KINDS and not _is_derived(c) for c in cited):
                block("advice_unsupported", i, "권고(~해 보세요)인데, 실제 습관·권고를 말한 원문 근거가 없습니다")
        if any(_FORMAL.search(s.strip()) for s in sentences):
            warn("formal_style", i, "문어체 끝맺음 — 말하듯이 바꾸세요")
        if len(nar.replace(" ", "")) > LONG_SENTENCE_CHARS:
            warn("long_sentence", i, f"나레이션이 깁니다({len(nar.replace(' ', ''))}자) — 둘로 나누세요")
        _check_visual(sc, i, role, scenes, block, warn)
        _check_subtitles(nar, i, warn)

    # 엔진 실사형 화면 규칙(장면이 답하나·도해 구조·분할 금지·글자 금지·화풍 어휘…) — 코드 판정만(Jev 끔, 0원).
    from . import drinks_screen

    g = drinks_screen.gate(scenes, jev=False)
    for code, where in g["blocks"]:
        block(code, _first_scene(where), drinks_screen.CODE_KO.get(code, code) + (f" (장면 {where})" if where else ""))
    for code, where in g["warns"]:
        warn(code, _first_scene(where), drinks_screen.CODE_KO.get(code, code) + (f" ({where})" if where else ""))
    if not any("?" in str(sc.get("narration") or "") for sc in scenes[:2]) and not spec.get("hook_question"):
        warn("hook_missing", None, "처음 두 장면 안에 질문이 없습니다")
    concl = spec.get("viewer_conclusion")
    if not concl:
        warn("conclusion_missing", None, "'시청자가 내릴 결론' 한 줄이 없습니다 — 이어 들었을 때의 결론을 원문과 대조합니다")
    else:
        ccids = [str(x) for x in (concl.get("claim_ids") or [])] if isinstance(concl, dict) else []
        if not ccids or any(c not in claims or _is_derived(claims[c]) for c in ccids):
            block("conclusion_unsupported", None, "'시청자가 내릴 결론'에 원문 근거가 없습니다")
    return rep


def _first_scene(where: str) -> Optional[int]:
    # 엔진 코드의 꼬리는 컷 목록("3,4")일 수도, 측정값("28자"·"0<1")일 수도 있다 — 컷 목록일 때만 장면 번호로 읽는다.
    m = re.fullmatch(r"\s*(\d+)(?:\s*,\s*\d+)*\s*", str(where or ""))
    return int(m.group(1)) if m else None


def _check_visual(sc: dict[str, Any], i: int, role: str, scenes: list[dict[str, Any]], block, warn) -> None:
    from . import photo_contract as pc

    if role == "text_card":
        return
    vp = str(sc.get("visual_prompt") or "").strip()
    if not vp:
        block("visual_prompt_missing", i, "그림을 사야 하는 장면에 영어 그림 지시문이 없습니다")
        return
    m = re.match(r"^\s*ref:(\d+)\s*$", str(sc.get("continuity") or ""))
    if m:
        n = int(m.group(1))
        if n >= i or n < 1 or (scenes[n - 1].get("visual_role") or "reality") == "text_card":
            block("continuity_invalid", i, f"이어 그릴 {n}번 장면이 앞의 그림 장면이 아닙니다")
    if pc._TEXT_REQUEST.search(vp) or pc._QUOTED_LABEL.search(vp):
        block("text_in_image", i, "그림 지시문이 글자·라벨을 그려 달라고 합니다(글자는 화면 자막·카드로만)")
    hit = pc._RENDER_STYLE_RE.search(vp)
    if hit:
        warn("style_word", i, f"잠긴 화풍과 싸우는 어휘: '{hit.group(0)}' — 화풍은 코드가 붙입니다")


def _check_subtitles(nar: str, i: int, warn) -> None:
    from . import subtitles

    prev = config.CAPTION_PHRASE_BREAKS
    config.CAPTION_PHRASE_BREAKS = True
    try:
        long_lines = [g for g in subtitles.phrase_groups(nar)
                      if len(g.replace(" ", "")) > config.CAPTION_PHRASE_MAX_CHARS and len(g.split()) > 1]
    finally:
        config.CAPTION_PHRASE_BREAKS = prev
    if long_lines:
        warn("subtitle_line_long", i, f"자막 한 줄이 깁니다: {long_lines[0]}")


def plan_spec(plan: dict[str, Any], claims: list[dict[str, Any]], *, sources: Optional[list[dict[str, Any]]] = None,
              brief: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """DB 제작 작업(drinks_start_render 의 job) → 검사 입력. 근거는 승인된 근거 묶음의 claims(source_refs 원문 인용)."""
    conc = (plan or {}).get("viewer_conclusion") or None
    return {"scenes": (plan or {}).get("scenes") or [], "claims": claims or [],
            "sources": [" ".join(str(v) for v in (s or {}).values()) for s in (sources or [])],
            "hook_question": (brief or {}).get("audience_question"), "viewer_conclusion": conc}


_HASHTAG = re.compile(r"#[^\s#]+")
# 한도 계산용 — 낱말 한가운데의 #·@(a#b, 메일 주소)는 태그·멘션이 아니다.
_HASHTAG_TOKEN = re.compile(r"(?<!\w)#\w+")
_MENTION_TOKEN = re.compile(r"(?<![\w.])@[\w.]+")


def check_caption(caption: str, claims: list[dict[str, Any]], *, sources: Optional[list[dict[str, Any]]] = None) -> Report:
    """인스타 캡션 검사(발행 워커가 게시 직전에, 0원). 대본과 같은 기계 규칙 셋만 — 원문에 없는 숫자·양·권고.

    캡션은 장면이 아니라서 근거 표시(claim_ids)가 없다 → 승인된 근거 묶음 **전체**의 원문 인용을 허용 범위로 본다.
    해시태그는 검사에서 뺀다(#2026 같은 태그가 숫자로 걸리지 않게)."""
    rep = Report()
    # 인스타 캡션 한도(Meta IG User Media v26.0, 2026-10-28) — config.DRINKS_CAPTION_LIMITS. 넘으면 게시가 거부된다.
    lim = config.DRINKS_CAPTION_LIMITS
    n_chars, n_tags, n_mentions = len(caption or ""), len(_HASHTAG_TOKEN.findall(caption or "")), len(_MENTION_TOKEN.findall(caption or ""))
    if n_chars > lim["max_chars"]:
        rep.blocks.append(Finding("caption_too_long", None, f"캡션이 {n_chars}자입니다(한도 {lim['max_chars']}자)"))
    if n_tags > lim["max_hashtags"]:
        rep.blocks.append(Finding("hashtags_over_limit", None, f"해시태그가 {n_tags}개입니다(한도 {lim['max_hashtags']}개)"))
    if n_mentions > lim["max_mentions"]:
        rep.blocks.append(Finding("mentions_over_limit", None, f"@멘션이 {n_mentions}개입니다(한도 {lim['max_mentions']}개)"))
    text = _HASHTAG.sub(" ", caption or "")
    usable = [c for c in claims or [] if isinstance(c, dict) and not _is_derived(c)]
    quotes = " ".join(q for c in usable for q in _quotes(c))
    meta = " ".join(" ".join(str(v) for v in (s or {}).values()) for s in (sources or []))
    missing = sorted(n for n in _nums(text) if n not in (_nums(quotes) | _nums(meta)))
    if missing:
        rep.blocks.append(Finding("number_unsupported", None, f"캡션에 원문에 없는 숫자: {', '.join(missing)}"))
    low = f" {quotes.lower()} "
    for m in _QUANTITY.finditer(text):
        if not any(w in low for w in _UNITS.get(m.group(1).lower(), _UNITS.get(m.group(1), ()))):
            rep.blocks.append(Finding("quantity_unsupported", None, f"캡션의 '{m.group(0)}' — 원문에 이 단위(양)가 없습니다"))
    lines = [s.strip() for s in re.split(r"[\n]+|(?<=[.?!])\s+", text) if s.strip()]
    if any(_ADVICE.search(s) for s in lines) and not any(_kind(c) in ADVICE_KINDS for c in usable):
        rep.blocks.append(Finding("advice_unsupported", None, "캡션에 권고(~해 보세요)가 있는데, 실제 습관·권고를 말한 원문 근거가 없습니다"))
    return rep


def summary_ko(rep: Report) -> str:
    lines = [("통과" if rep.ok else f"막힘 {len(rep.blocks)}건") + (f" · 알림 {len(rep.warns)}건" if rep.warns else "")]
    for f in rep.blocks:
        lines.append(f"  ✖ {('%d번' % f.scene) if f.scene else '전체'} {f.code}: {f.message}")
    for f in rep.warns:
        lines.append(f"  · {('%d번' % f.scene) if f.scene else '전체'} {f.code}: {f.message}")
    return "\n".join(lines)
