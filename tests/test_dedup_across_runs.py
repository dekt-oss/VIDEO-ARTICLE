"""같은 아티클 재등장 막기(engine/dedup.py) — 2026-11-23 운영 DB 실측 사례로 고정.

같은 글: 신한 엔비디아 텔레그램 재수집(11/19·11/20), 삼성전기 한경·네이버 포털 2건, arXiv ↔ 학술지 정식본.
다른 글(빼면 안 됨): KB 장마감코멘트(면책 문구만 같음), Japan Weekly 주차 다름,
                    'Market Weekly Check ME up!'(제목·머리말 같고 본문 다름).
"""

from __future__ import annotations

from types import SimpleNamespace

from engine import batch, dedup, report_batch, report_collect

NVDA = ("[신한투자증권 반도체/글로벌IT 김형태, 송혜수] 엔비디아(NVDA.US); 불안감 완화 ▶️ FY2028 매출 성장 "
        "가이던스 +75%로 5%p 추가 상향 - Rubin 출하 첫 분기 200억달러 매출 기록. FY2028 성장률 가이던스 "
        "5%p 추가 상향. 데이터센터 매출이 시장 기대를 웃돌았다. https://bbs2.shinhansec.com/x.pdf")
SEMCO = ("2026.11.19 삼성전기 (009150) 마진 피크는 아직 멀었음 Company Brief 밸류에이션 기준 변경, "
         "이익 추정치 상향 목표주가를 210만원에서 150만원으로 하향한다. 밸류에이션 방식을 사업부별 "
         "Peer 평균 P/E를 적용 후 합산하는 방식으로 바꾼다.")
KB_DISCLAIMER = ("KB증권은 동 조사분석자료를 기관투자가 또는 제 3자에게 제공한 사실이 없습니다. "
                 "본 자료를 작성한 조사분석담당자와 그 배우자는 해당 종목과 재산적 이해관계가 없습니다. "
                 "본 자료 작성자는 게재된 내용들이 본인의 의견을 정확하게 반영하고 있으며, "
                 "외부의 부당한 압력이나 간섭 없이 작성되었음을 확인합니다.")
SERIES_HEAD = ("Market Weekly Check ME up! 이번 주 국내외 주요 지표와 일정, 그리고 시장이 주목할 "
               "변수들을 한눈에 정리했습니다. 주간 핵심 체크포인트는 다음과 같습니다. "
               "금리, 환율, 수출입, 물가, 고용, 실적 발표 일정과 수급 흐름을 차례로 짚어 봅니다. ")


def _rec(rid, title, summary):
    return (rid, dedup.report_key(title, summary), title, dedup.report_body(summary))


# ── 판정 ─────────────────────────────────────────────────────────────────────

def test_report_key_ignores_links_and_disclaimers():
    a = dedup.report_key("t", NVDA)
    b = dedup.report_key("t", NVDA.replace("https://bbs2.shinhansec.com/x.pdf", ""))
    assert a and a == b
    assert dedup.report_key("t", KB_DISCLAIMER) is None      # 면책 문구뿐 → 열쇠 없음(판정 안 함)
    assert dedup.report_key("t", "짧은 글") is None


def test_portal_titles_differ_but_same_article():
    assert dedup.same_article("[삼성전기] 마진 피크는 아직 멀었음",
                              "삼성전기(009150) 마진 피크는 아직 멀었음삼성전기(009150) 마진 피크는")


def test_series_with_different_week_is_different_article():
    assert not dedup.same_article("Japan Weekly(10월 2주차)", "Japan Weekly(10월 3주차)")
    assert not dedup.same_article("11/18 KB 리서치 장마감코멘트", "11/19 KB 리서치 장마감코멘트")


def test_same_title_same_intro_but_different_body_is_different_article():
    a = SERIES_HEAD * 2 + "한국 20일간 수출 데이터가 발표됐다. 9월 수출 금액이 1,200억 달러를 넘었다." * 3
    b = SERIES_HEAD * 2 + "10월 소비자물가가 인플레이션 부담을 다시 상기시키는 소재로 작용했다." * 3
    t = "Market Weekly Check ME up!"
    assert dedup.report_key(t, a) == dedup.report_key(t, b)   # 열쇠(머리말)는 같지만
    assert not dedup.same_article(t, t, dedup.report_body(a), dedup.report_body(b))


def test_short_paper_titles_have_no_key():
    assert dedup.paper_key("New Products") is None
    assert dedup.paper_key("Aerosols and hydrocarbons in the atmosphere of a white dwarf")


# ── 수집: 이미 있는 글 거르기 ─────────────────────────────────────────────────

def _report(ext, title, summary):
    return SimpleNamespace(external_id=ext, title=title, summary=summary)


def _drop(items, existing):
    return dedup.drop_known(
        items, ext_of=lambda r: r.external_id,
        key_of=lambda r: dedup.report_key(r.title, r.summary),
        title_of=lambda r: r.title, existing=existing,
        body_of=lambda r: dedup.report_body(r.summary))


def test_telegram_repost_next_day_is_dropped():
    title = "[신한투자증권 반도체/글로벌IT 김형태, 송혜수] 엔비디아(NVDA.US); 불안감 완화"
    kept, dropped = _drop([_report("aria_signal:11869", title, NVDA)],
                          [_rec("aria_signal:11867", title, NVDA)])
    assert kept == [] and dropped == [("aria_signal:11869", "aria_signal:11867")]


def test_recollecting_the_same_id_is_an_update_not_a_duplicate():
    kept, dropped = _drop([_report("aria_signal:11867", "t", NVDA)],
                          [_rec("aria_signal:11867", "t", NVDA)])
    assert len(kept) == 1 and dropped == []


def test_same_report_from_two_portals_in_one_run():
    kept, dropped = _drop([_report("aria_research:14279", "삼성전기(009150) 마진 피크는 아직 멀었음", SEMCO),
                           _report("aria_research:14304", "[삼성전기] 마진 피크는 아직 멀었음", SEMCO)], [])
    assert [r.external_id for r in kept] == ["aria_research:14279"]
    assert dropped == [("aria_research:14304", "aria_research:14279")]


def test_daily_disclaimer_series_is_not_dropped():
    existing = [_rec(f"aria_research:{i}", f"11/{i} KB 리서치 장마감코멘트", KB_DISCLAIMER + f" 오늘 코스피 {i}")
                for i in range(1, 8)]
    kept, dropped = _drop([_report("aria_research:99", "11/20 KB 리서치 장마감코멘트", KB_DISCLAIMER)], existing)
    assert len(kept) == 1 and dropped == []


def test_boilerplate_shared_by_many_is_ignored():
    body = "안녕하세요 데일리에요 오늘의 로봇 방산 조선 업종 소식을 전해드립니다 주요 뉴스는 다음과 같습니다 " * 2
    existing = [_rec(f"aria_signal:{i}", "안녕하세요 데일리에요", body) for i in range(6)]
    kept, _ = _drop([_report("aria_signal:100", "안녕하세요 데일리에요", body)], existing)
    assert len(kept) == 1


# ── 배치: 이미 쌓인 중복·지난 후보와 겹침 ────────────────────────────────────

def test_report_batch_picks_one_per_article_and_skips_prior_twin():
    groups = dedup.group_ids([
        _rec("r1", "[삼성전기] 마진 피크는 아직 멀었음", SEMCO),
        _rec("r2", "삼성전기(009150) 마진 피크는 아직 멀었음", SEMCO),
        _rec("r3", "엔비디아 불안감 완화", NVDA),
        _rec("r4", "엔비디아 불안감 완화", NVDA),
        ("r5", None, "다른 글", ""),
    ])
    scores = [{"report_id": r, "interest_index": 9 - i, "story_index": 9 - i, "safety_index": 9 - i}
              for i, r in enumerate(["r1", "r2", "r4", "r5"])]
    rows = report_batch.build_report_batch_rows("2026-11-23", scores, exclude_ids={"r3"}, group_of=groups)
    assert [r["report_id"] for r in rows] == ["r1", "r5"]


def test_report_batch_without_groups_keeps_old_behavior():
    scores = [{"report_id": r, "interest_index": 1, "story_index": 1, "safety_index": 1} for r in ("a", "b")]
    assert len(report_batch.build_report_batch_rows("d", scores)) == 2


def test_paper_batch_preprint_and_journal_version_counted_once():
    title = "Scalable decision-making for games of imperfect information"
    groups = dedup.group_ids(dedup.paper_records([
        {"id": "p_arxiv", "title": title}, {"id": "p_doi", "title": title},
        {"id": "p_other", "title": "Aerosols and hydrocarbons in the atmosphere of a white dwarf"}]))
    scores = [{"paper_id": p, "fun_index": 5, "importance_index": 5} for p in ("p_arxiv", "p_doi", "p_other")]
    rows = batch.build_batch_rows("2026-11-23", scores, group_of=groups)
    assert sorted(r["paper_id"] for r in rows) == ["p_arxiv", "p_other"]
    rows = batch.build_batch_rows("2026-11-23", scores, exclude_ids={"p_arxiv"}, group_of=groups)
    assert [r["paper_id"] for r in rows] == ["p_other"]


# ── 수집 경로: 조회 실패해도 막지 않는다 ─────────────────────────────────────

def _boom(*_a, **_k):
    raise RuntimeError("db down")


def test_report_collect_fails_open(monkeypatch):
    monkeypatch.setattr(report_collect.report_db, "fetch_reports_for_dedup", _boom)
    reports = [_report("aria_signal:1", "t", NVDA)]
    assert report_collect.drop_already_stored(reports) == reports


def test_recollected_old_pair_does_not_switch_filter_off():
    """이미 쌓인 중복 쌍(A,B)을 다시 수집하면서 새 재게시(C)가 오는 경우 — 행 수가 아니라 글 수로 센다."""
    title = "엔비디아 불안감 완화"
    existing = [_rec("aria_signal:A", title, NVDA), _rec("aria_signal:B", title, NVDA)]
    run = [_report("aria_signal:A", title, NVDA), _report("aria_signal:B", title, NVDA),
           _report("aria_signal:C", title, NVDA)]
    kept, dropped = _drop(run, existing)
    assert [r.external_id for r in kept] == ["aria_signal:A", "aria_signal:B"]   # 재수집 = 갱신
    assert dropped == [("aria_signal:C", "aria_signal:A")]


def test_paper_titles_differing_only_in_greek_letters_are_different():
    a = dedup.paper_key("Observation of the rare decay B0→K*0τ+τ− at the LHCb experiment")
    b = dedup.paper_key("Observation of the rare decay B0→K*0μ+μ− at the LHCb experiment")
    assert a and b and a != b
