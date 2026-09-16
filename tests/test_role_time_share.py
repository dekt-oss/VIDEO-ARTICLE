"""역할별 화면시간 Phase A (2026-09-09, 외부 리뷰 GO WITH CHANGES 반영).

★ 이 파일이 지키는 계약 셋:
  ① 역할 비중은 **지표만**이다 — 문턱도 차단도 없다.
     `evidence_role` 은 모델 자기보고이고 코드가 내용을 검증하지 않으므로, 문턱을 걸면
     내용을 그대로 두고 라벨만 바꿔 통과할 수 있다.
  ② 그래서 **라벨 정합 검사**가 먼저 선다. 명백한 거짓 라벨만 잡고, 애매하면 넘어간다.
  ③ **경고도 재생성을 한 번 띄운다.** 종전에는 `photo_subject_dominates` 가 정확한 처방을
     갖고도 모델에게 전달되지 않았다(차단이 없으면 되먹임이 빈 문자열이었다).
"""

from __future__ import annotations

import pytest

from engine import config, directive as dv, photo_contract as pc


def _cut(no: int, role: str, sec: int = 5, claims: list[str] | None = None) -> dict:
    return {"cut_no": no, "evidence_role": role, "estimated_sec": sec,
            "visual_role": "REALITY", "visual_prompt": "a bench",
            "claim_ids": claims or []}


# ─────────────────────────────────────────────────────────────
# ① 지표는 재기만 한다
# ─────────────────────────────────────────────────────────────
def test_shares_are_measured():
    cuts = [_cut(1, "primary_result", 10), _cut(2, "scope", 6), _cut(3, "method", 4),
            _cut(4, "mechanism", 20)]
    s = pc.role_time_shares(cuts)
    assert s["reference_role_share"] == 0.25          # (6+4)/40
    assert s["mechanism_share"] == 0.5                # 20/40
    assert s["first_mechanism_start_share"] == 0.5    # 앞 20초 뒤에 시작


def test_no_mechanism_gives_none_not_zero():
    """★ '기전이 없다'와 '0초에 시작한다'는 다르다 — 섞으면 규칙이 거꾸로 돈다."""
    s = pc.role_time_shares([_cut(1, "scope", 10)])
    assert s["first_mechanism_start_share"] is None
    assert s["mechanism_share"] == 0.0


def test_empty_cuts_do_not_divide_by_zero():
    s = pc.role_time_shares([])
    assert s["reference_role_share"] == 0.0 and s["first_mechanism_start_share"] is None


def test_the_shares_reach_evaluate_stats_but_never_block():
    """★★ 이것이 v1 에서 v2 로 바뀐 핵심이다 — 재되 막지 않는다."""
    cuts = [_cut(1, "scope", 30), _cut(2, "connective", 30), _cut(3, "primary_result", 5)]
    res = pc.evaluate({"visual_sequences": []}, cuts, None)
    assert res["stats"]["reference_role_share"] > 0.9
    assert not any("reference_role" in r for r in res["block_reasons"]), res["block_reasons"]
    assert not any("mechanism_share" in r for r in res["block_reasons"])


# ─────────────────────────────────────────────────────────────
# ② 라벨 정합 — 명백한 거짓만
# ─────────────────────────────────────────────────────────────
_FS = {"claims": [
    {"claim_id": "C01", "claim_kind": "main_result", "population": "20개월령 생쥐"},
    {"claim_id": "C03", "claim_kind": "mechanism"},
    {"claim_id": "C07", "claim_kind": "number", "effect_size": "92"},
]}


def test_a_laundered_mechanism_label_is_caught():
    """★★ 이것이 자기보고 라벨의 구멍이다 — scope 내용을 mechanism 이라 부르면 지표 셋이
    동시에 좋아진다. 연결된 claim 이 기전을 말하지 않으면 그 라벨은 거짓이다."""
    got = pc.role_claim_mismatches([_cut(5, "mechanism", claims=["C01"])], _FS)
    assert got == ["컷5(mechanism)"], got


def test_an_honest_mechanism_label_passes():
    assert pc.role_claim_mismatches([_cut(5, "mechanism", claims=["C03"])], _FS) == []


def test_magnitude_passes_on_either_kind_or_effect_size():
    assert pc.role_claim_mismatches([_cut(4, "magnitude", claims=["C07"])], _FS) == []
    assert pc.role_claim_mismatches([_cut(4, "magnitude", claims=["C01"])], _FS) != []


def test_scope_passes_when_the_claim_carries_a_population():
    assert pc.role_claim_mismatches([_cut(5, "scope", claims=["C01"])], _FS) == []


def test_a_cut_without_claim_links_is_unverifiable_not_a_violation():
    """★★ 판정 불가와 위반을 섞지 않는다 — 이 저장소의 일관된 자세."""
    assert pc.role_claim_mismatches([_cut(5, "mechanism", claims=[])], _FS) == []
    assert pc.role_claim_mismatches([_cut(5, "mechanism", claims=["C99"])], _FS) == []


def test_without_a_fact_sheet_nothing_is_judged():
    assert pc.role_claim_mismatches([_cut(5, "mechanism", claims=["C01"])], None) == []


def test_roles_outside_the_table_are_not_judged():
    """★ 표에 없는 역할(implication·caveat 등)은 필요조건을 정의하지 않았다 — 건드리지 않는다."""
    assert pc.role_claim_mismatches([_cut(9, "implication", claims=["C01"])], _FS) == []


def test_the_mismatch_is_a_warning_not_a_block():
    res = pc.evaluate({"visual_sequences": []},
                      [_cut(5, "mechanism", claims=["C01"])], _FS)
    assert any(r.startswith("photo_role_claim_mismatch") for r in res["warnings"])
    assert not any(r.startswith("photo_role_claim_mismatch") for r in res["block_reasons"])


# ─────────────────────────────────────────────────────────────
# ③ 첫 기전 시점 — 경고, 소재가 지불할 때만
# ─────────────────────────────────────────────────────────────
def test_late_mechanism_warns_when_the_source_supplies_it():
    cuts = [_cut(1, "primary_result", 30), _cut(2, "scope", 30), _cut(3, "mechanism", 20)]
    res = pc.evaluate({"visual_sequences": []}, cuts, _FS)
    assert any(r.startswith("photo_mechanism_starts_late") for r in res["warnings"]), \
        res["warnings"]
    assert not any(r.startswith("photo_mechanism_starts_late") for r in res["block_reasons"])


def test_no_warning_when_the_source_has_no_mechanism():
    """★★ 없는 것을 앞당기라고 할 수는 없다 — 그러면 지어내거나 영원히 실패한다."""
    fs = {"claims": [{"claim_id": "C01", "claim_kind": "main_result"}]}
    cuts = [_cut(1, "primary_result", 30), _cut(2, "scope", 30), _cut(3, "mechanism", 20)]
    res = pc.evaluate({"visual_sequences": []}, cuts, fs)
    assert not any(r.startswith("photo_mechanism_starts_late") for r in res["warnings"])


def test_an_early_mechanism_does_not_warn():
    cuts = [_cut(1, "primary_result", 5), _cut(2, "mechanism", 20), _cut(3, "scope", 55)]
    res = pc.evaluate({"visual_sequences": []}, cuts, _FS)
    assert not any(r.startswith("photo_mechanism_starts_late") for r in res["warnings"])


# ─────────────────────────────────────────────────────────────
# ④ 경고가 재생성을 띄운다 (이번 변경의 핵심)
# ─────────────────────────────────────────────────────────────
def test_a_retryable_warning_alone_produces_feedback():
    """★★ 종전에는 여기서 빈 문자열이었다 — 정확한 처방을 갖고도 모델에게 말을 안 걸었다."""
    fb = pc.feedback_prompt([], ["photo_subject_dominates:0.51"])
    assert fb.strip(), "재생성 가능 경고인데 되먹임이 비었다"
    assert "연구 대상" in fb


def test_a_non_retryable_warning_alone_stays_silent():
    """★ 모든 경고로 재생성하지 않는다 — 오탐이 재생성을 남발하면 구조가 갈아엎힌다."""
    assert pc.feedback_prompt([], ["photo_world_churn:2.2"]) == ""


def test_no_input_stays_silent():
    assert pc.feedback_prompt([], []) == ""


def test_the_quality_only_header_does_not_say_contract_violation():
    """★ "계약 위반"이라고 말하면 모델이 없는 위반을 찾아 구조를 갈아엎는다(실측:
    되먹임을 쌓았더니 재생성이 1차 3건 → 2차 14건으로 악화)."""
    fb = pc.feedback_prompt([], ["photo_subject_dominates:0.51"])
    assert "계약 위반은 없다" in fb
    assert "구조를 갈아엎지 마라" in fb


def test_the_same_warning_is_not_listed_twice():
    """처방을 준 경고를 '가능하면 함께' 목록에 또 넣으면 무엇이 중요한지 흐려진다."""
    fb = pc.feedback_prompt([], ["photo_subject_dominates:0.51"])
    assert fb.count("photo_subject_dominates") == 0, fb


@pytest.mark.parametrize("code", config.RETRYABLE_QUALITY_WARNINGS)
def test_every_retryable_warning_has_a_prescription(code: str):
    """★★ 재생성을 띄우면서 고치는 법을 안 주면 같은 결함을 반복한다."""
    fb = pc.feedback_prompt([], [f"{code}:x"])
    assert fb.strip(), code
    assert "가능하면 함께 고쳐라" not in fb.split("(경고 — 함께 고쳐라)")[-1][:60] or "-" in fb


def test_generate_treats_quality_warnings_as_a_retry_reason():
    d = {"header": {"photo_gate": {"warnings": ["photo_subject_dominates:0.51",
                                                "photo_world_churn:2.2"]},
                    "mode_warnings": []}}
    assert dv._quality_retry_reasons(d) == ["photo_subject_dominates:0.51"]


def test_mode_warnings_are_seen_too():
    """★ 코드가 고친 것들(photo_subject_dominates 등)은 mode_warnings 로도 들어온다."""
    d = {"header": {"photo_gate": {"warnings": []},
                    "mode_warnings": ["photo_hook_visual_repeated"]}}
    assert dv._quality_retry_reasons(d) == ["photo_hook_visual_repeated"]


def test_the_retry_records_whether_quality_warnings_went_down():
    """되먹인 것이 값어치를 했는지 보는 유일한 지표 — 없으면 되먹임을 고칠 근거가 없다."""
    src = open(dv.__file__, encoding="utf-8").read()
    assert '"first_quality_warnings": first_quality,' in src
    assert '"retry_quality_warnings": _quality_retry_reasons(retry),' in src


# ─────────────────────────────────────────────────────────────
# ⑤ 접기로 한 것이 실제로 없는가 (v1 → v2)
# ─────────────────────────────────────────────────────────────
def test_no_hard_block_on_role_shares():
    """★★ 리뷰 판정의 핵심 — 자기보고 라벨에 차단을 걸지 않는다."""
    assert not hasattr(config, "REFERENCE_ROLE_SHARE_BLOCK")
    assert not hasattr(config, "MECHANISM_SHARE_MIN")
    assert "photo_reference_role_dominates" not in pc.BLOCK_REASONS
    assert "photo_mechanism_share_low" not in pc.BLOCK_REASONS
    assert "photo_mechanism_cuts_missing" not in pc.BLOCK_REASONS
    assert "photo_mechanism_starts_late" not in pc.BLOCK_REASONS


def test_method_is_only_a_statistic_not_a_target():
    """★ `method` 를 참고로 세는 것은 통계용이다. 차단 대상으로 삼으면 안 된다 —
    무작위 대조인지 관찰인지는 결과 해석에 필수일 수 있다(리뷰 지적)."""
    assert "method" in config.REFERENCE_EVIDENCE_ROLES
    assert not any("reference_role" in r for r in pc.BLOCK_REASONS)


# ─────────────────────────────────────────────────────────────
# ⑥ 대본이 소재의 기전 유무를 코드에게서 듣는가
# ─────────────────────────────────────────────────────────────
def test_the_draft_is_told_when_the_source_supplies_mechanism():
    """★★ 이것이 없어서 E2 압축이 역효과를 냈다(2026-09-09 실측).

    scope 를 한 씬으로 묶어 8초를 벌었는데, 그 시간이 원리가 아니라 **결과 나열**로 갔고
    기전 비중이 28% → 0% 가 됐다. E5(작동원리)가 "원리가 핵심이면"이라는 **모델 판단**에
    맡겨져 있었기 때문이다. 지시서 단계에는 같은 성격의 블록이 이미 있었다(`[기전 컷 수]`).
    """
    from engine import scriptgen as sg

    blk = sg.mechanism_supply_block(
        {"claims": [{"claim_id": "C03", "claim_kind": "mechanism"},
                    {"claim_id": "C05", "claim_kind": "author_interpretation"}]})
    assert "C03" in blk and "C05" in blk
    assert "반드시" in blk
    assert "직후" in blk, "어디에 놓을지를 말하지 않으면 또 뒤로 몰린다"
    assert "여기에 쓴다" in blk, "아낀 시간을 어디에 쓸지 말해야 결과 나열로 안 간다"


def test_the_draft_is_told_when_the_source_has_none():
    """★ 없으면 요구하지 않는다 — 요구하면 지어내거나 영원히 못 채운다."""
    from engine import scriptgen as sg

    blk = sg.mechanism_supply_block({"claims": [{"claim_id": "C01",
                                                 "claim_kind": "main_result"}]})
    assert "말하지 않는다" in blk and "억지로" in blk
    assert "반드시" not in blk


def test_the_block_is_actually_in_the_prompt():
    """상수만 만들고 프롬프트에 안 실으면 대본은 그대로다."""
    from engine import scriptgen as sg

    fs = {"claims": [{"claim_id": "C03", "claim_kind": "mechanism"}]}
    assert "[작동원리 소재]" in sg.script_user_prompt(fs)


def test_the_e2_compression_rule_is_in_the_draft_prompt():
    """scope 팽창을 막는 규칙 — 실측에서 세 씬 18초를 먹던 그것."""
    from engine import scriptgen as sg

    src = open(sg.__file__, encoding="utf-8").read()
    assert "E2(대상·지역·기간)는 한 씬으로 묶어라" in src
    assert "사실을 **버리라는 것이 아니라**" in src, "사실을 지우라는 말로 읽히면 안 된다"


def test_the_retry_tie_is_broken_by_quality():
    """★ 동점일 때 품질이 나아진 쪽을 버리면 되먹임이 값어치를 못 한다(실측: 첫 기전
    64% → 50% 로 좋아진 재생성본이 차단 수 동점이라 버려졌다)."""
    src = open(dv.__file__, encoding="utf-8").read()
    assert "len(retry_reasons), len(retry_short), _retry_q" in src
