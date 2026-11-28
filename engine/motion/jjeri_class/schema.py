"""Structural, text, and price checks for Jjeri episode directives."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from engine import config
from .language import EN_CARDINAL, MEASURE_CORE, QUANTITY_MODIFIER, noun_boundary, unit_core

LIQUIDS = {"amber", "mahogany", "clear", "blend", "deep", "sherry"}
ICONS = {"glass", "barrel", "vanilla", "caramel", "smoke", "star_anise", "grapes",
         "plum", "cherries", "bottle", "arrow", "charred_plank"}
TONES = {"tomato", "yellow", "grey", "amber", "mahogany"}
TEXT = "text"
ICON = "icon"
BEAT = "beat"
COLOR = "color"
WOOD = {"light", "dark"}
ICON_SPEC = {"icon": ICON, "wood?": WOOD, "liquid?": LIQUIDS, "label?": TEXT}
LIQUID_SPEC = {"label": TEXT, "liquid": LIQUIDS}
NOTE = {**ICON_SPEC, "beat?": BEAT}
PRICE_SPEC = {**ICON_SPEC, "chip": TEXT, "price_level": TEXT}

SLOTS = {
    "glass_pair_question": {
        "left": {**LIQUID_SPEC, "question": TEXT}, "right": {**LIQUID_SPEC, "question": TEXT},
    },
    "myth_question": {side: {**ICON_SPEC, "label": TEXT} for side in ("from", "to")},
    "truth_infuse_stamp": {
        "wall_label": TEXT, "inside_label": TEXT, "from_color": LIQUIDS, "to_color": LIQUIDS,
        "stamp": TEXT, "stamp_on_beat": BEAT,
    },
    "journey_multiply": {
        "object": ICON_SPEC, "from_label": TEXT, "to_label": TEXT, "move_on_beat": BEAT,
        "multiply_on_beat": BEAT, "multiply_count": range(1, 7), "benefit_chip": TEXT,
    },
    "flavor_rise": {"base": {**ICON_SPEC, "label": TEXT},
                    "notes": (1, 4, {**NOTE, "label": TEXT, "beat": BEAT})},
    "pour_infuse": {"pour": {**ICON_SPEC, "icon": {"bottle"}, "label": TEXT, "chip": TEXT},
                    "target": {**ICON_SPEC, "icon": {"barrel"}, "chip": TEXT, "tint": LIQUIDS},
                    "result_chip": TEXT},
    "fill_and_notes": {"source": ICON_SPEC, "glass_to": LIQUIDS, "notes": (1, 3, NOTE),
                       "chips": (2, 2, TEXT)},
    "scarcity_compare": {"many": {**PRICE_SPEC, "count": range(2, 7)}, "one": PRICE_SPEC},
    "two_methods": {"rows": (2, 2, {"label": TEXT, "steps": (5, 5, "step")})},
    "recap_board": {"rows": (2, 2, {"subject": {**ICON_SPEC, "chip": TEXT},
                                   "items": (1, 3, "recap_item")}),
                    "exception_chip?": TEXT, "exception_on_beat?": BEAT},
    "house_rule_search": {
        "label": {"lines": (1, 3, TEXT), "circle_lines": (1, 3, range(3)), "chip": TEXT},
        "search": {"hint": TEXT, "query": TEXT, "on_beat": BEAT, "after_chip": TEXT},
        "show_prices": False,
    },
    "vote_comment": {"left": LIQUID_SPEC, "right": LIQUID_SPEC, "comment": TEXT,
                     "loop_to_first_frame": bool},
}
TEMPLATES = frozenset(SLOTS)
SCENE_ID = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")
HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_DIGITS = r"\d[\d,]*(?:\.\d+)?"
_CARDINAL = r"[영공일이삼사오육칠팔구십백천만억]+"
_AMOUNT = rf"(?:{_DIGITS}|{_CARDINAL})"
_CODE = r"(?:USD|KRW|EUR|JPY|GBP|CNY)"
_SYMBOL = r"[₩$€£¥￦]"
_KO_CURRENCY = unit_core({
    "원": "액 주 두 료 산지 칙 리 래 통 형 숙 서 소 심 근 룸 더풀",
    "불": "꽃 빛 씨 길 일치 규칙 확실 가능",
    "달러": "", "유로": "파", "파운드": "", "위안": "", "엔": "진 트리",
})
_AMOUNT_END = noun_boundary(QUANTITY_MODIFIER)
_COUNT_UNITS = unit_core({
    "밀리리터": "", "리터": "", "배럴": "", "명": "령 예 칭", "개": "울 운 선",
    "병": "당 원 력 행", "잔": "향 액 물", "건": "강 축", "회": "사 원",
    "톤": "", "통": "로 계 신",
})
_QUANTITY_UNIT = rf"(?:{MEASURE_CORE}|{_COUNT_UNITS}|(?:kg|mg|g|ml|l)(?![A-Za-z]))"
_SCALED = rf"(?:{_DIGITS}\s*|[일이삼사오육칠팔구십백천]+)(?:만|억)"
_GROUPED = r"\d{1,3}(?:,\d{3})+"
_PER_BOTTLE = r"(?:병\s*당|(?:한|1)\s*병(?:에)?)"
_PRICE_TOPIC = r"(?:가격대?|값)"
_TRADE_VERB = r"(?:사[요는]|살\s*수|팔[아요려]|구매)"
_PRICE = re.compile(
    rf"{_SYMBOL}\s*{_DIGITS}|{_DIGITS}\s*{_SYMBOL}|"
    rf"(?<!\w)(?:{_DIGITS}|{EN_CARDINAL})\s*(?:{_CODE}|won|dollars?|bucks?|euros?|pounds?|yen|yuan)(?![A-Za-z])|"
    rf"(?<![A-Za-z]){_CODE}\s*{_DIGITS}|"
    rf"(?<![가-힣\d]){_SCALED}\s*(?:{_DIGITS}\s*|[일이삼사오육칠팔구십백]*)천"
    rf"(?!\s*{_QUANTITY_UNIT})|"
    rf"(?<![가-힣\d])(?:{_SCALED}|{_GROUPED})(?:에|이면|면)\s*{_TRADE_VERB}|"
    rf"(?<![가-힣\d]){_SCALED}(?:대{_AMOUNT_END}|\s*(?:선{_AMOUNT_END}|안팎{_AMOUNT_END}|"
    rf"정도\s*(?:해|합니|한)|넘[어요는]))",
    re.I,
)
_CURRENCY_TOKEN = re.compile(
    rf"(?P<number>(?<![\d.,]){_DIGITS}(?:\s*[천백만억]+)?|"
    rf"(?<![가-힣\d])(?:{_CARDINAL}|(?:수|몇)(?:십|백|천)?[만천백억]))"
    rf"(?P<gap>\s*)(?P<unit>{_KO_CURRENCY})"
)
_PRICE_CONTEXT = re.compile(
    rf"(?<![가-힣])(?:{_PRICE_TOPIC}|{_PER_BOTTLE}){noun_boundary(copula=False)}"
    rf"\s*(?:[은는이을]\s*)?[:=]?\s*(?P<number>{_SCALED}|{_AMOUNT})"
)
_SHORT_SINO = frozenset("영공일이삼사오육칠팔구")
_BARE_END = re.compile(r"[.!?…]*$")
_COUNT_SUFFIX = re.compile(rf"\s*{_QUANTITY_UNIT}", re.I)
_CIRCLE_CONTEXT = re.compile(r"모양|둥글|그리|회전|반지름|직경|중심|시작")
_FIRE_CONTEXT = re.compile(r"태[우워]|그을|불꽃|불씨|화력|쓰|써|끄|꺼|켜")
_BARE_GROUPED_AMOUNT = re.compile(rf"{_GROUPED}(?:\s*(?:이에요|예요|이죠|입니다))?[.!?…]*")
_PRICE_VARIANTS = str.maketrans({"萬": "만", "万": "만", "千": "천", "圓": "원", "円": "엔"})


def price_issue(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text).translate(_PRICE_VARIANTS).strip()
    if _PRICE.search(normalized) or _BARE_GROUPED_AMOUNT.fullmatch(normalized):
        return "price_forbidden"
    ambiguous = False
    for match in _CURRENCY_TOKEN.finditer(normalized):
        suffix = normalized[match.end():]
        if match["unit"] == "원" and re.match(r"조(?!차)", suffix):
            continue
        # Only a spaced, single demonstrative plus a homograph needs context.
        if match["number"] != "이" or not match["gap"] or match["unit"] not in {"원", "불"}:
            return "price_forbidden"
        clause = re.split(r"[.!?…]", suffix, maxsplit=1)[0]
        if re.search(_TRADE_VERB, clause):
            return "price_forbidden"
        if match["unit"] == "원" and re.match(r"인(?:은|이|을|의)?(?:\W|$)", suffix):
            continue
        context = _CIRCLE_CONTEXT if match["unit"] == "원" else _FIRE_CONTEXT
        if not context.search(clause):
            ambiguous = True
    for match in _PRICE_CONTEXT.finditer(normalized):
        number, suffix = match["number"], normalized[match.end():]
        if number in _SHORT_SINO:
            # A single syllable can be a demonstrative, verb, or ordinal in this context.
            if _BARE_END.fullmatch(suffix) or re.fullmatch(r"(?:이에요|예요|입니다)[.!?…]*", suffix):
                ambiguous = True
        elif not _COUNT_SUFFIX.match(suffix):
            return "price_forbidden"
    return "price_ambiguous" if ambiguous else None


def has_price(text: str) -> bool:
    return price_issue(text) is not None


# The immutable golden captures a legacy 18-character subtitle.
REPLAY_SUBTITLE = "마지막에 셰리 통에서 더 익혀요."


def _token(value, *, math=False):
    if not isinstance(value, str):
        return False
    if math and value in {"+", "→"}:
        return True
    name, separator, variant = value.partition(":")
    if not separator:
        return name in ICONS
    if name in {"glass", "glass_small"}:
        return variant in LIQUIDS
    return name == "barrel" and variant in WOOD


def _shape(spec, value, beats):
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            return ["slots_invalid"]
        allowed = {key.rstrip("?") for key in spec}
        errors = ["slot_unknown"] if value.keys() - allowed else []
        for key, child in spec.items():
            actual = key.rstrip("?")
            if actual in value:
                errors.extend(_shape(child, value[actual], beats))
            elif not key.endswith("?"):
                errors.append("slot_missing")
        return errors
    if isinstance(spec, tuple):
        lo, hi, child = spec
        if not isinstance(value, list) or not lo <= len(value) <= hi:
            return ["slots_invalid"]
        return [error for item in value for error in _shape(child, item, beats)]
    if isinstance(spec, set):
        return [] if isinstance(value, str) and value in spec else ["slots_invalid"]
    if isinstance(spec, range):
        return [] if type(value) is int and value in spec else ["slots_invalid"]
    if spec is False:
        return [] if value is False else ["price_forbidden"]
    if spec is bool:
        return [] if type(value) is bool else ["slots_invalid"]
    if spec == BEAT:
        return [] if type(value) is int and 0 <= value < beats else ["beat_reference_invalid"]
    if spec == ICON:
        return [] if isinstance(value, str) and value in ICONS else ["icon_unknown"]
    if spec == "step":
        return [] if _token(value, math=True) else ["icon_unknown"]
    if spec == "recap_item":
        if not isinstance(value, list) or len(value) != 2:
            return ["slots_invalid"]
        return ([] if _token(value[0]) else ["icon_unknown"]) + _shape(TEXT, value[1], beats)
    return [] if _text(value) else ["slots_invalid"]


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and not any(
        unicodedata.category(ch) in {"Cf", "Cc"} and ch != "\n" for ch in value
    )


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _colors_valid(episode):
    keywords = episode.get("keywords")
    accents = episode.get("title_accents")
    if not isinstance(keywords, list) or not isinstance(accents, dict):
        return False
    pairs = list(accents.items())
    for entry in keywords:
        if not isinstance(entry, dict) or set(entry) != {"word", "color"}:
            return False
        pairs.append((entry["word"], entry["color"]))
    return all(_text(word) and isinstance(color, str) and HEX.fullmatch(color) for word, color in pairs)


def validate_episode(episode: dict[str, Any], *, replay: bool = False) -> list[str]:
    if not isinstance(episode, dict):
        return ["format_invalid"]
    errors = []
    if episode.get("format") != "jjeri_class" or type(episode.get("version")) is not int or episode["version"] != 1:
        errors.append("format_invalid")
    voice = {"provider": "edge", "voice": config.JJERI_VOICE, "rate": config.JJERI_RATE, "atempo": config.JJERI_ATEMPO}
    if episode.get("voice") != voice:
        errors.append("voice_invalid")
    if not _colors_valid(episode) or not all(_text(episode.get(key)) for key in ("series", "episode", "topic", "caption_draft")):
        errors.append("metadata_invalid")
    scenes = episode.get("scenes")
    if not isinstance(scenes, list) or not config.JJERI_SCENE_MIN <= len(scenes) <= config.JJERI_SCENE_MAX or any(not isinstance(s, dict) for s in scenes):
        return errors + ["scene_count_invalid"]
    ids = [s.get("id") for s in scenes]
    if any(not isinstance(identifier, str) or not SCENE_ID.fullmatch(identifier) or (identifier in {"frame", "main", "root", "bgm"} or "--" in identifier
                    or re.fullmatch(r"(?:vo|sfx)\d+|fr-.*", identifier))
           for identifier in ids) or len(set(ids)) != len(ids):
        errors.append("scene_id_invalid")
    chapters = episode.get("chapters")
    if (not isinstance(chapters, list) or not config.JJERI_CHAPTER_MIN <= len(chapters) <= config.JJERI_CHAPTER_MAX
            or any(not isinstance(c, dict) or not _text(c.get("title")) or c.get("from_scene") not in ids for c in chapters)):
        errors.append("chapters_invalid")
    else:
        indices = [ids.index(c["from_scene"]) for c in chapters]
        if indices[0] != 0 or indices != sorted(set(indices)):
            errors.append("chapters_invalid")
    if scenes[0].get("template") != "glass_pair_question":
        errors.append("opening_invalid")
    if scenes[-1].get("template") != "vote_comment" or scenes[-2].get("template") != "house_rule_search":
        errors.append("ending_invalid")
    screen = [episode.get(key) for key in ("series", "episode", "topic", "chapters")]
    for scene in scenes:
        template = scene.get("template")
        if not isinstance(template, str) or template not in SLOTS:
            errors.append("template_unknown")
            continue
        beats = scene.get("beats")
        if not isinstance(beats, list) or not beats:
            errors.append("beats_invalid")
            beats = []
        for index, beat in enumerate(beats):
            if (not isinstance(beat, dict) or not _text(beat.get("text"))
                    or not isinstance(beat.get("claim_ids"), list)
                    or any(not _text(identifier) for identifier in beat["claim_ids"])):
                errors.append("beats_invalid")
                continue
            lines = beat["text"].split("\n")
            if len(lines) > config.JJERI_SUBTITLE_LINES or any(len(line) > config.JJERI_SUBTITLE_CHARS and not (
                    replay and template == "two_methods" and index == 0 and line == REPLAY_SUBTITLE)
                    for line in lines):
                errors.append("subtitle_overflow")
            screen.append(beat["text"])
        slots = scene.get("slots")
        errors.extend(_shape(SLOTS[template], slots, len(beats)))
        if isinstance(slots, dict):
            if template == "house_rule_search":
                if slots.get("show_prices") is not False:
                    errors.append("price_forbidden")
                label = slots.get("label")
                if isinstance(label, dict) and not _shape(SLOTS[template]["label"], label, len(beats)):
                    if max(label["circle_lines"]) >= len(label["lines"]):
                        errors.append("slot_reference_invalid")
            if template == "recap_board" and slots.get("exception_chip") and "exception_on_beat" not in slots:
                errors.append("beat_reference_invalid")
        if scene.get("tag") is not None:
            errors.extend(_shape({"text": TEXT, "tone": TONES}, scene["tag"], len(beats)))
        if scene.get("source_chip") is not None and not _text(scene["source_chip"]):
            errors.append("source_invalid")
        screen.extend([slots, scene.get("tag"), scene.get("source_chip")])
    errors.extend(issue for text in _strings(screen) if (issue := price_issue(text)))
    return list(dict.fromkeys(errors))
