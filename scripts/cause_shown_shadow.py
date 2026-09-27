"""'~해서 ~한다'의 원인이 화면에 있나 — Jev 그림자 (2026-09-27, 화면 구성 계약 ⑨).

저장된 실사형 지시서의 컷마다 decide.cause_shown(나레이션, 앞 컷 장면, 이 컷 장면)을 묻는다.
읽기 전용. 컷당 $0.00003 수준.

사용:
    python -m scripts.cause_shown_shadow
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import db, decide  # noqa: E402
from scripts.staging_shadow import OUT  # noqa: E402


def main() -> None:
    if not decide.enabled():
        raise SystemExit("JEV 가 꺼져 있다.")
    c = db.client()
    got = []
    for table in ("report_directives", "directives"):
        for d in (c.table(table).select("id,cuts").eq("version_type", "photo")
                  .order("created_at", desc=True).limit(40).execute().data or []):
            prev = ""
            for cu in d.get("cuts") or []:
                vis = str(cu.get("visual_prompt") or "")
                a = decide.cause_shown(str(cu.get("narration_ko") or ""), prev, vis)
                if a:
                    got.append({"directive": d["id"][:8], "cut": cu.get("cut_no"),
                                "role": cu.get("visual_role"),
                                "narration": cu.get("narration_ko"), "prev": prev, "visual": vis, **a})
                prev = vis
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "cause_shown_shadow.json"
    out.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
    causal = [g for g in got if g["states_cause"] >= 0.5]
    print(f"컷 {len(got)}개 · 원인을 말하는 나레이션 {len(causal)}개")
    for th in (0.1, 0.2, 0.3):
        print(f"  원인 안 보임(<{th}): {sum(1 for g in causal if g['cause_shown'] < th)}")
    print("\n[원인이 안 보이는 컷]")
    for g in sorted(causal, key=lambda g: g["cause_shown"])[:14]:
        print("  %s 컷%s %s shown=%.2f | %s\n      화면: %s" % (g["directive"], g["cut"], g["role"],
                                                          g["cause_shown"], g["narration"][:70],
                                                          g["visual"][:120]))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
