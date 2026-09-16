"""설명판 렌더 배선 테스트 — 보드가 실제로 렌더 경로를 타는가 (최종명세 v3.3 §21).

ffmpeg 없이 돈다(argv 만 검사). 고정하는 계약:
  K2  보드 컷은 유료 생성(Veo·이미지) 경로에 **도달할 수 없다** — 분기 위치로 구조 강제.
  K3  보드 클립 명령에 scale/crop/pad 가 없다 — 밴드 좌표가 픽셀 단위로 보존돼야 한다.
  격리 논문 라인은 이 경로에 진입하지 않는다.
"""

from __future__ import annotations

import os

import pytest

from engine import assemble, board_render, config
from engine import report_render as rr

EXPLAINER_HEADER = {"version_type": "explainer"}


# ── K2: 어떤 컷이 보드로 가는가 ──
def test_only_explainer_boards_are_code_rendered():
    assert board_render.code_render_board({"board": "NUMBER_BOARD"}, EXPLAINER_HEADER) == "NUMBER_BOARD"
    # 논문·만화식은 version_type 에서 즉시 걸러진다 — 도달 불가.
    assert board_render.code_render_board({"board": "NUMBER_BOARD"}, {"version_type": "comic"}) is None
    assert board_render.code_render_board({"board": "NUMBER_BOARD"}, {}) is None
    # CONTEXT_BOARD 는 생성 이미지 배경을 허용하는 유일한 보드다(§21 K2).
    assert board_render.code_render_board({"board": "CONTEXT_BOARD"}, EXPLAINER_HEADER) is None
    assert board_render.code_render_board({}, EXPLAINER_HEADER) is None


def test_every_code_render_board_is_a_known_board():
    for b in config.EXPLAINER_CODE_RENDER_BOARDS:
        assert b in config.EXPLAINER_BOARDS, b


# ── K3: 보드 클립 명령이 픽셀을 건드리지 않는가 ──
def test_board_clip_command_does_not_rescale_or_pad(tmp_path):
    """★ scale·crop·pad 가 붙으면 §20-3 밴드 좌표가 어긋난다 — 보드 시스템의 존재 이유가 사라진다."""
    pngs = [str(tmp_path / f"s{i}.png") for i in range(3)]
    for p in pngs:
        open(p, "w").close()
    concat = str(tmp_path / "list.txt")
    argv = assemble.build_board_clip_command(
        frame_paths=pngs, fps=30,
        audio_path=str(tmp_path / "a.m4a"), out_path=str(tmp_path / "o.mp4"),
        concat_file=concat)
    joined = " ".join(argv)
    for banned in ("scale=", "crop=", "pad=", "zoompan"):
        assert banned not in joined, f"{banned} 가 붙으면 밴드 좌표가 깨진다: {joined}"
    assert "-t 0.100" in joined                       # 3프레임 @30fps
    assert argv[:2] == ["ffmpeg", "-y"]


def test_board_clip_concat_repeats_last_frame(tmp_path):
    """concat demuxer 는 마지막 항목의 duration 을 무시한다 — 한 번 더 적지 않으면 끝이 잘린다."""
    pngs = [str(tmp_path / "a.png"), str(tmp_path / "b.png")]
    for p in pngs:
        open(p, "w").close()
    concat = str(tmp_path / "list.txt")
    assemble.build_board_clip_command(
        frame_paths=pngs, fps=30, audio_path="a.m4a",
        out_path="o.mp4", concat_file=concat)
    body = open(concat, encoding="utf-8").read()
    assert body.count(os.path.abspath(pngs[-1])) == 2, body


# ── 렌더 분기: 보드는 clip 으로 나오고 유료 경로를 타지 않는다 ──
def test_board_cut_returns_clip_and_costs_nothing(tmp_path, monkeypatch):
    import engine.render as render

    monkeypatch.setattr(render.tts_provider, "synthesize",
                        lambda cut, path, lang: {"sec": 5.0, "cost": 0.0, "words": []})
    monkeypatch.setattr(render.assemble, "run_ffmpeg", lambda argv: None)

    def _boom(*a, **k):
        raise AssertionError("보드 컷이 유료 생성 경로에 도달했다 — §21 K2 위반")

    monkeypatch.setattr(render, "_gen_still", _boom)
    monkeypatch.setattr(render, "_gen_veo_clip", _boom)

    cut = {"cut_no": 2, "board": "NUMBER_BOARD", "motion_source": "video",
           "number_claim_refs": [1],
           "overlay_plan": [{"type": "source_card", "text": "메리츠증권 리포트"}]}
    header = {"version_type": "explainer", "explainer": {
        "number_claims": [{"claim_no": 1, "value": "43", "unit": "%", "label": "성장률",
                           "comparison_basis": "직전", "comparison_value": "39",
                           "why_significant": "가속"}],
        "report_claim_summary": {"speaker": "메리츠증권"}, "watchpoint": {}}}

    vis, kind, aud, sec, cost, _ = render._gen_cut_assets(
        cut, header, str(tmp_path), idx=0, lang="ko")
    # ★ motion_source=video 인데도 Veo 로 가지 않았다 — 분기 순서가 K2 를 구조로 강제한다.
    assert kind == "clip"
    assert cost == 0.0
    assert vis.endswith(".mp4")


def test_paper_line_never_enters_board_branch(tmp_path, monkeypatch):
    """논문 만화식은 보드 분기를 타지 않고 기존 스틸 경로 그대로."""
    import engine.render as render

    monkeypatch.setattr(render.tts_provider, "synthesize",
                        lambda cut, path, lang: {"sec": 4.0, "cost": 0.0, "words": []})
    called = {"still": 0}

    def _still(cut, header, path, *args, **kw):
        # ★ *args — 호출측이 인자를 늘려도(P3-c 의 render_job_id) 이 스텁이 깨지지 않게.
        #   이 검사의 관심사는 "스틸 경로를 탔는가"이지 인자 수가 아니다.
        called["still"] += 1
        open(path, "w").close()
        return 0.0

    monkeypatch.setattr(render, "_gen_still", _still)
    cut = {"cut_no": 1, "board": "NUMBER_BOARD"}   # board 가 있어도 comic 이면 무시된다
    vis, kind, _, _, _, _ = render._gen_cut_assets(
        cut, {"version_type": "comic"}, str(tmp_path), idx=0, lang="ko")
    assert kind == "image" and called["still"] == 1


# ── K3: 레터박스 해제 ──
def test_letterbox_is_disabled_only_for_explainer():
    prev = config.LAYOUT_MODE
    with rr._explainer_layout("explainer"):
        assert config.LAYOUT_MODE == "full_bleed"
        assert assemble.letterbox_pad_suffix() == ""      # 검은 바가 생기지 않는다
    assert config.LAYOUT_MODE == prev                     # 반드시 복원

    with rr._explainer_layout("comic"):
        assert config.LAYOUT_MODE == prev                 # 만화식은 현행 유지
    assert config.LAYOUT_MODE == prev


def test_layout_is_restored_even_on_failure():
    prev = config.LAYOUT_MODE
    with pytest.raises(RuntimeError):
        with rr._explainer_layout("explainer"):
            raise RuntimeError("렌더 실패")
    assert config.LAYOUT_MODE == prev


# ── 보드 내용이 지시서에서만 온다(환각 방지) ──
def test_board_payload_uses_only_directive_values():
    pay = board_render.board_payload(
        {"board": "NUMBER_BOARD", "number_claim_refs": [1]},
        {"version_type": "explainer", "explainer": {
            "number_claims": [{"claim_no": 1, "value": "1.09", "unit": "조원",
                               "label": "신규 수주", "comparison_basis": "연간 목표",
                               "comparison_value": "4", "why_significant": "4분의 1"}],
            "report_claim_summary": {"speaker": "유안타증권"}, "watchpoint": {}}},
        None)
    assert pay["number"] == "1.09조원"
    assert pay["kicker"] == "유안타증권"
    assert "연간 목표" in pay["comparison"]


def test_board_payload_is_empty_when_directive_has_nothing():
    """근거가 없으면 빈 값이다 — 그럴듯한 기본값을 지어내지 않는다."""
    pay = board_render.board_payload({"board": "NUMBER_BOARD"}, {"version_type": "explainer"}, None)
    assert pay["number"] == "" and pay["comparison"] == ""


# ── K1: 생성 이미지가 차트·대시보드를 그리지 못하게 ──
def test_explainer_image_prompt_forbids_charts():
    """★ 공통 네거티브에는 `no numbers` 만 있어 '차트 모양' 자체는 막지 못했다 — 그래서 가짜
    대시보드가 그려졌다. explainer 에만 차트·UI 금지를 덧붙인다."""
    from engine.providers import image as image_provider

    cut = {"visual_prompt": "data center corridor"}
    p = image_provider._build_image_prompt(cut, {"version_type": "explainer"})
    for banned in ("no charts", "no dashboards", "no graphs", "no UI panels"):
        assert banned in p, p


def test_comic_image_prompt_is_unchanged():
    """만화식 프롬프트는 바이트 단위로 이전과 같아야 한다(A/B 비교 변수 오염 방지 계약)."""
    from engine.providers import image as image_provider

    cut = {"visual_prompt": "a robot"}
    p = image_provider._build_image_prompt(cut, {"version_type": "comic"})
    assert "no charts" not in p
    assert config.EXPLAINER_IMAGE_NEGATIVE_PROMPT not in p
