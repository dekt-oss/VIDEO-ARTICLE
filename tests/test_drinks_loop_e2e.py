"""주류 공장 순환 한 바퀴(e2e) — 수집 → 소재·근거 → 카드 렌더 → 검수 → 발행(가짜 인스타) → 성과 → 전략 제안 → 반영 → 다음 순서.

실제 Postgres 문법으로 도는 PGlite 에 0050~0055 를 올리고(supabase/tests/pglite_rpc_bridge.mjs), **Python 워커 코드
그대로**(drinks_collect·drinks_produce·drinks_publish·drinks_metrics·drinks_strategy)를 그 위에서 돌린다.
네트워크·유료 호출 0: 수집은 httpx MockTransport, 인스타는 FakeInstagram(상태 파일), 카드는 진짜 PNG 렌더.
시간 경과(게시 후 25시간·73시간)는 시험 전용 /sql 로 게시 시각을 되돌려 흉내 낸다.

node 와 web/node_modules(@electric-sql/pglite)가 없으면 건너뛴다(웹 의존성 설치 후 돈다).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from engine import drinks_collect as dc
from engine import drinks_metrics, drinks_produce, drinks_publish, drinks_strategy
from engine.drinks_fetch import SafeFetcher
from engine.providers.instagram import FakeInstagram

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "supabase" / "tests" / "pglite_rpc_bridge.mjs"
HOST = "www.nta.go.jp"
QUOTE1 = "大吟醸酒は精米歩合50%以下の白米を使う"
QUOTE2 = "醸造アルコールを加えない"
ARTICLE = (f"<div id='contents'><h1>大吟醸とは</h1><p>{QUOTE1}。{QUOTE2}。" + "日本酒の説明。" * 80 + "</p></div>").encode()
SCORES = {"relevance": 4, "utility": 4, "curiosity": 3, "fit_video": 1, "fit_carousel": 4, "timeliness": 2}
CARD_CK = {"page_order_ok": True, "no_text_overflow": True, "claims_match_evidence": True, "source_page_ok": True}

# 모듈 단위로 한 번만 건너뛴다(시험 4개가 4건으로 세지면 CI 의 '건너뜀 건수' 감시를 넘는다).
# CI 에서는 웹 의존성이 있는 web 잡이 이 파일을 따로 돌린다(.github/workflows/tests.yml).
if shutil.which("node") is None or not (ROOT / "web" / "node_modules" / "@electric-sql" / "pglite").exists():
    pytest.skip("node·web 의존성(@electric-sql/pglite)이 없어 순환 e2e 를 건너뜁니다", allow_module_level=True)


class Bridge:
    def __init__(self):
        self.proc = subprocess.Popen(["node", str(BRIDGE)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8")
        line = self.proc.stdout.readline()
        m = re.match(r"READY (\d+)", line or "")
        if not m:
            self.proc.kill()
            raise RuntimeError("다리가 뜨지 않았습니다: " + (line or "") + self.proc.stderr.read())
        self.base = f"http://127.0.0.1:{m.group(1)}"

    def _post(self, path: str, body: dict):
        rq = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                    headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    def rpc(self, fn: str, p: dict):
        out = self._post(f"/rpc/{fn}", {"p": p})
        if "error" in out:
            m = re.match(r"drinks:([a-z_]+):(.*)", out["error"]["message"], re.S)
            if m:
                raise dc.DbError(m.group(1), m.group(2))
            raise RuntimeError(f"{fn}: {out['error']['message']}")
        return out["data"]

    def sql(self, q: str, params=None):
        out = self._post("/sql", {"sql": q, "params": params or []})
        if "error" in out:
            raise RuntimeError(out["error"]["message"])
        return out["rows"]

    def close(self):
        self.proc.kill()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    b = Bridge()
    tmp = tmp_path_factory.mktemp("loop")
    fake = FakeInstagram(str(tmp / "fake_ig.json"))
    storage = drinks_produce.Storage(mode="local", root=str(tmp / "storage"))
    yield {"b": b, "rpc": b.rpc, "fake": fake, "storage": storage,
           "providers": lambda acc: fake if acc.get("connection") == "fake" else (_ for _ in ()).throw(AssertionError("실제 공급자"))}
    b.close()


def mock_fetcher(run):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=ARTICLE)
    return SafeFetcher(run["source"]["allowed_hosts"], interval_sec=3, max_requests=20, transport=httpx.MockTransport(handler),
                       resolver=lambda h, p: ["8.8.8.8"], verify_peer=False, sleep=lambda s: None)


def version(b, table, id_):
    return b.sql(f"select version from {table} where id = $1", [id_])[0]["version"]


def collect_snapshot(env) -> str:
    """① 수집: 수집원 등록 → 검증 실행 → 검증·활성 → 수집 실행 → 원문 스냅샷."""
    rpc, b = env["rpc"], env["b"]
    s = rpc("drinks_register_source", {"name": "국세청 술 안내", "home_url": f"https://{HOST}/", "method": "approved_page",
                                       "language": "ja", "categories": ["sake"], "entry_urls": [f"https://{HOST}/sake/daiginjo.htm"],
                                       "terms_status": "verified", "terms_note": "공공 안내문 — 인용·요약 허용", "terms_checked_at": "2026-10-20",
                                       "rights_default": "quote_ok", "parser_config": {"content_ids": ["contents"]}})
    for mode in ("validate", "collect"):
        rpc("drinks_request_run", {"source_id": s["source_id"], "mode": mode})
        res = dc.run_queue(rpc, worker_id="e2e", fetcher_factory=mock_fetcher)
        assert res and res[-1]["status"] not in ("failed", "lease_lost"), res
        if mode == "validate":
            for act in ("validate", "activate"):
                rpc("drinks_source_action", {"source_id": s["source_id"], "action": act,
                                             "expected_version": version(b, "drink_sources", s["source_id"])})
    snaps = b.sql("select id from drink_source_snapshots where canonical_url like $1", [f"https://{HOST}/sake/%"])
    assert snaps, "수집 실행이 원문 스냅샷을 남겨야 한다"
    return snaps[0]["id"]


def manual_snapshot(env, topic_id: str) -> str:
    r = env["rpc"]("drinks_add_source", {"topic_id": topic_id, "source": {
        "canonical_url": f"https://{HOST}/sake/{os.urandom(4).hex()}", "body_text": f"{QUOTE1}。{QUOTE2}。",
        "rights_status": "quote_ok", "title": "大吟醸"}})
    return r["snapshot_id"]


def approved_carousel(env, *, categories=("sake",), snapshot_id=None, title="다이긴조는 왜 비쌀까") -> str:
    """소재 → 경량 평가 → 근거 승인 → 카드 편성 → 카드 제작안 승인. 제작안 id 를 돌려준다."""
    rpc, b = env["rpc"], env["b"]
    q = f"{title} {os.urandom(3).hex()}"
    base = {"title": title, "question": q, "categories": list(categories), "lane": "evergreen"}
    t = rpc("drinks_create_topic_from_snapshot", {**base, "snapshot_id": snapshot_id}) if snapshot_id else rpc("drinks_create_topic", base)
    tid = t["topic_id"]
    rpc("drinks_triage", {"topic_id": tid, "expected_version": version(b, "drink_topics", tid), "scores": SCORES})
    rpc("drinks_topic_action", {"topic_id": tid, "expected_version": version(b, "drink_topics", tid), "action": "start_research"})
    if snapshot_id:
        rpc("drinks_link_snapshot", {"topic_id": tid, "snapshot_id": snapshot_id, "role": "evidence", "relation_note": "근거"})
        sid = snapshot_id
    else:
        sid = manual_snapshot(env, tid)
    claims = [{"claim_id": "c1", "text": "정미율 50% 이하", "claim_type": "process", "support_review": "supported",
               "source_refs": [{"snapshot_id": sid, "original_quote": QUOTE1}]},
              {"claim_id": "c2", "text": "양조 알코올 무첨가", "claim_type": "product_fact", "support_review": "supported",
               "source_refs": [{"snapshot_id": sid, "original_quote": QUOTE2}]}]
    brief = {"audience_question": "왜 비쌀까?", "core_takeaway": "쌀을 반 이상 깎는다", "selected_claim_ids": ["c1", "c2"],
             "proposed_formats": ["carousel"], "required_claims": {"carousel": ["c1", "c2"]}}
    sv = rpc("drinks_save_review", {"topic_id": tid, "expected_topic_version": version(b, "drink_topics", tid), "scores": SCORES,
                                    "brief": brief, "evidence_pack": {"claims": claims}})
    for act in ("submit", "approve"):
        rpc("drinks_review_action", {"review_id": sv["review_id"], "action": act,
                                     "expected_version": version(b, "drink_topic_reviews", sv["review_id"])})
    rv = b.sql("select approved_hash from drink_topic_reviews where id = $1", [sv["review_id"]])[0]
    rpc("drinks_select", {"topic_id": tid, "expected_version": version(b, "drink_topics", tid), "review_id": sv["review_id"],
                          "review_input_hash": rv["approved_hash"], "formats": ["carousel"], "editorial_week": "2026-10-26"})
    pl = rpc("drinks_save_plan", {"topic_id": tid, "format": "carousel", "topic_review_id": sv["review_id"], "plan_json": {"pages": [
        {"role": "cover", "heading": "다이긴조, 왜 비쌀까?"},
        {"role": "explain", "heading": "쌀을 반 이상 깎아요", "body": "정미율 50% 이하", "claim_ids": ["c1"]},
        {"role": "checklist", "heading": "라벨 체크", "body": "양조 알코올 무첨가", "claim_ids": ["c2"]}]}})
    for act in ("submit", "approve"):
        rpc("drinks_plan_action", {"revision_id": pl["revision_id"], "action": act,
                                   "expected_version": version(b, "drink_plan_revisions", pl["revision_id"])})
    return pl["revision_id"]


def render_and_approve(env, plan_id: str) -> str:
    """② 카드뉴스: 렌더 요청 → 제작 워커(진짜 PNG) → 검수 승인. 검수 id 를 돌려준다."""
    rpc, b = env["rpc"], env["b"]
    rpc("drinks_request_render", {"plan_revision_id": plan_id})
    res = drinks_produce.run_queue(rpc, env["storage"], worker_id="e2e", max_jobs=1)
    assert res and res[0]["status"] == "succeeded", res
    rev = b.sql("select id, version from drink_output_reviews where manifest_id = $1", [res[0]["manifest_id"]])[0]
    rpc("drinks_output_review_action", {"review_id": rev["id"], "expected_version": rev["version"], "action": "approve",
                                        "checklist": CARD_CK})
    return rev["id"]


def fake_account(env, ext="fake_sooljjerigo") -> str:
    rpc, b = env["rpc"], env["b"]
    found = b.sql("select id from drink_social_accounts where external_account_id = $1", [ext])
    if found:
        return found[0]["id"]
    env["fake"].add_account(ext, "sooljjerigo_test")
    a = rpc("drinks_register_account", {"external_account_id": ext, "display_name": "술째리고(시험)", "account_type": "test",
                                        "connection": "fake", "capabilities": {"post_types": ["carousel", "reel"]}})
    drinks_publish.verify_accounts(rpc, env["providers"])
    rpc("drinks_account_action", {"account_id": a["account_id"], "action": "enable_publish",
                                  "expected_version": version(b, "drink_social_accounts", a["account_id"])})
    return a["account_id"]


def schedule(env, review_id: str, account_id: str, *, caption: str, publish_at: datetime) -> str:
    """③ 발행안 작성 → 승인 요청 → (화면이 보여준 지문으로) 승인 → 예약."""
    rpc, b = env["rpc"], env["b"]
    r = rpc("drinks_create_publication", {"output_review_id": review_id, "account_id": account_id, "caption": caption,
                                          "publish_at": publish_at.isoformat()})
    rid = r["request_id"]
    rpc("drinks_publication_action", {"request_id": rid, "action": "submit", "expected_version": version(b, "drink_publication_requests", rid)})
    shown = rpc("drinks_publication_state", {"request_id": rid})
    rpc("drinks_publication_action", {"request_id": rid, "action": "approve", "expected_digest": shown["approval_digest"],
                                      "expected_version": shown["version"]})
    rpc("drinks_publication_action", {"request_id": rid, "action": "schedule",
                                      "expected_version": version(b, "drink_publication_requests", rid)})
    return rid


def age(b, rid: str, hours: float):
    """시험 전용 시간 되돌리기: 게시 시각을 hours 시간 전으로(불변 가드를 잠깐 끈다)."""
    b.sql("alter table drink_publication_requests disable trigger drink_publications_guard")
    b.sql("update drink_publication_requests set published_at = now() - make_interval(secs => $2) where id = $1",
          [rid, int(hours * 3600)])
    b.sql("alter table drink_publication_requests enable trigger drink_publications_guard")


def publish_run(env):
    return drinks_publish.run(env["rpc"], env["storage"], env["providers"], worker_id="e2e", wait_sec=1, poll_sec=0)


def req_row(b, rid):
    return b.sql("select * from drink_publication_requests where id = $1", [rid])[0]


NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def test_full_loop_collect_to_strategy(env):
    rpc, b, fake = env["rpc"], env["b"], env["fake"]
    # ① 수집 → ② 카드
    snap = collect_snapshot(env)
    plan = approved_carousel(env, snapshot_id=snap)
    review = render_and_approve(env, plan)
    pages = b.sql("select a.storage_key, a.width, a.height from drink_manifest_assets ma join drink_media_assets a on a.id = ma.asset_id "
                  "join drink_output_reviews r on r.manifest_id = ma.manifest_id where r.id = $1 order by ma.position", [review])
    assert len(pages) == 3 and all(p["storage_key"].startswith("local:drinks/") for p in pages)
    # ③ 발행
    acc = fake_account(env)
    rid = schedule(env, review, acc, caption="다이긴조는 쌀을 50% 이하로 깎아 만들어요. #사케 #술째리고",
                   publish_at=NOW() - timedelta(minutes=1))
    out = publish_run(env)
    assert [p["status"] for p in out["published"]] == ["published"], out
    row = req_row(b, rid)
    assert row["status"] == "published" and row["external_post_id"].startswith("m_")
    assert row["external_url"] and row["reconcile_state"] == "none"
    att = b.sql("select stage, provider_container_ids from drink_publication_attempts where request_id = $1", [rid])
    assert att[0]["stage"] == "confirmed" and len(att[0]["provider_container_ids"]) == 4, "자식 3 + 부모 1"
    st = json.loads(pathlib.Path(fake.path).read_text(encoding="utf-8"))
    kids = [c for c in st["containers"].values() if c["kind"] == "image"]
    assert len(kids) == 3 and all(k["url"].startswith("file:///") for k in kids), "파일은 저장소 임시 주소로 넘어간다"
    assert publish_run(env)["published"] == [], "게시된 요청은 다시 집히지 않는다"
    # ④ 성과 — 아직 칸이 안 열림 → 25시간 → 24h 칸 → 같은 칸 재수집 없음 → 73시간 → 72h 칸
    assert drinks_metrics.collect(rpc, env["providers"]) == []
    age(b, rid, 25)
    got = drinks_metrics.collect(rpc, env["providers"])
    assert [g["bucket"] for g in got] == ["24h"]
    assert drinks_metrics.collect(rpc, env["providers"]) == [], "같은 칸을 두 번 재지 않는다"
    age(b, rid, 73)
    assert [g["bucket"] for g in drinks_metrics.collect(rpc, env["providers"])] == ["72h"]
    snaps = b.sql("select age_bucket, metric_values, unavailable from drink_post_metric_snapshots where request_id = $1 order by id", [rid])
    assert [s["age_bucket"] for s in snaps] == ["24h", "72h"]
    assert "views" not in snaps[0]["metric_values"], "카드뉴스에 없는 지표를 0 으로 채우지 않는다"
    # ⑤ 전략 — 1편뿐 → 표본 부족 제안 → 반영 불가
    first = drinks_strategy.run(rpc)
    assert first["sufficient"] is False and "표본 부족" in first["summary_ko"]
    with pytest.raises(dc.DbError) as e:
        rpc("drinks_strategy_action", {"proposal_id": first["proposal_id"], "action": "accept"})
    assert e.value.code == "insufficient_sample"

    # 게시가 쌓인다: 위스키 3편은 저장·공유가 많고, 사케 2편은 적다(가짜 인스타가 그렇게 답하도록 정해 둔다)
    for cats, saved in [(("whisky",), 60), (("whisky",), 55), (("whisky",), 70), (("sake",), 8), (("sake",), 10)]:
        p = approved_carousel(env, categories=cats, title="위스키 물 몇 방울" if cats == ("whisky",) else "사케 보관")
        r2 = schedule(env, render_and_approve(env, p), acc, caption="원문 근거만 담은 카드예요 #술째리고",
                      publish_at=NOW() - timedelta(minutes=1))
        publish_run(env)
        fake.set_metrics(req_row(b, r2)["external_post_id"], {"reach": 1000, "saved": saved, "shares": saved // 2, "likes": 50,
                                                               "comments": 3})
        age(b, r2, 73)
    fake.set_metrics(req_row(b, rid)["external_post_id"], {"reach": 1000, "saved": 9, "shares": 4, "likes": 40, "comments": 2})
    drinks_metrics.collect(rpc, env["providers"])
    # 앞서 잰 1번 게시물의 72h 값은 이미 있다(다시 재지 않는다) — 사케 표본 3편 = 1번 + 2편
    second = drinks_strategy.run(rpc)
    assert second["sufficient"] is True, second
    prop = b.sql("select weights, basis from drink_strategy_proposals where id = $1", [second["proposal_id"]])[0]
    assert prop["weights"]["category"]["whisky"] > 0 > prop["weights"]["category"]["sake"]
    assert abs(prop["weights"]["category"]["whisky"]) <= 0.2, "한 번에 ±0.2 까지만 움직인다"
    assert prop["basis"]["groups"]["category"]["whisky"]["n"] == 3
    assert b.sql("select status from drink_strategy_proposals where id = $1", [first["proposal_id"]])[0]["status"] == "superseded"

    # 반영 전: 같은 점수의 사케·위스키 후보는 동점 → 반영 후: 위스키가 앞선다(다음 편성 순서가 바뀐다 = 순환)
    for cats, t in [(("sake",), "가 사케 새 후보"), (("whisky",), "나 위스키 새 후보")]:
        x = rpc("drinks_create_topic", {"title": t, "question": t + os.urandom(3).hex(), "categories": list(cats), "lane": "evergreen"})
        rpc("drinks_triage", {"topic_id": x["topic_id"], "expected_version": version(b, "drink_topics", x["topic_id"]), "scores": SCORES})
    names = lambda: [t["title"] for t in rpc("drinks_strategy_rank", {})["topics"] if "새 후보" in t["title"]]  # noqa: E731
    assert names() == ["가 사케 새 후보", "나 위스키 새 후보"]
    acc_res = rpc("drinks_strategy_action", {"proposal_id": second["proposal_id"], "action": "accept", "reason": "위스키 반응이 좋다"})
    assert acc_res["label"] == "strategy-v1"
    assert names() == ["나 위스키 새 후보", "가 사케 새 후보"]


def test_timeout_after_publish_is_unknown_never_republished_then_reconciled(env):
    rpc, b, fake = env["rpc"], env["b"], env["fake"]
    acc = fake_account(env)
    rid = schedule(env, render_and_approve(env, approved_carousel(env, title="타임아웃 시험")), acc,
                   caption="쌀을 깎아요 #사케", publish_at=NOW() - timedelta(minutes=1))
    fake.inject("publish", "timeout_after")   # 게시는 됐는데 응답을 잃는다
    rpc_calls = []
    out = drinks_publish.run(lambda fn, p: (rpc_calls.append(fn), rpc(fn, p))[1], env["storage"], env["providers"],
                             worker_id="e2e", wait_sec=1, poll_sec=0)
    assert [p["status"] for p in out["published"]] == ["unknown"]
    # 같은 실행의 대조 단계가 컨테이너를 조회해 게시됐음을 확인하고 정정한다(다시 게시하지 않았다)
    assert [r["status"] for r in out["reconciled"]] == ["published"]
    row = req_row(b, rid)
    assert row["status"] == "published" and row["reconcile_state"] == "reconciled"
    media = json.loads(pathlib.Path(fake.path).read_text(encoding="utf-8"))["media"]
    assert sum(1 for m in media.values() if m["caption"] == "쌀을 깎아요 #사케") == 1, "인스타에 한 번만 올라갔다"
    assert rpc_calls.count("drinks_claim_publication") == 2, "unknown 뒤에도 다시 집지 않았다(두 번째 점유는 빈손)"


def test_timeout_before_publish_reconciles_to_failed_then_retry(env):
    rpc, b, fake = env["rpc"], env["b"], env["fake"]
    acc = fake_account(env)
    rid = schedule(env, render_and_approve(env, approved_carousel(env, title="미게시 시험")), acc,
                   caption="양조 알코올을 넣지 않아요", publish_at=NOW() - timedelta(minutes=1))
    fake.inject("publish", "timeout_before")
    out = publish_run(env)
    assert [r["status"] for r in out["reconciled"]] == ["failed"], "컨테이너가 게시되지 않았음을 확인 → 확정 실패"
    rpc("drinks_publication_action", {"request_id": rid, "action": "retry", "expected_version": version(b, "drink_publication_requests", rid)})
    assert [p["status"] for p in publish_run(env)["published"]] == ["published"]


def test_late_schedule_pauses_and_caption_without_source_pauses(env):
    rpc, b = env["rpc"], env["b"]
    acc = fake_account(env)
    rid = schedule(env, render_and_approve(env, approved_carousel(env, title="늦은 예약")), acc, caption="정미율 이야기",
                   publish_at=NOW() - timedelta(minutes=1))
    b.sql("alter table drink_publication_requests disable trigger drink_publications_guard")
    b.sql("update drink_publication_requests set publish_at = now() - interval '3 hours' where id = $1", [rid])
    # 시각만 바꾸면 승인 지문 검사가 먼저 잡는다(digest_changed — 그것도 의도한 동작). 늦음만 보려고 지문도 맞춘다.
    b.sql("update drink_publication_requests r set approval_digest = drinks_pub_digest(r) where id = $1", [rid])
    b.sql("alter table drink_publication_requests enable trigger drink_publications_guard")
    publish_run(env)
    row = req_row(b, rid)
    assert (row["status"], row["pause_code"]) == ("paused", "late"), "2시간 넘게 늦으면 자동으로 늦은 게시를 하지 않는다"

    rid2 = schedule(env, render_and_approve(env, approved_carousel(env, title="캡션 시험")), acc,
                    caption="물을 세 티스푼 넣어 보세요 #위스키", publish_at=NOW() - timedelta(minutes=1))
    out = publish_run(env)
    assert [p["status"] for p in out["published"]] == ["paused"]
    row = req_row(b, rid2)
    assert row["pause_code"] == "caption_check" and "원문" in row["pause_reason"]
    assert b.sql("select provider_container_ids from drink_publication_attempts where request_id = $1", [rid2])[0][
        "provider_container_ids"] == [], "캡션이 막히면 인스타에 아무것도 만들지 않는다"
