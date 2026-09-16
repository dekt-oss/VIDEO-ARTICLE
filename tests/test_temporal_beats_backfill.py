"""비트가 모자라면 코드가 stage 선언으로 채운다 (2026-09-12 운영자 지시).

실측: 최근 실사형 지시서 10편·컷 124개 중 invest 는 1개뿐이었고 81개(65%)가
`temporal_contract_unmet` 하나로만 탈락했다. 비트는 영상 프롬프트에 실리는 값이라
(build_motion_prompt → temporal_plan.prose) 비트가 1개면 화면이 실제로 덜 움직인다 —
첫 실물 렌더에서 영상 7컷이 전부 "거의 정지"였다.

게이트 3요소(skill: gate-prompt-feedback-parity)를 함께 못박는다: 검사(evaluate)·
고지(지시서 프롬프트)·되먹임(shortfall_feedback)이 같은 어휘를 말해야 한다.
"""
import pathlib

from engine import config
from engine import temporal_plan as tp

DIRECTIVE_SRC = (pathlib.Path(__file__).resolve().parents[1] / "engine" / "directive.py").read_text(encoding="utf-8")


def _stage(*ops: str) -> dict:
    return {"mutations": [{"operation": o, "entity_id": "BRAIN_MODEL"} for o in ops]}


def test_backfill_satisfies_the_invest_contract_when_a_transform_exists():
    beats = tp.beats_from_stage({}, _stage("APPEAR", "ROTATE"))
    assert len(beats) >= int(config.TIER_PROFILE["invest"]["min_beats"])
    assert tp.evaluate({"temporal_plan": beats}, "invest") == []


def test_last_beat_pushes_in_and_cameras_differ():
    """벤치마크 공식: 횡이동 → 마지막 급속 푸시인. 카메라가 같으면 8초 내내 한 동작이다."""
    beats = tp.beats_from_stage({}, _stage("APPEAR", "ROTATE"))
    assert beats[-1]["camera"] == "DOLLY_IN"
    assert len({b["camera"] for b in beats}) >= 2


def test_the_transforming_mutation_lands_on_the_last_beat():
    beats = tp.beats_from_stage({}, _stage("TRANSFORM", "HIGHLIGHT"))
    assert beats[-1]["mutation"] == "TRANSFORM"


def test_it_does_not_invent_a_transformation():
    """stage 가 '나타남·빛남'뿐이면 비트는 채우되 invest 는 주지 않는다 — 내용을 지어내지 않는다."""
    beats = tp.beats_from_stage({}, _stage("APPEAR", "HIGHLIGHT"))
    assert beats, "카메라 비트는 채워야 화면이 움직인다"
    assert "temporal_no_transforming_mutation" in tp.evaluate({"temporal_plan": beats}, "invest")


def test_no_mutations_means_no_beats():
    assert tp.beats_from_stage({}, {}) == []
    assert tp.beats_from_stage({}, {"mutations": [{"operation": "NOT_A_REAL_OP"}]}) == []


def test_beats_never_exceed_the_clip_or_overlap():
    beats = tp.beats_from_stage({}, _stage("APPEAR", "ROTATE", "MOVE", "GROW"))
    clip = int(config.TIER_PROFILE["invest"]["clip_sec"])
    assert len(beats) <= int(config.TIER_PROFILE["invest"]["max_beats"])
    assert beats[0]["t0"] >= 0 and beats[-1]["t1"] <= clip
    for a, b in zip(beats, beats[1:]):
        assert a["t1"] <= b["t0"]


def test_directive_backfills_before_it_prices_the_order():
    """등급이 오르면 후보가 2발이 되어 영상비가 오른다 — 뒤에 두면 모달이 옛 총액을 보여 준다."""
    i_fill = DIRECTIVE_SRC.index("tplan.beats_from_stage")
    i_cost = DIRECTIVE_SRC.index('header["cost_plan"] = compute_cost_plan')
    assert i_fill < i_cost


def test_stage_without_transformation_is_retryable_with_a_prescription():
    """코드가 못 고치는 것은 되물어야 한다 — 비트는 채워도 '무엇이 변하나'는 지어낼 수 없다."""
    from engine import photo_contract

    assert "photo_stage_no_transformation" in config.RETRYABLE_QUALITY_WARNINGS
    fb = photo_contract.feedback_prompt([], ["photo_stage_no_transformation:S5_CORTEX"])
    assert "MOVE" in fb and "TRANSFORM" in fb, "고칠 어휘를 안 주면 재시도가 같은 답을 낸다"
    assert "라벨만 바꾸지 마라" in fb


def test_directive_emits_that_warning():
    assert 'photo_stage_no_transformation:' in DIRECTIVE_SRC
    assert "MECHANISM_SEQUENCE" in DIRECTIVE_SRC


def test_prompt_and_feedback_name_the_transforming_vocabulary():
    """검사만 있고 고지·되먹임이 없으면 게이트가 아니라 함정이다."""
    assert "APPEAR·HIGHLIGHT 만으로 끝내지 마라" in DIRECTIVE_SRC
    for word in ("TRANSFORM", "ROTATE", "SPLIT_OFF"):
        assert word in DIRECTIVE_SRC, word
    fb = tp.shortfall_feedback([1], [{"cut_no": 1, "temporal_plan": []}])
    assert "APPEAR" in fb and "TRANSFORM" in fb
