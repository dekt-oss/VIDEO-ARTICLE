"""Offline, repository-sample entrypoint. Production workers use separate audited APIs."""
import argparse
import json
from pathlib import Path

from engine import config, hf_render


def main():
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=("build","check","render"))
    p.add_argument("kind", choices=("anatomy","class"))
    p.add_argument("mode", choices=("golden","owned"))
    p.add_argument("project", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--workers", type=int)
    a=p.parse_args()
    if a.step=="build":
        if a.kind=="anatomy":
            from engine.jjeri_anatomy.build import build,load_sample
            result=build(load_sample(),a.project,mode="golden" if a.mode=="golden" else "owned_sample")
        else:
            from engine.motion.jjeri_class.build import build_replay
            result=build_replay(a.project,own_bed=a.mode=="owned")
        print(json.dumps({"total":result["total"]}))
    elif a.step=="check":
        print(hf_render.check_project(a.project))
    else:
        if a.out is None:
            p.error("--out is required")
        timeline=json.loads((a.project/"timeline.json").read_text(encoding="utf8"))
        print(json.dumps(hf_render.render_project(a.project,a.out,timeline["total"],normalize=a.mode=="owned",workers=a.workers,
                                                  loudnorm=config.JJERI_LOUDNORM)))


if __name__=="__main__":
    main()
