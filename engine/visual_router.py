"""Visual Router — 무엇을 어떤 방식으로 보여줄 것인가 (v3 Phase 2).

리뷰 §9 가 v3 에서 가장 중요한 판단으로 꼽은 것이 이것이다: **모든 것을 3D 로 만들지 않는다.**

    MECHANISM_SEQUENCE  원리·구조·인과·이동 — 같은 세계가 단계적으로 변한다
    CODE_VIZ            정확한 수치·비율·비교 — 코드가 그린다
    REALITY             실제 대상·현장 앵커
    OVERLAY             출처·범위·단서 카드

★ 분업이 이 모듈의 존재 이유다. LLM 은 컷에 **beat 라벨만** 단다("이건 결과다", "이건
  개입이다"). 그것을 무엇으로 보여줄지는 **코드가 정한다.** 라우팅까지 LLM 에 맡기면
  근거가 얇은 컷에도 3D 기전이 붙는다 — v2 가 정확히 그랬다: 초록만 있는 논문에
  코→뇌 분자 이동을 그렸고, 그 경로는 초록에 없었다.

★ 라우터가 소비하는 두 입력이 v2 에는 없었다:
    ① source_depth   — 오늘 만든 paper_evidence 가 Fact Sheet 에 남긴다.
                       초록만이면 절차·장비·전달경로를 그릴 근거가 없다(작업지시서 §12).
    ② 정량 유무      — Phase 0 실측: 생성 모델은 개수를 못 지킨다. 수치는 항상 코드로.

순수 모듈. 네트워크·DB 없음.
"""

from __future__ import annotations

import re
from typing import Any

from . import config, visual_sequence

# 나레이션이 "화면이 정확히 말해야 하는 수치"를 담고 있는가.
# ★ photo_contract._SPOKEN_NUMBER 와 목적이 다르다: 저기는 "화면 카드가 있는가"를 보고,
#   여기는 "이 컷을 3D 로 그리면 안 되는가"를 본다. 그래서 단위 목록을 공유하지 않고
#   더 넓게 잡는다 — 애매하면 코드 시각화로 보내는 쪽이 안전하다(숫자는 틀리면 안 된다).
_HAS_NUMBER = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|퍼센트|배|명|건|개|초|분|시간|년|개월|일|원|달러|km|kg|m\b)"
    r"|\d+(?:[.,]\d+)?\s*(?:percent|times|fold|people|participants?|seconds?|minutes?|"
    r"hours?|days?|years?|dollars?)\b",
    re.I)
# 연도·날짜는 **측정값이 아니다.** 먼저 지운 뒤에 수치를 찾는다.
#   ★ 이걸 안 하면 "2026년에 관측했습니다" 가 CODE_VIZ 로 가고, 그러면 거의 모든 컷이
#     차트가 된다 — 시퀀스가 사라진다. 옳게 한 것을 벌하는 라우팅은 무시당한다.
_YEAR_LIKE = re.compile(r"\b(?:19|20)\d{2}\s*(?:년|년도)?", re.I)


def sanitize_beat(value: Any) -> str:
    tok = str(value or "").strip().upper()
    return tok if tok in config.BEAT_KINDS else config.DEFAULT_BEAT_KIND


def speaks_a_number(cut: dict[str, Any]) -> bool:
    """이 컷이 **화면이 정확히 말해야 하는 수치**를 말하는가.

    연도는 뺀다 — 측정값이 아니고, 넣으면 날짜를 언급하는 거의 모든 컷이 차트가 된다.
    """
    text = f"{cut.get('narration_ko') or ''} {cut.get('narration_en') or ''}"
    return bool(_HAS_NUMBER.search(_YEAR_LIKE.sub(" ", text)))


# ★ 정본은 visual_sequence 다. 라우터·계약·지표가 **같은 함수**를 부르게 한다
#   (코덱스 리뷰 S4: 라우터만 고치고 지표를 안 고쳐 같은 지시서가 서로 다른 답을 냈다).
sequence_is_progression = visual_sequence.sequence_is_progression


def _claims_of(obj: Any) -> set[str]:
    return {str(x).strip() for x in ((obj or {}).get("claim_ids") or []) if str(x).strip()}


def route(cut: dict[str, Any], *, source_depth: str = "none",
          stage: dict[str, Any] | None = None,
          sequence: dict[str, Any] | None = None) -> dict[str, Any]:
    """컷 하나 → **resolved visual plan**. 코드가 판정한다.

    ★★ 종전과 무엇이 다른가(코덱스 리뷰 R1·R2·S5, 2026-08-30) — 세 가지가 뒤집혔다.

      ① **표현은 택1 이 아니라 합성이다.** 수치를 말한다고 세계를 끊지 않는다.
         세계(base)는 그대로 두고 그 위에 **코드 렌더 정밀 레이어**를 얹는다.
         ✗ 종전: 컷9("7분 주기가 8초 변했다") → 우주 시퀀스 종료, 독립 차트
         ✓ 지금: 같은 로켓이 계속 돌고 + 정확한 수치는 코드 오버레이가 말한다
         Phase 0 이 실측한 것은 "생성모델은 개수를 못 지킨다"이지 "수치가 있는 장면은
         3D 로 만들면 안 된다"가 아니었다. 실측을 과대해석한 것을 되돌린다.

      ② **source_depth 는 미디어를 바꾸지 않는다 — 구체성을 제한한다.**
         `abstract_only ≠ 기전 시각화 금지`. 후퇴는 근거 없는 컷을 막지 못하면서
         (골든A 는 REALITY 로 후퇴하고도 "사전 등록된 무작위 실험"을 그렸다) 정상 컷만
         벌했다. 이제 `detail_restrictions` 를 실어 보내고, **원문 대조**가 판정한다.

      ③ **시퀀스 소속을 무조건 믿지 않는다.** 컷이 stage 의 cut_refs 에 있다는 것만으로
         기전 시퀀스가 되면, 골든B 의 CTA 컷15("댓글로 의견을 남겨주세요")가 기전 stage 가
         된다(실제로 그렇게 됐다). factual stage 는 **주장이 겹칠 때만** 물려준다.

    반환의 `reasons` 는 판정의 흔적이다. 조용히 강등하지 않는다.
    """
    beat = sanitize_beat(cut.get("beat"))
    reasons: list[str] = []
    in_progression = bool(stage) and sequence_is_progression(sequence)

    # ③ 시퀀스 소속 — **세계를 물려받는 것**과 **기전 컷이 되는 것**을 나눈다.
    #
    #   ★ 둘을 붙여 두면 어느 쪽으로 틀려도 손해다:
    #     - 소속만으로 기전이 되면 → 골든B 의 CTA 컷15("댓글 남겨주세요")가 기전 stage 가 된다
    #     - 주장 교집합을 세계 상속의 조건으로 걸면 → 골든B 컷2·4 처럼 **정상 연결 컷**이
    #       세계 밖으로 튕겨 나간다(컷4 "정체는 팰컨 9 상단부입니다"는 그 시퀀스의 일부다)
    #
    #   그래서: **세계는 stage 에 속하면 물려받고**(연속성은 끊지 않는다),
    #   **기전 컷 자격은 그 컷이 사실 주장을 지불할 때만** 준다.
    #   주장이 아예 없는 컷(연결·CTA)은 배경만 이어받는다 — 리뷰 §10 의 `RETURN_WORLD`·
    #   `background_world_ref` 처리와 같은 뜻이다.
    inherits = False
    if in_progression:
        cut_claims = _claims_of(cut)
        if not cut_claims:
            # 사실 주장을 지불하지 않는 컷 — 기전 도해를 붙일 근거가 없다. 세계만 잇는다.
            reasons.append("connective_in_world")
        else:
            inherits = True
            reasons.append("in_visual_sequence")
            # 주장이 있는데 stage 와 겹치지 않는다 — 세계는 잇되 운영자에게 보인다.
            #   차단하지 않는 이유: 둘 다 사실 컷이고, 여기서 끊으면 옳게 만든 시퀀스가
            #   모델의 claim 태깅 실수 하나로 조각난다(골든B 컷4 가 실제 사례다).
            if _claims_of(stage) and not (_claims_of(stage) & cut_claims):
                reasons.append("cut_claim_not_in_stage")

    base = "MECHANISM_SEQUENCE" if inherits else config.BEAT_DEFAULT_TREATMENT.get(beat, "REALITY")

    # ① 정확한 수치 — 세계를 끊지 않고 **정밀 레이어**로 얹는다.
    precision = ""
    if speaks_a_number(cut):
        if base in config.PRECISION_LAYER_REDUNDANT_BASES:
            reasons.append("number_is_the_visual")      # 화면 전체가 이미 그래픽이다
        else:
            precision = "CODE_OVERLAY"
            reasons.append("number_needs_precision_layer")

    # ② 근거 깊이 — 미디어가 아니라 **구체성**을 제한한다.
    restrictions = list(config.DEPTH_DETAIL_RESTRICTIONS.get(str(source_depth or "none"), ()))
    if restrictions:
        reasons.append(f"depth_restricts_detail:{source_depth or 'none'}")

    return {
        "cut_no": int(cut.get("cut_no") or 0),
        "beat": beat,
        # ★ 모델이 beat 를 **실제로 선언했는가.** 선언이 없으면 위의 base 는 기본값에서
        #   합성된 것이지 판정이 아니다 — 비용 산정처럼 돈이 걸린 소비자는 이 구분을 봐야
        #   한다(실측: beat 없는 만화식 지시서 3컷이 전부 CODE_VIZ 로 세어졌다).
        "beat_declared": bool(cut.get("beat_declared",
                                      str(cut.get("beat") or "").strip().upper()
                                      in config.BEAT_KINDS)),
        "base": base,
        "precision_layer": precision,
        "representation_mode": str((stage or {}).get("representation_mode")
                                   or config.DEFAULT_REPRESENTATION_MODE),
        "sequence_ref": str((sequence or {}).get("sequence_id") or ""),
        "world_ref": str(((sequence or {}).get("world") or {}).get("world_id") or ""),
        "stage_ref": str((stage or {}).get("stage_id") or ""),
        "claim_refs": sorted(_claims_of(cut)),
        "detail_restrictions": restrictions,
        "reasons": reasons,
        # 하위호환 — 옛 필드를 읽는 화면·테스트가 있다. base 를 그대로 싣는다.
        "treatment": base,
    }


def route_all(cuts: list[dict[str, Any]], *, source_depth: str = "none",
              sequences: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """컷 목록 → resolved plan 목록. 시퀀스를 주면 소속 컷이 그 stage 를 물려받는다."""
    by_cut = visual_sequence.cut_to_stage(sequences or [])
    out: list[dict[str, Any]] = []
    for c in cuts:
        entry = by_cut.get(int(c.get("cut_no") or 0)) or {}
        seq = entry.get("_sequence")
        out.append(route(c, source_depth=source_depth,
                         stage=(entry or None), sequence=seq))
    return out


def source_depth_of(fact_sheet: dict[str, Any] | None) -> str:
    """Fact Sheet 에 남은 확보 수준. 없으면 'none' — 근거 없이 기전을 그리지 않는다.

    ★ paper_evidence.attach_evidence 가 `source_provenance` 를 남긴다. 그것이 없는
      Fact Sheet(엣지 경로로 만들어진 초안)는 대조 자체가 안 돈 것이므로 'none' 이 맞다.
    """
    prov = (fact_sheet or {}).get("source_provenance")
    if not isinstance(prov, dict):
        return "none"
    return str(prov.get("source_depth") or "none")


def routing_summary(routed: list[dict[str, Any]]) -> dict[str, Any]:
    """운영자·로그가 같은 숫자를 보게 한다."""
    counts: dict[str, int] = {t: 0 for t in config.VISUAL_TREATMENTS}
    for r in routed:
        counts[r["base"]] = counts.get(r["base"], 0) + 1
    return {
        "treatments": counts,
        # ★ 수치가 세계를 끊지 않고 **얹힌** 횟수. 종전 지표(number_routed_to_code)는
        #   "몇 컷이 차트로 튕겨 나갔는가"를 셌다 — 그 동작 자체가 없어졌다.
        "precision_layer_count": sum(1 for r in routed if r["precision_layer"]),
        "in_sequence": sum(1 for r in routed if "in_visual_sequence" in r["reasons"]),
        "connective_in_world": sum(1 for r in routed if "connective_in_world" in r["reasons"]),
        # 시퀀스 stage 에 들어 있으나 주장이 겹치지 않아 물려받지 못한 컷(코덱스 리뷰 §10).
        "cut_claim_mismatch": sum(1 for r in routed if "cut_claim_not_in_stage" in r["reasons"]),
        "detail_restricted": sum(1 for r in routed if r["detail_restrictions"]),
    }
