"""화면 정리 — 벤치마크 3번 (2026-09-28, 운영자 승인).

벤치마크(시화호·고기 핏물)는 그림이 화면을 꽉 채우고 큰 자막 1~2어절이 그림 위에 얹힌다.
우리는 가운데 띠 + 위(시리즈 제목·훅)·아래(자막·면책) 검정 바에 글줄 세 개가 늘 떠 있었다.
"""

from __future__ import annotations

from engine import config, report_render, subtitles


def test_the_picture_fills_the_frame_by_default():
    assert config.LAYOUT_MODE == "full_bleed"


def test_no_fixed_header_line_by_default():
    ass = subtitles.build_ass([(0.0, 2.0, "피일까요?")], header_title="오늘의 리포트",
                              header_hook="훅", total_sec=5.0)
    assert "오늘의 리포트" not in ass and ",Header,," not in ass


def test_captions_are_big_and_short():
    assert config.SUBTITLE_FONT_SIZE >= 80
    assert config.CAPTION_CHUNK_MAX["ko"] <= 3 and config.CAPTION_CHUNK_FAST["ko"] <= 2


def test_the_disclaimer_shows_only_on_the_last_cut():
    cut_map = [{"start_sec": 0.0}, {"start_sec": 8.0}, {"start_sec": 55.0}]
    assert report_render._footer_start(cut_map, 62.0) == 55.0
    ass = subtitles.build_ass([(0.0, 2.0, "본문")], total_sec=62.0, footer_text="출처 A · 면책",
                              footer_from=55.0)
    line = next(l for l in ass.splitlines() if ",Footer,," in l)
    assert line.startswith("Dialogue: 0,0:00:55.00,0:01:02.00,Footer")


def test_a_short_last_cut_still_shows_the_disclaimer_long_enough():
    cut_map = [{"start_sec": 0.0}, {"start_sec": 61.5}]
    assert report_render._footer_start(cut_map, 62.0) == 62.0 - config.FIN_DISCLAIMER_MIN_SEC


def test_switching_it_off_restores_the_full_length_footer(monkeypatch):
    monkeypatch.setattr(config, "REPORT_FOOTER_LAST_CUT_ONLY", False)
    assert report_render._footer_start([{"start_sec": 55.0}], 62.0) == 0.0


def test_the_report_render_passes_the_footer_start():
    import inspect
    assert "footer_from=_footer_start(cut_map, total)" in inspect.getsource(report_render)
