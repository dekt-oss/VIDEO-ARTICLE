"""화면의 한글 표가 엔진의 코드 어휘를 **다 덮는가** (2026-09-17).

★ 운영자 지시: "지시서에 영어로 되어있는건 한글로도 같이 입력해줘."
  코드 어휘(enum)는 표 하나로 한글이 된다 — 비용 0. 그런데 엔진에 새 enum 이 생기고 표에
  안 넣으면 **그 값만 화면에서 영어로 샌다.** 눈으로는 절대 안 잡힌다.

★ 화면은 모르는 값을 숨기지 않고 원값을 그대로 보여주므로(seqLabels.ts 의 규칙) 깨지지는
  않는다. 여기서 잡는 것은 "한글이 안 붙었다" 이지 "화면이 죽는다" 가 아니다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "web" / "lib" / "work" / "seqLabels.ts"


def _ts_table(name: str) -> set[str]:
    """seqLabels.ts 의 `const NAME: Record<string,string> = { KEY: "…", … }` 에서 키를 읽는다."""
    src = TS.read_text(encoding="utf-8")
    m = re.search(rf"const {name}: Record<string, string> = \{{(.*?)\n\}};", src, re.S)
    assert m, f"{name} 표를 seqLabels.ts 에서 못 찾았다"
    # 한 줄에 여러 키가 올 수 있다 — 줄머리만 보면 놓친다(이 파서로 한 번 헛짚었다).
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\"", m.group(1)))


# (엔진 config 상수, seqLabels.ts 표 이름)
PAIRS = [
    ("CAMERA_OPERATIONS", "CAMERA_OPERATION"),
    ("CAMERA_BASES", "CAMERA_BASE"),
    ("CONTINUITY_MODES", "CONTINUITY_MODE"),
    ("REPRESENTATION_MODES", "REPRESENTATION_MODE"),
    ("SEQUENCE_ROLES", "SEQUENCE_ROLE"),
    ("VISUAL_OPERATIONS", "VISUAL_OPERATION"),
    ("MUTATION_OPERATIONS", "MUTATION_OPERATION"),
]


@pytest.mark.parametrize("const_name,table_name", PAIRS)
def test_every_engine_vocab_value_has_a_korean_label(const_name: str, table_name: str):
    from engine import config

    engine_values = set(getattr(config, const_name))
    missing = sorted(engine_values - _ts_table(table_name))
    assert not missing, (
        f"엔진 {const_name} 에 있는데 seqLabels.ts 의 {table_name} 에 한글이 없다: {missing}. "
        "이 값만 화면에서 영어로 샌다 — 표에 한 줄씩 넣을 것.")


def test_labels_keep_the_original_english():
    """원값을 버리지 않는다 — 렌더·게이트가 쓰는 것은 영어고, 둘을 대조할 수 있어야 한다."""
    src = TS.read_text(encoding="utf-8")
    assert "seqTitle" in src, "원값을 툴팁으로 남기는 seqTitle 이 없다"
    assert "?? v;" in src, "모르는 값을 원값 그대로 돌려주는 폴백이 없다 — 조용히 사라지면 안 된다"
