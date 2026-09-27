"""수치를 사물 개수·높이로 그린 컷을 Jev 가 가려내나 — 읽기 전용 그림자 (2026-09-27).

운영자 판정(2026-09-24): "4GW" 를 **엔진 네 대**로, 13.7조 원을 **블록 막대**로 그리면 억지
비교다. 수치는 카드가 쓴다. 어휘로는 못 잡는다("four engines" 는 정상 장면에도 나온다) —
나레이션의 수치와 장면을 대조해야 한다. 그 질문(decide.NUMBER_AS_OBJECTS_Q)을 나레이션에
숫자가 있는 저장 컷에 대 본다.

읽기 전용. 비용은 컷당 $0.00003 수준.

사용:
    python -m scripts.number_objects_shadow
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import decide  # noqa: E402
from scripts.staging_shadow import OUT, load  # noqa: E402

_DIGIT = re.compile(r"\d")


def main() -> None:
    if not decide.enabled():
        raise SystemExit("JEV 가 꺼져 있다.")
    rows = [r for r in load(0) if _DIGIT.search(r["narration"])]
    print(f"숫자가 나오는 컷 {len(rows)}개")
    got = []
    for r in rows:
        p = decide.number_as_objects(r["narration"], r["visual"])
        if p is not None:
            got.append({**r, "p": p})
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "number_objects_shadow.json"
    out.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
    for th in (0.5, 0.7, 0.85):
        print(f"  p≥{th}: {sum(1 for g in got if g['p'] >= th)}컷")
    print("\n[가장 높은 컷 — 눈으로 볼 것]")
    for g in sorted(got, key=lambda g: -g["p"])[:12]:
        print("  %s 컷%s %s p=%.2f | %s\n      화면: %s" % (g["directive"], g["cut"], g["role"], g["p"],
                                                       g["narration"][:60], g["visual"][:140]))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
