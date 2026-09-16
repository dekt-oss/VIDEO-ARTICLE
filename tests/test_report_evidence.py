"""Evidence Contract · 씬 역할 면제 · Story Plan 검증 (작업지시서 영상엔진품질 v3 §5·§6).

전부 순수 함수 검사다 — 네트워크·DB·LLM 없이 돈다.
"""

from __future__ import annotations

import pytest

from engine import config, report_evidence as ev, report_scriptgen, report_selfcheck

# 하나증권 LG전자 리포트의 실제 문장(engine/aria/fixtures/research_details.json 발췌).
SOURCE_TEXT = (
    "연결기준 매출 23조 8,265억원(YoY +15%, QoQ +0.4%), 영업이익 1조 5,791억원"
    "(YoY +147%, QoQ -6%, OPM 6.6%)을 기록했다. "
    "LG전자에 대한 투자의견 BUY, 목표주가 26만원을 유지한다."
)
CHUNKS = [{"chunk_id": "C001", "text": SOURCE_TEXT}]
PACKET = {"text": SOURCE_TEXT, "chunks": CHUNKS}


def _fact(**kw):
    base = {"fact_id": "num_1", "value": 15791.0, "unit": "억원", "period": "2Q26",
            "metric": "영업이익", "comparator": {"basis": "전년 동기", "value": "+147%"},
            "source_refs": [{"chunk_id": "C001",
                             "quote": "영업이익 1조 5,791억원(YoY +147%, QoQ -6%, OPM 6.6%)을 기록했다."}]}
    base.update(kw)
    return base


# ── 단위·기간 정규화 ────────────────────────────────────────────────
def test_units_are_normalized():
    assert ev.normalize_unit("배") == ev.normalize_unit("x") == "x"
    assert ev.normalize_unit("억") == ev.normalize_unit("억원") == "억원"
    assert ev.normalize_unit("퍼센트") == "%"
    assert ev.normalize_unit("냥") == "냥", "모르는 단위를 임의로 매핑하지 않는다"
    assert ev.normalize_unit("") == ""


def test_period_must_be_explicit():
    for ok in ("2026F", "2Q26", "FY4Q26", "TTM", "연간", "2027"):
        assert ev.period_is_explicit(ok), ok
    for bad in ("", "최근", "향후", "올해 하반기쯤"):
        assert not ev.period_is_explicit(bad), bad


# ── 인용 대조 — §5-2 의 핵심 ────────────────────────────────────────
def test_quote_must_exist_in_source():
    assert ev.quote_found_in_source("목표주가 26만원을 유지한다", SOURCE_TEXT)
    # 줄바꿈·이중 공백이 섞인 PDF 추출물이라도 사람이 옳게 옮긴 인용은 찾아야 한다.
    assert ev.quote_found_in_source("목표주가  26만원을\n유지한다", SOURCE_TEXT)
    assert not ev.quote_found_in_source("목표주가 40만원을 유지한다", SOURCE_TEXT)


def test_too_short_quote_is_not_evidence():
    """짧은 인용은 우연히 원문에 있을 수 있어 대조 의미가 없다."""
    assert not ev.quote_found_in_source("매출", SOURCE_TEXT)


def test_value_must_appear_in_quote():
    q = "영업이익 1조 5,791억원(YoY +147%)"
    assert ev.value_supported_by_quote(15791, q)
    assert ev.value_supported_by_quote(1.5791, q), "억↔조 환산은 같은 값으로 본다"
    assert not ev.value_supported_by_quote(9999, q)


# ── evidence unit 승격 + 코드 판정 ──────────────────────────────────
def test_attach_evidence_overrides_model_selfreport():
    """모델이 validation 을 스스로 채워 보내도 코드 판정이 덮어쓴다."""
    fs = {"number_facts": [_fact(validation={"number_match": True, "quote_supports_claim": True})]}
    ev.attach_evidence(fs, PACKET)
    v = fs["number_facts"][0]["validation"]
    assert v["number_match"] is True and v["quote_supports_claim"] is True
    assert fs["number_facts"][0]["unit_norm"] == "억원"

    fake = {"number_facts": [_fact(source_refs=[{"chunk_id": "C001",
                                                 "quote": "영업이익 9조 9,999억원을 기록했다."}])]}
    ev.attach_evidence(fake, PACKET)
    assert fake["number_facts"][0]["validation"]["quote_supports_claim"] is False


def test_unknown_chunk_id_is_never_kept_as_is():
    """모델이 준 라벨을 그대로 남기지 않는다 — dangling 참조 금지.

    ★ 예전엔 모르는 id 를 **버렸다**(빈 문자열). 지금은 인용문 위치로 **다시 매긴다** —
      프로덕션에서 19개 ref 전부가 라벨 불일치로 버려지는 것을 보고 바꿨다. 어느 쪽이든
      C999 가 살아남지 않는다는 계약은 같다.
    """
    fs = {"number_facts": [_fact(source_refs=[
        {"chunk_id": "C999", "quote": "목표주가 26만원을 유지한다."}])]}
    ev.attach_evidence(fs, PACKET)
    got = fs["number_facts"][0]["source_refs"][0]["chunk_id"]
    assert got != "C999"
    assert got in ("", "C001")


def test_unverifiable_is_none_not_false():
    """원문이 없으면 '틀렸다'가 아니라 '검증 못 함'이다 — 둘을 섞으면 게이트가 거짓말한다."""
    fs = {"number_facts": [_fact()]}
    ev.attach_evidence(fs, {"text": "", "chunks": []})
    assert fs["number_facts"][0]["validation"]["quote_supports_claim"] is None


# ── 하드 차단 4종 ──────────────────────────────────────────────────
def test_hard_block_on_fabricated_quote():
    fs = {"number_facts": [_fact(source_refs=[{"chunk_id": "C001", "quote": "지어낸 문장입니다 여기."}])]}
    ev.attach_evidence(fs, PACKET)
    assert any(r.startswith("quote_not_in_source") for r in ev.hard_blocks(fs))


def test_hard_block_on_missing_period_and_unit():
    fs = {"number_facts": [_fact(period="", unit="")]}
    ev.attach_evidence(fs, PACKET)
    reasons = ev.hard_blocks(fs)
    assert any(r.startswith("number_without_period") for r in reasons)
    assert any(r.startswith("number_without_unit") for r in reasons)


def test_hard_block_when_no_fact_has_source_ref():
    fs = {"number_facts": [_fact(source_refs=[])]}
    ev.attach_evidence(fs, PACKET)
    assert "no_fact_has_source_ref" in ev.hard_blocks(fs)


def test_conflicting_numbers_are_not_auto_resolved():
    fs = {"number_facts": [_fact(), _fact(fact_id="num_2", value=15000.0)]}
    ev.attach_evidence(fs, PACKET)
    assert any(r.startswith("conflicting_numbers") for r in ev.hard_blocks(fs))


def test_clean_fact_sheet_has_no_hard_blocks():
    fs = {"number_facts": [_fact()]}
    ev.attach_evidence(fs, PACKET)
    assert ev.hard_blocks(fs) == []


def test_hard_block_is_off_by_default():
    """현 재고(요약 기반 162건)에 켜면 전부 막힌다 — 기본 off 를 고정한다."""
    fs = {"number_facts": [_fact(source_refs=[])]}
    ev.attach_evidence(fs, PACKET)
    assert ev.build_block(fs)["blocked"] is False
    assert ev.build_block(fs)["block_reasons"], "차단은 안 하되 사유는 보여준다"


# ── 프로파일 게이트 ────────────────────────────────────────────────
def test_profile_minimums_differ_by_type():
    """v1 의 일괄 기준(≥8/≥3)이 시황·이벤트에 과도했다는 지적(§0-1 #3)."""
    assert (config.EVIDENCE_PROFILE_MINIMUMS["event_flash"]["min_evidence"]
            < config.EVIDENCE_PROFILE_MINIMUMS["earnings_review"]["min_evidence"])


def test_profile_gate_flags_thin_evidence():
    fs = {"number_facts": [_fact()], "what": [], "basis": [], "risks": []}
    ev.attach_evidence(fs, PACKET)
    warns = ev.profile_gate(fs, "earnings_review")
    assert any(w.startswith("evidence_below_min") for w in warns)
    assert any(w.startswith("category_missing") for w in warns)


def test_gate_label_strips_suffix():
    assert ev.gate_label("number_without_unit:num_3") == ev.GATE_LABELS["number_without_unit"]
    assert ev.gate_label("모르는_토큰") == "모르는_토큰"


# ── §5-4 자기검증 면제 — Phase 0 이 실측한 오탐이 사라지는가 ──────────
def _selfcheck_raw(n: int):
    """LLM 이 훅(1)과 마무리(n)를 '근거 불충분'으로 찍은 실제 패턴을 재현."""
    return {"scenes": [
        {"scene": i, "grounded": i not in (1, n),
         "unsupported": [] if i not in (1, n) else [f"씬 {i} 문장"],
         "matched_facts": []}
        for i in range(1, n + 1)
    ]}


def test_hook_and_cta_false_positives_disappear():
    """실측: 최근 초안 6/6 이 첫 씬·마지막 씬에서 오탐. 면제 후 0 이어야 한다."""
    roles = {1: "HOOK", 2: "EVIDENCE", 3: "EVIDENCE", 4: "MECHANISM", 5: "RISK",
             6: "WATCHPOINT", 7: "CTA"}
    out = report_selfcheck.normalize_selfcheck(_selfcheck_raw(7), roles)
    assert out["all_grounded"] is True
    assert out["scenes"][0]["exempt"] is True and out["scenes"][0]["grounded"] is True
    assert out["scenes"][6]["exempt"] is True


def test_real_hallucination_still_flags():
    """면제가 진짜 환각까지 덮으면 안 된다 — 근거 씬의 플래그는 살아 있어야 한다."""
    raw = _selfcheck_raw(7)
    raw["scenes"][2]["grounded"] = False
    raw["scenes"][2]["unsupported"] = ["없는 수치를 말했다"]
    roles = {1: "HOOK", 7: "CTA"}
    out = report_selfcheck.normalize_selfcheck(raw, roles)
    assert out["all_grounded"] is False
    assert out["scenes"][2]["exempt"] is False


def test_exemption_needs_the_role_to_travel_through_the_pipeline():
    """report_draft 가 씬을 깎을 때 scene_role 을 빠뜨리면 면제가 무력해진다 — 그 급소를 고정."""
    import inspect

    from engine import report_draft

    src = inspect.getsource(report_draft.generate_report_draft)
    assert "scene_role" in src, "narr_scenes 에 scene_role 이 실려야 면제가 검증관에 도달한다"


def test_scene_role_is_whitelisted():
    """자유 텍스트가 들어오면 면제도 검사도 안 걸린다."""
    out = report_scriptgen.normalize_script(
        {"scenes": [{"scene": 1, "scene_role": "hook"},
                    {"scene": 2, "scene_role": "아무말"},
                    {"scene": 3}]})
    assert out["scenes"][0]["scene_role"] == "HOOK"
    assert out["scenes"][1]["scene_role"] == config.SCENE_ROLE_DEFAULT
    assert out["scenes"][2]["scene_role"] == config.SCENE_ROLE_DEFAULT


def test_scene_roles_do_not_pollute_explainer_beat_roles():
    """EXPLAINER_BEAT_ROLES 를 늘리면 explainer 의 비트 수 판정이 흔들린다."""
    assert "CTA" not in config.EXPLAINER_BEAT_ROLES
    assert "CTA" in config.SCENE_ROLES


# ── §6 Story Plan ─────────────────────────────────────────────────
def _plan(**kw):
    base = {
        "thesis": "AI 데이터센터 냉각 수주가 LG전자의 이익 체력을 바꾼다.",
        "content_profile": "earnings_review",
        "claim_chain": [
            {"order": 1, "role": "hook", "claim": "왜 목표가를 유지했나", "evidence_refs": []},
            {"order": 2, "role": "proof", "claim": "영업이익 급증", "evidence_refs": ["num_1"]},
            {"order": 3, "role": "closing", "claim": "확인 포인트", "evidence_refs": ["num_2"]},
        ],
    }
    base.update(kw)
    return base


FS = {"number_facts": [{"fact_id": "num_1"}, {"fact_id": "num_2"}]}


def test_story_plan_accepts_a_sound_chain():
    assert ev.validate_story_plan(_plan(), FS) == []


def test_story_plan_flags_missing_thesis_and_unpaid_claims():
    plan = _plan(thesis="", claim_chain=[
        {"order": 1, "role": "proof", "claim": "근거 없는 주장", "evidence_refs": []}])
    warns = ev.validate_story_plan(plan, FS)
    assert "thesis_missing" in warns
    assert any(w.startswith("claim_without_evidence") for w in warns)
    assert any(w.startswith("claims_below_min") for w in warns)


def test_story_plan_flags_conclusion_before_proof():
    plan = _plan(claim_chain=[
        {"order": 1, "role": "closing", "claim": "결론", "evidence_refs": ["num_1"]},
        {"order": 2, "role": "proof", "claim": "근거", "evidence_refs": ["num_2"]},
        {"order": 3, "role": "risk", "claim": "리스크", "evidence_refs": ["num_1"]},
    ])
    assert "closing_before_proof" in ev.validate_story_plan(plan, FS)


def test_story_plan_flags_unknown_and_reused_evidence():
    plan = _plan(claim_chain=[
        {"order": 1, "role": "proof", "claim": "a", "evidence_refs": ["num_1"]},
        {"order": 2, "role": "proof", "claim": "b", "evidence_refs": ["num_1"]},
        {"order": 3, "role": "proof", "claim": "c", "evidence_refs": ["num_없음"]},
    ])
    warns = ev.validate_story_plan(plan, FS)
    assert "evidence_reused:num_1" in warns
    assert "evidence_ref_unknown:num_없음" in warns


def test_story_plan_survives_garbage_input():
    """LLM 이 story_plan 을 통째로 빠뜨려도 파이프라인이 죽지 않는다."""
    out = report_scriptgen.normalize_script({"scenes": []})
    assert out["story_plan"]["thesis"] == ""
    assert out["story_plan"]["content_profile"] == config.EVIDENCE_PROFILE_DEFAULT


def test_text_density_flags_number_overload_per_scene():
    scenes = [
        {"scene": 1, "narration_ko": "매출 23조, 이익 1조, PER 12배, ROE 8%", "duration_sec": 10},
        {"scene": 2, "narration_ko": "짧은 문장", "duration_sec": 6},
    ]
    warns = ev.validate_text_density(scenes)
    assert "too_many_numbers_in_scene:1" in warns
    assert not any(w.startswith("too_many_numbers_in_scene:2") for w in warns)


def test_narration_length_is_not_compared_to_planned_cut_length():
    """렌더는 duration_sec 를 쓰지 않고 나레이션 실측으로 컷을 만든다 — 씬마다 경고하지 않는다.

    실측 배경: 최근 초안 12편 전부가 씬 대부분에서 "다 읽을 수 없다" 경고를 받았는데
    같은 편의 완성 영상은 43~59초로 정상이었다(계획은 25~30초).
    """
    scenes = [{"scene": 1, "narration_ko": "가" * 60, "duration_sec": 4}]
    warns = ev.validate_text_density(scenes)
    assert not any(w.startswith("narration_too_long_for_cut") for w in warns)


def test_plan_versus_speech_mismatch_is_one_warning_per_draft():
    """씬 6개가 전부 어긋나도 경고는 편당 1건이다(요약)."""
    scenes = [
        {"scene": i, "narration_ko": "가" * 45, "duration_sec": 4} for i in range(1, 7)
    ]
    warns = ev.validate_text_density(scenes)
    off = [w for w in warns if w.startswith("duration_estimate_off")]
    assert len(off) == 1
    # 사람이 읽을 숫자가 붙는다: "계획 24초 → 예상 36초"
    assert "계획" in off[0] and "예상" in off[0]


def test_matching_plan_makes_no_duration_warning():
    """계획이 발화 길이와 맞으면 아무 말도 하지 않는다."""
    scenes = [{"scene": 1, "narration_ko": "가" * 76, "duration_sec": 10}]  # 76/7.6 = 10초
    assert ev.validate_text_density(scenes) == []


# ══════════════════════════════════════════════════════════════
# 적대적 리뷰가 찾은 결함 — 전부 재현으로 확인된 것들이다.
# 이 절이 없으면 같은 결함이 다시 들어와도 39개 테스트가 초록으로 통과한다.
# ══════════════════════════════════════════════════════════════

# ── 숫자 대조: 부호·자릿수·근사값 ────────────────────────────────
def test_sign_is_not_thrown_away():
    """+15% 성장이 '-15% 감소' 원문으로 검증되던 결함."""
    assert ev.value_supported_by_quote(15, "전년 대비 -15% 감소했다") is False
    assert ev.value_supported_by_quote(-15, "전년 대비 -15% 감소했다") is True


def test_order_of_magnitude_error_is_caught():
    """15,791억을 1,579억 인용으로 검증하던 결함 — 10배는 단위 환산이 아니라 오기다."""
    assert ev.value_supported_by_quote(15791, "영업이익 1,579억원") is False


def test_near_miss_value_is_rejected():
    """5% 차이가 통과하던 결함(가수 절대차 0.1 이 실효 10% 허용이었다)."""
    assert ev.value_supported_by_quote(15791, "영업이익 1조 5,000억원") is False


def test_tolerance_is_consistent_across_magnitudes():
    """같은 10% 오차인데 가수 크기에 따라 판정이 갈리던 결함."""
    assert ev.value_supported_by_quote(9.9, "점유율 9.0%") is False
    assert ev.value_supported_by_quote(100, "배당성향 1.09배") is False


def test_legitimate_unit_conversion_still_passes():
    """막는 데 급해서 정상 환산까지 막으면 안 된다."""
    q = "연결기준 매출 23조 8,265억원, 영업이익 1조 5,791억원"
    assert ev.value_supported_by_quote(15791, q) is True        # 억원
    assert ev.value_supported_by_quote(1.5791, q) is True       # 조원
    assert ev.value_supported_by_quote(23.8265, q) is True      # 조원


# ── 한국어 자릿수 묶기 ─────────────────────────────────────────
def test_korean_scale_does_not_merge_across_separators():
    """'1조, 8,000억' 을 1.8조로 합산해 없는 값을 만들던 결함."""
    assert ev.korean_scaled_numbers("영업이익 1조, 순이익 8,000억") == [1e12, 8e11]
    assert ev.korean_scaled_numbers("영업이익 1조 (전년 5,000억)") == [1e12, 5e11]


def test_korean_scale_still_merges_one_value():
    assert ev.korean_scaled_numbers("영업이익 1조 5,791억원") == [pytest.approx(1.5791e12)]
    assert ev.korean_scaled_numbers("2조와 3조") == [2e12, 3e12]


def test_korean_scale_ignores_non_amount_prefixes():
    assert ev.korean_scaled_numbers("3분기 2조") == [2e12]
    assert ev.korean_scaled_numbers("2026년 3조") == [3e12]


# ── 밀도 오탐 ─────────────────────────────────────────────────
def test_year_and_scale_tokens_are_not_counted_as_spoken_numbers():
    """'2026년 영업이익은 1조 5,791억원' 은 들리는 수치가 하나다."""
    assert len(ev.spoken_numbers("2026년 영업이익은 1조 5,791억원")) == 1
    # duration_sec 는 발화 길이(20자/7.6≈2.6초)와 맞춰 둔다 — 여기서 보려는 것은 숫자 세기지 길이가 아니다.
    assert ev.validate_text_density(
        [{"scene": 1, "narration_ko": "2026년 영업이익은 1조 5,791억원", "duration_sec": 3}]) == []


# ── 게이트 오탐 ───────────────────────────────────────────────
def test_consensus_versus_actual_is_not_a_conflict():
    """컨센서스 14,000억 vs 실적 15,791억 은 정상 데이터다."""
    facts = [
        {"fact_id": "a", "value": 15791.0, "unit_norm": "억원", "period": "2Q26",
         "metric": "영업이익", "comparator": {"basis": "실적"}},
        {"fact_id": "b", "value": 14000.0, "unit_norm": "억원", "period": "2Q26",
         "metric": "영업이익", "comparator": {"basis": "컨센서스"}},
    ]
    assert ev.conflict_groups(facts) == []


def test_same_basis_different_value_is_still_a_conflict():
    facts = [
        {"fact_id": "a", "value": 15791.0, "unit_norm": "억원", "period": "2Q26",
         "metric": "영업이익", "comparator": {"basis": "실적"}},
        {"fact_id": "b", "value": 14000.0, "unit_norm": "억원", "period": "2Q26",
         "metric": "영업이익", "comparator": {"basis": "실적"}},
    ]
    assert ev.conflict_groups(facts)


def test_risk_category_uses_the_risks_array_not_keywords():
    """factsheet 가 'risks 없으면 빈 배열'로 바뀐 것과 게이트가 서로를 밟던 결함."""
    base = {"number_facts": [_fact(fact_id=f"n{i}") for i in range(7)],
            "what": ["매출 성장"], "basis": ["수주 확대"],
            "risks": ["중동 물류비 상승"]}
    ev.attach_evidence(base, PACKET)
    assert "risks_missing" not in ev.profile_gate(base, "earnings_review")

    base["risks"] = []
    assert "risks_missing" in ev.profile_gate(base, "earnings_review")


def test_hard_block_only_when_no_fact_has_a_quote():
    """facts[0] 을 핵심으로 가정하던 결함 — 순서는 LLM 출력 순서일 뿐이다."""
    fs = {"number_facts": [_fact(fact_id="a", source_refs=[]), _fact(fact_id="b")]}
    ev.attach_evidence(fs, PACKET)
    assert "no_fact_has_source_ref" not in ev.hard_blocks(fs)


def test_paper_explainer_profile_is_reachable():
    """config 에만 있고 대본 프롬프트 enum 에 없어 절대 선택되지 않던 값."""
    assert "paper_explainer" in report_scriptgen.SCRIPT_SYSTEM


# ── 면제 우회 ─────────────────────────────────────────────────
def test_exemption_cannot_be_claimed_by_every_scene():
    """전 씬에 HOOK 을 붙이면 자기검증이 통째로 무력해지던 결함."""
    scenes = [{"scene": i, "scene_role": "HOOK", "narration_ko": f"문장 {i}"} for i in range(1, 8)]
    raw = {"scenes": [{"scene": i, "grounded": False,
                       "unsupported": [f"근거 없음 {i}"], "matched_facts": []}
                      for i in range(1, 8)]}
    out = report_selfcheck.normalize_selfcheck(
        raw, {i: "HOOK" for i in range(1, 8)}, report_selfcheck.exempt_scenes(scenes))
    assert out["all_grounded"] is False


def test_scene_that_speaks_a_number_is_never_exempt():
    """훅이라도 수치를 말했으면 그 수치는 근거가 있어야 한다."""
    scenes = [
        {"scene": 1, "scene_role": "HOOK", "narration_ko": "영업이익이 1조 5,791억원입니다"},
        {"scene": 2, "scene_role": "EVIDENCE", "narration_ko": "설명"},
        {"scene": 3, "scene_role": "CTA", "narration_ko": "댓글로 알려주세요"},
    ]
    assert report_selfcheck.exempt_scenes(scenes) == {3}


def test_normal_hook_and_cta_are_still_exempt():
    scenes = [
        {"scene": 1, "scene_role": "HOOK", "narration_ko": "정말 이제 시작일까요?"},
        {"scene": 2, "scene_role": "EVIDENCE", "narration_ko": "설명"},
        {"scene": 3, "scene_role": "EVIDENCE", "narration_ko": "설명"},
        {"scene": 4, "scene_role": "EVIDENCE", "narration_ko": "설명"},
        {"scene": 5, "scene_role": "CTA", "narration_ko": "댓글로 알려주세요"},
    ]
    assert report_selfcheck.exempt_scenes(scenes) == {1, 5}


@pytest.mark.parametrize("roles", [
    ["HOOK", "CTA"],                      # cap=1 인데 예전엔 2개를 면제했다
    ["HOOK", "QUESTION", "CTA"],          # cap=1
    ["HOOK", "CTA", "BRIDGE", "QUESTION"],  # cap=1
])
def test_exempt_count_never_exceeds_cap_on_short_scripts(roles):
    """씬이 적으면 상한이 1인데 예전 코드는 늘 앞뒤 2개를 남겼다.

    ★ 그래서 씬 2개짜리 대본은 두 씬 모두 면제되어 all_grounded 가 항상 True 였다 —
      "전 씬에 HOOK" 우회를 씬 수를 줄이는 것만으로 재현할 수 있었다.
    """
    scenes = [{"scene": i, "scene_role": r, "narration_ko": "말입니다"}
              for i, r in enumerate(roles, 1)]
    cap = max(1, int(len(scenes) * config.SELFCHECK_EXEMPT_MAX_RATIO))
    exempt = report_selfcheck.exempt_scenes(scenes)
    assert len(exempt) <= cap
    assert len(exempt) < len(scenes)      # 전 씬 면제는 어떤 경우에도 안 된다


def test_two_scene_all_hook_script_still_gets_checked():
    """상한 회귀의 실제 증상 — 씬 2개 전부 면제되면 진짜 환각도 통과한다."""
    scenes = [{"scene": 1, "scene_role": "HOOK", "narration_ko": "질문입니다"},
              {"scene": 2, "scene_role": "CTA", "narration_ko": "댓글 주세요"}]
    raw = {"scenes": [{"scene": i, "grounded": False, "unsupported": ["지어낸 주장"],
                       "matched_facts": []} for i in (1, 2)]}
    out = report_selfcheck.normalize_selfcheck(
        raw, {1: "HOOK", 2: "CTA"}, report_selfcheck.exempt_scenes(scenes))
    assert out["all_grounded"] is False


# ── 하이픈 vs 마이너스 ────────────────────────────────────────
@pytest.mark.parametrize("value,quote", [
    (-5.0, "3-5% 성장"),          # 범위 표기의 뒷숫자를 음수로 읽던 결함
    (-2.0, "1-2배 수준"),
    (-2026.0, "2025-2026년 전망"),
])
def test_hyphen_range_is_not_read_as_a_minus_sign(value, quote):
    assert ev.value_supported_by_quote(value, quote) is False


@pytest.mark.parametrize("value,quote", [
    (-15.0, "전년 대비 -15% 감소했다"),
    (-77.0, "영업이익 1,130억원(-77% YoY)"),
    (-1200.0, "영업손실 (-1,200억원)"),
])
def test_real_minus_signs_still_verify(value, quote):
    """부호를 못 읽게 만들면 안 된다 — 공백·문두·괄호 뒤의 하이픈은 마이너스다."""
    assert ev.value_supported_by_quote(value, quote) is True


def test_year_range_yields_positive_years_only():
    assert ev.numbers_in("2025-2026년 전망") == [2025.0, 2026.0]


# ── 재검사 경로 ───────────────────────────────────────────────
def test_recheck_recomputes_evidence():
    """대본을 고치고 재검사를 눌러도 근거 경고가 옛날 것으로 남던 결함."""
    import inspect

    from engine import report_draft

    src = inspect.getsource(report_draft.recheck_compliance)
    assert "build_evidence_block" in src, "재검사가 근거 게이트를 다시 돌려야 한다"


def test_recheck_revalidates_facts_not_just_the_gate():
    """게이트만 다시 돌리면 검증기 수정이 기존 초안에 영영 안 닿는다.

    ★ 실측: 기간 표기 판정을 고치고 프로덕션에서 재검사를 돌렸는데
      `number_without_period` 3건이 그대로 남았다. hard_blocks 가 **저장된**
      validation.period_match 를 읽기 때문이다. validation 부터 다시 계산해야 한다.
    """
    import inspect

    from engine import report_draft

    src = inspect.getsource(report_draft.recheck_compliance)
    assert "revalidate_facts" in src, "재검사가 validation 을 다시 계산해야 한다"
    # 다시 계산해 놓고 저장하지 않으면 다음 조회에서 옛 판정이 되살아난다.
    #   (2026-08-20: 호출이 여러 줄로 늘어났다 — 씬·자기검증·지문도 함께 저장한다.
    #    한 줄만 보던 예전 단언은 그 줄바꿈에서 깨졌다. 인자 목록 전체를 본다.)
    call = src.split("update_report_draft_compliance")[1].split(")")[0]
    assert "fact_sheet" in call

    rv = inspect.getsource(report_draft.revalidate_facts)
    assert "attach_evidence" in rv
    assert "store=False" in rv, "재검사가 원문을 다시 저장할 이유가 없다"


def test_hard_blocks_read_stored_validation():
    """위 테스트가 지키는 계약의 근거 — 게이트는 저장된 판정을 읽는다(다시 계산하지 않는다)."""
    fs = {"number_facts": [_fact(period="2026F")]}
    ev.attach_evidence(fs, PACKET)
    assert not any(r.startswith("number_without_period") for r in ev.hard_blocks(fs))

    # 저장된 판정을 손으로 뒤집으면 게이트 결과가 따라 바뀐다 = 게이트는 저장값을 읽는다.
    fs["number_facts"][0]["validation"]["period_match"] = False
    assert any(r.startswith("number_without_period") for r in ev.hard_blocks(fs))


# ── 자릿수·부호·기간 정확도 (프로덕션 실측 + 적대적 리뷰 재현) ─────────
@pytest.mark.parametrize("text,expected", [
    ("매출 3조 순익 500억", [3e12, 5e10]),
    ("3조 규모 500억 투자", [3e12, 5e10]),
    ("1조 매출 5,000억 이익", [1e12, 5e11]),
    ("목표 1조 달성 3,000억 투자", [1e12, 3e11]),
    ("영업이익 1조, 순이익 8,000억", [1e12, 8e11]),
])
def test_scale_tokens_do_not_merge_across_words(text, expected):
    """조사 목록 방식일 때 '순익'·'규모'·'달성' 처럼 조사 없는 어절이 끼면 뚫렸다.

    ★ 검증기가 원문에 없는 값을 만들어내면 그 후보가 대조를 통과시켜 거짓 검증이 된다.
    """
    got = ev.korean_scaled_numbers(text)
    assert len(got) == len(expected)
    assert all(abs(a - b) < 1 for a, b in zip(got, expected))


@pytest.mark.parametrize("text,expected", [
    ("영업이익 1조 5,791억원", 1.5791e12),
    ("매출 23조 8,265억원", 2.38265e13),
    ("1조 5천억원", 1.5e12),
])
def test_real_compound_notation_still_merges(text, expected):
    got = ev.korean_scaled_numbers(text)
    assert len(got) == 1 and abs(got[0] - expected) < 1


def test_cheonueok_is_not_read_as_thousand():
    """'3천억'은 3×10³ 이 아니라 3×10¹¹ 이다 — '천'을 홑 자릿수로 넣으면 틀린 값을 만든다."""
    assert ev.korean_scaled_numbers("3천억원") == [3e11]
    assert ev.korean_scaled_numbers("3천만원") == [3e7]


@pytest.mark.parametrize("value,quote", [
    (500.0, "5억원"),            # 백만원 단위 재무제표
    (5.0, "500만 달러"),
    (300.0, "3억 달러"),
])
def test_million_and_billion_conversions_are_verifiable(value, quote):
    """만·억·조만 허용하던 시절 한국 재무제표의 기본 단위가 통째로 미검증이었다."""
    assert ev.value_supported_by_quote(value, quote) is True


@pytest.mark.parametrize("value,quote", [
    (-15.0, "영업이익이 15% 감소했다"),
    (-15.0, "영업이익 △15%"),
    (-8.0, "출하량이 8% 하락했다"),
])
def test_korean_decrease_wording_supports_a_negative_value(value, quote):
    """한국 리포트는 감소를 부호가 아니라 서술어·삼각기호로 쓴다.

    ★ 부호 보존만 넣었을 때 정직한 감소 사실이 number_not_in_quote 로 차단됐다 —
      오탐 하나를 막고 다른 오탐을 만든 상태였다.
    """
    assert ev.value_supported_by_quote(value, quote) is True


def test_explicit_minus_is_not_flipped_back_to_positive():
    """반대 방향까지 열어주면 부호 보존이 무의미해진다."""
    assert ev.value_supported_by_quote(15.0, "전년 대비 -15% 감소했다") is False
    assert ev.value_supported_by_quote(-15.0, "영업이익이 15% 증가했다") is False


@pytest.mark.parametrize("period", [
    "2026년", "1H26", "FY26", "2026.08", "2026.07.30", "26년 상반기", "12M", "12개월",
])
def test_real_world_period_notations_are_explicit(period):
    """프로덕션 실측: 정상 값 3건이 number_without_period 로 걸렸다(12M · 2026.07.30).

    ★ 프롬프트 예시에만 기대면 모델 출력이 흔들릴 때마다 정직한 사실이 차단된다.
    """
    assert ev.period_is_explicit(period), period


@pytest.mark.parametrize("period", ["", "최근", "향후", "올해 하반기쯤", "조만간"])
def test_vague_periods_are_still_rejected(period):
    assert not ev.period_is_explicit(period), period


@pytest.mark.parametrize("text,count", [
    ("2026F 영업이익은 1조 5,791억원", 1),
    ("26년 영업이익 3조", 1),
    ("2Q26 매출 7.6조원", 1),
    ("3분기 ESS 매출은 전분기보다 약 40% 증가할 것으로 예상됩니다", 1),
    ("2026F, 지금이 시작일까요?", 0),
    ("매출 7.6조원, 영업이익 1,130억원", 2),
])
def test_period_markers_are_not_spoken_numbers(text, count):
    """리터럴 '년'만 걸러서는 2026F·2Q26·3분기를 놓쳤다.

    ★ 놓치면 두 군데가 동시에 틀어진다 — 밀도 경고 오탐, 그리고 **면제 취소 오발동**으로
      훅이 다시 빨간 깃발을 받는다(§5-4 이전으로 회귀).
    """
    assert len(ev.spoken_numbers(text)) == count


# ── chunk_id 해소 (프로덕션 실측: 19/19 이 빈 문자열이었다) ────────────
def test_chunk_id_is_resolved_by_position_not_by_model_label():
    """모델이 붙인 chunk_id 라벨을 믿지 않고 인용문이 실제로 있는 청크를 찾는다.

    ★ 프로덕션 첫 성공 초안에서 source_refs 19개 전부 chunk_id 가 빈 문자열이었다.
      인용문 19개는 모두 원문에 그대로 있었는데(대조 확인) 라벨만 안 맞아 버려진 것이다.
    """
    refs = ev.normalize_source_refs(
        [{"chunk_id": "C999", "quote": "목표주가 26만원을 유지한다"}], CHUNKS)
    assert refs[0]["chunk_id"] == "C001", "라벨이 틀려도 위치로 찾아낸다"

    refs = ev.normalize_source_refs(
        [{"chunk_id": "", "quote": "목표주가 26만원을 유지한다"}], CHUNKS)
    assert refs[0]["chunk_id"] == "C001", "라벨이 비어도 위치로 찾아낸다"


def test_quote_absent_from_source_still_has_no_chunk_id():
    """지어낸 인용에 청크를 붙여주면 안 된다 — dangling 참조 금지 규칙은 그대로다."""
    refs = ev.normalize_source_refs(
        [{"chunk_id": "C001", "quote": "원문에 없는 지어낸 문장입니다"}], CHUNKS)
    assert refs[0]["chunk_id"] == ""


def test_chunk_is_located_across_multiple_chunks():
    chunks = [{"chunk_id": "C001", "text": "첫 청크 내용입니다."},
              {"chunk_id": "C002", "text": "영업이익 1조 5,791억원을 기록했다."}]
    refs = ev.normalize_source_refs(
        [{"chunk_id": "", "quote": "영업이익 1조 5,791억원을 기록했다."}], chunks)
    assert refs[0]["chunk_id"] == "C002"
