"""리포트 지시서 정규화에 Fact Sheet **전체**를 넘기면 무엇이 바뀌나 — 읽기 전용 그림자 (2026-09-25).

무엇을 재나
----------
PR #52 는 `report_directive._generate_once` 가 `normalize_directive` 에 원문 깊이 하나만
넘기게 고쳤다(`source_depth=`). 그런데 `fact_sheet` 인자는 깊이 말고도 게이트 여럿을 켠다 —
숫자 감사(`directive_audit`), 오버레이 연도 대조, 발표 연도(시점 오류), Claim 대조 ….
리포트 Fact Sheet 는 논문과 모양이 달라서(claims 없음) 그 게이트가 리포트에서 맞게 도는지
재 본 적이 없다.

저장된 리포트 지시서마다 짝 초안의 fact_sheet 를 가지고 정규화를 두 번 돌린다:
    (a) 현행 — source_depth 만
    (b) fact_sheet 전체
그리고 header 의 block_reasons·mode_warnings 를 코드(콜론 앞)별로 비교한다.

★ 돈이 들지 않는다 — LLM·Jev 를 부르지 않는다(판정 모델 스위치를 끄고, 부르면 죽게 막는다).
★ 두 방식 모두 **같은 저장본**을 다시 정규화하므로, 재정규화 자체가 만드는 차이는 상쇄된다.
★ 운영 표에 쓰지 않는다. 결과는 docs/실측_모델/(gitignore)에 떨군다.

사용:
    python -m scripts.report_factsheet_shadow
"""

from __future__ import annotations

import collections
import copy
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import config, db, decide, report_reasoning, selfcheck, visual_router  # noqa: E402
from engine import directive as dv  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")


def _no_llm(*_a, **_k):
    raise RuntimeError("그림자 측정은 LLM 을 부르지 않는다")


def _codes(xs: list[str]) -> collections.Counter:
    return collections.Counter(str(x).split(":", 1)[0] for x in xs or [])


def _normalize(stored: dict[str, Any], draft: dict[str, Any], full: bool) -> dict[str, Any]:
    header = copy.deepcopy(stored.get("header") or {})
    obj = {"header": header, "cuts": copy.deepcopy(stored.get("cuts") or []),
           "visual_sequences": header.get("visual_sequences") or []}
    fs = draft.get("fact_sheet") or {}
    return dv.normalize_directive(
        obj, stored.get("version_type") or "photo", cut_max_sec=config.CUT_MAX_SEC,
        fact_sheet=fs if full else None,
        source_depth=visual_router.source_depth_of(fs),
        mechanism_supply=report_reasoning.process_step_count(draft.get("financial_reasoning")))


def main() -> None:
    decide.enabled = lambda: False          # type: ignore[assignment]
    decide._post = _no_llm                  # type: ignore[assignment]
    selfcheck.check = _no_llm               # type: ignore[assignment]

    dirs = db.select_all("report_directives", "id,report_id,version_type,header,cuts,created_at",
                         key=("id",))
    drafts = {d["report_id"]: d for d in db.select_all(
        "report_drafts", "report_id,fact_sheet,financial_reasoning", key=("report_id",))}
    print(f"리포트 지시서 {len(dirs)}건 · 짝 초안 {sum(1 for d in dirs if d['report_id'] in drafts)}건")

    rows: list[dict[str, Any]] = []
    new_block = collections.Counter()
    new_warn = collections.Counter()
    gone_block = collections.Counter()
    gone_warn = collections.Counter()
    for d in dirs:
        draft = drafts.get(d["report_id"])
        if not draft or not (d.get("cuts") or []):
            continue
        try:
            a = _normalize(d, draft, full=False)["header"]
            b = _normalize(d, draft, full=True)["header"]
        except Exception as exc:            # 한 건이 죽어도 나머지는 잰다 — 사실은 기록한다
            rows.append({"directive": d["id"][:8], "error": str(exc)[:200]})
            continue
        ab, bb = _codes(a.get("block_reasons")), _codes(b.get("block_reasons"))
        aw, bw = _codes(a.get("mode_warnings")), _codes(b.get("mode_warnings"))
        new_block.update(bb - ab)
        new_warn.update(bw - aw)
        gone_block.update(ab - bb)
        gone_warn.update(aw - bw)
        rows.append({
            "directive": d["id"][:8], "report": d["report_id"][:8],
            "version": d.get("version_type"),
            "fs_keys": sorted((draft.get("fact_sheet") or {}).keys()),
            "a_blocks": a.get("block_reasons"), "b_blocks": b.get("block_reasons"),
            "a_warn": a.get("mode_warnings"), "b_warn": b.get("mode_warnings"),
            "a_audit": a.get("directive_audit"), "b_audit": b.get("directive_audit"),
            "cuts": [{"cut_no": c.get("cut_no"), "narration_ko": c.get("narration_ko"),
                      "overlay": [o.get("text") for o in (c.get("overlay_plan") or [])
                                  if isinstance(o, dict)]}
                     for c in (d.get("cuts") or [])],
            "fact_sheet": draft.get("fact_sheet"),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "report_factsheet_shadow.json"
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    errs = [r for r in rows if "error" in r]
    print(f"측정 {len(rows) - len(errs)}건 · 오류 {len(errs)}건")
    for r in errs[:5]:
        print("  오류", r["directive"], r["error"])
    for title, ctr in (("(b)에서 새로 생긴 차단", new_block), ("(b)에서 새로 생긴 경고", new_warn),
                       ("(b)에서 사라진 차단", gone_block), ("(b)에서 사라진 경고", gone_warn)):
        print(f"\n[{title}]")
        for k, v in ctr.most_common() or [("—", 0)]:
            print(f"  {k:40s} {v}")
    print(f"\n저장: {p}")


if __name__ == "__main__":
    main()
