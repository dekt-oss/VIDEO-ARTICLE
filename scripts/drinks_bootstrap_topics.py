"""주류 공장 - 상시 지식 질문 일괄 등록(0원). 2026-10-28. docs/deviation-drinks-discovery.md

    python -m scripts.drinks_bootstrap_topics docs/drinks-bootstrap/questions.csv            # 미리보기(기본, 아무것도 안 쓴다)
    python -m scripts.drinks_bootstrap_topics docs/drinks-bootstrap/questions.csv --apply    # 실제 등록

CSV 열: category, title, question, lane, question_kind, note  (양식: docs/drinks-bootstrap/questions_template.csv)
  · category  sake|traditional|whisky (한글 사케·전통주·위스키 가능, 여러 개는 | 로)
  · lane      evergreen|timely|reader_question (한글 상시·시의성·독자질문 가능). 비우면 evergreen
  · question_kind  storage|misconception|selection|debate|pairing|howto|general. 비우면 general
  · note      메모 - 소재의 '독자 효용(reader_value)' 칸으로 들어간다

대시보드 [소재·질문 직접 등록]이 부르는 것과 같은 DB 함수(drinks_create_topic)로 등록한다 - 새 경로가 아니다.
같은 질문(공백·문장부호·대소문자 무시)은 CSV 안에서 한 번만 등록하고, DB 에 이미 같은 주종·질문의 소재가 있으면 건너뛴다
(자동으로 '다른 소재'라고 우기지 않는다). 근거는 붙이지 않는다 - 사실 근거는 조사 단계에서 사람이 붙인다.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from engine import config

Rpc = Callable[[str, dict[str, Any]], Any]

COLUMNS = ("category", "title", "question", "lane", "question_kind", "note")


def _key(s: str) -> str:
    return re.sub(r"[\s_-]+", "", (s or "").strip().lower())


_CAT = {"sake": "sake", "사케": "sake", "traditional": "traditional", "전통주": "traditional", "whisky": "whisky", "위스키": "whisky"}
_LANE = {_key(k): v for k, v in {"evergreen": "evergreen", "상시": "evergreen", "상시지식": "evergreen", "timely": "timely", "시의성": "timely",
                                 "reader_question": "reader_question", "독자질문": "reader_question"}.items()}


@dataclass
class Row:
    line: int
    categories: list[str]
    title: str
    question: str
    lane: str
    question_kind: str
    note: str

    def payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {"title": self.title, "question": self.question, "categories": self.categories, "lane": self.lane,
                             "question_kind": self.question_kind}
        if self.note:
            p["reader_value"] = self.note
        return p


@dataclass
class Plan:
    rows: list[Row] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)    # (줄 번호, 사유) - 중복
    errors: list[tuple[int, str]] = field(default_factory=list)     # (줄 번호, 사유) - 형식 오류


def norm_question(text: str) -> str:
    """같은 질문 판정용: 소문자, 공백·문장부호 제거(DB 의 drinks_dedupe_part 와 같은 취지)."""
    return re.sub(r"[\W_]+", "", (text or "").lower())




def parse_csv(text: str) -> Plan:
    plan = Plan()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = [c for c in ("category", "title", "question") if c not in (reader.fieldnames or [])]
    if missing:
        plan.errors.append((1, f"필수 열이 없습니다: {', '.join(missing)}"))
        return plan
    seen: dict[str, int] = {}
    for line, raw in enumerate(reader, start=2):
        r = {k: (raw.get(k) or "").strip() for k in COLUMNS}
        if not any(r.values()):
            continue
        cats = [_CAT.get(_key(c)) for c in re.split(r"[|/;,]", r["category"]) if c.strip()]
        lane = _LANE.get(_key(r["lane"])) if r["lane"] else "evergreen"
        kind = r["question_kind"].lower() or "general"
        if not r["title"] or not r["question"]:
            plan.errors.append((line, "제목과 질문이 필요합니다"))
        elif not cats or None in cats:
            plan.errors.append((line, f"주종을 알 수 없습니다: {r['category']!r} (사케·전통주·위스키)"))
        elif lane is None:
            plan.errors.append((line, f"공급 경로를 알 수 없습니다: {r['lane']!r}"))
        elif kind not in config.DRINKS_QUESTION_KINDS:
            plan.errors.append((line, f"질문 유형을 알 수 없습니다: {r['question_kind']!r} ({'|'.join(config.DRINKS_QUESTION_KINDS)})"))
        else:
            k = norm_question(r["question"])
            if k in seen:
                plan.skipped.append((line, f"같은 질문 - {seen[k]}번째 줄과 중복"))
                continue
            seen[k] = line
            plan.rows.append(Row(line, sorted({c for c in cats if c}), r["title"], r["question"], lane, kind, r["note"]))
    return plan


def apply(plan: Plan, rpc: Rpc) -> dict[str, Any]:
    """DB 에 등록. 같은 주종·질문의 소재가 이미 있으면(duplicate_suggested) 건너뛴다 - confirm_not_duplicate 를 보내지 않는다."""
    from engine.drinks_collect import DbError

    created, existing, failed = [], [], []
    for row in plan.rows:
        try:
            res = rpc("drinks_create_topic", row.payload())
            created.append((row.line, (res or {}).get("topic_id")))
        except DbError as exc:
            (existing if exc.code == "duplicate_suggested" else failed).append((row.line, exc.message or exc.code))
    return {"created": created, "existing": existing, "failed": failed}


def render(plan: Plan, applied: Optional[dict[str, Any]] = None) -> str:
    head = "적용 결과" if applied else "미리보기(아무것도 쓰지 않았습니다)"
    out = [f"{head} - 등록 대상 {len(plan.rows)}건, 중복 건너뜀 {len(plan.skipped)}건, 오류 {len(plan.errors)}건"]
    for r in plan.rows:
        out.append(f"  + [{r.line}줄] {','.join(r.categories)} / {r.lane} / {r.question_kind} / {r.title} - {r.question}")
    out += [f"  = [{ln}줄] {why}" for ln, why in plan.skipped]
    out += [f"  ! [{ln}줄] {why}" for ln, why in plan.errors]
    if applied:
        out.append(f"등록됨 {len(applied['created'])}건, 이미 있어 건너뜀 {len(applied['existing'])}건, 실패 {len(applied['failed'])}건")
        out += [f"  = [{ln}줄] DB 에 같은 소재가 있음" for ln, _ in applied["existing"]]
        out += [f"  ! [{ln}줄] {msg}" for ln, msg in applied["failed"]]
    return "\n".join(out)


def main(argv: Optional[list[str]] = None, rpc: Optional[Rpc] = None) -> int:
    ap = argparse.ArgumentParser(description="질문 CSV 를 주류 소재로 일괄 등록(기본은 미리보기)")
    ap.add_argument("csv", type=Path)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="미리보기만(기본)")
    g.add_argument("--apply", action="store_true", help="실제로 등록 - SUPABASE_URL·SUPABASE_SERVICE_KEY 필요")
    a = ap.parse_args(argv)
    plan = parse_csv(a.csv.read_text(encoding="utf-8-sig"))
    if not a.apply:
        print(render(plan))
        return 1 if plan.errors else 0
    if plan.errors:
        print(render(plan))
        print("오류가 있어 등록하지 않았습니다 - CSV 를 고친 뒤 다시 실행하세요.", file=sys.stderr)
        return 1
    if rpc is None:
        if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
            print("--apply 는 SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다.", file=sys.stderr)
            return 2
        from engine.drinks_collect import supabase_rpc
        rpc = supabase_rpc()
    res = apply(plan, rpc)
    print(render(plan, res))
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
