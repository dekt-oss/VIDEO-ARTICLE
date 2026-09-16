"""Candidate Selection — **뽑아서 고른다** (v2 Phase E3).

무엇을 푸는가: 생성형 영상은 확률적이다. 한 번 뽑아 그대로 쓰는 것과

    후보 A · 후보 B → 더 나은 쪽 채택

은 결과 품질의 **상한**이 다르다. 벤치마크 채널이 정확히 그렇게 만든다
(`docs/benchmark-realistic-shorts-2026-08-19.md`): **"8초를 뽑아 좋은 3초만 쓴다."**
코덱스 리뷰 §9 가 이것을 "현재 설계에 없는 축"으로 지목했다 — 등급제는 **생성 품질
배분**만 있고 **선택 품질**이 없었다.

★★ **판정은 코드가 한다.** 이 저장소의 자세 그대로다 — 모델에게 "어느 쪽이 좋냐"고
  물으면 그 답이 또 자기보고다. 대신 영상 자체에서 신호를 뽑는다:

    freeze_ratio    얼어 있는 시간 비율 (ffmpeg freezedetect)
    scene_changes   장면이 실제로 바뀐 횟수 (ffmpeg scdet)
    motion_energy   프레임 간 변화량 평균
    text_burn_in    화면에 박힌 글자의 양 (기록 전용 — 문턱 미교정)

  이 셋은 리뷰 §16 이 요구한 Quality Parity 지표(Static Hold Ratio · Visual Change
  Rate · Camera Beat Density)와 **같은 축**이다 — 후보 선택에 쓰는 잣대를 최종
  품질 평가에도 그대로 쓴다(잣대가 둘이면 서로를 반박한다).

★ 선택 로직(`pick`)은 순수 함수라 라이브 키 없이 테스트된다. 신호 추출만 ffmpeg 의존
  이고 `render_qa.probe_signals` 와 같은 관례를 따른다(실패 항목은 보수적 기본값).
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from . import config
from .util import log


def probe_motion(mp4_path: str, clip_sec: float) -> dict[str, Any]:
    """클립에서 움직임 신호를 뽑는다. 실패하면 "모른다"를 남긴다(0 으로 채우지 않는다).

    ★ 판정 불가와 나쁨을 섞지 않는다 — `measured=False` 면 선택 로직이 이 후보를
      벌하지 않고 순서로 결정한다. ffmpeg 이 없다고 1번 후보가 나쁜 것은 아니다.
    """
    out: dict[str, Any] = {"measured": False, "freeze_sec": 0.0, "scene_changes": 0,
                           "world_drift": -1.0, "motion_median": -1.0,
                           "text_burn_in": -1.0,
                           "clip_sec": float(clip_sec or 0)}
    try:
        det = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", mp4_path,
             "-vf", (f"freezedetect=n={config.CANDIDATE_FREEZE_NOISE}:"
                     f"d={config.CANDIDATE_FREEZE_MIN_SEC},"
                     f"scdet=threshold={config.CANDIDATE_SCENE_THRESHOLD}"),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("후보 움직임 신호 추출 실패(순서로 결정): %s", exc)
        return out

    stderr = det.stderr or ""
    # ★★ freeze_duration 만 세면 **끝까지 얼어 있는 클립을 놓친다**(2026-09-03 실측).
    #   freezedetect 는 정지가 **끝날 때** duration 을 찍는다. 클립 끝까지 멈춰 있으면
    #   freeze_start 하나만 나오고 duration 은 영영 안 나온다 — 즉 가장 나쁜 후보가
    #   freeze_sec=0(완벽)으로 채점됐다. 실측: 8초 정지 영상이 0.00s 로 나왔다.
    #   render_qa.probe_signals 도 같은 자리를 같이 고쳤다.
    freeze = 0.0
    starts = [float(m.group(1)) for m in re.finditer(r"freeze_start:\s*([0-9.]+)", stderr)]
    ends = [float(m.group(1)) for m in re.finditer(r"freeze_duration:\s*([0-9.]+)", stderr)]
    freeze += sum(ends)
    if len(starts) > len(ends):            # 짝 없는 start = 클립 끝까지 정지
        freeze += max(0.0, float(clip_sec or 0) - starts[-1])
    out.update(measured=True, freeze_sec=round(freeze, 2),
               scene_changes=len(re.findall(r"lavfi\.scd\.score", stderr)),
               motion_median=motion_median(mp4_path),
               world_drift=world_drift(mp4_path, clip_sec),
               text_burn_in=text_burn_in(mp4_path))
    return out


def motion_median(mp4_path: str) -> float:
    """프레임 간 변화량의 **중앙값**. 높으면 **계속** 움직인다는 뜻이다.

    ★★ 왜 평균이 아니라 중앙값인가(2026-08-31 실측): G4 두 후보의 **평균이 같았다**
      (둘 다 0.0081). 그런데 중앙값은 0.0037 vs 0.0019 로 두 배 차이였다 —
      나쁜 쪽은 대부분 정지해 있다가 몇 번 크게 튄 것이고, 좋은 쪽은 내내 움직였다.
      **평균은 스파이크에 속고 중앙값은 안 속는다.** 눈으로 본 판정과도 중앙값이 맞았다.

    ★ 실패하면 -1(판정 불가). 0(=안 움직였다)과 섞지 않는다.
    """
    try:
        det = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", mp4_path,
             "-vf", "select='gt(scene,0)',metadata=print:key=lavfi.scene_score",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=240,
        )
    except (subprocess.SubprocessError, OSError):
        return -1.0
    vals = sorted(float(m) for m in
                  re.findall(r"lavfi\.scene_score=([0-9.]+)", det.stderr or ""))
    if not vals:
        return -1.0
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return round(med, 5)


def world_drift(mp4_path: str, clip_sec: float) -> float:
    """첫 프레임과 끝 프레임의 밝기 분포 차이(0~1). 높으면 **세계를 떠났다**는 신호.

    ★ 왜 필요한가(2026-08-31 G2·G4 실측): 네 클립 **전부** 달 표면 실사로 시작해
      "받침대 위 분화구 다이어그램"으로 끝났다. I2V 는 시작 프레임의 세계를
      **이어가야** 하는데 마지막 3초가 다른 장면이었다.
      기존 점수(정지·장면전환)는 그것을 전혀 못 본다 — G4 에서 점수가 옳은 후보를
      골랐지만 **그 이유로 고른 것이 아니었다**(우연히 일치했다).

    ★★ **점수에 넣지 않는다.** 충돌 → 분화구처럼 세계가 크게 변하는 것이 정상인 컷도
      있어서, 지금 벌점으로 만들면 옳게 한 컷을 벌하는 게이트가 된다(리뷰 §17 이
      경고한 그것). 지금은 **운영자에게 보이는 신호**로만 둔다 — 표본이 쌓이면
      기준을 정하고 그때 점수·게이트로 승격한다.
    """
    try:
        det = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", mp4_path,
             "-vf", (f"select='lte(t,0.4)+gte(t,{max(0.0, float(clip_sec) - 0.4):.2f})',"
                     "signalstats,metadata=print:key=lavfi.signalstats.YAVG"),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return -1.0                      # 판정 불가 — 0(=차이 없음)과 섞지 않는다
    vals = [float(m) for m in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", det.stderr or "")]
    if len(vals) < 2:
        return -1.0
    head = sum(vals[:max(1, len(vals) // 4)]) / max(1, len(vals) // 4)
    tail = sum(vals[-max(1, len(vals) // 4):]) / max(1, len(vals) // 4)
    return round(min(1.0, abs(tail - head) / 255.0 * 4), 3)


# ★ 실측 4클립에서 방향이 반대로 나왔다(아래 docstring). True 로 바꾸려면
#   tests/test_clip_candidates.py 의 `test_text_burn_in_orders_the_known_clips` 가
#   xfail 없이 통과해야 한다 — 그 테스트가 곧 검증 표본이다.
TEXT_BURN_IN_VALIDATED: bool = False


def text_burn_in(mp4_path: str) -> float:
    """화면에 **박힌 글자**의 양(정지 고주파 밀도, 0~255). 높으면 글자·도표가 박혔다.

    ★ 왜 필요한가(2026-08-31 G4 실측): 같은 지시로 두 번 뽑았는데 2번째 마지막 화면이
      **지어낸 글자로 뒤덮였다**(AGENT ZERO·LOYAL DEPLOY). 1번째는 거의 없었다.
      그런데 그 요인이 **점수에 아예 들어 있지 않았다** — 중앙 움직임이 우연히 같은
      답을 냈을 뿐이다. "지표가 옳은 답을 우연히 맞히는 것"을 경계하라는 그 사례다.

    ★ 어떻게 재는가: 글자는 **움직이지 않고 선명하다**. 그래서 먼저 시간 평균(tmix)으로
      2초 창을 뭉갠다 — 카메라가 움직이는 배경은 흐려지고 고정 오버레이만 선명하게
      남는다. 그 위에 edgedetect 를 태워 남은 윤곽의 평균 밝기를 잰다.
      (OCR 을 쓰지 않는다: 글자를 읽을 필요가 없고, 지어낸 글자는 대개 판독 불가다.)

    ★★ **점수에 넣지 않는다.** 정상적으로 글자가 많은 화면(코드 시각화·수치 보드)도
      있어서 지금 벌점으로 만들면 옳게 한 컷을 벌하는 게이트가 된다(리뷰 §17).
      world_drift 와 같은 자리다 — 기록만 하고, 표본이 쌓이면 문턱을 정한다.

    ★ 정규화하지 않고 **원시 값**을 돌려준다. 0~1 로 접으려면 배율이 필요한데 그 배율은
      지금 실측 근거가 없다. 지어낸 배율은 나중에 문턱처럼 취급되어 조용히 굳는다.
      실패하면 -1(판정 불가) — 0(=글자 없음)과 섞지 않는다.

    ★★★ **검증 결과: 이 값은 자기가 만들어진 바로 그 사례에서 방향이 반대다**
      (2026-09-02, docs/실측_품질/번인지표_검증_2026-09-02.md). 실측 4클립:
        G4 take1(깨끗)      4.864      G2 A_4s(굵은 도표선)  5.104
        G4 take2(글자 범벅)  3.703      G2 B_8s(작은 글자)    3.407
      마지막 3초만 잘라 봐도 같다(8.624 vs 5.823). 재는 것이 "글자"가 아니라
      **윤곽의 밝기**라서 — take1 의 굵고 흰 괄호 몇 개가 take2 의 흐릿하고 가는
      글자·지시선 여럿을 이긴다. 대체 체인 17종(저문턱 edge·이진 밀도·sobel·
      top-hat·밝은 픽셀 면적)도 전부 탈락했다: 실측 순서를 맞힌 것은 배경 밝기나
      질감(합성 흰 배경 255 / 노이즈 243)을 재고 있었다. **ffmpeg 픽셀 통계로는
      글자를 달 표면 돌 알갱이와 못 가른다.**
      ▸ 그래서 이 값으로 **문턱을 정하지 마라.** TEXT_BURN_IN_VALIDATED 가 False 인
        동안 calibrate 가 이 열을 다루면 안 된다. 기록은 유지한다(표본 축적).
      ▸ 실제로 글자를 가르는 것은 review_tie 의 시각 판정관(동점일 때)뿐이다.
      ▸ 고치려면 픽셀 통계가 아니라 **텍스트 영역 검출기**(EAST/CRAFT/PaddleOCR-det —
        판독이 아니라 상자 개수·면적)가 필요하다. 의존성 결정은 운영자 몫이다.
        검증 표본은 위 4클립이 그대로 쓰인다(무료).
    """
    try:
        det = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", mp4_path,
             "-vf", (f"fps={config.CANDIDATE_TEXT_TMIX_FPS},"
                     f"tmix=frames={config.CANDIDATE_TEXT_TMIX_FRAMES},"
                     "edgedetect,signalstats,"
                     "metadata=print:key=lavfi.signalstats.YAVG"),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
    except (subprocess.SubprocessError, OSError):
        return -1.0
    vals = [float(m) for m in
            re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", det.stderr or "")]
    if not vals:
        return -1.0                      # 필터가 안 돌았다 — 0 으로 채우지 않는다
    return round(sum(vals) / len(vals), 3)


def freeze_ratio(signals: dict[str, Any]) -> float:
    """얼어 있는 시간 비율. 이것이 높으면 8초를 준 의미가 없다."""
    clip = float(signals.get("clip_sec") or 0)
    if clip <= 0:
        return 0.0
    return round(min(1.0, float(signals.get("freeze_sec") or 0) / clip), 3)


def score(signals: dict[str, Any], *, min_beats: int = 0) -> dict[str, Any]:
    """후보 하나의 점수. 높을수록 좋다. 순수 함수.

    ★★ 2026-08-31 **실측 4클립으로 재설계**했다. 종전 점수는

          (1 - 정지비율) × 0.7  +  min(전환수, 비트)/비트 × 0.3

      였는데, 실측에서 **정지 비율이 네 클립 전부 0.00** 이었다. 즉 점수의 70% 가
      한 번도 갈리지 않았고 실제 판정은 전환 수 하나가 했다.
      G4 에서 "옳은 답을 우연히 맞혔다"의 정체가 그것이다.

    ★★ 그리고 **전환 수를 상으로 주는 것이 위험하다.** 좋은 invest 클립은 컷이 아니라
      카메라가 움직이는 **한 테이크**다. 컷에 점수를 주면 우리가 실제로 관측한
      **세계 이탈**(달 표면 → 다이어그램)에 상을 주게 된다. 그래서 전환은 보고만 한다.

    지금 점수 = 중앙 움직임(지속성) × 0.8 + 정지 가드 × 0.2.
    정지는 실측에서 안 갈렸지만 Manim·홀드 경로에서는 실재하는 실패라 0 으로 두지 않는다.
    """
    if not signals.get("measured"):
        return {"score": 0.0, "measured": False, "freeze_ratio": 0.0,
                "scene_changes": 0, "motion_score": 0.0}
    fr = freeze_ratio(signals)
    med = float(signals.get("motion_median") or -1.0)
    if med < 0:
        # 움직임을 못 쟀다 — 정지 가드만으로 판정하고 그 사실을 남긴다.
        return {"score": round((1.0 - fr) * config.CANDIDATE_W_FREEZE, 4),
                "measured": True, "freeze_ratio": fr,
                "scene_changes": int(signals.get("scene_changes") or 0),
                "motion_score": -1.0}
    motion = min(1.0, med / max(1e-9, config.CANDIDATE_MOTION_MEDIAN_TARGET))
    return {
        "score": round(motion * config.CANDIDATE_W_MOTION
                       + (1.0 - fr) * config.CANDIDATE_W_FREEZE, 4),
        "measured": True, "freeze_ratio": fr,
        "scene_changes": int(signals.get("scene_changes") or 0),
        "motion_score": round(motion, 4),
    }


_REVIEW_SYSTEM = (
    "너는 숏폼 영상 후보 검수자다. 같은 지시로 뽑은 두 후보의 마지막 프레임을 본다. "
    "첫 번째가 1번 후보, 두 번째가 2번 후보다."
)
_REVIEW_USER = (
    "어느 쪽이 더 나은 후보인가? 아래만 본다.\n"
    "- 화면에 **지어낸 글자·라벨·수치**가 박혔는가(가장 나쁘다 — 우리는 글자를 코드로 그린다)\n"
    "- 시작한 세계를 유지하는가(실사로 시작해 도표로 끝나지 않았는가)\n"
    "★ 예쁨·색감으로 고르지 마라. 위 둘만 본다.\n"
    'JSON 만 출력한다: {"better": 1|2, "reason": "한 문장"}'
)


def last_frame(mp4_path: str, out_png: str) -> bool:
    """클립의 마지막 프레임을 뽑는다. 실패하면 False.

    ★ 왜 마지막인가: 2026-08-31 G4 실측에서 글자 범벅이 **마지막 화면**에 나타났다.
      I2V 는 시작 프레임을 받아 이어 그리므로 앞은 대개 멀쩡하고 뒤가 무너진다.
    """
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-y", "-sseof", "-0.5",
             "-i", mp4_path, "-frames:v", "1", out_png],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def review_tie(decision: dict[str, Any], frame_paths: list[str],
               asker=None) -> dict[str, Any]:
    """코드가 못 가른 동점만 **그림을 보고** 가른다. 순수하지 않은 부분은 asker 뿐이다.

    ★★ 왜 동점일 때만인가: 이 저장소는 **코드 판정을 먼저 둔다.** 모델에게 매번 물으면
      그 답이 새로운 자기보고가 되고, 왜 그 후보를 골랐는지 코드가 설명하지 못한다.
      코드가 유의미한 차이(CANDIDATE_MEANINGFUL_GAP)를 못 찾은 경우에만 눈을 빌린다.
    ★ 무엇을 묻는가는 좁게 고정한다 — 글자 번인과 세계 유지, 둘뿐이다. "어느 쪽이 좋냐"고
      열어 두면 예쁨으로 고르고, 그러면 우리가 아는 실패(글자 범벅)를 놓친다.
    ★ 판정 불가면 코드 결정을 그대로 둔다. 못 물었다고 후보 순서를 흔들지 않는다.
    """
    scores = decision.get("scores") or []
    if len(scores) < 2 or len(frame_paths) < 2:
        return decision
    vals = sorted((float(x.get("score") or 0.0) for x in scores), reverse=True)
    if vals[0] - vals[1] >= config.CANDIDATE_MEANINGFUL_GAP:
        return decision                       # 코드가 이미 갈랐다 — 물을 이유가 없다
    ask = asker
    if ask is None:
        from . import continuity_qa
        if not continuity_qa.enabled():
            return decision
        ask = continuity_qa.ask
    data = ask(_REVIEW_SYSTEM, _REVIEW_USER, frame_paths[:2]) or {}
    better = data.get("better")
    if better not in (1, 2):
        return decision
    out = dict(decision)
    out["index"] = int(better) - 1
    out["reason"] = "visual_review"
    out["review_reason"] = str(data.get("reason") or "")
    return out


def pick(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """후보 점수 목록 → 채택 결정. 순수 함수. 반환: {index, reason, scores}.

    ★ 아무것도 못 쟀으면 **1번을 쓴다**(판정 불가 ≠ 실패). 동점도 1번 — 순서가
      결정론적 tie-break 이라 같은 입력에서 같은 답이 나온다.
    """
    if not scores:
        return {"index": 0, "reason": "no_candidates", "scores": []}
    if not any(s.get("measured") for s in scores):
        return {"index": 0, "reason": "not_measured", "scores": scores}
    best = max(range(len(scores)), key=lambda i: scores[i].get("score", 0.0))
    if best == 0:
        return {"index": 0, "reason": "first_is_best", "scores": scores}
    return {"index": best, "reason": "sustained_motion", "scores": scores}
