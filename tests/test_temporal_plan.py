"""Invest Temporal Contract — 8초를 **어떻게 쓸 것인가** (v2 Phase E2).

★ 이 파일이 막는 것: **"8초를 줬으니 좋아졌겠지"** 라는 착각.
  코덱스 리뷰 §7 이 지적한 그대로다 — 같은 8초라도 [고정 카메라·미세 움직임]과
  [wide reveal → lateral follow → rapid push-in]은 완전히 다른 영상이다.
  길이만 늘리면 **지루한 8초**가 된다.

★ 그리고 계약이 **실제로 프롬프트에 실리는지**까지 본다. 선언만 하고 prompt builder 가
  안 읽으면 이 저장소가 여덟 번 겪은 "만들어 놓고 한쪽만 연결"의 아홉 번째다.
"""

from __future__ import annotations

from engine import config, directive as dv, sequence_tier as st, temporal_plan as tp
from engine.providers import video as vp


BEATS_RAW = [
    {"t0": 0, "t1": 2.5, "entity_id": "FACTORY_LINE", "mutation": "APPEAR", "camera": "DOLLY_OUT"},
    {"t0": 2.5, "t1": 5.5, "entity_id": "ORDER_BLOCK", "mutation": "MOVE", "camera": "TRACK"},
    {"t0": 5.5, "t1": 8.0, "entity_id": "BACKLOG_QUEUE", "mutation": "GROW", "camera": "DOLLY_IN"},
]


# ── 정규화 ──────────────────────────────────────────────────
def test_the_benchmark_grammar_survives_normalization():
    """★ 벤치마크 문법: 8초 안에 비트 2~3개(전체 → 따라가기 → 급속 푸시인)."""
    beats = tp.normalize(BEATS_RAW, clip_sec=8)
    assert len(beats) == 3
    assert [b["camera"] for b in beats] == ["DOLLY_OUT", "TRACK", "DOLLY_IN"]
    assert tp.coverage(beats, 8) == 1.0


def test_free_text_camera_is_refused():
    """★★ 닫힌 목록만 받는다.

    자유 문장을 허용하면 규격 토큰이 화면에 글자로 박히는 사고가 되돌아온다
    (Phase 0 §3-3 — 프롬프트의 `35 degree` 가 영상에 "35°"로 그려졌다).
    """
    beats = tp.normalize([{"t0": 0, "t1": 4, "camera": "slow cinematic push"}], clip_sec=8)
    assert beats == []


def test_a_beat_outside_the_clip_is_dropped():
    """★ 없는 시간을 가리키는 비트를 프롬프트에 실으면 모델이 그 시간을 채우려 한다."""
    assert tp.normalize([{"t0": 6, "t1": 12, "camera": "TRACK"}], clip_sec=8) == []
    assert tp.normalize([{"t0": 4, "t1": 2, "camera": "TRACK"}], clip_sec=8) == []


def test_overlapping_beats_are_resolved_not_sent_as_a_contradiction():
    """★ 겹치면 같은 순간에 두 가지를 요구한다 — 모델은 둘 다 어중간하게 한다."""
    beats = tp.normalize([
        {"t0": 0, "t1": 5, "camera": "TRACK"},
        {"t0": 3, "t1": 8, "camera": "DOLLY_IN"},      # 앞과 겹친다
    ], clip_sec=8)
    assert len(beats) == 1 and beats[0]["camera"] == "TRACK"


def test_beats_are_capped():
    many = [{"t0": i, "t1": i + 1, "camera": "HOLD"} for i in range(8)]
    assert len(tp.normalize(many, clip_sec=8)) == config.TEMPORAL_MAX_BEATS


# ── 계약 판정 (TC-1) ────────────────────────────────────────
def test_an_empty_plan_fails_every_part_of_the_contract():
    got = tp.evaluate({"temporal_plan": []}, "invest")
    assert any(r.startswith("temporal_beats_too_few") for r in got)
    assert "temporal_camera_plan_missing" in got
    assert "temporal_state_change_missing" in got


def test_camera_moves_alone_are_not_a_mechanism():
    """★ 카메라만 움직이면 "같은 것을 다른 각도에서" 보는 것이지 기전이 아니다."""
    beats = tp.normalize([{"t0": 0, "t1": 4, "camera": "ORBIT"},
                          {"t0": 4, "t1": 8, "camera": "DOLLY_IN"}], clip_sec=8)
    got = tp.evaluate({"temporal_plan": beats}, "invest")
    assert got == ["temporal_state_change_missing"], got


def test_lower_tiers_are_not_asked_for_a_contract():
    """★ economy 브릿지 컷에 연출 계약을 요구하면 옳게 만든 것을 벌하는 게이트가 된다."""
    assert tp.evaluate({"temporal_plan": []}, "economy") == []


# ── 강등 (품질 계약 미이행) ──────────────────────────────────
def _header():
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"}, "entities": [{"entity_id": "A"}],
           "stages": [{"stage_id": f"S{i}", "cut_refs": [i],
                       "mutations": [{"entity_id": "A", "operation": "MOVE",
                                      "visible_change": True, "result_state": f"s{i}"}],
                       "observable_change": f"c{i}"} for i in (1, 2)]}
    return {"version_type": "photo", "visual_sequences": [seq]}


def _mech_cut(beats):
    return {"cut_no": 1, "claim_ids": ["C1"], "temporal_plan": beats,
            "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "sequence_ref": "SEQ1",
                                     "reasons": ["in_visual_sequence"]}}


def test_eight_seconds_is_not_given_to_a_cut_that_cannot_fill_it():
    """★★ TC-1 — 이것은 **비용 강등이 아니라 품질 계약 미이행**이다.

    돈을 아끼려는 것이 아니다. 채울 내용이 없는 컷에 8초를 주면 그 시간이 그대로
    정지 화면이 된다 — 리뷰가 말한 "A. 한 장면을 8초 유지"가 그것이다.
    """
    empty = st.effective_tier(_mech_cut([]), _header())
    assert empty["tier"] == "standard"
    assert "temporal_contract_unmet" in empty["reasons"]
    assert st.clip_sec_for(_mech_cut([]), _header()) == 4

    planned = st.effective_tier(_mech_cut(tp.normalize(BEATS_RAW, 8)), _header())
    assert planned["tier"] == "invest" and planned["reasons"] == []
    assert st.clip_sec_for(_mech_cut(tp.normalize(BEATS_RAW, 8)), _header()) == 8


# ── ★★ 실제로 발주되는가 (한쪽만 연결 방지) ─────────────────
def test_the_beats_are_actually_sent_to_the_video_model():
    """★★ 이것이 이 Phase 의 급소다.

    `temporal_plan` 을 선언하고 prompt builder 가 안 읽으면 계약은 장식이다.
    실제로 나가는 문자열에 시간 구간과 카메라 동작이 들어 있는지 본다.
    """
    beats = tp.normalize(BEATS_RAW, clip_sec=8)
    prompt = vp.build_motion_prompt({"cut_no": 1, "visual_role": "MECHANISM",
                                     "motion_prompt": "", "temporal_plan": beats},
                                    {"version_type": "photo"})
    assert "0.0-2.5s" in prompt and "5.5-8.0s" in prompt, prompt
    assert "pulls back" in prompt and "pushes in rapidly" in prompt
    assert "factory line" in prompt


def test_a_cut_without_beats_keeps_the_old_prompt_shape():
    """★ 하위호환 — 계약이 없으면 종전 모션 문장 그대로다."""
    prompt = vp.build_motion_prompt(
        {"cut_no": 1, "visual_role": "MECHANISM", "motion_prompt": "slow drift"},
        {"version_type": "photo"})
    assert "slow drift" in prompt and "shot sequence within the clip" not in prompt


def test_the_contract_reaches_every_version_that_can_use_it():
    """★★ 2026-08-31 즉시 발견 — 계약을 `_VIDEO_CLIP_GUIDANCE` 에만 넣었더니
    실사형(photo)은 `_PHOTO_VIDEO_CLIP_GUIDANCE` 를 써서 **등급제를 켜는 바로 그
    버전에 계약이 안 갔다.** 독립 상수로 뽑아 두 경로가 같은 문자열을 쓰게 했다.
    """
    import inspect

    from engine import directive as dv
    src = inspect.getsource(dv)
    assert src.count("+ TEMPORAL_CONTRACT_GUIDANCE") >= 3, "계약이 일부 버전에만 간다"
    assert "temporal_plan" in dv.DIRECTIVE_SYSTEM_BASE, "출력 스키마에 필드가 없다"


# ── TC-1: "미달 → 재생성 1회 → 강등" 에서 재생성이 없었다 (2026-09-03) ──
#
# ★★ 작업명세서 §3 은 TC-1 을 "미달 → **재생성 1회** → standard 강등 + 경고"로 정했는데
#   구현은 **바로 강등**이었다(명세 §미검증이 스스로 적어 둔 미구현 항목).
#   그런데 이게 사소한 누락이 아니었다 — 실측 두 편에서 `temporal_contract_unmet` 이
#   **압도적 1위 강등 사유**였고 Moon Impactor 는 invest 가 **0개**였다.
#   즉 등급제가 "기전 컷에 8초를 투자한다"는 목적을 거의 달성하지 못하고 있었다.
#
# ★ 원인은 모델의 태만이 아니라 **순서**다: 어떤 컷이 invest 인지는 시퀀스·라우터를 보고
#   코드가 나중에 정하는데 모델은 그걸 모른 채 비트를 쓴다(그래서 기본 1개).
#   1차 생성이 구조를 드러낸 뒤에야 "어느 컷에" 비트가 필요한지 찍어 줄 수 있다 —
#   명세가 재생성을 넣은 이유가 이것이다.

def _invest_cut(no, beats):
    """기전 시퀀스에 속하고 주장도 붙은 컷 — 계약만 채우면 invest 가 된다.

    ★ 모양은 실제 지시서(moon_impactor v5 컷1)에서 떴다. 픽스처를 손으로 지어내면
      내 오해를 그대로 복사한다 — 이 저장소가 이미 겪은 실패다.
    """
    return {"cut_no": no, "claim_ids": ["C01"], "temporal_plan": beats,
            "resolved_visual_plan": {"cut_no": no, "base": "MECHANISM_SEQUENCE",
                                     "sequence_ref": "SEQ1", "stage_ref": "S1",
                                     "claim_refs": ["C01"],
                                     "reasons": ["in_visual_sequence"]},
            "stage_mutations": [{"entity_id": "X", "property": "position",
                                 "operation": "APPEAR", "visible_change": True,
                                 "claim_ids": ["C01"]}]}


def _invest_header(cut_nos):
    """등급 판정은 **헤더의 시퀀스**를 본다(`sequence_tier._sequence_of`).

    컷만 만들어 놓으면 no_sequence 로 떨어진다 — 처음에 그렇게 써서 테스트가 잡았다.
    """
    return {"version_type": "photo", "visual_sequences": [{
        "sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
        "world": {"world_id": "LAB"},
        "entities": [{"entity_id": "X", "visual_identity": "a device"}],
        "stages": [
            {"stage_id": "S1", "cut_refs": list(cut_nos), "claim_ids": ["C01"],
             "observable_change": "단면이 열린다", "entity_refs": ["X"],
             "state_before": {"X": "closed"}, "state_after": {"X": "open"},
             "mutations": [{"entity_id": "X", "operation": "TRANSFORM",
                            "property": "section", "visible_change": "단면이 열린다"}]},
            {"stage_id": "S2", "cut_refs": [], "claim_ids": ["C01"],
             "continuity_mode": "CONTINUE_WORLD", "continuity_from": "S1",
             "observable_change": "흐름이 이동한다", "entity_refs": ["X"],
             "state_before": {"X": "open"}, "state_after": {"X": "flowing"},
             "mutations": [{"entity_id": "X", "operation": "TRANSFORM",
                            "property": "flow", "visible_change": "흐름이 보인다"}]},
        ]}]}


def test_shortfall_lists_cuts_that_only_miss_the_contract():
    """계약 하나만 걸린 컷 = 비트만 채우면 8초를 받는 컷."""
    thin = _invest_cut(3, [{"beat": 1, "t0": 0, "t1": 6, "entity_id": "X",
                            "mutation": "HIGHLIGHT", "camera": "HOLD"}])
    hdr = _invest_header([3])
    assert 3 in st.contract_shortfall([thin], hdr)


def test_a_cut_failing_for_other_reasons_is_not_a_shortfall():
    """★ 다른 이유로도 미달인 컷은 비트를 채워도 invest 가 안 된다 — 되먹임 대상이 아니다.

    이걸 안 가르면 고쳐도 소용없는 컷을 모델에게 고치라고 시킨다.
    """
    no_claim = _invest_cut(4, [])
    no_claim["claim_ids"] = []
    hdr = _invest_header([4])
    assert 4 not in st.contract_shortfall([no_claim], hdr)


def test_feedback_names_the_cut_numbers_and_what_is_missing():
    """되먹임은 "다시 해라"가 아니라 무엇이 왜 부족한지다(저장소 규율)."""
    thin = _invest_cut(7, [{"beat": 1, "t0": 0, "t1": 6, "entity_id": "X",
                            "mutation": "", "camera": "ORBIT"}])
    fb = tp.shortfall_feedback([7], [thin])
    assert "컷 7" in fb
    assert "temporal_beats_too_few" in fb
    assert "비트 2~3개" in fb
    assert "나머지 컷은 그대로 둬라" in fb      # 다른 컷을 망가뜨리지 않게


def test_no_shortfall_means_no_feedback():
    assert tp.shortfall_feedback([], []) == ""


def test_the_retry_is_triggered_by_shortfall_alone():
    """★★ 핵심 회귀: TC-1 은 **차단이 아니라 강등**이라 block_reasons 에 안 들어간다.

    그래서 종전에는 차단 사유가 없으면 재생성을 아예 안 띄웠고, 명세가 말한
    "재생성 1회"가 사실상 존재하지 않았다.
    """
    import inspect
    src = inspect.getsource(dv.generate)
    assert "first_short" in src
    # ★ 2026-09-09: 품질 경고도 재생성을 띄우게 되면서 조건에 항이 하나 늘었다.
    #   이 검사의 뜻은 그대로다 — **차단 사유만으로 판단하지 않는다.**
    assert "if not first_reasons and not first_short and not first_quality:" in src,         "차단 사유만으로 판단하고 있다"


def test_the_feedback_is_actually_attached():
    """상수를 만들고 붙이지 않는 것이 이 저장소의 단골 실패다."""
    import inspect
    assert "shortfall_feedback" in inspect.getsource(dv._contract_feedback)


def test_tc1_stays_a_demotion_not_a_block():
    """★ 재생성 뒤에도 미달이면 **강등**이지 차단이 아니다(명세 §3 그대로).

    여기를 차단으로 만들면 "모든 것을 막는 게이트"가 하나 더 생긴다.
    """
    import inspect
    src = inspect.getsource(dv.generate)
    assert "강등된다" in src
    # shortfall 이 approval_blocked 를 켜지 않는다
    assert "approval_blocked" not in src.split("retry_short")[-1][:400]


def test_tc1_feedback_is_not_stacked_on_block_reasons():
    """★★ 실측(2026-09-03): 되먹임을 쌓았더니 재생성이 **파괴적**으로 변했다.

        차단 되먹임만  1차 5건 → 2차 3건  (개선)
        TC-1 을 얹음   1차 3건 → 2차 14건 (악화)
      새로 생긴 위반: vseq_no_actual_mutation · vseq_no_progression ·
      vseq_state_lineage_mismatch — 모델이 시퀀스를 통째로 다시 쓰면서 진행을 깨뜨렸다.

    우선순위가 다르다: 차단은 **승인을 막는 것**이고 TC-1 은 8초 vs 4초 최적화다.
    """
    import inspect
    src = inspect.getsource(dv._contract_feedback)
    assert "_contract_reasons(directive)" in src, "차단 유무를 안 보고 얹고 있다"
    assert 'else tplan.shortfall_feedback' in src


def test_tc1_feedback_still_fires_when_there_are_no_blocks():
    """★ 차단이 없을 때는 TC-1 이 유일한 재생성 이유다 — 그때는 반드시 나가야 한다.

    안 그러면 TC-1 재생성이 다시 "한 번도 안 뜨는" 상태로 돌아간다.
    """
    thin = _invest_cut(3, [{"beat": 1, "t0": 0, "t1": 6, "entity_id": "X",
                            "mutation": "HIGHLIGHT", "camera": "HOLD"}])
    clean = {"header": {**_invest_header([3]), "photo_gate": {"block_reasons": []},
                        "visual_sequence_gate": {"block_reasons": []}},
             "cuts": [thin]}
    fb = dv._contract_feedback(clean)
    assert "연출 계약 미이행" in fb and "컷 3" in fb


# ── 계약이 "안 움직임"을 통과시키던 것 (2026-09-04) ──
#
# ★★ 운영자 지적: "달 클립 샘플은 괜찮았는데 직접 만든 건 왜 이렇게 별로냐."
#   추적해 보니 **좋은 샘플에서 성공 조건을 안 뽑았다.** G2 결과 문서(8/31)는 결함만
#   정리했고("세계를 버린다", "글자가 박혔다") 잘된 쪽은 "배선이 작동한다" 한 줄로 끝났다.
#   그 사이 계약은 `min_beats`·`camera_plan`·`state_change` 를 **필드 존재**로만 검사했다.
#   결과: 오늘 지시서가 `APPEAR+HOLD` 두 번으로 8초를 받고 아무것도 안 움직였다.
#
# ★ 기준선은 실측 둘이 같은 말을 한 것이다:
#     달 클립 좋았던 팔  DOLLY_OUT → TRACK → DOLLY_IN, 마지막 IMPACT
#     Apify 벤치마크    "8초에 비트 2개, 횡이동 + 마지막 급속 푸시인"

def _beats(*triples):
    out, t = [], 0.0
    for mut, cam, dur in triples:
        out.append({"t0": t, "t1": t + dur, "entity_id": "X", "mutation": mut, "camera": cam})
        t += dur
    return {"temporal_plan": out}


def test_the_moon_clip_beats_pass():
    """실제로 화면에서 작동한 비트가 계약을 통과해야 한다 — 기준선이다."""
    cut = _beats(("APPEAR", "DOLLY_OUT", 2.5), ("MOVE", "TRACK", 3.0), ("IMPACT", "DOLLY_IN", 2.5))
    assert tp.evaluate(cut, "invest") == []


def test_appear_and_hold_no_longer_earns_eight_seconds():
    """★★ 오늘 지시서의 invest 컷이 정확히 이랬다 — 8초를 받고 정지 화면이었다."""
    cut = _beats(("APPEAR", "HOLD", 3.0), ("APPEAR", "HOLD", 3.0))
    got = tp.evaluate(cut, "invest")
    assert "temporal_camera_never_moves" in got
    assert "temporal_no_transforming_mutation" in got


def test_a_camera_that_never_moves_is_caught():
    """HOLD 는 '카메라가 가만히 있다'다 — 필드가 있다고 계획이 있는 게 아니다."""
    cut = _beats(("TRANSFORM", "HOLD", 4.0), ("MOVE", "HOLD", 4.0))
    assert "temporal_camera_never_moves" in tp.evaluate(cut, "invest")


def test_the_same_camera_twice_is_not_a_multishot():
    """벤치마크의 '멀티샷'은 한 컷 안에서 화면이 여러 번 바뀌는 것이다."""
    cut = _beats(("TRANSFORM", "ORBIT", 4.0), ("MOVE", "ORBIT", 4.0))
    assert "temporal_camera_monotone" in tp.evaluate(cut, "invest")


def test_appear_and_highlight_alone_are_not_a_mechanism():
    """'나타났다/빛난다'는 정지 화면으로도 성립한다 — 기전을 설명하지 못한다."""
    cut = _beats(("APPEAR", "ORBIT", 4.0), ("HIGHLIGHT", "DOLLY_IN", 4.0))
    assert "temporal_no_transforming_mutation" in tp.evaluate(cut, "invest")


def test_standard_tier_is_untouched():
    """★ 계약을 조인 것은 invest 뿐이다 — standard·economy 는 종전 그대로다.

    여기를 같이 조이면 대부분의 컷이 강등돼 "모든 것을 막는 게이트"가 하나 더 생긴다.
    """
    cut = _beats(("APPEAR", "HOLD", 3.0))
    assert tp.evaluate(cut, "standard") == []
    assert tp.evaluate(cut, "economy") == []


def test_the_prompt_carries_the_measured_example():
    """★ 계약만 조이고 예시를 안 주면 모델은 또 최저선을 찾는다(라벨에서 배운 것)."""
    g = dv.TEMPORAL_CONTRACT_GUIDANCE
    assert "좋은 비트의 실측 예시" in g
    assert "TRACK" in g and "DOLLY_IN" in g and "IMPACT" in g
    assert "횡이동" in g          # 벤치마크 공식
    assert "최소 하나는 HOLD 가 아니어야" in g
