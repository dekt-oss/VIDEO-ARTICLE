"""S2 — 승인된 연속 장면 시험: 1번 슬롯 + 훅 슬롯(후보 2)만 산다. 기획 v2 §3-10 S2 · §10-2. 상한 $2.60.

    python -m scripts.explainer_s2                                  # 0원 dry-run: 지시서(기본 S0.5 dry-run 산출)로 S2 범위·금액·결재 문장
    python -m scripts.explainer_s2 --directive <경로.json>          # 다른 지시서 파일로 같은 계산
    python -m scripts.explainer_s2 preflight                        # 무료 GET 한 번(모델 조회) — 생성 호출이 아니다. GEMINI_API_KEY 필요
    python -m scripts.explainer_s2 status --plan-id <uuid>          # 읽기: 편 상태·슬롯·후보·결재
    python -m scripts.explainer_s2 plan --plan-id <uuid> --yes --approve "…"    # 운영 0원: 지시서 작업 요청 → 워커 1회(TTS 실측 → 지시서·금액)
    python -m scripts.explainer_s2 buy  --plan-id <uuid> --yes --approve "…"    # 운영(돈): 결재 등록(상한 $2.60) → 구매 요청(through_n=훅) → 워커 1회

구매(buy)는 그 위에 운영자 PC 에서 이 한 회만 DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1 을 켜야 움직인다. 코드가 켜지 않는다.
한 회가 사는 것: 1번 시작 그림·클립 1개 + 훅 슬롯 시작 그림·클립 2개(후보). `through_n` 뒤 슬롯은 건드리지 않는다. 그 다음은 대시보드에서 후보 판정·선택이다(사람).
운영 DB 에 0067(설명형 큐)이 없으면 쓰기 전에 멈춘다(2026-11-02 조회: 미적용).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from engine import config
from scripts import explainer_stages as st

STAGE = "S2 연속 장면 시험"
DEFAULT_DIRECTIVE = st.ROOT / "docs" / f"preview-{st.preview_date()}" / "explainer-s05" / "directive.json"


def load_directive(path: Optional[str]) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_DIRECTIVE
    if not p.exists():
        raise st.StageStop(f"지시서 파일이 없습니다: {p} — 먼저 `python -m scripts.explainer_s05` 를 돌리거나 --directive 로 지정하세요")
    return json.loads(p.read_text(encoding="utf-8"))


def describe(directive: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    scope = st.s2_scope(directive)
    table = st.format_table(scope["rows"], title=f"[{STAGE}] 사는 슬롯 1~{scope['through_n']} (훅 = {directive['hook_scene']}번, 후보 {config.DRINKS_EXPLAINER_HOOK_CANDIDATES})")
    sentence = st.approval_sentence(STAGE, purpose=f"공급자 {directive['provider']} {directive.get('resolution', '720p')} 연속 장면 시험", cap_usd=scope["cap_usd"], estimate_usd=scope["estimate_usd"],
                                    scope=f"슬롯 {scope['slots']} 시작 그림 {len(scope['rows'])}장 + 클립 {sum(r['candidates'] for r in scope['rows'])}개, through_n={scope['through_n']}")
    return scope, table, sentence


def dry_run(args: argparse.Namespace) -> int:
    d = load_directive(args.directive)
    scope, table, sentence = describe(d)
    out = st.preview_dir("explainer-s2")
    print(table)
    print(sentence)
    print(f"재시도 예비(가장 긴 클립 1회) ${scope['retry_reserve_usd']:.3f} — 상한 안 남는 폭 ${scope['headroom_usd']:.3f} ({'덮는다' if scope['retry_covered'] else '못 덮는다: 재시도는 새 결재'})")
    if not scope["fits"]:
        print(f"★ 예상 ${scope['estimate_usd']:.2f} 이 상한 ${scope['cap_usd']:.2f} 을 넘는다 — 이 지시서로는 S2 를 사지 않는다(대본을 줄이거나 결재를 다시 받는다)")
    report = {"stage": "s2", "dry_run": True, "money_spent_usd": 0.0, "provider_calls": 0, "directive_source": str(args.directive or DEFAULT_DIRECTIVE), "hook_scene": d["hook_scene"],
              "provider": d["provider"], "resolution": d.get("resolution"), "price_as_of": d.get("price_as_of"), "scope": {k: v for k, v in scope.items() if k != "rows"}, "rows": scope["rows"],
              "approval_sentence": sentence, "unverified": d.get("unverified"), "env": st.env_summary(),
              "doc_reference": {"s2_estimate_usd": 2.2, "s2_cap_usd": 2.6, "where": "기획 v2 §3-10"}}
    st.dump(out / "report.json", report)
    (out / "directive_table.txt").write_text(table + "\n" + sentence + "\n", encoding="utf-8")
    print(f"결과물: {out}")
    return 0 if scope["fits"] else 1


def preflight(args: argparse.Namespace) -> int:
    """무료 조회 한 번. 생성이 아니다. 결과(모델 이름·메서드)를 기록한다 — supportedGenerationMethods 이름은 [미검증] 이라 기록만."""
    from engine.providers import video as pv

    if not config.SECRETS.gemini_api_key:
        raise st.StageStop("GEMINI_API_KEY 가 없어 모델 조회를 보내지 않습니다")
    pre = pv.omni_preflight()
    rec = {"ok": pre.ok, "model": pre.model, "reason": pre.reason, "display_name": pre.display_name, "version": pre.version, "methods": list(pre.methods), "verified_by_docs": list(pv.OMNI_VERIFIED_BY_DOCS), "unverified": list(pv.OMNI_UNVERIFIED)}
    st.dump(st.preview_dir("explainer-s2") / "preflight.json", rec)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if pre.ok else 1


def _rpc_and_storage():
    st.require_db_env()
    from engine import drinks_produce as dp
    from engine.drinks_collect import supabase_rpc

    rpc = supabase_rpc()
    st.require_migration(rpc, "drinks_explainer_status", {"plan_revision_id": "00000000-0000-4000-8000-000000000000"})
    return rpc, dp


def status(args: argparse.Namespace) -> int:
    rpc, _dp = _rpc_and_storage()
    s = rpc("drinks_explainer_status", {"plan_revision_id": args.plan_id})
    ep = s.get("episode") or {}
    print(f"상태 {ep.get('state')} · 공급자 {ep.get('provider')} · through_n {ep.get('buy_through_n')} · 마지막 {ep.get('last_code')}: {ep.get('last_message')}")
    for sl in s.get("slots") or []:
        print(f"  슬롯 {sl['n']} {sl['status']} 후보 {[(c['k'], c['status'], c.get('auto_verdict'), c.get('human_verdict')) for c in sl.get('candidates') or []]}")
    for a in s.get("approvals") or []:
        print(f"  결재 {a.get('stage')} 상한 ${float(a.get('cap_usd') or 0):.2f} 사용 ${float(a.get('spent_usd') or 0):.3f} 가잡기 ${float(a.get('held_usd') or 0):.3f} {a.get('status')}")
    st.dump(st.preview_dir("explainer-s2") / "status.json", s)
    return 0


def plan(args: argparse.Namespace) -> int:
    """지시서 작업(0원·edge TTS). 운영 DB 에 작업을 넣으므로 --yes 를 받는다."""
    print(st.approval_sentence(STAGE, purpose="장면별 지시서 만들기(0원, TTS 실측)", cap_usd=0.0, estimate_usd=0.0, scope="explainer_plan 작업 1건 + 워커 1회"))
    st.require_yes(args, "운영 DB 쓰기")
    rpc, dp = _rpc_and_storage()
    rpc("drinks_explainer_request_plan", {"plan_revision_id": args.plan_id})
    res = dp.run_queue(rpc, dp.Storage(), worker_id="s2-plan", tts="edge", max_jobs=1)
    st.dump(st.preview_dir("explainer-s2") / "live-plan.json", res)
    print(json.dumps(res, ensure_ascii=False, default=str)[:2000])
    return status(args)


def buy(args: argparse.Namespace) -> int:
    rpc, dp = _rpc_and_storage()
    s = rpc("drinks_explainer_status", {"plan_revision_id": args.plan_id})
    ep = s.get("episode") or {}
    d = ep.get("directive") or {}
    if not d.get("slots"):
        raise st.StageStop("이 편에 장면별 지시서가 없습니다 — 먼저 `plan` 을 돌리세요")
    scope, table, sentence = describe(d)
    print(table)
    print(sentence)
    if not scope["fits"]:
        raise st.StageStop(f"예상 ${scope['estimate_usd']:.2f} 이 상한 ${scope['cap_usd']:.2f} 을 넘습니다 — 사지 않습니다")
    st.require_yes(args, "영상·그림 구매")
    st.require_provider_switch()
    from engine.providers import video as pv

    pre = pv.omni_preflight()
    if not pre.ok:
        raise st.StageStop(f"공급자 사전 검증 실패(무료 조회) — 보내지 않았습니다: {pre.reason}")
    open_ = [a for a in s.get("approvals") or [] if a.get("status") == "open" and not a.get("expired")]
    if open_:
        approval_id = open_[0]["approval_id"] if "approval_id" in open_[0] else open_[0].get("id")
        print(f"열린 결재를 다시 씁니다: {approval_id}")
    else:
        a = rpc("drinks_open_spend_approval", {"plan_revision_id": args.plan_id, "stage": STAGE, "purpose": f"{STAGE} — 시작 그림·클립(슬롯 {scope['slots']})", "cap_usd": scope["cap_usd"],
                                                 "allowed_kinds": ["image", "video"], "approved_by": "operator", "approver_words": args.approve, "order_hash": ep.get("order_hash")})
        approval_id = a["approval_id"]
        print(f"결재 등록: {approval_id} 상한 ${scope['cap_usd']:.2f}")
    rpc("drinks_explainer_request_buy", {"plan_revision_id": args.plan_id, "spend_approval_id": approval_id, "through_n": scope["through_n"]})
    res = dp.run_queue(rpc, dp.Storage(), worker_id="s2-buy", tts="edge", max_jobs=1)
    st.dump(st.preview_dir("explainer-s2") / "live-buy.json", {"approval_id": approval_id, "scope": {k: v for k, v in scope.items() if k != "rows"}, "worker": res})
    print(json.dumps(res, ensure_ascii=False, default=str)[:2000])
    print("다음(사람): 대시보드 제작 화면에서 후보를 보고 판정·선택한다. 첫 프레임 고정·실측 길이·청구 토큰은 status 로 본다.")
    return status(args)


def main(argv: Optional[list[str]] = None) -> int:
    st.utf8_console()
    ap = argparse.ArgumentParser(description="S2 연속 장면 시험 — 기본 0원 dry-run")
    ap.add_argument("step", nargs="?", choices=("dry-run", "preflight", "status", "plan", "buy"), default="dry-run")
    ap.add_argument("--directive", default=None, help="dry-run 에 쓸 지시서 json(기본 S0.5 dry-run 산출)")
    ap.add_argument("--plan-id", default=None, help="운영 제작안(drink_plan_revisions.id)")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--approve", default="", help="결재 문장(운영자가 승인한 말 그대로)")
    args = ap.parse_args(argv)
    try:
        if args.step == "dry-run":
            return dry_run(args)
        if args.step == "preflight":
            return preflight(args)
        if not args.plan_id:
            raise st.StageStop("--plan-id 가 필요합니다")
        return {"status": status, "plan": plan, "buy": buy}[args.step](args)
    except st.StageStop as stop:
        print(f"멈춤(돈 안 씀): {stop}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
