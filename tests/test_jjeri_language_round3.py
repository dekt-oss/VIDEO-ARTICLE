from copy import deepcopy
import json

import pytest

from engine.motion.jjeri_class.directive import generate_episode
from engine.motion.jjeri_class.evidence import EvidenceError
from test_jjeri_evidence import mock_episode
from test_jjeri_language import audit


# Exact suffix and continuation pairs used by the round-three review.
TAILS = [
    ("", "."), ("에", " 팔아요."), ("에도", " 팔아요."), ("에는", " 못 사요."), ("엔", " 못 사요."), ("으로", " 올랐어요."),
    ("으로도", " 충분해요."), ("이면", " 돼요."), ("이라", " 비싸요."), ("이라서", " 비싸요."), ("이라면", " 살래요."),
    ("이라는", " 말이 있어요."), ("이라도", " 사요."), ("이나", " 해요."), ("이고", " 흔해요."), ("이며", " 흔해요."),
    ("이지만", " 좋아요."), ("인데", " 좋아요."), ("인데요", "."), ("인데도", " 좋아요."), ("이었어요", "."),
    ("이었는데", " 올랐어요."), ("이었지만", " 올랐어요."), ("이었고", " 지금은 달라요."), ("이에요", "."), ("이죠", "."),
    ("이지요", "."), ("이거든요", "."), ("이니까", " 비싸요."), ("이잖아요", "."), ("일까요", "?"), ("인가요", "?"),
    ("인지", " 봐요."), ("일 때", " 좋아요."), ("이네", "."), ("이네요", "."), ("이군요", "."), ("이구나", "."),
    ("입니다", "."), ("입니다만", " 좋아요."), ("이랍니다", "."), ("이래요", "."), ("이라고요", "."), ("이고요", "."),
    ("이요", "."), ("까지", " 올라요."), ("까지만", " 봐요."), ("부터", " 시작해요."), ("부터는", " 달라요."),
    ("만큼", " 값져요."), ("뿐이에요", "."), ("조차", " 아까워요."), ("씩", " 올라요."), ("씩이나", " 올라요."),
    ("쯤", " 해요."), ("쯤은", " 해요."), ("정도", " 해요."), ("가량", " 해요."), ("대", "예요."), ("대의", " 술이에요."),
    ("짜리", "예요."), ("짜리를", " 골라요."), ("보다", " 싸요."), ("보다도", " 싸요."), ("처럼", " 보여요."),
    ("밖에", " 안 해요."), ("도", " 안 해요."), ("만", " 내요."), ("은", " 넘어요."), ("이", " 넘어요."), ("을", " 넘어요."),
    ("의", " 값을 해요."), ("과", " 비교해요."), ("이랑", " 비교해요."), ("이든", " 좋아요."), ("이야", "."),
]
PRICE_ONLY = [("어치", " 사요."), ("선", "이에요."), ("꼴", "이에요."), ("미만", "이에요."), ("남짓", "이에요."), ("하는", " 술이에요."),
              ("이 안 돼요", "."), ("을 넘겨요", ".")]
NUM_ONLY = [("만에", " 익어요."), ("차", "예요."), ("여", " 동안 익어요."), ("넘게", " 익어요."), ("남짓", " 익어요."),
            ("치", "예요."), ("묵은", " 술이에요."), ("이나 된", " 술이에요."), ("가까이", " 익어요."), ("내내", " 익어요.")]
@pytest.mark.parametrize("amount", ["3만 원", "삼만 원", "30달러", "30유로", "30 KRW"])
@pytest.mark.parametrize("tail,rest", TAILS + PRICE_ONLY + [("이겠습니다만", "."), ("하더라고요", ".")])
def test_currency_token_does_not_depend_on_tail(amount, tail, rest):
    with pytest.raises(EvidenceError, match="price_forbidden"):
        audit(amount + tail + rest, amount, surface="slot")


@pytest.mark.parametrize("amount,quote", [
    ("삼십 년", "30 years."), ("두 배", "Two times."), ("세 달", "Three months."),
    ("오십 퍼센트", "50 percent."), ("도수는 사십 도", "40% ABV."),
    ("삼십 년산", "30 years."), ("오십 프로", "50 percent."), ("세 개월", "Three months."),
])
@pytest.mark.parametrize("tail,rest", TAILS + NUM_ONLY + [("인들", " 달라요."), ("은커녕", " 짧아요.")])
def test_measure_token_requires_matching_evidence_regardless_of_tail(amount, quote, tail, rest):
    text = amount + tail + rest
    wrong = "12 years. 46% ABV. 20 percent. Six months. Four times."
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit(text, wrong, surface="slot")
    audit(text, quote, surface="slot")


@pytest.mark.parametrize("text,quote", [
    ("두 배거든요.", "Two times."), ("두 배잖아요.", "Two times."),
    ("두 배라는 말이 있어요.", "Two times."), ("두 배였는데 달라요.", "Two times."),
    ("두 배니까 비싸요.", "Two times."), ("두 배고요.", "Two times."),
    ("두 배라면 좋아요.", "Two times."), ("도수는 사십 도거든요.", "40% ABV."),
    ("도수는 사십 도니까 세요.", "40% ABV."), ("오십 프로거든요.", "50 percent."),
    ("오십 퍼센트니까 많아요.", "50 percent."), ("3개월이라서 달라요.", "Three months; 3 months."),
])
def test_natural_vowel_final_quantities(text, quote):
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit(text, "Four times. 46% ABV. 20 percent. Six months.", surface="slot")
    audit(text, quote, surface="slot")


@pytest.mark.parametrize("text,wrong,right", [
    ("도수는 사십 도지만 순해요.", "Bottled at 46% ABV.", "Bottled at 40% ABV."),
    ("도수가 사십 도면 세요.", "Bottled at 46% ABV.", "Bottled at 40% ABV."),
    ("도수는 사십 도지요.", "Bottled at 46% ABV.", "Bottled at 40% ABV."),
    ("도수는 사십 도구나.", "Bottled at 46% ABV.", "Bottled at 40% ABV."),
    ("도수는 사십 도기에 세요.", "Bottled at 46% ABV.", "Bottled at 40% ABV."),
    ("사십 도지만 순해요.", "It was 46 degrees.", "It was 40 degrees."),
    ("사십 도면 충분해요.", "It was 46 degrees.", "It was 40 degrees."),
])
def test_degree_endings_that_overlap_ordinary_words_still_require_a_matching_quote(text, wrong, right):
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit(text, wrong)
    audit(text, right)


@pytest.mark.parametrize("text", [
    "이 도로 끝에 있어요.", "한 도로 위 증류소", "이 도수가 높아요.",
    "도수는 병에 나와요.", "이 도면을 비교해요.", "이 도구나 통을 써요.", "이 도기에 담아요.",
])
def test_degree_endings_do_not_turn_ordinary_nouns_into_quantities(text):
    audit(text)


@pytest.mark.parametrize("text", [
    "삼만 원인데요.", "삼만 원이거든요.", "삼만 원일까요?", "만 원이잖아요.",
    "오만 원이라는 말이 있어요.", "30달러라면 사요.", "30달러거든요.", "100엔이거든요.",
])
def test_currency_variants_in_actual_subtitles(text):
    with pytest.raises(EvidenceError, match="price_forbidden"):
        audit(text, text)


@pytest.mark.parametrize("text", [
    "피로회복에 좋아요.", "건강증진에 좋아요.", "숙취예방에 좋아요.", "노화방지에 좋아요.",
    "면역강화에 좋아요.", "암예방 효과가 있어요.", "혈압강하 효과가 있어요.", "혈당조절에 좋아요.",
    "건강관리에 좋아요.", "면역력증진에 좋아요.", "마시면 건강해져요.", "건강을 지켜 줘요.",
    "건강을 챙겨요.", "몸이 가벼워져요.", "젊어져요.", "오래 살아요.", "숙취해소에 좋아요.",
    "건강식이에요.", "몸보신에 좋아요.", "기력 회복에 좋아요.", "항산화효과를 높여요.", "암예방",
])
def test_health_compounds_do_not_pass_with_verified_quote(text):
    with pytest.raises(EvidenceError, match="health_claim_forbidden"):
        audit(text, text)


@pytest.mark.parametrize("text", [
    "이 불로 통을 태워요.", "이 불에 통을 그을려요.", "이 불이 통을 태워요.", "이 불을 써요.",
    "이 원에서 시작해요.", "한 병에 이 모든 향이 담겨요.", "한 병에 이 향이 다 있어요.",
    "가격은 이 통이 정해요.", "가격은 이 희소성에서 와요.", "값은 이 정도 차이가 나요.",
    "가격이 일 순위는 아니에요.", "한 병 사 왔어요.", "한 도로 위 증류소", "이 도로 끝에 있어요.",
    "이 배로 실어 날라요.", "이 프로는 유명해요.", "이 달은 바빠요.", "위에 뚜껑이 있어요.",
    "장에 가면 있어요.", "눈에 띄는 색이 좋아요.", "위에서 눌러 좋아져요.", "몸통을 줄여요.",
    "통 속 온도가 높아요.", "같이 비교해 봐요.", "라벨을 확인해 보세요.", "댓글로 투표해 주세요.",
    "이 원두에서 향이 나요.", "삼십 도수계 눈금", "이 암벽 아래 증류소", "만 원료를 쓰는 건 아니에요.",
    "40%의 알코올", "암호 관리 효과를 비교해요.", "건강관리실이 있어요.", "한 배치만 만들어요.",
    "두 배치로 나눠 생산해요.",
])
def test_demonstratives_and_ordinary_compounds_are_not_claims_of_price_or_efficacy(text):
    _, qa = audit(text, f"{text} One bottle. 40% ABV.", surface="slot", kind="product_fact")
    assert qa["human_source_review_required"]


@pytest.mark.parametrize("text", ["3만 5천 리터더라고요.", "병당 30도거든요.", "3만 5천 통이라는 말이에요."])
def test_explicit_non_currency_units_keep_their_role_after_unlisted_tails(text):
    audit(text, text, surface="slot")


@pytest.mark.parametrize("text,code,guide", [
    ("이 년도 넘었어요.", "number_ambiguous", "2년"),
    ("이 배일까요?", "number_ambiguous", "2년"),
    ("이 원쯤이에요.", "price_ambiguous", "금액"),
    ("이 원쯤이에요. 이 원형이에요.", "price_ambiguous", "금액"),
    ("병당 이.", "price_ambiguous", "금액"),
])
def test_ambiguous_live_text_has_a_rewrite_instruction(text, code, guide):
    with pytest.raises(EvidenceError, match=code) as error:
        audit(text, text, surface="slot")
    assert guide in str(error.value)


def test_mock_provider_receives_ambiguous_text_rewrite_instruction():
    good, evidence = mock_episode()
    bad = deepcopy(good)
    bad["scenes"][0]["beats"][0]["text"] = "병당 이."
    corrections = []

    def respond(_, request):
        corrections.append(request.get("correction"))
        return json.dumps(bad if len(corrections) == 1 else good)

    assert generate_episode(evidence, topic=good["topic"], lesson=good["episode"], respond=respond) == good
    assert corrections[0] is None
    assert corrections[1]["code"] == "price_ambiguous"
    assert "금액은 빼고" in corrections[1]["instruction"]
