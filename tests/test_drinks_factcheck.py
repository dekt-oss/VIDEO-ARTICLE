"""AI 사실 확인(2026-11-06, 운영자 "AI 가 사실 확인에 통과한 근거는 '확인됨'으로 자동 표시") — 모델·네트워크 호출 0. 판정은 전부 가짜 응답이다.

지키는 것(docs/deviation-drinks-auto-factcheck.md §A):
  · 모델 판정을 코드가 다시 잰다 — 없는 근거 번호·근거 없는 판정·인용에 없는 숫자는 '불확실'
  · 맞음·틀림 판정이 댔고, 주장 문장이 인용 범위 안(faithful)이고, Jev 가 안 건 주장만 support_review='supported' + 한계 칸에 '자동' 표시
  · 응답을 못 읽으면 한 번 더 묻고, 그래도 안 되면 전부 불확실 — 작업은 실패시키지 않는다
  · 돈은 가잡기 → 확정(Ledger)으로만. 한도에 막히면 건너뛰고 작업은 계속. 취소는 그대로 멈춘다
  · 승인·제출 함수를 부르지 않는다
"""

from __future__ import annotations

import re

import pytest

import test_drinks_develop as base
from engine import config
from engine import drinks_develop as dd
from engine.drinks_collect import DbError
from engine.llm import JSONParseError

QUOTES = base.QUOTES[:4]


def claims_fixture():
    return [{"claim_id": f"c{i}", "text": f"주장 {i}", "claim_type": "process", "support_review": "not_reviewed",
             "source_refs": [{"snapshot_id": "s1", "original_quote": dd.clean_source_text(q)}]} for i, q in enumerate(QUOTES, 1)]


def good(ids=("c1", "c2"), verdict="TRUE", reason="인용이 그렇다고 말한다.", faithful=("c1", "c2", "c3", "c4")):
    return {"assertions": [{"assertion_ko": "위스키에 물을 넣으면 향이 달라진다", "verdict": verdict, "claim_ids": list(ids), "reason_ko": reason}],
            "claim_checks": [{"claim_id": c, "faithful": True, "reason_ko": "범위 안"} for c in faithful]}


# ── 판정 규칙(judge_verdicts) ─────────────────────────────────

def test_good_verdict_is_kept_and_cited_numbers_from_the_quote_pass():
    q = claims_fixture()[0]["source_refs"][0]["original_quote"]
    nums = sorted(dd._norm_nums(q))
    reason = f"c1 의 인용이 {nums[0]} 을 말한다." if nums else "c1 의 인용이 그렇게 말한다."
    j = dd.judge_verdicts(good(ids=("c1",), reason=reason), claims_fixture())
    a = j["assertions"][0]
    assert a["verdict"] == "TRUE" and a["code_note"] is None and a["claim_ids"] == ["c1"]


def test_hallucinated_claim_id_turns_the_verdict_uncertain():
    j = dd.judge_verdicts(good(ids=("c1", "c9")), claims_fixture())
    a = j["assertions"][0]
    assert a["verdict"] == "UNCERTAIN" and a["model_verdict"] == "TRUE"
    assert "c9" in a["code_note"] and a["claim_ids"] == ["c1"]


def test_number_in_reason_that_is_not_in_the_cited_quote_turns_uncertain():
    j = dd.judge_verdicts(good(ids=("c1",), reason="물을 47 방울 넣으면 달라진다."), claims_fixture())
    assert j["assertions"][0]["verdict"] == "UNCERTAIN" and "47" in j["assertions"][0]["code_note"]


def test_claim_id_digits_are_not_numbers_but_full_width_digits_are():
    j = dd.judge_verdicts(good(ids=("c1", "c2"), reason="c1·c2 의 인용이 같은 말을 한다."), claims_fixture())
    assert j["assertions"][0]["verdict"] == "TRUE"
    j2 = dd.judge_verdicts(good(ids=("c1",), reason="３８ 도에서 바뀐다."), claims_fixture())
    assert j2["assertions"][0]["verdict"] == "UNCERTAIN"


def test_true_or_false_without_claim_ids_and_unknown_verdicts_are_uncertain():
    j = dd.judge_verdicts(good(ids=()), claims_fixture())
    assert j["assertions"][0]["verdict"] == "UNCERTAIN" and "근거 번호 없이" in j["assertions"][0]["code_note"]
    j2 = dd.judge_verdicts(good(verdict="PROBABLY"), claims_fixture())
    assert j2["assertions"][0]["verdict"] == "UNCERTAIN"


def test_wrong_shape_is_none_so_the_caller_asks_again():
    assert dd.judge_verdicts({"verdicts": []}, claims_fixture()) is None
    assert dd.judge_verdicts([], claims_fixture()) is None
    assert dd.judge_verdicts({"assertions": "TRUE"}, claims_fixture()) is None


def test_assertions_are_capped():
    many = {"assertions": [good()["assertions"][0]] * 20, "claim_checks": []}
    assert len(dd.judge_verdicts(many, claims_fixture())["assertions"]) == config.DRINKS_DEVELOP_FACTCHECK_MAX_ASSERTIONS


# ── 작업 전체(process_job) ────────────────────────────────────

def run(factcheck, *, sources=None, **kw):
    rpc = base.FakeRpc(sources=sources if sources is not None else [base.src_row()], **kw)
    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(QUOTES), factcheck=factcheck))
    return rpc, res


def saved_claims(rpc):
    return {c["claim_id"]: c for c in rpc.saved_evidence["evidence_pack"]["claims"]}


def test_true_verdict_marks_only_its_cited_faithful_claims_supported_with_the_auto_note():
    rpc, res = run(lambda t, ctx, cl: good(ids=("c1", "c2", "c3"), faithful=("c1", "c3")))
    assert res["status"] == "succeeded"
    c = saved_claims(rpc)
    assert c["c1"]["support_review"] == "supported" and c["c1"]["limitations"] == config.DRINKS_DEVELOP_FACTCHECK_NOTE
    assert c["c2"]["support_review"] == "not_reviewed", "주장 문장 대조(faithful)가 없으면 자동으로 확인됨이 되지 않는다"
    assert c["c4"]["support_review"] == "not_reviewed", "판정의 근거로 쓰이지 않은 주장은 확인됨이 되지 않는다"
    fc = rpc.finish["result"]["factcheck"]
    assert fc["status"] == "ok" and fc["counts"] == {"TRUE": 1, "FALSE": 0, "UNCERTAIN": 0}
    assert fc["auto_supported"] == ["c1", "c3"] and {n["claim_id"] for n in fc["not_supported"]} == {"c2", "c4"}
    assert fc["assertions"][0]["sources"][0]["title"] == "논문 A"
    # 0076: 확인되지 않은 주장은 사람 숙제가 아니라 핵심 주장에서 빠진다(이유와 함께)
    assert rpc.saved_evidence["brief"]["selected_claim_ids"] == ["c1", "c3"]
    assert {x["claim_id"] for x in rpc.finish["result"]["excluded"]} == {"c2", "c4"}
    assert rpc.finish["result"]["needs_operator"] == []


def test_false_verdict_also_marks_the_correcting_claims_supported():
    rpc, _ = run(lambda t, ctx, cl: good(ids=("c3", "c4"), verdict="FALSE"))
    assert saved_claims(rpc)["c3"]["support_review"] == "supported"


def test_uncertain_and_hallucinated_verdicts_mark_nothing():
    """0076: 아무것도 확인되지 않으면 사람에게 판정을 넘기지 않고 '자료 부족'으로 멈춘다(초안을 저장하지 않는다)."""
    for out in (good(verdict="UNCERTAIN"), good(ids=("c1", "c77")), good(reason="정확히 100 년 간다")):
        rpc, res = run(lambda t, ctx, cl, o=out: o)
        assert res["status"] == "blocked" and rpc.finish["error_code"] == "evidence_insufficient", out
        assert rpc.saved_evidence is None
        kept = rpc.finish["result"]["unsaved_evidence"]["evidence_pack"]["claims"]
        assert all(c["support_review"] == "not_reviewed" for c in kept), out


def test_jev_flag_keeps_a_claim_for_the_operator():
    rpc = base.FakeRpc(sources=[base.src_row()])
    d = base.deps(extract_claims=base.fake_extract(QUOTES), factcheck=lambda t, ctx, cl: good(ids=("c1", "c2", "c3")),
                  jev_check=lambda n, s: 0.9 if n == "주장 가" else 0.1)
    dd.process_job(base.job(), rpc, d)
    c = saved_claims(rpc)
    assert c["c1"]["support_review"] == "not_reviewed" and c["c2"]["support_review"] == "supported"
    assert "c1" not in rpc.saved_evidence["brief"]["selected_claim_ids"], "Jev 가 건 주장은 핵심 주장에서 빠진다"
    assert any(n["claim_id"] == "c1" and "Jev" in n["why"] for n in rpc.finish["result"]["factcheck"]["not_supported"])


def test_bad_json_retries_once_then_closes_as_a_recoverable_failure_keeping_the_extraction():
    """0076: 사실 확인을 못 했으면 '자료 부족'도 '사람 확인'도 아니다 — 추출 결과를 보관하고 복구 가능한 실패(factcheck_unavailable)로 닫는다."""
    calls = []

    def bad(t, ctx, cl):
        calls.append(1)
        raise JSONParseError("모델이 JSON 이 아닌 글을 냈다")

    rpc, res = run(bad)
    assert res["status"] == "failed" and len(calls) == config.DRINKS_DEVELOP_FACTCHECK_ATTEMPTS == 2
    assert rpc.finish["error_code"] == "factcheck_unavailable" and rpc.saved_evidence is None
    kept = rpc.finish["result"]["unsaved_evidence"]
    assert len(kept["evidence_pack"]["claims"]) == 4 and kept["factcheck"] == {}, "다음 요청은 추출을 다시 하지 않고 사실 확인만 다시 한다"
    assert rpc.names.count("drinks_develop_hold") == rpc.names.count("drinks_develop_settle") == 1 + 2, "실패한 호출도 가잡기는 해제·확정된다"


def test_wrong_shape_then_good_answer_uses_the_second_answer():
    answers = iter([{"nope": 1}, good(ids=("c3", "c4"))])
    rpc, _ = run(lambda t, ctx, cl: next(answers))
    assert saved_claims(rpc)["c4"]["support_review"] == "supported"
    assert rpc.names.count("drinks_develop_hold") == 3


def test_budget_refusal_skips_the_factcheck_and_keeps_the_extraction_for_later():
    class CapAfterExtract(base.FakeRpc):
        def drinks_develop_hold(self, p):
            if p["note"].startswith("AI 사실 확인"):
                raise DbError("budget_exceeded", "이번 주 한도 초과")
            return super().drinks_develop_hold(p)

    rpc = CapAfterExtract(sources=[base.src_row()])
    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(QUOTES), factcheck=base.boom))
    assert res["status"] == "failed" and rpc.saved_evidence is None and rpc.finish["error_code"] == "factcheck_unavailable"
    assert "budget_exceeded" in rpc.finish["error_message"]
    assert len(rpc.finish["result"]["unsaved_evidence"]["evidence_pack"]["claims"]) == 4


def test_cancel_during_factcheck_still_stops_the_job():
    class CancelOnFactcheck(base.FakeRpc):
        def drinks_develop_hold(self, p):
            if p["note"].startswith("AI 사실 확인"):
                raise DbError("canceled", "운영자가 취소")
            return super().drinks_develop_hold(p)

    rpc = CancelOnFactcheck(sources=[base.src_row()])
    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(QUOTES), factcheck=base.boom))
    assert rpc.finish["outcome"] == "failed" and rpc.finish["error_code"] == "canceled" and rpc.saved_evidence is None


def test_disabled_flag_calls_nothing_and_keeps_the_old_behaviour(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_DEVELOP_FACTCHECK_ENABLED", False)
    rpc, res = run(base.boom)
    assert res["status"] == "succeeded" and rpc.names.count("drinks_develop_hold") == 1
    assert all(c["support_review"] == "not_reviewed" for c in saved_claims(rpc).values())
    assert rpc.finish["result"]["factcheck"]["status"] == "disabled"


def test_question_origin_text_goes_to_the_factcheck_not_to_the_evidence():
    seen = {}

    def fc(topic, context, claims):
        seen["context"] = context
        seen["prompt"] = dd.factcheck_user_prompt(topic, context, claims)
        return good()

    disc = base.src_row("커뮤니티 질문 글", role="discovery", kind="community", sid="d1", body="위스키에 물 타면 맛이 망가진다던데 진짜예요?")
    rpc, _ = run(fc, sources=[disc, base.src_row()])
    assert seen["context"][0]["title"] == "커뮤니티 질문 글" and "망가진다" in seen["context"][0]["text"]
    assert "사실 근거 아님" in seen["prompt"] and base.TOPIC["question"] in seen["prompt"]
    assert all(r["snapshot_id"] == "s1" for c in saved_claims(rpc).values() for r in c["source_refs"]), "질문이 나온 곳은 근거로 쓰지 않는다"


def test_factcheck_cost_goes_through_the_ledger_with_a_positive_estimate():
    rpc, res = run(lambda t, ctx, cl: good())
    holds = [p for n, p in rpc.calls if n == "drinks_develop_hold" and p["note"].startswith("AI 사실 확인")]
    assert len(holds) == 1 and holds[0]["est_usd"] > 0 and holds[0]["model"] == config.DRINKS_DEVELOP_FACTCHECK_MODEL
    assert any(c["note"].startswith("AI 사실 확인") for c in rpc.finish["result"]["cost"]["calls"])


def test_the_worker_still_never_calls_approval_or_submit_functions():
    rpc, _ = run(lambda t, ctx, cl: good())
    assert not any(re.search(r"approve|submit|review_action|plan_action|select", n) for n in rpc.names)


def test_estimated_cost_per_topic_is_small_and_inside_the_request_cap():
    """출처 4곳 추출(상한) + 사실 확인 1회(주장 12개) 예상 상한 — 요청 1건 상한($0.5) 안이어야 한다."""
    extract = dd.estimate_usd(config.DRINKS_DEVELOP_EXTRACT_MODEL, config.DRINKS_DEVELOP_SOURCE_MAX_CHARS + 2_000, config.DRINKS_DEVELOP_EXTRACT_MAX_TOKENS)
    many = [dict(claims_fixture()[0], claim_id=f"c{i}") for i in range(1, config.DRINKS_DEVELOP_MAX_CLAIMS + 1)]
    fc = dd.estimate_usd(config.DRINKS_DEVELOP_FACTCHECK_MODEL,
                         len(dd.factcheck_system()) + len(dd.factcheck_user_prompt(base.TOPIC, [], many)), config.DRINKS_DEVELOP_FACTCHECK_MAX_TOKENS)
    assert fc < 0.03 and config.DRINKS_DEVELOP_MAX_SOURCES * extract + fc < config.DRINKS_DEVELOP_MAX_USD_PER_REQUEST


# ── 리허설 고정본: 워커가 실제로 보내는 RPC 내용(0원) → web/lib/drinks/factcheck.db.test.ts 가 진짜 SQL(PGlite)에 그대로 다시 보낸다 ──
REHEARSAL = base.ROOT / "tests" / "fixtures" / "drinks_factcheck" / "worker_payloads.json"
REHEARSAL_TOPIC = {"id": "t1", "title": "사케 유통기한", "question": "사케는 유통기한이 없나요? 개봉하면 냉장 보관해야 하나요?",
                   "categories": ["sake"], "status": "researching", "version": 3, "target_subject": "sake", "angle": None}
REHEARSAL_BODY = " ".join(QUOTES) + " " + ("Additional background sentence about sake storage and labelling rules. " * 3)


def rehearsal_payloads():
    """공식 출처(보관 전용 쪽) 1곳 → 추출 4건 → AI 사실 확인(맞음 1·틀림 1·지어낸 번호 1) → 저장. 워커가 DB 에 보내는 두 호출을 그대로 돌려준다."""
    from types import SimpleNamespace

    class Fetcher:
        def get(self, url, accept=None, params=None):
            body = b"" if url.endswith("robots.txt") else f"<html><title>酒類の表示の基準</title><body><p>{REHEARSAL_BODY}</p></body></html>".encode()
            return SimpleNamespace(body=body, charset="utf-8", url=url, status=200, content_type="text/html")

    def verdicts(topic, context, claims):
        return {"assertions": [
            {"assertion_ko": "사케에는 표시된 날짜가 있다", "verdict": "TRUE", "claim_ids": ["c1", "c2"], "reason_ko": "c1·c2 의 인용이 그렇게 말한다."},
            {"assertion_ko": "사케는 상온에 둬도 된다", "verdict": "FALSE", "claim_ids": ["c3"], "reason_ko": "c3 의 인용이 다르게 말한다."},
            {"assertion_ko": "개봉하면 바로 상한다", "verdict": "TRUE", "claim_ids": ["c9"], "reason_ko": "지어낸 번호."}],
            "claim_checks": [{"claim_id": c, "faithful": True, "reason_ko": "범위 안"} for c in ("c1", "c2", "c3")]}

    rpc = base.FakeRpc(sources=[])
    job = dict(base.job(), topic=REHEARSAL_TOPIC)
    d = dd.Deps(extract_claims=base.fake_extract(QUOTES), write_plan=base.boom, jev_check=lambda n, s: None,
                fetcher_factory=lambda hosts: Fetcher(), factcheck=verdicts)
    res = dd.process_job(job, rpc, d)
    assert res["status"] == "succeeded", rpc.finish
    add = [p for n, p in rpc.calls if n == "drinks_develop_add_source"]
    save = next(p for n, p in rpc.calls if n == "drinks_develop_save_evidence")
    strip = lambda p: {k: v for k, v in p.items() if k not in ("request_id", "lease_token")}
    return {"topic": {k: REHEARSAL_TOPIC[k] for k in ("title", "question", "categories")},
            "add_source": [strip(p) for p in add], "save_evidence": strip(save),
            "factcheck": {k: rpc.finish["result"]["factcheck"][k] for k in ("status", "counts", "auto_supported")}}


def test_rehearsal_fixture_is_what_the_worker_sends_today():
    """고정본이 낡으면 DB 리허설이 옛 워커를 시험한다 — 다시 만들려면 DRINKS_REGEN_FIXTURES=1 pytest tests/test_drinks_factcheck.py"""
    import json
    import os

    now = rehearsal_payloads()
    assert now["factcheck"]["auto_supported"] == ["c1", "c2", "c3"] and now["factcheck"]["counts"] == {"TRUE": 1, "FALSE": 1, "UNCERTAIN": 1}
    assert {c["claim_id"]: c["support_review"] for c in now["save_evidence"]["evidence_pack"]["claims"]} == {
        "c1": "supported", "c2": "supported", "c3": "supported", "c4": "not_reviewed"}
    assert now["add_source"][0]["source"]["origin_group"] == "国税庁"
    if os.getenv("DRINKS_REGEN_FIXTURES") == "1":
        REHEARSAL.parent.mkdir(parents=True, exist_ok=True)
        REHEARSAL.write_text(json.dumps(now, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert json.loads(REHEARSAL.read_text(encoding="utf-8")) == now


SQL_75 = (base.ROOT / "supabase" / "migrations" / "0075_drinks_auto_factcheck.sql").read_text(encoding="utf-8")
SQL_81 = (base.ROOT / "supabase" / "migrations" / "0081_drinks_factcheck_estimate.sql").read_text(encoding="utf-8")   # 가정값의 최신 정의


def test_migration_0075_estimate_counts_the_factcheck_call_with_engine_constants():
    params = SQL_81.split("create or replace function drinks_develop_estimate_params()")[1].split("$$;")[0]
    assert f"'factcheck_max_tokens', {config.DRINKS_DEVELOP_FACTCHECK_MAX_TOKENS}," in params
    assert f"'extract_model', '{config.DRINKS_DEVELOP_FACTCHECK_MODEL}'" in params, "사실 확인은 추출과 같은 모델로 센다"
    for k, v in (("max_sources", config.DRINKS_DEVELOP_MAX_SOURCES), ("source_max_chars", config.DRINKS_DEVELOP_SOURCE_MAX_CHARS),
                 ("extract_max_tokens", config.DRINKS_DEVELOP_EXTRACT_MAX_TOKENS), ("plan_max_tokens", config.DRINKS_DEVELOP_PLAN_MAX_TOKENS)):
        assert f"'{k}', {v}," in params, k
    # 12개 주장 프롬프트가 가정값(factcheck_prompt_chars) 안에 든다 — 예상이 실제보다 작아지지 않게
    chars = int(re.search(r"'factcheck_prompt_chars', (\d+)\)", params).group(1))
    many = [{"claim_id": f"c{i}", "text": "가" * 120, "claim_type": "process", "source_refs": [{"original_quote": "q" * config.DRINKS_DEVELOP_QUOTE_MAX_CHARS}]}
            for i in range(1, config.DRINKS_DEVELOP_MAX_CLAIMS + 1)]
    ctx = [{"title": "t" * 60, "text": "x" * config.DRINKS_DEVELOP_FACTCHECK_CONTEXT_CHARS}] * config.DRINKS_DEVELOP_FACTCHECK_CONTEXT_MAX
    assert len(dd.factcheck_system()) + len(dd.factcheck_user_prompt(base.TOPIC, ctx, many)) <= chars * 1.0
    est = SQL_75.split("create or replace function drinks_develop_estimate(")[1].split("$$;")[0]
    assert "+ v_fc +" in est and "'factcheck_usd'" in est
    # 판정·승인 함수는 이 파일에서 고치지 않는다
    for f in ("drinks_review_blockers", "drinks_chain_stop_blockers", "drinks_approve_content", "drinks_save_review", "drinks_develop_save_evidence"):
        assert f"function {f}(" not in SQL_75
    assert "되돌리기" in SQL_75


@pytest.mark.parametrize("name", ["drinks_approve_content", "drinks_review_action", "drinks_plan_action"])
def test_source_has_no_approval_call(name):
    src = (base.ROOT / "engine" / "drinks_develop.py").read_text(encoding="utf-8")
    assert f'"{name}"' not in src


# ── 근거가 소재 질문에 답하는가(2026-11-10 버번: 제목은 '버번 vs 셰리 캐스크 맛', 근거는 미국 위스키 종류 규정뿐) ──

def test_question_answer_is_read_and_checked_by_code():
    claims = claims_fixture()
    ok = dd.judge_verdicts({**good(), "question_answer": {"answered": True, "answer_ko": "답", "claim_ids": ["c1", "c9"]}}, claims)
    assert ok["question_answer"]["answered"] is True and ok["question_answer"]["claim_ids"] == ["c1"], "목록에 없는 번호는 버린다"
    no_ids = dd.judge_verdicts({**good(), "question_answer": {"answered": True, "claim_ids": []}}, claims)
    assert no_ids["question_answer"]["answered"] is False, "근거 번호 없이 답했다고 하면 답하지 못한 것으로 본다"
    missing = dd.judge_verdicts(good(), claims)
    assert missing["question_answer"]["answered"] is None, "응답에 판정이 없으면 막지 않는다(판정 못 함)"


def test_off_topic_evidence_stops_before_saving_and_says_what_is_missing():
    off = {**good(ids=("c1", "c2", "c3", "c4")), "question_answer": {"answered": False, "claim_ids": [], "missing_ko": "셰리 캐스크가 맛에 주는 영향"}}
    rpc, res = run(lambda t, ctx, cl: off)
    assert rpc.saved_evidence is None and rpc.finish["error_code"] == "evidence_off_topic" and res["status"] == "blocked"
    assert "셰리 캐스크가 맛에 주는 영향" in rpc.finish["error_message"]
    assert rpc.finish["result"]["unsaved_evidence"]["evidence_pack"]["claims"], "추출 결과는 보관한다(다음 요청이 다시 사지 않게)"


def test_on_topic_evidence_saves_as_before():
    on = {**good(ids=("c1", "c2", "c3", "c4")), "question_answer": {"answered": True, "answer_ko": "답", "claim_ids": ["c1"]}}
    rpc, _ = run(lambda t, ctx, cl: on)
    assert rpc.saved_evidence is not None


def test_factcheck_prompt_asks_whether_the_title_question_is_answered():
    p = dd.factcheck_system()
    assert "question_answer" in p and "양쪽 모두" in p
