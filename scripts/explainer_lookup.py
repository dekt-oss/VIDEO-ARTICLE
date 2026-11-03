"""설명형 '결과 모름' 시도를 공급자에 물어본다. 운영자가 청구/없던 일로 닫기 전에 보는 자료다. docs/deviation-drinks-explainer-stage2.md

    python -m scripts.explainer_lookup --plan-id <uuid>                      # 읽기만: 결과 모름 시도와 요청 ID 유무. 공급자 호출 0
    python -m scripts.explainer_lookup --plan-id <uuid> --attempt <id> --yes # GET 한 번(생성 호출이 아니다). 운영자 PC 에서 스위치를 켠 한 회만

★ DB 에 아무것도 쓰지 않는다. 닫기는 대시보드에서 운영자가 한다(0067 이 worker 닫기를 거부한다). 받은 영상도 저장하지 않는다.
★ 조회가 공짜인지는 문서에 없다(미검증). 재시도하지 않고 한 번만 묻는다.
★ 응답이 오기 전에 끊긴 시도는 요청 ID 가 없어 물어볼 수 없다. 그때는 청구서로 대조한다.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Optional

from engine.drinks_paid import omni_tokens_usd
from engine.providers import video as pv
from scripts import explainer_stages as st


def unknown_attempts(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for slot in status.get("slots") or [] for c in slot.get("candidates") or [] for a in c.get("attempts") or [] if a.get("state") == "unknown_billed"]


def lookup_one(row: dict[str, Any], fetch: Callable[..., pv.ExplainerParsed]) -> dict[str, Any]:
    """결과를 판정만 한다. no_id·not_retrievable·unreadable 은 '청구 없음'이 아니다 — 모른다는 뜻이다."""
    out: dict[str, Any] = {"attempt_id": row["attempt_id"], "request_id": row.get("provider_request_id"), "est_usd": row.get("est_usd")}
    if not row.get("provider_request_id"):
        return {**out, "outcome": "no_id", "advice": "요청 ID 가 없어 물어볼 수 없습니다. 공급자 청구 내역으로 대조한 뒤 닫으세요"}
    try:
        parsed = fetch(row["provider_request_id"], approval_id=row.get("approval_id") or "")
    except pv.ExplainerSendRefused:
        raise
    except pv.ExplainerNotSent as exc:
        return {**out, "outcome": "not_retrievable", "advice": f"공급자가 조회를 거절했습니다({str(exc)[:120]}). 청구 내역으로 대조하세요"}
    except pv.ExplainerProviderError as exc:
        return {**out, "outcome": "unreadable", "advice": f"응답을 해석하지 못했습니다({str(exc)[:120]}). 청구 내역으로 대조하세요"}
    if not parsed.done:
        return {**out, "outcome": "in_progress", "advice": "아직 진행 중입니다. 지금 닫지 말고 나중에 다시 물어보세요"}
    return {**out, "outcome": "completed", "billed_units": parsed.billed_units, "usd": None if parsed.billed_units is None else omni_tokens_usd(parsed.billed_units), "video_bytes": len(parsed.video_bytes),
            "advice": "공급자가 완료했습니다. 청구된 것으로 닫는 쪽이 맞습니다(금액은 토큰 계산값, 청구서 대조 전)"}


def main(argv: Optional[list[str]] = None) -> int:
    st.utf8_console()
    ap = argparse.ArgumentParser(description="설명형 결과 모름 시도 조회 — 기본은 읽기만")
    ap.add_argument("--plan-id", required=True, help="운영 제작안(drink_plan_revisions.id)")
    ap.add_argument("--attempt", default=None, help="물어볼 시도 id")
    ap.add_argument("--yes", action="store_true", help="공급자에 GET 한 번")
    args = ap.parse_args(argv)

    from engine.drinks_collect import supabase_rpc

    rows = unknown_attempts(supabase_rpc()("drinks_explainer_status", {"plan_revision_id": args.plan_id}))
    if not args.attempt or not args.yes:
        for r in rows:
            print(f"{r['attempt_id']}  요청 ID {'있음' if r.get('provider_request_id') else '없음'}  가잡힌 금액 ${float(r.get('est_usd') or 0):.3f}")
        print(f"결과 모름 {len(rows)}건. 공급자 호출 0회." + (" --attempt <id> --yes 로 한 건을 물어볼 수 있습니다." if rows else ""))
        return 0
    row = next((r for r in rows if r["attempt_id"] == args.attempt), None)
    if row is None:
        print("그 시도는 결과 모름 상태가 아닙니다")
        return 2
    try:
        res = lookup_one(row, pv.fetch_omni_interaction)
    except pv.ExplainerSendRefused as stop:
        print(f"멈춤(호출 안 함): {stop}")
        return 2
    for k, v in res.items():
        print(f"{k}: {v}")
    print("DB 에 쓰지 않았습니다. 닫기는 대시보드 제작 화면에서 합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
