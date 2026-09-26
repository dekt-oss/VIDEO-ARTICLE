"""숫자 감사의 빨강 중 '원장 수치를 단위·표기만 바꿔 쓴 것'을 Jev 가 가려내나 — 읽기 전용 (2026-09-27).

저장된 지시서(리포트·논문 실사형)에 숫자 감사를 다시 돌려 빨강을 모으고, 각각에
decide.number_restated 를 물어 확률을 남긴다. 운영 표에 쓰지 않는다. 컷당 $0.00003 수준.

사용:
    python -m scripts.number_restated_shadow
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import db, decide, directive_audit  # noqa: E402
from engine import directive as dv  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")


def _pairs() -> list[tuple[str, dict, dict]]:
    c = db.client()
    out = []
    rd = {d["report_id"]: d for d in db.select_all("report_drafts", "report_id,fact_sheet",
                                                   key=("report_id",))}
    for d in c.table("report_directives").select("id,report_id,header,cuts").execute().data or []:
        if d["report_id"] in rd:
            out.append(("report:" + d["id"][:8], d, rd[d["report_id"]]["fact_sheet"] or {}))
    for d in (c.table("directives").select("id,paper_id,header,cuts").eq("version_type", "photo")
              .order("created_at", desc=True).limit(40).execute().data or []):
        fs = (c.table("drafts").select("fact_sheet").eq("paper_id", d["paper_id"])
              .limit(1).execute().data or [{}])[0].get("fact_sheet") or {}
        out.append(("paper:" + d["id"][:8], d, fs))
    return out


def main() -> None:
    if not decide.enabled():
        raise SystemExit("JEV 가 꺼져 있다.")
    rows = []
    for name, d, fs in _pairs():
        header, cuts = d.get("header") or {}, d.get("cuts") or []
        audit = directive_audit.audit(header, cuts, fs)
        facts = " | ".join(dv._fact_strings_with_numbers(fs))
        by_no = {c.get("cut_no"): c for c in cuts}
        for f in audit["findings"]:
            if f["level"] != "red" or "number" not in f:
                continue
            if f["code"] == "hook_number_not_in_source":
                sent = str(header.get("hook_ko") or "")
            else:
                c = by_no.get(f["cut_no"]) or {}
                sent = " / ".join([*(str(c.get(k) or "") for k in ("narration_ko", "narration_en")),
                                 *(str(o.get("text") or "") for o in (c.get("overlay_plan") or []) if isinstance(o, dict))])
            p = decide.number_restated(f["number"], sent, facts)
            rows.append({"directive": name, "cut": f["cut_no"], "number": f["number"],
                         "sentence": sent, "p": p})
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "number_restated_shadow.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in rows if r["p"] is not None]
    print(f"빨강 {len(rows)}건 · 판정 {len(ok)}건")
    for th in (0.5, 0.8, 0.9):
        print(f"  p≥{th}: {sum(1 for r in ok if r['p'] >= th)}")
    for r in sorted(ok, key=lambda r: -r["p"]):
        print("  %.2f %-16s 컷%-2s %-10s | %s" % (r["p"], r["directive"], r["cut"], r["number"],
                                                 r["sentence"][:90]))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
