"""저장소 용량 경고 — 순수 판정 테스트.

★ 무엇을 지키는가: 2026-08-24 사고는 "한도를 넘긴 것"이 아니라 **넘기는 동안 아무도
  몰랐던 것**이었다. 그래서 여기서 박는 것은 문구가 아니라 **경계**다 —
  80% 에서 조용하면 이 장치는 없는 것과 같다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine import storage_quota

GB = 1024 ** 3


@dataclass(frozen=True)
class FakeObj:
    size: int


def test_usage_sums_sizes_and_counts_files():
    objs = [FakeObj(100), FakeObj(250), FakeObj(0)]
    assert storage_quota.usage_of(objs) == {"bytes": 350, "files": 3}


def test_usage_of_empty_bucket_is_zero_not_error():
    assert storage_quota.usage_of([]) == {"bytes": 0, "files": 0}


def test_quiet_below_the_warn_ratio():
    # 실측 기준점: 2026-08-29 video-article storage 28MB — 한참 아래다.
    assert storage_quota.warnings_for(28 * 1024 * 1024, GB, 0.8) == []


def test_warns_exactly_at_the_boundary():
    """정확히 80.0% 는 경고한다(`>=`). 경계에서 조용하면 사고 직전에 조용해진다.

    ★ 한도를 1000 으로 잡는다. `int(GB * 0.8)` 로 쓰면 절삭 때문에 79.999...% 가 되어
      **부동소수점을 시험하는 테스트**가 된다(처음에 그렇게 썼다가 실패로 드러났다).
      경계 규칙을 보려면 경계가 정확히 표현되는 수를 써야 한다.
    """
    assert storage_quota.warnings_for(800, 1000, 0.8)


def test_silent_one_byte_below_the_boundary():
    """79.9% 는 조용하다 — `>=` 가 `>` 로 바뀌지 않았는지 반대편에서 잠근다."""
    assert storage_quota.warnings_for(799, 1000, 0.8) == []


def test_warns_just_below_full_but_does_not_claim_overflow():
    msgs = storage_quota.warnings_for(int(GB * 0.9), GB, 0.8)
    assert len(msgs) == 1
    assert "넘었다" not in msgs[0]


def test_over_limit_message_names_the_recovery_command():
    """한도를 넘었으면 '무엇을 하라'까지 말한다 — 경고만 하고 방법을 안 주면 무시된다."""
    msgs = storage_quota.warnings_for(int(GB * 1.53), GB, 0.8)   # 실측: 사고 당일 1.53GB
    assert len(msgs) == 1
    assert "넘었다" in msgs[0]
    assert "storage_gc --apply" in msgs[0]


def test_zero_limit_does_not_divide_by_zero():
    assert storage_quota.warnings_for(123, 0, 0.8) == []


def test_negative_usage_is_clamped():
    assert storage_quota.warnings_for(-1, GB, 0.8) == []


def test_check_reports_not_measured_when_lookup_fails(monkeypatch):
    """조회가 실패해도 예외를 올리지 않는다 — 보험이 본체(수집·채점)를 죽이면 안 된다."""
    from engine import storage_gc

    def boom(*_a, **_k):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(storage_gc, "walk_all", boom)
    monkeypatch.setattr("engine.db.client", lambda *_a, **_k: object())
    out = storage_quota.check()
    assert out["measured"] is False
    assert out["warnings"] == []


def test_check_uses_the_whole_bucket_not_just_job_folders(monkeypatch):
    """`walk_all` 을 쓴다 — 잡이 사라진 고아 폴더도 용량은 먹기 때문이다."""
    from engine import storage_gc

    seen: list[object] = []

    def fake_walk_all(supa, prefix=""):
        seen.append(prefix)
        return [FakeObj(int(GB * 0.85))]

    monkeypatch.setattr(storage_gc, "walk_all", fake_walk_all)
    out = storage_quota.check(supa=object())
    assert seen == [""]                       # 버킷 뿌리부터 훑는다
    assert out["measured"] is True
    assert out["warnings"]                    # 85% → 경고
