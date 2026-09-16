"""보드 렌더 기준 해시 생성기 (tests/test_board_render_golden.py 의 짝).

    python3 tests/make_golden.py

★ 이걸 언제 돌리나: **화면을 의도적으로 바꿨을 때만.** P2 리팩터(토큰 통일·컴포넌트 경계·
  레지스트리 라우팅)는 화면 불변이 합격기준이므로 이 스크립트를 돌리면 안 된다 —
  돌리는 순간 검사가 무의미해진다.

★★ 이걸 **어디서** 돌리나: 리눅스에서만. 기준값은 실행 환경을 탄다 — 윈도우 Pillow 휠에는
  텍스트 셰이퍼 raqm/harfbuzz 가 없어 글자 배치가 리눅스와 미세하게 다르다. 윈도우에서
  기준값을 만들면 **CI 가 그날로 빨개진다.** 그래서 아래에서 플랫폼을 보고 거부한다.
  사람이 쓰는 정식 경로는 워크플로다: Actions → golden-refresh → Run workflow.
  (2026-09-17 실측: docs/실측_골든해시_환경의존_2026-09-17.md)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_board_render_golden import (  # noqa: E402
    BASELINE_PLATFORM, GOLDEN, _render_all)

if __name__ == "__main__":
    if sys.platform != BASELINE_PLATFORM and not os.getenv("GOLDEN_ALLOW_ANY_PLATFORM"):
        raise SystemExit(
            f"거부: 기준값은 {BASELINE_PLATFORM} 에서만 만든다(여기는 {sys.platform}).\n"
            "  여기서 만든 값은 CI 와 어긋나 검사를 통째로 망가뜨린다.\n"
            "  정식 경로: Actions → golden-refresh → Run workflow (무엇을 바꿨는지 적는다).\n"
            "  그래도 강행하려면 GOLDEN_ALLOW_ANY_PLATFORM=1 — 그 결과를 커밋하지 말 것.")
    data = _render_all()
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"기준값 {len(data)} 보드 → {GOLDEN}")
    for board, v in data.items():
        print(f"  {board:22} frames={v['frames']:4} core_fill={v['core_fill']:.4f} "
              f"placements={v['placements']:2} {v['sha256'][:16]}")
