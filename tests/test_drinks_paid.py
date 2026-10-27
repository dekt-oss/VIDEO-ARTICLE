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

    def boom(*a):
        raise RuntimeError("429")
    with pytest.raises(RuntimeError):
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
# 0056 — 사진형 카드 유료 그림: 엔진과 SQL 이 같은 항목 이름·단가·대상·판정을 쓴다
# ─────────────────────────────────────────────────────────────

SQL56 = (ROOT / "supabase" / "migrations" / "0056_drinks_card_paid.sql").read_text(encoding="utf-8")


def test_card_item_keys_prices_and_targets_match_between_engine_and_0056():
    # 항목 이름: SQL 의 'page-NN-photo' 와 엔진 card_image_item 이 같은 꼴 (이미 산 쪽을 알아보는 열쇠)
    assert "'page-' || lpad(pg.position::text, 2, '0') || '-photo'" in SQL56
    assert [dpaid.card_image_item(n, "x").item_key for n in (1, 9, 12)] == ["page-01-photo", "page-09-photo", "page-12-photo"]
    # 단가: SQL 은 실사 단가(price_image_reality) — 0054 한도표와 엔진 카드 항목 단가가 같다
    limits = {k: float(v) for k, v in re.findall(r"'(price_[a-z_]+)', ([0-9.]+)", SQL)}
    assert dpaid.card_image_item(1, "x").est_usd == limits["price_image_reality"] == config.DRINKS_PAID_PRICES["image_reality"]
    est_fn = SQL56[SQL56.index("create or replace function drinks_estimate_render"):]
    est_fn = est_fn[:est_fn.index("$$;")]
    page_part = est_fn[est_fn.index("pg_priced"):]
    assert "price_image_reality" in page_part and "price_image_mechanism" not in page_part
    # 대상: 출처 장은 뺀다 + image_prompt 가 비지 않은 쪽만 — 엔진 build_card_image_items 와 같다
    assert "coalesce(e.s ->> 'role', '') <> 'source'" in est_fn and "e.s ->> 'image_prompt'" in est_fn
    pages = [{"position": 1, "role": "cover", "image_prompt": "a"}, {"position": 2, "role": "explain", "image_prompt": " \t\n"},
             {"position": 3, "role": "source", "image_prompt": "b"}, {"position": 4, "role": "explain"}, {"position": 5, "role": "explain", "image_prompt": "c"}]
    assert [it.position for it in dpaid.build_card_image_items(pages)] == [1, 5]
    # 반환 모양: 영상용 scenes 는 그대로, 카드는 pages — 합계는 둘을 합친다(화면은 total_usd·images·bought 를 읽는다)
    assert "'scenes'," in est_fn and "'pages'," in est_fn
    for k in ("images", "bought", "total_usd"):
        assert re.search(rf"'{k}',[^\n]*\+", est_fn), k


def test_photo_plan_judgement_and_guard_match_engine():
    from engine.drinks_cards_photo import is_photo_plan
    assert config.DRINKS_CARD_PHOTO_TEMPLATE == "card-photo-v1"
    judge = SQL56[SQL56.index("create or replace function drinks_is_photo_plan"):]
    judge = judge[:judge.index("$$;")]
    assert "'layout' = 'photo'" in judge and f"'template_version' = '{config.DRINKS_CARD_PHOTO_TEMPLATE}'" in judge
    assert is_photo_plan({"layout": "photo"}) and is_photo_plan({"template_version": "card-photo-v1"}) and not is_photo_plan({"template_version": "card-v1"})
    # 유료 허용 조건: 영상 또는 (카드뉴스 + 사진형). 글자 카드는 계속 거절
    req = SQL56[SQL56.index("create or replace function drinks_request_render"):]
    assert "pl.format = 'video' or (pl.format = 'carousel' and drinks_is_photo_plan(pl.plan_json))" in req
    for keep in ("approval_closed", "kind_not_approved", "'ownership'", "budget_insufficient", "paid_disabled", "drinks_estimate_render(pl.id)"):
        assert keep in req, keep   # 열린 결재·종류·전용·상한 검사는 그대로


def test_validate_plan_keeps_every_field_the_card_engine_reads():
    val = SQL56[SQL56.index("create or replace function drinks_validate_plan"):]
    val = val[:val.index("end $$;")]
    for field in ("image_prompt", "kicker", "category", "photo_shift", "layout", "caption"):
        assert f"'{field}'" in val, field
    # 엔진이 읽는 쪽 키(photo_shift·kicker·category·image_prompt)와 제작안 키(layout·caption) 이름이 실제로 엔진 소스에 있다
    src = (ROOT / "engine" / "drinks_cards_photo.py").read_text(encoding="utf-8") + (ROOT / "engine" / "drinks_caption.py").read_text(encoding="utf-8")
    for field in ("photo_shift", "kicker", "category", "layout", "caption"):
        assert field in src, field
    assert "image_prompt" in (ROOT / "engine" / "drinks_paid.py").read_text(encoding="utf-8")


def test_0056_regrants_service_role_only():
    low = SQL56.lower()
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", low)
    assert "revoke all on function %s from public, anon, authenticated" in SQL56
    assert "grant execute on function %s to service_role" in SQL56
    assert "create table" not in low and "create policy" not in low and "alter table" not in low   # 스키마 변경 없음 — 함수만
