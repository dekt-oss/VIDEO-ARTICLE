"""5단계 게시·성과 루프 0원 리허설 — 밈 1편·설명형 1편·카드 1편이 게시 요청까지 만들어져 가짜 인스타에 올라가고 성과 행이 생기는지 본다.

    python -m scripts.publish_loop_rehearsal          # 산출물: docs/preview-<날짜>/publish-loop/report.json (gitignore)

진짜 SQL 함수(메모리 PGlite, 0050~0068) + 진짜 워커(drinks_produce·drinks_meme·drinks_publish·drinks_metrics·drinks_strategy) + 가짜 공급자
(FakeInstagram 상태 파일·FakeAdapter 클립). 돈·네트워크·공급자 호출·공개 게시 0 — 소켓과 실제 공급자 함수에 줄을 걸어 0회를 숫자로 남긴다.
docs/deviation-drinks-stage5-publish-loop.md

★ 화면은 시험 영상·시험 글이다. 합격은 "경로가 끝까지 돈다"일 뿐이고 그림·글 품질은 본 적 없다.
★ 운영 DB 에 닿지 않는다. web 에서 npm ci 가 돼 있어야 한다(@electric-sql/pglite).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from engine import drinks_meme as dm
from engine import drinks_metrics, drinks_publish, drinks_strategy
from engine import drinks_produce as dp
from engine import drinks_explainer_queue as q
from engine.drinks_collect import DbError
from engine.providers.instagram import FakeInstagram
from engine.util import today_local
from scripts import explainer_queue_rehearsal as qr
from scripts import meme_rehearsal as mr

ROOT = Path(__file__).resolve().parents[1]
SCORES = {"relevance": 4, "utility": 4, "curiosity": 3, "fit_video": 1, "fit_carousel": 4, "timeliness": 2}
QUOTE1 = "大吟醸酒は精米歩合50%以下の白米を使う"
QUOTE2 = "醸造アルコールを加えない"
CARD_CK = {"page_order_ok": True, "no_text_overflow": True, "claims_match_evidence": True, "source_page_ok": True}
AI_LABEL = "AI 생성 영상"
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def _ver(db: qr.PgRpc, table: str, id_: str) -> int:
    return db.sql(f"select version from {table} where id = $1", [id_])[0]["version"]


def _pub(db: qr.PgRpc, rid: str) -> dict[str, Any]:
    return db.sql("select * from drink_publication_requests where id = $1", [rid])[0]


# ─────────────────────────────────────────────────────────────
# 계정 (가짜)
# ─────────────────────────────────────────────────────────────

def fake_account(db: qr.PgRpc, fake: FakeInstagram, providers: Any, ext: str = "fake_sooljjerigo") -> str:
    fake.add_account(ext, "sooljjerigo_test")
    a = db("drinks_register_account", {"external_account_id": ext, "display_name": "술째리고(시험)", "account_type": "test",
                                        "connection": "fake", "capabilities": {"post_types": ["carousel", "reel"]}})
    drinks_publish.verify_accounts(db, providers)
    db("drinks_account_action", {"account_id": a["account_id"], "action": "enable_publish", "expected_version": _ver(db, "drink_social_accounts", a["account_id"])})
    return a["account_id"]


# ─────────────────────────────────────────────────────────────
# 카드 1편 — 근거 → 카드 제작안 → 진짜 PNG 렌더 → 검수 승인
# ─────────────────────────────────────────────────────────────

def approved_card_review(db: qr.PgRpc, storage: dp.Storage) -> dict[str, Any]:
    q_text = f"다이긴조는 왜 비쌀까 {uuid.uuid4().hex[:4]}"
    t = db("drinks_create_topic", {"title": "다이긴조는 왜 비쌀까", "question": q_text, "categories": ["sake"], "lane": "evergreen"})
    tid = t["topic_id"]
    db("drinks_triage", {"topic_id": tid, "expected_version": _ver(db, "drink_topics", tid), "scores": SCORES})
    db("drinks_topic_action", {"topic_id": tid, "expected_version": _ver(db, "drink_topics", tid), "action": "start_research"})
    url = f"https://www.nta.go.jp/sake/{uuid.uuid4().hex[:8]}"
    sid = db("drinks_add_source", {"topic_id": tid, "source": {"canonical_url": url, "body_text": f"{QUOTE1}。{QUOTE2}。", "rights_status": "quote_ok", "title": "大吟醸"}})["snapshot_id"]
    claims = [{"claim_id": "c1", "text": "정미율 50% 이하", "claim_type": "process", "support_review": "supported", "source_refs": [{"snapshot_id": sid, "original_quote": QUOTE1}]},
              {"claim_id": "c2", "text": "양조 알코올 무첨가", "claim_type": "product_fact", "support_review": "supported", "source_refs": [{"snapshot_id": sid, "original_quote": QUOTE2}]}]
    brief = {"audience_question": "왜 비쌀까?", "core_takeaway": "쌀을 반 이상 깎는다", "selected_claim_ids": ["c1", "c2"], "proposed_formats": ["carousel"], "required_claims": {"carousel": ["c1", "c2"]}}
    sv = db("drinks_save_review", {"topic_id": tid, "expected_topic_version": _ver(db, "drink_topics", tid), "scores": SCORES, "brief": brief, "evidence_pack": {"claims": claims}})
    for act in ("submit", "approve"):
        db("drinks_review_action", {"review_id": sv["review_id"], "action": act, "expected_version": _ver(db, "drink_topic_reviews", sv["review_id"])})
    rv = db.sql("select approved_hash from drink_topic_reviews where id = $1", [sv["review_id"]])[0]
    db("drinks_select", {"topic_id": tid, "expected_version": _ver(db, "drink_topics", tid), "review_id": sv["review_id"], "review_input_hash": rv["approved_hash"],
                         "formats": ["carousel"], "editorial_week": "2026-11-02"})
    pl = db("drinks_save_plan", {"topic_id": tid, "format": "carousel", "topic_review_id": sv["review_id"], "plan_json": {"pages": [
        {"role": "cover", "heading": "다이긴조, 왜 비쌀까?"},
        {"role": "explain", "heading": "쌀을 반 이상 깎아요", "body": "정미율 50% 이하", "claim_ids": ["c1"]},
        {"role": "checklist", "heading": "라벨 체크", "body": "양조 알코올 무첨가", "claim_ids": ["c2"]}]}})
    for act in ("submit", "approve"):
        db("drinks_plan_action", {"revision_id": pl["revision_id"], "action": act, "expected_version": _ver(db, "drink_plan_revisions", pl["revision_id"])})
    db("drinks_request_render", {"plan_revision_id": pl["revision_id"]})
    res = dp.run_queue(db, storage, worker_id="rehearsal", max_jobs=1)
    if not res or res[0].get("status") != "succeeded":
        raise RuntimeError(f"카드 렌더 실패: {res}")
    rev = db.sql("select id, version from drink_output_reviews where manifest_id = $1", [res[0]["manifest_id"]])[0]
    db("drinks_output_review_action", {"review_id": rev["id"], "expected_version": rev["version"], "action": "approve", "checklist": CARD_CK})
    return {"topic_id": tid, "plan_id": pl["revision_id"], "review_id": rev["id"], "pages": 3}


# ─────────────────────────────────────────────────────────────
# 설명형 1편 — 지시서 → (가짜) 구매 → 선택 → 조립 → 검수 → 게시 대기(ready_to_publish)
# ─────────────────────────────────────────────────────────────

def approved_explainer_review(db: qr.PgRpc, storage: dp.Storage, out_root: Path) -> dict[str, Any]:
    adapter = qr.FakeAdapter(out_root / "fake-clips")
    deps = q.Deps(adapter=adapter, tts_fn=qr.fake_tts())
    plan = qr.seed_plan(db)
    db("drinks_explainer_request_plan", {"plan_revision_id": plan})
    qr.run_one(db, storage, deps)
    st = qr.status(db, plan)
    approval = qr.open_approval(db, plan, st["episode"]["directive"]["estimate"]["suggested_cap_usd"])
    qr.buy_all(db, storage, plan, approval, deps)
    db("drinks_explainer_request_assemble", {"plan_revision_id": plan})
    rendered = qr.run_one(db, storage, deps)
    job = db.sql("select status, error_code, error_message, result_manifest_id from drink_production_jobs where id = $1", [rendered["job_id"]])[0]
    if job["status"] != "succeeded":
        raise RuntimeError(f"설명형 조립 실패: {job['error_code']}: {job['error_message']}")
    db("drinks_explainer_review", {"plan_revision_id": plan, "stage": "process", "outcome": "pass", "checks": qr.PROCESS_CHECKS})
    db("drinks_explainer_review", {"plan_revision_id": plan, "stage": "quality", "outcome": "pass", "checks": qr.QUALITY_CHECKS})
    review = db.sql("select * from drink_output_reviews where manifest_id = $1", [job["result_manifest_id"]])[0]
    db("drinks_output_review_action", {"review_id": review["id"], "expected_version": review["version"], "action": "approve", "checklist": qr.OUTPUT_CHECKS})
    return {"plan_id": plan, "review_id": review["id"], "state": qr.state_of(db, plan), "provider_calls": len(adapter.calls)}


# ─────────────────────────────────────────────────────────────
# 밈 1편(+ 박자 맞춤 1편) — [쓰자] 카드 → 제작안 → 승인 → 진짜 렌더 → 게시 대기 / 앱 부착 대기
# ─────────────────────────────────────────────────────────────

def precise_card(db: qr.PgRpc, name: str, sync: Optional[str] = None) -> str:
    cid = db.sql("insert into drink_ig_cards (merge_key, kind, name, first_seen_on, decision, decided_at) values ($1, 'structure_hook', $2, current_date, 'use', now()) returning id",
                 [f"k-{uuid.uuid4().hex[:8]}", name])[0]["id"]
    for f in ("beat_count", "cut_lengths", "twist_at"):
        db.sql("insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, $2, '3', 'operator', 'high')", [cid, f])
    if sync:
        db.sql("insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) values ($1, 'music_sync', $2, 'operator', 'high')", [cid, sync])
    return cid


def rendered_meme(db: qr.PgRpc, storage: dp.Storage, *, fixture_group: str) -> dict[str, Any]:
    fx = next(f for f in mr.fixtures() if f["group"] == fixture_group)
    card = precise_card(db, fx["card"]["name"], sync="박자에 맞춰야 함(필수)" if fixture_group == "sync_required" else None)
    saved = db("drinks_meme_save_draft", {"card_id": card, "spec": fx["spec"]})
    if saved["blockers"]:
        raise RuntimeError(f"밈 제작안이 막혔습니다: {saved['blockers']}")
    db("drinks_meme_draft_action", {"draft_id": saved["draft_id"], "expected_version": saved["version"], "action": "approve"})
    res = dm.run_queue(db, storage, worker_id="rehearsal", kind="render", max_jobs=1)
    if not res or res[0].get("status") not in ("publish_waiting", "manual_audio"):
        raise RuntimeError(f"밈 렌더 실패: {res}")
    return {"draft_id": saved["draft_id"], "status": res[0]["status"], "card_id": card}


# ─────────────────────────────────────────────────────────────
# 발행안 → 승인 → 예약 → 가짜 게시 → 성과 → 전략
# ─────────────────────────────────────────────────────────────

def schedule(db: qr.PgRpc, rid: str) -> None:
    db("drinks_publication_action", {"request_id": rid, "action": "submit", "expected_version": _ver(db, "drink_publication_requests", rid)})
    shown = db("drinks_publication_state", {"request_id": rid})
    db("drinks_publication_action", {"request_id": rid, "action": "approve", "expected_digest": shown["approval_digest"], "expected_version": shown["version"]})
    db("drinks_publication_action", {"request_id": rid, "action": "schedule", "expected_version": _ver(db, "drink_publication_requests", rid)})


def age(db: qr.PgRpc, rid: str, hours: float) -> None:
    """시험 전용 시간 되돌리기: 게시 시각을 hours 시간 전으로(불변 가드를 잠깐 끈다). 운영 경로에는 이런 문이 없다."""
    db.sql("alter table drink_publication_requests disable trigger drink_publications_guard")
    db.sql("update drink_publication_requests set published_at = now() - make_interval(secs => $2) where id = $1", [rid, int(hours * 3600)])
    db.sql("alter table drink_publication_requests enable trigger drink_publications_guard")


def expect_fail(fn: Any, code: str) -> dict[str, Any]:
    try:
        fn()
    except DbError as exc:
        return {"code": exc.code, "ok": exc.code == code}
    return {"code": None, "ok": False}


def run(out_root: Path) -> dict[str, Any]:
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    storage = dp.Storage("local", str(out_root / "storage"))
    fake = FakeInstagram(str(out_root / "fake_ig.json"))

    def providers(acc: dict[str, Any]) -> Any:
        if acc.get("connection") != "fake":
            raise AssertionError("실제 공급자를 부르려 했습니다")
        return fake

    db = qr.PgRpc()
    report: dict[str, Any] = {"cost_usd": 0, "public_posts": 0}
    try:
        with qr.Wire() as wire:
            acc = fake_account(db, fake, providers)
            card = approved_card_review(db, storage)
            explainer = approved_explainer_review(db, storage, out_root)
            meme = rendered_meme(db, storage, fixture_group="sync_free")
            synced = rendered_meme(db, storage, fixture_group="sync_required")
            report.update(card=card, explainer=explainer, meme=meme, meme_sync_required=synced)

            board = db("drinks_publish_board", {})
            report["board_ready_memes"] = [m["draft_id"] for m in board.get("ready_memes") or []]
            report["board_ready_formats"] = sorted({o.get("content_format") for o in board.get("ready_outputs") or []})

            # 막혀야 하는 것 셋: 설명형 캡션에 AI 표기 없음 · 박자 맞춤 밈 발행안 · 게시 대기 아닌 제작안
            blocked = {
                "explainer_without_ai_label": expect_fail(lambda: db("drinks_create_publication", {"output_review_id": explainer["review_id"], "account_id": acc, "caption": "위스키 이야기 #술째리고",
                                                                                                    "publish_at": (NOW() - timedelta(minutes=1)).isoformat()}), "ai_label_missing"),
                "meme_sync_required": expect_fail(lambda: db("drinks_create_meme_publication", {"draft_id": synced["draft_id"], "account_id": acc}), "invalid_state"),
            }
            when = (NOW() - timedelta(minutes=1)).isoformat()
            r_card = db("drinks_create_publication", {"output_review_id": card["review_id"], "account_id": acc, "caption": "원문 근거만 담은 카드예요 #술째리고", "publish_at": when})
            r_expl = db("drinks_create_publication", {"output_review_id": explainer["review_id"], "account_id": acc, "caption": f"물 몇 방울 이야기\n{AI_LABEL}\n#위스키 #술째리고", "publish_at": when})
            r_meme = db("drinks_create_meme_publication", {"draft_id": meme["draft_id"], "account_id": acc, "publish_at": when})
            blocked["meme_duplicate"] = expect_fail(lambda: db("drinks_create_meme_publication", {"draft_id": meme["draft_id"], "account_id": acc, "publish_at": when}), "duplicate_publication")
            # 밈 캡션은 제작안의 캡션이다(사람이 승인한 글). 숫자·권고가 들어간 캡션은 작성 때 막힌다
            report["meme_caption_from_spec"] = r_meme["caption"]
            report["created_formats"] = {r_card["request_id"]: r_card["content_format"], r_expl["request_id"]: r_expl["content_format"], r_meme["request_id"]: r_meme["content_format"]}
            for r in (r_card, r_expl, r_meme):
                schedule(db, r["request_id"])
            # 예약 뒤 제작안을 되돌리면 게시 직전 재확인이 막는다 — 지문이 바뀌어서. 여기서는 확인만 하고(되돌리지 않음) 게시로 간다.
            report["blocks_before_publish"] = {r["request_id"]: db("drinks_publication_state", {"request_id": r["request_id"]})["block"] for r in (r_card, r_expl, r_meme)}

            out = drinks_publish.run(db, storage, providers, worker_id="rehearsal", wait_sec=2, poll_sec=0)
            report["publish_run"] = {p["request_id"]: p.get("status") for p in out["published"]}
            rows = {rid: _pub(db, rid) for rid in (r_card["request_id"], r_expl["request_id"], r_meme["request_id"])}
            report["published_rows"] = {rid: {"status": r["status"], "format": r["content_format"], "post_type": r["post_type"], "external_post_id": r["external_post_id"]} for rid, r in rows.items()}
            report["meme_draft_after"] = db.sql("select status, external_url from drink_meme_drafts where id = $1", [meme["draft_id"]])[0]
            st = json.loads(Path(fake.path).read_text(encoding="utf-8"))
            report["fake_ig"] = {"media": len(st["media"]), "kinds": sorted(c["kind"] for c in st["containers"].values()),
                                 "file_urls": all(str(c.get("url") or "file:///").startswith("file:///") for c in st["containers"].values())}
            report["second_run_publishes"] = len(drinks_publish.run(db, storage, providers, worker_id="rehearsal", wait_sec=2, poll_sec=0)["published"])

            # 성과: 25시간 → 24h 칸(형식별) → 73시간 → 72h 칸 → 전략 제안(형식 묶음)
            for rid in rows:
                age(db, rid, 25)
            got = drinks_metrics.collect(db, providers)
            report["metrics_24h"] = sorted((g["content_format"], g["bucket"]) for g in got)
            for rid in rows:
                age(db, rid, 73)
            got72 = drinks_metrics.collect(db, providers)
            report["metrics_72h"] = sorted((g["content_format"], g["bucket"]) for g in got72)
            report["snapshot_rows"] = db.sql("select r.content_format, s.age_bucket, s.fetch_status from drink_post_metric_snapshots s join drink_publication_requests r on r.id = s.request_id order by 1, 2")
            prop = drinks_strategy.run(db)
            basis = db.sql("select basis from drink_strategy_proposals where id = $1", [prop["proposal_id"]])[0]["basis"]
            report["strategy"] = {"sufficient": prop["sufficient"], "summary": prop["summary_ko"], "format_groups": basis["groups"].get("format"), "sample_total": basis["sample_total"]}
            analytics = db("drinks_analytics_board", {})
            report["analytics_format_counts"] = analytics.get("format_counts")
            report["analytics_post_formats"] = sorted(p.get("format") for p in analytics["posts"])
            report["blocked"] = blocked
            report["tripwire_hits"] = wire.hits
    finally:
        db.close()

    pub_statuses = [v["status"] for v in report["published_rows"].values()]
    fmts = sorted(v["format"] for v in report["published_rows"].values())
    checks = {
        "세 형식 발행안 생성(card·explainer·meme)": sorted(report["created_formats"].values()) == ["card", "explainer", "meme"],
        "밈 캡션은 제작안 캡션": report["meme_caption_from_spec"] == next(f for f in mr.fixtures() if f["group"] == "sync_free")["spec"]["caption"],
        "게시 직전 재확인 통과": all(b is None for b in report["blocks_before_publish"].values()),
        "세 편 전부 가짜 게시 성공": pub_statuses == ["published"] * 3 and fmts == ["card", "explainer", "meme"],
        "가짜 인스타에 세 게시물(캐러셀 1 + 릴스 2)": report["fake_ig"]["media"] == 3 and report["fake_ig"]["kinds"].count("reel") == 2 and report["fake_ig"]["file_urls"],
        "게시된 요청은 다시 집히지 않음": report["second_run_publishes"] == 0,
        "밈 제작안 → published": report["meme_draft_after"]["status"] == "published",
        "박자 맞춤 밈은 앱 부착 대기 + 발행안 거부": report["meme_sync_required"]["status"] == "manual_audio" and report["blocked"]["meme_sync_required"]["ok"],
        "설명형 'AI 생성 영상' 없으면 발행안 거부": report["blocked"]["explainer_without_ai_label"]["ok"],
        "같은 밈 발행안 중복 거부": report["blocked"]["meme_duplicate"]["ok"],
        "게시 대기 밈이 발행 화면 목록에": report["meme"]["draft_id"] in report["board_ready_memes"] and report["meme_sync_required"]["draft_id"] not in report["board_ready_memes"],
        "성과 24h 칸 형식별 3행": report["metrics_24h"] == [("card", "24h"), ("explainer", "24h"), ("meme", "24h")],
        "성과 72h 칸 형식별 3행": report["metrics_72h"] == [("card", "72h"), ("explainer", "72h"), ("meme", "72h")],
        "전략 제안이 형식 묶음을 본다(표본 부족은 정상)": bool(report["strategy"]["format_groups"]) and set(report["strategy"]["format_groups"]) == {"card", "explainer", "meme"}
            and report["strategy"]["sufficient"] is False,
        "성과 화면 형식별 편수": report["analytics_format_counts"] == {"card": 1, "explainer": 1, "meme": 1},
        "유료·네트워크·실제 공급자 호출 0": not report["tripwire_hits"],
    }
    report["checks"] = checks
    report["passed"] = all(checks.values())
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="5단계 게시·성과 루프 0원 리허설(가짜 공급자, 공개 게시 없음)")
    ap.add_argument("--out", default=None, help="산출물 폴더(기본 docs/preview-<오늘>/publish-loop)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out_root = Path(args.out).resolve() if args.out else ROOT / "docs" / f"preview-{today_local().isoformat()}" / "publish-loop"
    report = run(out_root)
    with open(out_root / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    shutil.rmtree(out_root / "storage", ignore_errors=True)
    shutil.rmtree(out_root / "fake-clips", ignore_errors=True)
    print("발행안:", report["created_formats"])
    print("게시 결과:", report["published_rows"])
    print("성과 24h:", report["metrics_24h"], "/ 72h:", report["metrics_72h"])
    print("전략:", report["strategy"]["summary"])
    for k, v in report["checks"].items():
        print(("통과 " if v else "실패 ") + k)
    print(f"비용 $0 · 공개 게시 0건 · 줄 걸림 {len(report['tripwire_hits'])}회 · 산출물 {out_root}")
    print("★ 화면·글은 시험용이다. 합격은 '경로가 끝까지 돈다'일 뿐이다.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
