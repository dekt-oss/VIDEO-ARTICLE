"""자리 배분은 **실측 낙점률**을 따른다 (2026-09-22).

무엇을 고쳤나
------------
하루 20편은 재미·중요·황금 세 정렬에서 **균등하게** 라운드로빈으로 뽑혔다.
그런데 사람 판정 256건에 대고 재 보니 세 정렬의 성적이 다르다
(`scripts/score_axis_audit.py`):

    golden 이 데려온 후보의 낙점률 20.8%(71/342)
    fun        13.3%(53/399)   ·   importance 12.0%(48/399)

가장 잘 맞히는 정렬이 자리의 1/3만 받고 있었다. 황금에 두 자리를 준다.

★ 왜 황금 단독이 아닌가. 황금은 곱이라 한쪽이 낮으면 통째로 깎인다 —
  "재미는 없지만 중요한" 논문은 단독 정렬에서 영영 안 올라온다.
  그리고 깊이별 실측이 그 균형을 지지한다: golden 의 4·5·6번째 자리도
  12~21% 로, fun 의 2~7번째(7~16%)·importance(5~12%)보다 낮지 않다.

★ 이것은 화면 **순서**와 무관하다 — 목록은 이미 황금순으로 보여 준다
  (`web/components/CandidateList.tsx` 기본값 `golden`). 여기서 바뀌는 것은
  **어떤 20편이 목록에 오르는가**다.
"""

from __future__ import annotations

import collections

import pytest

from engine import batch, config


def _pool(n: int) -> list[dict]:
    """세 정렬의 1등이 서로 **다르도록** 만든 후보 풀.

    균등 배분과 가중 배분이 같은 답을 내면 테스트가 아무것도 안 지킨다.
    """
    rows = []
    for i in range(n):
        if i % 3 == 0:        # 재미만 높다
            rows.append({"paper_id": f"f{i}", "fun_index": 10 - i * 0.01, "importance_index": 1.0})
        elif i % 3 == 1:      # 중요만 높다
            rows.append({"paper_id": f"i{i}", "fun_index": 1.0, "importance_index": 10 - i * 0.01})
        else:                 # 둘 다 중간 — 곱이 가장 크다
            rows.append({"paper_id": f"g{i}", "fun_index": 6 - i * 0.01, "importance_index": 6 - i * 0.01})
    return rows


def _mix(rows) -> collections.Counter:
    return collections.Counter(r["sort_mode"] for r in rows)


@pytest.fixture
def pool():
    return _pool(config.DAILY_BATCH_SIZE * 4)


def test_golden_gets_the_most_slots(pool):
    mix = _mix(batch.build_batch_rows("2026-09-22", pool))
    assert mix["golden"] > mix["fun"], mix
    assert mix["golden"] > mix["importance"], mix


def test_the_other_two_still_get_slots(pool):
    """황금만 남기면 '재미는 없지만 중요한' 논문이 영영 안 올라온다."""
    mix = _mix(batch.build_batch_rows("2026-09-22", pool))
    assert mix["fun"] > 0 and mix["importance"] > 0, mix


def test_the_ratio_follows_the_config_not_a_hardcoded_number(pool, monkeypatch):
    monkeypatch.setattr(config, "BATCH_MODE_SLOTS", {"golden": 1, "fun": 3, "importance": 1})
    mix = _mix(batch.build_batch_rows("2026-09-22", pool))
    assert mix["fun"] > mix["golden"], "설정을 뒤집었는데 결과가 그대로면 상수가 헛돈다"


def test_a_zero_slot_turns_a_sort_off(pool, monkeypatch):
    monkeypatch.setattr(config, "BATCH_MODE_SLOTS", {"golden": 1, "fun": 0, "importance": 0})
    mix = _mix(batch.build_batch_rows("2026-09-22", pool))
    assert mix["fun"] == 0 and mix["importance"] == 0


def test_the_list_is_still_exactly_the_batch_size(pool):
    assert len(batch.build_batch_rows("2026-09-22", pool)) == config.DAILY_BATCH_SIZE


def test_a_thin_pool_does_not_loop_forever():
    """후보가 배치 크기보다 적으면 있는 만큼만 — 무한 루프가 아니라."""
    rows = batch.build_batch_rows("2026-09-22", _pool(5))
    assert len(rows) == 5
    assert len({r["paper_id"] for r in rows}) == 5, "같은 논문이 두 자리를 먹으면 안 된다"


def test_ranks_are_still_1_to_n_without_gaps(pool):
    rows = batch.build_batch_rows("2026-09-22", pool)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))


def test_the_exclusion_filter_still_holds(pool):
    """신선도 필터가 자리 배분 변경에 휩쓸리면 같은 논문이 날마다 다시 뜬다."""
    first = {r["paper_id"] for r in batch.build_batch_rows("2026-09-22", pool)}
    second = batch.build_batch_rows("2026-09-23", pool, exclude_ids=first)
    assert {r["paper_id"] for r in second}.isdisjoint(first)
