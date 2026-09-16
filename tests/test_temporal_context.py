"""시점 오류 게이트 — 논문이 미래로 쓴 일을 제작 시점에도 미래로 읽는 컷 (§21).

★ 무엇을 지키는가: 이 게이트는 **오탐이 크면 존재 가치가 없다.** 이 저장소가 반복해서
  적어 둔 대로 "모든 것을 막는 게이트는 없는 게이트와 같다". 그래서 아래 테스트의 절반은
  "잡는가"가 아니라 **"정상 문장을 안 잡는가"** 다.
"""

from __future__ import annotations

from datetime import date

from engine import temporal_context as tc

TODAY = date(2026, 9, 2)


def cut(no: int, **fields):
    return {"cut_no": no, **fields}


# ── 잡아야 하는 것 ────────────────────────────────────────────

def test_catches_a_past_event_still_spoken_as_future():
    """2024년 논문이 2025년 충돌을 '예정'이라 했고, 지금은 2026년이다."""
    cuts = [cut(3, narration="탐사선은 2025년에 달에 충돌할 예정이다.")]
    assert tc.warnings_for(cuts, 2024, TODAY) == ["cut_stale_future_tense:3"]


def test_catches_english_future_tense_too():
    cuts = [cut(5, visual_prompt="The probe will impact the surface in 2025.")]
    assert tc.warnings_for(cuts, 2024, TODAY) == ["cut_stale_future_tense:5"]


def test_lists_every_offending_cut_in_one_code():
    cuts = [cut(1, narration="2025년에 발사될 예정이다."),
            cut(2, narration="정상적인 과거 서술이다."),
            cut(4, motion_prompt="launch is expected to happen in 2025")]
    assert tc.warnings_for(cuts, 2023, TODAY) == ["cut_stale_future_tense:1,4"]


def test_reads_the_overlay_plan_too():
    """화면 카드에 박히는 글자도 본다 — 나레이션만 보면 카드가 빠져나간다."""
    cuts = [cut(7, overlay_plan={"line": "2025년 충돌 예정"})]
    assert tc.warnings_for(cuts, 2024, TODAY)


# ── 잡으면 안 되는 것 (오탐 방지) ─────────────────────────────

def test_future_tense_without_a_stale_year_is_fine():
    """'앞으로 연구가 필요할 것이다' 는 정상이다. 미래 표현만으로 잡으면 안 된다."""
    cuts = [cut(1, narration="앞으로 더 큰 표본의 연구가 필요할 것이다.")]
    assert tc.warnings_for(cuts, 2024, TODAY) == []


def test_a_past_year_stated_in_past_tense_is_fine():
    """과거를 과거로 말하는 것은 옳다."""
    cuts = [cut(1, narration="2025년에 탐사선이 달에 충돌했다.")]
    assert tc.warnings_for(cuts, 2024, TODAY) == []


def test_this_year_is_not_stale_yet():
    """올해 안에 일어날 일을 미래형으로 말하는 것은 아직 옳다."""
    cuts = [cut(1, narration="2026년에 발사될 예정이다.")]
    assert tc.warnings_for(cuts, 2024, TODAY) == []


def test_a_year_before_the_paper_is_not_our_call():
    """논문보다 앞선 연도는 시점 오류가 아니라 다른 오류다 — 판정할 수 있는 것만 판정한다."""
    cuts = [cut(1, narration="2023년에 발사될 예정이다.")]
    assert tc.warnings_for(cuts, 2024, TODAY) == []


def test_will_does_not_match_inside_another_word():
    """'willing'·'Williams' 에 걸리면 영어 프롬프트 전체가 오탐이 된다."""
    assert tc.has_future_tense("Williams was willing to share the 2025 data") is False


def test_no_published_year_means_no_judgement():
    """발표 연도를 모르면 판정하지 않는다 — 틀린 기준으로 판정하느니 안 하는 게 낫다."""
    cuts = [cut(1, narration="2025년에 충돌할 예정이다.")]
    assert tc.warnings_for(cuts, None, TODAY) == []


def test_empty_input_is_handled_not_crashed():
    assert tc.warnings_for([], 2024, TODAY) == []
    assert tc.warnings_for(None, 2024, TODAY) == []


# ── 발표 연도 추출 ────────────────────────────────────────────

def test_published_year_prefers_the_fact_sheet():
    assert tc.published_year_of({"published_date": "2024-03-11"}, {"year": 2019}) == 2024


def test_published_year_falls_back_to_the_paper_row():
    assert tc.published_year_of({}, {"published_date": "2019-11-02"}) == 2019


def test_published_year_is_none_when_nothing_says_it():
    assert tc.published_year_of({}, {}) is None
    assert tc.published_year_of(None, None) is None


# ── 배선 ──────────────────────────────────────────────────────

def test_the_warning_reaches_the_directive_header():
    """만들어 놓고 한쪽만 연결하지 않는다 — 이 저장소의 상습 실패다."""
    import inspect

    from engine import directive

    src = inspect.getsource(directive)
    assert "temporal_context.warnings_for" in src
    assert "*stale_warnings," in src, "경고가 mode_warnings 에 합류하지 않는다"


def test_it_warns_and_does_not_block():
    """차단 목록이 아니라 경고로 간다 — 오탐률을 보기 전에는 막지 않는다."""
    from engine import photo_contract, visual_sequence_contract

    code = "cut_stale_future_tense"
    assert code not in photo_contract.BLOCK_REASONS
    assert code not in visual_sequence_contract.BLOCK_REASONS


def test_the_year_pattern_survives_a_korean_suffix():
    r""""2025년" 처럼 한글이 바로 붙어도 연도를 읽는다.

    ★ 처음 구현은 `\b(20[0-4]\d)\b` 였고 **한국어 나레이션을 통째로 놓쳤다** —
      한글은 `\w` 라서 5 와 년 사이에 워드 경계가 없다. 테스트가 잡았다.
      이 저장소는 워드 경계로 이미 두 번 사고를 냈다(§9-10).
    """
    assert tc.stale_years("2025년에 충돌한다", 2024, 2026) == [2025]
    assert tc.stale_years("in 2025.", 2024, 2026) == [2025]
    # 더 긴 숫자 안에 든 것은 연도가 아니다.
    assert tc.stale_years("id 20251234", 2024, 2026) == []
