"""Phase 3 진입 게이트 ENTRY-1~6 (코덱스 리뷰 §18, 2026-08-30).

이 여섯이 통과하기 전에는 **유료 렌더에 들어가지 않는다.**

★ 왜 골든 JSON 을 직접 물리는가: 여기 박는 것은 이론이 아니라 **실제로 관찰된 결함**이다.
  합성 fixture 로 쓰면 "이런 경우엔 잡힌다"만 증명하고, 정작 그날 그 산출물에서 잡는지는
  증명하지 못한다. 골든 두 편은 저장소에 있고(docs/review-2026-08-29/), LLM 호출 없이
  다시 판정할 수 있다.

★ 골든은 **낡은 산출물**이다. 새 계약이 요구하는 mutations 가 없어서 여전히 차단된다 —
  그것은 정상이다. 여기서 고정하는 것은 "그 결함을 코드가 **탐지하는가**"이지
  "골든이 통과하는가"가 아니다. 골든 자체는 프롬프트를 고쳐 다시 만들어야 통과한다.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from engine import (config, directive, paper_evidence,
                    visual_router as vr, visual_sequence as vs,
                    visual_sequence_contract as vc)

GOLDEN_DIR = pathlib.Path("docs/review-2026-08-29")


def _golden(name: str) -> dict:
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():                      # 산출물을 지운 체크아웃에서는 건너뛴다
        pytest.skip(f"골든 산출물 없음: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(name: str, depth: str):
    d = _golden(name)
    seqs = vs.normalize_all(d["header"].get("visual_sequences"))
    routed = vr.route_all(d["cuts"], source_depth=depth, sequences=seqs)
    return d, seqs, vc.evaluate(seqs, d["cuts"]), {r["cut_no"]: r for r in routed}


# ── ENTRY-1 — 정상 주장이 오탐 차단되지 않는다 ───────────────────────
def test_entry1_a_stale_verdict_does_not_block_a_cut():
    """★★ 골든B 컷 5·9·10·12 가 `cut_claim_not_in_source` 로 차단됐던 사고의 회귀.

    실측으로 밝혀진 원인은 대조 알고리즘이 아니라 **원장의 신선도**였다. 그 `false` 는
    커밋 c681613(연속 일치 비율 도입) 이전 코드가 DB 에 써 둔 값이고, 지금 코드로 재대조하면
    같은 주장 10개가 전부 통과한다(최저 연속 일치 0.992).

    저장된 판정은 검증 코드보다 오래 산다. 버전이 다른 판정은 **거짓이 아니라 판정 불가**다.
    """
    stale = {"claims": [{"claim_id": "C02", "source_quote": "…",
                         "validation": {"quote_verified": False, "quote_present": True,
                                        "contract_version": "2026-08-01.exact-match"}}]}
    cuts = [{"cut_no": 5, "claim_ids": ["C02"]}]
    assert directive.ungrounded_claim_cuts(cuts, stale) == []
    assert paper_evidence.block_reasons(stale) == []


def test_entry1_a_current_verdict_still_blocks():
    """게이트를 느슨하게 한 것이 아니다 — 지금 계약으로 내려진 판정에는 그대로 엄격하다."""
    fresh = {"claims": [{"claim_id": "C02", "source_quote": "지어낸 문장",
                         "validation": {"quote_verified": False, "quote_present": True,
                                        "contract_version": config.EVIDENCE_CONTRACT_VERSION}}]}
    cuts = [{"cut_no": 5, "claim_ids": ["C02"]}]
    assert directive.ungrounded_claim_cuts(cuts, fresh) == ["cut_claim_not_in_source:5"]


def test_entry1_verification_stamps_the_contract_version():
    got = paper_evidence.verify_claim(
        {"source_quote": "the quick brown fox jumps over the lazy dog", "evidence_grade": "A"},
        {"text": "… the quick brown fox jumps over the lazy dog …", "source_depth": "full_body"})
    assert got["quote_verified"] is True
    assert got["evidence_state"] == "SUPPORTED"
    assert paper_evidence.is_current(got)


def test_entry1_unverifiable_is_not_unsupported():
    """★ 확보 실패와 검증 실패를 섞으면 확보 못 한 논문이 전부 거짓말쟁이가 된다."""
    got = paper_evidence.verify_claim({"source_quote": "무언가"}, {"text": ""})
    assert got["quote_verified"] is None
    assert got["evidence_state"] == "UNVERIFIABLE_AT_CURRENT_DEPTH"


# ── ENTRY-2 — 초록이 지불하지 않는 구체 절차가 화면에 나가지 않는다 ──
def test_entry2_unsupported_protocol_detail_is_blocked():
    """★★ 골든A 컷4 의 회귀: 초록만 확보했는데 "사전 등록된 무작위 실험"을 그렸다.

    종전 설계(depth → REALITY 후퇴)는 이것을 **막지 못했다** — 후퇴한 컷도 같은 구체성을
    프롬프트에 실었다. 미디어가 아니라 구체성을 봐야 한다.
    """
    cuts = [{"cut_no": 4, "visual_prompt": "a double-blind randomized trial setup with vials"}]
    routed = [{"cut_no": 4, "detail_restrictions": ["protocol", "apparatus"]}]
    got = directive.unsupported_detail_cuts(cuts, routed, "Oxytocin increased trust behaviour.")
    assert any(r.startswith("cut_detail_not_in_source:protocol") for r in got)


def test_entry2_the_same_word_passes_when_the_source_actually_says_it():
    """★ 어휘 목록으로 막으면 **원문이 실제로 말하는 절차**까지 벌한다.

    옳게 한 것을 벌하는 게이트는 반드시 무시당한다 — 판정은 원문 대조로 한다.
    """
    cuts = [{"cut_no": 4, "visual_prompt": "a double-blind trial setup"}]
    routed = [{"cut_no": 4, "detail_restrictions": ["protocol"]}]
    src = "In this double-blind, placebo-controlled study we measured trust behaviour."
    assert directive.unsupported_detail_cuts(cuts, routed, src) == []


def test_entry2_no_source_means_no_judgement():
    """대조할 원문이 없으면 차단하지 않는다 — 판정 불가와 실패를 섞지 않는다."""
    cuts = [{"cut_no": 4, "visual_prompt": "a double-blind randomized trial"}]
    routed = [{"cut_no": 4, "detail_restrictions": ["protocol"]}]
    assert directive.unsupported_detail_cuts(cuts, routed, "") == []


def test_entry2_full_body_carries_no_restriction():
    cuts = [{"cut_no": 4, "visual_prompt": "a double-blind randomized trial"}]
    routed = [{"cut_no": 4, "detail_restrictions": []}]
    assert directive.unsupported_detail_cuts(cuts, routed, "unrelated source text") == []


# ── ENTRY-3 — 수치 포함 시퀀스는 base + precision layer ─────────────
def test_entry3_golden_b_number_cuts_keep_the_world():
    """★★ 골든B 컷9·12 가 세계 밖으로 튕겨 나갔던 사고의 회귀.

    컷9 "7분 주기가 8초 넘게 변했다" · 컷12 "초속 2.4km, 지름 40미터 분화구" —
    둘 다 시퀀스의 stage 인데 수치를 말한다는 이유로 독립 차트가 됐다.
    지금은 같은 로켓이 계속 돌고 정확한 수치는 **코드가 그린다.**
    """
    _d, _s, _gate, plans = _resolve("golden_B_v3", "full_body")
    for cut_no in (9, 12):
        plan = plans[cut_no]
        assert plan["base"] == "MECHANISM_SEQUENCE", cut_no
        assert plan["precision_layer"] == "CODE_OVERLAY", cut_no
        assert plan["stage_ref"], cut_no


def test_entry3_cost_plan_counts_the_resolved_plan_not_the_model_field():
    """★ 실측: 골든 두 편 모두 라우팅 CODE_VIZ 가 4·3 인데 cost_plan 은 0 이었다.

    비용 산정이 라우팅보다 **먼저** 돌았고, 게다가 모델이 쓴 asset_strategy 를 세고 있었다.
    ⑤ 확인 모달의 총액이 실제 계획과 다른 것을 보고 있었다는 뜻이다.
    """
    cuts = [{"cut_no": 1, "asset_strategy": "new_asset", "estimated_sec": 5,
             "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True,
                                      "precision_layer": "CODE_OVERLAY"}},
            {"cut_no": 2, "asset_strategy": "new_asset", "estimated_sec": 5,
             "resolved_visual_plan": {"base": "CODE_VIZ", "precision_layer": "",
                                      "beat_declared": True}},
            {"cut_no": 3, "asset_strategy": "new_asset", "estimated_sec": 5,
             "resolved_visual_plan": {"base": "REALITY", "precision_layer": "",
                                      "beat_declared": True}}]
    plan = directive.compute_cost_plan(cuts, "standard", "photo")
    assert plan["code_viz_count"] == 2          # 정밀 레이어도 코드 렌더다


# ── ENTRY-4 — 잘못된 state lineage 를 코드가 탐지한다 ────────────────
def test_entry4_golden_b_s6_lineage_is_detected():
    """★★ 골든B `S6_BENCHMARK` 는 `continuity_from=S1_APPROACH` 인데 state_before 에
    "Cratered surface after impact" 를 적었다. **S1 에는 분화구가 없다.**

    종전 게이트는 continuity_from 이 실재하는지만 봤으므로 그대로 통과시켰다.
    """
    _d, _s, gate, _p = _resolve("golden_B_v3", "full_body")
    assert any(r.startswith("vseq_state_lineage_mismatch") and "S6_BENCHMARK" in r
               for r in gate["block_reasons"]), gate["block_reasons"]


def test_entry4_declaring_absence_is_not_a_lineage_claim():
    """★ 반대 방향의 오탐 방지: `"not present"` 는 물려받겠다는 주장이 아니라
    앞 stage 에 없었다는 서술이다(골든A S5·S6 가 옳게 그렇게 썼다)."""
    assert vs._is_absence("not present") and vs._is_absence("없음")
    assert not vs._is_absence("Cratered surface after impact.")


def test_entry4_an_unchanged_background_entity_is_not_a_lineage_error():
    """★★ 골든B **재생성**이 드러낸 내 오탐(2026-08-30). 실측 없이는 못 찾았을 것이다.

    `compute_lineage` 를 빈 상태에서 시작하게 만들었더니 **세계에 있지만 변하지 않는
    개체가 원장에서 사라졌다.** S1 이 달 표면을 배경으로 선언했는데 변이는 로켓에만
    걸어서, 계산된 상태에 달이 없어졌다. 그래서 뒤 stage 세 개가 "달을 물려받았다"고
    적었다는 이유로 **정상인데 차단**됐다.

    물려받을 것이 없는 stage 에서는 모델의 선언이 유일한 근거다 — 그것을 시작 상태로 삼는다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"},
           "entities": [{"entity_id": "ROCKET", "visual_identity": "a rocket stage"},
                        {"entity_id": "MOON", "visual_identity": "the lunar surface"}],
           "stages": [
               # 달은 배경으로 선언되지만 변하지 않는다 — 그래도 세계에 **있다**.
               {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
                "observable_change": "로켓이 달에 다가온다", "entity_refs": ["ROCKET", "MOON"],
                "state_before": {"ROCKET": "distant", "MOON": "large background"},
                "mutations": [{"entity_id": "ROCKET", "operation": "MOVE",
                               "visible_change": True, "result_state": "closer"}]},
               {"stage_id": "S2", "cut_refs": [2], "claim_ids": ["C2"],
                "continuity_mode": "CONTINUE_WORLD", "continuity_from": "S1",
                "observable_change": "궤적이 그려진다", "entity_refs": ["ROCKET", "MOON"],
                # 변하지 않은 달을 그대로 적는다 — 이건 정상이다.
                "state_before": {"ROCKET": "closer", "MOON": "large background"},
                "mutations": [{"entity_id": "MOON", "operation": "HIGHLIGHT",
                               "visible_change": True, "result_state": "impact point lit"}]}]}
    got = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}, {"cut_no": 2}])
    assert not any(r.startswith("vseq_state_lineage_mismatch")
                   for r in got["block_reasons"]), got["block_reasons"]


def test_entry4_returning_to_a_world_cannot_bring_back_what_was_not_there():
    """★ 반대 방향은 그대로 잡는다: 앞 세계로 **되돌아가면서** 거기 없던 것을 데려올 수 없다.

    골든B 재생성의 S6 가 실제 사례다 — S1 의 세계로 돌아가면서 S2 에서야 생긴 궤적선을
    이미 있는 것처럼 적었다. 오탐 둘을 없애면서 이것까지 놓치면 고친 의미가 없다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"},
           "entities": [{"entity_id": "ROCKET", "visual_identity": "a rocket"},
                        {"entity_id": "LINE", "visual_identity": "a trajectory line"}],
           "stages": [
               {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
                "observable_change": "로켓이 다가온다", "entity_refs": ["ROCKET"],
                "state_before": {"ROCKET": "distant"},
                "mutations": [{"entity_id": "ROCKET", "operation": "MOVE",
                               "visible_change": True, "result_state": "closer"}]},
               {"stage_id": "S2", "cut_refs": [2], "claim_ids": ["C2"],
                "continuity_mode": "CONTINUE_WORLD", "continuity_from": "S1",
                "observable_change": "궤적선이 나타난다", "entity_refs": ["ROCKET", "LINE"],
                "state_before": {"ROCKET": "closer"},
                "mutations": [{"entity_id": "LINE", "operation": "APPEAR",
                               "visible_change": True, "result_state": "traced back"}]},
               # S1 로 되돌아가는데 S1 에 없던 LINE 을 이미 있는 것처럼 적었다.
               {"stage_id": "S3", "cut_refs": [3], "claim_ids": ["C3"],
                "continuity_mode": "RETURN_WORLD", "continuity_from": "S1",
                "observable_change": "기준선이 강조된다", "entity_refs": ["LINE"],
                "state_before": {"LINE": "multiple faint lines"},
                "mutations": [{"entity_id": "LINE", "operation": "HIGHLIGHT",
                               "visible_change": True, "result_state": "one stands out"}]}]}
    got = vc.evaluate(vs.normalize_all([seq]),
                      cuts=[{"cut_no": 1}, {"cut_no": 2}, {"cut_no": 3}])
    assert any(r.startswith("vseq_state_lineage_mismatch") and "S3" in r
               for r in got["block_reasons"]), got["block_reasons"]


# ── ENTRY-5 — 미선언 state entity 를 코드가 잡는다 ──────────────────
def test_entry5_golden_a_s5_undeclared_entities_are_detected():
    """★★ 골든A `S5` 는 state_after 에 `FEMALE_CHARACTER_SILHOUETTE` 와
    `HIGH_TRUST_MALE_SILHOUETTE` 를 등장시키는데 entities 에 선언이 없다.

    종전 검사는 `entity_refs` 만 봤으므로 S6 만 잡고 이것은 놓쳤다 —
    **선언 없는 인물이 화면에 나온다**는 뜻이고, stage 마다 다른 얼굴로 그려진다.
    """
    _d, _s, gate, _p = _resolve("golden_A_v3", "abstract_only")
    assert any(r.startswith("vseq_state_entity_undeclared") and "S5_LimitationScope" in r
               for r in gate["block_reasons"]), gate["block_reasons"]


def test_entry5_the_check_covers_refs_state_and_mutations():
    stage = {"entity_refs": ["A"], "state_before": {"B": "x"}, "state_after": {"C": "y"},
             "mutations": [{"entity_id": "D"}]}
    assert vs.stage_entity_ids(stage) == {"A", "B", "C", "D"}


# ── ENTRY-6 — CTA 컷이 시퀀스 소속만으로 기전이 되지 않는다 ──────────
def test_entry6_golden_b_cta_cut_is_not_a_mechanism_cut():
    """★★ 골든B 컷15 는 "댓글로 의견을 남겨주세요"인데 `in_visual_sequence` 하나로
    MECHANISM_SEQUENCE 가 됐다. 사실 주장을 지불하지 않는 컷에는 기전 도해를 붙일 근거가 없다.

    다만 세계 참조는 남긴다 — 배경 연속성까지 끊으면 CTA 만 다른 세계에서 뜬다.
    """
    _d, _s, _gate, plans = _resolve("golden_B_v3", "full_body")
    plan = plans[15]
    assert plan["base"] != "MECHANISM_SEQUENCE"
    assert "connective_in_world" in plan["reasons"]
    assert plan["world_ref"]                   # 배경은 이어진다


# ── 지표 의미 (코덱스 리뷰 §16) ─────────────────────────────────────
def test_metrics_use_structure_not_the_model_label():
    """★ 골든B 는 `sequence_role=RESULT_SEQUENCE` 라 종전 지표가 `mechanism_sequences: 0`
    을 냈다 — 같은 지시서에서 라우터는 7컷을 기전 시퀀스로 판정하고 있었는데도.
    라우터만 고치고 지표를 안 고치면 같은 지시서가 서로 다른 답을 낸다.
    """
    _d, _s, gate, _p = _resolve("golden_B_v3", "full_body")
    m = gate["metrics"]
    assert m["mechanism_sequences"] == 1        # 구조로 보면 진행한다
    assert m["declared_mechanism_role"] == 0    # 모델 라벨은 아니라고 했다 — 진단용으로만 남는다


def test_metric_names_match_what_they_measure():
    """★ 골든A 는 `persistent_entity_ratio = 1.0` 인데 미선언 개체가 실재했다.
    그 지표가 재던 것은 "선언된 개체를 참조한 stage 비율"이었지 "등장한 개체가 선언된
    비율"이 아니었다. 둘로 나누고 이름을 맞춘다.
    """
    _d, _s, gate, _p = _resolve("golden_A_v3", "abstract_only")
    m = gate["metrics"]
    assert "persistent_entity_ratio" not in m
    assert m["declared_entity_lock_ratio"] == 1.0        # 모든 stage 가 개체를 참조하긴 했다
    assert m["stage_entity_resolution_rate"] < 1.0       # 그런데 선언 안 된 개체가 있다


# ── 리뷰가 틀렸던 지적 — 게이트를 고치지 않는다 ──────────────────────
def test_negative_wording_is_already_scrubbed_and_stays_scrubbed():
    """★ 코덱스 리뷰 §13 은 골든A 컷5·6 이 `"No on-screen text."` 라는 **금지문 때문에**
    오탐 차단됐다고 봤다. 대조해 보니 사실이 아니다 — 부정문 스크럽은 이미 있고 동작한다.

    실제 사유는 컷5 프롬프트의 `15%`("a stack of coins that is visibly 15% taller")와
    컷6 motion_prompt 의 `bar chart` 였다. **둘 다 진짜 위반이다.**
    이 테스트는 두 가지를 동시에 못박는다: 부정문은 계속 통과하고, 진짜 요구는 계속 잡힌다.
    """
    from engine import photo_contract as pc
    ok = {"visual_prompt": "two figures at a table. No on-screen text, labels or charts.",
          "motion_prompt": ""}
    assert not pc._FORBIDDEN_SCREEN.search(pc._text_of(ok))
    assert not pc._FORBIDDEN_NUMBER_ON_SCREEN.search(pc._text_of(ok))

    bad_ratio = {"visual_prompt": "a stack of coins that is visibly 15% taller. No on-screen text.",
                 "motion_prompt": ""}
    assert pc._FORBIDDEN_NUMBER_ON_SCREEN.search(pc._text_of(bad_ratio))

    bad_chart = {"visual_prompt": "No on-screen text.",
                 "motion_prompt": "icons merge into the bar chart columns"}
    assert pc._FORBIDDEN_SCREEN.search(pc._text_of(bad_chart))


# ── 적대적 자기리뷰(코덱스 리뷰 §23)에서 스스로 찾은 구멍 셋 ─────────
def test_q1_declaring_a_mutation_that_changes_nothing_is_not_progression():
    """★ Q1 "모델이 다른 문자열만 넣으면 progression 을 속일 수 있는가"

    `visible_change: true` 는 여전히 **모델의 자기보고**다. 그래서 마지막에 코드가 계산한
    상태 두 벌을 한 번 더 본다 — 여기에는 모델이 개입할 수 없다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"},
           "entities": [{"entity_id": "A", "visual_identity": "a box"}],
           "stages": [
               {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
                "observable_change": "상자가 열린다", "entity_refs": ["A"],
                "mutations": [{"entity_id": "A", "operation": "MOVE",
                               "visible_change": True, "result_state": "open"}]},
               # 같은 결과 상태를 다시 선언한다 — 화면은 그대로다.
               {"stage_id": "S2", "cut_refs": [2], "claim_ids": ["C2"],
                "continuity_mode": "MUTATE_STATE", "continuity_from": "S1",
                "observable_change": "상자가 여전히 열려 있다", "entity_refs": ["A"],
                "mutations": [{"entity_id": "A", "operation": "MOVE",
                               "visible_change": True, "result_state": "open"}]}]}
    got = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}, {"cut_no": 2}])
    assert any(r.startswith("vseq_no_progression") and "S2" in r
               for r in got["block_reasons"]), got["block_reasons"]


def test_q3_literal_observation_needs_a_source_that_pays_for_it():
    """★ Q3 "claim_id 만 맞으면 잘못된 depiction 이 통과하는가"

    골든B 분광이 사례다 — 주장(C03)은 원문이 지지하지만 원문은 **지상 관측**인데 화면은
    우주에서 로켓에 빛을 쏘는 그림이었다. claim 은 맞고 묘사가 틀린 환각이다.

    코드가 "이 그림이 그 관측을 옳게 그렸는가"를 판정할 수는 없다. 판정할 수 있는 것은
    **그렇게 주장할 자격이 있는가**다 — 초록은 "어떻게 봤는가"를 말하지 않는다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "REALITY_ANCHOR",
           "world": {"world_id": "W"}, "entities": [],
           "stages": [{"stage_id": "S1", "cut_refs": [1],
                       "representation_mode": "LITERAL_OBSERVATION",
                       "observable_change": "x", "claim_ids": ["C1"]}]}
    blocked = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}],
                          source_depth="abstract_only")
    assert any(r.startswith("vseq_literal_without_source")
               for r in blocked["block_reasons"]), blocked["block_reasons"]

    allowed = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}],
                          source_depth="full_body")
    assert not any(r.startswith("vseq_literal_without_source")
                   for r in allowed["block_reasons"])


def test_q3_schematic_is_always_allowed():
    """★ 반대 방향: 도식은 실제 장면이라고 주장하지 않는다 — 근거 깊이와 무관하게 허용."""
    seq = {"sequence_id": "SEQ1", "sequence_role": "REALITY_ANCHOR",
           "world": {"world_id": "W"}, "entities": [],
           "stages": [{"stage_id": "S1", "cut_refs": [1],
                       "representation_mode": "SCHEMATIC_PRINCIPLE",
                       "observable_change": "x", "claim_ids": ["C1"]}]}
    got = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}],
                      source_depth="abstract_only")
    assert not any(r.startswith("vseq_literal_without_source") for r in got["block_reasons"])


def test_q4_legacy_role_and_resolved_plan_disagreement_is_surfaced():
    """★ Q4 "legacy photo gate 와 v3 plan 이 서로 다른 결론을 낼 수 있는가"

    낼 수 있다. R3 으로 정본을 하나로 모았지만 옛 필드는 하위호환으로 남아 있고, 렌더·화면
    계약이 아직 그것을 읽는 자리가 있다. 둘이 어긋나면 **어느 쪽이 화면에 나갈지 우리가 모른다.**

    차단하지 않는다 — 어긋남 자체가 잘못은 아니고(모델의 역할 라벨과 코드의 base 는 기준이
    다르다), 운영자에게 보이게 하는 것이 목적이다. 정본이 무엇인지는 코드가 이미 정했다.
    """
    cuts = [{"cut_no": 1, "visual_role": "MECHANISM"}]
    routed = [{"cut_no": 1, "base": "REALITY", "beat_declared": True}]
    got = vc.route_contract_conflicts(cuts, routed)
    assert got and got[0].startswith("vseq_route_contract_conflict:1")


def test_q4_no_conflict_when_the_model_never_declared_a_beat():
    """★ beat 를 안 쓴 옛 지시서의 base 는 **합성된 기본값**이다 — 그것을 충돌로 세면
    만화식 지시서 전체가 경고로 뒤덮인다(비용 산정에서 같은 실수를 이미 한 번 했다)."""
    cuts = [{"cut_no": 1, "visual_role": "MECHANISM"}]
    routed = [{"cut_no": 1, "base": "REALITY", "beat_declared": False}]
    assert vc.route_contract_conflicts(cuts, routed) == []


# ── 소스에 보이지 않는 제어문자가 들어오지 않는다 ────────────────────
def test_no_control_characters_in_engine_sources():
    """★ 2026-08-30 실측: 패치 도구가 정규식의 워드 경계 이스케이프를 **백스페이스
    (0x08)** 로 바꿔 놓아 `photo_contract._TEXT_REQUEST` 가 조용히 아무것도 매치하지
    않았다. 소스를 grep 해도 보이지 않는다 — 화면에는 정상으로 보인다.

    이 저장소는 워드 경계로 이미 두 번 사고를 냈다(photo_contract·visual_sequence_contract
    의 `%` 뒤 경계). 원인은 달라도 결과는 같다: **게이트가 조용히 죽는다.**

    ★ 검사할 문자는 chr() 로 만든다 — 리터럴로 쓰면 이 파일 자신이 위반이 된다.
    """
    banned = {name: chr(code) for name, code in
              (("BEL", 7), ("BS", 8), ("VT", 11), ("FF", 12), ("ESC", 27))}
    bad = []
    for root in ("engine", "tests"):
        for path in pathlib.Path(root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name, ch in banned.items():
                if ch in text:
                    bad.append(f"{path}: {name}")
    assert not bad, bad


# ── 여는 stage 의 세계 내용물이 원장에서 증발하던 오탐 (2026-09-02 실측) ──
#
# ★ 8/30 에 "안 변하는 배경이 사라진다"를 고치면서 씨앗을 state_before 로 잡았는데,
#   **여는 stage 의 state_before 는 비는 것이 자연스럽다**(앞에 아무것도 없다).
#   실측(Moon Impactor 실제 초안): S1 이 before={} after={MOON, FALCON9} 로 쓰자
#   MOON 이 계산 상태에서 사라졌고, S5 가 달을 물려받았다고 옳게 적었는데 차단됐다.
#   같은 오탐이 여는 stage 에서 재발한 것이다.

def test_opening_stage_world_survives_when_declared_only_in_state_after():
    """여는 stage 가 state_after 로만 선언한 개체도 뒤 stage 가 물려받을 수 있다."""
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"},
           "entities": [{"entity_id": "ROCKET", "visual_identity": "a rocket stage"},
                        {"entity_id": "MOON", "visual_identity": "the lunar surface"}],
           "stages": [
               {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
                "observable_change": "로켓이 나타난다", "entity_refs": ["ROCKET", "MOON"],
                "state_before": {},                       # ← 여는 stage 라 비어 있다
                "state_after": {"ROCKET": "orbiting", "MOON": "intact surface"},
                "mutations": [{"entity_id": "ROCKET", "operation": "APPEAR",
                               "property": "presence", "visible_change": "로켓이 등장한다"}]},
               {"stage_id": "S2", "cut_refs": [2], "claim_ids": ["C1"],
                "continuity_mode": "CONTINUE_WORLD", "continuity_from": "S1",
                "observable_change": "달에 분화구가 생긴다", "entity_refs": ["ROCKET", "MOON"],
                "state_before": {"MOON": "intact surface"},   # ← S1 이 state_after 로만 선언
                "state_after": {"MOON": "surface with a crater"},
                "mutations": [{"entity_id": "MOON", "operation": "TRANSFORM",
                               "property": "surface", "visible_change": "분화구가 파인다"}]},
           ]}
    seqs = vs.compute_lineage([seq])
    assert "MOON" in seqs[0]["stages"][0]["state_after_computed"], "여는 stage 의 세계가 증발했다"
    res = vc.evaluate(seqs, source_depth="full_body")
    assert not [r for r in res["block_reasons"] if r.startswith("vseq_state_lineage_mismatch")], \
        res["block_reasons"]


def test_the_seed_does_not_overwrite_what_mutations_decided():
    """★ 채우는 것은 **빈 자리뿐**이다 — 진행 판정은 여전히 mutations 가 한다.

    state_after 가 mutations 를 덮으면 모델의 자기보고가 변이를 이기게 된다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"},
           "entities": [{"entity_id": "ROCKET", "visual_identity": "a rocket"}],
           "stages": [
               {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
                "observable_change": "등장", "entity_refs": ["ROCKET"],
                "state_before": {},
                "state_after": {"ROCKET": "모델이 쓴 서술"},
                "mutations": [{"entity_id": "ROCKET", "operation": "APPEAR",
                               "property": "presence", "visible_change": "변이가 정한 상태"}]},
           ]}
    after = vs.compute_lineage([seq])[0]["stages"][0]["state_after_computed"]
    assert "모델이 쓴 서술" not in str(after["ROCKET"]), "자기보고가 변이를 덮었다"


# ── 세계가 화면이면 그 시퀀스 전체가 UI 가 된다 (2026-09-03 실측) ──
#
# ★★ 이것이 "컷이 아니라 시퀀스로 운영한다"의 실제 의미다(운영자 지적).
#   실사형 지시서의 세계 5개 중 3개가 화면이었다:
#     AD_CREATION_INTERFACE / SOCIAL_MEDIA_FEED / HUMAN_AI_COLLABORATION_SPACE
#   컷 단위 금지어를 세 번 조였는데(글자 → 아이콘 → 게이지) 매번 다른 회피가 나온 이유가
#   이것이다 — 컷은 **선언된 세계를 충실히 그렸을 뿐**이고 결정은 시퀀스에서 끝나 있었다.
#   등급제가 "품질 의도는 시퀀스, 실행은 컷"이라 말하는 그대로 **금지도 시퀀스에 건다.**

_SCREEN_WORLDS = [
    ("AD_CREATION_INTERFACE", "Clean, futuristic digital interface for ad creation"),
    ("SOCIAL_MEDIA_FEED", "Dynamic, clean social media feed interface"),
    ("HUMAN_AI_COLLABORATION_SPACE", "Abstract, clean digital space with interconnected nodes"),
]
_PHYSICAL_WORLDS = [
    ("RESEARCH_LAB", "Clean, organized research laboratory with modern equipment"),
    ("FACTORY_FLOOR", "Industrial factory floor, workers at stations"),
    ("BATTERY_CUTAWAY", "Sectioned battery cell, layers exposed"),
    ("CELL_SCREENING_BENCH", "Lab bench with screening plates"),   # 'screening' 은 화면이 아니다
]


def test_screen_worlds_are_blocked():
    for wid, style in _SCREEN_WORLDS:
        seq = {"sequence_id": wid, "world": {"world_id": wid, "style": style}}
        assert vc.screen_world_reasons([seq]), f"화면 세계를 놓친다: {wid}"


def test_physical_worlds_pass():
    """★ 오탐 방지 — 실사형이 **권장하는** 세계를 막으면 게이트가 통째로 불신된다."""
    for wid, style in _PHYSICAL_WORLDS:
        seq = {"sequence_id": wid, "world": {"world_id": wid, "style": style}}
        assert not vc.screen_world_reasons([seq]), f"오탐: {wid}"


def test_the_whole_world_block_is_searched_not_just_the_id():
    """world_id 만 보면 style 에만 화면을 적은 경우를 놓친다.

    ★ 예시를 바꿨다(2026-09-03 2차): 처음엔 `MEETING_ROOM` + "dashboard overlay" 로 썼는데,
      두 층 규칙이 들어오면서 `room` 이 물리 앵커라 정당하게 통과하게 됐다. 검사하려던 것은
      "모든 필드를 보는가"이므로 앵커 없는 예시로 바꾼다 — 규칙이 아니라 예시가 문제였다.
    """
    seq = {"sequence_id": "S", "world": {"world_id": "SCENE_A",
                                         "style": "a clean social media feed interface"}}
    assert vc.screen_world_reasons([seq])


def test_a_missing_world_is_not_a_reason():
    """판정 불가를 실패로 만들지 않는다(이 저장소의 규율)."""
    assert vc.screen_world_reasons([{"sequence_id": "S"}]) == []
    assert vc.screen_world_reasons([{"sequence_id": "S", "world": {}}]) == []


def test_the_prompt_says_the_world_must_be_physical():
    """게이트만 있고 프롬프트가 침묵하면 모델은 매번 걸리고 나서야 안다."""
    g = directive.VERSION_GUIDANCE["photo"]
    assert "세계는 물리적 장소다" in g
    assert "화면 속을 세계로 잡지 마라" in g
    assert "주제가 추상적일수록" in g            # 대안을 준다


def test_the_prompt_handles_screens_as_subject_matter():
    """★ 소재가 화면인 연구(광고·앱·소셜미디어)에서 대부분 틀린다.

    실측(2026-09-03): 이 논문은 'AI가 만든 광고를 소셜미디어에 집행'하는 연구라
    모델이 SOCIAL_MEDIA_FEED·AD_CREATION_INTERFACE 를 세계로 잡았다 — 소재로는 맞지만
    실사형에서는 통째로 UI 렌더가 된다. 처방은 금지가 아니라 **자리를 바꾸는 것**이다:
    화면은 세계가 아니라 **세계 안의 물건**(손에 든 폰)이다.
    """
    g = directive.VERSION_GUIDANCE["photo"]
    assert "소재 자체가 화면일 때" in g
    assert "화면을 보는 사람과 자리" in g
    assert "세계 안의 물건" in g


def test_plural_screen_words_are_caught():
    """★ 회귀(2026-09-03 실측): 복수형을 빠뜨려 화면 세계가 그대로 샜다.

    "a grid of digital ad displays… highlighting the screens" 가 통과했다 —
    목록에 `screen`·`display` 만 있고 `screens`·`displays` 가 없었다.
    화면 세계는 대개 **여럿**으로 쓰인다.
    """
    for style in ("clean minimalist grid of digital ad displays",
                  "soft light highlighting the screens",
                  "several interfaces side by side",
                  "modern workspace with a central holographic display"):
        seq = {"sequence_id": "S", "world": {"world_id": "W", "style": style}}
        assert vc.screen_world_reasons([seq]), f"놓친다: {style}"


def test_a_screen_as_an_object_in_a_physical_place_passes():
    """★★ 처방의 핵심 — 화면은 세계가 아니라 **세계 안의 물건**이면 된다.

    실측: 프롬프트 처방 뒤 모델이 LAB_CUBICLES("각 자리에 컴퓨터가 놓인 연구실 큐비클")를
    냈다. 컴퓨터가 있지만 세계는 물리적 장소다 — 이건 통과해야 한다.
    이게 막히면 처방을 따른 결과를 벌하는 게이트가 된다.
    """
    seq = {"sequence_id": "S", "world": {
        "world_id": "LAB_CUBICLES",
        "style": "clean, modern research lab with individual cubicles, each with a computer setup",
        "background": "rows of similar cubicles fading into the distance"}}
    assert vc.screen_world_reasons([seq]) == []


# ── 세계 검사 두 층 (2026-09-03 2차 실측) ──
#
# ★★ 한 덩어리로 막았더니 **처방을 따른 결과를 벌했다.** 모델이
#   SOCIAL_MEDIA_OFFICE("사람들이 일하는 오픈플랜 사무실, 화면 여러 대")를 냈는데
#   `screens` 하나로 차단됐다. 그건 물리적 사무실이고 화면은 그 안의 집기다 —
#   내가 프롬프트에 쓴 처방("화면은 세계가 아니라 세계 안의 물건") 그대로다.
#   게이트가 그걸 막으면 모델은 올바른 답을 내고도 계속 틀렸다는 신호를 받는다.

def _w(wid, **kw):
    return {"sequence_id": wid, "world": {"world_id": wid, **kw}}


def test_screens_inside_a_physical_place_pass():
    """SOFT — 물리적 앵커(사무실·사람)가 있으면 화면은 집기다."""
    seq = _w("SOCIAL_MEDIA_OFFICE",
             style="Modern, bustling social media marketing office, with multiple screens and people collaborating.",
             background="Open-plan office with people working on computers")
    assert vc.screen_world_reasons([seq]) == []


def test_a_world_that_is_only_a_screen_is_blocked():
    """SOFT — 앵커가 없으면 그 세계는 화면 속이라는 뜻이다."""
    seq = _w("SOCIAL_MEDIA_FEED",
             style="Dynamic, clean social media feed interface",
             background="Blurred digital background, suggesting a user's device")
    assert vc.screen_world_reasons([seq])


def test_abstract_and_virtual_spaces_are_blocked_even_with_people():
    """★ HARD — 공간 자체가 물리적이지 않으면 사람이 있어도 실사가 아니다.

    홀로그램·가상공간은 지어낸 것이라 실사형이 성립하지 않는다.
    """
    for wid, style, bg in [
        ("VIRTUAL_COLLABORATION_SPACE",
         "Clean minimalist 3D environment with glowing lines connecting elements", ""),
        ("COLLABORATION_HUB",
         "modern collaborative workspace with a central holographic display",
         "blurred figures of people collaborating"),
        ("HUMAN_AI_SPACE", "Abstract, clean digital space with interconnected nodes", ""),
    ]:
        assert vc.screen_world_reasons([_w(wid, style=style, background=bg)]), wid


def test_the_hard_layer_wins_over_the_anchor():
    """앵커가 있어도 HARD 는 막는다 — 한 시퀀스가 두 사유를 내지는 않는다."""
    seq = _w("HOLO_LAB", style="research laboratory with a holographic display and people")
    r = vc.screen_world_reasons([seq])
    assert len(r) == 1 and "holographic" in r[0]


def test_the_prompt_gives_physical_alternatives_for_comparison_passages():
    """★ 실측 5회 내내 '비교'와 '결론' 대목이 화면으로 갔다(그래프·게이지·피드).

    금지만 있고 대안이 없으면 모델은 계속 그쪽으로 간다 — 이 저장소가 라벨에서 이미
    배운 것이다("금지만 있고 대안이 없으면 너는 결국 이미지에 글자를 굽게 된다").
    연구가 실제로 만들어 낸 물건(인쇄물·폰 두 대·쌓인 더미)을 준다.
    """
    g = directive.VERSION_GUIDANCE["photo"]
    assert "비교·결론 대목의 실물 대안" in g
    assert "인쇄물 두 장을 나란히" in g
    assert "라벨 없이 차이만" in g          # 오버레이가 말한다


def test_the_prompt_shows_a_passing_world_example():
    """★ 통과하는 예를 같이 줘야 한다 — 금지 목록만 주면 어디까지가 안전한지 모른다."""
    g = directive.VERSION_GUIDANCE["photo"]
    assert "화면이 집기로 들어간 세계는 통과한다" in g


def test_printed_material_must_not_carry_charts():
    """★ 실측(2026-09-03): 인쇄물 처방을 따랐는데 그 위에 도표를 얹었다.

    "a printed report, with charts and data (no legible text) visible on the pages"
    → 폐기. '읽을 수 없게'를 덧붙여도 생성 모델은 그 단서를 못 지키고, 지켜도 가짜 도표다.
    처방을 조이는 것이지 게이트를 푸는 것이 아니다(이 저장소의 자세).
    """
    g = directive.VERSION_GUIDANCE["photo"]
    assert "인쇄물을 쓸 때 그 위에 도표를 그리지 마라" in g
    assert "글자 블록의 결" in g          # 대신 무엇을 보여줄지
    assert "종이가 몇 장인지" in g         # 그것이 곧 비교다
