"""Equity Visual Planner — 리포트 논증이 **실제로 화면을 잇는가** (v3 Phase 5).

★ 이 파일이 막는 것은 이 저장소가 여덟 번 반복한 실패다:
  **"만들어 놓고 한쪽만 연결."** 시퀀스를 컴파일해 놓고 라우터·비용·렌더가 그것을
  안 보면, 금융 라인은 예전처럼 숫자 카드 나열로 나가면서 지표만 좋아 보인다.
  그래서 여기 테스트는 컴파일 결과뿐 아니라 **하류가 그것을 어떻게 읽는지**까지 본다.

★ 전부 순수 판정이라 라이브 키 없이 돈다. LLM 호출은 0이다 — 이 라인의 설계가 그렇다.
"""

from __future__ import annotations

from engine import (config, directive as dv, equity_visual as ev,
                    sequence_render as sr, visual_sequence as vs,
                    visual_sequence_contract as vc)


def _unit(steps, unit_type="DRIVER_CHAIN", rid="R01"):
    return {"reasoning_id": rid, "unit_type": unit_type, "carries_thesis": True,
            "attributed_to": "유안타증권", "title": "t",
            "steps": [{"step": i, "text": t, "fact_ids": list(f), "source_refs": []}
                      for i, (t, f) in enumerate(steps, 1)]}


LS_STEPS = [
    ("AI 데이터센터 증가로 전력망 투자가 확대된다", ["F00"]),
    ("변압기 신규 수주가 늘어난다", ["F01"]),
    ("수주잔고가 쌓인다", ["F02"]),
    ("2~3분기 뒤 매출로 인식된다", []),
    ("고마진 제품 비중 상승으로 영업이익률이 개선된다", ["F03"]),
]


# ── ① 사업 의미 판정 ──────────────────────────────────────────
def test_the_more_specific_business_meaning_wins():
    """★ "수주잔고가 쌓인다"는 ORDER 와 BACKLOG 어휘를 둘 다 갖는다.

    화면에서 벌어지는 일은 **누적**이다. 표 순서가 곧 우선순위라는 것을 못박는다 —
    순서를 흩뜨리면 같은 문장이 다른 화면 연산으로 번역된다.
    """
    assert ev.semantic_operation("수주잔고가 쌓인다") == "BACKLOG"
    assert ev.semantic_operation("변압기 신규 수주가 늘어난다") == "ORDER"


def test_an_unmatched_step_is_marked_not_silently_defaulted():
    """★★ 기본값도 정본으로 읽힌다(계획서 §9-10). 채워 넣은 값에는 표시가 남아야 한다."""
    assert ev.semantic_matched("수주잔고가 쌓인다") is True
    assert ev.semantic_matched("그래서 회사는 좋아졌습니다") is False
    # 판정은 그래도 나온다 — 호출측이 "판정 실패"를 또 분기하지 않게.
    assert ev.semantic_operation("그래서 회사는 좋아졌습니다") in config.EQUITY_SEMANTIC_OPERATIONS


def test_every_translation_target_stays_inside_the_shared_enums():
    """★ 금융용으로 enum 을 복제하지 않는다(작업지시서 equity §3).

    번역표가 공용 목록 밖의 값을 내면 정규화가 조용히 기본값으로 바꾼다 —
    그러면 표를 고쳐도 화면이 안 바뀐다.
    """
    for sem, tr in config.EQUITY_OP_TRANSLATION.items():
        assert sem in config.EQUITY_SEMANTIC_OPERATIONS
        assert tr["operation"] in config.VISUAL_OPERATIONS
        assert tr["mutation"] in config.MUTATION_OPERATIONS
        assert tr["camera"] in config.CAMERA_OPERATIONS
        assert tr["entity"] in config.EQUITY_ENTITY_IDENTITY


# ── ② 컴파일 ────────────────────────────────────────────────
def test_a_reasoning_unit_becomes_one_continuing_world():
    """★ v3 의 요점: 단계마다 새 세계를 만들면 "시퀀스"라 불러도 컷 나열이다."""
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    assert len(seqs) == 1
    stages = seqs[0]["stages"]
    assert stages[0]["continuity_mode"] == "NEW_WORLD"
    assert all(s["continuity_mode"] == "CONTINUE_WORLD" for s in stages[1:])
    assert [s["continuity_from"] for s in stages[1:]] == [s["stage_id"] for s in stages[:-1]]


def test_the_screen_never_invents_a_step_the_report_did_not_state():
    """★★ EQ-V5 를 **게이트가 아니라 구조로** 막는다.

    stage 는 step 에서 1:1 로 나온다. 그래서 "수주 증가 → 매출 증가" 사이에 리포트가
    말하지 않은 공정이 끼어들 **자리가 없다.** 이 성질이 깨지면 여기서 깨진다.
    """
    unit = _unit(LS_STEPS)
    seqs = ev.compile_sequences({"units": [unit]})
    assert len(seqs[0]["stages"]) == len(unit["steps"])
    # 리포트 문장은 **버리지 않는다.** 화면에 안 실을 뿐이고 stage 마다 그대로 남는다 —
    # 운영자·게이트가 "이 화면이 무엇을 근거로 하는가"를 읽는 자리다.
    assert [s["reasoning_text"] for s in seqs[0]["stages"]] == \
           [s["text"] for s in unit["steps"]]


def test_exact_figures_never_reach_the_generated_picture():
    """★★ 2026-08-30 실제 리포트로 잡음 — 리포트 문장을 화면 계약에 그대로 실었더니
    그 안의 정확한 수치("지분 49.99%")를 **생성 이미지에게 그리라고 요구**하는 셈이 됐고
    VSEQ-7 이 차단했다(`vseq_quantitative_visual` 2건).

    Phase 0 이 잰 것이 그것이다: 생성모델은 개수를 의도대로 **읽지 지키지 않는다.**
    수치는 정밀 레이어(코드 렌더)와 claim_ids 가 정확히 담당한다(코덱스 리뷰 R1).
    """
    unit = _unit([("삼성SDI가 지분 49.99%를 인수해 지분율을 100%로 올린다", ["F01"]),
                  ("2027년 말까지 30GWh 이상의 생산능력을 구축한다", ["F02"])])
    seqs = ev.compile_sequences({"units": [unit]})
    assert vc.evaluate(seqs)["block_reasons"] == []
    for st in seqs[0]["stages"]:
        screen = st["observable_change"] + " " + \
                 " ".join(m["result_state"] for m in st["mutations"])
        assert "49.99" not in screen and "30GWh" not in screen, screen
        assert st["precision_layer"] == "CODE_OVERLAY"   # 수치는 코드가 그린다
        assert st["claim_ids"]                            # 그리고 원장에 붙어 있다


def test_the_same_business_meaning_twice_still_has_to_progress():
    """★★ 실제 리포트에서 같은 논증에 DEMAND_INCREASE 가 두 번 나왔다(수요가 두 이유로 는다).

    화면 문장이 똑같아 **코드가 계산한 상태가 동일**해졌고 상태 원장이
    `vseq_no_progression` 으로 차단했다. 게이트가 옳다 — 같은 화면 두 번은 진행이 아니다.
    2회차는 "앞 단계보다 한 번 더"가 된다. 게이트를 속이려고 문자열만 바꾸는 것이 아니라
    (코덱스 리뷰 S1 이 금지한 것), 흐름이 **실제로 앞보다 굵어지는** 것이다.
    """
    unit = _unit([("전력 수요가 늘어난다", ["F01"]),
                  ("데이터센터 투자로 수요가 또 늘어난다", ["F02"])])
    seqs = ev.compile_sequences({"units": [unit]})
    assert vc.evaluate(seqs)["block_reasons"] == []
    a, b = (s["observable_change"] for s in seqs[0]["stages"])
    assert a != b and "한 번 더" in b


def test_valuation_stays_code_viz_instead_of_becoming_a_3d_metaphor():
    """★ `+130%` 를 물체 13개로 보여주지 않는다(§6.2). 밸류에이션은 시퀀스가 아니다."""
    units = [_unit([("목표주가를 30만원으로 상향", ["F04"]), ("PER 25배 적용", ["F05"])],
                   unit_type="VALUATION_LOGIC", rid="R02")]
    assert ev.compile_sequences({"units": units}) == []


def test_a_single_step_is_a_scene_not_a_sequence():
    units = [_unit([("수주가 늘어난다", ["F01"])])]
    assert ev.compile_sequences({"units": units}) == []


def test_the_compiled_sequence_survives_the_shared_gates():
    """★★ 공용 게이트가 막는 것을 만들어 놓고 "됐다"고 하면 렌더에서 죽는다."""
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    res = vc.evaluate(seqs)
    assert res["block_reasons"] == [], res["block_reasons"]
    assert vs.sequence_is_progression(seqs[0]) is True
    m = res["metrics"]
    assert m["mechanism_sequences"] == 1
    assert m["stage_entity_resolution_rate"] == 1.0     # 선언 없는 개체가 없다


def test_an_exact_number_gets_a_precision_layer_not_its_own_world():
    """★ 코덱스 리뷰 R1 — 수치는 세계를 끊지 않고 코드 레이어로 얹힌다."""
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    layers = [s["precision_layer"] for s in seqs[0]["stages"]]
    assert layers == ["CODE_OVERLAY", "CODE_OVERLAY", "CODE_OVERLAY", "", "CODE_OVERLAY"]


# ── ③ 컷 배정 ───────────────────────────────────────────────
def test_cuts_bind_to_stages_by_what_they_say_not_by_our_guess():
    """★ 순서로 나눠 담으면 **우리가 지어낸 정렬**이다. 컷이 말한 단계로만 잇는다."""
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    cuts = [{"cut_no": 7, "reasoning_id": "R01", "reasoning_step": 3},
            {"cut_no": 2, "reasoning_id": "R01", "reasoning_step": 1},
            {"cut_no": 9, "reasoning_id": "", "reasoning_step": 0}]
    stages = ev.assign_cuts(seqs, cuts)[0]["stages"]
    assert stages[0]["cut_refs"] == [2]
    assert stages[2]["cut_refs"] == [7]
    assert stages[1]["cut_refs"] == [] and stages[3]["cut_refs"] == []


def test_a_step_number_that_does_not_exist_is_dropped():
    """★ dangling 금지 — `_filter_reasoning_ids` 와 같은 규율."""
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    seqs = ev.assign_cuts(seqs, [{"cut_no": 3, "reasoning_id": "R01", "reasoning_step": 99},
                                 {"cut_no": 4, "reasoning_id": "R99", "reasoning_step": 1}])
    assert all(not s["cut_refs"] for s in seqs[0]["stages"])


def test_a_bound_cut_is_told_what_it_pays_for():
    """★★ 이것이 없으면 시퀀스를 만들어 놓고도 **화면 판정이 전부 기본값**이 된다.

    리포트 컷은 `source_facts` 를 쓰고 `claim_ids` 를 쓰지 않는다. 라우터는 주장이 없는
    컷에 기전 자격을 주지 않으므로, 배정만 하고 끝내면 in_sequence 가 0 이 된다(실측).
    """
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    cuts = [{"cut_no": 2, "reasoning_id": "R01", "reasoning_step": 2}]
    ev.assign_cuts(seqs, cuts)
    assert cuts[0]["claim_ids"] == ["F01"]


def test_a_cut_that_declared_its_own_claims_is_not_overwritten():
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    cuts = [{"cut_no": 2, "reasoning_id": "R01", "reasoning_step": 2, "claim_ids": ["F09"]}]
    ev.assign_cuts(seqs, cuts)
    assert cuts[0]["claim_ids"] == ["F09"]


# ── ④ 배선 — 하류가 실제로 이것을 읽는가 ────────────────────────
def _directive_with_sequences():
    reasoning = {"units": [_unit(LS_STEPS)]}
    cuts = [{"cut_no": 1, "narration_ko": "훅", "narration_en": "h",
             "estimated_sec": 4, "visual_prompt": "x", "reasoning_id": "", "reasoning_step": 0}]
    for n, step in enumerate(range(1, 6), start=2):
        cuts.append({"cut_no": n, "narration_ko": f"단계{step}", "narration_en": "s",
                     "estimated_sec": 5, "visual_prompt": "y",
                     "reasoning_id": "R01", "reasoning_step": step})
    obj = {"header": {"aspect_ratio": "9:16", "hook_ko": "a", "hook_en": "b",
                      "cta_ko": "c", "cta_en": "d"}, "cuts": cuts}
    obj["visual_sequences"] = ev.build_for_directive(obj["cuts"], reasoning)
    return dv.normalize_directive(obj, "photo", cut_max_sec=8)


def test_report_directive_actually_calls_the_planner():
    """★★ 소비 지점이 사라지면 여기서 깨진다(논문 라인의 같은 테스트와 같은 취지)."""
    import inspect

    from engine import report_directive
    src = inspect.getsource(report_directive)
    assert "equity_visual.build_for_directive" in src, "지시서가 Equity Planner 를 부르지 않는다"
    assert "reasoning_step" in src, "컷↔stage 를 이을 단계 번호를 요구하지 않는다"


def test_the_router_sees_the_compiled_sequence_as_a_mechanism():
    """★★ 컴파일만 되고 라우터가 못 보면 화면은 예전 그대로다.

    ★ 5단계 중 **4개**가 기전 컷이다. 4단계("2~3분기 뒤 매출로 인식된다")는 리포트가
      숫자를 붙이지 않은 서술 단계라 지불할 주장이 없다 → 라우터가 `connective_in_world`
      로 둔다. 이것은 결함이 아니라 공용 규칙 그대로다(주장 없는 컷에 기전 도해를 붙일
      근거가 없다). **세계는 그대로 물려받는다** — 아래 렌더 테스트가 그것을 확인한다.
    """
    d = _directive_with_sequences()
    routing = d["header"]["visual_routing"]
    assert routing["in_sequence"] == 4, routing
    assert routing["treatments"]["MECHANISM_SEQUENCE"] == 4, routing
    assert routing["connective_in_world"] == 1, routing


def test_the_renderer_chains_the_world_across_report_cuts():
    """★★ 최종 확인 — 렌더가 앞 stage 그림을 참조로 받는가. 여기가 v3 의 목적지다."""
    d = _directive_with_sequences()
    header, assets, kinds = d["header"], {}, []
    for c in d["cuts"]:
        dec = sr.reference_decision(c, header, assets)
        kinds.append(dec["kind"])
        if dec["stage_id"]:
            assets[dec["stage_id"]] = f"/tmp/{dec['stage_id']}.png"
    # 훅은 시퀀스 밖, 첫 stage 가 세계를 세우고, 나머지는 앞 그림에서 이어 만든다.
    assert kinds == ["none", "new_world", "reference", "reference", "reference", "reference"]


def test_belonging_to_a_stage_is_not_by_itself_a_routing_judgement():
    """★★ 2026-08-30 배선 중 실측 — 금융 컷은 beat 를 선언하지 않는다.

    컷을 stage 에 묶자 `stage_ref` 가 생겼고, 그 순간 라우터가 **채워 넣은** 기본
    base(CODE_VIZ)가 판정으로 읽혀 시퀀스 컷이 전부 코드 시각화로 세어졌다 —
    이미지 예산이 0이 된다. 실제 판정의 표시는 `in_visual_sequence` 다.
    """
    plan = {"base": "CODE_VIZ", "beat_declared": False,
            "stage_ref": "S1_ORDER", "reasons": ["connective_in_world"]}
    assert dv._is_code_visual({"resolved_visual_plan": plan}) is False
    plan_real = {**plan, "reasons": ["in_visual_sequence"]}
    assert dv._is_code_visual({"resolved_visual_plan": plan_real}) is True


def test_the_cost_plan_budgets_images_for_a_business_sequence():
    """★ 기전 시퀀스는 그림을 그린다. 코드 차트로 세면 예산이 0이 되고 렌더에서 터진다."""
    cost = _directive_with_sequences()["header"]["cost_plan"]
    assert cost["code_viz_count"] == 0, cost
    assert cost["estimated_image_cost_usd"] > 0, cost


def test_the_planner_reads_the_key_the_ledger_actually_writes():
    """★★ 2026-08-30 실제 리포트로 잡은 결함. 이것이 틀리면 **Phase 5 전체가 무력화**된다.

    `reasoning_units` 는 LLM **출력**의 키다. 정규화를 지나 저장되는 정본 블록
    (`report_drafts.financial_reasoning`)은 `units` 로 담는다. 틀린 키를 읽으면
    조용히 빈 목록이 나오고, 게이트도 경고도 없이 화면은 예전 그대로 나간다.

    ★ 내 단위 테스트는 같은 오해를 픽스처에 담고 있어서 **통과했다.**
      진짜 리포트를 돌려서야 드러났다 — 그래서 여기서 `report_reasoning` 이
      실제로 만드는 모양을 기준으로 못박는다(픽스처를 믿지 않는다).
    """
    from engine import report_reasoning
    assert "units" in report_reasoning.empty(), "원장 블록의 키가 바뀌었다"
    assert "reasoning_units" not in report_reasoning.empty()
    # 원장이 쓰는 모양 그대로 넣으면 시퀀스가 나온다.
    block = {**report_reasoning.empty(), "units": [_unit(LS_STEPS)]}
    assert len(ev.compile_sequences(block)) == 1
    # LLM 출력 키로 넣으면 나오지 않는다 — 관대하게 받으면 정본이 흐려진다.
    assert ev.compile_sequences({"reasoning_units": [_unit(LS_STEPS)]}) == []


def test_out_of_order_cuts_still_produce_a_continuous_world():
    """★★ 2026-08-30 실제 지시서 실측 — 모델이 단계를 **역순으로** 집었다(컷4=4단계, 컷5=2단계).

    그대로 두면 컷4가 `S4` 를 먼저 그리는데 `S4` 는 `S3` 에서 이어받아야 한다.
    `S3` 그림이 없으니 참조를 못 붙이고 새 세계로 떨어졌다 —
    실측 `reference_conditioned 0 · world_reset 3`. 기계는 이어졌는데 화면은 안 이어졌다.

    세계의 사슬은 **화면 순서**를 따른다. 어느 컷이 어느 단계인지는 여전히 모델이
    말한 그대로고, 우리는 이미 정해진 컷 순서를 쓸 뿐이다.
    """
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    cuts = [{"cut_no": 4, "reasoning_id": "R01", "reasoning_step": 4},
            {"cut_no": 5, "reasoning_id": "R01", "reasoning_step": 2}]
    seqs = ev.project_to_screen(ev.assign_cuts(seqs, cuts))
    stages = seqs[0]["stages"]
    assert [s["cut_refs"] for s in stages] == [[4], [5]], "화면 순서를 따르지 않았다"
    assert stages[0]["continuity_mode"] == "NEW_WORLD"
    assert stages[1]["continuity_mode"] == "CONTINUE_WORLD"
    assert stages[1]["continuity_from"] == stages[0]["stage_id"], "세계가 끊겼다"


def test_the_operator_is_told_when_the_argument_is_out_of_order_or_cut_short():
    """★ 이어 붙이되 **숨기지 않는다.** 4단계를 2단계보다 먼저 설명하는 영상은
    대개 구성이 잘못된 것이고, 5단계 중 2개만 나가면 논증이 반쪽이다.
    """
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    cuts = [{"cut_no": 4, "reasoning_id": "R01", "reasoning_step": 4},
            {"cut_no": 5, "reasoning_id": "R01", "reasoning_step": 2}]
    seqs = ev.project_to_screen(ev.assign_cuts(seqs, cuts))
    warns = ev.screen_warnings(seqs)
    assert "equity_steps_out_of_order:SEQ_R01" in warns
    assert "equity_steps_off_screen:SEQ_R01#2/5" in warns
    assert seqs[0]["coverage"]["steps_skipped"] == 3


def test_a_sequence_that_reaches_the_screen_only_once_is_not_a_sequence():
    """★ 화면에 나가는 단계가 1개면 시퀀스가 아니라 한 장면이다.

    남겨 두면 "기전 시퀀스 1개"라고 지표만 좋아지고 화면은 아무것도 안 이어진다.
    """
    seqs = ev.compile_sequences({"units": [_unit(LS_STEPS)]})
    seqs = ev.project_to_screen(ev.assign_cuts(
        seqs, [{"cut_no": 6, "reasoning_id": "R01", "reasoning_step": 1}]))
    assert seqs == []


def test_the_directive_reads_warnings_from_what_it_built_not_the_stripped_header():
    """★★ 공용 정규화는 진단 필드를 버린다(공용 스키마에 없는 키라 당연하다).

    헤더에서 coverage 를 읽으면 경고가 **영영 0건**이 된다 — 만들어 놓고 한쪽만
    연결하는 그 실패의 또 다른 얼굴이다. 실측으로 확인하고 소비 지점을 옮겼다.
    """
    import inspect

    from engine import report_directive
    # 2026-09-14: 재생성 1회를 되살리며 LLM 1회분을 _generate_once 로 뺐다.
    src = inspect.getsource(report_directive._generate_once)
    assert "screen_warnings(seqs)" in src, "정규화 뒤 헤더에서 경고를 읽고 있다"
    # 그리고 실제로 정규화가 버린다는 사실 자체를 못박는다.
    seqs = ev.build_for_directive(
        [{"cut_no": n, "reasoning_id": "R01", "reasoning_step": s} for n, s in [(2, 1), (3, 2)]],
        {"units": [_unit(LS_STEPS)]})
    assert seqs[0].get("coverage"), "투영이 coverage 를 안 남긴다"
    obj = {"header": {"aspect_ratio": "9:16", "hook_ko": "a", "hook_en": "b",
                      "cta_ko": "c", "cta_en": "d"},
           "cuts": [{"cut_no": 2, "narration_ko": "x", "narration_en": "x",
                     "estimated_sec": 5, "visual_prompt": "p"}],
           "visual_sequences": seqs}
    normalized = dv.normalize_directive(obj, "photo", cut_max_sec=8)
    assert normalized["header"]["visual_sequences"][0].get("coverage") is None


def test_a_report_without_reasoning_is_unchanged():
    """★ D6 — 논증이 없으면 **아무 일도 일어나지 않는다.** 옛 리포트가 그대로 돈다."""
    assert ev.build_for_directive([{"cut_no": 1}], None) == []
    assert ev.compile_sequences({"units": []}) == []
