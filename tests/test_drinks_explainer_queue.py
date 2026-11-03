"""설명형 제작 큐(0067) — 지시서·구매 시도·멈춤·실호출 스위치. 돈·네트워크·공급자 호출 0.

두 층이다:
  ① 순수 시험 + 가짜 RPC: 언제나 돈다.
  ② 진짜 SQL(PGlite) + 진짜 워커 + 가짜 공급자로 한 편을 끝까지: web/node_modules 와 ffmpeg 가 있을 때만(scripts/explainer_queue_rehearsal.py).
SQL 규칙 자체는 web/lib/drinks/explainerQueue.db.test.ts 가 본다.
"""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from engine import config
from engine import drinks_explainer as dx
from engine import drinks_explainer_queue as q
from engine import drinks_paid as dpaid
from engine import drinks_produce as dp
from engine.drinks_collect import DbError
from engine.providers import video as pv
from scripts import explainer_lookup as lookup
from scripts import explainer_queue_rehearsal as qr
from scripts import explainer_rehearsal as base

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations" / "0067_drinks_explainer_queue.sql").read_text(encoding="utf-8")
SRC = (ROOT / "engine" / "drinks_explainer_queue.py").read_text(encoding="utf-8")
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
needs_db = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("node") and (ROOT / "web" / "node_modules" / "@electric-sql" / "pglite").exists()), reason="ffmpeg·node·web/node_modules 필요")
PLAN = "11111111-1111-4111-8111-111111111111"
TTS = {i: qr.SCENE_PLAN[i - 1][1] for i in range(1, 10)}


def job(scenes=None, question="왜 안 상할까요?"):
    scenes = scenes if scenes is not None else qr._scenes()
    return {"plan": {"scenes": scenes}, "topic": {"question": question}, "brief": {"audience_question": "왜"}, "sources": [],
            "claims": [{"claim_id": "c1", "text": "물", "source_refs": [{"snapshot_id": "s", "original_quote": qr.QUOTE}]}]}


# ── 장면별 지시서 ──────────────────────────────────────────────

def test_directive_matches_the_48_second_plan_and_quote():
    d = q.build_directive(PLAN, job(), qr.visual_claims(qr._scenes()), TTS, provider="omni")
    assert [s["clip_sec"] for s in d["slots"]] == [4, 8, 8, 6, 6, 8, 8, 8, 8], "§3-6-2 의 자산 길이"
    assert sum(s["clip_sec"] for s in d["slots"]) == 64
    assert [s["candidates_planned"] for s in d["slots"]] == [1, 2, 1, 1, 1, 1, 1, 1, 1], "후보 2발은 첫 도해(훅) 하나에만"
    assert d["hook_scene"] == 2 and 47.5 < d["final_ms"] / 1000 < 48.5
    assert d["estimate"]["estimate_usd"] == dx.quote_explainer("omni")["estimate_usd"] == 7.95, "§3-7 과 같은 금액"
    assert d["estimate"]["suggested_cap_usd"] == dx.quote_explainer("omni")["cap_usd"] == 8.9
    assert [s["boundary_in"] for s in d["slots"]] == ["loop", "cut_to_mechanism", "cut", "cut_to_mechanism", "match", "match", "cut_to_mechanism", "cut_to_mechanism", "match"]
    assert [s["continuity_ref"] for s in d["slots"]][4:6] == [4, 5]
    for s in d["slots"]:
        assert s["slot_id"] == f"{PLAN}:A{s['n']}"
        assert s["visual_claim_ko"] and s["forbidden_misreading"] and s["depiction_label"], "시각 주장표가 지시서에 실린다"
        assert s["min_src_ms"] == s["last_src_ms"] + config.DRINKS_EXPLAINER_MIN_SRC_MARGIN_MS
        assert s["clip_sec"] * 1000 >= s["last_src_ms"] + config.DRINKS_EXPLAINER_PLAN_MARGIN_MS
        assert s["clip_model"] == config.DRINKS_EXPLAINER_OMNI_MODEL, "종료된 Veo 미리보기 모델을 쓰지 않는다"
        assert s["forbidden_misreading"] in s["visual_prompt"], "금지할 오해는 프롬프트 부정어로도 쓴다(§3-4)"


@pytest.mark.parametrize("change,table,tts,code", [
    ("no_table", None, None, "visual_claims_missing"),
    ("no_motion", "auto", None, "motion_prompt_missing"),
    ("no_visual", "auto", None, "visual_prompt_missing"),
    ("text_card", "auto", None, "explainer_still_card"),
    ("long_scene", "auto", {1: 3600, 2: 11000}, "scene_too_long"),
    ("short_film", "auto", dict.fromkeys(range(1, 10), 3000), "duration_out_of_range"),
])
def test_directive_stops_before_any_purchase(change, table, tts, code):
    scenes = qr._scenes()
    if change == "no_motion":
        scenes[3]["motion_prompt"] = " "
    elif change == "no_visual":
        scenes[3]["visual_prompt"] = ""
    elif change == "text_card":
        scenes[3]["visual_role"] = "text_card"
    claims = None if table is None else qr.visual_claims([dict(s, visual_role="reality" if s["visual_role"] == "text_card" else s["visual_role"]) for s in scenes])
    times = {**TTS, **(tts or {})}
    with pytest.raises(dx.ExplainerStop) as e:
        q.build_directive(PLAN, job(scenes), claims, times, provider="omni")
    found = {p["code"] for p in e.value.problems} | {e.value.code}
    assert code in found, found


def test_hook_text_falls_back_then_stops_rather_than_cutting():
    assert q.pick_hook_text({"question": "왜 안 상할까요?"}, qr._scenes()) == "왜 안 상할까요?"
    long = "아주아주 긴 질문이 한 줄에 절대로 들어가지 않을 만큼 길게 이어지는 소재 질문 하나입니다 정말로요"
    assert q.pick_hook_text({"question": long}, [{"narration": "짧은 말"}]) == "짧은 말"
    with pytest.raises(dx.ExplainerStop) as e:
        q.pick_hook_text({"question": long}, [{"narration": long}])
    assert e.value.code == "hook_text_overflow"


def test_hook_beat_flashes_forward_from_the_mechanism_clip():
    beats = q.build_beats(qr._scenes(), PLAN, TTS, 2)
    first = beats[0].shots
    assert first[0].asset_id == dx.slot_id(PLAN, 2) and first[0].boundary == "loop" and first[0].raw_ms == config.DRINKS_EXPLAINER_HOOK_RAW_MS
    assert first[0].src_start_ms == 7500 - 300 - 1800, "§3-6: 사용 끝 조금 앞의 결정적 구간"
    assert first[1].asset_id == dx.slot_id(PLAN, 1) and first[1].boundary == "flash_forward"
    assert beats[-1].tail_ms == config.DRINKS_EXPLAINER_TAIL_MS


def test_continuity_must_point_backwards():
    scenes = qr._scenes()
    scenes[1]["continuity"] = "ref:5"
    with pytest.raises(dx.ExplainerStop) as e:
        q.scene_boundary(scenes, 2)
    assert e.value.code == "invalid_continuity"


# ── 한 시도(buy_clip_attempt) ──────────────────────────────────

class Rpc:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn in self.fail:
            raise self.fail[fn]
        return {"drinks_hold_spend": {"hold_id": "h1"}, "drinks_explainer_open_attempt": {"attempt_id": "c#a1", "idempotency_key": "k" * 64},
                "drinks_register_generated": {"asset_id": "a1"}}.get(fn, {})

    def names(self):
        return [c[0] for c in self.calls]

    def events(self):
        return [p["to_state"] for fn, p in self.calls if fn == "drinks_explainer_attempt_event"]

    def settles(self):
        return [p for fn, p in self.calls if fn == "drinks_settle_spend"]


class Storage:
    def put(self, path, key, mime):
        return f"local:{key}"


class Adapter:
    def __init__(self, exc=None, make=None):
        self.exc, self.make, self.n = exc, make, 0

    def clip(self, item, out, start, *, approval_id, idempotency_key):
        self.n += 1
        assert idempotency_key == "k" * 64 and approval_id == "ap"
        if self.exc:
            raise self.exc
        self.make(out)
        return SimpleNamespace(request_id="r1", billing_unit="tokens", billed_units=5792.0 * 4)


def item():
    return dpaid.clip_item(1, "reality", "the camera moves", "scene-01-reality", "x" * 64, clip_sec=4, candidate_id="P:A1#c1", provider="omni", resolution="720p")


def _buy(rpc, adapter, tmp_path):
    return dpaid.buy_clip_attempt(item(), rpc=rpc, storage=Storage(), approval_id="ap", out_dir=str(tmp_path), start_image="s.png", adapter=adapter, lease={"job_id": "j", "lease_token": "t"})


def test_attempt_row_exists_before_the_provider_is_called(tmp_path):
    order = []

    class Spy(Rpc):
        def __call__(self, fn, p):
            order.append(p.get("to_state") or fn)
            return super().__call__(fn, p)

    class A(Adapter):
        def clip(self, *a, **k):
            order.append("PROVIDER")
            raise pv.ExplainerNotSent("429")
    with pytest.raises(dpaid.PaidError):
        _buy(Spy(), A(), tmp_path)
    assert order[:4] == ["drinks_hold_spend", "drinks_explainer_open_attempt", "generating", "PROVIDER"]


def test_not_sent_releases_the_hold_and_closes_unbilled(tmp_path):
    rpc = Rpc()
    with pytest.raises(dpaid.PaidError) as e:
        _buy(rpc, Adapter(pv.ExplainerNotSent("429")), tmp_path)
    assert e.value.code == "attempt_failed_unbilled"
    assert rpc.events() == ["generating", "failed_unbilled"]
    assert [s["outcome"] for s in rpc.settles()] == ["released"]


@pytest.mark.parametrize("exc", [pv.ExplainerOutcomeUnknown("timeout"), httpx.ReadTimeout("t"), RuntimeError("죽음")])
def test_unknown_outcome_keeps_the_hold_and_never_retries(tmp_path, exc):
    rpc = Rpc()
    a = Adapter(exc)
    with pytest.raises(dpaid.PaidError) as e:
        _buy(rpc, a, tmp_path)
    assert e.value.code == "unknown_billed" and a.n == 1
    assert rpc.events() == ["generating", "unknown_billed"]
    assert rpc.settles() == [], "가잡기를 유지한다 — 운영자가 닫을 때 확정·해제된다"


def test_bad_file_is_billed_at_estimate(tmp_path):
    rpc = Rpc()
    with pytest.raises(dpaid.PaidError) as e:
        _buy(rpc, Adapter(pv.ExplainerBilledBadFile("깨짐")), tmp_path)
    assert e.value.code == "attempt_failed_billed"
    assert rpc.events() == ["generating", "failed_billed"]
    s = rpc.settles()[0]
    assert s["outcome"] == "settled" and s["actual_usd"] == item().est_usd


def test_budget_refusal_calls_nothing_and_uses_no_attempt(tmp_path):
    rpc = Rpc({"drinks_hold_spend": DbError("budget_exceeded", "넘음")})
    a = Adapter(make=lambda o: None)
    with pytest.raises(DbError):
        _buy(rpc, a, tmp_path)
    assert a.n == 0 and rpc.names() == ["drinks_hold_spend"]


def test_attempt_refusal_releases_the_hold(tmp_path):
    rpc = Rpc({"drinks_explainer_open_attempt": DbError("unknown_billed_open", "닫으세요")})
    a = Adapter(make=lambda o: None)
    with pytest.raises(DbError):
        _buy(rpc, a, tmp_path)
    assert a.n == 0 and [s["outcome"] for s in rpc.settles()] == ["released"]


@needs_ffmpeg
def test_success_records_measured_length_and_token_cost(tmp_path):
    rpc = Rpc()
    b = _buy(rpc, Adapter(make=lambda o: base.make_fake_clip(o, 3000)), tmp_path)
    assert rpc.events() == ["generating", "received", "probed", "stored"]
    reg = next(p for fn, p in rpc.calls if fn == "drinks_register_generated")
    assert 2950 <= reg["asset"]["duration_ms"] <= 3050, "4초를 주문해도 3초가 왔으면 3초로 적는다(E5)"
    assert reg["asset"]["provenance"]["requested_ms"] == 4000 and reg["asset"]["provenance"]["provider"] == "omni" and reg["asset"]["provenance"]["provider_request_id"] == "r1"
    assert b.cost_usd == pytest.approx(5792 * 4 * 17.5 / 1e6 + 1120 * 1.5 / 1e6, abs=1e-4)


def test_candidate_only():
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.buy_clip_attempt(dpaid.clip_item(1, "reality", "m", "s", "x" * 64, clip_sec=4), rpc=Rpc(), storage=Storage(), approval_id="ap", out_dir=".", start_image="s", adapter=Adapter())
    assert e.value.code == "invalid_order"


# ── 실호출 스위치 ──────────────────────────────────────────────

GOOD = {"status": "open", "expired": False}


def test_live_adapter_needs_switch_and_open_approval_and_key(monkeypatch):
    a = dpaid.LiveAdapter()
    assert config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED is False, "기본은 꺼짐"
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    with pytest.raises(dpaid.PaidError) as e:
        a.check_ready(GOOD)
    assert e.value.code == "provider_send_disabled"
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", True)
    # 사전 검증(무료 GET)은 네트워크다 — 시험에서는 가짜로 바꾼다. 아래에서 실패도 한 번 본다.
    pre = {"ok": True}
    monkeypatch.setattr(pv, "omni_preflight", lambda client=None: pv.OmniPreflight(pre["ok"], config.DRINKS_EXPLAINER_OMNI_MODEL, "시험: 모델 없음"))
    for bad in (None, {}, {"status": "closed", "expired": False}, {"status": "open", "expired": True}):
        with pytest.raises(dpaid.PaidError) as e:
            a.check_ready(bad)
        assert e.value.code == "approval_closed"
    a.check_ready(GOOD)
    pre["ok"] = False
    with pytest.raises(dpaid.PaidError) as e:
        a.check_ready(GOOD)
    assert e.value.code == "provider_preflight_failed" and "시험: 모델 없음" in e.value.message
    pre["ok"] = True
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.LiveAdapter("veo_fast").check_ready(GOOD)
    assert e.value.code == "provider_not_wired"
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key=""))
    with pytest.raises(dpaid.PaidError) as e:
        a.check_ready(GOOD)
    assert e.value.code == "api_key_missing"


def test_live_image_path_is_also_behind_the_switch(monkeypatch):
    monkeypatch.setattr(dpaid, "_generate", lambda *a: pytest.fail("그림 공급자가 불리면 안 된다"))
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.LiveAdapter().image(dpaid.image_item(1, "reality", "x"), "o.png", None)
    assert e.value.code == "provider_send_disabled"


def test_buy_job_with_switch_off_touches_nothing(monkeypatch, tmp_path):
    """워커 수준: 스위치가 꺼지면 가잡기·시도·공급자 전부 0. 작업은 실패로 닫힌다."""
    for name in ("generate_explainer_clip", "send_explainer_request", "generate_clip", "_veo_i2v"):
        monkeypatch.setattr(pv, name, lambda *a, **k: pytest.fail(f"{name} 가 불리면 안 된다"))
    calls = []

    def rpc(fn, p):
        calls.append(fn)
        if fn == "drinks_explainer_job_context":
            return {"episode": {"state": "approved", "directive": {"slots": [{"n": 1}]}}, "approval": GOOD, "slots": []}
        if fn == "drinks_heartbeat_render":
            return {"renderable": True}
        return {"status": p.get("outcome"), "error_code": p.get("error_code")}
    res = dp.process_job({"job_id": "j1", "lease_token": "t", "renderer": "explainer_buy", "plan_revision_id": PLAN, "spend_approval_id": "ap", "format": "video", "plan": {"scenes": []}, "topic": {}},
                         rpc, dp.Storage("local", str(tmp_path)))
    assert res["status"] == "failed" and res["error_code"] == "provider_send_disabled"
    assert not {"drinks_hold_spend", "drinks_explainer_open_attempt", "drinks_explainer_attempt_event", "drinks_find_generated"} & set(calls)
    assert "drinks_explainer_finish_job" in calls


def test_send_refused_when_switch_off_and_client_untouched():
    class No:
        def post(self, *a, **k):
            raise AssertionError("전송되면 안 된다")
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="m", clip_sec=8)
    with pytest.raises(pv.ExplainerSendRefused):
        pv.generate_explainer_clip(clip, "o.mp4", provider="omni", approval_id="ap", idempotency_key="k", client=No())
    with pytest.raises(pv.ExplainerSendRefused):
        pv.generate_explainer_clip(clip, "o.mp4", provider="veo_fast", approval_id="ap", idempotency_key="k", client=No())


class Resp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


MODEL_OK = Resp(200, {"name": f"models/{config.DRINKS_EXPLAINER_OMNI_MODEL}", "displayName": "Gemini Omni Flash", "supportedGenerationMethods": ["interactions"]})


class Client:
    """가짜 HTTP. GET(사전 검증·조회)과 POST(생성)를 따로 센다 — 생성은 한 번만 보내야 한다."""

    def __init__(self, resp=None, exc=None, model=MODEL_OK):
        self.resp, self.exc, self.n, self.gets, self.model = resp, exc, 0, 0, model

    def get(self, url, headers=None, params=None):
        self.gets += 1
        assert "key=" not in url, "키를 주소에 싣지 않는다"
        return self.model

    def post(self, url, headers, json):
        self.n += 1
        if self.exc:
            raise self.exc
        return self.resp


def interaction(video_b64=None, *, status="completed", tokens=23168, iid="int-1", uri=None):
    """문서 모양의 Interaction 자원(steps[].content[].type=video)."""
    content = []
    if video_b64 is not None or uri:
        content.append({"type": "video", "mime_type": "video/mp4", **({"data": video_b64} if video_b64 is not None else {}), **({"uri": uri} if uri else {})})
    return {"id": iid, "object": "interaction", "status": status, "model": config.DRINKS_EXPLAINER_OMNI_MODEL,
            "steps": [{"type": "model_output", "content": content}], "usage": {"total_output_tokens": tokens, "output_tokens_by_modality": [{"modality": "video", "tokens": tokens}]}}


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", True)
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))


@pytest.mark.parametrize("client,exc", [
    (Client(Resp(429, text="rate")), pv.ExplainerNotSent),
    (Client(Resp(400, text="bad")), pv.ExplainerNotSent),
    (Client(Resp(500, text="boom")), pv.ExplainerOutcomeUnknown),
    (Client(Resp(408, text="late")), pv.ExplainerOutcomeUnknown),
    (Client(exc=httpx.ReadTimeout("TEST-not-real 포함 문장")), pv.ExplainerOutcomeUnknown),
    (Client(Resp(200)), pv.ExplainerOutcomeUnknown),
    (Client(Resp(200, {"id": "x", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "거절"}]}]})), pv.ExplainerOutcomeUnknown),
    (Client(Resp(200, {"id": "x", "status": "failed", "steps": []})), pv.ExplainerOutcomeUnknown),
    (Client(Resp(200, interaction(status="in_progress"))), pv.ExplainerOutcomeUnknown),
    (Client(Resp(200, {"id": "x", "outputs": [{"type": "video", "data": "QUJD"}]})), pv.ExplainerOutcomeUnknown),   # 옛 가정 모양 — 이제 영상으로 읽지 않는다
    (Client(Resp(200, interaction(base64.b64encode(b"garbage" * 40).decode()))), pv.ExplainerBilledBadFile),
])
def test_failures_are_sorted_by_whether_money_went(live, tmp_path, client, exc):
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="m", clip_sec=8)
    with pytest.raises(exc) as e:
        pv.generate_explainer_clip(clip, str(tmp_path / "o.mp4"), provider="omni", approval_id="ap", idempotency_key="k", client=client)
    assert client.n == 1, "재시도하지 않는다"
    assert client.gets == 1, "생성 전에 무료 사전 검증 한 번"
    assert "TEST-not-real" not in str(e.value), "예외 문장에 비밀이 실리지 않는다"


@pytest.mark.parametrize("model_resp,reason", [
    (Resp(404, text="nf"), "404"),
    (Resp(200, {"name": "models/gemini-omni-2-flash"}), "이름이 다릅니다"),
    (Resp(503, text="down"), "503"),
])
def test_preflight_failure_refuses_before_sending(live, tmp_path, model_resp, reason):
    client = Client(Resp(200, interaction("QUJD")), model=model_resp)
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="m", clip_sec=8)
    with pytest.raises(pv.ExplainerNotSent) as e:
        pv.generate_explainer_clip(clip, str(tmp_path / "o.mp4"), provider="omni", approval_id="ap", idempotency_key="k", client=client)
    assert client.n == 0 and client.gets == 1 and reason in str(e.value)


def test_omni_request_shape_matches_the_documented_interactions_api():
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="the glass tilts", clip_sec=8, end_image_b64="REVG")
    req = pv.build_omni_request(clip)
    b = req.body
    assert req.url.endswith("/v1beta/interactions") and b["model"] == config.DRINKS_EXPLAINER_OMNI_MODEL
    assert [p["type"] for p in b["input"]] == ["image", "image", "text"] and b["input"][0] == {"type": "image", "mime_type": "image/png", "data": "QUJD"}
    assert b["generation_config"] == {"video_config": {"task": "image_to_video"}}, "첫 그림이 시작 프레임[문서]"
    assert b["response_format"] == {"type": "video", "aspect_ratio": "9:16", "resolution": "720p", "delivery": "inline", "duration": "8s"}
    assert b["background"] is False and b["store"] is True and b["stream"] is False, "store 를 끄면 결과 불명을 조회할 수 없다"
    assert "seed" not in str(b) and "negative" not in str(b).lower(), "문서에 없는 칸은 보내지 않는다"
    assert "8 seconds" in b["input"][-1]["text"], "길이는 문장에도 말한다(duration 형식이 미검증)"
    assert pv.build_omni_fetch_request("abc").url.endswith("/v1beta/interactions/abc") and pv.build_omni_fetch_request("abc").method == "GET"
    with pytest.raises(pv.ExplainerProviderError):
        pv.build_omni_fetch_request("a/b")


def test_fetch_interaction_corrects_unknown_outcome(live):
    client = Client(model=Resp(200, interaction("QUJD", iid="int-9")))
    parsed = pv.fetch_omni_interaction("int-9", approval_id="ap", client=client)
    assert parsed.request_id == "int-9" and parsed.video_bytes == b"ABC" and parsed.billed_units == 23168.0 and client.n == 0
    with pytest.raises(pv.ExplainerSendRefused):
        pv.fetch_omni_interaction("int-9", approval_id="", client=client)


def test_unknown_outcome_keeps_the_provider_id_when_it_got_one(live, tmp_path):
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="the glass tilts", clip_sec=8)
    client = Client(Resp(200, interaction(status="in_progress", iid="int-7")))
    with pytest.raises(pv.ExplainerOutcomeUnknown) as e:
        pv.generate_explainer_clip(clip, str(tmp_path / "a.mp4"), provider="omni", approval_id="ap", idempotency_key="k", client=client)
    assert e.value.request_id == "int-7"


def test_lookup_lists_unknown_and_never_calls_provider_without_an_id():
    status = {"slots": [{"candidates": [{"attempts": [
        {"attempt_id": "c#a1", "state": "unknown_billed", "provider": "omni", "provider_request_id": None, "approval_id": "ap", "est_usd": 1.0},
        {"attempt_id": "c#a2", "state": "unknown_billed", "provider": "omni", "provider_request_id": "int-9", "approval_id": "ap", "est_usd": 1.0},
        {"attempt_id": "c#a3", "state": "stored", "provider": "omni", "provider_request_id": "int-8", "approval_id": "ap"}]}]}]}
    rows = lookup.unknown_attempts(status)
    assert [r["attempt_id"] for r in rows] == ["c#a1", "c#a2"]
    calls = []

    def fetch(iid, *, approval_id):
        calls.append((iid, approval_id))
        return pv.ExplainerParsed(provider="omni", request_id=iid, billing_unit="tokens", billed_units=23168.0, video_bytes=b"ABC")

    no_id = lookup.lookup_one(rows[0], fetch)
    assert no_id["outcome"] == "no_id" and calls == [], "ID 가 없으면 부르지 않는다"
    found = lookup.lookup_one(rows[1], fetch)
    assert calls == [("int-9", "ap")] and found["outcome"] == "completed" and found["video_bytes"] == 3
    assert found["usd"] == round(23168 * 17.5 / 1e6 + 1120 * 1.5 / 1e6, 4)


def test_lookup_reports_not_retrievable_and_in_progress():
    row = {"attempt_id": "c#a2", "provider": "omni", "provider_request_id": "int-9", "approval_id": "ap", "est_usd": 1.0}

    def gone(iid, *, approval_id):
        raise pv.ExplainerNotSent("omni 404: not found")

    def running(iid, *, approval_id):
        return pv.ExplainerParsed(provider="omni", request_id=iid, billing_unit="tokens", billed_units=None, done=False)

    assert lookup.lookup_one(row, gone)["outcome"] == "not_retrievable"
    assert lookup.lookup_one(row, running)["outcome"] == "in_progress"


def test_lookup_script_has_no_db_write_and_no_switch():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "explainer_lookup.py").read_text(encoding="utf-8")
    assert "drinks_explainer_close_unknown" not in src and "drinks_explainer_attempt_event" not in src and "drinks_settle_spend" not in src, "닫기는 운영자 몫이다"
    assert "PROVIDER_SEND_ENABLED =" not in src and "os.environ[" not in src, "스위치를 코드가 켜지 않는다"


@needs_ffmpeg
def test_adapter_end_to_end_with_stub_client(live, tmp_path):
    src = tmp_path / "s.mp4"
    base.make_fake_clip(str(src), 4000)
    client = Client(Resp(200, interaction(base64.b64encode(src.read_bytes()).decode(), tokens=23168)))
    clip = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="m", clip_sec=4)
    out = pv.generate_explainer_clip(clip, str(tmp_path / "o.mp4"), provider="omni", approval_id="ap", idempotency_key="k", client=client)
    assert out.request_id == "int-1" and out.billed_units == 23168.0 and 3950 <= out.measured_ms <= 4050


# ── 경로 규칙(정적) ────────────────────────────────────────────

def _fn_body(src: str, name: str) -> str:
    m = re.search(rf"^def {name}\(.*?(?=^def |^class |^[A-Z_]+ = )", src, re.S | re.M)
    assert m, name
    return m.group(0)


def test_render_function_has_no_way_to_buy():
    body = _fn_body(SRC, "_run_render")
    code = "\n".join(l.split("#", 1)[0] for l in body.splitlines() if not l.strip().startswith('"""'))
    for bad in ("adapter", "dpaid.buy", "buy_clip_attempt", "drinks_hold_spend", "providers"):
        assert bad not in code, bad
    collect = _fn_body(SRC, "_collect_selected")
    assert "fetch_selected" in collect and "dpaid.buy" not in collect


def test_explainer_path_never_touches_the_old_still_renderer():
    assert "render_video" not in SRC and "VIDEO_FALLBACKS" not in SRC and "send_explainer_request" not in SRC
    assert "generate_clip" not in SRC and "generate_image" not in SRC
    produce = (ROOT / "engine" / "drinks_produce.py").read_text(encoding="utf-8")
    assert produce.index('startswith("explainer_")') < produce.index("render_video(job", produce.index("def process_job")), "설명형 분기가 옛 렌더보다 먼저다"


def test_ci_worker_has_no_switch_and_no_key():
    wf = (ROOT / ".github" / "workflows" / "drinks-produce.yml").read_text(encoding="utf-8")
    for key in ("DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", "GEMINI", "schedule:"):
        assert key not in wf, key


def test_screen_cannot_reach_worker_functions_or_set_auto_verdict():
    actions = (ROOT / "web" / "lib" / "drinks" / "actions.ts").read_text(encoding="utf-8")
    for fn in ("drinks_explainer_open_attempt", "drinks_explainer_attempt_event", "drinks_explainer_plan_slot", "drinks_explainer_save_directive", "drinks_explainer_episode_event", "drinks_explainer_finish_job", "drinks_explainer_sweep_stale"):
        assert fn not in actions, fn
    assert "delete p.auto_verdict" in actions and 'p.selected_by = "operator"' in actions and 'p.closed_by = "operator"' in actions
    route = (ROOT / "web" / "app" / "api" / "drinks" / "route.ts").read_text(encoding="utf-8")
    assert '"explainer_request_buy"' not in route.split("//")[0], "구매는 워크플로를 깨우지 않는다"
    code = "\n".join(l for l in route.splitlines() if not l.strip().startswith("//"))
    assert "explainer_request_buy" not in code


def test_sql_matches_config_and_python_states():
    code = "\n".join(l.split("--", 1)[0] for l in SQL.splitlines())
    flow = re.search(r"array\['plan_draft'.*?\]::text\[\]", code, re.S).group(0)
    assert re.findall(r"'(\w+)'", flow) == list(dx.EPISODE_FLOW)
    rend = re.search(r"check \(renderer in \((.*?)\)\)", code, re.S).group(1)
    assert set(re.findall(r"'(\w+)'", rend)) == {"local", "paid", *config.DRINKS_EXPLAINER_RENDERERS}
    assert "'drinks-explainer-v1'" in code and config.DRINKS_EXPLAINER_RENDERER_VERSION == "drinks-explainer-v1"
    bnd = re.search(r"boundary_in in \((.*?)\)", code).group(1)
    assert set(re.findall(r"'(\w+)'", bnd)) == set(config.DRINKS_EXPLAINER_BOUNDARY_KINDS)
    assert "운영 적용은 따로 결재" in SQL
    low = code.lower()
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", low)
    assert "create policy" not in low
    assert "alter table drink_explainer_episodes enable row level security" in low
    for bad in ("worker_id", "http", "net.http"):
        assert bad not in low, "SQL 이 공급자를 부르지 않는다"


# ── 진짜 SQL + 진짜 워커 + 가짜 공급자로 끝까지 ─────────────────────

@pytest.fixture(scope="module")
def report(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("node") and (ROOT / "web" / "node_modules" / "@electric-sql" / "pglite").exists()):
        pytest.skip("ffmpeg·node·web/node_modules 필요")
    return qr.run(tmp_path_factory.mktemp("explainer-queue-한글경로"))


@needs_db
def test_rehearsal_reaches_ready_to_publish_with_real_sql(report):
    f = report["full_episode"]
    assert report["passed"], report["checks"]
    assert f["states"][-1] == "ready_to_publish"
    assert f["slots"] == 9 and f["provider_calls"] == 10, "슬롯 9 + 훅 두 번째 후보 1"
    assert f["fake_cost_usd"] == pytest.approx(f["directive_estimate"]["estimate_usd"], abs=0.02)
    assert f["fake_cost_usd"] <= f["cap_usd"]
    assert 40_000 <= f["final_duration_ms"] <= 55_000
    assert f["auto_qa"]["blocks"] == [] and f["cuts_all_clip"] and f["video_fallbacks"] == []
    assert sum(s["clips_usd"] + s["image_usd"] for s in map(lambda x: {k: float(v) for k, v in x.items()}, f["slot_costs"])) == pytest.approx(f["fake_cost_usd"], abs=0.01), "슬롯별 합계 = 결재 원장"
    assert {r["stop"] for r in f["rounds"]} >= {"awaiting_selection", "awaiting_review"}, "이어 그리는 장면은 앞 슬롯 선택을 기다린다"
    assert f["match_refs"], "이어 그리기 시작 그림은 앞 클립 마지막 프레임을 참고한다"
    assert f["continuity"] and all("color_distance" in c for c in f["continuity"]), "연속성 숫자를 기록한다(차단 아님)"


@needs_db
@pytest.mark.parametrize("i,code", [(0, "clip_missing"), (1, "clip_corrupt"), (2, "clip_short")])
def test_forced_stops_block_the_whole_episode_and_buy_nothing(report, i, code):
    c = report["full_episode"]["forced_render_stops"][i]
    assert c["code"] == code and c["state"] == "blocked_assets" and c["job"] == "failed"
    assert c["new_holds"] == 0 and c["new_manifests"] == 0 and c["paid_or_network_hits"] == []


@needs_db
def test_cap_and_unknown_and_no_pass_and_switch_stop(report):
    b, u, n, s = report["budget"], report["unknown_billed"], report["no_pass"], report["switch_off"]
    assert b["code"] == "budget_exceeded" and b["state"] == "blocked_budget" and b["provider_calls"] == 0 and b["attempts"] == 0 and b["committed_usd"] <= b["cap_usd"]
    assert u["state"] == "unknown_billed" and u["provider_calls"] == 1 and u["rebuy_while_unknown"] == "unknown_billed_open" and u["held_while_unknown"] > 0
    assert u["state_after_close"] == "buying" and u["held_after_close"] == 0 and u["spent_after_close"] >= 0.41
    assert n["state"] == "blocked_no_pass" and n["slot_status"] == "no_pass" and n["auto_blocks"] == ["clip_short"] and n["provider_calls"] == 3
    assert s["code"] == "provider_send_disabled" and s["holds"] == 0 and s["attempts"] == 0 and s["provider_hits"] == []
    assert report["old_render"]["local"] == "not_renderable" and report["old_render"]["jobs"] == 0


@needs_db
def test_can_transition_matches_sql():
    db = qr.PgRpc()
    try:
        states = list(dx.EPISODE_FLOW) + list(dx.FAILURE_STATES)
        for a in states:
            rows = db.sql("select s as to_state, drinks_explainer_can_transition($1, s) as ok from unnest($2::text[]) s", [a, states])
            for r in rows:
                assert r["ok"] is dx.can_transition(a, r["to_state"]), (a, r["to_state"])
    finally:
        db.close()
