"""주류 소재 발견 - 질문 지도(2026-10-29). docs/주류_질문지도_v1_2026-10-29.md

네트워크 없음. 네이버는 httpx.MockTransport, Jev 는 decide 를 가짜로 바꿔서 본다 - 실제 호출 검증이 아니다.
"""
import json

import httpx
import pytest

from engine import config
from engine import drinks_discover as dd
from engine.drinks_collect import DbError
from engine.drinks_fetch import SafeFetcher
from scripts import drinks_dismiss_offmap_candidates as dismiss
from scripts import drinks_question_map_sources as qsrc

HUB = ["naverapihub.apigw.ntruss.com"]


def fetcher(handler):
    return SafeFetcher(HUB, interval_sec=3, max_requests=50, transport=httpx.MockTransport(handler),
                       resolver=lambda h, p: ["8.8.8.8"], verify_peer=False, sleep=lambda s: None)


def js(obj):
    return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(obj).encode())


@pytest.fixture
def naver_keys(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(naver_client_id="id-test", naver_client_secret="secret-test"))


# ── 지도 ──

def test_map_has_24_cells_of_two_queries_and_every_source_plan_fits_the_query_limit():
    m = config.DRINKS_QUESTION_MAP
    assert len(m) == 24 and all(len(c[3]) == 2 for c in m)
    assert len({(c[0], c[1]) for c in m}) == 24
    assert {c[0] for c in m} == {"sake", "traditional", "whisky"} and len({c[1] for c in m}) == 8
    queries = [q for c in m for q in c[3]]
    assert len(queries) == 48 and len(set(queries)) == 48
    plans = qsrc.plan_sources()
    assert len(plans) == 6
    for p in plans:
        assert len(p["queries"]) == 8 <= 10 and all(len(q) <= 100 for q in p["queries"])
        assert p["name"].startswith(config.DRINKS_QUESTION_MAP_SOURCE_PREFIX) and p["platform"] == "naver" and p["language"] == "ko"
        assert len(p["categories"]) == 1
    assert sorted(q for p in plans for q in p["queries"]) == sorted(queries), "48개가 6개 수집원에 빠짐없이 한 번씩"
    assert "위스키 1(보관·고르기·차이·마시는 법)" in "".join(p["name"] for p in plans)


def test_every_map_query_lands_in_its_own_cell():
    for cat, kind, _ko, qs in config.DRINKS_QUESTION_MAP:
        for q in qs:
            assert dd.question_cell(q) == (cat, kind), q


@pytest.mark.parametrize("q,cell", [
    ("히이레 니혼슈도 상온에 보관 하면 맛이 변할 수 있나요?", ("sake", "storage")),
    ("생막걸리 와 살균막걸리 는 무엇이 다를까요", ("traditional", "difference")),
    ("[이덕희의 사케 ] 사케 는 반드시 데워 마셔야 할까?", ("sake", "howto")),
    ("비오는 날엔 왜 파전 에 막걸리 일까요?", ("traditional", "pairing")),
    ("부나하벤 12년 은 왜 아일라 위스키 인데 피트 향이 약할까?", ("whisky", "label")),
    ("하지만 막걸리 , 과연 칼로리 면에서 그리 나쁜 선택일까요?", ("traditional", "misconception")),
    ("사케 도 숙성빨이 있나요", ("sake", "misconception")),
    ("누룩 을 선물 받았는데 어떻게 보관하나요?", ("traditional", "storage")),
    ("위스키 입문해보려고 합니다 입문용으로 좋은 위스키 추천 부탁드려도 될까요?", ("whisky", "selection")),
    ("캠핑 갈 때 뭐 챙기나요", (None, None)),
    ("기술 이야기 궁금합니다", (None, None)),   # '기술' 의 '술' 은 술이 아니다
])
def test_question_cell_by_keywords(q, cell):
    assert dd.question_cell(q) == cell


# ── 질문 규칙 ──

def test_long_sentences_are_not_questions_and_cjk_limit_is_shorter_than_latin():
    ok = "막걸리 유통기한이 지난 것을 마셔도 괜찮은지 궁금합니다"
    long_ko = "막걸리 " + "가나다라마바사 " * 10 + "괜찮은지 궁금합니다"   # 문장부호 없는 문단 하나
    assert len(ok) <= config.DRINKS_QUESTION_MAX_CHARS < len(long_ko)
    assert dd.extract_questions(ok) == [ok]
    assert dd.extract_questions(long_ko) == [], "요약 전체가 한 질문이 되던 것을 막는다"
    en = "Is it safe to drink whisky that has been open in the bottle for over ten years?"
    assert config.DRINKS_QUESTION_MAX_CHARS < len(en) <= config.DRINKS_QUESTION_MAX_CHARS_LATIN
    assert dd.extract_questions(en) == [en], "영어 제목은 더 길어도 된다"


def test_question_needs_a_drink_word_in_the_question_itself():
    assert dd.question_ok("막걸리 유통기한이 지나도 마셔도 되나요?") is True
    assert dd.question_ok("이거 유통기한 지나도 마셔도 되나요?") is False, "제목에만 술이 있고 질문에는 없다"
    assert dd.question_ok("기술 이야기를 해도 될까요?") is False
    assert dd.question_ok("막걸리 " + "가" * 80) is False, "길이 상한"
    assert dd.question_ok("How long does opened sake last?") is True
    assert dd.question_ok(None) is False


# ── 네이버: 정확도순 ──

def _items(n, date="20250101", prefix="막걸리"):
    return [{"title": f"{prefix} {i}", "link": f"https://blog.naver.com/z/{i}", "description": "", "postdate": date} for i in range(n)]


def test_sim_sort_skips_the_watermark_filter_and_the_full_page_count(naver_keys, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(config, "DRINKS_NAVER_SORT", "sim")
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return js({"items": _items(int(req.url.params["display"]))})   # 한 쪽을 꽉 채우고, 워처마크보다 한참 옛 글
    since = datetime(2026, 10, 20, tzinfo=timezone.utc)
    b = dd.naver(fetcher(h), {"queries": ["a 막걸리", "b 막걸리"], "kinds": ["blog"]}, since, 10)
    assert all(p["sort"] == "sim" for p in seen)
    assert b.incomplete == 0, "정확도순은 시간순이 아니라서 '꽉 찬 쪽' 판정이 없다"
    assert len(b.found) == 10, "옛 날짜 글도 버리지 않는다"


def test_date_sort_still_filters_by_watermark_and_counts_full_pages(naver_keys, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(config, "DRINKS_NAVER_SORT", "date")
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return js({"items": _items(int(req.url.params["display"]), date="20261029")})
    since = datetime(2026, 10, 20, tzinfo=timezone.utc)
    b = dd.naver(fetcher(h), {"queries": ["a", "b"], "kinds": ["blog"]}, since, 10)
    assert all(p["sort"] == "date" and "start" not in p for p in seen) and b.incomplete == 2
    old = dd.naver(fetcher(lambda r: js({"items": _items(3)})), {"queries": ["a"], "kinds": ["blog"]}, since, 10)
    assert old.found == [], "최신순에서는 워처마크보다 옛 글을 거른다"


def test_sim_sort_rotates_the_start_position_by_day_and_caps_at_naver_max():
    starts = [dd.naver_start(6, day) for day in range(10)]
    assert starts[:5] == [1, 7, 13, 19, 25] and starts[5:] == starts[:5], "날짜 순번 % 5 칸을 돈다"
    assert dd.naver_start(300, 4) == config.DRINKS_NAVER_MAX_START == 1000


def test_sim_request_carries_the_rotated_start(naver_keys, monkeypatch):
    monkeypatch.setattr(config, "DRINKS_NAVER_SORT", "sim")
    monkeypatch.setattr(dd, "kst_day_ordinal", lambda: 3)
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return js({"items": []})
    dd.naver(fetcher(h), {"queries": ["막걸리 추천"], "kinds": ["blog"]}, None, 30)
    assert seen and seen[0]["start"] == str(1 + 3 * 30)


# ── 묶기·점수 ──

def _it(i, text, url=None, platform="naver_blog", ch=None):
    return {"id": f"i{i}", "platform": platform, "channel_name": ch or f"ch{i}", "title": text, "summary": "", "summary_hash": f"h{i}",
            "questions": [text], "signals": ["question", "storage"], "canonical_url": url or f"https://blog.naver.com/p/{i}"}


def test_cluster_never_merges_across_cells_but_merges_inside_one():
    sake = _it(1, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?")
    whisky = _it(2, "위스키 개봉 후 냉장 보관 기간이 얼마나 되나요?")
    sake2 = _it(3, "사케 개봉하고 냉장 보관 기간은 얼마나 되나요?")
    assert dd.similarity(sake["questions"][0], whisky["questions"][0]) >= config.DRINKS_DISCOVERY_SIMILAR_MIN, "칸이 없으면 합쳐질 만큼 비슷하다"
    groups = dd.cluster([sake, whisky, sake2])
    cells = sorted(tuple(sorted(it["id"] for it in g)) for g in groups)
    assert cells == [("i1", "i3"), ("i2",)]


def test_card_carries_the_cell_and_a_capped_demand_bonus():
    one = dd.build_card([_it(1, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?")], [])
    assert one["interest"]["cell"] == {"category": "sake", "category_ko": "사케", "kind": "storage", "kind_ko": "보관·유통기한"}
    many = [_it(i, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?", ch="same") for i in range(12)]
    card = dd.build_card(many, [])
    base = dd.build_card(many[:1], [])
    assert "수요 0 " in base["score_reason"]
    assert f"수요 {config.DRINKS_DEMAND_BONUS_MAX} " in card["score_reason"], "추가 글 11개여도 가점은 상한"
    assert card["provisional_score"] <= 100
    two = dd.build_card(many[:2], [])
    assert f"수요 {config.DRINKS_DEMAND_BONUS_PER_ITEM} " in two["score_reason"]


def test_key_question_is_a_qualifying_question_not_a_long_title():
    it = _it(1, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?")
    it["title"] = "이것은 아주 긴 제목입니다 " * 8 + "사케 보관이 궁금합니다"
    assert dd.build_card([it], [])["key_question"] == "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?"


# ── 후보 만들기 + Jev ──

class Rec:
    def __init__(self, items, cands=None):
        self.items, self.cands, self.calls = items, cands or [], []

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn == "drinks_discovery_backlog":
            return {"items": self.items, "candidates": self.cands, "topics": []}
        return {"candidate_id": f"c{len(self.calls)}"}

    def made(self):
        return [p for fn, p in self.calls if fn == "drinks_suggest_candidate" and p["item_ids"]]


@pytest.fixture
def jev(monkeypatch):
    class J:
        enabled = True
        p = 0.9
        raises = False
        asked: list[str] = []
    j = J()
    j.asked = []
    monkeypatch.setattr(dd.decide, "enabled", lambda: j.enabled)

    def noul(state, instructions, criteria, site="", subject=""):
        j.asked.append(state)
        if j.raises:
            raise RuntimeError("boom")
        return j.p
    monkeypatch.setattr(dd.decide, "noul", noul)
    return j


QS = [_it(1, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?"), _it(2, "위스키 12년은 무슨 뜻인가요?")]


def test_jev_below_threshold_does_not_create_the_candidate(jev):
    jev.p = 0.2
    rpc = Rec([dict(x) for x in QS])
    out = dd.suggest_candidates(rpc)
    assert out["new"] == 0 and out["jev_rejected"] == 2 and not rpc.made()
    assert len(jev.asked) == 2, "후보 하나당 한 번"


def test_jev_pass_records_cell_and_p_on_the_card(jev):
    jev.p = 0.83
    rpc = Rec([dict(x) for x in QS])
    out = dd.suggest_candidates(rpc)
    assert out["new"] == 2 and out["jev_rejected"] == 0
    for p in rpc.made():
        assert p["interest"]["jev"] == "ok" and p["interest"]["jev_p"] == 0.83 and p["interest"]["cell"]["kind"] in ("storage", "label")
    assert {p["interest"]["cell"]["category"] for p in rpc.made()} == {"sake", "whisky"}


@pytest.mark.parametrize("mode", ["disabled", "none", "raises"])
def test_jev_unavailable_never_blocks_collection(jev, mode):
    if mode == "disabled":
        jev.enabled = False
    elif mode == "none":
        jev.p = None
    else:
        jev.raises = True
    rpc = Rec([dict(x) for x in QS])
    out = dd.suggest_candidates(rpc)
    assert out["new"] == 2 and out["jev_unavailable"] == 2
    assert all(p["interest"]["jev"] == "unavailable" and "jev_p" not in p["interest"] for p in rpc.made())
    if mode == "disabled":
        assert jev.asked == [], "꺼져 있으면 부르지 않는다"


def test_jev_call_cap_creates_the_rest_unjudged(jev, monkeypatch):
    monkeypatch.setattr(config, "DRINKS_DISCOVERY_JEV_MAX_PER_RUN", 1)
    rpc = Rec([dict(x) for x in QS])
    out = dd.suggest_candidates(rpc)
    assert len(jev.asked) == 1 and out["new"] == 2
    assert sorted(p["interest"]["jev"] for p in rpc.made()) == ["capped", "ok"]


def test_jev_is_not_asked_when_adding_to_an_open_candidate(jev):
    old = [_it(10 + i, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?") for i in range(2)]
    rpc = Rec([_it(1, "사케 개봉하고 냉장 보관 기간은 얼마나 되나요?")],
              [{"id": "c1", "key_question": "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?", "items": old}])
    out = dd.suggest_candidates(rpc)
    assert out["added"] == 1 and out["new"] == 0 and jev.asked == []


def test_open_candidate_in_another_cell_is_not_a_merge_target(jev):
    old = [_it(10, "위스키 개봉 후 냉장 보관 기간이 얼마나 되나요?")]
    rpc = Rec([_it(1, "사케 개봉 후 냉장 보관 기간이 얼마나 되나요?")],
              [{"id": "c1", "key_question": "위스키 개봉 후 냉장 보관 기간이 얼마나 되나요?", "items": old}])
    out = dd.suggest_candidates(rpc)
    assert out["added"] == 0 and out["new"] == 1


def test_parked_rejections_are_dismissed_not_left_open(jev, monkeypatch):
    monkeypatch.setattr(config, "DRINKS_DISCOVERY_JEV_PARK_REJECTED", True)
    jev.p = 0.1
    rpc = Rec([dict(QS[0])])
    out = dd.suggest_candidates(rpc)
    dismissed = [p for fn, p in rpc.calls if fn == "drinks_candidate_action"]
    assert out["new"] == 0 and out["jev_rejected"] == 1 and len(dismissed) == 1 and dismissed[0]["action"] == "dismiss"
    assert "Jev" in dismissed[0]["reason"]


def test_items_whose_question_has_no_drink_word_stay_in_the_inbox(jev):
    it = _it(1, "이거 유통기한 지나도 마셔도 되나요?")
    it["title"] = "막걸리 이야기"
    rpc = Rec([it])
    out = dd.suggest_candidates(rpc)
    assert out["new"] == 0 and out["skipped_items"] == 1 and jev.asked == []


# ── 스크립트: 수집원 교체 ──

class FakeDb:
    """drink_sources 흉내 - source_action/register/request_run 을 받아 상태를 바꾼다."""

    def __init__(self, sources, validated=()):
        self.sources = [dict(s) for s in sources]
        self.validated = set(validated)
        self.calls = []

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn == "drinks_register_discovery_source":
            self.sources.append({"id": f"new{len(self.sources)}", "name": p["name"], "state": "proposed", "platform": p["platform"],
                                 "purpose": "discovery", "version": 1, "terms_status": "unverified"})
            return {"source_id": self.sources[-1]["id"]}
        if fn == "drinks_source_action":
            s = next(x for x in self.sources if x["id"] == p["source_id"])
            if p["expected_version"] != s["version"]:
                raise DbError("version_conflict", "버전이 다릅니다")
            if p["action"] == "retire":
                s["state"] = "retired"
            elif p["action"] == "validate":
                s["state"] = "validated"
            elif p["action"] == "activate":
                assert s["terms_status"] == "verified" and s["state"] == "validated"
                s["state"] = "active"
            elif p["action"] == "update_terms":
                s["terms_status"] = p["terms_status"]
            s["version"] += 1
            return {}
        return {}

    def sources_(self):
        return [dict(s) for s in self.sources]

    def validation_status(self, sid):
        return "succeeded" if sid in self.validated else None


class Store:
    def __init__(self, db):
        self.db = db

    def sources(self):
        return self.db.sources_()

    def validation_status(self, sid):
        return self.db.validation_status(sid)


OLD = [
    {"id": "o1", "name": "네이버 카페·블로그 — 위스키", "state": "active", "platform": "naver", "purpose": "discovery", "version": 3, "terms_status": "verified"},
    {"id": "o2", "name": "네이버 막걸리", "state": "proposed", "platform": "naver", "purpose": "discovery", "version": 1, "terms_status": "unverified"},
    {"id": "o3", "name": "네이버 옛것", "state": "retired", "platform": "naver", "purpose": "discovery", "version": 5, "terms_status": "verified"},
    {"id": "o4", "name": "Stack Exchange 술", "state": "active", "platform": "stackexchange", "purpose": "discovery", "version": 2, "terms_status": "verified"},
]


def test_sources_script_dry_run_writes_nothing(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert qsrc.main([]) == 0
    out = capsys.readouterr().out
    assert "질문지도" in out and "미리보기" in out and out.count("개 —") == 6
    db = FakeDb(OLD)
    assert qsrc.main([], rpc=db, store=Store(db)) == 0
    out = capsys.readouterr().out
    assert db.calls == [] and "네이버 카페·블로그 — 위스키" in out and "네이버 막걸리" in out and "Stack Exchange" not in out.split("종료할")[1]


def test_sources_script_apply_retires_old_naver_registers_six_and_requests_validation(capsys):
    db = FakeDb(OLD)
    assert qsrc.main(["--apply"], rpc=db, store=Store(db)) == 0
    retired = [p["source_id"] for fn, p in db.calls if fn == "drinks_source_action" and p["action"] == "retire"]
    assert sorted(retired) == ["o1", "o2"], "교체 대상은 질문지도 머리말이 아닌 네이버 발견 수집원뿐 - 종료분·타 채널은 건드리지 않는다"
    assert all(p["reason"] == "질문 지도로 교체(2026-10-29)" for fn, p in db.calls if fn == "drinks_source_action")
    reg = [p for fn, p in db.calls if fn == "drinks_register_discovery_source"]
    assert len(reg) == 6 and all(len(p["queries"]) <= 10 for p in reg)
    runs = [p for fn, p in db.calls if fn == "drinks_request_run"]
    assert len(runs) == 6 and all(p["mode"] == "validate" for p in runs)
    # 두 번째 실행은 이미 있는 6개를 다시 등록하지 않는다
    before = len(reg)
    qsrc.main(["--apply"], rpc=db, store=Store(db))
    assert len([1 for fn, _ in db.calls if fn == "drinks_register_discovery_source"]) == before


def test_sources_script_apply_needs_env_when_no_rpc_given(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert qsrc.main(["--apply"]) == 2


def test_activate_only_touches_sources_whose_validation_succeeded(capsys):
    db = FakeDb(OLD)
    qsrc.main(["--apply"], rpc=db, store=Store(db))
    names = {s["name"]: s["id"] for s in db.sources if s["name"].startswith(config.DRINKS_QUESTION_MAP_SOURCE_PREFIX)}
    ready = sorted(names.values())[:2]
    db.validated = set(ready)
    db.calls.clear()
    assert qsrc.main(["--activate"], rpc=db, store=Store(db)) == 0
    assert db.calls == [], "--apply 없이는 미리보기"
    assert qsrc.main(["--activate", "--apply"], rpc=db, store=Store(db)) == 0
    acts = [(p["action"], p["source_id"]) for fn, p in db.calls if fn == "drinks_source_action"]
    assert sorted({sid for _, sid in acts}) == ready
    for sid in ready:
        assert [a for a, s in acts if s == sid] == ["update_terms", "validate", "activate"]
    terms = next(p for fn, p in db.calls if fn == "drinks_source_action" and p["action"] == "update_terms")
    assert terms["terms_status"] == "verified" and terms["terms_url"] == qsrc.TERMS_URL and "운영자 위임 확인(2026-10-29)" in terms["terms_note"]
    assert terms["terms_checked_at"]
    collects = [p["source_id"] for fn, p in db.calls if fn == "drinks_request_run" and p["mode"] == "collect"]
    assert sorted(collects) == ready
    assert {s["state"] for s in db.sources if s["id"] in ready} == {"active"}
    assert {s["state"] for s in db.sources if s["id"] in names.values() and s["id"] not in ready} == {"proposed"}


# ── 스크립트: 질문 지도 밖 후보 기각 ──

CANDS = [
    {"id": "k1", "key_question": "막걸리 유통기한 지나도 마셔도 되나요?", "version": 2, "status": "suggested"},
    {"id": "k2", "key_question": "이거 지나도 마셔도 되나요?", "version": 1, "status": "suggested"},
    {"id": "k3", "key_question": "막걸리 " + "가나다라마바사 " * 12 + "궁금합니다", "version": 4, "status": "suggested"},
    {"id": "k4", "key_question": "아고다 10월 할인코드 알아볼 때 · 후지카와구치코 독채 위치", "version": 1, "status": "suggested"},
]


def test_dismiss_script_dry_run_lists_offmap_and_writes_nothing(monkeypatch, capsys):
    calls = []
    rc = dismiss.main([], rpc=lambda fn, p: calls.append((fn, p)), candidates=CANDS)
    out = capsys.readouterr().out
    assert rc == 0 and calls == []
    assert "기준 미달 3건" in out and "술 낱말 없음" in out and "질문이 너무 김" in out
    assert "k1" not in out and "막걸리 유통기한" not in out, "통과한 후보는 목록에 없다"
    assert max(len(line) for line in out.splitlines() if line.startswith("  - [")) <= 80, "제목은 60자까지만 보인다"


def test_dismiss_script_apply_dismisses_with_version_and_reason():
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        if p["candidate_id"] == "k4":
            raise DbError("version_conflict", "먼저 바뀌었습니다")
        return {}
    assert dismiss.main(["--apply"], rpc=rpc, candidates=CANDS) == 1
    assert [(p["candidate_id"], p["expected_version"]) for _, p in calls] == [("k2", 1), ("k3", 4), ("k4", 1)]
    assert all(fn == "drinks_candidate_action" and p["action"] == "dismiss" and p["reason"].startswith("질문 지도 기준 미달(2026-10-29)")
               for fn, p in calls)


def test_dismiss_script_jev_flag_adds_judgement_and_fails_open(jev, capsys):
    jev.p = 0.1
    picked = dismiss.select_offmap(CANDS[:1], jev=True)
    assert [(c["id"], why) for c, why in picked] == [("k1", dismiss.JEV_LOW)]
    jev.enabled = False
    assert dismiss.select_offmap(CANDS[:1], jev=True) == [], "Jev 가 꺼져 있으면 규칙만"
    assert dismiss.select_offmap(CANDS[:1], jev=False) == []
