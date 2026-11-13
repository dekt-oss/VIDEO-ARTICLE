"""근거 막힘 해결안(2026-11-13, 0084) — off_topic 으로 막히면 지금 근거로 답할 수 있는 질문을 제안하고, 같은 사실 확인으로 미리 판정한다.
모델·네트워크 호출 0(가짜 주입)."""
from __future__ import annotations

import test_drinks_develop as base
import test_drinks_factcheck as fc
from engine import drinks_develop as dd

NEW_Q = "위스키에 물을 넣으면 향 성분은 어떻게 될까?"
IDS = ("c1", "c2", "c3", "c4")


def judge(answer_for):
    """질문마다 답했다/못했다를 정하는 가짜 사실 확인."""
    def f(topic, ctx, claims):
        ok = answer_for(topic["question"])
        qa = {"answered": True, "answer_ko": "인용대로의 답", "claim_ids": ["c1"]} if ok else \
             {"answered": False, "claim_ids": [], "missing_ko": "원래 질문의 핵심"}
        return {**fc.good(ids=IDS), "question_answer": qa}
    return f


def run(factcheck, reframe, jev=lambda n, s: None):
    rpc = base.FakeRpc(sources=[base.src_row()])
    res = dd.process_job(base.job(), rpc, base.deps(extract_claims=base.fake_extract(fc.QUOTES), factcheck=factcheck,
                                                    reframe=reframe, jev_check=jev))
    return rpc, res


def proposes(topic, claims):
    return {"question": NEW_Q, "title": "물 한 방울과 향", "why_ko": "근거가 향 성분을 말한다"}


def test_off_topic_block_carries_a_prechecked_rescue():
    rpc, res = run(judge(lambda q: q == NEW_Q), proposes)
    assert res["status"] == "blocked" and rpc.finish["error_code"] == "evidence_off_topic"
    rescue = rpc.finish["result"]["rescue"]
    assert rescue["question"] == NEW_Q and rescue["title"] == "물 한 방울과 향" and rescue["core_claims"] >= 2
    assert "해결안" in rpc.finish["error_message"] and NEW_Q in rpc.finish["error_message"]
    holds = [p["note"] for n, p in rpc.calls if n == "drinks_develop_hold"]
    assert any("해결안" in h for h in holds), "해결안 호출도 결재 장부(가잡기)를 탄다"


def test_rescue_that_the_factcheck_rejects_is_not_offered():
    rpc, _ = run(judge(lambda q: False), proposes)
    assert "rescue" not in rpc.finish["result"] and "해결안" not in rpc.finish["error_message"]


def test_rescue_failure_keeps_the_original_block():
    def broken(topic, claims):
        raise ValueError("bad json")
    rpc, res = run(judge(lambda q: q == NEW_Q), broken)
    assert res["status"] == "blocked" and "rescue" not in rpc.finish["result"]


def test_jev_veto_drops_the_rescue():
    rpc, _ = run(judge(lambda q: q == NEW_Q), proposes, jev=lambda n, s: 0.9)
    assert "rescue" not in rpc.finish["result"]


def test_applied_rescue_reuses_extraction_and_rejudges_with_the_new_question():
    first, _ = run(judge(lambda q: q == NEW_Q), proposes)
    kept = first.finish["result"]["unsaved_evidence"]
    assert kept["factcheck"]["question"] == base.TOPIC["question"]
    rpc = base.FakeRpc(sources=[base.src_row()])
    rpc.context = {"reusable": {"from_request_id": "q0", **kept}}
    j = base.job(topic={**base.TOPIC, "question": NEW_Q, "title": "물 한 방울과 향"})
    res = dd.process_job(j, rpc, base.deps(extract_claims=base.boom, factcheck=judge(lambda q: q == NEW_Q), reframe=base.boom))
    assert res["status"] == "succeeded", rpc.finish
    holds = [p["note"] for n, p in rpc.calls if n == "drinks_develop_hold"]
    assert len(holds) == 1 and holds[0].startswith("AI 사실 확인"), "추출은 다시 사지 않고 새 질문으로 사실 확인만 한다"
    assert rpc.saved_evidence["brief"]["audience_question"] == NEW_Q
