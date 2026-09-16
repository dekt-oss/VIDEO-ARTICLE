"""다듬기 방어막의 **판정 트윈**이 양쪽에서 같은 답을 내는지 실행해서 대조한다.

왜 필요한가: 논문 초안은 두 경로로 만들어진다 — 로컬 워커(`engine/script_polish.py`)와
엣지 함수(`supabase/functions/generate-draft/index.ts`, 대시보드 [초안 생성] 버튼).
`tests/test_prompt_sync.py` 는 **프롬프트 문구**만 대조하므로 방어 로직이 갈라져도 초록이다.
갈라지면 같은 대본이 **경로에 따라 다르게 다듬어진다** — 한쪽에서만 사실이 흘러간다.
(리포트 라인이 이미 같은 사고를 겪었다: `tests/test_edge_twin_parity.py` 머리말.)

node 가 없는 환경에서는 건너뛴다(엔진 테스트는 파이썬만으로 돌아야 한다).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine import script_polish as sp

INDEX_TS = Path(__file__).resolve().parents[1] / "supabase/functions/generate-draft/index.ts"

# 두 구현이 같은 답을 내야 하는 (원문, 다듬은 문장) 쌍.
CORPUS: list[tuple[str, str]] = [
    ("쥐 20마리에서 평균 30% 늘었습니다.", "쥐 20마리에서 평균 30% 증가했습니다."),
    ("이 연구에 대한 결과를 통해 확인되었습니다", "이 연구 결과로 확인했습니다"),
    ("92일 더 오래 살았습니다", "92일 더 오래 살았습니다"),
    ("30% 늘었습니다", "40% 늘었습니다"),
    ("30% 늘었습니다", "30배 늘었습니다"),
    ("평균 30% 늘었습니다", "30% 늘었습니다"),
    ("염증이 줄었습니다", "염증이 늘었습니다"),
    ("연관이 있었습니다", "때문입니다"),
    ("차이가 없었습니다", "차이가 있었습니다"),
    ("가나다라마바사", ""),
    ("일부 쥐에서 관찰된 이 변화는 매우 흥미로운 결과입니다", "일부 쥐 변화"),
    ("NAD+ 수치가 회복되는 경향을 보입니다", "엔에이디 플러스 수치가 회복되는 경향을 보입니다"),
    # 살아 있는 모델이 실제로 낸 교정들(2026-09-10 실측) — 전부 통과해야 한다.
    ("체중 감소에 대한 효과와 더불어 염증의 감소라고 하는 부분이 함께 관찰되어졌다.",
     "체중 감소 효과와 더불어 염증 감소가 함께 관찰되었습니다."),
    ("해당 약물의 투여에 의해서 유도되어진 대사적인 변화라고 하는 것은 92일이라고 하는"
     " 기간에 걸쳐서 지속되어지는 것으로 나타났습니다.",
     "약물 투여로 유도된 대사 변화는 92일 동안 지속되는 것으로 나타났습니다."),
    ("연구진에 의하면 이러한 결과는 30% 정도의 염증 감소와 연관이 있는 것으로 보여집니다.",
     "연구진에 따르면 이러한 결과는 30% 정도의 염증 감소와 연관이 있는 것으로 보입니다."),
    # 숫자도 뜻도 그대로인데 발견 하나가 통째로 빠진 교정 — 줄기 보존율만이 잡는다.
    ("쥐 20마리에서 수명이 30% 늘었고, 인지 기능과 운동 능력도 함께 개선됐습니다.",
     "쥐 20마리에서 수명이 30% 늘었습니다."),
]


def _js_module() -> str:
    """엣지 파일에서 방어막 블록만 떼어내 node 가 읽을 수 있게 타입 표기를 지운다.

    ★ 원본을 고쳐 두지 않는다 — **배포되는 그 코드**를 그대로 실행해야 대조가 의미 있다.
    """
    src = INDEX_TS.read_text(encoding="utf-8")
    start = src.index("const POLISH_NUMBER =")
    end = src.index("// engine/selfcheck.py:normalize_selfcheck 이식.")
    b = src[start:end]
    b = re.sub(r"new (Map|Set)<[^>]*>", r"new \1", b)
    b = re.sub(r"\)\s*:\s*[^{\n]+\{", ") {", b)
    b = re.sub(r"(\b[\w]+)\s*:\s*\[string, string\]\[\]", r"\1", b)
    b = re.sub(r"(\b[\w]+)\s*:\s*\{[^}]*\}\[\]", r"\1", b)
    b = re.sub(r"(\b[\w]+)\s*:\s*(?:string|number|any|boolean)(?:\[\])?(\s*[,)=])", r"\1\2", b)
    b = re.sub(r"const (\w+)\s*:\s*[^=]+=", r"const \1 =", b)
    # env 상수는 파이썬 기본값과 같은 값으로 고정한다(비교 대상은 로직이지 설정이 아니다).
    from engine import config
    for name in ("SCRIPT_POLISH_SHRINK_TOLERANCE", "SCRIPT_POLISH_MIN_STEM_RETENTION",
                 "SCRIPT_POLISH_LEN_TOLERANCE", "SCRIPT_POLISH_LEN_FLOOR_CHARS"):
        b = b.replace(name, str(getattr(config, name)))
    return "function toInt(v, f) { const n = Number(v); return Number.isFinite(n) ? Math.trunc(n) : f; }\n" + b


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_rejection_reason_matches_between_engine_and_edge():
    runner = (
        _js_module()
        + "\nconst CASES = " + json.dumps(CORPUS, ensure_ascii=False) + ";\n"
        + "console.log(JSON.stringify(CASES.map(([a, b]) => polishRejectionReason(a, b))));\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "twin.mjs"
        path.write_text(runner, encoding="utf-8")
        out = subprocess.run(["node", str(path)], capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    ts_says = json.loads(out.stdout.strip().splitlines()[-1])
    py_says = [sp.rejection_reason(a, b) for a, b in CORPUS]
    mismatch = [(c, p, t) for c, p, t in zip(CORPUS, py_says, ts_says) if p != t]
    assert not mismatch, f"판정이 갈렸다: {mismatch}"
