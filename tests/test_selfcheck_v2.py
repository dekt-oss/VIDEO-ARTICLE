"""자기검증 v2 — 범위·인과·숫자·수식어·편집적추론 + 커버리지·승인차단 (수정명세 §14).

기존 `all_grounded` 재계산과 같은 원칙을 확장한다: 모델의 자기 판정은 입력일 뿐 결론이 아니다.
레거시(원장 없는) 초안이 새 게이트에 걸려 막히지 않는 것도 함께 고정한다.
"""

from engine.factsheet import normalize_factsheet
from engine.selfcheck import normalize_selfcheck


def _ledger(*claims):
    return normalize_factsheet({
        "what_found": ["x"], "how": [], "numbers": [], "limitations": [], "claim_strength": "중",
        "claims": list(claims) or [
            {"claim_ko": "핵심 결과", "claim_kind": "main_result"},
            {"claim_ko": "연구 범위", "claim_kind": "scope"},
        ],
    })


def _plan(**over):
    base = {"primary_claim_id": "C01", "supporting_claim_ids": ["C02"],
            "selected_mode": "standard", "target_duration_min_sec": 36,
            "target_duration_max_sec": 50, "mode_warnings": []}
    base.update(over)
    return base


def _scene(no=1, **over):
    base = {
        "scene": no, "grounded": True, "unsupported": [], "matched_facts": [],
        "matched_claim_ids": ["C01"], "scope_match": True, "causal_calibration": "pass",
        "numeric_match": "not_applicable", "qualifier_preserved": True,
        "editorial_inference": False,
    }
    base.update(over)
    return base


def _clean():
    return {"scenes": [_scene(1), _scene(2, matched_claim_ids=["C02"])], "all_grounded": True}


def _covered(**flags):
    """커버리지는 완전하고(C01·C02 둘 다 지불) 지정한 LLM 판단 축만 어긋난 입력.

    커버리지를 채우지 않으면 missing_required_claims 라는 **다른**(정당한) 사유로 차단돼,
    "LLM 축이 차단하는가"를 검증할 수 없다.
    """
    return {"scenes": [_scene(1, **flags), _scene(2, matched_claim_ids=["C02"])]}


# ── 기존 동작 보존 ──
def test_all_grounded_still_recomputed():
    out = normalize_selfcheck({
        "scenes": [{"scene": 1, "grounded": True, "unsupported": ["근거 없는 문장"]}],
        "all_grounded": True,
    })
    assert out["all_grounded"] is False
    assert out["scenes"][0]["grounded"] is False


def test_matched_facts_key_preserved():
    out = normalize_selfcheck({"scenes": [{"scene": 1, "matched_facts": ["what_found[0]"]}]})
    assert out["scenes"][0]["matched_facts"] == ["what_found[0]"]


# ── 승인 차단은 코드가 계산 ──
def test_clean_check_is_not_blocked():
    out = normalize_selfcheck(_clean(), _ledger(), _plan(), 45)
    assert out["approval_blocked"] is False
    assert out["block_reasons"] == []
    assert out["coverage"]["primary_claim_covered"] is True
    assert out["coverage"]["missing_claim_ids"] == []


def test_llm_claim_of_not_blocked_is_ignored_when_primary_missing():
    payload = {"scenes": [_scene(1, matched_claim_ids=["C02"])], "approval_blocked": False}
    out = normalize_selfcheck(payload, _ledger(), _plan(), 45)
    assert out["approval_blocked"] is True
    assert "primary_claim_not_covered" in out["block_reasons"]
    assert "missing_required_claims" in out["block_reasons"]


def test_dangling_claim_id_blocks_and_is_dropped():
    out = normalize_selfcheck(
        {"scenes": [_scene(1, matched_claim_ids=["C01", "C99"])]}, _ledger(), _plan(), 45)
    assert out["scenes"][0]["matched_claim_ids"] == ["C01"]
    assert any(r.startswith("claim_id_invalid:C99") for r in out["block_reasons"])
    assert out["approval_blocked"] is True


# ── LLM 판단 축은 경고이지 차단이 아니다 ──
# 운영자 결정(2026-07-27): 차단은 코드가 데이터로 확정하는 사유만. 자기검증 LLM 이 오판하면
# 정상 지시서도 승인이 막히는데, 그 비용이 놓친 오류의 비용보다 크다. 리포트 라인의
# 컴플라이언스 하드차단도 같은 이유로 제거됐다(커밋 6a28761).
def test_scope_expansion_warns_not_blocks():
    out = normalize_selfcheck(
        _covered(scope_match=False), _ledger(), _plan(), 45)
    assert any(w.startswith("scope_expanded") for w in out["warnings"])
    assert out["approval_blocked"] is False


def test_causal_overreach_warns_but_not_applicable_is_silent():
    bad = normalize_selfcheck(
        _covered(causal_calibration="fail"), _ledger(), _plan(), 45)
    assert any(w.startswith("causal_overreach") for w in bad["warnings"])
    assert bad["approval_blocked"] is False
    ok = normalize_selfcheck(
        _covered(causal_calibration="not_applicable"), _ledger(), _plan(), 45)
    assert not any(w.startswith("causal_overreach") for w in ok["warnings"])


def test_numeric_mismatch_warns_but_not_applicable_is_silent():
    bad = normalize_selfcheck(
        _covered(numeric_match="fail"), _ledger(), _plan(), 45)
    assert any(w.startswith("numeric_mismatch") for w in bad["warnings"])
    ok = normalize_selfcheck(_clean(), _ledger(), _plan(), 45)
    assert not any(w.startswith("numeric_mismatch") for w in ok["warnings"])


def test_dropped_qualifier_warns():
    out = normalize_selfcheck(
        _covered(qualifier_preserved=False), _ledger(), _plan(), 45)
    assert any(w.startswith("qualifier_dropped") for w in out["warnings"])
    assert out["approval_blocked"] is False


def test_editorial_inference_warns():
    out = normalize_selfcheck(
        _covered(editorial_inference=True), _ledger(), _plan(), 45)
    assert any(w.startswith("editorial_inference") for w in out["warnings"])
    assert out["approval_blocked"] is False


def test_only_deterministic_reasons_can_block():
    """차단 사유는 전부 코드가 데이터로 확정한 것이어야 한다(LLM 판단 코드가 섞이면 회귀)."""
    llm_judgment = ("scope_expanded", "qualifier_dropped", "causal_overreach",
                    "numeric_mismatch", "editorial_inference")
    out = normalize_selfcheck(_covered(
        scope_match=False, qualifier_preserved=False, causal_calibration="fail",
        numeric_match="fail", editorial_inference=True), _ledger(), _plan(), 45)
    for reason in out["block_reasons"]:
        assert not reason.startswith(llm_judgment), f"LLM 판단이 차단 사유에 섞였다: {reason}"


def test_over_80_sec_blocks():
    out = normalize_selfcheck(_clean(), _ledger(), _plan(), 85)
    assert "over_max_duration" in out["block_reasons"]


def test_series_split_plan_recommends_but_does_not_block():
    """★ 되돌림(2026-09-03) — 자기검증 쪽에도 같은 사유가 흘러들어온다.

    근거는 engine/content_mode.block_reasons 주석이 정본이다: 명세가 "분할 권고까지만"인데
    코드가 차단으로 만들어 놨고, 원장 있는 초안 10건이 100% 걸렸다. 화면에 푸는 길도 없다.
    """
    out = normalize_selfcheck(_clean(), _ledger(), _plan(selected_mode="series_split"), 45)
    assert "series_split_required" not in out["block_reasons"]


# ── 커버리지 ──
def test_coverage_lists_missing_required_claims():
    out = normalize_selfcheck(
        {"scenes": [_scene(1, matched_claim_ids=["C01"])]}, _ledger(), _plan(), 45)
    assert out["coverage"]["missing_claim_ids"] == ["C02"]


def test_unknown_tristate_falls_back_to_not_applicable():
    out = normalize_selfcheck(
        {"scenes": [_scene(1, causal_calibration="아마도", numeric_match=None)]},
        _ledger(), _plan(), 45)
    assert out["scenes"][0]["causal_calibration"] == "not_applicable"
    assert out["scenes"][0]["numeric_match"] == "not_applicable"


# ── 레거시 보호: 새 게이트가 과거 초안을 막지 않는다 ──
def test_legacy_without_ledger_is_never_blocked():
    out = normalize_selfcheck({"scenes": [
        {"scene": 1, "grounded": True, "unsupported": []},
        {"scene": 2, "grounded": True, "unsupported": []},
    ]})
    assert out["approval_blocked"] is False
    assert out["block_reasons"] == []
    assert "legacy_no_claim_ledger" in out["warnings"]


def test_legacy_scene_flags_default_to_pass():
    out = normalize_selfcheck({"scenes": [{"scene": 1}]})
    row = out["scenes"][0]
    assert row["scope_match"] is True and row["qualifier_preserved"] is True
    assert row["editorial_inference"] is False
    assert row["matched_claim_ids"] == []


def test_ledger_without_plan_warns_only():
    out = normalize_selfcheck(_clean(), _ledger())
    assert out["approval_blocked"] is False
    assert "no_content_plan" in out["warnings"]


def test_mode_warnings_surface_as_warnings():
    plan = _plan(mode_warnings=["flash_with_many_evidence_units"])
    out = normalize_selfcheck(_clean(), _ledger(), plan, 45)
    assert "flash_with_many_evidence_units" in out["warnings"]


def test_garbage_scenes_tolerated():
    out = normalize_selfcheck({"scenes": [None, "x", 3, _scene(1)]}, _ledger(), _plan(), 45)
    assert len(out["scenes"]) == 1


def test_prompt_documents_new_axes():
    from engine.selfcheck import SELFCHECK_SYSTEM
    for axis in ("scope_match", "causal_calibration", "numeric_match",
                 "qualifier_preserved", "editorial_inference", "matched_claim_ids"):
        assert axis in SELFCHECK_SYSTEM
