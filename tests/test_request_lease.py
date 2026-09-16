"""생성 요청 큐의 임대·회복 (2026-08-29 리뷰 §8 필수 테스트).

리뷰가 요구한 재현: **Edge 또는 워커가 중간 종료됐을 때 요청이 복구되는가.**

실측된 사고(2026-08-28 13:07): Edge 가 202 를 돌려준 뒤 백그라운드에서 생성하다가 47초 만에
런타임이 끊겼다. catch 가 실행되지 않아 상태를 error 로 바꾸지도 못했고, 요청은 processing 인
채로 남아 아무도 다시 집지 않았다. 화면은 "생성 중"에서 영원히 멈춘다.

여기서는 DB 를 가짜로 세워 **임대 만료 → 재큐 → 시도 상한 → error 확정** 경로를 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine import config, db


class FakeTable:
    """Supabase 쿼리 빌더의 최소 흉내. 우리가 쓰는 체이닝만 지원한다."""

    def __init__(self, store: dict, name: str):
        self.store, self.name = store, name
        self._filters: list[tuple] = []
        self._payload: dict | None = None
        self._op = "select"

    # ── 빌더 ──
    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, vals))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    # ── 실행 ──
    def _match(self, row) -> bool:
        for kind, col, val in self._filters:
            cur = row.get(col)
            if kind == "eq" and cur != val:
                return False
            if kind == "in" and cur not in val:
                return False
            if kind == "gt":
                if cur is None or str(cur) <= str(val):
                    return False
        return True

    def execute(self):
        rows = [r for r in self.store[self.name] if self._match(r)]
        if self._op == "update":
            for r in rows:
                r.update(self._payload)
        elif self._op == "insert":
            self.store[self.name].append(dict(self._payload))
        return type("Resp", (), {"data": [dict(r) for r in rows], "count": len(rows)})()


class FakeClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeTable(self.store, name)


@pytest.fixture
def store(monkeypatch):
    data = {"directive_requests": []}
    monkeypatch.setattr(db, "client", lambda: FakeClient(data))
    return data


def _req(**kw):
    base = {"id": "r1", "paper_id": "p1", "version_type": "photo", "status": "processing",
            "attempt_count": 1, "lease_expires_at": None}
    base.update(kw)
    return base


def _iso(delta_sec: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_sec)).isoformat()


# ── 임대 만료 회수 ──
def test_expired_lease_is_requeued(store):
    """워커가 죽으면 임대가 만료되고 다른 워커가 되집는다."""
    store["directive_requests"].append(_req(lease_expires_at=_iso(-60)))
    assert db.requeue_stale_directive_requests() == 1
    row = store["directive_requests"][0]
    assert row["status"] == "queued"
    assert "임대 만료" in row["last_error"]


def test_request_with_no_lease_is_requeued(store):
    """임대 이전에 만들어진 옛 행(2026-08-28 사고의 그 행)도 회수 대상이다."""
    store["directive_requests"].append(_req(lease_expires_at=None))
    assert db.requeue_stale_directive_requests() == 1
    assert store["directive_requests"][0]["status"] == "queued"


def test_live_lease_is_not_stolen(store):
    """살아 있는 워커의 일을 뺏으면 같은 지시서를 두 번 만든다(유료 호출 2배)."""
    store["directive_requests"].append(_req(lease_expires_at=_iso(600)))
    assert db.requeue_stale_directive_requests() == 0
    assert store["directive_requests"][0]["status"] == "processing"


def test_attempts_are_capped_and_confirmed_as_error(store):
    """무한 재큐는 유료 호출을 무한히 태운다 — 상한을 넘으면 error 로 확정한다."""
    store["directive_requests"].append(
        _req(attempt_count=config.REQUEST_MAX_ATTEMPTS, lease_expires_at=_iso(-60)))
    assert db.requeue_stale_directive_requests() == 0
    row = store["directive_requests"][0]
    assert row["status"] == "error"
    assert "시도" in row["last_error"]


def test_queued_rows_are_untouched(store):
    store["directive_requests"].append(_req(status="queued"))
    assert db.requeue_stale_directive_requests() == 0
    assert store["directive_requests"][0]["status"] == "queued"


# ── 임대 획득 ──
def test_claim_takes_a_lease_and_counts_the_attempt(store):
    store["directive_requests"].append(_req(status="queued", attempt_count=0,
                                            lease_expires_at=None))
    rows = db.claim_directive_requests()
    assert len(rows) == 1
    row = store["directive_requests"][0]
    assert row["status"] == "processing"
    assert row["attempt_count"] == 1
    assert row["lease_expires_at"] is not None
    assert row["worker_id"] == config.WORKER_ID


def test_claim_first_recovers_stale_then_takes_it(store):
    """중단된 요청이 다음 폴링에서 실제로 다시 처리 대상이 된다(= 화면이 풀린다)."""
    store["directive_requests"].append(_req(status="processing", lease_expires_at=_iso(-60)))
    rows = db.claim_directive_requests()
    assert [r["id"] for r in rows] == ["r1"]
    assert store["directive_requests"][0]["status"] == "processing"
    assert store["directive_requests"][0]["attempt_count"] == 2


def test_heartbeat_extends_the_lease(store):
    store["directive_requests"].append(_req(lease_expires_at=_iso(1)))
    db.heartbeat_directive_request("r1")
    row = store["directive_requests"][0]
    assert row["lease_expires_at"] > _iso(config.REQUEST_LEASE_SEC - 60)


def test_finishing_a_request_releases_the_lease(store):
    store["directive_requests"].append(_req(lease_expires_at=_iso(600)))
    db.update_directive_request("r1", "done")
    row = store["directive_requests"][0]
    assert row["status"] == "done"
    assert row["lease_expires_at"] is None
