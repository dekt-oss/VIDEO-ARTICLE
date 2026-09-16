"""stage 영상 원장은 잡·지시서 번호를 달고 기록된다 (2026-09-11 실측).

성격 유전 전반부 렌더(job a688d355)에서 stage 영상 9행($3.10)이 render_job_id·directive_id 가
**비어** 기록됐다. `_build_stage_video` 는 그 인자를 받는데 `_render_cut_clips` 의 호출이 넘기지
않았다(바로 위 `_obtain_still` 은 넘겼다). 잡 기준으로 원장을 보면 영상비가 0 이었다.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "engine" / "render.py"
IDS = {"directive_id", "render_job_id", "render_job_kind"}


def _calls(name: str) -> list[ast.Call]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name]


def test_stage_video_call_passes_job_and_directive_ids():
    calls = _calls("_build_stage_video")
    assert calls, "호출 자리가 사라졌다 — 이 테스트를 옮겨라"
    for c in calls:
        got = {k.arg for k in c.keywords}
        assert IDS <= got, f"render.py:{c.lineno} 이 {sorted(IDS - got)} 를 안 넘긴다"


def test_the_function_still_accepts_them():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_build_stage_video")
    params = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs]}
    assert IDS <= params
