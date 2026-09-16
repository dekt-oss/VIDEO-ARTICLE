"""클립 길이 ↔ 나레이션 길이 보정 — 배선 테스트 (수정명세 v1 Part ③).

이 파일은 **Claude Code 소유분**(티어 선택 · ffmpeg 조립 배선 · QA · 로깅)만 검증한다.
`decide_strategy` 자체의 구간·경계값 판정은 `engine/clip_fit.py`(소유: Codex)와 그 단위테스트
(`tests/test_clip_fit.py`)의 몫이라 여기서 중복 검증하지 않는다. 대신 4개 전략(trim/hold/
pingpong/flagged)이 각각 어떤 ffmpeg 를 만드는지, QA 가 무엇을 플래그하는지를 고정한다.
"""

from __future__ import annotations

import pytest

from engine import assemble, config, render, render_qa
from engine.clip_fit_types import Strategy, fallback_decide_strategy
from engine.providers import video as video_provider


def _strategy(kind: str, **kw) -> Strategy:
    base = dict(clip_sec=4.0, narration_sec=6.0, ratio=0.333, target_sec=6.0)
    base.update(kw)
    return Strategy(kind=kind, **base)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────
# §3-2 길이 티어 선택
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("narration,expected", [
    (3.2, 4),   # 최소 티어로 충분
    (4.0, 4),   # 경계: 티어와 정확히 같으면 그 티어
    (4.1, 6),   # 4s 로는 부족 → 다음 티어
    (5.3, 6),   # 명세 예시: 5.3s → 6s(4s + 늘리기보다 우선)
    (6.0, 6),
    (7.8, 8),
    (12.0, 8),  # 최대 티어를 넘으면 최대 티어(남는 갭은 조립 보정이 흡수)
])
def test_pick_clip_tier_smallest_tier_at_or_above_narration(narration, expected):
    assert video_provider.pick_clip_tier(narration, max_sec=8) == expected


def test_pick_clip_tier_respects_cost_cap():
    # 상한이 4면 나레이션이 아무리 길어도 4s 만 요청한다(비용 불변 기본값 — config 근거).
    assert video_provider.pick_clip_tier(11.0, max_sec=4) == 4
    assert video_provider.pick_clip_tier(1.0, max_sec=4) == 4


def test_clip_sec_tiers_exposed_not_hardcoded():
    # 모델 교체 대비: 티어 목록은 제공자 모듈 상수로 노출되고 값은 config 에서 온다.
    assert video_provider.CLIP_SEC_TIERS == config.VEO_CLIP_SEC_TIERS
    assert len(video_provider.CLIP_SEC_TIERS) >= 2


# ─────────────────────────────────────────────────────────────
# §3-3 전략별 ffmpeg 배선 — 4구간을 각각 실제로 태운다
# ─────────────────────────────────────────────────────────────
def test_trim_adds_fade_out_and_no_tpad():
    s = _strategy("trim", clip_sec=8.0, narration_sec=6.0, ratio=-0.333, target_sec=6.0,
                  fade_out_sec=0.2)
    cmd = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.m4a", duration=6.0, out_path="o.mp4", strategy=s)
    vf = cmd[cmd.index("-vf") + 1]
    assert "fade=t=out:st=5.800:d=0.200" in vf   # 끝 0.2s 페이드아웃
    assert "tpad" not in vf                       # 클립이 더 길어 늘릴 필요 없음
    assert cmd[cmd.index("-t") + 1] == "6.000"    # -t 로 뒤를 잘라낸다


def test_hold_uses_tpad_clone_plus_ken_burns():
    s = _strategy("hold", clip_sec=5.5, narration_sec=6.0, ratio=0.083, target_sec=6.0,
                  hold_sec=0.5, ken_burns=True)
    cmd = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.m4a", duration=6.0, out_path="o.mp4", strategy=s)
    vf = cmd[cmd.index("-vf") + 1]
    assert "tpad=stop_mode=clone" in vf   # 마지막 프레임 복제로 연장
    assert "zoompan" in vf                 # 홀드 구간 켄번스(정지 사진처럼 보이지 않게)
    assert "reverse" not in vf and "setpts" not in vf  # 핑퐁·속도조절 아님


def test_pingpong_uses_filter_complex_reverse_concat():
    s = _strategy("pingpong", clip_sec=4.0, narration_sec=7.0, ratio=0.4286, target_sec=7.0,
                  loops=1)
    cmd = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.m4a", duration=7.0, out_path="o.mp4", strategy=s)
    # split/reverse/concat 은 라벨이 필요해 -vf(단일 입출력)로는 표현 못 한다 → filter_complex.
    assert "-vf" not in cmd
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "reverse" in graph and "concat=n=2:v=1:a=0" in graph
    assert graph.endswith("[v]") and cmd[cmd.index("-map") + 1] == "[v]"
    assert "1:a" in cmd                    # 오디오는 나레이션 입력에서
    assert "setpts" not in graph            # 속도 늘리기 금지


def test_pingpong_multiple_loops_repeats_in_even_multiples():
    s = _strategy("pingpong", clip_sec=4.0, narration_sec=15.0, ratio=0.733, target_sec=15.0,
                  loops=2)
    graph = assemble.pingpong_filter_complex("scale=1080:1920", loops=2, clip_sec=4.0, fps=30)
    # 왕복 1회 = 8s = 240프레임. loop 는 추가 반복 횟수(loops-1)만 준다.
    assert "loop=loop=1:size=240:start=0" in graph
    assert graph.count("reverse") == 1      # 왕복 단위를 반복(매번 뒤집지 않음 — 이음새 유지)
    assert s.loops == 2


def test_flagged_falls_back_to_hold_and_never_pingpongs():
    # ratio > 0.60 → 보정 금지. 그래도 컷 화면 시간은 나레이션 길이라 홀드로 채운다(검은 화면 방지).
    s = _strategy("flagged", clip_sec=4.0, narration_sec=12.0, ratio=0.667, target_sec=12.0,
                  hold_sec=8.0)
    cmd = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.m4a", duration=12.0, out_path="o.mp4", strategy=s)
    vf = cmd[cmd.index("-vf") + 1]
    assert "tpad=stop_mode=clone" in vf
    assert "reverse" not in vf


def test_legacy_call_without_strategy_keeps_previous_behavior():
    # 전략 미지정(레거시 호출)은 기존과 동일 — 짧으면 tpad 홀드, -t 로 트림. 켄번스 없음.
    cmd = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.m4a", duration=5.0, out_path="o.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert "tpad=stop_mode=clone:stop_duration=5.000" in vf and "zoompan" not in vf


# ─────────────────────────────────────────────────────────────
# §3-4 loop_safe 배선 — 미지정 컷은 안전측(핑퐁 금지)
# ─────────────────────────────────────────────────────────────
def test_decide_clip_fit_reads_loop_safe_from_cut(monkeypatch):
    seen: list[tuple[float, float, bool]] = []

    def fake_decide(clip_sec, narration_sec, loop_safe):
        seen.append((clip_sec, narration_sec, loop_safe))
        return fallback_decide_strategy(clip_sec, narration_sec, loop_safe)

    monkeypatch.setattr(assemble, "probe_duration", lambda p: 4.0)
    monkeypatch.setattr(render.clip_fit_types, "decide", fake_decide)

    render._decide_clip_fit("c.mp4", {"cut_no": 1, "loop_safe": True}, 6.0)
    render._decide_clip_fit("c.mp4", {"cut_no": 2}, 6.0)  # 미지정 → 기본값

    assert seen[0] == (4.0, 6.0, True)
    assert seen[1] == (4.0, 6.0, config.CLIP_FIT_LOOP_SAFE_DEFAULT)
    assert config.CLIP_FIT_LOOP_SAFE_DEFAULT is False  # 안전측 기본(핑퐁 금지 → 홀드)


def test_loop_safe_normalized_into_directive_cuts():
    from engine.directive import normalize_directive

    out = normalize_directive({"cuts": [
        {"cut_no": 1, "loop_safe": True, "estimated_sec": 5, "narration_ko": "가"},
        {"cut_no": 2, "estimated_sec": 5, "narration_ko": "나"},
        {"cut_no": 3, "loop_safe": "yes", "estimated_sec": 5, "narration_ko": "다"},
    ]}, "comic")
    flags = [c["loop_safe"] for c in out["cuts"]]
    assert flags[0] is True
    assert flags[1] is False          # 미지정 → 안전측
    assert isinstance(flags[2], bool)  # 문자열도 bool 로 정규화(스키마 보장)


# ─────────────────────────────────────────────────────────────
# §3-6 로깅 · QA
# ─────────────────────────────────────────────────────────────
def _rec(cut_no, strategy, clip=4.0, narration=6.0, ratio=0.333, loop_safe=False):
    return {"cut_no": cut_no, "clip_sec": clip, "narration_sec": narration,
            "ratio": ratio, "loop_safe": loop_safe, "strategy": strategy}


def test_evaluate_clip_fit_red_flags_oversized_gap():
    fit = render_qa.evaluate_clip_fit([
        _rec(1, "hold"),
        _rec(2, "flagged", clip=4.0, narration=12.0, ratio=0.667),
    ])
    assert fit["strategy_counts"] == {"hold": 1, "flagged": 1}
    assert len(fit["flags"]) == 1
    assert "컷2" in fit["flags"][0] and "컷 분할" in fit["flags"][0]


def test_evaluate_clip_fit_warns_on_pingpong_majority():
    fit = render_qa.evaluate_clip_fit([_rec(1, "pingpong"), _rec(2, "pingpong"), _rec(3, "hold")])
    assert fit["flags"] == []
    assert any("핑퐁 루프 컷 비중 2/3" in w for w in fit["warnings"])


def test_evaluate_clip_fit_quiet_when_healthy():
    fit = render_qa.evaluate_clip_fit([_rec(1, "hold"), _rec(2, "trim"), _rec(3, "pingpong")])
    assert fit["flags"] == [] and fit["warnings"] == []


def test_evaluate_clip_fit_records_every_cut_for_audit():
    # §3-6 DoD: 컷별 (clip_sec, narration_sec, ratio, strategy) 가 전부 남아야 사후 검증이 된다.
    records = [_rec(1, "hold"), _rec(2, "trim")]
    fit = render_qa.evaluate_clip_fit(records)
    assert len(fit["cuts"]) == 2
    for row in fit["cuts"]:
        assert {"cut_no", "clip_sec", "narration_sec", "ratio", "strategy"} <= set(row)


def test_merge_clip_fit_qa_warns_without_blocking_render():
    qa = {"passed": True, "hard_fail": [], "warnings": [], "signals": {}}
    fit = render_qa.merge_clip_fit_qa(qa, [_rec(1, "flagged", narration=12.0, ratio=0.667)])
    assert qa["hard_fail"] == [] and qa["passed"] is True  # 렌더 차단 아님(§3-6)
    assert len(qa["warnings"]) == 1                         # 승인 UI 경고로만
    assert fit["strategy_counts"] == {"flagged": 1}


def test_strategy_log_row_shape():
    row = _strategy("hold", hold_sec=2.0).as_log_row()
    assert set(row) == {"clip_sec", "narration_sec", "ratio", "strategy", "note"}
    assert row["strategy"] == "hold"


# ─────────────────────────────────────────────────────────────
# 예산 가드 — 티어 상한을 올리면 preflight 캡도 같은 초수로 조여야 한다
# ─────────────────────────────────────────────────────────────
def test_preflight_budget_prices_selected_tier_not_fixed_clip_sec(monkeypatch):
    from engine.directive import preflight_video_budget

    # 상한을 8s 로 올리면 estimated_sec=7 컷은 8s 티어를 요청하게 된다 → 초수 캡(기본 8s)에
    # 1개만 들어간다. 고정 VEO_CLIP_SEC(4s)로 계산하면 2개가 통과해 실제 과금을 놓친다.
    monkeypatch.setattr(config, "VEO_CLIP_MAX_TIER_SEC", 8)
    cuts = [{"cut_no": i + 1, "motion_source": "video", "estimated_sec": 7} for i in range(2)]
    preflight_video_budget(cuts, "image_preferred")
    kept = [c for c in cuts if c["motion_source"] == "video"]
    assert config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC == 8   # 이 테스트의 전제(기본 캡)
    assert len(kept) == 1 and kept[0]["cut_no"] == 1        # 8s 티어 1개로 캡이 찬다


def test_equal_length_clip_gets_no_fade():
    """clip_sec == narration_sec(Manim 클립의 일반 케이스)에는 페이드를 넣지 않는다.

    회귀 방어: 넣으면 모든 애니메이션 컷의 끝 0.2s 가 검게 죽어 컷 경계마다 번쩍인다.
    판정(fallback/clip_fit)과 조립(clip_fit_video_filter) 양쪽에서 막는다.
    """
    s = fallback_decide_strategy(6.0, 6.0, False)
    assert s.kind == "trim" and s.fade_out_sec == 0.0   # 판정에서 0

    # 판정이 잘못 페이드를 줘도 조립이 막는다(이중 방어).
    bad = _strategy("trim", clip_sec=6.0, narration_sec=6.0, ratio=0.0, target_sec=6.0,
                    fade_out_sec=0.2)
    vf = assemble.clip_fit_video_filter(bad, 6.0)
    assert "fade" not in vf

    # 진짜로 자르는 경우(8s → 6s)에는 페이드가 있어야 한다.
    real = _strategy("trim", clip_sec=8.0, narration_sec=6.0, ratio=-0.333, target_sec=6.0,
                     fade_out_sec=0.2)
    assert "fade=t=out" in assemble.clip_fit_video_filter(real, 6.0)
