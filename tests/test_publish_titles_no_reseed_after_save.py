"""저장 직후 화면이 스스로 옛 값으로 되돌리지 않는가 (2026-09-17).

★ 운영자 보고: "제목 바꿔서 저장했는데 내가 바꾼 내용이 저장 안 되고 원래 제목 그대로 되면서
  '제목 저장 (고친 내용 없음)' 이라고 뜹니다."
  **저장은 됐다**(DB 확인). 화면이 저장 직후 스스로 되돌렸다.

★ 원인은 되살리기 effect 의 deps 에 `dirty` 가 들어 있던 것이다. 저장 성공으로 dirty 가
  true→false 가 되는 순간 effect 가 다시 돌고, 그때 props 는 아직 서버를 다시 읽기 전이라
  옛 제목이었다. 그 값으로 덮어썼다.

★ 규칙 자체는 web/lib/work/reseed.ts 가 지고 순수 테스트(reseed.test.ts)가 막는다.
  여기서는 **그 규칙이 실제로 화면에 배선돼 있는지**를 본다 — 규칙만 있고 안 쓰면 소용없다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "web" / "components" / "PublishTitles.tsx"


def _reseed_effect_deps() -> str:
    """되살리기 useEffect 의 의존성 배열 문자열."""
    src = SRC.read_text(encoding="utf-8")
    m = re.search(r"useEffect\(\(\) => \{.*?\}, \[([^\]]*)\]\);", src, re.S)
    assert m, "PublishTitles 에서 되살리기 useEffect 를 못 찾았다"
    return m.group(1)


def test_reseed_effect_does_not_depend_on_dirty():
    """★ deps 에 dirty 가 있으면 저장 성공이 곧바로 되돌리기를 부른다 — 그게 원래 버그다."""
    deps = _reseed_effect_deps()
    assert "dirty" not in deps, (
        f"되살리기 effect 의 deps 에 dirty 가 들어 있다: [{deps}]. "
        "저장 성공으로 dirty 가 false 가 되는 순간 effect 가 다시 돌고, 그때 props 는 아직 "
        "옛 값이라 사용자가 고친 내용을 덮어쓴다(2026-09-17 실측).")


def test_it_uses_the_tested_rule_and_waits_for_the_server():
    """규칙 모듈을 실제로 쓰고, 저장 뒤 서버를 따라오게 만드는가."""
    src = SRC.read_text(encoding="utf-8")
    assert "decideReseed" in src, "되살리기 판단을 lib/work/reseed 에 맡기지 않았다"
    assert "afterSave(" in src, "저장한 값을 앞당겨 기억하지 않는다 — 옛 props 를 다시 믿게 된다"
    assert "router.refresh()" in src, (
        "저장 뒤 서버 props 를 갱신하지 않는다 — awaitingServer 가 영원히 풀리지 않는다")


def test_save_button_is_always_visible():
    """버튼을 dirty 일 때만 보여 주면 '수정하는 게 없다'로 읽힌다(2026-09-17 운영자 보고)."""
    src = SRC.read_text(encoding="utf-8")
    assert "{dirty && (\n        <button" not in src, "저장 버튼이 dirty 일 때만 보인다"
    assert "고친 내용 없음" in src, "안 고쳤을 때도 버튼이 보이고 비활성이라는 표시가 없다"
