"""엣지 함수(TS)와 엔진(Python)의 **판정 트윈**이 같은 답을 내는지 실행해서 대조한다.

왜 필요한가: 리포트 라인은 같은 판정을 두 벌로 들고 있다 — `engine/report_evidence.py`
(워커, 정본)와 `supabase/functions/generate-report-draft/index.ts`(엣지, 재검사 경로).
`tests/test_prompt_sync.py` 는 **프롬프트 문구**만 대조하므로 판정 로직이 갈라져도 초록이다.
실제로 갈라져 있었다(적대적 리뷰): TS 쪽 `spokenNumberCount` 는 한국어 자릿수 토막을 전부
1로 뭉개 "5억 15억" 을 1개로 셌고, 리터럴 '년' 만 연도로 걸러 `2026F`·`2Q26` 을 놓쳤다.

이 판정은 **면제 취소**(수치를 말하는 씬은 자기검증을 면제하지 않는다)를 좌우한다 —
개수가 갈리면 같은 대본이 경로에 따라 다른 검증을 받는다.

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

from engine import report_evidence as ev

INDEX_TS = Path(__file__).resolve().parents[1] / "supabase/functions/generate-report-draft/index.ts"

# 두 구현이 같은 답을 내야 하는 문장들. 프로덕션 나레이션과 리뷰 재현 케이스를 섞었다.
CORPUS = [
    "2026F 영업이익은 1조 5,791억원",
    "26년 영업이익 3조",
    "2Q26 매출 7.6조원",
    "1H26 실적",
    "3분기 ESS 매출은 전분기보다 약 40% 증가할 것으로 예상됩니다",
    "2026F, 지금이 시작일까요?",
    "매출 7.6조원, 영업이익 1,130억원",
    "매출 3조 순익 500억",
    "5억 15억",
    "3-5% 성장",
    "2025-2026년 전망",
    "주가 34% 하락, LG에너지솔루션에 무슨 일이?",
    "목표주가 55만원을 제시하며",
    "정말 이제 시작일까요?",
    "댓글로 알려주세요",
    "iM증권이 LG에너지솔루션의 2분기 실적을 분석했습니다",
    "영업이익 1조, 순이익 8,000억",
    "3천억원 규모",
    "전년 대비 -15% 감소했다",
]


def _extract_js() -> str:
    """index.ts 에서 판정 함수만 떼어 node 가 읽을 수 있게 타입 표기를 지운다.

    ★ 복사본을 만들지 않는다 — 복사하면 그 복사본이 세 번째 구현이 되어 같은 문제가 는다.
      항상 원본 파일에서 읽는다.
    """
    src = INDEX_TS.read_text(encoding="utf-8")

    marker = re.search(r"^const PERIOD_MARKER_RE\b", src, re.M)
    assert marker, "PERIOD_MARKER_RE 를 못 찾았다 — 엣지 함수 구조가 바뀌었으면 이 테스트를 고쳐라"
    fn = re.search(r"^function spokenNumberCount\(.*?^}", src[marker.start():], re.M | re.S)
    assert fn, "spokenNumberCount 를 못 찾았다"

    block = src[marker.start():marker.start() + fn.end()]
    # TS → JS: 이 블록에 실제로 쓰인 타입 표기만 지운다(범용 트랜스파일이 아니다).
    block = block.replace("function spokenNumberCount(text: string): number", "function spokenNumberCount(text)")
    block = block.replace("const spans: Array<[number, number]> = []", "const spans = []")
    block = block.replace("const SCALES: Record<string, number> =", "const SCALES =")

    # locateChunk 도 같은 방식으로 떼어 온다(별도 블록).
    loc = re.search(r"^function squash\(.*?^}\n\n.*?^function locateChunk\(.*?^}", src, re.M | re.S)
    assert loc, "squash/locateChunk 를 못 찾았다"
    locblk = (loc.group(0)
              .replace("function squash(text: string): string", "function squash(text)")
              .replace("function locateChunk(quote: string, chunks: any[]): string",
                       "function locateChunk(quote, chunks)"))
    return (f"const QUOTE_MIN_CHARS = {QUOTE_MIN_CHARS};\n" + locblk + "\n\n" + block +
            "\n\nconst input = JSON.parse(process.argv[2]);\n"
            "const out = input.mode === 'locate'\n"
            "  ? input.cases.map((c) => locateChunk(c.quote, c.chunks))\n"
            "  : input.texts.map(spokenNumberCount);\n"
            "console.log(JSON.stringify(out));\n")


QUOTE_MIN_CHARS = 8   # engine/config.EVIDENCE_QUOTE_MIN_CHARS


def _run_node(payload: dict) -> list:
    js = _extract_js()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "twin.mjs"
        path.write_text(js, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(path), json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=60,
        )
    assert proc.returncode == 0, f"node 실행 실패:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음 — TS 트윈 대조 건너뜀")
def test_spoken_number_count_matches_engine():
    ts_counts = _run_node({"texts": CORPUS})
    py_counts = [len(ev.spoken_numbers(t)) for t in CORPUS]
    mismatches = [(t, p, s) for t, p, s in zip(CORPUS, py_counts, ts_counts) if p != s]
    assert not mismatches, "엔진과 엣지가 수치 개수를 다르게 센다:\n" + "\n".join(
        f"  {t!r}: python={p} ts={s}" for t, p, s in mismatches)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_exemption_decision_matches_engine():
    """개수 자체보다 중요한 것 — **면제 취소 여부**(0개인가 아닌가)가 갈리면 안 된다."""
    ts_has = [c > 0 for c in _run_node({"texts": CORPUS})]
    py_has = [bool(ev.spoken_numbers(t)) for t in CORPUS]
    assert ts_has == py_has


# chunk_id 해소도 두 경로가 같아야 한다 — 프로덕션에서 19/19 이 빈 문자열이었던 자리다.
LOCATE_CASES = [
    {"quote": "목표주가 26만원을 유지한다", "chunks": [
        {"chunk_id": "C001", "text": "LG전자에 대한 투자의견 BUY, 목표주가 26만원을 유지한다."}]},
    {"quote": "원문에 없는 지어낸 문장입니다", "chunks": [
        {"chunk_id": "C001", "text": "LG전자에 대한 투자의견 BUY, 목표주가 26만원을 유지한다."}]},
    {"quote": "영업이익 1조 5,791억원을 기록했다.", "chunks": [
        {"chunk_id": "C001", "text": "첫 청크 내용입니다."},
        {"chunk_id": "C002", "text": "영업이익 1조 5,791억원을 기록했다."}]},
    {"quote": "목표주가  26만원을\n유지한다", "chunks": [
        {"chunk_id": "C007", "text": "투자의견 BUY, 목표주가 26만원을 유지한다."}]},
    {"quote": "짧음", "chunks": [{"chunk_id": "C001", "text": "짧음이 들어 있는 문장."}]},
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_locate_chunk_matches_engine():
    ts = _run_node({"mode": "locate", "cases": LOCATE_CASES})
    py = [ev.locate_chunk(c["quote"], c["chunks"]) for c in LOCATE_CASES]
    assert ts == py, f"chunk_id 해소가 갈린다: python={py} ts={ts}"
