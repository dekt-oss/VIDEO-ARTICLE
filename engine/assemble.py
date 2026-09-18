"""렌더 조립 엔진 (P-V1) — 승인된 지시서 → mp4. 결정론적 ffmpeg 파이프라인.

이 모듈은 두 종류의 순수 함수(테스트 대상)와 그것을 실행하는 얇은 subprocess 래퍼로 나뉜다:
- 커맨드 빌더(build_cut_command 등): ffmpeg argv 를 문자열로 조립만 한다(실행 없음 → 단위 테스트 가능).
- content_hash: 컷 내용 해시(멱등 캐시 키).
- run_ffmpeg / assemble: 실제 실행(ffmpeg 필요 — 로컬/GitHub Actions 러너에서만).

설계 메모(영상 전문가 보강):
- 컷별 mp4 를 먼저 만들고 concat demuxer 로 잇는다(단일 거대 필터그래프보다 견고·재시도 쉬움).
- 자막은 9:16 세이프에어리어(하단 SUBTITLE_SAFE_BOTTOM) 위에 얹는다(플랫폼 UI 겹침 회피).
- 최종 오디오는 loudnorm(-14 LUFS)로 정규화(유튜브 기준).
- effects/transition 은 통제 어휘 enum 만 해석하고 미지원 토큰은 무시한다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from typing import Any

from . import config, generation_spec
from .clip_fit_types import Strategy
from .util import log


# ─────────────────────────────────────────────────────────────
# 멱등 캐시 키
# ─────────────────────────────────────────────────────────────
def content_hash(cut: dict[str, Any], header: dict[str, Any],
                 *, reference_key: str = "") -> str:
    """컷 **이미지** 산출의 결정 요인만 해시. 편집 시 변경 컷만 재생성하도록.

    ★ 언어 필드가 없는 것은 의도다 — 이것이 KO 렌더가 만든 에셋을 EN 이 무료로 재사용하는 근거다
      (tests/test_shared_assets.py 가 고정). 여기에 lang 을 넣으면 이미지·Veo 비용이 두 배가 된다.
    ★ `crop`·`tone_grade` 도 없다. 파생 컷은 애초에 생성·캐시 경로에 들어가지 않기 때문이다
      (render._reuse_base_image 가 기준 컷 스틸에서 만들어 낸다). 만약 나중에 파생 컷도
      render_assets 에 캐시하려면 **이 해시에 crop·tone_grade 를 먼저 넣어야 한다** —
      안 그러면 같은 기준에서 배율만 다른 두 파생 컷이 같은 캐시 키로 충돌한다.
    ★ 2026-08-29: **생성 사양(모델·역할·화풍버전·출력설정)을 넣었다.** 넣기 전에는 같은
      프롬프트의 MECHANISM 컷과 REALITY 컷이 같은 키였다 — 그래서 과거 flash 로 만든 그림이
      프리미엄 모델로 올린 도해 컷에 그대로 재사용됐고, 모델 상향이 화면에 도달하지 못했다.
      대가는 **기존 캐시 전량 무효화**다(engine/generation_spec.py 머리말의 캐시 정책 참조).
    """
    payload = {
        "version_type": header.get("version_type", ""),
        "visual_type": cut.get("visual_type", ""),
        "scene_kind": cut.get("scene_kind", ""),
        "visual_prompt": cut.get("visual_prompt", ""),
        "global_style": header.get("global_style", ""),
        "effects": cut.get("effects", []),
        # ★ 실제 생성 사양. 여기가 캐시와 실제 호출을 잇는 유일한 끈이다.
        "generation": generation_spec.image_spec(
            cut, header, reference_key=reference_key).cache_fields(),
    }
    # 모션이 Veo 클립 산출을 바꾸므로 값이 있을 때만 캐시 키에 포함(명세 §3-2).
    # 조건부라서 still/image 컷(motion_prompt 빈값)의 기존 해시는 그대로 — 캐시 무효화 없음.
    mp = str(cut.get("motion_prompt") or "").strip()
    if mp:
        payload["motion_prompt"] = mp
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clip_content_hash(cut: dict[str, Any], header: dict[str, Any], *,
                      clip_sec: int, start_asset_hash: str = "") -> str:
    """컷 **클립(I2V)** 산출의 결정 요인 해시. 이미지 해시와 분리한다.

    ★ 왜 분리했나: 예전에는 클립도 `content_hash` 를 썼다. 그 키에는 Veo 모델도, 요청 티어도,
      **시작 이미지**도 없다. 그래서 두 가지가 조용히 깨졌다 —
        ① Veo 모델·티어를 바꿔도 옛 클립이 재사용된다.
        ② I2V 연쇄에서 **앞 컷이 바뀌어도 뒤 컷은 옛 클립을 쓴다.** 앞 컷의 마지막 프레임이
           이 컷의 시작 화면인데 키에 없었으니, 이어지는 그림이 어긋난 채로 굳는다.
    ★ 언어는 여전히 없다 — KO/EN 클립 공유는 그대로다.
    """
    payload = {
        "visual_prompt": cut.get("visual_prompt", ""),
        "motion_prompt": str(cut.get("motion_prompt") or ""),
        "global_style": header.get("global_style", ""),
        "version_type": header.get("version_type", ""),
        "generation": generation_spec.video_spec(
            cut, header, clip_sec=clip_sec, start_asset_hash=start_asset_hash).cache_fields(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_hit(existing: dict[str, Any] | None, new_hash: str) -> bool:
    """캐시된 에셋이 있고 해시가 같으면 재사용(재생성 불필요)."""
    return bool(existing) and existing.get("content_hash") == new_hash


# ─────────────────────────────────────────────────────────────
# 필터 조각 (순수)
# ─────────────────────────────────────────────────────────────
def layout_content_dims() -> tuple[int, int]:
    """비주얼이 채울 영역 크기. center_band 면 중앙 밴드(폭 전체 × 콘텐츠 높이), 아니면 전체 프레임."""
    if config.LAYOUT_MODE == "center_band":
        return config.RENDER_WIDTH, config.LETTERBOX_CONTENT_HEIGHT
    return config.RENDER_WIDTH, config.RENDER_HEIGHT


def letterbox_pad_suffix() -> str:
    """center_band: 콘텐츠 밴드를 전체 프레임에 상단 오프셋으로 얹고 상하 바를 채우는 pad 조각.

    2026 숏폼 트렌드 — 이미지를 꽉 채우지 않고 중앙 밴드 + 상하 검정 바. full_bleed 면 빈 문자열.
    """
    if config.LAYOUT_MODE != "center_band":
        return ""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    return f",pad={w}:{h}:0:{config.LETTERBOX_TOP_PX}:color={config.LETTERBOX_BAR_COLOR}"


def effect_filter(effects: list[str], duration: float, fps: int = config.RENDER_FPS) -> str:
    """effects enum → ffmpeg video 필터 조각. 켄번스/팬만 해석, 나머지는 정지.

    center_band 레이아웃이면 콘텐츠 밴드 크기로 렌더 후 letterbox pad(상하 바)를 덧붙인다.
    """
    frames = max(1, math.ceil(float(duration) * fps))
    w, h = layout_content_dims()
    pad = letterbox_pad_suffix()
    eff = set(effects or [])
    # ★ 줌은 컷 전체 길이에 걸쳐 선형으로 진행(on/frames)한다 — 예전엔 zoom+고정증분이라 ~3초 만에
    #   최대치에 닿고 남은 구간이 정지("정지화면")로 보였다. 중앙 기준(x/y)으로 줌해 흔들림 없이.
    zmax = 1.18
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    # ★★ **먼저 종횡비를 맞춰 잘라낸다**(2026-09-18 실측으로 잡았다). zoompan 의 `s=` 는 출력
    #   크기일 뿐 종횡비를 지켜 주지 않는다 — 9:16 그림(1080×1920)을 중앙 밴드(1080×1300)로
    #   내보내면 **세로로 눌린다.** 실측: 지름 600px 원이 600×406 타원이 됐다(68%).
    #   효과가 없는 컷은 아래 마지막 줄에서 이미 cover-crop 을 하고 있었다 — 켄번스·팬 branch 만
    #   그 줄을 안 지나가고 있었던 것이다. 저장된 지시서 실측: 스틸 컷 70개 중 21개(30%),
    #   13/40 편이 이 상태로 나갔다(사람은 납작하고 도해는 찌그러진다).
    fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
    if "ken_burns_zoom_in" in eff:
        return (fit + f"zoompan=z='min(1+{zmax - 1:.3f}*on/{frames},{zmax})':{center}"
                f":d={frames}:s={w}x{h}:fps={fps}") + pad
    if "ken_burns_zoom_out" in eff:
        return (fit + f"zoompan=z='max({zmax}-{zmax - 1:.3f}*on/{frames},1.0)':{center}"
                f":d={frames}:s={w}x{h}:fps={fps}") + pad
    if "pan_left" in eff:
        return fit + f"zoompan=z='{zmax}':x='(iw-iw/zoom)*(1-on/{frames})':d={frames}:s={w}x{h}:fps={fps}" + pad
    if "pan_right" in eff:
        return fit + f"zoompan=z='{zmax}':x='(iw-iw/zoom)*(on/{frames})':d={frames}:s={w}x{h}:fps={fps}" + pad
    # 효과 없음/미지원: 정지 프레임을 콘텐츠 영역에 맞춤(+상하 바).
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" + pad


# ─────────────────────────────────────────────────────────────
# 커맨드 빌더 (순수 — argv 리스트만 반환)
# ─────────────────────────────────────────────────────────────
def build_cut_command(
    *, image_path: str, audio_path: str, duration: float,
    effects: list[str], out_path: str,
) -> list[str]:
    """컷 1개 → mp4. 스틸을 duration(=나레이션 실측)만큼 루프 + 켄번스/팬 + 나레이션 오디오.

    ★ -shortest 필수: -loop 1(무한 프레임)+zoompan 은 스스로 끝나지 않으므로 오디오 길이에서
    멈춘다. duration 은 나레이션 실측(ffprobe)이라 -shortest 로 잘라도 목소리가 끝까지 나온다
    (예전 버그는 duration 을 반올림해 짧게 잡은 것이지 -shortest 자체가 아니었다).
    (자막은 조립 최종 단계에서 전체 타임라인에 ASS 로 번인한다.)"""
    vf = effect_filter(effects, duration)
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{float(duration):.3f}", "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        # ★ 오디오를 duration 까지 무음으로 채운다(2026-09-03). duration 에 숨 쉴 틈
        #   (CLIP_FIT_TAIL_PAD_SEC)이 들어가는데, -shortest 는 짧은 쪽에서 멈추므로 오디오를
        #   같이 늘리지 않으면 그 틈이 그대로 잘려 나간다. 패드가 0 이면 무음 0초 = 종전과 같다.
        "-af", f"apad=whole_dur={float(duration):.3f}",
        "-r", str(config.RENDER_FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        out_path,
    ]


def build_still_video_command(*, image_path: str, duration: float, effects: list[str],
                              out_path: str) -> list[str]:
    """스틸 한 장 → 오디오 없는 mp4(켄번스). stage 영상 자리에 **영상 생성 대신** 들어간다.

    ★ 2026-09-18 전·후 분할 스틸(연구 T2)의 영상 부분. build_cut_command 와 같은 필터를 쓰되
      오디오가 없다 — stage 영상은 컷들이 구간을 잘라 자기 나레이션을 얹기 때문이다
      (build_slice_cut_command). 길이는 -t 로 정확히 자른다(-shortest 가 기댈 오디오가 없다).
    """
    vf = effect_filter(effects, duration)
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{float(duration):.3f}", "-i", image_path,
        "-vf", vf,
        "-r", str(config.RENDER_FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an",
        out_path,
    ]


def clip_fit_video_filter(strategy: Strategy | None, duration: float,
                          fps: int = config.RENDER_FPS) -> str:
    """길이 보정 전략 → 단일 입출력 비디오 필터 조각(fit 뒤에 붙는다). 순수 함수.

    수정명세 v1 §3-3·§3-5. 클립은 고정 티어라 나레이션 길이와 딱 맞지 않는다:
      trim     : (-t 로 잘리고) 마지막 CLIP_FIT_TRIM_FADE_SEC 페이드아웃 — 나레이션이 타임라인 주인
      hold     : tpad=stop_mode=clone 으로 마지막 프레임을 늘리고 켄번스(zoom 1.00→1.04)
      flagged  : 보정 금지(=hold 로만 채우고 QA 빨간 플래그). 렌더는 막지 않는다
      pingpong : 여기서 다루지 않는다 — split/reverse/concat 은 라벨이 필요해 filter_complex 경로
                 (pingpong_filter_complex)로 간다.

    ★ 속도 늘리기(setpts)·단순 반복(head-to-tail loop) 금지 — 각각 모션이 끊기고 이음새가 튄다.
    """
    dur = float(duration)
    if strategy is None:
        # 전략 미판정(레거시 호출) → 기존 동작과 동일: 짧으면 홀드, -t 로 길면 트림.
        return f"tpad=stop_mode=clone:stop_duration={dur:.3f}"

    if strategy.kind == "trim":
        # ★ 잘라낼 것이 없으면(클립 길이 ≤ 목표) 페이드도 넣지 않는다. Manim 클립은 나레이션
        #   실측으로 렌더돼 clip_sec == target_sec 이라, 여기서 막지 않으면 모든 애니 컷의 끝이
        #   0.2s 검게 죽어 컷 경계마다 번쩍인다(판정 쪽에서도 0 으로 주지만 이중 방어).
        fade = min(float(strategy.fade_out_sec or 0.0), dur)
        if fade <= 0 or float(strategy.clip_sec) <= dur + 1e-6:
            return ""
        return f"fade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}"

    # hold / flagged / (loop_safe=false 로 폴백된 핑퐁): 마지막 프레임 홀드 + 켄번스.
    hold = f"tpad=stop_mode=clone:stop_duration={dur:.3f}"
    if strategy.ken_burns and strategy.hold_sec > 0:
        # 홀드 구간이 정지 사진처럼 보이지 않게 컷 전체에 미세 줌을 얹는다. 켄번스 표현은
        # effect_filter 와 동일한 zoompan 어휘를 재사용한다(재구현 금지 — §3-5).
        frames = max(1, math.ceil(dur * fps))
        w, h = layout_content_dims()
        zmax = config.CLIP_FIT_HOLD_ZOOM_MAX
        center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        hold += (f",zoompan=z='min(1+{zmax - 1:.3f}*on/{frames},{zmax})':{center}"
                 f":d={frames}:s={w}x{h}:fps={fps}")
    return hold


def pingpong_filter_complex(fit: str, loops: int, clip_sec: float,
                            fps: int = config.RENDER_FPS) -> str:
    """핑퐁 루프 filter_complex 문자열. 정방향+역재생을 이어붙여 이음새 없이 길이를 번다.

    라벨(`[a][b]`)이 필요한 다중 입출력 그래프라 -vf(단일 입출력)로는 표현할 수 없어 분리했다.
    loops>1 이면 왕복 단위를 loop 필터로 더 반복한다(짝수 배수라 이음새가 유지된다).
    출력 라벨은 항상 `[v]` — 호출측이 -map "[v]" 로 받는다.
    """
    n = max(1, int(loops))
    graph = (f"[0:v]{fit},setsar=1,split[pp_a][pp_b];[pp_b]reverse[pp_r];"
             f"[pp_a][pp_r]concat=n=2:v=1:a=0")
    if n > 1:
        # loop 는 프레임 단위. 왕복 1회 = clip_sec*2 초.
        frames = max(1, math.ceil(float(clip_sec) * 2 * fps))
        graph += f"[pp_c];[pp_c]loop=loop={n - 1}:size={frames}:start=0"
    return graph + "[v]"


def _clip_fit_geometry() -> str:
    """클립을 9:16 프레임(또는 center_band)에 맞추는 scale/crop/pad 조각."""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    cw, ch = layout_content_dims()
    if config.LAYOUT_MODE == "center_band":
        # ★ 콘텐츠 밴드를 "채운다"(increase+crop) — decrease+pad 로 하면 9:16 클립이 밴드 안에서
        #   좌우 필박스로 쪼그라들어 "화면만 작아진" 것처럼 보인다(사용자 피드백). 폭을 꽉 채우고
        #   밴드 높이로 crop 후 상하 바로 pad.
        return (f"scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},"
                f"pad={w}:{h}:0:{config.LETTERBOX_TOP_PX}:color={config.LETTERBOX_BAR_COLOR}")
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"


def build_board_clip_command(
    *, frame_paths: list[str], fps: int, audio_path: str,
    out_path: str, concat_file: str,
) -> list[str]:
    """설명판 프레임 시퀀스 → 컷 mp4 (명세 v3.4 §9 모션 규칙).

    ★ 왜 프레임 시퀀스인가: v3.3 은 단계 PNG 몇 장을 concat 으로 서로 다른 길이만큼 머물게 했다.
      그건 슬라이드쇼지 모션이 아니다 — §5-2 가 정면으로 금지한 "정적 텍스트가 주인공인 화면"이
      그대로 나갔다. 이제 30fps 로 그려 축이 그려지고 막대가 자라는 것이 실제로 보인다.
    ★ concat demuxer 를 그대로 쓴다(파일 목록 하나 = 그래프 길이 무관). 모든 프레임이 같은
      길이라 duration 은 1/fps 로 균일하다.
    ★ 스케일·크롭·pad 를 **일절 걸지 않는다.** 보드는 이미 1080×1920 로 그려졌고, 여기서 손대면
      §20-3 밴드 좌표가 픽셀 단위로 어긋난다(그게 이 보드 시스템의 존재 이유다).
    """
    fps = int(fps or config.RENDER_FPS)
    per = 1.0 / fps
    with open(concat_file, "w", encoding="utf-8") as f:
        for png in frame_paths:
            f.write(f"file '{os.path.abspath(png)}'\n")
            f.write(f"duration {per:.5f}\n")
        if frame_paths:
            # concat demuxer 는 마지막 항목의 duration 을 무시하므로 한 번 더 적어 준다.
            f.write(f"file '{os.path.abspath(frame_paths[-1])}'\n")
    total = len(frame_paths) * per
    return ["ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-i", audio_path,
            "-vf", f"fps={config.RENDER_FPS},format=yuv420p,setsar=1",
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-shortest", out_path]


def build_concat_clips_command(*, clip_paths: list[str], out_path: str,
                               concat_file: str) -> list[str]:
    """여러 Veo 클립 → **끊김 없는 stage 영상 하나**. 재인코딩 없이 이어 붙인다.

    ★ 왜 필요한가: Veo 는 한 번에 8초까지만 만든다. 20초 시퀀스는 8+8+4 로 나눠 만들고
      여기서 하나로 잇는다. 컷 단위 렌더가 컷 경계마다 화면을 끊던 것을 없애는 첫 걸음이다.
    ★ concat demuxer 를 쓴다 — 모든 클립이 같은 코덱·해상도(Veo 출력)라 재인코딩이 필요 없다.
      필터그래프로 이으면 길이만큼 메모리가 늘고 재시도가 어렵다(이 파일 맨 위 주석의 이유).
    """
    with open(concat_file, "w", encoding="utf-8") as fh:
        for path in clip_paths:
            # concat demuxer 는 POSIX 구분자를 원한다 — 윈도우 경로를 바꿔 준다.
            fh.write("file '%s'\n" % path.replace("\\", "/"))
    return ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c", "copy", out_path]


def build_pad_video_command(*, video_path: str, out_path: str,
                            target_sec: float) -> list[str]:
    """stage 영상이 계획보다 짧을 때만 — 마지막 프레임을 늘려 목표 길이를 채운다.

    ★★ **이것은 정상 경로가 아니다.** 시퀀스 렌더의 목적이 정지 화면(hold)을 없애는
      것인데 이 함수는 정지를 만든다. 그런데도 두는 이유: stage 안 클립 하나가 실패해
      영상이 짧아지면, 뒤 컷들의 구간이 영상 끝을 넘어가 **나레이션이 잘린다.**
      말이 잘리는 것이 화면이 멈추는 것보다 나쁘다 — 둘 중 덜 나쁜 쪽을 고른다.
    ★ 그래서 여기로 오면 반드시 경고를 남긴다(호출측 `stage_short`). 조용히 메우면
      "정지를 없앴다"고 믿는 채로 정지가 돌아온다.
    """
    return ["ffmpeg", "-y", "-i", video_path,
            "-vf", f"tpad=stop_mode=clone:stop_duration={float(target_sec):.3f}",
            "-t", f"{float(target_sec):.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", out_path]


def build_slice_cut_command(*, video_path: str, audio_path: str,
                            start_sec: float, duration: float, out_path: str) -> list[str]:
    """stage 영상의 **한 구간** + 그 컷의 나레이션 → 컷 mp4.

    ★★ 이것이 시퀀스 렌더의 핵심이다. 컷은 자기 영상을 갖지 않고 **연속 영상의 서로 다른
      구간**을 본다 — 그래서 컷 경계에서 화면이 끊기지 않는다.
    ★ hold(정지) 전략이 없다. stage 영상은 나레이션 전체를 덮도록 만들어졌으므로
      메울 구멍이 없다 — 얼어붙을 자리가 구조적으로 사라진다.

    ★★ **`-ss` 는 영상 입력 `-i` 앞에 온다**(2026-09-08 첫 실물 렌더에서 잡았다).
      종전에는 두 입력 **뒤에** 있었고, 거기서는 입력 탐색이 아니라 **출력 옵션**이 된다 —
      즉 완성된 스트림의 앞 `start_sec` 초를 버린다. 그런데 나레이션은 컷마다 0초에서
      시작하는 자기 파일이라, 그 만큼이 **목소리에서 깎여 나갔다.**
      시작 지점이 나레이션 길이를 넘는 컷(= stage 의 두 번째 컷부터)은 남는 게 없어
      **261바이트 빈 mp4** 가 됐고, 조립은 그것을 모른 채 이어 붙여 42초짜리가 13.5초로
      나갔다(실측: 7컷 중 4컷 소실). 옛 주석은 "-i 앞에 두면 키프레임으로 스냅한다"고
      적었지만, **재인코딩할 때 ffmpeg 은 앞쪽 `-ss` 도 정확히 탐색한다** — 여기는
      libx264 로 다시 인코딩하므로 해당되지 않는다.
      ★ 오디오 입력에는 `-ss` 를 걸지 않는다. 컷 나레이션은 언제나 0초에서 시작한다.
    """
    fit = _clip_fit_geometry()
    return ["ffmpeg", "-y",
            "-ss", f"{float(start_sec):.3f}", "-i", video_path,
            "-i", audio_path,
            "-t", f"{float(duration):.3f}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", fit,
            "-af", f"apad=whole_dur={float(duration):.3f}",
            "-r", str(config.RENDER_FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", out_path]


def build_clip_cut_command(
    *, clip_path: str, audio_path: str, duration: float, out_path: str,
    strategy: Strategy | None = None,
) -> list[str]:
    """클립 컷(Manim/Veo) → mp4. 9:16 맞춤 + 나레이션 길이로 conform + 길이 보정 전략 적용.

    duration 은 나레이션 실측(ffprobe)이라 -t/-shortest 로 잘라도 목소리가 끝까지 나온다.
    strategy 가 있으면 §3-3 전략(trim/hold/pingpong/flagged)대로 비디오 필터를 얹는다.
    없으면 기존 동작(tpad 홀드 + 트림)과 동일 — 레거시 호출 호환.
    """
    fit = _clip_fit_geometry()
    tail = ["-t", f"{float(duration):.3f}",
            # ★ 오디오를 duration 까지 무음으로 채운다 — 스틸 빌더와 같은 이유(2026-09-03).
            #   두 분기(핑퐁·일반)가 이 tail 을 공유하므로 여기 한 곳이면 된다.
            "-af", f"apad=whole_dur={float(duration):.3f}",
            "-r", str(config.RENDER_FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac"]

    if strategy is not None and strategy.kind == "pingpong" and strategy.loops >= 1:
        # ★ 핑퐁(reverse)은 fit 뒤에 둔다 — 프레임 수가 줄어든 축소본을 뒤집는 게 싸다.
        #   왕복이 목표를 넘길 수 있으므로 tpad 없이 -t 로 자른다(넘침은 무해).
        graph = pingpong_filter_complex(fit, strategy.loops, strategy.clip_sec)
        return ["ffmpeg", "-y", "-i", clip_path, "-i", audio_path,
                "-filter_complex", graph,
                "-map", "[v]", "-map", "1:a", *tail, "-shortest", out_path]

    parts = [fit, "setsar=1", clip_fit_video_filter(strategy, duration)]
    vf = ",".join(p for p in parts if p)
    return ["ffmpeg", "-y", "-i", clip_path, "-i", audio_path,
            "-vf", vf,
            "-map", "0:v", "-map", "1:a", *tail, "-shortest", out_path]


def build_concat_file(cut_paths: list[str]) -> str:
    """concat demuxer 입력 파일 내용."""
    return "\n".join(f"file '{p}'" for p in cut_paths) + "\n"


def build_concat_command(list_path: str, out_path: str) -> list[str]:
    """컷 mp4 들을 concat demuxer 로 이어붙임(재인코딩 — transition 안전)."""
    return [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        out_path,
    ]


def build_loudnorm_command(
    in_path: str, out_path: str, lufs: float = config.LOUDNESS_LUFS
) -> list[str]:
    """최종 오디오 라우드니스 정규화(-14 LUFS 기본)."""
    return [
        "ffmpeg", "-y", "-i", in_path,
        "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11",
        "-c:v", "copy", "-c:a", "aac",
        out_path,
    ]


# ─────────────────────────────────────────────────────────────
# 자막 번인 (libass, ASS) — M-V5
# ─────────────────────────────────────────────────────────────
# ASS 파일에 PlayResX/Y 를 영상 해상도로 명시하므로 폰트/마진이 실제 픽셀 단위로 동작한다
# (SRT+force_style 은 libass 기본 PlayResY=288 좌표계로 스케일돼 마진/크기가 어긋난다).
def filter_path(path: str) -> str:
    """필터 그래프 안에 넣을 파일 경로를 이스케이프한다.

    ★ 왜 필요한가(2026-08-29 Windows 실측): 윈도우 절대경로를 그대로 넣으면 ffmpeg 가
      드라이브 문자 뒤의 **콜론을 옵션 구분자**로 읽어, 뒤쪽 경로가 `original_size` 값으로
      넘어가며 실패한다("Unable to parse original_size option value"). 역슬래시도 필터
      문법에서 이스케이프 문자다.
    ★ 리눅스 경로에는 콜론·역슬래시가 없어 **동작이 바뀌지 않는다**(GitHub Actions 무영향).
    """
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def build_subtitles_command(in_video: str, ass_path: str, out_path: str) -> list[str]:
    """joined 영상에 ASS 자막을 번인(오디오는 그대로 복사)."""
    return [
        "ffmpeg", "-y", "-i", in_video, "-vf", f"ass=filename='{filter_path(ass_path)}'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
        out_path,
    ]


# ─────────────────────────────────────────────────────────────
# BGM 톤(플레이스홀더) + 더킹 믹스 (sidechaincompress) — M-V5
# ─────────────────────────────────────────────────────────────
def build_bgm_tone_command(out_path: str, duration: float,
                           freq: int = 220, volume: float = config.BGM_VOLUME) -> list[str]:
    """플레이스홀더 BGM: 저음 사인 톤(구성상 로열티프리). 실제 라이브러리 트랙은 M-V5 마무리에서 교체."""
    return [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={max(1.0, float(duration)):.2f}",
        "-af", f"volume={volume}",
        "-c:a", "aac", out_path,
    ]


def build_bgm_duck_command(in_video: str, bgm_path: str, out_path: str,
                           lufs: float = config.LOUDNESS_LUFS,
                           bgm_volume: float = config.BGM_VOLUME) -> list[str]:
    """나레이션(0:a)으로 BGM(1:a)을 사이드체인 더킹 → 믹스 → loudnorm. 나레이션 명료도 확보."""
    th, ratio = config.BGM_DUCK_THRESHOLD, config.BGM_DUCK_RATIO
    filt = (
        f"[1:a]volume={bgm_volume}[bg];"
        f"[bg][0:a]sidechaincompress=threshold={th}:ratio={ratio}:attack=5:release=250[duck];"
        f"[0:a][duck]amix=inputs=2:duration=first:dropout_transition=0[mix];"
        f"[mix]loudnorm=I={lufs}:TP=-1.5:LRA=11[a]"
    )
    return [
        "ffmpeg", "-y", "-i", in_video, "-i", bgm_path,
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        out_path,
    ]


# ─────────────────────────────────────────────────────────────
# ④ 엔벨로프 더킹 (DV10) — VO 스팬 간극 병합 → 사전계산 볼륨 엔벨로프 (펌핑 방지)
# ─────────────────────────────────────────────────────────────
def duck_spans_from_words(words: list[dict[str, Any]],
                          merge_gap_ms: int | None = None) -> list[tuple[float, float]]:
    """전역 VO 단어 스팬 → 간극 병합된 더킹 구간 [(start,end)…].

    인접 스팬 간극이 merge_gap_ms(기본 DUCK_MERGE_GAP_MS=800) 미만이면 하나로 병합한다.
    → 청크 사이 미세 간극에서 BGM 이 튀어오르는 펌핑을 원천 차단(명세 §4.2). 순수 로직.
    """
    gap = (config.DUCK_MERGE_GAP_MS if merge_gap_ms is None else merge_gap_ms) / 1000.0
    spans: list[tuple[float, float]] = []
    for w in words:
        try:
            s, e = float(w.get("start")), float(w.get("end"))
        except (TypeError, ValueError):
            continue
        if e <= s:
            continue
        if spans and s - spans[-1][1] < gap:
            spans[-1] = (spans[-1][0], max(spans[-1][1], e))
        else:
            spans.append((s, e))
    return spans


def _db_to_gain(db: float) -> float:
    """dB 감쇠 → 선형 게인. -20dB → 0.1."""
    return 10.0 ** (float(db) / 20.0)


def build_volume_envelope_expr(spans: list[tuple[float, float]], *,
                               duck_db: float | None = None,
                               attack_ms: int | None = None,
                               release_ms: int | None = None) -> str:
    """더킹 구간 → ffmpeg volume 표현식(t 기반, attack/release 선형 램프).

    구간 밖은 게인 1(원복), 구간 안은 duck_db 감쇠. 진입은 attack 동안 1→G, 이탈은 release 동안 G→1
    선형 램프(펌핑 없는 부드러운 사전계산 엔벨로프). 결정론적 — 실시간 사이드체인보다 재현성 우수.
    """
    g = _db_to_gain(config.DUCK_DB if duck_db is None else duck_db)
    a = (config.DUCK_ATTACK_MS if attack_ms is None else attack_ms) / 1000.0
    r = (config.DUCK_RELEASE_MS if release_ms is None else release_ms) / 1000.0
    expr = "1"
    for s, e in reversed(spans):
        dur = e - s
        aa = max(1e-3, min(a, dur / 2))
        rr = max(1e-3, min(r, dur / 2))
        attack = f"({1.0:.4f}+({g - 1.0:.4f})*(t-{s:.3f})/{aa:.4f})"
        release = f"({g:.4f}+({1.0 - g:.4f})*(t-{e - rr:.3f})/{rr:.4f})"
        inner = (
            f"if(lt(t,{s + aa:.3f}),{attack},"
            f"if(gt(t,{e - rr:.3f}),{release},{g:.4f}))"
        )
        expr = f"if(between(t,{s:.3f},{e:.3f}),{inner},{expr})"
    return expr


def build_bgm_envelope_duck_command(in_video: str, bgm_path: str, out_path: str,
                                    spans: list[tuple[float, float]], *,
                                    lufs: float = config.LOUDNESS_LUFS,
                                    bgm_volume: float = config.BGM_VOLUME) -> list[str]:
    """④사전계산 엔벨로프 더킹: BGM 을 VO 병합구간에서만 감쇠 → 믹스 → loudnorm.

    실시간 sidechaincompress 대신 t 기반 volume 엔벨로프를 적용(결정론·재현성, 펌핑 없음).
    """
    expr = build_volume_envelope_expr(spans)
    filt = (
        f"[1:a]volume={bgm_volume}[bg];"
        f"[bg]volume=eval=frame:volume='{expr}'[duck];"
        f"[0:a][duck]amix=inputs=2:duration=first:dropout_transition=0[mix];"
        f"[mix]loudnorm=I={lufs}:TP=-1.5:LRA=11[a]"
    )
    return [
        "ffmpeg", "-y", "-i", in_video, "-i", bgm_path,
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        out_path,
    ]


# ─────────────────────────────────────────────────────────────
# 실행 (ffmpeg 필요)
# ─────────────────────────────────────────────────────────────
def probe_duration(path: str) -> float:
    """미디어 파일 실측 길이(초). 실패하면 0.0 — 호출측이 "미측정"으로 다룬다.

    §3-3 길이 보정은 클립의 *실제* 길이를 알아야 한다(요청 티어와 다를 수 있고, Manim 클립은
    애초에 티어 개념이 없다). ffprobe 의존이라 순수 함수 테스트 대상 밖.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return round(float((out.stdout or "").strip()), 3)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        log.warning("ffprobe 길이 측정 실패(%s): %s", path, exc)
        return 0.0


def build_last_frame_command(clip_path: str, out_png: str) -> list[str]:
    """영상의 **마지막 프레임**을 PNG 로 뽑는다 (I2V 연쇄용).

    ★ 왜 필요한가: 다음 영상 컷의 시작 화면으로 쓰면 카메라가 끊기지 않고 이어진다.
      벤치마크 채널의 "이어지는 느낌"이 여기서 나온다 —
      docs/benchmark-realistic-shorts-2026-08-19.md.
    ★ -sseof 로 끝에서 되짚는다(길이를 몰라도 된다). -update 1 은 단일 이미지 출력.
    """
    return [
        "ffmpeg", "-y", "-sseof", "-0.5", "-i", clip_path,
        "-vframes", "1", "-update", "1", "-q:v", "2", out_png,
    ]


def run_ffmpeg(argv: list[str]) -> None:
    log.info("ffmpeg: %s", " ".join(argv[:6]) + " …")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=config.FFMPEG_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg 타임아웃({config.FFMPEG_TIMEOUT_SEC}s): {' '.join(argv[:6])} …") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패({proc.returncode}): {proc.stderr[-500:]}")


def assemble(cut_files: list[str], work_dir: str, out_path: str) -> str:
    """컷 mp4 목록 → concat → loudnorm → 최종 mp4. 반환: out_path."""
    import os

    list_path = os.path.join(work_dir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write(build_concat_file(cut_files))
    joined = os.path.join(work_dir, "_joined.mp4")
    run_ffmpeg(build_concat_command(list_path, joined))
    run_ffmpeg(build_loudnorm_command(joined, out_path))
    return out_path


def build_speed_command(in_path: str, out_path: str, speed: float) -> list[str]:
    """완성 영상 → 전체 재생속도 조정. 영상·소리를 **같은 비율로** 건다.

    ★ `setpts=PTS/N` 은 프레임 표시 시각을 당기고 `atempo=N` 은 소리를 같은 배로 줄인다.
      둘이 같아야 입모양·자막·더킹이 안 어긋난다 — 한쪽만 걸면 싱크가 깨진다.
    ★ `atempo` 는 0.5~2.0 만 받는다. 그 밖은 두 번 걸어야 하는데, 재생속도를 2배 넘게
      바꿀 일이 없으므로 범위를 벗어나면 **속도를 포기하고 원본을 그대로 둔다**
      (조용히 이상한 배속을 내보내는 것보다 안 바꾸는 것이 낫다).
    """
    if not (0.5 <= float(speed) <= 2.0):
        raise ValueError(f"재생속도는 0.5~2.0 만 지원한다: {speed}")
    return ["ffmpeg", "-y", "-i", in_path,
            "-filter:v", f"setpts=PTS/{float(speed):.3f}",
            "-filter:a", f"atempo={float(speed):.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            out_path]


def assemble_full(cut_files: list[str], work_dir: str, out_path: str, *,
                  ass_text: str = "", bgm: bool = None, total_sec: float = 0.0,
                  duck_spans: list[tuple[float, float]] | None = None) -> str:
    """컷 mp4 → concat → (ASS 자막 번인) → (BGM 더킹)/loudnorm → 최종 mp4.

    ass_text 있으면 libass 로 자막 번인. bgm(기본 config.BGM_ENABLED) 이면 플레이스홀더 톤을
    BGM 으로 더킹해 믹스, 아니면 loudnorm 만.

    ④더킹 방식: config.DUCK_METHOD=='precomputed_envelope' 이고 duck_spans 가 있으면 사전계산
    엔벨로프(펌핑 없음). 없으면 기존 실시간 사이드체인으로 폴백. 반환: out_path.
    """
    import os as _os

    use_bgm = config.BGM_ENABLED if bgm is None else bgm

    # ★★ **빈 컷 파일을 조용히 넘기지 않는다**(2026-09-08 첫 실물 렌더).
    #   컷 7개 중 4개가 261바이트짜리 빈 mp4 였는데(구간 자르기 인자 결함), concat 은
    #   그것을 말없이 건너뛰었고 렌더는 **성공으로 끝났다** — 42초여야 할 영상이 13.5초로
    #   나갔고 로그 어디에도 사유가 없었다. 조립이 조용히 절반을 버리면 아무도 모른다.
    #   여기서 막으면 "왜 짧지?"를 파일 크기 하나로 즉시 알 수 있다.
    empty = [p for p in cut_files
             if not _os.path.exists(p) or _os.path.getsize(p) < config.MIN_CUT_FILE_BYTES]
    if empty:
        raise RuntimeError(
            f"빈 컷 파일 {len(empty)}/{len(cut_files)}개 — 조립을 멈춘다"
            f"(이어 붙이면 그만큼 짧은 영상이 조용히 나간다): "
            + ", ".join(_os.path.basename(p) for p in empty[:6]))

    list_path = _os.path.join(work_dir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write(build_concat_file(cut_files))
    stage = _os.path.join(work_dir, "_joined.mp4")
    run_ffmpeg(build_concat_command(list_path, stage))

    if ass_text.strip():
        ass_path = _os.path.join(work_dir, "subs.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_text)
        subbed = _os.path.join(work_dir, "_subbed.mp4")
        run_ffmpeg(build_subtitles_command(stage, ass_path, subbed))
        stage = subbed

    if use_bgm:
        bgm_path = _os.path.join(work_dir, "bgm.m4a")
        run_ffmpeg(build_bgm_tone_command(bgm_path, total_sec or 30.0))
        if config.DUCK_METHOD == "precomputed_envelope" and duck_spans:
            run_ffmpeg(build_bgm_envelope_duck_command(stage, bgm_path, out_path, duck_spans))
        else:
            run_ffmpeg(build_bgm_duck_command(stage, bgm_path, out_path))
    else:
        run_ffmpeg(build_loudnorm_command(stage, out_path))

    # ★ 전체 재생속도 — **조립이 끝난 파일에 한 번만** 건다(config 주석의 이유).
    #   1.0 이면 아무것도 하지 않는다 → 기존 출력 바이트 불변.
    speed = float(config.RENDER_PLAYBACK_SPEED)
    if abs(speed - 1.0) > 0.001:
        sped = _os.path.join(work_dir, "_sped.mp4")
        _os.replace(out_path, sped)
        run_ffmpeg(build_speed_command(sped, out_path, speed))
    return out_path
