"""실사형 화면 계약의 결정론적 게이트 (2026-08-29 리뷰 §4·§5 필수 테스트).

이 파일이 지키는 것: **2026-08-28 에 실제로 승인 가능했던 지시서가 이제는 막힌다.**
그날 나온 지시서는 계약을 여섯 곳에서 어겼는데 게이트가 잡은 것은 하나뿐이었다
(docs/리뷰요청_지시서렌더엔진_v1.md §3).

★ 동시에 반대 방향도 지킨다 — **정상 지시서는 통과해야 한다.** 오탐이 나면 운영자가 게이트를
  무시하기 시작하고, 그러면 게이트가 있으나 마나가 된다.
"""

from __future__ import annotations

from engine import config, photo_contract as pc
from engine.directive import normalize_directive

GOOD_MECH = {
    "subject": "비강 투여 경로",
    "components": ["비강 점막", "후각신경", "뇌 표적 영역"],
    "relationship": "점막에서 흡수된 분자가 신경을 따라 이동한다",
    "initial_state": "스프레이가 비강에 분사된 직후",
    "transformation": "분자가 점막을 통과해 신경 경로로 올라간다",
    "final_state": "표적 영역에 도달해 수용체에 결합",
    "highlighted_element": "신경 경로",
    "claim_ids": ["C01"],
}


def _cut(n, **kw):
    base = {
        "cut_no": n, "scene_kind": "comic_panel", "narration_ko": "문장입니다",
        "narration_en": "a sentence", "estimated_sec": 4,
        "visual_prompt": "cutaway cross-section showing the layers, one layer highlighted",
        "visual_role": "REALITY", "motion_source": "still",
        "source_facts": ["what_found[0]"], "overlay_plan": [],
    }
    base.update(kw)
    return base


def _good_directive(n=10):
    """계약을 지키는 지시서 — 반드시 **통과**해야 한다."""
    cuts = []
    for i in range(1, n + 1):
        if i in (3, 4, 5):
            cuts.append(_cut(i, visual_role="MECHANISM", mechanism=dict(GOOD_MECH),
                             motion_source="video",
                             visual_prompt="cutaway cross-section of the nasal cavity showing "
                                           "the pathway from mucosa to the target region"))
        else:
            # ★ 컷1·2 는 **서로 다른 그림**이어야 한다(2026-09-09). 종전에는 전부 같은
            #   문장이라 `photo_hook_visual_repeated` 가 떴는데, 경고가 재생성을 띄우지
            #   않던 시절이라 아무 일도 안 일어나 "정상 지시서"로 통했다.
            #   이제 경고도 재생성을 띄우므로, 이 fixture 가 진짜로 깨끗해야 한다.
            cuts.append(_cut(i, visual_prompt=(
                "a gloved hand lifting a sample tray from a research lab bench" if i == 2
                else "documentary photo of a research lab bench")))
    header = {"hook_ko": "의심 많은 사람에게 생긴 변화", "total_estimated_sec": 40}
    return header, cuts


# ── 정상 케이스가 통과하는가(오탐 방지) ──
def test_valid_photo_directive_is_approvable():
    header, cuts = _good_directive()
    result = pc.evaluate(header, cuts)
    assert result["block_reasons"] == [], f"정상 지시서가 막혔다: {result['block_reasons']}"


def test_valid_photo_directive_passes_through_normalize():
    header, cuts = _good_directive()
    out = normalize_directive({"header": header, "cuts": cuts}, "photo")
    assert out["header"]["approval_blocked"] is False, out["header"]["block_reasons"]


# ── 2026-08-28 실측 지시서의 위반 6종 ──
def test_empty_hook_blocks():
    header, cuts = _good_directive()
    header["hook_ko"] = ""
    assert "photo_hook_missing" in pc.evaluate(header, cuts)["block_reasons"]


def test_missing_visual_role_blocks():
    header, cuts = _good_directive()
    cuts[1]["visual_role"] = ""
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_visual_role_missing") for r in reasons)


def test_chart_and_label_prompt_blocks():
    """실측 컷5: 'Placebo vs Oxytocin 막대그래프, 축 라벨 포함' — 가짜 숫자가 화면에 박힌다."""
    header, cuts = _good_directive()
    cuts[4]["visual_prompt"] = ("A simple bar chart comparing Placebo and Oxytocin groups "
                                "on a vertical axis labeled Trusting Behavior")
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_forbidden_screen_request") for r in reasons)


def test_forbidden_vocabulary_is_case_and_plural_tolerant():
    header, cuts = _good_directive()
    for bad in ("BAR CHARTS in the background", "with Graphs and Legends",
                "an infographic overlay", "dashboard UI", "showing 15% on screen",
                "a labeled diagram"):
        cuts[6]["visual_prompt"] = bad
        reasons = pc.evaluate(header, cuts)["block_reasons"]
        assert any(r.startswith("photo_forbidden_screen_request") for r in reasons), bad


def test_spoken_number_without_overlay_blocks(monkeypatch):
    # ★ 근거 카드는 2026-09-08 운영자 지시로 **기본 꺼짐**이다
    #   (config.EVIDENCE_OVERLAY_ENABLED). 이 테스트가 지키는 것은 "카드를 쓰기로 한
    #   날 그 규칙이 제대로 도는가" 이므로 스위치를 켜고 검사한다 — 규칙 자체는 살려 둔다.
    monkeypatch.setattr(config, "EVIDENCE_OVERLAY_ENABLED", True)
    header, cuts = _good_directive()
    cuts[5]["narration_ko"] = "그 결과 신뢰 행동이 15% 더 많았습니다"
    cuts[5]["overlay_plan"] = []
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_number_without_overlay") for r in reasons)


def test_spoken_number_with_overlay_passes():
    header, cuts = _good_directive()
    cuts[5]["narration_ko"] = "그 결과 신뢰 행동이 15% 더 많았습니다"
    cuts[5]["overlay_plan"] = [{"type": "number_punch", "text": "+15%"}]
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert not any(r.startswith("photo_number_without_overlay") for r in reasons)


def test_year_in_narration_is_not_treated_as_a_screen_number():
    """오탐 방지: 연도·순번까지 오버레이를 요구하면 게이트가 성가셔진다."""
    header, cuts = _good_directive()
    cuts[6]["narration_ko"] = "연구는 여러 해에 걸쳐 진행됐습니다"
    assert not any(r.startswith("photo_number_without_overlay")
                   for r in pc.evaluate(header, cuts)["block_reasons"])


def test_too_few_cuts_blocks():
    """실측: 40초에 8컷. 계약은 10~14컷 — 한 컷 = 한 문장."""
    header, cuts = _good_directive(n=6)
    header["total_estimated_sec"] = 45
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_cut_count_low") for r in reasons)


def test_no_mechanism_cut_blocks():
    header, cuts = _good_directive()
    for c in cuts:
        c["visual_role"] = "REALITY"
        c.pop("mechanism", None)
    assert "photo_mechanism_missing" in pc.evaluate(header, cuts)["block_reasons"]


# ── §5 도해 구조 ──
def test_mechanism_without_structure_blocks():
    """enum 하나로는 '빛나는 큐브를 든 추상적 인간'을 막을 수 없다."""
    header, cuts = _good_directive()
    cuts[2]["mechanism"] = {}
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_mechanism_spec_missing") for r in reasons)


def test_mechanism_structure_needs_two_components_and_a_change():
    assert not pc.mechanism_spec_complete({"subject": "x", "components": ["a"],
                                           "relationship": "r", "transformation": "t",
                                           "initial_state": "i"})
    assert not pc.mechanism_spec_complete(dict(GOOD_MECH, transformation=""))
    assert not pc.mechanism_spec_complete(dict(GOOD_MECH, initial_state="", final_state=""))
    assert pc.mechanism_spec_complete(GOOD_MECH)


def test_decorative_mechanism_prompt_blocks_when_two_signals():
    """구조 어휘가 없고 + 장식 어휘가 있으면 그건 도해가 아니라 배경이다."""
    header, cuts = _good_directive()
    cuts[2]["visual_prompt"] = ("A minimalist 3D scene with two abstract featureless human "
                                "figures, one holding a glowing cube")
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_mechanism_decorative") for r in reasons)


def test_structural_prompt_with_one_signal_is_only_a_warning():
    """오탐 위험이 큰 항목은 경고로 — 게이트를 불신하게 만들지 않는다."""
    header, cuts = _good_directive()
    cuts[2]["visual_prompt"] = "the inside of a battery cell, glowing separator layer"
    result = pc.evaluate(header, cuts)
    assert not any(r.startswith("photo_mechanism_decorative") for r in result["block_reasons"])
    assert any(w.startswith("photo_mechanism_thin") for w in result["warnings"])


# ── 영상 컷 배치(경고) ──
def test_scattered_video_cuts_warn_not_block():
    header, cuts = _good_directive()
    for c in cuts:
        c["motion_source"] = "still"
    cuts[0]["motion_source"] = "video"
    cuts[4]["motion_source"] = "video"
    cuts[8]["motion_source"] = "video"
    result = pc.evaluate(header, cuts)
    assert "photo_video_cuts_not_adjacent" in result["warnings"]
    assert "photo_video_cuts_not_adjacent" not in result["block_reasons"]


# ── 다른 버전에는 걸리지 않는다 ──
def test_gate_does_not_apply_to_comic():
    header, cuts = _good_directive()
    header["hook_ko"] = ""
    for c in cuts:
        c["visual_role"] = ""
        c.pop("mechanism", None)
    out = normalize_directive({"header": header, "cuts": cuts}, "comic")
    assert not any(r.startswith("photo_") for r in out["header"]["block_reasons"])


def test_reason_codes_are_declared():
    """사유 코드는 정본 목록에 있어야 한다 — 웹 라벨이 그 목록을 미러한다."""
    header, cuts = _good_directive()
    header["hook_ko"] = ""
    cuts[2]["mechanism"] = {}
    result = pc.evaluate(header, cuts)
    for r in result["block_reasons"]:
        assert r.split(":", 1)[0] in pc.BLOCK_REASONS, r
    for w in result["warnings"]:
        assert w.split(":", 1)[0] in pc.WARNING_REASONS, w


def test_feedback_prompt_names_the_fix_not_just_the_problem():
    text = pc.feedback_prompt(["photo_forbidden_screen_request:5", "photo_mechanism_spec_missing:3"])
    assert "overlay_plan" in text and "mechanism" in text
    assert "다시" in text


def test_thresholds_come_from_config():
    """임계값이 코드에 박히면 오탐 때 게이트를 끄는 쪽이 빨라진다."""
    assert config.PHOTO_MIN_CUTS and config.PHOTO_CUT_SEC_MAX


# ─────────────────────────────────────────────────────────────
# §7 제한적 재생성 — 1회만, 그리고 재생성 결과도 **다시 검사**한다
# ─────────────────────────────────────────────────────────────
def _draft_row():
    return {"script_md": "문장 하나.", "fact_sheet": {}, "video_flow": {},
            "video_prompts": []}


def _raw(hook: str, n=10, bad_cut: bool = False):
    header, cuts = _good_directive(n)
    header["hook_ko"] = hook
    if bad_cut:
        cuts[6]["visual_prompt"] = "bar chart with axis labels"
    return {"header": header, "cuts": cuts}


def test_contract_violation_triggers_exactly_one_retry(monkeypatch):
    from engine import directive as dv

    calls = []

    def fake_call_json(**kw):
        calls.append(kw["user"])
        # 1회차는 위반(빈 훅), 2회차는 정상.
        return _raw("" if len(calls) == 1 else "좋은 훅")

    monkeypatch.setattr(dv, "call_json", fake_call_json)
    out = dv.generate(_draft_row(), "photo")
    assert len(calls) == 2, "재생성이 1회 일어나야 한다"
    assert out["header"]["approval_blocked"] is False
    assert out["header"]["contract_retry"]["attempted"] is True
    # 되먹임에 **처방**이 들어갔는가(사유 나열만으로는 같은 결함이 반복된다).
    assert "header.hook_ko" in calls[1]


def test_retry_result_is_re_checked_not_trusted(monkeypatch):
    """모델이 '고쳤다'고 해도 코드가 다시 판정한다 — 두 번째도 위반이면 승인이 막힌다."""
    from engine import directive as dv

    calls = []

    def fake_call_json(**kw):
        calls.append(kw["user"])
        return _raw("")          # 두 번 다 위반

    monkeypatch.setattr(dv, "call_json", fake_call_json)
    out = dv.generate(_draft_row(), "photo")
    assert len(calls) == 2, "재시도는 1회로 묶여야 한다(무한 루프 금지)"
    assert out["header"]["approval_blocked"] is True, "자동 승인되면 안 된다"
    assert out["header"]["contract_retry"]["retry_block_reasons"]


def test_retry_reports_new_violations_it_introduced(monkeypatch):
    """되먹임이 다른 곳을 깨뜨렸으면 그 사실이 보여야 한다."""
    from engine import directive as dv

    calls = []

    def fake_call_json(**kw):
        calls.append(kw["user"])
        # 1회차: 빈 훅. 2회차: 훅은 고쳤지만 금지 프롬프트가 새로 생김.
        return _raw("") if len(calls) == 1 else _raw("좋은 훅", bad_cut=True)

    monkeypatch.setattr(dv, "call_json", fake_call_json)
    out = dv.generate(_draft_row(), "photo")
    retry = out["header"]["contract_retry"]
    assert "photo_forbidden_screen_request" in retry["new_violations"]
    assert out["header"]["approval_blocked"] is True


def test_no_retry_when_contract_is_satisfied(monkeypatch):
    from engine import directive as dv

    calls = []

    def fake_call_json(**kw):
        calls.append(kw["user"])
        return _raw("좋은 훅")

    monkeypatch.setattr(dv, "call_json", fake_call_json)
    out = dv.generate(_draft_row(), "photo")
    assert len(calls) == 1, "정상인데 재생성하면 매번 돈이 두 배로 나간다"
    assert "contract_retry" not in out["header"]


# ─────────────────────────────────────────────────────────────
# Fable Review 2026-08-29 에서 실제로 찾은 우회 경로
# ─────────────────────────────────────────────────────────────
def test_english_only_number_cannot_bypass_the_overlay_rule(monkeypatch):
    """KO 만 검사하면 **영어 나레이션에만 숫자를 두어** 게이트를 우회할 수 있었다.
    EN 영상도 같은 화면으로 렌더되므로 같은 규칙이 필요하다."""
    # ★ 근거 카드는 2026-09-08 운영자 지시로 **기본 꺼짐**이다
    #   (config.EVIDENCE_OVERLAY_ENABLED). 이 테스트가 지키는 것은 "카드를 쓰기로 한
    #   날 그 규칙이 제대로 도는가" 이므로 스위치를 켜고 검사한다 — 규칙 자체는 살려 둔다.
    monkeypatch.setattr(config, "EVIDENCE_OVERLAY_ENABLED", True)
    header, cuts = _good_directive()
    cuts[6]["narration_ko"] = "문장입니다"
    cuts[6]["narration_en"] = "trust increased by 15%"
    cuts[6]["overlay_plan"] = []
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_number_without_overlay") for r in reasons)


def test_english_number_regex_actually_matches_percent():
    """★ 정규식이 조용히 아무것도 안 잡던 버그: 단어 경계를 `%` 뒤에 붙이면 '15%' 가 안 걸린다."""
    assert pc._speaks_a_number({"narration_en": "increased by 15%"})
    assert pc._speaks_a_number({"narration_en": "15 percent higher"})
    assert pc._speaks_a_number({"narration_en": "359 participants"})
    # 연도·버전 번호는 여전히 통과(오탐 방지)
    assert not pc._speaks_a_number({"narration_en": "in 2026 the team ran it"})
    assert not pc._speaks_a_number({"narration_en": "version 3 of the model"})


def test_forbidden_request_hidden_in_motion_prompt_is_caught():
    """금지 요구를 visual_prompt 대신 motion_prompt 에 숨기는 우회."""
    header, cuts = _good_directive()
    cuts[6]["motion_prompt"] = "camera pans across a chart with axis labels"
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_forbidden_screen_request") for r in reasons)


def test_fake_overlay_type_does_not_satisfy_the_number_rule(monkeypatch):
    """오버레이 type 을 아무 문자열로 위조해도 통과하지 않는다(화이트리스트)."""
    # ★ 근거 카드는 2026-09-08 운영자 지시로 **기본 꺼짐**이다
    #   (config.EVIDENCE_OVERLAY_ENABLED). 이 테스트가 지키는 것은 "카드를 쓰기로 한
    #   날 그 규칙이 제대로 도는가" 이므로 스위치를 켜고 검사한다 — 규칙 자체는 살려 둔다.
    monkeypatch.setattr(config, "EVIDENCE_OVERLAY_ENABLED", True)
    header, cuts = _good_directive()
    cuts[6]["narration_ko"] = "15% 늘었습니다"
    cuts[6]["overlay_plan"] = [{"type": "made_up_type", "text": "15%"}]
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_number_without_overlay") for r in reasons)


def test_whitespace_only_mechanism_fields_do_not_count():
    """구조 필드를 공백으로만 채워 검사를 통과하려는 우회."""
    assert not pc.mechanism_spec_complete(
        {"subject": " ", "components": [" ", " "], "relationship": " ",
         "transformation": " ", "initial_state": " "})


# ─────────────────────────────────────────────────────────────
# 2026-08-29 실제 재생성에서 드러난 결함 2건
# ─────────────────────────────────────────────────────────────
def test_hook_emptied_after_dedup_is_still_caught():
    """★ 순서 버그: 훅 중복 제거가 게이트보다 **뒤에** 돌면, 게이트는 훅을 보고 통과시킨 뒤
    코드가 훅을 비운다 → 빈 훅이 사유 없이 승인 가능 상태로 나간다(실제로 그렇게 나갔다)."""
    header, cuts = _good_directive()
    # 훅이 1컷 나레이션과 같으면 정규화가 훅을 비운다.
    header["hook_ko"] = cuts[0]["narration_ko"]
    out = normalize_directive({"header": header, "cuts": cuts}, "photo")
    assert out["header"]["hook_ko"] == "", "중복 훅은 비워지는 것이 기존 동작이다"
    assert "photo_hook_missing" in out["header"]["block_reasons"], "비워졌으면 게이트가 잡아야 한다"


def test_scope_tag_counts_as_a_number_card():
    """오탐: 손으로 적은 화이트리스트에 scope_tag 가 빠져, '359명'을 말하며 화면에
    'Population: 359 low-trusting men' 카드를 띄운 정상 컷이 위반으로 잡혔다."""
    header, cuts = _good_directive()
    cuts[2]["narration_ko"] = "남성 359명에게 투여했습니다"
    cuts[2]["overlay_plan"] = [{"type": "scope_tag", "text": "Population: 359 low-trusting men"}]
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert not any(r.startswith("photo_number_without_overlay") for r in reasons)


def test_overlay_whitelist_comes_from_config():
    """어휘를 두 곳에서 정의하면 한쪽이 낡는다 — config.OVERLAY_TYPES 가 정본이다."""
    assert set(pc._NUMBER_OVERLAY_TYPES) <= set(config.OVERLAY_TYPES)
    assert "scope_tag" in pc._NUMBER_OVERLAY_TYPES
    assert "caveat_tag" not in pc._NUMBER_OVERLAY_TYPES, "단서 카드는 숫자 카드가 아니다"


def test_negated_forbidden_words_are_compliance_not_violation():
    """★ 오탐: 모델이 'no labels, no on-screen text' 라고 **옳게** 썼는데 게이트가 'labels'
    한 단어만 보고 차단했다. 이 저장소는 프롬프트 끝에 부정문을 붙이는 것이 관례다
    (config.BURN_IN_NEGATIVE_PROMPT). 옳게 한 것을 벌하는 게이트는 반드시 무시당한다."""
    header, cuts = _good_directive()
    cuts[6]["visual_prompt"] = ("Split screen, two hands and coins, identical framing. "
                                "no labels, no on-screen text.")
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert not any(r.startswith("photo_forbidden_screen_request") for r in reasons)


def test_negation_does_not_hide_a_real_request():
    """부정문을 앞에 붙여 놓고 뒤에서 실제로 요구하는 우회는 막힌다."""
    header, cuts = _good_directive()
    cuts[6]["visual_prompt"] = "no text overlay, but show a bar chart with an axis"
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_forbidden_screen_request") for r in reasons)


def test_regex_sources_are_free_of_control_characters():
    """★ 편집 사고 방지: 정규식에 제어문자(\x08 등)가 섞이면 **조용히 아무것도 안 잡는다.**
    실제로 두 번 일어났다(EN 숫자 검사·부정문 검사). 눈으로는 보이지 않는다."""
    for name in ("_FORBIDDEN_SCREEN", "_FORBIDDEN_NUMBER_ON_SCREEN", "_STRUCTURAL",
                 "_DECORATIVE", "_SPOKEN_NUMBER", "_SPOKEN_NUMBER_EN", "_NEGATED"):
        pattern = getattr(pc, name).pattern
        bad = [c for c in pattern if ord(c) < 32 and c not in "\n\t"]
        assert not bad, f"{name} 에 제어문자가 있다: {[hex(ord(c)) for c in bad]}"


def test_reuse_cut_inherits_mechanism_structure(monkeypatch):
    """운영자 결정(2026-08-29): 구조를 요구하는 목적은 **새 그림을 그릴 때 인과를 먼저
    확정시키는 것**이다. 앞 컷 이미지를 그대로 쓰는 컷은 새로 그리지 않으므로 면제한다."""
    header, cuts = _good_directive()
    cuts[3]["mechanism"] = {}                       # 구조 없음
    cuts[3]["asset_strategy"] = "reuse_with_state_change"
    cuts[3]["base_asset_ref"] = "3"
    result = pc.evaluate(header, cuts)
    assert not any(r.startswith("photo_mechanism_spec_missing") for r in result["block_reasons"])
    assert any(w.startswith("photo_mechanism_spec_inherited") for w in result["warnings"]), \
        "면제했다는 사실은 화면에 보여야 한다(조용히 넘어가지 않는다)"


def test_new_asset_cut_still_needs_the_structure():
    """새로 그리는 컷은 면제 대상이 아니다 — 면제가 구멍이 되면 안 된다."""
    header, cuts = _good_directive()
    cuts[3]["mechanism"] = {}
    cuts[3]["asset_strategy"] = "new_asset"
    reasons = pc.evaluate(header, cuts)["block_reasons"]
    assert any(r.startswith("photo_mechanism_spec_missing") for r in reasons)


# ── 2026-08-29 실측 사고의 회귀 가드 ───────────────────────────
def _photo_cut(no: int, **kw):
    """계약을 통과하는 최소 컷. 검사 대상 필드만 갈아 끼워 쓴다."""
    base = {
        "cut_no": no, "visual_role": "REALITY", "estimated_sec": 4,
        "narration_ko": "설명 문장이다", "visual_prompt": "a researcher at a lab bench",
        "asset_strategy": "new_asset", "overlay_plan": [],
    }
    base.update(kw)
    return base


def test_role_name_leaking_into_the_prompt_is_blocked():
    """★ 완성 영상의 컷1 에 'MECHANISM' 이라는 글자가 두 번 그려져 있었다.

    코드는 이 단어를 프롬프트에 넣지 않는다 — 지시서 LLM 이 visual_prompt 에 써 넣었고
    이미지 모델이 그것을 라벨로 읽었다. `no text, no labels` 네거티브로는 못 막는다.
    """
    cuts = [_photo_cut(1, visual_prompt="a glowing orb labeled MECHANISM beside a man"),
            _photo_cut(2, visual_role="MECHANISM",
                       visual_prompt="cutaway cross-section of a battery cell, layers separated",
                       mechanism={"subject": "셀", "components": ["분리막", "음극"],
                                  "relationship": "이온이 지난다", "transformation": "충전",
                                  "initial_state": "방전", "final_state": "충전",
                                  "highlighted_element": "분리막"})]
    got = pc.evaluate({"hook_ko": "훅"}, cuts)
    assert any(r.startswith("photo_role_name_in_prompt") for r in got["block_reasons"])


def test_lowercase_mechanism_is_normal_english_and_not_punished():
    """★ 오탐 방지. 소문자 'mechanism' 은 평범한 영어이고 _STRUCTURAL 이 좋은 신호로 센다.

    옳게 쓴 프롬프트를 벌하는 게이트는 반드시 무시당한다(이 모듈 설계원칙 1).
    """
    cuts = [_photo_cut(1, visual_prompt=(
        "cutaway cross-section showing the mechanism of the valve, "
        "layers separated, arrows tracing the flow"))]
    got = pc.evaluate({"hook_ko": "훅"}, cuts)
    assert not any(r.startswith("photo_role_name_in_prompt") for r in got["block_reasons"])


def test_reuse_without_declared_state_change_is_blocked():
    """재사용 컷이 '무엇이 눈에 보이게 달라지는가'를 안 밝히면 차단한다.

    ★ 재사용 자체가 죄가 아니다 — 서사가 진행돼서 같은 대상이 다시 나오는 것은 옳다.
      죄는 화면이 아무것도 안 변한 채 또 나오는 것이다(실측: 컷5와 컷6 이 동일 파일).
    """
    cuts = [_photo_cut(1),
            _photo_cut(2, asset_strategy="reuse_background_new_overlay",
                       base_asset_ref="1", state_change="")]
    got = pc.evaluate({"hook_ko": "훅"}, cuts)
    assert any(r.startswith("photo_reuse_without_state_change") for r in got["block_reasons"])


def test_reuse_with_a_real_state_change_passes():
    cuts = [_photo_cut(1),
            _photo_cut(2, asset_strategy="reuse_with_state_change", base_asset_ref="1",
                       state_change="동전 더미가 3층에서 5층으로 늘어난다")]
    got = pc.evaluate({"hook_ko": "훅"}, cuts)
    assert not any(r.startswith("photo_reuse_without_state_change")
                   for r in got["block_reasons"])


def test_one_base_cut_dominating_the_screen_warns():
    """★ 실측: 컷1 하나가 컷1·10·11 세 자리를 차지했다."""
    cuts = [_photo_cut(1)] + [
        _photo_cut(n, asset_strategy="reuse_zoom", base_asset_ref="1",
                   state_change="같은 인물을 더 가까이 본다")
        for n in (2, 3, 4)]
    got = pc.evaluate({"hook_ko": "훅"}, cuts)
    assert any(w.startswith("photo_reuse_base_overused") for w in got["warnings"])


def test_overlay_year_not_in_the_fact_sheet_is_blocked():
    """★ 실측: 출처 카드가 `Source: Vogt et al., PNAS (2023)` 로 나왔다 — 실제 발표는 2026 년.

    Fact Sheet 에 연도가 없으면 모델은 비워 두는 게 아니라 **채워 넣는다**는 것이 증명됐다.
    오버레이는 화면에 그대로 나가는 코드 그래픽이라 여기서 막지 않으면 시청자가 틀린 연도를 본다.
    """
    fs = {"claims": [{"claim_id": "C01", "text": "신뢰가 15% 늘었다"}],
          "venue": "PNAS", "published_date": "2026-08-06"}
    cuts = [_photo_cut(1, overlay_plan=[
        {"type": "source_card", "text": "Source: Vogt et al., PNAS (2023)"}])]
    got = pc.evaluate({"hook_ko": "훅"}, cuts, fs)
    assert any(r.startswith("photo_overlay_year_unverified") for r in got["block_reasons"])


def test_overlay_year_present_in_the_fact_sheet_passes():
    fs = {"claims": [], "published_date": "2026-08-06"}
    cuts = [_photo_cut(1, overlay_plan=[
        {"type": "source_card", "text": "Source: Vogt et al., PNAS (2026)"}])]
    got = pc.evaluate({"hook_ko": "훅"}, cuts, fs)
    assert not any(r.startswith("photo_overlay_year_unverified")
                   for r in got["block_reasons"])


def test_year_check_is_skipped_without_a_fact_sheet():
    """원장이 없으면 근거가 없다 — 근거 없이 차단하지 않는다."""
    cuts = [_photo_cut(1, overlay_plan=[
        {"type": "source_card", "text": "Source: X et al. (1999)"}])]
    got = pc.evaluate({"hook_ko": "훅"}, cuts, None)
    assert not any(r.startswith("photo_overlay_year_unverified")
                   for r in got["block_reasons"])
