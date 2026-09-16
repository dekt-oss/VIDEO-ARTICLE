"""보드 렌더 기준 해시 생성기 (tests/test_board_render_golden.py 의 짝).

    python3 tests/make_golden.py

★ 이걸 언제 돌리나: **화면을 의도적으로 바꿨을 때만.** P2 리팩터(토큰 통일·컴포넌트 경계·
  레지스트리 라우팅)는 화면 불변이 합격기준이므로 이 스크립트를 돌리면 안 된다 —
  돌리는 순간 검사가 무의미해진다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_board_render_golden import GOLDEN, _render_all  # noqa: E402

if __name__ == "__main__":
    data = _render_all()
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"기준값 {len(data)} 보드 → {GOLDEN}")
    for board, v in data.items():
        print(f"  {board:22} frames={v['frames']:4} core_fill={v['core_fill']:.4f} "
              f"placements={v['placements']:2} {v['sha256'][:16]}")
