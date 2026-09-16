"""시퀀스 등급제 — **품질 의도(시퀀스)에서 실행 품질(컷)로** (v2 Phase B).

무엇을 푸는가: 예전에는 영상 예산이 **컷 순서 선착순**이었다
(`directive.enforce_mode_video_budget` — 앞 컷이 먼저 먹고 뒤는 스틸로 강등).
중요도를 전혀 안 봤다. 실측(2026-08-31 ESS 지시서)에서 `컷 9 스틸로 강등`·
`컷 10 스틸로 강등` 로그가 그대로 찍혔다 — 기전 시퀀스가 뒤에 놓였으면 그게 잘렸다.

이 모듈은 그 반대를 한다: **무엇을 설명하는 컷인가**로 실행 품질을 정한다.

    Visual Sequence ──→ 품질 의도(어떤 장면에 투자할 것인가)
                            ↓
    resolved_visual_plan ──→ 라우터 정본(이 컷이 실제로 무엇을 하는가)
                            ↓
                      effective_tier(컷의 실행 품질 + 시간)

★★ **canonical router 를 우회하지 않는다** (코덱스 리뷰 P0-1). 시퀀스 소속만 보면
  같은 기전 시퀀스 안의 **연결 컷·CTA 도 8초 invest 를 받는다.** 라우터는 이미 컷
  단위로 그것을 갈라 놓았다(`connective_in_world`) — 등급이 그 판정을 다시 뒤집으면
  라우터가 두 번 일하고 결과는 어긋난다.

★ **등급은 길이가 아니라 Quality Profile 이다**(리뷰 §7). 8초를 주는 것과 8초를
  제대로 쓰는 것은 다른 문제다 — 비트 수·카메라 플랜·상태 변화·후보 개수까지가
  등급의 내용이고, 그 표는 `config.TIER_PROFILE` 에 있다.

★ 순수 모듈이다 — 파일·네트워크·DB·LLM 없음. 입력은 컷과 헤더뿐이다.
"""

from __future__ import annotations

from typing import Any

from . import config, temporal_plan, visual_sequence


# invest 자격 미달 사유 코드(정본). 화면·원장이 이 문자열을 그대로 쓴다.
TIER_REASONS: tuple[str, ...] = (
    "no_sequence",              # 이 컷은 어떤 시퀀스에도 속하지 않는다
    "not_a_progression",        # 시퀀스가 구조적으로 진행하지 않는다(자기보고 아님)
    "plan_not_mechanism",       # 라우터 정본이 이 컷을 기전으로 보지 않는다
    "connective_cut",           # 세계만 물려받는 연결 컷 — 기전 도해가 아니다
    "claim_unlinked",           # 지불하는 주장이 없다
    "claim_mismatch",           # 컷과 stage 의 주장이 어긋난다
    "temporal_contract_unmet",  # 8초를 채울 연출 계약(비트·카메라·변화)이 없다
)


def _plan(cut: dict[str, Any]) -> dict[str, Any]:
    plan = cut.get("resolved_visual_plan")
    return plan if isinstance(plan, dict) else {}


def _sequence_of(cut: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    """이 컷이 속한 시퀀스. 없으면 빈 dict."""
    ref = str(_plan(cut).get("sequence_ref") or "")
    if not ref:
        return {}
    for seq in (header or {}).get("visual_sequences") or []:
        if str(seq.get("sequence_id") or "") == ref:
            return seq
    return {}


def invest_blockers(cut: dict[str, Any], header: dict[str, Any]) -> list[str]:
    """invest 자격을 막는 사유 전부. 빈 목록이면 자격이 있다.

    ★★ 조건들의 **교집합**이다(기획서 §3, 리뷰 §6 — 단 ②는 실측으로 뺐다. 아래 참조). 하나만 봐도 통과시키면
      "설명 가치가 낮은 컷 + 남의 claim_id + 형식적 progression" 으로 8초를 훔칠 수
      있다. 조건을 모아 두는 이유는 사유를 **개별로 남기기** 위해서다 —
      "왜 이 컷이 invest 가 아닌가"를 운영자가 읽을 수 있어야 한다.

    ★ 전부 **코드가 판정한 것**만 본다. 모델이 붙인 `sequence_role` 라벨은 **쓰지 않는다** —
      골든B 가 6 stage 진행을 `RESULT_SEQUENCE` 라 라벨한 실측이 그 이유다(아래 ②).
      구조 판정(`sequence_is_progression`)과 라우터 정본이 대신 답한다.
    """
    out: list[str] = []
    seq = _sequence_of(cut, header)
    if not seq:
        return ["no_sequence"]

    # ① 구조 판정 — 라벨이 아니라 상태가 실제로 진행하는가.
    if not visual_sequence.sequence_is_progression(seq):
        out.append("not_a_progression")
    # ② ~~시퀀스 역할 라벨이 MECHANISM 인가~~ → **검사하지 않는다.**
    #
    #   ★★ 코덱스 리뷰 §6 은 조건 목록에 "sequence role == MECHANISM" 을 넣었지만,
    #     그대로 구현하니 **이 저장소가 이미 한 번 고친 결함이 그대로 재현됐다**
    #     (2026-08-31 골든B 실측):
    #
    #       골든B 시퀀스: 6 stage 진행 · 라우터는 6컷 전부 MECHANISM_SEQUENCE 판정
    #       그런데 모델이 붙인 라벨은 `RESULT_SEQUENCE`
    #       → 라벨을 믿으면 **진짜 기전 시퀀스가 통째로 invest 자격을 잃는다**
    #
    #     이것이 계획서 §9-2 **S4** 가 기록한 바로 그 사고다:
    #       "라벨 RESULT_SEQUENCE → 지표 0. 그런데 라우터는 7컷을 MECHANISM_SEQUENCE 로
    #        판정했다. 라우터만 고치고 지표는 안 고쳤다."
    #     조치도 이미 정해져 있다 — "`sequence_role` 은 진단용 메타데이터로 강등."
    #
    #   ★ 리뷰의 지적도 코드·산출물과 대조한 뒤 반영한다(§9-0 규율). 여기서는 리뷰의
    #     항목이 저장소의 확정된 결정과 충돌했고, 실측이 저장소 쪽 손을 들어 줬다.
    #     그리고 리뷰의 **본래 의도**(canonical router 를 우회하지 말 것)는 아래 ③이
    #     이미 지킨다 — 라우터의 base 는 라벨이 아니라 구조로 계산된 값이다.

    plan = _plan(cut)
    reasons = [str(r) for r in (plan.get("reasons") or [])]
    # ③ 라우터 정본이 이 컷을 기전으로 판정했는가.
    if str(plan.get("base") or "") != "MECHANISM_SEQUENCE":
        out.append("plan_not_mechanism")
    # ④ 세계만 물려받는 연결 컷은 기전 도해가 아니다(리뷰 P0-1 의 핵심).
    if "connective_in_world" in reasons:
        out.append("connective_cut")
    # ⑤ 지불하는 주장이 있는가.
    if not (cut.get("claim_ids") or []):
        out.append("claim_unlinked")
    # ⑥ 컷과 stage 의 주장이 어긋나지 않는가(라우터가 이미 경고로 남긴다).
    if "cut_claim_not_in_stage" in reasons:
        out.append("claim_mismatch")
    # ⑦ 8초를 **채울 계획**이 있는가(TC-1, Phase E2).
    #   ★ 이것은 비용 강등이 아니라 **품질 계약 미이행**이다. 돈을 아끼려는 것이 아니라,
    #     채울 내용이 없는 컷에 8초를 주면 그 시간이 정지 화면이 되기 때문이다.
    #     "8초를 주는 것과 8초를 제대로 쓰는 것은 다른 문제"(코덱스 리뷰 §7).
    if temporal_plan.evaluate(cut, "invest"):
        out.append("temporal_contract_unmet")
    # ★ 사유를 **중요한 순서로** 정렬한다(TIER_REASONS 순). 운영자는 첫 줄을 읽는다 —
    #   "시퀀스가 없다"와 "주장이 안 붙었다"는 고치는 방법이 다르고 앞의 것이 먼저다.
    #   목록 밖 코드가 생기면 맨 뒤로 밀리며 드러난다(오타가 조용히 통과하지 않는다).
    return sorted(out, key=lambda r: TIER_REASONS.index(r)
                  if r in TIER_REASONS else len(TIER_REASONS))


def effective_tier(cut: dict[str, Any], header: dict[str, Any] | None = None) -> dict[str, Any]:
    """이 컷의 **실행 품질 등급**. 반환: {tier, reasons, defaulted}.

    등급제 밖 버전이면 등급을 매기지 않는다(`tier=""`) — 종전 경로가 그대로 돈다.

    강등 규칙:
      invest 자격 미달 → 시퀀스에 속해 있으면 standard, 아니면 economy.
      ★ 이것은 **비용 강등이 아니라 품질 판정**이다. 기전을 설명하지 않는 컷에
        8초를 주는 것이 낭비여서가 아니라, 줘 봐야 채울 내용이 없기 때문이다.

    `defaulted` 는 "판정 근거가 없어 기본값으로 채웠다"는 표시다 — 시퀀스 자체가
    없는 경우다. 판정해서 내려간 것(미달)과 구분한다: 기본값도 정본으로 읽히므로
    표시가 필요하다(계획서 §9-10 교훈).
    """
    header = header or {}
    if not config.tiering_enabled(str(header.get("version_type") or "")):
        return {"tier": "", "reasons": [], "defaulted": False}

    blockers = invest_blockers(cut, header)
    if not blockers:
        return {"tier": "invest", "reasons": [], "defaulted": False}
    if blockers == ["no_sequence"]:
        return {"tier": "economy", "reasons": blockers, "defaulted": True}
    # 시퀀스 안에 있으나 기전 컷은 아니다 — 세계는 잇되 연출 계약은 요구하지 않는다.
    return {"tier": "standard", "reasons": blockers, "defaulted": False}


def clip_sec_for(cut: dict[str, Any], header: dict[str, Any] | None = None,
                 *, version_cap: int | None = None) -> int:
    """이 컷이 살 클립 길이(초). 등급이 정하고, 버전 상한을 넘지 않는다.

    ★ 등급제 밖이면 0 을 돌려준다 — 호출측이 종전 로직(나레이션 기반 티어)을 쓴다.
      여기서 기본값을 지어내면 등급제와 종전 경로가 조용히 섞인다.
    """
    tier = effective_tier(cut, header)["tier"]
    if not tier:
        return 0
    want = int(config.tier_profile(tier)["clip_sec"])
    cap = int(version_cap if version_cap is not None
              else config.clip_tier_max(str((header or {}).get("version_type") or "")))
    return min(want, cap)


def candidates_for(cut: dict[str, Any], header: dict[str, Any] | None = None) -> int:
    """이 컷을 몇 번 생성해 고를 것인가. 등급제 밖이면 1.

    ★ 벤치마크가 "8초를 뽑아 좋은 3초만 쓴다"고 한 그 선택 단계다(리뷰 §9).
      생성은 확률적이라 1발과 2발-선택은 **품질 상한**이 다르다.
    """
    tier = effective_tier(cut, header)["tier"]
    if not tier:
        return 1
    return max(1, int(config.tier_profile(tier)["candidates"]))


def summary(cuts: list[dict[str, Any]], header: dict[str, Any] | None = None) -> dict[str, Any]:
    """편 단위 등급 요약. ⑤ 화면·원장이 같은 숫자를 본다."""
    counts: dict[str, int] = {t: 0 for t in config.SEQUENCE_TIERS}
    defaulted = 0
    for c in cuts or []:
        d = effective_tier(c, header)
        if not d["tier"]:
            continue
        counts[d["tier"]] = counts.get(d["tier"], 0) + 1
        defaulted += 1 if d["defaulted"] else 0
    return {"tiers": counts, "tier_defaulted": defaulted}


def contract_shortfall(cuts: list[dict[str, Any]],
                       header: dict[str, Any] | None = None) -> list[int]:
    """**연출 계약만 못 채워서** invest 를 놓친 컷 번호들 (TC-1, 작업명세서 §3).

    ★★ 왜 따로 세는가(2026-09-03 실측): 이 컷들은 자격이 **있다** — 기전 시퀀스에 속하고,
      진행하고, 라우터가 기전으로 보고, 주장도 붙어 있다. 딱 하나, `temporal_plan` 비트를
      1개만 써서 8초를 놓친다. 실측 두 편에서 이것이 **압도적 1위 강등 사유**였다:
        성격조합  13컷 중 11컷 · Moon Impactor 12컷 중 10컷(invest 0개)
      즉 등급제가 "기전에 투자한다"는 목적을 거의 달성하지 못하고 있었다.

    ★ 원인은 모델의 태만이 아니라 **순서**다. 어떤 컷이 invest 가 될지는 시퀀스·라우터를
      보고 **코드가 나중에** 정하는데, 모델은 그걸 모르는 채로 비트를 쓴다. 그래서 기본값
      1개를 쓴다 — 닭과 달걀이다. 작업명세서 TC-1 이 "미달 → **재생성 1회** → 강등"이라고
      쓴 이유가 이것이다: 1차 생성이 구조를 드러내면, 2차에서 **어느 컷에** 비트가 필요한지
      찍어서 알려줄 수 있다.

    ★ 반환은 컷 번호뿐이다(순수). 되먹임 문구는 temporal_plan.shortfall_feedback 이 만든다.
    """
    out: list[int] = []
    for cut in cuts or []:
        blockers = invest_blockers(cut, header or {})
        # 계약 하나만 걸려 있는 컷 = 비트만 채우면 invest 가 된다.
        if blockers == ["temporal_contract_unmet"]:
            try:
                out.append(int(cut.get("cut_no")))
            except (TypeError, ValueError):
                continue
    return out
