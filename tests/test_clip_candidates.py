"""Candidate Selection — 뽑아서 고른다 (v2 Phase E3).

★ 벤치마크의 핵심 문장: **"8초를 뽑아 좋은 3초만 쓴다."**
  생성형 영상은 확률적이라 1발과 2발-선택은 결과 품질의 **상한**이 다르다.
  코덱스 리뷰 §9 가 "현재 설계에 없는 축"으로 지목한 그것이다.

★ 판정은 코드가 한다 — 모델에게 "어느 쪽이 좋냐"고 물으면 그 답이 또 자기보고다.
  선택 로직은 순수 함수라 라이브 키 없이 돈다.
"""

from __future__ import annotations

from engine import clip_candidates as cc, config


def _sig(freeze, changes, clip=8.0, measured=True, median=0.0037):
    return {"measured": measured, "freeze_sec": freeze, "scene_changes": changes,
            "motion_median": median, "clip_sec": clip}


def test_a_frozen_clip_scores_worse_than_a_moving_one():
    """★ 8초를 샀는데 뒤가 얼어 있으면 **길이만 산 것**이다.

    이 파이프라인이 실제로 만든 실패가 그것이었다 — "5.76초 컷에 4초 클립이라
    1.76초가 정지"(config 주석). 길이를 늘려도 같은 실패가 가능하다.
    """
    frozen = cc.score(_sig(4.0, 1), min_beats=2)
    moving = cc.score(_sig(0.5, 2), min_beats=2)
    assert moving["score"] > frozen["score"]
    assert frozen["freeze_ratio"] == 0.5


def test_the_better_candidate_is_chosen():
    got = cc.pick([cc.score(_sig(4.0, 1, median=0.0011), min_beats=2),
                   cc.score(_sig(0.2, 3, median=0.0037), min_beats=2)])
    assert got["index"] == 1 and got["reason"] == "sustained_motion"


def test_the_first_candidate_wins_ties_deterministically():
    """★ 같은 입력에서 같은 답이 나와야 한다 — 순서가 결정론적 tie-break 다."""
    same = cc.score(_sig(1.0, 2), min_beats=2)
    got = cc.pick([dict(same), dict(same)])
    assert got["index"] == 0 and got["reason"] == "first_is_best"


def test_unmeasurable_candidates_do_not_punish_anyone():
    """★★ 판정 불가 ≠ 실패. ffmpeg 이 없다고 1번 후보가 나쁜 것은 아니다.

    이 저장소가 반복해서 지키는 규율이다 — 못 잰 것을 나쁨으로 읽으면 게이트가
    엉뚱한 것을 벌한다.
    """
    got = cc.pick([cc.score(_sig(0, 0, measured=False)),
                   cc.score(_sig(0, 0, measured=False))])
    assert got["index"] == 0 and got["reason"] == "not_measured"


def test_no_candidates_is_handled_not_crashed():
    assert cc.pick([])["reason"] == "no_candidates"


def test_scene_changes_no_longer_buy_score():
    """★★ 2026-08-31 재교정 — 전환 수는 **점수에서 뺐다.**

    좋은 invest 클립은 컷이 아니라 카메라가 움직이는 **한 테이크**다. 컷에 상을
    주면 우리가 실제로 관측한 **세계 이탈**(달 표면 → 다이어그램)에 상을 주게 된다.
    실측 4클립의 하드컷은 전부 0 이었고, 세어진 "전환"은 소프트 변화였다.
    """
    a = cc.score(_sig(0.0, 0), min_beats=2)
    b = cc.score(_sig(0.0, 9), min_beats=2)
    assert a["score"] == b["score"], "전환 수가 아직 점수를 바꾼다"
    assert a["scene_changes"] == 0 and b["scene_changes"] == 9   # 보고는 한다


def test_the_weights_live_in_config_not_in_the_code():
    """★ 매직넘버 금지 — 가중치·목표값은 실측표에서 온다(config 주석의 4클립)."""
    assert config.CANDIDATE_W_MOTION + config.CANDIDATE_W_FREEZE == 1.0
    # 실측에서 정지는 4/4 가 0.00 이라 안 갈렸다 → 지배 항은 움직임이다.
    assert config.CANDIDATE_W_MOTION > config.CANDIDATE_W_FREEZE
    assert config.CANDIDATE_MOTION_MEDIAN_TARGET > 0


# ── 실측 교정 고정 (2026-08-31, 클립 4개) ─────────────────────
# docs/실측_품질/교정_2026-08-31.md 의 표를 그대로 옮긴 것이다.
# 값은 ffmpeg 로 잰 것이고 파일은 저장소에 있다(재현 가능).
MEASURED = {                       # 정지, 전환, 중앙움직임
    "G2 계약없음": (0.0, 0, 0.00107),
    "G2 연출계약": (0.0, 1, 0.00175),
    "G4 take1":   (0.0, 2, 0.00373),
    "G4 take2":   (0.0, 1, 0.00188),
}


def _measured_score(name):
    fr, ch, med = MEASURED[name]
    return cc.score(_sig(fr, ch, clip=10.01, median=med), min_beats=2)["score"]


def test_the_contract_arm_wins_on_the_measured_numbers():
    """★★ G2 실측 — 연출 계약이 붙은 쪽이 **움직임이 더 많았다**(0.00175 vs 0.00107).

    종전 점수는 이 차이를 못 보고 전환 수로 갈랐다. 지금은 그 차이가 점수를 만든다.
    """
    assert _measured_score("G2 연출계약") > _measured_score("G2 계약없음")


def test_the_visually_better_take_wins_on_the_measured_numbers():
    """★★ G4 실측 — 눈으로 본 판정(take1 이 낫다)과 점수가 **같은 이유로** 일치한다.

    평균 움직임은 둘 다 0.0081 로 같았다. 중앙값이 0.00373 vs 0.00188 로 갈렸다 —
    take2 는 대부분 정지하다 몇 번 튀고 take1 은 내내 움직인다.
    평균만 봤으면 못 갈랐다.
    """
    assert _measured_score("G4 take1") > _measured_score("G4 take2")


def test_the_measured_gaps_clear_the_meaningful_threshold():
    """★ 실측 격차가 "차이 없음" 문턱 위여야 이 지표가 쓸모가 있다."""
    g2 = _measured_score("G2 연출계약") - _measured_score("G2 계약없음")
    g4 = _measured_score("G4 take1") - _measured_score("G4 take2")
    assert g2 >= config.CANDIDATE_MEANINGFUL_GAP, g2
    assert g4 >= config.CANDIDATE_MEANINGFUL_GAP, g4


def test_freeze_alone_could_not_have_told_them_apart():
    """★★ 재교정의 근거. 네 클립의 정지 비율이 **전부 같다**(0.00).

    종전 점수는 그 항에 70% 를 걸고 있었다 — 점수의 대부분이 한 번도 갈리지
    않았다는 뜻이고, 그래서 "옳은 답을 우연히 맞히는" 일이 생겼다.
    """
    assert len({v[0] for v in MEASURED.values()}) == 1
    only_freeze = [cc.score(_sig(v[0], v[1], clip=10.01, median=-1.0))["score"]
                   for v in MEASURED.values()]
    assert len(set(only_freeze)) == 1, "정지만으로는 네 클립이 구분되지 않는다"


# ── 자기 교정 표본 수집 (2026-08-31) ─────────────────────────
def test_every_clip_is_measured_not_only_the_ones_with_candidates():
    """★★ 문턱을 못 정한 진짜 이유는 **표본이 없어서**였다.

    종전에는 후보가 2개일 때만 지표를 쟀다 — 그러면 invest 컷에서만 기록이 생기고
    나머지는 아무 데이터가 없다. 손으로 뽑은 4개가 전부 나쁜 표본이라 세계이탈
    경계를 못 그은 것이 정확히 그 문제였다.

    렌더가 **컷마다** 재서 남기면 좋은 클립·나쁜 클립이 섞여 들어오고,
    문턱이 사람 손이 아니라 **데이터에서** 나온다. 비용은 0이다.
    """
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert "clip_metrics_out.append" in src, "컷 지표를 남기지 않는다"
    assert 'qa["clip_metrics"] = clip_metrics' in src, "남긴 지표가 저장되지 않는다"
    # n>1 조건 안에서만 재던 옛 형태로 되돌아가지 않는다.
    assert "sig = clip_candidates.probe_motion(cand, tier_sec)" in src


def test_the_calibration_tool_refuses_to_guess_from_too_few_samples():
    """★ 적은 표본으로 기준을 그으면 교정이 아니라 추측이다.

    잘못 그은 게이트는 정상 컷을 벌하고, 그러면 운영자가 게이트를 무시하기 시작한다 —
    이 저장소가 반복해서 경계하는 실패다.
    """
    from scripts import calibrate_clip_metrics as cal
    assert cal.MIN_SAMPLES >= 20
    src = __import__("inspect").getsource(cal.main)
    assert "문턱을 정하지 않는다" in src
    assert "자동 적용되지 않는다" in src, "도구가 문턱을 스스로 적용하려 한다"


# ── 배선 (한쪽만 연결 방지) ──────────────────────────────────
def test_the_render_path_generates_and_picks():
    """★★ 후보 로직을 만들고 렌더가 1발만 뽑으면 이 Phase 는 없는 것과 같다."""
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert "clip_candidates.pick" in src, "렌더가 후보를 고르지 않는다"
    assert "int(vid_spec.candidates)" in src, "렌더가 후보 개수를 스펙에서 읽지 않는다"


def test_candidates_are_generated_serially():
    """★ Gemini 동시 호출은 429 를 만든다(운영 제약). 루프여야 한다."""
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert "for k in range(n):" in src, "후보 생성이 직렬 루프가 아니다"


def test_every_candidate_is_billed_in_the_ledger():
    """★★ 2개를 뽑았으면 2개 값을 냈다. 한 행으로 묶으면 **원장이 비용을 절반으로
    거짓말한다** — 이 저장소는 "원장이 진실을 말한다"를 규율로 삼는다.
    """
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert "for _k in range(_n):" in src, "후보마다 원장 행을 남기지 않는다"
    assert "attempt_no=_k + 1" in src, "attempt_no 로 후보를 구분하지 않는다"


# ─────────────────────────────────────────────────────────────
# 텍스트 번인(화면에 박힌 글자) — 2026-09-02 추가
#
# ★ 왜 지표를 더하는가: 2026-08-31 G4 실측에서 take2 를 망친 가장 큰 요인이
#   지어낸 글자 범벅이었는데 **점수에 아예 없었다.** 중앙 움직임이 우연히 같은
#   답을 냈을 뿐이다("지표가 옳은 답을 우연히 맞히는 것을 경계하라").
# ★ 여기서 박는 것은 문턱이 아니라 **계약**이다 — 아직 표본이 없어 문턱을 정하면
#   그것이 곧 실측 없는 매직넘버다. 그래서 "점수를 바꾸지 않는다"를 잠근다.

def test_text_burn_in_is_recorded_in_the_signals():
    """probe_motion 이 실패해도 키가 있어야 한다 — 없으면 소비 측이 조용히 KeyError."""
    sig = cc.probe_motion("/does/not/exist.mp4", 8.0)
    assert "text_burn_in" in sig
    assert sig["text_burn_in"] == -1.0        # 판정 불가는 -1, 0(=글자 없음)이 아니다


def test_text_burn_in_does_not_change_the_score():
    """기록 전용이다. 점수에 넣으면 코드 시각화·수치 보드 컷을 벌하게 된다(리뷰 §17)."""
    clean = {"measured": True, "freeze_sec": 0.0, "scene_changes": 1,
             "motion_median": 0.0037, "clip_sec": 8.0, "text_burn_in": 0.0}
    burned = dict(clean, text_burn_in=200.0)  # 글자가 화면을 덮은 극단값
    assert cc.score(clean) == cc.score(burned)


def test_text_burn_in_reports_raw_values_not_a_normalized_ratio():
    """0~1 로 접지 않는다 — 접으려면 배율이 필요하고 그 배율은 지금 실측 근거가 없다.

    ★ 정규화 상수를 두면 그것이 나중에 문턱처럼 굳는다. 원시 값을 남기고
      `scripts/calibrate_clip_metrics.py` 가 표본으로 정하게 둔다.
    """
    import inspect

    src = inspect.getsource(cc.text_burn_in)
    assert "SCALE" not in src and "/ 255" not in src


def test_the_burn_in_window_lives_in_config_not_in_the_code():
    """시간 평균 창(fps·프레임 수)은 config 에 둔다 — CLAUDE.md 매직넘버 규약."""
    import inspect

    src = inspect.getsource(cc.text_burn_in)
    assert "config.CANDIDATE_TEXT_TMIX_FPS" in src
    assert "config.CANDIDATE_TEXT_TMIX_FRAMES" in src


# ─────────────────────────────────────────────────────────────
# photo_reuse_identical_render — 선언만 있고 나가지 않던 사유 코드 (2026-09-02)
#
# ★ 무엇이 문제였나: 사유 코드(photo_contract.BLOCK_REASONS)와 처방 문구는
#   2026-08-29 부터 있었는데, **그 코드를 내보내는 곳이 어디에도 없었다.**
#   검출은 이미 render.py 에 있었다 — 재사용 결과가 기준 컷과 픽셀 차이가 없으면
#   새로 생성하도록 되돌린다. 없던 것은 **그 사실을 남기는 한 줄**이었다.
#   sweep_unwired 는 이런 것을 못 잡는다(상수가 목록에서 참조되고 있으니까).

def test_the_reuse_reason_code_actually_leaves_the_renderer():
    """검출부가 사유 코드를 기록한다 — '선언만 있고 안 나가는' 상태로 되돌아가지 않는다."""
    import inspect

    from engine import render

    src = inspect.getsource(render._reuse_base_image)
    assert "photo_reuse_identical_render" in src, "검출해 놓고 사유를 안 남긴다"
    assert "reuse_out.append" in src


def test_the_reason_code_is_the_one_declared_in_the_contract():
    """render 가 쓰는 문자열이 photo_contract 의 정본 목록에 실제로 있다.

    ★ 오타가 조용히 통과하는 것을 막는다 — 사유 코드는 web/lib/blockLabels.ts 가
      표시 문자열을 미러하므로, 목록에 없는 코드는 화면에서 이름 없이 뜬다.
    """
    from engine import photo_contract

    assert "photo_reuse_identical_render" in photo_contract.BLOCK_REASONS


def test_the_finding_travels_all_the_way_to_render_qa():
    """배선이 끊기지 않았는지 본다 — 이 저장소의 상습 실패가 '만들어 놓고 한쪽만 연결'이다."""
    import inspect

    from engine import render

    src = inspect.getsource(render)
    assert "reuse_out=reuse_log" in src, "수집 리스트가 렌더 루프에 전달되지 않는다"
    assert 'qa["reuse_identical"] = reuse_log' in src, "모은 것이 qa 에 저장되지 않는다"


def test_recording_does_not_block_the_render():
    """기록일 뿐 차단이 아니다 — 렌더는 이미 새로 생성해 화면을 복구했다."""
    import inspect

    from engine import render

    src = inspect.getsource(render._reuse_base_image)
    # 기록 뒤에도 종전과 같이 False(=새로 생성)를 돌려준다. raise 로 바뀌지 않았다.
    assert "raise" not in src.split("reuse_out.append")[1].split("return False")[0]


# ─────────────────────────────────────────────────────────────
# 동점일 때만 그림을 보고 가른다 (리뷰 §9 멀티모달 판정, 2026-09-02)
#
# ★★ 왜 "동점일 때만"인가: 이 저장소는 코드 판정을 먼저 둔다. 모델에게 매번 물으면
#   그 답이 새로운 자기보고가 되고, 왜 그 후보를 골랐는지 코드가 설명하지 못한다.

def _dec(*vals):
    return {"index": 0, "reason": "first_is_best",
            "scores": [{"score": v} for v in vals]}


def test_a_clear_winner_is_not_second_guessed():
    """코드가 유의미하게 갈랐으면 묻지 않는다 — 유료 호출도, 판정 흔들림도 없다."""
    called = []

    def asker(*a, **k):
        called.append(a)
        return {"better": 2}

    dec = _dec(0.90, 0.10)
    out = cc.review_tie(dec, ["/a.png", "/b.png"], asker=asker)
    assert out == dec
    assert called == [], "차이가 뚜렷한데 모델에게 물었다"


def test_a_tie_is_broken_by_the_picture():
    dec = _dec(0.50, 0.51)                      # 차이 0.01 < CANDIDATE_MEANINGFUL_GAP
    out = cc.review_tie(dec, ["/a.png", "/b.png"],
                        asker=lambda *a, **k: {"better": 2, "reason": "글자 없음"})
    assert out["index"] == 1
    assert out["reason"] == "visual_review"
    assert out["review_reason"] == "글자 없음"


def test_an_unusable_answer_leaves_the_code_decision_alone():
    """판정 불가면 코드 결정을 그대로 둔다 — 못 물었다고 순서를 흔들지 않는다."""
    dec = _dec(0.50, 0.51)
    assert cc.review_tie(dec, ["/a.png", "/b.png"], asker=lambda *a, **k: None) == dec
    assert cc.review_tie(dec, ["/a.png", "/b.png"],
                         asker=lambda *a, **k: {"better": 3}) == dec


def test_missing_frames_mean_no_review():
    """프레임을 못 뽑았으면 물을 재료가 없다."""
    dec = _dec(0.50, 0.51)
    assert cc.review_tie(dec, [], asker=lambda *a, **k: {"better": 2}) == dec


def test_the_question_only_asks_about_burn_in_and_world():
    """'어느 쪽이 좋냐'로 열어 두면 예쁨으로 고르고, 우리가 아는 실패를 놓친다."""
    assert "글자" in cc._REVIEW_USER
    assert "세계" in cc._REVIEW_USER
    assert "better" in cc._REVIEW_USER


def test_no_undefined_names_in_the_veo_candidate_path():
    """★ 스코프 오류(NameError)를 **실제로** 잡는다.

    첫 구현이 `_gen_veo_clip` 안에서 그 함수에 없는 `work_dir`·`idx` 를 썼다. 테스트는
    전부 초록이었다 — 그 줄이 실행되려면 유료 Veo 호출이 필요해서 아무도 안 밟았기
    때문이다. 소스 문자열을 grep 하는 테스트로도 안 잡힌다(문자열은 멀쩡하다).

    그래서 **이름 해석을 정적으로** 본다: 이 함수 안에서 읽는 이름이 인자·지역변수·
    모듈 전역·빌트인 어디에도 없으면 실행 시 NameError 다.

    ★ 검사 대상은 **유료 경로 전부**다. 후보 루프가 `_veo_generate_scored` 로 빠져나가고
      시퀀스 렌더가 `_build_stage_video` 로 생기면서, 한 함수만 보던 이 검사는 정작 새로
      쓴 코드를 놓치게 됐다 — 돈이 드는 줄일수록 실행으로 밟히지 않는다는 것이 이
      테스트의 존재 이유이므로, 새 유료 경로를 목록에 넣는다.
    """
    import ast
    import builtins
    import inspect

    from engine import render

    tree = ast.parse(inspect.getsource(render))
    module = {n.id for n in ast.walk(tree)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    module |= {a.asname or a.name.split(".")[0]
               for imp in ast.walk(tree) if isinstance(imp, (ast.Import, ast.ImportFrom))
               for a in imp.names}
    module |= {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}

    for name in ("_gen_veo_clip", "_veo_generate_scored", "_build_stage_video"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        read = {n.id for n in ast.walk(fn)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        bound = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        bound |= {n.id for n in ast.walk(fn)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        bound |= {h.name for h in ast.walk(fn)
                  if isinstance(h, ast.ExceptHandler) and h.name}
        unknown = sorted(read - bound - module - set(dir(builtins)))
        assert unknown == [], f"{name} 에 없는 이름을 읽는다(실행 시 NameError): {unknown}"


def _unused_docstring_anchor():
    """자리 표시자 — 위 테스트의 docstring 이 이어지도록 분리했다."""


# ─────────────────────────────────────────────────────────────
# text_burn_in — 검증 표본 (2026-09-02)
#
# ★ 이 지표는 자기가 만들어진 바로 그 사례(G4 take2 글자 범벅)에서 **방향이 반대**로
#   나왔다(take1 4.864 > take2 3.703). 대체 체인 17종도 전부 탈락했다 —
#   docs/실측_품질/번인지표_검증_2026-09-02.md. 여기서 박는 것은 두 가지다:
#   ① 검증 표본을 코드로 고정한다(누가 고치든 이 4클립을 통과해야 한다).
#   ② xfail(strict) — 지금은 실패가 정상이고, **통과하기 시작하면 테스트가 깨진다.**
#      그때 TEXT_BURN_IN_VALIDATED 를 True 로 올리고 xfail 을 떼는 것이 절차다.
#      "고쳤는데 아무도 모르는" 상태와 "안 고쳤는데 True 인" 상태를 둘 다 막는다.

import os as _os
import shutil as _shutil

import pytest as _pytest

_KNOWN_CLIPS = {
    "clean": "docs/실측_품질/G4/입력/A_take1.mp4",      # 괄호 몇 개, 글자 없음
    "burned": "docs/실측_품질/G4/입력/B_take2.mp4",     # 글자 덩어리·숫자표·지시선 다수
}


def test_text_burn_in_is_declared_unvalidated_until_the_sample_passes():
    """상수와 xfail 테스트가 서로 잠근다 — 한쪽만 바꾸면 여기서 걸린다."""
    assert cc.TEXT_BURN_IN_VALIDATED is False, (
        "True 로 올렸으면 아래 test_text_burn_in_orders_the_known_clips 의 xfail 을 떼라")


@_pytest.mark.skipif(not _shutil.which("ffmpeg"), reason="ffmpeg 없음")
@_pytest.mark.skipif(not all(_os.path.exists(p) for p in _KNOWN_CLIPS.values()),
                     reason="실측 클립 없음")
@_pytest.mark.xfail(strict=True,
                    reason="실측(2026-09-02): 글자 범벅 클립이 더 낮게 나온다 — 지표 미검증")
def test_text_burn_in_orders_the_known_clips():
    """글자로 뒤덮인 클립이 깨끗한 클립보다 **높아야** 한다. 지금은 반대다."""
    clean = cc.text_burn_in(_KNOWN_CLIPS["clean"])
    burned = cc.text_burn_in(_KNOWN_CLIPS["burned"])
    assert clean >= 0 and burned >= 0
    assert burned > clean, f"burned={burned} clean={clean}"
