"""모션그래픽 지시서를 로컬에서 렌더해 본다(0원 — 그림 API 없음, Edge TTS·HyperFrames 만).

사용:
  python -m scripts.motion_preview tests/fixtures/motion_usedcar.json            # 정규화→렌더
  python -m scripts.motion_preview <fixture.json> --build-only                    # HTML 만(렌더 X)
  python -m scripts.motion_preview --directive <report_directive_id>              # 저장된 지시서(DB 읽기만)
결과: outputs/motion_preview/<이름>/final.mp4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.motion import build, schema


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", nargs="?")
    ap.add_argument("--directive")
    ap.add_argument("--build-only", action="store_true")
    a = ap.parse_args()
    if a.directive:
        from engine import report_db
        from engine.report_render import motion_meta
        d = report_db.get_report_directive(a.directive) or {}
        meta, name = motion_meta(d), a.directive[:8]
    else:
        fx = json.loads(Path(a.fixture).read_text(encoding="utf-8"))
        d = schema.normalize_motion_directive(fx["directive"], fx.get("fact_sheet"), fx.get("broker", ""))
        meta, name = fx.get("meta") or {}, Path(a.fixture).stem
        print("경고:", d["header"]["mode_warnings"] or "없음")
    out = Path("outputs/motion_preview") / name
    out.mkdir(parents=True, exist_ok=True)
    if a.build_only:
        info = build.build_project(d, out / "motion_proj", meta)
        print(json.dumps(info, ensure_ascii=False)[:600]); return
    r = build.render(d, str(out), meta)
    print(json.dumps({k: v for k, v in r.items() if k != "cut_map"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
