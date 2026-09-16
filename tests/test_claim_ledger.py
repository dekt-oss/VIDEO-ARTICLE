"""Claim Ledger 순수 로직 — 구조화 주장 원장 (수정명세 §4).

관심사는 두 가지다: (1) 초록에 없는 값을 만들어내지 않는가, (2) 코드가 LLM 자기보고를 덮어쓰는가.
`engine/report_factsheet.py` 의 number_facts 정규화와 같은 패턴(추가 + 결정론적 id + 코드 재계산).
"""

from engine import config
from engine.factsheet import (
    claim_ids,
    normalize_factsheet,
    primary_claim_candidates,
)


def _fs(**over):
    base = {
        "what_found": ["법 시행 지역 기업의 환경 성과가 낮게 나타남"],
        "how": ["시행 지역과 비교 지역 비교"],
        "numbers": [],
        "limitations": ["인과 해석 제한"],
        "claim_strength": "중 — 관찰 연구",
    }
    base.update(over)
    return base


# ── 결정론적 claim_id ──
def test_claim_id_assigned_deterministically():
    fs = normalize_factsheet(_fs(claims=[{"claim_ko": "a"}, {"claim_ko": "b"}, {"claim_ko": "c"}]))
    assert [c["claim_id"] for c in fs["claims"]] == ["C01", "C02", "C03"]


def test_explicit_claim_id_preserved():
    fs = normalize_factsheet(_fs(claims=[{"claim_id": "M1", "claim_ko": "a"}]))
    assert fs["claims"][0]["claim_id"] == "M1"


def test_duplicate_claim_ids_made_unique():
    # 중복이 남으면 대본·지시서 참조가 어느 주장인지 알 수 없어진다.
    fs = normalize_factsheet(_fs(claims=[
        {"claim_id": "C01", "claim_ko": "a"},
        {"claim_id": "C01", "claim_ko": "b"},
        {"claim_id": "C01", "claim_ko": "c"},
    ]))
    ids = [c["claim_id"] for c in fs["claims"]]
    assert ids == ["C01", "C01_1", "C01_2"]
    assert len(set(ids)) == 3


# ── 없는 값은 추정하지 않는다 ──
def test_absent_fields_are_none_not_empty_string():
    fs = normalize_factsheet(_fs(claims=[{"claim_ko": "결과만 있는 주장"}]))
    claim = fs["claims"][0]
    for field in ("sample_size", "study_period", "effect_size", "geography", "comparison"):
        assert claim[field] is None, f"{field} 는 None 이어야 한다(빈 문자열은 '확인됨'으로 오독된다)"


def test_null_like_strings_coerced_to_none():
    fs = normalize_factsheet(_fs(claims=[{
        "claim_ko": "x", "sample_size": "", "study_period": "  ",
        "geography": "미상", "comparison": "N/A", "effect_size": "null",
    }]))
    claim = fs["claims"][0]
    assert claim["sample_size"] is None and claim["study_period"] is None
    assert claim["geography"] is None and claim["comparison"] is None and claim["effect_size"] is None


def test_present_values_survive():
    fs = normalize_factsheet(_fs(claims=[{
        "claim_ko": "x", "sample_size": "1,240개 기업", "study_period": "2016-2022",
        "effect_size": "3.2", "effect_unit": "%p",
    }]))
    claim = fs["claims"][0]
    assert claim["sample_size"] == "1,240개 기업"
    assert claim["study_period"] == "2016-2022"
    assert claim["effect_size"] == "3.2" and claim["effect_unit"] == "%p"


# ── missing_fields 는 코드가 재계산 ──
def test_missing_fields_recomputed_ignoring_llm_claim():
    fs = normalize_factsheet(_fs(claims=[{
        "claim_ko": "x",
        "sample_size": "1240",
        "missing_fields": ["전부", "다", "있음"],   # LLM 이 엉터리로 신고
    }]))
    missing = fs["claims"][0]["missing_fields"]
    assert "sample_size" not in missing          # 실제로 있으니 빠져야 한다
    assert "study_period" in missing             # 실제로 없으니 들어가야 한다
    assert set(missing) <= set(config.CLAIM_NULLABLE_FIELDS)


# ── enum 강제 ──
def test_causal_strength_defaults_conservative():
    fs = normalize_factsheet(_fs(claims=[{"claim_ko": "x", "causal_strength": "매우 인과적"}]))
    assert fs["claims"][0]["causal_strength"] == config.DEFAULT_CAUSAL_STRENGTH == "association_only"


def test_enums_normalized():
    fs = normalize_factsheet(_fs(claims=[{
        "claim_ko": "x", "claim_kind": "MAIN_RESULT",
        "effect_direction": "DECREASE", "causal_strength": "Quasi_Causal",
    }]))
    claim = fs["claims"][0]
    assert claim["claim_kind"] == "main_result"
    assert claim["effect_direction"] == "decrease"
    assert claim["causal_strength"] == "quasi_causal"


def test_unknown_enum_falls_back_to_default():
    fs = normalize_factsheet(_fs(claims=[{"claim_ko": "x", "claim_kind": "bogus",
                                          "effect_direction": "sideways"}]))
    claim = fs["claims"][0]
    assert claim["claim_kind"] == config.DEFAULT_CLAIM_KIND
    assert claim["effect_direction"] == config.DEFAULT_EFFECT_DIRECTION


# ── 근거 등급: 초록만이면 A 를 줄 수 없다 (§4-6) ──
def test_abstract_only_demotes_grade_a():
    fs = normalize_factsheet(_fs(claims=[{
        "claim_ko": "x", "evidence_grade": "A", "source_section": "abstract"}]))
    assert fs["claims"][0]["evidence_grade"] == config.ABSTRACT_ONLY_MAX_GRADE == "B"


def test_body_section_keeps_grade_a():
    fs = normalize_factsheet(_fs(claims=[{
        "claim_ko": "x", "evidence_grade": "A", "source_section": "body", "source_page": 7}]))
    claim = fs["claims"][0]
    assert claim["evidence_grade"] == "A"
    assert claim["source_page"] == 7


def test_weak_grades_not_promoted_by_demotion_rule():
    for grade in ("C", "D"):
        fs = normalize_factsheet(_fs(claims=[{
            "claim_ko": "x", "evidence_grade": grade, "source_section": "abstract"}]))
        assert fs["claims"][0]["evidence_grade"] == grade


def test_source_section_defaults_to_abstract():
    fs = normalize_factsheet(_fs(claims=[{"claim_ko": "x", "evidence_grade": "A"}]))
    # 섹션 미지정 = 초록 취급 → A 강등. 수집이 초록만 저장하는 현실과 맞는 안전측 기본값.
    assert fs["claims"][0]["source_section"] == "abstract"
    assert fs["claims"][0]["evidence_grade"] == "B"


# ── 레거시 하위호환 ──
def test_legacy_factsheet_without_claims_is_unchanged():
    legacy = _fs()
    out = normalize_factsheet(legacy)
    assert out["claims"] == []
    for key in ("what_found", "how", "numbers", "limitations", "claim_strength"):
        assert out[key] == legacy[key]


def test_claims_not_a_list_is_tolerated():
    assert normalize_factsheet(_fs(claims="쓰레기"))["claims"] == []
    assert normalize_factsheet(_fs(claims=None))["claims"] == []


def test_claim_item_as_bare_string():
    fs = normalize_factsheet(_fs(claims=["문자열 주장"]))
    claim = fs["claims"][0]
    assert claim["claim_ko"] == "문자열 주장"
    assert claim["claim_id"] == "C01"
    assert claim["sample_size"] is None


def test_source_block_still_preserved():
    fs = normalize_factsheet(_fs(source={"title": "t", "authors": ["a"]}))
    assert fs["source"]["title"] == "t"


# ── 다운스트림 헬퍼 ──
def test_claim_ids_helper():
    fs = normalize_factsheet(_fs(claims=[{"claim_ko": "a"}, {"claim_ko": "b"}]))
    assert claim_ids(fs) == ("C01", "C02")
    assert claim_ids({}) == ()
    assert claim_ids(None) == ()


def test_primary_claim_candidates_detects_split_signal():
    fs = normalize_factsheet(_fs(claims=[
        {"claim_ko": "a", "claim_kind": "main_result"},
        {"claim_ko": "b", "claim_kind": "method"},
        {"claim_ko": "c", "claim_kind": "main_result"},
    ]))
    assert primary_claim_candidates(fs) == ("C01", "C03")   # 2개 → 시리즈 분할 신호


def test_prompt_documents_claims_schema():
    from engine.factsheet import FACTSHEET_SYSTEM
    assert '"claims"' in FACTSHEET_SYSTEM
    assert "추정하지 말고 null" in FACTSHEET_SYSTEM
    assert "초록만 주어졌으면 A 를 쓰지 마라" in FACTSHEET_SYSTEM
