"""주류 유료 생성(결재 안에서만) — 주문 항목·프롬프트·사기 흐름·워커 연결. 네트워크·유료 호출 없음."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine import config
from engine import drinks_paid as dpaid
from engine import drinks_produce as dp

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "docs" / "drinks-pilot" / "gi-sake-v1.json").read_text(encoding="utf-8"))
SQL = (ROOT / "supabase" / "migrations" / "0054_drinks_spend.sql").read_text(encoding="utf-8")


def test_prices_match_sql_and_engine_price_table():
    lim = {k: float(v) for k, v in re.findall(r"'(price_[a-z_]+)', ([0-9.]+)", SQL)}
    assert lim == {f"price_{k}": v for k, v in config.DRINKS_PAID_PRICES.items()}
    assert config.PRICING[config.image_model_for("MECHANISM")]["image_standard"] == config.DRINKS_PAID_PRICES["image_mechanism"]
    assert config.PRICING[config.image_model_for("REALITY")]["image_standard"] == config.DRINKS_PAID_PRICES["image_reality"]
    assert config.PRICING[config.VEO_MODEL]["video_720p_per_sec"] == config.DRINKS_PAID_PRICES["video_per_sec"]
    assert "cap_usd <= 10" in SQL and "'max_cap_usd', 10" in SQL
    # 화면 예상이 '이미 산 장면'을 알아보는 항목 이름 — 워커와 SQL 이 같은 꼴을 쓴다
    assert "'scene-' || lpad(sc.position::text, 2, '0') || '-' || sc.role" in SQL
    assert dpaid.image_item(3, "mechanism", "x").item_key == "scene-03-mechanism"


def test_image_item_uses_locked_photo_style_and_no_brand_clause():
    it = dpaid.image_item(2, "mechanism", "Isometric diorama of a brewery")
    assert it.model == config.image_model_for("MECHANISM") and it.est_usd == 0.134
    assert config.DRINKS_PRODUCT_CLAUSE in it.prompt
    assert config.BURN_IN_NEGATIVE_PROMPT in it.prompt
    assert config.PHOTO_GLOBAL_STYLE in it.prompt
    assert config.VISUAL_ROLE_NEGATIVE["MECHANISM"] in it.prompt
    r = dpaid.image_item(1, "reality", "A shelf of bottles")
    assert r.model == config.image_model_for("REALITY") and r.est_usd == 0.039
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.image_item(3, "text_card", "x")
    assert e.value.code == "invalid_order"
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.image_item(3, "reality", "  ")
    assert e.value.code == "visual_prompt_missing"


def test_build_items_skips_text_cards_and_chains_references():
    items = dpaid.build_image_items(SPEC["scenes"])
    assert [i.position for i in items] == [1, 2, 3, 4, 5], "정리 카드(6·7번)는 사지 않는다"
    s3 = items[2]
    assert s3.ref_item == "scene-01-reality" and s3.prompt.startswith(config.SEQUENCE_REFERENCE_INSTRUCTION[:30])
    # 같은 장면은 언제 만들어도 같은 해시(시험 스크립트와 워커가 같은 그림을 다시 사지 않는다)
    assert [i.prompt_hash for i in dpaid.build_image_items(SPEC["scenes"])] == [i.prompt_hash for i in items]
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.build_image_items(SPEC["scenes"], [3])
    assert e.value.code == "invalid_order", "이어 그릴 1번 그림 없이 3번만 주문할 수 없다"
    # 1번 지시문이 바뀌면 3번(이어 그리기)도 다른 항목이다
    changed = [dict(s) for s in SPEC["scenes"]]
    changed[0]["visual_prompt"] += ", seen from slightly higher"
    assert dpaid.build_image_items(changed)[2].prompt_hash != s3.prompt_hash


def test_pilot_spec_is_grounded_and_within_stage_caps():
    claims = {c["claim_id"] for c in SPEC["claims"]}
    for i, sc in enumerate(SPEC["scenes"], 1):
        assert set(sc.get("claim_ids") or []) <= claims, i
        if sc["content_kind"] == "fact":
            assert sc.get("claim_ids"), f"{i}번 사실 장면에 근거가 없다"
        if sc["visual_role"] != "text_card":
            assert sc.get("visual_prompt"), i
    from scripts import drinks_pilot as pilot

    one = pilot.stage_items(SPEC, "1")
    assert round(sum(i.est_usd for i in one), 3) == 0.212 <= SPEC["stages"]["1"]["cap_usd"]
    two = pilot.stage_items(SPEC, "2")
    assert len(two) == 1 and two[0].kind == "video" and two[0].clip_sec == 6 and two[0].est_usd == 0.3
    assert two[0].ref_item == "scene-02-mechanism" and two[0].est_usd <= SPEC["stages"]["2"]["cap_usd"]


class FakeRpc:
    def __init__(self, cache=None):
        self.calls: list[tuple[str, dict]] = []
        self.cache = cache or []

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn == "drinks_find_generated":
            return [c for c in self.cache if c["prompt_hash"] in p["prompt_hashes"]]
        if fn == "drinks_hold_spend":
            return {"hold_id": "h1", "remaining_usd": 0.1}
        if fn == "drinks_settle_spend":
            return {"hold_id": p["hold_id"], "status": p["outcome"]}
        if fn == "drinks_register_generated":
            return {"asset_id": "a1", "existing": False}
        return {}

    def names(self):
        return [c[0] for c in self.calls]


class FakeStorage:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def put(self, path, key, mime):
        self.files[key] = Path(path).read_bytes()
        return f"local:{key}"

    def get(self, key, dest):
        Path(dest).write_bytes(self.files[key.removeprefix("local:")])


def _png(path, color=(10, 20, 30)):
    from PIL import Image

    Image.new("RGB", (768, 1344), color).save(path)


def test_buy_holds_generates_settles_and_registers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    it = dpaid.image_item(1, "reality", "A shelf of bottles")
    rpc, st = FakeRpc(), FakeStorage()

    def gen(item, out, ref):
        _png(out)
        return 0.039
    b = dpaid.buy(it, rpc=rpc, storage=st, approval_id="ap", out_dir=str(tmp_path), generate=gen)
    assert rpc.names() == ["drinks_find_generated", "drinks_hold_spend", "drinks_settle_spend", "drinks_register_generated"]
    hold = rpc.calls[1][1]
    assert hold["approval_id"] == "ap" and hold["est_usd"] == 0.039 and hold["item_key"] == "scene-01-reality"
    assert rpc.calls[2][1]["outcome"] == "settled" and rpc.calls[2][1]["actual_usd"] == 0.039
    reg = rpc.calls[3][1]
    assert reg["prompt_hash"] == it.prompt_hash and reg["asset"]["storage_key"].startswith("local:drinks/generated/")
    assert (b.cost_usd, b.reused, b.width, b.height) == (0.039, False, 768, 1344)


def test_buy_reuses_cached_file_without_spending(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key=""))   # 키가 없어도 재사용은 된다
    it = dpaid.image_item(1, "reality", "A shelf of bottles")
    src = tmp_path / "src.png"
    _png(src)
    from engine.drinks_render import sha256_file

    st = FakeStorage({"drinks/generated/x.png": src.read_bytes()})
    rpc = FakeRpc([{"prompt_hash": it.prompt_hash, "storage_key": "local:drinks/generated/x.png", "sha256": sha256_file(str(src)),
                    "asset_id": "a0"}])
    b = dpaid.buy(it, rpc=rpc, storage=st, approval_id="ap", out_dir=str(tmp_path / "o"), generate=lambda *a: pytest.fail("사면 안 된다"))
    assert rpc.names() == ["drinks_find_generated"] and b.reused and b.cost_usd == 0


def test_buy_releases_hold_on_failure_and_settles_billed_video(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    it = dpaid.image_item(1, "reality", "A shelf of bottles")
    rpc = FakeRpc()

    # 리뷰 R1(2026-11-04, 의도한 변경): 해제는 "확실히 안 보냄"(ImageNotSent)일 때만이다. 예전엔 아무 예외나 해제했다.
    from engine.providers.image import ImageNotSent

    def boom(*a):
        raise ImageNotSent("429 from gemini image")
    with pytest.raises(ImageNotSent):
        dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path), generate=boom)
    assert rpc.calls[-1][0] == "drinks_settle_spend" and rpc.calls[-1][1]["outcome"] == "released"

    class Billed(RuntimeError):
        clip_sec = 6
    clip = dpaid.clip_item(2, "mechanism", "the envelope slides", "scene-02-mechanism", "x" * 64)
    rpc2 = FakeRpc()

    def billed(*a):
        raise Billed("download failed")
    with pytest.raises(Billed):
        dpaid.buy(clip, rpc=rpc2, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path), ref_path="s.png", generate=billed)
    last = rpc2.calls[-1][1]
    assert last["outcome"] == "settled" and last["actual_usd"] == 0.3, "생성 완료 뒤 받기 실패는 청구 유력 — 금액을 남긴다"


def test_buy_refuses_without_key_before_holding(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key=""))
    rpc = FakeRpc()
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.buy(dpaid.image_item(1, "reality", "x"), rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path))
    assert e.value.code == "api_key_missing" and "drinks_hold_spend" not in rpc.names()


def test_paid_provider_switch_is_restored_even_on_error():
    before = (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER)
    with pytest.raises(ValueError):
        with dpaid._paid_provider("image"):
            assert config.IMAGE_PROVIDER == "gemini"
            raise ValueError
    assert (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER) == before


def test_paid_job_without_visual_prompt_fails_before_any_spend(tmp_path):
    calls = []

    def rpc(fn, p):
        calls.append(fn)
        return {"status": p.get("outcome")} if fn == "drinks_finish_render" else {}
    job = {"job_id": "j1", "lease_token": "t", "format": "video", "renderer": "paid", "spend_approval_id": "ap",
           "plan": {"scenes": [{"narration": "a", "visual_role": "reality"}]}, "topic": {"title": "t", "question": "q"}}
    res = dp.process_job(job, rpc, dp.Storage("local", str(tmp_path)))
    assert res["status"] == "failed"
    assert "drinks_hold_spend" not in calls and "drinks_find_generated" not in calls
    fin = [c for c in calls if c == "drinks_finish_render"]
    assert len(fin) == 1


def test_spend_migration_is_service_role_only_and_ci_worker_stays_keyless():
    low = SQL.lower()
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", low)
    assert "create policy" not in low
    for t in re.findall(r"create table if not exists (\w+)", low):
        assert f"alter table {t} enable row level security" in low, t
    # 렌더 큐 워커(GitHub Actions)에는 아직 그림 생성 키를 주지 않는다 — 3단계 결재 때 정한다.
    wf = (ROOT / ".github" / "workflows" / "drinks-produce.yml").read_text(encoding="utf-8")
    assert "GEMINI" not in wf
    # 화면은 돈을 쓰는 함수를 부르지 못한다
    actions = (ROOT / "web" / "lib" / "drinks" / "actions.ts").read_text(encoding="utf-8")
    for fn in ["drinks_hold_spend", "drinks_settle_spend", "drinks_register_generated"]:
        assert fn not in actions, fn


# ─────────────────────────────────────────────────────────────
# 리뷰 R1(2026-11-04): 시작 그림의 숨은 재시도·잘못된 해제
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("exc", [RuntimeError("죽음"), TimeoutError("t")])
def test_image_failure_of_unknown_kind_keeps_the_hold(tmp_path, monkeypatch, exc):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    it = dpaid.image_item(1, "reality", "A shelf of bottles")
    rpc = FakeRpc()

    def boom(*a):
        raise exc
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path), generate=boom)
    assert e.value.code == "unknown_billed"
    assert "drinks_settle_spend" not in rpc.names(), "보냈을 수 있는 그림의 가잡기는 풀지 않는다"


def _fake_gemini(monkeypatch, handler):
    """httpx.Client 를 가짜 전송으로 바꾼다 — 소켓을 열지 않는다. 보낸 POST 수를 센다."""
    import httpx

    from engine.providers import image as img

    sent = []

    def counted(request):
        sent.append(request)
        return handler(request)
    real = httpx.Client
    monkeypatch.setattr(img.httpx, "Client", lambda **k: real(transport=httpx.MockTransport(counted), **k))
    monkeypatch.setattr(img._image_limiter, "wait", lambda: None)
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    return sent


def _read_timeout(request):
    import httpx

    raise httpx.ReadTimeout("공급자가 접수한 뒤 응답이 늦음", request=request)


@pytest.mark.parametrize("handler,why", [
    (_read_timeout, "접수 후 타임아웃"),
    (lambda r: __import__("httpx").Response(503, request=r), "5xx"),
    (lambda r: __import__("httpx").Response(200, content=b"{not json", request=r), "응답 해석 실패"),
    (lambda r: __import__("httpx").Response(200, json={"candidates": [{"content": {"parts": [{"text": "no image"}]}}]}, request=r), "그림 없음"),
])
def test_paid_image_posts_once_and_keeps_the_hold_when_outcome_is_unknown(tmp_path, monkeypatch, handler, why):
    sent = _fake_gemini(monkeypatch, handler)
    it = dpaid.image_item(1, "reality", "A shelf of bottles")
    rpc = FakeRpc()
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path))
    assert len(sent) == 1, f"{why}: 유료 POST 는 한 번만 — 자동 재전송 0회"
    assert e.value.code == "unknown_billed" and "drinks_settle_spend" not in rpc.names(), why


@pytest.mark.parametrize("status", [429, 400, 403])
def test_paid_image_rejected_before_generation_releases_the_hold(tmp_path, monkeypatch, status):
    import httpx

    sent = _fake_gemini(monkeypatch, lambda r: httpx.Response(status, request=r))
    it = dpaid.image_item(1, "reality", "A shelf of bottles")
    rpc = FakeRpc()
    from engine.providers.image import ImageNotSent

    with pytest.raises(ImageNotSent):
        dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path))
    assert len(sent) == 1
    assert rpc.calls[-1][0] == "drinks_settle_spend" and rpc.calls[-1][1]["outcome"] == "released"


def test_paid_image_connect_failure_is_not_sent(tmp_path, monkeypatch):
    import httpx

    def refuse(request):
        raise httpx.ConnectError("연결 거부", request=request)
    _fake_gemini(monkeypatch, refuse)
    from engine.providers.image import ImageNotSent

    rpc = FakeRpc()
    with pytest.raises(ImageNotSent):
        dpaid.buy(dpaid.image_item(1, "reality", "A shelf of bottles"), rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path))
    assert rpc.calls[-1][1]["outcome"] == "released"


def test_paid_image_success_still_settles_and_registers(tmp_path, monkeypatch):
    import base64
    import io

    import httpx
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1080, 1920), (1, 2, 3)).save(buf, "PNG")
    body = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}}]}}]}
    sent = _fake_gemini(monkeypatch, lambda r: httpx.Response(200, json=body, request=r))
    rpc = FakeRpc()
    b = dpaid.buy(dpaid.image_item(1, "reality", "A shelf of bottles"), rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path))
    assert len(sent) == 1 and not b.reused and b.cost_usd > 0
    assert [c[1].get("outcome") for c in rpc.calls if c[0] == "drinks_settle_spend"] == ["settled"]
    assert "drinks_register_generated" in rpc.names()


def test_paper_factory_image_path_keeps_its_retry():
    """논문 공장 경로(_gemini_image)는 결재 원장이 없다 — 이번 수정 범위 밖이라 재시도를 그대로 둔다."""
    from engine.providers import image as img

    assert hasattr(img._gemini_image, "retry")
    assert not hasattr(img.gemini_image_once, "retry")
