"""Q1 정지 화면 · Q4 출처 가시성 (지시서 v3 §9 · §14-1).

두 검사 다 **선언은 있는데 검사가 없던** 자리다 — 이 저장소가 반복해 겪은
"만들어 놓고 한쪽만 연결"의 같은 계열이다.

Q1 (§9 "3초 동일 프레임" · §14-1 "3초 연속 빈 콘텐츠 0")
    컷 후보에는 freezedetect 가 있는데(clip_candidates) **조립된 최종 mp4 에는 없었다.**
    오디오가 있고 길이만 맞으면 멈춘 화면도 통과였다 — 코스피 빈 화면과 같은 계열.

Q4 (§9 "출처 footer 최소 표시 시간")
    OVERLAY_MIN_SEC(2.0초)를 normalize_overlay_plan 이 **선언 단계에서** 강제하는데,
    build_overlay_cues 가 컷 경계에서 큐를 **잘라낸다**. 계약을 정한 곳과 어기는 곳이
    달라서 0.1초짜리 출처 카드가 나가도 아무도 몰랐다.
"""

from __future__ import annotations

import shutil

import pytest

from engine import config
from engine import clip_candidates as cc
from engine import evidence_overlay as eo
from engine import render_qa

_BASE = {"duration_sec": 45, "has_audio": True, "frame_decodable": True,
         "max_silence_ms": 0, "end_black_sec": 0.0, "audio_peak_db": -3.0}


# ── Q1 정지 화면 ──────────────────────────────────────────────
def test_a_frozen_render_is_reported():
    r = render_qa.evaluate_qa(dict(_BASE, max_freeze_sec=8.2))
    assert any("정지 화면" in w for w in r["warnings"]), r


def test_a_short_freeze_is_not_reported():
    """짧은 정지는 정상이다 — 보드가 한 상태를 잠깐 유지하는 것도 연출이다."""
    r = render_qa.evaluate_qa(dict(_BASE, max_freeze_sec=1.5))
    assert not any("정지 화면" in w for w in r["warnings"]), r


def test_missing_freeze_signal_does_not_crash():
    """옛 신호 dict(키 없음)로도 돌아야 한다 — evaluate_qa 는 순수 계약이다."""
    assert render_qa.evaluate_qa(dict(_BASE))["passed"] is True


def test_freeze_is_a_warning_not_a_block_until_calibrated():
    """★ 문턱을 실제 렌더 분포에 대고 잰 적이 없다(렌더 0회).

    근거 없는 문턱을 차단으로 걸면 core_underfilled 가 8건 중 5건을 죽인 일이 반복된다.
    Phase 4 가 분포를 주면 RENDER_QA_FREEZE_BLOCKS 로 올린다.
    """
    assert config.RENDER_QA_FREEZE_BLOCKS is False
    r = render_qa.evaluate_qa(dict(_BASE, max_freeze_sec=99.0))
    assert r["passed"] is True and r["hard_fail"] == []


# ── Q1 실측: 끝까지 얼어 있는 영상 (가장 나쁜 경우) ────────────
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_a_video_frozen_to_the_end_is_measured(tmp_path, monkeypatch):
    """★★ 회귀(2026-09-03 실측). freezedetect 는 정지가 **끝날 때** duration 을 찍는다.

    영상 끝까지 멈춰 있으면 freeze_start 하나만 나오고 duration 은 영영 안 나온다 —
    `freeze_duration` 만 파싱하던 종전 코드는 **8초짜리 완전 정지 영상을 0.00s** 로 봤다.
    가장 나쁜 경우가 조용히 만점을 받던 셈이다.
    """
    import subprocess
    mp4 = tmp_path / "frozen.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=navy:s=180x320:d=6:r=25",
         "-f", "lavfi", "-i", "sine=f=440:d=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mp4)],
        check=True, timeout=120)
    # ffprobe 는 이 검사와 무관하고 이 환경에 없다. monkeypatch 로 **되돌려지게** 둔다 —
    # 모듈 속성을 그냥 덮으면 같은 세션의 뒤 테스트로 새어 나간다.
    monkeypatch.setattr(render_qa, "_ffprobe_json", lambda p: {
        "format": {"duration": "6.0"},
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]})
    sig = render_qa.probe_signals(str(mp4))
    assert sig["max_freeze_sec"] >= 5.0, sig       # 0.00 이면 옛 버그가 살아난 것


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_the_same_bug_is_fixed_in_clip_candidates(tmp_path):
    """★ 같은 파싱 결함이 후보 채점에도 있었다 — 끝까지 얼어붙은 후보가 만점을 받았다."""
    import subprocess
    mp4 = tmp_path / "frozen.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=navy:s=180x320:d=6:r=25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)],
        check=True, timeout=120)
    sig = cc.probe_motion(str(mp4), 6.0)
    assert sig["freeze_sec"] >= 5.0, sig
    assert cc.score(sig)["freeze_ratio"] > 0.8, cc.score(sig)


# ── Q4 출처 가시성 ────────────────────────────────────────────
def test_a_clipped_source_card_is_reported():
    """컷 경계에서 잘려 0.4초만 뜬 출처 카드 — 읽을 수 없다."""
    cues = [(3.0, 3.4, "출처: Nature 2026", "Evidence")]
    w = eo.cue_visibility_warnings(cues)
    assert w and w[0].startswith("overlay_too_brief:Evidence:")


def test_a_normal_cue_is_not_reported():
    assert eo.cue_visibility_warnings([(0.0, 3.0, "출처: PNAS", "Evidence")]) == []


def test_source_cards_are_listed_first():
    """사유가 많아 잘려도 **귀속**이 남아야 한다 — 근거 없는 화면이 되면 안 된다."""
    cues = [(0.0, 0.5, "수치", "Number"), (1.0, 1.4, "출처: PNAS", "Evidence")]
    w = eo.cue_visibility_warnings(cues)
    assert ":Evidence:" in w[0], w


def test_the_floor_is_the_declared_contract_not_a_new_number():
    """★ 새 숫자를 만들지 않는다 — 선언 단계가 쓰는 값과 **같은 상수**를 본다.

    둘이 갈라지면 "선언은 2초, 검사는 1초" 같은 조용한 어긋남이 생긴다.
    """
    just_under = [(0.0, config.OVERLAY_MIN_SEC - 0.05, "x", "Evidence")]
    just_over = [(0.0, config.OVERLAY_MIN_SEC + 0.05, "x", "Evidence")]
    assert eo.cue_visibility_warnings(just_under)
    assert eo.cue_visibility_warnings(just_over) == []


def test_build_overlay_cues_can_actually_produce_a_too_brief_cue():
    """★ 이 검사가 가상의 문제를 막는 게 아니라는 증명.

    컷이 짧으면 build_overlay_cues 가 실제로 2초 미만 큐를 만든다(end 를 컷 경계로 자름).
    """
    cuts = [{"cut_no": 1, "overlay_plan": [
        {"type": "source_card", "text": "출처: PNAS", "start_sec": 2.0, "duration_sec": 3.0}]}]
    cues = eo.build_overlay_cues(cuts, starts=[0.0], durations=[2.3])
    assert cues, "큐가 아예 안 만들어졌다면 이 테스트의 전제가 틀렸다"
    shown = cues[0][1] - cues[0][0]
    assert shown < config.OVERLAY_MIN_SEC, shown
    assert eo.cue_visibility_warnings(cues), "실제로 만들어지는 위반을 검사가 못 잡는다"


def test_the_check_is_wired_into_the_render_job():
    """순수 함수만 있고 부르는 곳이 없으면 검사는 없는 것이다."""
    import inspect
    from engine import render
    src = inspect.getsource(render.process_job)
    assert "cue_visibility_warnings" in src
    assert "overlay_visibility" in src
