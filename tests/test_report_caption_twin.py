"""리포트 설명란 — 화면(TS)과 업로드 워커(파이썬)가 **같은 글자**를 만드는가 (2026-09-27).

운영자 보고: "주식 리포트에는 왜 제목이랑 본문 내용 안 보이냐". 리포트 작업 화면에 발행용 제목·
설명란 칸이 없었다(DB 칸과 저장 라우트는 있었다). 설명란을 화면에 붙이면서 규칙이 두 벌이
됐다 — 화면에서 복사한 것과 워커가 올리는 것이 다르면 운영자가 본 것이 올라가지 않는다.
두 벌을 **한 정답 파일**(tests/report_caption_golden.json)에 묶는다. TS 쪽은
web/lib/publishCaption.test.ts 가 같은 파일을 읽는다.
"""

from __future__ import annotations

import json
import pathlib

from engine import config
from engine.report_attribution import build_publish_caption, build_source

GOLDEN = json.loads((pathlib.Path(__file__).parent / "report_caption_golden.json")
                    .read_text(encoding="utf-8"))


def test_python_matches_the_golden_captions():
    for f in GOLDEN["fixtures"]:
        assert build_publish_caption(build_source(f["report"]), f["teaser"], f["lang"]) == f["expect"]


def test_the_ts_twin_carries_the_same_disclaimer():
    ts = (pathlib.Path(__file__).parents[1] / "web/lib/publishCaption.ts").read_text(encoding="utf-8")
    assert config.REPORT_DISCLAIMER_TEXT in ts
