"""렌더 QA 게이트 (수정지시서 v2 §7) — 발행 전 실제 mp4 프레임/오디오 실검.

명세 §7 정정: "자막 CC 미사용률 98.8%=번인 버그"는 오독이었다. 그래서 여기서는 CC 지표가 아니라
**실제 렌더 산출물**을 ffprobe/ffmpeg 로 실측해, 자동 판정 가능한 하드 신호만 게이트로 삼는다:
끝 검은 프레임 · >250ms 무음 · 오디오 클리핑 · 길이 이상 · 오디오 트랙 유무.

자막 "존재"는 우리 파이프라인이 assemble 에서 ASS 를 결정적으로 번인하므로 구조적으로 보장된다 —
프레임이 디코드되는지(깨진 출력이 아닌지)만 확인하고, 자막 가독성/싱크는 승인 UI 썸네일로 육안 확인
(프레임 OCR 자동판정은 과투자라 넣지 않는다 — 명세 §7 원칙).

핵심 판정(evaluate_qa)은 ffprobe 신호 dict 만 받는 **순수 함수**라 네트워크 없이 단위 테스트한다.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from . import config
from .util import log


def evaluate_qa(signals: dict[str, Any]) -> dict[str, Any]:
    """ffprobe/ffmpeg 로 뽑은 신호 → {passed, hard_fail[], warnings[], signals}(순수 함수).

    signals 기대 키: duration_sec, has_audio(bool), max_silence_ms(int), end_black_sec(float),
    audio_peak_db(float|None), frame_decodable(bool), max_freeze_sec(float).
    hard_fail = 발행 차단(오디오 없음·끝 검은프레임·길이 이상·프레임 손상).
    warnings = 표시하되 승인 가능(긴 무음·클리핑·정지 화면).

    ★ Q1 정지 화면(§9 "3초 동일 프레임"): 조립된 영상에는 이 검사가 **없었다**(2026-09-03).
      컷 후보에는 freezedetect 가 있는데 최종 mp4 에는 없어서, 화면이 멈춘 채로 나가도
      오디오가 있고 길이만 맞으면 통과였다. 지금은 **경고**다 —
      문턱을 실제 렌더 분포에 대고 잰 적이 없어서(렌더 0회) 차단으로 올리지 않았다.
      config.RENDER_QA_FREEZE_BLOCKS 를 켜면 차단이 된다(Phase 4 이후 판단).
    """
    hard: list[str] = []
    warn: list[str] = []

    dur = float(signals.get("duration_sec") or 0)
    if dur < config.RENDER_QA_MIN_SEC or dur > config.RENDER_QA_MAX_SEC:
        hard.append(f"길이 이상: {dur:.1f}s (허용 {config.RENDER_QA_MIN_SEC}~{config.RENDER_QA_MAX_SEC}s)")

    if not signals.get("has_audio", True):
        hard.append("오디오 트랙 없음")

    if not signals.get("frame_decodable", True):
        hard.append("프레임 디코드 실패(손상된 출력)")

    end_black = float(signals.get("end_black_sec") or 0)
    if end_black > config.RENDER_QA_END_BLACK_MAX_SEC:
        hard.append(f"끝 검은 프레임 {end_black:.2f}s (허용 {config.RENDER_QA_END_BLACK_MAX_SEC}s)")

    max_sil = int(signals.get("max_silence_ms") or 0)
    if max_sil > config.RENDER_QA_MAX_SILENCE_MS:
        warn.append(f"긴 무음 {max_sil}ms (>{config.RENDER_QA_MAX_SILENCE_MS}ms)")

    freeze = float(signals.get("max_freeze_sec") or 0)
    if freeze > config.RENDER_QA_MAX_FREEZE_SEC:
        msg = (f"정지 화면 {freeze:.1f}s 연속 "
               f"(허용 {config.RENDER_QA_MAX_FREEZE_SEC}s) — 화면이 멈췄거나 비었다")
        (hard if config.RENDER_QA_FREEZE_BLOCKS else warn).append(msg)

    peak = signals.get("audio_peak_db")
    if peak is not None and float(peak) > config.RENDER_QA_PEAK_CEILING_DB:
        warn.append(f"오디오 피크 {float(peak):.1f}dB (클리핑 위험, 천장 {config.RENDER_QA_PEAK_CEILING_DB}dB)")

    return {"passed": not hard, "hard_fail": hard, "warnings": warn, "signals": signals}


def evaluate_clip_fit(records: list[dict[str, Any]]) -> dict[str, Any]:
    """컷별 길이 보정 로그 → {strategy_counts, flags[], warnings[], cuts}(순수 함수). 수정명세 v1 §3-6.

    records 각 행 기대 키: cut_no, clip_sec, narration_sec, ratio, loop_safe, strategy.
    판정(§3-6):
      - strategy='flagged'(=ratio > CLIP_FIT_PINGPONG_RATIO_MAX) 컷 존재 → 빨간 플래그.
        "4s 클립에 12s 나레이션"은 연출 실패이므로 렌더로 가릴 문제가 아니다 → 컷 분할 권고.
        렌더 자체는 막지 않는다(승인 UI 경고).
      - strategy='pingpong' 비중 > CLIP_FIT_PINGPONG_WARN_SHARE → 노란 경고(컷 설계 재검토 신호).
    """
    counts: dict[str, int] = {}
    for r in records or []:
        kind = str(r.get("strategy") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1

    flags: list[str] = []
    warns: list[str] = []
    total = len(records or [])

    flagged = [r for r in (records or []) if r.get("strategy") == "flagged"]
    if flagged:
        detail = ", ".join(
            f"컷{r.get('cut_no')}(클립 {float(r.get('clip_sec') or 0):.1f}s vs "
            f"나레이션 {float(r.get('narration_sec') or 0):.1f}s)" for r in flagged)
        flags.append(
            f"클립이 나레이션보다 과도하게 짧음(ratio>{config.CLIP_FIT_PINGPONG_RATIO_MAX}): "
            f"{detail} — 렌더 보정 대신 컷 분할을 권고")

    pingpong = counts.get("pingpong", 0)
    if total and pingpong / total > config.CLIP_FIT_PINGPONG_WARN_SHARE:
        warns.append(
            f"핑퐁 루프 컷 비중 {pingpong}/{total} "
            f"(>{int(config.CLIP_FIT_PINGPONG_WARN_SHARE * 100)}%) — 지시서 컷 설계 재검토")

    return {"strategy_counts": counts, "flags": flags, "warnings": warns,
            "cuts": list(records or [])}


def evaluate_clip_motion(records: list[dict[str, Any]]) -> dict[str, Any]:
    """컷별 클립 지표 → {warnings[], low_cuts[], median} (순수 함수).

    무엇을 잡는가: **"영상인데 거의 정지해 있다"**. 운영자가 첫 실사형 렌더를 보고 한 말이
    "화려하게 3d로 역동적으로 움직여야 하는데 의미없는 화면"이었고, 그 인상평이
    숫자로 확인됐다 — 벤치 중앙값 0.0117 vs 우리 0.0012, **9.5배**.

    ★ 왜 종전에는 못 잡았나: `clip_metrics` 가 motion_median 을 **기록만** 했다.
      문턱이 없었던 이유는 정당했다 — 비교할 좋은 표본이 없었다. 2026-09-04 에
      운영자가 발행된 영상을 줘서 기준선이 생겼다(config.CLIP_MOTION_MEDIAN_FLOOR 주석).

    ★ 후보가 여럿인 컷은 **채택된 것이 아니라 최고치**로 본다. 여기 오는 records 에는
      후보가 전부 들어 있고 어느 것이 뽑혔는지 표시가 없다 — 최고치를 쓰면
      "그나마 가장 잘 움직인 후보조차 미달"이라는 더 강한 진술이 된다(오탐이 줄어든다).
    ★ 재지 못한 컷(measured=False)은 **세지 않는다**. 스틸 컷은 애초에 정지가 정상이고,
      측정 실패를 품질 미달로 부르면 지표가 거짓말을 한다.
    """
    best: dict[Any, float] = {}
    for r in records or []:
        if not r.get("measured"):
            continue
        try:
            med = float(r.get("motion_median"))
        except (TypeError, ValueError):
            continue
        if med < 0:
            continue                       # -1.0 = 못 쟀다는 표시(clip_candidates)
        no = r.get("cut_no")
        best[no] = max(best.get(no, -1.0), med)

    if not best:
        return {"warnings": [], "low_cuts": [], "median": None, "measured_cuts": 0}

    floor = float(config.CLIP_MOTION_MEDIAN_FLOOR)
    low = sorted(no for no, med in best.items() if med < floor)
    vals = sorted(best.values())
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0

    warns: list[str] = []
    share = len(low) / float(len(best))
    if low and share > float(config.CLIP_MOTION_LOW_SHARE_WARN):
        warns.append(
            f"영상 컷 {len(low)}/{len(best)}개가 거의 정지({floor} 미만) — "
            f"중앙값 {median:.4f}, 발행 벤치마크는 {config.CANDIDATE_MOTION_MEDIAN_TARGET}. "
            f"컷 {', '.join(str(n) for n in low[:8])}. "
            "temporal_plan 의 카메라·변형이 프롬프트까지 갔는지 본다")
    elif low:
        warns.append(
            f"거의 정지한 영상 컷 {len(low)}개: {', '.join(str(n) for n in low[:8])} "
            f"(motion_median < {floor})")
    return {"warnings": warns, "low_cuts": low, "median": round(median, 5),
            "measured_cuts": len(best)}


def merge_clip_motion_qa(qa: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """움직임 QA 를 mp4 QA 결과에 합친다. **경고만** — hard_fail 에 넣지 않는다."""
    mot = evaluate_clip_motion(records)
    if mot["warnings"]:
        qa.setdefault("warnings", []).extend(mot["warnings"])
        log.warning("클립 움직임 QA: %s", mot["warnings"])
    return mot


def merge_clip_fit_qa(qa: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """길이 보정 QA 를 mp4 QA 결과에 합친다. 빨간 플래그·노란 경고를 warnings 에 노출.

    ★ hard_fail 에는 넣지 않는다 — §3-6 "승인 UI 경고, 렌더 차단은 아님". 반환값은 clip_fit 블록.
    """
    fit = evaluate_clip_fit(records)
    if fit["flags"] or fit["warnings"]:
        qa.setdefault("warnings", []).extend([*fit["flags"], *fit["warnings"]])
        log.warning("길이 보정 QA: 플래그=%s 경고=%s", fit["flags"], fit["warnings"])
    return fit


def _ffprobe_json(path: str) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return json.loads(out.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def probe_signals(mp4_path: str) -> dict[str, Any]:
    """실제 mp4 에서 QA 신호 추출(ffprobe/ffmpeg). 실패한 항목은 보수적 기본값.

    네트워크 없음이나 subprocess(ffmpeg/ffprobe) 의존 — evaluate_qa 와 분리해 테스트 대상 밖에 둔다.
    """
    meta = _ffprobe_json(mp4_path)
    fmt = meta.get("format") or {}
    streams = meta.get("streams") or []
    duration = float(fmt.get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    has_video = any(s.get("codec_type") == "video" for s in streams)

    # >Nms 무음 구간: silencedetect. 끝 검은 프레임: blackdetect. 피크: astats.
    max_silence_ms = 0
    end_black_sec = 0.0
    max_freeze_sec = 0.0
    freeze_starts: list[float] = []
    audio_peak_db: float | None = None
    try:
        det = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", mp4_path,
             "-af", f"silencedetect=n=-40dB:d={config.RENDER_QA_MAX_SILENCE_MS/1000.0},astats=metadata=1:reset=0",
             "-vf", (f"blackdetect=d=0.1:pic_th=0.98,"
                     f"freezedetect=n={config.RENDER_QA_FREEZE_NOISE}:"
                     f"d={config.RENDER_QA_MAX_FREEZE_SEC}"),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        stderr = det.stderr or ""
        for line in stderr.splitlines():
            if "silence_duration:" in line:
                try:
                    dur_ms = int(float(line.split("silence_duration:")[1].strip()) * 1000)
                    max_silence_ms = max(max_silence_ms, dur_ms)
                except (ValueError, IndexError):
                    pass
            if "black_start:" in line and "black_end" not in line:
                # 끝부분 블랙만 관심 — black_start 가 (duration - tolerance) 이후면 끝 블랙.
                try:
                    start = float(line.split("black_start:")[1].split()[0])
                    if duration and start >= duration - 1.0:
                        end_black_sec = max(end_black_sec, duration - start)
                except (ValueError, IndexError):
                    pass
            # ★★ freeze_duration 만 보면 **끝까지 얼어 있는 영상을 놓친다**(2026-09-03 실측).
            #   freezedetect 는 정지가 **끝날 때** freeze_end·freeze_duration 을 찍는다.
            #   영상 끝까지 멈춰 있으면 freeze_start 하나만 나오고 duration 은 영영 안 나온다 —
            #   즉 **가장 나쁜 경우가 조용히 0 으로 잡혔다.** 실측: 8초 정지 영상이 0.00s.
            #   그래서 start 를 따로 모으고, 짝이 없으면 영상 끝까지로 친다.
            if "freeze_start:" in line:
                try:
                    freeze_starts.append(float(line.split("freeze_start:")[1].split()[0]))
                except (ValueError, IndexError):
                    pass
            if "freeze_duration:" in line:
                try:
                    dur_f = float(line.split("freeze_duration:")[1].split()[0])
                    max_freeze_sec = max(max_freeze_sec, dur_f)
                    if freeze_starts:
                        freeze_starts.pop(0)      # 짝이 맞은 start 는 소비한다
                except (ValueError, IndexError):
                    pass
            if "Peak level dB:" in line:
                try:
                    audio_peak_db = float(line.split("Peak level dB:")[1].strip())
                except (ValueError, IndexError):
                    pass
        # 짝 없는 freeze_start = 영상 끝까지 얼어 있었다는 뜻이다.
        for st in freeze_starts:
            if duration:
                max_freeze_sec = max(max_freeze_sec, max(0.0, duration - st))
    except (subprocess.SubprocessError, OSError) as exc:  # ffmpeg 없거나 실패 → 신호 일부 결측
        log.warning("렌더 QA 신호 추출 실패(부분): %s", exc)

    return {
        "duration_sec": round(duration, 2),
        "has_audio": has_audio,
        "frame_decodable": has_video and duration > 0,
        "max_silence_ms": max_silence_ms,
        "end_black_sec": round(end_black_sec, 2),
        # ★ 원장에 남긴다 — 지금은 경고지만, Phase 4 가 분포를 주면 이 값으로 문턱을 정한다.
        "max_freeze_sec": round(max_freeze_sec, 2),
        "audio_peak_db": audio_peak_db,
    }


def run_qa(mp4_path: str) -> dict[str, Any]:
    """mp4 경로 → QA 결과 dict(probe + evaluate). render.py 가 렌더 직후 호출."""
    if not config.RENDER_QA_ENABLED:
        return {"passed": True, "hard_fail": [], "warnings": [], "signals": {}, "skipped": True}
    signals = probe_signals(mp4_path)
    result = evaluate_qa(signals)
    if result["hard_fail"]:
        log.warning("렌더 QA 하드 실패 %s: %s", mp4_path, result["hard_fail"])
    elif result["warnings"]:
        log.info("렌더 QA 경고 %s: %s", mp4_path, result["warnings"])
    return result
