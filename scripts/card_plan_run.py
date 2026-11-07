"""카드 대본(제작안) 실제 생성 준비 — 운영 소재 1건을 가짜 응답으로 끝까지 돌리고, 질문 지도 24문항에 대본 규칙 검사기를 댄다. docs/deviation-drinks-stage3-4.md

    python -m scripts.card_plan_run                   # 운영 Supabase 를 **읽기만** 해 승인된 근거가 있는 소재 1건 → 가짜 응답으로 끝까지(0원, DB 쓰기 0)
    python -m scripts.card_plan_run --topic <id>      # 특정 소재
    python -m scripts.card_plan_run --offline         # Supabase 없이 시험 입력(scripts/sample_card_reel 의 위스키 근거)
    python -m scripts.card_plan_run --yes --approve "결재 문장"   # 실제 모델 호출 1회. 상한 $0.10(config.DRINKS_CARD_PLAN_RUN_CAP_USD). 결재 문장 없으면 부르지 않는다
                                                      # ★ 실제 호출도 DB 에 제작안을 쓰지 않는다 — 산출물 파일만. 운영 저장은 워커(drinks-develop)가 한다.
                                                      #   단, LLM 호출의 비용 원장(generation_attempts)은 평소처럼 기록된다 — 보고서 db_writes 가 둘을 나눠 적는다.

산출물: docs/preview-2026-11-02/card-plan/ (gitignore) — report.json · plan.json · source_table.md · question_map_check.json/md
보이는 것:
  1. 워커 경로(drinks_develop.process_job → drinks_card_plan.run_card_plan)가 운영 소재의 근거로 끝까지 간다. 저장 함수는 가짜 RPC 가 받는다.
  2. 질문 지도(네이버 질문 8유형 × 3주종 = 24문항)마다 "쉬운 구어체·뜻 단위 자막·없는 처방 금지·왜가 중심" 넷을 어긴 가짜 답을 넣어
     check_card_plan 이 **넷 다 잡는지**, 그리고 지키는 답은 통과하는지 표로 남긴다. 검사기 시험이지 대본 품질 판정이 아니다.
★ 가짜 응답은 근거 문장을 그대로 옮긴 것이다. 실제 모델이 쓴 대본이 아니다. 대본 품질은 --yes 1회 뒤 운영자가 본다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from engine import config
from engine import drinks_card_plan as cp
from engine import drinks_develop as dd
from engine import drinks_script_check as script_check
from scripts.explainer_rehearsal import Tripwire

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "docs" / "preview-2026-11-02" / "card-plan"
RULES = ("formal_style", "quantity_or_number", "advice_unsupported", "why_or_rule")   # 운영자 규칙 넷 ↔ 검사 코드


# ─────────────────────────────────────────────────────────────
# 입력: 운영 소재(읽기만) 또는 시험 입력
# ─────────────────────────────────────────────────────────────

def offline_job() -> dict[str, Any]:
    from scripts.sample_card_reel import CLAIMS, SOURCES

    review = {"review_id": "offline-r1", "status": "approved", "claims": CLAIMS, "core_claim_ids": [c["claim_id"] for c in CLAIMS], "sources": SOURCES,
              "brief": {"selected_claim_ids": [c["claim_id"] for c in CLAIMS], "required_claims": {"carousel": ["c1", "c2"]}, "core_takeaway": "도수가 높아 안 상하지만 열면 맛이 바뀐다"}}
    topic = {"id": "offline-t1", "title": "위스키에도 유통기한이 있을까?", "question": "위스키는 왜 안 상할까?", "categories": ["whisky"]}
    return {"request_id": "offline-q1", "lease_token": "offline-l1", "kind": "plan", "budget_id": "offline-b1", "topic": topic, "review": review,
            "format_intent": "card", "draft_evidence": True, "offline": True}


def load_live_job(topic_id: Optional[str]) -> dict[str, Any]:
    """운영 DB 읽기만. 승인된(취소 안 된) 근거 버전 중 원문 인용이 있는 주장이 1개 이상인 소재를 고른다. 쓰는 호출은 없다."""
    from engine import db

    cli = db.client()
    q = cli.table("drink_topic_reviews").select("id, topic_id, status, brief, evidence_pack, decided_at, drink_topics!drink_topic_reviews_topic_id_fkey(id, title, question, categories, status)") \
        .eq("status", "approved").is_("revoked_at", "null").order("decided_at", desc=True).limit(30)
    if topic_id:
        q = q.eq("topic_id", topic_id)
    rows = q.execute().data or []
    picked = None
    for r in rows:
        claims = [c for c in ((r.get("evidence_pack") or {}).get("claims") or []) if isinstance(c, dict) and not script_check._is_derived(c)]
        if claims:
            picked = (r, claims)
            break
    if picked is None:
        raise SystemExit("승인된 근거(원문 인용 있음)가 있는 소재를 찾지 못했습니다 — --offline 으로 시험 입력을 쓰세요")
    r, _ = picked
    brief = r.get("brief") or {}
    selected = [str(x) for x in brief.get("selected_claim_ids") or []]
    all_claims = [c for c in (r.get("evidence_pack") or {}).get("claims") or [] if isinstance(c, dict)]
    claims = [c for c in all_claims if str(c.get("claim_id")) in selected] if selected else all_claims
    snap_ids = sorted({str(ref.get("snapshot_id")) for c in claims for ref in (c.get("source_refs") or []) if isinstance(ref, dict) and ref.get("snapshot_id")})
    sources = []
    if snap_ids:
        srows = cli.table("drink_source_snapshots").select("id, title, publisher, canonical_url, published_at").in_("id", snap_ids[:150]).execute().data or []
        sources = [{"snapshot_id": s["id"], "title": s.get("title"), "publisher": s.get("publisher"), "url": s.get("canonical_url"), "published_at": s.get("published_at")} for s in srows]
    t = r.get("drink_topics") or {}
    if isinstance(t, list):
        t = t[0] if t else {}
    topic = {"id": t.get("id") or r["topic_id"], "title": t.get("title"), "question": t.get("question"), "categories": t.get("categories"), "status": t.get("status")}
    review = {"review_id": r["id"], "status": r["status"], "brief": brief, "core_claim_ids": selected or [str(c.get("claim_id")) for c in claims], "claims": claims, "sources": sources}
    return {"request_id": f"dry-{r['id'][:8]}", "lease_token": "dry-lease", "kind": "plan", "budget_id": "dry-budget", "topic": topic, "review": review,
            "format_intent": "card", "draft_evidence": True, "offline": False}


# ─────────────────────────────────────────────────────────────
# 가짜 응답 — 근거 문장을 그대로 옮긴다(모델 흉내가 아니라 경로 시험)
# ─────────────────────────────────────────────────────────────

def _lines(text: str, max_chars: int = config.DRINKS_CARD_LINE_MAX_CHARS) -> str:
    """뜻 단위(어절 묶음)로 줄을 끊는다. 한 줄 글자 수 상한 안에서."""
    words, out, cur = str(text or "").split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and len(cand.replace(" ", "")) > max_chars:
            out.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        out.append(cur)
    return "\n".join(out[:4])


def _spoken(text: str) -> str:
    """-다 끝맺음을 -요 로(문어체 차단 규칙은 -습니다/-입니다 만 막지만, 운영자 규칙은 말하듯이다)."""
    s = str(text or "").strip().rstrip(".")
    s = re.sub(r"(않는다|않다)$", "않아요", s)
    s = re.sub(r"(한다)$", "해요", s)
    s = re.sub(r"(있다)$", "있어요", s)
    s = re.sub(r"(된다)$", "돼요", s)
    s = re.sub(r"(바뀐다|변한다)$", lambda m: m.group(1)[:-2] + "어요" if m.group(1) == "바뀐다" else "변해요", s)
    s = re.sub(r"(이다)$", "이에요", s)
    return s   # 그 밖의 -다 끝맺음은 그대로 둔다(활용을 못 맞추면 '바꾼다요' 가 된다). 차단 규칙은 -ㅂ니다 체만 본다


def fake_card_plan(question: str, claims: list[dict[str, Any]], brief: dict[str, Any], feedback: Optional[list[str]] = None) -> dict[str, Any]:
    usable = [c for c in claims if not script_check._is_derived(c)]
    req = cp.required_claims(brief)
    ordered = sorted(usable, key=lambda c: (str(c.get("claim_id")) not in req, str(c.get("claim_id"))))
    lo, hi = config.DRINKS_CARD_PAGES
    n = max(lo - 2, min(hi - 2, len(ordered)))
    body_claims = ordered[:n] if len(ordered) >= n else ordered
    q = str(question or "").strip().rstrip("?")
    hook = (q if "왜" in q else f"왜 {q}")
    hook = hook[: config.DRINKS_CARD_HOOK_MAX_CHARS - 1] + "?"
    pages: list[dict[str, Any]] = [{"role": "cover", "heading": hook[: config.DRINKS_CARD_HEADING_MAX_CHARS], "body": "", "claim_ids": []}]
    strip_nums = bool(feedback and any("number_unsupported" in f or "quantity_unsupported" in f for f in feedback))
    for i, c in enumerate(body_claims, 1):
        text = _spoken(str(c.get("text") or ""))
        if strip_nums:
            text = re.sub(r"[0-9][0-9,.]*\s*\S*", "", text).strip() or "근거에 적힌 대로예요"
        heading = (text.split(" ")[0] + " 이야기")[: config.DRINKS_CARD_HEADING_MAX_CHARS]
        pages.append({"role": "explain", "heading": heading, "body": _lines(text)[: config.DRINKS_CARD_BODY_MAX_CHARS], "claim_ids": [str(c.get("claim_id"))]})
    while len(pages) < lo - 1:   # 근거가 적으면 같은 주장을 다시 쓰지 않고 마무리 페이지로 채운다(분량 때문에 상식을 덧붙이지 않는다)
        first = body_claims[0]
        pages.append({"role": "explain", "heading": "정리하면 이래요", "body": _lines(_spoken(str(first.get("text") or ""))), "claim_ids": [str(first.get("claim_id"))]})
    pages.append({"role": "source", "heading": "출처", "body": "", "claim_ids": []})
    first_id = str(body_claims[0].get("claim_id")) if body_claims else None
    return {"pages": pages,
            "reel": {"hook_title": hook, "share_line": "궁금해하던 친구에게 저장해서 보내 주세요"[: config.DRINKS_CARD_SHARE_MAX_CHARS]},
            "viewer_conclusion": {"text": _spoken(str(body_claims[0].get("text") or "")) if body_claims else "", "claim_ids": [first_id] if first_id else []}}


class MemRpc:
    """워커가 부르는 DB 함수를 받아 적기만 한다. 운영 DB 에는 아무것도 쓰지 않는다."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.saved: Optional[dict[str, Any]] = None
        self.finish: Optional[dict[str, Any]] = None
        self.holds = 0

    def __call__(self, fn: str, p: dict[str, Any]) -> Any:
        self.calls.append(fn)
        if fn in ("drinks_heartbeat_develop", "drinks_develop_context"):   # 0076: 부가 정보(수정 지시 없음)
            return {}
        if fn == "drinks_develop_hold":
            self.holds += 1
            return {"hold_id": f"h{self.holds}", "remaining_usd": 1.0}
        if fn == "drinks_develop_settle":
            return {}
        if fn == "drinks_develop_save_plan":
            self.saved = p
            return {"revision_id": "(저장 안 함 — 가짜 RPC)", "coverage": {"recorded": False}}
        if fn == "drinks_finish_develop":
            self.finish = p
            return {"status": p["outcome"], "result": p.get("result"), "error_code": p.get("error_code"), "error_message": p.get("error_message")}
        raise AssertionError(f"예상 밖 DB 함수: {fn}")


def source_table_md(rows: list[dict[str, Any]]) -> str:
    out = ["# 페이지 → 근거 → 원문 인용 대조표", "", "| 쪽 | 역할 | 제목 | 본문 | 근거 | 원문 인용 |", "|---|---|---|---|---|---|"]
    for r in rows:
        quotes = " / ".join(f"[{c['claim_id']}] " + " · ".join((q.get("quote") or "")[:120] for q in c["quotes"]) for c in r["claims"]) or "-"
        claims = ", ".join(c["claim_id"] for c in r["claims"]) or "-"
        out.append(f"| {r['page']} | {r['role']} | {r['heading']} | {(r['body'] or '').replace(chr(10), ' / ')} | {claims} | {quotes} |")
    return "\n".join(out) + "\n"


# ─────────────────────────────────────────────────────────────
# 질문 지도 × 규칙 검사기
# ─────────────────────────────────────────────────────────────

QM_QUOTE = "The high alcohol content keeps microbes from growing, so the drink does not spoil the way wine does."
QM_REVIEW = {"review_id": "qm", "status": "approved", "sources": [{"snapshot_id": "s", "title": "시험 출처", "publisher": "시험", "url": "https://example.org/q"}],
             "claims": [{"claim_id": "k1", "text": "도수가 높아 미생물이 자라지 못해 상하지 않는다", "claim_type": "process", "source_refs": [{"snapshot_id": "s", "original_quote": QM_QUOTE}]},
                        {"claim_id": "k2", "text": "라벨에는 유통기한 대신 제조 번호가 있을 수 있다", "claim_type": "fact", "source_refs": [{"snapshot_id": "s", "original_quote": "Labels may show a bottling lot instead of an expiry date."}]}],
             "brief": {"selected_claim_ids": ["k1", "k2"], "required_claims": {"carousel": ["k1"]}}}


def _hook_safe(q: str) -> str:
    """질문을 훅으로 옮길 때 '마셔야' 같은 권유 낱말은 바꿔 적는다(실제 모델도 그래야 한다 — 훅의 drinking_encouraged 차단)."""
    return q.replace("마셔야", "마시는 게 좋을지")


def qm_good(question: str) -> dict[str, Any]:
    q = _hook_safe(question.strip().rstrip("?"))
    hook = (q if "왜" in q else f"{q}, 왜 그럴까")[: config.DRINKS_CARD_HOOK_MAX_CHARS - 1] + "?"
    return {"pages": [
        {"role": "cover", "heading": hook[: config.DRINKS_CARD_HEADING_MAX_CHARS], "body": "", "claim_ids": []},
        {"role": "explain", "heading": "술이 세서 그래요", "body": "도수가 높으면\n미생물이 못 자라요", "claim_ids": ["k1"]},
        {"role": "explain", "heading": "그래서 안 상해요", "body": "와인처럼\n상하지 않아요", "claim_ids": ["k1"]},
        {"role": "explain", "heading": "라벨에 날짜가 없다면요?", "body": "유통기한 대신\n제조 번호가\n있을 수 있어요", "claim_ids": ["k2"]},
        {"role": "source", "heading": "출처", "body": "", "claim_ids": []},
    ], "reel": {"hook_title": hook, "share_line": "궁금해하던 친구에게 저장해서 보내 주세요"},
        "viewer_conclusion": {"text": "도수가 높아 잘 안 상해요", "claim_ids": ["k1"]}}


def qm_variants(question: str) -> dict[str, dict[str, Any]]:
    """운영자 규칙 넷을 하나씩 어긴 답. 검사기가 각각을 잡아야 한다."""
    import copy

    base = qm_good(question)
    formal = copy.deepcopy(base)
    formal["pages"][1]["body"] = "도수가 높으면\n미생물이 자라지 못합니다"
    quantity = copy.deepcopy(base)
    quantity["pages"][1]["body"] = "40도쯤이면\n물 한 티스푼만 타도\n미생물이 못 자라요"
    advice = copy.deepcopy(base)
    advice["pages"][2]["body"] = "그러니 오래된 병도\n걱정 말고 드세요"
    why = copy.deepcopy(base)
    why["reel"]["hook_title"] = "위스키 유통기한 정리"
    why["pages"][0]["heading"] = "위스키 유통기한 정리"
    why["pages"][2]["body"] = "주세법 규정과\n표시 기준 고시가\n이렇게 정해요"
    why["pages"][3]["body"] = "표시 기준 법령은\n제조 번호를\n허용해요"
    return {"good": base, "formal_style": formal, "quantity_or_number": quantity, "advice_unsupported": advice, "why_or_rule": why}


EXPECT = {"formal_style": {"formal_style"}, "quantity_or_number": {"number_unsupported", "quantity_unsupported"}, "advice_unsupported": {"advice_unsupported"},
          "why_or_rule": {"hook_not_question", "rule_not_side_note"}}


def question_map_check() -> dict[str, Any]:
    rows = []
    all_ok = True
    for cat, kind, kind_ko, questions in config.DRINKS_QUESTION_MAP:
        for q in questions:
            topic = {"title": q, "question": q, "categories": [cat]}
            res: dict[str, Any] = {"category": config.DRINKS_CATEGORY_KO.get(cat, cat), "kind": kind_ko, "question": q}
            for name, plan in qm_variants(q).items():
                rep = cp.check_card_plan(plan, QM_REVIEW, topic)
                blocks, warns = sorted({f.code for f in rep.blocks}), sorted({f.code for f in rep.warns})
                if name == "good":
                    # 질문 자체에 숫자가 있으면("위스키 12년 의미") 훅의 그 숫자도 근거 인용에 있어야 통과한다 — 검사기가 맞게 막은 것이라 '잡음'으로 적는다.
                    number_from_question = set(blocks) <= {"number_unsupported"} and bool(re.search(r"[0-9]", q))
                    ok = rep.ok or number_from_question
                    res["good"] = {"ok": ok, "warns": warns, "note": "질문의 숫자를 훅에 쓰려면 근거 인용에 있어야 함(검사기가 막음)" if number_from_question else None}
                else:
                    ok = bool(set(blocks) & EXPECT[name])
                    res[name] = {"caught": ok, "blocks": blocks}
                all_ok = all_ok and ok
            rows.append(res)
    return {"questions": len(rows), "all_rules_caught_and_good_passes": all_ok, "rows": rows,
            "rules": {"쉬운 구어체": "formal_style", "없는 처방·양 금지": "quantity_or_number / advice_unsupported", "왜가 중심(규칙은 곁가지)": "why_or_rule",
                      "뜻 단위 자막": "line_long(알림) — 가짜 답은 짧아 알림이 없다. 줄 끊기는 렌더(meaning_lines)가 다시 본다"}}


def question_map_md(qm: dict[str, Any]) -> str:
    out = ["# 질문 지도 24문항 × 대본 규칙 검사기", "", f"전부 잡고 좋은 답은 통과: **{'예' if qm['all_rules_caught_and_good_passes'] else '아니오'}**", "",
           "| 주종 | 유형 | 질문 | 좋은 답 | 문어체 | 없는 양·숫자 | 처방 | 왜 없음·규칙 과다 |", "|---|---|---|---|---|---|---|---|"]
    for r in qm["rows"]:
        mark = lambda k: ("잡음" if r[k]["caught"] else "**놓침**") + f" ({', '.join(r[k]['blocks'])})"
        good = ("통과" if r["good"]["ok"] else "**막힘**") + (f" 알림 {', '.join(r['good']['warns'])}" if r["good"]["warns"] else "") + (f" — {r['good']['note']}" if r["good"].get("note") else "")
        out.append(f"| {r['category']} | {r['kind']} | {r['question']} | {good} | {mark('formal_style')} | {mark('quantity_or_number')} | {mark('advice_unsupported')} | {mark('why_or_rule')} |")
    return "\n".join(out) + "\n"


# ─────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────

LEDGER_CALLS = {"n": 0}   # 이번 실행에서 비용 원장(generation_attempts) 기록을 시도한 LLM 호출 수 — 보고에 그대로 적는다


def run_job(job: dict[str, Any], *, live: bool) -> tuple[dict[str, Any], MemRpc, float]:
    rpc = MemRpc()
    if live:
        deps = dd.Deps(write_card_plan=cp.llm_write_card_plan, jev_check=lambda n, s: None)
        with dd.capture_usage() as box:
            res = dd.process_job(job, rpc, deps)
        LEDGER_CALLS["n"] = box.calls
        return res, rpc, round(box.usd, 6)
    deps = dd.Deps(write_card_plan=fake_card_plan, jev_check=lambda n, s: None)
    with Tripwire(allow_network=True) as wire:   # 모델·이미지·영상·구매 경로에 줄. 네트워크는 운영 DB 읽기(위 load) 뒤라 여기서는 안 쓴다
        res = dd.process_job(job, rpc, deps)
    if wire.hits:
        raise SystemExit(f"가짜 실행인데 유료 경로에 닿았습니다: {wire.hits}")
    return res, rpc, 0.0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="카드 대본 생성 준비 — 가짜 응답으로 끝까지(0원) / --yes 로 실제 1회(상한 $0.10)")
    ap.add_argument("--topic", default=None, help="소재 id(없으면 승인된 근거가 있는 최근 소재)")
    ap.add_argument("--offline", action="store_true", help="Supabase 없이 시험 입력으로")
    ap.add_argument("--yes", action="store_true", help="실제 모델 호출 1회(돈이 든다)")
    ap.add_argument("--approve", default="", help="결재 문장(운영자가 승인한 말 그대로). --yes 에 필수")
    ap.add_argument("--out", default=str(PREVIEW))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    job = offline_job() if args.offline else load_live_job(args.topic)
    claims = job["review"]["claims"]
    in_chars = len(cp.system_prompt()) + len(cp.user_prompt(job["topic"]["question"], claims, job["review"].get("brief") or {}, None))
    est = dd.estimate_usd(config.DRINKS_CARD_PLAN_MODEL, in_chars, config.DRINKS_CARD_PLAN_MAX_TOKENS)
    live = False
    if args.yes:
        if not args.approve.strip():
            print("실제 호출에는 --approve \"결재 문장\" 이 필요합니다. 부르지 않았습니다.")
            return 2
        if est * (1 + config.DRINKS_DEVELOP_MAX_REWRITES) > config.DRINKS_CARD_PLAN_RUN_CAP_USD:
            print(f"예상액 ${est:.4f} × 최대 {1 + config.DRINKS_DEVELOP_MAX_REWRITES}회 가 상한 ${config.DRINKS_CARD_PLAN_RUN_CAP_USD:.2f} 를 넘습니다. 부르지 않았습니다.")
            return 2
        live = True
    res, rpc, actual = run_job(job, live=live)
    plan = rpc.saved["plan_json"] if rpc.saved else (rpc.finish or {}).get("result", {}).get("rejected_plan")
    result = (rpc.finish or {}).get("result") or {}
    qm = question_map_check()
    report = {
        "mode": "live" if live else ("offline" if args.offline else "dry-run(운영 소재 읽기만)"),
        "topic": {k: job["topic"].get(k) for k in ("id", "title", "question", "categories")},
        "review_id": job["review"]["review_id"], "claims": len(claims), "claims_with_quotes": sum(1 for c in claims if not script_check._is_derived(c)),
        "estimate_usd_per_call": est, "cap_usd": config.DRINKS_CARD_PLAN_RUN_CAP_USD, "actual_usd": actual, "approve_words": args.approve or None,
        "model": config.DRINKS_CARD_PLAN_MODEL if live else "(가짜 응답)",
        "status": res.get("status"), "error_code": (rpc.finish or {}).get("error_code"), "error_message": (rpc.finish or {}).get("error_message"),
        "checks": result.get("checks"), "rewrites": result.get("rewrites"), "coverage": result.get("coverage"),
        # 리뷰 §5(2026-11-04): '쓰기 0'을 둘로 나눠 적는다. 제작안은 어느 모드에서도 운영 DB 에 저장하지 않지만, 실제 호출(--yes)은
        # LLM 비용 원장(generation_attempts)에 호출마다 한 행씩 기록을 시도한다(engine/llm._record_text_usage → cost.record).
        "db_writes": {"plan_saves": 0, "cost_ledger_rows_attempted": LEDGER_CALLS["n"] if live else 0},
        "rpc_calls": rpc.calls, "saved_to_db": False,
        "note": ("제작안은 가짜 RPC 가 받아 적었을 뿐 운영 DB 에 저장하지 않았다. 운영 저장은 [이걸로] → drinks-develop 워커가 한다."
                 + (" 실제 호출의 비용은 운영 비용 원장(generation_attempts)에 기록을 시도했다(실패해도 호출은 막지 않는다)." if live else " 모델 호출 0회 — 비용 원장 기록도 없다.")),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if result.get("source_table"):
        (out / "source_table.md").write_text(source_table_md(result["source_table"]), encoding="utf-8")
    (out / "question_map_check.json").write_text(json.dumps(qm, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "question_map_check.md").write_text(question_map_md(qm), encoding="utf-8")

    print(f"[{report['mode']}] 소재: {report['topic']['title']} / {report['topic']['question']}  근거 {report['claims']}건(인용 있음 {report['claims_with_quotes']})")
    print(f"워커 결과: {report['status']}  {report['error_code'] or ''} {('— ' + str(report['error_message'])[:160]) if report['error_message'] else ''}")
    if plan:
        for p in plan.get("pages") or []:
            print(f"  {p.get('position', '')}. [{p.get('role')}] {p.get('heading')}  {('/ ' + str(p.get('body')).replace(chr(10), ' / ')) if p.get('body') else ''}")
        reel = plan.get("reel") or {}
        print(f"  훅: {reel.get('hook_title')}  · 저장 한 줄: {reel.get('share_line')}")
    print(f"예상 ${est:.4f}/회 · 실제 ${actual:.4f} · 상한 ${config.DRINKS_CARD_PLAN_RUN_CAP_USD:.2f} · DB 쓰기 0")
    print(f"질문 지도 {qm['questions']}문항: 규칙 넷 전부 잡고 좋은 답 통과 = {'예' if qm['all_rules_caught_and_good_passes'] else '아니오'}")
    print(f"산출물 {out}")
    return 0 if (res.get("status") == "succeeded" and qm["all_rules_caught_and_good_passes"]) else 1


if __name__ == "__main__":
    sys.exit(main())
