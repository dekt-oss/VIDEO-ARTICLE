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


# ── 릴스 2차 묶음(2026-10-28): 무료 경로 대본 검사 · 슬라이드 릴스 · 말 속도 ─────────────

def _video_job(scenes, claims=None, renderer="local", card_pages=None):
    return {"job_id": "22222222-3333-4444-5555-666666666666", "lease_token": "t", "format": "video", "renderer": renderer,
            "renderer_version": "v1", "topic": {"title": "t", "question": "q"}, "claims": claims or [], "sources": [],
            "plan": {"scenes": scenes}, "card_pages": card_pages or []}


def _fake_rendered(tmp_path, qa=None):
    p = tmp_path / "final.mp4"
    p.write_bytes(b"mp4")
    c = tmp_path / "cover.jpg"
    c.write_bytes(b"jpg")
    return dr.Rendered(files=[{"path": str(p), "role": "final_video", "position": 1, "mime": "video/mp4"},
                              {"path": str(c), "role": "cover", "position": 1, "mime": "image/jpeg"}],
                       qa=qa if qa is not None else {"warnings": []}, costs=[])


def test_free_path_runs_script_check_and_only_warns(tmp_path, monkeypatch):
    """무료 경로(2026-10-28 진단: 대본 검사가 안 물려 있었다) — 원문 밖 숫자는 qa 에 막힘으로 실리되 작업은 성공한다."""
    seen = {}

    def fake_render(job, work, **kw):
        seen["card_pages"] = kw.get("card_pages")
        return _fake_rendered(tmp_path)
    monkeypatch.setattr(dp, "render_video", fake_render)
    claims = [{"claim_id": "c1", "claim_type": "process", "source_refs": [{"original_quote": "diluted to around 40 vol-%"}]}]
    scenes = [{"narration": "70도에서 마셔요?", "claim_ids": ["c1"], "visual_role": "text_card", "content_kind": "fact"}]
    rpc = FakeRpc()
    out = dp.process_job(_video_job(scenes, claims), rpc, dp.Storage("local", str(tmp_path / "st")))
    assert out["status"] == "succeeded", "대본 검사 막힘은 무료 경로에서 작업을 실패시키지 않는다"
    qa = rpc.calls[-1][1]["qa"]
    assert qa["script_check"]["ok"] is False
    assert any(b["code"] == "number_unsupported" and b["scene"] == 1 for b in qa["script_check"]["blocks"])
    assert "script_check_blocked" in qa["warnings"]
    assert seen["card_pages"] == {}


def test_free_path_script_check_clean_plan_has_no_blocked_warning_and_survives_checker_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "render_video", lambda job, work, **kw: _fake_rendered(tmp_path))
    claims = [{"claim_id": "c1", "claim_type": "process", "source_refs": [{"original_quote": "diluted to around 40 vol-%"}]}]
    scenes = [{"narration": "도수는 40쯤이에요?", "claim_ids": ["c1"], "visual_role": "text_card", "content_kind": "fact"}]
    rpc = FakeRpc()
    assert dp.process_job(_video_job(scenes, claims), rpc, dp.Storage("local", str(tmp_path / "st")))["status"] == "succeeded"
    qa = rpc.calls[-1][1]["qa"]
    assert qa["script_check"]["ok"] is True and "script_check_blocked" not in qa["warnings"]
    # 검사기가 죽어도 영상은 나간다(경고 코드만)
    monkeypatch.setattr(dp.script_check, "check", lambda spec: (_ for _ in ()).throw(RuntimeError("boom")))
    rpc2 = FakeRpc()
    assert dp.process_job(_video_job(scenes, claims), rpc2, dp.Storage("local", str(tmp_path / "st2")))["status"] == "succeeded"
    qa2 = rpc2.calls[-1][1]["qa"]
    assert "script_check" not in qa2 and "script_check_error" in qa2["warnings"]


def _page_png(path, size=(1080, 1350), color=(200, 30, 30)):
    Image.new("RGB", size, color).save(path, "PNG")
    return str(path)


def test_compose_card_page_centres_uncropped_page_on_brand_background(tmp_path):
    page = _page_png(tmp_path / "p.png")
    out = tmp_path / "o.png"
    qa = dr.compose_card_page(page, {"visual_role": "text_card"}, 2, 5, str(out))
    im = Image.open(out).convert("RGB")
    assert im.size == (1080, 1920) and qa["card_page"] is True and qa["label"] == dr.SCENE_LABEL["text_card"]
    top = (1920 - 1350) // 2   # 285
    assert im.getpixel((540, top + 700)) == (200, 30, 30), "페이지가 가운데에 그대로"
    assert im.getpixel((5, top + 5)) == (200, 30, 30) and im.getpixel((1074, top + 1344)) == (200, 30, 30), "모서리까지 자르지 않음"
    assert im.getpixel((5, top - 3)) == dr.BRAND["bg"] and im.getpixel((5, top + 1350 + 3)) == dr.BRAND["bg"], "위·아래는 브랜드 배경"
    # 배지(위쪽 띠)는 페이지 위에 겹치지 않는다
    assert all(im.getpixel((x, top + 2)) == (200, 30, 30) for x in (200, 540, 900))
    # 다른 크기의 페이지는 비율을 지킨 채 화면 안에 맞춘다
    wide = _page_png(tmp_path / "w.png", size=(2160, 2700), color=(30, 30, 200))
    dr.compose_card_page(wide, {"visual_role": "reality"}, 1, 1, str(out))
    assert Image.open(out).convert("RGB").getpixel((540, 960)) == (30, 30, 200)


def test_card_page_of_accepts_only_1_to_20_integers():
    f = dr.card_page_of
    assert f({"card_page": 1}) == 1 and f({"card_page": 20}) == 20 and f({"card_page": 3.0}) == 3
    assert [f({"card_page": v}) for v in (0, 21, 1.5, True, "2", None)] == [None] * 6 and f({}) is None


def test_worker_fetches_only_the_card_pages_the_plan_uses(tmp_path):
    st = dp.Storage("local", str(tmp_path / "st"))
    for n in (1, 2, 3):
        d = tmp_path / "st" / "drinks" / "cardjob"
        d.mkdir(parents=True, exist_ok=True)
        _page_png(d / f"page_{n:02d}.png")
    job = _video_job([{"narration": "a", "card_page": 2}, {"narration": "b"}, {"narration": "c", "card_page": 9}],
                     card_pages=[{"position": n, "storage_key": f"local:drinks/cardjob/page_{n:02d}.png", "mime": "image/png"}
                                 for n in (1, 2, 3)])
    got = dp.fetch_card_pages(job, st, str(tmp_path / "work"))
    assert sorted(got) == [2], "쓰지 않는 페이지는 받지 않고, 없는 9쪽은 빠진다"
    assert os.path.exists(got[2])
    # 꺼내기 실패는 건너뛴다(그 장면만 대체 카드)
    job["card_pages"][1]["storage_key"] = "local:drinks/cardjob/gone.png"
    assert dp.fetch_card_pages(job, st, str(tmp_path / "work2")) == {}


def test_asset_provenance_marks_card_pages_but_paid_images_win(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "render_video", lambda job, work, **kw: _fake_rendered(
        tmp_path, {"warnings": [], "card_page_scenes": [2], "generated_scenes": []}))
    rpc = FakeRpc()
    dp.process_job(_video_job([{"narration": "a?", "card_page": 1, "visual_role": "text_card", "content_kind": "transition"}]),
                   rpc, dp.Storage("local", str(tmp_path / "st")))
    regs = [p["asset"] for fn, p in rpc.calls if fn == "drinks_register_asset"]
    assert regs and all(a["provenance"]["images"] == "card_pages" and a["rights"] == "generated_local" for a in regs)
    assert dp._image_provenance({"generated_scenes": [3], "card_page_scenes": [2]}) == "generated_paid"
    assert dp._image_provenance({}) == "local_stand_in_cards"


def _fake_engine(monkeypatch, tmp_path, captured):
    """엔진 렌더·ffprobe 를 바꿔 끼워 render_video 의 qa 조립만 본다(실제 영상은 로컬 e2e 로 확인)."""
    from engine import render as engine_render

    def fake_directive_local(directive, out, work_dir=None, lang="ko", platform=None):
        captured.update(platform=platform, speed=config.RENDER_PLAYBACK_SPEED, directive=directive)
        open(out, "wb").write(b"mp4")
        for i in range(len(directive["cuts"])):
            open(os.path.join(work_dir, f"cut_{i}.m4a"), "wb").write(b"a")
        return out
    monkeypatch.setattr(engine_render, "render_directive_local", fake_directive_local)
    monkeypatch.setattr(dr, "_probe", lambda p: {"width": 1080, "height": 1920, "duration_sec": 20.0, "audio_streams": 1, "video_codec": "h264",
                                                 "audio_codec": "aac", "audio_sample_rate": 48000, "fps": 30.0})
    monkeypatch.setattr(dr, "_mean_volume_db", lambda p: -20.0)
    monkeypatch.setattr(dr, "moov_before_mdat", lambda p: True)
    # _guard_free 가 바꾸는 전역을 시험이 끝나면 되돌린다
    for k in ("RENDER_PLAYBACK_SPEED", "IMAGE_PROVIDER", "VIDEO_PROVIDER", "TTS_PROVIDER", "IMAGE_REUSE_DIR", "CAPTION_PHRASE_BREAKS"):
        monkeypatch.setattr(config, k, getattr(config, k))


def test_render_video_qa_visual_source_card_pages_missing_page_speech_rate_and_platform(tmp_path, monkeypatch):
    cap = {}
    _fake_engine(monkeypatch, tmp_path, cap)
    page = _page_png(tmp_path / "p1.png")
    scenes = [{"narration": "가나다라마바사 아자차카타파하" * 2, "visual_role": "reality", "explanation": "x"},          # 대체 카드
              {"narration": "카드 한 장", "visual_role": "text_card", "card_page": 1},                                  # 카드 페이지
              {"narration": "없는 쪽", "visual_role": "mechanism", "card_page": 7},                                     # 페이지 없음
              {"narration": "정리", "visual_role": "text_card"}]                                                       # 정리 카드(대체 아님)
    r = dr.render_video(_video_job(scenes), str(tmp_path / "w"), card_pages={1: page})
    qa = r.qa
    assert qa["visual_source"] == {"stand_in": [1, 3], "card_pages": [2], "generated": []}
    assert "card_page_missing" in qa["warnings"]
    assert qa["stand_in_scenes"] == [1, 3] and qa["card_page_scenes"] == [2]
    assert cap["platform"] == config.DRINKS_CAPTION_PLATFORM == "reels", "릴스 자막 앵커가 엔진까지 전달된다"
    assert cap["speed"] == config.DRINKS_PLAYBACK_SPEED, "속도는 TTS 한 곳 — 조립 끝 배속은 주류 설정을 따른다"
    sr = qa["speech_rate"]
    assert sr["syllables"] == 28 + 4 + 3 + 2 and sr["final_sec"] == 20.0 and sr["tts_rate"] == config.EDGE_TTS_RATE
    assert sr["syl_per_sec"] == round(37 / 20.0, 2) and sr["playback_speed"] == config.DRINKS_PLAYBACK_SPEED
    assert "speech_rate_fast" not in qa["warnings"]
    # 산 그림이 있는 장면은 카드 페이지보다 우선
    img = _page_png(tmp_path / "g.png", size=(1024, 1024))
    r2 = dr.render_video(_video_job([{"narration": "a", "card_page": 1, "visual_role": "reality"}]), str(tmp_path / "w2"),
                         images={1: img}, card_pages={1: page})
    assert r2.qa["visual_source"] == {"stand_in": [], "card_pages": [], "generated": [1]} and "card_page_missing" not in r2.qa["warnings"]


def test_speech_rate_helper_counts_letters_not_punctuation_and_flags_fast(tmp_path, monkeypatch):
    sr = dr.speech_rate(["위스키에 물을, 왜 떨어뜨릴까요?", "50% 입니다."], 5.0, 1.0, "+10%")
    assert sr["syllables"] == len("위스키에물을왜떨어뜨릴까요") + len("50입니다") and sr["syl_per_sec"] == round(sr["syllables"] / 5.0, 2)
    assert dr.speech_rate([], 0.0, 1.0, "+10%")["syl_per_sec"] == 0.0
    cap = {}
    _fake_engine(monkeypatch, tmp_path, cap)
    fast = [{"narration": "가" * 140, "visual_role": "text_card"}]   # 140음절 / 20초 = 7.0 > 문턱 6.5
    assert "speech_rate_fast" in dr.render_video(_video_job(fast), str(tmp_path / "w"), tts="placeholder").qa["warnings"]


def test_guard_free_applies_drinks_playback_speed(monkeypatch):
    for k in ("IMAGE_PROVIDER", "VIDEO_PROVIDER", "TTS_PROVIDER", "CAPTION_PHRASE_BREAKS", "RENDER_PLAYBACK_SPEED"):
        monkeypatch.setattr(config, k, getattr(config, k))
    assert config.DRINKS_PLAYBACK_SPEED == 1.2, "운영자 판정(2026-10-28) — 주류도 1.2×"
    monkeypatch.setattr(config, "DRINKS_PLAYBACK_SPEED", 1.05)
    dr._guard_free("edge")
    assert config.RENDER_PLAYBACK_SPEED == 1.05
