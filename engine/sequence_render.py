"""시퀀스 → 렌더 결정 (v3 Phase 3).

무엇을 푸는가: Phase 1·2 가 `resolved_visual_plan` 과 `visual_sequences` 를 만들었는데
**렌더가 그것을 읽지 않았다.** 저장소 지도를 떠 보니 그 세 필드의 참조가 렌더 경로에
정확히 0곳이었다 — 정본 작업지시서가 경고한 "schema field 를 만들었지만 renderer 가
무시한다"가 실제로 그 상태였다. 이 모듈이 그 다리다.

이 모듈이 답하는 질문은 하나다:

    이 컷의 그림을 만들 때 **무엇을 참조로 넣어야 하는가?**

    없음        NEW_WORLD — 새 세계다. 텍스트만으로 그린다
    참조 생성   앞 stage 의 그림을 시작 프레임으로 주고 상태만 바꾼다
    파생        RETURN_WORLD — 이미 그린 세계로 돌아간다. 새로 만들 이유가 없다(크롭·톤)

★ 순수 모듈이다 — 파일을 읽지도 만들지도 않고 네트워크·DB 를 모른다. 입력은 컷·헤더와
  "지금까지 어떤 stage 의 그림이 생겼는가"라는 dict 뿐이다. 그래서 라이브 키 없이 테스트된다.

★ **판정 불가와 실패를 섞지 않는다**(이 저장소의 반복되는 규율). 참조를 못 붙인 경우
  `degraded_*` 사유를 남기고 진행한다 — 렌더를 죽이지 않되 조용히 넘어가지도 않는다.
  Phase 0 이 실측한 것은 "참조를 주면 세계가 유지된다"이지 "항상 참조를 붙일 수 있다"가 아니다.
"""

from __future__ import annotations

from typing import Any

from . import config, generation_spec, visual_sequence


def plan_of(cut: dict[str, Any]) -> dict[str, Any]:
    """이 컷의 **정본 시각 계획**. 없으면 빈 dict(옛 지시서 — 종전 경로 그대로)."""
    plan = cut.get("resolved_visual_plan")
    return plan if isinstance(plan, dict) else {}


def stage_index(header: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """컷 번호 → 그 컷을 담당하는 stage. 시퀀스가 없으면 빈 dict.

    ★ `visual_sequence.cut_to_stage` 를 그대로 쓴다 — 지시서 생성과 렌더가 **같은 색인**을
      보게 한다. 두 벌로 만들면 한쪽만 고쳐지는 날이 온다.
    """
    seqs = header.get("visual_sequences")
    if not isinstance(seqs, list) or not seqs:
        return {}
    return visual_sequence.cut_to_stage(seqs)


def reference_decision(cut: dict[str, Any], header: dict[str, Any],
                       stage_assets: dict[str, str],
                       *, generation_mode: str | None = None) -> dict[str, Any]:
    """이 컷을 무엇으로 만들 것인가.

    반환:
      kind        `new_world` | `reference` | `derive` | `none`
      ref_stage   참조·파생의 원본 stage_id ("" 이면 없음)
      ref_asset   그 stage 의 그림 경로 ("" 이면 없음)
      reference_key  캐시 키에 실을 값(참조가 없으면 "")
      stage_id    이 컷이 속한 stage
      degraded    붙이지 못한 이유 코드 목록(비면 정상)

    `stage_assets` 는 **지금까지 만들어진** stage 그림들이다: {stage_id: 파일경로}.
    호출부가 컷을 순서대로 돌면서 채운다.
    """
    stage = stage_index(header).get(int(cut.get("cut_no") or 0)) or {}
    stage_id = str(stage.get("stage_id") or "")
    out: dict[str, Any] = {"kind": "none", "ref_stage": "", "ref_asset": "",
                           "reference_key": "", "stage_id": stage_id, "degraded": []}
    if not stage:
        return out                      # 시퀀스에 속하지 않는 컷 — 종전 경로 그대로

    mode = str(stage.get("continuity_mode") or "")
    if mode not in config.CONTINUITY_NEEDS_REFERENCE:
        out["kind"] = "new_world"
        return out

    # ★★ **정본이 이 컷을 그 세계 안에 두었는가.** stage 소속만으로는 부족하다
    #   (2026-08-30 Mini Render B 실측 — 이 한 줄이 없어서 우주 장면이 회의실 모니터가 됐다).
    #
    #   라우터는 주장을 지불하지 않는 컷을 `connective_in_world` 로 판정한다 — 배경 세계는
    #   물려받되 **기전 도해는 아니다**(코덱스 리뷰 §10). 그런 컷의 내용은 애초에 다른
    #   장면이다: 골든B 컷3 은 "arXiv 논문"을 그리라고 한다. 거기에 앞 stage 의 우주
    #   프레임을 시작 화면으로 주면 모델이 둘을 억지로 합쳐 **우주를 모니터에 띄운
    #   회의실**을 그린다(실측). 그리고 그 모니터에 'arXiv' 글자가 박힌다.
    #
    #   즉 "같은 세계를 잇는다"와 "이 컷이 그 세계를 그린다"는 다른 말이다.
    #   전자만 보고 참조를 걸면 세계가 이어지는 게 아니라 **오염된다.**
    plan = plan_of(cut)
    if plan.get("beat_declared") and plan.get("base") != "MECHANISM_SEQUENCE":
        out["kind"] = "connective"
        out["ref_stage"] = str(stage.get("continuity_from") or "")
        return out

    # 여기부터는 **참조가 필요한 컷**이다. 못 붙이면 그 사실을 남긴다.
    if not config.SEQUENCE_REFERENCE_ENABLED:
        out["kind"] = "new_world"
        out["degraded"] = ["degraded_reference_disabled"]
        return out

    # ★ Batch 는 참조를 실을 수 없다 — 요청이 렌더 **시작 전에** 제출되므로 앞 stage 의
    #   그림이 그때 존재하지 않는다. 강제 실시간 스위치가 꺼져 있으면 그 사실을 남긴다.
    mode_now = generation_mode or config.IMAGE_GENERATION_MODE
    if mode_now == "batch" and not config.SEQUENCE_REFERENCE_FORCES_REALTIME:
        out["kind"] = "new_world"
        out["degraded"] = ["degraded_batch_mode"]
        return out

    ref_stage = str(stage.get("continuity_from") or "")
    ref_asset = stage_assets.get(ref_stage) or ""
    if not ref_asset:
        # 앞 stage 의 그림이 없다(생성 실패했거나 아직 안 만들어졌다).
        #   ★ 차단하지 않는다: 그림 하나가 없다고 편 전체를 죽이면 운영이 멈춘다.
        #     대신 `degraded_continuity` 로 남겨 승인 화면과 원장이 그 사실을 본다.
        out["kind"] = "new_world"
        out["degraded"] = ["degraded_no_reference_frame"]
        return out

    # ★ RETURN_WORLD 는 **다시 만들지 않는다.** 이미 그린 세계로 돌아가는 것이므로 크롭·톤
    #   파생이 더 정확하고(같은 픽셀에서 나온다) 생성 호출이 0이다. 작업계획서 Phase 3 의
    #   "RETURN_WORLD 는 crop 파생 우선"이 이 줄이다.
    #
    # ★★ **단, 그 stage 가 눈에 보이는 변화를 선언했으면 파생하지 않는다**
    #   (2026-08-30 골든B 완성본 실측). 파생은 크롭·톤만 적용할 수 있고 `mutations` 를
    #   읽지 않는다 — `render._derive_from_stage` 는 크롭 선언이 없으면 앞 그림을
    #   **바이트 복사**한다. 그래서 컷6이 "궤적선 하나를 강조"(HIGHLIGHT,
    #   visible_change=true)라고 선언했는데 화면에는 S1 그림이 그대로 나갔다.
    #   게이트는 전부 통과했고(degraded_continuity 비어 있음) **조립해서 눈으로 봐야**
    #   보였다. 작업계획서 §9-9 Q9 가 예고한 바로 그 퇴행이다:
    #     "렌더가 그것을 파일 복사로 구현하면 퇴행한다 → Phase 3 배선에서 반드시 본다."
    #
    #   판정은 `visual_sequence.stage_has_progress` **정본 하나**로 한다(코덱스 리뷰 S4 —
    #   같은 질문에 두 벌의 답을 만들면 한쪽만 고쳐지는 날이 온다).
    #
    #   변화가 있으면 참조 조건 생성으로 간다. 같은 그림을 **시작 프레임**으로 주므로
    #   세계는 그대로 유지되고 변화만 일어난다(Phase 0 이 실측한 그것이다). 파생보다
    #   생성 호출이 1회 늘지만, **선언한 변화가 화면에서 조용히 사라지는 것보다 낫다** —
    #   운영자가 §8 에서 "편당 비용 2배까지 허용"으로 확정한 범위 안이다.
    if (mode == "RETURN_WORLD" and config.RETURN_WORLD_PREFERS_DERIVE
            and not visual_sequence.stage_has_progress(stage)):
        out.update(kind="derive", ref_stage=ref_stage, ref_asset=ref_asset,
                   # ★ 파생도 키를 싣는다. 파생이 실패해 참조 생성으로 떨어질 때
                   #   키가 비어 있으면 참조로 만든 그림과 텍스트로 만든 그림이 **같은
                   #   캐시 키**를 갖는다(이 파일 reference_key 독스트링의 그 사고).
                   reference_key=reference_key(stage, ref_stage))
        return out

    out.update(kind="reference", ref_stage=ref_stage, ref_asset=ref_asset,
               reference_key=reference_key(stage, ref_stage))
    return out


def reference_key(stage: dict[str, Any], ref_stage: str) -> str:
    """참조 조건 생성의 **논리적** 캐시 키.

    ★ 파일 바이트가 아니라 **그 그림을 결정한 값**을 해시한다(generation_spec 의 관례 그대로).
      그래야 렌더를 돌리지 않고도 키를 계산할 수 있다.

    ★★ 이 키가 없으면 참조로 만든 그림과 텍스트로 만든 그림이 **같은 캐시 키**를 갖는다.
      이 저장소는 이미 그 사고를 한 번 겪었다 — `VideoSpec.start_asset_hash` 가 없던 시절
      I2V 연쇄에서 앞 컷이 바뀌어도 뒤 컷이 옛 클립을 재사용했다.
    """
    return generation_spec.asset_logical_hash({
        "ref_stage": ref_stage,
        "stage_id": stage.get("stage_id"),
        "continuity_mode": stage.get("continuity_mode"),
        "operation": stage.get("operation"),
        "camera_operation": stage.get("camera_operation"),
        # 상태는 **코드가 계산한 것**을 쓴다. 모델이 쓴 서술을 키에 넣으면 같은 변화를
        # 다르게 적기만 해도 캐시가 깨진다(그 반대도 문제다).
        "state_after": stage.get("state_after_computed") or stage.get("state_after") or {},
        "mutations": [{"entity_id": m.get("entity_id"), "operation": m.get("operation"),
                       "property": m.get("property")}
                      for m in (stage.get("mutations") or [])],
    })


def change_prose(stage: dict[str, Any]) -> str:
    """이 stage 에서 **무엇만 바뀌는지**를 한 줄로. 참조 프롬프트의 꼬리에 붙는다.

    ★ 변이 선언(mutations)을 우선한다 — 구조가 서술보다 정확하다. 없으면 사람이 쓴
      `observable_change` 로 후퇴한다(옛 지시서 하위호환).
    """
    muts = [m for m in (stage.get("mutations") or []) if m.get("entity_id")]
    if muts:
        parts = []
        for m in muts:
            target = str(m.get("entity_id"))
            result = str(m.get("result_state") or "").strip()
            op = str(m.get("operation") or "").lower().replace("_", " ")
            parts.append(f"{target} {op}" + (f" to {result}" if result else ""))
        return "; ".join(parts)
    return str(stage.get("observable_change") or "").strip()


def appearing_entity_prose(stage: dict[str, Any], sequence: dict[str, Any] | None) -> str:
    """이 stage 에서 **새로 등장하는** 개체들의 외형 서술.

    ★ 왜 필요한가(2026-08-30 채팅 실측): 참조 프롬프트를 "변화만" 말하도록 고치면서
      **개체가 어떻게 생겼는지를 같이 떨어뜨렸다.** 궤적선을 `Glowing blue line` 이라고
      선언해 뒀는데 프롬프트에 안 실려서 화면엔 주황색으로 나왔다(화풍 접미사의
      amber accent 가 대신 결정한 것이다).

    ★ **새로 등장하는 것만** 싣는다. 이미 화면에 있는 개체는 참조 이미지가 이미 보여 주고
      있으므로, 그 외형을 또 말하면 "바꾸라"는 신호로 읽힐 수 있다.
      선언은 이미 구조로 있다(entities[].visual_identity) — 만들어 놓고 배선하지 않았던
      `visual_sequence.entity_prose` 를 여기서 잇는다.
    """
    appears = [str(m.get("entity_id")) for m in (stage.get("mutations") or [])
               if m.get("operation") == "APPEAR" and m.get("entity_id")]
    if not appears:
        return ""
    return visual_sequence.entity_prose((sequence or {}).get("entities") or [], appears)


def degraded_summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """편 단위 요약. 운영자·원장이 같은 숫자를 본다.

    ★ `world_reset` 을 세는 것이 v3 의 핵심 지표다(작업계획서 Phase 3 "원장에 stage·
      world reset 기록"). 세계를 자주 새로 만들면 "시퀀스"라고 부르지만 실은 컷 나열이다.
    """
    counts: dict[str, int] = {}
    for d in decisions:
        for code in d.get("degraded") or []:
            counts[code] = counts.get(code, 0) + 1
    return {
        "stages_rendered": sum(1 for d in decisions if d.get("stage_id")),
        "reference_conditioned": sum(1 for d in decisions if d.get("kind") == "reference"),
        "derived": sum(1 for d in decisions if d.get("kind") == "derive"),
        "world_reset": sum(1 for d in decisions if d.get("kind") == "new_world"),
        # 세계 배경만 물려받는 연결 컷 — 참조를 걸지 **않는 것이 정상**이다(저하가 아니다).
        "connective": sum(1 for d in decisions if d.get("kind") == "connective"),
        "degraded_continuity": counts,
    }
