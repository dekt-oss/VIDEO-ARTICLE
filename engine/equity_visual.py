"""Equity Visual Planner — 리포트 논증을 **공용 Visual Sequence 로 컴파일**한다 (v3 Phase 5).

무엇을 푸는가: 리포트 라인은 `report_reasoning` 이 만든 논증 단계를 이미 갖고 있는데,
**화면은 그것을 모른다.** 저장소를 훑어 보면 `report_*.py` 어디에도 `visual_sequences`·
`resolved_visual_plan`·`sequence_render` 참조가 **한 곳도 없다**(2026-08-30 확인).
그래서 "왜 이 증권사가 이렇게 전망하는가"가 숫자 카드와 낱장 그림의 나열로 나간다.

이 모듈이 그 다리다:

    report_reasoning.reasoning_units[].steps  →  공용 visual_sequences

★★ **다시 추출하지 않는다**(작업지시서 equity §4). LLM 호출이 **0** 이다 — 이 모듈은
  순수 함수다. 같은 논증에서 매번 같은 시퀀스가 나오고, 비용이 들지 않으며, 무엇보다
  **리포트가 말하지 않은 단계가 생길 수 없다**: stage 는 step 에서 1:1 로 나온다.
  EQ-V5("수주 증가 → 매출 증가 사이에 원문이 말하지 않은 단계가 추가되면 안 된다")를
  게이트로 막는 대신 **구조로 불가능하게** 만든 것이다.

★ 금융용 스키마를 새로 만들지 않는다(§3). VisualSequence·VisualWorld·PersistentEntity·
  StateMutation·enum 전부 `visual_sequence`·`config` 의 공용 정의를 그대로 쓴다.
  Paper 와 Report 가 다른 것은 **Domain Planner** 뿐이고, 그것이 이 파일이다.

★ 두 층을 섞지 않는다(§5). 리포트 문장이 말하는 것은 **사업 의미**(ORDER·BACKLOG…)이고
  화면이 하는 것은 **시각 연산**(TRANSFER·ACCUMULATE…)이다. 번역표는 `config` 에 있다.

라우팅(§6): 사업 기전 논증만 시퀀스가 된다. 밸류에이션·비교는 정확한 수치가 본체라
code viz 로 남는다 — `+130%` 를 물체 13개로 보여주지 않는다(§6.2).
정확한 수치를 든 단계는 세계를 끊지 않고 **정밀 레이어**를 얹는다(코덱스 리뷰 R1).
"""

from __future__ import annotations

from typing import Any

from . import config, visual_sequence
from .util import log


# ─────────────────────────────────────────────────────────────
# ① 사업 의미 판정 — 코드가 한다
# ─────────────────────────────────────────────────────────────
def semantic_operation(text: str) -> str:
    """단계 문장 → Equity Semantic Operation. **먼저 맞는 것이 이긴다.**

    ★ 순서가 곧 우선순위다. "수주잔고가 쌓인다"는 ORDER 와 BACKLOG 어휘를 둘 다 갖지만
      화면에서 벌어지는 일은 **누적**이다 — 더 구체적인 쪽이 표 앞에 있다.

    ★ 아무것도 안 맞으면 기본값을 준다. 여기서 빈 값을 돌려주면 호출측이 "판정 실패"와
      "해당 없음"을 구분하려고 또 분기하게 된다 — 대신 `matched` 를 따로 노출한다.
    """
    low = str(text or "").lower()
    for op, terms in config.EQUITY_SEMANTIC_TERMS:
        if any(t.lower() in low for t in terms):
            # ★ 닫힌 목록 밖이면 어휘표의 오타다. 조용히 흘려보내면 `translate` 의
            #   기본값으로 떨어져 **엉뚱한 화면 연산**이 되고 아무도 모른다.
            if op not in config.EQUITY_SEMANTIC_OPERATIONS:
                log.warning("어휘표에 알 수 없는 사업 의미: %s", op)
                return config.DEFAULT_EQUITY_SEMANTIC_OP
            return op
    return config.DEFAULT_EQUITY_SEMANTIC_OP


def semantic_matched(text: str) -> bool:
    """어휘가 **실제로** 맞았는가(기본값으로 채운 것과 구분).

    ★ 이 저장소가 반복해서 배운 것: **기본값도 정본으로 읽힌다.** 라우터가 빈 beat 를
      RESULT 로 채웠더니 만화식 지시서 3컷이 전부 코드 시각화로 세어졌다(계획서 §9-10).
      그래서 채워 넣은 값에는 표시를 남긴다.
    """
    low = str(text or "").lower()
    return any(t.lower() in low
               for _, terms in config.EQUITY_SEMANTIC_TERMS for t in terms)


def translate(semantic_op: str) -> dict[str, str]:
    """사업 의미 → 화면 연산·변이·지속 개체·카메라. 공용 enum 안에서만 고른다."""
    return config.EQUITY_OP_TRANSLATION.get(
        semantic_op, config.EQUITY_OP_TRANSLATION[config.DEFAULT_EQUITY_SEMANTIC_OP])


# ─────────────────────────────────────────────────────────────
# ② 컴파일 — 논증 단위 하나가 시퀀스 하나가 된다
# ─────────────────────────────────────────────────────────────
def _world_of(unit: dict[str, Any], index: int) -> dict[str, Any]:
    """이 논증이 사는 세계. 세계는 **논증 단위마다 하나**다 — 단계마다 새로 만들지 않는다."""
    return {
        "world_id": f"W_{unit.get('reasoning_id') or index}",
        "style": "industrial technical render, physically based materials, engineering clarity",
        "lighting": "volumetric studio lighting with soft ambient occlusion",
        "background": "neutral desaturated industrial interior",
        "identity_lock": True,
    }


def _stage_of(step: dict[str, Any], idx: int, unit: dict[str, Any],
              prev_stage_id: str, repeat: int = 1, seq_id: str = "") -> dict[str, Any]:
    """논증 단계 하나 → stage 하나. **1:1 이다** — 여기서 단계를 만들지도 합치지도 않는다.

    repeat: 이 시퀀스에서 같은 (개체, 사업 의미)가 **몇 번째로** 나오는가.
      ★ 2회차부터는 "앞보다 더"를 붙인다. 왜 필요한가(2026-08-30 실제 리포트로 실측):
        같은 논증에 DEMAND_INCREASE 가 두 번 나왔는데(수요가 두 가지 이유로 는다)
        화면 문장이 똑같아서 **코드가 계산한 상태가 동일**해졌고, 상태 원장이
        `vseq_no_progression` 으로 차단했다. 게이트가 옳다 — 같은 화면이 두 번이면
        진행이 아니다.
      ★ 이것은 게이트를 속이려고 문자열만 바꾸는 것이 **아니다**(코덱스 리뷰 S1 이 금지한 것).
        리포트가 "수요가 또 늘어난다"고 말했으므로 흐름은 **실제로 앞보다 굵어진다** —
        화면에서 눈에 보이는 차이가 진짜로 있다.
    """
    text = str(step.get("text") or "")
    sem = semantic_operation(text)
    tr = translate(sem)
    prose = dict(config.EQUITY_CHANGE_PROSE.get(
        sem, config.EQUITY_CHANGE_PROSE[config.DEFAULT_EQUITY_SEMANTIC_OP]))
    if repeat > 1:
        prose["en"] = f"{prose['en']}, further than in the previous stage"
        prose["ko"] = f"{prose['ko']} — 앞 단계보다 한 번 더"
    entity = tr["entity"]
    # ★★ stage_id 에 **시퀀스 이름을 앞에 붙인다**(2026-09-19 실측으로 잡았다).
    #   종전에는 `S{단계번호}_{의미}` 였다 — 논증 단위마다 단계 번호가 1부터 다시 시작하고
    #   의미 낱말(DEMAND_INCREASE 등)도 되풀이되니, **다른 시퀀스가 같은 stage_id 를 갖는다.**
    #   `visual_sequence.stage_index` 는 시퀀스를 가로질러 평평한 dict 라 나중 것이 앞 것을
    #   덮어쓰고, `continuity_from` 이 **다른 시퀀스의 stage** 를 가리킨다 — 렌더가 엉뚱한 그림을
    #   참조로 붙이는데 화면은 멀쩡해 보인다(조용히 어긋나는 종류).
    #   실측: 리포트 지시서 efa58017 은 stage 6개 중 2개가 색인에서 사라졌다(3편 중 2편에서 발생).
    stage_id = f"{seq_id}_S{idx}_{sem}" if seq_id else f"S{idx}_{sem}"
    # 첫 단계는 세계를 세우고, 이후는 **같은 세계의 다음 상태**다.
    #   ★ 여기서 CONTINUE_WORLD 를 쓰는 것이 v3 의 요점이다. NEW_WORLD 를 연달아 쓰면
    #     "시퀀스"라고 부르지만 실은 컷 나열이다(공용 지표 world_reset 이 그것을 센다).
    mode = "NEW_WORLD" if idx == 1 else "CONTINUE_WORLD"
    return {
        "stage_id": stage_id,
        "cut_refs": [],                      # 컷 배정은 지시서 단계가 한다
        "representation_mode": "SCHEMATIC_PRINCIPLE",
        "operation": tr["operation"],
        "camera_operation": tr["camera"],
        "continuity_mode": mode,
        "continuity_from": "" if idx == 1 else prev_stage_id,
        "entity_refs": [entity],
        "mutations": [{
            "entity_id": entity,
            "property": sem.lower(),
            "operation": tr["mutation"],
            "visible_change": True,
            # ★★ 화면 계약에는 **방향과 동작**만 싣는다 — 리포트 문장을 그대로 실으면
            #   그 안의 정확한 수치("지분 49.99%")를 생성 이미지에게 그리라고 요구하는
            #   셈이고 VSEQ-7 이 차단한다(2026-08-30 실제 리포트로 실측).
            #   수치는 정밀 레이어와 claim_ids 가 정확히 담당한다(코덱스 리뷰 R1).
            "result_state": prose["en"],
            "claim_ids": list(step.get("fact_ids") or []),
        }],
        "state_before": {},
        "state_after": {},
        "observable_change": prose["ko"],
        # ★ 리포트 문장은 **버리지 않는다.** 화면에 안 실을 뿐이고, 운영자·게이트·UI 가
        #   그대로 읽는다. 지어내는 것이 아니라 층을 나누는 것이다.
        "reasoning_text": text,
        # ★ 근거 연결. fact_id 가 곧 claim 이다 — 리포트 라인의 원장은 number_facts 다.
        "claim_ids": list(step.get("fact_ids") or []),
        "visual_prompt": "",
        # ── 아래는 공용 스키마가 정규화에서 버리는 진단용 메타데이터다 ──
        "equity_semantic_operation": sem,
        "equity_semantic_matched": semantic_matched(text),
        "reasoning_id": str(unit.get("reasoning_id") or ""),
        "reasoning_step": int(step.get("step") or idx),
        # 정확한 수치를 든 단계는 세계를 끊지 않고 **정밀 레이어**를 얹는다(R1).
        "precision_layer": "CODE_OVERLAY" if (step.get("fact_ids") or []) else "",
    }


def compile_unit(unit: dict[str, Any], index: int) -> dict[str, Any] | None:
    """논증 단위 하나 → 시퀀스 하나. 자격이 없으면 None.

    자격:
      ① 사업 기전 논증인가(밸류에이션·비교는 code viz 가 맞다 — §6.2)
      ② 단계가 최소 개수 이상인가(1단계는 진행이 아니라 한 장면이다)
    """
    if str(unit.get("unit_type") or "") not in config.EQUITY_MECHANISM_UNIT_TYPES:
        return None
    steps = [s for s in (unit.get("steps") or []) if str(s.get("text") or "").strip()]
    if len(steps) < config.EQUITY_MIN_STAGES:
        return None

    # ★ 시퀀스 이름을 **먼저** 정한다 — stage_id 가 그것을 앞에 붙이기 때문이다(아래 주석).
    seq_id = f"SEQ_{unit.get('reasoning_id') or index}"
    stages: list[dict[str, Any]] = []
    prev = ""
    seen: dict[str, int] = {}          # (개체·사업 의미) → 몇 번째 등장인가
    for i, step in enumerate(steps, 1):
        sem = semantic_operation(str(step.get("text") or ""))
        key = f"{translate(sem)['entity']}|{sem}"
        seen[key] = seen.get(key, 0) + 1
        st = _stage_of(step, i, unit, prev, repeat=seen[key], seq_id=seq_id)
        stages.append(st)
        prev = st["stage_id"]

    entity_ids: list[str] = []
    for st in stages:                        # 등장 순서를 지킨다(set 은 순서를 잃는다)
        for e in st["entity_refs"]:
            if e not in entity_ids:
                entity_ids.append(e)
    return {
        "sequence_id": seq_id,
        "sequence_role": "MECHANISM_SEQUENCE",
        "world": _world_of(unit, index),
        "entities": [{"entity_id": e, "entity_type": "equity_business_object",
                      "visual_identity": config.EQUITY_ENTITY_IDENTITY.get(e, ""),
                      "continuity": "locked"} for e in entity_ids],
        "stages": stages,
        # 진단용 — 어느 논증에서 나왔는지. EQ-V1 이 이것을 검사한다.
        "reasoning_id": str(unit.get("reasoning_id") or ""),
        "attributed_to": str(unit.get("attributed_to") or ""),
        "carries_thesis": bool(unit.get("carries_thesis")),
    }


def compile_sequences(reasoning: dict[str, Any] | None) -> list[dict[str, Any]]:
    """`financial_reasoning` → 공용 `visual_sequences`. **LLM 호출 0.**

    ★ 반환값은 공용 정규화를 **통과한 뒤**의 것이다. 정규화를 건너뛰면 금융 쪽만
      느슨한 스키마를 갖게 되고, 그때부터 두 라인이 갈라진다.
    """
    if not config.EQUITY_SEQUENCE_ENABLED:
        return []
    # ★★ 키는 `units` 다 — `reasoning_units` 가 아니다(2026-08-30 실제 리포트로 잡음).
    #   `reasoning_units` 는 **LLM 출력의 키**이고, `normalize_units` 를 지나 저장되는
    #   정본 블록(`report_drafts.financial_reasoning`)은 `units` 로 담는다
    #   (`report_reasoning.empty`·`build`·`reasoning_ids`·`units_block` 전부 `units` 를 읽는다).
    #   틀린 키를 읽으면 조용히 빈 목록이 나와 **Phase 5 전체가 무력화**된다 — 게이트도
    #   경고도 없이 예전 화면 그대로 나간다. 내 단위 테스트는 같은 오해를 픽스처에 담고
    #   있어서 통과했고, **진짜 리포트를 돌려서야** 드러났다.
    #   관대하게 둘 다 받지 않는다. 정본 키가 무엇인지 흐려지는 순간 같은 사고가 돌아온다.
    units = (reasoning or {}).get("units") or []
    raw = [c for i, u in enumerate(units, 1) if (c := compile_unit(u, i))]
    if not raw:
        return []
    normalized = visual_sequence.normalize_all(raw)
    # ★ 정규화가 버리는 진단 필드를 다시 얹는다. 공용 스키마를 넓히지 않으면서
    #   금융 게이트(EQ-V1)가 볼 것을 남기는 자리다.
    for norm, src in zip(normalized, raw):
        norm["reasoning_id"] = src["reasoning_id"]
        norm["attributed_to"] = src["attributed_to"]
        norm["carries_thesis"] = src["carries_thesis"]
        for nst, sst in zip(norm["stages"], src["stages"]):
            for key in ("equity_semantic_operation", "equity_semantic_matched",
                        "reasoning_id", "reasoning_step", "precision_layer",
                        "reasoning_text"):
                nst[key] = sst[key]
    return normalized


def assign_cuts(sequences: list[dict[str, Any]],
                cuts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """컷을 stage 에 배정한다 — 컷이 **스스로 말한** (reasoning_id, reasoning_step) 으로.

    ★ 왜 순서로 나눠 담지 않는가: "R01 을 옮기는 컷 3개를 stage 5개에 고르게 배분"은
      **우리가 지어낸 정렬**이다. 그러면 화면이 3단계를 말하는데 계약은 5단계를 믿는다.
      지시서 모델은 이미 컷마다 `reasoning_id` 를 적는다 — 거기에 단계 번호 하나를 더
      받아 정확히 잇는다. 존재하지 않는 단계를 가리키면 **버린다**(dangling 금지,
      `_filter_reasoning_ids` 와 같은 규율).

    ★ 배정되지 않은 stage 는 그대로 둔다. 공용 게이트가 `vseq_stage_without_cut` 경고로
      드러낸다 — 조용히 지우면 "논증은 5단계인데 화면은 3단계"가 보이지 않는다.
    """
    by_reasoning = {s.get("reasoning_id"): s for s in sequences if s.get("reasoning_id")}
    for cut in cuts or []:
        rid = str(cut.get("reasoning_id") or "").strip()
        seq = by_reasoning.get(rid)
        if not seq:
            continue
        try:
            step = int(cut.get("reasoning_step") or 0)
            cut_no = int(cut.get("cut_no"))
        except (TypeError, ValueError):
            continue
        stages = seq.get("stages") or []
        if not 1 <= step <= len(stages):
            continue                      # 없는 단계를 가리킨다 — 지어낸 것이므로 버린다
        stage = stages[step - 1]
        refs = stage.setdefault("cut_refs", [])
        if cut_no not in refs:
            refs.append(cut_no)
        # ★★ 이 컷이 **무엇을 지불하는지** 말해 준다. 안 하면 라우터가 "주장 없는 컷"으로
        #   보고 기전 컷 자격을 안 준다 — 리포트 컷은 `source_facts`(Fact Sheet 키)를 쓰지
        #   `claim_ids` 를 쓰지 않기 때문이다. 그러면 시퀀스를 만들어 놓고도 화면 판정은
        #   전부 기본값(CODE_VIZ)으로 떨어진다(실측: in_sequence 0, CODE_VIZ 6).
        #   원장은 `number_facts` 이고 `fact_ids` 는 `report_reasoning` 이 이미 그 원장과
        #   대조해 남긴 것이다 — 지어낸 id 가 아니다.
        # ★ 컷이 스스로 선언했으면 건드리지 않는다. 덮어쓰면 모델의 판단을 지운다.
        if not (cut.get("claim_ids") or []):
            cut["claim_ids"] = list(stage.get("claim_ids") or [])
    return sequences


def project_to_screen(sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """논증 시퀀스 → **화면에 실제로 나가는** 시퀀스. 컷이 붙은 stage 만, 컷 순서대로.

    ★★ 왜 필요한가(2026-08-30 실제 지시서 실측). 컴파일은 논증 **전체**를 stage 로 편다.
      그런데 지시서 모델은 그중 일부만, 게다가 **순서를 어겨** 컷에 붙였다:

          컷4 → R01 step4 · 컷5 → R01 step2 · 컷6 → R03 step1

      그대로 두면 컷4가 `S4` 를 먼저 그리려는데 `S4` 는 `S3` 에서 이어받아야 한다.
      `S3` 그림이 없으니 참조를 못 붙이고 **새 세계로 떨어진다.** 실측 결과가
      `reference_conditioned 0 · world_reset 3` 이었다 — 기계는 이어졌는데 화면은 안 이어졌다.

    ★ 그래서 **세계의 사슬은 화면 순서를 따른다.** 시청자가 보는 순서가 곧 세계가
      변해 가는 순서다. 이것은 "지어낸 정렬"이 아니다 — 어느 컷이 어느 단계인지는
      여전히 모델이 말한 그대로고, 우리는 **이미 정해진 컷 순서**를 쓸 뿐이다.

    ★ 컷이 없는 stage 는 화면이 없다. 남겨 두면 lineage 만 끊는다 — 대신
      `coverage` 에 몇 단계가 빠졌는지 숫자로 남긴다(조용히 지우지 않는다).

    ★ 논증 순서를 어긴 것 자체는 **경고로 드러낸다**(`equity_steps_out_of_order`).
      4단계를 2단계보다 먼저 설명하는 영상은 대개 구성이 잘못된 것이다.
    """
    out: list[dict[str, Any]] = []
    for seq in sequences:
        stages = seq.get("stages") or []
        bound = [st for st in stages if st.get("cut_refs")]
        bound.sort(key=lambda st: min(st["cut_refs"]))
        steps_seen = [int(st.get("reasoning_step") or 0) for st in bound]
        seq["coverage"] = {
            "steps_total": len(stages),
            "steps_on_screen": len(bound),
            "steps_skipped": len(stages) - len(bound),
            "out_of_order": steps_seen != sorted(steps_seen),
        }
        if len(bound) < config.EQUITY_MIN_STAGES:
            # 화면에 나가는 단계가 1개 이하 — 시퀀스가 아니라 한 장면이다.
            #   시퀀스로 두면 "기전 시퀀스 1개"라고 지표만 좋아지고 화면은 안 이어진다.
            seq["coverage"]["dropped"] = True
            continue
        for i, st in enumerate(bound, 1):
            st["continuity_mode"] = "NEW_WORLD" if i == 1 else "CONTINUE_WORLD"
            st["continuity_from"] = "" if i == 1 else bound[i - 2]["stage_id"]
        seq["stages"] = bound
        out.append(seq)
    return out


def screen_warnings(sequences: list[dict[str, Any]]) -> list[str]:
    """화면 투영에서 드러난 것들. 차단이 아니라 **운영자에게 보이는 경고**다."""
    warns: list[str] = []
    for seq in sequences:
        cov = seq.get("coverage") or {}
        sid = seq.get("sequence_id")
        if cov.get("out_of_order"):
            warns.append(f"equity_steps_out_of_order:{sid}")
        if cov.get("steps_skipped"):
            warns.append(f"equity_steps_off_screen:{sid}"
                         f"#{cov['steps_on_screen']}/{cov['steps_total']}")
    return warns


def build_for_directive(cuts: list[dict[str, Any]] | None,
                        reasoning: dict[str, Any] | None) -> list[dict[str, Any]]:
    """지시서 정규화에 **넣을** 시퀀스. `report_directive.generate` 가 부른다.

    ★★ 여기가 배선의 핵심이다. 정규화(`directive.normalize_directive`)는 시퀀스가 있으면
      라우팅·`resolved_visual_plan`·`stage_mutations`·공용 게이트를 **이미 전부** 돌린다.
      그래서 시퀀스를 정규화 **앞에** 꽂으면 금융 라인이 그 기계를 통째로 물려받는다 —
      새 파이프라인을 만들지 않는다는 §1 이 요구하는 모양이 바로 이것이다.

    ★ 시퀀스가 비면 빈 목록을 돌려준다. 그러면 정규화는 **아무 일도 하지 않고**
      리포트 라인은 종전 경로 그대로다(마이그레이션 없음).

    순서: 컴파일(논증 전체) → 컷 배정 → **화면 투영**(컷이 붙은 것만, 화면 순서로).
    마지막 단계가 없으면 세계가 이어지지 않는다(`project_to_screen` 주석 참조).
    """
    return project_to_screen(assign_cuts(compile_sequences(reasoning), cuts))


def summary(sequences: list[dict[str, Any]]) -> dict[str, Any]:
    """편 단위 요약. 운영자·원장이 같은 숫자를 본다."""
    stages = [st for s in sequences for st in s.get("stages") or []]
    return {
        "sequences": len(sequences),
        "stages": len(stages),
        "progressions": sum(1 for s in sequences
                            if visual_sequence.sequence_is_progression(s)),
        "precision_layers": sum(1 for st in stages if st.get("precision_layer")),
        # 어휘가 안 맞아 기본값으로 채운 단계 — 많으면 번역표를 넓혀야 한다는 신호다.
        "semantic_defaulted": sum(1 for st in stages
                                  if not st.get("equity_semantic_matched")),
    }
