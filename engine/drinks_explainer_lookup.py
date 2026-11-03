"""설명형 '결과 모름' 시도 조회 — 운영자가 billed/void 로 닫기 전에 공급자에게 결과를 물어본다(2026-11-03).

왜 있나: 영상 구매 호출이 끊기거나 "아직 진행 중"으로 끝나면 시도는 unknown_billed 로 멈춘다(돈이 나갔는지 모름).
지금까지는 운영자가 청구서만 보고 닫았다. 공급자(Omni)는 interaction id 로 결과를 다시 알려 준다
(GET v1beta/interactions/{id}, 조회라 생성비가 들지 않는다[문서, 미검증]). 이 명령이 그 조회를 해서 판정과
권하는 닫기 금액을 보여 준다.

★ 아무것도 쓰지 않는다. 시도를 닫는 것은 여전히 운영자다(/drinks/production 의 [청구된 것으로 닫기]·[없던 일로 닫기]).
★ 받은 영상은 저장하지 않는다. 완성된 영상을 시도에 다시 붙이는 정정(unknown_billed → received)은 아직 없다.
★ 전송 게이트는 구매와 같다 — DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED 와 그 시도의 결재가 있어야 GET 이 나간다.

사용(운영자 PC, .env 에 SUPABASE_*·GEMINI_API_KEY):
    DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1 python -m engine.drinks_explainer_lookup <attempt_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

from . import drinks_paid
from .providers import video as video_provider


@dataclass(frozen=True)
class LookupVerdict:
    attempt_id: str
    verdict: str            # completed | in_progress | provider_failed | no_request_id | not_unknown | lookup_failed
    suggest: str            # billed | wait | check_invoice | none
    message: str
    request_id: str = ""
    billed_units: Optional[float] = None
    suggested_usd: Optional[float] = None


def judge_attempt(attempt: dict[str, Any], fetch: Callable[[str, str], Any]) -> LookupVerdict:
    """시도 행 하나를 판정한다(순수 + 주입된 조회). fetch(interaction_id, approval_id) → ExplainerParsed."""
    aid = str(attempt.get("attempt_id") or "")
    if attempt.get("state") != "unknown_billed":
        return LookupVerdict(aid, "not_unknown", "none", f"결과 모름 시도가 아닙니다(state={attempt.get('state')})")
    if attempt.get("provider") != "omni":
        return LookupVerdict(aid, "lookup_failed", "check_invoice", f"이 공급자({attempt.get('provider')})는 조회를 연결하지 않았습니다 — 청구서로 닫으세요")
    rid = str(attempt.get("provider_request_id") or "")
    if not rid:
        return LookupVerdict(aid, "no_request_id", "check_invoice",
                             "공급자 요청 ID 가 없습니다(응답을 못 받고 끊겼거나 2026-11-03 이전 시도) — 청구서로 닫으세요")
    try:
        parsed = fetch(rid, str(attempt.get("approval_id") or ""))
    except video_provider.ExplainerSendRefused as exc:
        return LookupVerdict(aid, "lookup_failed", "none", f"조회를 보내지 않았습니다: {exc}", request_id=rid)
    except video_provider.ExplainerProviderError as exc:
        # status=failed 등. 실패한 생성이 청구되는지는 문서로 확인하지 못했다 — 없던 일로 단정하지 않는다.
        return LookupVerdict(aid, "provider_failed", "check_invoice", f"공급자가 완성본이 없다고 답했습니다: {str(exc)[:300]} — 청구서로 확인하세요",
                             request_id=rid)
    units = getattr(parsed, "billed_units", None)
    if not getattr(parsed, "done", True):
        return LookupVerdict(aid, "in_progress", "wait", "아직 만드는 중입니다 — 몇 분 뒤 다시 조회하세요", request_id=rid, billed_units=units)
    usd = drinks_paid.omni_usd_from_tokens(units) if units is not None else None
    return LookupVerdict(aid, "completed", "billed",
                         "완성됐습니다 — 청구된 것으로 닫으세요" + (f"(토큰 기준 ${usd:.4f}, 청구서 대조 전)" if usd is not None else "(토큰 수가 없어 금액은 청구서로)"),
                         request_id=rid, billed_units=units, suggested_usd=usd)


def _read_attempt(attempt_id: str) -> Optional[dict[str, Any]]:
    from . import db
    res = (db.client().table("drink_explainer_attempts")
           .select("attempt_id,state,provider,provider_request_id,approval_id")
           .eq("attempt_id", attempt_id).limit(1).execute())
    rows = res.data or []
    return rows[0] if rows else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="설명형 결과 모름 시도 조회(아무것도 쓰지 않는다)")
    ap.add_argument("attempt_id")
    args = ap.parse_args(argv)
    row = _read_attempt(args.attempt_id)
    if row is None:
        print(json.dumps({"attempt_id": args.attempt_id, "verdict": "not_found"}, ensure_ascii=False))
        return 1
    v = judge_attempt(row, lambda rid, ap_id: video_provider.fetch_omni_interaction(rid, approval_id=ap_id))
    print(json.dumps(asdict(v), ensure_ascii=False, indent=2))
    return 0 if v.verdict in ("completed", "in_progress") else 1


if __name__ == "__main__":
    sys.exit(main())
