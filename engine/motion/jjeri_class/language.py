"""Lexical boundaries shared by the Jjeri rules for amounts and units."""
import re

# Build endings from grammatical parts. A particle may take a focus marker;
# bound quantity modifiers may take either a particle or a copula.
_FOCUS = r"(?:은|는|도|만|까지|조차|마저)"
_CASE = r"(?:으로|로|에서|에|에게|한테|께|부터|보다|밖에|의|처럼|대로|당)"
_PARTICLE = rf"(?:{_CASE}{_FOCUS}?|{_FOCUS}|엔|을|를|이|가|과|와|이?나|이?랑)"
_COPULA = (
    r"(?:이?(?:다|죠|라고|라서|라|면|고|지만|며|네요|래요|란|라니|는데|든지|든|기에)"
    r"|이었(?:어요|습니다|죠|다)?|였(?:어요|습니다|죠|다)?"
    r"|이에요|이예요|예요|에요|이야|야|입(?:니다|니까)|인(?:데)?|일|임)"
)
QUANTITY_MODIFIER = r"(?:대|째|짜리|간|씩|쯤|가량|정도|안팎|이상|이하|동안|된)"


def noun_boundary(modifier="", *, copula=True):
    """Match the end of a noun plus productive tails, never another word's prefix."""
    modifier = rf"(?:{modifier})?" if modifier else ""
    ending = rf"(?:{_PARTICLE}|{_COPULA})" if copula else _PARTICLE
    return rf"(?={modifier}{ending}?(?!\w))"


def unit_core(units):
    """Recognize the unit before its inflection, excluding known lexical compounds."""
    choices = []
    for token in sorted(units, key=len, reverse=True):
        compounds = units[token].split()
        guard = "(?!" + "|".join(map(re.escape, compounds)) + ")" if compounds else ""
        choices.append(re.escape(token) + guard)
    return "(?:" + "|".join(choices) + ")"


MEASURE_CORE = unit_core({
    "개월": "", "달": "러 콤 걀 력 빛 팽이 리기",
    "년산": "", "년숙성": "", "년": "",
    "도": "수 구 움 시 전 장 서 자 기 약 참 감 산 지 면 복 색 료",
    "배": "럴 합 경 터리 우 추 송 등 양",
    "퍼센트": "", "프로": "그램 세스 필 젝트 듀서 토콜 그래밍",
    "%": "",
})


_EN_SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
             "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_EN_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_EN_VALUES = dict(zip(_EN_SMALL, range(20))) | dict(zip(_EN_TENS, range(20, 100, 10)))
_EN_ONES = "|".join(_EN_SMALL[1:10])
_EN_SUB_HUNDRED = rf"(?:{'|'.join(_EN_TENS)})(?:[ -](?:{_EN_ONES}))?|{'|'.join(_EN_SMALL)}"
EN_CARDINAL = rf"(?:(?:{_EN_ONES})\s+hundred(?:[ -]+(?:and\s+)?(?:{_EN_SUB_HUNDRED}))?|{_EN_SUB_HUNDRED})"
EN_LARGE_PREFIX = re.compile(r"\b(?:hundred|thousand|million|billion)(?:[\s-]+and)?[\s-]*$", re.I)


def english_number(text):
    """Convert a match from EN_CARDINAL."""
    words = text.casefold().replace("-", " ").split()
    if "hundred" in words:
        return _EN_VALUES[words[0]] * 100 + sum(_EN_VALUES[word] for word in words[2:] if word != "and")
    return sum(_EN_VALUES[word] for word in words)
