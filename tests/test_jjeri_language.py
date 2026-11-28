import pytest

from engine.motion.jjeri_class.evidence import EvidenceError, audit_episode
from test_jjeri_evidence import mock_episode


def audit(text, quote=None, *, surface="beat", kind=None):
    episode, evidence = mock_episode()
    scene = episode["scenes"][0]
    claim = evidence["claims"][0]
    if quote is not None:
        claim["source_refs"][0]["original_quote"] = quote
    if kind:
        claim["kind"] = kind
    if surface == "beat":
        scene["beats"][0]["text"] = text
    elif surface == "slot":
        scene["slots"]["left"]["label"] = text
    elif surface == "chapter":
        episode["chapters"][0]["title"] = text
    elif surface == "topic":
        episode["topic"] = text
    elif surface == "tag":
        scene["tag"] = {"text": text, "tone": "yellow"}
        episode["text_claim_ids"]["scenes.0.tag.text"] = ["c1"]
    elif surface == "caption":
        episode["caption_draft"] = text
    else:
        source = evidence["sources"][0]
        if surface == "title":
            del source["publisher"]
        source[surface] = text
    return audit_episode(episode, evidence)


@pytest.mark.parametrize("text", [
    "3만 원에 팔아요.", "3만 원에 살 수 있어요.", "만 원이면 사요.", "5만 원쯤 해요.",
    "3만 원이라 비싸요.", "3만 원이었어요.", "3만 원인데 좋아요.", "3만 원이고 흔해요.",
    "3만 원이나 해요.", "3만 원보다 싸요.", "3만 원가량이에요.", "3만 원정도예요.",
    "3만 원이네요.", "3만 원임.", "3만 원에요.", "3만 원이 넘어요.", "3만 원 넘어요.",
    "3만 원!", "3만원짜리예요.", "30달러에 팔려요.", "30달러면 사요.", "30달러쯤 해요.",
    "삼만 원에 팔아요.", "오만 원이면 사요.", "삼만 원이라 비싸요.", "30,000원에 사요.",
    "30000원이면 돼요.", "3만 원\n에 팔아요.", "병당 3만이에요.", "한 병 3만이에요.",
    "3만이면 사요.", "3만에 팔아요.", "3만대예요.", "3만 안팎이에요.", "한 병 39,900이에요.",
    "39,900에 사요.", "가격이 39,900이에요.", "값이 3만이에요.", "값 3만.",
    "가격대는 3만이에요.", "12만 넘어요.", "3만 5천쯤 해요.", "삼만 오천쯤 해요.",
    "한 병에 삼만이에요.", "한 병에 3만 정도예요.", "thirty dollars", "30 KRW예요",
    "₩30", "30원", "100엔이에요.",
])
def test_money_cannot_be_licensed_by_a_quote(text):
    with pytest.raises(EvidenceError, match="price_forbidden"):
        audit(text, text)


@pytest.mark.parametrize("surface", ["topic", "chapter", "beat", "slot", "tag", "publisher", "title"])
def test_money_inflection_blocked_on_every_screen_surface(surface):
    code = "source_label_invalid" if surface in {"publisher", "title"} else "price_forbidden"
    with pytest.raises(EvidenceError, match=code):
        audit("3만 원에 파는 가게", "3만 원에 파는 가게", surface=surface)


@pytest.mark.parametrize("amount", ["삼십 원", "30불", "30달러", "30유로", "30엔", "30 KRW"])
@pytest.mark.parametrize("ending", ["에", "에도", "이면", "이나", "보다", "이었어요", "짜리예요"])
def test_currency_particle_and_copula_combinations(amount, ending):
    with pytest.raises(EvidenceError, match="price_forbidden"):
        audit(amount + ending, amount)


@pytest.mark.parametrize("text", [
    "이 원주를 통에 담아요.", "이 원두 향이 나요.", "구 원조 증류소", "만 원숙한 맛",
    "원은 둥글어요.", "이 원은 통 모양이에요.", "오 원더풀", "천 원주",
    "두 원액을 섞어요.", "이 불은 통을 태워요.", "값진 통이에요.",
    "가격은 다음 시간에 봐요.", "만 가지 향이 나요.",
])
def test_ordinary_words_are_not_currency(text):
    audit(text, text)


@pytest.mark.parametrize("text", ["3만 5천 병이에요.", "3만 5천 리터", "30불꽃", "30엔진", "30유로파"])
def test_number_followed_by_a_unit_or_non_currency_noun(text):
    audit(text, text)


def test_per_bottle_words_without_an_amount_keep_the_quantity_contract():
    audit("한 병에 다 담아요.", "Pour it all into one bottle.")


@pytest.mark.parametrize("text", [
    "두 배로 늘어요.", "세 배로 커져요.", "두 배나 비싸요.", "두 배다.", "두 배죠.", "두 배라고 해요.",
    "두 배쯤 돼요.", "삼십 년된 술이에요.", "삼십 년 된 술이에요.", "삼십 년이라 귀해요.",
    "삼십 년인데 싸요.", "삼십 년이고 귀해요.", "삼십 년째 익어요.", "삼십 년보다 길어요.",
    "삼십 년이면 충분해요.", "삼십 년이 넘어요.", "삼십 년간 익어요.", "삼십 년이었어요.",
    "삼십 년이네요.", "삼십 년이래요.", "삼십 년산이라 귀해요.", "삼십 년산인데 싸요.",
    "사십 도로 병입해요.", "사십 도이고 순해요.", "도수는 사십 도라 세요.", "세 달이면 돼요.",
    "세 달째 익어요.", "오십 퍼센트나 날아가요.", "오십 퍼센트로 줄어요.",
    "오십 프로나 돼요.", "삼십 년,", "삼십 년!", "(삼십 년)", "삼십년숙성이에요.", "십이 년\n된 술이에요.",
])
def test_inflected_hangul_quantities_still_need_matching_evidence(text):
    quote = "Aged for 11 years. Bottled at 46% ABV. It lost 20 percent. It took 6 months. Four times bigger."
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit(text, quote)


@pytest.mark.parametrize("amount,quote", [
    ("두 배", "Two times."), ("삼십 년", "Thirty years."), ("세 달", "Three months."),
    ("세 개월", "Three months."), ("사십 도", "40 degrees."), ("오십 퍼센트", "50 percent."),
    ("오십 프로", "50 percent."), ("오십%", "50 percent."),
])
@pytest.mark.parametrize("ending", ["로", "나", "보다", "이면", "이라", "이네요", "이었어요", "째"])
def test_measure_particle_combinations_require_the_right_value_and_unit(amount, quote, ending):
    text = amount + ending
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit(text, "100 bottles.")
    audit(text, quote)


@pytest.mark.parametrize("text,quote", [
    ("두 배로 늘어요.", "Two times."), ("삼십 년된 술이에요.", "Thirty years."),
    ("삼십 년이라 귀해요.", "Thirty years."), ("사십 도로 병입해요.", "40 degrees."),
    ("세 달이면 돼요.", "Three months."), ("오십 퍼센트나 날아가요.", "50 percent."),
    ("이십일 년 숙성", "Twenty-one years."), ("백 년 넘은 증류소", "One hundred years."),
    ("백삼 년 숙성", "One hundred and three years."),
])
def test_inflected_quantities_accept_matching_evidence(text, quote):
    audit(text, quote)


@pytest.mark.parametrize("text", [
    "건강에도 좋아요.", "건강엔 좋아요.", "건강에는 정말 좋아요.", "혈압에도 좋아요.",
    "면역력에도 좋아요.", "혈당에도 좋아요.", "건강까지 좋아져요.", "숙취까지 없애 줘요.",
    "암까지 예방해요.", "당뇨에도 효과가 있어요.", "혈압까지 낮춰요.", "건강과 미용에 좋아요.",
    "숙취해소에 좋아요.", "건강에 좋은 술이에요.", "몸에 좋은 술이에요.", "건강에 좋다고 해요.",
    "몸에 좋대요.", "건강에 좋습니다.", "건강에 좋죠.", "몸에 좋죠.", "위에 좋아요.",
    "장에 좋아요.", "눈에 좋아요.", "뼈에 좋아요.", "심장에 좋아요.", "혈관에 좋아요.",
    "관절에 좋아요.", "기억력이 좋아져요.", "노화를 늦춰요.", "염증을 줄여요.", "해독에 좋아요.",
    "숙면에 도움이 돼요.", "보약이에요.", "약효가 있어요.", "원기 회복에 좋아요.", "기운이 나요.",
    "몸이 따뜻해져요.", "혈당 걱정이 없어요.", "칼로리가 낮아요.", "살 안 쪄요.", "숙취 없는 술이에요.",
    "머리가 안 아파요.", "우울함을 날려요.", "수명을 늘려요.", "병을 낫게 해요.", "면역을 키워요.",
    "면역력을 키워요.", "건강주예요.", "몸에도 좋죠.", "숙취가 덜해요.", "살도 빠져요.", "잠도 잘 와요.",
    "간에도 좋아요.", "건강에 참 좋아요.", "숙취가 적어요.", "피로 회복에 좋아요.",
    "피로를 풀어 줘요.", "암 예방에 좋아요.", "암도 예방해요.", "살이 안 쪄요.",
    "약이 돼요.", "건강에 이로워요.", "몸에 이로워요.",
])
def test_health_inflections_and_claims_block_even_with_verified_quote(text):
    with pytest.raises(EvidenceError, match="health_claim_forbidden"):
        audit(text, text)


@pytest.mark.parametrize("surface", ["publisher", "title"])
def test_health_phrase_in_source_display_name_does_not_pass(surface):
    with pytest.raises(EvidenceError, match="source_label_invalid"):
        audit("몸에 좋은 술 연구소", surface=surface)


@pytest.mark.parametrize("text", [
    "강추해요.", "한 병 사세요.", "구매하세요.", "꼭 드셔 보세요.", "마셔야 해요.", "놓치지 마세요.",
    "추천드려요.", "권장해요.", "추천하는 술이에요.", "이걸 추천해요, 정말.", "사 두면 좋아요.",
    "하나 장만하세요.", "입문용으로 좋아요.", "선물용으로 좋아요.", "선물하기 좋아요.",
    "스트레이트가 정답이에요.", "하이볼로 즐겨요.", "얼음과 함께 즐겨 보세요.", "안 마시면 손해예요.",
    "이건 사야 해.", "꼭 맛보세요.", "드셔 보시길 권해요.",
])
def test_new_drinking_and_purchase_advice_requires_direct_recommendation(text):
    with pytest.raises(EvidenceError, match="advice_unsupported"):
        audit(text)
    with pytest.raises(EvidenceError, match="advice_unsupported"):
        audit(text, text, kind="product_fact")
    audit(text, f"{text} Use one bottle.", kind="recommendation")


@pytest.mark.parametrize("text", [
    "시간에 따라 좋아져요.", "순간에 향이 풀려요.", "몸통이 굵은 통이에요.", "간이 센 안주예요.",
    "소화전 옆 증류소", "피로연에서 마셔요.", "다이어트 콜라와 섞어도 좋아요.", "스트레스 없이 익어요.",
    "암갈색 통이 좋아요.", "통 속에서 숙성이 풀려요.", "건강 얘기가 아니에요.", "피부처럼 얇은 막이에요.",
    "통이 맛을 정해요.", "증류소가 이 통을 추천받았어요.", "저는 셰리파예요.", "다음 시간에 만나요.",
    "같이 비교해 봐요.", "함께 검색해 보세요.", "직접 투표해 봐요.", "여기서 차이가 나요.",
    "라벨에서 통 이름을 찾아보세요.", "댓글로 알려 주세요!",
])
def test_normal_screen_copy_is_not_a_health_claim_or_recommendation(text):
    _, qa = audit(text, kind="product_fact", surface="slot")
    assert qa["human_source_review_required"]


def test_neutral_interaction_prefix_does_not_exempt_drinking_advice():
    with pytest.raises(EvidenceError, match="advice_unsupported"):
        audit("같이 비교해 봐요.\n마셔야 해요.")
