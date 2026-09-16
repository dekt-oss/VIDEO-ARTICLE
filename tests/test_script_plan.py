"""대본 단계의 근거 계획·훅 후보 정규화 (수정명세 §4-2·§5·§8).

관심사는 "모델이 뭐라 주장하든 코드가 다시 판정하는가" 다 — 원장에 없는 claim 참조 드롭,
훅 즉시탈락, 읽는 숫자 계수, 모드·길이 재유도.
"""

from engine import config
from engine.factsheet import normalize_factsheet
from engine.scriptgen import count_spoken_numbers, normalize_script


def _ledger(*claims):
    return normalize_factsheet({
        "what_found": ["x"], "how": [], "numbers": [], "limitations": [], "claim_strength": "중",
        "claims": list(claims) or [{"claim_ko": "핵심 결과", "claim_kind": "main_result"}],
    })


def _hook(**over):
    base = {
        "text_ko": "블록체인을 장려했더니 기업이 덜 친환경적으로 변했다고요?",
        "angle": "counterintuition",
        "claim_ids": ["C01"],
        "scope_preserved": True,
        "causal_calibrated": True,
        "promise": "장려법 시행 지역에서 환경 성과가 낮게 나타난 결과",
        "risk": "medium",
    }
    base.update(over)
    return base


# ── 씬별 Claim 연결 ──
def test_scene_claim_ids_filtered_against_ledger():
    fs = _ledger({"claim_ko": "a", "claim_kind": "main_result"}, {"claim_ko": "b"})
    out = normalize_script({
        "scenes": [{"narration_ko": "x", "claim_ids": ["C01", "C99"], "evidence_role": "primary_result"}],
    }, fs)
    assert out["scenes"][0]["claim_ids"] == ["C01"]   # C99 는 원장에 없다 → 드롭


def test_scene_claim_ids_kept_when_no_ledger_given():
    # 레거시 경로: fact_sheet 없이 부르면 대조하지 않고 형태만 보정한다.
    out = normalize_script({"scenes": [{"narration_ko": "x", "claim_ids": ["C99"]}]})
    assert out["scenes"][0]["claim_ids"] == ["C99"]


def test_scene_evidence_role_and_delivery_enums():
    out = normalize_script({"scenes": [
        {"narration_ko": "a", "evidence_role": "PRIMARY_RESULT", "evidence_delivery": "BOTH"},
        {"narration_ko": "b", "evidence_role": "쓰레기", "evidence_delivery": "쓰레기"},
    ]})
    assert out["scenes"][0]["evidence_role"] == "primary_result"
    assert out["scenes"][0]["evidence_delivery"] == "both"
    assert out["scenes"][1]["evidence_role"] == config.DEFAULT_EVIDENCE_ROLE
    assert out["scenes"][1]["evidence_delivery"] == config.DEFAULT_EVIDENCE_DELIVERY


# ── 읽는 숫자는 코드가 센다 ──
def test_count_spoken_numbers():
    assert count_spoken_numbers("3.2%p 낮았습니다") == 1
    assert count_spoken_numbers("1,240개 기업을 2016년부터 봤습니다") == 2
    assert count_spoken_numbers("숫자 없는 문장") == 0
    assert count_spoken_numbers("") == 0


def test_too_many_spoken_numbers_warns():
    out = normalize_script({"scenes": [
        {"narration_ko": "3.2%p 낮았고"},
        {"narration_ko": "1,240개 기업에서"},
        {"narration_ko": "2016년부터 2022년까지"},
    ]})
    plan = out["video_flow"]["content_plan"]
    assert plan["spoken_number_count"] > config.MAX_SPOKEN_NUMBERS
    assert "too_many_spoken_numbers" in plan["mode_warnings"]


def test_visual_only_scenes_do_not_count_toward_spoken_numbers():
    out = normalize_script({"scenes": [
        {"narration_ko": "3.2%p 낮았습니다", "evidence_delivery": "spoken"},
        {"narration_ko": "1,240개 기업 2016년 2022년", "evidence_delivery": "visual"},
    ]})
    # 화면으로만 전달하는 씬은 "소리 내 읽는 숫자"가 아니다 — 그게 이 개정의 요점이다.
    assert out["video_flow"]["content_plan"]["spoken_number_count"] == 1


# ── 훅 후보 게이트 (§8-2) ──
def test_hook_ids_assigned_and_eligible_hook_selected():
    fs = _ledger()
    out = normalize_script({
        "hook_candidates": [_hook(), _hook(text_ko="두 번째"), _hook(text_ko="세 번째")],
        "selected_hook_id": "H-B",
    }, fs)
    flow = out["video_flow"]
    assert [h["hook_id"] for h in flow["hook_candidates"]] == ["H-A", "H-B", "H-C"]
    assert all(h["eligible"] for h in flow["hook_candidates"])
    assert flow["selected_hook_id"] == "H-B"


def test_scope_expanding_hook_disqualified():
    fs = _ledger()
    out = normalize_script({
        "hook_candidates": [
            _hook(text_ko="블록체인이 지구를 망친다", scope_preserved=False),
            _hook(text_ko="정상 훅"),
        ],
        "selected_hook_id": "H-A",
    }, fs)
    flow = out["video_flow"]
    assert flow["hook_candidates"][0]["eligible"] is False
    assert "scope_not_preserved" in flow["hook_candidates"][0]["disqualify_reasons"]
    # 탈락한 훅이 선택돼 있었다 → 통과한 후보로 강제 교체
    assert flow["selected_hook_id"] == "H-B"


def test_causal_overreach_disqualified():
    out = normalize_script({"hook_candidates": [_hook(causal_calibrated=False)]}, _ledger())
    hook = out["video_flow"]["hook_candidates"][0]
    assert "causal_not_calibrated" in hook["disqualify_reasons"]


def test_hook_without_claim_link_disqualified():
    out = normalize_script({"hook_candidates": [_hook(claim_ids=[])]}, _ledger())
    hook = out["video_flow"]["hook_candidates"][0]
    assert "no_claim_link" in hook["disqualify_reasons"]


def test_hook_with_dangling_claim_is_treated_as_unlinked():
    out = normalize_script({"hook_candidates": [_hook(claim_ids=["C99"])]}, _ledger())
    hook = out["video_flow"]["hook_candidates"][0]
    assert hook["claim_ids"] == []
    assert "no_claim_link" in hook["disqualify_reasons"]


def test_hook_without_promise_disqualified():
    out = normalize_script({"hook_candidates": [_hook(promise="")]}, _ledger())
    assert "no_promise" in out["video_flow"]["hook_candidates"][0]["disqualify_reasons"]


def test_bold_claim_on_weak_evidence_disqualified():
    # 초록만 확인된 C 등급 주장에 "폭락" 같은 단정형 표현은 근거가 감당하지 못한다.
    fs = _ledger({"claim_ko": "a", "claim_kind": "main_result", "evidence_grade": "C"})
    out = normalize_script({"hook_candidates": [_hook(text_ko="기업 환경 성과가 폭락했습니다")]}, fs)
    hook = out["video_flow"]["hook_candidates"][0]
    assert "bold_claim_on_weak_evidence" in hook["disqualify_reasons"]


def test_bold_claim_allowed_on_body_verified_evidence():
    fs = _ledger({"claim_ko": "a", "claim_kind": "main_result",
                  "evidence_grade": "A", "source_section": "body"})
    out = normalize_script({"hook_candidates": [_hook(text_ko="환경 성과가 폭락했습니다")]}, fs)
    assert out["video_flow"]["hook_candidates"][0]["eligible"] is True


def test_all_hooks_disqualified_leaves_selection_empty():
    fs = _ledger()
    out = normalize_script({
        "hook_candidates": [_hook(scope_preserved=False), _hook(causal_calibrated=False)],
        "selected_hook_id": "H-A",
    }, fs)
    assert out["video_flow"]["selected_hook_id"] == ""


def test_no_hook_candidates_is_tolerated():
    out = normalize_script({"scenes": []})
    assert out["video_flow"]["hook_candidates"] == []
    assert out["video_flow"]["selected_hook_id"] == ""


# ── 계획은 원장·규칙으로 재판정 ──
def test_two_main_results_force_series_split():
    fs = _ledger(
        {"claim_ko": "a", "claim_kind": "main_result"},
        {"claim_ko": "b", "claim_kind": "main_result"},
    )
    out = normalize_script({"content_plan": {"selected_mode": "standard"}}, fs)
    plan = out["video_flow"]["content_plan"]
    assert plan["selected_mode"] == "series_split"


def test_plan_duration_overridden_by_mode():
    out = normalize_script({"content_plan": {
        "selected_mode": "flash", "target_duration_min_sec": 60, "target_duration_max_sec": 70,
    }})
    plan = out["video_flow"]["content_plan"]
    assert (plan["target_duration_min_sec"], plan["target_duration_max_sec"]) == (25, 35)


def test_prompt_drops_fixed_six_beat_and_uses_shared_rules():
    from engine.scriptgen import SCRIPT_SYSTEM
    assert "전체 길이를 먼저 고정하지 마라" not in SCRIPT_SYSTEM  # 그 문구는 지시서 쪽
    assert "길이를 먼저 고정하지 마라" in SCRIPT_SYSTEM
    assert "content_plan" in SCRIPT_SYSTEM and "hook_candidates" in SCRIPT_SYSTEM
    # 공통 규칙이 별도 사본이 아니라 config 상수에서 온다(드리프트 차단).
    assert config.EVIDENCE_RULES_SHARED in SCRIPT_SYSTEM
    # 고정 6단 구조의 흔적이 남아 있으면 모드별 가변 구조와 충돌한다.
    assert "순서 고정" not in SCRIPT_SYSTEM
