"""작업명세서 모델 실측 — 같은 입력·같은 프롬프트로 **모델만** 바꿔 지시서를 뽑고 코드로 채점한다.

무엇을 푸는가(운영자 지시 2026-09-19): "딥시크와 재미나이의 동일한 기준으로 작업명세서
결과 각각 뽑아서 비교해봅시다. 어느정도 성능차이인지 보구요."

★★ 채점은 **렌더 파이프라인이 쓰는 바로 그 함수**로 한다 — scripts/quality_experiment.py 가
  세운 원칙 그대로다. 눈으로 "이게 더 좋아 보인다"는 인상평이고, 그것으로 공급자를 바꾸면
  나중에 무엇이 나아졌는지 아무도 말할 수 없다. 여기서 쓰는 게이트는 전부 지시서 생성
  경로가 실제로 통과해야 하는 것들이다:

    · directive._contract_reasons      — 재생성을 부르는 계약 위반
    · directive._quality_retry_reasons — 재생성을 부르는 품질 경고
    · sequence_tier.contract_shortfall — 시간 계약 미달
    · cut_skeleton.shortfall           — 골격 칸수 미달(11칸 줬는데 7컷)
    · directive_audit.audit            — 나레이션이 근거를 벗어났는가(red/yellow)
    · directive.validate_reuse_refs    — 재사용 참조가 실재하는가
    · photo_contract.*                 — 키워드 카드·지시선·색 충돌·기전 라벨·화면 분할
    · header.approval_blocked          — 사람 검수로 넘어가는가

★ 실험은 **한 가지만 바꾼다**(paired). 두 팔의 draft_row·system·user 프롬프트·max_tokens·
  temperature 가 모두 같다. 다른 것은 모델 ID 하나뿐이다.

★ **재생성 루프를 타지 않는다.** build_directive 는 계약 위반 시 1회 재생성하는데, 한쪽만
  재생성이 걸리면 "두 번 시도한 결과"와 "한 번 시도한 결과"를 비교하게 된다. 여기서는 한 발씩만
  쏘고, **재생성이 걸렸겠는가**를 점수로 센다 — 그게 실제로 알고 싶은 것이다.

★ 생성은 확률적이다. `--repeat 2` 이상을 권한다. 한 번 뽑아 나온 차이는 모델 차이가 아니라
  그날 운일 수 있다(저장소의 G4 실험이 정확히 그것을 재는 실험이었다).

★ 이 스크립트는 **유료 텍스트 호출**을 한다(팔 × repeat 회). 영상·이미지는 만들지 않는다.
  지시서 1벌은 수십 원 수준이지만, 공짜가 아니라는 것은 말해 둔다.

사용:
    python -m scripts.model_ab --paper <paper_id>                       # 기본 2모델 1회
    python -m scripts.model_ab --paper <id> --repeat 2                  # 권장
    python -m scripts.model_ab --paper <id> --models gemini-2.5-pro,deepseek-v4-pro
    python -m scripts.model_ab --list                                   # 후보 draft 목록
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine import (  # noqa: E402
    config, cut_skeleton, db, directive as D, directive_audit,
    photo_contract, sequence_tier,
)
from engine.llm import call_json, set_text_purpose  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")

# 기본 두 팔. 지시서는 지금 gemini-2.5-pro 가 만든다 — 그 자리를 놓고 겨룬다.
DEFAULT_MODELS = ["gemini-2.5-pro", "deepseek-v4-pro"]


def _generate(draft_row: dict[str, Any], version_type: str, model: str) -> dict[str, Any]:
    """한 발. build_directive 의 `_once` 와 **같은 순서**로 하되 재생성은 하지 않는다."""
    skeleton = (cut_skeleton.build(draft_row.get("script_md") or "", version_type=version_type)
                if (config.CUT_SKELETON_ENABLED and version_type == "photo") else [])
    fact_sheet = D.refresh_claim_evidence(draft_row)      # LLM 0건·무료
    source_text = D._source_text_for(draft_row)
    system = D.DIRECTIVE_SYSTEM_BASE
    user = D.directive_user_prompt(draft_row, version_type)

    set_text_purpose("directive")
    t0 = time.time()
    obj = call_json(model=model, system=system, user=user,
                    max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS)
    elapsed = time.time() - t0

    d = D.normalize_directive(
        obj, version_type, fact_sheet=fact_sheet,
        content_plan=(draft_row.get("video_flow") or {}).get("content_plan"),
        source_text=source_text)
    return {"directive": d, "fact_sheet": fact_sheet, "skeleton": skeleton,
            "elapsed_sec": elapsed, "prompt_chars": len(system) + len(user)}


def _score(run: dict[str, Any]) -> dict[str, Any]:
    """코드 채점. **낮을수록 좋다**(문제 개수)는 것을 이름으로 드러낸다.

    `_` 로 시작하는 항목은 점수가 아니라 **맥락**이다. 컷이 적으면 문제도 적게 나오므로,
    문제합만 보고 이겼다고 말하면 안 된다 — 그래서 컷 수를 같은 표에 둔다.
    """
    d = run["directive"]
    header, cuts, fs = d.get("header") or {}, d.get("cuts") or [], run["fact_sheet"]

    audit = directive_audit.audit(header, cuts, fs)
    findings = audit.get("findings") or []
    kw_a, kw_b = photo_contract.keyword_card_problems(cuts)
    split_a, split_b = photo_contract.split_composition_cuts(cuts)
    # ★ 게이트가 쓰는 **그 유도식** 그대로 읽는다(photo_contract 1447·1624행). 처음엔
    #   header["total_sec"] / header["sequences"] 로 읽었는데 그런 키는 없어서 네 항목이
    #   전부 0 으로 나왔다 — 맥락 칸이라 판정을 틀리게 하진 않았지만, 0 을 사실처럼
    #   보고할 뻔했다. 채점기가 채점 대상과 다른 키를 보면 조용히 거짓말을 한다.
    seqs = [x for x in (header.get("visual_sequences") or []) if isinstance(x, dict)]
    total_sec = int(header.get("total_estimated_sec") or 0) or sum(
        int(c.get("estimated_sec") or 0) for c in cuts)

    return {
        # ── 재생성을 부르는가 (파이프라인의 자기 판정)
        "계약위반": len(D._contract_reasons(d)),
        "품질경고": len(D._quality_retry_reasons(d)),
        "시간계약미달": 1 if sequence_tier.contract_shortfall(cuts, header) else 0,
        "골격미달": 1 if cut_skeleton.shortfall(run["skeleton"], cuts) else 0,
        "승인차단": 1 if header.get("approval_blocked") else 0,
        # ── 근거를 벗어났는가
        "근거red": sum(1 for f in findings if f.get("level") == "red"),
        "근거yellow": sum(1 for f in findings if f.get("level") == "yellow"),
        "재사용참조오류": len(D.validate_reuse_refs(cuts)),
        # ── 화면 계약
        "키워드카드문제": len(kw_a) + len(kw_b),
        "지시선문제": len(photo_contract.pointer_zone_problems(cuts)),
        "색충돌": len(photo_contract.color_code_conflicts(header)),
        "기전라벨누락": len(photo_contract.mechanism_unlabeled_cuts(header, cuts)),
        "화면분할컷": len(split_a) + len(split_b),
        # ── 맥락(점수 아님)
        "_컷수": len(cuts),
        "_총초": total_sec,
        "_시퀀스수": len(seqs),
        "_유효런타임": photo_contract.effective_runtime(cuts, total_sec),
        "_분당세계수": round(photo_contract.worlds_per_minute(seqs, total_sec), 2),
        "_invest컷": sum(1 for c in cuts
                        if (sequence_tier.effective_tier(c, header) or {}).get("tier") == "invest"),
        "_block_reasons": list(header.get("block_reasons") or []),
    }


def _problem_total(sc: dict[str, Any]) -> int:
    """문제 개수 항목만 합산. `_` 로 시작하는 맥락 항목은 더하지 않는다."""
    return sum(v for k, v in sc.items() if not k.startswith("_") and isinstance(v, int))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default="")
    ap.add_argument("--version-type", default="photo")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="대본 있는 draft 목록만 보고 끝낸다")
    args = ap.parse_args()

    if args.list:
        rows = db.client().table("drafts").select("paper_id, created_at").order(
            "created_at", desc=True).limit(15).execute().data or []
        for r in rows:
            print(f"  {r['paper_id']}  {str(r.get('created_at'))[:19]}")
        return

    if not args.paper:
        ap.error("--paper 를 주거나 --list 로 고르세요")
    draft_row = db.get_draft_full(args.paper)
    if not draft_row:
        raise SystemExit(f"draft 없음: {args.paper}")

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    results: list[dict[str, Any]] = []
    for rep in range(args.repeat):
        for model in models:
            print(f"[{rep + 1}/{args.repeat}] {model} ...", flush=True)
            try:
                run = _generate(draft_row, args.version_type, model)
                # ★ 지시서 원본을 남긴다. 채점기를 고칠 때마다 유료 호출을 다시 하는 것은
                #   낭비이고, 무엇보다 **다시 뽑으면 다른 결과**라 예전 점수와 비교가 안 된다.
                OUT.mkdir(parents=True, exist_ok=True)
                (OUT / f"지시서-{model}-{rep + 1}.json").write_text(
                    json.dumps(run["directive"], ensure_ascii=False, indent=2), encoding="utf-8")
                sc = _score(run)
                sc["_모델"], sc["_회차"] = model, rep + 1
                sc["_초"] = round(run["elapsed_sec"], 1)
                sc["_문제합"] = _problem_total(sc)
                results.append(sc)
                print(f"    문제합 {sc['_문제합']:>3}  컷 {sc['_컷수']:>2}  {sc['_초']}s")
            except Exception as exc:     # noqa: BLE001 — 한 팔이 죽어도 다른 팔은 본다
                print(f"    실패: {type(exc).__name__}: {str(exc)[:200]}")
                results.append({"_모델": model, "_회차": rep + 1,
                                "_실패": f"{type(exc).__name__}: {exc}"})

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"모델실측-{stamp}.json"
    path.write_text(json.dumps(
        {"paper_id": args.paper, "version_type": args.version_type,
         "models": models, "repeat": args.repeat, "results": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {path}")

    # 표. 실패한 팔은 숨기지 않는다 — 실패도 결과다.
    ok = [r for r in results if "_실패" not in r]
    if ok:
        keys = [k for k in ok[0] if not k.startswith("_")]
        head = "".join(f"{(r['_모델'][:13] + '#' + str(r['_회차'])):>18}" for r in ok)
        print(f"\n{'항목':<16}{head}")
        for k in keys + ["_문제합", "_컷수", "_총초", "_invest컷", "_초"]:
            print(f"{k:<16}" + "".join(f"{str(r.get(k, '-')):>18}" for r in ok))
    for r in results:
        if "_실패" in r:
            print(f"\n실패 — {r['_모델']} #{r['_회차']}: {r['_실패'][:300]}")


if __name__ == "__main__":
    main()
