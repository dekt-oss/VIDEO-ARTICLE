"""클립 지표 교정 — **쌓인 표본에서 문턱을 뽑는다** (2026-08-31).

무엇을 푸는가: `world_drift` 문턱을 못 정하고 있다. 손으로 뽑은 표본 4개가 **전부
나빴기** 때문이다(0.80~1.00) — 좋은 값이 하나도 없으면 "얼마부터 나쁜가"의 경계를
그을 수 없다. 그렇다고 운영자가 매번 샘플을 뽑아 줄 수는 없다.

그래서 렌더가 컷마다 지표를 재서 `render_jobs.qa["clip_metrics"]` 에 남기고
(engine/render.py — 기록 전용, 아무것도 차단하지 않는다), 이 도구가 그 **쌓인 표본**
에서 문턱 후보를 계산한다.

★★ 문턱을 **자동으로 적용하지 않는다.** 숫자를 보여 주고 끝이다.
  기준을 잘못 그으면 정상 컷을 벌하고(리뷰 §17), 그러면 운영자가 게이트를 무시하기
  시작한다 — 이 저장소가 반복해서 경계하는 실패다. 적용은 사람이 config 를 고쳐서 한다.

★ 표본이 적으면 **적다고 말하고 멈춘다.** 4개로 문턱을 정하면 그건 교정이 아니라 추측이다.

사용:
    python -m scripts.calibrate_clip_metrics            # DB 에 쌓인 표본으로
    python -m scripts.calibrate_clip_metrics --files    # 로컬 실측 파일로(오프라인)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config  # noqa: E402
from engine.util import log  # noqa: E402

# 문턱을 논하려면 이만큼은 있어야 한다. 그 아래면 "표본 부족"이라고만 말한다.
MIN_SAMPLES: int = 20


def _from_db(limit: int = 500) -> list[dict]:
    """렌더 잡의 qa 에서 clip_metrics 를 모은다."""
    from engine import db
    rows: list[dict] = []
    try:
        res = (db.client().table("render_jobs").select("id,qa")
               .order("created_at", desc=True).limit(limit).execute())
    except Exception as exc:  # noqa: BLE001 — 조회 실패는 도구 실패지 파이프라인 실패가 아니다
        log.warning("render_jobs 조회 실패: %s", exc)
        return rows
    for job in res.data or []:
        for m in ((job.get("qa") or {}).get("clip_metrics") or []):
            if m.get("measured"):
                rows.append({**m, "job_id": job.get("id")})
    return rows


def _from_files() -> list[dict]:
    """로컬 실측 파일(docs/실측_품질/*/입력/*.mp4)로. 오프라인 확인용."""
    from engine import clip_candidates as cc
    from scripts.web_order import _ensure_ffmpeg, _mp4_duration
    _ensure_ffmpeg()
    rows: list[dict] = []
    for p in sorted(pathlib.Path("docs/실측_품질").glob("*/입력/*.mp4")):
        sec = _mp4_duration(str(p))
        sig = cc.probe_motion(str(p), sec)
        if sig.get("measured"):
            rows.append({**sig, "source": str(p)})
    return rows


def _report(name: str, vals: list[float], *, higher_is_better: bool) -> None:
    if not vals:
        print(f"  {name:<16} 표본 없음")
        return
    vals = sorted(vals)
    q = statistics.quantiles(vals, n=10) if len(vals) >= 10 else None
    print(f"  {name:<16} n={len(vals):<4} 최소 {vals[0]:.5f}  중앙 "
          f"{statistics.median(vals):.5f}  최대 {vals[-1]:.5f}")
    if q:
        # 문턱 후보: 나쁜 쪽 10% 를 자르는 자리. **제안일 뿐 적용하지 않는다.**
        edge = q[0] if higher_is_better else q[-1]
        print(f"  {'':<16} → 문턱 후보(하위/상위 10%): {edge:.5f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", action="store_true", help="DB 대신 로컬 파일로 계산")
    a = ap.parse_args()

    rows = _from_files() if a.files else _from_db()
    print(f"\n=== 클립 지표 교정 (표본 {len(rows)}개)\n")
    if not rows:
        print("  표본이 없다. 렌더가 돌면 qa['clip_metrics'] 에 쌓인다.")
        return

    _report("움직임(중앙)", [float(r["motion_median"]) for r in rows
                             if float(r.get("motion_median", -1)) >= 0], higher_is_better=True)
    _report("세계이탈", [float(r["world_drift"]) for r in rows
                        if float(r.get("world_drift", -1)) >= 0], higher_is_better=False)
    _report("정지(초)", [float(r.get("freeze_sec") or 0) for r in rows], higher_is_better=False)

    print(f"\n  현재 설정: 움직임 목표 {config.CANDIDATE_MOTION_MEDIAN_TARGET} · "
          f"세계이탈 알림 {config.WORLD_DRIFT_NOTICE}")
    if len(rows) < MIN_SAMPLES:
        print(f"\n  ★★ 표본이 {len(rows)}개다({MIN_SAMPLES}개 필요). **문턱을 정하지 않는다** —")
        print("     적은 표본으로 기준을 그으면 교정이 아니라 추측이고, 잘못 그으면")
        print("     정상 컷을 벌하는 게이트가 된다.")
        return
    print("\n  ★ 위 '문턱 후보'는 **제안일 뿐 자동 적용되지 않는다.**")
    print("    적용하려면 config 의 상수를 사람이 고친다(근거를 주석에 남길 것).")


if __name__ == "__main__":
    main()
