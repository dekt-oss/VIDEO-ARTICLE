"""빈 화면(placeholder 컷)이 섞인 편은 **failed** 다 — 발행할 수 없다 (2026-09-24 실측).

무엇이 있었나
------------
전체 렌더(report_render_jobs 2826f84d): 워커가 Gemini 429 를 맞아 10컷 중 6컷이 placeholder 로
떨어졌다. mp4 는 만들어졌고 **QA 는 "통과"** 였다 — 무음·검은 프레임·길이만 보는 검사라 그림이
가짜인지 몰랐다. 원장(generation_attempts)에는 fallback 이 24행 남았지만 그것을 읽어 발행을
막는 곳이 없었다. 운영자가 "유튜브까지 올려라"고 한 편이 그 상태로 done 이었다.

★ degraded 가 아니라 failed 인 이유: degraded 는 사람이 보고 승인하면 발행이다. 빈 화면은
  승인할 대상이 아니고, 원인(429·402)은 다시 돌리면 풀린다 — 재시도가 답이다.
★ 두 공장이 같은 함수(render.fail_if_placeholders)를 쓴다.
"""

from __future__ import annotations

import inspect

from engine import render, report_render


def setup_function(_fn):
    render.PLACEHOLDER_FALLBACKS.clear()


def test_no_placeholders_leaves_the_verdict_alone():
    qa = {"passed": True, "hard_fail": []}
    assert render.fail_if_placeholders("done", [], qa) == ("done", [])
    assert qa["passed"] is True


def test_one_placeholder_cut_fails_the_job_and_names_the_cut():
    render.PLACEHOLDER_FALLBACKS.extend([1, 1, 2, 2, 10])   # 같은 컷이 두 경로에서 등록된다(실측)
    qa = {"passed": True, "hard_fail": [], "warnings": ["긴 무음"]}
    status, reasons = render.fail_if_placeholders("done", ["x"], qa)
    assert status == "failed"
    assert reasons == ["x", "placeholder_cuts:1,2,10"]
    assert qa["passed"] is False and "placeholder_cuts:1,2,10" in qa["hard_fail"]


def test_even_a_degraded_job_becomes_failed():
    render.PLACEHOLDER_FALLBACKS.append(3)
    assert render.fail_if_placeholders("degraded", ["important"], {})[0] == "failed"


def test_the_registry_is_emptied_so_the_next_job_starts_clean():
    render.PLACEHOLDER_FALLBACKS.append(3)
    render.fail_if_placeholders("done", [], {})
    assert render.PLACEHOLDER_FALLBACKS == []
    assert render.fail_if_placeholders("done", [], {}) == ("done", [])


def test_both_factories_call_it_before_writing_the_verdict():
    for mod in (render, report_render):
        src = inspect.getsource(mod)
        i_fail = src.index("fail_if_placeholders(status, reasons, qa)")
        i_write = src.index("update_render_job(job_id, status=status" if mod is render
                            else "update_report_render_job(job_id, status=status")
        assert i_fail < i_write, mod.__name__


def test_the_fallback_path_registers_the_cut():
    src = inspect.getsource(render._gen_still)
    assert "PLACEHOLDER_FALLBACKS.append(cut_no)" in src
