"""리포트 팩토리 순수 로직 테스트 (채점·지수·배치·정규화·ARIA fixture). 네트워크/LLM 없음."""

from engine import config
from engine.report_batch import build_report_batch_rows
from engine.report_collect import normalize_signal
from engine.report_scoring import (
    interest_index,
    parse_axes,
    safety_index,
    story_index,
    zero_axes,
)
from engine.aria import FixtureAriaClient


def test_parse_axes_clamps_and_defaults():
    axes = parse_axes({"timeliness": 12, "explainability": -3, "story": "7",
                       "safety": None, "one_liner_ko": "안녕", "angle": "앵글"})
    assert axes["timeliness"] == 10       # 상한 클램프
    assert axes["explainability"] == 0    # 하한 클램프
    assert axes["story"] == 7             # 문자열 숫자 허용
    assert axes["safety"] == 0            # None → 0
    assert axes["one_liner_ko"] == "안녕"
    assert axes["angle"] == "앵글"


def test_zero_axes_has_risk_note():
    z = zero_axes()
    assert z["timeliness"] == 0 and z["safety"] == 0
    assert "실패" in z["risk_note"]


def test_indices():
    axes = {"timeliness": 10, "explainability": 10, "story": 10, "safety": 8}
    # 가중치 합이 1 이므로 만점 축은 지수도 만점.
    assert interest_index(axes) == 10.0
    assert story_index(axes) == 10.0
    assert safety_index(axes) == 8.0


def test_interest_index_uses_config_weights():
    w = config.REPORT_INTEREST_WEIGHTS
    axes = {"timeliness": 6, "explainability": 4, "story": 2, "safety": 5}
    expected = round(w["timeliness"] * 6 + w["explainability"] * 4 + w["story"] * 2, 4)
    assert interest_index(axes) == expected


def test_build_report_batch_dedups_and_caps():
    n = config.REPORT_DAILY_BATCH_SIZE + 5
    scores = []
    for i in range(n):
        scores.append({
            "report_id": f"r{i}",
            "interest_index": float(i),
            "story_index": float(n - i),
            "safety_index": float(i % 10),
            "aria_priority": float(i),
        })
    rows = build_report_batch_rows("2026-07-16", scores)
    assert len(rows) == config.REPORT_DAILY_BATCH_SIZE
    rids = [r["report_id"] for r in rows]
    assert len(rids) == len(set(rids))               # 중복 없음
    assert all(r["batch_date"] == "2026-07-16" for r in rows)
    assert {r["sort_mode"] for r in rows} <= set(config.REPORT_SORT_MODES)


def test_build_report_batch_aria_priority_tiebreak():
    # 같은 interest_index 지만 aria_priority 높은 쪽이 먼저 뽑혀야(동점 보정).
    scores = [
        {"report_id": "low", "interest_index": 5.0, "story_index": 0, "safety_index": 0, "aria_priority": 1},
        {"report_id": "high", "interest_index": 5.0, "story_index": 0, "safety_index": 0, "aria_priority": 99},
    ]
    rows = build_report_batch_rows("2026-07-16", scores)
    interest_first = [r for r in rows if r["sort_mode"] == "interest"][0]
    assert interest_first["report_id"] == "high"


def test_build_report_batch_excludes_prior():
    scores = [{"report_id": "a", "interest_index": 1, "story_index": 1, "safety_index": 1}]
    rows = build_report_batch_rows("2026-07-16", scores, exclude_ids={"a"})
    assert rows == []


def test_normalize_signal_from_aria_item():
    item = {
        "id": 2871, "theme_name": "메모리반도체", "signal_level": "HIGH",
        "total_score": 10, "is_risk": False,
        "matched_keywords": {"SK하이닉스": 3},
        "message_text": "**[신한투자증권]** 반도체 호황 현재진행형 https://ex.com/r/1",
    }
    detail = {"channel": "[주식] 증권사 리포트", "source_url": "https://ex.com/report/1",
              "raw_content": "원문 전문(저장 안 함)"}
    rep = normalize_signal(item, detail, macro_context="연준 동결 기대")
    row = rep.to_row()
    assert row["external_id"] == "aria_signal:2871"   # 멱등 중복제거 키
    assert row["source"] == "aria_signal"
    assert row["theme"] == "메모리반도체"
    assert row["signal_level"] == "HIGH"
    assert row["aria_priority"] == 10.0
    assert row["broker"] == "[주식] 증권사 리포트"
    assert row["report_url"] == "https://ex.com/report/1"  # detail 우선
    assert row["macro_context"] == "연준 동결 기대"
    assert "*" not in row["title"]                    # 마크다운 제거
    assert len(row["summary"]) <= config.REPORT_SUMMARY_MAX_CHARS


def test_normalize_signal_summary_is_truncated():
    long_msg = "가" * (config.REPORT_SUMMARY_MAX_CHARS + 500)
    rep = normalize_signal({"id": 1, "message_text": long_msg})
    assert len(rep.summary) == config.REPORT_SUMMARY_MAX_CHARS  # 원문 전문 저장 금지


def test_fixture_aria_client_pass_only_filter():
    client = FixtureAriaClient()
    res = client.list_signals(limit=50, pass_only=True, today=False)
    assert res["items"], "fixture 신호가 비어 있으면 안 됨"
    assert all(s["signal_level"] in ("HIGH", "MID") for s in res["items"])
    # get_signal 상세 캡처가 로드되는지.
    detail = client.get_signal(2871)
    assert detail.get("channel") == "[주식] 증권사 리포트"


def test_fixture_broker_targets_query_filter():
    client = FixtureAriaClient()
    res = client.broker_targets(query="SK하이닉스", days=30)
    assert res["groups"] and res["groups"][0]["stock_name"] == "SK하이닉스"


# ── 수집 볼륨 개선(중복 제거·출처 추정·미채점 배치 폴백) ──

def test_dedup_signals_keeps_strongest_per_document():
    from engine.report_collect import dedup_signals
    doc_a = "마켓 뷰 (7월16일) Summary: 손바닥 뒤집기 - 코스피 급락에 사이드카 발동, 반도체주 전반 약세 지속으로 하루만에 7천선 재이탈. 금리 인상 기조 속 금융주 방어, 조선업 수주 모멘텀은 유지되는 흐름."
    signals = [
        {"id": 1, "theme_name": "시황", "total_score": 10, "message_text": doc_a},
        {"id": 2, "theme_name": "금융", "total_score": 15, "message_text": doc_a},   # 같은 문서, 더 강한 매칭
        {"id": 3, "theme_name": "조선", "total_score": 16, "message_text": doc_a},   # 같은 문서, 최강
        {"id": 4, "theme_name": "로봇", "total_score": 8, "message_text": "현대차 보스턴다이나믹스 로봇개 스팟 라스트마일 배송 실증 사업 추진. 미국 물류기업과 주 5일 하루 200개 실증."},
    ]
    out = dedup_signals(signals)
    assert len(out) == 2                       # 문서 2건으로 접힘
    assert out[0]["id"] == 3                   # 같은 문서 중 total_score 최고만 생존
    assert out[1]["id"] == 4


def test_guess_broker_from_message_header():
    from engine.report_collect import _guess_broker
    assert _guess_broker("**[현대차증권 리서치센터] 미 증시 강세** 종목: 한화에어로스페이스") == "현대차증권"
    assert _guess_broker("[시장] 하나증권 Morning Brief - 투자유망종목 요약") == "하나증권"
    assert _guess_broker("아무 증권사명 없는 일반 메시지") is None


def test_normalize_signal_broker_fallback_without_detail():
    from engine.report_collect import normalize_signal
    item = {"id": 9, "theme_name": "방산", "total_score": 8, "signal_level": "HIGH",
            "message_text": "[기업] **[현대차증권 리서치센터] 미 증시 강세** 한화에어로스페이스 BUY"}
    r = normalize_signal(item, detail={})       # get_signal 상세 실패 경로
    assert r.broker == "현대차증권"


def test_build_report_batch_includes_unscored_by_aria_priority():
    # 미채점(지수 0) 행도 배치에 들어가되, 채점된 행 뒤에서 aria_priority 순으로 정렬.
    scores = [
        {"report_id": "scored-1", "interest_index": 7.0, "story_index": 6.0, "safety_index": 5.0, "aria_priority": 1.0},
        {"report_id": "unscored-hi", "interest_index": 0.0, "story_index": 0.0, "safety_index": 0.0, "aria_priority": 20.0},
        {"report_id": "unscored-lo", "interest_index": 0.0, "story_index": 0.0, "safety_index": 0.0, "aria_priority": 3.0},
    ]
    rows = build_report_batch_rows("2026-07-17", scores)
    ids = [r["report_id"] for r in rows]
    assert ids[0] == "scored-1"                          # 채점된 후보가 최상위
    assert ids.index("unscored-hi") < ids.index("unscored-lo")  # 미채점끼리는 aria_priority 순
    assert len(rows) == 3
