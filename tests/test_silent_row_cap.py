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
    """range(start, end) 를 실제로 존중하는 가짜 테이블.

    `server_cap` 은 Supabase 의 max-rows 설정을 흉내 낸다 — 요청한 범위보다 적게 돌려준다.
    """

    def __init__(self, rows, server_cap=None):
        self.rows = rows
        self.calls = []
        self.orders = []
        self.server_cap = server_cap

    def select(self, *_a, **_k):
        self.orders = []          # 새 쿼리마다 정렬 기록을 비운다
        return self

    def order(self, col, *_a, **_k):
        self.orders.append(col)
        return self

    def lt(self, *_a, **_k):
        return self

    def range(self, start, end):
        self.calls.append((start, end))
        n = end + 1 - start
        if self.server_cap:
            n = min(n, self.server_cap)
        self._slice = self.rows[start:start + n]
        return self

    def execute(self):
        return mock.Mock(data=list(self._slice))


def _client_with(rows, server_cap=None):
    t = _FakeTable(rows, server_cap)
    c = mock.MagicMock()
    c.table.return_value = t
    return c, t


def test_select_all_reads_past_the_thousand_row_cap():
    rows = [{"id": str(i)} for i in range(2_345)]
    c, t = _client_with(rows)
    with mock.patch.object(db, "client", return_value=c):
        got = db.select_all("papers", "id", key=("id",))
    assert len(got) == 2_345, "1,000 에서 멈추면 이 결함이 돌아온 것이다"
    assert len({r["id"] for r in got}) == 2_345, "페이지 경계에서 겹치거나 빠지면 안 된다"


def test_an_exact_multiple_of_the_page_still_ends():
    """정확히 페이지 크기의 배수일 때 무한 루프가 되면 안 된다."""
    c, _ = _client_with([{"id": str(i)} for i in range(config.DB_PAGE_ROWS)])
    with mock.patch.object(db, "client", return_value=c):
        got = db.select_all("papers", "id", key=("id",))
    assert len(got) == config.DB_PAGE_ROWS


def test_an_empty_table_is_one_call_not_a_loop():
    c, t = _client_with([])
    with mock.patch.object(db, "client", return_value=c):
        assert db.select_all("papers", "id", key=("id",)) == []
    assert len(t.calls) == 1


def test_a_server_cap_below_the_page_size_does_not_truncate():
    """★ Supabase 의 max-rows 는 프로젝트 설정이다. 누가 500 으로 낮추는 날,
    "요청보다 적게 왔으면 끝" 규칙은 첫 페이지에서 멈춰 조용한 잘림을 되살린다."""
    rows = [{"id": str(i)} for i in range(1_234)]
    c, _ = _client_with(rows, server_cap=500)
    with mock.patch.object(db, "client", return_value=c):
        got = db.select_all("papers", "id", key=("id",))
    assert len(got) == 1_234


def test_every_page_is_ordered_by_a_unique_key():
    """ORDER BY 가 없거나 겹치는 값으로만 정렬하면 Postgres 는 페이지 사이 순서를 약속하지
    않는다 — 경계에서 행이 빠지거나 두 번 나온다. 유일 키가 **마지막** 정렬 키여야 한다."""
    c, t = _client_with([{"id": "a"}])
    with mock.patch.object(db, "client", return_value=c):
        db.select_all("papers", "id", key=("id",), order="published_date", desc=True)
    assert t.orders == ["published_date", "id"], t.orders


def test_a_call_without_a_key_is_refused():
    """기본 키를 두지 않았다 — 표마다 유일 키가 다르고, 틀린 기본값은 조용히 통과한다."""
    import pytest
    with pytest.raises(TypeError):
        db.select_all("papers", "id")                       # key 누락
    with pytest.raises(ValueError):
        db.select_all("papers", "id", key=())


def test_no_engine_caller_pages_without_a_key():
    """새 호출부가 key 를 빼먹으면 TypeError 로 죽지만, 그건 **실행할 때**다.
    야간 크론에서 처음 죽지 않도록 소스에서 먼저 센다."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for f in list((root / "engine").glob("*.py")) + list((root / "scripts").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"select_all\(", src):
            if src[max(0, m.start() - 4):m.start()] == "def ":
                continue
            # 여는 괄호에 짝이 맞는 닫는 괄호까지가 한 호출이다(인자가 여러 줄에 걸친다).
            depth, end = 1, m.end()
            while depth and end < len(src):
                depth += {"(": 1, ")": -1}.get(src[end], 0)
                end += 1
            call = src[m.end():end]
            if "key=" not in call:
                bad.append(f"{f.name}:{src[:m.start()].count(chr(10)) + 1}")
    assert not bad, f"key 없는 select_all 호출: {bad}"


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
