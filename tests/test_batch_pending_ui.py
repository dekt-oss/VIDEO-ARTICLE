"""밀린 날짜를 화면이 **나열하는가**(운영자 지적 2026-09-04).

지적 원문: "이전 날짜의 후보가 안보여., 3일치 확인안됬다고해서 봣는데 하루치만보임"

실측으로 확인한 것:
  · 데이터는 멀쩡했다 — 리포트 공장 배치 38일 중 35일 확인, 미확인 정확히 3일
    (2026-09-02·03·04). 세 날짜 모두 후보 15건이 정상 조회됐다.
  · ← → 버튼도 살아 있었다(disabled=false).
  · **문제는 화면이 "미확인 3일"이라고만 말하고 나머지 이틀이 어디 있는지 안 알려준 것.**
    숫자만 말하고 갈 곳을 안 주면 그 숫자는 후보가 사라졌다는 불안만 만든다.

그래서 밀린 날짜를 전부 칩으로 나열하고(1/3·2/3·3/3), "한 화면에 하루씩"이라고 못박았다.
이 파일은 그 UI 가 **다시 사라지지 않게** 잠근다(화면이 안 부르면 만든 의미가 없다 —
이 저장소의 단골 실패).
"""

from __future__ import annotations

import pathlib

BAR = pathlib.Path("web/components/BatchDateBar.tsx").read_text(encoding="utf-8")
CSS = pathlib.Path("web/app/globals.css").read_text(encoding="utf-8")


def test_the_bar_lists_every_pending_date_not_just_the_count():
    assert "batch-bar-pending" in BAR
    assert "r.unreviewed.map(" in BAR, "밀린 날짜를 나열하지 않는다"


def test_each_chip_shows_its_position_in_the_queue():
    """★ '3일 밀렸다'만으로는 지금 몇 번째인지 알 수 없다 — 1/3 · 2/3 · 3/3."""
    assert "{i + 1}/{r.unreviewed.length}" in BAR


def test_each_chip_navigates_to_that_date():
    """★ 보여주기만 하고 못 가면 아무것도 해결되지 않는다."""
    seg = BAR.split("batch-bar-pending", 1)[1].split("batch-bar-sub", 1)[0]
    assert "onClick={() => r.go(d)}" in seg


def test_the_current_date_is_marked_and_not_clickable():
    seg = BAR.split("batch-bar-pending", 1)[1].split("batch-bar-sub", 1)[0]
    assert "chip-on" in seg and "disabled={d === batchDate}" in seg


def test_the_screen_says_out_loud_that_it_shows_one_day_at_a_time():
    """★ 이번 혼선의 핵심 — 숫자를 보고 '3일치가 한 화면에 나오겠거니' 하고 기다렸다."""
    assert "한 화면에 하루씩" in BAR


def test_a_single_pending_day_does_not_get_the_chip_row():
    """밀린 날이 하루면 칩이 한 개뿐이라 소음이다."""
    assert "r.unreviewed.length > 1 && (" in BAR


def test_the_chip_styles_exist_so_the_row_is_not_invisible():
    assert ".batch-bar-pending" in CSS and ".batch-bar-pending .chip" in CSS
    assert ".chip-on" in CSS


# ── 날짜를 옮기면 목록이 실제로 바뀌는가 ─────────────────────
#
# ★★ 운영자 지적 2026-09-04: "3일동안 같은 후보인게 맞는거야?"
#   맞지 않았다. DB 는 날짜마다 완전히 다른 리포트를 갖고 있었는데(겹침 0건)
#   화면만 첫 날짜 목록을 계속 보여줬다:
#       09-02 DB 1위 메모리반도체        화면 메모리반도체  ✓
#       09-03 DB 1위 미국-캐나다 관세     화면 메모리반도체  ✗
#       09-04 DB 1위 애플 폴더블폰        화면 메모리반도체  ✗
#   원인: `useState(initial)` 은 **첫 마운트에서만** 초기값을 쓴다. 클라이언트 이동으로
#   같은 자리의 컴포넌트가 재사용되면 새 props 를 무시한다. 날짜 제목·칩·카운트는
#   서버 컴포넌트라 제대로 바뀌어서 목록만 낡은 것을 알아채기가 더 어려웠다.

LISTS = {
    "CandidateList.tsx": pathlib.Path("web/components/CandidateList.tsx").read_text(encoding="utf-8"),
    "ReportCandidateList.tsx": pathlib.Path("web/components/ReportCandidateList.tsx").read_text(encoding="utf-8"),
}
PAGES = {
    "app/page.tsx": pathlib.Path("web/app/page.tsx").read_text(encoding="utf-8"),
    "app/finance/page.tsx": pathlib.Path("web/app/finance/page.tsx").read_text(encoding="utf-8"),
}


def test_both_factories_remount_the_list_when_the_date_changes():
    """★ key={batchDate} 가 없으면 React 가 같은 인스턴스를 재사용해 옛 목록이 남는다."""
    for name, src in PAGES.items():
        assert "key={batchDate} initial={candidates}" in src, f"{name} 에 key 가 없다"


def test_both_lists_also_reseed_themselves_when_props_change():
    """★ key 하나만 두면 다음에 누가 그것을 빼는 순간 조용히 되돌아간다 — 안전망을 겹쳐 둔다."""
    for name, src in LISTS.items():
        assert "seedRef" in src, f"{name} 이 props 변경을 감지하지 않는다"
        assert "setItems(initial)" in src, f"{name} 이 목록을 갈아엎지 않는다"
        # ★ 줄 번호를 가정하지 않는다 — 파일마다 헤더 주석 길이가 다르다.
        assert 'import { useMemo, useRef, useState } from "react";' in src, \
            f"{name} 의 useRef import 누락"


def test_the_reason_is_written_where_the_next_person_will_look():
    """왜 이 코드가 있는지 없으면 다음 사람이 '중복'이라고 지운다."""
    for src in LISTS.values():
        assert "첫 마운트에서만" in src
