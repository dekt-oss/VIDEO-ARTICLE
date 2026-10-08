"""V2 결과의 첫 질문만 다시 쓴다 — 후보 5개 + 지금 질문을 같은 Jev 검사로 재고 나란히 보여 준다(저장·발행 없음).

    python -m scripts.rewrite_hook <compare_explanation_v2 결과 JSON>

비용: 후보 작성 1회(config.MODEL_V2_HOOK) + Jev 약 (후보 수+2)×2회. 결과는 같은 폴더에 `-hook.md/.json`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine import db, hook_rewrite


def _fact_sheet(domain: str, content_id: str) -> dict:
    client = db.client() if hasattr(db, "client") else db.get_client()
    if domain == "paper":
        rows = client.table("drafts").select("fact_sheet").eq("paper_id", content_id).limit(1).execute().data
    else:
        rows = client.table("report_drafts").select("fact_sheet").eq("report_id", content_id).limit(1).execute().data
    return (rows or [{}])[0].get("fact_sheet") or {}


def markdown(current: dict, legacy: dict | None, rows: list[dict], chosen: dict) -> str:
    def line(tag: str, r: dict) -> str:
        f = lambda v: "-" if v is None else f"{v:.2f}"
        return f"| {tag} | {r['text']} | {f(r['jargon'])} | {f(r['spoiler'])} | {f(r['unsupported'])} |"
    out = ["# 첫 질문 다시 쓰기 — 후보 비교", "",
           "점수는 0~1, **낮을수록 좋다**(전문용어 · 답 노출 · 근거 넘음). 바꿀 자격: 세 검사 모두 문턱 안 +",
           "지금 질문보다 나쁘지 않고 전문용어나 답 노출이 확실히 낫다.", "",
           "| 구분 | 첫 장면 | 전문용어 | 답 노출 | 근거 넘음 |", "|---|---|---:|---:|---:|"]
    if legacy:
        out.append(line("운영 대본(참고)", legacy))
    out.append(line("**지금 V2**", current))
    for i, r in enumerate(rows, 1):
        out.append(line(f"후보 {i} ({r.get('angle') or '-'})", r))
    out += ["", f"**자동 선택:** {'후보로 교체 → ' + chosen['text'] if chosen['changed'] else '지금 질문 유지(더 나은 후보 없음)'}",
            "", "최종 결정은 운영자가 한다 — 이 결과는 어디에도 저장되지 않았다."]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json")
    args = parser.parse_args()
    path = Path(args.result_json)
    result = json.loads(path.read_text(encoding="utf-8"))
    shadow = result.get("shadow") or {}
    scenes = ((shadow.get("writer") or {}).get("script") or {}).get("scenes") or []
    if len(scenes) < 2:
        raise SystemExit("V2 대본 장면이 없습니다")
    current, next_scene = scenes[0]["narration_ko"], scenes[1]["narration_ko"]
    core = ((shadow.get("reasoning") or {}).get("reasoning") or {}).get("core_question") or ""
    fact_sheet = _fact_sheet(result["domain"], result["content_id"])
    legacy_md = str((result.get("legacy") or {}).get("script_md") or "").strip()
    legacy_hook = legacy_md.split("\n")[0].strip() if legacy_md else ""

    proposals = hook_rewrite.propose(fact_sheet, current, next_scene, core)
    texts = [current, *([legacy_hook] if legacy_hook else []), *[p["text"] for p in proposals]]
    scored = hook_rewrite.score(texts, fact_sheet)
    now, rest = scored[0], scored[1:]
    legacy = rest.pop(0) if legacy_hook else None
    for row, p in zip(rest, proposals):
        row["angle"] = p["angle"]
    chosen = hook_rewrite.choose(now, rest)
    out = {"current": now, "legacy": legacy, "candidates": rest, "chosen": chosen}
    base = path.with_name(path.stem + "-hook")
    base.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(now, legacy, rest, chosen), encoding="utf-8")
    print(json.dumps({"changed": chosen["changed"], "chosen": chosen["text"], "markdown": str(base.with_suffix(".md"))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
