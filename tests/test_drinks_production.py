"""주류 C단계 제작 — 어댑터·카드·저장·워커(네트워크·ffmpeg 없이). 실제 영상 렌더는 로컬 e2e 로 확인했다
(docs/deviation-drinks-production.md) — 여기서는 렌더 함수를 바꿔 끼워 워커 규칙만 본다."""
import os

import pytest
from PIL import Image

from engine import config
from engine import drinks_produce as dp
from engine import drinks_render as dr

SCENES = [{"position": 1, "narration": "사케, 한 번 따면?", "visual_role": "reality", "content_kind": "transition", "explanation": "냉장고 속 병",
           "claim_ids": [], "timing_sec": 3},
          {"position": 2, "narration": "쌀을 반 깎아요", "visual_role": "mechanism", "content_kind": "fact", "explanation": "쌀 50%",
           "claim_ids": ["c1"], "timing_sec": 30}]


def test_plan_to_directive_uses_engine_fields_and_never_photo_mode():
    d = dr.plan_to_directive({"scenes": SCENES}, {"question": "Q?"})
    assert d["header"]["version_type"] == "image_sequence", "photo 는 영상 필수 경로(VideoRequiredError) — 쓰지 않는다"
    c1, c2 = d["cuts"]
    assert (c1["cut_no"], c1["narration_ko"], c1["visual_type"]) == (1, "사케, 한 번 따면?", "image")
    assert c2["estimated_sec"] == 20, "장면 길이 상한"
    assert "motion_source" not in c1 and "visual_role" not in c1, "영상 생성·실사 계약 경로를 켜지 않는다"
    assert c2["source_facts"] == ["c1"]


def test_scene_card_carries_scene_type_label_and_flags_truncation(tmp_path):
    long = {**SCENES[0], "explanation": "아주 긴 설명 " * 80}
    qa = dr.draw_scene_card(long, 1, 2, {}, str(tmp_path / "a.png"))
    assert qa["label"] == dr.SCENE_LABEL["reality"] and "실제 제품" in qa["label"]
    assert qa["truncated"] is True, "넘친 글자는 조용히 자르지 않고 qa 로 올린다"
    assert Image.open(tmp_path / "a.png").size == (config.RENDER_WIDTH, config.RENDER_HEIGHT)
    assert dr.draw_scene_card(SCENES[1], 2, 2, {}, str(tmp_path / "b.png"))["truncated"] is False


def test_paid_providers_are_refused(monkeypatch):
    with pytest.raises(dr.RenderError) as e:
        dr._guard_free("elevenlabs")
    assert e.value.code == "paid_disabled"
    monkeypatch.setattr(config, "image_is_paid", lambda: True)
    with pytest.raises(dr.RenderError):
        dr._guard_free("edge")


def test_local_storage_never_overwrites_different_content(tmp_path):
    s = dp.Storage("local", str(tmp_path))
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert s.put(str(a), "drinks/j1/final_video_01.mp4", "video/mp4") == "local:drinks/j1/final_video_01.mp4"
    assert s.put(str(a), "drinks/j1/final_video_01.mp4", "video/mp4"), "같은 내용은 통과(재시도)"
    with pytest.raises(dr.RenderError):
        s.put(str(b), "drinks/j1/final_video_01.mp4", "video/mp4")
    with pytest.raises(AssertionError):
        s.put(str(a), "directive-id/final.mp4", "video/mp4")   # 논문 폴더 모양 금지


class FakeRpc:
    def __init__(self, fail=None, hb=None):
        self.calls, self.fail, self.hb = [], fail or {}, hb or {"cancel_requested": False, "renderable": True}

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn in self.fail:
            from engine.drinks_collect import DbError
            raise DbError(self.fail[fn], "x")
        if fn == "drinks_heartbeat_render":
            return self.hb
        if fn == "drinks_register_asset":
            return {"asset_id": f"a{len(self.calls)}"}
        if fn == "drinks_finish_render":
            return {"status": "succeeded" if p.get("outcome") == "succeeded" else "failed", **p}
        return {}


JOB = {"job_id": "11111111-2222-3333-4444-555555555555", "lease_token": "t", "format": "carousel", "renderer_version": "v1",
       "topic": {"title": "t"}, "claims": [], "sources": [], "plan": {"pages": [{"position": 1, "role": "cover", "heading": "표지"}]}}


def test_worker_stores_registers_costs_and_finishes(tmp_path):
    rpc = FakeRpc()
    out = dp.process_job(JOB, rpc, dp.Storage("local", str(tmp_path)))
    assert out["status"] == "succeeded"
    fns = [fn for fn, _ in rpc.calls]
    assert fns[:2] == ["drinks_heartbeat_render", "drinks_heartbeat_render"] and "drinks_register_asset" in fns
    reg = next(p for fn, p in rpc.calls if fn == "drinks_register_asset")["asset"]
    assert reg["storage_key"] == f"local:drinks/{JOB['job_id']}/page_01.png" and len(reg["sha256"]) == 64
    fin = rpc.calls[-1][1]
    assert fin["assets"] == [{"asset_id": "a3", "role": "page", "position": 1}]
    assert os.path.exists(tmp_path / "drinks" / JOB["job_id"] / "page_01.png")


def test_worker_stops_before_render_when_canceled_or_evidence_invalid(tmp_path):
    rpc = FakeRpc(hb={"cancel_requested": False, "renderable": False})
    out = dp.process_job(JOB, rpc, dp.Storage("local", str(tmp_path)))
    assert out["error_code"] == "canceled_before_render"
    assert not any(fn == "drinks_register_asset" for fn, _ in rpc.calls), "비용·파일을 만들기 전에 멈춘다"


def test_worker_lease_lost_does_not_finish_and_render_error_is_recorded(tmp_path, monkeypatch):
    # ★ 임대를 잃은 순간 이미 올린 파일은 남는다(고아 — 새 위치라 다른 묶음을 해치지 않는다). 여기서 보는 것은 '끝내기 안 함'.
    rpc = FakeRpc(fail={"drinks_register_asset": "lease_lost"})
    assert dp.process_job(JOB, rpc, dp.Storage("local", str(tmp_path))) == {"status": "lease_lost"}
    assert not any(fn == "drinks_finish_render" for fn, _ in rpc.calls)
    from engine import drinks_cards

    monkeypatch.setattr(drinks_cards, "render_carousel", lambda job, d: (_ for _ in ()).throw(dr.RenderError("font_missing", "x")))
    rpc2 = FakeRpc()
    out = dp.process_job(JOB, rpc2, dp.Storage("local", str(tmp_path)))
    assert out["error_code"] == "font_missing" and out["status"] == "failed"


def test_worker_closes_the_job_on_any_db_refusal(tmp_path):
    rpc = FakeRpc(fail={"drinks_record_cost": "invalid_input"})
    out = dp.process_job(JOB, rpc, dp.Storage("local", str(tmp_path)))
    assert out["status"] == "failed" and out["error_code"] == "invalid_input", "'렌더 중'에 남기지 않는다"
