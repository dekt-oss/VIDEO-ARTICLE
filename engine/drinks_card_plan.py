"""주류 카드뉴스 제작안 초안 — 승인 전 근거로 카드 대본을 쓰고 코드로 검사한다(0065). 2026-11-02. docs/deviation-drinks-card-reels.md

    drinks_develop 워커가 부른다: 요청이 draft_evidence 이고 고른 형식이 카드뉴스면 이 경로다.

흐름은 설명형 대본(drinks_develop.run_plan)과 같다: [가잡기 → 모델 → 확정] → 코드 검사 → 막히면 딱 한 번 다시 쓴다 → 그래도 막히면 **저장하지 않고** 멈춘다.
승인은 사람이 내용 승인 화면에서 [승인] 한 번으로 한다 — 이 모듈은 초안까지만 쓰고 제출·승인 함수를 부르지 않는다.

운영자 규칙을 코드로 옮긴 것:
  · 쉬운 구어체(~요). 문어체(-습니다)는 막는다. 본문 줄은 뜻 단위로 끊는다(긴 줄은 알림).
  · 원문에 없는 숫자·양·처방을 막는다(페이지가 든 근거의 인용과 대조). 표지·훅에 근거를 넘는 숫자가 있어도 막는다.
  · 뼈대는 "왜". 훅은 질문이어야 하고, 법령·표시 규칙은 곁가지 한 줄(소재 자체가 그 규칙일 때만 예외).
  · 사실을 말하는 페이지는 근거 주장에 연결한다. 필수 주장은 다 전해야 한다(DB 커버리지 검사와 같은 규칙).
★ 한계: 문장의 **뜻**이 원문을 넘었는지는 코드가 못 본다 — Jev(켜졌을 때)와 사람의 대조표(result.source_table)가 본다.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from . import config
from . import drinks_script_check as script_check
from .drinks_collect import DbError
from .drinks_develop import Deps, DevelopError, Ledger, Rpc, assert_review_usable, core_takeaway_draft, develop_context, estimate_usd, jev_unsupported_p

FACT_ROLES = ("explain", "compare", "checklist")
ALL_ROLES = ("cover", *FACT_ROLES, "source")
# 법령·표시 규칙 낱말. 소재 자체가 이것을 묻지 않으면 한 페이지까지만 — "왜"가 뼈대다(2026-10-30 운영자).
_RULE_WORDS = re.compile(r"(표시\s*(기준|규칙|의무)|법령|고시|시행령|시행규칙|법률|법적|규정|규제)")
_SAVE_WORDS = re.compile(r"(저장|보내|공유)")
# 저장/보내기 한 줄·훅에 쓰면 안 되는 말 — 음주 조장(밈 규칙과 같은 취지, 기획 v2 §5).
_DRINK_PUSH = re.compile(r"(한\s*잔\s*(하|해|합)|마셔\s*(봐|보|요)|마시자|마셔야|취하|원샷|건배|안주\s*삼아)")


def system_prompt() -> str:
    lo, hi = config.DRINKS_CARD_PAGES
    return (
        f"너는 술 이야기를 쉽게 풀어 주는 인스타 카드뉴스 {lo}~{hi}장의 글을 쓴다. 입력으로 받은 근거(주장과 원문 인용)만 쓴다. JSON 만 낸다.\n"
        "뼈대:\n"
        "- 이 소재의 핵심 궁금증 '왜'를 표지에서 던지고, 설명 페이지가 그 답을 한 걸음씩 풀어 간다. 정의·목록을 늘어놓지 않는다.\n"
        "- 법령·표시 규칙은 곁가지다. 소재가 그 규칙을 묻는 경우가 아니면 한 페이지 한 줄로만 쓴다.\n"
        "말투:\n"
        "- 대중이 한 번에 알아듣는 쉬운 구어체로, 말하듯 ~해요/~예요. 문어체(-습니다·-입니다)와 어려운 낱말을 쓰지 않는다. 전문용어는 쉬운 말로 풀어 쓴다.\n"
        f"- body 는 한 줄 {config.DRINKS_CARD_LINE_MAX_CHARS}자 안쪽으로, 뜻이 끊기는 자리마다 줄바꿈(\\n)을 넣는다. 꾸미는 말과 꾸밈 받는 말을 다른 줄로 가르지 않는다.\n"
        "지어내지 않기(가장 중요):\n"
        "- 근거의 인용에 없는 숫자·양(방울·티스푼·ml·잔)·처방('~해 보세요')·결론·인과를 만들지 않는다. 인용에 있는 숫자만 쓴다. 계산·환산하지 않는다.\n"
        "- 근거가 말하는 선에서 멈춘다. 분량을 채우려고 일반 상식을 덧붙이지 않는다. 근거가 모자라면 페이지를 줄인다.\n"
        "- 술을 권하거나 많이 마시는 것을 좋게 말하지 않는다.\n"
        "페이지:\n"
        f"- pages 는 {lo}~{hi}개. 첫 페이지 role=cover, 마지막 role=source, 그 사이 role=explain·compare·checklist.\n"
        "- 사실을 말하는 페이지(explain·compare·checklist)는 claim_ids 에 근거의 claim_id 를 반드시 단다. '필수 주장'은 빠짐없이 어느 페이지엔가 단다.\n"
        f"- heading 은 {config.DRINKS_CARD_HEADING_MAX_CHARS}자 안, body 는 {config.DRINKS_CARD_BODY_MAX_CHARS}자 안. checklist 의 body 는 줄마다 한 항목.\n"
        "- source 페이지의 heading 은 '출처' 로 하고 body 는 비운다(코드가 출처 목록을 넣는다).\n"
        "릴스용 두 줄(reel):\n"
        f"- hook_title: 릴스 첫 화면의 큰 제목. {config.DRINKS_CARD_HOOK_MAX_CHARS}자 안의 질문(물음표로 끝남). 가능하면 '왜'를 넣는다.\n"
        f"- share_line: 마지막 화면의 한 줄. {config.DRINKS_CARD_SHARE_MAX_CHARS}자 안에서 '저장' 또는 '보내'를 넣어, 누구에게 왜 보낼 만한지 말한다. 숫자·효능을 넣지 않는다.\n"
        "- viewer_conclusion: {\"text\": \"다 읽은 사람이 내릴 결론 한 줄\", \"claim_ids\": [근거 id…]} — 결론도 인용 안에서만.\n"
        "출력 형식: {\"pages\": [{\"role\": \"cover\", \"heading\": \"…\", \"body\": \"…\", \"claim_ids\": []}, …], "
        "\"reel\": {\"hook_title\": \"…\", \"share_line\": \"…\"}, \"viewer_conclusion\": {…}}"
    )


def required_claims(brief: dict[str, Any]) -> list[str]:
    """카드 형식의 필수 주장. 비었으면 다른 형식 목록 → 핵심 주장 앞 N개. SQL drinks_format_required 와 같은 규칙이다."""
    req = (brief or {}).get("required_claims") or {}
    for key in ("carousel", "video"):
        ids = [str(x) for x in req.get(key) or []]
        if ids:
            return ids
    return [str(x) for x in ((brief or {}).get("selected_claim_ids") or [])[: config.DRINKS_DEVELOP_REQUIRED_CLAIMS]]


def user_prompt(question: str, claims: list[dict[str, Any]], brief: dict[str, Any], feedback: Optional[list[str]]) -> str:
    rows = [{"claim_id": c.get("claim_id"), "text": c.get("text"), "claim_type": c.get("claim_type"),
             "quotes": [r.get("original_quote") for r in (c.get("source_refs") or []) if isinstance(r, dict)]} for c in claims]
    parts = [f"소재 질문: {question}", f"핵심 메시지(운영자): {(brief or {}).get('core_takeaway') or '(없음)'}",
             f"필수 주장(빠짐없이 전한다): {', '.join(required_claims(brief)) or '(없음)'}",
             "근거:\n" + json.dumps(rows, ensure_ascii=False)]
    rewrite = (brief or {}).get("_rewrite") or {}
    if rewrite.get("instruction"):
        # 운영자 수정 지시(0076 스튜디오). 근거 밖으로 나가라는 뜻이 아니다 — 위 규칙(인용 밖 숫자·처방 금지)이 그대로 먼저다.
        parts.append("운영자 수정 지시(근거 규칙을 지키는 범위에서 따른다): " + str(rewrite["instruction"])[:500])
        if rewrite.get("current_pages"):
            parts.append("지금 초안(이것을 바탕으로 고쳐 쓴다. 페이지마다 claim_ids 연결은 그대로 둔다):\n"
                         + json.dumps(rewrite["current_pages"], ensure_ascii=False)[:6000])
    if feedback:
        parts.append("직전 초안이 아래 검사에 막혔다. 같은 문제를 고쳐서 처음부터 다시 쓴다:\n" + "\n".join(f"- {m}" for m in feedback))
    return "\n\n".join(parts)


def llm_write_card_plan(question: str, claims: list[dict[str, Any]], brief: dict[str, Any], feedback: Optional[list[str]] = None) -> dict[str, Any]:
    from . import llm

    llm.set_text_purpose("drinks_develop_card_plan")
    return llm.call_json(model=config.DRINKS_CARD_PLAN_MODEL, system=system_prompt(),
                         user=user_prompt(question, claims, brief, feedback), max_tokens=config.DRINKS_CARD_PLAN_MAX_TOKENS)


def _text(page: dict[str, Any]) -> str:
    return f"{page.get('heading') or ''}\n{page.get('body') or ''}"


def check_card_plan(plan: dict[str, Any], review: dict[str, Any], topic: dict[str, Any]) -> script_check.Report:
    """코드 검사(0원). 막힘이 하나라도 있으면 저장하지 않는다."""
    rep = script_check.Report()

    def block(code: str, page: Optional[int], msg: str) -> None:
        rep.blocks.append(script_check.Finding(code, page, msg))

    def warn(code: str, page: Optional[int], msg: str) -> None:
        rep.warns.append(script_check.Finding(code, page, msg))

    pages = plan.get("pages") if isinstance(plan, dict) else None
    if not isinstance(pages, list) or not pages or not all(isinstance(p, dict) for p in pages):
        block("no_pages", None, "페이지(pages)가 없습니다")
        return rep
    lo, hi = config.DRINKS_CARD_PAGES
    if not (lo <= len(pages) <= hi):
        block("page_count", None, f"페이지가 {len(pages)}장입니다({lo}~{hi}장이어야 합니다)")
    roles = [str(p.get("role") or "") for p in pages]
    if roles[0] != "cover" or roles.count("cover") != 1:
        block("cover_position", 1, "첫 페이지만 표지(cover)여야 합니다")
    if roles[-1] != "source" or roles.count("source") != 1:
        block("source_position", len(pages), "마지막 페이지만 출처(source)여야 합니다")

    claims = {str(c.get("claim_id")): c for c in review.get("claims") or [] if isinstance(c, dict)}
    usable = [c for c in claims.values() if not script_check._is_derived(c)]
    all_quotes = " ".join(q for c in usable for q in script_check._quotes(c))
    source_meta = " ".join(" ".join(str(v) for v in (s or {}).values()) for s in review.get("sources") or [])
    covered: set[str] = set()
    rule_pages: list[int] = []

    def text_checks(text: str, i: Optional[int], quotes: str, *, advice_ok: bool = False) -> None:
        missing = sorted(n for n in script_check._nums(text) if n not in (script_check._nums(quotes) | script_check._nums(source_meta)))
        if missing:
            block("number_unsupported", i, f"근거 인용에 없는 숫자: {', '.join(missing)}")
        low = f" {quotes.lower()} "
        for m in script_check._QUANTITY.finditer(text):
            units = script_check._UNITS.get(m.group(1).lower(), script_check._UNITS.get(m.group(1), ()))
            if not any(w in low for w in units):
                block("quantity_unsupported", i, f"'{m.group(0)}' — 근거 인용에 이 단위(양)가 없습니다")
        lines = [s.strip() for s in re.split(r"[\n]+|(?<=[.?!])\s+", text) if s.strip()]
        if not advice_ok and any(script_check._ADVICE.search(s) for s in lines):
            block("advice_unsupported", i, "권고(~해 보세요)입니다 — 원문에 없는 처방을 쓰지 않습니다")
        if any(script_check._FORMAL.search(s) for s in lines):
            block("formal_style", i, "문어체 끝맺음(-습니다·-입니다) — 말하듯이 ~해요로 씁니다")

    for i, pg in enumerate(pages, 1):
        role = str(pg.get("role") or "")
        if role not in ALL_ROLES:
            block("page_role", i, f"페이지 역할 '{role}' 은 쓸 수 없습니다")
        heading, body = str(pg.get("heading") or "").strip(), str(pg.get("body") or "").strip()
        if not heading:
            block("heading_missing", i, "페이지 제목이 없습니다")
        if len(heading) > config.DRINKS_CARD_HEADING_MAX_CHARS:
            block("heading_long", i, f"제목이 {len(heading)}자입니다({config.DRINKS_CARD_HEADING_MAX_CHARS}자 안) — 화면에서 잘립니다")
        if len(re.sub(r"\s", "", body)) > config.DRINKS_CARD_BODY_MAX_CHARS:
            block("body_long", i, f"본문이 깁니다({config.DRINKS_CARD_BODY_MAX_CHARS}자 안) — 화면에서 잘립니다")
        for ln in body.split("\n"):
            if len(ln.replace(" ", "")) > config.DRINKS_CARD_LINE_MAX_CHARS:
                warn("line_long", i, f"본문 한 줄이 깁니다 — 뜻 단위로 끊으세요: {ln[:30]}")
        cids = [str(x) for x in pg.get("claim_ids") or []]
        unknown = [c for c in cids if c not in claims]
        if unknown:
            block("claim_not_allowed", i, f"근거 목록에 없는 주장: {', '.join(unknown)}")
        derived = [c for c in cids if c in claims and script_check._is_derived(claims[c])]
        if derived:
            block("derived_claim_cited", i, f"원문 인용이 아닌 근거를 씁니다: {', '.join(derived)}")
        if role in FACT_ROLES:
            if not cids:
                block("fact_page_no_claim", i, "사실을 말하는 페이지인데 근거(claim_ids)가 없습니다")
            covered.update(cids)
        # 사실 페이지는 자기가 단 근거의 인용과만 대조한다. 표지·출처는 어느 근거에도 안 묶이므로 전체 인용과 대조한다.
        quotes = " ".join(q for c in cids if c in claims and not script_check._is_derived(claims[c]) for q in script_check._quotes(claims[c])) \
            if role in FACT_ROLES else all_quotes
        text_checks(_text(pg), i, quotes)
        if _RULE_WORDS.search(_text(pg)):
            rule_pages.append(i)

    missing_req = [c for c in required_claims(review.get("brief") or {}) if c not in covered]
    if missing_req:
        block("required_claim_missing", None, f"필수 주장을 전하지 않았습니다: {', '.join(missing_req)}")

    topic_text = f"{topic.get('title') or ''} {topic.get('question') or ''}"
    if len(rule_pages) > 1 and not _RULE_WORDS.search(topic_text):
        block("rule_not_side_note", rule_pages[1], f"법령·표시 규칙이 {len(rule_pages)}페이지에 나옵니다 — 곁가지 한 줄로 줄이고 '왜'를 뼈대로 쓰세요")

    reel = plan.get("reel") if isinstance(plan.get("reel"), dict) else {}
    hook, share = str(reel.get("hook_title") or "").strip(), str(reel.get("share_line") or "").strip()
    if not hook.endswith("?"):
        block("hook_not_question", 1, "릴스 훅 제목은 질문(물음표)이어야 합니다")
    if len(hook) > config.DRINKS_CARD_HOOK_MAX_CHARS:
        block("hook_long", 1, f"훅 제목이 {len(hook)}자입니다({config.DRINKS_CARD_HOOK_MAX_CHARS}자 안)")
    if hook and "왜" not in hook:
        warn("hook_no_why", 1, "훅 제목에 '왜'가 없습니다 — 핵심 궁금증을 던지는지 보세요")
    if hook:
        text_checks(hook, 1, all_quotes)
    if not share:
        block("share_line_missing", len(pages), "저장/보내기 한 줄이 없습니다")
    elif not _SAVE_WORDS.search(share):
        block("share_line_no_action", len(pages), "한 줄에 '저장' 또는 '보내'가 없습니다")
    if len(share) > config.DRINKS_CARD_SHARE_MAX_CHARS:
        block("share_line_long", len(pages), f"한 줄이 {len(share)}자입니다({config.DRINKS_CARD_SHARE_MAX_CHARS}자 안)")
    if share:
        # '저장해 두세요' 는 술 처방이 아니라 게시물 행동이라 권고 검사에서 뺀다.
        text_checks(share, len(pages), "", advice_ok=True)
    for label, text, page_no in (("훅 제목", hook, 1), ("저장/보내기 한 줄", share, len(pages))):
        if _DRINK_PUSH.search(text):
            block("drinking_encouraged", page_no, f"{label}이 술을 권합니다")

    concl = plan.get("viewer_conclusion")
    if not isinstance(concl, dict) or not str(concl.get("text") or "").strip():
        block("conclusion_missing_dev", None, "'다 읽은 사람이 내릴 결론' 한 줄이 없습니다")
    else:
        ccids = [str(x) for x in concl.get("claim_ids") or []]
        if not ccids or any(c not in claims or script_check._is_derived(claims[c]) for c in ccids):
            block("conclusion_unsupported", None, "결론에 원문 근거가 없습니다")
        else:
            text_checks(str(concl.get("text")), None, " ".join(q for c in ccids for q in script_check._quotes(claims[c])))
    return rep


def jev_flags(plan: dict[str, Any], claims: list[dict[str, Any]], check: Callable[[str, str], Optional[float]]) -> list[dict[str, Any]]:
    """사실 페이지의 뜻이 인용을 넘는지(Jev, 켜졌을 때만). 신호이지 판정이 아니다 — 있으면 한 번 다시 쓰게 한다."""
    by_id = {str(c.get("claim_id")): c for c in claims}
    out = []
    for i, pg in enumerate(plan.get("pages") or [], 1):
        cids = [str(x) for x in pg.get("claim_ids") or [] if str(x) in by_id]
        if not cids or pg.get("role") not in FACT_ROLES:
            continue
        src = "\n".join(q for c in cids for q in script_check._quotes(by_id[c]))
        p = check(_text(pg), src)
        if p is not None and p >= config.DRINKS_DEVELOP_JEV_UNSUPPORTED_MIN:
            out.append({"page": i, "p": round(p, 3)})
    return out


def source_table(plan: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    """페이지 → 근거 → 원문 인용 대조표. 운영자가 승인 전에 눈으로 대조한다(요청 결과에 남는다)."""
    by_id = {str(c.get("claim_id")): c for c in review.get("claims") or []}
    meta = {str(s.get("snapshot_id")): s for s in review.get("sources") or []}
    rows = []
    for i, pg in enumerate(plan.get("pages") or [], 1):
        cl = []
        for cid in [str(x) for x in pg.get("claim_ids") or []]:
            c = by_id.get(cid)
            if not c:
                continue
            quotes = [{"quote": r.get("original_quote"), "source_title": (meta.get(str(r.get("snapshot_id"))) or {}).get("title"),
                       "source_url": (meta.get(str(r.get("snapshot_id"))) or {}).get("url"), "snapshot_id": r.get("snapshot_id")}
                      for r in c.get("source_refs") or [] if isinstance(r, dict)]
            cl.append({"claim_id": cid, "text": c.get("text"), "quotes": quotes})
        rows.append({"page": i, "role": pg.get("role"), "heading": pg.get("heading"), "body": pg.get("body"), "claims": cl})
    return rows


def clean_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """저장용: DB 검증기(0065 drinks_validate_plan)가 보존하는 칸만. 결론은 notes 한 줄로 옮긴다(설명형과 같다)."""
    concl = plan.get("viewer_conclusion") if isinstance(plan.get("viewer_conclusion"), dict) else {}
    ids = "·".join(str(c) for c in concl.get("claim_ids") or [])
    notes = f"시청자 결론({ids}): {concl.get('text')}" if concl.get("text") else None
    pages = [{"position": i, "role": p.get("role"), "heading": str(p.get("heading") or "").strip(), "body": str(p.get("body") or "").strip() or None,
              "claim_ids": [str(x) for x in p.get("claim_ids") or []]} for i, p in enumerate(plan.get("pages") or [], 1)]
    reel = plan.get("reel") or {}
    return {"pages": pages, "notes": notes, "template_version": "card-reel-v1",
            "reel": {"hook_title": str(reel.get("hook_title") or "").strip(), "share_line": str(reel.get("share_line") or "").strip()}}


def run_card_plan(job: dict[str, Any], rpc: Rpc, lease: dict[str, Any], ledger: Ledger, deps: Deps, beat: Callable[[str], None]) -> dict[str, Any]:
    assert_review_usable(job)
    topic, review = job["topic"], job["review"]
    claims = review.get("claims") or []
    if not claims:
        raise DevelopError("no_core_claims", "근거 버전에 핵심 주장이 없습니다")
    brief = review.get("brief") or {}
    ctx = develop_context(rpc, lease)
    if ctx.get("instruction"):
        brief = {**brief, "_rewrite": {"instruction": ctx["instruction"], "current_pages": (ctx.get("current_plan") or {}).get("pages")}}
    question = topic["question"]
    feedback: Optional[list[str]] = None
    plan: dict[str, Any] = {}
    rep = script_check.Report()
    flags: list[dict[str, Any]] = []
    rewrites = 0
    for attempt in range(config.DRINKS_DEVELOP_MAX_REWRITES + 1):
        beat(f"write:{attempt}")
        in_chars = len(system_prompt()) + len(user_prompt(question, claims, brief, feedback))
        est = estimate_usd(config.DRINKS_CARD_PLAN_MODEL, in_chars, config.DRINKS_CARD_PLAN_MAX_TOKENS)
        plan = ledger.run(config.DRINKS_CARD_PLAN_MODEL, est, lambda fb=feedback: deps.write_card_plan(question, claims, brief, fb),
                          "카드 제작안 초안" if attempt == 0 else "카드 제작안 다시 쓰기")
        if not isinstance(plan, dict):
            plan = {}
        beat(f"check:{attempt}")
        rep = check_card_plan(plan, review, topic)
        flags = jev_flags(plan, claims, deps.jev_check)
        if rep.ok and not flags:
            break
        if attempt < config.DRINKS_DEVELOP_MAX_REWRITES:
            feedback = [f"{f.scene or '전체'}번 {f.code}: {f.message}" for f in rep.blocks] + \
                       [f"{f['page']}번 페이지: 인용한 원문을 넘는 주장일 수 있음(Jev {f['p']})" for f in flags] + \
                       [f"(알림) {f.scene or '전체'}번 {f.code}: {f.message}" for f in rep.warns[:6]]
            rewrites += 1
    if not rep.ok:
        raise DevelopError("script_check_failed", "카드 제작안 검사에서 막혔습니다(다시 쓴 뒤에도).\n" + script_check.summary_ko(rep), "blocked",
                           {"checks": rep.as_dict(), "rewrites": rewrites, "jev_flags": flags, "rejected_plan": plan})
    beat("save")
    cleaned = clean_plan(plan)
    try:
        # 수정 지시면 옛 초안을 막고 새 초안을 한 트랜잭션에서 넣는다(0076 drinks_develop_save_rewrite — 그 사이 사람이 고쳤으면 거절).
        saved = rpc("drinks_develop_save_rewrite" if ctx.get("supersedes_plan_id") else "drinks_develop_save_plan",
                    {**lease, "plan_json": cleaned, **core_takeaway_draft(job, plan)})
    except DbError as exc:
        if exc.code == "lease_lost":
            raise
        # 설명형과 같다: 돈을 낸 초안은 저장이 거부돼도 요청 기록에 남긴다.
        raise DevelopError(exc.code, f"카드 제작안은 만들었지만 저장이 거부됐습니다: {exc.message}", "failed",
                           {"checks": rep.as_dict(), "rewrites": rewrites, "jev_flags": flags, "unsaved_plan": cleaned,
                            "source_table": source_table(plan, review)}) from exc
    return {"revision_id": saved.get("revision_id"), "format": "carousel", "checks": rep.as_dict(), "rewrites": rewrites, "jev_flags": flags,
            "source_table": source_table(plan, review), "viewer_conclusion": plan.get("viewer_conclusion"), "coverage": saved.get("coverage")}


__all__ = ["check_card_plan", "clean_plan", "jev_unsupported_p", "llm_write_card_plan", "required_claims", "run_card_plan", "source_table", "system_prompt", "user_prompt"]
