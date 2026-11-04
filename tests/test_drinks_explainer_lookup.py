"""결과 모름 시도의 interaction id 보존과 조회 판정(2026-11-03). 0원 — 가짜 HTTP·가짜 조회만."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine import config
from engine import drinks_explainer_lookup as lk
from engine import drinks_paid as dpaid
from engine.providers import video as pv
from tests.test_drinks_explainer_queue import Adapter, Client, Resp, Rpc, _buy, interaction, live  # noqa: F401 — live 는 fixture


def test_in_progress_response_carries_the_interaction_id(live, tmp_path):
    """진행 중 응답의 id 가 예외에 실려야 시도 행에 남는다 — 전에는 문장에만 있었다."""
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="the glass tilts", clip_sec=8)
    client = Client(Resp(200, interaction(status="in_progress", iid="int-77")))
    with pytest.raises(pv.ExplainerOutcomeUnknown) as e:
        pv.generate_explainer_clip(clip, str(tmp_path / "o.mp4"), provider="omni", approval_id="ap", idempotency_key="k" * 64, client=client)
    assert e.value.request_id == "int-77" and client.n == 1


def test_unknown_attempt_records_the_request_id(tmp_path):
    rpc = Rpc()
    with pytest.raises(dpaid.PaidError):
        _buy(rpc, Adapter(pv.ExplainerOutcomeUnknown("진행 중", request_id="int-77")), tmp_path)
    ev = [p for fn, p in rpc.calls if fn == "drinks_explainer_attempt_event" and p["to_state"] == "unknown_billed"]
    assert ev and ev[0]["provider_request_id"] == "int-77"


def test_unknown_without_id_records_none(tmp_path):
    rpc = Rpc()
    with pytest.raises(dpaid.PaidError):
        _buy(rpc, Adapter(RuntimeError("끊김")), tmp_path)
    ev = [p for fn, p in rpc.calls if fn == "drinks_explainer_attempt_event" and p["to_state"] == "unknown_billed"]
    assert ev[0]["provider_request_id"] is None


ROW = {"attempt_id": "P:A1#c1#a1", "state": "unknown_billed", "provider": "omni", "provider_request_id": "int-9", "approval_id": "ap"}


def test_completed_lookup_suggests_billed_with_token_price():
    seen = []
    v = lk.judge_attempt(ROW, lambda rid, ap: seen.append((rid, ap)) or SimpleNamespace(done=True, billed_units=23168.0))
    assert seen == [("int-9", "ap")]
    assert v.verdict == "completed" and v.suggest == "billed"
    assert v.suggested_usd == dpaid.omni_usd_from_tokens(23168.0) == round(23168 * 17.5 / 1e6 + 1120 * 1.5 / 1e6, 4)


def test_in_progress_lookup_says_wait():
    v = lk.judge_attempt(ROW, lambda rid, ap: SimpleNamespace(done=False, billed_units=None))
    assert v.verdict == "in_progress" and v.suggest == "wait"


def test_provider_failure_never_suggests_void():
    def boom(rid, ap):
        raise pv.ExplainerProviderError("status=failed")
    v = lk.judge_attempt(ROW, boom)
    assert v.verdict == "provider_failed" and v.suggest == "check_invoice", "실패 생성의 청구 여부는 미검증 — 없던 일로 단정하지 않는다"


def test_switch_off_sends_nothing(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", False)
    v = lk.judge_attempt(ROW, lambda rid, ap: pv.fetch_omni_interaction(rid, approval_id=ap, client=Client()))
    assert v.verdict == "lookup_failed" and v.suggest == "none"


@pytest.mark.parametrize("row,verdict", [
    ({**ROW, "provider_request_id": None}, "no_request_id"),
    ({**ROW, "state": "stored"}, "not_unknown"),
    ({**ROW, "provider": "veo_fast"}, "lookup_failed"),
])
def test_rows_that_cannot_be_looked_up_do_not_call_the_provider(row, verdict):
    def never(rid, ap):
        raise AssertionError("조회하면 안 된다")
    assert lk.judge_attempt(row, never).verdict == verdict
