"""최근 배치만 재채점하는 스크립트의 대상 선정 로직(운영자 지시 2026-09-04).

★ 왜 전체가 아닌가: mechanism 축이 붙어도 저장된 3,976행의 등급은 그대로 유효하다
  (scoring.stored_scale 이 옛 행을 옛 자로 잰다 — 실측 변동 0건). 전체 재채점은
  LLM 4,000회이고 얻는 것이 없다. 새 축의 효과는 **다시 채점한 논문에서만** 나타나므로
  지금 눈앞에서 고르는 최근 배치만 다시 돌린다.
"""

from __future__ import annotations

from unittest import mock

from scripts import rescore_batch


def _rows(pairs):
    return [{"batch_date": d, "paper_id": p} for d, p in pairs]


def _patched(rows):
    tbl = mock.MagicMock()
    tbl.select.return_value = tbl
    tbl.order.return_value = tbl
    tbl.limit.return_value = tbl
    tbl.execute.return_value = mock.Mock(data=rows)
    client = mock.MagicMock()
    client.table.return_value = tbl
    return mock.patch.object(rescore_batch.db, "client", return_value=client)


def test_one_batch_is_the_default_scope():
    with _patched(_rows([("2026-09-04", "a"), ("2026-09-04", "b"), ("2026-09-03", "c")])):
        assert rescore_batch.recent_batch_paper_ids(1) == ["a", "b"]


def test_more_batches_widen_the_scope_in_recency_order():
    with _patched(_rows([("2026-09-04", "a"), ("2026-09-03", "c"), ("2026-09-02", "d")])):
        assert rescore_batch.recent_batch_paper_ids(3) == ["a", "c", "d"]


def test_a_paper_on_two_days_is_scored_once():
    """★ 배치에 다시 오른 논문을 두 번 채점하면 돈만 두 번 나간다."""
    with _patched(_rows([("2026-09-04", "a"), ("2026-09-03", "a"), ("2026-09-03", "b")])):
        assert rescore_batch.recent_batch_paper_ids(2) == ["a", "b"]


def test_zero_or_negative_still_means_at_least_one_batch():
    with _patched(_rows([("2026-09-04", "a"), ("2026-09-03", "b")])):
        assert rescore_batch.recent_batch_paper_ids(0) == ["a"]


def test_an_empty_batch_table_is_not_a_crash():
    with _patched([]):
        assert rescore_batch.recent_batch_paper_ids(1) == []


def test_dry_run_never_calls_the_scorer():
    """★ --dry-run 이 돈을 쓰면 그건 dry run 이 아니다."""
    with _patched(_rows([("2026-09-04", "a")])), \
         mock.patch.object(rescore_batch.db, "fetch_papers_to_score",
                           return_value=[{"id": "a", "title": "t", "abstract": "x"}]), \
         mock.patch.object(rescore_batch.score_mod, "_score_one") as scorer, \
         mock.patch.object(rescore_batch.db, "upsert_scores") as up:
        assert rescore_batch.run(batches=1, dry_run=True) == 1
        scorer.assert_not_called()
        up.assert_not_called()
