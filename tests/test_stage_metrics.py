"""단계별 소요시간 계측 (작업지시서 영상엔진품질 v3 §10).

무엇을 고정하는가: ① 계측이 실제로 붙는다 ② **관측이 파이프라인을 죽이지 않는다**
③ 두 렌더 워커가 같은 방식으로 남긴다. ②가 특히 중요하다 — 이 저장소는 관측을 켜다가
잘 만든 mp4 를 잃을 뻔한 전력이 있다(report_render 의 run_qa 를 try 로 감싼 이유).
"""

from __future__ import annotations

import inspect

import pytest

from engine import stage_metrics as sm


def test_stage_records_elapsed_ms():
    m: dict = {}
    with sm.stage(m, "asset"):
        pass
    assert "asset_ms" in m
    assert isinstance(m["asset_ms"], int) and m["asset_ms"] >= 0


def test_stage_records_even_when_the_block_raises():
    """실패한 잡의 소요시간이 오히려 더 궁금하다 — 어디까지 가다 죽었나."""
    m: dict = {}
    with pytest.raises(ValueError):
        with sm.stage(m, "render"):
            raise ValueError("boom")
    assert "render_ms" in m


def test_stage_is_a_noop_without_a_sink():
    """계측 배선이 안 된 호출자를 막지 않는다 — 관측이 파이프라인을 죽이면 안 된다."""
    with sm.stage(None, "qa"):
        pass  # 예외 없이 지나가면 통과


def test_unknown_stage_name_is_rejected():
    """오타로 새 키가 생기면 집계가 조용히 갈린다. 어휘를 고정한다."""
    with pytest.raises(ValueError):
        with sm.stage({}, "asstes"):   # 오타
            pass


def test_total_ms_sums_only_stage_keys():
    m = {"asset_ms": 10, "qa_ms": 5, "total_ms": 999, "board": [1, 2]}
    assert sm.total_ms(m) == 15, "total_ms 를 다시 더하거나 비-단계 키를 세면 안 된다"
    assert sm.total_ms({}) == 0


def test_summarize_puts_the_slowest_stage_first():
    """눈이 먼저 가야 할 곳이 앞에 있어야 한다."""
    out = sm.summarize({"asset_ms": 5, "assemble_ms": 100, "qa_ms": 20})
    assert out.startswith("assemble=100ms")
    assert sm.summarize({}) == "(계측 없음)"


# ── 배선 ────────────────────────────────────────────────────
@pytest.mark.parametrize("mod_name", ["render", "report_render"])
def test_both_workers_record_stage_metrics(mod_name):
    """한쪽만 계측하면 두 라인의 느려짐을 같은 자로 비교할 수 없다."""
    import importlib

    mod = importlib.import_module(f"engine.{mod_name}")
    src = inspect.getsource(mod.process_job)
    for stage_name in ("asset", "assemble", "qa", "upload"):
        assert f'"{stage_name}"' in src, f"{mod_name}: {stage_name} 단계가 계측되지 않는다"
    assert 'qa["stage_ms"] = metrics' in src, f"{mod_name}: 계측만 하고 저장하지 않는다"


@pytest.mark.parametrize("mod_name", ["render", "report_render"])
def test_stage_metrics_ride_along_in_the_qa_jsonb(mod_name):
    """★ 마이그레이션 없이 qa jsonb 에 얹는다(qa["board"]·qa["cut_map"] 과 같은 관례).
    새 컬럼을 만들면 운영자가 적용해야 할 마이그레이션이 하나 더 쌓인다."""
    import importlib

    mod = importlib.import_module(f"engine.{mod_name}")
    src = inspect.getsource(mod.process_job)
    assert "total_ms" in src
    # 저장 지점은 **대입 한 곳**이어야 한다. 둘이면 어느 쪽이 최종으로 남는지 알 수 없다.
    # ★ 주석에도 같은 문자열이 나오므로 주석 줄을 뺀 대입만 센다(집 관례 — 예전에
    #   src.index("upload_render") 가 주석에 걸려 오탐이 났던 것과 같은 함정이다).
    assigns = [ln for ln in src.splitlines()
               if 'qa["stage_ms"]' in ln and not ln.strip().startswith("#")]
    assert len(assigns) == 1, f"stage_ms 대입이 {len(assigns)}곳이다"


# ── TTS 를 asset 에서 떼어낸다 (Codex 리뷰 #86) ────────────────
def test_tts_is_timed_separately_from_the_rest_of_asset_work():
    """★ 리뷰 지적: `_render_cut_clips` 전체를 asset_ms 한 덩어리로 재면, 느린 렌더의 원인이
    TTS 인지 유료 생성인지 컷 ffmpeg 인지 구분할 수 없다. STAGES 에 tts 를 선언해 놓고
    기록하지 않으면 관측이 실제보다 완전해 보인다."""
    src = inspect.getsource(__import__("engine.render", fromlist=["x"])._gen_cut_assets)
    assert "tts_ms" in src, "TTS 구간이 따로 계측되지 않는다"
    assert "stage_out" in src


def test_tts_accumulates_across_cuts():
    """컷마다 덮어쓰면 마지막 컷 시간만 남는다 — 편당 TTS 총량이어야 한다."""
    src = inspect.getsource(__import__("engine.render", fromlist=["x"])._gen_cut_assets)
    assert 'stage_out.get("tts_ms", 0)' in src, "누적이 아니라 덮어쓰기다"


@pytest.mark.parametrize("mod_name", ["render", "report_render"])
def test_workers_pass_the_metrics_sink_into_cut_rendering(mod_name):
    """sink 를 안 넘기면 위 계측이 조용히 무동작이 된다(stage_out=None)."""
    import importlib

    mod = importlib.import_module(f"engine.{mod_name}")
    assert "stage_out=metrics" in inspect.getsource(mod.process_job)


# ── 중첩 단계 이중 계상 (Codex 리뷰 #87) ──────────────────────
def test_nested_stage_is_not_double_counted():
    """★ 실측 사고: TTS 는 `_gen_cut_assets` 안에서 재는데 그 함수 전체가 이미 asset 블록
    안에 있다. asset_ms 에 TTS 가 포함돼 있는데 total_ms 가 tts_ms 를 또 더해서, 성공한
    모든 렌더의 합계가 부풀려졌다. 이 파일의 total_ms 가 스스로 적어 둔 '겹치는 단계가
    없다'는 가정을 이 파일 자신이 깨고 있었다."""
    m = {"asset_ms": 100, "tts_ms": 40, "qa_ms": 10}
    assert sm.total_ms(m) == 110, "TTS 는 asset 안에 있으므로 더하면 안 된다"


def test_tts_is_declared_nested():
    assert "tts" in sm.NESTED_STAGES
    assert sm.NESTED_STAGES <= set(sm.STAGES), "중첩 선언은 STAGES 어휘 안에 있어야 한다"


def test_nested_stage_is_still_reported():
    """합계에서 뺀다고 감추는 것은 아니다 — TTS 가 얼마였는지는 여전히 알아야 한다."""
    out = sm.summarize({"asset_ms": 100, "tts_ms": 40})
    assert "tts=40ms(내부)" in out, "중첩 표시가 없으면 합계와 항목이 안 맞아 보인다"
    assert "asset=100ms" in out


def test_workers_measure_tts_inside_the_asset_block():
    """★ 이 테스트가 위 제외의 **근거**다. 배선이 바뀌어 TTS 가 asset 밖으로 나가면
    NESTED_STAGES 에서 빼야 하는데, 그때 이 테스트가 먼저 깨져 알려 준다."""
    import importlib

    for mod_name in ("render", "report_render"):
        mod = importlib.import_module(f"engine.{mod_name}")
        src = inspect.getsource(mod.process_job)
        lines = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
        asset_i = next(i for i, ln in enumerate(lines) if 'sm.stage(metrics, "asset")' in ln)
        sink_i = next(i for i, ln in enumerate(lines) if "stage_out=metrics" in ln)
        assert asset_i < sink_i, f"{mod_name}: TTS 계측이 asset 블록 밖이면 제외 규칙이 틀린다"
