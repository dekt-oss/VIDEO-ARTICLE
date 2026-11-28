"""Local side effects only: PGlite + mocked model responses."""
import json
from dataclasses import replace

import httpx
import pytest

from engine import drinks_develop as develop
from engine.drinks_collect import DbError
from test_drinks_loop_e2e import Bridge, SCORES, version
from test_jjeri_evidence import mock_episode


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.setenv("DRINKS_BRIDGE_JJERI", "1")
    bridge = Bridge()
    try:
        yield bridge
    finally:
        bridge.close()


def prepared_topic(b, *, select=True, anatomy=None):
    rpc = b.rpc
    episode, evidence = anatomy or mock_episode()
    quote = " ".join(c["source_refs"][0]["original_quote"] for c in evidence["claims"]) if anatomy else evidence["claims"][0]["source_refs"][0]["original_quote"]
    topic = rpc("drinks_create_topic", {"title": episode["topic"], "question": "어떻게 달라질까?",
                                       "categories": ["whisky"], "lane": "evergreen"})["topic_id"]
    scores = {**SCORES, "fit_video": 4}
    rpc("drinks_triage", {"topic_id": topic, "expected_version": version(b, "drink_topics", topic), "scores": scores})
    rpc("drinks_topic_action", {"topic_id": topic, "expected_version": version(b, "drink_topics", topic),
                                "action": "start_research"})
    snapshot = rpc("drinks_add_source", {"topic_id": topic, "source": {
        "canonical_url": "https://example.org/jjeri-generation", "title": "Verified source",
        "body_text": quote, "rights_status": "quote_ok"}})["snapshot_id"]
    review_payload = {"topic_id": topic, "scores": scores,
        "brief": {"audience_question": "어떻게 달라질까?", "core_takeaway": "캐스크 비교",
                  "selected_claim_ids": ["c1"], "proposed_formats": ["video"], "required_claims": {"video": ["c1"]}},
        "evidence_pack": {"claims": [{"claim_id": "c1", "text": "모의 실험 결과", "claim_type": "process",
                                    "support_review": "supported", "source_refs": [
                                        {"snapshot_id": snapshot, "original_quote": quote}]}]}}
    if anatomy:
        review_payload["brief"].update(selected_claim_ids=["c1","c2","c3"], required_claims={"video":["c1","c2","c3"]})
        review_payload["evidence_pack"]["claims"] = [
            {**c, "text": "로컬 원문 대조 자료", "source_refs":[{"snapshot_id":snapshot,"original_quote":c["source_refs"][0]["original_quote"]}]}
            for c in evidence["claims"] if c["claim_id"] in ("c1","c2","c3")
        ]
    review, digest = approve_review(b, review_payload)
    budget = rpc("drinks_open_develop_budget", {"stage": "째리 로컬 모의", "cap_usd": 2, "days": 7,
                                               "approver_words": "로컬 모의 호출 원장 시험"})["budget_id"]
    form = {"topic_id": topic, "review_id": review, "review_hash": digest, "lesson": episode.get("episode"),
            "budget_id": budget, "max_usd": 0.5, "spend_confirmed": True}
    if anatomy:
        form.update(format="jjeri_anatomy")
    if select:
        schedule_video(b, form)
    return form, episode, quote, review_payload


def schedule_video(b, form):
    topic = form["topic_id"]
    b.rpc("drinks_select", {"topic_id": topic, "expected_version": version(b, "drink_topics", topic),
        "review_id": form["review_id"], "review_input_hash": form["review_hash"], "formats": ["video"],
        "editorial_week": "2026-11-23"})


def approve_review(b, review_payload):
    review = save_review(b, review_payload)
    activate_review(b, review)
    return review, b.sql("select approved_hash from drink_topic_reviews where id = $1", [review])[0]["approved_hash"]


def save_review(b, payload):
    return b.rpc("drinks_save_review", {**payload,
        "expected_topic_version": version(b, "drink_topics", payload["topic_id"])})["review_id"]


def activate_review(b, review):
    for action in ("submit", "approve"):
        b.rpc("drinks_review_action", {"review_id": review, "action": action,
              "expected_version": version(b, "drink_topic_reviews", review)})


def worker(b, respond, *, anatomy=False):
    return develop.run_queue(b.rpc, develop.Deps(jjeri_respond=respond, jjeri_anatomy_enabled=anatomy), worker_id="mock-jjeri", max_jobs=1)[0]


def test_shared_ledger_keeps_meme_ordinary_and_orphan_owner_rules(factory):
    b = factory
    form, _, _, _ = prepared_topic(b)
    card = b.sql("insert into drink_ig_cards (merge_key, kind, name, first_seen_on, decision, decided_at) "
                 "values ('hold-fixture', 'structure_hook', 'Meme hold', current_date, 'use', now()) returning id")[0]["id"]
    b.sql("insert into drink_ig_card_fields (card_id, field, value, evidence, confidence) "
          "select $1, field, '3', 'operator', 'high' from unnest(array['beat_count','cut_lengths','twist_at']) as field", [card])
    b.rpc("drinks_meme_request_text", {"card_id": card, "frame": "top_text", "budget_id": form["budget_id"]})
    meme = b.rpc("drinks_meme_claim", {"kind": "text", "worker_id": "mock"})["job"]
    hold = b.rpc("drinks_meme_hold", {"draft_id": meme["draft_id"], "lease_token": meme["lease_token"],
                                    "est_usd": 0.01, "model": "mock"})
    b.rpc("drinks_develop_settle", {"hold_id": hold["hold_id"], "outcome": "settled", "actual_usd": 0.004})
    row = b.sql("select request_id, meme_draft_id from drink_develop_holds where id = $1", [hold["hold_id"]])[0]
    assert row == {"request_id": None, "meme_draft_id": meme["draft_id"]}
    for request_id, error in [(None, "check constraint"), ("00000000-0000-0000-0000-000000000001", "foreign key")]:
        with pytest.raises(RuntimeError, match=error):
            b.sql("insert into drink_develop_holds (request_id, budget_id, model, est_usd) values ($1,$2,'mock',0.01)",
                  [request_id, form["budget_id"]])
    ordinary = b.rpc("drinks_request_develop", {"topic_id": form["topic_id"], "kind": "plan", "budget_id": form["budget_id"],
                                               "review_id": form["review_id"]})
    job = b.rpc("drinks_start_develop", {"worker_id": "ordinary"})["job"]
    assert job["request_id"] == ordinary["request_id"]
    assert b.rpc("drinks_develop_hold", {"request_id": job["request_id"], "lease_token": job["lease_token"],
                                       "model": "mock", "est_usd": 0.01})["hold_id"]


def test_ordinary_studio_can_prepare_and_save_evidence_while_jjeri_is_queued(factory):
    b = factory
    form, _, _, review = prepared_topic(b)
    q = b.rpc("drinks_request_jjeri_episode", form)["request_id"]
    next_review = save_review(b, review)
    assert next_review != form["review_id"]
    prepared = b.rpc("drinks_studio_prepare", {"topic_id": form["topic_id"], "format_intent": "explainer"})
    assert prepared["action"] not in ("already_running", "stopped")
    state = b.rpc("drinks_studio_status", {"topic_id": form["topic_id"]})
    assert state["active"] is None or state["active"]["request_id"] != q
    assert b.rpc("drinks_jjeri_generation_status", {"topic_id": form["topic_id"]})["request"]["request_id"] == q


def test_studio_recovery_uses_last_ordinary_failure_even_with_newer_jjeri(factory):
    b = factory
    form, _, _, _ = prepared_topic(b)
    topic = form["topic_id"]
    ordinary = b.rpc("drinks_request_develop", {"topic_id": topic, "kind": "evidence", "budget_id": form["budget_id"]})
    job = b.rpc("drinks_start_develop", {"worker_id": "ordinary"})["job"]
    b.rpc("drinks_finish_develop", {"request_id": job["request_id"], "lease_token": job["lease_token"],
                                    "outcome": "failed", "error_code": "worker_error"})
    q = b.rpc("drinks_request_jjeri_episode", form)["request_id"]
    b.rpc("drinks_cancel_develop", {"request_id": q})
    b.rpc("drinks_review_action", {"review_id": form["review_id"], "action": "revoke",
          "expected_version": version(b, "drink_topic_reviews", form["review_id"]), "reason": "mock"})
    recovered = b.rpc("drinks_studio_recover_all", {})["recovered"]
    assert [item["recovery_of"] for item in recovered if "recovery_of" in item] == [ordinary["request_id"]]
    assert b.rpc("drinks_studio_status", {"topic_id": topic})["active"]["kind"] == "evidence"


def test_jjeri_preview_then_approve_and_render_via_existing_version_contract(factory):
    b = factory
    form, episode, quote, _ = prepared_topic(b, select=False)
    status = b.rpc("drinks_jjeri_generation_status", {"topic_id": form["topic_id"]})
    assert status["current_review"]["id"] == form["review_id"] and not status["can_request"]
    with pytest.raises(DbError) as err:
        b.rpc("drinks_request_jjeri_episode", form)
    assert err.value.code == "format_not_selected"
    schedule_video(b, form)
    with pytest.raises(DbError):
        b.rpc("drinks_request_jjeri_episode", {**form, "spend_confirmed": False})
    created = b.rpc("drinks_request_jjeri_episode", form)
    q = created["request_id"]
    assert created["status"] == "queued"
    assert b.rpc("drinks_request_jjeri_episode", form)["request_id"] == q
    assert b.rpc("drinks_start_develop", {"worker_id": "old"})["job"] is None
    assert b.rpc("drinks_studio_status", {"topic_id": form["topic_id"]})["active"] is None
    assert b.rpc("drinks_develop_status", {"topic_id": form["topic_id"]})["requests"] == []
    with pytest.raises(DbError):
        b.rpc("drinks_approve_jjeri_episode", {"request_id": q, "review_confirmed": True})
    calls = []

    def respond(_, body):
        data = json.loads(body)
        assert data["claims"][0]["quotes"] == [quote]
        assert data["required_claim_ids"] == ["c1"]
        calls.append(data)
        if len(calls) == 2:
            lease = b.sql("select lease_token from drink_develop_requests where id=$1", [q])[0]["lease_token"]
            with pytest.raises(DbError) as err:
                b.rpc("drinks_develop_hold", {"request_id": q, "lease_token": lease,
                    "est_usd": 0.0001, "model": "mock", "note": "third call"})
            assert err.value.code == "hold_limit"
        return "bad json" if len(calls) == 1 else json.dumps(episode)

    done = worker(b, respond)
    assert done["status"] == "succeeded", done
    assert len(calls) == 2 and calls[1]["correction"]["code"] == "json_invalid"
    assert b.sql("select count(*) as n from drink_plan_revisions")[0]["n"] == 0
    assert b.sql("select count(*) as n from drink_develop_holds where request_id=$1 and status='settled'", [q])[0]["n"] == 2
    assert b.rpc("drinks_request_jjeri_episode", form)["request_id"] == q
    state = b.rpc("drinks_jjeri_generation_status", {"topic_id": form["topic_id"]})
    assert state["can_approve"] and state["request"]["result"]["plan"]["jjeri_class"] == episode
    with pytest.raises(DbError):
        b.rpc("drinks_approve_jjeri_episode", {"request_id": q})
    approval = {"request_id": q, "review_confirmed": True}
    result = b.rpc("drinks_approve_jjeri_episode", approval)
    plan_id = result["revision_id"]
    assert b.rpc("drinks_approve_jjeri_episode", approval) == {"revision_id": plan_id, "existing": True}
    assert b.rpc("drinks_request_jjeri_episode", form)["request_id"] == q
    plan = b.sql("select * from drink_plan_revisions where id=$1", [plan_id])[0]
    assert plan["plan_status"] == "approved" and plan["input_hash"] == plan["approved_hash"]
    assert plan["topic_review_id"] == form["review_id"] and plan["plan_json"]["jjeri_class"] == episode
    assert b.rpc("drinks_request_jjeri_render", {"plan_revision_id": plan_id})["renderer"] == "jjeri_class"
    again = {**form, "regenerate_of": q}
    with pytest.raises(DbError):
        b.rpc("drinks_request_jjeri_episode", {**again, "spend_confirmed": False})
    replacement = b.rpc("drinks_request_jjeri_episode", again)["request_id"]
    assert replacement != q and b.rpc("drinks_request_jjeri_episode", again)["request_id"] == replacement
    assert b.sql("select plan_status from drink_plan_revisions where id = $1", [plan_id])[0]["plan_status"] == "approved"
    for name in ("request", "approve", "finish"):
        grants = b.sql("select has_function_privilege('anon', $1, 'EXECUTE') as anon, "
                       "has_function_privilege('authenticated', $1, 'EXECUTE') as authed, "
                       "has_function_privilege('service_role', $1, 'EXECUTE') as operator",
                       [f"drinks_{name}_jjeri_episode(jsonb)"])[0]
        assert grants == {"anon": False, "authed": False, "operator": True}


@pytest.mark.parametrize("change", ["revoked", "superseded"])
def test_jjeri_cannot_finish_or_retry_on_stale_snapshot(factory, change):
    b = factory
    form, episode, _, payload = prepared_topic(b)
    replacement = None
    if change == "superseded":
        replacement = save_review(b, {**payload, "brief": {**payload["brief"], "core_takeaway": "새 원문 대조"}})
    q = b.rpc("drinks_request_jjeri_episode", form)["request_id"]
    calls = 0

    def respond(_, __):
        nonlocal calls
        calls += 1
        if change == "revoked":
            b.rpc("drinks_review_action", {"review_id": form["review_id"], "action": "revoke",
                "expected_version": version(b, "drink_topic_reviews", form["review_id"]), "reason": "원문 확인"})
        else:
            activate_review(b, replacement)
        return "bad json" if change == "superseded" else json.dumps(episode)

    done = worker(b, respond)
    assert calls == 1 and done["status"] == "failed", done
    assert done["error_code"] == "jjeri_review_changed"
    assert b.rpc("drinks_jjeri_generation_status", {"topic_id": form["topic_id"]})["can_approve"] is False
    for action, data in [("approve", {"request_id": q, "review_confirmed": True}), ("request", {**form, "retry_of": q})]:
        with pytest.raises(DbError):
            b.rpc(f"drinks_{action}_jjeri_episode", data)
    assert b.sql("select count(*) as n from drink_plan_revisions")[0]["n"] == 0


def test_jjeri_cap_failure_explicit_retry_lease_and_concurrent_plan(factory):
    b = factory
    form, episode, _, _ = prepared_topic(b)
    low = {**form, "max_usd": 0.0001}
    first = b.rpc("drinks_request_jjeri_episode", low)["request_id"]

    def unexpected(*_):
        pytest.fail("model called despite the cap")

    blocked = worker(b, unexpected)
    assert blocked["error_code"] == "jjeri_request_cap_exceeded", blocked
    retry = {**form, "retry_of": first}
    q = b.rpc("drinks_request_jjeri_episode", retry)["request_id"]
    assert q != first and b.rpc("drinks_request_jjeri_episode", retry)["request_id"] == q
    job = b.rpc("drinks_start_develop", {"worker_id": "mock", "allow_jjeri": True})["job"]
    with pytest.raises(DbError):
        b.rpc("drinks_finish_jjeri_episode", {"request_id": q, "lease_token": "ba000000-0000-0000-0000-000000000000"})
    result = develop.process_job(job, b.rpc, develop.Deps(jjeri_respond=lambda *_: json.dumps(episode)))
    assert result["status"] == "succeeded", result
    b.rpc("drinks_save_plan", {"topic_id": form["topic_id"], "topic_review_id": form["review_id"],
                              "format": "video", "plan_json": {"scenes": [{"narration": "캐스크를 비교해요.", "claim_ids": ["c1"]}]}})
    with pytest.raises(DbError) as err:
        b.rpc("drinks_approve_jjeri_episode", {"request_id": q, "review_confirmed": True})
    assert err.value.code == "version_conflict"
    assert b.sql("select count(*) as n from drink_plan_revisions where plan_status='approved'")[0]["n"] == 0


def test_jjeri_provider_transport_is_submitted_at_most_once(monkeypatch):
    from engine import llm

    calls = []

    def timeout(**kwargs):
        calls.append(kwargs)
        raise httpx.ReadTimeout("mock timeout")

    monkeypatch.setattr(llm, "_deepseek_submit", timeout)
    with pytest.raises(httpx.ReadTimeout):
        develop.llm_write_jjeri("mock system", "mock user")
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == develop.config.DRINKS_DEVELOP_PLAN_MAX_TOKENS


@pytest.mark.parametrize(("status_code", "outcome"), [(429, "released"), (503, "settled")])
def test_jjeri_provider_status_does_not_overlap_calls_or_holds(factory, monkeypatch, status_code, outcome):
    from engine import llm

    b = factory
    form, _, _, _ = prepared_topic(b)
    q = b.rpc("drinks_request_jjeri_episode", form)["request_id"]
    calls = []
    client = httpx.Client

    def respond(request):
        calls.append(request)
        return httpx.Response(status_code, json={"error": "mock"})

    def configure_transport(**kwargs):
        return client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(llm.config, "SECRETS", replace(llm.config.SECRETS, deepseek_api_key="mock"))
    monkeypatch.setattr(llm.httpx, "Client", configure_transport)
    result = worker(b, develop.llm_write_jjeri)
    assert result["error_code"] == "jjeri_provider_unavailable"
    assert len(calls) == 1
    holds = b.sql("select status, est_usd, actual_usd from drink_develop_holds where request_id = $1", [q])
    assert len(holds) == 1 and holds[0]["status"] == outcome
    if outcome == "settled":
        assert holds[0]["actual_usd"] == holds[0]["est_usd"]
    else:
        assert holds[0]["actual_usd"] is None
