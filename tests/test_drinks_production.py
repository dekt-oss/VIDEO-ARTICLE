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


# ── 릴스 파일 규격(2026-10-28, docs/진단_주류릴스엔진_2026-10-28.md) ─────────
OK_PROBE = {"width": 1080, "height": 1920, "duration_sec": 40.0, "audio_streams": 1, "video_codec": "h264",
            "audio_codec": "aac", "audio_sample_rate": 48000, "fps": 30.0}


def _w(**kw):
    args = {"probe": OK_PROBE, "file_bytes": 5_000_000, "moov_first": True, "cover_mime": "image/jpeg", "cover_bytes": 200_000}
    args.update(kw)
    return dr.reel_spec_warnings(**args)


def test_reel_spec_compliant_has_no_warnings():
    assert _w() == []


def test_reel_spec_flags_each_violation():
    assert "reel_audio_rate_over_48k" in _w(probe={**OK_PROBE, "audio_sample_rate": 96000})
    assert "reel_moov_not_first" in _w(moov_first=False)
    assert "reel_cover_not_jpeg" in _w(cover_mime="image/png")
    assert "reel_duration_out_of_range" in _w(probe={**OK_PROBE, "duration_sec": 2.0})
    assert "reel_width_over_1920" in _w(probe={**OK_PROBE, "width": 2160})
    assert "reel_fps_out_of_range" in _w(probe={**OK_PROBE, "fps": 120.0})
    assert "reel_video_codec" in _w(probe={**OK_PROBE, "video_codec": "vp9"})
    assert "reel_audio_codec" in _w(probe={**OK_PROBE, "audio_codec": "mp3"})
    assert "reel_file_too_big" in _w(file_bytes=301 * 1024 * 1024)
    assert "reel_cover_too_big" in _w(cover_bytes=9 * 1024 * 1024)


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    import struct
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def test_moov_before_mdat_reads_top_level_atoms(tmp_path):
    front, back = tmp_path / "front.mp4", tmp_path / "back.mp4"
    front.write_bytes(_box(b"ftyp", b"isom0000") + _box(b"moov", b"x" * 20) + _box(b"mdat", b"y" * 50))
    back.write_bytes(_box(b"ftyp", b"isom0000") + _box(b"mdat", b"y" * 50) + _box(b"moov", b"x" * 20))
    assert dr.moov_before_mdat(str(front)) is True
    assert dr.moov_before_mdat(str(back)) is False


def test_cover_is_written_as_jpeg(tmp_path):
    out = tmp_path / "cover.jpg"
    qa = dr.draw_cover({"title": "사케는 쌀을 얼마나 깎나", "question": "한 병에 쌀이 얼마나 들어갈까?"}, {}, str(out))
    img = Image.open(out)
    assert img.format == "JPEG" and img.size == (1080, 1920)
    assert qa["truncated"] is False


def test_asset_extension_follows_mime():
    assert dp.MIME_EXT["video/mp4"] == ".mp4" and dp.MIME_EXT["image/jpeg"] == ".jpg" and dp.MIME_EXT["image/png"] == ".png"
