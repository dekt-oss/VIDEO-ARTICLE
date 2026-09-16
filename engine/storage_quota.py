"""저장소 용량 경고 — 한도에 다가가는 것을 **미리** 알려 준다 (2026-09-02 신설).

왜 생겼나
---------
2026-08-24, Supabase Storage 가 무료 한도 1GB 를 넘겨(1.53GB) **조직 전체가 정지**했다.
대시보드·API 가 전부 402 를 뱉었고 같은 조직의 다른 프로젝트까지 함께 멈췄다.

그 사고 뒤 `engine/storage_gc.py` 가 "쌓이면 지운다"를 맡았다. 하지만 **한도에 다가가는
것을 알려 주는 장치는 없었다** — 정리가 따라잡지 못하면 다음에도 똑같이, 아무 예고 없이
멈춘다. 작업계획서_시각엔진_v3 Phase S 가 지정하고 남아 있던 잔여 작업이 이것이다.

무엇을 하나
-----------
버킷 전체의 파일 크기를 합쳐 한도의 80% 를 넘으면 경고한다. **지우지 않는다** —
지우는 것은 `storage_gc` 의 일이고, 두 장치가 같은 파일을 두고 다투면 안 된다.
경고는 GitHub Actions 주석(`::warning::`)으로도 나가 Actions 탭 요약에 뜬다.

★ 실패해도 잡을 죽이지 않는다. 용량 조회가 안 된다고 수집·채점이 멈추면, 보험이
  본체를 망가뜨리는 셈이다. 못 쟀으면 못 쟀다고 말하고 0 으로 끝낸다.

쓰는 법
-------
    python -m engine.storage_quota        # 경고만 (종료코드 항상 0)
"""

from __future__ import annotations

import sys

from . import config
from .util import log


def usage_of(objects) -> dict[str, int]:
    """오브젝트 목록 → {bytes, files}. 순수 함수."""
    total = sum(int(getattr(o, "size", 0) or 0) for o in objects)
    return {"bytes": total, "files": len(objects)}


def warnings_for(used_bytes: int,
                 limit_bytes: int | None = None,
                 warn_ratio: float | None = None) -> list[str]:
    """한도 대비 사용량 → 경고 문장들. 순수 함수라 키 없이 테스트된다.

    ★ 경계에서 무엇이 나오는지 분명히 한다: 정확히 80.0% 는 **경고한다**(`>=`).
      "아직 안 넘었다"로 읽히는 애매한 경계를 만들면 사고 직전에 조용해진다.
    ★ 한도가 0 이하면 판정하지 않는다 — 설정이 비었을 때 0 으로 나눠 죽지 않게.
    """
    limit = int(limit_bytes if limit_bytes is not None else config.STORAGE_LIMIT_BYTES)
    ratio = float(warn_ratio if warn_ratio is not None else config.STORAGE_WARN_RATIO)
    if limit <= 0:
        return []
    used = max(0, int(used_bytes))
    pct = used / limit
    mb = used / 1024 / 1024
    limit_mb = limit / 1024 / 1024
    if pct >= 1.0:
        return [f"저장소가 한도를 넘었다 — {mb:.0f}MB / {limit_mb:.0f}MB ({pct * 100:.0f}%). "
                f"2026-08-24 처럼 조직 전체가 402 로 멈출 수 있다. "
                f"`python -m engine.storage_gc --apply` 로 회수하라."]
    if pct >= ratio:
        return [f"저장소가 한도의 {pct * 100:.0f}% 다 — {mb:.0f}MB / {limit_mb:.0f}MB. "
                f"`python -m engine.storage_gc` 로 회수 가능량을 먼저 확인하라."]
    return []


def check(supa=None) -> dict[str, object]:
    """실제 버킷을 훑어 사용량과 경고를 돌려준다. 조회 실패는 예외를 내지 않는다."""
    from . import storage_gc
    from .db import client

    try:
        supa = supa or client()
        objects = storage_gc.walk_all(supa)
    except Exception as exc:                      # noqa: BLE001 — 보험이 본체를 죽이지 않는다
        log.warning("저장소 용량을 재지 못했다(건너뛴다): %s", exc)
        return {"measured": False, "bytes": 0, "files": 0, "warnings": []}
    used = usage_of(objects)
    return {"measured": True, **used, "warnings": warnings_for(used["bytes"])}


def main() -> int:
    result = check()
    if not result.get("measured"):
        log.info("저장소 용량: 판정 불가")
        return 0
    mb = int(result["bytes"]) / 1024 / 1024                      # type: ignore[arg-type]
    log.info("저장소 용량: %.0f MB · 파일 %s개", mb, result["files"])
    for w in result["warnings"]:                                 # type: ignore[union-attr]
        log.warning(w)
        print(f"::warning title=저장소 용량::{w}", file=sys.stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
