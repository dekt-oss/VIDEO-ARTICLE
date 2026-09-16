"""시퀀스 등급제 — 품질 의도가 실행 품질이 되는가 (v2 Phase A·B).

★ 이 파일이 막는 것 둘:
  ① **선착순 회귀** — 예산이 컷 순서대로 나가고 뒤의 기전 컷이 스틸로 강등되던 것
     (2026-08-31 ESS 실측: `컷 9 스틸로 강등`). 등급은 순서를 보지 않는다.
  ② **라우터 우회** — 시퀀스 소속만 보면 같은 기전 시퀀스의 연결 컷·CTA 도 8초를
     받는다. 등급은 canonical router 판정(`resolved_visual_plan`)을 반드시 읽는다.

★ 전부 순수 판정이라 라이브 키 없이 돈다.
"""

from __future__ import annotations

from engine import config, generation_spec as gs, sequence_tier as st


def _seq(sid="SEQ1", role="MECHANISM_SEQUENCE", stages=2):
    """진행하는 시퀀스(구조 판정 통과)."""
    return {
        "sequence_id": sid, "sequence_role": role,
        "world": {"world_id": "W"}, "entities": [{"entity_id": "A"}],
        "stages": [{"stage_id": f"S{i}", "cut_refs": [i],
                    "mutations": [{"entity_id": "A", "operation": "MOVE",
                                   "visible_change": True, "result_state": f"state {i}"}],
                    "observable_change": f"변화 {i}"} for i in range(1, stages + 1)],
    }


def _header(*seqs, version="photo"):
    return {"version_type": version, "visual_sequences": list(seqs) or [_seq()]}


# 연출 계약을 채운 비트(TC-1 통과용). invest 는 8초를 **어떻게 쓸지**까지 있어야 한다.
BEATS = [{"beat": 1, "t0": 0.0, "t1": 3.0, "entity_id": "A",
          "mutation": "APPEAR", "camera": "DOLLY_OUT"},
         {"beat": 2, "t0": 3.0, "t1": 8.0, "entity_id": "A",
          "mutation": "GROW", "camera": "DOLLY_IN"}]


def _cut(no=1, base="MECHANISM_SEQUENCE", reasons=("in_visual_sequence",),
         claims=("C1",), seq="SEQ1", beats=None):
    return {"cut_no": no, "claim_ids": list(claims),
            "temporal_plan": list(BEATS if beats is None else beats),
            "resolved_visual_plan": {"base": base, "sequence_ref": seq,
                                     "reasons": list(reasons)}}


# ── 등급 판정 ───────────────────────────────────────────────
def test_a_real_mechanism_cut_earns_the_investment():
    got = st.effective_tier(_cut(), _header())
    assert got["tier"] == "invest" and got["reasons"] == [] and got["defaulted"] is False


def test_a_connective_cut_in_the_same_sequence_does_not_get_eight_seconds():
    """★★ 코덱스 리뷰 P0-1 의 핵심.

    라우터는 이미 "세계만 물려받는 연결 컷"을 갈라 놓았다. 시퀀스 소속만 보고 등급을
    주면 그 판정을 덮어써서 CTA·브릿지가 8초를 먹는다 — 투자할 곳에 투자가 안 된다.
    """
    cut = _cut(reasons=("connective_in_world",), base="CODE_VIZ")
    got = st.effective_tier(cut, _header())
    assert got["tier"] == "standard"
    assert "connective_cut" in got["reasons"]
    assert st.clip_sec_for(cut, _header()) == 4


def test_the_models_sequence_label_is_not_trusted():
    """★★ 2026-08-31 골든B 실측 — 이 저장소가 이미 한 번 고친 결함의 재발 방지.

    골든B 는 6 stage 짜리 진짜 진행인데 모델이 `RESULT_SEQUENCE` 라 라벨했다.
    라우터는 6컷 전부 MECHANISM_SEQUENCE 로 판정했다. 라벨을 조건에 넣으면
    **진짜 기전 시퀀스가 통째로 invest 자격을 잃는다** — 계획서 §9-2 S4 가
    기록한 그 사고("라우터만 고치고 지표는 안 고쳤다")가 그대로 재현된다.

    코덱스 리뷰 §6 의 조건 목록에는 이 항목이 있었지만, 실측이 저장소의 확정
    결정(라벨은 진단용 메타데이터) 손을 들어 줬다.
    """
    mislabeled = _seq(role="RESULT_SEQUENCE")     # 라벨은 틀렸지만 구조는 진행이다
    got = st.effective_tier(_cut(), _header(mislabeled))
    assert got["tier"] == "invest", got["reasons"]


def test_a_label_alone_cannot_buy_the_investment():
    """★ 시퀀스가 MECHANISM 이라 **말만** 하고 실제로 진행하지 않으면 자격이 없다.

    구조 판정(`sequence_is_progression`)이 앞에 선다 — 새 자기보고를 만들지 않고
    기존 코드 판정을 그대로 소비한다(코덱스 리뷰 S4).
    """
    flat = _seq(stages=1)                       # stage 1개 = 진행이 아니다
    got = st.effective_tier(_cut(), _header(flat))
    assert got["tier"] != "invest"
    assert "not_a_progression" in got["reasons"]


def test_a_cut_that_pays_no_claim_is_not_a_mechanism_cut():
    got = st.effective_tier(_cut(claims=()), _header())
    assert got["tier"] != "invest" and "claim_unlinked" in got["reasons"]


def test_a_cut_outside_every_sequence_falls_back_and_says_so():
    """★ 판정해서 내려간 것과 **근거가 없어 기본값으로 채운 것**을 구분한다(§9-10)."""
    cut = {"cut_no": 9, "resolved_visual_plan": {"base": "CODE_VIZ", "sequence_ref": ""}}
    got = st.effective_tier(cut, _header())
    assert got["tier"] == "economy" and got["defaulted"] is True
    assert got["reasons"] == ["no_sequence"]


def test_every_blocker_is_reported_not_just_the_first():
    """★ "왜 invest 가 아닌가"를 운영자가 읽어야 한다. 하나만 남기면 고칠 수 없다."""
    cut = _cut(base="CODE_VIZ", reasons=("connective_in_world",), claims=())
    got = st.effective_tier(cut, _header(_seq(role="FRAMING")))
    for expected in ("plan_not_mechanism", "connective_cut", "claim_unlinked"):
        assert expected in got["reasons"], got["reasons"]


# ── 선착순 회귀 방지 ─────────────────────────────────────────
def test_position_in_the_video_does_not_decide_quality():
    """★★ 이 저장소가 실제로 겪은 사고의 회귀 테스트.

    예전 `enforce_mode_video_budget` 은 앞 컷부터 예산을 주고 뒤를 스틸로 강등했다
    (실측 로그: `컷 9 스틸로 강등`). 기전 시퀀스가 **마지막 컷**이어도 invest 여야 한다.
    """
    header = _header(_seq())
    first = st.effective_tier(_cut(no=1), header)
    last = st.effective_tier(_cut(no=99), header)
    assert first["tier"] == last["tier"] == "invest"
    assert st.clip_sec_for(_cut(no=99), header) == 8


# ── 등급제 밖 버전은 종전 그대로 ────────────────────────────
def test_versions_outside_the_scheme_are_untouched():
    """★ 만화식·설명판형은 등급을 매기지 않는다. 종전 경로가 그대로 돈다(하위호환)."""
    got = st.effective_tier(_cut(), _header(version="comic"))
    assert got["tier"] == "" and got["reasons"] == []
    # 길이도 지어내지 않는다 — 0 은 "호출측이 종전 로직을 쓰라"는 뜻이다.
    assert st.clip_sec_for(_cut(), _header(version="comic")) == 0
    assert st.candidates_for(_cut(), _header(version="comic")) == 1


# ── Quality Profile — 등급은 길이 하나가 아니다 ──────────────
def test_the_tier_carries_direction_not_just_duration():
    """★ 리뷰 §7: 8초를 주는 것과 8초를 제대로 쓰는 것은 다른 문제다."""
    inv = config.tier_profile("invest")
    assert inv["clip_sec"] == 8
    assert inv["min_beats"] >= 2                  # 한 클립 안에 편집 시퀀스가 들어간다
    assert inv["camera_plan"] == "required"
    assert inv["state_change"] == "required"
    # ★ 2 → 1 (2026-09-13 운영자 지시 "후보 1발로 내려"). 2발은 그 컷 영상비가 두 배인데
    #   지금까지 렌더가 전부 standard 라 2발이 한 번도 실행된 적이 없다 — 더 낫다는 실측이
    #   나오면 INVEST_CANDIDATES=2 로 되돌린다. 길이·연출 계약은 그대로다(등급의 본체).
    assert inv["candidates"] == 1
    assert config.tier_profile("economy")["candidates"] == 1


def test_candidates_follow_the_configured_profile():
    """2026-09-13 이전에는 invest 가 2발이었다(test 이름도 그랬다). 지금은 설정이 정본이다."""
    assert st.candidates_for(_cut(), _header()) == config.TIER_PROFILE["invest"]["candidates"]
    assert st.candidates_for(_cut(reasons=("connective_in_world",)), _header()) == 1


def test_the_version_cap_still_bounds_the_tier():
    """★ 등급이 버전 상한을 넘어서 사지는 않는다."""
    assert st.clip_sec_for(_cut(), _header(), version_cap=4) == 4


# ── 단일 실행 계약 (P0-2) ───────────────────────────────────
def test_the_spec_carries_the_tier_into_the_cache_key():
    """★★ 등급이 캐시 키에 없으면 8초로 올려도 옛 4초 클립이 재사용된다."""
    a = gs.video_spec({"cut_no": 1}, {}, clip_sec=8, tier="invest", candidates=2)
    b = gs.video_spec({"cut_no": 1}, {}, clip_sec=8, tier="standard", candidates=1)
    assert a.cache_fields() != b.cache_fields()
    assert a.cache_fields()["tier"] == "invest"


def test_the_provider_does_not_re_decide_length_or_model():
    """★★ 코덱스 리뷰 P0-2 — 가장 위험한 "만들어 놓고 소비자가 안 읽는" 지점.

    provider 가 `pick_clip_tier` 를 재호출하고 전역 `VEO_MODEL` 을 쓰면, 스펙에 8초를
    적어도 4초를 사게 된다. 예상 스펙 = 발주 스펙 = 기록 스펙이어야 한다.
    """
    import inspect

    from engine.providers import video as vp
    src = inspect.getsource(vp._veo_i2v)
    assert "spec.clip_sec" in src, "provider 가 스펙의 길이를 읽지 않는다"
    assert "spec.model" in src, "provider 가 스펙의 모델을 읽지 않는다"
    assert "spec.unit_price_usd" in src, "provider 가 스펙의 단가를 읽지 않는다"
    # 스펙이 있으면 전역 상한 재적용 경로로 가지 않는다.
    assert "int(spec.clip_sec) if spec is not None" in src


# ── Phase E: I2V 연쇄 경계 + 드리프트 제어 ────────────────────
def _chain_decisions(worlds):
    """컷마다 world_ref 를 주고 렌더의 사슬 판정만 재현한다(파일 접근 없음).

    렌더 루프의 리셋 규칙을 그대로 옮긴 것이라, 규칙이 바뀌면 이 테스트가 먼저 깨진다.
    """
    chain = {"frame": None, "clip_key": None, "world_ref": "", "depth": 0}
    out = []
    for w in worlds:
        world_ref = str(w or "")
        same_world = bool(world_ref) and world_ref == str(chain["world_ref"] or "")
        if chain["frame"] and not same_world:
            chain.update(frame=None, clip_key=None, depth=0)
        if int(chain["depth"]) >= config.MAX_CHAIN_DEPTH:
            chain.update(frame=None, clip_key=None, depth=0)
        chain["world_ref"] = world_ref
        chained = bool(chain["frame"])
        if chained:
            chain["depth"] += 1
        out.append(chained)
        chain["frame"] = "f.png"          # 이 컷이 영상이라 다음 컷에 프레임을 남긴다
    return out


def test_the_same_world_keeps_the_chain():
    assert _chain_decisions(["W1", "W1"])[1] is True


def test_a_new_world_breaks_the_chain():
    """★ video-first 의 선행조건 — 스틸이 없어져도 세계가 바뀌면 끊긴다."""
    assert _chain_decisions(["W1", "W2"])[1] is False


def test_two_unknown_worlds_are_not_the_same_world():
    """★★ 코덱스 리뷰 §11 문제 1 — `None == None` 을 연쇄로 읽으면 안 된다.

    세계를 **모르는** 두 컷은 같은 세계라는 근거가 없다. 판정 불가를 "같다"로
    읽는 순간, 시퀀스 밖 컷들이 서로의 마지막 프레임에서 이어 만들어진다.
    """
    assert _chain_decisions(["", ""])[1] is False


def test_the_chain_rebases_before_drift_accumulates():
    """★ 생성물을 다시 anchor 로 쓰는 깊이 상한(리뷰 §11 문제 2).

    8초 클립이 길어질수록 identity·geometry 드리프트가 누적된다 —
    일정 깊이마다 원본으로 되돌린다.
    """
    got = _chain_decisions(["W1"] * 5)
    assert config.MAX_CHAIN_DEPTH == 2
    assert got == [False, True, True, False, True], got   # 2회 이어붙인 뒤 rebase


def test_video_first_cannot_be_switched_on_without_the_chain_boundary():
    """★★ 작업명세서가 요구한 **강제**다.

    video-first 는 스틸이라는 유일한 사슬 경계를 없앤다. Phase E(world 경계)가 없으면
    세계가 바뀌어도 앞 장면 마지막 프레임에서 이어 만들어 **엉뚱한 장소가 계속된다.**
    스위치만 켜고 경계를 안 넣는 순서를 코드로 막는다.
    """
    import inspect

    from engine import render
    if not config.VIDEO_FIRST_VERSIONS:
        return                              # 아직 안 켰다 — 검사할 것이 없다
    src = inspect.getsource(render)
    assert 'chain["world_ref"]' in src, \
        "video-first 가 켜졌는데 world 경계가 없다 — 엉뚱한 장소가 이어진다"
    assert "config.MAX_CHAIN_DEPTH" in src, \
        "video-first 가 켜졌는데 연쇄 깊이 제한이 없다 — 드리프트가 누적된다"


def test_video_first_respects_an_explicit_still():
    """★ 목표는 "모든 컷을 video 플래그로"가 아니라 **정적으로 느껴지지 않는 화면**이다.

    모델이 명시적으로 still 이라고 적은 컷까지 뒤집으면 Veo 를 CTA 에 쓰게 된다 —
    리뷰 §10 이 경고한 "쓸모없는 생성물이 늘어난다"가 그것이다.
    """
    from engine import directive as dv
    assert dv.sanitize_motion_source("still", "photo") == "still"
    assert dv.sanitize_motion_source("video", "photo") == "video"


def test_the_render_loop_owns_these_rules():
    """★ 위 규칙이 렌더에서 사라지면 여기서 깨진다(테스트만 통과하는 규칙 방지)."""
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert 'chain["world_ref"]' in src, "렌더가 세계 경계를 보지 않는다"
    assert "config.MAX_CHAIN_DEPTH" in src, "렌더가 연쇄 깊이를 제한하지 않는다"


# ── Phase C: 조용한 강등 제거 ────────────────────────────────
def _directive_obj(version="photo", n=10):
    """영상 컷 10개짜리 지시서 raw. 상한(8개)을 일부러 넘긴다."""
    cuts = [{"cut_no": i, "narration_ko": f"문장{i}", "narration_en": "x",
             "estimated_sec": 5, "visual_prompt": "p", "motion_source": "video",
             "motion_value": "low",            # 종전이면 motion 게이트가 전부 스틸로 내린다
             "scene_kind": "broll_stock"}
            for i in range(1, n + 1)]
    return {"header": {"aspect_ratio": "9:16", "hook_ko": "a", "hook_en": "b",
                       "cta_ko": "c", "cta_en": "d"}, "cuts": cuts}


def test_no_cut_is_silently_turned_into_a_still():
    """★★ 이 저장소가 겪은 사고의 본체.

    종전에는 네 겹(motion 게이트 · 모드 선착순 · 전역 개수 캡 · preflight)이 전부
    `motion_source` 를 말없이 바꿨다. 실측 로그가 `컷 9 스틸로 강등`이었다.
    등급제 버전에서는 **하나도 바꾸지 않는다** — 대신 경고로 드러난다.
    """
    from engine import directive as dv
    d = dv.normalize_directive(_directive_obj(), "photo", cut_max_sec=8)
    assert all(c["motion_source"] == "video" for c in d["cuts"]), \
        [c["cut_no"] for c in d["cuts"] if c["motion_source"] != "video"]
    warns = d["header"]["mode_warnings"]
    assert any(w.startswith("motion_gate_would_demote") for w in warns), warns
    assert any(w.startswith("video_cap_exceeded") for w in warns), warns


def test_a_version_outside_the_scheme_keeps_the_old_demotions():
    """★ 하위호환 — 만화식은 종전 그대로 강등된다. 등급제가 새어 들어가지 않는다."""
    from engine import directive as dv
    d = dv.normalize_directive(_directive_obj(version="comic"), "comic", cut_max_sec=8)
    demoted = [c for c in d["cuts"] if c["motion_source"] == "still"]
    assert demoted, "등급제 밖 버전인데 종전 강등이 사라졌다"


def test_the_estimate_counts_the_length_and_the_candidates_it_will_actually_buy():
    """★★ ⑤ 가 4초로 보여주고 렌더가 8초를 두 번 사면 총액이 4배 어긋난다.

    이 숫자가 `video_budget_exceeded`(발주 전 fail-fast)의 입력이므로, 틀리면
    P0-4 안전장치가 엉뚱한 값으로 돌거나 아예 안 돈다.
    """
    from engine import directive as dv
    seq = _seq()
    cuts = [dict(_cut(no=1), motion_source="video", estimated_sec=4,
                 narration_ko="x", narration_en="x", visual_prompt="p")]
    plan_tiered = dv.compute_cost_plan(cuts, "standard", "photo", [seq])
    plan_legacy = dv.compute_cost_plan(cuts, "standard", "comic", [seq])
    # invest: 8초 × 후보 1 = 8초(2026-09-13 운영자 지시로 후보 2→1). 등급제 밖: 4초.
    expect = 8 * config.TIER_PROFILE["invest"]["candidates"]
    assert plan_tiered["video_generated_sec"] == expect, plan_tiered["video_generated_sec"]
    assert plan_legacy["video_generated_sec"] == 4, plan_legacy["video_generated_sec"]


def test_the_estimate_the_spec_and_the_breakdown_are_one_number():
    """★★ G1 정합 — "예상 비용을 보고 조절한다"(운영자 확정)가 성립하려면
    예상·발주·내역이 **같은 숫자**여야 한다. 하나라도 갈라지면 조절의 근거가 사라진다.

    리뷰 §13 이 요구한 단일 진실원: cost_plan = VideoSpec = 원장.
    """
    from engine import directive as dv, generation_spec as gs

    seq = _seq()
    hdr = _header(seq)
    cuts = [dict(_cut(no=i), motion_source="video", estimated_sec=5,
                 narration_ko="x", narration_en="x", visual_prompt="p") for i in (1, 2)]
    plan = dv.compute_cost_plan(cuts, "standard", "photo", [seq])

    spec_sec = 0
    for c in cuts:
        tier = st.effective_tier(c, hdr)["tier"]
        spec = gs.video_spec(c, hdr, clip_sec=st.clip_sec_for(c, hdr), tier=tier,
                             candidates=st.candidates_for(c, hdr))
        spec_sec += spec.clip_sec * spec.candidates

    assert plan["video_generated_sec"] == spec_sec, "예상과 발주 스펙이 갈라진다"
    assert sum(r["video_sec"] for r in plan["sequences"]) == spec_sec, \
        "장면 내역 합계가 총액과 어긋난다 — 운영자가 '나머지는 어디 갔나'를 묻게 된다"


def test_the_approval_budget_does_not_block_the_quality_configuration():
    """★★ 2026-08-31 실측 — **내가 만든 게이트가 스스로를 막고 있었다.**

    지금 엔진으로 지시서를 재생성했더니 등급제가 영상 70초를 만들었는데 승인 예산은
    등급제 이전 값(48초) 그대로라 `video_budget_exceeded` 로 차단됐다. 하드캡은
    4→8 로 올려 놓고 **승인 예산은 안 올린** 것이다.

    ★ 모든 것을 막는 게이트는 **없는 게이트와 같다.** 운영자가 매번 강제 승인을
      누르기 시작하면 그 뒤로는 진짜 초과도 안 보인다.

    세 숫자가 한 구성에서 나와야 한다:
        승인 예산  <  예상 총액  <  하드캡
    """
    sec, usd = config.video_budget_for("photo", {"max_video_generated_sec": 8,
                                                 "max_video_cost_usd": 0.4})
    # 품질 우선 구성(기획서 §8): invest 4컷×8초×후보2 + 나머지 8컷×4초 = 96초
    assert sec >= 96, f"승인 예산({sec}초)이 품질 구성(96초)을 못 담는다"
    assert usd < config.render_budget_cap("photo"), "승인 예산이 하드캡보다 크면 순서가 뒤집힌다"


def test_the_hard_cap_leaves_room_for_the_quality_configuration():
    """★ 캡은 하드 스톱이라(렌더 도중 RuntimeError) 품질 구성보다 낮으면 정상 편이 죽는다.

    품질 우선 구성 실측 추정 ~$5.3–6.0 (기획서 §8) — 캡이 그보다 커야 한다.
    """
    assert config.render_budget_cap("photo") >= 6.0


def test_a_legacy_cut_calls_the_provider_exactly_as_before():
    """★★ 2026-08-31 실측 — 새 kwarg 를 무조건 넘겼더니 테스트 3건이 깨졌다.

    표면적으로는 페이크 시그니처 문제지만 드러난 것은 더 중요하다: 옛 시그니처
    호출부가 있으면 **TypeError 가 재시도 루프에 삼켜져 조용히 스틸로 떨어진다.**
    영상이 사라지는데 사유는 "I2V 실패"로만 남는다. 이미지 경로가 같은 이유로
    이미 "참조가 없으면 인자를 안 넘긴다"로 되어 있다.

    그래서 등급이 없으면 `spec` 을 넘기지 않는다. spec 을 못 받는 페이크로 못박는다.

    ★ 이 검사는 종전에 소스 문자열(`"if vid_spec.tier:" in src`)을 봤다. 그건 규약의
      **대리 표지**일 뿐이라, 동작이 그대로여도 리팩터링 한 번에 깨지고(실제로 후보
      루프를 함수로 빼자 깨졌다) 반대로 문자열만 남기고 동작을 바꿔도 통과한다.
      지금은 **실제로 호출해** 본다 — 옛 시그니처(spec 을 못 받는) 페이크에게
      등급 없는 컷을 보내 TypeError 가 안 나는지 보고, 등급 있는 컷은 spec 을
      받았는지 본다. 규약 자체를 검사하므로 리팩터링에 흔들리지 않는다.
    """
    from unittest import mock

    from engine import render

    calls: list[dict] = []

    def legacy_provider(cut, header, out_path, duration, lang="ko",
                        start_image=None, fact_sheet=None):
        """spec kwarg 를 **못 받는** 옛 시그니처. 넘기면 TypeError 가 난다."""
        calls.append({"duration": duration, "start_image": start_image})
        return out_path, 0.0

    legacy_spec = gs.video_spec({}, {}, clip_sec=4, tier="")
    assert legacy_spec.tier == "", "이 테스트의 전제(등급 없음)가 깨졌다"
    with mock.patch.object(render.video_provider, "generate_clip", legacy_provider):
        cost, pick = render._veo_generate_scored(
            {}, {}, "/tmp/x.mp4", 4, "/tmp/a.png", legacy_spec, cut_no=1)
    assert calls and pick is None and cost == 0.0

    # 등급이 있으면 반대로 spec 을 **반드시** 받는다(P0-2: 발주한 스펙 = 기록한 스펙).
    got: list = []

    def tiered_provider(cut, header, out_path, duration, lang="ko",
                        start_image=None, fact_sheet=None, spec=None):
        got.append(spec)
        return out_path, 0.0

    tiered = gs.video_spec({}, {}, clip_sec=8, tier="invest", candidates=1)
    with mock.patch.object(render.video_provider, "generate_clip", tiered_provider), \
            mock.patch.object(render.clip_candidates, "probe_motion", lambda *a: {}), \
            mock.patch.object(render.clip_candidates, "score", lambda *a, **k: {"score": 1}):
        render._veo_generate_scored({}, {}, "/tmp/y.mp4", 8, "/tmp/a.png", tiered, cut_no=2)
    assert got == [tiered], "등급 컷이 스펙 없이 발주됐다 — 길이·모델을 provider 가 다시 정한다"


def test_the_render_path_actually_asks_for_the_tier():
    """★ 소비 지점이 사라지면 여기서 깨진다(등급을 만들고 렌더가 무시하는 것 방지)."""
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert "sequence_tier.effective_tier" in src
    assert "sequence_tier.candidates_for" in src
    assert "spec=vid_spec" in src, "provider 에 스펙을 넘기지 않는다"
