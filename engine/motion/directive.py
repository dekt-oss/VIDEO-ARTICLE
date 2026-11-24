"""모션그래픽 지시서 생성 — LLM 은 컷마다 **템플릿 하나를 고르고 칸만 채운다**.

자유 HTML 을 쓰게 하지 않는 이유: 화면이 깨지고(겹침·잘림), 숫자를 지어낼 자리가 생긴다.
칸 숫자는 schema.number_gate 가 Fact Sheet 와 대조하고, 출처 쪽수는 코드가 만든다.
"""

from __future__ import annotations

import json
from typing import Any

from .. import config
from ..llm import call_json
from ..util import log
from . import schema

MOTION_SYSTEM = f"""너는 증권사 리포트를 1분 안팎 세로 쇼츠로 옮기는 모션그래픽 연출가다. 입력은 대본(script_md)과
Fact Sheet 다. 컷마다 아래 [템플릿] 중 하나를 고르고 칸(slots)만 채운 지시서를 JSON 으로만 출력한다.

★ 사실 규칙(어기면 그 컷은 코드가 숫자 없는 카드로 바꾼다):
- 화면 글자(slots)와 나레이션의 수치·주장은 **Fact Sheet 에 있는 것만**. 새 숫자·계산값 금지.
- 칸에 숫자를 쓰면 **단위째** Fact Sheet 문장과 같게("74.5조", "2.2배", "-15.9%"). 반올림·환산 금지.
- 각 컷 source_facts 에 근거 키를 적는다: number_facts 의 fact_id, 또는 "what[0]"·"basis[1]"·"risks[0]"·"opinion".
- 전망·추정은 "(전망)"·"추정"을 칸이나 나레이션에 남긴다. 실적처럼 단정하지 마라.
- 출처 쪽수는 쓰지 마라(코드가 Fact Sheet 에서 붙인다). 끝 출처 카드·면책 컷도 만들지 마라(코드가 고정으로 붙인다).
- [컴플라이언스] 매수·매도 권유, 목표가로 수익률 계산, 단정적 예측 금지. 증권사 판단은 "리포트는 ~로 본다"로 귀속.

★ 연출 규칙:
- 컷 {config.MOTION_MIN_CUTS}~{config.MOTION_MAX_CUTS}개, 전체 나레이션 45~70초. 한 컷 = 한 메시지.
- 1컷은 호기심을 거는 질문/반전. 마지막 컷은 "다만 ~" 처럼 한계·리스크로 균형.
- 나레이션은 말하듯 쉬운 구어체. 한 컷에 소리로 읽는 숫자는 1~2개.
- cue_words: 그 컷 narration_ko 안에 **그대로 있는 낱말**(띄어쓰기까지 같게). 애니메이션이 그 낱말이 들릴 때 터진다.
  템플릿마다 순서대로 필요한 개수만큼.
- 같은 템플릿을 연달아 쓰지 마라. 숫자 비교가 없는 컷에 bar_compare 를 쓰지 마라.

[템플릿] (cue 개수 · slots)
- hook_number (2: 숫자 등장, 도장): {{"chip","number","unit","stamp_title","stamp_sub"}}  큰 숫자 + 도장
- bar_compare (2: 막대, 배지): {{"title","subtitle","items":[{{"label","value"}}…2~4],"highlight":<강조 index>,"badge"}}
    value 가 있으면 그 숫자로 높이를 잰다(같은 단위끼리만). 값이 리포트에 없고 순서만 있으면 value 대신 "rel"(상대값)
- vs_split (2: 왼쪽, 오른쪽): {{"title","left":{{"label","value","sub"}},"right":{{…}}}}
- icon_ratio (3: A, B, 배지): {{"icon":"person|car|coin","a":{{"label","sub","count","value"}},"b":{{…}},"badge"}}  count 는 1~{config.MOTION_MAX_ICONS}, 비율이 맞게
- card_stack (카드 수+1): {{"title","items":["…"2~4],"note"}}
- strike_vs_fact (2: 오해, 실제): {{"chip","wrong","right","wrong_label","right_label"}}
- flow_chain (2: 사슬, 태그): {{"title","steps":["…"2~4],"tag"}}
- cycle3 (5: 노드1·2·3, 가운데, 칩): {{"nodes":["…"×3],"center","center_sub","chips":["…"0~4]}}
- scale_tilt (1: 기울기): {{"chip","left","right"}}  기준이 left→right 로 옮겨감
- stamp_card (2: 도장, 카드): {{"headline","stamp","stamp_sub","card_title","card_body"}}
- text_card (1): {{"title","body"}}  위 어느 것도 안 맞을 때만
칸 글자는 짧게(한 칸 2~14자, card_body 30자 이내).

[출력] JSON only:
{{"header": {{"title_lines": ["<상단 제목 1줄(14자 내)>", "<2줄, 핵심 질문(14자 내)>"], "hook_ko": "<한 줄 제목>", "hook_en": "<English title>"}},
  "cuts": [{{"narration_ko": "<한국어>", "narration_en": "<English>", "estimated_sec": <int>,
             "source_facts": ["<키>"], "novelty_event": "<새 정보 한 구절>",
             "motion": {{"template": "<이름>", "cue_words": ["<낱말>"], "slots": {{…}}}}}}]}}"""


def user_prompt(draft_row: dict[str, Any]) -> str:
    fs = draft_row.get("fact_sheet") or {}
    return "\n\n".join([
        f"대본(script_md):\n{draft_row.get('script_md') or ''}",
        f"Fact Sheet:\n{json.dumps(fs, ensure_ascii=False, indent=1)}",
    ])


def generate(draft_row: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
    """LLM 1회 → 정규화(숫자 검문·쪽수). 반환: 저장 모양 지시서."""
    obj = call_json(model=config.MODEL_REPORT_DIRECTIVE, system=MOTION_SYSTEM,
                    user=user_prompt(draft_row), max_tokens=config.LLM_DIRECTIVE_MAX_TOKENS)
    d = schema.normalize_motion_directive(obj, draft_row.get("fact_sheet"),
                                          str((report or {}).get("broker") or ""))
    log.info("모션 지시서: 컷 %d · 경고 %s", len(d["cuts"]), ", ".join(d["header"]["mode_warnings"]) or "없음")
    return d
