"""공개 저장소가 보관 저장소에서 **빠뜨린 것 없이** 옮겨졌는가 (2026-09-17).

★ 왜 필요한가: 공개 저장소 전환은 허용목록(allowlist) 방식이라, 목록에 안 적은 파일은
  경고 없이 그냥 빠진다. 실제로 화풍 점검 도구 2개(`scripts/style_probe.py`·`order_sheet.py`)가
  그렇게 빠져 있었다 — 그 도구가 **만들어 낸 문서 3개는 옮겨졌는데** 도구만 없었다.
  결과 문서만 있고 다시 만들 방법이 없는 상태였다.

★ 여기서 보관 저장소를 읽지 않는다. 그 폴더는 이 저장소를 clone 한 사람에게는 없다.
  대신 "저장소 안에서 서로 가리키는 것이 실재하는가"를 본다 — 그것만으로 이 사고가 잡힌다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 화풍(실사형)은 2026-09-08 에 고정됐고 임의 변경 금지다(CLAUDE.md). 그 화풍을 **돈 안 쓰고**
# 점검하는 유일한 수단이 이 둘이다. 빠지면 화풍을 눈으로 확인할 방법이 사라진다.
STYLE_TOOLS = ("scripts/style_probe.py", "scripts/order_sheet.py")


@pytest.mark.parametrize("rel", STYLE_TOOLS)
def test_style_inspection_tools_are_present(rel: str):
    p = ROOT / rel
    assert p.exists(), (
        f"{rel} 이 없다. 화풍 점검(비용 0으로 실제 발주 프롬프트를 뽑는 것)을 할 수 없다. "
        "공개 저장소 전환이 허용목록 방식이라 조용히 빠질 수 있다 — 보관 저장소에서 가져올 것.")
    assert p.stat().st_size > 1000, f"{rel} 이 비어 있다"


def test_style_tools_still_call_the_real_prompt_builder():
    """이 도구의 값어치는 **렌더가 실제로 부르는 빌더를 그대로 부른다**는 것 하나다.

    따로 프롬프트를 조립하기 시작하면 "여기서 본 문장"과 "Gemini 에 나가는 문장"이 갈리고,
    그때부터 이 도구로 화풍을 판정할 수 없다.
    """
    for rel in STYLE_TOOLS:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "providers" in src and "image" in src, f"{rel} 이 이미지 프로바이더를 안 부른다"
        assert "_build_image_prompt" in src or "build_motion_prompt" in src, (
            f"{rel} 이 실제 프롬프트 빌더를 안 부른다 — 그러면 화풍 판정에 쓸 수 없다")
