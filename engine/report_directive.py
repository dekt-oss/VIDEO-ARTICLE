"""PF2: 리포트 대본 → 컷 제작 지시서 생성 (논문 engine/directive.py 미러).

입력: report_drafts 행(script_md + fact_sheet + scenes) + version_type.
출력: 지시서 JSON(header + cuts). 렌더 엔진의 입력이자 사람이 승인하는 산출물.

★ 정규화·enum 강제·근거 보존은 논문 directive.normalize_directive 를 그대로 재사용(순수·무관).
★ 컴플라이언스: 지시서 나레이션도 report_scriptgen 의 금지/필수 규칙을 따른다(투자권유·수익률·단정 금지,
  증권사 귀속, 면책은 나레이션 낭독 금지 — 하단 자막으로 렌더).

실행: python -m engine.report_directive                          # 큐 1회 폴링
     python -m engine.report_directive <report_id> [version]   # 즉시 생성
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import config, report_db
from . import equity_visual
from . import equity_contract
from . import report_reasoning
from . import directive as dv
from .llm import call_json
from . import script_revision
from .util import log

# 논문 지시서 프롬프트의 서사/효과/토큰 규칙을 리포트용 + 컴플라이언스로 재구성.
REPORT_DIRECTIVE_SYSTEM = f"""너는 증권사 리포트 대중화 숏폼 영상의 연출가 겸 스토리 작가다. 입력은
"대본(script_md)" + "Fact Sheet" + 기존 "장면들(scenes 초안)"이다. 이것들만으로 지정된 버전 규격에 맞는
"컷별 제작 지시서"를 JSON 으로만 출력한다.

★ 절대 규칙(사실·컴플라이언스):
- Fact Sheet/대본에 근거 없는 내용은 절대 넣지 마라. 각 컷은 source_facts 로 근거 키를 명시하라
  (예: "numbers[0]", "basis[1]", "opinion"). 근거가 없으면 그 컷을 만들지 마라.
- [컴플라이언스 금지] 매수/매도/보유 등 투자행동 권유, 미실현 수익률·상승여력% 광고, 단정적 미래 예측,
  리포트를 '내 분석'인 척 서술(반드시 "OO증권에 따르면"으로 귀속) — 하나라도 어기면 실패.
- [컴플라이언스 필수] 목표가·의견은 사실 인용만, 출처(증권사) 최소 1회, 리스크 한 줄 포함.
- ★ 면책 문구를 나레이션으로 낭독하는 전용 컷을 만들지 마라(면책은 영상 하단 고정 자막으로 렌더된다).
- effects/transition/scene_kind 는 아래 [허용 토큰] 안에서만. 자유 텍스트 금지.
- 나레이션은 KO/EN 둘 다. 한 컷은 {config.CUT_MIN_SEC}~{config.CUT_MAX_SEC}초. 전체 약 {config.TARGET_TOTAL_SEC}초(유연).
- 화면 글자는 자막/텍스트 오버레이(effects)로만. visual_prompt 엔 "no on-screen text" 유지.

★ 연출·서사 규칙:
1) 로그라인 먼저 — 모든 컷이 한 문장 핵심 주장을 향하게. 곁가지 사실 금지.
2) 컷은 "의미 단위"로(한 컷=한 메시지): [후크]→[종목/테마]→[핵심 팩트·수치]→[증권사 논리(귀속)]→[리스크]→[마무리].
   그 역할을 render_notes 앞에 대괄호로 표기.
3) 앞뒤 문맥 연결(그래서/하지만/즉…). 순서대로 읽으면 하나의 매끄러운 이야기.
4) 데이터 절제 — 한 컷에 소리 내 읽는 숫자는 대표값 1개. 세부 수치는 시각(text_overlay/그래프)이 담당.
5) EN 은 KO 의 자연스러운 번역(직역 금지).
6) 출처 구체화 — "OO증권에 따르면"처럼 증권사를 구체 지칭(source 에 있는 것만).

[허용 토큰] effects: {dv._EFFECTS_HELP}
  transition: cut|crossfade
  scene_kind: {dv._SCENE_KINDS_HELP}

[출력 스키마] JSON only. 설명·마크다운·코드펜스 금지.
{{
  "header": {{
    "aspect_ratio": "{config.ASPECT_RATIO}",
    "global_style": "<전 컷 일관 화풍/톤 앵커 한 줄>",
    "hook_ko": "<상단 고정 부제 — 1컷 나레이션과 **다른 문장**. 제목처럼 짧게(20자 내외)>",
    "hook_en": "<top subtitle — must differ from cut 1 narration. short, title-like>",
    "cta_ko": "<저장/댓글 유도>", "cta_en": "<save/comment CTA>",
    "bgm": {{ "mood": "<차분|긴장|경쾌 등>", "track_ref": "" }},
    "total_estimated_sec": <int>
  }},
  "cuts": [
    {{
      "cut_no": <int>, "scene_kind": "<허용 씬종류 중 1>",
      "narration_ko": "<한국어>", "narration_en": "<English>",
      "estimated_sec": <int, {config.CUT_MIN_SEC}~{config.CUT_MAX_SEC}>,
      "visual_prompt": "<이미지/클립 생성용 영문 프롬프트>",
      "style_anchor_ref": "<일관성 참조 or 빈값>",
      "effects": ["<허용 토큰만>"], "transition": "cut|crossfade",
      "bgm_cue": "<or 빈값>", "source_facts": ["<Fact Sheet 키>"],
      "render_notes": "<or 빈값>", "motion_source": "still|video"
    }}
  ]
}}"""

# ── 실사형 photo 추가 계약 (2026-08-19) ──
# ★ 왜 이 블록이 필요한가: 만화식은 overlay_plan 을 컷의 5%(12/235)만 채웠고 설명판형은
#   94%(33/35)를 채웠다. 그 차이가 곧 "나레이션은 22%인데 화면 막대는 -3%" 같은 사고의
#   원인이었다 — 채워야 할 곳을 안 채우니 숫자가 이미지 프롬프트로 흘러갔다.
#   실사형은 설명판형의 그 습관만 물려받는다(보드는 물려받지 않는다).
PHOTO_CONTRACT = f"""

[추가 계약 — 실사형 photo · 벤치마크 문법]
이 영상은 건축·구조 해설 쇼츠(신비한 건축사전·이런거지 류)의 화면 문법으로 만든다.
■ 컷 호흡: 한 컷 = 나레이션 한 문장(2~4초). **문장이 끝나는 지점에서 화면 전환**.
  그래서 컷 수는 만화식(6~8)보다 많다 — 40~50초 영상이면 **10~14컷**을 목표로 하라.
  estimated_sec 하한({config.CUT_MIN_SEC}초)은 계획값일 뿐이다. 실제 컷 길이는 나레이션
  실측으로 정해지므로, 문장을 짧게 쓰면 컷이 짧아진다. 문장을 길게 쓰고 컷을 늘리지 마라.
■ 화면의 글자·숫자는 **전부 overlay_plan** 이 담당한다. 이미지에 글자를 굽지 않는다.
  숫자를 화면에 내보내려면 그 컷의 overlay_plan 에 number_punch 카드로 넣어라. 벤치 채널이
  화면 위에 붉은 계측선·치수를 "얹어" 보여주듯, 우리는 리포트 수치를 카드로 얹는다.
■ 수치가 나오는 컷은 **반드시** 그 수치의 출처를 같은 화면에 둔다(source_card).
  본문 나레이션에서 증권사를 말했더라도 화면 카드는 별도로 필요하다.
■ 오버레이는 한 컷에 최대 {config.OVERLAY_MAX_PER_CUT}개. 많으면 읽히지 않는다.
■ 컷마다 visual_role 을 선언한다(MECHANISM 3D 도해 / REALITY 실사). 12컷 기준 도해 5~7 · 실사 3~5.
  ★ [증권 리포트 라인의 MECHANISM 소재] 리포트는 다리·궁궐처럼 눈에 보이는 물건이 아니라서
    무엇을 도해할지 정하는 것이 이 버전의 성패다. 아래에서 고른다:
      · 공급망 흐름 — 원료에서 최종 수요처까지 단계를 잇는 도해(예: 광산 → 양극재 → 셀 → ESS → 데이터센터).
        그 편의 주인공 기업이 어느 칸에 있는지 강조한다.
      · 제품 단면 — 그 회사가 만드는 물건을 잘라 구조를 보여준다(셀의 층 구조, 모듈 결합 방식).
      · 수요 전이 경로 — 수요가 A 에서 B 로 옮겨가는 과정(전기차용 → ESS용).
      · 전후 비교 — 리포트가 말하는 변화의 전과 후를 나란히.
      · 원가·마진 구조 — 무엇이 얼마를 차지하는지 블록으로.
    ★ 도해에 **숫자를 그리지 마라.** 숫자는 overlay_plan 이 얹는다. 도해는 구조와 방향만 보여준다.
  ★ [REALITY 소재] 공장·생산라인·물류·항만·제품 실물. 훅과 마무리, 그리고 도해가 추상적으로
    흐를 때 현실로 끌어오는 자리.
■ visual_prompt 에는 **무엇을 보여줄지만** 쓴다 — 화풍 형용사(photorealistic, 3D render 등)는
  코드가 역할에 따라 붙이므로 쓰지 마라. 차트·그래프·대시보드·UI·인포그래픽·퍼센트·라벨 금지.
  얼굴 클로즈업·정장 인물·악수 금지.
■ 움직임: 이 버전은 "움직이는 화면"이 정체성이다. **영상 컷(motion_source=video)을 6~8개**
  배정하라(기본 지침의 "0개여도 좋다"는 실사형에 적용되지 않는다).
  ★ 그리고 영상 컷을 **서로 붙여서** 배치하라. 렌더가 앞 영상 컷의 마지막 화면에서 다음 컷을
    이어 만들기 때문에, 영상 컷이 연달아 있어야 카메라가 끊기지 않고 흐른다.
    영상-스틸-영상처럼 띄엄띄엄 두면 그 연결이 끊긴다.
■ 훅: 첫 문장은 반전 평서문으로 시작한다 — "…인 줄 알았는데 사실은 …였습니다" /
  "…가 …를 일부러 …한 이유". 첫 3초에 상식을 뒤집는 한 문장 + 숫자 하나.
■ 서사: 문제 제기 → "왜?" → 예측을 깨는 원인 → 해결의 메커니즘 → 그래서 무엇(확인 포인트).
  마술처럼 시청자가 한쪽을 보게 만들고 다른 쪽에서 답이 나오게 하라(예측 오류).

[추가 필드] 위 기본 스키마의 각 컷에 다음을 더해서 출력하라.
  "overlay_plan": [ {{ "type": "source_card|evidence_card|number_punch|caveat_tag",
                       "text": "<화면 카드 문구>", "start_sec": <초>, "duration_sec": <초> }} ]
"""


# ── 논증 단위 계약(설명엔진 v2 §7) — 컷이 어느 논증을 옮기는지 표시하게 한다 ──
REASONING_CUT_CONTRACT = """[논증 단위 — 아래 구간이 주어졌다]
이 단위들은 대본보다 **먼저** 만들어진 논증 경로다. 컷을 나눌 때:
- carries_thesis=true 인 단위는 **최소 한 컷**이 화면으로 옮겨야 한다.
- 단위에 없는 인과를 visual_prompt 나 나레이션에 추가하지 마라.
- 단위의 breaks_if 는 리스크·확인 포인트 컷의 재료다("무엇이 깨지면 이 이야기가 틀리는가").

[추가 필드] 위 기본 스키마의 **각 컷에** 다음을 더해서 출력하라:
  "reasoning_id": "<이 컷이 화면으로 옮기는 논증 단위 id (예: R01). 아래 목록에 있는 것만.
                    논증을 옮기지 않는 컷(훅·마무리 등)은 빈 문자열>"
  "reasoning_step": <이 컷이 옮기는 **단계 번호**(위 목록의 step 값). 논증을 옮기지 않으면 0>
  ★ 목록에 없는 id 나 없는 step 을 지어내지 마라 — 코드가 원장과 대조해 버린다.
  ★ step 이 중요한 이유: 화면은 이 단계들을 **같은 세계에서 이어지는 장면**으로 만든다.
    어느 컷이 어느 단계인지 모르면 그 연결을 코드가 지어내야 하고, 그러면 논증은
    5단계인데 화면은 3단계인 채로 어긋난 것을 아무도 못 본다.

★★ [단계 배치 규칙 — 어기면 화면이 끊긴다]
  한 논증을 화면에 옮기기로 했으면 그 단계들을 **1부터 순서대로, 건너뛰지 말고,
  연속된 컷으로** 이어라. 2단계를 4단계보다 **뒤에** 두지 마라.
  ★ 왜: 각 단계는 앞 단계의 **그림에서 이어서** 만들어진다. 4단계를 먼저 그리려 하면
    이어받을 3단계 그림이 아직 없어서 그 컷은 **전혀 다른 새 화면**이 된다.
    실측에서 그렇게 나왔다 — 연속성이 한 번도 안 생겼다.
  ★ 논증 하나를 **깊게** 밟는 편이 여러 논증을 한 단계씩 훑는 것보다 낫다.
    carries_thesis=true 인 논증을 골라 그 단계들을 끝까지 따라가라."""


def _filter_reasoning_ids(directive: dict, draft_row: dict) -> dict:
    """컷의 reasoning_id 를 원장과 대조해 **없는 것은 버린다**(dangling 금지).

    ★ 씬(report_scriptgen.normalize_script)과 같은 규칙을 지시서에서도 한 번 더 적용한다.
      지시서는 대본과 별도의 LLM 호출이라, 대본에서 걸러도 여기서 다시 생길 수 있다.
    """
    known = set(report_reasoning.reasoning_ids(draft_row.get("financial_reasoning")))
    dropped = 0
    for cut in directive.get("cuts") or []:
        rid = str(cut.get("reasoning_id") or "")
        if rid and rid not in known:
            cut["reasoning_id"] = ""
            dropped += 1
    if dropped:
        log.warning("지시서 컷의 존재하지 않는 reasoning_id %d개를 버렸다", dropped)
    return directive


def scene_block(scenes: list[dict[str, Any]], fresh: bool) -> str:
    """⑤ 프롬프트의 "기존 장면들" 구간. 대본과 어긋난 씬은 **싣지 않는다**.

    ★ 실으면 운영자가 ④ 에서 지운 문장이 지시서에 되살아난다(PR #94 후속 리뷰 P1-1).
      비울 때는 이유를 적어 준다 — 빈 자리만 두면 모델이 옛 문장을 상상해 채운다.
    """
    if fresh:
        head = "기존 장면들(scenes — 나레이션 초안. 흐름·근거를 계승하되 위 규칙에 맞게 다듬어라):"
        return head + chr(10) + json.dumps(scenes, ensure_ascii=False, indent=2)
    return ("기존 장면들: **없다.** 대본이 씬 생성 이후 편집됐다. 위 대본(script_md)이 유일한 "
            "정본이니 그것만 보고 컷을 나눠라. 옛 문장을 상상해 되살리지 마라.")


def report_directive_user_prompt(draft_row: dict[str, Any], version_type: str) -> str:
    """지시서 생성 입력: 버전 지시 + 대본 + Fact Sheet + 기존 장면들(report_drafts.scenes)."""
    fact_sheet = draft_row.get("fact_sheet") or {}
    script_md = draft_row.get("script_md") or ""
    # ★ 대본 정본은 script_md 다(PR #94 후속 리뷰 P1-1). 씬은 **지금 대본과 일치할 때만**
    #   싣는다. ④ 화면은 script_md 만 저장하므로, 운영자가 문장을 고치거나 지운 뒤 재검사를
    #   건너뛰면 씬은 옛 원고다 — 그대로 실으면 지운 문장이 지시서에 되살아난다.
    scenes = draft_row.get("scenes") or []
    scenes_fresh = script_revision.scenes_match_script(scenes, script_md)
    guidance = dv.VERSION_GUIDANCE.get(version_type, dv.VERSION_GUIDANCE[config.DEFAULT_VERSION])
    if version_type == "photo":
        guidance += PHOTO_CONTRACT
    # ★ 논증 단위(설명엔진 v2 §7)를 지시서 단계에도 싣는다. 대본에만 주고 여기서 빼면
    #   컷이 어느 논증을 옮기는지 알 수 없어 reasoning_id 가 빈 채로 나온다 — 그러면 승인
    #   화면이 "설명이 빠진 논증"을 짚지 못한다.
    units = report_reasoning.units_block(draft_row.get("financial_reasoning"))
    blocks = [
        guidance,
        f"대본(script_md):\n{script_md}",
        f"Fact Sheet:\n{json.dumps(fact_sheet, ensure_ascii=False, indent=2)}",
    ]
    if units:
        blocks.append(REASONING_CUT_CONTRACT + "\n" + units)
    blocks.append(scene_block(scenes, scenes_fresh))
    return "\n\n".join(blocks)

def generate(draft_row: dict[str, Any], version_type: str,
             report: dict[str, Any] | None = None) -> dict[str, Any]:
    """리포트 대본 행 + 버전 → 정규화된 지시서 dict(논문 normalize 재사용).

    ★ 2026-08-28: 설명판형(explainer)을 폐기하면서 **게이트 되먹임 재생성도 함께 사라졌다.**
      그 장치(계약 위반 사유를 프롬프트에 되먹여 1회 재생성)는 아이디어로서는 옳았고, 지금
      계약 위반이 새는 곳은 실사형이다 — 실사형 게이트를 만들 때 같은 모양으로 되살린다.
      되살릴 때 참고: 커밋 이력의 attach_explainer / gate_feedback_prompt.
    ★★ 2026-09-14 되살렸다(운영자: "증권 리포트에도 바로 다 적용돼 있는 거지"). 논문 라인
      (directive.generate)과 같은 모양 — **실사형 화면 계약(photo_gate) 차단이 있을 때만** 처방을
      되먹여 1회 재생성하고, 결과를 다시 검사해 차단이 적은 쪽을 남긴다.
      ★ 시퀀스·EQ-V 차단은 되먹이지 않는다 — 리포트 시퀀스는 LLM 이 아니라 코드
        (equity_visual)가 만든다. 모델에게 자기가 안 쓴 것을 고치라고 하면 구조만 갈아엎는다.
    """
    user = report_directive_user_prompt(draft_row, version_type)
    first = _generate_once(draft_row, version_type, user)
    blocks = list((first["header"].get("photo_gate") or {}).get("block_reasons") or [])
    if not (config.DIRECTIVE_CONTRACT_RETRY and version_type == "photo" and blocks):
        return first
    from . import photo_contract
    log.warning("리포트 실사형 계약 위반 → 사유를 되먹여 1회 재생성: %s", ", ".join(blocks))
    retry = _generate_once(
        draft_row, version_type,
        user + photo_contract.feedback_prompt(
            blocks, (first["header"].get("photo_gate") or {}).get("warnings")))
    retry_blocks = list((retry["header"].get("photo_gate") or {}).get("block_reasons") or [])
    record = {"attempted": True, "first_block_reasons": blocks,
              "retry_block_reasons": retry_blocks,
              "new_violations": sorted({r.split(":", 1)[0] for r in retry_blocks}
                                       - {r.split(":", 1)[0] for r in blocks})}
    # 덜 나쁜 쪽 — 전체 차단 사유 수로 비교한다(재생성이 다른 계약을 깨뜨렸을 수 있다).
    keep = retry if (len(retry["header"].get("block_reasons") or [])
                     < len(first["header"].get("block_reasons") or [])) else first
    keep["header"]["contract_retry"] = record
    return keep


def _generate_once(draft_row: dict[str, Any], version_type: str, user: str) -> dict[str, Any]:
    """LLM 1회 → 시퀀스 컴파일 → 공용 정규화 → EQ-V 계약. generate 가 재생성에 한 번 더 부른다."""
    obj = call_json(
        model=config.MODEL_DIRECTIVE,
        system=REPORT_DIRECTIVE_SYSTEM,
        user=user,
        max_tokens=config.LLM_SCRIPT_MAX_TOKENS,
    )
    # ★★ Equity Visual Planner (v3 Phase 5) — 논증을 **공용 시각 시퀀스로 컴파일**해서
    #   정규화 **앞에** 꽂는다. 정규화는 시퀀스가 있으면 라우팅·resolved_visual_plan·
    #   stage_mutations·공용 게이트를 이미 전부 돌리므로, 여기 한 줄로 금융 라인이 그
    #   기계를 통째로 물려받는다 — 금융 파이프라인을 새로 만들지 않는다(equity §1).
    #   LLM 호출은 0이다: 논증은 이미 `report_reasoning` 이 만들었고 다시 추출하지 않는다(§4).
    seqs = equity_visual.build_for_directive(
        obj.get("cuts"), draft_row.get("financial_reasoning"))
    obj["visual_sequences"] = seqs
    # ★ 컷 상한을 명시적으로 CUT_MAX_SEC(8) 로 고정한다. 논문 라인은 근거밀도 개정으로
    #   종류별 완화(10/12초)를 받았지만, 이 프롬프트의 계약은 여전히 3~8초다(§2 위 스키마).
    #   빠뜨리면 논문 전용 완화가 범위 밖인 금융 라인으로 새어 들어온다.
    d = dv.normalize_directive(obj, version_type, cut_max_sec=config.CUT_MAX_SEC)
    # ★ 화면 투영에서 드러난 것(단계 역순·화면에 못 나간 단계)을 **기존 경고 키에 합류**
    #   시킨다. 승인 화면과 라우트가 이미 mode_warnings 를 보므로 새 표면을 만들지 않는다.
    #   차단하지 않는 이유: 순서가 어긋나도 렌더는 돌아간다(세계가 덜 이어질 뿐이다).
    #   ★ 정규화가 **진단 필드를 버린다**(공용 스키마에 없는 키라 당연하다). 그래서
    #     `d["header"]["visual_sequences"]` 가 아니라 **정규화에 넣기 전의 `seqs`** 를 본다.
    #     헤더에서 읽으면 coverage 가 없어 경고가 영영 0건이 된다(실측으로 확인).
    # ★ EQ-V 계약(작업지시서 §11). 논문 라인에는 차단 게이트가 26개인데 리포트 라인에는
    #   **하나도 없었다** — 같은 엔진의 두 라인이 비대칭이었다.
    #   ★★ 구조 판정은 차단, 어휘 판정은 경고다: 코드가 만든 데이터의 모양을 보는 검사
    #     (EQ-V1 연결·V4 수치·V6 진행)는 오탐이 없으므로 막고, 리포트 **문장**을 어휘로
    #     읽는 검사(V2·V3·V7)는 경고로 두고 오탐률을 본 뒤 올린다.
    #   ★ `seqs` 를 본다 — 정규화가 진단 필드(reasoning_id·precision_layer)를 버리므로
    #     헤더에서 읽으면 검사가 영영 0건이 된다(위 screen_warnings 와 같은 이유다).
    warns = [*equity_visual.screen_warnings(seqs), *equity_contract.warnings(seqs)]
    if warns:
        d["header"]["mode_warnings"] = sorted(set([*(d["header"].get("mode_warnings") or []),
                                                   *warns]))
        log.warning("Equity 화면 투영 경고: %s", ", ".join(warns))
    blocks = equity_contract.block_reasons(seqs)
    if blocks:
        d["header"]["block_reasons"] = sorted(set([*(d["header"].get("block_reasons") or []),
                                                   *blocks]))
        d["header"]["approval_blocked"] = True
        log.warning("EQ-V 계약 위반(승인 차단): %s", ", ".join(blocks))
    return _filter_reasoning_ids(d, draft_row)


def process_report(report_id: str, version_type: str) -> dict[str, Any]:
    draft = report_db.get_report_draft(report_id)
    if not draft:
        raise ValueError(f"report_draft 없음(먼저 초안 생성): {report_id}")
    # 리포트 메타(증권사·제목)는 하단 면책 자막의 출처 표기에 쓴다.
    report = report_db.get_report(report_id) or {}
    directive = generate(draft, version_type, report)
    # 렌더 워커가 하단 면책 자막에 출처를 넣도록 header 에 broker 주입(normalize 가 미허용 키를 버린 뒤).
    directive["header"]["broker"] = report.get("broker") or ""
    row = {
        "report_id": report_id,
        "version_type": directive["version_type"],
        "header": directive["header"],
        "cuts": directive["cuts"],
        "status": "draft",
    }
    dir_id = report_db.insert_report_directive(row)
    flagged = len(dv.ungrounded_cuts(directive))
    log.info("리포트 지시서 생성: report=%s version=%s cuts=%d 근거없음=%d id=%s",
             report_id, version_type, len(directive["cuts"]), flagged, dir_id)
    return directive


def poll_once(limit: int = 5) -> int:
    reqs = report_db.claim_report_directive_requests(limit)
    if not reqs:
        log.info("report_directive_requests: 대기 없음")
        return 0
    for r in reqs:
        try:
            process_report(r["report_id"], r.get("version_type") or config.REPORT_DEFAULT_VERSION)
            report_db.update_report_directive_request(r["id"], "done")
        except Exception as exc:  # noqa: BLE001
            log.exception("리포트 지시서 요청 실패 id=%s: %s", r["id"], exc)
            report_db.update_report_directive_request(r["id"], "error", str(exc))
    return len(reqs)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 2:
            process_report(sys.argv[1], sys.argv[2])
        elif len(sys.argv) > 1:
            process_report(sys.argv[1], config.REPORT_DEFAULT_VERSION)
        else:
            poll_once()
    except Exception as exc:  # noqa: BLE001
        log.exception("report_directive 실패: %s", exc)
        sys.exit(1)
