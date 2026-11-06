"""독립 리뷰(2026-11-04) 후속 — 실패 주입 시험. 진짜 SQL(메모리 PGlite, 0050~0071) + 진짜 워커 + 가짜 공급자. 네트워크·유료 호출 0.

  R3 근거 철회 후 정보형 밈 게시 — 만든 뒤·발행안 전·예약 전·claim 전·claim 뒤 철회 모두 게시 호출 0회, 농담 밈은 그대로 게시
  R4 고아 가잡기 — 시도 행만 만들고 끊김 / failed_billed 뒤 정산 응답 유실 / 그림 결과 불명 → sweep·운영자 닫기로 복구, 이중 정산 없음
  R6 게시 가능 시각 — 새벽·자정·23:30 경계
  R2 Apify 월 상한 — 요청 행을 넣는 순간 다시 센다(트리거)

PGlite 는 연결이 하나라 "동시" 실행을 진짜로 겹쳐 돌릴 수는 없다 — 동시성은 잠금·고유 색인·상태 검사로 막혔는지를 순서대로 확인한다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from engine import config
from engine import drinks_paid as dpaid
from engine import drinks_produce as dp
from engine import drinks_publish
from engine.drinks_collect import DbError
from engine.providers import video as pv
from engine.providers.instagram import FakeInstagram

ROOT = Path(__file__).resolve().parents[1]
# 모듈 단위로 한 번만 건너뛴다(test_drinks_loop_e2e.py 와 같은 규칙). 시험 16개가 각각 건너뛰면 CI 의 '건너뜀 건수' 감시(기준 14)를
# 넘긴다 — 2026-11-06 PR #143 파이썬 잡이 25건으로 실패했다. CI 에서는 웹 의존성이 있는 web 잡이 이 파일을 따로 돌린다.
if shutil.which("node") is None or not (ROOT / "web" / "node_modules" / "@electric-sql" / "pglite").exists():
    pytest.skip("node·web 의존성(@electric-sql/pglite)이 없어 리뷰 후속 DB 시험을 건너뜁니다 — web 에서 npm ci", allow_module_level=True)
needs_db = pytest.mark.skipif(False, reason="")   # 모듈 상단에서 이미 걸렀다. 표시는 남겨 어느 시험이 DB 를 쓰는지 보이게 한다
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


@pytest.fixture(scope="module")
def db():
    from scripts import explainer_queue_rehearsal as qr

    d = qr.PgRpc()
    yield d
    d.close()


def _fails(fn, code: str) -> None:
    with pytest.raises(DbError) as e:
        fn()
    assert e.value.code == code, e.value


# ─────────────────────────────────────────────────────────────
# R6 — 게시 가능 시각
# ─────────────────────────────────────────────────────────────

@needs_db
@pytest.mark.parametrize("kst,ok", [("06:59", False), ("07:00", True), ("12:00", True), ("23:30", True), ("23:31", False), ("00:00", False), ("03:00", False)])
def test_publish_window_boundaries(db, kst, ok):
    got = db.sql(f"select drinks_publish_window_ok(('2026-11-05 {kst}:00'::timestamp at time zone 'Asia/Seoul')) as ok")[0]["ok"]
    assert got is ok


def test_publish_window_matches_config_and_cron():
    sql = (ROOT / "supabase" / "migrations" / "0071_drinks_review_fixes.sql").read_text(encoding="utf-8")
    w = config.DRINKS_PUBLISH_WINDOW
    assert f"'start', '{w['start']}', 'end', '{w['end']}'" in sql and f"'timezone', '{w['timezone']}'" in sql
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "drinks-publish.yml").read_text(encoding="utf-8"))
    crons = [c["cron"] for c in (wf.get("on") or wf.get(True))["schedule"]]
    assert config.DRINKS_PUBLISH_CRON_PUBLISH in crons
    # 게시 크론(UTC)을 KST 로 풀어, 하루의 첫·마지막 실행이 창의 시작·끝과 같은지 본다.
    minute, hour = config.DRINKS_PUBLISH_CRON_PUBLISH.split()[:2]
    hours = []
    for part in hour.split(","):
        a, _, b = part.partition("-")
        hours += list(range(int(a), int(b or a) + 1))
    times = sorted(f"{(h + 9) % 24:02d}:{int(m):02d}" for h in hours for m in minute.split(","))
    assert times[0] == w["start"] and times[-1] == w["end"], times
    web = (ROOT / "web" / "lib" / "drinks" / "publishWindow.ts").read_text(encoding="utf-8")
    assert f'start: "{w["start"]}"' in web and f'end: "{w["end"]}"' in web and f'timezone: "{w["timezone"]}"' in web


# ─────────────────────────────────────────────────────────────
# R3 — 근거 철회 후 정보형 밈 게시
# ─────────────────────────────────────────────────────────────

class CountingIG(FakeInstagram):
    """가짜 인스타. 게시(publish) 호출 수를 센다. on_container 가 있으면 claim 뒤(컨테이너 만들 때) 한 번 부른다."""

    def __init__(self, path: str):
        super().__init__(path)
        self.publishes = 0
        self.on_container = None

    def create_container(self, *a, **k):
        if self.on_container:
            fn, self.on_container = self.on_container, None
            fn()
        return super().create_container(*a, **k)

    def publish(self, *a, **k):
        self.publishes += 1
        return super().publish(*a, **k)


@pytest.fixture(scope="module")
def pubenv(db, tmp_path_factory):
    from scripts import publish_loop_rehearsal as pr

    root = tmp_path_factory.mktemp("pub")
    db.sql("create or replace function drinks_publish_window() returns jsonb language sql immutable as $$ "
           "select jsonb_build_object('timezone', 'Asia/Seoul', 'start', '00:00', 'end', '23:59:59') $$")
    storage = dp.Storage("local", str(root / "storage"))
    ig = CountingIG(str(root / "ig.json"))

    def providers(acc):
        assert acc.get("connection") == "fake"
        return ig
    acc = pr.fake_account(db, ig, providers)
    card = pr.approved_card_review(db, storage)
    review = db.sql("select topic_review_id from drink_plan_revisions where id = $1", [card["plan_id"]])[0]["topic_review_id"]
    yield {"db": db, "storage": storage, "ig": ig, "providers": providers, "acc": acc, "review": review, "pr": pr}
    db.sql("create or replace function drinks_publish_window() returns jsonb language sql immutable as $$ "
           f"select jsonb_build_object('timezone', '{config.DRINKS_PUBLISH_WINDOW['timezone']}', 'start', '{config.DRINKS_PUBLISH_WINDOW['start']}', "
           f"'end', '{config.DRINKS_PUBLISH_WINDOW['end']}') $$")


def _meme(env, *, info: bool) -> str:
    from engine import drinks_meme as dm

    db, pr = env["db"], env["pr"]
    card = pr.precise_card(db, "리뷰 시험 카드")
    if info:
        spec = dm.build_spec(frame="top_text", top_line="다이긴조 라벨, 알고 있었어?", beats=[{"text": "양조 알코올을", "keyword": "", "ms": 3200},
                             {"text": "안 넣는대요", "keyword": "", "ms": 3800}], caption="근거는 국세청 자료예요", palette="night",
                             audio={"mode": "ambient_local"}, contains_info=True, claim_ids=["c2"])
        review = env["review"]
    else:
        spec = dm.build_spec(frame="top_text", top_line="POV: 와인 고르는 척하는 나", beats=[{"text": "앞면을 본다", "keyword": "", "ms": 3000},
                             {"text": "가격표만 기억난다", "keyword": "가격표", "ms": 4000}], caption="다들 이러잖아요", palette="wine")
        review = None
    saved = db("drinks_meme_save_draft", {"card_id": card, "spec": spec, **({"evidence_review_id": review} if review else {})})
    assert not saved["blockers"], saved["blockers"]
    db("drinks_meme_draft_action", {"draft_id": saved["draft_id"], "expected_version": saved["version"], "action": "approve"})
    res = dm.run_queue(db, env["storage"], worker_id="t", kind="render", max_jobs=1)
    assert res and res[0]["status"] == "publish_waiting", res
    return saved["draft_id"]


def _revoke(env) -> None:
    env["db"].sql("select drinks_revoke_review_internal($1, '리뷰 R3 시험')", [env["review"]])


def _restore(env) -> None:
    """다음 경우를 위해 근거를 되살린다(시험 전용 — 운영에는 철회를 되돌리는 문이 없다)."""
    db = env["db"]
    db.sql("set session_replication_role = replica")
    db.sql("update drink_topic_reviews set revoked_at = null, revoked_reason = null, status = 'approved' where id = $1", [env["review"]])
    db.sql("set session_replication_role = origin")


def _create(env, draft: str) -> str:
    from datetime import datetime, timedelta, timezone

    when = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    return env["db"]("drinks_create_meme_publication", {"draft_id": draft, "account_id": env["acc"], "publish_at": when})["request_id"]


def _run(env) -> list[dict[str, Any]]:
    return drinks_publish.run(env["db"], env["storage"], env["providers"], worker_id="t", wait_sec=1, poll_sec=0)["published"]


@needs_db
@needs_ffmpeg
def test_r3_revoked_evidence_blocks_meme_publication_at_every_stage(pubenv):
    env, db = pubenv, pubenv["db"]
    ig = env["ig"]
    before = ig.publishes

    # ① 제작 뒤, 발행안 전에 철회 → 발행안을 만들 수 없다
    d1 = _meme(env, info=True)
    _revoke(env)
    _fails(lambda: _create(env, d1), "not_publishable")
    _restore(env)

    # ② 발행안 뒤·승인 요청 전에 철회 → 승인 요청이 막힌다
    d2 = _meme(env, info=True)
    r2 = _create(env, d2)
    _revoke(env)
    _fails(lambda: env["pr"].schedule(db, r2), "not_publishable")
    _restore(env)

    # ③ 예약 뒤·claim 전에 철회 → claim 이 멈춤(paused)으로 돌리고 게시 0회
    d3 = _meme(env, info=True)
    r3 = _create(env, d3)
    env["pr"].schedule(db, r3)
    _revoke(env)
    assert db("drinks_publication_state", {"request_id": r3})["block"] == "meme_evidence_missing"
    _run(env)
    row = db.sql("select status, pause_code from drink_publication_requests where id = $1", [r3])[0]
    assert row == {"status": "paused", "pause_code": "meme_evidence_missing"}
    _restore(env)

    # ④ claim 뒤(컨테이너를 만드는 순간)에 철회 → 게시 직전 재확인이 막는다
    d4 = _meme(env, info=True)
    r4 = _create(env, d4)
    env["pr"].schedule(db, r4)
    ig.on_container = lambda: _revoke(env)
    _run(env)
    row = db.sql("select status from drink_publication_requests where id = $1", [r4])[0]
    assert row["status"] != "published", row
    assert ig.publishes == before, "철회 뒤에는 실제 게시 호출이 한 번도 없어야 한다"
    _restore(env)


@needs_db
@needs_ffmpeg
def test_r3_joke_meme_still_publishes_and_changed_draft_needs_reapproval(pubenv):
    env, db = pubenv, pubenv["db"]
    d = _meme(env, info=False)
    r = _create(env, d)
    env["pr"].schedule(db, r)
    out = _run(env)
    assert [p.get("status") for p in out if p["request_id"] == r] == ["published"]
    # 승인 뒤 제작안이 바뀌면(지문 불일치) 게시하지 않는다
    d2 = _meme(env, info=False)
    r2 = _create(env, d2)
    env["pr"].schedule(db, r2)
    db.sql("set session_replication_role = replica")
    db.sql("update drink_meme_drafts set spec = jsonb_set(spec, '{caption}', '\"바뀐 캡션\"') where id = $1", [d2])
    db.sql("set session_replication_role = origin")
    assert db("drinks_publication_state", {"request_id": r2})["block"] == "meme_digest_changed"


# ─────────────────────────────────────────────────────────────
# R4 — 고아 가잡기
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def xenv(db, tmp_path_factory):
    from engine import drinks_explainer_queue as q
    from scripts import explainer_queue_rehearsal as qr

    root = tmp_path_factory.mktemp("x")
    storage = dp.Storage("local", str(root / "storage"))
    deps = q.Deps(adapter=qr.FakeAdapter(root / "clips"), tts_fn=qr.fake_tts())
    plan = qr.plan_to_directive(db, storage, deps)
    approval = qr.open_approval(db, plan, 5)
    start = root / "start.png"
    from PIL import Image

    Image.new("RGB", (768, 1344), (40, 50, 60)).save(start)
    cands = []
    for n in (11, 12):   # 시험 전용 슬롯(제작안 장면 번호와 겹치지 않게). 후보 2개씩
        slot = db("drinks_explainer_plan_slot", {"plan_revision_id": plan, "n": n, "role": "reality", "spec_hash": f"{n:02d}" * 32, "min_src_ms": 3000,
                                                 "candidates_planned": 2})
        cands += slot["candidate_ids"]
    return {"db": db, "storage": storage, "approval": approval, "cands": cands, "start": str(start), "root": root}


def _item(cid: str) -> dpaid.OrderItem:
    return dpaid.clip_item(1, "reality", "the camera slowly pushes in", "scene-01-reality", "a" * 64, clip_sec=4, candidate_id=cid, provider="omni")


class Dies:
    """RPC 하나에서 프로세스가 죽은 것처럼(응답 유실) 예외를 낸다. after=True 면 DB 에는 반영된 뒤 응답만 잃는다."""

    def __init__(self, db, fn: str, *, after: bool = False, match=None):
        self.db, self.fn, self.after, self.match, self.fired = db, fn, after, match, False

    def __call__(self, fn: str, p: dict[str, Any]) -> Any:
        if fn == self.fn and not self.fired and (self.match is None or self.match(p)):
            self.fired = True
            if self.after:
                self.db(fn, p)
            raise ConnectionError(f"{fn} 응답 유실(주입)")
        return self.db(fn, p)


def _age(db, hours: float = 2) -> None:
    db.sql("alter table drink_explainer_attempts disable trigger user")
    db.sql("update drink_explainer_attempts set updated_at = now() - make_interval(secs => $1)", [int(hours * 3600)])
    db.sql("alter table drink_explainer_attempts enable trigger user")
    db.sql("alter table drink_spend_holds disable trigger user")
    db.sql("update drink_spend_holds set created_at = now() - make_interval(secs => $1) where status = 'held'", [int(hours * 3600)])
    db.sql("alter table drink_spend_holds enable trigger user")


def _hold(db, approval: str, item_key: str) -> dict[str, Any]:
    return db.sql("select id, status, actual_usd from drink_spend_holds where approval_id = $1 and item_key = $2 order by created_at desc limit 1", [approval, item_key])[0]


class Billed:
    live = False

    def clip(self, *a, **k):
        raise pv.ExplainerBilledBadFile("받은 파일이 깨짐(주입)")


@needs_db
def test_r4a_attempt_opened_then_worker_dies_before_generating(xenv):
    """재현 A: 가잡기 → 시도 행 → generating 기록 전 중단. 예전엔 시도에 hold_id 가 없어 sweep 이 닫아도 가잡기가 남았다."""
    db, ap, cid = xenv["db"], xenv["approval"], xenv["cands"][0]
    rpc = Dies(db, "drinks_explainer_attempt_event", match=lambda p: p.get("to_state") == "generating")
    # generating 기록이 끊기면 워커가 바로 failed_unbilled 로 닫으려 한다 — 그 기록도 잃은 것처럼(프로세스가 죽음) 이어서 끊는다
    rpc2 = Dies(rpc, "drinks_explainer_attempt_event", match=lambda p: p.get("to_state") == "failed_unbilled")
    with pytest.raises(ConnectionError):
        dpaid.buy_clip_attempt(_item(cid), rpc=rpc2, storage=xenv["storage"], approval_id=ap, out_dir=str(xenv["root"] / "o"), start_image=xenv["start"], adapter=Billed())
    att = db.sql("select state, hold_id from drink_explainer_attempts where candidate_id = $1", [cid])[0]
    assert att["state"] == "requested" and att["hold_id"] is not None, "가잡기가 시도 행에 처음부터 묶인다"
    _age(db)
    out = db("drinks_explainer_sweep_stale", {"older_than_sec": 600})
    assert out["failed_unbilled"] >= 1
    assert _hold(db, ap, cid)["status"] == "released"


@needs_db
def test_r4b_failed_billed_then_settle_response_lost_is_repaired_once(xenv):
    """재현 B: failed_billed 기록 직후 정산 RPC 실패 → 예전엔 held 가 남고 sweep 처리 0건."""
    db, ap, cid = xenv["db"], xenv["approval"], xenv["cands"][1]
    rpc = Dies(db, "drinks_settle_spend")
    with pytest.raises(ConnectionError):
        dpaid.buy_clip_attempt(_item(cid), rpc=rpc, storage=xenv["storage"], approval_id=ap, out_dir=str(xenv["root"] / "o"), start_image=xenv["start"], adapter=Billed())
    assert db.sql("select state from drink_explainer_attempts where candidate_id = $1", [cid])[0]["state"] == "failed_billed"
    assert _hold(db, ap, cid)["status"] == "held"
    _age(db)
    out = db("drinks_explainer_sweep_stale", {"older_than_sec": 600})
    assert out["repaired_holds"] == 1
    h = _hold(db, ap, cid)
    assert h["status"] == "settled" and float(h["actual_usd"]) == pytest.approx(_item(cid).est_usd)
    again = db("drinks_explainer_sweep_stale", {"older_than_sec": 600})
    assert again["repaired_holds"] == 0, "두 번 정산하지 않는다"
    _fails(lambda: db("drinks_settle_spend", {"hold_id": h["id"], "outcome": "settled", "actual_usd": 1}), "invalid_state")


@needs_db
def test_r4_orphan_image_hold_is_listed_and_closed_only_by_operator(xenv, monkeypatch):
    """R1 의 결과 불명 시작 그림은 어느 시도에도 묶이지 않은 held 가잡기로 남는다 — 목록에 나오고, 운영자만 닫는다. 자동 해제 없음."""
    db, ap = xenv["db"], xenv["approval"]
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    it = dpaid.image_item(7, "reality", "A shelf of bottles")

    def boom(*a):
        raise TimeoutError("접수 뒤 응답 없음(주입)")
    with pytest.raises(dpaid.PaidError):
        dpaid.buy(it, rpc=db, storage=xenv["storage"], approval_id=ap, out_dir=str(xenv["root"] / "img"), generate=boom)
    _fails(lambda: dpaid.buy(it, rpc=db, storage=xenv["storage"], approval_id=ap, out_dir=str(xenv["root"] / "img"), generate=boom), "hold_in_progress")
    _age(db)
    db("drinks_explainer_sweep_stale", {"older_than_sec": 600})
    h = _hold(db, ap, it.item_key)
    assert h["status"] == "held", "sweep 은 고아 가잡기를 자동으로 풀지 않는다"
    orphans = [o["hold_id"] for o in db("drinks_spend_orphan_holds", {"older_than_sec": 600})["holds"]]
    assert h["id"] in orphans
    _fails(lambda: db("drinks_close_orphan_hold", {"hold_id": h["id"], "resolution": "void", "closed_by": "worker", "note": "x"}), "invalid_input")
    db("drinks_close_orphan_hold", {"hold_id": h["id"], "resolution": "billed", "actual_usd": it.est_usd, "closed_by": "운영자", "note": "청구 내역에 1건 있음"})
    assert _hold(db, ap, it.item_key)["status"] == "settled"
    _fails(lambda: db("drinks_close_orphan_hold", {"hold_id": h["id"], "resolution": "void", "closed_by": "운영자", "note": "다시"}), "invalid_state")


@needs_db
def test_r4_close_unknown_changes_state_and_ledger_together_once(xenv):
    db, ap, cid = xenv["db"], xenv["approval"], xenv["cands"][2]

    class Unknown:
        live = False

        def clip(self, *a, **k):
            raise TimeoutError("응답 없음(주입)")
    with pytest.raises(dpaid.PaidError):
        dpaid.buy_clip_attempt(_item(cid), rpc=db, storage=xenv["storage"], approval_id=ap, out_dir=str(xenv["root"] / "o"), start_image=xenv["start"], adapter=Unknown())
    att = db.sql("select attempt_id, hold_id from drink_explainer_attempts where candidate_id = $1 and state = 'unknown_billed'", [cid])[0]
    _fails(lambda: db("drinks_close_orphan_hold", {"hold_id": att["hold_id"], "resolution": "void", "closed_by": "운영자", "note": "x"}), "invalid_state")
    db("drinks_explainer_close_unknown", {"attempt_id": att["attempt_id"], "resolution": "void", "closed_by": "운영자", "note": "청구 없음 확인"})
    assert _hold(db, ap, cid)["status"] == "released"
    _fails(lambda: db("drinks_explainer_close_unknown", {"attempt_id": att["attempt_id"], "resolution": "billed", "closed_by": "운영자", "note": "또", "actual_usd": 1}), "invalid_state")
    assert _hold(db, ap, cid)["status"] == "released"


# ─────────────────────────────────────────────────────────────
# R2 — Apify 월 상한을 행을 넣는 순간 다시 센다
# ─────────────────────────────────────────────────────────────

@needs_db
def test_r2_month_guard_rechecks_on_insert(db):
    month = db.sql("select drinks_apify_month_key() as m")[0]["m"]
    cap = config.DRINKS_APIFY_MONTH_CAP_USD
    # 이달 쓴 돈을 상한 바로 아래로(끝난 요청 하나)
    db.sql("insert into drink_apify_requests (kind, topic_id, cap_usd, est_usd, actual_usd, month_key, status, finished_at) "
           "select 'explainer_reference', id, 0.05, 0.05, $1, $2, 'done', now() from drink_topics limit 1", [round(cap - 0.01, 4), month])
    # 함수의 앞쪽 검사를 거치지 않고 바로 넣어도(= 다른 요청이 그 사이에 커밋된 경우) 트리거가 막는다
    with pytest.raises(DbError) as e:
        db.sql("insert into drink_apify_requests (kind, topic_id, cap_usd, est_usd, month_key) select 'explainer_reference', id, 0.02, 0.02, $1 from drink_topics limit 1", [month])
    assert e.value.code == "apify_budget_exhausted"
    trig = db.sql("select count(*)::int n from pg_trigger where tgname = 'drink_apify_month_guard'")[0]["n"]
    assert trig == 1
    assert "pg_advisory_xact_lock" in (ROOT / "supabase" / "migrations" / "0071_drinks_review_fixes.sql").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 리뷰 P2 — 카드 릴스 + 음원 계약을 가짜 공급자 경로로(게시 루프 리허설의 카드 사례는 캐러셀뿐이었다)
# ─────────────────────────────────────────────────────────────

@needs_db
@needs_ffmpeg
def test_card_reel_with_music_goes_through_the_fake_publish_path(pubenv):
    from datetime import datetime, timedelta, timezone

    env, db, pr = pubenv, pubenv["db"], pubenv["pr"]
    # 앞 시험(R3)이 철회한 소재와 섞이지 않게 새 소재 하나를 쓴다(철회는 편성을 푼다)
    card = pr.approved_card_review(db, env["storage"])
    tid = card["topic_id"]
    review = db.sql("select topic_review_id from drink_plan_revisions where id = $1", [card["plan_id"]])[0]["topic_review_id"]
    pages = [{"role": "cover", "heading": "다이긴조, 왜 비쌀까?"},
             {"role": "explain", "heading": "쌀을 반 이상 깎아요", "body": "정미율 50% 이하", "claim_ids": ["c1"]},
             {"role": "explain", "heading": "넣지 않는 것", "body": "양조 알코올 무첨가", "claim_ids": ["c2"]},
             {"role": "checklist", "heading": "라벨 체크", "body": "양조 알코올 무첨가", "claim_ids": ["c2"]}]
    dv = db.sql("select version from drink_deliverables where topic_id = $1 and format = 'carousel'", [tid])[0]["version"]
    pl = db("drinks_save_plan", {"topic_id": tid, "format": "carousel", "topic_review_id": review, "expected_deliverable_version": dv,
                                 "plan_json": {"pages": pages, "reel": {"hook_title": "다이긴조는 왜 비쌀까?", "share_line": "라벨 볼 때 떠올려 봐"}}})
    for act in ("submit", "approve"):
        db("drinks_plan_action", {"revision_id": pl["revision_id"], "action": act, "expected_version": pr._ver(db, "drink_plan_revisions", pl["revision_id"])})
    db("drinks_request_render", {"plan_revision_id": pl["revision_id"]})
    res = dp.run_queue(db, env["storage"], worker_id="t", max_jobs=1)
    assert res and res[0]["status"] == "succeeded", res
    rev = db.sql("select id, version from drink_output_reviews where manifest_id = $1", [res[0]["manifest_id"]])[0]
    db("drinks_output_review_action", {"review_id": rev["id"], "expected_version": rev["version"], "action": "approve",
                                       "checklist": {**pr.CARD_CK, "reel_motion_ok": True, "reel_hook_share_ok": True}})
    aid = "fake-audio-card-01"
    db.sql("insert into drink_ig_audio (audio_id, audio_type, title, display_artist, first_seen_on, last_seen_on) values ($1, 'music', '노래', '가수', current_date, current_date)", [aid])
    db.sql("insert into drink_ig_audio_observations (audio_id, observed_on, list_position) values ($1, current_date, 1)", [aid])
    when = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    # 음원 없이 만든 릴스 발행안은 승인 요청에서 막힌다(0065 계약) — 취소하고 음원을 골라 새로 만든다
    r0 = db("drinks_create_publication", {"output_review_id": rev["id"], "account_id": env["acc"], "caption": "원문 근거만 담은 카드예요", "post_type": "reel", "publish_at": when})
    _fails(lambda: db("drinks_publication_action", {"request_id": r0["request_id"], "action": "submit",
                                                    "expected_version": pr._ver(db, "drink_publication_requests", r0["request_id"])}), "audio_required")
    db("drinks_publication_action", {"request_id": r0["request_id"], "action": "cancel", "expected_version": pr._ver(db, "drink_publication_requests", r0["request_id"])})
    r = db("drinks_create_publication", {"output_review_id": rev["id"], "account_id": env["acc"], "caption": "원문 근거만 담은 카드예요", "post_type": "reel", "publish_at": when,
                                         "audio": {"mode": "ig_audio", "audio_id": aid, "audio_volume": 90, "video_volume": 10, "sync_grade": "sync_free"}})
    pr.schedule(db, r["request_id"])
    before = env["ig"].publishes
    out = _run(env)
    assert [p.get("status") for p in out if p["request_id"] == r["request_id"]] == ["published"]
    assert env["ig"].publishes == before + 1
    row = db.sql("select post_type, audio, audio_verified_at from drink_publication_requests where id = $1", [r["request_id"]])[0]
    assert row["post_type"] == "reel" and row["audio"]["audio_id"] == aid and row["audio_verified_at"] is not None, "게시 직전 음원 재조회를 지났다"
    st = json.loads(Path(env["ig"].path).read_text(encoding="utf-8"))
    reels = [c for c in st["containers"].values() if c["kind"] in ("reel", "REELS")]
    assert reels and any(c.get("audio_id") == aid or aid in json.dumps(c) for c in reels), "가짜 인스타 컨테이너에 음원이 실렸다"
