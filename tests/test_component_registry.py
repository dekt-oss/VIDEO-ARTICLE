"""시각 컴포넌트 레지스트리 (작업지시서 영상엔진품질 v3 §7). 순수 함수 검사."""

from __future__ import annotations

import pytest

from engine import component_registry as cr
from engine import config


# ── 어휘 통합 — 이름이 세 벌이 되는 것을 막는다 ────────────────────
def test_existing_chart_template_names_are_all_registered():
    """config.FIN_CHART_TEMPLATES 5종이 정본이다.

    ★ 지시서 §7-1 의 core_v1 이름(step_line_chart 등)을 새로 만들면 어휘가 세 벌이 된다
      (config 5종 + fin_charts 타입 + 신규). 기존 이름을 그대로 쓴다.
    """
    for name in config.FIN_CHART_TEMPLATES:
        assert name in cr.CORE_COMPONENTS, f"{name} 이 레지스트리에 없다"


def test_spec_alias_documents_the_instruction_name():
    """지시서 이름은 별칭으로만 남긴다 — 조회 키가 되면 안 된다."""
    assert cr.get_component("number_count").spec_alias
    for alias in ("counter_number", "step_line_chart", "progress_vs_target"):
        assert alias not in cr.CORE_COMPONENTS, f"{alias} 는 별칭이지 정본 키가 아니다"


# ── 조회 ──────────────────────────────────────────────────────
def test_unknown_component_raises_with_the_known_list():
    with pytest.raises(KeyError) as e:
        cr.get_component("없는컴포넌트")
    assert "등록됨" in str(e.value)


def test_every_fallback_points_at_a_registered_component():
    for name, spec in cr.CORE_COMPONENTS.items():
        if spec.fallback_component is not None:
            assert spec.fallback_component in cr.CORE_COMPONENTS, f"{name} 의 폴백이 미등록"


def test_every_intent_in_the_routing_table_resolves():
    for intent in cr.COMPONENT_BY_INTENT:
        assert cr.resolve(intent).component in cr.CORE_COMPONENTS


def test_every_board_maps_to_a_known_intent():
    """보드 이름은 저장된 지시서 데이터에 있다 — 라우팅이 비면 그 컷이 빈 화면이 된다."""
    for board in config.EXPLAINER_BOARD_SCENE_KIND:
        intent = cr.intent_for_board(board)
        assert intent in cr.COMPONENT_BY_INTENT, f"{board} → {intent} 라우팅 없음"


def test_unknown_board_falls_back_instead_of_raising():
    """모르는 보드로 예외를 던지면 렌더 잡이 통째로 죽는다 — 최종 폴백으로 내린다."""
    assert cr.intent_for_board("듣도보도못한보드") == "context"
    assert cr.resolve_for_board("듣도보도못한보드").component == "text_core"


# ── draft 폴백 — 미구현 컴포넌트로 빈 화면이 나가지 않게 ──────────
def test_draft_components_fall_back_when_not_allowed():
    """미구현 컴포넌트로 라우팅해 빈 화면이 나가지 않게 하는 스위치.

    ★ 이 스위치는 실제로 일을 한다 — dual_marker 가 등록만 되고 안 그려지므로,
      target_vs_current 의도는 allow_draft 여부에 따라 결과가 갈린다. 핵심 불변식은
      "allow_draft=False 면 **절대** draft 컴포넌트를 돌려주지 않는다"이다.
      빈 화면이 나가는 것이 이 저장소가 고치는 결함이다.
    """
    for intent in cr.COMPONENT_BY_INTENT:
        assert not cr.resolve(intent, allow_draft=False).draft, (
            f"{intent} 가 미구현 컴포넌트로 라우팅됐다 — 그 컷은 빈 화면이 된다")

    # 가상의 미구현 컴포넌트를 끼워 넣어 스위치가 실제로 작동하는지 본다.
    fake = cr.ComponentSpec(component="_fake", version="v0", supported_intents=("trend",),
                            required_params=(), fallback_component="race_bar", draft=True)
    cr.CORE_COMPONENTS["_fake"] = fake
    cr.COMPONENT_BY_INTENT["_fake_intent"] = "_fake"
    try:
        assert cr.resolve("_fake_intent", allow_draft=True).component == "_fake"
        assert cr.resolve("_fake_intent", allow_draft=False).component == "race_bar"
    finally:
        del cr.CORE_COMPONENTS["_fake"]
        del cr.COMPONENT_BY_INTENT["_fake_intent"]


def test_draft_fallback_chain_terminates():
    """폴백이 순환하면 무한루프가 된다."""
    for intent in cr.COMPONENT_BY_INTENT:
        spec = cr.resolve(intent, allow_draft=False)       # 예외·행 없이 끝나야 한다
        assert spec.component in cr.CORE_COMPONENTS


def test_implemented_is_a_subset_of_registered():
    """등록만 하고 드로잉을 안 붙인 컴포넌트가 **정확히 무엇인지** 고정한다.

    ★ 예전엔 `implemented == registered` 를 단언하며 "P2-d 완료 — 등록된 것이 전부
      그려진다"고 적어 뒀는데, **사실이 아니었다.** dual_marker 는 draw_component 에 분기가
      없다(형제 테스트 test_component_has_a_draw_branch 도 4종만 검사한다). 레지스트리가
      draft=False 로 거짓말을 하고 있었고, 그래서 allow_draft=False 가드가 이걸 못 막았다.
      목록을 못박아 두면 새로 등록만 하고 안 그린 컴포넌트가 여기서 잡힌다.
    """
    assert set(cr.implemented_names()) <= set(cr.registered_names())
    undrawn = set(cr.registered_names()) - set(cr.implemented_names())
    assert undrawn == {"dual_marker"}, (
        f"등록만 되고 안 그려지는 컴포넌트가 바뀌었다: {sorted(undrawn)}. "
        "그렸으면 draft=False 로 내리고, 새로 등록만 했으면 이 목록에 넣어라.")


# ── 파라미터 검증 (§7-2 B2) ───────────────────────────────────
def test_missing_required_param_is_reported():
    assert "param_missing:value_ref" in cr.validate_params("number_count", {})


def test_unknown_param_is_reported():
    """오타로 값이 조용히 버려지는 것을 막는다."""
    out = cr.validate_params("number_count", {"value_ref": "num_1", "valu_ref": "num_2"})
    assert "param_unknown:valu_ref" in out


def test_clean_params_produce_no_findings():
    assert cr.validate_params("number_count", {"value_ref": "num_1", "warn": False}) == []


def test_numeric_param_must_point_at_a_real_fact():
    """근거 없는 수치가 화면에 그려지는 것을 막는 지점 — §7-2 B2."""
    out = cr.validate_params("number_count", {"value_ref": "num_없음"}, known_fact_ids={"num_1"})
    assert out == ["evidence_ref_unknown:value_ref:num_없음"]

    ok = cr.validate_params("number_count", {"value_ref": "num_1"}, known_fact_ids={"num_1"})
    assert ok == []


def test_list_valued_refs_are_each_checked():
    out = cr.validate_params(
        "race_bar",
        {"entry_refs": ["num_1", "num_9"], "attribution_badge": "유안타증권 추정"},
        known_fact_ids={"num_1"},
    )
    assert out == ["evidence_ref_unknown:entry_refs:num_9"]


def test_non_numeric_params_are_not_evidence_checked():
    """텍스트 파라미터에 근거를 요구하면 섹션 제목조차 못 그린다."""
    assert cr.validate_params("section_kicker", {"text": "다만—"}, known_fact_ids=set()) == []


def test_evidence_backed_params_are_declared_params():
    """근거 필수 목록이 실제 파라미터 이름과 어긋나면 검사가 아무것도 안 한다."""
    for name, spec in cr.CORE_COMPONENTS.items():
        allowed = set(spec.required_params) | set(spec.optional_params)
        unknown = set(spec.evidence_backed_params) - allowed
        assert not unknown, f"{name}: 선언되지 않은 파라미터에 근거를 요구한다 {unknown}"


# ── 애니메이션 계약 (§7-2 · §9 Q3 의 판정 기준) ────────────────
def test_moving_components_declare_a_change_threshold():
    """'움직인다'고 선언해 놓고 기준이 0 이면 Q3 가 아무것도 못 잡는다."""
    for name, spec in cr.CORE_COMPONENTS.items():
        if spec.animation.type != "none":
            assert spec.animation.min_change_ratio > 0, f"{name} 의 변화 기준이 0"


def test_source_badge_has_no_fallback():
    """출처는 폴백이 없다 — 없으면 그 자체가 실패다(§8-2 critical)."""
    assert cr.get_component("source_badge").fallback_component is None


def test_the_end_of_every_fallback_chain_is_implemented():
    """폴백 사슬 끝이 미구현이면 폴백 자체가 빈 화면을 만든다.

    ★ 이것이 Phase 0 이 실측한 결함(CORE 충전율 0.235 가 통과)과 같은 계열이다 —
      "실패했는데 뭔가 나간 것처럼 보이는" 경로를 만들지 않는다.
    """
    for name in cr.registered_names():
        spec = cr.get_component(name)
        seen = {name}
        while spec.draft and spec.fallback_component:
            assert spec.fallback_component not in seen, f"{name}: 폴백 순환"
            seen.add(spec.fallback_component)
            spec = cr.get_component(spec.fallback_component)
        assert not spec.draft, f"{name} 의 폴백 사슬 끝({spec.component})이 미구현이다"


def test_no_implemented_component_falls_back_through_a_draft_one():
    """구현된 컴포넌트가 미구현 컴포넌트를 거쳐 폴백하면, 폴백 한 단계가 헛돈다."""
    for name in cr.implemented_names():
        fb = cr.get_component(name).fallback_component
        if fb is not None:
            assert not cr.get_component(fb).draft, f"{name} → {fb} (미구현)"


# ── P2-e 라우팅이 오늘의 화면과 일치하는가 ─────────────────────
# 교체 전 `board_render._draw_frame` 의 if 분기가 하던 일. 이 표가 어긋나면 화면이 바뀐다.
LEGACY_ROUTING = {
    "NUMBER_BOARD": "number_count",
    "VALUATION_BOARD": "number_count",
    "CHART_BOARD": "race_bar",
    "COMPARISON_BOARD": "race_bar",
    "EVIDENCE_BOARD": "source_badge",
    # 나머지는 전부 else → _draw_text_core
    "HOOK_BOARD": "text_core",
    "CLAIM_BOARD": "text_core",
    "REPORT_REASON_BOARD": "text_core",
    "MECHANISM_BOARD": "text_core",
    "WATCHPOINT_BOARD": "text_core",
    "CONTEXT_BOARD": "text_core",
}


@pytest.mark.parametrize("board,expected", sorted(LEGACY_ROUTING.items()))
def test_routing_reproduces_todays_screen(board, expected):
    """P2-e 의 합격기준은 화면 불변이다(운영자 결정).

    ★ MECHANISM·HOOK 의 자연스러운 의도는 progress_vs_goal·trend 지만 그 컴포넌트가 아직
      안 그려진다. P2-d 에서 구현하면 이 표와 INTENT_BY_BOARD 를 **함께** 옮긴다 —
      한쪽만 바꾸면 여기서 깨진다.
    """
    assert cr.resolve_for_board(board, allow_draft=False).component == expected


def test_core_routing_no_longer_lives_in_if_branches():
    """레지스트리를 만들어 놓고 렌더러가 계속 보드 이름으로 분기하면 통합이 무의미하다.

    ★ 라우팅 결정 자체는 §7-3 이후 `render_board` 로 옮겼다 — 컷이 선언한 데이터 모양까지
      봐야 하고, 그 답을 manifest 선언과 **같은 값**으로 써야 하기 때문이다. `_draw_frame` 은
      ctx 에 실려 온 결정을 읽기만 한다. 두 곳에서 각자 풀면 선언과 그림이 갈린다.
    """
    import inspect

    from engine import board_render

    decide = inspect.getsource(board_render.render_board)
    assert "resolve_for_cut" in decide, "render_board 가 레지스트리로 라우팅하지 않는다"

    src = inspect.getsource(board_render._draw_frame)
    assert 'ctx["core_component"]' in src, "_draw_frame 이 결정을 다시 풀고 있다"
    assert "resolve_for" not in src, "라우팅을 두 곳에서 풀면 manifest 선언과 갈린다"
    assert 'board in ("NUMBER_BOARD", "VALUATION_BOARD")' not in src
    assert 'board == "EVIDENCE_BOARD"' not in src


def test_draw_component_returns_none_when_data_is_missing():
    """숫자가 없는 NUMBER_BOARD 는 빈 CORE 가 아니라 텍스트 코어로 떨어져야 한다.

    ★ 예전 if 분기의 `and pay["number"]` 조건이다. 옮기면서 빠뜨리면 그 컷이 빈 화면이 된다.
    """
    import inspect

    from engine import board_render

    src = inspect.getsource(board_render.draw_component)
    assert 'if not pay["number"]' in src
    # ★ 막대 하나짜리는 차트가 아니다 — 가드가 `not chart_items` 였을 때 CHART_BOARD 컷이
    #   막대 하나만 그려 충전율 0.178 로 잡이 3회 연속 실패했다(실측 2026-08-04).
    assert 'if len(ctx["chart_items"] or []) < 2' in src


# ── §7-3 의미 라우팅 — 데이터 모양으로 정한다 ────────────────
def test_narrative_board_with_a_time_series_draws_a_trend():
    """서술형 보드도 컷이 시계열을 선언했으면 글자 대신 추이선을 그린다(§7-3)."""
    spec = cr.resolve_for_cut("MECHANISM_BOARD", series_len=3, period_like=True)
    assert spec.component == "step_climb"


def test_narrative_board_without_period_labels_stays_text():
    """라벨이 기간이 아니면 그건 추이가 아니라 항목 비교다 — 추이선으로 그리면 화면이 과장한다."""
    assert cr.resolve_for_cut("MECHANISM_BOARD", series_len=3,
                              period_like=False).component == "text_core"
    # 점이 2개면 '비교'지 '추이'가 아니다.
    assert cr.resolve_for_cut("MECHANISM_BOARD", series_len=2,
                              period_like=True).component == "text_core"
    # 선언이 없으면 오늘과 똑같다.
    assert cr.resolve_for_cut("HOOK_BOARD").component == "text_core"


def test_boards_that_declare_their_own_meaning_are_not_overridden():
    """NUMBER_BOARD 는 이름 그대로 숫자가 주인공이다 — 데이터 모양으로 뒤집지 않는다."""
    for board in cr.FIXED_INTENT_BOARDS:
        assert (cr.resolve_for_cut(board, series_len=3, period_like=True).component
                == cr.resolve_for_board(board, allow_draft=False).component)


def test_unrouted_components_stay_unrouted_with_a_reason():
    """켜지 않은 컴포넌트가 실수로 라우팅되면 화면이 없는 사실을 주장하게 된다.

    · gauge_fill  — number_claims 에 '목표' 필드가 없다(items[-1] 을 목표로 가정 금지)
    · race_bar    — 서술형 보드에는 axis/bar0/bar1/diff 단계가 없어 빈 리스트가 나온다
    · strike_reveal — 지시서에 '통념 반전' 신호가 없다(§7-4 억지 취소선 금지)
    · dual_marker — 그리는 코드가 없다
    """
    reachable = {cr.resolve_for_cut(b, series_len=n, period_like=pl).component
                 for b in list(cr.INTENT_BY_BOARD) + ["UNKNOWN_BOARD"]
                 for n in (0, 1, 2, 3, 5)
                 for pl in (True, False)}
    assert "gauge_fill" not in reachable
    assert "strike_reveal" not in reachable
    assert "dual_marker" not in reachable


def test_single_item_chart_falls_back_and_clears_the_fill_gate():
    """★ P1 지적(리뷰 #90 14차): 폴백으로 내려가는 것만으로는 부족하다 — 내려간 화면이
    충전율 게이트를 **통과**해야 잡이 산다. 안 그러면 컷은 여전히 렌더 불가다.

    실측 사고: CHART_BOARD 컷의 숫자가 하나뿐이라 막대 하나가 0.178 로 잡을 죽였다.
    폴백만 붙였을 때는 0.217 로 여전히 미달이었고, 카드를 키워 0.38 이 됐다.
    """
    import tempfile

    from engine import board_render, config

    header = {"version_type": "explainer", "broker": "SK증권", "explainer": {
        "profile": "NUMERIC",
        "number_claims": [{
            "claim_no": 4, "unit": "조원", "value": "13.6",
            "label": "2028년 예상 합산 영업이익", "big_number_ok": True,
            "why_significant": "펀더멘털이 견고하다는 전망의 근거",
            # ★ 비교값이 **숫자가 아닌 서술**이다 — 증권사 리포트에서 흔하다. 그래서
            #   차트에 올릴 항목이 하나뿐이 된다(_chart_items).
            "comparison_basis": "과거 최고점(2011년 6.6조원) 대비",
            "comparison_value": "약 2배"}],
        "report_claim_summary": {"speaker": "SK증권", "statement": "낙폭과대 국면이다."},
        "watchpoint": {"text": "신규 수주 실적을 확인할 필요가 있습니다.", "metric": "신규 수주량"}}}
    cut = {"board": "CHART_BOARD", "cut_no": 6, "beat_role": "EVIDENCE",
           "scene_kind": "data_viz", "estimated_sec": 5,
           "narration_ko": "2028년 합산 영업이익은 13조 원을 넘어설 것으로 전망했습니다.",
           "number_claim_refs": [4],
           "overlay_plan": [{"text": "2028년 전망: 13.6조원", "type": "number_punch",
                             "priority": "supporting", "start_sec": 1, "duration_sec": 3.5}]}

    with tempfile.TemporaryDirectory() as tmp:
        res = board_render.render_board(cut, header, {}, tmp, 5, total_sec=5.0, lang="ko")

    assert res.core_fill >= config.EXPLAINER_CORE_MIN_FILL, (
        f"폴백은 됐지만 게이트를 못 넘었다({res.core_fill:.3f}) — 컷이 여전히 렌더 불가다")
    assert not res.layout_qa.get("fail"), res.layout_qa.get("fail")
