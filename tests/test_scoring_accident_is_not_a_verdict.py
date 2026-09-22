"""사고로 실패한 채점을 0점으로 **저장하면 안 된다** (2026-09-22).

무엇이 있었나
------------
`_score_one` 이 모든 예외를 0점 행으로 바꿔 저장했다. 저장되는 순간
`fetch_papers_to_score` 가 "채점 완료"로 보기 때문에 그 논문은 **다시는 채점되지 않는다.**

실측: 저장된 채점 4,650행 중 353행(7.6%)이 그 상태이고 전부 `429 from gemini` 다.
0점은 후보 목록에 영영 못 오르는데 화면에서는 그냥 점수 낮은 논문처럼 보인다 —
사장님이 그중 하나(CEO 보수와 도덕성)를 낙점한 기록이 남아 있다.

무엇을 가르나
------------
    429·5xx·타임아웃 → **사고**. 논문과 무관하다. 저장하지 않고 다음 실행에 넘긴다.
    JSON 파싱 실패    → **판정**. 모델이 그 초록에 대해 계속 같은 실수를 할 수 있다.
                        (`call_json` 이 이미 안에서 재시도한 뒤다.) 0점으로 남긴다.
    401/404 등 설정 오류 → 0점으로 남긴다. 조용히 넘기면 설정이 틀린 채로 계속 돈다.
"""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from engine import score
from engine.llm import JSONParseError

PAPER = {"id": "p1", "external_id": "arXiv:1", "title": "t", "abstract": "a", "venue": "v"}


def _raise(exc):
    def _f(**_k):
        raise exc
    return _f


@pytest.mark.parametrize("exc", [
    httpx.TransportError("429 from gemini"),       # ← 실측 353행의 정체
    httpx.TransportError("503 from gemini"),
    httpx.TimeoutException("read timeout"),
    ConnectionError("연결 끊김"),
])
def test_an_accident_is_not_written_down(exc):
    with mock.patch.object(score, "call_json", _raise(exc)):
        with pytest.raises(score.TransientScoringError):
            score._score_one(PAPER)


def test_a_parse_failure_is_a_verdict_and_stays_zero():
    """모델이 계속 같은 실수를 할 수 있다 — 매번 다시 사면 돈만 나간다."""
    with mock.patch.object(score, "call_json", _raise(JSONParseError("bad"))), \
         mock.patch.object(score.translate, "translate_title", return_value="제목"):
        row = score._score_one(PAPER)
    assert row["surprise"] == 0
    assert row["red_flag"].startswith("[채점 실패")


def test_a_misconfiguration_stays_visible_as_zero():
    """401/404 를 조용히 넘기면 설정이 틀린 채로 계속 돈다."""
    with mock.patch.object(score, "call_json", _raise(RuntimeError("401 unauthorized"))), \
         mock.patch.object(score.translate, "translate_title", return_value="제목"):
        row = score._score_one(PAPER)
    assert row["red_flag"].startswith("[채점 실패")


def test_the_run_skips_accidents_and_stores_the_rest():
    papers = [dict(PAPER, id="a"), dict(PAPER, id="b"), dict(PAPER, id="c")]
    calls = iter([
        {"paper_id": "a"},
        score.TransientScoringError("429"),
        {"paper_id": "c"},
    ])

    def fake_one(_p):
        got = next(calls)
        if isinstance(got, Exception):
            raise got
        return got

    stored = {}
    with mock.patch.object(score.db, "fetch_papers_to_score", return_value=papers), \
         mock.patch.object(score, "_score_one", side_effect=fake_one), \
         mock.patch.object(score.db, "upsert_scores",
                           side_effect=lambda rows: stored.setdefault("rows", rows)), \
         mock.patch.object(score.db, "fetch_scores_for_papers", return_value=[]), \
         mock.patch.object(score.db, "fetch_prior_batch_paper_ids", return_value=set()), \
         mock.patch.object(score.db, "replace_daily_batch", return_value=0):
        n = score.run()
    assert n == 2
    assert [r["paper_id"] for r in stored["rows"]] == ["a", "c"], \
        "사고 난 b 는 행을 만들지 않아야 다음 실행이 다시 집어 간다"
