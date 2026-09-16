"""작업 D(언어 독립 공유 에셋) DoD 통합 테스트 — 명세 §5.7.

불변식: 시각 에셋(이미지)은 언어 무관 캐시(content_hash)라 KO 렌더가 만든 에셋을 EN 렌더가
그대로 재사용한다 → 유료 이미지 생성 호출은 주제(directive)당 1회. 언어가 늘어도 이미지비 불변.
`_gen_still` 이 애초에 lang 인자를 받지 않는다는 것 자체가 언어 독립성의 구조적 증거다.

이 테스트는 두 숏츠 라인(논문/신규 주제) 공통으로 지켜야 하는 "공유 에셋 이중과금 방지" 가드다.
"""

from __future__ import annotations

import os

import engine.render as render
from engine import assemble, crop


def test_gen_still_shared_across_languages(tmp_path, monkeypatch):
    # 유료 제공자(gemini)로 세팅해야 캐시 경로가 켜진다(placeholder 는 공짜라 캐시 우회).
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")

    store: dict[tuple, dict] = {}
    calls = {"generate": 0}

    def fake_generate(cut, header, out_path, model="", ref_path=None):
        calls["generate"] += 1
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG-fresh")
        return out_path, render.config.GEMINI_IMAGE_COST_USD

    def fake_get(directive_id, cut_no, asset_type):
        return store.get((directive_id, cut_no, asset_type))

    def fake_upsert(row):
        store[(row["directive_id"], row["cut_no"], row["asset_type"])] = dict(row)

    def fake_upload(path, dest, content_type="image/png"):
        return f"https://fake.storage/{dest}"

    def fake_download(url, dest):
        with open(dest, "wb") as f:
            f.write(b"\x89PNG-cached")

    # 비용 원장 기록 횟수를 센다(§6.3 공유 에셋 중복 계상 방지 검증).
    ledger: list[dict] = []
    monkeypatch.setattr(render.cost_ledger, "record", lambda attempt: ledger.append(attempt))

    monkeypatch.setattr(render.image_provider, "generate_image", fake_generate)
    monkeypatch.setattr(render.db, "get_render_asset", fake_get)
    monkeypatch.setattr(render.db, "upsert_render_asset", fake_upsert)
    monkeypatch.setattr(render.db, "upload_render", fake_upload)
    monkeypatch.setattr(render, "_download_to", fake_download)

    cut = {"cut_no": 1, "visual_type": "image", "visual_prompt": "a quantum lab",
           "effects": [], "narration_ko": "한국어 나레이션", "narration_en": "English narration"}
    header = {"version_type": "image_sequence", "global_style": "clean editorial"}

    # KO 렌더가 이미지를 생성(1회) → 캐시 기록.
    ko_path = str(tmp_path / "ko_cut1.png")
    cost_ko = render._gen_still(cut, header, ko_path, directive_id="dir1")

    # EN 렌더(동일 컷·동일 directive)는 캐시 재사용 → 생성 0회·비용 0.
    en_path = str(tmp_path / "en_cut1.png")
    cost_en = render._gen_still(cut, header, en_path, directive_id="dir1")

    assert calls["generate"] == 1                    # 주제당 1회만 유료 생성(언어 무관 공유)
    assert cost_ko == render.config.GEMINI_IMAGE_COST_USD
    assert cost_en == 0.0                            # 재사용은 무료
    assert (tmp_path / "en_cut1.png").exists()       # EN 도 실제 파일 확보(캐시 다운로드)
    # 원장도 1행만(§6.3): 공유 이미지비가 KO·EN 에 이중 계상되지 않는다.
    assert len(ledger) == 1
    assert ledger[0]["asset_type"] == "image" and ledger[0]["actual_cost_usd"] == "0.039000"


def test_content_hash_ignores_localizations():
    # localizations(언어별 나레이션·자막)가 있어도 시각 해시는 동일 → 언어별 재생성 안 함.
    base = {"cut_no": 1, "visual_type": "image", "visual_prompt": "x", "effects": []}
    header = {"version_type": "image_sequence", "global_style": "clean"}
    ko = {**base, "narration_ko": "가", "subtitle": "가",
          "localizations": {"ko": {"narration": "가", "subtitle": "가"}}}
    en = {**base, "narration_en": "b", "subtitle": "b",
          "localizations": {"en": {"narration": "b", "subtitle": "b"}}}
    assert assemble.content_hash(ko, header) == assemble.content_hash(en, header)


def test_gen_veo_clip_shared_across_languages(tmp_path, monkeypatch):
    """언어 추가 렌더(수정명세 v1 Part ②) DoD: 영상 생성 API 호출 = 0.

    ⑥ 화면의 "다른 언어 버전 추가 생성"은 별도 플래그 없이 이 캐시 위에서 성립한다 —
    클립 content_hash 에 언어가 없으므로 KO 가 만든 Veo 클립을 EN 잡이 그대로 내려받는다.
    티어 선택(§3-2) 도입 후에도 이 불변식이 유지되는지 고정한다(첫 언어의 티어를 뒤 언어가 물려받음).
    """
    monkeypatch.setattr(render.config, "VIDEO_PROVIDER", "veo")

    store: dict[tuple, dict] = {}
    calls = {"generate": 0, "requested_sec": []}

    def fake_generate_clip(cut, header, out_path, duration, lang="ko", start_image=None):
        calls["generate"] += 1
        calls["requested_sec"].append(duration)
        with open(out_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42-fresh")
        return out_path, duration * render.config.VEO_COST_PER_SEC_USD

    monkeypatch.setattr(render.video_provider, "generate_clip", fake_generate_clip)
    monkeypatch.setattr(render.db, "get_render_asset",
                        lambda d, c, t: store.get((d, c, t)))
    monkeypatch.setattr(render.db, "upsert_render_asset",
                        lambda row: store.__setitem__(
                            (row["directive_id"], row["cut_no"], row["asset_type"]), dict(row)))
    monkeypatch.setattr(render.db, "upload_render",
                        lambda p, dest, ct="video/mp4": f"https://fake.storage/{dest}")
    monkeypatch.setattr(render, "_download_to",
                        lambda url, dest: open(dest, "wb").write(b"ftyp-cached"))
    monkeypatch.setattr(render.cost_ledger, "record", lambda attempt: None)

    cut = {"cut_no": 2, "visual_prompt": "a slow push-in on the lab bench",
           "motion_prompt": "slow push-in", "motion_source": "video", "effects": []}
    header = {"version_type": "comic", "global_style": "flat webtoon"}

    ok_ko, key_ko, cost_ko = render._gen_veo_clip(
        cut, header, str(tmp_path / "ko.mp4"), str(tmp_path / "start.png"),
        directive_id="dir1", narration_sec=5.3)
    # EN 나레이션이 더 짧아도(4.1s) 캐시가 먼저라 재생성하지 않는다.
    ok_en, key_en, cost_en = render._gen_veo_clip(
        cut, header, str(tmp_path / "en.mp4"), str(tmp_path / "start.png"),
        directive_id="dir1", narration_sec=4.1)

    assert ok_ko and ok_en
    assert calls["generate"] == 1        # 유료 영상 생성은 주제당 1회 — 언어가 늘어도 불변
    assert cost_en == 0.0                # 재사용은 무료
    assert (tmp_path / "en.mp4").exists()
    # 요청 초수는 티어 선택 결과(§3-2). 기본 상한(VEO_CLIP_MAX_TIER_SEC=VEO_CLIP_SEC)이면 비용 불변.
    assert calls["requested_sec"] == [render.video_provider.pick_clip_tier(5.3)]


# ── 에셋 재사용(수정명세 §10-5) — 길이가 늘어도 이미지 수가 함께 늘지 않는다 ──
def _stub_real_image_providers(monkeypatch, calls):
    """생성 스텁이 **진짜 PNG** 를 쓴다 — 크롭·톤 파생과 픽셀 비교가 실제로 돌게.

    ★ 가짜 바이트(b"\\x89PNG-cut1")를 쓰면 derive_image 가 열지 못해 '복사'로 강등되고,
      픽셀 판정도 '판정 불가'로 빠진다. 그러면 이 파일의 재사용 테스트가 **실제 경로를 한 번도
      타지 않으면서** 통과한다.
    """
    from PIL import Image

    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")

    def fake_generate(cut, header, out_path, model="", ref_path=None):
        calls["generate"] += 1
        no = int(cut.get("cut_no") or 0)
        # 컷마다 다른 색 — 기준 컷과 파생 컷이 구분돼야 비교가 의미를 갖는다.
        Image.new("RGB", (240, 426), (40 + no * 30, 90, 160)).save(out_path, "PNG")
        return out_path, render.config.GEMINI_IMAGE_COST_USD

    def fake_tts(cut, out_path, lang="ko"):
        with open(out_path, "wb") as f:
            f.write(b"AUD")
        return {"sec": 4.0, "cost": 0.0, "words": []}

    monkeypatch.setattr(render.image_provider, "generate_image", fake_generate)
    monkeypatch.setattr(render.tts_provider, "synthesize", fake_tts)


def test_reuse_with_visible_change_skips_generation_call(tmp_path, monkeypatch):
    """**화면이 실제로 달라지는** reuse_* 컷은 기준 스틸에서 파생하고 생성 API 를 안 부른다.

    이게 안 되면 지시서가 재사용을 선언해도 절감은 서류상으로만 남는다.
    """
    calls = {"generate": 0}
    _stub_real_image_providers(monkeypatch, calls)

    header = {"version_type": "webtoon", "global_style": "s"}
    base = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p",
            "asset_strategy": "new_asset"}
    reuse = {"cut_no": 2, "narration_ko": "b", "visual_prompt": "p",
             "asset_strategy": "reuse_with_state_change", "base_asset_ref": "1",
             "state_change": "강조 부위가 후각구에서 편도체로 옮겨간다",
             "tone_grade": "warm"}

    index: dict[int, str] = {}
    vis1, kind1, *_ = render._gen_cut_assets(base, header, str(tmp_path), 0, None, "ko", index)
    index[1] = vis1
    vis2, kind2, *_ = render._gen_cut_assets(reuse, header, str(tmp_path), 1, None, "ko", index)

    assert kind1 == "image" and kind2 == "image"
    assert calls["generate"] == 1, "재사용 컷이 생성 API 를 불렀다 — 절감이 사라진다"
    assert crop.mean_abs_delta(vis1, vis2) >= render.config.REUSE_MIN_PIXEL_DELTA


def test_reuse_without_any_visible_change_is_regenerated(tmp_path, monkeypatch):
    """★ 2026-08-29 실측 사고의 회귀 테스트.

    크롭도 톤도 오버레이도 없는 재사용은 기준 컷을 **바이트까지 그대로** 복사했다. 실제로
    완성 영상의 컷5와 컷6 이 동일한 파일이었고, 시청자에게는 화면이 멈춘 것으로 보였다.
    같은 인물·같은 부품이 다시 나오는 것 자체는 옳다(서사가 진행되니까) — 문제는 **아무것도
    안 변한 반복**이다. 그런 컷은 아껴서는 안 되고 새로 그려야 한다.
    """
    calls = {"generate": 0}
    _stub_real_image_providers(monkeypatch, calls)

    header = {"version_type": "photo", "global_style": "s"}
    base = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p",
            "asset_strategy": "new_asset"}
    flat = {"cut_no": 2, "narration_ko": "b", "visual_prompt": "p",
            "asset_strategy": "reuse_background_new_overlay", "base_asset_ref": "1"}

    index: dict[int, str] = {}
    vis1, *_ = render._gen_cut_assets(base, header, str(tmp_path), 0, None, "ko", index)
    index[1] = vis1
    vis2, _kind, _a, _m, cost2, _w = render._gen_cut_assets(
        flat, header, str(tmp_path), 1, None, "ko", index)

    assert calls["generate"] == 2, "변화 없는 재사용이 같은 그림을 그대로 내보냈다"
    assert cost2 > 0.0
    assert crop.mean_abs_delta(vis1, vis2) >= render.config.REUSE_MIN_PIXEL_DELTA


def test_reuse_falls_back_to_generation_when_base_missing(tmp_path, monkeypatch):
    """참조가 깨졌으면 화면을 비우지 말고 새로 생성한다(저장된 옛 지시서 방어)."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")
    calls = {"generate": 0}

    def fake_generate(cut, header, out_path, model="", ref_path=None):
        calls["generate"] += 1
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG")
        return out_path, render.config.GEMINI_IMAGE_COST_USD

    def fake_tts(cut, out_path, lang="ko"):
        with open(out_path, "wb") as f:
            f.write(b"AUD")
        return {"sec": 4.0, "cost": 0.0, "words": []}

    monkeypatch.setattr(render.image_provider, "generate_image", fake_generate)
    monkeypatch.setattr(render.tts_provider, "synthesize", fake_tts)

    orphan = {"cut_no": 2, "narration_ko": "b", "visual_prompt": "p",
              "asset_strategy": "reuse_zoom", "base_asset_ref": "99"}
    vis, kind, *_ = render._gen_cut_assets(orphan, header={}, work_dir=str(tmp_path),
                                           idx=0, directive_id=None, lang="ko",
                                           asset_index={})
    assert kind == "image" and calls["generate"] == 1
    assert os.path.exists(vis)


def test_new_asset_strategy_still_generates(tmp_path, monkeypatch):
    """재사용이 아닌 컷의 기존 동작은 그대로다(회귀 가드)."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")
    calls = {"generate": 0}

    def fake_generate(cut, header, out_path, model="", ref_path=None):
        calls["generate"] += 1
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG")
        return out_path, render.config.GEMINI_IMAGE_COST_USD

    def fake_tts(cut, out_path, lang="ko"):
        with open(out_path, "wb") as f:
            f.write(b"AUD")
        return {"sec": 4.0, "cost": 0.0, "words": []}

    monkeypatch.setattr(render.image_provider, "generate_image", fake_generate)
    monkeypatch.setattr(render.tts_provider, "synthesize", fake_tts)

    cut = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p"}
    render._gen_cut_assets(cut, {}, str(tmp_path), 0, None, "ko", {})
    assert calls["generate"] == 1


# ── 장면 파생(웹툰 v1 §3) — 크롭이 생성 호출을 늘리지 않는다 ──
def _stub_providers(monkeypatch, calls):
    """이미지 생성·TTS 를 가짜로 바꾼다. 세 파생 테스트가 같은 배선을 쓴다."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")

    def fake_generate(cut, header, out_path, model="", ref_path=None):
        calls["generate"] += 1
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG-base")
        return out_path, render.config.GEMINI_IMAGE_COST_USD

    def fake_tts(cut, out_path, lang="ko"):
        with open(out_path, "wb") as f:
            f.write(b"AUD")
        return {"sec": 4.0, "cost": 0.0, "words": []}

    monkeypatch.setattr(render.image_provider, "generate_image", fake_generate)
    monkeypatch.setattr(render.tts_provider, "synthesize", fake_tts)


def test_cropped_derived_cut_costs_zero_and_generates_nothing(tmp_path, monkeypatch):
    """파생 컷이 유료 생성을 부르면 이 기능의 존재 이유가 사라진다.

    지시서 v2 의 절감 근거가 바로 이것이다 — 장면 4장 생성 + 컷 4개 파생 = 8장 생성의 절반.
    """
    calls = {"generate": 0, "derive": 0}
    _stub_providers(monkeypatch, calls)

    def fake_derive(base, out, crop_spec, tone):
        calls["derive"] += 1
        with open(out, "wb") as f:
            f.write(b"\x89PNG-derived")

    monkeypatch.setattr(render.crop, "derive_image", fake_derive)

    header = {"version_type": "webtoon", "global_style": "s"}
    base = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p", "asset_strategy": "new_asset"}
    derived = {"cut_no": 2, "narration_ko": "b", "visual_prompt": "p",
               "asset_strategy": "reuse_zoom", "base_asset_ref": "1",
               "crop": {"cx": 0.5, "cy": 0.42, "scale": 2.2}, "tone_grade": "none"}

    index: dict[int, str] = {}
    vis1, _, _, _, cost1, _ = render._gen_cut_assets(base, header, str(tmp_path), 0, None,
                                                     "ko", index)
    index[1] = vis1
    vis2, kind2, _, _, cost2, _ = render._gen_cut_assets(derived, header, str(tmp_path), 1, None,
                                                         "ko", index)

    assert calls["generate"] == 1, "파생 컷이 생성 API 를 불렀다"
    assert calls["derive"] == 1, "크롭이 실제로 일어나지 않았다"
    assert cost1 > 0 and cost2 == 0.0
    assert kind2 == "image"
    # 파생물은 기준과 **다른** 파일이어야 한다(단순 복사로 퇴행하지 않았는지).
    assert open(vis2, "rb").read() != open(vis1, "rb").read()


def test_broken_derive_falls_back_to_copy_not_generation(tmp_path, monkeypatch):
    """크롭이 깨져도 유료 생성으로 떨어지지 않는다 — 이 기능의 핵심 안전 속성이다."""
    calls = {"generate": 0}
    _stub_providers(monkeypatch, calls)

    def exploding_derive(base, out, crop_spec, tone):
        raise RuntimeError("PIL 폭발")

    monkeypatch.setattr(render.crop, "derive_image", exploding_derive)

    header = {"version_type": "webtoon", "global_style": "s"}
    base = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p", "asset_strategy": "new_asset"}
    derived = {"cut_no": 2, "narration_ko": "b", "visual_prompt": "p",
               "asset_strategy": "reuse_crop", "base_asset_ref": "1",
               "crop": {"cx": 0.3, "cy": 0.6, "scale": 2.0}}

    index: dict[int, str] = {}
    vis1, *_ = render._gen_cut_assets(base, header, str(tmp_path), 0, None, "ko", index)
    index[1] = vis1
    vis2, kind2, _, _, cost2, _ = render._gen_cut_assets(derived, header, str(tmp_path), 1, None,
                                                         "ko", index)

    assert calls["generate"] == 1, "파생 실패가 유료 생성으로 이어졌다"
    assert cost2 == 0.0 and kind2 == "image"
    assert open(vis2, "rb").read() == open(vis1, "rb").read()   # 기준 이미지 그대로


def test_video_cut_still_is_indexed_for_later_reuse(tmp_path, monkeypatch):
    """영상 컷의 첫 프레임도 뒤 컷이 base_asset_ref 로 가리킬 수 있어야 한다.

    지시서 v2 매핑의 마지막 컷(첫 장면으로 되돌아오는 루프)이 정확히 이 경우다.
    인덱싱이 없으면 이미 만들어 둔 스틸이 있는데도 새로 생성한다.
    """
    calls = {"generate": 0}
    _stub_real_image_providers(monkeypatch, calls)
    # Veo 는 실패시켜 스틸 폴백으로 보낸다 — 이 테스트가 보는 것은 인덱싱이지 클립이 아니다.
    monkeypatch.setattr(render, "_gen_veo_clip", lambda *a, **k: (False, None, 0.0))

    header = {"version_type": "webtoon", "global_style": "s"}
    video_cut = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p",
                 "asset_strategy": "new_asset", "motion_source": "video"}
    # ★ 이 테스트가 보는 것은 **인덱싱**이다. 다만 재사용 컷은 화면이 실제로 달라져야 통과하는
    #   계약이 생겼으므로(2026-08-29), 톤 변화를 준다. 안 그러면 "인덱싱은 됐는데 변화가 없어
    #   새로 그렸다"가 되어 이 테스트가 인덱싱을 검증하지 못한다.
    later = {"cut_no": 2, "narration_ko": "b", "visual_prompt": "p",
             "asset_strategy": "reuse_with_state_change", "base_asset_ref": "1",
             "state_change": "같은 장면이 밤으로 넘어간다", "tone_grade": "warm"}

    index: dict[int, str] = {}
    render._gen_cut_assets(video_cut, header, str(tmp_path), 0, None, "ko", index)
    assert 1 in index, "영상 컷의 첫 프레임이 인덱싱되지 않았다"

    _, _, _, _, cost2, _ = render._gen_cut_assets(later, header, str(tmp_path), 1, None,
                                                  "ko", index)
    assert calls["generate"] == 1, "영상 컷을 참조한 재사용이 새 이미지를 만들었다"
    assert cost2 == 0.0


def test_video_cut_first_frame_can_itself_be_derived(tmp_path, monkeypatch):
    """되돌아오는 영상 컷은 첫 장면을 파생해 쓰고 새로 생성하지 않는다."""
    calls = {"generate": 0, "derive": 0}
    _stub_providers(monkeypatch, calls)

    def fake_derive(base, out, crop_spec, tone):
        calls["derive"] += 1
        with open(out, "wb") as f:
            f.write(b"\x89PNG-graded")

    monkeypatch.setattr(render.crop, "derive_image", fake_derive)
    monkeypatch.setattr(render, "_gen_veo_clip", lambda *a, **k: (False, None, 0.0))

    header = {"version_type": "webtoon", "global_style": "s"}
    opener = {"cut_no": 1, "narration_ko": "a", "visual_prompt": "p",
              "asset_strategy": "new_asset"}
    loop_back = {"cut_no": 8, "narration_ko": "z", "visual_prompt": "p",
                 "asset_strategy": "reuse_with_state_change", "base_asset_ref": "1",
                 "tone_grade": "red", "motion_source": "video"}

    index: dict[int, str] = {}
    vis1, *_ = render._gen_cut_assets(opener, header, str(tmp_path), 0, None, "ko", index)
    index[1] = vis1
    _, _, _, _, cost8, _ = render._gen_cut_assets(loop_back, header, str(tmp_path), 7, None,
                                                  "ko", index)

    assert calls["generate"] == 1, "루프 컷이 첫 장면을 다시 생성했다"
    assert calls["derive"] == 1, "톤 그레이딩이 적용되지 않았다"
    assert cost8 == 0.0
