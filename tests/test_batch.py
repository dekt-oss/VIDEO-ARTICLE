"""engine.batch.build_batch_rows 순수 로직 테스트.

신선도 필터(exclude_ids)로 이전 배치 등장 논문이 후보에서 빠지는지 검증.
"""

from engine import config
from engine.batch import build_batch_rows


def _score(pid: str, fun: float, imp: float) -> dict:
    return {"paper_id": pid, "fun_index": fun, "importance_index": imp}


def _scores(n: int) -> list[dict]:
    # 점수 내림차순으로 p0(최고)~p{n-1}.
    return [_score(f"p{i}", fun=10 - i, imp=10 - i) for i in range(n)]


def test_no_exclude_picks_top():
    scores = _scores(config.DAILY_BATCH_SIZE + 5)
    rows = build_batch_rows("2026-07-09", scores)
    assert len(rows) == config.DAILY_BATCH_SIZE
    pids = {r["paper_id"] for r in rows}
    assert "p0" in pids  # 최고 점수는 반드시 선정


def test_exclude_drops_prior_papers():
    scores = _scores(config.DAILY_BATCH_SIZE + 5)
    exclude = {"p0", "p1", "p2"}  # 이전 배치에 오른 상위 3편
    rows = build_batch_rows("2026-07-09", scores, exclude_ids=exclude)
    pids = {r["paper_id"] for r in rows}
    assert pids.isdisjoint(exclude)  # 제외 논문은 하나도 안 들어감
    assert len(rows) == config.DAILY_BATCH_SIZE  # 나머지로 채워짐


def test_exclude_none_is_noop():
    scores = _scores(5)
    assert build_batch_rows("d", scores, exclude_ids=None) == build_batch_rows("d", scores)


def test_exclude_shrinks_when_pool_small():
    # 후보가 배치 크기보다 적고 일부를 제외하면 남은 만큼만.
    scores = _scores(4)
    rows = build_batch_rows("d", scores, exclude_ids={"p0"})
    pids = {r["paper_id"] for r in rows}
    assert pids == {"p1", "p2", "p3"}
