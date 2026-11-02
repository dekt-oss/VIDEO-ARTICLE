"""인스타 트렌드 보드(engine/drinks_ig_trends.py) — 순수 함수와 워커 한 바퀴.
네트워크·토큰·DB 없음(httpx.MockTransport + 메모리 rpc). 실제 Graph API 응답 모양은 **미검증**이다(첫 실측 때 확인).
DB 규칙(거부·권한·SQL)은 web/lib/drinks/igTrends.db.test.ts 가 실제 Postgres(PGlite)로 본다.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from engine import config
from engine import drinks_ig_trends as ig
from engine.drinks_collect import DbError
from engine.drinks_fetch import FetchError, SafeFetcher

ROOT = Path(__file__).resolve().parent.parent
SQL = (ROOT / "supabase" / "migrations" / "0063_drinks_ig_trend_board.sql").read_text(encoding="utf-8")
TS = (ROOT / "web" / "lib" / "drinks" / "igTrends.ts").read_text(encoding="utf-8")
TOKEN = "EAAtest-secret-token-value"
TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 9, 22, 30, tzinfo=timezone.utc)   # KST 11-10 07:30


def d(n):
    """오늘에서 n일 전 날짜 문자열."""
    return (TODAY - timedelta(days=n)).isoformat()


# ── 나이 구간 ──

@pytest.mark.parametrize("hours,bucket", [
    (0, "h0_24"), (23.99, "h0_24"), (24, "h24_72"), (71.9, "h24_72"), (72, "d3_7"), (167.9, "d3_7"), (168, "d7_plus"), (5000, "d7_plus"), (None, None),
])
def test_age_bucket_boundaries(hours, bucket):
    assert ig.age_bucket(hours) == bucket


def test_age_hours_reads_graph_timestamp_and_clamps_future_and_rejects_garbage():
    assert ig.age_hours("2026-11-09T10:30:00+0000", NOW) == 12
    assert ig.age_hours("2026-11-09T10:30:00Z", NOW) == 12
    assert ig.age_hours("2026-11-20T10:30:00+0000", NOW) == 0, "시계 차이로 미래면 0"
    assert ig.age_hours("어제", NOW) is None and ig.age_hours(None, NOW) is None


# ── 기준선·뜨는 릴스 ──

def rows(user, bucket, values):
    return [{"username": user, "media_id": f"{user}-{bucket}-{i}", "age_bucket": bucket, "view_count": v} for i, v in enumerate(values)]


def test_baseline_is_per_account_per_bucket_and_needs_eight_reels():
    bl = ig.build_baselines(rows("a", "d3_7", [10, 20, 30, 40, 50, 60, 70, 80]) + rows("a", "h0_24", [1000] * 7) + rows("b", "d3_7", [5] * 8))
    assert bl[("a", "d3_7")].median == 45 and bl[("a", "d3_7")].sample == 8
    assert bl[("b", "d3_7")].median == 5, "계정끼리 섞이지 않는다"
    assert bl[("a", "h0_24")].insufficient and bl[("a", "h0_24")].sample == 7, "8개 미만은 판정하지 않는다"


def test_baseline_skips_missing_views_when_counting_the_sample():
    bl = ig.build_baselines(rows("a", "d3_7", [10] * 7 + [None, None]))
    assert bl[("a", "d3_7")].insufficient and bl[("a", "d3_7")].sample == 7


def test_rising_at_three_times_baseline_exactly_and_not_below():
    bl = ig.Baseline(8, 100.0)
    assert ig.judge_reel(300, "d3_7", bl) == {"trend_flag": "rising", "baseline_views": 100.0, "view_multiple": 3.0}
    assert ig.judge_reel(299, "d3_7", bl)["trend_flag"] == "normal"


def test_judgement_excludes_missing_views_without_turning_them_into_zero():
    got = ig.judge_reel(None, "d3_7", ig.Baseline(8, 100.0))
    assert got == {"trend_flag": "no_views", "baseline_views": None, "view_multiple": None}
    assert ig.judge_reel(5000, None, ig.Baseline(8, 100.0))["trend_flag"] == "no_age"
    assert ig.judge_reel(5000, "d3_7", ig.Baseline(7, None))["trend_flag"] == "insufficient_sample"
    assert ig.judge_reel(5000, "d3_7", None)["trend_flag"] == "insufficient_sample"


def test_zero_baseline_never_makes_everything_rising():
    assert ig.judge_reel(5, "d3_7", ig.Baseline(8, 0.0))["trend_flag"] == "normal"


def test_same_reel_same_bucket_counts_once_and_today_wins():
    history = [{"username": "a", "media_id": "m1", "age_bucket": "d3_7", "view_count": 10}]
    today = [{"username": "a", "media_id": "m1", "age_bucket": "d3_7", "view_count": 99}]
    merged = ig.merge_observations(history, today)
    assert merged == today
    # 나이 구간이 바뀌면 다른 구간의 표본이다
    assert len(ig.merge_observations(history, [{"username": "a", "media_id": "m1", "age_bucket": "d7_plus", "view_count": 99}])) == 2


def test_backfill_flag_only_on_first_observation_day():
    assert ig.backfill_flag(None, TODAY) is True
    assert ig.backfill_flag(TODAY.isoformat(), TODAY) is True, "같은 날 다시 돌아도 첫 관측일이다"
    assert ig.backfill_flag(d(1), TODAY) is False


# ── 음원 ──

def test_position_wording_is_our_account_today_not_a_global_rank():
    assert ig.position_label(7) == "목록 7번째(우리 계정 기준, 오늘)"


def test_rising_audio_new_in_list_or_three_days_never_rank_movement():
    ok = [d(3), d(2), d(1)]
    assert ig.rising_audio_reason(TODAY, None, ok, []) == "new"
    assert ig.rising_audio_reason(TODAY, TODAY.isoformat(), ok, []) == "new", "같은 날 다시 돌아도 처음 들어온 것이다"
    assert ig.rising_audio_reason(TODAY, d(3), ok, [d(2), d(1)]) == "three_days"
    assert ig.rising_audio_reason(TODAY, d(3), ok, [d(1)]) is None, "어제만 있으면 3일 연속이 아니다"
    assert ig.rising_audio_reason(TODAY, d(3), ok, [d(3), d(1)]) is None
    # 자리 바뀜을 받는 인자 자체가 없다
    import inspect
    assert not any("position" in p or "rank" in p for p in inspect.signature(ig.rising_audio_reason).parameters)


def test_first_ever_observation_does_not_call_the_whole_list_new():
    assert ig.rising_audio_reason(TODAY, None, [], []) is None


def test_failed_t1_day_neither_breaks_nor_fills_the_three_day_streak():
    # d(2) 는 T1 실패라 ok 목록에 없다 → d(3), d(1) 이 연속 두 날이다
    assert ig.rising_audio_reason(TODAY, d(3), [d(3), d(1)], [d(3), d(1)]) == "three_days"


def test_audio_first_seen_on_a_partial_day_is_still_new_on_the_next_ok_day():
    assert ig.rising_audio_reason(TODAY, d(1), [d(3), d(2)], [d(1)]) == "new"


def test_generic_titles_are_not_meme_names():
    for t in ("Original audio", "original sound - 9gag", "오리지널 오디오", "오리지널 사운드", "원본 오디오", "", None):
        assert ig.is_generic_audio_title(t), t
    assert not ig.is_generic_audio_title("곶감 챌린지")
    assert ig.is_challenge_title("곶감 챌린지") and ig.is_challenge_title("Tiger Challenge") and not ig.is_challenge_title("Original audio challenge")


# ── 상태 5종·정상 관측일 ──

@pytest.mark.parametrize("a,s,i,st", [(8, 8, 200, "ok"), (8, 8, 0, "ok_empty"), (8, 3, 50, "partial"), (8, 0, 0, "failed"), (0, 0, 0, "ok_empty")])
def test_run_status(a, s, i, st):
    assert ig.run_status(a, s, i) == st


@pytest.mark.parametrize("t1,att,suc,want", [
    ("ok", 10, 8, True), ("ok", 10, 7, False), ("ok", 5, 4, True), ("partial", 10, 10, False), ("ok_empty", 10, 10, False),
    ("failed", 10, 10, False), (None, 10, 10, False), ("ok", 0, 0, False),
])
def test_normal_observation_day(t1, att, suc, want):
    assert ig.is_normal_day(t1, att, suc) is want


def day_runs(day, t1="ok", att=10, suc=10):
    return [{"source": "t1", "observed_on": day, "status": t1, "attempted": 8, "succeeded": 8},
            {"source": "t2", "observed_on": day, "status": "ok", "attempted": att, "succeeded": suc}]


def test_freeze_needs_three_missing_days_counting_gaps_and_failures():
    assert not ig.freeze_state(day_runs(d(0)), TODAY).frozen
    two = day_runs(d(2)) + day_runs(d(1), t1="failed") + day_runs(d(0), t1="failed")
    s = ig.freeze_state(two, TODAY)
    assert (s.frozen, s.missing_streak, s.last_normal_day) == (False, 2, d(2))
    three = day_runs(d(3)) + day_runs(d(2), t1="failed") + day_runs(d(1), t1="failed") + day_runs(d(0), att=10, suc=5)
    assert ig.freeze_state(three, TODAY).frozen and ig.freeze_state(three, TODAY).missing_streak == 3
    gap = day_runs(d(4)) + day_runs(d(0), t1="failed")   # 사이 날짜에 기록이 없어도 끊긴 날이다
    assert ig.freeze_state(gap, TODAY).frozen and ig.freeze_state(gap, TODAY).missing_streak == 4


def test_freeze_lifts_on_a_normal_day_and_never_fires_before_the_first_run():
    back = day_runs(d(5)) + day_runs(d(1), t1="failed") + day_runs(d(0))
    assert not ig.freeze_state(back, TODAY).frozen
    assert ig.freeze_state([], TODAY) == ig.FreezeState(False, 0, None), "기록이 없으면 끊긴 것이 아니라 시작 전이다"


def test_freeze_does_not_count_today_before_todays_run():
    rows_ = day_runs(d(3)) + day_runs(d(2), t1="failed") + day_runs(d(1), t1="failed")   # 오늘 기록 없음
    s = ig.freeze_state(rows_, TODAY)
    assert (s.frozen, s.missing_streak) == (False, 2)


def test_missing_dates_fill_only_the_skipped_days_and_are_capped():
    assert ig.missing_dates(None, TODAY) == []
    assert ig.missing_dates(d(1), TODAY) == []
    assert ig.missing_dates(d(0), TODAY) == []
    assert [x.isoformat() for x in ig.missing_dates(d(3), TODAY)] == [d(2), d(1)]
    assert len(ig.missing_dates(d(500), TODAY)) == config.DRINKS_IG_NOT_RUN_FILL_MAX_DAYS


# ── 형식 칸 ──

def test_video_only_fields_are_nulled_without_video_or_operator_evidence():
    got = ig.sanitize_fields([
        {"field": "beat_count", "value": "4", "evidence": "cover", "confidence": "high"},
        {"field": "cut_lengths", "value": "1,2", "evidence": "caption", "confidence": "low"},
        {"field": "twist_at", "value": "3.2", "evidence": "api_metrics", "confidence": "high"},
        {"field": "first_1_5s", "value": "x", "evidence": None},
        {"field": "music_sync", "value": "yes", "evidence": "cover"},
        {"field": "beat_count", "value": "5", "evidence": "video", "confidence": "high"},
        {"field": "cut_lengths", "value": "1,1", "evidence": "operator", "confidence": "high"},
        {"field": "caption_hook", "value": "훅", "evidence": "caption", "confidence": "high"},
        {"field": "cover_text", "value": None, "evidence": "cover"},
        {"field": "structure", "value": "  ", "evidence": "cover"},
    ])
    assert [(f["field"], f["evidence"]) for f in got] == [("beat_count", "video"), ("cut_lengths", "operator"), ("caption_hook", "caption")]


def test_caption_hook_takes_first_real_line_only():
    assert ig.caption_hook("#밈 #웃김\n내가 술 끊는다고 한 날 https://x.y @친구\n둘째 줄") == "내가 술 끊는다고 한 날"
    assert ig.caption_hook("#only #tags") is None and ig.caption_hook(None) is None
    assert len(ig.caption_hook("가" * 500)) == config.DRINKS_IG_HOOK_MAX_CHARS


def test_hook_similarity_needs_real_overlap():
    assert ig.hook_similarity("내일부터 진짜 금주한다", "내일부터 진짜 금주한다고") > 0.8
    assert ig.hook_similarity("가", "가") == 0
    assert ig.hook_similarity("오늘 날씨", "내일 술자리") == 0
    assert ig.hook_similarity(None, "x") == 0


# ── 카드 병합·분리 ──

def el(**kw):
    kw.setdefault("origin", "rising_reel")
    kw.setdefault("name", "이름")
    return ig.Element(**kw)


def test_merge_key_priority_audio_then_challenge_then_structure_hook():
    both = el(audio_id="A1", challenge_name="곶감 챌린지", structure="pov", hook="훅", media_id="m")
    assert ig.card_key(both, []) == ("audio:A1|s:pov", "audio")
    assert ig.card_key(el(challenge_name="곶감 챌린지", structure="pov", hook="훅", media_id="m"), []) == ("challenge:곶감챌린지", "challenge")
    assert ig.card_key(el(structure="pov", hook="내일부터 진짜 금주한다", media_id="m9"), [])[1] == "structure_hook"


def test_same_audio_different_structure_splits_and_same_name_different_audio_splits():
    assert ig.card_key(el(audio_id="A1", structure="pov"), [])[0] != ig.card_key(el(audio_id="A1", structure="list"), [])[0]
    assert ig.card_key(el(audio_id="A1", name="original audio"), [])[0] != ig.card_key(el(audio_id="A2", name="original audio"), [])[0]


def test_audio_name_is_never_part_of_the_key():
    key, _ = ig.card_key(el(audio_id="A1", name="오리지널 사운드"), [])
    assert "오리지널" not in key


def test_structure_hook_merges_only_with_same_structure_and_similar_hook():
    cards = [{"merge_key": "hook:pov:m1", "structure": "pov", "caption_hook": "내일부터 진짜 금주한다"}]
    assert ig.card_key(el(structure="pov", hook="내일부터 진짜 금주한다고", media_id="m2"), cards)[0] == "hook:pov:m1"
    assert ig.card_key(el(structure="list", hook="내일부터 진짜 금주한다고", media_id="m2"), cards)[0] == "hook:list:m2"
    assert ig.card_key(el(structure="pov", hook="전혀 다른 문장이에요", media_id="m3"), cards)[0] == "hook:pov:m3"


def test_reel_without_structure_or_audio_never_merges_on_hook_alone():
    assert ig.card_key(el(hook="같은 훅", media_id="m1"), []) == ("reel:m1", "single_reel")
    assert ig.card_key(el(hook="같은 훅", media_id="m2"), []) == ("reel:m2", "single_reel")


def test_reels_are_not_attached_to_audio_cards_automatically():
    res = {"a": ig.AccountResult("a", 1, [{"media_id": "m1", "username": "a", "trend_flag": "rising", "is_backfill": False,
                                           "caption_hook": "곶감 챌린지 해봄", "_caption": "곶감 챌린지 해봄", "media_audio_type": "ORIGINAL"}])}
    els = ig.reel_elements(res, set(), ["곶감 챌린지"])
    assert els[0].audio_id is None and els[0].challenge_name == "곶감 챌린지"
    assert ig.card_key(els[0], [])[0] == "challenge:곶감챌린지"


def test_reel_elements_exclude_backfill_normal_and_already_attached():
    def r(mid, **kw):
        return {"media_id": mid, "username": "a", "trend_flag": "rising", "is_backfill": False, "caption_hook": None, **kw}
    res = {"a": ig.AccountResult("a", 1, [r("m1"), r("m2", is_backfill=True), r("m3", trend_flag="normal"), r("m4")])}
    assert [e.media_id for e in ig.reel_elements(res, {"m4"}, [])] == ["m1"]


def test_audio_elements_only_rising_named_original_sounds_by_list_position():
    audio = [
        {"audio_id": "1", "audio_type": "music", "title": "노래", "list_position": 1, "rising_reason": "new"},
        {"audio_id": "2", "audio_type": "original_sound", "title": "Original audio", "list_position": 2, "rising_reason": "new"},
        {"audio_id": "3", "audio_type": "original_sound", "title": "곶감 챌린지", "list_position": 9, "rising_reason": "three_days"},
        {"audio_id": "4", "audio_type": "original_sound", "title": "웃긴 소리", "list_position": 3, "rising_reason": "new"},
        {"audio_id": "5", "audio_type": "original_sound", "title": "안 오르는 소리", "list_position": 4, "rising_reason": None},
    ]
    assert [e.audio_id for e in ig.audio_elements(audio)] == ["4", "3"]


# ── 수명 ──

def card(**kw):
    base = {"card_id": "c1", "state": "new", "first_seen_on": d(5), "last_evaluated_on": d(1), "quiet_normal_days": 0, "increase_streak": 0}
    return {**base, **kw}


def life(c, new_examples=0, in_list=False, three=False):
    return ig.next_lifecycle(c, today=TODAY, new_examples=new_examples, audio_in_list=in_list, audio_three_days=three)


def test_creation_day_is_not_an_increase():
    got = life(card(first_seen_on=TODAY.isoformat(), last_evaluated_on=None), new_examples=3)
    assert got["state"] == "new" and got["increase_streak"] == 0 and got["quiet_normal_days"] == 0


def test_rising_needs_two_consecutive_increases_then_peak_when_it_stops():
    one = life(card(), new_examples=1)
    assert one["state"] == "new" and one["increase_streak"] == 1
    two = life(card(increase_streak=1), new_examples=1)
    assert two["state"] == "rising"
    assert life(card(state="rising", increase_streak=2))["state"] == "peak"
    assert life(card(state="peak", increase_streak=0), new_examples=1)["state"] == "peak", "하루 늘었다고 바로 오르지 않는다"
    assert life(card(state="peak", increase_streak=1), new_examples=1)["state"] == "rising"


def test_three_day_audio_rises_once_then_peaks():
    assert life(card(), in_list=True, three=True)["state"] == "rising"
    assert life(card(state="rising"), in_list=True, three=True)["state"] == "peak"
    assert life(card(state="peak"), in_list=True, three=True)["state"] == "peak"


def test_cooled_after_seven_quiet_normal_days_and_audio_in_list_keeps_it_alive():
    assert life(card(quiet_normal_days=5))["state"] == "new"
    got = life(card(quiet_normal_days=6))
    assert got["state"] == "cooled" and got["quiet_normal_days"] == 7
    assert life(card(quiet_normal_days=6), in_list=True)["quiet_normal_days"] == 0


def test_cooled_card_with_new_activity_comes_back_as_new():
    assert life(card(state="cooled", quiet_normal_days=9))["state"] == "cooled"
    assert life(card(state="cooled", quiet_normal_days=9), new_examples=1)["state"] == "new"


def test_same_day_is_not_counted_twice():
    assert life(card(last_evaluated_on=TODAY.isoformat()), new_examples=1) is None


# ── 토큰 ──

def test_debug_token_parsing_and_warning_at_fourteen_days():
    far = int((NOW + timedelta(days=30)).timestamp())
    info = ig.parse_debug_token({"data": {"is_valid": True, "expires_at": far, "data_access_expires_at": far}}, NOW)
    assert info.status == "ok" and info.days_left == 30 and ig.token_warning(info) is None
    near = ig.parse_debug_token({"data": {"is_valid": True, "expires_at": int((NOW + timedelta(days=13, hours=1)).timestamp())}}, NOW)
    assert near.days_left == 13 and "13일" in ig.token_warning(near)
    edge = ig.parse_debug_token({"data": {"is_valid": True, "expires_at": int((NOW + timedelta(days=14, hours=1)).timestamp())}}, NOW)
    assert ig.token_warning(edge) is None


def test_debug_token_invalid_expired_never_and_bad_shape():
    assert ig.parse_debug_token({"data": {"is_valid": False}}, NOW).status == "expired"
    past = int((NOW - timedelta(days=1)).timestamp())
    assert ig.parse_debug_token({"data": {"is_valid": True, "expires_at": past}}, NOW).status == "expired"
    never = ig.parse_debug_token({"data": {"is_valid": True, "expires_at": 0}}, NOW)
    assert never.status == "ok" and never.expires_at is None and never.days_left is None
    assert ig.parse_debug_token({}, NOW).status == "unavailable"


@pytest.mark.parametrize("code,msg,reason", [
    (190, "expired", "token_expired"), (102, "", "token_expired"), (4, "", "rate_limited"), (17, "", "rate_limited"), (32, "", "rate_limited"),
    (613, "", "rate_limited"), (110, "Invalid user id", "invalid_user"), (100, "Invalid user id", "invalid_user"),
    (100, "Tried accessing nonexisting field", "bad_request"), (10, "", "permission"), (200, "API access blocked", "permission"),
    (1, "", "api_error"), (None, None, "api_error"),
])
def test_graph_error_classes(code, msg, reason):
    assert ig.classify_graph_error(code, msg) == reason


# ── 워커 한 바퀴 (MockTransport + 메모리 rpc) ──

class FakeDb:
    """0063 함수의 모양만 흉내 낸다. 규칙은 PGlite 시험이 본다. 단 '정상 관측일 아니면 거부'는 같이 흉내 낸다."""

    def __init__(self, accounts=(), links=(), runs=(), cards=(), audio_first_seen=None, audio_recent=(), last_run_on=None, baseline=()):
        self.accounts = [dict(a) for a in accounts]
        self.links = list(links)
        self.runs = {(r["source"], str(r["observed_on"])): dict(r) for r in runs}
        self.cards = {c["merge_key"]: dict(c) for c in cards}
        self.audio_first_seen = dict(audio_first_seen or {})
        self.audio_recent = list(audio_recent)
        self.last_run_on = last_run_on
        self.baseline = list(baseline)
        self.calls = []
        self.media = {}
        self.audio = {}
        self.examples = {}
        self.token_checks = []
        self.finished_links = {}

    def __call__(self, fn, p):
        self.calls.append((fn, json.loads(json.dumps(p, default=str))))
        return getattr(self, fn.replace("drinks_ig_", "f_"))(p)

    def f_worker_state(self, p):
        return {"accounts": self.accounts, "last_run_on": self.last_run_on, "runs": list(self.runs.values()),
                "audio_first_seen": self.audio_first_seen, "audio_recent": self.audio_recent, "pending_links": self.links,
                "unattached_links": [], "cards": list(self.cards.values()), "attached_media": list(self.examples)}

    def f_record_run(self, p):
        key = (p["source"], p["observed_on"])
        if p["status"] == "not_run" and key in self.runs:
            return {"written": False}
        self.runs[key] = dict(p)
        return {"written": True}

    def f_record_token_check(self, p):
        self.token_checks.append(p)
        return {}

    def f_baseline_rows(self, p):
        return self.baseline

    def f_record_audio(self, p):
        for a in p["items"]:
            self.audio[a["audio_id"]] = a
        return {"recorded": len(p["items"])}

    def f_record_media(self, p):
        for m in p["items"]:
            self.media[m["media_id"]] = m
        return {"recorded": len(p["items"])}

    def f_mark_account(self, p):
        return {"updated": True}

    def f_finish_link(self, p):
        self.finished_links[p["link_id"]] = p
        return {}

    def _normal(self, day):
        t1, t2 = self.runs.get(("t1", day)), self.runs.get(("t2", day))
        return bool(t1 and t2 and ig.is_normal_day(t1["status"], t2["attempted"], t2["succeeded"]))

    def f_upsert_card(self, p):
        if not self._normal(p["observed_on"]):
            raise DbError("not_normal_day", "정상 관측일이 아닙니다")
        created = p["merge_key"] not in self.cards
        c = self.cards.setdefault(p["merge_key"], {"card_id": f"card-{len(self.cards) + 1}", "merge_key": p["merge_key"], "kind": p["kind"], "state": "new",
                                                   "first_seen_on": p["observed_on"], "last_evaluated_on": None, "quiet_normal_days": 0,
                                                   "increase_streak": 0, "audio_id": p.get("audio_id")})
        for e in p["examples"]:
            self.examples.setdefault(e["media_id"], c["card_id"])
        return {"card_id": c["card_id"], "created": created, "new_examples": len(p["examples"])}

    def f_apply_lifecycle(self, p):
        if not self._normal(p["observed_on"]):
            raise DbError("not_normal_day", "정상 관측일이 아닙니다")
        by_id = {c["card_id"]: c for c in self.cards.values()}
        n = 0
        for u in p["cards"]:
            c = by_id[u["card_id"]]
            if (c.get("last_evaluated_on") or "") < p["observed_on"]:
                c.update(state=u["state"], quiet_normal_days=u["quiet_normal_days"], increase_streak=u["increase_streak"], last_evaluated_on=p["observed_on"])
                n += 1
        return {"applied": n, "skipped": len(p["cards"]) - n}

    def run_row(self, source, day=None):
        return self.runs[(source, day or TODAY.isoformat())]

    def names(self):
        return [c[0] for c in self.calls]


def jr(obj, status=200):
    return httpx.Response(status, headers={"content-type": "application/json; charset=UTF-8"}, content=json.dumps(obj, ensure_ascii=False).encode())


def audio_row(i, kind):
    row = {"audio_id": f"{kind}-{i}", "title": f"{kind} 제목 {i}", "duration_in_ms": 15000, "audio_type": kind, "download_url": "https://cdn.example/x.mp3"}
    return {**row, "ig_username": "someone"} if kind == "original_sound" else {**row, "display_artist": "가수"}


def reel(mid, views=100, hours=100, **kw):
    t = (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    m = {"id": mid, "caption": f"{mid} 캡션 첫 줄\n둘째 줄 #태그", "media_type": "VIDEO", "media_product_type": "REELS", "permalink": f"https://www.instagram.com/reel/{mid}abcde/",
         "timestamp": t, "like_count": 5, "comments_count": 1, "thumbnail_url": f"https://cdn.example/{mid}.jpg", "media_audio_type": "ORIGINAL"}
    if views is not None:
        m["view_count"] = views
    return {**m, **kw}


class Graph:
    """가짜 Graph API. 받은 요청을 기록하고, 토큰이 URL 에 들어가는지 함께 본다."""

    def __init__(self, *, accounts=None, audio_pages=1, token_body=None, token_status=200, audio_error=None, audio_map=None):
        self.accounts = accounts or {}
        self.audio_pages = audio_pages
        self.token_body = token_body if token_body is not None else {"data": {"is_valid": True, "expires_at": int((NOW + timedelta(days=50)).timestamp()),
                                                                              "data_access_expires_at": int((NOW + timedelta(days=80)).timestamp())}}
        self.token_status = token_status
        self.audio_error = audio_error
        self.audio_map = audio_map
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        assert req.headers.get("authorization") == f"Bearer {TOKEN}"
        path = urlsplit(str(req.url)).path
        q = parse_qs(urlsplit(str(req.url)).query)
        if path.endswith("/debug_token"):
            return jr(self.token_body, self.token_status)
        if path.endswith("/ig_audio"):
            assert TOKEN not in str(req.url), "토큰은 헤더로만"
            if self.audio_error:
                return jr({"error": self.audio_error}, 400)
            kind = q["audio_type"][0]
            page = int(q.get("after", ["0"])[0])
            rows = self.audio_map[kind] if self.audio_map else [audio_row(page * 2 + i, kind) for i in range(2)]
            body = {"audio": rows}
            if page + 1 < self.audio_pages:
                body["paging"] = {"cursors": {"after": str(page + 1)},
                                  "next": f"https://graph.facebook.com/x?access_token=LEAK&after={page + 1}&audio_type={kind}"}
            return jr(body)
        assert TOKEN not in str(req.url), "토큰은 헤더로만"
        fields = q["fields"][0]
        u = re.search(r"username\(([^)]+)\)", fields).group(1)
        got = self.accounts.get(u)
        if got is None:
            return jr({"error": {"code": 110, "message": "Invalid user id"}}, 400)
        if isinstance(got, dict) and "error" in got:
            return jr(got, 400)
        return jr({"business_discovery": {"id": "1", "username": u, "followers_count": 1000, "media_count": 25, "media": {"data": got}}, "id": "2"})


def fetcher(graph, max_requests=500):
    return SafeFetcher(["graph.facebook.com"], interval_sec=3, max_requests=max_requests, transport=httpx.MockTransport(graph),
                       resolver=lambda h, p: ["8.8.8.8"], verify_peer=False, sleep=lambda s: None)


def go(db, graph, token=TOKEN):
    return ig.run(db, fetcher(graph), token=token, ig_user_id="123", today=TODAY, now=NOW)


def accs(*names, first=None):
    return [{"username": n, "first_observed_on": first or d(10)} for n in names]


def test_normal_day_records_all_sources_and_fills_position_across_pages():
    db = FakeDb(accounts=accs("a"), runs=day_runs(d(1)), last_run_on=d(1))
    g = Graph(accounts={"a": [reel("m1")]}, audio_pages=2)
    out = go(db, g)
    assert db.run_row("t1")["status"] == "ok" and db.run_row("t1")["attempted"] == 4 and db.run_row("t1")["items"] == 8
    assert db.run_row("t2")["status"] == "ok" and (db.run_row("t2")["attempted"], db.run_row("t2")["succeeded"]) == (1, 1)
    assert db.run_row("t3")["status"] == "ok_empty"
    assert out["normal_day"] is True and ig.exit_code(out) == 0
    assert db.audio["music-3"]["list_position"] == 4, "자리는 쪽을 넘어 이어진다"
    assert "t4" not in {c[1].get("source") for c in db.calls if c[0] == "drinks_ig_record_run"}


def test_paging_uses_values_not_the_next_url_and_stops_at_page_cap():
    g = Graph(accounts={}, audio_pages=9)
    go(FakeDb(), g)
    audio_reqs = [r for r in g.requests if urlsplit(str(r.url)).path.endswith("/ig_audio")]
    assert len(audio_reqs) == config.DRINKS_IG_AUDIO_PAGES * 2
    assert all("LEAK" not in str(r.url) for r in audio_reqs), "응답 주소의 access_token 을 다시 보내지 않는다"


def test_download_url_and_video_url_values_are_never_recorded():
    db = FakeDb(accounts=accs("a"))
    go(db, Graph(accounts={"a": [reel("m1", media_url="https://cdn.example/video.mp4")]}))
    dumped = json.dumps(db.calls, ensure_ascii=False)
    assert "video.mp4" not in dumped and "x.mp3" not in dumped
    assert db.media["m1"]["has_video_url"] is True
    assert "둘째 줄" not in dumped, "캡션 전문을 저장하지 않는다"
    assert db.media["m1"]["caption_hook"] == "m1 캡션 첫 줄"


def test_missing_view_count_stays_null_is_excluded_and_counted():
    db = FakeDb(accounts=accs("a"), baseline=[])
    out = go(db, Graph(accounts={"a": [reel("m1", views=None), reel("m2", views=0), reel("m3", views="많음")]}))
    assert db.media["m1"]["view_count"] is None and db.media["m1"]["trend_flag"] == "no_views"
    assert db.media["m2"]["view_count"] == 0, "진짜 0 은 0 이다"
    assert db.media["m3"]["view_count"] is None, "숫자가 아니면 null"
    assert db.run_row("t2")["excluded_no_views"] == 2 == out["excluded_no_views"]


def test_rising_reel_makes_a_card_on_a_normal_day_with_age_bucket_baseline():
    history = [{"username": "a", "media_id": f"old{i}", "age_bucket": "d3_7", "view_count": 100} for i in range(8)]
    db = FakeDb(accounts=accs("a"), baseline=history)
    out = go(db, Graph(accounts={"a": [reel("hit", views=900, hours=100), reel("meh", views=120, hours=100), reel("young", views=9000, hours=2)]}))
    assert db.media["hit"]["trend_flag"] == "rising" and db.media["hit"]["view_multiple"] == 9
    assert db.media["meh"]["trend_flag"] == "normal"
    assert db.media["young"]["trend_flag"] == "insufficient_sample", "다른 나이 구간은 그 구간 표본으로만 본다"
    assert out["cards_created"] == 1 and "reel:hit" in db.cards


def test_backfill_reels_are_flagged_and_make_no_card_even_when_they_would_rise():
    history = [{"username": "a", "media_id": f"old{i}", "age_bucket": "d3_7", "view_count": 100} for i in range(8)]
    db = FakeDb(accounts=accs("a", first=TODAY.isoformat()), baseline=history)
    out = go(db, Graph(accounts={"a": [reel("hit", views=900)]}))
    assert db.media["hit"]["is_backfill"] is True and db.media["hit"]["trend_flag"] == "rising"
    assert out["cards_created"] == 0 and db.cards == {}


def test_t2_partial_below_eighty_percent_records_reasons_and_touches_no_card():
    history = [{"username": "a", "media_id": f"old{i}", "age_bucket": "d3_7", "view_count": 100} for i in range(8)]
    db = FakeDb(accounts=accs("a", "b", "c"), baseline=history)
    out = go(db, Graph(accounts={"a": [reel("hit", views=900)], "b": {"error": {"code": 1, "message": "x"}}}))
    r = db.run_row("t2")
    assert r["status"] == "partial" and (r["attempted"], r["succeeded"]) == (3, 1)
    assert r["failure_reasons"] == {"api_error": 1, "invalid_user": 1}
    assert out["normal_day"] is False and db.cards == {}
    assert "drinks_ig_upsert_card" not in db.names() and "drinks_ig_apply_lifecycle" not in db.names()
    assert db.media["hit"]["trend_flag"] == "rising", "관측은 남긴다 - 다음 정상 관측일에 다시 판정한다"


def test_rate_limit_stops_further_calls_and_counts_the_rest_as_failed():
    g = Graph(accounts={"a": {"error": {"code": 4, "message": "x"}}, "b": [reel("m")], "c": [reel("n")]})
    db = FakeDb(accounts=accs("a", "b", "c"))
    go(db, g)
    r = db.run_row("t2")
    assert r["status"] == "failed" and r["failure_reasons"] == {"rate_limited": 3}
    assert sum(1 for x in g.requests if "fields" in str(x.url)) == 1


def test_t1_failure_and_bad_shape_are_failed_not_empty():
    db = FakeDb(accounts=accs("a"))
    out = go(db, Graph(accounts={"a": []}, audio_error={"code": 1, "message": "x"}))
    assert db.run_row("t1")["status"] == "failed" and db.run_row("t1")["failure_reasons"] == {"api_error": 2}
    assert out["normal_day"] is False and ig.exit_code(out) == 1

    class Shape(Graph):
        def __call__(self, req):
            if urlsplit(str(req.url)).path.endswith("/ig_audio"):
                return jr({"data": []})
            return super().__call__(req)
    db2 = FakeDb(accounts=accs("a"))
    go(db2, Shape(accounts={"a": []}))
    assert db2.run_row("t1")["status"] == "failed" and db2.run_row("t1")["failure_reasons"] == {"bad_shape": 2}


def test_t1_truly_empty_is_ok_empty_and_not_a_normal_day():
    db = FakeDb(accounts=accs("a"))
    out = go(db, Graph(accounts={"a": []}, audio_map={"music": [], "original_sound": []}))
    assert db.run_row("t1")["status"] == "ok_empty" and db.run_row("t1")["attempted"] == 2
    assert out["normal_day"] is False


def test_no_active_accounts_is_recorded_honestly_and_is_not_a_normal_day():
    db = FakeDb()
    out = go(db, Graph())
    r = db.run_row("t2")
    assert r["status"] == "ok_empty" and r["attempted"] == 0 and r["detail"]["no_active_accounts"] is True
    assert out["normal_day"] is False


def test_skipped_dates_are_filled_with_not_run_before_today():
    db = FakeDb(accounts=accs("a"), last_run_on=d(3))
    go(db, Graph(accounts={"a": []}))
    assert db.run_row("t1", d(2))["status"] == "not_run" and db.run_row("t2", d(1))["status"] == "not_run" and db.run_row("t3", d(1))["status"] == "not_run"
    assert ("t4", d(1)) not in db.runs
    assert db.run_row("t1")["status"] != "not_run"


# ── 합격 시험(기획 §9 P1): 토큰을 빼면 failed 로 기록되고 카드 수명이 멈춘다 ──

def seed_card(**kw):
    return {"card_id": "c1", "merge_key": "reel:old", "kind": "single_reel", "state": "new", "first_seen_on": d(9), "last_evaluated_on": d(1),
            "quiet_normal_days": 6, "increase_streak": 0, "audio_id": None, **kw}


def test_acceptance_removed_token_records_failed_and_lifecycle_stops_counting():
    db = FakeDb(accounts=accs("a", "b"), cards=[seed_card()], runs=day_runs(d(1)), last_run_on=d(1),
                links=[{"link_id": "l1", "shortcode": "abcde", "username": "a", "attempts": 0}])
    g = Graph()
    out = ig.run(db, fetcher(g), token=None, ig_user_id="123", today=TODAY, now=NOW)
    for src in ("t1", "t2", "t3"):
        r = db.run_row(src)
        assert r["status"] == "failed" and r["failure_reasons"].get("token_missing", 0) >= 1, src
    assert db.run_row("t2")["attempted"] == 2, "화면의 '계정 성공 0 / 목록 2' 가 사실대로 나간다"
    assert g.requests == [], "토큰이 없으면 외부 호출을 하지 않는다"
    assert db.token_checks[-1]["status"] == "missing"
    assert "drinks_ig_apply_lifecycle" not in db.names() and "drinks_ig_upsert_card" not in db.names()
    c = db.cards["reel:old"]
    assert c["quiet_normal_days"] == 6 and c["state"] == "new" and c["last_evaluated_on"] == d(1), "하루 더 조용했어도 식음으로 안 넘어간다"
    assert db.finished_links == {}, "링크는 다음 실행이 다시 집는다"
    assert ig.exit_code(out) == 1


def test_contrast_same_card_on_a_normal_day_does_cool():
    db = FakeDb(accounts=accs("a", "b"), cards=[seed_card()], runs=day_runs(d(1)), last_run_on=d(1))
    out = go(db, Graph(accounts={"a": [], "b": []}))
    assert out["normal_day"] is True
    c = db.cards["reel:old"]
    assert c["state"] == "cooled" and c["quiet_normal_days"] == 7


@pytest.mark.parametrize("graph", [
    Graph(token_body={"data": {"is_valid": False}}),
    Graph(token_body={"error": {"code": 190, "message": "expired"}}, token_status=401),
    Graph(token_body={"data": {"is_valid": True, "expires_at": int((NOW - timedelta(hours=1)).timestamp())}}),
])
def test_token_expired_means_failed_everywhere_with_reason(graph):
    db = FakeDb(accounts=accs("a"), cards=[seed_card()])
    out = go(db, graph)
    for src in ("t1", "t2", "t3"):
        assert db.run_row(src)["status"] == "failed" and db.run_row(src)["failure_reasons"].get("token_expired", 0) >= 1
    assert out["token_status"] == "expired" and ig.exit_code(out) == 1
    assert db.cards["reel:old"]["quiet_normal_days"] == 6
    assert not any(urlsplit(str(r.url)).path.endswith("/ig_audio") for r in graph.requests), "이미 만료면 더 부르지 않는다"


def test_token_dying_mid_run_marks_the_rest_and_corrects_the_token_row():
    class Dies(Graph):
        def __call__(self, req):
            if "business_discovery" in str(req.url) or "fields" in str(req.url):
                self.requests.append(req)
                return jr({"error": {"code": 190, "message": "expired"}}, 400)
            return super().__call__(req)
    db = FakeDb(accounts=accs("a", "b"), links=[{"link_id": "l1", "shortcode": "abcde", "username": "z", "attempts": 0}])
    out = go(db, Dies())
    assert db.run_row("t1")["status"] == "ok"
    assert db.run_row("t2")["status"] == "failed" and db.run_row("t2")["failure_reasons"] == {"token_expired": 2}
    assert db.run_row("t3")["status"] == "failed" and db.finished_links == {}
    assert db.token_checks[-1]["status"] == "expired" and out["token_status"] == "expired"


def test_debug_token_unavailable_does_not_stop_collection():
    db = FakeDb(accounts=accs("a"))
    out = go(db, Graph(accounts={"a": []}, token_body={"error": {"code": 1, "message": "x"}}, token_status=500))
    assert out["token_status"] == "unavailable" and db.token_checks[-1]["status"] == "unavailable"
    assert db.run_row("t1")["status"] == "ok"


def test_token_warning_goes_to_the_log(caplog):
    caplog.set_level("INFO")
    near = int((NOW + timedelta(days=5)).timestamp())
    out = go(FakeDb(), Graph(token_body={"data": {"is_valid": True, "expires_at": near}}))
    assert out["token_days_left"] == 5
    assert any("5일" in r.getMessage() for r in caplog.records)


def test_token_never_appears_in_logs_or_db_calls_even_on_errors(caplog):
    caplog.set_level("DEBUG")
    db = FakeDb(accounts=accs("a"))

    def boom(req):
        if urlsplit(str(req.url)).path.endswith("/debug_token"):
            raise httpx.ConnectError("boom")
        return Graph(accounts={"a": []})(req)
    out = ig.run(db, fetcher(boom), token=TOKEN, ig_user_id="123", today=TODAY, now=NOW)
    assert out["token_status"] == "unavailable"
    go(FakeDb(), Graph())
    text = " ".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in text, "로그에 토큰이 없어야 한다(httpx 요청 로그 포함)"
    assert TOKEN not in json.dumps(db.calls, ensure_ascii=False)
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_graph_error_carries_no_url_or_cause():
    g = Graph(accounts={})
    client = ig.GraphClient(fetcher(g), TOKEN)
    with pytest.raises(ig.GraphError) as e:
        client.get("123", {"fields": ig.business_discovery_fields("nobody")})
    assert e.value.reason == "invalid_user" and e.value.__cause__ is None
    assert TOKEN not in str(e.value) and "http" not in str(e.value)


def test_request_cap_stops_cleanly_without_pretending_success():
    db = FakeDb(accounts=accs("a", "b", "c"))
    # 토큰 1 + 음원 2 까지만 허용
    out = ig.run(db, fetcher(Graph(accounts={"a": []}), max_requests=3), token=TOKEN, ig_user_id="123", today=TODAY, now=NOW)
    assert db.run_row("t2")["status"] == "failed" and db.run_row("t2")["failure_reasons"] == {"request_cap": 3}
    assert out["normal_day"] is False


# ── T3 ──

def link(code="m1abcde", user="a", attempts=0):
    return {"link_id": f"l-{code}", "shortcode": code, "username": user, "attempts": attempts}


def test_link_resolves_by_shortcode_and_makes_a_card_on_a_normal_day_without_opening_the_link():
    db = FakeDb(accounts=accs("a"), links=[link()])
    g = Graph(accounts={"a": [reel("m1")]})
    out = go(db, g)
    assert db.finished_links["l-m1abcde"]["status"] == "resolved" and db.finished_links["l-m1abcde"]["media_id"] == "m1"
    assert db.run_row("t3")["status"] == "ok" and db.run_row("t3")["items"] == 1
    assert out["cards_created"] == 1 and db.examples["m1"]
    assert all(r.url.host == "graph.facebook.com" for r in g.requests)
    assert sum(1 for r in g.requests if "fields" in str(r.url)) == 1, "T2 에서 받은 계정은 다시 부르지 않는다"


def test_link_outcomes_not_found_account_unavailable_and_retryable_failure():
    db = FakeDb(accounts=accs("a"), links=[link("zzzzzzz"), link("q1abcde", user="nobody"), link("r1abcde", user="broken"), link("s1abcde", user="broken2", attempts=2)])
    go(db, Graph(accounts={"a": [reel("m1")], "broken": {"error": {"code": 1, "message": "x"}}, "broken2": {"error": {"code": 1, "message": "x"}}}))
    f = db.finished_links
    assert f["l-zzzzzzz"]["status"] == "not_found"
    assert f["l-q1abcde"]["status"] == "account_unavailable"
    assert f["l-r1abcde"]["status"] == "pending", "일시 실패는 다음에 다시"
    assert f["l-s1abcde"]["status"] == "failed", "세 번째면 포기"
    r = db.run_row("t3")
    assert (r["attempted"], r["succeeded"], r["items"]) == (4, 2, 0) and r["status"] == "partial"


def test_link_on_a_non_normal_day_is_kept_for_the_next_normal_day():
    db = FakeDb(accounts=accs("a"), links=[link()])
    out = go(db, Graph(accounts={"a": [reel("m1")]}, audio_error={"code": 1, "message": "x"}))
    assert out["normal_day"] is False and db.cards == {}
    assert db.finished_links["l-m1abcde"]["status"] == "resolved"
    assert 'unattached_links' in SQL


# ── 동일 날 재실행 ──

def test_rerun_same_day_does_not_count_lifecycle_twice():
    history = [{"username": "a", "media_id": f"old{i}", "age_bucket": "d3_7", "view_count": 100} for i in range(8)]
    db = FakeDb(accounts=accs("a"), baseline=history, cards=[seed_card(merge_key="reel:other", card_id="c2", quiet_normal_days=2)])
    g = Graph(accounts={"a": [reel("hit", views=900)]})
    go(db, g)
    before = dict(db.cards["reel:other"])
    assert before["quiet_normal_days"] == 3
    go(db, g)
    assert db.cards["reel:other"] == before


# ── 상한·설정 ──

def test_new_card_cap_is_recorded_not_silent(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_IG_MAX_NEW_CARDS_PER_RUN", 1)
    rows_ = [audio_row(i, "original_sound") for i in range(3)]
    db = FakeDb(accounts=accs("a"), audio_first_seen={}, runs=day_runs(d(1)), last_run_on=d(1))
    out = go(db, Graph(accounts={"a": []}, audio_map={"music": [audio_row(0, "music")], "original_sound": rows_}))
    assert out["cards_created"] == 1 and out["cards_capped"] == 2


def test_operator_links_come_before_the_cap():
    els = ig.link_elements([{"media_id": "m1", "username": "a"}, {"media_id": "m1", "username": "a"}, {"media_id": "m2", "username": "a"}], {"m2"})
    assert [e.media_id for e in els] == ["m1"] and els[0].origin == "operator_link"


def test_request_budget_covers_the_active_limit():
    need = 1 + len(config.DRINKS_IG_AUDIO_TYPES) * config.DRINKS_IG_AUDIO_PAGES + config.DRINKS_IG_ACTIVE_LIMIT + config.DRINKS_IG_LINKS_PER_RUN
    assert config.DRINKS_IG_MAX_REQUESTS >= need


# ── 값 대조: SQL·화면·config 가 같은 문턱을 쓴다 ──

def test_sql_thresholds_match_config():
    assert f"succeeded::numeric / attempted >= {config.DRINKS_IG_NORMAL_T2_MIN_RATE}" in SQL
    assert f"v_quiet < {config.DRINKS_IG_COOLED_NORMAL_DAYS}" in SQL
    assert f"username <> v_user) >= {config.DRINKS_IG_ACTIVE_LIMIT}" in SQL
    for f in config.DRINKS_IG_VIDEO_ONLY_FIELDS:
        assert f"'{f}'" in SQL
    assert "field not in ('beat_count','cut_lengths','twist_at','first_1_5s','music_sync')" in SQL


def test_web_thresholds_match_config():
    assert f"NORMAL_T2_MIN_RATE = {config.DRINKS_IG_NORMAL_T2_MIN_RATE}" in TS
    assert f"FREEZE_MISSING_DAYS = {config.DRINKS_IG_FREEZE_MISSING_DAYS}" in TS
    assert f"TOKEN_WARN_DAYS = {config.DRINKS_IG_TOKEN_WARN_DAYS}" in TS


def test_status_vocabulary_matches_sql_and_web():
    for st in ig.RUN_STATUSES:
        assert f"'{st}'" in SQL and st in TS


# ── 경계: 돈·남의 영상·공개 범위 ──

def _code(path):
    return "\n".join(l.split("#", 1)[0] for l in path.read_text(encoding="utf-8").splitlines())


def test_worker_has_no_apify_llm_or_spend_path():
    src = (ROOT / "engine" / "drinks_ig_trends.py").read_text(encoding="utf-8")
    for bad in ["apify.com", "ApifyClient", "APIFY_TOKEN", "maxTotalChargeUsd", "anthropic", "gemini", "deepseek", "decide.", "drinks_paid"]:
        assert bad not in src, bad
    assert config.DRINKS_IG_GRAPH_HOST == "graph.facebook.com"


def test_worker_never_writes_video_bytes_or_storage():
    src = _code(ROOT / "engine" / "drinks_ig_trends.py")
    for bad in ["open(", "storage", "Storage", ".upload", "write_bytes"]:
        assert bad not in src, bad


def test_migration_stays_private_and_t4_is_inert():
    sql = SQL.lower()
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", sql)
    assert "create policy" not in sql
    tables = re.findall(r"create table if not exists (\w+)", sql)
    assert tables and all(t.startswith("drink_ig_") for t in tables)
    for t in tables:
        assert f"alter table {t} enable row level security" in sql, t
    altered = set(re.findall(r"alter table (\w+)", sql))
    assert altered <= set(tables), altered
    assert "drink_trend_posts" not in re.sub(r"^--.*$", "", sql, flags=re.M), "0059 와 표를 나눈다"
    assert "source not in ('t1','t2','t3')" in sql, "기록 함수가 t4 를 받지 않는다"
    assert "media_url" not in re.sub(r"^--.*$", "", sql, flags=re.M), "영상 주소 칸을 두지 않는다"
    assert "view_count bigint default" not in sql


def test_seed_is_candidates_only_with_documented_names():
    block = SQL[SQL.index("insert into drink_ig_watch_accounts"):SQL.index("on conflict (username) do nothing;")]
    rows_ = re.findall(r"\('([a-z0-9._]+)',\s+'(\w+)',", block)
    assert {n for n, _ in rows_} >= {"9gag", "pubity", "memezar", "daquan"}
    assert {s for _, s in rows_} == {"candidate"}, "활성화는 운영자만"
    doc = (ROOT / "docs" / "검토_Apify도입_2026-11-01.md").read_text(encoding="utf-8")
    for n, _ in rows_:
        assert n in doc, f"{n}: 문서에 없는 이름은 넣지 않는다"


def test_workflow_is_daily_0730_kst_least_privilege_and_free():
    wf = (ROOT / ".github" / "workflows" / "drinks-trend-board.yml").read_text(encoding="utf-8")
    assert '"30 22 * * *"' in wf and "workflow_dispatch" in wf and "contents: read" in wf
    assert "python -m engine.drinks_ig_trends" in wf and "SOOLJJERIGO_FB_TOKEN: ${{ secrets.SOOLJJERIGO_FB_TOKEN }}" in wf
    collect = (ROOT / ".github" / "workflows" / "drinks-collect.yml").read_text(encoding="utf-8")
    for use in re.findall(r"uses:\s*(\S+)", wf):
        assert use in collect, f"{use}: drinks-collect 와 같은 고정 SHA"
    for bad in ["ANTHROPIC", "GEMINI", "DEEPSEEK", "APIFY", "JEV"]:
        assert bad not in wf, bad


def test_fetch_error_keeps_error_body_only_for_classification():
    def h(req):
        return jr({"error": {"code": 190, "message": "secret-ish message"}}, 400)
    f = fetcher(h)
    with pytest.raises(FetchError) as e:
        f.get("https://graph.facebook.com/v1/x", accept=("application/json",))
    assert b"secret-ish" in e.value.error_body and "secret-ish" not in str(e.value)
