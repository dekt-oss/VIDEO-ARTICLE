"""Visual Sequence — 스키마·정규화 (v3 Phase 1).

무엇이 달라지는가: 영상의 기본 단위가 **독립 컷의 나열**에서 **하나의 세계가 단계적으로
변하는 시퀀스**로 바뀐다.

    v2:  Cut 1 · Cut 2 · Cut 3          (컷 경계 = 세계 리셋)
    v3:  Sequence A [ Stage A1 → A2 → A3 ]   (컷은 나레이션·타이밍 단위로 존속)

★ 왜 이 전환이 필요한가 — v2 실측이 스스로 증명했다. 11컷짜리 영상에서 원본 이미지가
  6장뿐이었고 컷5·6 은 바이트까지 같은 파일이었다. 원인은 게으름이 아니라 **구조**다:
  컷마다 새로 그리면 같은 인물이 다른 사람이 되므로, "연속성"을 표현할 유일한 수단이
  파일 복사였다. 연속성과 복붙이 같은 것이 되어 버린 것이다.

  Phase 0 실측(docs/실측_continuity_v3.md)에서 셋이 갈라졌다:
    NEW_WORLD      새 세계
    CONTINUE_WORLD 같은 세계의 다음 상태   ← 참조 조건 생성으로 가능함이 확인됨(단가 동일)
    REUSE          같은 파일                ← 변화가 없으면 금지(기존 게이트)

이 모듈의 책임은 **모양을 강제하는 것**까지다. "진행이 진짜인가"는
`visual_sequence_contract.py` 가 판정하고, 화면에서 실제로 달라졌는지는 렌더 뒤
멀티모달 QA 가 본다(Phase 3). 세 층을 섞지 않는다.

순수 모듈이다 — 네트워크·DB 를 모른다.
"""

from __future__ import annotations

import re
from typing import Any

from . import config

# 규격 토큰 제거기. config 의 패턴을 한 번만 컴파일한다.
_SPEC_TOKEN = re.compile(config.SPEC_TOKEN_PATTERN)
_MULTISPACE = re.compile(r"\s{2,}")


def scrub_spec_tokens(text: str) -> str:
    """프롬프트 본문에서 **규격 토큰을 지운다**(각도·렌즈·해상도 표기).

    ★ 왜 필요한가(Phase 0 실측 §3-3): 세계 프롬프트에 `35 degree isometric camera` 를
      넣었더니 Veo 가 화면에 **"35°" 를 글자로 그렸다.** 같은 날 아침 이미지에서 잡은
      `MECHANISM` 누출과 같은 계열 — 기계에게 하는 말이 화면에 그려진다.

    ★ 금지어 목록으로는 못 막는다: "35 degree isometric camera" 는 정당한 카메라 서술이다.
      단어가 아니라 **형태**(숫자+단위)를 지운다. 남은 문장은 여전히 뜻이 통한다:
      "35 degree isometric camera" → "isometric camera".
    """
    return _MULTISPACE.sub(" ", _SPEC_TOKEN.sub("", str(text or ""))).strip(" ,")


def _enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """대소문자만 맞춰 주는 enum 강제. 모르는 값은 조용히 기본값으로 — 실패시키지 않는다.

    ★ allowed 의 표기(대문자 operation / 소문자 camera_base)를 그대로 존중한다.
      한쪽으로 통일하지 않는 이유: operation 은 코드 상수처럼 읽히고 camera_base 는
      설정값처럼 읽히는 것이 호출부에서 자연스럽다.
    """
    tok = str(value or "").strip()
    for a in allowed:
        if tok.upper() == a.upper():
            return a
    return default


def normalize_world(raw: Any) -> dict[str, Any]:
    """VisualWorld — 시퀀스 안에서 고정되는 것들.

    ★ 카메라는 **구조화 토큰**으로만 받는다(자유 문장 금지). 산문 변환은 camera_prose()
      가 하고, 그 결과에는 숫자 규격이 들어가지 않는다.
    """
    d = raw if isinstance(raw, dict) else {}
    return {
        "world_id": str(d.get("world_id") or "").strip(),
        # 화풍·조명·배경은 자유 문장을 허용하되 규격 토큰은 지운다.
        "style": scrub_spec_tokens(d.get("style")),
        "lighting": scrub_spec_tokens(d.get("lighting")),
        "background": scrub_spec_tokens(d.get("background")),
        # ★ 한글 쌍둥이(2026-09-17 운영자 지시: "영어로 되어있는건 한글로도 같이 입력해줘").
        #   **렌더·게이트는 영어 원문만 쓴다** — 이 값은 화면에서 사람이 읽는 용도다.
        #   여기 안 적으면 정규화가 모델이 준 한글을 통째로 버린다(이 함수는 고정 키만 남긴다).
        "style_ko": str(d.get("style_ko") or "").strip(),
        "lighting_ko": str(d.get("lighting_ko") or "").strip(),
        "background_ko": str(d.get("background_ko") or "").strip(),
        "camera_base": _enum(d.get("camera_base"), config.CAMERA_BASES,
                             config.DEFAULT_CAMERA_BASE),
        "identity_lock": bool(d.get("identity_lock", True)),
    }


def normalize_entity(raw: Any) -> dict[str, Any]:
    """PersistentEntity — stage 를 건너 유지되어야 하는 개체."""
    d = raw if isinstance(raw, dict) else {}
    return {
        "entity_id": str(d.get("entity_id") or "").strip(),
        "entity_type": str(d.get("entity_type") or "").strip(),
        # 렌더가 프롬프트에 실을 짧은 외형 서술. 여기도 규격 토큰은 지운다.
        "visual_identity": scrub_spec_tokens(d.get("visual_identity")),
        # ★ 한글 쌍둥이(2026-09-17 운영자 지시: "영어로 되어있는건 한글로도 같이 입력해줘").
        #   **렌더·게이트는 영어 원문만 쓴다** — 이 값은 화면에서 사람이 읽는 용도다.
        #   여기 안 적으면 정규화가 모델이 준 한글을 통째로 버린다(이 함수는 고정 키만 남긴다).
        "visual_identity_ko": str(d.get("visual_identity_ko") or "").strip(),
        "continuity": "locked" if str(d.get("continuity") or "locked") == "locked" else "free",
    }


def normalize_mutation(raw: Any) -> dict[str, Any]:
    """StateMutation — **LLM 이 제안하는 것은 변화(delta)뿐이다**(코덱스 리뷰 S1).

    ★ 왜 상태 두 벌을 안 받는가: `state_before` 와 `state_after` 를 **둘 다 모델이 쓰면**
      진행 판정이 결국 자기보고가 된다. 모델이 `standing` → `standing calmly` 처럼 형식만
      다르게 써도 "달라졌다"로 통과한다. 그래서 모델은 **무엇이 어떻게 바뀌는지**만 적고
      상태 자체는 코드가 계산한다(compute_lineage).

    ★ operation 은 닫힌 목록이다. 자유 문장이면 같은 문제가 되돌아온다.
    """
    d = raw if isinstance(raw, dict) else {}
    return {
        "entity_id": str(d.get("entity_id") or "").strip(),
        "property": str(d.get("property") or "").strip(),
        "operation": _enum(d.get("operation"), config.MUTATION_OPERATIONS, "TRANSFORM"),
        # 화면에서 **눈에 보이게** 달라지는가. 보이지 않는 변화는 진행이 아니다.
        "visible_change": bool(d.get("visible_change", True)),
        # 이 변화가 무엇으로 보이는지(사람 말). 상태 계산의 값으로도 쓰인다.
        "result_state": scrub_spec_tokens(d.get("result_state")),
        "claim_ids": [str(x).strip() for x in (d.get("claim_ids") or []) if str(x).strip()],
    }


def normalize_stage(raw: Any, index: int) -> dict[str, Any]:
    """Stage — 세계 안에서 일어나는 한 단계의 상태 변화."""
    d = raw if isinstance(raw, dict) else {}
    cut_refs = [int(x) for x in (d.get("cut_refs") or []) if str(x).strip().lstrip("-").isdigit()]
    return {
        "stage_id": str(d.get("stage_id") or f"S{index}").strip(),
        "cut_refs": cut_refs,
        # ★ 이 stage 가 어느 수준의 표현인가(코덱스 리뷰 §11). claim_id 가 맞아도 묘사가
        #   틀릴 수 있다 — 골든B 분광이 그랬다(원문은 지상 관측, 화면은 우주에서 조사).
        "representation_mode": _enum(d.get("representation_mode"),
                                     config.REPRESENTATION_MODES,
                                     config.DEFAULT_REPRESENTATION_MODE),
        # ★ 연결·CTA 컷을 세계 배경만 물려받게 하는 **명시적** 예외(코덱스 리뷰 §10).
        #   기본은 False 다 — 컷이 stage 에 들어 있다는 것만으로 기전 시퀀스가 되면
        #   골든B 의 CTA 컷15 처럼 "댓글 남겨주세요"가 기전 stage 가 된다.
        "allow_connective": bool(d.get("allow_connective", False)),
        "mutations": [normalize_mutation(m) for m in (d.get("mutations") or [])
                      if isinstance(m, dict)],
        "operation": _enum(d.get("operation"), config.VISUAL_OPERATIONS, "REVEAL"),
        "camera_operation": _enum(d.get("camera_operation"), config.CAMERA_OPERATIONS, "HOLD"),
        # ★★ **축척은 stage 가 바꾼다**(2026-09-04). 종전에는 camera_base 가 world 에만
        #   있어서, 세계를 하나로 유지하면(=우리가 원하는 것) 화면 축척이 영영 하나였다.
        #   프롬프트는 "세계 안에서 camera_base 를 바꿔라"라고 지시하는데 **담을 칸이
        #   없었다** — 지시와 스키마가 어긋나 있었다.
        #   벤치마크가 하는 일이 정확히 이것이다: 같은 시화호에 머물며 광역 부감 →
        #   중경 → 손바닥 클로즈업으로 내려간다(3초 만에).
        # ★ 비우면 world 의 값을 쓴다 — 옛 지시서는 그대로 돈다.
        "camera_base": _enum(d.get("camera_base"), config.CAMERA_BASES, ""),
        "continuity_mode": _enum(d.get("continuity_mode"), config.CONTINUITY_MODES,
                                 config.DEFAULT_CONTINUITY_MODE),
        "continuity_from": str(d.get("continuity_from") or "").strip(),
        "entity_refs": [str(x).strip() for x in (d.get("entity_refs") or []) if str(x).strip()],
        # 상태는 자유 dict 다 — 도메인마다 다르다(토큰 개수 / 수주 잔고 / 강조 부위).
        "state_before": d.get("state_before") if isinstance(d.get("state_before"), dict) else {},
        "state_after": d.get("state_after") if isinstance(d.get("state_after"), dict) else {},
        # ★ 계약의 핵심: **화면에서 무엇이 보이게 달라지는가**를 사람 말로 적는다.
        "observable_change": str(d.get("observable_change") or "").strip(),
        # ★ 한글 쌍둥이(2026-09-17 운영자 지시: "영어로 되어있는건 한글로도 같이 입력해줘").
        #   **렌더·게이트는 영어 원문만 쓴다** — 이 값은 화면에서 사람이 읽는 용도다.
        #   여기 안 적으면 정규화가 모델이 준 한글을 통째로 버린다(이 함수는 고정 키만 남긴다).
        "observable_change_ko": str(d.get("observable_change_ko") or "").strip(),
        "claim_ids": [str(x).strip() for x in (d.get("claim_ids") or []) if str(x).strip()],
        "visual_prompt": scrub_spec_tokens(d.get("visual_prompt")),
    }


def normalize_sequence(raw: Any, index: int = 1) -> dict[str, Any]:
    d = raw if isinstance(raw, dict) else {}
    stages = [normalize_stage(s, i) for i, s in enumerate(d.get("stages") or [], 1)]
    return {
        "sequence_id": str(d.get("sequence_id") or f"SEQ{index}").strip(),
        "sequence_role": _enum(d.get("sequence_role"), config.SEQUENCE_ROLES, "FRAMING"),
        "world": normalize_world(d.get("world")),
        "entities": [normalize_entity(e) for e in (d.get("entities") or [])],
        "stages": stages,
    }


# ─────────────────────────────────────────────────────────────
# State Ledger — 상태는 **코드가 계산한다** (코덱스 리뷰 S1·S2, 2026-08-30)
# ─────────────────────────────────────────────────────────────
# "없다"를 뜻하는 상태값. 이런 값은 **물려받겠다는 주장이 아니다** — 앞 stage 에 그 개체가
# 없었다는 사실을 적은 것이므로 lineage 검사에서 제외한다.
#   ★ 이 예외가 없으면 골든A S5 의 `MALE_CHARACTER_B: "not present"` 가 오탐 차단된다.
#     옳게 쓴 것을 벌하는 게이트는 무시당한다.
#   ★ "No NAD+ molecules visible." 도 없다는 서술이다(2026-09-14 저장 지시서 4baede40 실측).
#     종전 목록은 `not …` 로 시작하는 것만 알아서 이것을 "물려받았다"로 셌다.
_ABSENCE = re.compile(
    r"^(?:not\s+(?:present|yet|shown|visible|introduced)|absent|none|empty|"
    r"no\s+[^.]{0,60}?(?:visible|present|shown|yet)\b|"
    r"없음|아직\s*없|없다|미등장)", re.I)


def _is_absence(value: Any) -> bool:
    return bool(_ABSENCE.match(str(value or "").strip()))


def _mutation_state(mutation: dict[str, Any]) -> str:
    """변이 하나가 만드는 상태값. result_state 를 우선하고, 없으면 연산·속성으로 적는다."""
    if mutation.get("result_state"):
        return str(mutation["result_state"])
    prop = mutation.get("property") or "state"
    return f"{prop}: {mutation.get('operation')}"


def compute_lineage(sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """각 stage 에 **코드가 계산한 상태**를 붙인다(제자리 갱신 후 반환).

        state_before_computed = continuity_from 이 만든 상태 (NEW_WORLD 면 빈 dict)
        state_after_computed  = state_before_computed + mutations

    ★ 모델이 쓴 `state_before`/`state_after` 는 지우지 않는다 — 사람이 읽는 서술로 남기고,
      **어긋남을 판정하는 근거**로 쓴다(visual_sequence_contract 의 lineage 검사).
      계산값과 선언값을 나란히 두는 것이 요점이다: 하나만 있으면 대조할 것이 없다.

    ★ 선언 순서대로 한 번만 훑는다. 앞선 stage 를 가리키는 것이 계약이므로(VSEQ-3)
      역방향 참조는 계산 대상이 없고, 그 경우 `state_before_computed` 는 빈 dict 가 된다.
      그것 자체가 dangling 검사에서 이미 잡힌다 — 여기서 두 번 벌하지 않는다.
    """
    computed: dict[str, dict[str, Any]] = {}
    for seq in sequences:
        for st in seq.get("stages") or []:
            mode = str(st.get("continuity_mode") or "")
            ref = str(st.get("continuity_from") or "")
            if mode in config.CONTINUITY_NEEDS_REFERENCE and ref in computed:
                before = dict(computed[ref])
            else:
                # ★★ 새 세계는 **모델이 선언한 시작 상태**에서 출발한다(2026-08-30 실측 수정).
                #
                #   처음에 빈 dict 로 시작했더니 **세계에 있지만 변하지 않는 개체가 원장에서
                #   사라졌다.** 골든B 재생성이 그것을 드러냈다: S1 이 달 표면을 배경으로
                #   선언했는데 변이는 로켓에만 걸어서, 계산된 상태에 달이 없어졌다. 그래서
                #   뒤 stage 세 개가 "달을 물려받았다"고 적었다는 이유로 오탐 차단됐다.
                #
                #   물려받을 것이 없는 stage 에서는 모델의 선언이 **유일한 근거**이므로 이것을
                #   신뢰한다. 자기보고를 믿는 것이 아니다 — 여기엔 대조할 앞 상태가 없다.
                #   진행 판정은 여전히 mutations 가 하고(after 는 before + 변이),
                #   대조는 **이어받는 stage** 에서만 의미가 있다.
                before = dict(st.get("state_before") or {})
            after = dict(before)
            for m in st.get("mutations") or []:
                eid = m.get("entity_id")
                if not eid:
                    continue
                if m.get("operation") == "DISAPPEAR":
                    after.pop(eid, None)
                else:
                    after[eid] = _mutation_state(m)
            # 변이 선언이 없는 옛 지시서는 모델이 쓴 state_after 를 그대로 계승 상태로 쓴다
            # (하위호환 — 시퀀스 있는 옛 지시서를 계산 불가로 만들지 않는다).
            if not (st.get("mutations") or []) and isinstance(st.get("state_after"), dict):
                after = {**after, **st["state_after"]}
            # ★★ **여는 stage 는 state_after 로 세계의 내용물을 마저 채운다**(2026-09-02 실측).
            #
            #   2026-08-30 에 "빈 dict 로 시작하면 안 변하는 배경이 사라진다"를 고치면서
            #   씨앗을 `state_before` 로 잡았다. 그런데 **여는 stage 의 state_before 는 비는
            #   것이 자연스럽다** — 그 앞에는 아무것도 없기 때문이다. 실측(Moon Impactor):
            #       S1  before={}  after={MOON, FALCON9}  mutations=[FALCON9 APPEAR]
            #   MOON 은 state_after 에만 있어서 계산 상태에서 사라졌고, S2~S4 가 변한 로켓만
            #   싣고 가는 사이 MOON 이 원장에서 증발했다. 그래서 S5 가 "달을 물려받았다"고
            #   옳게 적었는데 `vseq_state_lineage_mismatch` 로 **정상인데 차단**됐다.
            #   8/30 에 고친 것과 **같은 오탐이 여는 stage 에서 재발한 것**이다.
            #
            #   ★ 이미 있는 키는 덮지 않는다 — 진행 판정은 여전히 mutations 가 한다.
            #     비어 있던 자리만 채운다(세계의 내용물 ≠ 변화의 근거).
            #   ★ 골든B 는 그대로 차단된다(회귀 테스트로 박아 둠): 그 S1 의 state_after 에는
            #     MOON_SURFACE 가 **없어서** S6 의 "Cratered surface" 는 여전히 계보 위반이다.
            if not (mode in config.CONTINUITY_NEEDS_REFERENCE and ref in computed):
                for eid, val in (st.get("state_after") or {}).items():
                    after.setdefault(eid, val)
            st["state_before_computed"] = before
            st["state_after_computed"] = after
            computed[str(st.get("stage_id"))] = after
    return sequences


def repair_lineage_appears(sequences: list[dict[str, Any]]) -> list[str]:
    """앞 stage 에 없던 **선언된 개체**를 state_before 에 적었으면 APPEAR 변이로 옮긴다 → 고친 자리.

    ★ 2026-09-14 실측: 저장된 실사형 지시서 중 시퀀스가 있는 29편에서 7편(24%, 성격 유전 원본 포함)이
      `vseq_state_lineage_mismatch` 로 막혔고, 문제 키 **전부**가 그 시퀀스의 entities 에 선언된
      개체였다. 운영자가 손으로 한 수정도 매번 같았다 — 그 개체를 APPEAR 로 앞에 넣고
      state_before 에서 뺀다. 프롬프트·되먹임이 이미 "새로 등장시키려면 APPEAR"라고 시키는데
      모델이 매번 한둘을 흘린다. 모양이 정해진 수리라 코드가 한다(normalize_optics 와 같은 자세).

    ★ 지어내지 않는다: entities 에 **선언되지 않은** 개체는 손대지 않는다 — 그건 무엇이 화면에
      나오는지의 문제라 게이트(vseq_state_entity_undeclared / lineage)와 되먹임이 되묻는다.
    ★ 한 stage 를 고치면 뒤 stage 의 계산 상태가 달라지므로 고칠 때마다 계보를 다시 계산한다
      (앞에서 등장시킨 개체를 뒤 stage 가 물려받는 것은 정상이 된다).
    """
    touched: list[str] = []
    for seq in sequences:
        declared = {str(e.get("entity_id")) for e in (seq.get("entities") or [])
                    if str(e.get("entity_id") or "").strip()}
        for st in seq.get("stages") or []:
            mode = str(st.get("continuity_mode") or "")
            # ★ RETURN_WORLD 는 고치지 않는다. 앞 세계로 **되돌아가며** 거기 없던 것을 적은 것은
            #   대개 가리킨 원본을 틀린 것이다(골든B S6 "Cratered surface after impact" 가 S1 을
            #   가리켰다) — APPEAR 로 덮으면 논리 오류가 "분화구가 나타난다"로 숨는다.
            #   실측 7건은 전부 CONTINUE_WORLD 였다.
            if mode not in config.CONTINUITY_NEEDS_REFERENCE or mode == "RETURN_WORLD":
                continue
            ref = str(st.get("continuity_from") or "")
            src = stage_index(sequences).get(ref)
            if src is None:
                continue                      # dangling 은 별도 차단이 잡는다
            src_after = src.get("state_after_computed") or {}
            before = st.get("state_before")
            if not isinstance(before, dict):
                continue
            appears = {str(m.get("entity_id")) for m in (st.get("mutations") or [])
                       if m.get("operation") == "APPEAR"}
            moved = [k for k, v in before.items()
                     if not _is_absence(v) and str(k) not in appears
                     and str(k) not in src_after and str(k) in declared]
            if not moved:
                continue
            new_muts = [{"entity_id": str(k), "property": "presence", "operation": "APPEAR",
                         "visible_change": True, "result_state": scrub_spec_tokens(before[k]),
                         "claim_ids": list(st.get("claim_ids") or [])} for k in moved]
            st["mutations"] = [*new_muts, *(st.get("mutations") or [])]
            st["state_before"] = {k: v for k, v in before.items() if k not in moved}
            touched.append(f"{seq.get('sequence_id')}/{st.get('stage_id')}({', '.join(moved[:3])})")
            compute_lineage(sequences)
    return touched


def stage_entity_ids(stage: dict[str, Any]) -> set[str]:
    """이 stage 가 **어떤 식으로든 언급하는** 개체 전부(코덱스 리뷰 S3).

    ★ 종전에는 `entity_refs` 만 봤다. 그래서 골든A S5 가 `state_after` 에
      `FEMALE_CHARACTER_SILHOUETTE`·`HIGH_TRUST_MALE_SILHOUETTE` 를 선언 없이 등장시켰는데
      게이트가 통과시켰다 — **선언하지 않은 인물이 화면에 나온다**는 뜻이다.
    """
    out = {str(x) for x in (stage.get("entity_refs") or []) if str(x).strip()}
    for key in ("state_before", "state_after"):
        val = stage.get(key)
        if isinstance(val, dict):
            out |= {str(k) for k in val if str(k).strip()}
    out |= {str(m.get("entity_id")) for m in (stage.get("mutations") or [])
            if str(m.get("entity_id") or "").strip()}
    return out


def stage_has_progress(stage: dict[str, Any]) -> bool:
    """이 stage 에서 **눈에 보이는 변화가 일어나는가.**

    변이 선언이 있으면 그것으로 판정한다(구조). 없으면 옛 지시서이므로 서술 차이로
    후퇴 판정한다 — 다만 **차단은 서술로 하지 않는다**(vseq_no_actual_mutation 이 별도로
    변이 선언을 요구한다). 흐린 판정에 차단 일을 시키지 않는 것이 이 분리의 요점이다.
    """
    muts = stage.get("mutations") or []
    if muts:
        return any(m.get("visible_change") for m in muts)
    before, after = stage.get("state_before") or {}, stage.get("state_after") or {}
    if before != after:
        return True
    return bool(stage.get("observable_change")) and not before and not after


def sequence_is_progression(seq: dict[str, Any] | None) -> bool:
    """이 시퀀스가 **실제로 진행하는가** — 모델이 붙인 sequence_role 라벨을 믿지 않는다.

    ★ 왜 라벨을 안 보는가(2026-08-29 골든 실측): Moon Impactor 지시서의 시퀀스는 세계 하나에서
      6단계가 이어지는 완벽한 기전 진행이었는데 모델은 그것을 `RESULT_SEQUENCE` 라고 라벨했다.
      라벨을 믿었더니 `mechanism_sequences: 0` 이 나왔다. **구조를 보고 코드가 판정한다.**

    ★ 이 함수가 정본이다. 라우터·계약·지표가 **전부 여기를 부른다**(코덱스 리뷰 S4) —
      라우터만 고치고 지표를 안 고쳐서 같은 지시서가 서로 다른 답을 냈던 것이 실측 결함이다.
    """
    stages = (seq or {}).get("stages") or []
    if len(stages) < 2:
        return False
    return any(stage_has_progress(st) for st in stages)


def normalize_all(raw: Any) -> list[dict[str, Any]]:
    """지시서 header 의 `visual_sequences` → 정규화된 목록. 없으면 빈 목록.

    ★ 시퀀스가 없는 지시서는 **종전 경로 그대로** 동작해야 한다(마이그레이션 없음, D6).
      빈 목록을 돌려주면 계약 검사도 게이트도 아무것도 하지 않는다.
    """
    if not isinstance(raw, list):
        return []
    return compute_lineage([normalize_sequence(s, i) for i, s in enumerate(raw, 1)])


# ─────────────────────────────────────────────────────────────
# 프롬프트 조립 — 구조화 필드 → 산문 (숫자 규격 없이)
# ─────────────────────────────────────────────────────────────
def camera_prose(world: dict[str, Any], stage: dict[str, Any]) -> str:
    """카메라를 **산문**으로. 숫자·기호가 들어가지 않는 것이 이 함수의 존재 이유다."""
    base = config.CAMERA_BASE_PROSE.get(
        str(stage.get("camera_base") or world.get("camera_base") or ""),
        config.CAMERA_BASE_PROSE[config.DEFAULT_CAMERA_BASE])
    move = config.CAMERA_OPERATION_PROSE.get(str(stage.get("camera_operation") or "HOLD"), "")
    return f"{base}, {move}" if move else base


def world_prose(world: dict[str, Any]) -> str:
    """세계 고정 요소를 한 줄로. 빈 항목은 넣지 않는다(빈 마커 금지)."""
    parts = [world.get("style"), world.get("lighting"), world.get("background")]
    return ", ".join(p for p in parts if p)


def entity_prose(entities: list[dict[str, Any]], refs: list[str]) -> str:
    """이 stage 가 유지해야 할 개체들의 외형 서술. 참조가 없으면 빈 문자열."""
    want = set(refs)
    named = [e for e in entities if e.get("entity_id") in want and e.get("visual_identity")]
    if not named:
        return ""
    return "; ".join(f"{e['entity_id']}: {e['visual_identity']}" for e in named)


_HANGUL = re.compile(r"[가-힣]")
_WORD = re.compile(r"[a-z]+")
_PROSE_STOP = frozenset(
    "a an the of in on at to for and or with without from by into over under between across "
    "through as is are be this that these those its it their his her one two three left right "
    "top bottom front back side same new old small large big".split())


def _english(value: Any) -> str:
    """영어로만 적힌 값. 한글이 섞이면 빈 문자열 — 그림에는 영어만 보낸다."""
    text = str(value or "").strip()
    return "" if (not text or _HANGUL.search(text)) else text


def _phrase(value: Any, *, max_words: int = 12) -> str:
    """이름·구절로 쓸 수 있는 영어 값. 문장(마침표·너무 긴 것)은 버린다 — 프롬프트 안에서
    "the The two models as a comparative pair. is the part" 같은 파편이 된다(2026-09-18 실측)."""
    text = _english(value).rstrip(".").strip()
    if not text or len(text.split()) > max_words:
        return ""
    return text


def mechanism_prose(cut: dict[str, Any], *, referenced: bool = False) -> str:
    """도해 구조(mechanism) → 이미지 프롬프트에 붙일 한 문장 (2026-09-18, 연구 T1-a).

    ★ 왜 생겼나: `mechanism` 은 subject/components/transformation 을 필드로 받아 게이트가
      검사했지만 **그림에는 한 번도 닿지 않았다**(연구_기전시퀀스_교육력 §3-1). 구조가 완벽해도
      화면은 visual_prompt 의 배경 사진이었다. `entity_prose`·`world_prose` 와 같은 처지였다 —
      만들어 놓고 배선하지 않은 것.

    ★ 영어 필드만 싣는다. 한글이 섞인 필드는 뺀다 — 생성 모델이 한글을 글자로 구울 수 있고,
      그림은 언어판이 공유한다. 지시서 프롬프트가 이제 이 필드들을 영어로 요구한다
      (사람이 읽는 것은 `mechanism_ko`).

    ★★ **전·후를 한 프롬프트에 나열하지 않는다**(2026-09-18 유료 실측 4장 전부). 첫 판은
      "before: …; after: …" 를 붙였고 Gemini 는 그것을 **세로 3단 스토리보드**로 그렸다 —
      한 화면에 두 뇌가 세 줄로 반복됐다. 한 장은 한 상태다. 무엇이 보여야 하고 무엇이
      설명 대상인지만 말하고, 상태는 visual_prompt(그 컷의 장면)가 말한다. 그리고 "한 장면"
      을 명시한다 — 구성요소를 나열하면 모델이 칸을 나누고 싶어한다.

    ★ referenced=True(참조 그림에 이어 그리는 컷)에서는 **변화와 강조만** 말한다. 전·후를 다
      말하면 "이것만 바꿔라"와 싸운다(providers/image.py 의 참조 프롬프트 규칙 그대로).
    """
    spec = cut.get("mechanism")
    if not isinstance(spec, dict):
        return ""
    comps = [c for c in (_phrase(x) for x in (spec.get("components") or [])) if c]
    focus = _phrase(spec.get("highlighted_element"))
    if referenced:
        change = _english(spec.get("transformation")).rstrip(".").strip()
        parts: list[str] = []
        if change:
            parts.append(f"The change to show: {change}")
        if focus:
            parts.append(f"keep the attention on {focus}")
        return ". ".join(parts) if parts else ""
    if len(comps) < 2:
        return ""
    prose = (f"One single scene (no panels, no grid, no storyboard) showing "
             f"{', '.join(comps[:-1])} and {comps[-1]} all visible together")
    if focus:
        prose += f"; {focus} is the part being explained"
    return prose


def mechanism_component_hits(cut: dict[str, Any]) -> tuple[int, int]:
    """(프롬프트에 등장하는 영어 구성요소 수, 영어 구성요소 수). 연구 T1-b 게이트의 재료.

    낱말 겹침으로 잰다(4자 이상, 복수형·-ing 을 거칠게 벗긴다). 정밀하지 않지만 실측
    117컷에서 0겹침 4건이 전부 진짜였고 오탐이 없었다(config.PHOTO_MECHANISM_PROMPT_MIN_HITS).
    """
    spec = cut.get("mechanism")
    if not isinstance(spec, dict):
        return 0, 0
    comps = [c for c in (_english(x) for x in (spec.get("components") or [])) if c]
    prompt_words = _stems(str(cut.get("visual_prompt") or ""))
    hits = sum(1 for c in comps if _stems(c) & prompt_words)
    return hits, len(comps)


def _stems(text: str) -> set[str]:
    out: set[str] = set()
    for tok in _WORD.findall(text.lower()):
        if len(tok) < 4 or tok in _PROSE_STOP:
            continue
        for suf in ("ing", "es", "ed", "s"):
            if tok.endswith(suf) and len(tok) - len(suf) >= 4:
                tok = tok[: -len(suf)]
                break
        out.add(tok)
    return out


def stage_changes_state(stage: dict[str, Any] | None) -> bool:
    """이 stage 가 **의미 변화**(모양이 바뀜·커짐·줄어듦·갈라짐·합쳐짐·사라짐)를 선언하는가.

    I2V 가 못 하는 종류의 변화다 — 운동(MOVE·ROTATE·IMPACT)은 여기 들지 않는다.
    렌더가 전·후 분할 스틸로 갈지 정할 때 쓴다(config.MECHANISM_SPLIT_OPERATIONS).
    """
    for m in ((stage or {}).get("mutations") or []):
        if str(m.get("operation") or "") in config.MECHANISM_SPLIT_OPERATIONS:
            return True
    return False


def stage_index(sequences: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """stage_id → stage. 연속성 참조 검사와 렌더가 같은 색인을 쓴다."""
    out: dict[str, dict[str, Any]] = {}
    for seq in sequences:
        for st in seq.get("stages") or []:
            out[str(st.get("stage_id"))] = st
    return out


def cut_to_stage(sequences: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """컷 번호 → 그 컷을 담당하는 stage. 렌더가 컷 단위로 도는 구조를 유지한 채
    시퀀스 정보를 찾을 수 있게 한다(Cut 을 없애지 않는다 — 작업지시서 Paper §2.1)."""
    out: dict[int, dict[str, Any]] = {}
    for seq in sequences:
        for st in seq.get("stages") or []:
            for c in st.get("cut_refs") or []:
                out.setdefault(int(c), {**st, "_sequence": seq})
    return out
