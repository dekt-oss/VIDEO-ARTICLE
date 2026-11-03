"""S0.5 — 설명형 대본 다시 개발(위스키 "왜 안 상하나"). 기획 v2 §3-10 S0.5 · §10-11. 상한 $0.30.

    python -m scripts.explainer_s05                       # 0원 dry-run: 가짜 모델 응답으로 대본 검사 → 시각 주장표 → 장면별 지시서·금액까지 끝까지
    python -m scripts.explainer_s05 --tts edge            # dry-run 이지만 나레이션 길이만 무료 TTS 로 실측(네트워크)
    python -m scripts.explainer_s05 evidence --yes --approve "…"   # 운영: 결재($0.30) → 근거 다시 모으기 요청 → 워커 1회. (B3·B7 근거 보강)
    python -m scripts.explainer_s05 plan --yes --approve "…" [--budget-id …]   # 운영: 승인된 근거로 48초 대본 요청 → 워커 1회

흐름(운영): evidence → [대시보드에서 새 근거 버전 승인 — 사람] → plan → [대시보드에서 대본 승인 — 사람]. 두 요청이 한 결재($0.30)를 나눠 쓴다.
돈이 나가는 것은 모델 호출뿐이고(DB 가 결재 상한을 막는다), 영상·그림은 이 단계에서 사지 않는다.
★ dry-run 의 장면은 손으로 쓴 가짜 응답이다(docs/drinks-pilot/whisky-spoil-explainer-dryrun.json). 운영에 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from engine import config
from engine import drinks_develop as dd
from engine import drinks_explainer_queue as q
from engine.util import today_local
from scripts import explainer_stages as st

FIXTURE = st.ROOT / "docs" / "drinks-pilot" / "whisky-spoil-explainer-dryrun.json"
STAGE = "S0.5 대본 다시 개발"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class DryRpc:
    """0060 함수 흉내 — 결재 상한만 진짜처럼 막는다. 운영 DB 에 닿지 않는다."""

    def __init__(self, cap_usd: float):
        self.cap, self.committed, self.names, self.saved, self.finish = cap_usd, 0.0, [], None, None

    def __call__(self, fn: str, p: dict[str, Any]) -> Any:
        self.names.append(fn)
        if fn == "drinks_heartbeat_develop":
            return {"cancel_requested": False}
        if fn == "drinks_develop_hold":
            if self.committed + p["est_usd"] > self.cap:
                from engine.drinks_collect import DbError
                raise DbError("budget_exceeded", f"결재 상한 ${self.cap:.2f} 초과(예상 ${p['est_usd']:.3f})")
            self.committed += p["est_usd"]
            return {"hold_id": f"h{len(self.names)}"}
        if fn == "drinks_develop_settle":
            return {"hold_id": p["hold_id"]}
        if fn == "drinks_develop_save_plan":
            self.saved = p
            return {"revision_id": "dry-run-plan", "coverage": {}}
        if fn == "drinks_finish_develop":
            self.finish = p
            return {"status": p["outcome"], "result": p.get("result")}
        raise AssertionError(f"dry-run 이 모르는 호출: {fn}")


def tts_ms_estimate(scenes: list[dict[str, Any]]) -> dict[int, int]:
    """나레이션 길이 추정(음절 ÷ 5.9/초, §3-6-2 말 속도) — ffmpeg·네트워크 없이. 글자·숫자만 센다(문장부호 제외). 실측은 --tts edge."""
    import re

    return {i: int(max(1.0, len(re.sub(r"[^0-9A-Za-z가-힣]", "", str(sc.get("narration") or ""))) / config.DRINKS_EXPLAINER_PLACEHOLDER_SYL_PER_SEC) * 1000) for i, sc in enumerate(scenes, 1)}


def tts_ms_measured(scenes: list[dict[str, Any]], out_dir: Path, tts: str) -> dict[int, int]:
    from engine import drinks_explainer as dx

    paths = q.synth_narrations(scenes, str(out_dir), tts, q.Deps())
    return {i: dx.media_duration_ms(p) for i, p in paths.items()}


def dry_run(out: Path, *, tts: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    fx = load_fixture()
    review = {"status": "approved", "claims": fx["claims"], "brief": fx["brief"], "sources": fx["sources"]}
    job = {"request_id": "dry-run", "lease_token": "dry", "kind": "plan", "budget_id": "dry-budget", "topic": fx["topic"], "review": review}
    rpc = DryRpc(st.cap_for("s05"))
    seen: dict[str, Any] = {}

    def fake_write(question: str, claims: list[dict[str, Any]], brief: dict[str, Any], feedback: Optional[list[str]] = None) -> dict[str, Any]:
        seen["question"], seen["claim_ids"], seen["feedback"] = question, [c["claim_id"] for c in claims], feedback
        seen["system_prompt"], seen["user_prompt"] = dd.plan_system(), dd.plan_user_prompt(question, claims, brief, feedback)
        return json.loads(json.dumps(fx["fake_plan"]))

    done = dd.process_job(job, rpc, dd.Deps(write_plan=fake_write, extract_claims=lambda *_: [], jev_check=lambda n, s: None, fetcher_factory=lambda h: None))
    result = (rpc.finish or {}).get("result") or {}
    (out / "prompt_system.txt").write_text(seen.get("system_prompt", ""), encoding="utf-8")
    (out / "prompt_user.txt").write_text(seen.get("user_prompt", ""), encoding="utf-8")
    st.dump(out / "develop_result.json", {"status": done.get("status"), "finish": rpc.finish, "rpc_calls": rpc.names})
    if done.get("status") != "succeeded":
        return {"ok": False, "develop": done, "finish": rpc.finish}

    plan = fx["fake_plan"]
    scenes = plan["scenes"]
    tts_ms = tts_ms_measured(scenes, out / "narration", tts) if tts else tts_ms_estimate(scenes)
    djob = {"plan": {"scenes": scenes}, "topic": fx["topic"], "claims": fx["claims"], "sources": fx["sources"], "brief": fx["brief"]}
    directive = q.build_directive("dry-run-plan", djob, result["visual_claims"], tts_ms, provider=config.DRINKS_EXPLAINER_DEFAULT_PROVIDER)
    st.dump(out / "directive.json", directive)
    st.dump(out / "visual_claims.json", result["visual_claims"])
    st.dump(out / "source_table.json", result["source_table"])
    (out / "source_table.md").write_text(source_table_md(result["source_table"], result["visual_claims"]), encoding="utf-8")
    rows = st.slot_rows(directive)
    summary = {"ok": True, "checks": result["checks"], "rewrites": result["rewrites"], "scenes": len(scenes), "raw_sec": round(sum(float(s["timing_sec"]) for s in scenes), 1),
               "tts_total_ms": sum(tts_ms.values()), "tts_source": tts or "estimate(5.9 syl/s)", "final_sec_planned": round(directive["final_ms"] / 1000, 2),
               "edit_cuts": directive["edit_cuts"], "hook_scene": directive["hook_scene"], "boundaries": [s["boundary_in"] for s in directive["slots"]],
               "estimate": directive["estimate"], "s2": {k: v for k, v in st.s2_scope(directive).items() if k != "rows"}, "develop_cost_cap_usd": st.cap_for("s05"),
               "model_calls_made": 0, "money_spent_usd": 0.0, "fixture": str(FIXTURE.relative_to(st.ROOT)), "note": "가짜 응답이다 — 그림·대본 품질을 본 것이 아니다"}
    st.dump(out / "report.json", summary)
    (out / "directive_table.txt").write_text(st.format_table(rows, title="장면별 지시서(가짜 대본 기준, 0원)"), encoding="utf-8")
    return summary


def source_table_md(table: list[dict[str, Any]], claims: list[dict[str, Any]]) -> str:
    by_scene = {int(r["scene"]): r for r in claims}
    lines = ["# 장면별 원문 대조표 (S0.5 dry-run · 가짜 대본)", "", "| 장면 | 나레이션 | 근거 | 원문 인용 | 시각 주장 | 표기 |", "|---|---|---|---|---|---|"]
    for r in table:
        vc = by_scene.get(int(r["scene"]), {})
        cl = "<br>".join(f"{c['claim_id']}: {c['text']}" for c in r["claims"]) or "(도입·마무리)"
        qs = "<br>".join(f"“{q['quote']}” — {q['source_title'][:40]}…" for c in r["claims"] for q in c["quotes"]) or "—"
        lines.append(f"| {r['scene']} | {r['narration']} | {cl} | {qs} | {vc.get('visual_claim_ko', '')} | {vc.get('depiction_label', '')} |")
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# 운영(돈): --yes 와 결재 문장이 있어야 한다
# ─────────────────────────────────────────────────────────────

def live(args: argparse.Namespace) -> dict[str, Any]:
    cap = st.cap_for("s05")
    sentence = st.approval_sentence(STAGE, purpose="위스키 '왜 안 상하나' 근거 보강(B3·B7) + 48초 대본", cap_usd=cap, estimate_usd=0.10,
                                    scope=f"{args.step} 요청 1건 + 워커 1회(모델 호출만, 영상·그림 구매 없음)")
    print(sentence)
    st.require_yes(args, "모델 호출")
    st.require_db_env()
    from engine.drinks_collect import supabase_rpc

    rpc = supabase_rpc()
    topic_id = args.topic_id or config.DRINKS_EXPLAINER_S05_TOPIC_ID
    budget_id = args.budget_id
    if not budget_id:
        b = rpc("drinks_open_develop_budget", {"cap_usd": cap, "stage": STAGE, "purpose": "설명형 S0.5 — 근거 보강·48초 대본", "approver_words": args.approve, "approved_by": "operator"})
        budget_id = b["budget_id"]
        print(f"결재 열림: budget_id={budget_id} 상한 ${cap:.2f}")
    req = rpc("drinks_request_develop", {"topic_id": topic_id, "kind": args.step, "budget_id": budget_id})
    print(f"요청: {args.step} request_id={req.get('request_id')} existing={req.get('existing', False)}")
    res = dd.run_queue(rpc, dd.Deps(), worker_id=f"s05-{today_local().isoformat()}", max_jobs=1)
    # 워커는 큐의 맨 앞 요청을 집는다 — 다른 소재의 요청이 먼저 있었으면 그것이 돌았다(그쪽 결재로). 어느 요청이 돌았는지 숨기지 않는다.
    if res and res[0].get("request_id") != req.get("request_id"):
        print(f"★ 주의: 집은 요청이 다릅니다 — 돈 요청 {res[0].get('request_id')} ≠ 우리 요청 {req.get('request_id')}. 우리 요청은 아직 큐에 있다. 같은 명령을 다시 실행한다")
    out = {"budget_id": budget_id, "request": req, "worker": res}
    st.dump(st.preview_dir("explainer-s05") / f"live-{args.step}.json", out)
    for r in res:
        cost = ((r.get("result") or {}).get("cost") or {})
        print(f"워커: {r.get('status')} 사용액 ${float(cost.get('spent_usd') or 0):.4f} (상한 ${cap:.2f})")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    st.utf8_console()
    ap = argparse.ArgumentParser(description="S0.5 설명형 대본 다시 개발 — 기본 0원 dry-run")
    ap.add_argument("step", nargs="?", choices=("dry-run", "evidence", "plan"), default="dry-run")
    ap.add_argument("--yes", action="store_true", help="운영 DB 에 요청을 넣고 모델을 부른다(돈). 없으면 아무것도 보내지 않는다")
    ap.add_argument("--approve", default="", help="결재 문장(운영자가 승인한 말 그대로)")
    ap.add_argument("--budget-id", default=None, help="이미 열어 둔 개발 결재를 다시 쓴다(evidence 뒤의 plan)")
    ap.add_argument("--topic-id", default=None)
    ap.add_argument("--tts", default="", choices=("", "edge", "placeholder"), help="dry-run 에서 나레이션 길이 실측(edge 는 네트워크)")
    args = ap.parse_args(argv)
    out = st.preview_dir("explainer-s05")
    try:
        if args.step == "dry-run":
            rep = dry_run(out, tts=args.tts)
            print(json.dumps({k: v for k, v in rep.items() if k not in ("checks",)}, ensure_ascii=False, indent=1))
            if rep.get("ok"):
                print((out / "directive_table.txt").read_text(encoding="utf-8"))
                print(f"결과물: {out}")
                print("다음(운영자): " + st.approval_sentence(STAGE, purpose="위스키 '왜 안 상하나' 근거 보강(B3·B7) + 48초 대본", cap_usd=st.cap_for('s05'), estimate_usd=0.10,
                                                     scope="evidence 요청 1건 + plan 요청 1건(모델 호출만)"))
                return 0
            print("dry-run 이 검사에 막혔다:", json.dumps(rep, ensure_ascii=False)[:2000])
            return 1
        live(args)
        return 0
    except st.StageStop as stop:
        print(f"멈춤(돈 안 씀): {stop}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
