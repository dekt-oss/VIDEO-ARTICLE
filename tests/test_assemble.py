"""engine.assemble 순수 커맨드 빌더 테스트 (ffmpeg 실행 없음).

ffmpeg argv·필터 문자열이 규격대로 조립되는지만 검증한다(실제 렌더는 CI/로컬).
"""

from engine import config
from engine.assemble import (
    build_bgm_duck_command,
    build_bgm_envelope_duck_command,
    build_bgm_tone_command,
    build_clip_cut_command,
    build_concat_command,
    build_concat_file,
    build_cut_command,
    build_loudnorm_command,
    build_subtitles_command,
    build_volume_envelope_expr,
    duck_spans_from_words,
    effect_filter,
)


def test_effect_filter_ken_burns_and_frames():
    f = effect_filter(["ken_burns_zoom_in"], duration=4, fps=30)
    assert "zoompan" in f
    assert "d=120" in f  # 4초 * 30fps
    # 콘텐츠 밴드 크기로 렌더(레이아웃에 따라 전체 or 밴드).
    cw, ch = __import__("engine.assemble", fromlist=["layout_content_dims"]).layout_content_dims()
    assert f"{cw}x{ch}" in f


def test_effect_filter_center_band_letterbox():
    # center_band 면 콘텐츠 밴드 크기 렌더 + 상하 바 pad. (기본 레이아웃)
    from engine.assemble import layout_content_dims, letterbox_pad_suffix
    if config.LAYOUT_MODE == "center_band":
        cw, ch = layout_content_dims()
        assert (cw, ch) == (config.RENDER_WIDTH, config.LETTERBOX_CONTENT_HEIGHT)
        f = effect_filter([], duration=3)
        # 콘텐츠는 밴드 높이로 crop 후 전체 프레임으로 pad(상단 오프셋·바 색).
        assert f"crop={cw}:{ch}" in f
        assert f"pad={config.RENDER_WIDTH}:{config.RENDER_HEIGHT}:0:{config.LETTERBOX_TOP_PX}" in f
        assert config.LETTERBOX_BAR_COLOR in f
        assert letterbox_pad_suffix().startswith(",pad=")


def test_effect_filter_pan_and_none():
    assert "x='" in effect_filter(["pan_left"], 5)
    none = effect_filter([], 5)
    assert "scale=" in none and "crop=" in none  # 효과 없으면 캔버스 맞춤


def test_effect_filter_ignores_unknown_tokens():
    # 미지원 토큰만 있으면 정지(scale/crop) — enum 밖은 무시.
    assert "scale=" in effect_filter(["explode"], 5)


def test_build_cut_command_structure():
    cmd = build_cut_command(
        image_path="a.png", audio_path="a.m4a", duration=5,
        effects=["ken_burns_zoom_in"], out_path="o.mp4",
    )
    assert cmd[0] == "ffmpeg"
    assert "-loop" in cmd and "a.png" in cmd and "a.m4a" in cmd and cmd[-1] == "o.mp4"
    assert cmd[cmd.index("-t") + 1] == "5.000"  # -t duration(float, 소수 3자리)
    assert "-shortest" in cmd  # -loop+zoompan 은 스스로 안 끝나므로 오디오 길이에서 멈춤(필수)
    vf = cmd[cmd.index("-vf") + 1]
    assert "zoompan" in vf  # 효과 적용(자막은 최종 단계 번인)


def test_build_clip_cut_command_conforms_to_audio():
    cmd = build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.m4a", duration=5, out_path="o.mp4",
    )
    assert "-loop" not in cmd  # 클립은 루프 안 함(스틸과 대비)
    assert "c.mp4" in cmd and "a.m4a" in cmd and cmd[-1] == "o.mp4"
    assert cmd[cmd.index("-t") + 1] == "5.000"  # duration(float)로 캡
    assert "-shortest" in cmd  # 나레이션 길이에서 멈춤
    vf = cmd[cmd.index("-vf") + 1]
    assert "tpad" in vf and "scale=" in vf  # 짧으면 마지막 프레임 유지 + 9:16 맞춤
    assert "zoompan" not in vf  # 클립은 켄번스 미적용


def test_build_concat_file_and_command():
    content = build_concat_file(["x.mp4", "y.mp4"])
    assert "file 'x.mp4'" in content and "file 'y.mp4'" in content
    cmd = build_concat_command("list.txt", "out.mp4")
    assert "concat" in cmd and cmd[-1] == "out.mp4"


def test_build_loudnorm_command_targets_configured_lufs():
    cmd = build_loudnorm_command("in.mp4", "out.mp4")
    af = cmd[cmd.index("-af") + 1]
    assert f"loudnorm=I={config.LOUDNESS_LUFS}" in af


def test_build_subtitles_command_burns_ass():
    cmd = build_subtitles_command("in.mp4", "subs.ass", "out.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "ass=filename='subs.ass'"  # 스타일은 ASS 파일 내부에
    assert cmd[-1] == "out.mp4"


def test_subtitle_path_is_escaped_for_the_filter_graph():
    """★ 2026-08-29 Windows 실측: 절대경로를 그대로 넣으면 드라이브 문자 뒤 콜론이 필터의
    옵션 구분자로 읽혀 렌더가 **조립 단계에서** 죽는다("Unable to parse original_size").
    리눅스 경로는 그대로라 GitHub Actions 동작은 바뀌지 않는다."""
    from engine.assemble import filter_path

    win = filter_path("C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + "subs.ass")
    assert win == "C" + chr(92) + ":/Users/x/subs.ass"
    assert filter_path("/tmp/x/subs.ass") == "/tmp/x/subs.ass"


def test_build_bgm_tone_command():
    cmd = build_bgm_tone_command("bgm.m4a", duration=12)
    i = cmd[cmd.index("-i") + 1]
    assert "sine=frequency=" in i and cmd[-1] == "bgm.m4a"


def test_build_bgm_duck_command_ducks_and_normalizes():
    cmd = build_bgm_duck_command("v.mp4", "bgm.m4a", "out.mp4")
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in fc  # 나레이션으로 BGM 더킹
    assert "amix" in fc                # 믹스
    assert f"loudnorm=I={config.LOUDNESS_LUFS}" in fc
    assert "-map" in cmd and cmd[-1] == "out.mp4"


# ── ④ 엔벨로프 더킹 (DV10) ─────────────────────────────────────
def test_duck_spans_merges_small_gaps():
    # 간극 0.3s(<800ms) 는 병합, 1.5s(>=800ms) 는 분리.
    words = [
        {"start": 0.0, "end": 1.0},
        {"start": 1.3, "end": 2.0},   # 간극 0.3s → 병합
        {"start": 3.5, "end": 4.0},   # 간극 1.5s → 분리
    ]
    spans = duck_spans_from_words(words)
    assert spans == [(0.0, 2.0), (3.5, 4.0)]


def test_duck_spans_gap_threshold_configurable_and_skips_bad():
    words = [{"start": 0.0, "end": 1.0}, {"start": 1.2, "end": 2.0},
             {"start": 5.0, "end": 4.0}]  # end<=start 는 무시
    spans = duck_spans_from_words(words, merge_gap_ms=100)  # 0.2s 간극 >= 0.1s → 분리
    assert spans == [(0.0, 1.0), (1.2, 2.0)]


def test_volume_envelope_expr_has_gain_and_bounds():
    spans = [(1.0, 2.0)]
    expr = build_volume_envelope_expr(spans, duck_db=-20, attack_ms=10, release_ms=100)
    assert "between(t,1.000,2.000)" in expr  # 구간 게이팅
    assert "0.1000" in expr                   # -20dB → 0.1 선형 게인
    # 구간 밖 기본 게인 1(원복).
    assert expr.rstrip(")").endswith("1") or ",1)" in expr


def test_build_bgm_envelope_duck_command_uses_volume_envelope():
    spans = [(0.0, 1.5), (3.0, 5.0)]
    cmd = build_bgm_envelope_duck_command("v.mp4", "bgm.m4a", "out.mp4", spans)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "volume=eval=frame" in fc          # 사전계산 엔벨로프(사이드체인 아님)
    assert "sidechaincompress" not in fc
    assert "amix" in fc and f"loudnorm=I={config.LOUDNESS_LUFS}" in fc
    assert cmd[-1] == "out.mp4"
