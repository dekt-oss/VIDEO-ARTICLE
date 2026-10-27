"""주류 공장 ④ 성과 수집(인스타 게시물 지표 스냅샷). 2026-10-27. docs/deviation-drinks-publish-loop.md

    python -m engine.drinks_metrics           # 칸(24h·72h·7d)이 열린 게시물만 지표를 읽어 스냅샷을 남긴다

규칙(명세 §9.4):
  · 칸은 DB 가 게시 시각에서 정한다. 창(예: 72h 는 72~96시간)을 놓치면 그 칸은 비어 있다 — 나중에 추정해 채우지 않는다.
  · **받은 지표만 키로 저장한다.** 공급자가 안 준 지표는 0 이 아니라 unavailable 에 이유와 함께 남는다.
  · 읽기 전용이다. 게시물을 고치거나 지우지 않는다. 하루 한 번이면 충분하다(쿼터·비용).
"""

from __future__ import annotations

import argparse
from typing import Any, Callable, Optional

from .drinks_collect import supabase_rpc
from .providers.instagram import METRIC_SCHEMA_VERSION, AuthError, PublishError, provider_for
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]


def collect(rpc: Rpc, providers: Callable[[dict[str, Any]], Any], *, limit: int = 50) -> list[dict[str, Any]]:
    out = []
    for d in rpc("drinks_metrics_due", {"limit": limit}) or []:
        base = {"request_id": d["request_id"], "external_post_id": d["external_post_id"],
                "metric_schema_version": METRIC_SCHEMA_VERSION}
        try:
            values, unavailable = providers(d["account"]).insights(d["account"], d["external_post_id"], d["post_type"])
            status = "ok" if not unavailable else ("partial" if values else "failed")
            res = rpc("drinks_record_metrics", {**base, "values": values, "unavailable": unavailable, "fetch_status": status})
        except PublishError as exc:
            if isinstance(exc, AuthError):
                rpc("drinks_account_verified", {"account_id": d["account"]["account_id"], "ok": False, "error_code": exc.code})
            res = rpc("drinks_record_metrics", {**base, "values": {}, "unavailable": {}, "fetch_status": "failed",
                                                "error_code": exc.code})
        log.info("drinks: 성과 %s %s → %s", d["request_id"], res.get("bucket"), "중복" if res.get("duplicate") else "기록")
        out.append({"request_id": d["request_id"], **res})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="주류 공장 인스타 성과 수집")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args(argv)
    collect(supabase_rpc(), provider_for, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
