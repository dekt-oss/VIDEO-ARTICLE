"""CORE 밴드 충전율 분포 측정 (작업지시서 영상엔진품질 v3 §9 · P3-b).

    python3 scripts/measure_core_fill.py                    # Supabase 에서 직접 읽기
    python3 scripts/measure_core_fill.py directives.json   # 미리 뽑아 둔 JSON 으로

무엇을 위한 것인가: Phase 0 이 실측한 결함 ② — CORE 충전율 **0.235** 인데 판정기가
`fail: []` 로 통과시킨다. 이걸 `warn → fail` 로 승격하면 빈 화면이 막히지만, **지금 나가는
화면 상당수가 렌더 실패로 뒤집힐 수 있다.** 그래서 운영자 결정은 "측정 먼저"다.

이 스크립트는 저장된 `report_directives` 를 실제로 그려 충전율 분포를 낸다.
그 숫자를 보고 기준값(현행 0.30 / 지시서 0.70 / 실측 기반)과 승격 시점을 정한다.

★ 유료 API 를 한 번도 부르지 않는다 — 보드는 PIL 로 그린다(TTS·이미지·Veo 경로 미접촉).
★ 판정을 바꾸지 않는다. 읽고 세기만 한다.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import board_render, config, report_db  # noqa: E402

# 컷당 렌더 길이. 짧게 잡아도 충전율은 끝 프레임 기준이라 분포가 안 바뀐다(프레임 수만 준다).
SAMPLE_SEC = 1.0


def _load(path: str | None) -> list[dict]:
    """지시서 목록. 인자로 JSON 을 주면 그걸 쓴다.

    ★ 파일 입력을 둔 이유: 이 저장소의 샌드박스에는 SUPABASE_SERVICE_KEY 가 없어 DB 를
      직접 못 읽는다. 운영자가 MCP·대시보드로 뽑아 준 JSON 으로도 같은 분석이 돌아야
      "측정 먼저" 결정이 환경 때문에 막히지 않는다.
    """
    if path:
        import json

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else data.get("rows") or []
    return report_db.client().table("report_directives").select(
        "id, header, cuts").execute().data or []


def main() -> int:
    rows = _load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"지시서 {len(rows)}건")

    samples: list[tuple[str, int, str, float]] = []   # (directive, cut_no, board, fill)
    skipped = 0
    with tempfile.TemporaryDirectory() as work:
        for row in rows:
            header = row.get("header") or {}
            cuts = row.get("cuts") or []
            for i, cut in enumerate(cuts):
                board = board_render.code_render_board(cut, header)
                if not board:
                    skipped += 1        # 코드 보드가 아닌 컷(생성 이미지/클립) — 대상 아님
                    continue
                try:
                    res = board_render.render_board(
                        cut, header, None, work, i, total_sec=SAMPLE_SEC, lang="ko")
                except Exception as exc:  # noqa: BLE001 — 못 그리는 컷도 사실이다
                    print(f"  ! {row['id'][:8]} 컷{cut.get('cut_no')} {board}: {type(exc).__name__}")
                    skipped += 1
                    continue
                samples.append((row["id"], int(cut.get("cut_no") or i + 1), board,
                                res.core_fill))

    if not samples:
        print("측정 대상 컷이 없다(코드 보드 컷 0). 리포트 지시서가 explainer 인지 확인하라.")
        return 1

    fills = sorted(f for _, _, _, f in samples)
    print(f"\n측정 {len(samples)}컷 / 건너뜀 {skipped}컷")
    print(f"  최소 {fills[0]:.4f}  중앙 {statistics.median(fills):.4f}  최대 {fills[-1]:.4f}")
    print(f"  평균 {statistics.fmean(fills):.4f}")

    print("\n기준값별 미달 컷 수:")
    for thr in (0.20, 0.30, 0.40, 0.50, 0.70):
        n = sum(1 for f in fills if f < thr)
        mark = "  ← 현행" if abs(thr - config.EXPLAINER_CORE_MIN_FILL) < 1e-9 else (
            "  ← 지시서 목표" if thr == 0.70 else "")
        print(f"  < {thr:.2f} : {n:3}/{len(fills)} ({n / len(fills) * 100:5.1f}%){mark}")

    print("\n보드별 중앙값:")
    by_board: dict[str, list[float]] = {}
    for _, _, board, f in samples:
        by_board.setdefault(board, []).append(f)
    for board, vals in sorted(by_board.items(), key=lambda kv: statistics.median(kv[1])):
        print(f"  {board:22} n={len(vals):3}  중앙 {statistics.median(vals):.4f}  "
              f"최소 {min(vals):.4f}  최대 {max(vals):.4f}")

    print("\n가장 빈 컷 10개:")
    for did, cut_no, board, f in sorted(samples, key=lambda s: s[3])[:10]:
        print(f"  {f:.4f}  {board:22} {did[:8]} 컷{cut_no}")

    print("\n★ 이 스크립트는 판정을 바꾸지 않는다. 위 분포로 기준값을 정한 뒤")
    print("  board_layout.py 의 core_underfilled 를 warn → fail 로 옮긴다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
