"""텍스트 모델 실측 — 같은 입력·같은 프롬프트로 **모델만** 바꿔 뽑고 코드로 채점한다.

무엇을 푸는가(운영자 지시 2026-09-19): "딥시크와 재미나이의 동일한 기준으로 작업명세서
결과 각각 뽑아서 비교해봅시다. 어느정도 성능차이인지 보구요."

두 작업을 잰다. **티어가 다르면 따로 재야 한다** — 지시서에서 나온 결과가 flash 티어에도
적용된다는 보장이 없다(운영자 판단 2026-09-19: "먼저 재보고 결정").

  · `--job directive` — pro 티어. 현행 gemini-2.5-pro.  채점: 렌더 게이트(아래)
  · `--job factsheet` — flash 티어. 현행 gemini-2.5-flash. 채점: 정규화기가 고친 횟수

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
    python -m scripts.model_ab --paper <paper_id> --repeat 3             # 지시서(기본)
    python -m scripts.model_ab --paper <id> --job factsheet --repeat 3   # Fact Sheet
    python -m scripts.model_ab --paper <id> --models deepseek-flash      # 팔 직접 지정
    python -m scripts.model_ab --list                                    # 후보 draft 목록
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
    config, cut_skeleton, db, directive as D, directive_audit, factsheet as F,
    photo_contract, sequence_tier,
)
from engine.llm import call_json, set_text_purpose  # noqa: E402

OUT = pathlib.Path("docs/실측_모델")

# 작업마다 겨루는 자리가 다르다. 지시서는 pro 티어(gemini-2.5-pro), Fact Sheet 는
# flash 티어(gemini-2.5-flash)다 — **그 자리의 현행 모델**을 기준 팔로 세운다.
DEFAULT_MODELS = {
    "directive": ["gemini-2.5-pro", "deepseek-v4-pro"],
    "report_directive": ["gemini-2.5-pro", "deepseek-v4-pro"],
    "factsheet": ["gemini-2.5-flash", "deepseek-flash"],
    "scoring": ["gemini-2.5-flash", "deepseek-flash"],
}


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


# ─────────────────────────────────────────────────────────────
# Fact Sheet — flash 티어의 대표 작업
# ─────────────────────────────────────────────────────────────
# ★ 왜 Fact Sheet 인가: flash 티어의 네 작업(채점·추출·자기검증·대본) 가운데 **코드가 혼자
#   채점할 수 있는** 것이 이것뿐이다. 자기검증은 그 자체가 LLM 판정이라 심사관 모델을 하나 더
#   끌어들이고, 그러면 무엇을 재는지 흐려진다.
#
# ★★ 채점 방법이 이 작업의 핵심이다: **정규화기가 얼마나 고쳐야 했는가**를 센다.
#   `normalize_factsheet` 는 모델이 스키마를 어겨도 조용히 고쳐 준다 — enum 을 기본값으로
#   되돌리고, 빠진 claim_id 를 지어 주고, 중복을 떼어 낸다. 그래서 최종 산출물만 보면 두
#   모델이 똑같아 보인다. 고친 **횟수**가 곧 "이 모델이 지시를 얼마나 안 지켰는가"이고,
#   그건 공짜로·객관적으로 셀 수 있다.
_ENUM_FIELDS = (
    ("claim_kind", config.CLAIM_KINDS, config.DEFAULT_CLAIM_KIND),
    ("effect_direction", config.EFFECT_DIRECTIONS, config.DEFAULT_EFFECT_DIRECTION),
    ("causal_strength", config.CAUSAL_STRENGTHS, config.DEFAULT_CAUSAL_STRENGTH),
)


def _generate_factsheet(paper: dict[str, Any], model: str) -> dict[str, Any]:
    """한 발. factsheet.extract 와 **같은 프롬프트**로 부르되 원본 응답도 함께 들고 온다."""
    set_text_purpose("factsheet")
    t0 = time.time()
    raw = call_json(model=model, system=F.FACTSHEET_SYSTEM,
                    user=F.factsheet_user_prompt(paper.get("title") or "",
                                                 paper.get("venue"),
                                                 paper.get("abstract") or ""))
    elapsed = time.time() - t0
    return {"raw": raw, "normalized": F.normalize_factsheet(raw), "elapsed_sec": elapsed}


def _score_factsheet(run: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    raw_claims = [c for c in (run["raw"].get("claims") or []) if isinstance(c, dict)]
    norm = run["normalized"]
    claims = norm.get("claims") or []

    # ① enum 위반 — 모델이 허용 토큰 밖의 값을 냈고 코드가 기본값으로 되돌린 횟수.
    enum_fixed = sum(
        1 for c in raw_claims for name, allowed, _ in _ENUM_FIELDS
        if str(c.get(name) or "").strip().lower() not in allowed)
    # ② claim_id 를 아예 안 붙인 항목.
    id_missing = sum(1 for c in raw_claims if not str(c.get(name := "claim_id") or "").strip())
    # ③ claim_id 중복 — 같은 ID 를 두 번 썼다.
    ids = [str(c.get("claim_id") or "").strip() for c in raw_claims]
    ids = [i for i in ids if i]
    id_dup = len(ids) - len(set(ids))
    # ④ evidence_grade 가 허용 밖.
    grade_bad = sum(1 for c in raw_claims
                    if str(c.get("evidence_grade") or "").strip().upper()
                    not in config.EVIDENCE_GRADES)

    return {
        "enum위반": enum_fixed,
        "claim_id누락": id_missing,
        "claim_id중복": id_dup,
        "등급값오류": grade_bad,
        # ⑤ 원문의 숫자를 원장이 지불하지 못한다 — 하류에서 그 숫자를 말하면 red 가 된다.
        #   ★★ **게이트가 보는 것과 같은 것을 본다**: `source_numbers` 는 Fact Sheet 를
        #     통째로 훑으므로 최상위 `numbers` 키가 비어도 claims 본문에 있으면 지불된다.
        #     처음엔 `len(norm["numbers"])` 를 맥락으로 찍었는데, 그게 0 인 것을 보고
        #     "숫자를 놓쳤다"고 읽을 뻔했다 — 실제로는 다섯 벌 모두 커버리지 1/1 이었다.
        #     **키 개수는 게이트가 쓰는 값이 아니다.**
        "숫자미지불": len(_source_nums(paper) - directive_audit.source_numbers(norm)),
        # ── 맥락: 얼마나 뽑았는가. 많이 뽑는 것이 곧 좋은 것은 아니다(프롬프트가
        #   "많이 뽑는 것이 아니라 고르는 것"이라고 말한다) — 그래서 점수가 아니라 맥락이다.
        #   더 뽑는 성질이 곧 출력 상한 절단의 원인이기도 하다(2026-09-19 실측).
        "_claim수": len(claims),
        "_미확인필드합": sum(len(c.get("missing_fields") or []) for c in claims),
        "_source_quote": sum(1 for c in claims if c.get("source_quote")),
        "_what_found": len(norm.get("what_found") or []),
        "_숫자커버": f"{len(_source_nums(paper) & directive_audit.source_numbers(norm))}/{len(_source_nums(paper))}",
        "_limitations": len(norm.get("limitations") or []),
    }


def _source_nums(paper: dict[str, Any]) -> set[str]:
    """초록이 지불하는 숫자. audit 이 쓰는 그 추출기로 뽑는다."""
    return directive_audit._numbers(paper.get("abstract") or "")


# ─────────────────────────────────────────────────────────────
# 리포트 지시서 — pro 티어의 **둘째** 자리
# ─────────────────────────────────────────────────────────────
# ★ 왜 `directive` 로 같이 못 재나: 프롬프트·스키마·게이트가 다르다. 리포트는 논증 단위
#   (financial_reasoning)를 화면으로 옮기고 EQ-V 계약을 추가로 받는다. 논문에서 나온
#   결과가 이 자리에도 적용된다는 보장이 없다 — flash 티어에서 실제로 **정반대**가
#   나왔다(2026-09-19: deepseek-flash 가 3회 중 1회 절단으로 죽었다).
#
# ★★ 채점은 논문과 **같은 함수**를 쓴다(`_score`). 그래야 두 자리의 숫자를 같은 눈으로
#   읽을 수 있다. 리포트에만 있는 계약(EQ-V)은 아래에서 더한다.
def _generate_report(draft_row: dict[str, Any], version_type: str,
                     model: str) -> dict[str, Any]:
    """한 발. `report_directive._generate_once` 와 **같은 순서**로 하되 재생성은 하지 않는다."""
    from engine import equity_visual, report_directive as RD

    user = RD.report_directive_user_prompt(draft_row, version_type)
    set_text_purpose("directive")
    t0 = time.time()
    obj = call_json(model=model, system=RD.REPORT_DIRECTIVE_SYSTEM, user=user,
                    max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS)
    elapsed = time.time() - t0

    # 본 경로와 같은 순서: 모델이 쓴 시퀀스 우선 → 꼬리표 → 공용 정규화.
    model_seqs = [s for s in (obj.get("visual_sequences") or []) if isinstance(s, dict)]
    if model_seqs:
        seqs = equity_visual.annotate(model_seqs, obj.get("cuts"),
                                      draft_row.get("financial_reasoning"))
    else:
        seqs = equity_visual.build_for_directive(obj.get("cuts"),
                                                 draft_row.get("financial_reasoning"))
    obj["visual_sequences"] = seqs
    d = D.normalize_directive(obj, version_type, cut_max_sec=config.CUT_MAX_SEC)
    return {"directive": d, "fact_sheet": draft_row.get("fact_sheet") or {},
            "skeleton": [], "seqs": seqs, "elapsed_sec": elapsed,
            "prompt_chars": len(RD.REPORT_DIRECTIVE_SYSTEM) + len(user)}


def _score_report(run: dict[str, Any]) -> dict[str, Any]:
    """논문 채점 + 리포트 전용 계약(EQ-V). 낮을수록 좋다."""
    from engine import equity_contract, equity_visual

    sc = _score(run)
    seqs = run["seqs"]
    # ★ `seqs` 를 본다 — 정규화가 진단 필드(reasoning_id·precision_layer)를 버리므로
    #   헤더에서 읽으면 이 검사가 영영 0건이 된다(report_directive 주석과 같은 이유).
    sc["EQ계약위반"] = len(equity_contract.block_reasons(seqs))
    sc["EQ경고"] = len(equity_contract.warnings(seqs))
    sc["화면투영경고"] = len(equity_visual.screen_warnings(seqs))
    # 맥락: 모델이 시퀀스를 **직접 썼는가**(2026-09-19부터 그게 정본이다). 폴백이면 0.
    sc["_모델이쓴시퀀스"] = len(seqs)
    return sc


# ─────────────────────────────────────────────────────────────
# 5축 채점 — flash 티어에서 **호출이 가장 많은** 자리
# ─────────────────────────────────────────────────────────────
# ★ 왜 이 자리를 따로 재나(2026-09-22 운영자 지시): 딥시크는 제미나이보다 2.4배 느린데
#   (지시서 실측 309초 vs 110초) **채점은 밤 21:10 크론이 혼자 돈다** — 아무도 안 기다린다.
#   그리고 호출이 제일 많다(원장 998회 중 대부분). 느려도 되는 자리 × 호출 최다 =
#   단가 차이가 가장 크게 작동하는 자리다.
#
# ★★ 채점법: **정규화기가 얼마나 고쳐야 했는가**를 센다 — Fact Sheet 하네스와 같은 규율이다.
#   `scoring.parse_axes` 는 모델이 스키마를 어겨도 조용히 고쳐 준다(범위 밖 점수를 자르고,
#   빠진 축을 0 으로 채우고, 없는 enum 을 기본값으로 되돌린다). 그래서 최종 산출물만 보면
#   두 모델이 똑같아 보인다. **고친 횟수가 곧 "지시를 얼마나 안 지켰는가"** 이고 공짜로 셀 수 있다.
#
# ★ 축 점수 자체의 옳고 그름은 여기서 판정하지 않는다 — 그건 사람 판단이고, 심사관 모델을
#   하나 더 끌어들이면 무엇을 재는지 흐려진다(Fact Sheet 하네스 주석과 같은 이유).
#   대신 **두 모델이 같은 논문에 얼마나 다른 점수를 주는가**를 맥락으로 남긴다.
def _generate_scoring(paper: dict[str, Any], model: str) -> dict[str, Any]:
    """한 발. `score._score_one` 과 **같은 순서**로 하되 저장하지 않는다."""
    from engine import scoring

    set_text_purpose("judge")
    t0 = time.time()
    raw = call_json(
        model=model,
        system=scoring.SCORING_SYSTEM,
        user=scoring.scoring_user_prompt(
            paper.get("title") or "", paper.get("venue"), paper.get("abstract") or ""),
    )
    elapsed = time.time() - t0
    return {"raw": raw, "axes": scoring.parse_axes(raw), "elapsed_sec": elapsed}


_AXES = ("surprise", "explainability", "relatability", "significance")


def _score_scoring(run: dict[str, Any]) -> dict[str, Any]:
    """낮을수록 좋다(문제 개수). `_` 항목은 점수가 아니라 맥락."""
    raw, axes = run["raw"], run["axes"]

    missing = [a for a in _AXES if not isinstance(raw.get(a), (int, float))]
    # 범위를 벗어난 축 — 정규화기가 잘라 준다(그래서 산출물만 보면 안 보인다).
    out_of_range = [a for a in _AXES
                    if isinstance(raw.get(a), (int, float)) and not 0 <= float(raw[a]) <= 10]
    # 사람이 읽는 칸이 비었는가. 승인 화면이 이걸 보여 준다.
    empty_text = [k for k in ("title_ko", "one_liner_ko", "rationale")
                  if not str(raw.get(k) or "").strip()]
    prod = raw.get("production")
    return {
        "축누락": len(missing),
        "축범위벗어남": len(out_of_range),
        "설명칸빔": len(empty_text),
        "제작준비도누락": 0 if isinstance(prod, dict) and prod else 1,
        # ── 맥락(점수 아님)
        "_축점수": [axes.get(a) for a in _AXES],
        "_한줄": str(axes.get("one_liner_ko") or "")[:34],
    }


def _problem_total(sc: dict[str, Any]) -> int:
    """문제 개수 항목만 합산. `_` 로 시작하는 맥락 항목은 더하지 않는다."""
    return sum(v for k, v in sc.items() if not k.startswith("_") and isinstance(v, int))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default="", help="논문 id, 또는 report_directive 면 리포트 id")
    ap.add_argument("--job", default="directive", choices=sorted(DEFAULT_MODELS),
                    help="directive=논문 지시서(pro), report_directive=리포트 지시서(pro), "
                         "factsheet=flash 티어 근거 추출, scoring=5축 채점(호출 최다)")
    ap.add_argument("--version-type", default="photo")
    ap.add_argument("--models", default="", help="비우면 그 작업의 현행 모델 + DeepSeek 대응 티어")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="대본 있는 draft 목록만 보고 끝낸다")
    args = ap.parse_args()

    if args.list:
        if args.job == "report_directive":
            from engine import report_db
            rows = report_db.client().table("report_drafts").select(
                "report_id, created_at").order("created_at", desc=True).limit(15).execute().data or []
            for r in rows:
                print(f"  {r['report_id']}  {str(r.get('created_at'))[:19]}")
            return
        rows = db.client().table("drafts").select("paper_id, created_at").order(
            "created_at", desc=True).limit(15).execute().data or []
        for r in rows:
            print(f"  {r['paper_id']}  {str(r.get('created_at'))[:19]}")
        return

    if not args.paper:
        ap.error("--paper 를 주거나 --list 로 고르세요")

    if args.job == "directive":
        source = db.get_draft_full(args.paper)
        if not source:
            raise SystemExit(f"draft 없음: {args.paper}")
    elif args.job == "report_directive":
        from engine import report_db
        source = report_db.get_report_draft(args.paper)
        if not source:
            raise SystemExit(f"report_draft 없음: {args.paper} (--paper 에 report_id 를 준다)")
    elif args.job == "scoring":
        resp = db.client().table("papers").select(
            "id, title, venue, abstract").eq("id", args.paper).maybe_single().execute()
        source = (resp.data if resp else None) or {}
        if not (source.get("abstract") or "").strip():
            raise SystemExit(f"초록 없음: {args.paper}")
    else:
        resp = db.client().table("papers").select(
            "id, title, venue, abstract").eq("id", args.paper).maybe_single().execute()
        source = (resp.data if resp else None) or {}
        if not (source.get("abstract") or "").strip():
            raise SystemExit(f"초록 없음: {args.paper}")

    models = ([m.strip() for m in args.models.split(",") if m.strip()]
              or list(DEFAULT_MODELS[args.job]))
    results: list[dict[str, Any]] = []
    for rep in range(args.repeat):
        for model in models:
            print(f"[{rep + 1}/{args.repeat}] {args.job} / {model} ...", flush=True)
            try:
                # ★ 산출물 원본을 남긴다. 채점기를 고칠 때마다 유료 호출을 다시 하는 것은
                #   낭비이고, 무엇보다 **다시 뽑으면 다른 결과**라 예전 점수와 비교가 안 된다.
                OUT.mkdir(parents=True, exist_ok=True)
                if args.job == "directive":
                    run = _generate(source, args.version_type, model)
                    keep, sc = run["directive"], _score(run)
                elif args.job == "report_directive":
                    run = _generate_report(source, args.version_type, model)
                    keep, sc = run["directive"], _score_report(run)
                elif args.job == "scoring":
                    run = _generate_scoring(source, model)
                    keep, sc = run["raw"], _score_scoring(run)
                else:
                    run = _generate_factsheet(source, model)
                    keep, sc = run["raw"], _score_factsheet(run, source)
                (OUT / f"{args.job}-{model}-{rep + 1}.json").write_text(
                    json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
                sc["_모델"], sc["_회차"] = model, rep + 1
                sc["_초"] = round(run["elapsed_sec"], 1)
                sc["_문제합"] = _problem_total(sc)
                results.append(sc)
                extra = (f"컷 {sc['_컷수']:>2}" if args.job.endswith("directive")
                         else (f"축 {sc['_축점수']}" if args.job == "scoring"
                               else f"claim {sc['_claim수']:>2}"))
                print(f"    문제합 {sc['_문제합']:>3}  {extra}  {sc['_초']}s")
            except Exception as exc:     # noqa: BLE001 — 한 팔이 죽어도 다른 팔은 본다
                print(f"    실패: {type(exc).__name__}: {str(exc)[:200]}")
                results.append({"_모델": model, "_회차": rep + 1,
                                "_실패": f"{type(exc).__name__}: {exc}"})

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"모델실측-{args.job}-{stamp}.json"
    path.write_text(json.dumps(
        {"paper_id": args.paper, "job": args.job, "version_type": args.version_type,
         "models": models, "repeat": args.repeat, "results": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {path}")

    # 표. 실패한 팔은 숨기지 않는다 — 실패도 결과다.
    ok = [r for r in results if "_실패" not in r]
    if ok:
        keys = [k for k in ok[0] if not k.startswith("_")]
        head = "".join(f"{(r['_모델'][:13] + '#' + str(r['_회차'])):>18}" for r in ok)
        print(f"\n{'항목':<16}{head}")
        ctx = (["_컷수", "_총초", "_invest컷"] if args.job == "directive"
               else ["_claim수", "_숫자커버", "_미확인필드합", "_source_quote"])
        for k in keys + ["_문제합"] + ctx + ["_초"]:
            print(f"{k:<16}" + "".join(f"{str(r.get(k, '-')):>18}" for r in ok))
    for r in results:
        if "_실패" in r:
            print(f"\n실패 — {r['_모델']} #{r['_회차']}: {r['_실패'][:300]}")


if __name__ == "__main__":
    main()
