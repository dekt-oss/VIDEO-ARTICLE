"""조건 없는 select 는 1,000행에서 **조용히** 잘린다 (2026-09-22).

무엇이 있었나
------------
웹 쪽은 이미 막아 뒀는데(`web/lib/supabase/chunked.ts`, CLAUDE.md) **엔진 쪽은
안 막혀 있었다.** 실측:

    papers       6,016행 → 한 번에 select 하면 1,000행
    scores       4,650행 → 한 번에 select 하면 1,000행
    daily_batch  1,140행 → 한 번에 select 하면 1,000행

그래서 `fetch_papers_to_score` 의 "이미 채점된 것" 집합이 1,000개뿐이었고,
**이미 채점한 3,650편이 '미채점'으로 보여 매 실행마다 다시 채점됐다.**
저장된 채점 4,650행 중 353행(7.6%)이 `429 from gemini` 로 0점이 된 것이
그 결과다 — 스스로 만든 레이트리밋이었다.

★ 오류가 안 난다는 것이 이 결함의 전부다. 호출부에는 "그게 전부"로 보인다.
  그래서 **끝까지 읽었는지**를 테스트가 대신 확인한다.
"""

from __future__ import annotations

from unittest import mock

from engine import batch, config, db


class _FakeTable:
    """range(start, end) 를 실제로 존중하는 가짜 테이블."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def lt(self, *_a, **_k):
        return self

    def range(self, start, end):
        self.calls.append((start, end))
        self._slice = self.rows[start:end + 1]
        return self

    def execute(self):
        return mock.Mock(data=list(self._slice))


def _client_with(rows):
    t = _FakeTable(rows)
    c = mock.MagicMock()
    c.table.return_value = t
    return c, t


def test_select_all_reads_past_the_thousand_row_cap():
    rows = [{"id": str(i)} for i in range(2_345)]
    c, t = _client_with(rows)
    with mock.patch.object(db, "client", return_value=c):
        got = db.select_all("papers", "id")
    assert len(got) == 2_345, "1,000 에서 멈추면 이 결함이 돌아온 것이다"
    assert len(t.calls) == 3, "페이지를 끝까지 넘겨야 한다"


def test_a_short_last_page_ends_the_loop():
    """정확히 상한의 배수가 아닐 때 무한 루프가 되면 안 된다."""
    c, _ = _client_with([{"id": str(i)} for i in range(config.DB_PAGE_ROWS)])
    with mock.patch.object(db, "client", return_value=c):
        got = db.select_all("papers", "id")
    assert len(got) == config.DB_PAGE_ROWS


def test_an_empty_table_is_one_call_not_a_loop():
    c, t = _client_with([])
    with mock.patch.object(db, "client", return_value=c):
        assert db.select_all("papers", "id") == []
    assert len(t.calls) == 1


# ── 채점 실패 표식 ────────────────────────────────────────────────
def test_a_failed_scoring_row_is_told_apart_from_a_real_zero():
    """0점 자체로는 '모델이 정말 0을 줬다'와 구별되지 않는다 — 표식이 정본이다."""
    assert db.scoring_failed("[채점 실패: API 오류: 429 from gemini]")
    assert db.scoring_failed("  [채점 실패: JSON 파싱 불가]")
    assert not db.scoring_failed("")
    assert not db.scoring_failed(None)
    assert not db.scoring_failed("표본이 작아 일반화가 어렵다")   # 진짜 빨간깃발


def test_retry_failed_reopens_only_the_failed_rows():
    papers = [{"id": "ok"}, {"id": "bad"}, {"id": "new"}]
    scores = [{"paper_id": "ok", "red_flag": ""},
              {"paper_id": "bad", "red_flag": "[채점 실패: API 오류: 429 from gemini]"}]

    def fake_select_all(table, _cols, **_k):
        return papers if table == "papers" else scores

    with mock.patch.object(db, "select_all", side_effect=fake_select_all):
        plain = [p["id"] for p in db.fetch_papers_to_score()]
        again = [p["id"] for p in db.fetch_papers_to_score(retry_failed=True)]
    assert plain == ["new"], "기본값은 종전대로 — 실패 행을 건드리지 않는다"
    assert again == ["bad", "new"], "명시로 켰을 때만 실패 행이 대상에 돌아온다"


# ── 나이 창 ──────────────────────────────────────────────────────
def test_the_age_window_is_explicit_now_not_an_accident():
    """잘림이 우연히 하던 일(≈최근 1,000편 ≈ 21일)을 코드가 말로 한다."""
    import datetime as dt
    today = dt.date(2026, 9, 22)
    rows = [{"id": "fresh", "published_date": "2026-09-20"},
            {"id": "edge", "published_date": "2026-09-01"},
            {"id": "old", "published_date": "2024-01-01"},
            {"id": "nodate", "published_date": None}]
    got = {p["id"] for p in batch.within_window(rows, today, max_age_days=21)}
    assert "fresh" in got and "edge" in got
    assert "old" not in got
    assert "nodate" in got, "발행일이 없는 것을 '오래됐다'로 읽으면 안 된다"


def test_a_zero_window_means_no_window():
    import datetime as dt
    rows = [{"id": "old", "published_date": "2007-06-25"}]
    assert batch.within_window(rows, dt.date(2026, 9, 22), max_age_days=0) == rows


def test_an_unreadable_date_is_kept_not_dropped():
    import datetime as dt
    rows = [{"id": "weird", "published_date": "미상"}]
    assert batch.within_window(rows, dt.date(2026, 9, 22), max_age_days=21) == rows
