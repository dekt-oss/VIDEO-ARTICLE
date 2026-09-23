"""지시서를 만드는 **모든** 워크플로가 같은 키를 들고 있는가 (2026-09-23 리뷰).

무엇이 있었나
------------
지시서는 한 곳에서만 만들어지지 않는다. 같은 `normalize_directive` 가 다섯 워크플로에서 돈다:

    draft.yml         engine.draft · engine.directive     (대시보드 버튼)
    engine.yml        engine.draft                        (야간 크론이 밀린 초안을 잇는다)
    queues.yml        engine.report_draft · report_directive
    report-draft.yml  engine.report_draft                 (초안 뒤 리포트 지시서를 잇는다)
    report-video.yml  engine.report_directive

PR #50 은 Jev 를 draft.yml·queues.yml **둘에만** 실었다. 나머지 셋에서 만들어진 지시서는
Jev 없이 정규식만으로 판정된다 — **같은 지시서가 어느 버튼·크론을 탔느냐에 따라 다른
판정**을 받는다. 그리고 리뷰에서 같은 모양의 구멍이 하나 더 나왔다: 논문 지시서 기본 모델이
deepseek-v4-pro 인데 engine.yml 에 DEEPSEEK_API_KEY 가 없었다(draft.yml 에만 있었다).

사람이 워크플로를 하나씩 기억해서 맞추는 방식은 이미 두 번 빠졌다. 그래서 기계가 센다.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"

#: 실행하면 `directive.normalize_directive`(= 실사형 게이트 = Jev)를 타는 모듈.
#: 초안 모듈이 들어 있는 이유: 초안 뒤에 **같은 실행에서** 지시서를 잇는다(chain_directives).
DIRECTIVE_MAKERS = ("engine.directive", "engine.draft", "engine.report_directive",
                    "engine.report_draft", "scripts.regen_from_draft")
#: 그중 **논문** 지시서를 만드는 것 — 기본 모델이 deepseek-v4-pro 라 그 키가 있어야 한다.
PAPER_DIRECTIVE_MAKERS = ("engine.directive", "engine.draft", "scripts.regen_from_draft")

_RUN = re.compile(r"python3?\s+-m\s+([\w.]+)")


def _steps():
    """(파일, 스텝 이름, 실행 모듈들, 그 스텝이 보는 env 키) 를 전부 낸다."""
    for f in sorted(WF.glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        wf_env = set((doc.get("env") or {}).keys())
        for job in (doc.get("jobs") or {}).values():
            job_env = wf_env | set((job.get("env") or {}).keys())
            for step in job.get("steps") or []:
                # 셸 주석은 뺀다 — "지시서 생성(python -m engine.report_directive)은 …" 같은
                # 설명 줄이 실행으로 잡히면 설치 스텝에까지 키를 요구하게 된다(실측).
                run = "\n".join(ln for ln in str(step.get("run") or "").splitlines()
                                if not ln.lstrip().startswith("#"))
                mods = set(_RUN.findall(run))
                if mods:
                    env = job_env | set((step.get("env") or {}).keys())
                    yield f.name, step.get("name") or "?", mods, env


def _makers(targets):
    return [(f, n, m, e) for f, n, m, e in _steps() if m & set(targets)]


def test_the_scan_actually_finds_the_directive_steps():
    """아무것도 못 찾고 통과하면 이 파일은 아무것도 지키지 않는다."""
    files = {f for f, *_ in _makers(DIRECTIVE_MAKERS)}
    assert {"draft.yml", "engine.yml", "queues.yml",
            "report-draft.yml", "report-video.yml"} <= files, files


@pytest.mark.parametrize("key", ["JEV_API_KEY", "JEV_ENABLED"])
def test_every_directive_path_carries_the_judge(key):
    missing = [f"{f} · {n}" for f, n, _m, env in _makers(DIRECTIVE_MAKERS) if key not in env]
    assert not missing, (
        f"{key} 가 빠진 지시서 경로: {missing} — 같은 지시서가 경로에 따라 다른 판정을 받는다")


def test_every_paper_directive_path_carries_the_directive_model_key():
    from engine import config
    if not config.MODEL_DIRECTIVE.startswith("deepseek"):
        pytest.skip("논문 지시서 기본 모델이 deepseek 가 아니다")
    missing = [f"{f} · {n}" for f, n, _m, env in _makers(PAPER_DIRECTIVE_MAKERS)
               if "DEEPSEEK_API_KEY" not in env]
    assert not missing, (
        f"DEEPSEEK_API_KEY 가 빠진 논문 지시서 경로: {missing} — "
        "초안은 멀쩡히 돌고 이어지는 지시서 단계만 조용히 죽는다")
