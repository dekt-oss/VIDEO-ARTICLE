import json
from pathlib import Path

import pytest

from test_jjeri_schema import REVIEW_PRICES

from engine.motion.jjeri_class.directive import generate_episode
from engine.motion.jjeri_class.evidence import EvidenceError, MUSIC_CREDIT, audit_episode, text_fields


def mock_episode():
    path = Path(__file__).resolve().parents[1] / "assets/templates/jjeri-class/episode.example.json"
    episode = json.loads(path.read_text(encoding="utf-8"))
    episode["scenes"][8]["beats"][0]["text"] = episode["scenes"][8]["beats"][0]["text"].rstrip(".")
    for scene in episode["scenes"]:
        scene["source_chip"] = None
        for beat in scene["beats"]:
            beat["claim_ids"] = ["c1"]
    episode["caption_draft"] = "통과 맛의 비교"
    episode["text_claim_ids"] = {key: ["c1"] for key, _, _ in text_fields(episode) if key not in {"series", "episode"}}
    evidence = {
        "approved": True, "selected_claim_ids": ["c1"],
        "claims": [{"claim_id": "c1", "kind": "practice", "text": "모의 자료", "support_review": "supported",
                    "source_refs": [{"snapshot_id": "source-1", "original_quote": "Mock verified quotation.", "quote_check": "matched"}]}],
        "sources": [{"snapshot_id": "source-1", "publisher": "Mock Publisher", "url": "https://example.com/mock"}],
    }
    return episode, evidence


@pytest.fixture
def rehearsal():
    return mock_episode()


def test_fake_model_and_source_chip(rehearsal):
    episode, evidence = rehearsal
    evidence["claims"].append({"claim_id": "unapproved", "text": "must not enter the prompt"})

    def respond(prompt, payload):
        assert "Never supply source_chip" in prompt
        assert [c["claim_id"] for c in payload["claims"]] == ["c1"]
        return json.dumps(episode)

    raw = generate_episode(evidence, topic=episode["topic"], lesson=episode["episode"], respond=respond)
    checked, qa = audit_episode(raw, evidence)
    assert all(scene["source_chip"] == "Mock Publisher" for scene in checked["scenes"])
    assert MUSIC_CREDIT in checked["caption_draft"]
    assert qa["human_source_review_required"] is True
    assert raw["scenes"][0]["source_chip"] is None


@pytest.mark.parametrize("edit,code", [
    ("question_disguise", "fact_scene_no_claim"),
    ("unknown", "claim_unknown"),
    ("derived", "derived_claim_cited"),
    ("no_quote", "derived_claim_cited"),
    ("source", "source_unverified"),
    ("unmatched", "source_unverified"),
    ("number", "number_unsupported"),
    ("quantity", "quantity_unsupported"),
    ("advice", "advice_unsupported"),
    ("forgery", "source_chip_supplied"),
    ("unapproved", "evidence_not_approved"),
    ("screen", "fact_scene_no_claim"),
    ("caption", "caption_credit_supplied"),
])
def test_blocks_unsupported_model_output(rehearsal, edit, code):
    episode, evidence = rehearsal
    beat = episode["scenes"][0]["beats"][0]
    claim = evidence["claims"][0]
    if edit == "question_disguise":
        beat.update(text="오크가 암을 낫게 하나요?", claim_ids=[], content_kind="question")
    elif edit == "unknown":
        beat["claim_ids"] = ["unknown"]
    elif edit == "derived":
        claim["kind"] = "derived"
    elif edit == "no_quote":
        claim["source_refs"][0]["original_quote"] = ""
    elif edit == "source":
        evidence["sources"].clear()
    elif edit == "unmatched":
        claim["source_refs"][0]["quote_check"] = "unmatched"
    elif edit == "number":
        beat["text"] = "보통 77도예요."
    elif edit == "quantity":
        beat["text"] = "두 티스푼이에요."
    elif edit == "advice":
        beat["text"] = "물 넣어서 드세요."
        claim["kind"] = "product_fact"
    elif edit == "forgery":
        episode["scenes"][0]["source_chip"] = "Forged Publisher"
    elif edit == "unapproved":
        evidence["approved"] = False
    elif edit == "screen":
        del episode["text_claim_ids"]["scenes.0.slots.left.question"]
    elif edit == "caption":
        episode["caption_draft"] = "출처: 검증 안 된 출처"
    with pytest.raises(EvidenceError, match=code):
        audit_episode(episode, evidence)


def test_multi_source_sort_and_overflow(rehearsal):
    episode, evidence = rehearsal
    evidence["sources"].append({"snapshot_id": "source-2", "publisher": "A Publisher", "url": "https://example.com/2"})
    evidence["claims"][0]["source_refs"].append({"snapshot_id": "source-2", "original_quote": "Another quote.", "quote_check": "matched"})
    checked, _ = audit_episode(episode, evidence)
    assert checked["scenes"][0]["source_chip"] == "A Publisher · Mock Publisher"
    evidence["sources"][1]["publisher"] = "A" * 52
    with pytest.raises(EvidenceError, match="source_chip_overflow"):
        audit_episode(episode, evidence)


def test_fixed_question_may_omit_source(rehearsal):
    episode, evidence = rehearsal
    last = episode["scenes"][-1]
    last["beats"][0] = {"text": "댓글로 알려 주세요!", "claim_ids": []}
    last["slots"]["left"]["label"] = "당신은 어느 쪽?"
    last["slots"]["right"]["label"] = "당신은 어느 쪽?"
    for key in list(episode["text_claim_ids"]):
        if key.startswith("scenes.11.") or key == "chapters.7.title":
            del episode["text_claim_ids"][key]
    checked, _ = audit_episode(episode, evidence)
    assert checked["scenes"][-1]["source_chip"] is None



def test_fake_response_receives_specific_correction(rehearsal):
    episode, evidence = rehearsal
    attempts = []

    def respond(_, payload):
        attempts.append(payload)
        if len(attempts) == 1:
            return "invalid JSON"
        assert payload["correction"]["code"] == "json_invalid"
        assert payload["correction"]["field"] == "episode"
        return json.dumps(episode)

    assert generate_episode(evidence, topic=episode["topic"], lesson=episode["episode"], respond=respond) == episode
    assert len(attempts) == 2


@pytest.mark.parametrize("price", [*REVIEW_PRICES, "만 원대로도 충분해요."])
def test_production_audit_rejects_review_prices_with_approved_claim(rehearsal, price):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = price
    with pytest.raises(EvidenceError, match="price_forbidden"):
        audit_episode(episode, evidence)


@pytest.mark.parametrize("text,quote", [
    ("삼십 년 숙성이 최고예요.", "The sample costs 30 dollars."),
    ("도수는 사십 도예요.", "The barrel is 40 years old."),
    ("두 배예요.", "The sample aged 2 years."),
    ("세 개월이에요.", "It takes 13 months."),
    ("이십 퍼센트예요.", "The container holds 20 liters."),
])
def test_korean_quantity_requires_matching_number_and_unit(rehearsal, text, quote):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    evidence["claims"][0]["source_refs"][0]["original_quote"] = quote
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit_episode(episode, evidence)


@pytest.mark.parametrize("text,quote", [
    ("삼십 년 숙성", "Aged for 30 years."),
    ("도수는 사십 도예요.", "Bottled at 40% ABV."),
    ("두 배예요.", "Its capacity is twice the original."),
    ("세 개월이에요.", "Aged for 3 months."),
    ("이십 퍼센트예요.", "Ten years, then 20 percent."),
    ("이십오 년 숙성", "이십오 년 숙성했습니다."),
])
def test_verified_matching_quantity_is_preserved(rehearsal, text, quote):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    evidence["claims"][0]["source_refs"][0]["original_quote"] = quote
    audit_episode(episode, evidence)


@pytest.mark.parametrize("text,code", [
    ("매일 꼭 마셔요.", "advice_unsupported"),
    ("매일 드시는 게 좋아요.", "advice_unsupported"),
    ("버번은 암을 치료해요.", "health_claim_forbidden"),
    ("혈압을 낮춰 줘요.", "health_claim_forbidden"),
    ("면역력 강화에 좋아요.", "health_claim_forbidden"),
])
def test_unrelated_approved_claim_does_not_authorize_health_or_advice(rehearsal, text, code):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    with pytest.raises(EvidenceError, match=code):
        audit_episode(episode, evidence)


def test_direct_recommendation_quote_is_required(rehearsal):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = "물과 비교해 보세요."
    quote = evidence["claims"][0]["source_refs"][0]
    quote["original_quote"] = "The guide does not say 물과 비교해 보세요."
    with pytest.raises(EvidenceError, match="advice_unsupported"):
        audit_episode(episode, evidence)
    quote["original_quote"] = "물과 비교해 보세요."
    audit_episode(episode, evidence)


def test_generated_source_label_cannot_restore_price(rehearsal):
    episode, evidence = rehearsal
    evidence["sources"][0]["publisher"] = "30€"
    with pytest.raises(EvidenceError, match="source_label_invalid"):
        audit_episode(episode, evidence)


@pytest.mark.parametrize("text", [
    "삼만 오천", "가격 삼만", "가격은 삼만 구천", "한 병에 3만", "39,900",
    "값은 39,900", "30 dollars", "30 bucks", "3만 선이에요", "5만 정도 해요",
    "가격은 삼만이에요", "한 병에 3만이에요", "삼십 달러",
])
def test_recheck_money_is_forbidden_even_when_supported(rehearsal, text):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    evidence["claims"][0]["source_refs"][0]["original_quote"] = "The source says: " + text
    with pytest.raises(EvidenceError, match="price_forbidden"):
        audit_episode(episode, evidence)


@pytest.mark.parametrize("text", [
    "몸에 좋아요", "간에 좋아요", "피로가 풀려요", "감기에 좋아요", "잠이 잘 와요",
    "살이 빠져요", "소화를 도와요", "혈액순환에 좋아요", "치매를 막아 줘요",
    "심장병 위험을 줄여요", "항산화 성분이 많아요", "스트레스가 풀려요", "장수의 비결이에요",
    "약으로 쓰였어요", "피부가 좋아져요", "다이어트에 도움이 돼요", "콜레스테롤을 낮춰요",
    "통증을 줄여 줘요", "건강한 술이에요", "숙취가 없어요",
])
@pytest.mark.parametrize("quote_matches", [False, True])
def test_recheck_health_claims_are_forbidden_regardless_of_quote(rehearsal, text, quote_matches):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    if quote_matches:
        evidence["claims"][0]["source_refs"][0]["original_quote"] = text
    with pytest.raises(EvidenceError, match="health_claim_forbidden"):
        audit_episode(episode, evidence)


@pytest.mark.parametrize("label_source", ["publisher", "title"])
def test_recheck_source_chip_cannot_display_health_claim(rehearsal, label_source):
    episode, evidence = rehearsal
    source = evidence["sources"][0]
    if label_source == "title":
        del source["publisher"]
    source[label_source] = "숙취가 없어요"
    evidence["claims"][0]["source_refs"][0]["original_quote"] = source[label_source]
    with pytest.raises(EvidenceError, match="source_label_invalid"):
        audit_episode(episode, evidence)


@pytest.mark.parametrize("text", [
    "얼음 없이 즐기세요", "추천해요", "이건 무조건 사야 해요", "초보라면 버번 통부터 시작해요",
    "따뜻하게 데워 드셔도 돼요", "선물로 딱이에요", "입문자에게 권해요",
])
def test_recheck_advice_requires_the_recommendation_itself(rehearsal, text):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    claim = evidence["claims"][0]
    with pytest.raises(EvidenceError, match="advice_unsupported"):
        audit_episode(episode, evidence)
    claim["source_refs"][0]["original_quote"] = text
    claim["kind"] = "product_fact"
    with pytest.raises(EvidenceError, match="advice_unsupported"):
        audit_episode(episode, evidence)
    claim["kind"] = "recommendation"
    audit_episode(episode, evidence)


@pytest.mark.parametrize("text", [
    "이 원주를 통에 담아요.", "이 원두 향이 나요.", "이 원인은 통이에요.", "이 원통에서 익혀요.",
    "이 원형 통이에요.", "구 원조 증류소", "오 원더풀", "만 원숙한 맛",
    "이 달콤한 향이 나요.", "두 달콤한 향이 섞여요.", "이 도수가 높아요.",
    "이 배경이 중요해요.", "이 배가 달아요.", "이 프로그램을 봐요.", "이 프로세스가 길어요.",
    "이 달에 나왔어요.", "이 년도에 시작했어요.", "한 도전이에요.",
    "암갈색 통이 좋아요", "암시하는 맛이 좋아요", "암석 위에서 익혀 좋아져요",
    "라벨에서 통 이름을 찾아보세요.",
])
def test_recheck_ordinary_korean_text_is_preserved(rehearsal, text):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    checked, qa = audit_episode(episode, evidence)
    assert checked["scenes"][0]["beats"][0]["text"] == text
    assert qa["human_source_review_required"] is True


@pytest.mark.parametrize("text,quote", [
    ("3만 5천 리터", "3만 5천 리터"),
    ("2만 5천 통", "2만 5천 통"),
    ("39,900병", "39,900 bottles"),
    ("사십 도짜리예요", "Bottled at 40% ABV."),
    ("최소 삼 년 익혀요", "A minimum of three years."),
    ("열 배 귀해요", "Ten times rarer."),
    ("온도는 높고\n도수는 사십 도예요.", "Bottled at 40% ABV."),
    ("오 년 간 숙성 효과", "Five years of aging."),
])
def test_recheck_normal_quantities_use_matching_units(rehearsal, text, quote):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    evidence["claims"][0]["source_refs"][0]["original_quote"] = quote
    audit_episode(episode, evidence)


@pytest.mark.parametrize("text,quote", [
    ("세 달 익혀요.", "삼 달콤한 향."),
    ("사십 도에서 보관해요.", "Bottled at 40% ABV."),
    ("온도는 사십 도예요.\n도수는 높아요.", "Bottled at 40% ABV."),
    ("도수는 사십 도예요.", "The liquid was 40 degrees."),
    ("사십 년 숙성", "Aged for 1,040 years."),
    ("삼 년 숙성", "Aged for one hundred and three years."),
    ("사십 년 숙성", "1040년간 익혔습니다."),
    ("십이년산이에요.", "Aged for 10 years."),
])
def test_recheck_units_require_a_whole_token_and_local_context(rehearsal, text, quote):
    episode, evidence = rehearsal
    episode["scenes"][0]["beats"][0]["text"] = text
    evidence["claims"][0]["source_refs"][0]["original_quote"] = quote
    with pytest.raises(EvidenceError, match="number_unsupported"):
        audit_episode(episode, evidence)
