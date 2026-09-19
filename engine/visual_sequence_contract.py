"""Visual Sequence 계약 — VSEQ-1~7 결정론적 검사 (v3 Phase 1).

무엇을 푸는가: `photo_contract.py` 는 컷 하나의 **문자열**을 본다 — "프롬프트에 cutaway 라는
단어가 있는가". 그것으로는 시퀀스가 성립하는지 알 수 없다. 리뷰(§14)가 그 한계를 정확히
지적했다:

    나쁜 검사: visual_prompt 에 "cutaway" 라는 단어가 있는가?
    좋은 검사: Stage 가 2개 이상인가? 이전 stage 의 개체·상태가 다음으로 이어지는가?
              state_before 와 state_after 가 실제로 다른가?

그래서 이 모듈은 **구조**를 본다. photo_contract 는 폐기하지 않고 남긴다 — 명백한 금지
표현(차트 요구·역할명 누출)을 잡는 것은 여전히 문자열 검사의 몫이고, 둘은 보완 관계다.

★ 이 계약이 판정할 수 있는 것과 없는 것을 처음부터 갈라 둔다(정직성):
    여기서 판정   선언의 구조 — stage 수·참조 무결성·상태 변화 선언·정량 침범
    여기서 불가   그 선언이 **화면에서 참인가** — 렌더 뒤 멀티모달 QA 의 몫(Phase 3)

  Phase 0 실측에서 이 경계가 왜 중요한지 확인됐다: 멀티모달 판정 모델은 identity·world 는
  정확했지만 **개수는 의도를 따라 읽었다**("아홉 개"라고 답했는데 화면엔 없었다).
  그래서 정량은 어느 층에서도 화면에 맡기지 않는다 — VSEQ-7 이 아예 금지한다.

순수 모듈. 네트워크·DB 없음.
"""

from __future__ import annotations

import re
from typing import Any

from . import config, visual_sequence

# 사유 코드(정본). web/lib/blockLabels.ts 가 표시 문자열을 미러한다.
BLOCK_REASONS: tuple[str, ...] = (
    "vseq_too_few_stages",        # MECHANISM_SEQUENCE 인데 stage 가 1개 이하
    "vseq_no_progression",        # state_before == state_after 이거나 변화 서술이 없다
    "vseq_dangling_continuity",   # 이어받는다고 했는데 그 stage 가 없다
    "vseq_missing_entity",        # 참조한 개체가 entities 에 없다
    "vseq_quantitative_visual",   # 정확한 수치를 화면 물체로 표현하려 한다
    "vseq_spec_token_in_prompt",  # 규격 토큰(각도·렌즈)이 프롬프트에 남았다
    # ── 코덱스 리뷰(2026-08-30)가 실측으로 찾아낸 구멍 셋 ──
    "vseq_state_lineage_mismatch",   # 앞 stage 에 없던 상태를 물려받았다고 적었다
    "vseq_state_entity_undeclared",  # 선언 없는 개체가 상태·변이에 등장한다
    "vseq_no_actual_mutation",       # 진행 시퀀스인데 변이 선언이 없다(자기보고만 남는다)
    "vseq_literal_without_source",   # 실제 관측이라고 선언했는데 근거가 그것을 지불하지 않는다
    "vseq_duplicate_stage_id",       # 같은 stage_id 가 둘 — 색인이 덮어써 참조가 엉뚱한 곳을 본다
)
WARNING_REASONS: tuple[str, ...] = (
    "vseq_static_repeat",         # 같은 세계·같은 상태·같은 operation 이 반복된다
    "vseq_world_reset_high",      # 세계를 너무 자주 새로 만든다(시퀀스의 의미가 옅다)
    "vseq_screen_world",          # 시퀀스가 머무는 "세계"가 화면·인터페이스·추상 공간이다
    "vseq_stage_without_cut",     # stage 가 어느 컷도 담당하지 않는다
    "vseq_claim_unlinked",        # stage 가 근거를 가리키지 않는다
    "vseq_cut_claim_mismatch",    # stage 에 든 컷인데 주장이 겹치지 않는다(물려받지 못함)
    "vseq_invalid_return_snapshot",  # 되돌아간 세계의 상태가 원래 stage 와 어긋난다
    "vseq_route_contract_conflict",  # 옛 역할 선언과 새 정본 계획이 서로 다른 결론이다
)

# 정확한 수치를 **화면 물체로** 표현하려는 시도.
#
# ★ 왜 차단인가(Phase 0 실측 §3-1): "ten identical discs" 를 요구했는데 화면엔 4묶음이
#   나왔다. 이후 7/3·9·5/4 도 성립하지 않았다. 생성 모델은 개수를 지키지 못한다 —
#   따라서 개수로 수치를 말하는 계획은 **애초에 성립 불가능**이다.
#   어제 v2 의 컷7("동전 10개 vs 11~12개로 15% 증가 표현")이 정확히 그 실패였다.
#
#   시각이 표현할 수 있는 것은 방향과 관계다("늘어난다·옮겨간다·쌓인다").
#   "얼마나"는 코드 오버레이가 말한다.
#   ★ `\b` 는 **단어 대안에만** 붙인다. `%` 뒤에 붙이면 "15%" 가 매치되지 않는다
#     (`%` 는 비단어라 뒤 공백과의 사이에 경계가 없다). 이 저장소는 이 실수를 이미
#     한 번 했다 — photo_contract._SPOKEN_NUMBER_EN 의 같은 자리 주석 참조.
#     그리고 나는 그것을 고친 날 여기서 **똑같이 반복했다**(자기리뷰에서 발견).
_QUANTITATIVE_VISUAL = re.compile(
    r"\b(?:exactly|precisely)\s+\d+"
    r"|\d+\s*%"
    r"|\b\d+\s*(?:percent|percentage\s+points?)\b"
    r"|\b\d{2,}\s+(?:discs?|coins?|tokens?|blocks?|units?|items?|objects?|people|figures?)\b"
    r"|\b(?:count|number)\s+of\s+\w+\s+(?:shows?|represents?|equals?)\b",
    re.I)
_SPEC_TOKEN = re.compile(config.SPEC_TOKEN_PATTERN)


def _state_changed(stage: dict[str, Any]) -> bool:
    """상태가 실제로 달라졌다고 **선언**했는가.

    ★ 선언 검사다. 화면에서 참인지는 렌더 뒤 QA 가 본다 — 모듈 docstring 의 경계 참조.
      다만 여기서 통과 못 하는 것은 애초에 계획이 없는 것이므로 차단이 맞다.
    """
    before, after = stage.get("state_before") or {}, stage.get("state_after") or {}
    if before != after:
        return True
    # 상태 dict 를 안 쓰고 서술만 쓰는 도메인도 있다 — 그때는 서술이 실체다.
    return bool(stage.get("observable_change")) and not before and not after


def _norm_state_value(value: Any) -> str:
    """상태값 비교용 정규화. 대소문자·구두점·공백 차이는 같은 값으로 본다."""
    return re.sub(r"[^0-9a-z가-힣]+", " ", str(value or "").lower()).strip()


def _lineage_problems(stage: dict[str, Any], source_after: dict[str, Any] | None
                      ) -> tuple[bool, bool]:
    """(계보 어긋남, 되돌린 세계 스냅샷 어긋남).

    ★ 무엇을 판정하는가(코덱스 리뷰 S2): 골든B `S6_BENCHMARK` 는 `continuity_from=S1_APPROACH`
      인데 `state_before` 에 "Cratered surface after impact" 를 적었다. **S1 에는 분화구가
      없다.** 종전 게이트는 continuity_from 이 실재하는지만 봤으므로 그대로 통과시켰다.

    ★ 판정은 **키 수준**으로 한다. 값(자유 서술)을 대조하면 오탐이 쏟아진다.
      물려받겠다고 선언한 개체가 원본 stage 의 상태에 **아예 없으면** 그건 물려받은 것이
      아니다 — 있지도 않던 것을 이어받을 수는 없다.

    ★ "없다"를 뜻하는 값은 제외한다. `MALE_CHARACTER_B: "not present"` 는 물려받겠다는
      주장이 아니라 앞 stage 에 없었다는 서술이다(골든A S5 — 옳게 쓴 것을 벌하지 않는다).
      이 stage 가 스스로 등장시키는(APPEAR) 개체도 제외한다.
    """
    if source_after is None:
        return False, False
    declared = stage.get("state_before")
    if not isinstance(declared, dict) or not declared:
        return False, False
    appears = {str(m.get("entity_id")) for m in (stage.get("mutations") or [])
               if m.get("operation") == "APPEAR"}
    mismatch = False
    snapshot_off = False
    for key, val in declared.items():
        if visual_sequence._is_absence(val) or str(key) in appears:
            continue
        if str(key) not in source_after:
            mismatch = True
        elif _norm_state_value(source_after[str(key)]) != _norm_state_value(val):
            snapshot_off = True
    return mismatch, snapshot_off


# ★★ 세계가 화면이면 그 안의 모든 컷이 화면이 된다 (2026-09-03 실측).
#   실사형 지시서의 세계 5개 중 3개가 이랬다:
#     AD_CREATION_INTERFACE  "futuristic digital interface… glow from the interface itself"
#     SOCIAL_MEDIA_FEED      "social media feed interface… bright, even screen light"
#     HUMAN_AI_COLLABORATION_SPACE  "Abstract, clean digital space with interconnected nodes"
#   컷 단위 금지어(photo_contract)를 아무리 조여도 소용이 없었다 — 컷은 **선언된 세계를
#   충실히 그린 것**이고, 결정은 이미 시퀀스에서 끝나 있었다. 글자를 막으니 아이콘으로,
#   아이콘을 막으니 게이지로 옮겨 다닌 이유가 이것이다.
#   등급제가 "품질 의도는 시퀀스, 실행은 컷"이라고 말하는 그대로, **금지도 시퀀스에 걸어야
#   한다.** 컷에서 잡는 것은 증상이고 여기가 원인이다.
#
# ★★★ **두 층으로 나눈다**(2026-09-03 2차 실측). 한 덩어리로 막았더니 처방을 따른 결과를
#   벌했다: 모델이 `SOCIAL_MEDIA_OFFICE`("사람들이 일하는 오픈플랜 사무실, 화면 여러 대")를
#   냈는데 `screens` 하나로 차단됐다. 그건 **물리적 사무실**이고 화면은 그 안의 집기다 —
#   내가 프롬프트에 쓴 처방("화면은 세계가 아니라 세계 안의 물건") 그대로인데 게이트가
#   막으면, 모델은 올바른 답을 내고도 계속 틀렸다는 신호를 받는다.
#
#   ① HARD — **공간 자체가 물리적이지 않다.** 물리 앵커가 있어도 막는다.
#      추상 공간·가상 공간·홀로그램은 실사형이 될 수 없다.
#   ② SOFT — **화면은 집기일 수 있다.** 물리적 장소 앵커(사무실·실험실·사람…)가 함께
#      있으면 통과시킨다. 없으면 그 세계는 화면 속이라는 뜻이므로 막는다.
_HARD_WORLD = re.compile(
    r"\b(abstract|conceptual|virtual|cyberspace|holograms?|holographic|"
    r"digital\s+space|data\s+space|network\s+graph|nodes?)\b", re.I)

_SOFT_SCREEN = re.compile(
    # ★ 복수형을 빠뜨리면 그대로 샌다(2026-09-03 실측). "a grid of digital ad displays…
    #   highlighting the screens" 가 통과했다 — 화면 세계는 대개 **여럿**으로 쓰인다.
    r"\b(interfaces?|HUDs?|dashboards?|screens?|displays?|feeds?|browsers?|websites?)\b",
    re.I)

# 물리적 장소·사람이 있다는 증거. 하나라도 있으면 SOFT 어휘는 집기로 본다.
_PHYSICAL_ANCHOR = re.compile(
    r"\b(office|room|lab|laboratory|bench|desk|studio|factory|floor|building|"
    r"workspace|workshop|clinic|warehouse|kitchen|street|field|site|hall|"
    r"people|person|worker|workers|marketer|researcher|scientist|participant|"
    r"cubicles?|table|chair|window|windows)\b", re.I)


def screen_world_reasons(sequences: list[dict[str, Any]]) -> list[str]:
    """세계 선언이 화면·인터페이스·추상 공간인 시퀀스 (실사형 전용 개념).

    실사형의 세계는 **물리적 장소나 실물**이어야 한다 — 실험실·현장·장비·사람이 있는 곳.
    화면 속을 세계로 잡으면 그 시퀀스는 통째로 UI 렌더가 된다.

    ★ 검사 대상은 world 의 서술 전부다(style·lighting·background). world_id 만 보면
      `AD_CREATION_INTERFACE` 는 잡아도 style 에만 "digital interface" 를 쓴 경우를 놓친다.
    ★ 판정 불가(세계 없음)는 사유를 만들지 않는다.
    """
    out: list[str] = []
    for seq in sequences or []:
        w = seq.get("world")
        if not isinstance(w, dict) or not w:
            continue
        text = " ".join(str(w.get(k) or "") for k in
                        ("world_id", "style", "lighting", "background")).replace("_", " ")
        hard = _HARD_WORLD.search(text)
        if hard:
            out.append(f"vseq_screen_world:{seq.get('sequence_id')}:{hard.group(0).lower()}")
            continue
        # 화면 어휘는 **물리적 앵커가 없을 때만** 세계가 화면이라는 뜻이다.
        soft = _SOFT_SCREEN.search(text)
        if soft and not _PHYSICAL_ANCHOR.search(text):
            out.append(f"vseq_screen_world:{seq.get('sequence_id')}:{soft.group(0).lower()}")
    return out


def evaluate(sequences: list[dict[str, Any]],
             cuts: list[dict[str, Any]] | None = None,
             source_depth: str = "none",
             routed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """정규화된 시퀀스 목록 → {block_reasons, warnings, metrics}.

    시퀀스가 없으면 **아무것도 하지 않는다** — 시퀀스 없는 지시서는 종전 경로 그대로다.
    """
    if not sequences:
        return {"block_reasons": [], "warnings": [], "metrics": {}}

    blocks: list[str] = []
    warns: list[str] = []
    blocks.extend(screen_world_reasons(sequences))
    stages_by_id = visual_sequence.stage_index(sequences)
    known_stages = set(stages_by_id)
    cut_claims = {int(c.get("cut_no")): {str(x) for x in (c.get("claim_ids") or [])}
                  for c in (cuts or []) if str(c.get("cut_no") or "").isdigit()}
    cut_nos = set(cut_claims)

    total_stages = 0
    continued = 0
    new_worlds = 0
    entity_linked = 0
    entity_named = 0
    entity_resolved = 0
    seen_signature: set[tuple[str, str, str]] = set()

    # ★★ **stage_id 는 지시서 전체에서 유일해야 한다**(2026-09-19 리포트 리뷰에서 잡았다).
    #   `visual_sequence.stage_index` 는 시퀀스를 가로질러 **평평한 dict** 라, 같은 id 가 둘이면
    #   나중 것이 앞 것을 덮어쓴다. 그러면 `continuity_from` 이 **다른 시퀀스의 stage** 를 가리키고
    #   렌더는 엉뚱한 그림을 참조로 붙인다 — 화면은 멀쩡해 보이는데 이어지지 않는다.
    #   실측: 리포트 지시서 efa58017 은 stage 6개 중 **2개가 색인에서 사라졌다**(3편 중 2편에서 발생).
    #   오탐이 있을 수 없다(중복은 객관적으로 틀린 것이다) — 그래서 처음부터 차단이다.
    _seen_stage_ids: dict[str, str] = {}
    for _seq in sequences:
        for _st in (_seq.get("stages") or []):
            _sid = str(_st.get("stage_id") or "")
            if not _sid:
                continue
            if _sid in _seen_stage_ids:
                blocks.append(f"vseq_duplicate_stage_id:{_sid}"
                              f"({_seen_stage_ids[_sid]}·{_seq.get('sequence_id')})")
            else:
                _seen_stage_ids[_sid] = str(_seq.get("sequence_id") or "?")

    for seq in sequences:
        sid = seq.get("sequence_id")
        stages = seq.get("stages") or []
        entity_ids = {e.get("entity_id") for e in (seq.get("entities") or []) if e.get("entity_id")}
        total_stages += len(stages)
        # ★ 진행 판정은 **구조**로 한다. 모델의 sequence_role 라벨을 믿지 않는다(코덱스 리뷰 S4).
        progression = visual_sequence.sequence_is_progression(seq)

        # VSEQ-1 — 시퀀스라면 진행이 있어야 한다.
        if seq.get("sequence_role") == "MECHANISM_SEQUENCE" and len(stages) < 2:
            blocks.append(f"vseq_too_few_stages:{sid}")

        for st in stages:
            tag = f"{sid}/{st.get('stage_id')}"
            mode = str(st.get("continuity_mode") or "")
            if mode == "NEW_WORLD":
                new_worlds += 1
            elif mode in config.CONTINUITY_NEEDS_REFERENCE:
                continued += 1

            # VSEQ-2 — 진행. 앵커·프레이밍 시퀀스는 진행이 목적이 아니므로 면제한다
            #   (옳게 한 것을 벌하는 게이트는 무시당한다 — photo_contract 설계원칙 1).
            role_needs_progress = seq.get("sequence_role") in (
                "MECHANISM_SEQUENCE", "RESULT_SEQUENCE")
            # ★★ `allow_connective` stage 는 진행 검사에서 뺀다(2026-09-14 실측).
            #   지시서 프롬프트가 "주장을 지불하지 않는 컷(전환·출처·CTA)을 stage 에 넣을 때는
            #   allow_connective 를 true 로 하라 — 그런 컷에는 기전 도해가 붙지 않는다"고 가르친다.
            #   그런데 이 검사는 그 표시를 보지 않고 변이·진행을 요구했다 — 모델이 시킨 대로 하면
            #   막히는 **함정**이었다. 실측: 최근 지시서의 connective stage 27개 중 4개(15%)가
            #   vseq_no_actual_mutation·vseq_no_progression 으로 차단됐다(성격 유전 S2 출처 컷 포함).
            if st.get("allow_connective"):
                pass
            elif role_needs_progress or progression:
                if not visual_sequence.stage_has_progress(st) or not st.get("observable_change"):
                    blocks.append(f"vseq_no_progression:{tag}")
                # ★ 변이 선언을 **요구한다**(코덱스 리뷰 S1). 상태 두 벌을 모델이 다 쓰면
                #   진행 판정이 자기보고가 된다 — standing → standing calmly 로 통과한다.
                #   모델은 delta 만 적고 상태는 코드가 계산한다(compute_lineage).
                if not (st.get("mutations") or []):
                    blocks.append(f"vseq_no_actual_mutation:{tag}")
                # ★ 적대적 자기리뷰 Q1: 변이를 **선언만** 하고 결과가 같으면 진행이 아니다.
                #   `visible_change: true` 는 여전히 모델의 자기보고다. 그래서 코드가 계산한
                #   상태 두 벌을 마지막으로 한 번 더 본다 — 여기서는 모델이 개입할 수 없다.
                elif (st.get("state_after_computed") or {}) == (
                        st.get("state_before_computed") or {}):
                    blocks.append(f"vseq_no_progression:{tag}")

            # VSEQ-3 — 연속성 참조 무결성. 이어받는다고 했으면 그 stage 가 실재해야 한다.
            if mode in config.CONTINUITY_NEEDS_REFERENCE:
                ref = str(st.get("continuity_from") or "")
                if not ref or ref not in known_stages:
                    blocks.append(f"vseq_dangling_continuity:{tag}")
                else:
                    src_after = stages_by_id[ref].get("state_after_computed")
                    bad_lineage, snapshot_off = _lineage_problems(st, src_after)
                    if bad_lineage:
                        blocks.append(f"vseq_state_lineage_mismatch:{tag}")
                    if snapshot_off and mode == "RETURN_WORLD":
                        warns.append(f"vseq_invalid_return_snapshot:{tag}")

            # 개체 참조 무결성 — **선언한 것만 화면에 나온다.**
            #   ★ 범위를 넓혔다(코덱스 리뷰 S3): entity_refs 만 보던 종전 검사는 골든A S5 가
            #     state_after 에 선언 없는 실루엣 둘을 등장시킨 것을 통과시켰다.
            missing_refs = [e for e in (st.get("entity_refs") or []) if e not in entity_ids]
            if missing_refs:
                blocks.append(f"vseq_missing_entity:{tag}")
            named = visual_sequence.stage_entity_ids(st)
            entity_named += len(named)
            entity_resolved += len(named & entity_ids)
            undeclared = named - entity_ids - set(missing_refs)
            if undeclared:
                blocks.append(f"vseq_state_entity_undeclared:{tag}")
            if st.get("entity_refs"):
                entity_linked += 1

            # VSEQ-7 — 정량은 화면이 말하지 않는다.
            #   ★ 정밀 레이어(R1)가 생겼어도 이 금지는 유지한다. 레이어는 **코드가 그리는**
            #     것이고, 여기서 막는 것은 **생성 이미지에게** 정확한 비율을 그리라는 요구다.
            # ★ 적대적 자기리뷰 Q3(코덱스 리뷰 §11): claim_id 가 맞아도 **묘사가 틀릴 수 있다.**
            #   골든B 분광이 사례다 — 주장(C03)은 원문이 지지하지만 원문은 지상 관측인데
            #   화면은 우주에서 로켓에 빛을 쏘는 그림이었다.
            #
            #   코드가 "이 그림이 그 관측을 옳게 그렸는가"를 판정할 수는 없다. 판정할 수
            #   있는 것은 **그렇게 주장할 근거가 있는가**다: 초록만 확보한 논문은 관측
            #   방식을 말하지 않으므로 LITERAL_OBSERVATION 을 선언할 자격이 없다.
            #   확실치 않으면 SCHEMATIC_PRINCIPLE 이다 — 그건 실제 장면이라고 주장하지 않는다.
            if (st.get("representation_mode") == "LITERAL_OBSERVATION"
                    and source_depth in config.DEPTH_LITERAL_FORBIDDEN):
                blocks.append(f"vseq_literal_without_source:{tag}")

            # ★★ **게이트는 프롬프트로 나갈 바로 그 문자열을 본다**(2026-08-30 채팅 실측).
            #   참조 컷의 프롬프트 꼬리는 이제 stage 의 **변이 선언**에서 만들어진다
            #   (sequence_render.change_prose). 그런데 게이트는 visual_prompt 와
            #   observable_change 만 보고 있었다 — 즉 **실제로 보내는 문장을 검사하지 않았다.**
            #   실측: 컷 프롬프트에서 타이머 요구를 막았더니 같은 요구가
            #   `TIMER_OVERLAY appear to Digital timer showing…` 로 변이 선언에 남아 있었고
            #   화면에 `3.456 s` 가 그대로 박혔다. 검사 대상과 전송 대상이 다르면 게이트는
            #   있으나 마나다.
            text = " ".join([
                str(st.get("visual_prompt") or ""),
                str(st.get("observable_change") or ""),
                *[f"{m.get('entity_id')} {m.get('property')} {m.get('result_state')}"
                  for m in (st.get("mutations") or [])],
            ])
            if _QUANTITATIVE_VISUAL.search(text):
                blocks.append(f"vseq_quantitative_visual:{tag}")

            # 규격 토큰 잔존(Phase 0 §3-3). 정규화가 지우므로 여기 걸리면 우회 경로가 있다는 뜻.
            if _SPEC_TOKEN.search(text):
                blocks.append(f"vseq_spec_token_in_prompt:{tag}")

            # VSEQ-4 — 같은 세계·같은 상태·같은 operation 반복(경고).
            sig = (str(seq.get("world", {}).get("world_id") or sid),
                   str(sorted((st.get("state_after_computed") or {}).items())),
                   str(st.get("operation")))
            if sig in seen_signature:
                warns.append(f"vseq_static_repeat:{tag}")
            seen_signature.add(sig)

            # 컷 연결·근거 연결(경고).
            refs = st.get("cut_refs") or []
            if not refs or (cut_nos and not (set(refs) & cut_nos)):
                warns.append(f"vseq_stage_without_cut:{tag}")
            if not st.get("claim_ids"):
                warns.append(f"vseq_claim_unlinked:{tag}")

            # ★ stage 에 든 컷인데 주장이 겹치지 않는다(코덱스 리뷰 §10). 라우터는 이런 컷에
            #   세계를 물려주지 않는다 — 그 사실을 운영자가 보게 남긴다. 연결 컷으로 **명시**
            #   했으면 정상이므로 경고하지 않는다.
            if not st.get("allow_connective"):
                stage_claims = {str(x) for x in (st.get("claim_ids") or [])}
                for cno in refs:
                    if cno in cut_claims and stage_claims and not (stage_claims & cut_claims[cno]):
                        warns.append(f"vseq_cut_claim_mismatch:{tag}#{cno}")

    warns.extend(route_contract_conflicts(cuts or [], routed or []))

    metrics = sequence_metrics(sequences, total_stages, continued, new_worlds,
                               entity_linked, entity_named, entity_resolved)
    if metrics.get("world_reset_rate", 0.0) > config.VSEQ_WORLD_RESET_WARN:
        warns.append(f"vseq_world_reset_high:{metrics['world_reset_rate']}")

    return {"block_reasons": sorted(set(blocks)), "warnings": sorted(set(warns)),
            "metrics": metrics}


def route_contract_conflicts(cuts: list[dict[str, Any]],
                            routed: list[dict[str, Any]]) -> list[str]:
    """옛 역할 선언(`visual_role`)과 새 정본(`resolved_visual_plan`)이 **다른 결론**인 컷.

    ★ 적대적 자기리뷰 Q4(코덱스 리뷰 §12): 지금 지시서에는 판정권을 가진 것처럼 보이는
      필드가 넷이다 — visual_role · visual_treatment · photo_contract · visual_router.
      R3 으로 정본을 하나로 모았지만 **옛 필드는 하위호환으로 남아 있고**, 렌더·화면 계약이
      아직 그것을 읽는 자리가 있다. 둘이 어긋나면 어느 쪽이 화면에 나갈지 우리가 모른다.

    ★ 차단하지 않는 이유: 어긋남 자체가 잘못이 아니다. 모델이 `visual_role` 을 붙이는 기준과
      코드가 base 를 정하는 기준이 원래 다르다(전자는 컷의 성격, 후자는 시퀀스 소속·수치).
      운영자가 **보이게** 하는 것이 목적이고, 정본이 무엇인지는 코드가 이미 정했다.
    """
    by_cut = {int(r.get("cut_no") or 0): r for r in routed}
    out: list[str] = []
    for c in cuts:
        plan = by_cut.get(int(c.get("cut_no") or 0))
        if not plan or not plan.get("beat_declared"):
            continue
        role = str(c.get("visual_role") or "")
        base = str(plan.get("base") or "")
        if role == "MECHANISM" and base in ("REALITY", "OVERLAY"):
            out.append(f"vseq_route_contract_conflict:{c.get('cut_no')}#{role}/{base}")
        elif role == "REALITY" and base == "MECHANISM_SEQUENCE":
            out.append(f"vseq_route_contract_conflict:{c.get('cut_no')}#{role}/{base}")
    return out


def sequence_metrics(sequences: list[dict[str, Any]], total_stages: int,
                     continued: int, new_worlds: int, entity_linked: int,
                     entity_named: int = 0, entity_resolved: int = 0) -> dict[str, Any]:
    """v3 KPI (리뷰 §13). **품질을 대신하지 않는다** — 최종 판정은 사람 눈이다.

    ★ 이름이 재는 것과 달랐다(코덱스 리뷰 §16). 골든A 는 `persistent_entity_ratio = 1.0`
      인데 **선언 안 된 개체가 stage 에 실재했다.** 그 지표는 "선언된 개체를 참조한 stage
      비율"이었지 "등장한 개체가 선언돼 있는 비율"이 아니었다. 둘로 나누고 이름을 맞춘다.

    ★ `mechanism_sequences` 도 모델의 `sequence_role` 라벨이 아니라 **구조 판정**을 쓴다
      (코덱스 리뷰 S4). 라벨을 세던 종전 지표는 골든B 를 0 으로 셌다 — 같은 지시서에서
      라우터는 7컷을 기전 시퀀스로 판정하고 있었는데도.
    """
    n = max(1, total_stages)
    return {
        "sequence_count": len(sequences),
        "stage_count": total_stages,
        "avg_stages_per_sequence": round(total_stages / max(1, len(sequences)), 2),
        "world_reset_rate": round(new_worlds / n, 3),
        "continuity_rate": round(continued / n, 3),
        # 선언된 개체를 **참조한** stage 비율(종전 persistent_entity_ratio 의 실제 의미).
        "declared_entity_lock_ratio": round(entity_linked / n, 3),
        # stage 에 등장한 개체 중 **선언돼 있는** 비율. 1.0 미만이면 미선언 개체가 있다.
        "stage_entity_resolution_rate": (round(entity_resolved / entity_named, 3)
                                         if entity_named else 1.0),
        "mechanism_sequences": sum(1 for s in sequences
                                   if visual_sequence.sequence_is_progression(s)),
        "declared_mechanism_role": sum(1 for s in sequences
                                       if s.get("sequence_role") == "MECHANISM_SEQUENCE"),
    }


def feedback_prompt(block_reasons: list[str]) -> str:
    """위반 사유를 모델에게 되먹일 문장. **무엇이 왜 틀렸고 어떻게 고치는지**를 적는다
    (photo_contract.feedback_prompt 와 같은 자세 — "다시 만들어라"는 지시가 아니다)."""
    if not block_reasons:
        return ""
    hints = {
        "vseq_too_few_stages":
            "MECHANISM_SEQUENCE 인데 stage 가 하나뿐이다. 한 장면으로 끝나는 설명은 시퀀스가"
            " 아니다 — 무엇이 먼저 보이고 그다음 무엇이 달라지는지 단계로 나눠라.",
        "vseq_no_progression":
            "state_before 와 state_after 가 같거나 observable_change 가 비었다. 그 stage 는"
            " 화면이 멈춰 있다는 뜻이다. 무엇이 눈에 보이게 달라지는지 적어라.",
        "vseq_dangling_continuity":
            "이어받을 stage 를 가리켰는데 그런 stage 가 없다. continuity_from 에는 **앞선**"
            " stage_id 를 정확히 적어라.",
        "vseq_missing_entity":
            "참조한 개체가 entities 목록에 없다. 유지할 개체는 먼저 선언하고 그 id 를 써라.",
        "vseq_quantitative_visual":
            "정확한 수치를 화면 물체 개수로 표현하려 했다. 생성 모델은 개수를 지키지 못한다"
            "(실측 확인). 화면은 방향과 관계만 보여주고 — 늘어난다·옮겨간다·쌓인다 —"
            " 수치는 overlay_plan 이 말한다.",
        "vseq_no_actual_mutation":
            "진행하는 시퀀스인데 mutations 가 비었다. state_before 와 state_after 를 네가 둘 다"
            " 쓰면 달라졌다는 판정이 결국 네 자기보고가 된다. **무엇이 어떻게 바뀌는지**"
            "(entity_id·property·operation·visible_change)만 적어라 — 상태는 코드가 계산한다.",
        "vseq_state_lineage_mismatch":
            "continuity_from 이 가리키는 stage 에 **없던 개체의 상태**를 물려받았다고 적었다."
            " 있지도 않던 것을 이어받을 수는 없다. 그 개체를 이 stage 에서 등장시키려면"
            " mutations 에 APPEAR 로 선언하라.",
        "vseq_state_entity_undeclared":
            "선언하지 않은 개체가 상태·변이에 등장한다. 화면에 나올 개체는 entities 에 먼저"
            " 선언하고 그 id 를 써라 — 선언 없는 개체는 stage 마다 다른 모습으로 그려진다.",
        # ★★ 이것만 처방이 비어 있었다(2026-08-31). 차단 사유 10개 중 9개에만 문장이
        #   있었고, 하필 재생성 실측에서 실제로 막힌 것이 이것이었다 — 재시도는 무엇을
        #   고쳐야 하는지 듣지 못했다. `test_feedback_covers_every_block_reason` 로 고정한다.
        "vseq_duplicate_stage_id":
            "같은 stage_id 를 두 시퀀스가 쓰고 있다. stage_id 는 **지시서 전체에서 유일해야 한다** —"
            " 색인이 나중 것으로 덮어써서 continuity_from 이 **다른 시퀀스의 stage** 를 가리키고,"
            " 렌더가 엉뚱한 그림을 참조로 붙인다. 시퀀스 이름을 앞에 붙여 구분하라"
            "(SEQ_R01_S1_… / SEQ_R04_S1_… 처럼). 논증 단위 이름을 그대로 돌려 쓰지 마라.",
        "vseq_literal_without_source":
            "실제 관측 장면(LITERAL_OBSERVATION)이라고 선언했는데 **그렇게 주장할 근거가"
            " 없다.** 초록은 \"무엇을 알아냈는가\"를 말하지 \"어떻게 봤는가\"를 말하지 않는다."
            " 그 stage 의 representation_mode 를 SCHEMATIC_PRINCIPLE 로 바꿔라 —"
            " **그림을 바꾸라는 뜻이 아니라** 실제 관측이라고 주장하지 말라는 뜻이다."
            " 함께: 원문이 지불하지 않는 장비·절차(주사기·바이알·이중맹검 등)를 화면에서 빼라.",
        "vseq_spec_token_in_prompt":
            "카메라 각도·렌즈 같은 규격 표기가 프롬프트에 남았다. 그런 토큰은 화면에 글자로"
            " 그려진다(실측 확인). 카메라는 camera_base/camera_operation 으로만 선언하라.",
    }
    seen: list[str] = []
    for r in block_reasons:
        head = r.split(":", 1)[0]
        if head in hints and hints[head] not in seen:
            seen.append(hints[head])
    if not seen:
        return ""
    return ("\n\n[시각 시퀀스 계약 위반 — 아래를 고쳐 다시 만들어라]\n"
            + "\n".join(f"- {s}" for s in seen))
