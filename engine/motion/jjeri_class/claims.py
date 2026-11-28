"""Conservative checks for quantities and sensitive language in Jjeri captions."""

import re
import unicodedata
from decimal import Decimal

from engine import drinks_script_check as shared
from .language import EN_CARDINAL, EN_LARGE_PREFIX, MEASURE_CORE, english_number, noun_boundary

_DIGITS = dict(zip("영일이삼사오육칠팔구", range(10)))
_DIGITS["공"] = 0
_NATIVE = dict(zip(("한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열"), range(1, 11)))
_PLACE = {"십": 10, "백": 100, "천": 1000, "만": 10000, "억": 100000000}
_KO_NUM = r"(?:다섯|여섯|일곱|여덟|아홉|[한두세네열]|[영공일이삼사오육칠팔구십백천만억]+)"
_DEGREE_COLLISION_END = r"(?:지만|면|지요|구나|기에)(?!\w)"
_KO_MEASURE = rf"(?P<gap>\s*)(?P<unit>{MEASURE_CORE}|도(?={_DEGREE_COLLISION_END}))"
_KO_PAIRS = re.compile(rf"(?<![가-힣\d])(?P<number>{_KO_NUM}){_KO_MEASURE}")
_ARABIC = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_KO_ARABIC = re.compile(rf"(?<![\d.,])(?P<number>{_ARABIC}){_KO_MEASURE}")
_EN_PAIRS = re.compile(
    rf"(?<![\w.,-])(?P<number>{_ARABIC}|{EN_CARDINAL})\s*[-–]?\s*"
    r"(?P<unit>years?\b|yrs?\b|months?\b|times?\b|[x×](?!\w)|degrees?\b|°|\bpercent\b|%)", re.I
)
_DEGREE_CONTEXT = re.compile(r"(?P<abv>도수|알코올|알콜|\bABV\b)|(?P<degree>온도|섭씨|화씨)", re.I)
_ROAD_CONTEXT = re.compile(r"로\s*(?:끝|위|아래|옆|건너|변|입구|가운데|따라)")
_BATCH_CONTEXT = re.compile(r"치(?:만|로|를|가|는|에|에서)?\s*(?:제조|생산|만들|혼합|나눠|작업|발효)")
_DEMONSTRATIVE_CONTEXT = {
    "달": re.compile(r"(?:에|은|에는)\s*(?:나왔|출시|공개|열렸|바쁘|바빠|일정|행사)"),
    "배": re.compile(r"(?:가\s*(?:달아|달콤|맛있)|(?:로|를|에)\s*(?:실어|운반|나르|날라|항해|운항|타고|떠나))"),
    "프로": re.compile(r"(?:는|가|를|에)\s*(?:유명|방영|방송|본방|봤|봐|시청)"),
}
_PARTICLE_END = noun_boundary(copula=False)
_HEALTH_TARGET = (
    r"(?:암|질병|당뇨|혈압|면역(?:력)?|건강|혈당|숙취|몸|피로|감기|혈액\s*순환|치매|"
    r"심장병|소화|스트레스|피부|다이어트(?!\s*콜라)|콜레스테롤|통증|노화|염증|해독|숙면|"
    r"기억력|약효|우울함|수명|칼로리|심장|혈관|관절|뼈)"
)
_EFFICACY = (
    r"(?:치료|예방|완치|효과|개선|낮[아춰추]|높[여이]|강화|좋|이롭|이로워|낫게|낫는|"
    r"없[애어는습]|해소|풀[려어]|막아|줄[여이]|도움|돕|도와|늦[춰추]|덜해|적어|날려|키워|"
    r"늘려|따뜻해|지켜|챙겨|가벼워)"
)
_HEALTH_EFFECT_COMPOUND = (
    r"(?:건강\s*(?:증진|관리|회복)|(?:숙취|암|질병|당뇨)\s*(?:예방|해소|치료)|"
    r"면역(?:력)?\s*(?:강화|증진)|혈압\s*(?:강하|조절)|혈당\s*조절|노화\s*방지|"
    r"(?:피로|기력)\s*회복|항산화\s*효과|몸\s*보신)"
)
_HEALTH = re.compile(
    rf"(?<![가-힣])(?:{_HEALTH_TARGET}{_PARTICLE_END}|간(?=에|을|이|의){_PARTICLE_END}|간\s*기능)"
    rf"[^.!?]{{0,20}}{_EFFICACY}"
    rf"|(?<![가-힣]){_HEALTH_EFFECT_COMPOUND}{_PARTICLE_END}[^.!?]{{0,20}}{_EFFICACY}"
    # These organ names also have a common spatial or everyday meaning.
    rf"|(?<![가-힣])(?:위|장|눈)(?:에(?:도|는)?|엔|을|이)(?![가-힣])\s*(?:(?:참|정말|아주|매우)\s+)?{_EFFICACY}"
    r"|(?<![가-힣])(?:잠(?:이|도|은)?\s*잘\s*와|살(?:이|도|은)?\s*(?:빠져|안\s*쪄)|"
    r"항산화\s*(?:성분|효과)|장수의\s*비결|약(?:으로\s*(?:쓰|사용)|이\s*돼)|"
    r"건강(?:한\s*술|주|식(?:이|예|입))|숙취\s*해소|원기\s*회복|보약(?:이|예|입)|"
    r"약효가?\s*있|마시면\s*건강해|기운이\s*나|머리가\s*안\s*아파|병을\s*낫게)"
    r"|^(?:젊어져요|오래\s*살아요)[.!?…]*$"
    r"|^(?:(?:암|숙취|질병)\s*예방|혈압\s*강하|혈당\s*조절|면역(?:력)?\s*강화)[.!?…]*$"
    r"|\b(?:cures?|treats?|prevents?)\s+(?:cancer|diabetes|disease)\b"
    r"|\b(?:boosts?\s+immunity|lowers?\s+blood pressure)\b", re.I
)
_DRINK_ADVICE = re.compile(
    r"(?:매일|매주|날마다|꼭|반드시|권장|추천).{0,14}(?:마시|마셔|드세|드시|먹으)"
    r"|(?:마시|마셔|드세|드시).{0,12}(?:좋아요|좋습니다|권장|추천|세요|보세요)"
    r"|(?<!에서 )(?:마셔요|드시죠|드셔요)[.!?…]*$"
    r"|(?:즐기세요|즐겨요|권해요|권합니다|맛보세요)[.!?…]*$"
    r"|(?:추천|강추|권장)(?:하|해|합|드리|드려|할|이(?:에요|죠))"
    r"|(?<![가-힣])(?:사|구매하|장만하)세요"
    r"|(?:마셔|드셔|사|구매해)야\s*해|(?:사|구매해)\s*두면\s*좋"
    r"|(?:입문용|선물)(?:용)?(?:으로|로|하기)\s*(?:좋|딱)"
    r"|(?:스트레이트|니트|온더록|하이볼)(?:가|이|는)\s*정답"
    r"|안\s*(?:마시|드시)면\s*손해"
    r"|(?:초보|입문자)(?:라면|는).{0,20}(?:부터\s*시작해요|고르면\s*돼요)[.!?…]*$"
    r"|(?:마셔도|드셔도|드려도)\s*돼요[.!?…]*$"
    r"|\b(?:drink it daily|you should drink|drink every day)\b", re.I
)


def _unit_key(unit):
    if unit in {"개월", "달"} or unit.startswith("month"):
        return "month"
    if unit.startswith(("년", "yr", "year")):
        return "year"
    if unit in {"배", "x", "×"} or unit.startswith("time"):
        return "multiple"
    if unit in {"도", "°"} or unit.startswith("degree"):
        return "degree"
    return "percent"


def _number(value):
    if value[0].isdecimal():
        return Decimal(value.replace(",", ""))
    if value in _NATIVE:
        return Decimal(_NATIVE[value])
    if value.isascii():
        return Decimal(english_number(value))
    if all(ch in _DIGITS for ch in value):
        return Decimal("".join(str(_DIGITS[ch]) for ch in value))
    total = section = digit = 0
    for ch in value:
        if ch in _DIGITS:
            digit = _DIGITS[ch]
            continue
        size = _PLACE[ch]
        if size >= 10000:
            total += (section + digit or 1) * size
            section = 0
        else:
            section += (digit or 1) * size
        digit = 0
    return Decimal(total + section + digit)


def _degree_key(prefix, suffix, stated):
    context = list(_DEGREE_CONTEXT.finditer(prefix))
    if context:
        return context[-1].lastgroup
    if stated and suffix.startswith("짜리"):
        return "degree_or_abv"
    return "degree"


def _measure_key(match, prefix, suffix, stated):
    number, unit, gap = match["number"], match["unit"], match["gap"]
    if gap and number in {"이", "한"} and unit == "도" and _ROAD_CONTEXT.match(suffix):
        return None
    # 도구/도기 and similar nouns can also begin with these endings in speech.
    if (unit == "도" and re.match(_DEGREE_COLLISION_END, suffix)
            and (number in _NATIVE or number in _DIGITS) and not _DEGREE_CONTEXT.search(prefix)):
        return None
    # 배치 (batch) and 배+치 (folds' worth) share a spelling.
    if unit == "배" and _BATCH_CONTEXT.match(suffix):
        return None
    if gap and number == "이":
        ordinary = _DEMONSTRATIVE_CONTEXT.get(unit)
        if ordinary:
            if ordinary.match(suffix):
                return None
            return "ambiguous" if stated else None
        if unit == "도" and not _DEGREE_CONTEXT.search(prefix):
            return "ambiguous" if stated else None
        if unit == "년" and suffix.startswith("도"):
            if re.match(r"도(?:에|는|의|부터)\b", suffix):
                return None
            return "ambiguous" if stated else None
    return _degree_key(prefix, suffix, stated) if unit == "도" else _unit_key(unit)


def _pairs(sentence, patterns, *, stated=False):
    for pattern in patterns:
        for match in pattern.finditer(sentence):
            number, unit = match.group("number", "unit")
            prefix = sentence[:match.start()]
            suffix = sentence[match.end():]
            if pattern is _EN_PAIRS and EN_LARGE_PREFIX.search(prefix):
                # Leave unparsed multiword magnitudes to review instead of accepting their tail as a value.
                continue
            key = _unit_key(unit.casefold()) if pattern is _EN_PAIRS else _measure_key(match, prefix, suffix, stated)
            if key is None:
                continue
            value = _number(number)
            if key == "percent" and re.match(r"\s*(?:ABV|alc\b|alcohol\b)", suffix, re.I):
                yield value, "abv"
            yield value, key


def _quote_pairs(quotes):
    pairs = set()
    for quote in quotes:
        normalized = unicodedata.normalize("NFKC", quote)
        for sentence in shared._SENT_SPLIT.split(normalized):
            pairs.update(_pairs(sentence, (_KO_PAIRS, _KO_ARABIC, _EN_PAIRS)))
        if re.search(r"\btwice\b", quote, re.I):
            pairs.add((Decimal(2), "multiple"))
    return pairs


def _literal(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).strip(" .!?…")


def has_health_claim(text):
    normalized = unicodedata.normalize("NFKC", " ".join(text.split()))
    return any(_HEALTH.search(sentence) for sentence in shared._SENT_SPLIT.split(normalized))


def sensitive_text_block(text, checked_claims):
    normalized = unicodedata.normalize("NFKC", " ".join(text.split()))
    sentences = shared._SENT_SPLIT.split(normalized)
    if any(_HEALTH.search(sentence) for sentence in sentences):
        return "health_claim_forbidden"
    stated = {(value, unit) for sentence in sentences for value, unit in _pairs(sentence, (_KO_PAIRS,), stated=True)}
    if any(unit == "ambiguous" for _, unit in stated):
        return "number_ambiguous"
    if stated:
        quoted = _quote_pairs(ref["original_quote"] for claim in checked_claims for ref in claim["source_refs"])
        for value, unit in stated:
            accepted = {"degree", "abv"} if unit == "degree_or_abv" else {unit}
            if not any((value, candidate) in quoted for candidate in accepted):
                return "number_unsupported"
    for sentence in sentences:
        if shared._ADVICE.search(sentence) or _DRINK_ADVICE.search(sentence):
            # Every advice sentence must be present in the approved recommendation's own matched quote.
            if not any(claim["kind"] in shared.ADVICE_KINDS and any(
                _literal(sentence) == _literal(quoted_sentence)
                for ref in claim["source_refs"]
                for quoted_sentence in shared._SENT_SPLIT.split(ref["original_quote"])
            ) for claim in checked_claims):
                return "advice_unsupported"
    return None
