"""첫 실사형 렌더(2026-09-03, $5.39)가 드러낸 결함 셋에 대한 회귀 잠금.

운영자 지적 세 가지 → 원인 → 고침:
  ① "3D 도해도 원리 설명도 아닌 의미 없는 화면"
     → 라우터의 시퀀스 소속(`in_visual_sequence`)이 그대로 화풍 판정이 되어 REALITY 컷 5개가
       isometric 3D + "no people in focus" 를 받았다(마네킹·홀로그램의 직접 원인).
     → 도해 화풍은 **자를 구조가 선언된 컷**(mechanism_spec_complete)만 받는다.
  ② "나레이션이 끝나기도 전에 화면이 넘어가 뚝뚝 끊긴다"
     → 컷 화면 길이 == 나레이션 실측(13컷 전부 trim, 4.368s→4.4s). 숨 쉴 틈 0초.
     → CLIP_FIT_TAIL_PAD_SEC 를 나레이션 뒤에 붙이고, 오디오도 apad 로 같이 늘린다
       (-shortest 가 짧은 쪽에서 멈추므로 영상만 늘리면 잘려 나간다).
  ③ "TTS 가 식상하고 급하다"
     → EDGE_TTS_RATE +20%. 기본값을 +5% 로 내렸다(음성 선택은 운영자 취향).

★ 여기서 박는 것은 **실제 지시서 모양**이다. 픽스처를 손으로 지어내면 내 오해를 복사한다 —
  이 저장소가 이미 겪은 실패(reasoning_units vs units). v6 지시서 JSON 을 그대로 읽는다.
"""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from engine import assemble, config, generation_spec, render

V6 = pathlib.Path("docs/review-2026-08-31/personality_pairing_photo_v6.json")


# ── ① 화풍은 선언된 구조를 따른다 ────────────────────────────
@pytest.mark.skipif(not V6.exists(), reason="실측 지시서 없음")
def test_real_directive_role_split_matches_declared_structure():
    """실측 지시서: 구조가 완비된 컷은 정확히 5·8·11 이고, 뒤집혔던 1·4·6·7·10 은 전부 미완비였다."""
    d = json.loads(V6.read_text(encoding="utf-8"))
    roles = {c["cut_no"]: generation_spec.effective_visual_role(c) for c in d["cuts"]}
    assert {n for n, r in roles.items() if r == "MECHANISM"} == {5, 8, 11}, roles
    for n in (1, 4, 6, 7, 10):
        assert roles[n] == "REALITY", (n, roles[n])


def test_a_mechanism_label_still_wins_without_a_spec():
    """모델이 스스로 MECHANISM 이라 라벨했으면 구조가 얇아도 존중한다 — 게이트(photo_contract)가
    따로 `photo_mechanism_thin` 으로 잡는다. 여기서 REALITY 로 내리면 두 판정이 싸운다."""
    cut = {"visual_role": "MECHANISM",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True}}
    assert generation_spec.effective_visual_role(cut) == "MECHANISM"


# ── ② 숨 쉴 틈 — 영상과 오디오를 **같이** 늘린다 ─────────────
def test_tail_pad_is_a_positive_config_constant():
    assert config.CLIP_FIT_TAIL_PAD_SEC > 0
    # 자막 tail_hold(0.5s)보다 길면 다음 컷 자막과 겹친다 — 그 안에 있어야 한다.
    assert config.CLIP_FIT_TAIL_PAD_SEC <= config.CAPTION_TAIL_HOLD_MAX_SEC


def test_render_adds_the_pad_to_the_cut_duration():
    """clip_dur 가 나레이션 실측에 패드를 더한다(문자열 존재 아니라 식 자체를 본다)."""
    src = inspect.getsource(render._render_cut_clips)
    assert "clip_dur = float(measured) + float(config.CLIP_FIT_TAIL_PAD_SEC)" in src


def test_still_cut_command_pads_audio_to_the_duration():
    """★ -shortest 는 짧은 쪽에서 멈춘다. 오디오를 안 늘리면 패드가 그대로 잘려 나간다."""
    cmd = assemble.build_cut_command(
        image_path="a.png", audio_path="a.wav", duration=4.75, effects=[], out_path="o.mp4")
    assert "-af" in cmd
    assert cmd[cmd.index("-af") + 1] == "apad=whole_dur=4.750"
    assert "-shortest" in cmd


def test_clip_cut_command_pads_audio_in_both_branches():
    from engine.clip_fit_types import Strategy
    trim = Strategy(kind="trim", clip_sec=8.0, narration_sec=4.75, ratio=-0.68,
                    target_sec=4.75, fade_out_sec=0.2)
    cmd = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.wav", duration=4.75, out_path="o.mp4", strategy=trim)
    assert cmd[cmd.index("-af") + 1] == "apad=whole_dur=4.750"
    ping = Strategy(kind="pingpong", clip_sec=2.0, narration_sec=4.75, ratio=0.58,
                    target_sec=4.75, loops=2)
    cmd2 = assemble.build_clip_cut_command(
        clip_path="c.mp4", audio_path="a.wav", duration=4.75, out_path="o.mp4", strategy=ping)
    assert cmd2[cmd2.index("-af") + 1] == "apad=whole_dur=4.750"


# ── ③ TTS 속도 ────────────────────────────────────────────────
def test_tts_rate_follows_the_operator_not_my_diagnosis():
    """9/3: '뚝뚝 끊김'을 +20% 탓으로 보고 +5% 로 내렸다. 9/5 운영자가 +20% 를 명시했다.
    되짚어 보면 끊김의 원인은 속도가 아니라 **컷 골격이 문장 중간을 자른 것**(cut_skeleton)과
    꼬리 여백 0초였고 둘 다 따로 고쳤다. 속도는 운영자 취향이다 — 내 진단이 아니다.

    ★ 2026-09-12 운영자 지시("나레이션을 좀 자연스럽게")로 **+10%** 로 한 단계 내렸다.
      여전히 내 진단이 아니라 운영자 지시다 — 값이 바뀌면 이 줄도 함께 바뀐다."""
    assert config.EDGE_TTS_RATE == "+10%"
