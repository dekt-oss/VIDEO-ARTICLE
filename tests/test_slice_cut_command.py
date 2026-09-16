"""stage 구간 자르기 인자 계약 (2026-09-08, 첫 실물 렌더에서 잡은 결함).

★ 무엇이 문제였나: `-ss` 가 두 입력 **뒤에** 있었다. 그 자리에서는 입력 탐색이 아니라
  **출력 옵션**이라 완성된 스트림의 앞부분을 버린다. 컷 나레이션은 언제나 0초에서 시작하는
  자기 파일이므로, 그 만큼이 **목소리에서 깎여 나갔다.** 시작 지점이 나레이션 길이를 넘는
  컷(= stage 의 두 번째 컷부터)은 남는 게 없어 261바이트 빈 mp4 가 됐다.
  실측: 7컷 중 4컷이 그렇게 사라졌고, 42초여야 할 영상이 13.5초로 나갔다.

★★ **왜 이 결함이 살아남았나**: 유일한 시퀀스 테스트(`test_stage_render_wiring.py`)가
  `build_slice_cut_command` 를 **통째로 모킹**한다. 그래서 "구간을 요청했는가"는 검사했지만
  **그 요청이 ffmpeg 에게 무슨 뜻인지**는 아무도 검사하지 않았다.
  렌더를 실제로 돌려야만 드러나는 결함이었다(skill: render-required-verification-audit) —
  드러난 뒤에는 정적 검사로 고정해 재발을 막는다.
"""

from __future__ import annotations

from engine import assemble


def _argv(start: float = 9.4, duration: float = 6.0) -> list[str]:
    return assemble.build_slice_cut_command(
        video_path="stage.mp4", audio_path="cut.m4a",
        start_sec=start, duration=duration, out_path="out.mp4")


def test_the_seek_is_an_input_option_on_the_video():
    """★ `-ss` 는 영상 `-i` **앞**에 와야 입력 탐색이 된다. 뒤에 오면 출력에서 잘라낸다."""
    a = _argv()
    ss, vi = a.index("-ss"), a.index("stage.mp4")
    assert ss < vi, f"-ss 가 영상 입력 뒤에 있다: {a}"
    assert a[ss + 1] == "9.400"
    assert a[vi - 1] == "-i", "-ss 와 -i 사이에 다른 것이 끼면 안 된다"


def test_the_narration_input_is_never_seeked():
    """★★ 컷 나레이션은 언제나 0초에서 시작한다 — 여기에 탐색을 걸면 목소리가 깎인다.

    이것이 실측에서 컷 4개를 통째로 날린 그 결함이다.
    """
    a = _argv()
    ai = a.index("cut.m4a")
    assert a[ai - 1] == "-i"
    assert a[ai - 2] != "-ss", f"나레이션에 -ss 가 걸렸다: {a}"
    # 영상 뒤에 오는 -ss 는 하나도 없어야 한다(출력 탐색 금지).
    assert a.index("-ss") < ai, f"두 번째 -ss 가 있다: {a}"
    assert a.count("-ss") == 1


def test_the_duration_limits_the_output_not_the_input_read():
    """`-t` 는 입력 뒤에 와서 출력 길이를 정한다 — 앞에 두면 읽기 자체를 자른다."""
    a = _argv()
    assert a.index("-t") > a.index("cut.m4a")
    assert a[a.index("-t") + 1] == "6.000"


def test_a_zero_start_still_produces_a_valid_command():
    """stage 의 첫 컷은 start=0 이다 — 특수 분기 없이 같은 모양이어야 한다."""
    a = _argv(start=0.0)
    assert a[a.index("-ss") + 1] == "0.000"
    assert a.index("-ss") < a.index("stage.mp4")


def test_both_streams_are_mapped_and_the_audio_is_padded():
    """계약의 나머지 — 회귀로 잃지 않게 함께 못박는다."""
    a = _argv()
    assert "-map" in a and "0:v:0" in a and "1:a:0" in a
    assert any(x.startswith("apad=whole_dur=") for x in a)
    assert a[-1] == "out.mp4" and "-shortest" in a


# ─────────────────────────────────────────────────────────────
# 조립이 빈 컷을 조용히 넘기지 않는다
# ─────────────────────────────────────────────────────────────
def test_assemble_refuses_to_join_empty_cut_files(tmp_path):
    """★★ 실측: 빈 컷 4개를 concat 이 말없이 건너뛰어 42초가 13.5초로 나갔고
    렌더는 **성공으로 끝났다.** 조용히 절반을 버리면 아무도 모른다."""
    import pytest

    good = tmp_path / "cut_0.mp4"
    good.write_bytes(b"x" * 200_000)
    empty = tmp_path / "cut_1.mp4"
    empty.write_bytes(b"x" * 261)          # 실측에서 나온 그 크기
    with pytest.raises(RuntimeError) as e:
        assemble.assemble_full([str(good), str(empty)], str(tmp_path),
                               str(tmp_path / "out.mp4"))
    assert "cut_1.mp4" in str(e.value), str(e.value)


def test_assemble_also_refuses_a_missing_cut_file(tmp_path):
    import pytest

    good = tmp_path / "cut_0.mp4"
    good.write_bytes(b"x" * 200_000)
    with pytest.raises(RuntimeError):
        assemble.assemble_full([str(good), str(tmp_path / "nope.mp4")],
                               str(tmp_path), str(tmp_path / "out.mp4"))


# ─────────────────────────────────────────────────────────────
# 전체 재생속도 (2026-09-09 운영자 지시)
# ─────────────────────────────────────────────────────────────
def test_speed_applies_to_video_and_audio_at_the_same_ratio():
    """★★ 한쪽만 걸면 싱크가 깨진다 — 자막은 이미 구워져 있어 영상을 따라간다."""
    a = assemble.build_speed_command("in.mp4", "out.mp4", 1.1)
    assert "setpts=PTS/1.100" in a and "atempo=1.100" in a


def test_speed_refuses_a_ratio_atempo_cannot_do():
    """★ atempo 는 0.5~2.0 만 받는다. 조용히 이상한 배속을 내보내는 것보다 거절이 낫다."""
    import pytest

    for bad in (0.4, 2.5):
        with pytest.raises(ValueError):
            assemble.build_speed_command("in.mp4", "out.mp4", bad)


def test_speed_one_leaves_the_file_untouched():
    """★ 1.0 이면 조립이 속도 단계를 아예 건너뛴다 — 기존 출력 바이트 불변."""
    src = open(assemble.__file__, encoding="utf-8").read()
    assert "if abs(speed - 1.0) > 0.001:" in src
