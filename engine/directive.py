"""P-V0: 대본 → 버전별 컷 제작 지시서 생성 (명세 §4·§5).

입력: drafts 행(script_md + fact_sheet + video_prompts[scenes]) + version_type.
출력: 명세 §4 지시서 JSON(header + cuts). 렌더 엔진의 입력이자 사람이 승인하는 산출물.

★ 환각 방지 불변식 계승: 지시서 내용은 대본+Fact Sheet 근거만. 각 컷 source_facts 로 근거를 남기고,
  근거 없는 컷은 승인 화면에 빨간 표시한다(여기선 정규화만; 표시는 대시보드).
★ 통제 어휘: effects/transition/bgm_cue 는 config enum 만. enum 밖 토큰은 드롭+로그(자유 텍스트 금지).

★ 이중 관리 지점: 이 모듈의 프롬프트·정규화 규칙은 supabase/functions/generate-directive/index.ts 로
  이식돼 있다(generate-draft 와 동일). 한쪽을 고치면 다른 쪽도 동기화한다.

실행: ``python -m engine.directive``                        # directive_requests 큐 1회 폴링
     ``python -m engine.directive <paper_id> <version>``   # 특정 논문·버전 즉시 생성
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from typing import Any

from . import (
    config, content_mode, cost, cut_skeleton, db, directive_audit, evidence_overlay,
    factsheet, paper_evidence, selfcheck, visual_router, visual_sequence,
    visual_sequence_contract)
from . import generation_spec
from . import sequence_tier
from . import temporal_plan as tplan
from . import temporal_context
from . import photo_contract
from .llm import call_json, set_text_purpose
from .providers import video  # 길이 티어(pick_clip_tier) — 예산 캡을 실제 요청 초수로 조인다
from .util import log

# ─────────────────────────────────────────────────────────────
# 프롬프트 (명세 §5-1 공통 골격 + §5-2 버전별 추가지시)
# ─────────────────────────────────────────────────────────────
_EFFECTS_HELP = (
    "ken_burns_zoom_in|ken_burns_zoom_out|pan_left|pan_right|highlight|"
    "text_overlay:<문구>|particle:none|particle:soft"
)
_SCENE_KINDS_HELP = "|".join(config.SCENE_KINDS)  # ③ 시각 다양성 래더(규격 v2 §2.2)
# 훅·리텐션 개정 v2 — 통제 어휘 표시용.
_HOOK_TYPES_HELP = "|".join(config.HOOK_TYPES)
_ANGLES_HELP = "|".join(config.HOOK_ANGLES)
_CTA_HELP = "|".join(config.CTA_TYPES)
_BANNED_HOOK_HELP = " / ".join(config.HOOK_BANNED_PHRASES)
# 근거밀도·가변길이 개정 — 통제 어휘 표시용(수정명세 §5·§6·§10).
_CONTENT_MODES_HELP = "|".join(config.CONTENT_MODES)
_EVIDENCE_ROLES_HELP = "|".join(config.EVIDENCE_ROLES)
_BEAT_KINDS_HELP = "|".join(config.BEAT_KINDS)
_SEQUENCE_ROLES_HELP = "|".join(config.SEQUENCE_ROLES)
_VISUAL_OPERATIONS_HELP = "|".join(config.VISUAL_OPERATIONS)
_CAMERA_OPERATIONS_HELP = "|".join(config.CAMERA_OPERATIONS)
_CONTINUITY_MODES_HELP = "|".join(config.CONTINUITY_MODES)
_CAMERA_BASES_HELP = "|".join(config.CAMERA_BASES)
_MUTATION_OPERATIONS_HELP = "|".join(config.MUTATION_OPERATIONS)
_REPRESENTATION_MODES_HELP = "|".join(config.REPRESENTATION_MODES)
_MOTION_VALUES_HELP = "|".join(config.MOTION_VALUES)
_MUTATIONS_HELP = "|".join(config.MUTATION_OPERATIONS)
_CAMERA_OPS_HELP = "|".join(config.CAMERA_OPERATIONS)
_ASSET_STRATEGIES_HELP = "|".join(config.ASSET_STRATEGIES)
_OVERLAY_TYPES_HELP = "|".join(config.OVERLAY_TEXT_TYPES)
_POINTER_ZONES_HELP = " / ".join(config.OVERLAY_POINTER_ZONES)
_TONE_GRADES_HELP = "|".join((config.DEFAULT_TONE_GRADE, *config.TONE_GRADES))

DIRECTIVE_SYSTEM_BASE = f"""너는 논문 대중화 숏폼 영상의 연출가 겸 스토리 작가다. 입력은
"대본(script_md)" + "Fact Sheet" + 기존 "장면들(scenes 초안)"이다. 이것들만으로 지정된 버전 규격에 맞는
"컷별 제작 지시서"를 JSON 으로만 출력한다.

★ 절대 규칙(사실):
- Fact Sheet/대본에 근거 없는 내용은 절대 넣지 마라. 각 컷은 source_facts 로 근거 키를 명시하라
  (예: "what_found[0]", "numbers[1]"). 근거가 없으면 그 컷을 만들지 마라.
- effects/transition/bgm_cue 는 아래 [허용 토큰] 안에서만 사용하라. 자유 텍스트 금지.
- 나레이션은 KO/EN 둘 다 작성한다. 한 컷은 {config.CUT_MIN_SEC}~{config.PAPER_CUT_MAX_SEC}초
  (scene_kind=data_viz 는 {config.DATA_VIZ_CUT_MAX_SEC}초까지, motion_source=video 는 {config.VIDEO_CUT_MAX_SEC}초까지).
- ★비용·연출 효율: 컷을 너무 잘게 쪼개지 마라. 한 메시지가 유지되면 8초를 넘겨도 컷을 쪼개지 않는다 —
  컷마다 이미지 1장이 필요하므로 컷이 적을수록 제작비가 낮다. 나레이션 문장이 끝났다는 이유만으로 새
  이미지를 만들지 마라. 다만 {config.CUT_STATE_CHANGE_MIN_SEC}초를 넘는 컷은 반드시 state_change 를 채워라
  (줌·하이라이트·그래프 변화·오버레이 교체). 정지 이미지 10초 홀드는 금지다.
- ★전체 길이를 먼저 고정하지 마라. content_mode 가 길이를 정한다:
  flash 25~35초 / standard 36~50초 / deep 51~65초 / extended 66~80초.
  header.content_mode 범위 안에서 **가장 짧은** 길이를 선택하고, 그 이유를 duration_reason 에 한 문장으로 적어라.
  단순히 60초를 채우기 위한 일상 예시·반복·CTA 를 추가하지 마라. 80초는 절대 넘기지 않는다.
- 화면 안에 읽히는 글자는 자막/텍스트 오버레이(effects)로만. visual_prompt 에는 "no on-screen text" 를 유지한다.
- 각 컷은 scene_kind 를 [허용 씬종류] 중 하나로 지정한다. 같은 scene_kind 를 3컷 연속 쓰지 마라(최대 2연속).
  10초마다 최소 1회는 "고효율 씬"(motion_graphic/kinetic_typography/data_viz)을 넣어라(켄번스 반복만으로 때우지 말 것).
  broll_stock·comic_panel 은 반드시 나레이션 내용과 의미가 연결돼야 한다(무작위 스톡 금지).
- 훅/CTA 는 언어별로 각각 관용적으로 재작성한다(직역 금지 — 트랜스크리에이션). header 의 hook_ko/hook_en·cta_ko/cta_en 을 독립 생성하라.

★ 연출·서사 규칙(품질 — 이게 이 영상의 완성도를 좌우한다):
1) 로그라인 먼저: 시작 전, 이 영상이 전하려는 "한 문장 핵심 주장(logline)"을 스스로 정하라. 모든 컷은 그 로그라인을
   향해야 하며, 로그라인과 무관한 곁가지 사실은 넣지 마라(주제 이탈 금지).
2) 컷 분할은 "시간"이 아니라 "의미 단위"로: 한 컷 = 정확히 하나의 메시지. 각 컷은 evidence_role 로 자기가 맡은
   근거 역할을 밝힌다: [{_EVIDENCE_ROLES_HELP}]. 같은 역할을 render_notes 앞부분에 대괄호로도 표기하라(예 "[근거] ...").
   ★각 컷은 claim_ids 로 자기가 지불하는 주장을 명시한다(원장에 있는 id 만). 연결어·질문·CTA 컷만 예외다.
3) 앞뒤 문맥 연결: 각 컷 나레이션은 이전 컷의 마지막을 자연스럽게 이어받아라(그래서/하지만/그런데/즉/결국 등 연결어 활용).
   컷들을 순서대로 이어 읽으면 하나의 매끄러운 이야기가 되어야 한다. 마지막 컷은 반드시 후크에서 던진 질문에 답한다.
4) 근거·숫자·방법·한계 규칙:
{config.EVIDENCE_RULES_SHARED}
   세부 수치는 시각(effects text_overlay/그래프)이 담당하되 text_overlay 는 한 컷에 최대 1~2개.
5) EN 나레이션은 KO 의 자연스러운 번역(직역 금지, 같은 뜻·같은 흐름).
6) 출처 구체화: 나레이션에서 "한 연구/어떤 연구"처럼 추상적으로 말하지 말고 Fact Sheet의 source로 구체 지칭.
   ★우선순위: 기관 > 저자명 > 게재처. 기관이 없으면 저자명으로("제인 도 연구진이") 지칭하고, "arXiv에 발표된
   연구"처럼 게재처만으로 밋밋하게 끝내지 마라(저자명이 있으면 사람 이름을 넣어라). 저자·기관 다 없을 때만
   게재처/분야로. ★source에 있는 것만 — 없는 기관·저자는 지어내지 마라. 추상적 나레이션은 source로 구체화(근거 유지).

★ 훅·리텐션 규칙(v2 — 성과의 핵심. 반드시 지켜라):
【P1】 첫 컷(0~1.5초) = "증거 선공개" (예고 금지):
  - 컷1은 논문에서 확인된 "가장 강한 사실"을 먼저 제시하라: 충격 수치 / 결과 / 반전 / 전후 비교 중 하나.
  - 예고·서론형 문구 전면 금지(훅에 절대 쓰지 마라): {_BANNED_HOOK_HELP}.
  - 정답/회사명/핵심어 공개는 필요시 5~15초로 지연해 미스터리를 유지해도 좋다.
  - header.hook_type 을 [{_HOOK_TYPES_HELP}] 중 하나로: H1 충격수치형 / H2 상식반전형 / H3 인과미스터리 / H4 개인영향형.
【P2】 앵글 리프레이밍 — 이 논문의 "가장 강한 각도 1개"만 골라 header.hook_reframe_angle 로:
  [{_ANGLES_HELP}]. 추상 주제(우주·의식·철학)도 scientific_wonder 로 착지 가능(억지로 돈·불안으로 비틀지 말 것).
  앵글은 사실 왜곡이 아닌 '각도' 변경 — 과장·허위 금지.
【P3】 훅↔본문 정합 + 근거강도 게이트(출력 전 필수 자기검증):
  - 컷1 훅이 약속한 것을 본문 컷이 실제로 지불(payoff)하는지 확인해 header.hook_promise_check 에 기록:
    {{pass, promise(훅이 약속한 것), payoff_cut_no(지불하는 컷번호 배열), reason}}. 낚시(불일치) 금지.
  - 대담·단정형 훅(H1/H2 강주장)은 evidence_strength=high AND generalization_risk=low 일 때만 허용.
    header.science_reliability 에 {{claim_type, evidence_strength, generalization_risk, required_caveat}} 를 기록하라.
    (claim_type: measured_result 실측 / author_interpretation 저자해석 / model_projection 모델추정 / speculation 추측)
【P5】 마무리 = 결론 우선, CTA 는 5택1(강제 아님). header.cta_type 을 [{_CTA_HELP}] 중 하나로:
  우선순위 ①영상 결론 ②첫 장면으로 잇는 의미 루프(loop_match=true) ③다음 편 연결 ④구독요청.
  "충격이었다면 좋아요·구독" 같은 상투적 강제 금지. 마지막 문장이 컷1 질문으로 되돌아가면 header.loop_match=true.
■ 리텐션 골격은 content_mode 마다 다르다 — 아래 [모드 골격]에 주어진 것을 따르라(없으면
  증거선공개(0~1.5s) → 의미/질문(~4s) → 최소배경 → 작동원리 → 페이오프(마지막 15~25%) → 루프).
  ★{config.RETENTION_MAX_NO_NOVELTY_SEC}초마다 새 Claim·새 비교·새 시각 상태 중 하나가 등장해야 한다.
  그 "새 정보"가 무엇인지 컷의 novelty_event 에 한 구절로 적어라.

[허용 토큰] effects: {_EFFECTS_HELP}
  transition: cut|crossfade
  scene_kind: {_SCENE_KINDS_HELP}
  hook_type: {_HOOK_TYPES_HELP}   hook_reframe_angle: {_ANGLES_HELP}   cta_type: {_CTA_HELP}

[출력 스키마] JSON only. 설명·마크다운·코드펜스 금지.
{{
  "header": {{
    "aspect_ratio": "{config.ASPECT_RATIO}",
    "global_style": "<전 컷 일관성 기준 — 화풍/톤 앵커 한 줄(영문 키워드 포함 가능)>",
    "hook_ko": "<한국어 훅 — 관용적 재작성>", "hook_en": "<English hook — idiomatic>",
    "cta_ko": "<저장/댓글 유도>",           "cta_en": "<save/comment CTA>",
    "bgm": {{ "mood": "<차분|긴장|경쾌 등>", "track_ref": "" }},
    "total_estimated_sec": <int>,
    "hook_type": "<{_HOOK_TYPES_HELP} 중 1>",
    "hook_reframe_angle": "<{_ANGLES_HELP} 중 1>",
    "hook_promise_check": {{ "pass": <bool>, "promise": "<훅이 약속한 것>",
      "payoff_cut_no": [<지불 컷번호>], "reason": "<어느 컷이 어떻게 지불하는지>" }},
    "science_reliability": {{ "claim_type": "<measured_result|author_interpretation|model_projection|speculation>",
      "evidence_strength": "<high|medium|low>", "generalization_risk": "<low|medium|high>",
      "required_caveat": "<일반화 시 필요한 단서 or 빈값>" }},
    "cta_type": "<{_CTA_HELP} 중 1>",
    "loop_match": <bool>,
    "series_id": "<시리즈 태그 or 빈값>",
    "content_mode": "<{_CONTENT_MODES_HELP} 중 1 — 입력 content_plan 을 따르라>",
    "primary_claim_id": "<핵심 주장 claim_id>",
    "supporting_claim_ids": ["<보조 주장 claim_id>"],
    "essential_evidence_units": ["<E1~E8 중 이번 영상에 필수인 것>"],
    "duration_reason": "<왜 이 길이인지 한 문장>",
    "retention_plan": {{ "open_loop": "<끝까지 보게 만드는 미해결 질문 한 줄>",
      "pattern_interrupt_cut_nos": [<리듬을 끊어 주의를 되돌리는 컷 번호>] }}
  }},
  "visual_sequences": [
    {{ "sequence_id": "<SEQ1 …>",
       "sequence_role": "<{_SEQUENCE_ROLES_HELP} 중 1>",
       "world": {{ "world_id": "<이 시퀀스가 머무는 세계의 이름>",
                  "style": "<이 세계가 **어디인가** 한 구절 — 장소·공간·거기 놓인 것."
                  " 화풍·재질·렌더 방식은 쓰지 마라(코드가 정한다). 카메라 각도·렌즈 수치도 금지."
                  " 좋음 'A cell culture room with incubators and a steel bench'."
                  " 나쁨 'Microscopic, detailed 3D rendering of cellular structures'(장소가 아니라 그리는 방법)>",
                  "lighting": "<그 장소의 **광원** 한 구절(창·형광등·작업등). 분위기·발광 효과 금지 —"
                  " 'Soft, internal glow' 는 광원이 아니라 효과다. 발광하는 물체를 그리고 싶으면"
                  " 그 물체를 lighting 이 아니라 장면에 적어라>",
                  "background": "<뒤에 **무엇이 있는가** 한 구절."
                  " ★ 'blurred'·'out of focus' 를 쓰지 마라. 흐림은 코드가 정한다."
                  " 뒤에 있다는 것은 **거리**로 말한다 — 'blurred lab equipment' 가 아니라"
                  " 'lab equipment further back along the far wall'. 배경이 부차적이라는 것은"
                  " 위치로 충분히 전달된다>",
                  "camera_base": "<{_CAMERA_BASES_HELP} 중 1 — 이 토큰만 쓴다>",
                  "style_ko": "<style 을 한국어로 — 운영자가 읽는 용도. 영어 원문은 그대로 둔다>",
                  "lighting_ko": "<lighting 을 한국어로>",
                  "background_ko": "<background 를 한국어로>" }},
       "entities": [
         {{ "entity_id": "<PARTICIPANT_A / TOKEN_SET 처럼 대문자 식별자>",
            "entity_type": "<person|object|structure>",
            "visual_identity": "<이 개체를 매 stage 같게 만들 외형 한 구절>",
            "visual_identity_ko": "<위 외형을 한국어로 — 운영자가 읽는 용도>" }} ],
       "stages": [
         {{ "stage_id": "<S1 …>",
            "cut_refs": [<이 stage 가 담당하는 컷 번호들>],
            "operation": "<{_VISUAL_OPERATIONS_HELP} 중 1>",
            "camera_operation": "<{_CAMERA_OPERATIONS_HELP} 중 1>",
            "camera_base": "<{_CAMERA_BASES_HELP} 중 1 — **이 stage 의 축척**. 세계가 하나여도"
            " stage 마다 바꿔라. 최소 하나는 close_detail(근접)이어야 한다>",
            "continuity_mode": "<{_CONTINUITY_MODES_HELP} 중 1>",
            "continuity_from": "<이어받는 **앞선** stage_id. NEW_WORLD 면 빈값>",
            "entity_refs": ["<이 stage 에서 유지되는 entity_id>"],
            "representation_mode": "<{_REPRESENTATION_MODES_HELP} 중 1>",
            "allow_connective": false,
            "mutations": [
              {{ "entity_id": "<위 entities 에 선언한 id>",
                 "property": "<무엇이 바뀌는가 — position/size/state/rotation …>",
                 "operation": "<{_MUTATION_OPERATIONS_HELP} 중 1>",
                 "visible_change": true,
                 "result_state": "<바뀐 뒤 그 개체가 어떻게 보이는가 한 구절>",
                 "claim_ids": ["<이 변화가 지불하는 claim_id>"] }} ],
            "state_before": {{ "<개체 id>": "<이전 상태>" }},
            "state_after":  {{ "<개체 id>": "<이후 상태>" }},
            "observable_change": "<화면에서 눈에 보이게 달라지는 것 한 문장(영어)>",
            "observable_change_ko": "<바로 위 문장을 한국어로 — 운영자가 읽는 용도>",
            "claim_ids": ["<이 stage 가 지불하는 claim_id>"] }} ] }}
  ],
  "cuts": [
    {{
      "cut_no": <int>,
      "scene_kind": "<허용 씬종류 중 1>",
      "evidence_role": "<{_EVIDENCE_ROLES_HELP} 중 1>",
      "claim_ids": ["<이 컷이 지불하는 claim_id — 원장에 있는 것만>"],
      "narration_ko": "<한국어 나레이션>",
      "narration_en": "<영어 나레이션>",
      "estimated_sec": <int, {config.CUT_MIN_SEC}~{config.PAPER_CUT_MAX_SEC}(data_viz {config.DATA_VIZ_CUT_MAX_SEC}, video {config.VIDEO_CUT_MAX_SEC})>,
      "novelty_event": "<이 컷이 주는 '새 정보' 한 구절(새 Claim/새 비교/새 시각 상태)>",
      "asset_strategy": "<{_ASSET_STRATEGIES_HELP} 중 1 — 새 이미지가 정말 필요한 컷만 new_asset>",
      "visual_role": "<MECHANISM|REALITY — 실사형에서만 쓴다. 그 외 버전은 빈값>",
      "mechanism": {{ "subject": "<무엇의 원리인가(한 구절, **영어**)>",
                     "components": ["<화면에 보여야 하는 물체 2개 이상 — **영어, 보이는 물체 이름**(entity_id·데이터셋명 금지)>"],
                     "relationship": "<구성요소들이 서로 어떻게 맞물리는가(영어)>",
                     "initial_state": "<변화 전 상태(영어, 눈에 보이는 모습)>",
                     "transformation": "<무엇이 무엇을 어떻게 바꾸는가 — 이 컷의 핵심(영어)>",
                     "final_state": "<변화 후 상태(영어, 눈에 보이는 모습)>",
                     "highlighted_element": "<화면에서 강조할 하나(영어)>",
                     "claim_ids": ["<이 도해가 지불하는 claim_id>"] }},
      "mechanism_ko": "<위 구조를 한국어 한 문장으로 — 무엇이 무엇을 어떻게 바꾸는지(사람이 읽는 용도)>",
      "visual_reuse_group": "<같은 연구대상·같은 비교축을 공유하는 컷들의 그룹 태그(예: G01). 없으면 빈값>",
      "base_asset_ref": "<재사용 전략일 때 기준이 되는 **앞선** 컷 번호(예: '3'). 아니면 빈값>",
      "crop": {{ "cx": <0~1 가로 중심 비율>, "cy": <0~1 세로 중심 비율>,
                 "scale": <{config.CROP_MIN_SCALE}~{config.CROP_MAX_SCALE} 확대 배율> }},
      "tone_grade": "<{_TONE_GRADES_HELP} 중 1 — 색만 바꿔 시간·감정 변화를 표현. 기본 none>",
      "state_change": "<재사용 컷이나 {config.CUT_STATE_CHANGE_MIN_SEC}초 초과 컷: 화면에서 무엇이 어떻게 바뀌는지>",
      "overlay_plan": [
        {{ "type": "<{_OVERLAY_TYPES_HELP} 중 1>",
           "text": "<화면에 뜰 짧은 문구(표본·기간·수치·단서). 나레이션과 중복하지 마라>",
           "payload": {{ "<legend 일 때>": "items: [{{color: amber|blue|coral, label: 한글 낱말}}] (2~3개)",
                        "<label_pair 일 때>": "top: 위 화면이 무엇인지 / bottom: 아래 화면이 무엇인지 (한글, 짧게)",
                        "<pointer 일 때>": "at: [구역 1~3개] — {_POINTER_ZONES_HELP}" }},
           "claim_ids": ["<이 카드가 근거하는 claim_id>"],
           "start_sec": <컷 시작 기준 초>, "duration_sec": <int, 최소 {config.OVERLAY_MIN_SEC}>,
           "priority": "primary|supporting" }}
      ],
      "visual_prompt": "<이미지/클립 생성용 영문 프롬프트>",
      "visual_prompt_ko": "<위 영문 프롬프트가 무엇을 그리라는 것인지 한국어 한두 문장>",
      "beat": "<{_BEAT_KINDS_HELP} 중 1 — 이 컷이 설명에서 맡은 역할>",
      "motion_value": "<{_MOTION_VALUES_HELP} — 움직임이 이해·감정·반전에 직접 기여하면 high>",
      "motion_source": "<video|still — 이 컷을 I2V 영상으로 낼지 스틸로 낼지. 버전 지침이 영상 컷 수를 정했으면 그만큼 video 로 적어라. 기본 still>",
      "motion_prompt": "<motion_source=video 컷만: 카메라·피사체 모션 전용 영문(visual_prompt 와 분리). still 컷은 빈값>",
      "temporal_plan": [ {{ "t0": <초>, "t1": <초>, "entity_id": "<이 구간에서 변하는 개체>",
                            "mutation": "<{_MUTATIONS_HELP}>", "camera": "<{_CAMERA_OPS_HELP}>" }} ],
      "loop_safe": <bool — 역재생해도 어색하지 않은 모션인지. 기본 false>,
      "style_anchor_ref": "<이전 컷/기준 이미지 참조 설명 — 일관성, 없으면 빈값>",
      "effects": ["<허용 토큰만>"],
      "transition": "cut|crossfade",
      "bgm_cue": "<이 컷의 BGM 강약/전환 지시 or 빈값>",
      "source_facts": ["<Fact Sheet 항목 키>"],
      "render_notes": "<렌더러용 특기사항 or 빈값>"
    }}
  ]
}}"""

# 모든 버전 공통: 영상은 "기본 자산"이 아니라 선택 투자다. 개수를 채우는 게 아니라 값어치로 고른다.
# ★ 개정(수정명세 §10-4): 예전 문구는 "상한을 꽉 채워 배정하라 — 남기지 마라"였는데, 그러면 모델이
#   상한만큼 배정하고 preflight 이 절반을 스틸로 강등하는 낭비가 반복됐다. 이제 motion_value 로 고른다.
# ★★ 연출 계약(v2 Phase E2)은 **독립 상수**다. 종전에 이 문단을 _VIDEO_CLIP_GUIDANCE 에만
#   넣었더니 실사형(photo)이 _PHOTO_VIDEO_CLIP_GUIDANCE 를 쓰는 바람에 **등급제를 켜는 바로
#   그 버전에 계약이 안 갔다** — 만들어 놓고 한쪽만 연결의 아홉 번째가 될 뻔했다(즉시 발견).
#   두 지침이 같은 문자열을 참조하게 해서 구조로 막는다.
TEMPORAL_CONTRACT_GUIDANCE: str = (
    " ★★[연출 계약] **기전(원리·구조·인과)을 설명하는 영상 컷**에는 temporal_plan 을 2~3개"
    " 비트로 채워라. 한 클립은 '한 장면을 오래 보여주는 것'이 아니라 **작은 편집 시퀀스**다:"
    " 예) 0-2.5s 전체 구조를 DOLLY_OUT 으로 드러내고 → 2.5-5.5s 작동 부위를 TRACK 으로 따라가고"
    " → 5.5-8s 핵심 부위로 DOLLY_IN 급속 push-in. 각 비트는 시간 구간·변하는 개체·변화(mutation)"
    " ·카메라를 갖는다. 비트가 없으면 그 컷은 긴 클립을 받지 못하고 짧아진다."
    " ★ camera·mutation 은 위 목록 토큰만 쓴다(자유 문장 금지 — 화면에 글자로 박힌다)."
    " ★ 비트 시간은 겹치지 않게, 앞에서 뒤로 이어지게 적어라."
    " ★★ [좋은 비트의 실측 예시 — 이대로 써라] 실제로 화면에서 작동한 8초 컷이다"
    " (달 충돌 실측 2026-08-31, 그리고 벤치마크 채널 제작법이 공개한 공식과 같다):"
    "   0.0-2.5s  DOLLY_OUT  로켓이 들어온다      (전체 구조를 드러낸다)"
    "   2.5-5.5s  TRACK      로켓이 가로질러 간다  (횡이동 — 이 구간이 화면에 실제로 나타났다)"
    "   5.5-8.0s  DOLLY_IN   분화구를 때린다      (마지막 급속 푸시인 + 사건)"
    " 벤치마크 공식: **횡이동 → 마지막 급속 푸시인**, 8초에 비트 2~3개."
    " ★★★ 계약이 요구하는 것은 **필드 채우기가 아니라 실제 움직임**이다:"
    "   ① 카메라 중 **최소 하나는 HOLD 가 아니어야** 한다. HOLD 만 쓰면 8초가 정지 화면이 된다."
    "   ② 비트마다 **카메라를 다르게** 써라(같은 토큰 반복 금지) — 한 컷 안의 멀티샷이다."
    "   ③ 변이 중 **최소 하나는 실제 변형**이어야 한다:"
    " MOVE·GROW·SHRINK·ROTATE·TRANSFORM·SPLIT_OFF·MERGE_INTO·REVERSE_TRACE·IMPACT."
    " APPEAR·HIGHLIGHT·DIM 만 쓰면 '나타났다/빛난다'뿐이라 정지 화면으로도 성립한다 —"
    " 실측(2026-09-03): `APPEAR+HOLD` 두 번으로 8초를 받은 컷이 아무것도 안 움직였다."
    " ★ 즉 좋은 비트는 **무엇이 어떻게 변하는지 + 카메라가 어디로 가는지**가 매 비트 다르다."
)

# 서사 골격 — **대본이 원리를 설명해야 그림도 원리를 설명할 수 있다**(2026-09-04).
#
# ★ 왜 생겼나: 실측에서 지시서 **20개 전부**(20/20) evidence_role 에 `mechanism` 이
#   **0개**였다. 그런데 같은 프롬프트가 그림에는 "MECHANISM 도해 컷 5~7개"를 요구한다.
#   즉 **말은 원리를 한 번도 설명하지 않는데 그림에만 원리를 그리라고 시켰다.**
#   운영자가 첫 실사형 렌더를 보고 한 말 — "3d 도해나 원인과 원리를 설명하는 내용과
#   전혀 상관없는 의미없는 화면" — 은 화풍 문제가 아니라 **대본에 원리가 없다**는 뜻이었다.
#   실제 그 지시서의 흐름: 훅 → 출처 → 규모 → 결과 → 결과 → 결과 → 규모 → 시사점.
#   인과가 한 번도 없는 **결과 나열**이다.
#
# ★ 근거: 운영자가 준 발행 벤치마크(신비한 건축사전 시화호 편, 105초)는 기전을 **세 번**
#   설명한다 — 원인(방조제가 물길을 끊었다) → 재정의(오염이 아니라 호수 자체가 문제다)
#   → 해법(방조제에 구멍을 뚫고 터빈을 심는다). 그 셋이 3D 도해가 놓인 자리다.
#   docs/벤치마크_시화호_구조분석_2026-09-04.md 1·5절.
#
# ★ 어휘를 새로 만들지 않는다. 기존 `evidence_role` 의 `mechanism` 을 **쓰게** 할 뿐이다
#   (config.SCENE_ROLES 주석이 경고한 "역할 어휘 4벌째"를 만들지 않는다).
PHOTO_NARRATIVE_ARC: str = (
    " ★★★ [서사 골격 — 이것부터 정하고 컷을 나눠라] 좋은 설명 영상은 결과 나열이 아니라"
    " **인과 사슬 하나**다. 발행 벤치마크의 105초가 이 순서였다:"
    "   ① 훅(결론을 먼저) → ② 반전·문제(그런데 이런 문제가 있었다) →"
    " ③ 원인(왜 그렇게 됐나) → ④ 증거(숫자로 확인) → ⑤ 시도와 한계(이렇게 해봤지만) →"
    " ⑥ **원리·해법(그래서 이렇게 푼다 — 어떻게 작동하는가)** → ⑦ 결과(그래서 이렇게 됐다)."
    " ★★ 이 중 **⑥ 원리가 이 영상의 심장**이다. ⑥ 이 없으면 '무슨 일이 있었다'는 소식이지"
    " 설명이 아니고, 그림은 그릴 원리가 없어서 의미 없는 화면이 된다."
    " ★★ 따라서 **evidence_role='mechanism' 컷**을 반드시 두어라 — 몇 개인지는"
    " 아래 [기전 컷 수]가 영상 길이에서 정해 준다(길수록 늘어난다)."
    " 2개 이상이면 하나는 '왜 그런 일이 벌어지는가(원인·기전)',"
    " 하나는 '그래서 어떻게 작동하는가(해법·구조)'로 갈라라."
    " 이 컷들의 나레이션은 **결과가 아니라 과정**을 말한다:"
    " '무엇이 무엇에 작용해서 무엇이 된다'는 문장이어야 한다."
    "   나쁜 예(결과 나열): '성격 조합이 광고 품질에 직접적인 영향을 미쳤습니다.'"
    "   좋은 예(기전): '외향적인 사람은 아이디어를 넓게 벌리는데, 성실한 AI 는 그걸 계속"
    " 규격에 맞춰 좁힙니다. 그래서 확장과 수렴이 서로를 상쇄해 평범한 결과만 남습니다.'"
    " ★ MECHANISM 도해 컷은 **바로 이 mechanism 나레이션 위에 놓아라.** 그림이 설명하는"
    " 원리와 말이 설명하는 원리가 **같아야** 한다 — 지금까지의 실패가 정확히 이 어긋남이었다."
    " ★★★ [기전 컷은 **상태가 아니라 과정**이다] 실측 사고(2026-09-09): 세포 도해 세 컷이"
    " 전부 '세포 하나가 놓여 있고 주변에 뭔가 있다'였고, 그래서 세 컷이 같은 그림이 됐다."
    " 기전은 **A가 B에 작용해서 C가 된다**는 움직임이다. 한 화면이 그 움직임을 담게 적어라:"
    "   ① 한 화면 안에 **왼쪽 원인 → 가운데 작용 → 오른쪽 결과** 로 벌려 놓거나,"
    "   ② 같은 대상의 **전과 후를 반반으로 갈라** 나란히 두거나,"
    "   ③ 붙는 자리·잘리는 자리처럼 **일이 실제로 벌어지는 지점**을 화면 가운데 둔다."
    " (화살표·라벨·글자를 그리라는 말이 아니다 — 물체의 **배치**로 말하라.)"
    " ★★★ [배우를 먼저 무대에 세워라] 한 세계의 **여는 컷**(NEW_WORLD stage 의 첫 컷)이"
    " 그 세계의 **유일한 새 그림**이다. 뒤 컷들은 그 그림을 그대로 첨부하고 \"이것만"
    " 바꿔라\"로 만들어진다 — 그래서 **여는 그림에 없는 물체는 뒤에서 줄일 수도 키울 수도"
    " 없다.** 실측 사고: 여는 컷이 세포 모형만 그렸는데 뒤 컷들이 '붉은 조각을 줄여라'"
    " '노란 조각을 줄여라'고 해서, 없는 것을 줄이지 못한 세 컷이 같은 화면으로 나왔다."
    " ★★ 그러니 뒤 stage 가 움직일 개체는 **전부 여는 컷의 visual_prompt 에 물체로** 적어라:"
    " 모양·색·개수·놓인 자리. 줄어드는 것을 보여줄 생각이면 여는 컷에 **넉넉히** 놓아라."
    " ★★ '염증의 징후가 보인다' 처럼 **판정**으로 적지 마라 — 징후는 물체가 아니라서"
    " 아무것도 안 그려진다(실측). '세포 주변에 흩어진 작고 붉은 불규칙한 조각들' 처럼"
    " 눈으로 셀 수 있게 적어라."
    " ★★★ [컷마다 축척을 바꿔라] 같은 세계에 머무는 것은 옳지만, **연속한 stage 가 같은"
    " camera_base 면 두 컷이 사실상 같은 그림**이 된다(실측: 세포 stage 셋이 전부"
    " close_detail 이었다). 세계 바깥 → 잘린 단면 → 물체가 붙는 자리 근접, 이렇게"
    " **들어가면서** 설명하라. 눈이 확 가는 것은 색이 아니라 **축척 변화**에서 나온다."
    " ★ 논문에 기전이 정말 없으면(순수 상관·메타분석) 지어내지 마라. 대신 **연구가 제시한"
    " 해석**을 기전 자리에 놓고, 그것이 해석임을 나레이션에 밝혀라('연구진은 …로 봅니다')."
    " ★★★ [같은 사진을 두 번 틀지 마라] 실사형에서 asset_strategy 는 항상 new_asset 이다."
    " 재사용(reuse_*)을 적으면 코드가 무시한다. 통일성은 앞 stage 그림을 **참조**해 새 프레임을"
    " 그리는 것으로 얻는다 — 같은 파일을 복사해 나레이션만 바꾸는 것이 아니다."
    " 실측: 재사용 8컷이 같은 두 쥐 20초, 같은 구체 32초를 만들었다."
    " ★★★ [연구 대상이 화면을 먹지 않게 하라] 동물·시료·장비 같은 **연구 대상**은 전체의"
    " 35%를 넘기지 마라. 실측: 쥐 실험 영상에서 쥐가 86초 중 42초(49%)를 차지했고 운영자는"
    " '생쥐 이미지를 40초 보고 싶어 할 것 같으냐'고 했다. 대상은 **훅과 규모 실감에서만** 짧게"
    " 보이고, 나머지는 원리(도해)·맥락(약이 쓰이는 현장)·의미(시청자 세계)로 옮겨라."
    " 절차 컷(주사·케이지·측정)은 한 컷을 넘기지 마라."
    " ★★★ [훅은 **화면**으로도 훅이어야 한다] 훅 규칙(P1~P3)은 나레이션에 대한 것이다."
    " 말로만 반전을 하고 화면은 무난한 설정 샷을 쓰면 훅이 아니다."
    " ★★ 컷1·2 의 화면은 **한눈에 대비가 보여야** 한다 — 나란히 놓기 / 전과 후 /"
    " 같아 보이는데 다른 것. 시청자가 0.5초 안에 '어? 왜 다르지?' 해야 한다."
    " ★★ 훅에 **설정 샷을 쓰지 마라**: 연구실 전경, 우리 속 동물 한 마리, 연구자가"
    " 현미경을 들여다보는 장면, 책상 위 장비. 그건 배경이지 훅이 아니다."
    " 실측(2026-09-04): 훅 두 컷이 '우리 속 쥐 한 마리'였고 **정작 대비 화면(두 우리를"
    " 나란히)은 컷3 출처 소개에 가 있었다.** 가장 센 그림을 뒤에 두지 마라."
    " ★★ 컷1 과 컷2 는 **다른 그림**이어야 한다(실측 22%가 같은 이미지를 재사용했다)."
    " 벤치마크 문법: 컷1 에서 대비를 넓게 보여 주고(TRACK), 컷2 에서 한쪽으로"
    " **급속 푸시인**(DOLLY_IN)하며 숫자를 얹는다."
    " ★ 주제가 '노화·수명·질병'처럼 시청자 몸에 닿는 것이면 훅 화면도 그 축에 세워라 —"
    " 연구 절차(주사·케이지·라벨)가 아니라 **결과의 모습**을 먼저 보여준다."
        " ★★★ [세계는 하나, 바뀌는 것은 축척이다] 발행 벤치마크는 **105초 내내 같은 장소**에"
    " 머문다. 하드 컷은 37초에 6번뿐이고 나머지는 **같은 세계 안에서 카메라가 이동**한다."
    " 바뀌는 것은 장소가 아니라 **축척**이다: 광역 부감 ↔ 중경 ↔ 근접."
    "   예) 방조제 12.7km 전체(광역) → 농지와 도시 배치(중경) → 손이 물을 뜬다 →"
    " 유리병 클로즈업(근접). **3초 만에 광역에서 손바닥까지 내려온다.**"
    " ★★ 그러니 시퀀스마다 새 세계를 만들지 마라. 앞 시퀀스의 world_id 를 **그대로 재사용**하고"
    " camera_base 와 카메라 동작만 바꿔라(CONTINUE_WORLD·RETURN_WORLD·CAMERA_REVEAL)."
    " 실측: 우리 지시서가 71초에 세계를 4개 만들었고 컷 경계마다 화면이 갈아엎어졌다."
    " 반면 화면이 좋았던 지시서들은 전부 **세계 1개**였다."
    " ★★ 축척은 **stage 의 camera_base** 로 바꾼다. 각 stage 에 camera_base 를 적어라"
    " (top_down·elevated_three_quarter·eye_level_front·side_profile·low_angle·close_detail)."
    " 세계가 하나여도 stage 마다 축척이 달라야 화면이 살아난다."
    " ★★ 그리고 **최소 하나의 stage 는 camera_base='close_detail'**(근접)이어야 한다."
    " 크기 대비가 있어야 '이게 진짜 있는 일'이 된다 — 전부 멀리서 보면 도해가 지도처럼"
    " 남고 실감이 안 난다. 벤치마크는 광역 12.7km 에서 손바닥의 물 한 컵까지 3초 만에 내려간다."
    " ★ 물리적 장소가 정말 여럿이면(현장 A → 실험실 B) 새 세계를 만들어도 된다."
    " 다만 **연결·평가 문장 때문에** 세계를 새로 만들지는 마라."
    " ★★★ [단, 결과·한계·결론은 실험실 밖으로 나가라] 위 '세계는 하나'는 **기전을 설명하는"
    " 구간**의 규칙이다. 행동·삶의 결과·연구의 한계·결론처럼 **시청자의 세계**를 말하는"
    " 구간까지 실험실 탁자에 가두면 영상 전체가 한 장면이 된다 — 그 구간은 사람과 일상 장소"
    " (출근길·가족 식탁·교실·거리)를 REALITY 세계로 새로 열어라. 실측 2026-09-14 운영자:"
    " '시퀀스의 배경이 뇌의 이미지와 뇌 안에서 벌어지는 이미지로 너무 한정된다'(13컷 전부"
    " 실험실 탁자 한 세계였다). 기전 구간은 하나의 세계, 결과·결론 구간은 사람의 세계 — 둘이다."
    " ★★★ [영상 컷은 카메라가 움직여야 한다] motion_source='video' 인 컷은 **모두**"
    " temporal_plan 의 카메라 중 최소 하나가 HOLD 가 아니어야 한다. 기전 컷만이 아니다 —"
    " 영상비를 내고 정지 화면을 받는 것이 가장 나쁘다(실측: HOLD 만 쓴 영상 컷이 매번 나왔다)."
    " ★★★ [오버레이는 코드가 그린다 — 프롬프트에서 언급하지 마라] overlay_plan 의 카드는"
    " 렌더가 그린다. visual_prompt·motion_prompt 에 'text overlay', '카드가 나타난다',"
    " '숫자가 뜬다' 같은 말을 적지 마라. 실측 사고: motion_prompt 에"
    " \"allowing the text overlay to appear prominently\" 가 들어가 같은 컷의"
    " \"No on-screen text\" 와 정면으로 부딪혀 승인이 막혔다. 화면에 글자를 그리는 것은"
    " 생성 모델의 일이 아니다."
    " ★★★ [수치는 크게, 그리고 수치만] overlay_plan 의 number_punch 는 **수치와 단위만**"
    " 담는다('254MW', '+16.9%', '12.7km'). 화면 폭을 크게 차지하는 한 방이라서, 문장을 넣으면"
    " 여러 줄로 감겨 화면을 덮는다. 실측: number_punch 에 28자짜리 요약문이 들어와 있었다"
    " ('AI 데이터센터 ESS 수요 2030년까지 20배↑'). **설명은 evidence_card 로 옮겨라.**"
)

_VIDEO_CLIP_GUIDANCE: str = (
    " ★영상 클립(I2V)은 값비싼 선택 투자다. 개수 상한을 의무적으로 채우지 마라 — 움직임이 이해·감정·반전에"
    " 직접 기여하는 컷에만 배정한다. 컷마다 motion_value 를 판정하라:"
    " high(움직임이 이해에 직접 기여) / medium(리듬은 좋아지나 이해에 필수 아님) / low(스틸+모션 효과로 충분)."
    " ★motion_value 가 high 인 컷만 \"motion_source\": \"video\" 로 지정한다. medium·low 는 스틸이다."
    " 단순 출처 카드·수치 카드에는 절대 영상을 배정하지 마라(코드 그래픽·오버레이가 더 낫고 공짜다)."
    " 후보 우선순위: 오프닝 훅에 실제 움직임이 필요한 경우 → 현상 전개·메커니즘 설명 → 전후 비교가"
    " 동적으로 변하는 장면 → 마지막 의미 루프. 배정할 만한 컷이 없으면 0개여도 좋다."
    " 영상 컷에는 카메라·피사체 모션을 별도 필드 motion_prompt(영문)에 적어라 — visual_prompt 에는 정적"
    " 장면만, 모션 구절은 넣지 마라(예: motion_prompt='slow push-in, subtle motion, elements gently drift')."
    " 나머지 정적 컷은 \"motion_source\": \"still\"(또는 생략)이고 motion_prompt 는 비워둔다."
    " ★표본·기간·수치·비교는 생성 영상보다 코드 시각화(scene_kind=data_viz)·오버레이를 우선한다."
    " ★영상 컷도 스틸과 완전히 같은 화풍/톤이어야 한다(그림을 그대로 애니메이션 — 톤이 튀면 안 됨)."
    # §3-4: 클립이 나레이션보다 짧을 때 핑퐁 루프(정방향→역방향)를 쓸 수 있는지 컷이 선언한다.
    " ★카메라가 천천히 움직이거나 분위기만 담는 컷은 \"loop_safe\": true. 인물의 걷기·물의 흐름·"
    "요소의 등장처럼 방향이 있는 모션은 \"loop_safe\": false(역재생하면 티가 난다)."
)

# 에셋 재사용(수정명세 §10-5). 길이가 늘어도 이미지 수가 함께 늘지 않게 하는 실제 장치다.
_ASSET_REUSE_GUIDANCE: str = (
    " ★에셋 예산: 새 이미지를 만드는 컷(asset_strategy=new_asset)은 [비용 예산]의 고유 에셋 상한 이내로."
    " 상한은 **넘으면 안 되는 선**이지 채워야 할 목표가 아니고, 마찬가지로 재사용도"
    " **채워야 할 할당량이 아니다.** 기본값은 new_asset 이다."
    " ★★ 재사용은 **서사가 진행돼서 같은 대상이 다시 나올 때만** 쓴다 — 같은 인물의 다음 단계,"
    " 같은 장치의 다음 상태, 같은 비교축의 다음 수치. 즉 **화면에서 무엇인가 눈에 보이게 달라져야"
    " 한다.** 앞 컷과 같은 인물·같은 포즈·같은 구도가 아무 변화 없이 또 나오면 그것은 재사용이"
    " 아니라 **같은 장면을 두 번 트는 것**이고, 시청자는 영상이 멈춘 줄 안다."
    " 재사용 컷은 base_asset_ref 로 **앞선** 컷 번호를 가리키고, 같은 대상을 공유하는 컷끼리는"
    " visual_reuse_group 을 맞추고, **state_change 에 무엇이 어떻게 달라지는지를 적어라**"
    " (예: '동전 더미가 3층에서 5층으로 늘어난다', '단면의 강조 부위가 후각구에서 편도체로 옮겨간다')."
    " state_change 를 못 적겠으면 그 컷은 재사용이 아니다 — new_asset 으로 바꿔라."
    " ★ 코드가 렌더 뒤 기준 컷과 픽셀을 비교한다. 실제로 달라지지 않았으면 그 컷은 폐기된다 —"
    " state_change 에 적은 변화는 **화면에 보이는 변화**여야 한다(설명 문장이 아니라)."
    " 텍스트만 바뀌는 전환은 text_only_transition, 코드 그래픽은 code_viz 를 쓴다(둘 다 생성비 0)."
)

# ★ 실사형 전용 클립 지침. 공통 _VIDEO_CLIP_GUIDANCE 는 "움직임이 꼭 필요한 컷만, 0개여도
#   좋다"고 강하게 말리는데, 그 문구가 실사형 계약의 "6~8개 배정하라"를 이겼다(실측: 두 번
#   생성해 두 번 다 영상 컷 2개). 실사형은 움직이는 화면이 정체성이라 지침 자체를 갈아 끼운다.
#   유지하는 것: 모션 구절은 motion_prompt 에 따로, loop_safe 선언, 실패 시 스틸 폴백.
_PHOTO_VIDEO_CLIP_GUIDANCE: str = (
    " ★영상 클립(I2V): 이 버전은 **움직이는 화면이 기본**이다. 컷의 절반 이상,"
    " 즉 **6~8개를 \"motion_source\": \"video\"** 로 지정하라(스틸은 보조다)."
    " ★영상 컷은 **MECHANISM(3D 도해)에 먼저** 배정하라. 단면이 열리고, 층이 분리되고, 흐름이"
    " 이동하는 것 — 그 움직임 자체가 이 버전의 설명력이다. **정지된 3D 도해는 그냥 그림이고,"
    " 말로 하는 설명을 도로 가져간다.** REALITY 컷은 훅·마무리처럼 현장감이 필요한 자리에만 영상을 쓴다."
    " ★영상 컷은 **연달아 붙여서** 배치하라. 렌더가 앞 영상 컷의 마지막 화면에서 다음 컷을 이어"
    " 만들기 때문에, 붙어 있어야 카메라가 끊기지 않고 한 장면처럼 흐른다. 영상-스틸-영상처럼"
    " 띄엄띄엄 두면 그 연결이 매번 끊긴다."
    " ★카메라·피사체 모션은 별도 필드 motion_prompt(영문)에 적어라 — visual_prompt 에는 정적"
    " 장면만 쓴다(예: motion_prompt='slow aerial orbit, subtle heat haze, workers moving in background')."
    " 이어지는 영상 컷들의 motion_prompt 는 **같은 카메라 동작을 이어가듯** 써라"
    " (예: 오비트 → 계속 오비트하며 접근 → 접근 끝에서 푸시인)."
    " ★카메라가 천천히 움직이거나 분위기만 담는 컷은 \"loop_safe\": true. 인물의 걷기·물의 흐름·"
    "요소의 등장처럼 방향이 있는 모션은 \"loop_safe\": false(역재생하면 티가 난다)."
    " ★표·수치·출처는 영상으로 만들지 마라 — overlay_plan(코드 그래픽)이 담당한다."
    " ★영상 프롬프트는 **카메라와 피사체가 어떻게 움직이는지만** 말한다"
    " (화면에 무엇이 나타나는지는 아래 [화면 그래픽 금지]가 정한다)."
)

# 화면 그래픽·글자 요구 금지(v2, 2026-08-31 개정). ★★ **독립 상수이자 필드 중립**이다.
#   종전에는 이 문단이 _PHOTO_VIDEO_CLIP_GUIDANCE 안에서 "[motion_prompt 금지]" 로 시작했다.
#   그랬더니 모델이 그것을 **motion_prompt 에만 걸린 규칙**으로 읽고 같은 요구를
#   visual_prompt 에 썼다 — 재생성 실측 3건이 전부 visual_prompt 였다(로고 / 단어
#   'Astonishing' 텍스트 애니메이션 / computer screen showing data visualization).
#   게이트(engine/photo_contract._raw_text_of)는 처음부터 두 필드를 다 보고 있었으므로
#   **반쪽이었던 것은 게이트가 아니라 프롬프트다.** 필드 이름으로 범위를 만들지 않는다.
# 초안 장면(video_prompts[])에서 실사형 지시서 입력으로 **넘기지 않는** 필드.
#   초안 단계의 시각 제안이다 — 지시서 단계가 다시 정하는 것이 바로 이것이고, 금지된
#   화면 그래픽 요구가 여기 실려 그대로 계승됐다(directive_user_prompt 의 주석).
_DRAFT_SCENE_VISUAL_FIELDS: frozenset[str] = frozenset(
    {"image_prompt", "image_prompt_ko", "video_prompt", "video_prompt_ko"})

SCREEN_GRAPHIC_BAN_GUIDANCE: str = (
    " ★★[화면 그래픽 금지 — visual_prompt·motion_prompt **둘 다**]"
    " **화면에 그래픽·오버레이·라벨·치수선·계기판·로고·글자가 있거나 나타난다고 쓰지 마라.**"
    " 두 필드 중 어느 쪽에 적든 똑같이 폐기 사유다 — 생성 모델은 필드를 구분하지 않고"
    " 합쳐서 그린다."
    " 금지 예시(전부 실측에서 나온 문장이다):"
    " 'a graphic overlay appears indicating…', 'annotation lines mark…', 'a readout shows…',"
    " \"a subtle logo of a fictional university\", \"text animation of the word 'Astonishing'\","
    " 'a computer screen showing a data visualization'."
    " ★ 'fictional'·'no actual names'·'no on-screen text' 같은 단서를 붙여도 금지다."
    " 실측(2026-08-31): 모델이 같은 문장 안에서 글자를 요구하면서 동시에 금지했고,"
    " 화면에는 지어낸 글자가 그대로 박혔다. 부정문은 생성 모델에 통하지 않는다."
    " 실측(2026-08-31): 그런 문장 하나 때문에 클립 4개가 **전부** 달 표면 실사에서"
    " 도표 화면으로 튕겨 나갔다 — 글자만 문제가 아니라 **세계를 떠난다**."
    " ★ 대신 이렇게 써라: 화면에 얹히는 글자·수치·지시선·출처는 overlay_plan 이 코드로"
    " 그린다(수치=number_punch, 비교=group_compare, 전후=before_after, 표본·기간=scope_tag,"
    " 출처=source_card). **이미지에는 라벨 없이 차이만** 그리고, 어느 쪽이 무엇인지는"
    " 오버레이 카드가 말한다. 소속·기관이 필요하면 로고가 아니라 **장소로** 보여라"
    " (간판 글자가 아니라 건물·복도·실험대)."
)

# 시각 시퀀스 지침(v3 Phase 2). ★ 이 저장소가 v2 에서 실제로 겪은 실패를 근거로 쓴다.
_SEQUENCE_GUIDANCE: str = (
    " ■■ 시각 시퀀스 — 이 버전의 화면 문법이다."
    " 컷 하나에 세계 하나를 만들지 마라. **같은 세계가 단계적으로 변하면서** 설명이 진행된다:"
    " 전체 → 내부 공개 → 흐름 → 결과. 컷은 나레이션·타이밍 단위로 남고, 그 위에 stage 가 얹힌다."
    " ★ 실측 근거: v2 는 11컷 영상에 원본 이미지가 6장뿐이었고 그중 둘은 완전히 같은 파일이었다."
    " 컷마다 새로 그리면 같은 인물이 다른 사람이 되므로 연속성의 유일한 수단이 복붙이었다."
    " 이제 참조 조건 생성으로 **같은 세계의 다음 상태**를 만들 수 있다(실측 확인, 단가 동일)."
    " ■■ [세계는 물리적 장소다] world 는 **실제로 가 볼 수 있는 곳이나 만질 수 있는 실물**이어야"
    " 한다 — 실험실·공장 라인·시술실·현장, 또는 단면을 연 장치·시료·부품."
    " **화면 속을 세계로 잡지 마라**: 인터페이스·대시보드·앱 화면·소셜 피드·'digital space'·"
    " 'abstract space with nodes' 전부 금지다. 세계가 화면이면 **그 시퀀스의 모든 컷이 UI 렌더가"
    " 된다** — 컷에서 글자를 금지해도 소용이 없다. 결정은 여기서 끝난다."
    " 실측(2026-09-03): 세계 5개 중 3개를 AD_CREATION_INTERFACE·SOCIAL_MEDIA_FEED·"
    " HUMAN_AI_COLLABORATION_SPACE 로 잡았고, 그 안의 컷들이 게이지·막대그래프·아이콘으로"
    " 채워져 **통째로 폐기**됐다."
    " ★ 주제가 추상적일수록(성격·협업·신뢰·효율) 세계는 **더 구체여야** 한다:"
    " 그 연구가 실제로 벌어진 방, 참가자가 앉은 자리, 결과가 인쇄된 종이."
    " ★★ **소재 자체가 화면일 때**(광고·앱·소셜미디어·대시보드 연구) — 여기서 대부분 틀린다."
    " 화면을 세계로 잡지 말고 **그 화면을 보는 사람과 자리**를 세계로 잡아라."
    "  ▸ 나쁨: world=SOCIAL_MEDIA_FEED (피드 자체가 세계 → 컷이 전부 UI 렌더)"
    "  ▸ 좋음: world=사람이 손에 든 폰을 들여다보는 카페 자리 — 화면은 그 손 안에 **소품으로**"
    " 들어간다. 카메라는 사람과 공간에 있고, 화면 내용은 작게·비스듬히·부분만 보인다."
    " 즉 **화면은 세계가 아니라 세계 안의 물건**이다. 이렇게 잡아야 실사가 성립하고,"
    " 화면 속 글자를 지어낼 필요도 사라진다(작게 나오므로)."
    "  ▸ 화면이 집기로 들어간 세계는 통과한다 — 예: '사람들이 일하는 오픈플랜 사무실,"
    " 모니터 여러 대', '각 자리에 컴퓨터가 놓인 연구실 큐비클'. 반대로 세계 자체가"
    " 'feed'·'interface'·'digital space'·'holographic' 이면 막힌다."
    " ★★ [비교·결론 대목의 실물 대안] 여기서 가장 자주 화면으로 도망간다."
    " 'A와 B를 비교한다'·'그래서 이런 뜻이다' 같은 대목은 그릴 실물이 없어 보이지만,"
    " **연구가 실제로 만들어 낸 물건**이 있다. 그것을 책상에 놓아라:"
    "  ▸ 두 결과 비교 → **인쇄물 두 장을 나란히** 놓고 한쪽에 손이 얹힌다 /"
    " **폰 두 대를 나란히 든 손** / 서류 두 묶음의 **두께 차이**"
    "  ▸ 성과가 늘었다 → 같은 책상에 **쌓인 양이 달라진** 두 더미(코인·서류·시료)"
    "  ▸ 결론·시사점 → 연구자가 그 결과물을 들고 있는 자리, 회의 탁자 위의 인쇄물"
    " ★ 어느 쪽이 무엇인지는 **오버레이 카드가 말한다** — 화면에 라벨을 그리지 마라."
    " 이미지에는 **라벨 없이 차이만** 나오게 한다(같은 조명·같은 구도, 양만 다르게)."
    " ★★ **인쇄물을 쓸 때 그 위에 도표를 그리지 마라**(실측 2026-09-03: '인쇄된 보고서,"
    " 페이지에 charts and data 가 보인다'가 폐기됐다). '읽을 수 없게' 라고 덧붙여도"
    " 마찬가지다 — 생성 모델은 그 단서를 지키지 못하고, 지켜도 그건 가짜 도표다."
    " 인쇄물에서 보여줄 것은 **글자 블록의 결·종이 두께·넘기는 손·쌓인 높이**다."
    " 종이가 몇 장인지, 어느 쪽이 두꺼운지가 곧 비교다."
    " ■ visual_sequences 를 채워라. 각 시퀀스는 world(머무는 세계) + entities(유지되는 개체)"
    " + stages(단계)를 갖는다. MECHANISM_SEQUENCE 는 **stage 가 2개 이상**이어야 한다 —"
    " 한 장면으로 끝나는 설명은 시퀀스가 아니다."
    " ■■ stage 마다 **mutations 를 반드시 채워라** — 이것이 진행의 증거다."
    " 무엇이(entity_id) 어떤 속성이(property) 어떻게(operation) 바뀌고 그것이 눈에 보이는지"
    " (visible_change)를 적는다. state_before/state_after 는 사람이 읽는 서술로 함께 적되,"
    " **진행 판정은 mutations 로 한다** — 상태 두 벌을 네가 다 쓰면 달라졌다는 말이 결국"
    " 네 자기보고가 되기 때문이다(standing → standing calmly 로도 통과해 버린다)."
    " mutations 가 빈 stage 는 폐기된다."
    " ■■ **기전 stage 는 APPEAR·HIGHLIGHT 만으로 끝내지 마라.** '나타났다'와 '빛난다'는"
    " 정지 화면으로도 성립해서 원리를 설명하지 못한다 — 최소 하나는 실제로 **변형**돼야 한다"
    " (MOVE·GROW·SHRINK·ROTATE·TRANSFORM·SPLIT_OFF·MERGE_INTO·REVERSE_TRACE·IMPACT)."
    " 실측 2026-09-12: 최근 지시서 10편의 컷 124개 중 절반 가까이가 '나타남·빛남'뿐이어서"
    " 8초 등급을 받지 못하고 화면이 거의 정지했다."
    " ■ state_before 에는 **앞 stage 에 실제로 있던 개체**만 적어라. 앞에 없던 것을"
    " 물려받았다고 쓰면 폐기된다 — 새로 등장시키려면 mutations 에 APPEAR 로 선언한다."
    " ■ 상태·변이에 쓰는 개체 id 는 **전부 entities 에 먼저 선언**해야 한다. 선언 없는"
    " 개체는 stage 마다 다른 모습으로 그려진다."
    " ■ representation_mode 를 정확히 골라라. LITERAL_OBSERVATION 은 **원문이 그 관측"
    " 방식까지 말할 때만** 쓴다 — 지상 망원경으로 한 분광을 우주에서 조사하는 그림으로"
    " 그리면 주장은 맞고 묘사가 틀린 환각이 된다. 확실치 않으면 SCHEMATIC_PRINCIPLE 이다."
    " ★ 이번 건에 그 자격이 있는지는 아래 [원문 확보 수준]이 **단정해서** 알려준다 —"
    " 네가 짐작하지 마라."
    " ■ 사실 주장을 지불하지 않는 컷(전환·CTA)을 stage 의 cut_refs 에 넣을 때는"
    " allow_connective 를 true 로 하라. 그런 컷에는 기전 도해가 붙지 않고 세계 배경만 이어진다."
    " ■ 이어지는 stage 는 continuity_mode 를 CONTINUE_WORLD / MUTATE_STATE / CAMERA_REVEAL /"
    " RETURN_WORLD 중에서 고르고 continuity_from 에 **앞선** stage_id 를 적어라."
    " 같은 인물·같은 물체가 다시 나오는 것은 옳다 — 단 무엇인가 진행돼야 한다."
    " ■ 컷마다 beat 를 선언하라(이 컷이 설명에서 맡은 역할). **어떻게 보여줄지는 코드가**"
    " 근거 깊이와 수치 유무를 보고 정한다 — 네가 정하지 않는다."
    " ■ 수치를 말하는 컷도 시퀀스 안에 그대로 두어라. 세계는 이어지고 정확한 수치는"
    " **코드가 그리는 오버레이**가 말한다 — 세계를 끊고 차트로 나가지 마라."
    " ■ camera_operation 은 **꼭 필요할 때만** HOLD 가 아닌 값을 쓴다. 카메라가 움직이면"
    " 연속성 잠금이 풀려 같은 물체가 다르게 그려질 위험이 커진다(실측). 개체 하나가"
    " 나타나거나 상태만 바뀌는 stage 는 HOLD 다 — 카메라를 움직여야만 보이는 것이 있을 때만"
    " ORBIT·DOLLY_IN·SECTION_DIVE 를 쓴다."
    " ■■ 카메라는 camera_base 토큰과 camera_operation 으로만 선언하라."
    " 각도·렌즈 수치(35 degree, 50mm, 4K)를 문장에 쓰지 마라 — **화면에 글자로 그려진다**"
    " (실측: 세계 프롬프트의 '35 degree isometric camera' 가 영상에 '35°' 로 박혔다)."
    " ■■ 정확한 수치를 물체 개수로 표현하지 마라. 생성 모델은 개수를 지키지 못한다"
    " (실측: 'ten discs' 를 요구했는데 화면엔 4묶음이 나왔다)."
    " 화면은 방향과 관계만 보여준다 — 늘어난다·옮겨간다·쌓인다. '얼마나'는 overlay 가 말한다."
)

# 버전별 추가지시 (명세 §5-2). visual_type 은 정규화에서 강제하므로 여기선 성격만 안내.
VERSION_GUIDANCE: dict[str, str] = {
    "comic": (
        "[버전=만화식 comic] 각 컷을 만화/웹툰 패널 장면으로 만든다."
        " ★화풍 일관성이 최우선: global_style 에 구체적 화풍 앵커를 한 줄로 고정하라"
        " (예: 'flat modern webtoon style, bold clean ink outlines, soft cel shading, muted pastel palette,"
        " consistent character design'). 그리고 모든 컷의 visual_prompt 는 반드시 그 global_style 문구로 시작해"
        " 같은 화풍·같은 인물 디자인·같은 색조를 유지하라(컷마다 화풍이 튀면 안 된다)."
        " visual_prompt 에는 인물·구도·표정·배경을 구체적으로. 서사 흐름(누가·어디서·무엇을)을 살려라."
        + _VIDEO_CLIP_GUIDANCE + TEMPORAL_CONTRACT_GUIDANCE + _ASSET_REUSE_GUIDANCE
    ),
    "photo": (
        "[버전=실사형 photo] 이 버전의 핵심은 화풍이 아니라 **화면이 설명을 하는가**다."
        + PHOTO_NARRATIVE_ARC +
        " 컷마다 반드시 visual_role 을 선언하라 — MECHANISM 또는 REALITY."
        " ■ MECHANISM(3D 도해) — **화면이 설명을 한다.** 단면(cutaway)·절개·분해·조립 순서·"
        " 흐름 추적·전후 비교·크기 대비. 말로 설명하는 원리를 그림이 대신 보여주는 컷이다."
        " 예: 지반을 세로로 잘라 물이 어느 층으로 빠지는지 / 부품이 하나씩 조립되는 순서 /"
        " 전과 후를 나란히 놓은 비교. 12컷 기준 **5~7개**."
        " ■ REALITY(실사) — 실제 현장·제품·규모. 이건 진짜 있는 일이다를 앵커한다."
        " 훅과 마무리, 그리고 도해가 추상적으로 흐를 때 현실로 끌어오는 자리다. 12컷 기준 **3~5개**."
        " ■ MECHANISM 컷은 **먼저 mechanism 구조를 채우고**, visual_prompt 는 그 구조에서"
        " 파생시켜라(구조에 없는 물체를 그리지 마라). subject / components(2개 이상) /"
        " relationship / initial_state / transformation / final_state / highlighted_element."
        " 구조를 못 채우겠으면 그 컷은 MECHANISM 이 아니다 — REALITY 로 바꿔라."
        " ★★ **mechanism 의 필드는 영어로 써라 — 그 문장이 그대로 이미지 프롬프트에 실린다.**"
        " components 는 화면에 실제로 보일 **물체 이름**(a damaged neuron, a healthy neuron,"
        " the visual cortex)이지 entity_id·데이터셋명·개념어가 아니다. 그리고 visual_prompt 는"
        " 그 물체들을 **같은 이름으로** 그려라 — 구조에 있는 물체가 장면에 없으면 차단된다"
        " (photo_mechanism_prompt_detached). 사람이 읽을 한 줄은 mechanism_ko 에 한글로."
        " ★★ [기전 컷의 색 규약 — 세 색뿐이다] amber=설명하는 부분, blue=첫 집단·변화 전,"
        " coral=둘째 집단·변화 후. 두 집단이나 전·후를 나란히 놓는 컷은 visual_prompt 에서"
        " 한쪽을 muted blue, 다른 쪽을 muted coral 로 칠하고(**표면색**이다 — 'the left model is"
        " muted blue' 처럼 써라. 'rendered in'·'render' 는 화풍 어휘라 차단되고, 'glow'·'glowing"
        " light' 는 발광이라 무광 화풍과 싸운다), 그 컷의 overlay_plan 에 legend"
        " (payload.items=[{color, label(한글)}])를 넣어 어느 색이 무엇인지 말하라 —"
        " 기전 시퀀스마다 legend 하나는 있어야 한다. 상태가 **바뀌는** stage(TRANSFORM·GROW·"
        " SHRINK·SPLIT_OFF·MERGE_INTO·DISAPPEAR)의 컷은 코드가 앞 stage 의 그림(전)과 이 stage"
        " 의 그림(후)을 **위·아래로 붙인 한 장**으로 만든다(영상은 의미 변화를 못 만든다). 그"
        " 컷에는 label_pair(payload.top / payload.bottom, 한글 짧게)를 넣어 위·아래가 무엇인지"
        " 말하라. **한 컷에 두 상태를 다 그리려 하지 마라** — 이 컷의 visual_prompt 는 '후'만 그린다."
        " ★ 모든 주제에 억지로 도해를 만들지 마라. 실제로 시각화 가능한 원리·구조·전후 변화가"
        " 있는 컷에만 쓴다."
        " ★★ **도해할 물리적 대상이 없는 문장**(메타분석·통계 재분석·연구 설계 언급·'효과가"
        " 일관적이었다' 류)은 MECHANISM 이 **아니다**. 그런 칸은 REALITY 로 내고, 화면은"
        " 그 연구가 실제로 벌어진 현실을 앵커하라 — 데이터를 들여다보는 연구자, 쌓인 논문,"
        " 실험실 책상. **추상 3D 로 도망가지 마라.**"
        " ★★ [연결 문장 처방] 물리적 주어가 없는 **짧은 연결·평가·부정 문장**"
        " ('…에 직접적인 영향을 미쳤습니다', '이건 그냥 점수놀이가 아니었습니다', '결과는"
        " 놀라웠습니다')에는 **새 세계를 만들지 마라.** 그릴 것이 없으니 모델은 글자나"
        " 계기판으로 화면을 채우게 되는데, 그건 화면이 아니라 자막이다."
        " 실측(2026-09-03): 3초짜리 연결 컷 둘이 각각"
        " \"a dynamic text animation of the word 'IMPACT'\" 와"
        " \"a score counter dropping to zero\" 로 나왔고 **둘 다 폐기됐다.**"
        " ▸ 대신 **앞 컷의 세계를 이어라** — 같은 장면·같은 개체를 유지하고 카메라만"
        " 움직이거나(밀어들어가기·빼기) 시선을 옮긴다. base_asset_ref 로 앞 컷을 가리키고"
        " state_change 에 무엇이 달라지는지 적는다. 이것이 시퀀스가 존재하는 이유다."
        " ▸ 그것도 애매하면 **그 연구가 실제로 벌어진 자리**로 돌아가라 — 참가자들이 앉아"
        " 있는 실험실, 화면 앞의 연구자, 쌓인 결과물. 문장이 추상적일수록 화면은 구체여야 한다."
        " ▸ 연결 문장에 **영상 클립을 배정하지 마라.** 움직임이 이해에 기여하지 않는 자리이고,"
        " 거기 쓴 클립 값은 기전 컷에서 빠진다."
        " ■ 다만 이 규칙을 과하게 읽지 마라(실측 2026-08-29: 13컷에 도해가 3개뿐이었다)."
        " '물리적 대상'은 기계 부품만이 아니다. **절차·집단·비교도 물리적으로 배치하면 도해가"
        " 된다** — 실제로 그렇게 벌어진 일이기 때문이다. 예:"
        " ▸ 이중맹검 설계 = 똑같이 생긴 두 무리를 나란히 놓고 한쪽에만 진짜 약병이 간다."
        " ▸ 통합 분석 = 두 연구의 참가자 무리가 한자리로 합쳐져 더 큰 하나가 된다."
        " ▸ 범위 한정 = 사람들이 늘어선 줄에서 해당 집단만 남고 나머지는 물러난다."
        " ▸ 전후 비교 = 같은 배치에서 한쪽의 양이 눈에 띄게 늘어난다."
        " 이런 컷은 **셀 수 있는 실물**(사람·약병·동전·서류 묶음)을 배치해 그린다."
        " ★ 사람을 그릴 때는 **실제 사람**이다 — 'abstract/minimalist humanoid figures' 처럼"
        " 추상 형상으로 대체하면 그 컷은 폐기된다. 손·얼굴·옷이 있는 진짜 사람을 그려라."
        " 금지(그대로 쓰면 폐기된다): abstract, conceptual, data visualization, data points,"
        " clusters/clouds merging, glowing cube/orb/blocks, floating particles, aura,"
        " symbolic representation. 이런 화면은 아무것도 설명하지 않는다."
        " ★★ **아이콘 인포그래픽도 같은 금지다**(2026-09-03 실측). 금지: icon(s),"
        " 'personality icons', pictogram, symbol connecting with a line, gauge, meter bar,"
        " bar graph rising, 'clean digital interface', UI card, dashboard-like panel."
        " 실측: 추상 주제(성격·협업 품질)를 받자 모델이 글자를 피한 대신"
        " \"personality icons connecting with a dynamic line, leading to a rising 'ad quality'"
        " gauge, clean digital interface\" 로 도망갔다 — **글자만 안 썼을 뿐 같은 회피**다."
        " 이 버전은 실사(REALITY)와 3D 도해(MECHANISM) 둘뿐이고 **인포그래픽은 셋째 선택지가"
        " 아니다.** 아이콘을 그리고 싶어지면 그 컷은 MECHANISM 이 아니라 REALITY 다 —"
        " 사람·장비·결과물이 있는 실제 장면으로 내려라."
        " ■ 도해 컷의 visual_prompt 는 **무엇을 잘라서 무엇을 보여주는지**를 적어라."
        " 관련 있는 장면을 적으면 그 컷은 배경이 된다 — 이 버전이 실패하는 유일한 방식이다."
        " 나쁜 예: a modern factory interior. 좋은 예: cutaway cross-section of a battery cell"
        " showing the separator layer between anode and cathode, one layer highlighted."
        " ■ 화풍은 코드가 역할에 따라 붙인다. visual_prompt 에 화풍 형용사를 쓰지 마라 —"
        " **무엇을 보여줄지**만 적는다. 네가 쓰면 코드가 붙이는 화풍과 충돌하고,"
        " 실측 4회에서 **매번 네 쪽이 이겼다**(그래서 원하지 않은 그림이 나왔다)."
        " 삭제 대상(그대로 쓰면 차단된다): stylized, photorealistic, 3D render, CGI,"
        " illustration, painterly, cel shading, line art, vector art, anime, cartoon,"
        " low poly, cinematic still — 그리고 렌즈 어휘 depth of field, bokeh, macro detail,"
        " lens flare, film grain, motion blur, blurred, out of focus."
        " ★ 이 규칙은 `world.style`·`world.lighting`·`world.background` 에도 **똑같이** 적용된다."
        " ■■ **장소가 없는 주제(세포·분자·힘)의 세계는 '스튜디오 탁자'로 적어라.**"
        " 실측(2026-09-07): 실험실 세계는 장소를 적어 원하는 화면이 나왔고, 세포 세계는"
        " 'Microscopic view of a cellular environment' 라고 적어 **교과서 삽화**가 나왔다."
        " 세포에는 실물 사진이 없으니 모델이 배운 대로 삽화를 그린다. 그래서 대상을"
        " **물리적 모형**으로 내려라 — 'A plain studio tabletop holding a cutaway teaching"
        " model of an animal cell, with small painted resin pieces laid beside it'."
        " 그러면 모델이 삽화가 아니라 **탁자 위의 물건**을 떠올린다(실측에서 아웃라인이 사라졌다)."
        " 분자·입자는 'resin piece'·'painted block'·'machined part' 처럼 **만질 수 있는 것**으로 적어라."
        " ■■ **연구 조건(대상·계통·연령·기간)은 한 컷으로 합쳐라.** 각각 독립 컷으로 쪼개면 화면이 통째로 연구 대상 사진이 되고, 시청자는 원리를 만나기 전에 떠난다."
        " 실측 사고: 그 세 문장이 18초를 먹어 전반부 36초의 절반이 됐다."
        " ■■ **원리 설명(evidence_role='mechanism')을 앞으로 당겨라.** 결과와 숫자를 말한 직후가 자리다. 총량이 충분해도 뒤로 몰리면 전반부가 통째로 연구 소개가 된다 —"
        " 실측: 기전 총량 28% 인데 첫 기전이 51% 지점이라 전반부에 원리가 0개였다."
        " 소재가 기전을 대지 않으면 억지로 만들지 마라(지어내는 것이 더 나쁘다)."
        " ■ **evidence_role 은 정직하게 적어라.** 그 컷이 가리키는 claim 이 실제로 그 역할을 지불해야 한다 — 라벨만 바꾸면 코드가 잡는다(photo_role_claim_mismatch)."
        " ■■ **차이는 판정이 아니라 물체로 적어라.** 생성 모델은 '건강함'·'개선'을 그릴 수 없다."
        " 실측 사고: '더 건강하고 활동적인 세포로 변한다'고 썼더니 두 세포가 **똑같이** 나왔다 —"
        " 그 컷의 내용 전체가 비교였는데 화면에 비교가 없었다."
        " 금지: healthier, more active, improved, better, enhanced, more pronounced,"
        " vibrant, glowing, revitalized, superior."
        " 대신 **눈으로 셀 수 있는 차이**를 적어라 — 형태·색·자세·개수·거리·높이·기울기."
        " 나쁨: 'the right cell becomes healthier and more active'."
        " 좋음: 'the right model is assembled from whole, tightly packed parts;"
        " the left one has gaps and two pieces lying detached beside it'."
        " ■ 컷 호흡: 한 컷 = 나레이션 한 문장(2~4초). 문장이 끝나는 지점에서 화면 전환."
        " 정확한 컷 수는 아래 [컷 수]가 목표 길이에서 역산해 알려준다 — 그 범위를 지켜라."
        " ■ 화면의 글자·숫자는 전부 overlay_plan(코드 그래픽)이 담당한다."
        " visual_prompt 에 차트·그래프·대시보드·숫자·라벨을 절대 요구하지 마라 —"
        " 생성 모델이 그린 숫자는 근거 없는 가짜다."
        " ★★ **지도·지구본도 그리지 마라.** 생성 모델은 나라 경계를 틀리고 지명을 지어내며,"
        " '서구 지역만'이라고 해도 전 세계에 표시를 찍는다(실측 2026-09-14). 지역·집단의"
        " 편중은 **물체의 양**으로 보여줘라(시료관 선반에서 한 색이 대부분인 장면 등)."
        " ★★ **라벨이 필요하다고 느껴지면 그건 오버레이가 할 일이다.** 금지만 있고 대안이"
        " 없으면 너는 결국 이미지에 글자를 굽게 된다. 아래로 옮겨라:"
        " 두 그룹·두 색이 무엇인지 → overlay_plan 의 legend / 위·아래 분할 화면의 전후 → label_pair /"
        " 표본·기간·대상 → scope_tag / 수치 → number_punch / 출처 → source_card."
        " ■■ **[키워드 카드] 컷마다 낱말 하나를 붙여라.** 화면 속 물체에 이름표를 다는 것이다:"
        " `type: keyword`, text 는 **대문자 영어 낱말 하나 또는 수치 하나**"
        f" (MYOGLOBIN · 75% WATER · 30-60 MIN · 1984). {config.OVERLAY_KEYWORD_MAX_WORDS}낱말·"
        f"{config.OVERLAY_KEYWORD_MAX_CHARS}자를 넘기면 그건 카드가 아니라 자막이다."
        " ★ 나레이션을 옮겨 적지 마라 — 귀로 듣는 말을 눈으로 또 읽히면 화면만 복잡해진다."
        " 나레이션이 '근육의 대부분은 물'이라 말하면 카드는 `75% WATER` 다(같은 문장이 아니다)."
        " ■■ **[지시 화살표] 설명 대상을 직접 찍어라.** `type: pointer`, payload.at 에 구역 이름을"
        f" 1~3개: {_POINTER_ZONES_HELP}. **좌표(픽셀)를 적지 마라** — 너는 그 그림을 본 적이 없다."
        " 네가 아는 것은 네가 짠 구도뿐이다('왼쪽이 청각인'이면 left)."
        " 색·글자로 가리키는 것보다 화살표가 세다 — 원리를 설명하는 컷에는 되도록 붙여라."
    " ★★ **훅 컷도 예외가 아니다**(실측: 두 번 연속 여기서 막혔다). 컷1 이 숫자를 말하면"
    " (\"수명을 92일 연장\") 그 컷의 overlay_plan 에도 number_punch 를 넣어라 —"
    " 숫자를 말하는 **모든** 컷이 대상이고, 첫 컷이 가장 자주 빠진다."
        " ■■ **대상에 따옴표로 이름을 붙이지 마라** — 그 이름이 그림에 글자로 그려진다."
        " 실측 사고(2026-09-07): `the left model represents 'Calorie Restriction' and the"
        " right represents 'Semaglutide' … 'Exploratory Behavior', 'Spatial Memory',"
        " 'Glucose Control'` 라고 적었더니 **다섯 개가 전부 영어 글자로 화면에 박혔다.**"
        " 글자를 그려 달라고 한 적이 없어도 그렇게 된다 — 이름을 주면 모델은 라벨로 읽는다."
        " 이미지는 한국어판·영어판이 **공유**하므로 영어가 구워지면 언어 공유가 통째로 깨진다."
        " 두 대상은 **생김새로** 구별되게 적어라(왼쪽은 낮고 평평한 접시, 오른쪽은 높고 칸이"
        " 나뉜 접시). 어느 쪽이 무엇인지는 overlay_plan 이 말한다."
        " ■■ **세계를 여는 컷(continuity_mode=NEW_WORLD 인 stage 의 첫 컷)은 그 세계를"
        " 실제로 그려야 한다.** 그 컷의 그림이 곧 세계이고, 뒤 stage 들은 그것을 참조로"
        " 물려받는다. 여는 컷이 딴 것을 그리면 world 선언이 죽고 오해가 끝까지 간다 —"
        " 실측: world 가 '세포 단면 모형'인데 여는 컷이 벤 다이어그램을 그려 세포가 사라졌다."
        " 여는 컷의 visual_prompt 에 world 가 말한 장소와 물건을 그대로 적어라."
        " ■ 그러면 이미지에는 **라벨 없이 차이만** 그린다. 예:"
        " 나쁨 — 'split screen, left labeled Placebo, right labeled Oxytocin'."
        " 좋음 — 'two identical figures facing each other; the left passes a single coin,"
        " the right passes a tall stack of coins; identical lighting and framing so only the"
        " amount differs'. 어느 쪽이 무엇인지는 오버레이 카드가 말한다."
        " ■ 훅 문형: 반전 평서문 + 숫자 하나(…인 줄 알았는데 사실은 …였습니다)."
        " 금지: 증권 전광판·돈다발·로켓·상승 화살표 클리셰·가짜 로고·정장 인물 악수."
        " ■ [논문 라인 소재] MECHANISM = 분자·세포·장치가 작동하는 원리, 실험 전후 비교,"
        " 투여 경로, 구조 단면. REALITY = 실험실·장비·임상 현장·시료."
        + _SEQUENCE_GUIDANCE + _PHOTO_VIDEO_CLIP_GUIDANCE
        + SCREEN_GRAPHIC_BAN_GUIDANCE
        + TEMPORAL_CONTRACT_GUIDANCE + _ASSET_REUSE_GUIDANCE
    ),
    "image_sequence": (
        "[버전=이미지 나열식 image_sequence] 각 컷의 핵심을 대표하는 사실적/일러스트 이미지 1장을 지정한다."
        " visual_prompt 는 주제를 직접 표현하는 리치 프롬프트. 강조가 필요한 컷엔 effects(ken_burns/텍스트오버레이/highlight)를"
        " 적극 지정하라. global_style 은 톤 앵커(예: 'clean editorial illustration, cohesive palette')."
        + _VIDEO_CLIP_GUIDANCE + TEMPORAL_CONTRACT_GUIDANCE + _ASSET_REUSE_GUIDANCE
    ),
}


def _mode_guidance(content_plan: dict[str, Any] | None, version_type: str = "",
                   cut_count: int = 0) -> str:
    """선택된 모드의 골격·길이·비용 예산만 주입한다.

    ★4개 모드를 전부 나열하면 시스템 프롬프트가 비대해져 지금 작동 중인 훅·리텐션 규칙이 희석된다.
    지시서 단계에서는 모드가 이미 정해져 있으므로 그것 하나만 넣으면 된다.

    ★ 영상 예산은 **버전 상향을 반영한다**(2026-08-21). 이것이 상한의 **네 번째 층**이었다 —
      enforce/cap/preflight 세 겹을 버전 인식으로 고쳤는데도 실사형 지시서가 영상 컷 0개로
      나왔다. 범인은 코드가 아니라 이 문장이었다: 실사형 계약이 바로 위에서 "6~8개를 video 로
      지정하라"고 하는데, 여기가 "I2V 클립 최대 2개 … 넘으면 안 되는 선"이라고 못을 박아서
      모델이 보수적으로 0개를 골랐다(실측: 9컷 전부 still, motion_value=high 인 컷 3개 포함).
    """
    plan = content_plan if isinstance(content_plan, dict) else {}
    mode = str(plan.get("selected_mode") or "").strip()
    if mode not in config.CONTENT_MODE_DURATION:
        mode = config.DEFAULT_CONTENT_MODE
    lo, hi = content_mode.duration_range(mode)
    budget = content_mode.resolve_cost_plan(mode)
    # 버전 상향(실사형)이 있으면 그것이 모드 상한을 이긴다 — 코드가 강제하는 값과 같은 숫자를
    # 모델에게 보여줘야 한다. 다르면 둘 중 하나는 반드시 거짓말이 된다.
    v_clips = config.video_clips_max(version_type, budget["max_video_clips"])
    v_sec, _v_cost = config.video_budget_for(version_type, budget)
    # ★ 에셋 상한도 버전을 본다(2026-08-29). 만화식 전제의 고정값(standard=6)이 11컷 실사형에
    #   걸려 5컷이 강제 복제됐다. 여기 문구와 compute_cost_plan 의 검사는 **같은 함수**를
    #   불러야 한다 — 다르면 둘 중 하나가 반드시 거짓말이 된다(영상 상한에서 이미 겪었다).
    u_assets = config.unique_assets_max(version_type, budget["max_unique_assets"], cut_count)
    units = ", ".join(plan.get("essential_evidence_units") or []) or "(미지정)"
    parts = [
        f"\n\n[모드 골격] content_mode={mode} · 목표 {lo}~{hi}초 · 필수 근거 {units}",
        f"\n{content_mode.MODE_SKELETONS.get(mode, '')}",
        f"\n[비용 예산] 새로 만드는 고유 에셋 최대 {u_assets}개 ·"
        f" I2V 클립 최대 {v_clips}개(총 {v_sec}초)"
        f" · 코드 시각화 권장 {budget['preferred_code_viz_count']}개."
        " 이 상한은 '채워야 하는 목표'가 아니라 '넘으면 안 되는 선'이다."
        " (버전 지침이 영상 컷 수를 따로 정했다면 그 지침을 따르되 이 상한 안에서 정하라.)",
    ]
    # ★ 컷 수는 **게이트와 같은 함수**로 역산해 보여준다(2026-08-31).
    #   종전에는 프롬프트가 "40~50초면 10~14컷"으로 고정돼 있는데 게이트는
    #   `total_estimated_sec` 에서 매번 역산했다. 실측: 모델이 61초·11컷을 냈고 게이트
    #   하한은 12였다 → `photo_cut_count_low:11<12` 로 승인이 막혔다. 모델은 자기가 몇 컷을
    #   내야 하는지 **알 수가 없었다**. 영상 상한·에셋 상한에서 이미 두 번 겪은
    #   "프롬프트와 코드가 다른 숫자를 말한다"의 세 번째다.
    if version_type == "photo":
        c_lo, _ = photo_contract.target_cut_range(lo)
        _, c_hi = photo_contract.target_cut_range(hi)
        parts.append(
            f"\n[컷 수] 목표 {lo}~{hi}초이므로 컷은 **{c_lo}~{c_hi}개**다."
            f" ★ 검사는 네가 적은 estimated_sec 합계로 한다:"
            f" **컷 수 ≥ (전체 초수 ÷ {config.PHOTO_CUT_SEC_MAX})**, 미달이면 승인이 막힌다."
            f" 즉 길게 만들수록 컷도 같이 늘려야 한다 — 총 60초를 적었다면 컷은 12개 이상이다."
            f" 어느 컷도 estimated_sec 를 {config.PHOTO_CUT_SEC_MAX}초 넘게 잡지 마라"
            f" (한 컷에 두 문장을 담은 것이고, 그러면 컷 수가 모자라 막힌다).")
        # ★ 기전 컷 수도 **게이트와 같은 함수**로 역산해 보여준다(2026-09-04).
        #   위 [컷 수] 가 겪은 것과 같은 함정을 미리 막는다 — 프롬프트가 고정값을 말하고
        #   게이트가 길이에서 역산하면 모델은 자기가 몇 개를 내야 하는지 알 수가 없다.
        #   운영자 지시로 이 수는 길이에 따라 유동이다(photo_contract.min_mechanism_cuts).
        m_lo = photo_contract.min_mechanism_cuts(lo)
        m_hi = photo_contract.min_mechanism_cuts(hi)
        m_txt = f"{m_lo}개" if m_lo == m_hi else f"{m_lo}~{m_hi}개(길이에 비례)"
        parts.append(
            f"\n[기전 컷 수] evidence_role='mechanism' 컷은 **{m_txt}** 이상이다."
            f" ★ 검사도 네가 적은 estimated_sec 합계로 한다:"
            f" **기전 컷 수 ≥ round(전체 초수 ÷ {config.PHOTO_MECHANISM_SEC_PER_CUT})**"
            f" (하한 {config.PHOTO_MIN_MECHANISM_CUTS_FLOOR}, 상한"
            f" {config.PHOTO_MIN_MECHANISM_CUTS_CAP}). 길게 만들수록 원리도 같이 늘려야 한다."
            " 이 간격은 발행 벤치마크(105초에 기전 3회 — 원인·재정의·해법)에서 실측한 값이다."
            " ★ 소스에 기전이 정말 없으면(순수 상관·메타분석) **지어내지 마라** —"
            " 연구진의 해석을 그 자리에 놓고 해석임을 나레이션에 밝혀라.")
    if plan.get("duration_reason"):
        parts.append(f"\n[길이 근거] {plan['duration_reason']}")
    if plan.get("primary_claim_id"):
        parts.append(f"\n[핵심 주장] {plan['primary_claim_id']} — 이 영상의 결론은 이 주장 하나다."
                     " 독립적인 두 번째 결론을 나열하지 마라.")
    # ★ 보조 주장까지 반드시 적어 준다. 예전에는 "핵심 주장 하나만 지불한다"만 주면서 승인 게이트는
    #   primary + supporting 전부가 컷에 실렸는지를 봤다 — 프롬프트와 게이트가 서로 반대라
    #   모델이 지시대로 할수록 missing_required_claims 로 차단됐다(2026-08-05 실측: C04 누락).
    required = [x for x in [plan.get("primary_claim_id"), *(plan.get("supporting_claim_ids") or [])] if x]
    if required:
        parts.append(f"\n[반드시 지불할 주장] {', '.join(required)} —"
                     " 각 주장을 최소 한 컷의 claim_ids 에 넣어라. 보조 주장은 새 결론이 아니라"
                     " 핵심 주장을 떠받치는 근거(범위·방법·크기·한계)로 쓴다."
                     " 하나라도 빠지면 승인이 차단된다.")
    return "".join(parts)


# ★★ 원문 확보 수준 → 표현 수준 제약. **게이트와 같은 함수**(visual_router.source_depth_of)로
#   판정한다(2026-08-31).
#
#   실측: 재생성본이 `vseq_literal_without_source:SEQ2/S4` 로 막혔다. 게이트는
#   `fact_sheet.source_provenance.source_depth` 를 보고 LITERAL_OBSERVATION 을 통째로
#   금지하는데, **모델은 자기가 어느 수준의 원문을 받았는지 프롬프트에서 들은 적이 없었다.**
#   지침은 "확실치 않으면 SCHEMATIC_PRINCIPLE" 이라고만 했고 — 모델 입장에서는 초록만 받은
#   것인지 전문을 받은 것인지 구분할 방법이 없으니 "확실하다"고 판단할 수도 있다.
#
#   컷 수 상한·영상 상한·에셋 상한에 이은 **네 번째** "프롬프트와 코드가 다른 것을 안다" 다.
#   처방은 매번 같다: 검사하는 값을 검사하는 함수로 뽑아 프롬프트에 넣는다.
DEPTH_LABELS: dict[str, str] = {
    "full_body": "원문 전문",
    "partial_body": "원문 일부",
    "abstract_only": "초록만",
    "parse_failed": "원문 파싱 실패(초록 수준)",
    "none": "원문 없음(초록 수준)",
}


# 소재가 원리를 대지 못할 때의 **대체 판형**(운영자 승인 2026-09-04, 선택지 B).
#
# ★ 왜 필요한가: 선별에 원리 축을 넣어도(선택지 A) 기전 없는 논문은 계속 들어온다 —
#   그런 논문이 나쁜 것도 아니다. 대규모 무작위 실험이 "무엇이 관측됐는지"만 정확히
#   보고하는 것은 정상적인 과학이다. 문제는 **그걸로 원리 영상을 만들려 한 것**이다.
#   실측: 고정 대상 논문 전문 46,952자에 why 0회인데 우리는 3D 도해를 요구하고 있었다.
#
# ★ 그래서 없는 원리를 짜내는 대신 **관측을 또렷하게 보여주는 판형**으로 보낸다.
#   벤치마크가 원리 구간 말고도 잘한 것이 이것이다 — 손이 물을 뜨고, 유리병을 비추고,
#   계기판 바늘이 17.4를 가리킨다. 원리가 아니라 **증거를 실물로 만든 화면**이다.
NO_MECHANISM_PLAYBOOK: str = (
    " ★★★ [이 논문은 '왜'를 말하지 않는다 — 판형을 바꿔라] Fact Sheet 에 기전·연구진 해석"
    " 주장이 없다. **원리 도해를 억지로 만들지 마라 — 그건 지어내는 것이다.**"
    " 대신 **관측을 실물로 만드는 판형**으로 간다:"
    "   ① 조건 대비 — 무엇과 무엇을 비교했는지를 나란히 놓는다(좌우 분할·전후)."
    "   ② 규모 실감 — 표본·기간·건수를 손에 잡히는 크기로 보여준다"
    " (7,266개 광고 = 책상을 덮은 인쇄물 더미, 1,258명 = 가득 찬 강당)."
    "   ③ 현장 앵커 — 그 연구가 실제로 벌어진 장소·사람·도구를 보여준다."
    " ★ MECHANISM 도해 컷은 **줄이고** REALITY 를 늘려라. 도해를 쓸 자리는 '원리'가 아니라"
    " **'무엇을 어떻게 쟀는가'(실험 설계·비교 구조)** 다 — 그건 논문이 실제로 말하는 것이다."
    " ★ 나레이션도 마찬가지다. '왜냐하면'을 지어내지 말고 **관측된 사실을 또렷하게** 말하라."
    " 저자 해석이 있으면 해석임을 밝혀 인용하라('연구진은 …로 봅니다')."
)


def source_depth_guidance(fact_sheet: dict[str, Any] | None) -> str:
    """이번 건의 원문 확보 수준과 그것이 만드는 표현 제약을 단정한다."""
    depth = visual_router.source_depth_of(fact_sheet)
    label = DEPTH_LABELS.get(depth, depth)
    if depth in config.DEPTH_LITERAL_FORBIDDEN:
        return (
            f"\n[원문 확보 수준] 이번 건은 **{label}**({depth})이다."
            " ★★ 따라서 어느 stage 에서도 representation_mode 를 **LITERAL_OBSERVATION 으로"
            " 쓰지 마라 — 쓰면 승인이 차단된다.** 초록은 \"무엇을 알아냈는가\"를 말하지"
            " \"어떻게 봤는가\"를 말하지 않으므로, 실제 관측 장면이라고 주장할 자격이 없다."
            " SCHEMATIC_PRINCIPLE(원리를 도식으로) 또는 METAPHOR 를 써라."
            " ★ 화면이 달라지는 것은 아니다 — 같은 그림을 그리되 **실제 관측이라고 주장하지"
            " 않는 것**이다. 그래서 구체적인 장비·절차(주사기·바이알·이중맹검 문구 등)도"
            " 원문이 지불하지 않으면 화면에 넣지 마라.")
    return (
        f"\n[원문 확보 수준] 이번 건은 **{label}**({depth})이다."
        " 원문이 관측·측정 방식을 말하는 대목에 한해 representation_mode 를"
        " LITERAL_OBSERVATION 으로 쓸 수 있다. 원문이 그 방식을 말하지 않는 stage 는"
        " 그대로 SCHEMATIC_PRINCIPLE 이다 — 확보 수준이 깊다고 전부 실측 장면이 되지 않는다.")


def directive_user_prompt(draft_row: dict[str, Any], version_type: str) -> str:
    """지시서 생성 입력: 버전 지시 + 모드 골격 + 대본 + Fact Sheet + 기존 장면들."""
    fact_sheet = draft_row.get("fact_sheet") or {}
    script_md = draft_row.get("script_md") or ""
    scenes = draft_row.get("video_prompts") or []
    # ★★ 실사형에는 초안 장면의 **시각 제안 필드를 빼고** 넘긴다(2026-09-02 실측).
    #   Moon Impactor 실제 초안으로 재생성하자 화면 그래픽 위반 3건이 남았는데, 세 문장이
    #   전부 초안 `video_prompts[].image_prompt/video_prompt` 에 **그대로** 있었다 —
    #   "a graphic overlay appears indicating a crater diameter of '~40m'"(8/31 G2·G4 를
    #   망친 바로 그 문장), "digital timer overlay … displays", "infographic overlay of a
    #   light spectrum graph appears". 아래 문구가 "흐름·근거를 최대한 계승 … 통째로 버리지
    #   말 것"이라 모델은 금지문과 계승 지시 사이에서 **계승을 골랐다.** 금지 어휘를 더
    #   쌓아도 못 이긴다 — 입력에서 빼는 것이 구조적 답이다.
    #   초안의 시각 제안은 만화식 전제로 쓰인 것이라("한국 웹툰 스타일…") 실사형에는 어차피
    #   맞지 않는다. 남기는 것은 나레이션·근거·역할·길이 — 프롬프트가 스스로 "나레이션
    #   초안"이라 부르는 그것이다. 만화식·나열식은 종전대로 전부 넘긴다.
    if version_type == "photo":
        scenes = [{k: v for k, v in s.items() if k not in _DRAFT_SCENE_VISUAL_FIELDS}
                  for s in scenes if isinstance(s, dict)]
    plan = (draft_row.get("video_flow") or {}).get("content_plan")
    guidance = VERSION_GUIDANCE.get(version_type, VERSION_GUIDANCE[config.DEFAULT_VERSION])
    # ★ 컷 골격(리뷰 §6). 실사형은 컷 수·리듬이 품질을 좌우하는데, 예전에는 LLM 이 대본 씬
    #   개수를 그대로 물려받아 칸을 스스로 줄였다(실측 40초 8컷). 코드가 문장 경계로 칸을
    #   먼저 만들고 LLM 은 그 칸을 시각 표현으로 채운다.
    skeleton = ""
    cut_count = 0
    if config.CUT_SKELETON_ENABLED and version_type == "photo":
        bones = cut_skeleton.build(script_md, version_type=version_type)
        cut_count = len(bones)
        skeleton = cut_skeleton.skeleton_block(bones)
    # ★ 표현 수준 제약은 **시퀀스를 쓰는 버전에만** 붙인다 — 시퀀스가 없으면
    #   representation_mode 자체가 없고, 없는 필드를 두고 설교하면 프롬프트만 희석된다.
    depth_block = source_depth_guidance(fact_sheet) if version_type == "photo" else ""
    # ★ 소재가 원리를 대지 못하면 **판형 자체를 바꾼다**(선택지 B). 게이트가 요구를 낮추는
    #   것만으로는 부족하다 — 프롬프트가 여전히 "3D 도해 5~7개"를 요구하고 있으면
    #   모델은 원리 없는 도해를 만든다(그게 "의미 없는 화면"의 정체였다).
    if version_type == "photo" and not photo_contract.source_supplies_mechanism(fact_sheet):
        depth_block += NO_MECHANISM_PLAYBOOK
    return (
        f"{guidance}{_mode_guidance(plan, version_type, cut_count)}{depth_block}{skeleton}\n\n"
        f"대본(script_md):\n{script_md}\n\n"
        f"Fact Sheet:\n{json.dumps(fact_sheet, ensure_ascii=False, indent=2)}\n\n"
        f"기존 장면들(scenes — 나레이션 초안이다. 흐름·근거를 최대한 계승하되, 위 [연출·서사 규칙]에 맞게\n"
        f"다듬어라. 문맥이 끊기거나 한 컷에 메시지가 여러 개면 쪼개고 이어라. 통째로 버리지 말 것):\n"
        f"{json.dumps(scenes, ensure_ascii=False, indent=2)}"
    )


# ─────────────────────────────────────────────────────────────
# 정규화 (★ 신뢰민감: enum 강제 · 근거 보존 · duration 클램프)
# ─────────────────────────────────────────────────────────────
def _as_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return config.CUT_MIN_SEC


def _clamp_sec(v: Any, scene_kind: str | None = None, motion_source: str | None = None) -> int:
    """컷 길이 클램프. 상한은 컷 종류에 따라 다르다(수정명세 §10-2):
    기본 10초 / data_viz 12초 / 영상(I2V) 컷 8초(clip_fit 보정 범위 보호)."""
    cap = content_mode.cut_max_sec(scene_kind, motion_source)
    return max(config.CUT_MIN_SEC, min(cap, _as_int(v)))


def sanitize_effects(effects: Any) -> list[str]:
    """허용 토큰(정확 일치 또는 허용 접두사)만 남긴다. 밖의 토큰은 드롭+로그."""
    if isinstance(effects, str):
        effects = [effects]
    if not isinstance(effects, list):
        return []
    out: list[str] = []
    for e in effects:
        tok = str(e).strip()
        if not tok:
            continue
        if tok in config.ALLOWED_EFFECTS or tok.startswith(config.ALLOWED_EFFECT_PREFIXES):
            out.append(tok)
        else:
            log.warning("지시서: 미허용 effect 드롭: %s", tok)
    return out


def sanitize_transition(t: Any) -> str:
    tok = str(t or "").strip()
    if tok in config.ALLOWED_TRANSITIONS:
        return tok
    if tok:
        log.warning("지시서: 미허용 transition '%s' → '%s'", tok, config.DEFAULT_TRANSITION)
    return config.DEFAULT_TRANSITION


def _str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v] if v else []
    if not isinstance(v, list):
        return []
    return [str(x) for x in v]


def _step_no(v: Any) -> int:
    """논증 단계 번호. 숫자가 아니거나 음수면 0(=해당 없음).

    ★ 0 과 "잘못된 값"을 굳이 나누지 않는다 — 실재 여부는 `equity_visual.assign_cuts`
      가 시퀀스와 대조해 판정한다. 여기서는 타입만 지킨다.
    """
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def sanitize_scene_kind(v: Any, version_type: str) -> str:
    """③ scene_kind 강제: 허용 enum 밖이면 버전 기본값으로 폴백(규격 v2 §2.2)."""
    tok = str(v or "").strip()
    if tok in config.SCENE_KINDS:
        return tok
    if tok:
        log.warning("지시서: 미허용 scene_kind '%s' → 버전 기본값", tok)
    return config.VERSION_DEFAULT_SCENE_KIND.get(version_type, config.SCENE_KINDS[0])


def sanitize_motion_source(v: Any, version_type: str) -> str:
    """컷을 영상(I2V)으로 낼지(video) 스틸로 낼지(still). 모든 제공 버전이 영상 컷을 지원한다.

    허용값: 'video' | 'still'. 'video' 가 아니면 'still'.

    ★★ video-first(v2 Phase F): `VIDEO_FIRST_VERSIONS` 에 든 버전은 **기본이 영상**이다.
      단 목표는 "모든 컷의 video 플래그"가 아니라 **시청자가 정적이라고 느끼는 순간이
      없는 것**이다(코덱스 리뷰 §10) — 그래서 전부-영상이 아니라 video-first 다.
      브릿지·CTA 는 여전히 스틸로 둘 수 있고, 켄번스가 그 컷을 움직인다.
      모델이 명시적으로 still 이라고 적었으면 그 판단을 존중한다 — 여기서 뒤집으면
      Veo 를 CTA 에까지 쓰게 되고 리뷰가 경고한 "쓸모없는 생성물"이 늘어난다.
    """
    tok = str(v or "").strip().lower()
    if tok in ("video", "still"):
        return tok
    # 모델이 아무 말도 안 한 컷만 기본값이 갈린다.
    return "video" if version_type in config.VIDEO_FIRST_VERSIONS else "still"


def sanitize_motion_value(v: Any) -> str:
    tok = str(v or "").strip().lower()
    return tok if tok in config.MOTION_VALUES else config.DEFAULT_MOTION_VALUE


def sanitize_mechanism(value: Any) -> dict[str, Any]:
    """도해 구조 정규화(§5). 형태만 보장하고 **내용 판정은 photo_contract 가 한다**.

    ★ 빈 dict 를 돌려주지 않고 키를 채운 dict 를 돌려준다 — 화면·게이트가 `.get()` 분기를
      만들지 않게. 값이 비었는지는 photo_contract.mechanism_spec_complete 가 본다.
    """
    src = value if isinstance(value, dict) else {}
    comps = src.get("components")
    if isinstance(comps, str):
        comps = [comps]
    claim_ids = src.get("claim_ids")
    if isinstance(claim_ids, str):
        claim_ids = [claim_ids]
    return {
        "subject": str(src.get("subject") or "").strip(),
        "components": [str(x).strip() for x in (comps or []) if str(x).strip()][:6],
        "relationship": str(src.get("relationship") or "").strip(),
        "initial_state": str(src.get("initial_state") or "").strip(),
        "transformation": str(src.get("transformation") or "").strip(),
        "final_state": str(src.get("final_state") or "").strip(),
        "highlighted_element": str(src.get("highlighted_element") or "").strip(),
        "claim_ids": [str(x).strip() for x in (claim_ids or []) if str(x).strip()][:6],
    }


def sanitize_visual_role(v: Any) -> str:
    """컷 화면 역할(MECHANISM|REALITY) 화이트리스트. 모르는 값·빈값은 빈 문자열.

    ★ 빈값을 REALITY 로 채우지 않는다. 역할을 **선언하지 않은** 컷(만화식·웹툰·설명판형과
      레거시 지시서)은 예전 경로를 그대로 타야 한다 — 기본값을 넣으면 그 버전들의 화풍이
      조용히 바뀐다.
    """
    tok = str(v or "").strip().upper()
    return tok if tok in config.VISUAL_ROLES else ""


def sanitize_asset_strategy(v: Any) -> str:
    tok = str(v or "").strip().lower()
    return tok if tok in config.ASSET_STRATEGIES else config.DEFAULT_ASSET_STRATEGY


def sanitize_tone_grade(v: Any) -> str:
    """톤 그레이딩 enum. 밖이면 'none'(무연산). 통제 어휘 규약 — 자유 텍스트 금지."""
    tok = str(v or "").strip().lower()
    if not tok or tok == config.DEFAULT_TONE_GRADE:
        return config.DEFAULT_TONE_GRADE
    if tok in config.TONE_GRADES:
        return tok
    log.warning("지시서: 미허용 tone_grade '%s' → '%s'", tok, config.DEFAULT_TONE_GRADE)
    return config.DEFAULT_TONE_GRADE


def normalize_crop(v: Any) -> tuple[dict[str, float] | None, bool]:
    """크롭 비율 정규화. 반환: (정규화된 crop 또는 None, 클램프가 일어났는지).

    ★ 클램프 사실을 **버린 값으로 조용히 삼키지 않는다.** 모델이 3.5배를 요청했는데 2.5로 깎였다면
      운영자가 그 컷의 확대가 의도보다 약하다는 걸 알아야 한다 → `header.mode_warnings` 로 올라간다.
    ★ 중앙·배율 1.0(=할 일 없음)이면 None 을 돌려준다. 의미 없는 필드가 지시서에 남으면 diff 와
      content_hash 가 지저분해지고, 렌더는 어차피 파일 복사로 간다.
    """
    if not isinstance(v, dict):
        return None, False
    clamped = False

    def _num(key: str, default: float, lo: float, hi: float) -> float:
        nonlocal clamped
        try:
            raw = float(v.get(key, default))
        except (TypeError, ValueError):
            return default
        if raw != raw:                      # NaN
            return default
        if raw < lo or raw > hi:
            clamped = True
            return lo if raw < lo else hi
        return raw

    cx = _num("cx", config.CROP_DEFAULT_CENTER, 0.0, 1.0)
    cy = _num("cy", config.CROP_DEFAULT_CENTER, 0.0, 1.0)
    scale = _num("scale", config.CROP_MIN_SCALE, config.CROP_MIN_SCALE, config.CROP_MAX_SCALE)
    if scale <= config.CROP_MIN_SCALE:
        return None, clamped
    return {"cx": round(cx, 4), "cy": round(cy, 4), "scale": round(scale, 4)}, clamped


def enforce_motion_value_gate(
    cuts: list[dict[str, Any]], declared: set[int] | None = None,
    *, tiered: bool = False, warnings_out: list[str] | None = None,
) -> list[dict[str, Any]]:
    """움직임이 이해에 기여하지 않는 컷에서 영상비를 걷어낸다 (수정명세 §10-4).

    ★ 이게 "상한을 꽉 채우는" 습관을 실제로 막는 지점이다. 개수 캡(다음 단계)은 넘친 뒤에야
      자르지만, 이건 애초에 값어치 없는 컷을 후보에서 뺀다. high 만 영상으로 살아남는다.

    ★ `declared` = motion_value 를 **실제로 선언한** 컷 번호들. 선언하지 않은 컷은 이 계약을
      모르는 쪽(레거시 지시서, 그리고 engine/report_directive.py 의 금융 라인)이므로 건드리지
      않는다. 그러지 않으면 motion_value 를 안 쓰는 금융 지시서의 영상 컷이 전부 조용히
      스틸로 강등된다 — 범위 밖 라인을 깨는 일이다.
    """
    if declared is None:
        declared = {c.get("cut_no") for c in cuts}  # type: ignore[misc]
    for c in cuts:
        if c.get("cut_no") not in declared:
            continue
        if c.get("motion_source") == "video" and c.get("motion_value") != "high":
            # ★★ 등급제(v2): 품질 결정권은 등급에 있다. 여기서 조용히 스틸로 내리면
            #   `sequence_tier` 가 invest 로 판정한 기전 컷이 motion_value 라벨 하나로
            #   영상을 잃는다 — 그것도 **모델의 자기보고 라벨**로. 강등하지 않고 드러낸다.
            if tiered:
                if warnings_out is not None:
                    warnings_out.append(f"motion_gate_would_demote#{c.get('cut_no')}")
                continue
            c["motion_source"] = "still"
            log.info("motion_value=%s → 컷 %s 스틸로 강등(영상 불필요)",
                     c.get("motion_value"), c.get("cut_no"))
    return cuts


def enforce_mode_video_budget(cuts: list[dict[str, Any]], content_mode_name: str,
                              version_type: str = "") -> list[dict[str, Any]]:
    """모드별 영상 클립 개수 상한(결정 D-E1). 모드를 모르면 전역 캡으로 폴백한다.

    ★ 버전별 상향(실사형)이 있으면 그것이 이긴다 — config.video_clips_max 가 판정한다.
    """
    limit = config.video_clips_max(
        version_type, content_mode.resolve_cost_plan(content_mode_name)["max_video_clips"])
    kept = 0
    for c in cuts:
        if c.get("motion_source") == "video":
            if kept < limit:
                kept += 1
            else:
                c["motion_source"] = "still"
                log.info("모드 %s 영상 상한(%s개) 초과 → 컷 %s 스틸로 강등",
                         content_mode_name, limit, c.get("cut_no"))
    return cuts


def validate_reuse_refs(cuts: list[dict[str, Any]]) -> list[str]:
    """에셋 재사용 참조 검증. 앞선 컷만 가리킬 수 있다(렌더가 순서대로 만들기 때문).

    깨진 참조는 조용히 두면 렌더가 기준 에셋을 못 찾아 결국 새로 생성한다 — 절감이 사라진다.
    그래서 여기서 new_asset 으로 강등하고 경고를 남긴다.
    """
    warnings: list[str] = []
    seen: set[int] = set()
    for c in cuts:
        no = c.get("cut_no")
        strategy = c.get("asset_strategy")
        if strategy in config.ASSET_STRATEGY_REUSE:
            ref = str(c.get("base_asset_ref") or "").strip()
            try:
                ref_no = int(ref)
            except (TypeError, ValueError):
                ref_no = -1
            if ref_no not in seen:
                c["asset_strategy"] = config.DEFAULT_ASSET_STRATEGY
                # ★ 크롭·톤도 함께 비운다. 남겨 두면 **갓 생성한 새 이미지**에 낡은 크롭이 얹혀
                #   조용히 잘린다 — 참조가 깨진 것보다 알아채기 어려운 사고다.
                c["crop"] = None
                c["tone_grade"] = config.DEFAULT_TONE_GRADE
                warnings.append(f"invalid_reuse_ref#{no}")
                log.warning("컷 %s 재사용 참조 '%s' 무효 → new_asset 강등(크롭·톤 제거)", no, ref)
        if isinstance(no, int):
            seen.add(no)
    return warnings


def enforce_video_clip_cap(cuts: list[dict[str, Any]], version_type: str,
                           *, tiered: bool = False,
                           warnings_out: list[str] | None = None) -> list[dict[str, Any]]:
    """편당 영상 컷 상한(VEO_MAX_CLIPS_PER_DRAFT) 강제(비용 가드). 초과분은 앞에서부터 유지하고
    나머지는 스틸로 강등한다(결정론적). 모든 버전 공통."""
    limit = config.video_clips_max(version_type)
    kept = 0
    for c in cuts:
        if c.get("motion_source") == "video":
            if kept < limit:
                kept += 1
            else:
                # ★ 등급제에서는 개수로 자르지 않는다. 총액은 preflight 와 ⑤ 가 본다.
                if tiered:
                    if warnings_out is not None:
                        warnings_out.append(f"video_cap_exceeded#{c.get('cut_no')}")
                    continue
                c["motion_source"] = "still"
                log.info("영상 컷 상한(%s개) 초과 → 컷 %s 스틸로 강등", limit, c.get("cut_no"))
    return cuts


def sanitize_media_policy(v: Any) -> str:
    tok = str(v or "").strip()
    if tok in config.MEDIA_POLICIES:
        return tok
    if tok:
        log.warning("지시서: 미허용 media_policy '%s' → 기본값", tok)
    return config.DEFAULT_MEDIA_POLICY


def preflight_video_budget(
    cuts: list[dict[str, Any]], media_policy: str,
    max_sec: int | None = None, max_cost_usd: float | None = None,
    version_type: str = "", *, tiered: bool = False,
    warnings_out: list[str] | None = None,
) -> list[dict[str, Any]]:
    """작업 B 이중 캡 + 정책 강제 (명세 §8.2~8.4). 렌더(유료 API 호출) 이전, 지시서 생성 시점에
    적용한다 — 캡을 넘는 컷은 애초에 Veo 를 호출하지 않아 렌더 단계 예산 초과로 스핀 낭비가 없다.

    - image_only: 전 컷 스틸 강제.
    - video_required: 캡을 넘어도 최우선(등장 순서상 가장 앞) 1개는 유지(사람 개입 큐가 없는 경량
      경로라 "렌더 중단" 대신 강제 유지 + 경고 로그로 대체, §8.2).
    - 그 외(image_preferred/video_allowed): 초수·금액 둘 다 캡 안에 들 때까지 등장 순서대로 채우고,
      넘는 컷부터 스틸로 강등(우선순위 낮은 영상부터 강등, §8.4).

    ★ `max_sec`/`max_cost_usd` 를 주면 그 예산으로 조인다(결정 D-E1: 모드별 캡이 전역 캡을
      **대체**한다). 안 주면 기존 전역 캡 — 모드를 모르는 레거시·금융 라인이 그대로 동작한다.
    """
    # ★★ 등급제(v2 Phase C): **비용을 이유로 품질을 자동으로 깎지 않는다**(코덱스 리뷰 P0-4).
    #   대신 초과 사실이 `cost_plan` 을 통해 `video_budget_exceeded` 차단 사유가 되어
    #   ⑤ 승인에서 **돈이 나가기 전에** 멈춘다(approvalGate 가 이미 그 키를 읽는다).
    #   운영자가 명시적으로 승인해야 진행된다 — "조용한 강등"보다 "발주 전 중단"이 옳다.
    #   ★ image_only 는 예외다. 그건 비용 판단이 아니라 **운영자가 고른 정책**이다.
    if tiered and media_policy != "image_only":
        if warnings_out is not None:
            warnings_out.append("video_budget_not_enforced_by_demotion")
        return cuts

    if media_policy == "image_only":
        for c in cuts:
            if c.get("motion_source") == "video":
                c["motion_source"] = "still"
                log.info("media_policy=image_only → 컷 %s 스틸 강등", c.get("cut_no"))
        return cuts

    price = cost.unit_price(config.VEO_MODEL, f"video_{config.VEO_RESOLUTION}_per_sec")
    sec_budget = (max_sec if max_sec is not None
                  else config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC)
    cost_budget = Decimal(str(max_cost_usd if max_cost_usd is not None
                              else config.VIDEO_MAX_COST_USD_PER_TOPIC))
    used_sec, used_cost, kept_any = 0, Decimal("0"), False

    for c in cuts:
        if c.get("motion_source") != "video":
            continue
        # ★ 컷별 요청 초수는 고정이 아니다 — 렌더 시 나레이션 길이 이상인 최소 티어를 요청한다
        # (수정명세 v1 §3-2). 여기(렌더 이전)에서는 나레이션 실측이 없으니 지시서의 estimated_sec
        # 을 대리값으로 같은 티어 함수를 태운다. 상한(VEO_CLIP_MAX_TIER_SEC)이 기본값이면 결과는
        # VEO_CLIP_SEC 과 같아 기존 동작·비용이 그대로다. 상한을 올리면 이 캡도 함께 올라간 초수로
        # 조여야 예산 가드가 실제 과금을 놓치지 않는다.
        # ★ 티어 상한은 **버전별**이다(2026-08-21). 안 넘기면 여기는 4초로 예산을 잡고
        #   렌더는 8초를 산다(실사형) — 실제 과금이 예산의 2배가 되고, 캡은 하드 스톱이라
        #   돈을 쓴 뒤 렌더가 도중에 죽는다.
        clip_sec = video.pick_clip_tier(_clamp_sec(c.get("estimated_sec")),
                                        max_sec=config.clip_tier_max(version_type))
        clip_cost = price * Decimal(str(clip_sec))
        fits = used_sec + clip_sec <= sec_budget and used_cost + clip_cost <= cost_budget
        if fits or (media_policy == "video_required" and not kept_any):
            used_sec += clip_sec
            used_cost += clip_cost
            kept_any = True
            if not fits:
                log.warning("media_policy=video_required: 컷 %s 캡 초과지만 유지(예산 상한 무시)",
                            c.get("cut_no"))
        else:
            c["motion_source"] = "still"
            log.info("영상 예산 캡 초과(초=%s/%s, $=%.3f/%.3f) → 컷 %s 스틸 강등",
                     used_sec, sec_budget, float(used_cost), float(cost_budget), c.get("cut_no"))
    return cuts


def enforce_scene_variety(cuts: list[dict[str, Any]], version_type: str) -> list[dict[str, Any]]:
    """③ 다양성 제약 강제: 같은 scene_kind 3연속 금지(최대 2연속).

    3번째 연속이 나오면 그 컷의 scene_kind 를 다른 종류로 교체한다. 교체 우선순위는 고효율 씬
    (motion_graphic/kinetic_typography/data_viz) 중 직전과 다른 것 → 나머지 enum. 결정론적(순수).
    high-effort 카덴스(10초당 1회)는 검증·로그로만 다루고 여기선 자동 주입하지 않는다.
    """
    max_same = config.SCENE_MAX_CONSECUTIVE_SAME
    prefer = list(config.SCENE_HIGH_EFFORT_KINDS) + [
        k for k in config.SCENE_KINDS if k not in config.SCENE_HIGH_EFFORT_KINDS
    ]
    run_kind: str | None = None
    run_len = 0
    for c in cuts:
        kind = c.get("scene_kind")
        if kind == run_kind:
            run_len += 1
        else:
            run_kind, run_len = kind, 1
        if run_len > max_same:
            alt = next((k for k in prefer if k != run_kind), run_kind)
            c["scene_kind"] = alt
            run_kind, run_len = alt, 1
    return cuts


def scene_variety_report(cuts: list[dict[str, Any]]) -> dict[str, Any]:
    """다양성 준수 요약(로그·검증용). 3연속 위반 여부 + 고효율 씬 개수."""
    kinds = [c.get("scene_kind") for c in cuts]
    max_run = 0
    run = 0
    prev = None
    for k in kinds:
        run = run + 1 if k == prev else 1
        prev = k
        max_run = max(max_run, run)
    high = sum(1 for k in kinds if k in config.SCENE_HIGH_EFFORT_KINDS)
    return {"max_consecutive": max_run, "high_effort_cuts": high, "total_cuts": len(cuts)}


def compute_cost_plan(cuts: list[dict[str, Any]], content_mode_name: str,
                      version_type: str = "",
                      sequences: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """모드 예산(상한) + 이 지시서의 실제 사용량·예상 생성비를 함께 담는다 (수정명세 §15-1).

    ★ 상한은 config 에서, 실사용은 컷에서 온다. 모델이 header 에 써 보낸 cost_plan 은 쓰지 않는다.
      단가는 engine/cost.py 의 PRICING 스냅샷을 그대로 쓴다(새 산수 금지, Decimal).
    """
    plan = content_mode.resolve_cost_plan(content_mode_name)
    # ★ "고유 에셋" = 렌더가 **실제로 생성 API 를 부르는** 컷이다. 재사용 전략만 빠진다.
    #   code_viz·text_only_transition 은 이론상 공짜지만 아직 렌더 경로가 없어(M-E4) 지금은
    #   생성 이미지로 나간다 — 여기서 빼면 예상 비용이 실제보다 낮게 나온다.
    unique = [c for c in cuts if c.get("asset_strategy") not in config.ASSET_STRATEGY_REUSE]
    reused = [c for c in cuts if c.get("asset_strategy") in config.ASSET_STRATEGY_REUSE]
    video_cuts = [c for c in cuts if c.get("motion_source") == "video"]
    # ★ 코드 시각화 개수는 **resolved plan** 에서 센다(코덱스 리뷰 §15, 2026-08-30).
    #   종전에는 모델이 쓴 `asset_strategy == "code_viz"` 를 셌는데, 라우팅은 코드가 정하므로
    #   둘이 어긋났다 — 골든 두 편 모두 라우팅 CODE_VIZ 4·3 에 cost_plan 0 이었다.
    #   `asset_strategy` 는 정본이 없을 때(옛 지시서)만 폴백으로 본다.
    code_viz = [c for c in cuts if _is_code_visual(c)]

    # ★ 버전별 티어 상한을 반영한다 — ⑤ 확인 모달이 총액을 보는 유일한 지점이라, 여기가
    #   4초로 계산하면 실사형 발주가 실제보다 싸게 보인다(실측 기준 최대 2배 과소).
    # ★★ 등급제(v2): 예상 초수도 **등급이 정한 길이 × 후보 수**로 센다. 그러지 않으면
    #   ⑤ 가 4초로 보여주고 렌더는 8초를 두 번 사서, 총액이 2~4배 어긋난다.
    #   이 숫자가 곧 `video_budget_exceeded` 판정의 입력이라 — 여기가 틀리면 발주 전
    #   fail-fast 가 엉뚱한 값으로 돌거나 아예 안 돈다(P0-4 가 무력화된다).
    _tiered = config.tiering_enabled(version_type)
    _hdr = {"version_type": version_type, "visual_sequences": sequences or []}
    video_sec = 0
    for c in video_cuts:
        base = video.pick_clip_tier(int(c.get("estimated_sec") or config.CUT_MIN_SEC),
                                    max_sec=config.clip_tier_max(version_type))
        if _tiered:
            want = sequence_tier.clip_sec_for(c, _hdr)
            base = max(base, want) if want else base
            base *= sequence_tier.candidates_for(c, _hdr)   # 후보를 2개 뽑으면 2배 산다
        video_sec += base
    # ★ 컷마다 **실제 모델**로 계산한다(2026-08-29). 예전엔 전 컷을 config.IMAGE_MODEL 로
    #   묶어, 프리미엄 모델을 쓰는 3D 도해 컷이 flash 단가로 계산됐다 — ⑤ 확인 모달의 총액이
    #   실제보다 싸게 보였고, 예산 가드도 그 낮은 값을 봤다.
    image_cost = sum(
        (cost.compute_cost(spec.model, spec.unit_type, 1)
         for spec in (generation_spec.image_spec(c) for c in unique)),
        Decimal("0"),
    )
    image_models = sorted({generation_spec.image_spec(c).model for c in unique})
    video_cost = cost.compute_cost(
        config.VEO_MODEL, f"video_{config.VEO_RESOLUTION}_per_sec", video_sec)

    denom = len(unique) + len(reused)
    # ★ 상한도 버전 상향을 반영한다. 안 하면 실사형 6클립×8초=48초가 모드 상한 8초를 넘겨
    #   directive_block_reasons 가 video_budget_exceeded 로 **정상 지시서를 승인 차단**한다.
    _v_sec, _v_cost = config.video_budget_for(version_type, plan)
    plan.update({
        "max_unique_assets": config.unique_assets_max(
            version_type, plan["max_unique_assets"], len(cuts)),
        "max_video_clips": config.video_clips_max(version_type, plan["max_video_clips"]),
        "max_video_generated_sec": _v_sec,
        "max_video_cost_usd": _v_cost,
        "unique_asset_count": len(unique),
        "reuse_count": len(reused),
        "asset_reuse_ratio": round(len(reused) / denom, 3) if denom else 0.0,
        "code_viz_count": len(code_viz),
        "video_clip_count": len(video_cuts),
        "video_generated_sec": video_sec,
        "estimated_image_cost_usd": float(image_cost),
        # 어떤 모델로 계산했는지 남긴다 — 원장과 대조할 때 이 줄이 없으면 총액만 보고
        # "왜 비싼가"를 물어야 한다.
        "image_models": image_models,
        "video_model": config.VEO_MODEL,
        "estimated_video_cost_usd": float(video_cost),
        "estimated_total_generation_cost_usd": float(image_cost + video_cost),
    })
    if _tiered:
        # ★★ 장면별 내역(v2 Phase D). 운영자가 "예상 비용을 보고 조절"하려면 **어느
        #   장면에 얼마가 가는지**부터 보여야 한다. 총액 한 줄로는 등급표를 못 고친다.
        #   ★ 렌더가 읽는 것과 **같은 판정**(`effective_tier`)에서 집계한다 — 산정기가
        #     자체 재계산하면 ⑤ 숫자와 실제가 갈라진다(§9-4 "같은 resolved plan" 원칙).
        plan["sequences"] = sequence_cost_lines(cuts, _hdr, version_type)
        plan.update(sequence_tier.summary(cuts, _hdr))
    return plan


def sequence_cost_lines(cuts: list[dict[str, Any]], header: dict[str, Any],
                        version_type: str) -> list[dict[str, Any]]:
    """장면별 비용 내역. ⑤ 확인 모달이 이 목록을 표로 그린다.

    ★ 시퀀스에 속하지 않는 컷(훅·CTA)도 `"(시퀀스 밖)"` 한 줄로 모은다 — 빼면
      장면 합계와 편 총액이 어긋나 운영자가 "나머지는 어디 갔나"를 묻게 된다.
    """
    seq_role = {str(s.get("sequence_id") or ""): str(s.get("sequence_role") or "")
                for s in (header.get("visual_sequences") or [])}
    lines: dict[str, dict[str, Any]] = {}
    for c in cuts:
        if str(c.get("motion_source") or "") != "video":
            continue
        sid = str((c.get("resolved_visual_plan") or {}).get("sequence_ref") or "") or "(시퀀스 밖)"
        info = sequence_tier.effective_tier(c, header)
        sec = video.pick_clip_tier(int(c.get("estimated_sec") or config.CUT_MIN_SEC),
                                   max_sec=config.clip_tier_max(version_type))
        want = sequence_tier.clip_sec_for(c, header)
        sec = max(sec, want) if want else sec
        n = sequence_tier.candidates_for(c, header)
        row = lines.setdefault(sid, {
            "sequence_id": sid, "role": seq_role.get(sid, ""), "tier": info["tier"],
            "cuts": 0, "clips": 0, "video_sec": 0, "candidates": n,
            "tier_defaulted_count": 0,
        })
        row["cuts"] += 1
        row["clips"] += n
        row["video_sec"] += sec * n
        row["tier_defaulted_count"] += 1 if info["defaulted"] else 0
        # 한 시퀀스 안에서 등급이 갈리면 **높은 쪽**을 보여 준다(투자한 장면임을 놓치지 않게).
        if config.SEQUENCE_TIERS.index(info["tier"] or config.DEFAULT_SEQUENCE_TIER) \
                < config.SEQUENCE_TIERS.index(row["tier"] or config.DEFAULT_SEQUENCE_TIER):
            row["tier"] = info["tier"]
    for row in lines.values():
        row["est_usd"] = float(cost.compute_cost(
            config.video_model_for_tier(row["tier"]),
            f"video_{config.VEO_RESOLUTION}_per_sec", row["video_sec"]))
    return sorted(lines.values(), key=lambda r: (-r["video_sec"], r["sequence_id"]))


def _is_code_visual(cut: dict[str, Any]) -> bool:
    """이 컷이 **코드가 그리는 그래픽**을 쓰는가 — 화면 전체든 정밀 레이어든.

    ★ 정본은 `resolved_visual_plan` 이다(코덱스 리뷰 R3). 정밀 레이어(CODE_OVERLAY)도
      코드 렌더이므로 함께 센다 — R1 이후 수치 컷의 다수가 이 형태다.

    ★★ 다만 **beat 도 시퀀스도 없는 컷의 base 는 판정이 아니라 기본값**이다. 라우터는
      beat 가 비면 RESULT 로 채우고 RESULT 의 기본 표현이 CODE_VIZ 라, v3 라벨을 쓰지 않는
      만화식·옛 지시서의 컷이 **전부 코드 시각화로 세어졌다**(실측: 3컷 중 3컷).
      돈이 걸린 소비자는 합성된 기본값과 실제 판정을 구분해야 한다.

    ★★ **stage 에 속한다는 것만으로는 판정이 아니다**(2026-08-30, 리포트 라인 배선 중 실측).
      금융 컷은 beat 를 선언하지 않는다. 그런데 Equity Planner 가 컷을 stage 에 묶자
      `stage_ref` 가 생겼고, 그 순간 라우터가 **채워 넣은** 기본 base(CODE_VIZ)가 판정으로
      읽혀 시퀀스 컷 4개가 전부 코드 시각화로 세어졌다 — 이미지 예산이 0이 된다.
      실제 판정의 표시는 라우터가 남기는 `in_visual_sequence` 다. 그것을 본다.
    """
    plan = cut.get("resolved_visual_plan")
    routed_by_sequence = isinstance(plan, dict) and \
        "in_visual_sequence" in (plan.get("reasons") or [])
    if isinstance(plan, dict) and (plan.get("beat_declared") or routed_by_sequence):
        return plan.get("base") == "CODE_VIZ" or bool(plan.get("precision_layer"))
    return cut.get("asset_strategy") == "code_viz"


def _image_unit_type() -> str:
    """현재 이미지 생성 모드에 맞는 단가 항목(Batch 면 반값)."""
    return "image_batch" if config.IMAGE_GENERATION_MODE == "batch" else "image_standard"


def directive_warnings(header: dict[str, Any], cuts: list[dict[str, Any]]) -> list[str]:
    """차단은 아니지만 운영자가 승인 전에 봐야 하는 신호들 (수정명세 §14-4)."""
    out: list[str] = []
    plan = header.get("cost_plan") or {}
    if plan.get("unique_asset_count", 0) > plan.get("max_unique_assets", 0):
        out.append("unique_assets_over_budget")
    if plan.get("asset_reuse_ratio", 0.0) < plan.get("asset_reuse_target", 0.0):
        out.append("asset_reuse_below_target")
    if bold_hook_gate_violation(header):
        out.append("bold_hook_on_weak_evidence")
    if header.get("hook_promise_check", {}).get("pass") is False:
        out.append("hook_promise_unpaid")
    for c in cuts:
        no = c.get("cut_no")
        if int(c.get("estimated_sec") or 0) > config.CUT_STATE_CHANGE_MIN_SEC \
                and not str(c.get("state_change") or "").strip():
            out.append(f"long_cut_without_state_change#{no}")
        if not str(c.get("novelty_event") or "").strip():
            out.append(f"no_novelty_event#{no}")
    return out


def refresh_claim_evidence(draft_row: dict[str, Any]) -> dict[str, Any] | None:
    """지시서를 만들기 전에 **근거 원장을 지금 계약으로 다시 찍는다**(코덱스 리뷰 §4).

    ★ 왜 필요한가: `validation` 은 초안 단계에서 DB 에 기록되고 그대로 남는다. 그래서
      대조 코드를 고쳐도 **이미 저장된 판정은 바뀌지 않는다** — 골든B 가 그 상태였다.
      낡은 `false` 4건이 정상 컷 4개를 계속 차단했는데, 지금 코드로는 10/10 통과한다.

    ★ 무료다. 보관된 원문을 읽고 문자열 대조만 한다 — LLM 호출 0건, 네트워크는 Supabase 뿐.
      원문이 없으면 초록을 원문으로 삼는다(paper_evidence.verification_packet).

    ★ 실패해도 죽이지 않는다. 조회가 안 되면 원장을 그대로 두고, 그러면 낡은 판정은
      `is_current` 에 걸려 **차단이 아니라 판정 불가**로 다뤄진다. 안전한 쪽으로 무너진다.
    """
    fact_sheet = draft_row.get("fact_sheet")
    if not isinstance(fact_sheet, dict) or not fact_sheet.get("claims"):
        return fact_sheet
    if all(paper_evidence.is_current(c.get("validation"))
           for c in fact_sheet["claims"] if isinstance(c, dict)):
        return fact_sheet                      # 이미 지금 계약으로 찍혀 있다
    try:
        paper = draft_row.get("paper") or db.get_paper(str(draft_row.get("paper_id") or "")) or {}
        packet = db.get_paper_source(str(paper.get("external_id") or "")) or {}
    except Exception as exc:                   # noqa: BLE001 — 보관 조회 실패는 치명적이지 않다
        log.warning("근거 재대조를 건너뛴다(원문 조회 실패): %s", exc)
        return fact_sheet
    packet = paper_evidence.verification_packet(packet, paper.get("abstract"))
    return paper_evidence.attach_evidence(fact_sheet, packet)


def unsupported_detail_cuts(cuts: list[dict[str, Any]],
                            routed: list[dict[str, Any]],
                            source_text: str) -> list[str]:
    """**확보한 근거가 지불하지 않는 구체성**을 화면에 그리려는 컷 (코덱스 리뷰 R2·ENTRY-2).

    ★ 무엇이 달라졌나: 종전에는 `source_depth` 가 얕으면 기전 시퀀스를 통째로 REALITY 로
      후퇴시켰다. 그 후퇴는 **근거 없는 컷을 막지 못하면서**(골든A 는 후퇴하고도 컷4 에
      "사전 등록된 무작위 실험"을 그렸다) 정상 컷만 벌했다. `abstract_only ≠ 기전 금지` 다.

    ★ 그래서 미디어가 아니라 **구체성**을 본다. 그리고 판정은 어휘 목록이 아니라
      **원문 대조**로 한다 — 프롬프트에 `double-blind` 가 있는데 원문에 그 말이 없으면
      지어낸 것이고, 원문에 있으면 통과다. 어휘 목록만으로 막으면 원문이 실제로 말하는
      절차까지 벌하게 되고, 그러면 운영자가 게이트를 무시하기 시작한다.

    ★ 대조할 원문이 없으면(확보 실패) **차단하지 않는다.** 판정 불가와 실패를 섞지 않는다.
    """
    src = str(source_text or "").lower()
    if not src:
        return []
    by_cut = {int(r.get("cut_no") or 0): r for r in routed}
    hits: dict[str, list[str]] = {}
    for c in cuts:
        plan = by_cut.get(int(c.get("cut_no") or 0)) or {}
        restricted = plan.get("detail_restrictions") or []
        if not restricted:
            continue
        text = " ".join(str(c.get(k) or "") for k in
                        ("visual_prompt", "motion_prompt", "state_change")).lower()
        spec = c.get("mechanism")
        if isinstance(spec, dict):
            text += " " + " ".join(str(v) for v in spec.values() if isinstance(v, str)).lower()
        for category in restricted:
            for term in config.DETAIL_SPECIFICITY_TERMS.get(category, ()):
                if term in text and term not in src:
                    hits.setdefault(category, []).append(str(c.get("cut_no")))
                    break
    return [f"cut_detail_not_in_source:{cat}:{','.join(sorted(set(nos))[:6])}"
            for cat, nos in sorted(hits.items())]


def ungrounded_relation_cuts(cuts: list[dict[str, Any]],
                             source_text: str,
                             fact_sheet: dict[str, Any] | None = None) -> list[str]:
    """**원문에 없는 관계를 화면이 지어내는** 컷 (리뷰 §14, 2026-09-02).

    ★ 무엇이 비어 있었나: 기존 문자열 게이트는 `glow`·`decorative` 같은 **스타일**만 봤다.
      정작 위험한 것은 스타일이 아니라 **주장**이다 — 골든B 컷14 "다른 궤도들이 기준
      궤도에 맞춰 정렬된다" 는 원문에 없는 관계인데 아무 사유 없이 통과했다.
      화면이 "A 가 B 를 유발한다"고 그리면 그건 연출이 아니라 **논문이 하지 않은 주장**이다.

    ★ 판정은 어휘가 하지 않는다. `RELATION_TERMS` 는 **어디를 볼지**만 정하고, 통과 여부는
      `unsupported_detail_cuts` 와 똑같이 **원문 대조**가 정한다. 그래서 논문이 실제로
      말하는 관계("수용체에 결합한다")는 그대로 통과한다 — 어휘 목록만으로 막으면 옳게
      한 컷을 벌하고, 그러면 운영자가 게이트를 무시하기 시작한다(리뷰 §17).

    ★ Fact Sheet 의 주장도 근거로 친다. 초록만 확보한 논문에서 원문 대조는 좁은데,
      우리가 이미 검증한 주장이 그 관계를 말하고 있으면 그것도 지불된 근거다.

    ★ 대조할 원문이 아예 없으면 **아무것도 내지 않는다** — 판정 불가를 위반으로
      기록하지 않는다(`unsupported_detail_cuts` 와 같은 계약).
    """
    grounded = str(source_text or "").lower()
    for c in ((fact_sheet or {}).get("claims") or []):
        if isinstance(c, dict):
            grounded += " " + " ".join(str(v) for v in c.values()
                                       if isinstance(v, str)).lower()
    if not grounded.strip():
        return []
    hits: list[str] = []
    for cut in cuts:
        text = " ".join(str(cut.get(k) or "") for k in
                        ("visual_prompt", "motion_prompt", "state_change")).lower()
        if any(t in text and t not in grounded for t in config.RELATION_TERMS):
            hits.append(str(cut.get("cut_no")))
    if not hits:
        return []
    return [f"cut_relation_not_in_source:{','.join(hits)}"]


def ungrounded_claim_cuts(cuts: list[dict[str, Any]],
                          fact_sheet: dict[str, Any] | None) -> list[str]:
    """**지어낸 인용에 기대는 컷**들의 사유 코드 (2026-08-29).

    ★ 왜 지시서 단계에도 두는가: 대조 자체는 초안 단계에서 끝난다
      (engine/paper_evidence.attach_evidence). 하지만 초안이 승인된 뒤 지시서가 어느 주장을
      화면에 실을지는 여기서 정해진다 — 근거가 무너진 주장을 컷이 집어 오면 그것이 화면에
      나간다. 그래서 **컷 단위로 한 번 더** 본다.

    ★ 판정 불가(원문 미확보)는 차단하지 않는다. 확보율이 63% 라 전부 막으면 열 편 중 네 편이
      멈춘다 — 그건 등급 상한으로 다루고 운영자는 source_depth 로 그 사실을 본다.
      차단하는 것은 **대조했더니 원문에 없더라**는 경우뿐이다.
    """
    claims = {str(c.get("claim_id")): c
              for c in ((fact_sheet or {}).get("claims") or [])
              if isinstance(c, dict) and c.get("claim_id")}
    if not claims:
        return []
    if not any(isinstance(c, dict) and c.get("validation") for c in claims.values()):
        return []                     # 대조가 안 돈 초안 — 차단이 아니라 경고다(아래 함수)
    # ★★ **낡은 계약으로 내려진 판정은 차단하지 않는다**(코덱스 리뷰 §4, 2026-08-30).
    #
    #   실측 사고: 골든B 가 컷 5·9·10·12 를 `cut_claim_not_in_source` 로 차단했는데,
    #   지금 코드로 재대조하면 그 주장 4개는 **전부 원문에 있다**(최저 연속 일치 0.992).
    #   차이는 표기뿐이었다 — 모델은 `$\sim$7 min` 이라 쓰고 원문은 `\sim 7 min` 이다.
    #   그 `false` 는 커밋 c681613(연속 일치 비율) 이전 코드가 DB 에 써 둔 값이었고,
    #   지시서 단계는 그것을 그대로 믿었다.
    #
    #   즉 **저장된 판정이 검증 코드보다 오래 살았다.** 게이트를 느슨하게 하는 것이 아니라
    #   낡은 판정을 판정 불가로 되돌리는 것이 옳은 수정이다 — 신선한 판정에는 그대로 엄격하다.
    #   (지시서 생성 경로는 이보다 앞서 재대조를 시도한다: refresh_claim_evidence)
    bad = {cid for cid, c in claims.items()
           if paper_evidence.is_current(c.get("validation"))
           and (c.get("validation") or {}).get("quote_verified") is False}
    if not bad:
        return []
    hit = sorted({str(c.get("cut_no")) for c in cuts
                  if bad & {str(x) for x in (c.get("claim_ids") or [])}})
    return [f"cut_claim_not_in_source:{','.join(hit[:6])}"] if hit else []


def claim_evidence_warnings(fact_sheet: dict[str, Any] | None) -> list[str]:
    """대조가 **돌지 않았다**는 사실을 화면에 남긴다. 차단은 아니다.

    ★ 왜 필요한가(2026-08-29): 엣지 함수(supabase/functions/generate-draft)는 원문을 확보하지도
      대조하지도 않는다 — 초록만 보고 Fact Sheet 를 뽑는다. 그 경로로 만들어진 초안에는
      claim.validation 이 아예 없어서 게이트가 "위반 0건"으로 통과시킨다.
      **검증을 통과한 것과 검증을 안 한 것이 같은 화면으로 보이는 것**이 가장 위험하다.

    ★ 차단하지 않는 이유: 오늘 대시보드 [초안 생성] 버튼이 그 엣지 경로다. 차단하면 버튼이
      통째로 죽는다. 정본을 워커로 옮기는 것은 별개의 운영 결정이다(리포트 라인은 이미
      REPORT_DRAFT_EDGE_FALLBACK 로 그 전환을 했다).
    """
    claims = [c for c in ((fact_sheet or {}).get("claims") or []) if isinstance(c, dict)]
    if not claims:
        return []
    if any(c.get("validation") for c in claims):
        return []
    return ["claim_evidence_not_run"]


def directive_block_reasons(
    header: dict[str, Any], cuts: list[dict[str, Any]],
    content_plan: dict[str, Any] | None = None,
    fact_sheet: dict[str, Any] | None = None,
    routed: list[dict[str, Any]] | None = None,
    source_text: str = "",
) -> list[str]:
    """승인 차단 사유 (수정명세 §14-3). 경고와 달리 사람이 승인 버튼을 누를 수 없게 만든다.

    ★ 원장·계획이 없는 레거시 지시서에는 Claim·길이 축이 돌지 않는다(비용 축만).
      80초 하드 상한은 이번 개정이 새로 세운 계약이라, 45~90초 규칙으로 만들어진 과거 지시서를
      소급 차단하면 안 된다(수정명세 §7 DoD "레거시는 차단 없이 정규화됨").
    """
    out: list[str] = []
    if content_plan:
        out.extend(content_mode.block_reasons(
            content_plan, header.get("total_estimated_sec")))
    plan = header.get("cost_plan") or {}
    if plan.get("video_generated_sec", 0) > plan.get("max_video_generated_sec", 0):
        out.append("video_budget_exceeded")
    if plan.get("estimated_video_cost_usd", 0.0) > plan.get("max_video_cost_usd", 0.0) + 1e-9:
        out.append("video_cost_exceeded")
    if content_plan:
        coverage = header.get("evidence_coverage") or {}
        if coverage.get("missing_claim_ids"):
            out.append("missing_required_claims")
        if coverage.get("required_claim_ids") and not coverage.get("primary_claim_covered"):
            out.append("primary_claim_not_covered")
    out.extend(ungrounded_claim_cuts(cuts, fact_sheet))
    # ★ 확보한 근거가 지불하지 않는 구체성(코덱스 리뷰 R2). 원문이 없으면 돌지 않는다 —
    #   판정 불가를 실패로 만들지 않는다.
    if routed and source_text:
        out.extend(unsupported_detail_cuts(cuts, routed, source_text))
    return sorted(set(out))


def _sanitize_enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """enum 밖/빈 값은 default 로. 훅·앵글·CTA·근거강도 통제 어휘 공용(자유 텍스트 금지)."""
    v = str(value or "").strip()
    return v if v in allowed else default


def normalize_hook_promise_check(obj: Any) -> dict[str, Any]:
    """훅↔본문 정합 자기검증 필드 정규화(P3). 형식 보장 + payoff 컷번호 int 리스트."""
    d = obj if isinstance(obj, dict) else {}
    payoff = d.get("payoff_cut_no")
    cut_nos: list[int] = []
    if isinstance(payoff, list):
        for x in payoff:
            try:
                cut_nos.append(int(x))
            except (TypeError, ValueError):
                continue
    return {
        "pass": bool(d.get("pass", False)),
        "promise": str(d.get("promise") or ""),
        "payoff_cut_no": cut_nos,
        "reason": str(d.get("reason") or ""),
    }


def normalize_science_reliability(obj: Any) -> dict[str, Any]:
    """근거강도 게이트 필드 정규화(P3). claim_type/evidence_strength/generalization_risk enum 강제."""
    d = obj if isinstance(obj, dict) else {}
    return {
        "claim_type": _sanitize_enum(d.get("claim_type"), config.CLAIM_TYPES, config.DEFAULT_CLAIM_TYPE),
        "evidence_strength": _sanitize_enum(
            d.get("evidence_strength"), config.EVIDENCE_STRENGTHS, config.DEFAULT_EVIDENCE_STRENGTH),
        "generalization_risk": _sanitize_enum(
            d.get("generalization_risk"), config.GENERALIZATION_RISKS, config.DEFAULT_GENERALIZATION_RISK),
        "required_caveat": str(d.get("required_caveat") or ""),
    }


def bold_hook_gate_violation(header: dict[str, Any]) -> bool:
    """대담·단정형 훅(H1/H2)인데 근거강도 게이트 미달이면 True(승인 화면 경고 대상, P3).

    게이트: evidence_strength=high AND generalization_risk=low 일 때만 대담 훅 허용.
    """
    if header.get("hook_type") not in ("H1", "H2"):
        return False
    sr = header.get("science_reliability") or {}
    return not (sr.get("evidence_strength") == "high" and sr.get("generalization_risk") == "low")


def normalize_directive(
    obj: dict[str, Any], version_type: str,
    fact_sheet: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    cut_max_sec: int | None = None,
    source_text: str = "",
) -> dict[str, Any]:
    """LLM 출력 → 명세 §4 지시서 shape 보장. visual_type 은 버전에서 강제,
    total_estimated_sec 은 컷 합으로 재계산(모델 자기보고 불신).

    `fact_sheet`·`content_plan` 을 주면 Claim 대조·모드 예산·근거 커버리지까지 강제한다.
    안 주면 기존 동작(전역 캡)으로 폴백 — 레거시 지시서가 그대로 정규화된다.

    `cut_max_sec` 를 주면 컷 길이 상한을 그 값으로 **평탄하게** 건다(종류별 규칙 미적용).
    금융 라인(engine/report_directive.py)이 자기 프롬프트의 3~8초 계약을 유지하려고 쓴다 —
    논문 전용 완화(10/12초)가 범위 밖 라인으로 새지 않게 하는 장치다.
    """
    version = version_type if version_type in config.VIDEO_VERSIONS else config.DEFAULT_VERSION
    visual_type = config.VERSION_VISUAL_TYPE[version]
    known_claims = factsheet.claim_ids(fact_sheet) if fact_sheet else ()

    header_in = obj.get("header") if isinstance(obj.get("header"), dict) else {}
    bgm_in = header_in.get("bgm") if isinstance(header_in.get("bgm"), dict) else {}
    # 모드는 계획이 정본이다. 계획이 없으면 헤더 값, 그것도 없으면 기본값.
    mode = str((content_plan or {}).get("selected_mode")
               or header_in.get("content_mode") or "").strip()
    if mode not in config.CONTENT_MODES:
        mode = config.DEFAULT_CONTENT_MODE

    cuts_in = obj.get("cuts") or []
    cuts: list[dict[str, Any]] = []
    declared_motion: set[int] = set()   # motion_value 를 실제로 선언한 컷(게이트 적용 대상)
    crop_warnings: list[str] = []       # 크롭 비율이 상한 밖이라 깎인 컷(운영자에게 보인다)
    for i, c in enumerate(cuts_in if isinstance(cuts_in, list) else []):
        if not isinstance(c, dict):
            continue
        try:
            cut_no = int(c.get("cut_no") or (i + 1))
        except (TypeError, ValueError):
            cut_no = i + 1
        scene_kind = sanitize_scene_kind(c.get("scene_kind"), version)  # ③ 다양성 래더
        motion_source = sanitize_motion_source(c.get("motion_source"), version)
        if "motion_value" in c:
            declared_motion.add(cut_no)
        sec_cap = cut_max_sec or content_mode.cut_max_sec(scene_kind, motion_source)
        claim_ids = [x.strip() for x in _str_list(c.get("claim_ids")) if x.strip()]
        if known_claims:
            claim_ids = [x for x in claim_ids if x in known_claims]  # dangling 참조 드롭
        role = str(c.get("evidence_role") or "").strip().lower()
        strategy = sanitize_asset_strategy(c.get("asset_strategy"))
        # ★★ 실사형은 **스틸 복사 재사용을 쓰지 않는다**(운영자 지시 2026-09-05).
        #   실측(세마글루타이드 렌더): 14컷 중 8컷이 reuse_* 였고, 렌더는 그 컷들의
        #   visual_prompt 를 **생성기에 보내지도 않고** 앞 컷 스틸을 복사했다(overlay 만 다르면
        #   복사 — render._reuse_base_image). 결과: 컷2~4 가 같은 두 쥐 20초, 컷8~12 가 같은
        #   구체 32초, 컷14 의 "빈 복도"는 컷13 의 쥐 우리로 나갔다. 운영자: "동일한 그림은
        #   통일성 전략이지, 사진을 띄워놓고 나레이션 읽으라고 한 적은 없다."
        #   통일성은 **참조 조건 생성**(앞 stage 그림을 참조로 새 프레임을 그린다)이 담당한다 —
        #   그건 살아 있다(_obtain_still 우선순위 ③). 죽이는 것은 "같은 파일을 두 번 트는" 경로다.
        if version_type == "photo" and strategy in config.ASSET_STRATEGY_REUSE:
            strategy = config.DEFAULT_ASSET_STRATEGY
        # 크롭·톤은 **재사용 전략 컷에서만** 의미가 있다. new_asset 컷에 크롭이 붙으면 갓 생성한
        # 이미지를 잘라내는 셈이라 지시서 의도와 어긋난다 → 여기서 떨어뜨린다.
        is_reuse = strategy in config.ASSET_STRATEGY_REUSE
        crop_val, crop_clamped = normalize_crop(c.get("crop")) if is_reuse else (None, False)
        if crop_clamped:
            crop_warnings.append(f"crop_clamped#{cut_no}")
        cuts.append({
            "cut_no": cut_no,
            "scene_kind": scene_kind,
            "narration_ko": str(c.get("narration_ko") or ""),
            "narration_en": str(c.get("narration_en") or ""),
            # 상한은 컷 종류·모션에 따라 다르다(§10-2): 기본 10 / data_viz 12 / 영상 8.
            "estimated_sec": max(config.CUT_MIN_SEC, min(sec_cap, _as_int(c.get("estimated_sec")))),
            "visual_type": visual_type,  # 버전에서 강제(모델 값 무시, 레거시 호환)
            "visual_prompt": str(c.get("visual_prompt") or ""),
            # ★ 한글 쌍둥이 — 화면에서 사람이 읽는 용도. 렌더는 위 영어만 쓴다(2026-09-17).
            "visual_prompt_ko": str(c.get("visual_prompt_ko") or ""),
            # 모션 전용(명세 §3-2): motion_source=video 컷의 Veo 프롬프트에 합류. still 컷은 소비 안 함.
            "motion_prompt": str(c.get("motion_prompt") or ""),
            "motion_prompt_ko": str(c.get("motion_prompt_ko") or ""),
            # 길이 보정(수정명세 v1 §3-4): 핑퐁 루프(역재생) 허용 여부. 기본 false(안전측) —
            # 미지정 컷은 홀드 전략으로 강제돼 방향 있는 모션이 역재생으로 망가지지 않는다.
            "loop_safe": bool(c.get("loop_safe", config.CLIP_FIT_LOOP_SAFE_DEFAULT)),
            "style_anchor_ref": str(c.get("style_anchor_ref") or ""),
            "effects": sanitize_effects(c.get("effects")),
            "transition": sanitize_transition(c.get("transition")),
            "bgm_cue": str(c.get("bgm_cue") or ""),
            "source_facts": _str_list(c.get("source_facts")),
            "render_notes": str(c.get("render_notes") or ""),
            # hybrid: 이 컷을 실사 I2V 영상으로 낼지(video) 스틸로 낼지(still). 그 외 버전은 항상 still.
            "motion_source": motion_source,
            # ── 근거밀도·가변길이 개정(수정명세 §4-4) ──
            "claim_ids": claim_ids,
            # 이 컷이 화면으로 옮기는 논증 단위(리포트 라인, 설명엔진 v2 §7). 화이트리스트
            # 재구성이 필드를 떨어뜨리므로 여기에 둔다 — 실재 여부는 report_directive 가
            # 원장과 대조해 거른다(여기서는 draft 를 모른다).
            "reasoning_id": str(c.get("reasoning_id") or ""),
            # 그 논증의 **몇 번째 단계**인가(v3 Phase 5). 이것이 컷↔stage 를 잇는다 —
            # 없으면 코드가 정렬을 지어내야 하고, 그러면 어긋남이 보이지 않는다.
            "reasoning_step": _step_no(c.get("reasoning_step")),
            "evidence_role": role if role in config.EVIDENCE_ROLES else config.DEFAULT_EVIDENCE_ROLE,
            "novelty_event": str(c.get("novelty_event") or ""),
            "beat": visual_router.sanitize_beat(c.get("beat")),
            # ★ 모델이 beat 를 **실제로 말했는가.** 위 정규화가 빈 값을 기본 beat 로 채우므로
            #   이 줄이 없으면 "선언했다"와 "채워 넣었다"를 영영 구분할 수 없다.
            #   비용 산정이 그 구분에 기댄다(_is_code_visual 주석 참조).
            "beat_declared": str(c.get("beat") or "").strip().upper() in config.BEAT_KINDS,
            "motion_value": sanitize_motion_value(c.get("motion_value")),
            "asset_strategy": strategy,
            "visual_reuse_group": str(c.get("visual_reuse_group") or ""),
            "base_asset_ref": str(c.get("base_asset_ref") or ""),
            "state_change": str(c.get("state_change") or ""),
            # 장면 파생(웹툰 v1 §2): 기준 컷 이미지에서 잘라낼 영역(비율)과 색보정. 둘 다
            # 생성 호출 0 — 카메라 이동을 이미지 생성이 아니라 크롭으로 만드는 장치다.
            "crop": crop_val,
            "tone_grade": sanitize_tone_grade(c.get("tone_grade")) if is_reuse
            else config.DEFAULT_TONE_GRADE,
            # §11 근거 오버레이 — 말하지 않고 화면으로 증명하는 카드(M-E3 에서 렌더 배선).
            "overlay_plan": evidence_overlay.normalize_overlay_plan(c.get("overlay_plan")),
            # 화면 역할(2026-08-20): 3D 도해냐 실사냐. 프롬프트 화풍이 여기서 갈린다.
            "visual_role": sanitize_visual_role(c.get("visual_role")),
            # 도해 구조(2026-08-29 리뷰 §5). enum 하나로는 "빛나는 큐브를 든 추상적 인간"을
            # 막을 수 없다 — 무엇이 무엇을 어떻게 바꾸는지를 **필드로** 받아 검사한다.
            "mechanism": sanitize_mechanism(c.get("mechanism")),
            # 사람이 읽는 구조 요약(2026-09-18). 구조 필드는 영어(그림용), 이 줄은 한글(화면용).
            "mechanism_ko": str(c.get("mechanism_ko") or "").strip(),
            # 연출 계약(v2 Phase E2). 클립 안의 작은 편집 시퀀스 — 8초를 **어떻게 쓸지**.
            #   길이는 등급이 정하므로 여기서는 invest 상한(8초)으로 정규화하고,
            #   실제 클립 길이는 렌더가 다시 확정한다.
            "temporal_plan": tplan.normalize(
                c.get("temporal_plan"),
                int(config.tier_profile("invest")["clip_sec"])),
        })

    # ★ 강제 순서가 중요하다(수정명세 §6):
    #   값어치 없는 영상을 먼저 걷어내고(motion_value) → 모드 예산으로 개수를 조이고 →
    #   기존 전역 캡·금액 preflight 을 **마지막 백스톱으로 남긴다**(불변식 퇴행 방지).
    #
    # ★★ 등급제(v2 Phase C) — **조용한 강등을 걷어낸다.**
    #   종전에는 이 네 겹이 전부 `motion_source` 를 말없이 스틸로 바꿨고, 그중 하나는
    #   **컷 순서 선착순**이었다(실측: `컷 9 스틸로 강등`). 그래서 운영자가 "여기 투자해"
    #   라고 등급을 정해도 상한이 말없이 이겼다. 등급제 버전에서는 전부 경고로 바꾸고,
    #   총액 초과는 `cost_plan` → `video_budget_exceeded` 로 **승인 단계에서** 멈춘다.
    tiered = config.tiering_enabled(version)
    tier_warnings: list[str] = []
    enforce_scene_variety(cuts, version)   # ③ 같은 scene_kind 3연속 금지(제자리 교정)
    enforce_motion_value_gate(cuts, declared_motion, tiered=tiered,
                              warnings_out=tier_warnings)
    if not tiered:
        # ★ 선착순 강등은 등급제에서 **호출하지 않는다**(삭제와 같은 효과, 레거시는 보존).
        enforce_mode_video_budget(cuts, mode, version)  # D-E1 모드별 클립 개수
    enforce_video_clip_cap(cuts, version, tiered=tiered, warnings_out=tier_warnings)
    media_policy = sanitize_media_policy(header_in.get("media_policy"))
    # 작업 B 이중 캡(초수·금액) — 렌더(과금) 이전에 강등. 모드가 있으면 모드 예산으로 조인다
    # (D-E1: 모드별 캡이 전역 캡을 대체). 모드가 없으면 전역 캡 그대로.
    _budget = content_mode.resolve_cost_plan(mode)
    # ★ 버전 상향(실사형)이 있으면 초수·금액도 함께 올린다. 개수만 올리면 여기서 다시 잘린다.
    _max_sec, _max_cost = config.video_budget_for(version, _budget)
    preflight_video_budget(cuts, media_policy, _max_sec, _max_cost, version,
                           tiered=tiered, warnings_out=tier_warnings)
    reuse_warnings = validate_reuse_refs(cuts)
    total = sum(c["estimated_sec"] for c in cuts)
    header = {
        "version_type": version,
        "aspect_ratio": str(header_in.get("aspect_ratio") or config.ASPECT_RATIO),
        "global_style": str(header_in.get("global_style") or ""),
        # ⑤ 훅·CTA 트랜스크리에이션(언어별 독립). 직역 금지.
        "hook_ko": str(header_in.get("hook_ko") or ""),
        "hook_en": str(header_in.get("hook_en") or ""),
        "cta_ko": str(header_in.get("cta_ko") or ""),
        "cta_en": str(header_in.get("cta_en") or ""),
        "bgm": {
            "mood": str(bgm_in.get("mood") or ""),
            "track_ref": str(bgm_in.get("track_ref") or ""),
        },
        "media_policy": media_policy,  # 작업 B(§8.2) — 영상 생성 정책
        "total_estimated_sec": total,
        # 훅·리텐션 개정 v2 — 통제 어휘 강제 + 정합/근거강도 자기검증(§4·§5).
        "hook_type": _sanitize_enum(header_in.get("hook_type"), config.HOOK_TYPES, config.DEFAULT_HOOK_TYPE),
        "hook_reframe_angle": _sanitize_enum(
            header_in.get("hook_reframe_angle"), config.HOOK_ANGLES, config.DEFAULT_HOOK_ANGLE),
        "hook_promise_check": normalize_hook_promise_check(header_in.get("hook_promise_check")),
        "science_reliability": normalize_science_reliability(header_in.get("science_reliability")),
        "cta_type": _sanitize_enum(header_in.get("cta_type"), config.CTA_TYPES, config.DEFAULT_CTA_TYPE),
        "loop_match": bool(header_in.get("loop_match", False)),
        "series_id": str(header_in.get("series_id") or ""),
        # ── 근거밀도·가변길이 개정(수정명세 §4-4) ──
        "content_mode": mode,
        "primary_claim_id": str((content_plan or {}).get("primary_claim_id")
                                or header_in.get("primary_claim_id") or ""),
        "supporting_claim_ids": list((content_plan or {}).get("supporting_claim_ids")
                                     or _str_list(header_in.get("supporting_claim_ids"))),
        "essential_evidence_units": list((content_plan or {}).get("essential_evidence_units")
                                         or _str_list(header_in.get("essential_evidence_units"))),
        "target_duration_min_sec": content_mode.duration_range(mode)[0],
        "target_duration_max_sec": content_mode.duration_range(mode)[1],
        "duration_reason": str((content_plan or {}).get("duration_reason")
                               or header_in.get("duration_reason") or ""),
        "retention_plan": _normalize_retention_plan(header_in.get("retention_plan")),
    }
    # 커버리지·비용은 **컷에서** 계산한다(헤더가 써 보낸 값은 쓰지 않는다).
    header["evidence_coverage"] = content_mode.compute_evidence_coverage(
        cuts,
        required_claim_ids=tuple(
            x for x in [header["primary_claim_id"], *header["supporting_claim_ids"]] if x),
        primary_claim_id=header["primary_claim_id"],
    )
    # ★ 시점 오류(§21) — 논문이 미래로 쓴 일을 제작 시점에도 미래로 읽는 컷.
    #   기존 게이트가 못 보던 종류다: `cut_detail_not_in_source` 는 "원문에 있는 말인가"를
    #   보는데, 이 문장은 **원문에 있다**. 원문에 있는 것이 지금도 참인지는 아무도 안 물었다.
    #   ★ 경고로 둔다 — 어휘로 시제를 판정하는 것은 오탐이 크고, 실제 지시서에서 오탐률을
    #     보고 나서 차단으로 올릴지 정한다(world_drift·text_burn_in 과 같은 자리).
    stale_warnings = temporal_context.warnings_for(
        cuts, temporal_context.published_year_of(fact_sheet))
    # ★ 관계 환각(리뷰 §14) — 원문에 없는 관계를 화면이 지어내는 컷.
    #   §21 과 같은 이유로 경고다: 어휘가 어디를 볼지만 정하고 원문 대조가 판정하지만,
    #   실제 지시서에서 오탐률을 보기 전에는 차단으로 올리지 않는다.
    relation_warnings = ungrounded_relation_cuts(cuts, source_text, fact_sheet)
    header["mode_warnings"] = sorted(set(
        [*(content_plan or {}).get("mode_warnings", []), *reuse_warnings, *crop_warnings,
         *tier_warnings, *stale_warnings, *relation_warnings,
         *content_mode.duration_warnings(content_plan, total)]))
    # ★ 실사형 화면 계약(2026-08-29 리뷰 §4). 기존 게이트는 비용·길이·claim 만 봤고 화면은
    #   아무도 검사하지 않았다 — 계약을 6곳 어긴 지시서가 그대로 승인 가능이었다.
    #   사유는 **기존 키(block_reasons/mode_warnings)에 합류**시킨다. 승인 화면·라우트가 이미
    #   그 둘을 보므로 새 표면을 만들지 않는다(설명판형이 쓰던 방식과 같다).
    # ★ 순서 주의(2026-08-29 실측 버그): 훅 중복 제거를 **게이트보다 먼저** 돌린다.
    #   반대로 두면 게이트가 "훅 있음"으로 통과시킨 뒤 이 함수가 훅을 비워, 빈 훅이 사유
    #   없이 승인 가능 상태로 나간다(실제로 그렇게 나갔다).
    _drop_hook_duplicating_first_cut(header, cuts)
    # ★ 인접 컷이 같은 문장을 되풀이하면 한 번만 남긴다(2026-09-14 운영자 실측 — 아래 함수 주석).
    repeated = _drop_repeated_narration(cuts)
    if repeated:
        header["mode_warnings"] = sorted(set([*header.get("mode_warnings", []),
                                              "narration_repeat_removed:" + ",".join(repeated[:6])]))
    # ★ 시각 시퀀스 정규화 + 계약. 시퀀스가 없으면 아무 일도 하지 않는다(D6 — 옛 지시서 불변).
    sequences = visual_sequence.normalize_all(obj.get("visual_sequences"))
    # ★ 앞 stage 에 없던 선언 개체를 물려받았다고 적은 것은 코드가 APPEAR 로 옮긴다
    #   (2026-09-14 — 저장 지시서 24% 가 이것으로 막혔고 전부 기계 수리 가능했다. 함수 주석).
    #   라우팅·비트 채우기보다 **먼저** 돌린다 — 둘 다 stage 의 mutations 를 읽는다.
    lineage_fixed = visual_sequence.repair_lineage_appears(sequences)
    if lineage_fixed:
        header["mode_warnings"] = sorted(set([*header.get("mode_warnings", []),
                                              "vseq_lineage_appear_inserted:"
                                              + "; ".join(lineage_fixed[:6])]))
    vseq: dict[str, Any] = {}
    depth = visual_router.source_depth_of(fact_sheet)
    routed = visual_router.route_all(cuts, source_depth=depth, sequences=sequences)

    # ★ 라우팅은 **코드가 정한다**(v3 Phase 2). LLM 은 beat 라벨만 달았다.
    #   ★★ 순서 주의: **시퀀스를 먼저 정규화한 뒤** 라우팅한다. 반대로 두면 라우터가
    #      시퀀스를 못 보고 beat 고정표만으로 판정하는데, 골든 실측(2026-08-29)에서
    #      그것이 정확히 실패했다 — 시퀀스 stage 인 컷 8개가 전부 차트로 빠졌다.
    for c, r in zip(cuts, routed):
        # ★★ `resolved_visual_plan` 이 **정본**이다(코덱스 리뷰 R3, 2026-08-30).
        #    종전에는 visual_role·visual_treatment·photo_contract·visual_router 넷이 각자
        #    최종 판정권을 갖는 것처럼 보였고, 실제로 서로 다른 답을 냈다. Phase 3 렌더러가
        #    무엇을 믿을지 지금 못박지 않으면 "schema 필드를 renderer 가 무시한다"가 그대로
        #    재현된다. 계약·비용·렌더·QA 가 **이 객체 하나**를 소비한다.
        c["resolved_visual_plan"] = r
        # ★ 화면 계약이 어휘가 아니라 **구조**를 볼 수 있게 stage 의 변이를 컷에 붙인다
        #   (코덱스 리뷰 §14). 정본은 header.visual_sequences 이고 여기 있는 것은 사본이다.
        stage = visual_sequence.cut_to_stage(sequences).get(int(c.get("cut_no") or 0)) or {}
        c["stage_mutations"] = list(stage.get("mutations") or [])
        # 하위호환 — 옛 필드를 읽는 화면·테스트가 있다. 정본에서 파생시킨다.
        c["visual_treatment"] = r["base"]
        c["routing_reasons"] = r["reasons"]
    header["visual_routing"] = {**visual_router.routing_summary(routed),
                                "source_depth": depth}

    # ★ 시퀀스 계약은 **라우팅 뒤**에 돈다 — 정본(resolved plan)과 옛 역할 선언의 충돌을
    #   보려면 둘 다 있어야 한다(적대적 자기리뷰 Q4).
    if sequences:
        header["visual_sequences"] = sequences
        vseq = visual_sequence_contract.evaluate(sequences, cuts,
                                                 source_depth=depth, routed=routed)
        header["visual_sequence_gate"] = vseq
        header["mode_warnings"] = sorted(set([*header["mode_warnings"], *vseq["warnings"]]))

    # ★★ 비용은 **라우팅이 끝난 뒤** 계산한다(코덱스 리뷰 §15, 2026-08-30).
    #    실측: 골든 두 편 모두 `visual_routing.CODE_VIZ` 가 4·3 인데 `cost_plan.code_viz_count`
    #    는 0 이었다. compute_cost_plan 이 라우팅보다 **먼저** 돌았고, 게다가 라우터 판정이
    #    아니라 모델이 쓴 asset_strategy 를 세고 있었다 — ⑤ 확인 모달이 보는 총액이 실제
    #    계획과 다른 것을 보고 있었다는 뜻이다. 순서를 고정한다:
    #      Evidence → Beat → Sequence → State Ledger → Routing → Resolved Plan
    #        → Contract → Cost Plan → Render
    # ★ 시퀀스를 넘긴다 — 등급 판정이 렌더와 **같은 입력**을 봐야 예상과 실제가 맞는다.
    # ★★ [비트는 코드가 채운다 — 2026-09-12 운영자 지시] 실측: 최근 실사형 지시서 10편·컷 124개
    #   중 invest 는 **1개**뿐이었고 81개(65%)가 `temporal_contract_unmet` 하나로만 탈락했다.
    #   비트는 `video.build_motion_prompt` 가 프롬프트에 싣는 값이라, 비트가 1개면 8초를 놓칠
    #   뿐 아니라 **화면이 실제로 덜 움직인다**(첫 실물 렌더에서 영상 7컷이 전부 "거의 정지").
    #   프롬프트·되먹임이 이미 2~3개를 요구하는데도 모델이 1개를 쓰는 이유는 구조상 닭과 달걀이다
    #   (어느 컷이 invest 인지는 코드가 나중에 정한다) — 그래서 코드가 채운다.
    #   ★ 지어내지 않는다: stage 에 **이미 선언된 mutations** 로만 만든다. 선언이 없으면 비워 두고
    #     그 컷은 강등된다(내용 문제는 위 프롬프트·되먹임이 푼다).
    #   ★ 비용 산정보다 **먼저** 돌린다 — 등급이 오르면 후보가 2발이 되어 영상비가 오르는데,
    #     뒤에 두면 ⑤ 확인 모달이 옛 등급으로 계산한 총액을 보여 준다.
    if version == "photo" and sequences:
        stage_by_cut = visual_sequence.cut_to_stage(sequences)
        min_beats = int(config.tier_profile("invest").get("min_beats") or 2)
        beats_filled: list[int] = []
        for c in cuts:
            if str(c.get("motion_source") or "") != "video":
                continue
            if len(c.get("temporal_plan") or []) >= min_beats:
                continue
            stage_of_cut = stage_by_cut.get(int(c.get("cut_no") or 0)) or {}
            got = tplan.beats_from_stage(c, stage_of_cut) if stage_of_cut else []
            if got:
                c["temporal_plan"] = got
                beats_filled.append(int(c.get("cut_no") or 0))
        if beats_filled:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_temporal_beats_backfilled:"
                + ",".join(str(x) for x in beats_filled[:8])]))

        # ★★ [코드가 못 고치는 나머지는 되물어야 한다] 비트는 코드가 채울 수 있지만 **무엇이
        #   변하는지**는 못 지어낸다. stage 가 APPEAR·HIGHLIGHT 만 선언하면 그 컷은 8초를 못 받고
        #   화면도 거의 안 움직인다(실측 2026-09-12: 재생성 뒤에도 13컷 중 12컷이 이 이유 하나).
        #   재생성 가능 경고로 올려 모델에게 처방과 함께 되묻는다(config.RETRYABLE_QUALITY_WARNINGS).
        flat_stages: list[str] = []
        for seq in sequences:
            if str(seq.get("sequence_role") or "") != "MECHANISM_SEQUENCE":
                continue
            for st in (seq.get("stages") or []):
                ops = {str(m.get("operation") or "").upper()
                       for m in (st.get("mutations") or []) if isinstance(m, dict)}
                if ops and not (ops & set(config.TRANSFORMING_MUTATIONS)):
                    flat_stages.append(str(st.get("stage_id") or "?"))
        if flat_stages:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_stage_no_transformation:" + ", ".join(flat_stages[:6])]))

    header["cost_plan"] = compute_cost_plan(cuts, mode, version,
                                            header.get("visual_sequences") or [])
    header["mode_warnings"] = sorted(set([*header["mode_warnings"],
                                          *directive_warnings(header, cuts)]))

    photo_gate: dict[str, Any] = {}
    if version == "photo":
        # ★★ 실사형은 컷마다 화풍 역할이 있어야 렌더가 그림을 고를 수 있다. 모델이 비워 두면
        #   승인이 막히는데, **연결·CTA 컷**에서 반복해서 비었다(실측: 컷 9 "즉, 단순히
        #   체중 감소 효과를 넘어선다는 거죠" → visual_role="" 로 두 번 연속 차단).
        #   연결 문장은 정의상 도해가 아니므로 REALITY 가 옳은 답이다 — 막을 이유가 없다.
        # ★ 조용히 채우지 않는다. 경고로 남겨 모델이 계속 비우는지 보이게 한다.
        #   sanitize_visual_role 은 공유 함수라 건드리지 않는다(다른 버전 화풍이 바뀐다).
        # ★★ [영상비를 내고 정지 화면을 받지 않는다] motion_source='video' 인데 비트의
        #   카메라가 전부 HOLD 인 컷은 **마지막 비트를 DOLLY_IN 으로 바꾼다.**
        #
        #   왜 코드가 고치나: 실측 히트율 57%(지시서 26개 중 15개, 컷 36개)다. 차단으로
        #   올리면 재시도가 잦아지고, 재시도 뒤에도 남으면 오히려 승인이 막힌다.
        #   프롬프트로도 지시하지만(§영상 컷은 카메라가 움직여야 한다) 매번 한둘이 샌다.
        #   ★ 왜 하필 DOLLY_IN 인가: 벤치마크가 공개한 제작 공식이 "횡이동 → 마지막 급속
        #     푸시인"이고, 달 클립 실측에서도 마지막 비트가 DOLLY_IN 이었다. 어떤 장면에도
        #     안전하게 얹히는 유일한 동작이다(TRACK·ORBIT 은 공간을 가정한다).
        #   ★ 조용히 하지 않는다 — 경고로 남겨 모델이 계속 HOLD 만 쓰는지 보이게 한다.
        stilled: list[int] = []
        for c in cuts:
            beats = c.get("temporal_plan") or []
            if (str(c.get("motion_source") or "") == "video" and beats
                    and all(str(b.get("camera") or "").upper() == "HOLD" for b in beats)):
                beats[-1]["camera"] = "DOLLY_IN"
                stilled.append(int(c.get("cut_no") or 0))
        if stilled:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_video_camera_repaired:" + ",".join(str(x) for x in stilled[:6])]))

        blank = [c for c in cuts if not str(c.get("visual_role") or "").strip()]
        for c in blank:
            c["visual_role"] = config.PHOTO_DEFAULT_VISUAL_ROLE
        if blank:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_visual_role_backfilled:"
                + ",".join(str(c.get("cut_no")) for c in blank[:6])]))

        # ★★ [렌즈 어휘는 코드가 걷어낸다] 2026-09-07 실측: 프롬프트에 금지와 대안을 둘 다
        #   적고 재생성을 두 번 돌렸는데 모델이 **부분만** 지켰다(world 3개 중 1개).
        #   어휘 치환은 기계가 확실히 하는 일이다 — 모델에게 반복시키며 재시도 비용을 내는
        #   것은 설계 실패다. `photo_video_camera_repaired` 와 같은 자세로 고치고 남긴다.
        #   ★ 화풍 **선언** 어휘(stylized·3D render)는 여기서 고치지 않는다 — 단어를 지워도
        #     모델이 그 장면을 삽화로 구상했다는 사실은 남는다. 그건 게이트가 돌려보낸다.
        # ★★ [전 컷 일관성 앵커는 코드가 정한다] 2026-09-08 운영자 지시("저 화풍으로 고정").
        #   `global_style` 은 이미지·영상 프롬프트의 **맨 앞**에 붙는데 출력 스키마가 LLM 에게
        #   "화풍/톤 앵커 한 줄"을 시켜서, 편마다 다른 화풍 선언이 맨 앞에 왔다
        #   (실측: "Scientific realism, clean laboratory aesthetic, natural light").
        #   화풍이 정해지는 자리가 하나 더 있었던 것이고, 그러면 화면이 편마다 달라진다.
        #   실사형에서는 코드가 덮어쓴다 — 다른 버전(만화식 등)은 손대지 않는다.
        header["global_style"] = config.PHOTO_GLOBAL_STYLE

        optics_fixed = photo_contract.normalize_optics(header, cuts)
        if optics_fixed:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_optics_normalized:" + ", ".join(optics_fixed[:6])]))
        # ★ 위 주석의 예외 — `stylized` 만은 코드가 지운다(2026-09-11 운영자 지시).
        #   형용사라 지워도 장면이 남는다. 근거: config.PHOTO_STYLE_WORD_REWRITES.
        style_fixed = photo_contract.normalize_style_words(header, cuts)
        if style_fixed:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_style_word_normalized:" + ", ".join(style_fixed[:6])]))
        # ★ 카드가 이미 그리는 퍼센트 수치는 이미지 프롬프트에서 코드가 지운다(2026-09-14 —
        #   같은 논문 세 편 연속 같은 차단, 세 번 다 손으로 숫자만 지웠다. 함수 주석).
        numbers_fixed = photo_contract.normalize_prompt_numbers(cuts)
        if numbers_fixed:
            header["mode_warnings"] = sorted(set([
                *header.get("mode_warnings", []),
                "photo_prompt_number_removed:" + ", ".join(numbers_fixed[:6])]))

        photo_gate = photo_contract.evaluate(header, cuts, fact_sheet)
        header["photo_gate"] = photo_gate
        header["mode_warnings"] = sorted(set([*header["mode_warnings"],
                                              *photo_gate["warnings"]]))
    # ★★ [지시서 ↔ 기초 자료 대조] 여기가 마지막 관문이다 — 이 뒤로는 아무도 안 본다.
    #   selfcheck 는 **초안**에서만 돌았는데 지시서 LLM 이 나레이션을 다시 쓰고
    #   운영자가 화면에서 또 고친다. 훅이 가장 많이 바뀌고 가장 과장되기 쉬운 자리다.
    #   ① 기계 판정(무료) ② 의미 판정(LLM 1회). 둘 다 경고이며 승인을 막지 않는다.
    if config.DIRECTIVE_AUDIT_ENABLED:
        audit = directive_audit.audit(header, cuts, fact_sheet)
        header["directive_audit"] = audit
        if audit["findings"]:
            header["mode_warnings"] = sorted(set([
                *header["mode_warnings"],
                *(f"audit_{f['code']}:{f['cut_no']}" for f in audit["findings"])]))
            log.info("근거 대조: 빨강 %d 노랑 %d",
                     audit["stats"]["red"], audit["stats"]["yellow"])
    if config.DIRECTIVE_SELFCHECK_ENABLED and (fact_sheet or {}).get("claims"):
        try:
            # 컷을 selfcheck 가 아는 씬 모양으로 넘긴다 — 최종 나레이션 그대로 본다.
            scenes = [{"scene_no": c.get("cut_no"), "narration_ko": c.get("narration_ko"),
                       "narration_en": c.get("narration_en")} for c in cuts]
            sc = selfcheck.check(fact_sheet, scenes, content_plan,
                                 header.get("total_estimated_sec"))
            header["directive_selfcheck"] = sc
            flags = [s2 for s2 in (sc.get("scenes") or []) if s2.get("grounded") is False]
            if flags:
                header["mode_warnings"] = sorted(set([
                    *header["mode_warnings"],
                    "directive_ungrounded:" + ",".join(
                        str(s2.get("scene_no")) for s2 in flags[:6])]))
                log.warning("최종 나레이션 근거 미확인 %d컷: %s", len(flags),
                            [s2.get("scene_no") for s2 in flags[:6]])
        except Exception as exc:      # 검증 실패가 생성을 죽이면 안 된다
            log.warning("지시서 자기검증 실패(무시하고 진행): %s", str(exc)[:120])
            header["mode_warnings"] = sorted(set([*header["mode_warnings"],
                                                  "directive_selfcheck_failed"]))

    # ★ 대조가 돌지 않은 초안이면 그 사실을 남긴다(차단 아님) — 버전 무관.
    header["mode_warnings"] = sorted(set([*header["mode_warnings"],
                                          *claim_evidence_warnings(fact_sheet)]))
    header["block_reasons"] = sorted(set([
        *directive_block_reasons(header, cuts, content_plan, fact_sheet,
                                 routed=routed, source_text=source_text),
        *photo_gate.get("block_reasons", []),
        *vseq.get("block_reasons", []),
    ]))
    header["approval_blocked"] = bool(header["block_reasons"])
    return {"version_type": version, "header": header, "cuts": cuts}


def _hook_text_key(text: str) -> str:
    """훅·나레이션 비교용 정규화 — 공백·문장부호·말줄임 차이는 같은 문장으로 본다."""
    import re
    return re.sub(r"[\s\.\!\?…·,'\"“”‘’]+", "", str(text or "")).strip()


def _drop_hook_duplicating_first_cut(header: dict[str, Any], cuts: list[dict[str, Any]]) -> None:
    """1컷 나레이션과 사실상 같은 훅은 비운다 — 화면에 같은 문장이 두 번 뜨는 것을 막는다.

    왜: 상단 헤더(시리즈 제목 + 훅)는 영상 **전 구간** 떠 있고, 하단 자막은 컷 나레이션을
    따라간다(engine/subtitles.build_ass). 그래서 훅과 1컷 나레이션이 같으면 영상 시작 몇 초
    동안 위아래에 똑같은 문장이 겹쳐 보인다. 프롬프트 스키마가 훅을 `"<한국어 훅>"` 한 줄로만
    정의해 모델이 1컷 나레이션을 그대로 복사하는 일이 잦다(리포트 라인 실측 2/2, 논문 6/57).

    비우면 상단은 시리즈 제목만 남는다 — 훅이 빈 지시서(논문 16/57)에서 이미 쓰이는 표시다.
    ★ 삭제가 아니라 화면 표시만 생략한다: 컷 나레이션에 같은 문장이 그대로 남아 있으므로
      훅 문구가 소실되지 않는다.
    """
    if not cuts:
        return
    first = _hook_text_key(cuts[0].get("narration_ko"))
    if not first:
        return
    for key in ("hook_ko", "hook_en"):
        # EN 훅은 EN 나레이션과 비교해야 한다(언어를 섞어 비교하면 절대 안 걸린다).
        target = first if key == "hook_ko" else _hook_text_key(cuts[0].get("narration_en"))
        if target and _hook_text_key(header.get(key)) == target:
            header[key] = ""


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_REPEAT_MIN_KEY = 8          # 이보다 짧은 조각("네.", "즉,")은 우연히 겹칠 수 있어 보지 않는다


def _drop_repeated_narration(cuts: list[dict[str, Any]]) -> list[str]:
    """인접한 두 컷이 **같은 문장**을 읽으면 한 번만 남긴다 → 고친 자리 목록("3>4" 꼴).

    무엇을 푸는가(2026-09-14 운영자 실측): 컷 3 나레이션 끝이 "이 중 무려 824개는 이전에 보고되지
    않은 새로운 변이입니다."였고 컷 4 가 **그 문장 하나를 통째로** 다시 읽었다. 영상에서
    "824개는 새로운 변이입니다"가 두 번 나왔고, 렌더가 끝난 뒤 영상을 잘라서야 고칠 수 있었다.
    저장 지시서 인접 컷 603쌍 중 2쌍(2편)이었다 — 드물지만 들리는 순간 영상이 망가진다.

    규칙(결정론적, 지어내지 않는다 — 문장을 **빼기만** 한다):
      ① 반복 문장이 한쪽 컷의 **유일한 내용**이면 그 컷에 남기고 다른 컷에서 뺀다.
         그 컷은 그 문장을 위해 만든 화면(표지 강조·숫자 카드)이다.
      ② 둘 다 다른 내용도 있으면 **뒤 컷**에서 뺀다 — 처음 말한 자리를 지킨다.
      ③ 빼고 나서 나레이션이 비면 빼지 않는다(컷을 벙어리로 만들지 않는다).
    ko·en 을 따로 본다 — 한쪽 언어만 반복되는 경우도 있다.
    """
    def sentences(text: Any) -> list[str]:
        return [s for s in _SENTENCE_SPLIT.split(str(text or "").strip()) if s.strip()]

    def keyed(parts: list[str]) -> list[tuple[str, str]]:
        return [(s, _hook_text_key(s)) for s in parts]

    ordered = sorted(cuts, key=lambda c: int(c.get("cut_no") or 0))
    touched: list[str] = []
    for field in ("narration_ko", "narration_en"):
        for prev, cur in zip(ordered, ordered[1:]):
            ps, cs = keyed(sentences(prev.get(field))), keyed(sentences(cur.get(field)))
            shared = ({k for _, k in ps if len(k) >= _REPEAT_MIN_KEY}
                      & {k for _, k in cs if len(k) >= _REPEAT_MIN_KEY})
            if not shared:
                continue
            cur_only = all(k in shared for _, k in cs)
            prev_only = all(k in shared for _, k in ps)
            if cur_only and not prev_only:
                target, keep = prev, ps           # ① 뒤 컷이 그 문장 전용 → 앞 컷에서 뺀다
            else:
                target, keep = cur, cs            # ①(앞 컷 전용) 또는 ② → 뒤 컷에서 뺀다
            remaining = [s for s, k in keep if k not in shared]
            if not remaining:
                continue                          # ③ 벙어리 컷은 만들지 않는다
            target[field] = " ".join(remaining)
            touched.append(f"{prev.get('cut_no')}>{cur.get('cut_no')}"
                           + ("" if field == "narration_ko" else "(en)"))
    return touched


def _normalize_retention_plan(obj: Any) -> dict[str, Any]:
    """리텐션 계획 정규화. 간격 상한은 config 가 정본이라 모델 값을 받지 않는다."""
    d = obj if isinstance(obj, dict) else {}
    nos: list[int] = []
    for x in (d.get("pattern_interrupt_cut_nos") or []):
        try:
            nos.append(int(x))
        except (TypeError, ValueError):
            continue
    return {
        "novelty_interval_max_sec": config.RETENTION_MAX_NO_NOVELTY_SEC,
        "payoff_start_ratio": config.RETENTION_PAYOFF_START_RATIO,
        "open_loop": str(d.get("open_loop") or ""),
        "pattern_interrupt_cut_nos": nos,
    }


def ungrounded_cuts(directive: dict[str, Any]) -> list[int]:
    """근거(source_facts) 없는 컷 번호 목록. 승인 화면 빨간 표시 기준(환각 방지)."""
    return [c["cut_no"] for c in directive.get("cuts", []) if not c.get("source_facts")]


def _source_text_for(draft_row: dict[str, Any]) -> str:
    """구체성 대조에 쓸 원문. 전문이 없으면 초록 — 그것도 없으면 빈 문자열(게이트가 안 돈다).

    ★ 원문이 없을 때 **빈 문자열을 돌려주는 것이 계약**이다. unsupported_detail_cuts 는
      빈 원문이면 아무것도 차단하지 않는다 — 확보 실패를 위반으로 기록하지 않기 위해서다.
    """
    try:
        paper = draft_row.get("paper") or db.get_paper(str(draft_row.get("paper_id") or "")) or {}
        packet = db.get_paper_source(str(paper.get("external_id") or "")) or {}
    except Exception as exc:                   # noqa: BLE001 — 조회 실패는 치명적이지 않다
        log.warning("구체성 대조를 건너뛴다(원문 조회 실패): %s", exc)
        return ""
    return str(packet.get("text") or paper.get("abstract") or "")


# ★★ 되먹임 대상은 **계약 두 벌 모두**다(2026-08-31).
#
#   종전에는 재생성이 `header.photo_gate` 만 봤다. 그런데 승인 차단은 세 곳에서 나온다
#   (normalize_directive: directive_block_reasons + photo_gate + visual_sequence_gate).
#   결과가 둘이었다:
#     ① 시각 시퀀스 계약**만** 위반한 지시서는 `first_reasons` 가 비어
#        **재생성이 아예 돌지 않았다** — 그대로 사람 검수로 갔다.
#     ② 둘 다 위반해도 모델은 시퀀스 쪽 처방을 못 들었다.
#   `visual_sequence_contract.feedback_prompt` 는 **아무 데서도 불리지 않았다** —
#   만들어 놓고 한쪽만 연결한 것이 이 저장소에서 또 한 번 나왔다.
#
#   ★ `directive_block_reasons` 는 일부러 넣지 않는다. 거기엔 예산 초과·원문 미확보처럼
#     **다시 물어봐야 고쳐지지 않는** 사유가 섞여 있고, 처방 어휘도 아직 없다.
#     되먹일 문장이 없는 사유로 재생성을 돌리면 유료 호출만 한 번 더 나간다.
#     (그 사유들은 approval_blocked 로 남아 사람 검수로 간다 — 차단은 그대로다.)
def _contract_reasons(directive: dict[str, Any]) -> list[str]:
    """되먹일 수 있는 계약 위반만 모은다(photo + 시각 시퀀스 + 빠진 필수 주장)."""
    header = directive.get("header") or {}
    # ★ 빠진 필수 주장도 되먹인다(2026-09-14). 승인은 막으면서 재생성·처방이 없어서
    #   성격 유전 원본(b699ba0b)은 운영자가 컷 12 나레이션에 C04 를 손으로 넣었다.
    #   게이트 셋(검사·고지·되먹임) 중 되먹임만 빠져 있던 자리다.
    missing = (header.get("evidence_coverage") or {}).get("missing_claim_ids") or []
    return sorted({
        *((header.get("photo_gate") or {}).get("block_reasons") or []),
        *((header.get("visual_sequence_gate") or {}).get("block_reasons") or []),
        *(["missing_required_claims:" + ",".join(str(x) for x in missing)] if missing else []),
    })


def missing_claims_feedback(directive: dict[str, Any],
                            fact_sheet: dict[str, Any] | None) -> str:
    """빠진 필수 주장 → **번호와 Fact Sheet 원문**을 되먹인다. 없으면 빈 문자열.

    ★ 번호만 주면 모델은 무슨 말을 넣어야 할지 모른다 — 지어낸다. 원문을 준다.
    ★ 새 컷을 만들라고 하지 않는다: 그 주장을 떠받치기에 가장 가까운 기존 컷의 나레이션에
      싣고 claim_ids 에 넣으라고 한다(운영자 손 수정과 같은 방식, 구조를 갈아엎지 않게).
    """
    header = directive.get("header") or {}
    missing = [str(x) for x in ((header.get("evidence_coverage") or {})
                                .get("missing_claim_ids") or [])]
    if not missing:
        return ""
    text = {str(c.get("claim_id") or ""): str(c.get("claim_ko") or c.get("text") or "").strip()
            for c in ((fact_sheet or {}).get("claims") or []) if isinstance(c, dict)}
    lines = [f"  · {cid}: {text.get(cid) or '(Fact Sheet 문장 없음 — 번호만 맞춰라)'}"
             for cid in missing]
    return ("\n\n[빠진 필수 주장] 아래 주장을 **어느 컷도 지불하지 않아** 승인이 막혔다.\n"
            + "\n".join(lines)
            + "\n- 새 컷을 만들지 말고, 그 내용에 가장 가까운 기존 컷의 나레이션(KO·EN)에 위 문장의"
              " 내용을 한 문장으로 싣고 그 컷의 claim_ids 에 번호를 넣어라."
              " 문장에 없는 수치·해석을 덧붙이지 마라. 나머지 컷·시퀀스는 그대로 둬라.")


def _quality_retry_reasons(directive: dict[str, Any]) -> list[str]:
    """**경고인데도 재생성을 띄우는** 사유들 (2026-09-09 외부 리뷰).

    ★ 왜 필요한가: `photo_subject_dominates` 는 정확한 처방 문장을 이미 갖고 있는데
      모델에게 한 번도 전달되지 않았다 — `feedback_prompt` 이 차단 없으면 빈 문자열을
      돌려주고, `generate()` 가 차단·등급미달 없으면 재생성을 안 하기 때문이다.
      이번 문제("연구 대상이 화면의 51%")를 감지하고 고칠 말도 갖고 있었는데 말을 안 걸었다.

    ★★ **승인 차단이 아니다.** 계약은 "경고 → 재생성 1회 → 그래도 남으면 경고인 채로
      사람에게 보여준다". 오탐이 생산을 막지 않는다는 기존 철학을 그대로 지킨다.
    """
    header = directive.get("header") or {}
    warns = [*((header.get("photo_gate") or {}).get("warnings") or []),
             *(header.get("mode_warnings") or [])]
    return sorted({w for w in warns
                   if str(w).split(":", 1)[0] in config.RETRYABLE_QUALITY_WARNINGS})


def _contract_feedback(directive: dict[str, Any]) -> str:
    """세 계약의 처방을 한 번에 붙인다(photo · 시퀀스 · TC-1 연출계약)."""
    header = directive.get("header") or {}
    pg = header.get("photo_gate") or {}
    vg = header.get("visual_sequence_gate") or {}
    return (photo_contract.feedback_prompt(list(pg.get("block_reasons") or []),
                                           pg.get("warnings"))
            + visual_sequence_contract.feedback_prompt(list(vg.get("block_reasons") or []))
            # ★ TC-1(작업명세서 §3): "미달 → 재생성 1회 → standard 강등 + 경고".
            #   종전에는 재생성이 없어서 **바로 강등**됐다 — 명세와 달랐다.
            #
            # ★★ **차단 사유가 있을 때는 얹지 않는다**(2026-09-03 실측). 되먹임을 쌓았더니
            #   재생성이 파괴적으로 변했다:
            #       차단 되먹임만  → 1차 5건 → 2차 3건 (개선)
            #       TC-1 을 얹음  → 1차 3건 → 2차 **14건** (악화)
            #     새로 생긴 위반: vseq_no_actual_mutation · vseq_no_progression ·
            #     vseq_state_lineage_mismatch — 모델이 시퀀스를 통째로 다시 쓰면서
            #     진행 선언을 깨뜨렸다. 한 번에 여러 가지를 고치라고 하면 구조를 갈아엎는다.
            #   우선순위가 다르다: 차단은 **승인을 막는 것**이고 TC-1 은 8초 vs 4초 최적화다.
            #   차단부터 풀고, 계약 부족은 그다음 생성에서 다룬다.
            + ("" if _contract_reasons(directive) else tplan.shortfall_feedback(
                sequence_tier.contract_shortfall(directive.get("cuts") or [], header),
                directive.get("cuts") or [])))


def generate(draft_row: dict[str, Any], version_type: str) -> dict[str, Any]:
    """대본 행 + 버전 → 정규화된 지시서 dict.

    ★ 계약 위반이면 **1회만** 다시 만든다(2026-08-29 리뷰 §7). 되먹임은 "다시 만들어라"가
      아니라 무엇이 왜 틀렸고 어떻게 고치는지다(photo_contract.feedback_prompt).

    ★ 재생성 후에도 **같은 코드 검사를 다시 돌린다.** 모델이 "고쳤다"고 말하는 것은 근거가
      아니다 — 이 저장소의 자세 그대로다. 두 번째도 위반이면 자동 승인을 막고(approval_blocked)
      사람 검수로 보낸다. 덜 나쁜 쪽(사유가 적은 쪽)을 남겨 운영자가 고칠 거리를 줄인다.
    """
    # ★ 골격을 프롬프트에 넣기만 하고 지켰는지 보지 않으면 모델은 대본 씬 리듬으로 돌아간다
    #   (실측: 11칸을 줬는데 7컷). 지시는 검사되지 않으면 지켜지지 않는다.
    skeleton = (cut_skeleton.build(draft_row.get("script_md") or "", version_type=version_type)
                if (config.CUT_SKELETON_ENABLED and version_type == "photo") else [])
    # ★★ 근거 원장을 **지금 계약으로 다시 찍는다**(코덱스 리뷰 §4). LLM 호출 0건·무료다.
    #    이걸 안 하면 초안 때 박힌 낡은 판정이 정상 컷을 계속 차단한다(골든B 실측 4컷).
    fact_sheet = refresh_claim_evidence(draft_row)
    source_text = _source_text_for(draft_row)

    def _once(feedback: str = "") -> dict[str, Any]:
        set_text_purpose("directive")     # 비용 원장의 용도 라벨(engine/llm.py)
        obj = call_json(
            model=config.MODEL_DIRECTIVE,
            system=DIRECTIVE_SYSTEM_BASE,
            user=directive_user_prompt(draft_row, version_type) + feedback,
            # 컷마다 근거·모션·에셋 필드가 늘어 출력이 약 900토큰 커졌다. 너무 낮으면 잘림 →
            # JSON 파싱 실패 → 재시도 1회 → 하드 에러(파이프라인 정지)라 소프트 저하가 아니다.
            # ★ 상수로 뺐다(2026-08-29): 8192 가 코드에 박혀 있어 **Anthropic 경로만** 잘렸다.
            #   Gemini pro 는 자체 하한을 받아 같은 프롬프트가 살아남았다 — 백엔드에 따라
            #   죽고 사는 것은 상한이 잘못 놓였다는 뜻이다. 근거는 config 주석.
            max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS,
        )
        d = normalize_directive(
            obj, version_type,
            fact_sheet=fact_sheet,
            content_plan=(draft_row.get("video_flow") or {}).get("content_plan"),
            source_text=source_text,
        )
        short = cut_skeleton.shortfall(skeleton, d["cuts"])
        if short:
            gate = d["header"].setdefault("photo_gate", {"block_reasons": [], "warnings": []})
            gate["block_reasons"] = sorted({*gate.get("block_reasons", []), short})
            d["header"]["block_reasons"] = sorted({*d["header"]["block_reasons"], short})
            d["header"]["approval_blocked"] = True
        return d

    directive = _once()
    if not config.DIRECTIVE_CONTRACT_RETRY:
        return directive
    first_reasons = _contract_reasons(directive)
    # ★ TC-1 은 **차단이 아니라 강등**이라 block_reasons 에 안 들어간다. 그래서 종전에는
    #   재생성을 한 번도 못 띄웠고, 명세가 말한 "재생성 1회"가 사실상 없었다.
    #   실측(2026-09-03): 이 사유가 두 지시서 모두에서 압도적 1위 강등 사유였고
    #   Moon Impactor 는 invest 가 **0개**였다 — 등급제가 목적을 거의 못 이루고 있었다.
    first_short = sequence_tier.contract_shortfall(directive.get("cuts") or [],
                                                   directive.get("header") or {})
    # ★ 품질 경고도 재생성을 띄운다(2026-09-09). 차단만 보던 종전에는 화면 구성 문제가
    #   감지돼도 모델에게 전달되지 않았다.
    first_quality = _quality_retry_reasons(directive)
    if not first_reasons and not first_short and not first_quality:
        return directive

    log.warning("계약 위반 → 사유를 되먹여 1회 재생성: %s",
                ", ".join(first_reasons + ([f"temporal_contract_unmet:{first_short}"]
                                           if first_short else [])
                          + [f"quality:{q}" for q in first_quality]))
    retry = _once(_contract_feedback(directive) + missing_claims_feedback(directive, fact_sheet))
    retry_reasons = _contract_reasons(retry)
    retry_short = sequence_tier.contract_shortfall(retry.get("cuts") or [],
                                                   retry.get("header") or {})
    retry["header"]["contract_retry"] = {
        "attempted": True,
        "first_block_reasons": first_reasons,
        "retry_block_reasons": retry_reasons,
        # ★ 등급을 놓친 컷 수도 남긴다 — 되먹임이 실제로 8초를 되찾았는지 보는 지표다.
        "first_tier_shortfall": first_short,
        "retry_tier_shortfall": retry_short,
        # ★ 품질 경고가 재생성으로 실제로 줄었는지 — 경고를 되먹인 것이 값어치를 했는지
        #   보는 유일한 지표다. 안 줄면 되먹임 문장을 고쳐야 한다는 뜻이다.
        "first_quality_warnings": first_quality,
        "retry_quality_warnings": _quality_retry_reasons(retry),
        # ★ 새 중대 위반이 생겼는지 — 되먹임이 다른 곳을 깨뜨렸다는 신호다.
        "new_violations": sorted(set(_codes(retry_reasons)) - set(_codes(first_reasons))),
    }
    if not retry_reasons and not retry_short:
        log.info("재생성으로 계약 통과")
        return retry
    if retry_reasons:
        log.warning("재생성 후에도 계약 위반 → 사람 검수로 보낸다: %s", ", ".join(retry_reasons))
    if retry_short:
        # ★ 여기는 차단이 아니다 — 명세대로 **강등 + 경고**로 끝난다(TC-1).
        log.warning("연출 계약 미이행 유지 → 해당 컷은 standard 로 강등된다: %s", retry_short)
    # 덜 나쁜 쪽을 남긴다. 차단 사유가 먼저, 그다음 8초를 더 많이 지킨 쪽,
    # **그다음 품질 경고가 적은 쪽**이다.
    #
    # ★★ 마지막 항이 없으면 품질 되먹임이 값어치를 못 한다(2026-09-09 실측).
    #   재생성이 첫 기전 시점을 64% → 50% 로 당겼는데 차단 사유 수와 강등 수가 **같아서**
    #   1차를 남겼다 — 경고를 되먹여 재생성까지 해 놓고 좋아진 결과를 버린 것이다.
    #   품질 경고는 승인을 막지 않으므로 우선순위는 맨 뒤가 맞다. 다만 동점을 가르는
    #   자리에는 있어야 한다.
    _retry_q = len(_quality_retry_reasons(retry))
    if ((len(retry_reasons), len(retry_short), _retry_q)
            >= (len(first_reasons), len(first_short), len(first_quality))):
        directive["header"]["contract_retry"] = retry["header"]["contract_retry"]
        return directive
    return retry


def _codes(reasons: list[str]) -> list[str]:
    """`photo_x:3,5` → `photo_x` (컷 번호를 뗀 사유 코드)."""
    return [r.split(":", 1)[0] for r in reasons]


# ─────────────────────────────────────────────────────────────
# 오케스트레이션 / 큐 폴러 (engine/draft.py 패턴)
# ─────────────────────────────────────────────────────────────
def process_paper(paper_id: str, version_type: str) -> dict[str, Any]:
    draft = db.get_draft_full(paper_id)
    if not draft:
        raise ValueError(f"draft 없음(먼저 초안 생성): {paper_id}")
    directive = generate(draft, version_type)
    row = {
        "paper_id": paper_id,
        "version_type": directive["version_type"],
        "header": directive["header"],
        "cuts": directive["cuts"],
        "status": "draft",
    }
    dir_id = db.insert_directive(row)
    flagged = len(ungrounded_cuts(directive))
    log.info("지시서 생성: paper=%s version=%s cuts=%d 근거없음=%d id=%s",
             paper_id, version_type, len(directive["cuts"]), flagged, dir_id)
    return directive


def poll_once(limit: int = 5) -> int:
    reqs = db.claim_directive_requests(limit)
    if not reqs:
        log.info("directive_requests: 대기 없음")
        return 0
    for r in reqs:
        try:
            # ★ 생성 전에 임대를 한 번 연장한다. 앞 요청이 오래 걸렸으면 이 요청의 임대가
            #   이미 만료돼 다른 워커가 되집어 갈 수 있다(같은 지시서 이중 생성 = 유료 2배).
            db.heartbeat_directive_request(r["id"])
            process_paper(r["paper_id"], r.get("version_type") or config.DEFAULT_VERSION)
            db.update_directive_request(r["id"], "done")
        except Exception as exc:  # noqa: BLE001
            log.exception("지시서 요청 실패 id=%s: %s", r["id"], exc)
            db.update_directive_request(r["id"], "error", str(exc))
    return len(reqs)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 2:
            process_paper(sys.argv[1], sys.argv[2])
        elif len(sys.argv) > 1:
            process_paper(sys.argv[1], config.DEFAULT_VERSION)
        else:
            poll_once()
    except Exception as exc:
        log.exception("directive 실패: %s", exc)
        sys.exit(1)
