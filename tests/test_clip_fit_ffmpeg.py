"""클립 길이 보정 — 실제 ffmpeg 실행 검증 (수정명세 v1 §6 Part③ DoD).

`tests/test_clip_fit_wiring.py` 는 argv 문자열만 본다. 그것으로는 "필터그래프가 ffmpeg 에서
실제로 동작하는지"를 알 수 없다 — 특히 핑퐁은 `split`/`reverse`/`concat` 라벨 그래프라
`-filter_complex` 배선이 틀리면 argv 는 그럴듯한데 실행이 죽는다.

그래서 여기서는 합성 클립·합성 오디오를 만들어 4전략을 전부 태우고, **산출 mp4 의 실측 길이가
나레이션 길이와 같은지**를 확인한다. 이것이 DoD "나레이션이 잘리거나 영상이 먼저 끝나는 컷 = 0"
의 직접 검증이다.

ffmpeg/ffprobe 가 없는 환경(저장소 기본 pytest 는 순수 로직 테스트)에서는 skip 된다.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from engine import assemble
from engine.clip_fit_types import Strategy

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe 없음 — 조립 실행 검증은 렌더 러너/로컬에서만",
)

# 길이 허용 오차(초). 컷 경계는 프레임 단위로 떨어지므로 1~2프레임(30fps ≈ 0.067s)은 정상.
TOLERANCE_SEC = 0.15


def _make_clip(path: str, sec: float) -> None:
    """움직이는 9:16 테스트 클립. testsrc 라 역재생·홀드가 프레임으로 구분된다."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=540x960:rate=30:duration={sec}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True, check=True, timeout=120)


def _make_audio(path: str, sec: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={sec}",
         "-c:a", "aac", path], capture_output=True, check=True, timeout=120)


def _audio_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a:0", "-show_entries",
         "stream=duration", "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, timeout=60)
    return float((out.stdout or "0").strip() or 0)


# (이름, 클립 실측 길이, 나레이션 길이, 전략) — §3-3 표의 4구간을 각각 실제로 태운다.
CASES = [
    ("trim", 8.0, 6.0,
     Strategy(kind="trim", clip_sec=8.0, narration_sec=6.0, ratio=-0.333,
              target_sec=6.0, fade_out_sec=0.2)),
    ("hold", 5.5, 6.0,
     Strategy(kind="hold", clip_sec=5.5, narration_sec=6.0, ratio=0.083,
              target_sec=6.0, hold_sec=0.5, ken_burns=True)),
    ("pingpong", 4.0, 7.0,
     Strategy(kind="pingpong", clip_sec=4.0, narration_sec=7.0, ratio=0.4286,
              target_sec=7.0, loops=1)),
    ("pingpong_multi", 4.0, 15.0,
     Strategy(kind="pingpong", clip_sec=4.0, narration_sec=15.0, ratio=0.733,
              target_sec=15.0, loops=2)),
    ("flagged", 4.0, 12.0,
     Strategy(kind="flagged", clip_sec=4.0, narration_sec=12.0, ratio=0.667,
              target_sec=12.0, hold_sec=8.0)),
    ("legacy_no_strategy", 4.0, 5.0, None),
]


@pytest.mark.parametrize("name,clip_sec,narration_sec,strategy", CASES,
                         ids=[c[0] for c in CASES])
def test_cut_output_matches_narration_length(tmp_path, name, clip_sec, narration_sec, strategy):
    clip = str(tmp_path / f"{name}_in.mp4")
    audio = str(tmp_path / f"{name}.m4a")
    out = str(tmp_path / f"{name}_out.mp4")
    _make_clip(clip, clip_sec)
    _make_audio(audio, narration_sec)

    argv = assemble.build_clip_cut_command(
        clip_path=clip, audio_path=audio, duration=narration_sec, out_path=out,
        strategy=strategy)
    assemble.run_ffmpeg(argv)  # 필터그래프가 실제로 통과해야 한다(여기서 죽으면 실패)

    video_sec = assemble.probe_duration(out)
    assert abs(video_sec - narration_sec) <= TOLERANCE_SEC, (
        f"{name}: 영상 {video_sec:.2f}s ≠ 나레이션 {narration_sec:.2f}s "
        f"(영상이 먼저 끝나거나 남는다)")
    assert abs(_audio_duration(out) - narration_sec) <= TOLERANCE_SEC, (
        f"{name}: 나레이션이 잘렸다")


def test_pingpong_actually_doubles_source_length(tmp_path):
    """핑퐁 검증의 핵심: tpad 없이 4s 클립에서 7s 가 나온다면 reverse+concat 이 동작한 것이다."""
    clip = str(tmp_path / "pp_in.mp4")
    audio = str(tmp_path / "pp.m4a")
    out = str(tmp_path / "pp_out.mp4")
    _make_clip(clip, 4.0)
    _make_audio(audio, 7.0)

    s = Strategy(kind="pingpong", clip_sec=4.0, narration_sec=7.0, ratio=0.4286,
                 target_sec=7.0, loops=1)
    argv = assemble.build_clip_cut_command(
        clip_path=clip, audio_path=audio, duration=7.0, out_path=out, strategy=s)
    assert "tpad" not in " ".join(argv)  # 홀드로 늘린 게 아님을 먼저 확정
    assemble.run_ffmpeg(argv)

    assert assemble.probe_duration(out) >= 7.0 - TOLERANCE_SEC


def test_render_cut_clips_populates_fit_log_and_conforms_each_cut(tmp_path, monkeypatch):
    """관통 검증: _render_cut_clips → _decide_clip_fit → fit_log → QA 를 실제 ffmpeg 로 태운다.

    Manim·Veo 는 이 환경에 없으므로 클립 제공자만 대체해 진짜 4초 mp4 를 내놓게 한다. 그 외
    (길이 실측 · 전략 판정 · 조립 · 로그 수집)는 전부 실제 코드 경로다.
    """
    from engine import config, render, render_qa

    # ★ 실제 video_provider.generate_clip 시그니처를 따라야 한다. fact_sheet 인자가 빠져 있어
    #   TypeError 로 클립 생성이 매번 실패하고 스틸로 폴백했다 — 그래서 fit_log 가 비었다.
    #   ffmpeg 없는 환경에서 이 테스트가 통째로 skip 돼 오랫동안 드러나지 않았다.
    def fake_generate_clip(cut, header, out_path, duration, lang="ko",
                           start_image=None, fact_sheet=None):
        _make_clip(out_path, 4.0)   # 나레이션보다 짧은 클립 → 보정이 반드시 걸린다
        return out_path, 0.0

    def fake_tts(cut, out_path, lang="ko"):
        sec = float(cut["_narration_sec"])
        _make_audio(out_path, sec)
        return {"sec": sec, "cost": 0.0, "words": []}

    monkeypatch.setattr(render.video_provider, "generate_clip", fake_generate_clip)
    monkeypatch.setattr(render.tts_provider, "synthesize", fake_tts)
    monkeypatch.setattr(config, "ANIMATION_ENGINE", "manim")  # clip 경로를 타게

    directive = {
        "version_type": "animation",
        "header": {"version_type": "animation", "global_style": "schematic"},
        "cuts": [
            # 6.0s 나레이션 vs 4s 클립 → 보정 필요. loop_safe 를 양쪽 다 둔다.
            {"cut_no": 1, "scene_kind": "motion_graphic", "visual_prompt": "flow",
             "effects": [], "narration_ko": "가", "loop_safe": True, "_narration_sec": 6.0},
            {"cut_no": 2, "scene_kind": "data_viz", "visual_prompt": "compare",
             "effects": [], "narration_ko": "나", "loop_safe": False, "_narration_sec": 3.0},
        ],
    }

    fit_log: list[dict] = []
    cut_files, cues, total, _ = render._render_cut_clips(
        directive, str(tmp_path), lang="ko", fit_log=fit_log)

    assert len(cut_files) == 2
    # §3-6: 컷마다 (clip_sec, narration_sec, ratio, strategy) 가 남는다.
    assert len(fit_log) == 2
    for row in fit_log:
        assert {"cut_no", "clip_sec", "narration_sec", "ratio", "loop_safe", "strategy"} <= set(row)
        assert row["clip_sec"] == pytest.approx(4.0, abs=TOLERANCE_SEC)  # 실측이 실제로 됐다
    assert fit_log[0]["loop_safe"] is True and fit_log[1]["loop_safe"] is False

    # 각 컷 mp4 가 그 컷 나레이션 길이 **+ 꼬리 패드**와 같다 → "영상이 먼저 끝나는 컷 = 0".
    #
    # ★ 기대값을 고쳤다(2026-09-09). 2026-09-03 에 컷 길이가 `나레이션 + CLIP_FIT_TAIL_PAD_SEC`
    #   (숨 쉴 틈)로 바뀌었는데 이 단언은 나레이션만 기대한 채 남아 있었다.
    #   **드러나지 않은 이유는 이 파일이 ffmpeg 없는 환경에서 통째로 skip 되기 때문이다**
    #   (파일 머리말의 그 경고 그대로). 로컬에 ffmpeg 을 깔자 바로 6.35 vs 6.0 으로 터졌다.
    #   회귀가 아니라 **오래 가려져 있던 낡은 기대값**이다.
    pad = config.CLIP_FIT_TAIL_PAD_SEC
    for path, cut in zip(cut_files, directive["cuts"]):
        assert assemble.probe_duration(path) == pytest.approx(
            cut["_narration_sec"] + pad, abs=TOLERANCE_SEC)
    assert total == pytest.approx(9.0 + 2 * pad, abs=TOLERANCE_SEC)

    # QA 가 이 로그를 해석할 수 있다(렌더 차단 없이).
    qa = {"passed": True, "hard_fail": [], "warnings": [], "signals": {}}
    fit = render_qa.merge_clip_fit_qa(qa, fit_log)
    assert sum(fit["strategy_counts"].values()) == 2
    assert qa["hard_fail"] == []
