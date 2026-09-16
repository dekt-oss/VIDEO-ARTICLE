"""시퀀스 단위 렌더 **배선** 검증 — 계획이 아니라 실행 경로를 본다.

계획 로직은 tests/test_stage_render.py 가 본다. 이 파일은 그 계획이 실제로
`render._render_cut_clips` 안에서 **쓰이는지**를 본다. 이 저장소가 반복해 겪은 실패가
"만들어 놓고 아무도 안 부른다"이기 때문이다.

★ 생성기(Veo·이미지·TTS)는 전부 가짜다 — 네트워크·비용 없음.
  ffmpeg 호출도 가짜다(이 PC 에 ffmpeg 이 없다). 확인하는 것은 **어떤 함수가 몇 번
  불렸는가**이지 화면이 예쁜가가 아니다. 그건 렌더를 돌려야 알고 운영자 승인 사항이다.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from engine import config, render


def _cut(no, stage, sec=5):
    return {"cut_no": no, "estimated_sec": sec,
            "narration_ko": f"{no}번 문장입니다.", "narration_en": f"Sentence {no}.",
            "motion_source": "video", "visual_role": "REALITY",
            "visual_prompt": "a scene", "motion_prompt": "camera moves",
            "resolved_visual_plan": {"stage_ref": stage, "world_ref": "W1"}}


DIRECTIVE = {
    "header": {"version_type": "photo", "hook_ko": "훅",
               "visual_sequences": [{"sequence_id": "SEQ1", "world": {"world_id": "W1"},
                                     "stages": [{"stage_id": "S1"}, {"stage_id": "S2"}]}]},
    "cuts": [_cut(1, "S1"), _cut(2, "S1"), _cut(3, "S2")],
}


class _Recorder:
    """생성 호출을 세는 가짜들."""

    def __init__(self):
        self.clips: list[tuple[int, str | None]] = []   # (초수, 시작그림)
        self.stills = 0
        self.slices: list[tuple[float, float]] = []
        self.concats = 0


@pytest.fixture
def rec(tmp_path):
    r = _Recorder()

    def fake_clip(cut, header, out_path, duration, lang="ko", start_image=None, **kw):
        r.clips.append((int(duration), start_image))
        open(out_path, "wb").write(b"clip")
        return out_path, 0.4

    def fake_still(cut, header, img_path, **kw):
        r.stills += 1
        open(img_path, "wb").write(b"png")
        return 0.039

    def fake_tts(cut, out_path, lang="ko"):
        open(out_path, "wb").write(b"aud")
        return {"path": out_path, "sec": 5.0, "cost": 0.0, "words": []}

    def fake_slice(*, video_path, audio_path, start_sec, duration, out_path):
        r.slices.append((round(start_sec, 2), round(duration, 2)))
        return ["ffmpeg", "-slice", out_path]

    def fake_concat(*, clip_paths, out_path, concat_file):
        r.concats += 1
        return ["ffmpeg", "-concat", out_path]

    def fake_run(argv):
        # 마지막 인자를 출력 파일로 보고 만들어 준다(다음 단계가 존재를 확인한다).
        if argv and argv[-1].endswith((".mp4", ".png")):
            open(argv[-1], "wb").write(b"out")

    with mock.patch.object(render.video_provider, "generate_clip", fake_clip), \
         mock.patch.object(render, "_obtain_still", fake_still), \
         mock.patch.object(render.tts_provider, "synthesize", fake_tts), \
         mock.patch.object(render.assemble, "build_slice_cut_command", fake_slice), \
         mock.patch.object(render.assemble, "build_concat_clips_command", fake_concat), \
         mock.patch.object(render.assemble, "run_ffmpeg", fake_run), \
         mock.patch.object(render.clip_candidates, "last_frame", lambda a, b: False), \
         mock.patch.object(render.clip_candidates, "probe_motion", lambda *a, **k: {}):
        yield r


def _run(tmp_path, directive=None):
    return render._render_cut_clips(directive or DIRECTIVE, str(tmp_path))


# ── 배선이 실제로 켜지는가 ───────────────────────────────────
def test_stage_mode_generates_one_video_per_stage_not_per_cut(rec, tmp_path):
    """★★ 이 검사가 이 작업의 전부다 — 컷 3개인데 stage 2개만 만들어야 한다."""
    _run(tmp_path)
    # S1 은 컷 2개(10초) → 8+4, S2 는 컷 1개(5초) → 6초. 총 클립 3개, stage 2개.
    assert rec.concats == 1, "여러 클립을 이어 붙인 stage 가 없다"
    assert rec.stills == 2, f"stage 당 시작 그림 1장이어야 하는데 {rec.stills}장"


def test_every_cut_takes_a_slice_instead_of_its_own_clip(rec, tmp_path):
    """컷은 자기 영상을 갖지 않고 stage 영상의 구간을 본다."""
    _run(tmp_path)
    assert len(rec.slices) == 3
    # S1 의 두 컷은 이어진 구간(0→5.35), S2 는 다시 0 에서 시작
    starts = [s for s, _ in rec.slices]
    assert starts[0] == 0.0 and starts[1] > 0.0 and starts[2] == 0.0


def test_slices_of_one_stage_are_adjacent_so_nothing_freezes(rec, tmp_path):
    """★ 구간 사이에 틈이 있으면 그 자리가 정지 화면이 된다."""
    _run(tmp_path)
    (s0, d0), (s1, _), _ = rec.slices
    assert abs(s1 - (s0 + d0)) < 0.05


def test_generated_video_covers_the_narration(rec, tmp_path):
    """★★ hold(정지)를 없애는 조건 — 만든 초수가 나레이션보다 짧으면 반드시 언다."""
    _run(tmp_path)
    made = sum(sec for sec, _ in rec.clips)
    narration = 3 * (5.0 + config.CLIP_FIT_TAIL_PAD_SEC)
    assert made >= narration - 0.05, (made, narration)


def test_clips_after_the_first_chain_from_the_previous_frame(rec, tmp_path):
    """연쇄가 안 걸리면 클립마다 새 장면이 되어 지금과 똑같이 끊긴다."""
    with mock.patch.object(render.clip_candidates, "last_frame",
                           side_effect=lambda a, b: (open(b, "wb").write(b"f"), True)[1]):
        _run(tmp_path)
    # S1 의 두 번째 클립은 첫 클립의 마지막 프레임에서 시작한다
    starts = [img for _, img in rec.clips]
    assert any(s and s.endswith("_last.png") for s in starts), starts


# ── 안전장치 ─────────────────────────────────────────────────
def test_a_directive_without_stages_uses_the_old_cut_path(rec, tmp_path):
    """★ 새 경로가 옛 산출물을 조용히 바꾸면 안 된다."""
    d = {"header": {"version_type": "photo"},
         "cuts": [{**_cut(1, "S1"), "resolved_visual_plan": {}}]}
    with mock.patch.object(render, "_gen_cut_assets") as legacy:
        legacy.return_value = (str(tmp_path / "x.png"), "image",
                               str(tmp_path / "a.m4a"), 4.0, 0.0, [])
        open(tmp_path / "x.png", "wb").write(b"p")
        open(tmp_path / "a.m4a", "wb").write(b"a")
        _run(tmp_path, d)
    assert legacy.called
    assert rec.slices == []


def test_the_switch_falls_back_to_the_cut_path(rec, tmp_path):
    with mock.patch.object(config, "STAGE_RENDER_ENABLED", False), \
         mock.patch.object(render, "_gen_cut_assets") as legacy:
        legacy.return_value = (str(tmp_path / "x.png"), "image",
                               str(tmp_path / "a.m4a"), 4.0, 0.0, [])
        open(tmp_path / "x.png", "wb").write(b"p")
        open(tmp_path / "a.m4a", "wb").write(b"a")
        _run(tmp_path)
    assert legacy.called and rec.slices == []


def test_a_failed_stage_video_falls_back_instead_of_killing_the_render(tmp_path):
    """★ stage 하나가 실패해도 렌더 전체가 죽으면 안 된다 — 화면이 비는 게 가장 나쁘다."""
    def boom(*a, **k):
        raise RuntimeError("Veo 죽음")

    with mock.patch.object(render.video_provider, "generate_clip", boom), \
         mock.patch.object(render, "_obtain_still", lambda c, h, p, **k: (
             open(p, "wb").write(b"png"), 0.0)[1]), \
         mock.patch.object(render.tts_provider, "synthesize",
                           lambda c, p, l="ko": (open(p, "wb").write(b"a"),
                                                 {"path": p, "sec": 4.0, "cost": 0.0,
                                                  "words": []})[1]), \
         mock.patch.object(render.assemble, "run_ffmpeg", lambda argv: None), \
         mock.patch.object(render, "_gen_cut_assets") as legacy:
        legacy.return_value = (str(tmp_path / "x.png"), "image",
                               str(tmp_path / "a.m4a"), 4.0, 0.0, [])
        open(tmp_path / "x.png", "wb").write(b"p")
        open(tmp_path / "a.m4a", "wb").write(b"a")
        _run(tmp_path)
    assert legacy.called, "stage 실패 뒤 컷 경로로 안 넘어갔다"


def test_tts_runs_once_per_cut_not_twice(rec, tmp_path):
    """★ 선행 패스로 합성한 오디오를 루프가 다시 써야 한다.
    두 번 합성하면 시간도 두 배고 두 파일 길이가 미세하게 달라 싱크가 어긋난다."""
    calls = []
    with mock.patch.object(render.tts_provider, "synthesize",
                           side_effect=lambda c, p, l="ko": (
                               calls.append(c["cut_no"]), open(p, "wb").write(b"a"),
                               {"path": p, "sec": 5.0, "cost": 0.0, "words": []})[2]):
        _run(tmp_path)
    assert sorted(calls) == [1, 2, 3], calls


def test_stage_clip_metrics_are_recorded_for_qa(tmp_path):
    """움직임 QA 가 stage 클립도 봐야 한다 — 안 그러면 새 경로가 측정 밖으로 샌다."""
    out: list = []
    def fake_clip(cut, header, out_path, duration, lang="ko", start_image=None, **kw):
        open(out_path, "wb").write(b"c")
        return out_path, 0.1
    with mock.patch.object(render.video_provider, "generate_clip", fake_clip), \
         mock.patch.object(render, "_obtain_still", lambda c, h, p, **k: (
             open(p, "wb").write(b"png"), 0.0)[1]), \
         mock.patch.object(render.tts_provider, "synthesize",
                           lambda c, p, l="ko": (open(p, "wb").write(b"a"),
                                                 {"path": p, "sec": 5.0, "cost": 0.0,
                                                  "words": []})[1]), \
         mock.patch.object(render.assemble, "run_ffmpeg", lambda argv: None), \
         mock.patch.object(render.clip_candidates, "last_frame", lambda a, b: False), \
         mock.patch.object(render.clip_candidates, "probe_motion",
                           lambda *a, **k: {"measured": True, "motion_median": 0.01}):
        render._render_cut_clips(DIRECTIVE, str(tmp_path), clip_metrics_out=out)
    # ★ 스키마가 바뀌었다(2026-09-07). 전에는 stage 클립을 tier="stage" 라는 **가짜 티어**로
    #   적었는데, 그러면 "이 클립이 어느 티어로 생성됐나"를 잃는다(움직임 QA 의 min_beats 가
    #   티어별로 다르다). 이제 tier 는 **실제 티어**를 담고 stage 여부는 stage_id 로 남긴다.
    assert out, "clip_metrics 가 비었다 — stage 클립이 움직임 QA 밖으로 샜다"
    assert all(r.get("stage_id") for r in out), out
    assert all(r.get("tier") and r["tier"] != "stage" for r in out), \
        f"tier 에 실제 티어가 아니라 가짜 값이 들어갔다: {out}"
    # stage 안에서 몇 번째 클립인지, 앞 클립을 물려받았는지(연쇄)도 남아야 한다.
    assert all("clip_index" in r and "chained" in r for r in out), out


# ── stage 영상이 계획보다 짧을 때 ────────────────────────────
# ★ 왜 검사하나: 클립 하나가 실패해 stage 영상이 짧아지면, 뒤 컷의 슬라이스가 영상 끝을
#   넘어가 **나레이션이 잘린다.** 그래서 마지막 프레임으로 메운다(정지가 생기지만 말이
#   잘리는 것보다 낫다). 이건 시퀀스 렌더의 목적(정지 제거)에 역행하는 경로라, 조용히
#   일어나면 "정지를 없앴다"고 믿는 채로 정지가 돌아온다 — 반드시 흔적이 남아야 한다.

def test_short_stage_video_is_padded_and_reported(rec, tmp_path):
    """영상이 계획보다 짧으면 메우고 stage_short 를 남긴다."""
    qa: list = []
    # 계획은 S1=12초·S2=6초. 실제로는 1초씩 모자라게 측정된 것처럼 꾸민다.
    with mock.patch.object(render.assemble, "probe_duration", lambda p: 5.0):
        render._render_cut_clips(DIRECTIVE, str(tmp_path), stage_qa_out=qa)

    shorts = [q for q in qa if q.get("code") == "stage_short"]
    assert shorts, f"짧은 stage 를 조용히 넘겼다 — qa 기록이 없다: {qa}"
    for s in shorts:
        assert s["have_sec"] == 5.0
        assert s["short_by_sec"] > 0
        assert s["need_sec"] > s["have_sec"]
        # 몇 개를 만들려다 몇 개가 됐는지가 있어야 원인을 좁힐 수 있다.
        assert "clips_planned" in s and "clips_made" in s


def test_unmeasurable_duration_is_not_treated_as_short(rec, tmp_path):
    """★ 측정 실패(0.0)를 '짧다'로 착각하면 안 된다.

    probe_duration 은 ffprobe 가 없거나 실패하면 0.0 을 돌려준다(assemble.py §probe_duration).
    그걸 '영상이 0초다'로 읽으면 **멀쩡한 stage 를 매번 패딩**해서, 없애려던 정지 화면을
    스스로 만들어 넣는다. 이 PC 에는 ffprobe 가 없어서 실제로 매번 0.0 이 온다.
    """
    qa: list = []
    with mock.patch.object(render.assemble, "probe_duration", lambda p: 0.0):
        render._render_cut_clips(DIRECTIVE, str(tmp_path), stage_qa_out=qa)

    assert not [q for q in qa if q.get("code") == "stage_short"], \
        f"측정 실패를 '짧음'으로 잘못 판정했다: {qa}"


def test_sufficient_stage_video_is_left_alone(rec, tmp_path):
    """넉넉하면 아무것도 하지 않는다(불필요한 재인코딩·정지 방지)."""
    qa: list = []
    with mock.patch.object(render.assemble, "probe_duration", lambda p: 999.0):
        render._render_cut_clips(DIRECTIVE, str(tmp_path), stage_qa_out=qa)

    assert not [q for q in qa if q.get("code") == "stage_short"], qa
