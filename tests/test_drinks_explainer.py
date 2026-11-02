"""주류 설명형 릴스 — 편집표·강제 조건·자동 검사·키·공급자 어댑터(기획 v2 §3). 유료·네트워크 호출 0.

지키는 것: 모든 화면은 클립의 한 구간 · 모자라면 메우지 않고 멈춤 · 렌더는 사지 않음 · 사진 대체 경로 없음 · 길이는 잰다 · 후보끼리 파일이 합쳐지지 않음.
ffmpeg 가 없으면 파일을 만드는 시험은 건너뛴다(순수 로직은 그대로 돈다).
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import config
from engine import drinks_develop as dd
from engine import drinks_explainer as dx
from engine import drinks_paid as dpaid
from engine import render_qa
from engine.drinks_render import sha256_file
from engine.providers import video as pv
from scripts import explainer_rehearsal as rehearsal

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "engine" / "drinks_explainer.py").read_text(encoding="utf-8")
SQL = (ROOT / "supabase" / "migrations" / "0062_drinks_explainer_assets.sql").read_text(encoding="utf-8")
GOLD = json.loads((ROOT / "docs" / "drinks-pilot" / "whisky-water-v1.json").read_text(encoding="utf-8"))
ROLES = {a: r for a, r, _ in rehearsal.ASSET_PLAN}
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg 없음")


def timeline():
    return dx.build_timeline(rehearsal.plan_beats(), ROLES, hook_text=rehearsal.HOOK, speed=1.2)


# ── 길이·계획(§3-6-2) ───────────────────────────────────────────

def test_script_range_is_final_range_times_speed():
    lo, hi = config.DRINKS_EXPLAINER_FINAL_SEC
    assert (lo, hi) == (40.0, 55.0)
    assert config.DRINKS_DEVELOP_SECONDS == (lo * config.DRINKS_EXPLAINER_PLAYBACK_SPEED, hi * config.DRINKS_EXPLAINER_PLAYBACK_SPEED) == (48.0, 66.0)
    assert config.DRINKS_DEVELOP_SCENES == (8, 11)


def test_plan_prompt_and_check_read_the_same_config(monkeypatch):
    assert "장면은 8~11개" in dd.plan_system() and "48~66초" in dd.plan_system()
    assert "30~40" not in dd.plan_system() and "5~7" not in dd.plan_system()
    monkeypatch.setattr(config, "DRINKS_DEVELOP_SCENES", (2, 3))
    monkeypatch.setattr(config, "DRINKS_DEVELOP_SECONDS", (10.0, 12.0))
    assert "장면은 2~3개" in dd.plan_system() and "10~12초" in dd.plan_system()
    scenes = [{"narration": "왜일까?", "timing_sec": 5}, {"narration": "그래요", "timing_sec": 6}]
    assert not {f.code for f in dd.develop_checks({"scenes": scenes, "viewer_conclusion": {"text": "x"}}, set())} & {"scene_count", "duration_out_of_range"}
    monkeypatch.setattr(config, "DRINKS_DEVELOP_SCENES", (8, 11))
    assert "scene_count" in {f.code for f in dd.develop_checks({"scenes": scenes, "viewer_conclusion": {"text": "x"}}, set())}


def test_timeline_reproduces_the_48s_plan():
    tl = timeline()
    assert tl.raw_ms == 57600 and tl.final_ms == 48000
    assert sum(ms for _, _, ms in rehearsal.ASSET_PLAN) == 64000 and sum(1 for _, r, _ in rehearsal.ASSET_PLAN if r == "mechanism") == 3
    first, second, third, fourth = tl.cuts[:4]
    assert (first.asset_id, first.src_start_ms, first.src_end_ms, first.timeline_start_ms, first.timeline_end_ms, first.boundary) == ("M1", 5400, 7200, 0, 1800, "loop")
    assert (second.asset_id, second.src_start_ms, second.src_end_ms, second.boundary) == ("R1", 0, 1800, "flash_forward")
    assert (third.asset_id, third.src_start_ms, third.boundary, third.zoom) == ("M1", 0, "cut_to_mechanism", 1.0), "앞당겨 보여 주기가 뒤 구간을 먹지 않는다"
    assert (fourth.asset_id, fourth.src_start_ms, fourth.boundary, fourth.zoom) == ("M1", third.src_end_ms, "same_clip", 1.15), "같은 클립을 이어 자를 때만 확대"
    for c in tl.cuts:
        assert all(isinstance(v, int) for v in (c.src_start_ms, c.src_end_ms, c.timeline_start_ms, c.timeline_end_ms))
        assert (c.timeline_end_ms - c.timeline_start_ms) / 1.2 <= config.DRINKS_EXPLAINER_CUT_MAX_FINAL_MS
    planned = {a: ms for a, _, ms in rehearsal.ASSET_PLAN}
    assert dx.plan_margin_problems(tl.cuts, planned) == [], "계획 규칙: 사용 길이 ≤ 자산 길이 − 0.5초"
    assert dx.slot_min_src_ms(tl.cuts)["M1"] == 7700, "가장 늦은 사용 지점 + 200ms(§3-3)"


def test_final_is_raw_divided_by_speed():
    assert dx.raw_to_final_ms(32640, 1.2) == 27200   # §3-6 표
    assert dx.final_to_raw_ms(1500, 1.2) == 1800


def test_hook_is_first_cut_only_and_bottom_captions_cover_speech():
    tl = timeline()
    hooks = [(c.cut_id, ly) for c in tl.cuts for ly in c.subtitle_layers if ly.kind == "hook"]
    assert [h[0] for h in hooks] == ["E1"] and hooks[0][1].start_ms == 0 and hooks[0][1].end_ms == 1800
    band = [config.RENDER_HEIGHT * p for p in config.DRINKS_EXPLAINER_HOOK_BAND_PCT]
    assert band[0] <= hooks[0][1].box[1] and hooks[0][1].box[3] <= band[1]
    phrases = [ly for c in tl.cuts for ly in c.subtitle_layers if ly.kind == "phrase"]
    assert phrases and any(ly.accent == "자리 표시" for ly in phrases)
    assert all(any(ly.kind == "depiction" for ly in c.subtitle_layers) for c in tl.cuts), "화면 표기(§3-4)는 모든 컷에"
    bad = [ly for c in tl.cuts for ly in c.subtitle_layers if not dx._box_in_safe_area(list(ly.box)) or ly.overflow]
    assert not bad, bad[:2]


def test_too_long_caption_is_flagged_not_cut():
    long = dx.layout_caption("hook", "가" * 80)
    assert long["overflow"] is True and "".join(long["lines"]) == "가" * 80, "자르지 않는다"


def test_ass_uses_positions_without_auto_wrap_and_strips_override_chars():
    tl = timeline()
    ass = dx.build_ass(tl.cuts)
    assert "WrapStyle: 2" in ass and "\\pos(510,392)" in ass and "\\an8" in ass and "Pretendard" in ass
    assert "\\c&H00E0FF&" in ass, "핵심 낱말 강조색(CAPTION_HIGHLIGHT_COLOR)"
    assert dx._ass_text("a{\\b1}b") == "ab1b"


@pytest.mark.parametrize("change", [
    {"zoom": 1.2}, {"src_end_ms": 9999}, {"timeline_start_ms": 5}, {"boundary": "hold"}, {"asset_id": ""}, {"src_start_ms": 1.5},
])
def test_invalid_edit_cuts_stop(change):
    base = dx.EditCut("E1", "B1", "M1", 0, 1000, 0, 1000, "loop")
    with pytest.raises(dx.ExplainerStop) as e:
        dx.validate_edit_cuts([dataclasses.replace(base, **change)])
    assert e.value.code == "edit_cut_invalid" and e.value.state == "auto_qa_fail"


def test_slow_playback_is_refused(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PLAYBACK_SPEED", 0.9)
    with pytest.raises(dx.ExplainerStop) as e:
        dx.playback_speed()
    assert e.value.code == "edit_cut_invalid"


def test_beat_time_mismatch_stops():
    beat = dx.Beat("B1", 1000, (dx.Shot("M1", "loop", raw_ms=400), dx.Shot("R1", "match", raw_ms=400)))
    with pytest.raises(dx.ExplainerStop):
        dx.build_timeline([beat], ROLES)


# ── 시각 주장표(§3-4) ──────────────────────────────────────────

CLAIMS = [{"claim_id": "c1", "original_quote": "Ethanol at 40% inhibits growth"}]


def scene(**kw):
    base = {"narration": "왜일까?", "visual_role": "mechanism", "claim_ids": ["c1"], "visual_claim_ko": "에탄올이 미생물을 억제한다",
            "allowed_simplification": "미생물 = 초록 알갱이", "forbidden_misreading": "미생물이 죽어 사라진다", "depiction_label": "설명용 도해", "motion_prompt": "the microbes approach and stop"}
    base.update(kw)
    return base


@pytest.mark.parametrize("sc, code", [
    (scene(), None),
    (scene(motion_prompt=" "), "motion_prompt_missing"),
    (scene(visual_claim_ko=""), "visual_claim_missing"),
    (scene(forbidden_misreading=None), "visual_claim_missing"),
    (scene(depiction_label="CG 연출"), "depiction_label_mismatch"),
    (scene(visual_role="reality", depiction_label="설명용 도해"), "depiction_label_mismatch"),
    (scene(claim_ids=[]), "visual_claim_no_evidence"),
    (scene(claim_ids=[], visual_claim_ko="장면 분위기: 도입"), None),
    (scene(claim_ids=[], visual_claim_ko="장면 분위기: 40% 술"), "visual_claim_number_unsupported"),
    (scene(visual_claim_ko="에탄올 40%가 억제한다"), None),
    (scene(visual_claim_ko="에탄올 60%가 억제한다"), "visual_claim_number_unsupported"),
    (scene(visual_role="text_card"), "explainer_still_card"),
])
def test_visual_claim_checks(sc, code):
    found = {f.code for f in dd.visual_claim_checks({"scenes": [sc]}, CLAIMS)}
    assert found == ({code} if code else set())


def test_visual_claim_table_goes_in_the_result_because_the_db_strips_it():
    validator = (ROOT / "supabase" / "migrations" / "0057_drinks_slide_reel.sql").read_text(encoding="utf-8")
    assert "visual_claim_ko" not in validator, "DB 검증기가 칸을 보존하게 되면 이 우회를 다시 봐야 한다"
    rows = dd.visual_claim_table({"scenes": [scene()]})
    assert rows[0]["scene"] == 1 and rows[0]["visual_claim_ko"] == "에탄올이 미생물을 억제한다" and rows[0]["depiction_label"] == "설명용 도해"
    assert "visual_claim_ko" in dd.plan_system() and "forbidden_misreading" in dd.plan_system() and "text_card 금지" in dd.plan_system()


# ── 자동 검사(§3-8 A) ─────────────────────────────────────────

def good_signals():
    return {"probe": {"ok": True, "has_video": True, "duration_ms": 48033, "width": 1080, "height": 1920, "fps": 30.0, "video_codec": "h264",
                      "audio_codec": "aac", "audio_sample_rate": 48000},
            "bytes": 20_000_000, "moov_first": True, "freeze": [], "black": [], "lufs": -14.1, "errors": []}


def good_manifest():
    tl = timeline()
    return {"playback_speed": 1.2, "final_ms": tl.final_ms, "video_fallbacks": [], "pre_caption_freeze": [], "timeline_warnings": [],
            "cuts": [{"kind": "clip", "cut_id": c.cut_id, "asset_id": c.asset_id, "src_start_ms": c.src_start_ms, "src_end_ms": c.src_end_ms,
                      "timeline_start_ms": c.timeline_start_ms, "timeline_end_ms": c.timeline_end_ms, "zoom": c.zoom,
                      "subtitle_layers": [dx._layer_row(ly) for ly in c.subtitle_layers]} for c in tl.cuts]}


def codes(sig=None, man=None):
    return dx.evaluate_auto_qa(sig or good_signals(), man or good_manifest()).blocks


def test_clean_render_passes_with_only_hook_length_notes():
    r = dx.evaluate_auto_qa(good_signals(), good_manifest())
    assert r.ok and r.state == "auto_qa_pass" and r.blocks == []
    assert r.warns == ["cut_under_min:E1", "cut_under_min:E2"], "훅 컷 1.5초는 §2-2 2초 규칙 밖 — 막지 않고 알린다"


@pytest.mark.parametrize("patch, code", [
    ({"duration_ms": 39000}, "duration_out_of_range"),
    ({"duration_ms": 56000}, "duration_out_of_range"),
    ({"duration_ms": 47000}, "duration_manifest_mismatch"),
    ({"width": 720, "height": 1280}, "spec_not_1080x1920"),
    ({"fps": 20.0}, "reel_fps_out_of_range"),
    ({"video_codec": "vp9"}, "reel_video_codec"),
    ({"audio_codec": "mp3"}, "reel_audio_codec"),
    ({"audio_sample_rate": 96000}, "reel_audio_rate_over_48k"),
])
def test_spec_and_duration_block(patch, code):
    s = good_signals()
    s["probe"].update(patch)
    assert code in codes(sig=s)


@pytest.mark.parametrize("patch, code", [
    ({"freeze": [[3.0, 0.8]]}, "freeze"),
    ({"black": [[3.0, 0.3]]}, "black_frames"),
    ({"lufs": -11.5}, "loudness_off_target"),
    ({"lufs": -16.5}, "loudness_off_target"),
    ({"lufs": None}, "loudness_unmeasured"),
    ({"bytes": 400 * 1024 * 1024}, "reel_file_too_big"),
    ({"moov_first": False}, "reel_moov_not_first"),
    ({"errors": ["detect_failed"]}, "detect_failed"),
])
def test_video_signals_block(patch, code):
    s = good_signals()
    s.update(patch)
    assert code in codes(sig=s)


def test_thresholds_near_the_edges():
    s = good_signals()
    s.update(freeze=[[3.0, 0.79]], black=[[3.0, 0.29]], lufs=-12.1)
    assert codes(sig=s) == []


def test_measuring_failure_never_passes():
    s = {"probe": {"ok": False, "has_video": False, "duration_ms": 0, "error": "x"}, "bytes": 0, "moov_first": False, "freeze": [], "black": [], "lufs": None, "errors": ["probe_failed"]}
    assert "probe_failed" in codes(sig=s) and "loudness_unmeasured" in codes(sig=s)


def test_manifest_rules():
    m = good_manifest()
    m["cuts"][3]["kind"] = "hold"
    assert "manifest_cut_not_clip:E4" in codes(man=m)
    m = good_manifest()
    m["cuts"][5]["src_end_ms"] = None
    assert "manifest_cut_no_source:E6" in codes(man=m)
    m = good_manifest()
    m["video_fallbacks"] = [3]
    assert "manifest_fallback_recorded" in codes(man=m)
    m = good_manifest()
    m["cuts"][2]["timeline_start_ms"] += 1
    assert "manifest_timeline_gap:E3" in codes(man=m)
    assert "manifest_no_cuts" in codes(man={**good_manifest(), "cuts": []})
    m = good_manifest()
    m["cuts"][1]["zoom"] = 1.3
    assert "manifest_zoom_over:E2" in codes(man=m)
    m = good_manifest()
    m["pre_caption_freeze"] = [[2.0, 1.0]]
    assert "freeze_under_captions" in codes(man=m), "문턱 0.8초 × 1.2배 = 0.96초(배속 전)"


def test_caption_and_hook_rules():
    def with_layer(i, kind, **kw):
        m = good_manifest()
        layer = next(ly for ly in m["cuts"][i]["subtitle_layers"] if ly["kind"] == kind)
        layer.update(kw)
        return m
    assert any(c.startswith("caption_out_of_safe_area") for c in codes(man=with_layer(5, "phrase", box=[60, 1500, 500, 1600])))   # 아래 340px 침범
    assert any(c.startswith("caption_out_of_safe_area") for c in codes(man=with_layer(5, "phrase", box=[60, 1500, 1000, 1570])))  # 오른쪽 120px 침범
    assert any(c.startswith("caption_overflow") for c in codes(man=with_layer(5, "phrase", overflow=True)))
    assert "hook_out_of_band" in codes(man=with_layer(0, "hook", box=[100, 200, 900, 300]))
    assert "hook_outside_window" in codes(man=with_layer(0, "hook", end_ms=2400))
    assert "hook_outside_window" in codes(man=with_layer(0, "hook", start_ms=100))
    m = good_manifest()
    m["cuts"][0]["subtitle_layers"] = [ly for ly in m["cuts"][0]["subtitle_layers"] if ly["kind"] != "hook"]
    assert "hook_missing" in codes(man=m)
    m = good_manifest()
    m["cuts"][1]["subtitle_layers"].append(dict(next(ly for ly in m["cuts"][0]["subtitle_layers"] if ly["kind"] == "hook")))
    assert "hook_not_first_cut_only" in codes(man=m)


def test_shared_freeze_warning_is_untouched():
    assert config.RENDER_QA_MAX_FREEZE_SEC == 3.0 and config.RENDER_QA_FREEZE_BLOCKS is False
    assert config.DRINKS_EXPLAINER_FREEZE_MIN_SEC == 0.8 and config.DRINKS_EXPLAINER_FREEZE_NOISE == "-55dB"


def test_freeze_parser_catches_a_video_frozen_to_the_end():
    log = "[freezedetect @ 0] lavfi.freezedetect.freeze_start: 1.5\n[freezedetect @ 0] lavfi.freezedetect.freeze_duration: 2\n[freezedetect @ 0] lavfi.freezedetect.freeze_end: 3.5\n[freezedetect @ 0] lavfi.freezedetect.freeze_start: 40\n"
    assert render_qa.parse_freeze_spans(log, 48.0) == [(1.5, 2.0), (40.0, 8.0)]


# ── 상태(§3-9)·키(§3-3)·견적(§3-7) ─────────────────────────────

def test_state_machine():
    assert dx.EPISODE_FLOW[0] == "plan_draft" and dx.EPISODE_FLOW[-1] == "ready_to_publish"
    assert dx.can_transition("assets_complete", "rehearsal") and not dx.can_transition("assets_complete", "rendered"), "건너뛰지 못한다"
    assert dx.can_transition("rendered", "blocked_assets") and not dx.can_transition("blocked_assets", "buying"), "막힌 뒤 자동 재구매 없음"
    assert set(dx.FAILURE_STATES) == {"blocked_assets", "blocked_no_pass", "blocked_budget", "unknown_billed", "auto_qa_fail", "review_fail"}
    assert dx.AUTO_REBUY is False and dx.BLOCKED_ASSET_CODES == ("clip_missing", "clip_corrupt", "clip_short")
    for code in dx.BLOCKED_ASSET_CODES:
        assert dx.ExplainerStop(code, "x").state == "blocked_assets"


def test_ids_and_idempotency_key_match_the_sql_formula():
    s = dx.slot_id("P", 1)
    c = dx.candidate_id(s, 1)
    a = dx.attempt_id(c, 1)
    assert (s, c, a) == ("P:A1", "P:A1#c1", "P:A1#c1#a1")
    spec = "a" * 64
    assert dx.idempotency_key(a, spec) == hashlib.sha256((a + spec).encode()).hexdigest() == "6840b8eadc5bd23d8e5f2f09ae2ee806da9cf0c72bb4caec82fc9cdec5565455", "web/lib/drinks/explainer.db.test.ts 와 같은 값"
    with pytest.raises(ValueError):
        dx.candidate_id(s, 3)
    with pytest.raises(ValueError):
        dx.attempt_id(c, 3)
    base = dict(model="m", prompt="p", start_image_sha256="s", clip_sec=8, resolution="720p")
    assert dx.spec_hash(**base) == dx.spec_hash(**base)
    for change in ({"model": "n"}, {"prompt": "q"}, {"start_image_sha256": "t"}, {"clip_sec": 6}, {"resolution": "1080p"}):
        assert dx.spec_hash(**{**base, **change}) != dx.spec_hash(**base)


def test_limits_match_the_migration():
    lim = dict(re.findall(r"'([a-z_]+)', ([0-9]+)", SQL.split("drinks_explainer_limits()")[1].split("$$;")[0]))
    assert int(lim["max_candidates_per_slot"]) == config.DRINKS_EXPLAINER_MAX_CANDIDATES_PER_SLOT == 2
    assert int(lim["max_attempts_per_candidate"]) == config.DRINKS_EXPLAINER_MAX_ATTEMPTS_PER_CANDIDATE == 2
    assert int(lim["max_attempts_per_slot"]) == config.DRINKS_EXPLAINER_MAX_ATTEMPTS_PER_SLOT == 4
    assert "enable row level security" in SQL and "되돌리기" in SQL
    assert re.search(r"revoke all on table .*from anon, authenticated", SQL)
    assert "where state in ('requested','generating','received','probed','unknown_billed')" in SQL


def test_boundary_kinds_match_the_migration():
    allowed = re.search(r"boundary_in\s+text check \(boundary_in in \(([^)]*)\)\)", SQL).group(1)
    # 'cut' 은 0067 이 더했다(tests/test_drinks_explainer_queue.py 가 그 체크를 대조).
    assert set(re.findall(r"'(\w+)'", allowed)) | {"cut"} == set(config.DRINKS_EXPLAINER_BOUNDARY_KINDS)


def test_quote_matches_the_document_table():
    omni = dx.quote_explainer("omni")
    veo = dx.quote_explainer("veo_fast")
    assert (omni["estimate_usd"], omni["cap_usd"]) == (7.95, 8.90)
    assert (veo["estimate_usd"], veo["cap_usd"]) == (6.40, 7.20)
    assert omni["as_of"] == "2026-10-31" and omni["per_sec_usd"] == 0.10136
    with pytest.raises(ValueError):
        dx.quote_explainer("veo_lite")


# ── 사진·길이 보정 경로가 없다(정적 시험) ─────────────────────────

def _engine_imports() -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            out.add(node.module or "")
            if not node.module:
                out.update(a.name for a in node.names)
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_render_module_has_no_still_or_stretch_route():
    forbidden_imports = {"clip_fit", "clip_fit_types", "render", "providers", "providers.video", "providers.image", "drinks_paid", "video", "image", "drinks_produce"}
    assert not (_engine_imports() & forbidden_imports), "렌더는 공급자·길이 보정·사진 대체 경로를 import 하지 않는다"
    for token in ("clip_fit", "ken_burns", "zoompan", "tpad", "reverse", "VIDEO_FALLBACKS", "build_still_video_command", "build_pad_video_command",
                  "effect_filter", "build_cut_command", "pingpong", "stop_mode", "-loop", "generate_clip", "render_directive_local", "plan_to_directive"):
        assert token not in SRC, token


def test_render_uses_only_named_assemble_helpers():
    used = {n.attr for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "assemble"}
    # build_last_frame_command 는 다음 슬롯 시작 그림의 참고 프레임을 뽑을 뿐이다(§3-5, last_frame). 편집표·타임라인에 들어가지 않는다.
    assert used == {"build_concat_clips_command", "build_loudnorm_command", "build_speed_command", "filter_path", "build_last_frame_command"}, used
    assert "last_frame(" not in SRC[SRC.index("def render_explainer"):SRC.index("def measure_final")], "렌더는 마지막 프레임을 쓰지 않는다"


def test_cut_filter_touches_no_time_and_caps_zoom():
    for vf in (dx.cut_filter(1.0), dx.cut_filter(1.15)):
        for token in ("setpts", "tpad", "reverse", "loop", "zoompan", "minterpolate"):
            assert token not in vf
    argv = dx.build_cut_argv(dx.EditCut("E1", "B1", "M1", 5400, 7200, 0, 1800, "loop"), "a.mp4", "o.mp4")
    assert argv[argv.index("-frames:v") + 1] == "54" and "-an" in argv and "-loop" not in argv
    assert argv[argv.index("-ss") + 1] == "5.400" and argv.index("-ss") < argv.index("-i")


def test_render_refuses_while_a_paid_provider_cannot_be_forced_off(monkeypatch):
    monkeypatch.setattr(config, "image_is_paid", lambda: True)
    with pytest.raises(dx.ExplainerStop) as e:
        with dx.free_providers():
            pass
    assert e.value.code == "paid_disabled"


def test_free_guard_restores_providers():
    monkeypatch_prev = (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER)
    with dx.free_providers():
        assert (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER) == ("reuse", "placeholder")
        assert not config.image_is_paid() and not config.video_is_paid()
    assert (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER) == monkeypatch_prev


# ── 강제 시험 4종 + 3종(ffmpeg) ───────────────────────────────

@pytest.fixture(scope="module")
def fake(tmp_path_factory):
    base = tmp_path_factory.mktemp("explainer-한글경로")
    assets = rehearsal.make_assets(base / "clips")
    beats = rehearsal.make_narration(rehearsal.plan_beats(), base / "narration", "")
    return base, assets, beats


@needs_ffmpeg
def test_all_forced_stops_stop_with_no_cost_no_still_no_output(fake):
    base, assets, beats = fake
    rows = rehearsal.run_forced(assets, beats, base / "run")
    assert [r["case"] for r in rows][:4] == ["1", "2", "3", "4"]
    for r in rows:
        assert r["stopped"], r
        assert r["code"] == r["expected"], r
        assert r["state"] == "blocked_assets", r
        assert r["paid_calls"] == 0 and r["stills_used"] == 0 and r["cuts_rendered"] == 0, r
        assert r["output_exists"] is False, "지난번 출력도 남지 않는다"


@needs_ffmpeg
def test_problems_are_all_listed(fake, tmp_path):
    base, assets, beats = fake
    case = rehearsal._copy_assets(assets, tmp_path / "c")
    os.remove(case["M2"].path)
    shutil.copyfile(case["R5"].path, case["M3"].path)
    tl = dx.build_timeline(beats, ROLES, hook_text=rehearsal.HOOK, speed=1.2)
    with pytest.raises(dx.ExplainerStop) as e:
        dx.check_assets(tl.cuts, case)
    assert {(p["code"], p["asset_id"]) for p in e.value.problems} == {("clip_missing", "M2"), ("clip_corrupt", "M3")}


@needs_ffmpeg
def test_declared_length_is_not_believed(fake, tmp_path):
    """계획 길이를 8초로 적어도 실제 길이로 판정한다(E5)."""
    base, assets, beats = fake
    p = tmp_path / "M1.mp4"
    rehearsal.make_fake_clip(str(p), 7200)
    case = {**assets, "M1": dataclasses.replace(assets["M1"], path=str(p), sha256=sha256_file(str(p)), planned_ms=8000)}
    tl = dx.build_timeline(beats, ROLES, speed=1.2)
    with pytest.raises(dx.ExplainerStop) as e:
        dx.check_assets(tl.cuts, case)
    assert e.value.code == "clip_short" and e.value.asset_id == "M1"
    probe = dx.probe_clip(str(p))
    assert 7150 <= probe["duration_ms"] <= 7260 and probe["width"] == 720 and probe["height"] == 1280 and probe["frames"] > 100


@needs_ffmpeg
def test_probe_reports_corrupt_but_not_a_missing_tool(tmp_path):
    p = tmp_path / "garbage.mp4"
    p.write_bytes(b"not a video at all" * 100)
    got = dx.probe_clip(str(p))
    assert got["ok"] is False and got["has_video"] is False and got["error"]


# ── 실제 조립(ffmpeg) — 짧은 표로 빠르게 ─────────────────────────

def _short_plan(tmp: Path, *, frozen_m1: bool = False, seconds: int = 4):
    clips = tmp / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    assets = {}
    for name, role in (("M1", "mechanism"), ("R1", "reality")):
        p = clips / f"{name}.mp4"
        rehearsal.make_fake_clip(str(p), 8000, frozen=frozen_m1 and name == "M1")
        assets[name] = dx.Asset(name, str(p), sha256_file(str(p)), role, 8000)
    a = tmp / "a.wav"
    b = tmp / "b.wav"
    rehearsal.make_tone(str(a), seconds * 1000)
    rehearsal.make_tone(str(b), seconds * 1000)
    beats = [dx.Beat("B1", seconds * 1000, (dx.Shot("M1", "loop", raw_ms=1800, src_start_ms=5000), dx.Shot("R1", "flash_forward")), narration="리허설 자리 표시 문장이에요.", keyword="자리 표시", narration_path=str(a)),
             dx.Beat("B2", seconds * 1000, (dx.Shot("M1", "cut_to_mechanism"),), narration="리허설 두번째 자리 표시 문장이에요.", narration_path=str(b))]
    return beats, assets


@pytest.fixture(scope="module")
def short_render(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("short-한글")
    beats, assets = _short_plan(tmp)
    out = tmp / "최종.mp4"
    rendered = dx.render_explainer(beats, assets, hook_text=rehearsal.HOOK, out_path=str(out), work_dir=str(tmp / "work"), plan_id="t")
    return tmp, rendered


@needs_ffmpeg
def test_render_makes_the_reel_from_clip_ranges_only(short_render):
    tmp, r = short_render
    probe = dx.probe_clip(r.out_path)
    assert (probe["width"], probe["height"], probe["video_codec"], probe["audio_codec"], probe["audio_sample_rate"]) == (1080, 1920, "h264", "aac", 48000)
    assert abs(probe["duration_ms"] - r.manifest["final_ms"]) < 150, "최종 = 배속 전 ÷ 1.2"
    m = json.loads(Path(r.manifest_path).read_text(encoding="utf-8"))
    assert all(c["kind"] == "clip" and c["asset_id"] in ("M1", "R1") for c in m["cuts"]) and m["video_fallbacks"] == []
    joined = " ".join(" ".join(a) for a in r.argv_log)
    for token in ("tpad", "zoompan", "reverse", "-loop", "drawtext", ".png"):
        assert token not in joined, token
    assert len(re.findall(r"(?<!a)setpts", joined)) == 1 and "setpts=PTS/1.200" in joined, "영상 시간을 건드리는 것은 조립 끝 배속 하나뿐"
    assert not [p for p in (tmp / "work").iterdir() if p.suffix.lower() in (".png", ".jpg")]


@needs_ffmpeg
def test_auto_qa_on_a_real_short_render_only_complains_about_length(short_render):
    _, r = short_render
    qa = dx.run_auto_qa(r.out_path, r.manifest)
    assert qa.blocks == ["duration_out_of_range"], (qa.blocks, qa.signals)
    assert abs(qa.signals["lufs"] - config.LOUDNESS_LUFS) <= config.DRINKS_EXPLAINER_LOUDNESS_TOLERANCE_LU


@needs_ffmpeg
def test_stale_output_disappears_when_a_later_render_stops(short_render, tmp_path):
    _, r = short_render
    out = tmp_path / "final.mp4"
    shutil.copyfile(r.out_path, out)
    beats = [dx.Beat("B1", 1000, (dx.Shot("없음", "loop"),), narration_path=str(tmp_path / "없는파일.wav"))]
    with pytest.raises(dx.ExplainerStop) as e:
        dx.render_explainer(beats, {}, hook_text="x", out_path=str(out), work_dir=str(tmp_path / "w"))
    assert e.value.code == "narration_missing" and not out.exists()


@needs_ffmpeg
def test_frozen_clip_is_blocked_even_under_changing_captions(tmp_path):
    """★ 자막이 바뀌면 최종 영상의 정지 검출이 끊길 수 있다 — 자막 입히기 전 화면에서 따로 잰 값이 잡는다."""
    beats, assets = _short_plan(tmp_path, frozen_m1=True)
    r = dx.render_explainer(beats, assets, hook_text=rehearsal.HOOK, out_path=str(tmp_path / "f.mp4"), work_dir=str(tmp_path / "w"))
    qa = dx.run_auto_qa(r.out_path, r.manifest)
    assert r.manifest["pre_caption_freeze"], "자막 전 화면은 정지로 잡힌다"
    assert "freeze_under_captions" in qa.blocks, qa.blocks


@needs_ffmpeg
def test_final_video_frozen_to_the_end_is_caught(tmp_path):
    p = tmp_path / "frozen.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=navy:s=1080x1920:d=3:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    sig = dx.measure_final(str(p))
    assert sig["freeze"] and max(d for _, d in sig["freeze"]) >= 2.0, sig["freeze"]
    assert "freeze" in dx.evaluate_auto_qa(sig, good_manifest()).blocks


@needs_ffmpeg
def test_black_frames_are_measured(tmp_path):
    p = tmp_path / "black.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=320x240:d=1:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    assert dx.measure_final(str(p))["black"], "검은 화면 0.3초 이상"


@needs_ffmpeg
@pytest.mark.parametrize("kind, text", [("hook", "(리허설) 훅 자막 자리"), ("phrase", "자리 표시 문장이에요"), ("depiction", "설명용 도해"),
                                        ("phrase", "둘째 줄까지 넘어가는 아주 긴 자리 표시 문장을 일부러 만들어 봅니다")])
def test_computed_caption_box_contains_what_libass_actually_draws(tmp_path, kind, text):
    """상자 계산이 실제 그림과 맞아야 안전 영역 검사가 뜻이 있다. 검은 배경에 그려 흰 글자 범위를 잰다."""
    from PIL import Image

    ly = dx.make_layer(kind, text, 0, 1000)
    work = tmp_path / "w"
    work.mkdir()
    dx.prepare_burn_dir(str(work))
    (work / "l.ass").write_text(dx.build_ass([dx.EditCut("E1", "B", "A", 0, 1000, 0, 1000, "loop", subtitle_layers=(ly,))]), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=1080x1920:d=0.2:r=30",
                    "-vf", "ass=filename=l.ass:fontsdir=fonts", "-frames:v", "1", "o.png"], check=True, cwd=work, capture_output=True)
    with Image.open(work / "o.png") as im:
        ink = im.convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    assert ink, "글자가 그려지지 않았다"
    x0, y0, x1, y1 = ly.box
    tol = 3
    assert x0 - tol <= ink[0] and y0 - tol <= ink[1] and ink[2] <= x1 + tol and ink[3] <= y1 + tol, (ink, ly.box)
    assert ink[2] - ink[0] > (x1 - x0) * 0.7, "상자가 실제보다 턱없이 크면 다른 글꼴로 대체된 것이다"


# ── drinks_paid: E5·후보 캐시(§3-3) ─────────────────────────────

class FakeRpc:
    def __init__(self, selected=None):
        self.calls = []
        self.selected = selected

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        return {"drinks_find_generated": [], "drinks_hold_spend": {"hold_id": "h1"}, "drinks_settle_spend": {}, "drinks_register_generated": {"asset_id": "a1"},
                "drinks_explainer_selected_asset": self.selected or {}}[fn]

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


def test_candidates_never_collapse_into_one_file_and_old_hash_is_unchanged():
    plain = dpaid.clip_item(2, "mechanism", "the envelope slides", "scene-02-mechanism", "x" * 64, clip_sec=8)
    c1 = dpaid.clip_item(2, "mechanism", "the envelope slides", "scene-02-mechanism", "x" * 64, clip_sec=8, candidate_id="P:A1#c1")
    c2 = dpaid.clip_item(2, "mechanism", "the envelope slides", "scene-02-mechanism", "x" * 64, clip_sec=8, candidate_id="P:A1#c2")
    assert len({plain.prompt_hash, c1.prompt_hash, c2.prompt_hash}) == 3
    assert c1.item_key == "P:A1#c1" and c2.item_key == "P:A1#c2", "후보마다 별도 항목 — 0054 의 시도 상한이 후보마다"
    assert plain.item_key == "scene-02-clip8" and plain.candidate_id is None
    expected = dpaid._hash({"kind": "video", "model": plain.model, "prompt": plain.prompt, "start": "x" * 64, "sec": 8})
    assert plain.prompt_hash == expected, "후보 없는 주문의 해시는 종전 그대로 — 이미 산 시험 클립이 다시 쓰인다"


def _gen_clip(ms=6000):
    def gen(item, out, ref):
        rehearsal.make_fake_clip(out, ms)
        return item.est_usd
    return gen


@needs_ffmpeg
def test_buy_records_the_measured_length_not_the_requested_one(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    it = dpaid.clip_item(2, "mechanism", "m", "s", "x" * 64, clip_sec=8)
    rpc = FakeRpc()
    b = dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path), ref_path="s.png", generate=_gen_clip(6000))
    reg = next(p for fn, p in rpc.calls if fn == "drinks_register_generated")
    assert 5950 <= reg["asset"]["duration_ms"] <= 6050, "8초를 주문해도 6초가 왔으면 6초로 적는다"
    assert reg["asset"]["width"] == 720 and reg["asset"]["height"] == 1280
    assert reg["asset"]["provenance"]["requested_ms"] == 8000 and reg["asset"]["provenance"]["measured_frames"] > 100
    assert b.duration_ms == reg["asset"]["duration_ms"] and b.frames > 100


def test_buy_unreadable_clip_keeps_the_money_record_and_registers_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    monkeypatch.setattr(dx, "probe_clip", lambda p: {"ok": False, "has_video": False, "still": False, "duration_ms": 0, "error": "깨짐"})
    it = dpaid.clip_item(2, "mechanism", "m", "s", "x" * 64, clip_sec=8)
    rpc = FakeRpc()

    def gen(item, out, ref):
        Path(out).write_bytes(b"garbage")
        return item.est_usd
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path), ref_path="s.png", generate=gen)
    assert e.value.code == "clip_corrupt"
    assert "drinks_settle_spend" in rpc.names() and "drinks_register_generated" not in rpc.names(), "돈은 기록되고 깨진 파일은 재사용 목록에 안 들어간다"


@needs_ffmpeg
def test_candidate_fill_never_looks_at_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    it = dpaid.clip_item(2, "mechanism", "m", "s", "x" * 64, clip_sec=4, candidate_id="P:A1#c2")
    rpc = FakeRpc()
    dpaid.buy(it, rpc=rpc, storage=FakeStorage(), approval_id="ap", out_dir=str(tmp_path), ref_path="s.png", generate=_gen_clip(4000))
    assert "drinks_find_generated" not in rpc.names()
    assert next(p for fn, p in rpc.calls if fn == "drinks_hold_spend")["item_key"] == "P:A1#c2"
    assert next(p for fn, p in rpc.calls if fn == "drinks_register_generated")["asset"]["provenance"]["candidate_id"] == "P:A1#c2"


def test_reuse_is_only_the_selected_asset(tmp_path):
    payload = b"selected clip bytes"
    st = FakeStorage({"drinks/generated/x.mp4": payload})
    sha = hashlib.sha256(payload).hexdigest()
    rpc = FakeRpc({"storage_key": "local:drinks/generated/x.mp4", "sha256": sha, "asset_id": "a9", "width": 720, "height": 1280, "duration_ms": 8000})
    b = dpaid.fetch_selected("P:A1", rpc=rpc, storage=st, out_dir=str(tmp_path))
    assert b.reused and b.cost_usd == 0 and b.asset_id == "a9" and b.duration_ms == 8000
    assert rpc.names() == ["drinks_explainer_selected_asset"], "사는 함수를 부르지 않는다"
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.fetch_selected("P:A2", rpc=FakeRpc(), storage=st, out_dir=str(tmp_path))
    assert e.value.code == "no_selected_asset"
    bad = FakeRpc({"storage_key": "local:drinks/generated/x.mp4", "sha256": "0" * 64})
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.fetch_selected("P:A1", rpc=bad, storage=st, out_dir=str(tmp_path))
    assert e.value.code == "cache_corrupt"


# ── 공급자 어댑터(호출 없음) ─────────────────────────────────────

CLIP = pv.ExplainerClipInput(start_image_b64="QUJD", motion_prompt="the glass slowly turns", clip_sec=8, resolution="720p", candidate_k=2)


def test_omni_request_shape():
    r = pv.build_omni_request(CLIP)
    assert r.method == "POST" and r.url == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert set(r.body) == {"model", "input", "response_format"}, "문서에 있는 최상위 칸만"
    assert r.body["model"] == "gemini-omni-1.1-flash" and r.auth == "gemini_api_key" and r.billing_unit == "tokens"
    assert r.body["input"][0] == {"type": "image", "mime_type": "image/png", "data": "QUJD"}
    assert r.body["input"][-1]["type"] == "text" and "the glass slowly turns" in r.body["input"][-1]["text"]
    assert r.body["response_format"]["aspect_ratio"] == "9:16"
    assert "시작 그림 첫 프레임 고정" in r.unverified, "[미검증]을 단정하지 않는다"
    with_end = pv.build_omni_request(dataclasses.replace(CLIP, end_image_b64="REVG"))
    assert [p["type"] for p in with_end.body["input"]] == ["image", "image", "text"]
    for bad in ({"clip_sec": 2}, {"clip_sec": 11}, {"resolution": "8k"}, {"motion_prompt": " "}, {"start_image_b64": ""}):
        with pytest.raises(pv.ExplainerProviderError):
            pv.build_omni_request(dataclasses.replace(CLIP, **bad))


def test_omni_response_parsing():
    import base64

    raw = b"\x00\x00\x00\x18ftypmp42"
    data = {"id": "int-1", "outputs": [{"type": "text", "text": "ok"}, {"type": "video", "data": base64.b64encode(raw).decode()}], "usage": {"total_output_tokens": 46336}}
    p = pv.parse_omni_response(data)
    assert (p.request_id, p.video_bytes, p.billing_unit, p.billed_units) == ("int-1", raw, "tokens", 46336.0)
    for bad in ({}, {"outputs": []}, {"outputs": [{"type": "text", "text": "거절"}]}, {"outputs": [{"type": "video", "data": "@@not base64@@"}]}):
        with pytest.raises(pv.ExplainerProviderError):
            pv.parse_omni_response(bad)


def test_vertex_request_shape():
    r = pv.build_vertex_veo_request(CLIP, "proj-1")
    assert r.url == ("https://us-central1-aiplatform.googleapis.com/v1/projects/proj-1/locations/us-central1/publishers/google/models/"
                     "veo-3.1-fast-generate-001:predictLongRunning")
    assert r.auth == "gcp_bearer" and r.billing_unit == "seconds_unverified"
    inst, params = r.body["instances"][0], r.body["parameters"]
    assert inst["image"] == {"bytesBase64Encoded": "QUJD", "mimeType": "image/png"} and "lastFrame" not in inst
    assert params["aspectRatio"] == "9:16" and params["durationSeconds"] == 8 and params["resolution"] == "720p" and params["sampleCount"] == 1
    assert "seed" not in params and "storageUri" not in params
    both = pv.build_vertex_veo_request(dataclasses.replace(CLIP, end_image_b64="REVG", seed=7), "proj-1", storage_uri="gs://b/x")
    assert both.body["instances"][0]["lastFrame"]["bytesBase64Encoded"] == "REVG" and both.body["parameters"]["seed"] == 7 and both.body["parameters"]["storageUri"] == "gs://b/x"
    for bad in ({"clip_sec": 5}, {"clip_sec": 10}, {"resolution": "360p"}):
        with pytest.raises(pv.ExplainerProviderError):
            pv.build_vertex_veo_request(dataclasses.replace(CLIP, **bad), "proj-1")
    with pytest.raises(pv.ExplainerProviderError):
        pv.build_vertex_veo_request(CLIP, " ")
    f = pv.build_vertex_fetch_request("projects/p/operations/o1", "proj-1")
    assert f.url.endswith(":fetchPredictOperation") and f.body == {"operationName": "projects/p/operations/o1"} and f.method == "POST"


def test_vertex_operation_parsing():
    pending = pv.parse_vertex_operation({"name": "op/1", "done": False}, 8)
    assert pending.done is False and pending.request_id == "op/1" and not pending.gcs_uri
    done = pv.parse_vertex_operation({"name": "op/1", "done": True, "response": {"videos": [{"gcsUri": "gs://b/a.mp4"}]}}, 8)
    assert done.done and done.gcs_uri == "gs://b/a.mp4" and done.billed_units == 8.0
    inline = pv.parse_vertex_operation({"name": "op/2", "done": True, "response": {"videos": [{"bytesBase64Encoded": "QUJD"}]}}, 6)
    assert inline.video_bytes == b"ABC"
    for bad in ({"name": "x", "done": True, "error": {"code": 3}}, {"name": "x", "done": True, "response": {"videos": []}}):
        with pytest.raises(pv.ExplainerProviderError):
            pv.parse_vertex_operation(bad, 8)


@needs_ffmpeg
def test_common_output_measures_the_received_file(tmp_path):
    src = tmp_path / "s.mp4"
    rehearsal.make_fake_clip(str(src), 4000)
    parsed = pv.ExplainerParsed(provider="omni", request_id="r1", billing_unit="tokens", billed_units=10.0, video_bytes=src.read_bytes())
    out = pv.store_parsed_clip(parsed, str(tmp_path / "o.mp4"))
    assert 3950 <= out.measured_ms <= 4050 and out.request_id == "r1" and out.billing_unit == "tokens" and out.width == 720
    with pytest.raises(pv.ExplainerProviderError):
        pv.store_parsed_clip(dataclasses.replace(parsed, video_bytes=b"garbage" * 50), str(tmp_path / "bad.mp4"))
    with pytest.raises(pv.ExplainerProviderError):
        pv.store_parsed_clip(dataclasses.replace(parsed, video_bytes=b""), str(tmp_path / "none.mp4"))


class NoClient:
    def post(self, *a, **k):
        raise AssertionError("전송되면 안 된다")


def test_real_send_refuses_unless_explicitly_enabled(monkeypatch):
    req = pv.build_omni_request(CLIP)
    assert config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED is False, "기본은 꺼짐"
    with pytest.raises(pv.ExplainerSendRefused):
        pv.send_explainer_request(req, approval_id="ap", client=NoClient())
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", True)
    with pytest.raises(pv.ExplainerSendRefused):
        pv.send_explainer_request(req, approval_id=" ", client=NoClient())
    with pytest.raises(pv.ExplainerSendRefused):
        pv.send_explainer_request(pv.build_vertex_veo_request(CLIP, "p"), approval_id="ap", client=NoClient())


def test_enabled_send_goes_through_only_the_given_client(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", True)
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    seen = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"id": "x"}

    class Client:
        def post(self, url, headers, json):
            seen.update(url=url, json=json)
            return Resp()
    req = pv.build_omni_request(CLIP)
    assert pv.send_explainer_request(req, approval_id="ap", client=Client()) == {"id": "x"}
    assert seen["url"] == req.url and seen["json"] == req.body


def test_nothing_in_the_render_reaches_the_send_path():
    assert "send_explainer_request" not in SRC and "providers" not in _engine_imports()
    for rel in ("engine/drinks_produce.py", "engine/drinks_render.py", "engine/drinks_paid.py", "engine/render.py", "engine/assemble.py"):
        assert "send_explainer_request" not in (ROOT / rel).read_text(encoding="utf-8"), rel
    src = (ROOT / "engine" / "providers" / "video.py").read_text(encoding="utf-8")
    assert "미검증" in src


def test_price_table_is_dated_and_from_the_document():
    p = config.DRINKS_EXPLAINER_PRICES
    assert p["as_of"] == "2026-10-31"
    assert p["omni"]["model"] == config.DRINKS_EXPLAINER_OMNI_MODEL == "gemini-omni-1.1-flash" and p["veo_fast"]["model"] == config.DRINKS_EXPLAINER_VERTEX_MODEL == "veo-3.1-fast-generate-001"
    assert p["omni"]["output_usd_per_mtok"] == 17.5 and p["omni"]["tokens_per_sec"] == {"720p": 5792, "1080p": 8688}
    assert p["veo_fast"]["video_only_usd_per_sec"] == {"720p": 0.08, "1080p": 0.10}
    assert p["image"]["mechanism"]["usd"] == 0.134 and p["image"]["reality"]["usd"] == 0.039


# ── 리허설 자리 표시가 사실을 말하지 않는다 ─────────────────────

def test_rehearsal_text_is_obviously_placeholder():
    for b in rehearsal.plan_beats():
        assert "리허설" in b.narration and "자리 표시" in b.narration
        assert not re.search(r"위스키|에탄올|미생물|막걸리|맥주|소주|브랜디|증류|도수|유통기한|소비기한|\d+\s*%", b.narration), b.narration
        for text in (b.card_text, b.tail_text):
            assert not text or "리허설" in text
    assert "리허설" in rehearsal.HOOK
    src = (ROOT / "scripts" / "explainer_rehearsal.py").read_text(encoding="utf-8")
    assert '"--tts"' in src and "default=\"\"" in src, "TTS 는 선택 사항이다"


def test_gold_plan_stretched_to_explainer_shape_passes_all_checks():
    """옛 사례를 설명형 길이·시각 주장표로 늘리면 검사를 통과한다 — 새 범위·새 칸이 다른 규칙과 부딪히지 않는지 본다."""
    scenes = [copy.deepcopy(s) for s in GOLD["scenes"] if (s.get("visual_role") or "reality") != "text_card"]
    while len(scenes) < 9:
        extra = copy.deepcopy(next(s for s in GOLD["scenes"] if (s.get("visual_role") or "reality") == "reality"))
        extra.pop("continuity", None)
        extra.update(claim_ids=["c1"], content_kind="fact")
        scenes.append(extra)
    for s in scenes:
        s["timing_sec"] = 6.4
        s.pop("card_page", None)
        s.update(allowed_simplification="없음", forbidden_misreading="실제 제품 촬영으로 오해", depiction_label=config.DRINKS_EXPLAINER_DEPICTION_LABELS[s.get("visual_role") or "reality"])
        s.setdefault("motion_prompt", "the camera slowly pushes in")
        s["visual_claim_ko"] = "화면이 나레이션을 보여 준다" if s.get("claim_ids") else f"{config.DRINKS_EXPLAINER_MOOD_PREFIX}: 도입"
    plan = {"scenes": scenes, "viewer_conclusion": GOLD.get("viewer_conclusion")}
    review = {"claims": GOLD["claims"], "brief": {"audience_question": "질문"}, "sources": [GOLD.get("source")]}
    rep = dd.check_plan(plan, review, {"question": "질문"})
    assert rep.ok, [f.__dict__ for f in rep.blocks]
