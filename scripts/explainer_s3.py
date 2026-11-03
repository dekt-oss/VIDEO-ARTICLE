"""S3 — 첫 편(위스키 48초 전체) · S4 — 같은 구성으로 재현(사케). 기획 v2 §3-10 S3·S4 · §10-4. 상한 $8.90 − S2 사용액.

    python -m scripts.explainer_s3                                   # 0원 dry-run: 지시서(기본 S0.5 dry-run 산출) + --s2-spent 로 금액 표·결재 문장·캡션 초안
    python -m scripts.explainer_s3 --s2-spent 2.21 --selected 1,2    # S2 에서 산 슬롯은 다시 사지 않는다(§3-10 "S2 자산은 다시 쓴다")
    python -m scripts.explainer_s3 buy      --plan-id <uuid> --yes --approve "…"   # 운영(돈): 결재(상한 = 8.90 − 원장의 S2 사용액) → 구매 요청(전체) → 워커 1회
    python -m scripts.explainer_s3 buy      --plan-id <uuid> --yes --approve "…"   # 사람 선택 뒤 다시 실행하면 [이어서 구매]다(열린 결재를 다시 쓴다)
    python -m scripts.explainer_s3 assemble --plan-id <uuid> --yes                  # 운영 0원: 조립 요청 → 워커 1회 → 자동 검사
    python -m scripts.explainer_s3 caption  --plan-id <uuid>                        # 0원: 캡션 초안("AI 생성 영상" 줄 포함) 출력

S4(사케 편)는 같은 스크립트를 다른 --plan-id 로 돈다 — 합격 구성을 바꾸지 않는다. 품질 판정 6항목은 대시보드 제작 화면에서 운영자가 체크한다(코드가 대신하지 않는다).
구매는 운영자 PC 에서 이 한 회만 DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1. 운영 DB 에 0067 이 없으면 쓰기 전에 멈춘다.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from engine import config
from scripts import explainer_s2 as s2
from scripts import explainer_stages as st

STAGE = "S3 첫 편"


def s2_spent_from_status(status: dict[str, Any]) -> float:
    """원장 기준 S2 사용액 = 이 편의 결재들이 확정한 금액 합(가잡기 중인 것도 더한다 — 적게 적지 않는다)."""
    total = 0.0
    for a in status.get("approvals") or []:
        total += float(a.get("spent_usd") or 0) + float(a.get("held_usd") or 0)
    return round(total, 4)


def selected_slots(status: dict[str, Any]) -> tuple[int, ...]:
    return tuple(int(s["n"]) for s in status.get("slots") or [] if s.get("status") == "selected")


def describe(directive: dict[str, Any], *, s2_spent: float, selected: tuple[int, ...]) -> tuple[dict[str, Any], str, str]:
    scope = st.s3_scope(directive, s2_spent_usd=s2_spent, selected_slots=selected)
    table = st.format_table(scope["rows"], title=f"[{STAGE}] 남은 슬롯(S2 에서 선택된 {list(scope['skipped_slots']) or '없음'} 은 다시 쓴다)")
    sentence = st.approval_sentence(STAGE, purpose=f"공급자 {directive['provider']} {directive.get('resolution', '720p')} 편 전체", cap_usd=scope["cap_usd"], estimate_usd=scope["estimate_usd"],
                                    scope=f"슬롯 {[r['n'] for r in scope['rows']]} 시작 그림 {len(scope['rows'])}장 + 클립 {sum(r['candidates'] for r in scope['rows'])}개 · 상한 = ${st.cap_for('s3'):.2f} − S2 ${s2_spent:.2f}")
    return scope, table, sentence


def caption_draft(topic: dict[str, Any], hook_text: str, conclusion: str = "") -> str:
    """캡션 초안 — 첫 줄 아래에 'AI 생성 영상'(§3-4). 숫자·권고 검사는 게시 워커가 다시 한다(drinks_script_check.check_caption)."""
    first = str(topic.get("question") or hook_text or "").strip()
    lines = [first, config.DRINKS_EXPLAINER_CAPTION_AI_LINE]
    if conclusion:
        lines += ["", conclusion.strip()]
    lines += ["", "#술째리고 #위스키" if "whisky" in (topic.get("categories") or []) else "#술째리고"]
    return "\n".join(lines)


def dry_run(args: argparse.Namespace) -> int:
    d = s2.load_directive(args.directive)
    selected = tuple(int(x) for x in str(args.selected or "").split(",") if x.strip())
    scope, table, sentence = describe(d, s2_spent=float(args.s2_spent or 0), selected=selected)
    out = st.preview_dir("explainer-s3")
    print(table)
    print(sentence)
    print(f"재시도 예비 ${scope['retry_reserve_usd']:.3f} — 상한 안 남는 폭 ${scope['headroom_usd']:.3f} ({'덮는다' if scope['retry_covered'] else '못 덮는다: 재시도는 새 결재'})")
    if not scope["fits"]:
        print(f"★ 예상 ${scope['estimate_usd']:.2f} 이 상한 ${scope['cap_usd']:.2f} 을 넘는다 — 사지 않는다")
    cap = caption_draft({"question": "위스키 병에는 왜 유통기한이 안 보일까?", "categories": ["whisky"]}, d.get("hook_text", ""),
                        "도수 높은 술은 미생물로 상하는 게 기준이 아니라 맛과 향이 기준이에요. 그래서 병에는 소비기한 대신 제조연월일이 적혀요.")
    print("캡션 초안:\n" + cap)
    report = {"stage": "s3", "dry_run": True, "money_spent_usd": 0.0, "provider_calls": 0, "s2_spent_input_usd": float(args.s2_spent or 0), "selected_input": list(selected),
              "scope": {k: v for k, v in scope.items() if k != "rows"}, "rows": scope["rows"], "approval_sentence": sentence, "caption_draft": cap,
              "quality_items": list(config.DRINKS_EXPLAINER_QUALITY_ITEMS), "env": st.env_summary(), "doc_reference": {"s3_cap_usd": 8.90, "episode_estimate_usd": 7.95, "where": "기획 v2 §3-7·§3-10"}}
    st.dump(out / "report.json", report)
    (out / "directive_table.txt").write_text(table + "\n" + sentence + "\n\n" + cap + "\n", encoding="utf-8")
    print(f"결과물: {out}")
    return 0 if scope["fits"] else 1


def buy(args: argparse.Namespace) -> int:
    rpc, dp = s2._rpc_and_storage()
    s = rpc("drinks_explainer_status", {"plan_revision_id": args.plan_id})
    ep = s.get("episode") or {}
    d = ep.get("directive") or {}
    if not d.get("slots"):
        raise st.StageStop("이 편에 장면별 지시서가 없습니다 — `python -m scripts.explainer_s2 plan` 을 먼저")
    if s.get("unknown_attempts"):
        raise st.StageStop("결과를 모르는 시도가 있습니다 — 대시보드에서 billed/void 로 닫은 뒤에 삽니다")
    spent = s2_spent_from_status(s)
    scope, table, sentence = describe(d, s2_spent=spent, selected=selected_slots(s))
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
    open_ = [a for a in s.get("approvals") or [] if a.get("status") == "open" and not a.get("expired") and str(a.get("stage") or "").startswith("S3")]
    if open_:
        approval_id = open_[0].get("approval_id") or open_[0].get("id")
        print(f"열린 S3 결재를 다시 씁니다(이어서 구매): {approval_id}")
    else:
        a = rpc("drinks_open_spend_approval", {"plan_revision_id": args.plan_id, "stage": STAGE, "purpose": f"{STAGE} — 편 전체 시작 그림·클립", "cap_usd": scope["cap_usd"],
                                                 "allowed_kinds": ["image", "video"], "approved_by": "operator", "approver_words": args.approve, "order_hash": ep.get("order_hash")})
        approval_id = a["approval_id"]
        print(f"결재 등록: {approval_id} 상한 ${scope['cap_usd']:.2f} (= ${st.cap_for('s3'):.2f} − S2 ${spent:.2f})")
    rpc("drinks_explainer_request_buy", {"plan_revision_id": args.plan_id, "spend_approval_id": approval_id})
    res = dp.run_queue(rpc, dp.Storage(), worker_id="s3-buy", tts="edge", max_jobs=1)
    st.dump(st.preview_dir("explainer-s3") / "live-buy.json", {"approval_id": approval_id, "scope": {k: v for k, v in scope.items() if k != "rows"}, "worker": res})
    print(json.dumps(res, ensure_ascii=False, default=str)[:2000])
    print("워커는 사람 선택이 필요한 자리(match 경계)에서 멈춘다 — 대시보드에서 고른 뒤 같은 명령을 다시 실행하면 이어서 산다.")
    return s2.status(args)


def assemble(args: argparse.Namespace) -> int:
    print(st.approval_sentence(STAGE, purpose="선택된 클립 조립 + 자동 검사(0원, 렌더 중 구매 없음)", cap_usd=0.0, estimate_usd=0.0, scope="explainer_render 작업 1건 + 워커 1회"))
    if not args.yes:
        raise st.StageStop("운영 DB 쓰기는 `--yes` 가 있어야 합니다")
    rpc, dp = s2._rpc_and_storage()
    rpc("drinks_explainer_request_assemble", {"plan_revision_id": args.plan_id})
    res = dp.run_queue(rpc, dp.Storage(), worker_id="s3-assemble", tts="edge", max_jobs=1)
    st.dump(st.preview_dir("explainer-s3") / "live-assemble.json", res)
    print(json.dumps(res, ensure_ascii=False, default=str)[:2000])
    print("다음(사람): 대시보드에서 과정 검수 3항목 → 품질 검수 6항목(" + ", ".join(config.DRINKS_EXPLAINER_QUALITY_ITEMS) + ") → 파일 승인. 하나라도 아니면 게시하지 않는다.")
    return s2.status(args)


def caption(args: argparse.Namespace) -> int:
    rpc, _dp = s2._rpc_and_storage()
    s = rpc("drinks_explainer_status", {"plan_revision_id": args.plan_id})
    ep = s.get("episode") or {}
    topic = s.get("topic") or {}
    print(caption_draft(topic, (ep.get("directive") or {}).get("hook_text", "")))
    print(f"\n(캡션의 숫자·권고 검사는 게시 워커가 한다. '{config.DRINKS_EXPLAINER_CAPTION_AI_LINE}' 줄은 §3-4 — 인스타 AI 표시가 API 로 켜지는지 확인 전까지 넣는다.)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    st.utf8_console()
    ap = argparse.ArgumentParser(description="S3 첫 편 / S4 재현 — 기본 0원 dry-run")
    ap.add_argument("step", nargs="?", choices=("dry-run", "buy", "assemble", "caption"), default="dry-run")
    ap.add_argument("--directive", default=None)
    ap.add_argument("--plan-id", default=None)
    ap.add_argument("--s2-spent", type=float, default=0.0, help="dry-run: S2 에서 쓴 금액(운영은 원장에서 읽는다)")
    ap.add_argument("--selected", default="", help="dry-run: S2 에서 선택된 슬롯(예: 1,2)")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--approve", default="")
    args = ap.parse_args(argv)
    try:
        if args.step == "dry-run":
            return dry_run(args)
        if not args.plan_id:
            raise st.StageStop("--plan-id 가 필요합니다")
        return {"buy": buy, "assemble": assemble, "caption": caption}[args.step](args)
    except st.StageStop as stop:
        print(f"멈춤(돈 안 씀): {stop}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
