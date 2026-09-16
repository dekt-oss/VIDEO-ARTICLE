"""엣지 함수가 **구문으로 성립하는지** 병합 전에 본다 (2026-09-11).

왜 필요한가 — 실측 사고: `generate-draft/index.ts` 에 다듬기 경로를 이식하면서 파이썬
히어독이 `\\n` 을 **진짜 줄바꿈으로 바꿔** 문자열 리터럴이 끊겼다.

    "아래 씬들의 한국어를 다듬어라. …그대로 둔다.
    " +

파이썬 테스트도, `tests/test_prompt_sync.py`(문자열 앵커 대조)도, `tests/test_polish_twin_parity.py`
(**파일의 일부만** 떼어내 node 로 실행)도 전부 초록이었다. 이 결함이 처음 드러난 곳은
`supabase functions deploy` 였고, 거기서는 이미 프로덕션에 올리는 중이었다.

즉 **파일 전체를 파서에 통과시켜 본 곳이 한 군데도 없었다.** 여기서 그것을 한다.

★ 타입 검사가 아니라 **구문 검사**다. esbuild 는 타입을 지우고 파싱만 한다 — 그거면 충분하다.
  이번 결함은 타입 문제가 아니라 문자열이 끊긴 것이었고, 그 종류가 셸을 거친 편집에서
  반복해 나온다(저장소 관례: "백슬래시를 셸로 보내지 마라").

npx·node 가 없는 환경에서는 건너뛴다(엔진 테스트는 파이썬만으로 돌아야 한다).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = sorted(p for p in (ROOT / "supabase" / "functions").glob("*/index.ts"))


def test_there_is_something_to_check():
    """엣지 함수가 하나도 안 잡히면 이 테스트가 조용히 통과한다 — 그것부터 막는다."""
    assert FUNCTIONS, "supabase/functions/*/index.ts 를 하나도 찾지 못했다"


# ★ Windows 에서 `npx` 는 `npx.cmd` 라 그냥 넘기면 WinError 2 가 난다. 실제 경로를 찾아 쓴다.
NPX = shutil.which("npx")


@pytest.mark.skipif(NPX is None, reason="npx 없음")
@pytest.mark.parametrize("path", FUNCTIONS, ids=lambda p: p.parent.name)
def test_edge_function_parses(path: Path, tmp_path: Path):
    out = subprocess.run(
        [NPX, "--yes", "esbuild@0.25.0", "--bundle", "--format=esm",
         "--platform=neutral", "--external:https://*", "--external:node:*",
         "--outfile=" + str(tmp_path / "out.js"), str(path)],
        capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=ROOT,
    )
    assert out.returncode == 0, (
        f"{path.parent.name}/index.ts 가 파싱되지 않는다 — 배포하면 400 으로 거절된다:\n"
        + (out.stderr or out.stdout)[-2000:]
    )
