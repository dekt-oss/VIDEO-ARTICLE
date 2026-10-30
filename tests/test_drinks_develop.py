"""주류 소재 자동 개발 워커(0단계) — 모델·네트워크 호출 0. 모든 모델 호출은 주입한 가짜 함수다.

지키는 것: 원문 인용은 글자 그대로만 통과 · 근거 부족이면 쓰지 않고 멈춤 · 승인된 핵심 주장만으로 대본 · 막히면 한 번만 다시 쓰고 그래도 막히면 저장 안 함
          · 결재가 없으면 모델을 한 번도 안 부름 · 상한은 DB 가 거절 · 손으로 만든 통과 사례는 통과, 사고 났던 사례는 막힘(재생).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import config
from engine import drinks_develop as dd
from engine import drinks_script_check as sc
from engine.drinks_collect import DbError

ROOT = Path(__file__).resolve().parents[1]
GOLD_WHISKY = json.loads((ROOT / "docs" / "drinks-pilot" / "whisky-water-v1.json").read_text(encoding="utf-8"))
GOLD_SAKE = json.loads((ROOT / "docs" / "drinks-pilot" / "gi-sake-v1.json").read_text(encoding="utf-8"))
FIX = ROOT / "tests" / "fixtures" / "drinks_scripts"
SQL = (ROOT / "supabase" / "migrations" / "0060_drinks_develop.sql").read_text(encoding="utf-8")

TOPIC = {"id": "t1", "title": "위스키에 물 한두 방울", "question": "위스키 고수들은 왜 물을 한두 방울 넣을까?", "categories": ["whisky"],
         "status": "researching", "version": 3, "target_subject": "whisky", "angle": None}
# 원문 = 손으로 만든 사례의 인용들을 이어 붙인 글(글자 그대로 들어 있는 인용을 시험하기 위해)
QUOTES = [c["original_quote"] for c in GOLD_WHISKY["claims"] if "…" not in c["original_quote"]]
BODY = " ".join(QUOTES) + " " + ("Additional background sentence about whisky production and maturation in oak casks. " * 3)


# ── 가짜 DB(RPC) ──────────────────────────────────────────────

class FakeRpc:
    """0060 함수의 동작을 흉내 낸다: 결재 남은 금액·요청 1건 상한·호출 횟수·취소. 호출 이름을 순서대로 기록한다."""

    def __init__(self, *, sources=None, cap=1.0, cancel_after=None):
        self.sources = sources if sources is not None else []
        self.cap = cap
        self.held = {}
        self.settled = 0.0
        self.names: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.saved_evidence = None
        self.saved_plan = None
        self.finish = None
        self.added: list[dict] = []
        self.linked: list[str] = []
        self.settles: list[dict] = []
        self.holds = 0
        self.cancel_after = cancel_after
        self.beats = 0

    def __call__(self, fn, p):
        self.names.append(fn)
        self.calls.append((fn, p))
        return getattr(self, fn)(p)

    def drinks_develop_sources(self, p):
        return self.sources

    def drinks_heartbeat_develop(self, p):
        self.beats += 1
        return {"cancel_requested": self.cancel_after is not None and self.beats > self.cancel_after}

    def drinks_develop_hold(self, p):
        committed = sum(self.held.values()) + self.settled
        if self.holds >= config.DRINKS_DEVELOP_MAX_HOLDS_PER_REQUEST:
            raise DbError("hold_limit", "호출 횟수 상한")
        if committed + p["est_usd"] > config.DRINKS_DEVELOP_MAX_USD_PER_REQUEST:
            raise DbError("request_cap_exceeded", "요청 상한")
        if committed + p["est_usd"] > self.cap:
            raise DbError("budget_exceeded", "결재 금액 초과")
        self.holds += 1
        hid = f"h{self.holds}"
        self.held[hid] = p["est_usd"]
        return {"hold_id": hid}

    def drinks_develop_settle(self, p):
        est = self.held.pop(p["hold_id"])
        self.settles.append(p)
        if p["outcome"] == "settled":
            self.settled += p["actual_usd"]
        return {"hold_id": p["hold_id"], "est": est}

    def drinks_develop_link_snapshot(self, p):
        self.linked.append(p["snapshot_id"])
        return {"snapshot_id": p["snapshot_id"], "role": "evidence"}

    def drinks_develop_add_source(self, p):
        self.added.append(p["source"])
        return {"snapshot_id": f"new{len(self.added)}", "role": "evidence"}

    def drinks_develop_save_evidence(self, p):
        self.saved_evidence = p
        return {"review_id": "rv1", "quote_check": {"matched": len(p["evidence_pack"]["claims"]), "unmatched": 0, "not_checked": 0}}

    def drinks_develop_save_plan(self, p):
        self.saved_plan = p
        return {"revision_id": "pl1", "coverage": {}}

    def drinks_finish_develop(self, p):
        self.finish = p
        return {"status": p["outcome"]}


def src_row(title="논문 A", *, body=BODY, linked=True, role="evidence", kind="expert", sid="s1", url="https://example.org/a"):
    return {"snapshot_id": sid, "canonical_url": url, "title": title, "publisher": "Sci Rep", "source_kind": kind, "rights_status": "quote_ok",
            "usage_terms": "CC BY 4.0", "linked": linked, "role": role if linked else None, "body_text": body, "depth": "full_text"}


def job(kind="evidence", budget="b1", **kw):
    j = {"request_id": "q1", "lease_token": "lt", "kind": kind, "budget_id": budget, "topic": TOPIC, "budget": {"remaining_usd": 1}}
    j.update(kw)
    return j


def fake_extract(quotes, calls=None):
    def f(question, text):
        if calls is not None:
            calls.append(text)
        return [{"text": f"주장 {'가나다라마바사아자차'[i - 1]}", "original_quote": q, "claim_type": "process"} for i, q in enumerate(quotes, 1)]
    return f


def boom(*a, **k):
    raise AssertionError("모델을 부르면 안 됩니다")


def deps(**kw):
    base = {"extract_claims": boom, "write_plan": boom, "jev_check": lambda n, s: None, "fetcher_factory": lambda hosts: boom()}
    base.update(kw)
    return dd.Deps(**base)


# ── 원문 인용 대조 ─────────────────────────────────────────────

def test_verify_quote_exact_and_whitespace_case_normalized_but_not_paraphrase():
    src = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking in order to further enhance the taste."
    assert dd.verify_quote("Whisky enthusiasts often also add a few drops of water to the spirit", src)
    assert dd.verify_quote("whisky  enthusiasts\n often also add a few drops\tof water to the spirit", src), "공백·대소문자 차이는 무시"
    assert dd.verify_quote("Whisky enthusiasts often also add a few drops of water to the spirit".replace(" ", " "), src), "모델 인용의 NBSP 는 정리해 준다"
    assert not dd.verify_quote("Whisky lovers often also add a few drops of water to the spirit", src), "단어를 바꾼 풀어쓰기는 불일치"
    assert not dd.verify_quote("Whisky enthusiasts often add a few drops of water to the spirit", src), "단어를 빼도 불일치"
    assert not dd.verify_quote("a few drops", src), "너무 짧은 인용은 거절"
    assert not dd.verify_quote("Whisky enthusiasts often also add … before drinking in order to further", src), "줄임표로 이은 발췌는 거절"
    assert not dd.verify_quote("위스키 애호가들은 마시기 전에 물을 몇 방울 넣곤 한다는 번역", src)
    assert not dd.verify_quote("x" * 600, "x" * 600), "너무 긴 인용도 거절"


def test_verify_quote_is_not_more_lenient_than_the_db_on_the_source_side():
    nbsp_src = "Whisky enthusiasts often also add a few drops of water to the spirit"
    assert not dd.verify_quote("Whisky enthusiasts often also add a few drops of water", nbsp_src), "원문 쪽 NBSP 는 DB 도 같은 공백으로 안 본다 — 통과시키지 않는다"
    assert dd.verify_quote("Whisky enthusiasts often also add a few drops of water", dd.clean_source_text(nbsp_src)), "보관 전에 정리한 본문은 통과"


def test_verify_claims_drops_and_counts_each_reason():
    q = QUOTES[0]
    raw = [{"text": "맞는 주장", "original_quote": q, "claim_type": "process"},
           {"text": "같은 인용 또 한 번", "original_quote": q, "claim_type": "process"},
           {"text": "지어낸 인용", "original_quote": "This sentence is nowhere in the source text at all", "claim_type": "process"},
           {"text": "형식 잘못", "original_quote": QUOTES[1], "claim_type": "advice"},
           {"text": "환산한 숫자 45%", "original_quote": QUOTES[1], "claim_type": "product_fact"},
           {"text": "", "original_quote": QUOTES[1], "claim_type": "process"}, "not a dict"]
    kept, dropped = dd.verify_claims(raw, BODY)
    assert [k["text"] for k in kept] == ["맞는 주장"]
    assert dropped == {"duplicate_quote": 1, "quote_not_in_source": 1, "bad_type": 1, "number_not_in_quote": 1, "empty": 1, "not_object": 1}


# ── 근거 초안 ──────────────────────────────────────────────────

def test_evidence_keeps_only_verified_quotes_links_used_sources_and_saves_a_draft():
    rpc = FakeRpc(sources=[src_row(), src_row("쓸모없는 글", sid="s2", body="Nothing relevant here. " * 30)])
    seen = []
    ex = fake_extract(QUOTES[:4] + ["Invented sentence that the model made up and is not in the source"], seen)
    res = dd.process_job(job(), rpc, deps(extract_claims=lambda q, t: ex(q, t) if t == BODY[: len(t)] and "Nothing relevant" not in t else []))
    assert res["status"] == "succeeded"
    assert rpc.finish["outcome"] == "succeeded"
    pack = rpc.saved_evidence["evidence_pack"]["claims"]
    assert [c["claim_id"] for c in pack] == ["c1", "c2", "c3", "c4"]
    assert all(c["support_review"] == "not_reviewed" for c in pack), "의미 검토는 운영자 몫"
    assert [c["source_refs"][0]["original_quote"] for c in pack] == [dd.clean_source_text(q) for q in QUOTES[:4]]
    assert all(c["source_refs"][0]["snapshot_id"] == "s1" for c in pack)
    brief = rpc.saved_evidence["brief"]
    assert brief["selected_claim_ids"] == ["c1", "c2", "c3", "c4"]
    assert brief["required_claims"]["video"] == ["c1", "c2", "c3"] and "core_takeaway" not in brief
    assert rpc.linked == [] and rpc.added == [], "이미 근거 역할로 붙은 출처는 다시 붙이지 않고, 쓸모없던 출처는 붙이지 않는다"
    r = rpc.finish["result"]
    assert r["claims_kept"] == 4 and r["dropped_total"] == 1
    assert {s["title"]: s["claims_kept"] for s in r["sources"]} == {"논문 A": 4, "쓸모없는 글": 0}
    assert r["cost"]["calls"] and r["cost"]["spent_usd"] > 0
    # 호출마다 가잡기 → 확정, 승인·제출 함수는 없다
    assert rpc.names.count("drinks_develop_hold") == rpc.names.count("drinks_develop_settle") == 2
    assert not any(re.search(r"approve|submit|review_action|plan_action|select", n) for n in rpc.names)


def test_evidence_links_collected_sources_and_adds_new_text_only_when_claims_survive():
    collected = src_row("수집된 공식 글", linked=False, kind="official", sid="s9")
    rpc = FakeRpc(sources=[collected])
    res = dd.process_job(job(), rpc, deps(extract_claims=fake_extract(QUOTES[:3])))
    assert res["status"] == "succeeded"
    assert rpc.linked == ["s9"]
    # 수집원 글이 쓸모없으면 붙이지 않는다
    rpc2 = FakeRpc(sources=[src_row("수집된 공식 글", linked=False, kind="official", sid="s9")])
    res2 = dd.process_job(job(), rpc2, deps(extract_claims=lambda q, t: []))
    assert res2["status"] == "blocked" and rpc2.linked == []


def test_evidence_insufficient_blocks_without_writing_and_tells_the_operator_what_to_add():
    rows = [src_row(), src_row("주소만 등록한 출처", sid="s3", body=None, url="https://example.org/meta"),
            src_row("누군가의 후기", sid="s4", kind="community"), src_row("질문 신호 글", sid="s5", role="discovery"),
            src_row("자동 수집 블로그", sid="s6", linked=False, kind="media")]
    rpc = FakeRpc(sources=rows)
    res = dd.process_job(job(), rpc, deps(extract_claims=fake_extract(QUOTES[:2])))   # 2건 < 최소 3건
    assert res["status"] == "blocked"
    f = rpc.finish
    assert f["outcome"] == "blocked" and f["error_code"] == "evidence_insufficient"
    assert rpc.saved_evidence is None, "근거 부족이면 아무 근거도 쓰지 않는다"
    msg = f["error_message"]
    assert "2건" in msg and "출처 추가" in msg and "붙여넣" in msg
    assert "주소만 등록한 출처" in msg and "본문이 없고" in msg
    assert "누군가의 후기" in msg and "질문·인기 신호" in msg and "자동 수집 블로그" in msg
    assert f["result"]["claims_kept"] == 2 and f["result"]["skipped"]


def test_evidence_with_no_usable_source_never_calls_the_model():
    rpc = FakeRpc(sources=[])
    res = dd.process_job(job(), rpc, deps())
    assert res["status"] == "blocked" and rpc.finish["error_code"] == "evidence_insufficient"
    assert "하나도 없었습니다" in rpc.finish["error_message"]
    assert "drinks_develop_hold" not in rpc.names


# ── 비용 장치 ──────────────────────────────────────────────────

def test_without_budget_no_model_call_and_no_hold():
    rpc = FakeRpc(sources=[src_row()])
    for kind in ("evidence", "plan"):
        rpc = FakeRpc(sources=[src_row()])
        res = dd.process_job(job(kind, budget=None, review={"claims": []}), rpc, deps())
        assert res["status"] == "blocked"
        assert rpc.finish["error_code"] == "budget_missing"
        assert "drinks_develop_hold" not in rpc.names and "drinks_develop_sources" not in rpc.names


def test_ledger_refuses_without_budget_even_if_called_directly():
    called = []
    led = dd.Ledger(FakeRpc(), {"request_id": "q", "lease_token": "l"}, None)
    with pytest.raises(dd.DevelopError) as e:
        led.run("m", 0.01, lambda: called.append(1), "x")
    assert e.value.code == "budget_missing" and not called


def test_db_cap_refusal_stops_the_job_before_the_model_is_called():
    rpc = FakeRpc(sources=[src_row()], cap=0.001)
    called = []
    res = dd.process_job(job(), rpc, deps(extract_claims=lambda q, t: called.append(1) or []))
    assert res["status"] == "blocked" and rpc.finish["error_code"] == "budget_exceeded" and not called


def test_request_cap_is_enforced_by_the_db_not_the_worker():
    rpc = FakeRpc(sources=[src_row(sid=f"s{i}", title=f"출처 {i}") for i in range(4)], cap=100)
    n = []
    big = dd.Deps(extract_claims=lambda q, t: n.append(1) or [], write_plan=boom)
    orig = dd.estimate_usd
    try:
        dd.estimate_usd = lambda *a, **k: 0.3   # 호출 1회 예상이 크면 두 번째 가잡기부터 요청 상한(0.5)에 걸린다
        res = dd.process_job(job(), rpc, big)
    finally:
        dd.estimate_usd = orig
    assert len(n) == 1, "두 번째 출처는 호출 전에 DB 가 거절했다"
    assert rpc.finish["error_code"] == "request_cap_exceeded" and res["status"] == "blocked"


def test_failed_model_call_releases_the_hold():
    rpc = FakeRpc(sources=[src_row()])

    def fail(q, t):
        raise RuntimeError("503")

    res = dd.process_job(job(), rpc, deps(extract_claims=fail))
    assert res["status"] == "failed" and rpc.finish["error_code"] == "worker_error"
    assert [s["outcome"] for s in rpc.settles] == ["released"] and rpc.settled == 0


def test_cancel_stops_before_the_next_step():
    rpc = FakeRpc(sources=[src_row()], cancel_after=1)
    res = dd.process_job(job(), rpc, deps(extract_claims=boom))
    assert res["status"] == "failed" and rpc.finish["error_code"] == "canceled"


def test_estimates_are_positive_upper_bounds_and_unknown_models_are_refused():
    e = dd.estimate_usd(config.DRINKS_DEVELOP_PLAN_MODEL, 8000, config.DRINKS_DEVELOP_PLAN_MAX_TOKENS)
    assert 0.03 < e < config.DRINKS_DEVELOP_MAX_USD_PER_REQUEST
    # gemini 는 결제 실패 시 deepseek 로 갈아타므로, 더 비싼 쪽 단가로 센다
    g = dd.estimate_usd("gemini-2.5-flash", 40000, config.DRINKS_DEVELOP_EXTRACT_MAX_TOKENS)
    only_gemini = (40000 / config.DRINKS_DEVELOP_CHARS_PER_TOKEN) * 0.30e-6 + config.DRINKS_DEVELOP_EXTRACT_MAX_TOKENS * 2.5e-6
    assert g > only_gemini
    with pytest.raises(dd.DevelopError) as exc:
        dd.estimate_usd("made-up-model", 10, 10)
    assert exc.value.code == "price_unknown"
    # 평소 두 단계가 요청 상한 안에 들어온다
    assert 4 * g + 2 * e < config.DRINKS_DEVELOP_MAX_USD_PER_REQUEST * 1.5


def test_capture_usage_sums_real_usage_without_hiding_the_original_record(monkeypatch):
    from engine import llm

    seen = []
    monkeypatch.setattr(llm, "_record_text_usage", lambda model, usage: seen.append(model))
    with dd.capture_usage() as box:
        llm._record_text_usage("deepseek-v4-pro", {"prompt_tokens": 1000, "completion_tokens": 2000})
    assert seen == ["deepseek-v4-pro"] and box.calls == 1
    assert box.usd == pytest.approx(1000 * 1.32e-6 + 2000 * 3.96e-6)
    assert llm._record_text_usage is not None and getattr(llm._record_text_usage, "__name__", "") != "wrapper"


# ── 제작안 초안 ────────────────────────────────────────────────

def review_from_gold(gold=GOLD_WHISKY):
    claims = [{"claim_id": c["claim_id"], "text": c["text"], "claim_type": "process",
               "source_refs": [{"snapshot_id": "s1", "original_quote": c["original_quote"]}], **({"kind": c["kind"]} if c.get("kind") else {})}
              for c in gold["claims"]]
    return {"review_id": "rv", "brief": {"audience_question": gold["topic"]["question"], "core_takeaway": "물을 조금 타면 향이 산다",
            "selected_claim_ids": [c["claim_id"] for c in claims]}, "claims": claims,
            "core_claim_ids": [c["claim_id"] for c in claims],
            "sources": [{"snapshot_id": "s1", "title": gold["source"]["title"], "publisher": gold["source"]["publisher"], "url": gold["source"]["url"]}]}


def gold_plan(gold=GOLD_WHISKY):
    return {"scenes": copy.deepcopy(gold["scenes"]), "viewer_conclusion": copy.deepcopy(gold.get("viewer_conclusion"))}


def plan_job(review=None, **kw):
    return job("plan", review=review or review_from_gold(), **kw)


def test_plan_phase_passes_the_hand_made_gold_plan_and_saves_a_draft_with_a_source_table():
    rpc = FakeRpc()
    seen = {}

    def write(question, claims, brief, feedback=None):
        seen.update(question=question, ids=[c["claim_id"] for c in claims], feedback=feedback)
        return gold_plan()

    res = dd.process_job(plan_job(), rpc, deps(write_plan=write))
    assert res["status"] == "succeeded", rpc.finish
    assert seen["feedback"] is None and seen["ids"] == [c["claim_id"] for c in GOLD_WHISKY["claims"]]
    saved = rpc.saved_plan["plan_json"]
    assert set(saved) == {"scenes", "notes"}, "DB 검증기가 보존하는 칸만 보낸다"
    assert saved["notes"].startswith("시청자 결론(c3·c5)")
    table = rpc.finish["result"]["source_table"]
    assert len(table) == len(GOLD_WHISKY["scenes"])
    s3 = table[2]
    assert [c["claim_id"] for c in s3["claims"]] == ["c9", "c2"] and s3["claims"][0]["quotes"][0]["quote"].startswith("have a typical smoky taste")
    assert s3["claims"][0]["quotes"][0]["source_url"] == GOLD_WHISKY["source"]["url"]
    assert rpc.finish["result"]["rewrites"] == 0 and rpc.finish["result"]["checks"]["ok"] is True
    assert rpc.names.count("drinks_develop_hold") == 1
    assert not any(re.search(r"approve|submit|review_action|plan_action|select", n) for n in rpc.names)


def invented_dosing_plan():
    plan = gold_plan()
    plan["scenes"][3]["narration"] = "60도 위스키라면, 30ml에 물 세 티스푼쯤 타 보세요."
    return plan


def test_check_block_triggers_exactly_one_rewrite_which_gets_the_block_messages_and_then_passes():
    rpc = FakeRpc()
    calls = []

    def write(question, claims, brief, feedback=None):
        calls.append(feedback)
        return invented_dosing_plan() if len(calls) == 1 else gold_plan()

    res = dd.process_job(plan_job(), rpc, deps(write_plan=write))
    assert res["status"] == "succeeded"
    assert len(calls) == 2 and calls[0] is None
    fb = "\n".join(calls[1])
    assert "quantity_unsupported" in fb and "number_unsupported" in fb and "advice_unsupported" in fb
    assert rpc.finish["result"]["rewrites"] == 1
    assert rpc.names.count("drinks_develop_hold") == rpc.names.count("drinks_develop_settle") == 2


def test_second_block_stops_without_saving_and_keeps_the_report_in_the_error():
    rpc = FakeRpc()
    calls = []

    def write(question, claims, brief, feedback=None):
        calls.append(1)
        return invented_dosing_plan()

    res = dd.process_job(plan_job(), rpc, deps(write_plan=write))
    assert res["status"] == "blocked" and len(calls) == 2, "다시 쓰기는 딱 한 번"
    assert rpc.saved_plan is None, "막힌 초안은 저장하지 않는다"
    assert rpc.finish["error_code"] == "script_check_failed"
    assert "quantity_unsupported" in rpc.finish["error_message"]
    r = rpc.finish["result"]
    assert r["rewrites"] == 1 and r["checks"]["ok"] is False and r["rejected_plan"]["scenes"]


def test_plan_may_only_cite_the_approved_core_claims_and_shorts_shape_is_enforced():
    review = review_from_gold()
    review["claims"] = [c for c in review["claims"] if c["claim_id"] in ("c1", "c2", "c3", "c5", "c9")]
    plan = gold_plan()
    plan["scenes"][4]["claim_ids"] = ["c4"]   # 승인 핵심 주장 목록에 없는 c4
    rep = dd.check_plan(plan, review, TOPIC)
    codes = {(f.code, f.scene) for f in rep.blocks}
    assert ("claim_unknown", 5) in codes and ("claim_not_allowed", 5) in codes
    short = gold_plan()
    short["scenes"] = short["scenes"][:3]
    assert "scene_count" in {f.code for f in dd.check_plan(short, review_from_gold(), TOPIC).blocks}
    longer = gold_plan()
    longer["scenes"][0]["timing_sec"] = 20
    assert "duration_out_of_range" in {f.code for f in dd.check_plan(longer, review_from_gold(), TOPIC).blocks}
    nohook = gold_plan()
    nohook["scenes"][0]["narration"] = "위스키에 물을 떨어뜨립니다."
    assert "first_scene_not_question" in {f.code for f in dd.check_plan(nohook, review_from_gold(), TOPIC).blocks}
    noconcl = gold_plan()
    noconcl.pop("viewer_conclusion")
    assert "conclusion_missing_dev" in {f.code for f in dd.check_plan(noconcl, review_from_gold(), TOPIC).blocks}


def test_jev_flags_never_block_but_trigger_the_single_rewrite_and_are_recorded():
    rpc = FakeRpc()
    calls = []

    def write(question, claims, brief, feedback=None):
        calls.append(feedback)
        return gold_plan()

    res = dd.process_job(plan_job(), rpc, deps(write_plan=write, jev_check=lambda n, s: 0.9))
    assert res["status"] == "succeeded", "Jev 는 신호이지 차단이 아니다"
    assert len(calls) == 2 and any("Jev" in m for m in calls[1])
    assert rpc.finish["result"]["jev_flags"]


def test_jev_is_off_by_default_and_cannot_call_out_in_stage0():
    assert config.DRINKS_DEVELOP_JEV_ENABLED is False
    assert dd.jev_unsupported_p("문장", "원문") is None


# ── 재생: 손으로 만든 통과 사례 / 사고 났던 사례 ───────────────────────

def test_replay_whisky_gold_plan_passes_the_plan_phase_checks():
    """손으로 만든 통과 사례(whisky-water-v1, v6.1)는 개발 단계 검사(코드 검사 + 쇼츠 모양)를 통과한다."""
    rep = dd.check_plan(gold_plan(), review_from_gold(), TOPIC)
    assert rep.ok, sc.summary_ko(rep)
    assert sc.check(GOLD_WHISKY).ok, "원본 모양(source 칸 포함)으로 재도 통과"


def test_replay_gi_sake_gold_no_longer_passes_the_current_checks():
    """docs/drinks-pilot/gi-sake-v1.json 은 엔진 규칙이 들어오기 전 사례다(연도 환산·근거 없는 권고·도해 구조 없음) — 지금 검사는 이것을 막는다.
    통과 사례로 쓰지 않는다(fixtures/drinks_scripts/sake-v2 와 같은 종류)."""
    rep = sc.check(GOLD_SAKE)
    assert not rep.ok
    assert {"number_unsupported", "advice_unsupported", "photo_mechanism_spec_missing"} <= set(rep.codes())


@pytest.mark.parametrize("name", ["whisky-v1", "whisky-v2", "whisky-v3", "whisky-v4", "whisky-v5", "sake-v2"])
def test_replay_known_bad_versions_are_blocked_in_the_plan_phase(name):
    v = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    review = {"claims": v["claims"], "brief": {"audience_question": v["topic"]["question"]}, "sources": [v["source"]]}
    plan = {"scenes": v["scenes"], "viewer_conclusion": v.get("viewer_conclusion")}
    assert not dd.check_plan(plan, review, TOPIC).ok, name


# ── Europe PMC · 공식 목록 (기본 꺼짐, 시험은 명시적으로 켠다) ─────────────

JATS = ("<article><body><sec><title>Intro</title><p>" + " ".join(QUOTES[:3]) + "</p></sec></body>"
        "<back><ref-list><ref>Reference text that must be dropped</ref></ref-list></back></article>")


class FakeFetcher:
    def __init__(self):
        self.urls = []

    def get(self, url, accept=None, params=None, headers=None):
        self.urls.append(url)
        if url.endswith("/search"):
            hits = [{"pmcid": "PMC1", "doi": "10.1/x", "title": "Dilution", "journalTitle": "Sci Rep", "pubYear": "2017", "license": "cc by"},
                    {"pmcid": "PMC2", "title": "No license", "license": ""}, {"title": "no pmcid", "license": "cc by"}]
            body = json.dumps({"resultList": {"result": hits}}).encode()
        else:
            body = JATS.encode()
        return SimpleNamespace(body=body, charset="utf-8", url=url)


def test_europepmc_is_off_by_default_so_no_fetcher_is_created():
    assert config.DRINKS_DEVELOP_EUROPEPMC_ENABLED is False
    assert config.DRINKS_DEVELOP_OFFICIAL_SOURCES == []
    rpc = FakeRpc(sources=[])
    called = []
    dd.gather_sources(job(), rpc, {"request_id": "q", "lease_token": "l"}, dd.Deps(fetcher_factory=lambda h: called.append(h)))
    assert called == []


def test_europepmc_when_enabled_finds_open_access_text_and_adds_it_only_after_quotes_verify(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_DEVELOP_EUROPEPMC_ENABLED", True)
    topic = {**TOPIC, "title": "whisky water", "question": "why add water to whisky", "target_subject": None}
    fetcher = FakeFetcher()
    rpc = FakeRpc(sources=[])
    d = deps(extract_claims=fake_extract(QUOTES[:3]), fetcher_factory=lambda hosts: fetcher)
    res = dd.process_job(job(topic=topic), rpc, d)
    assert res["status"] == "succeeded", rpc.finish
    assert any(u.endswith("/search") for u in fetcher.urls) and any(u.endswith("/PMC1/fullTextXML") for u in fetcher.urls)
    assert not any("PMC2" in u for u in fetcher.urls), "라이선스 없는 논문은 본문도 받지 않는다"
    assert len(rpc.added) == 1
    added = rpc.added[0]
    assert added["rights_status"] == "quote_ok" and "CC BY" in added["usage_terms"] and added["canonical_url"] == "https://doi.org/10.1/x"
    assert "Reference text" not in added["body_text"]
    assert added["body_text"] == dd.clean_source_text(added["body_text"]), "보관 본문 = 대조에 쓴 본문"
    assert all(dd.verify_quote(c["source_refs"][0]["original_quote"], added["body_text"]) for c in rpc.saved_evidence["evidence_pack"]["claims"])


def test_europepmc_needs_english_terms_and_jats_drops_references():
    assert dd.ascii_query_terms({"title": "위스키 물", "question": "왜?"}) == []
    assert "Reference text" not in dd.jats_to_text(JATS)
    notes = dd.find_europepmc({"title": "위스키", "question": "왜"}, FakeFetcher())
    assert notes[0] == [] and "건너뜀" in notes[1][0]


def test_official_sources_without_operator_verified_terms_are_ignored(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_DEVELOP_OFFICIAL_SOURCES", [{"name": "x", "url": "https://example.gov/a", "terms_verified": False}])
    out, notes = dd.find_official(TOPIC, deps())
    assert out == [] and notes == []


# ── 제한값 · 파일 점검 ─────────────────────────────────────────

def test_limits_match_sql_constants():
    lim = json.loads("{" + ",".join(f'"{k}":{v}' for k, v in re.findall(r"'([a-z_]+)', ([0-9.]+)", SQL.split("drinks_develop_limits()")[1].split("$$;")[0])) + "}")
    assert lim["max_cap_usd"] == config.DRINKS_DEVELOP_MAX_BUDGET_USD == 10
    assert lim["max_usd_per_request"] == config.DRINKS_DEVELOP_MAX_USD_PER_REQUEST
    assert lim["max_holds_per_request"] == config.DRINKS_DEVELOP_MAX_HOLDS_PER_REQUEST
    assert "cap_usd > 0 and cap_usd <= 10" in SQL


def test_migration_workers_never_call_approval_functions_and_every_function_is_pinned():
    for forbidden in ("drinks_review_action", "drinks_plan_action", "drinks_select(", "drinks_topic_action"):
        assert forbidden not in SQL
    assert "alter function %s set search_path = public, pg_temp" in SQL
    funcs = re.findall(r"create or replace function (\w+)\(", SQL)
    assert funcs and all(f.startswith(("drinks_", "drink_")) for f in funcs)
    for f in re.findall(r"create or replace function (drinks_(?:develop|request_develop|cancel_develop|start_develop|heartbeat_develop|finish_develop|open_develop|close_develop|reap_develop)\w*)\(", SQL):
        body = SQL.split(f"create or replace function {f}(")[1].split("$$;")[0]
        assert "set search_path = public, pg_temp" in body.split("as $$")[0], f


def test_workflow_is_manual_only_and_has_the_keys_it_needs():
    y = (ROOT / ".github" / "workflows" / "drinks-develop.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in y and "schedule:" not in y and "cron:" not in y
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "JEV_API_KEY", "JEV_ENABLED", "engine.drinks_develop"):
        assert k in y
    assert "GITHUB_DISPATCH_TOKEN" in y
    assert "DRINKS_DEVELOP_EUROPEPMC_ENABLED:" not in y, "Europe PMC 는 켜지 않는다(env 로 주지 않는다)"
