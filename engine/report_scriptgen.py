"""(b) 대본 생성 — 컴플라이언스 규칙 주입 (명세 5-2).

입력은 Fact Sheet "만". 프롬프트에 금지/필수 규칙을 하드코딩한다(자본시장법·저작권 대응).
논문 scriptgen.py 미러 + 금융 컴플라이언스 규칙. 각 씬은 source_facts 로 근거를 남긴다.
"""

from __future__ import annotations

import json
from typing import Any

from . import config, narrative, report_reasoning, report_source, source_adequacy
from .narrative import NARRATIVE_ARC
from .llm import call_json, set_text_purpose

SCRIPT_SYSTEM = """너는 증권사 리포트를 대중용 숏폼 대본으로 각색하는 작가다.
JSON only. 설명·마크다운·코드펜스 금지.

[입력 두 가지 — 쓰임새가 다르다. 헷갈리면 이 대본은 실패한다]
■ <<EVIDENCE_PACKET>> … <</EVIDENCE_PACKET>> : 검증된 근거 묶음(Fact Sheet).
  **화면과 나레이션에 나가는 수치·주장은 여기 있는 것만 쓴다.** 이 묶음에 없는 수치를
  말하면 그 편은 폐기된다.
■ <<FULL_SOURCE>> … <</FULL_SOURCE>> : 리포트 원문 전문(있을 때만 주어진다).
  **맥락을 이해하라고 주는 것이다** — 그 숫자가 왜 나왔는지, 증권사의 논리가 어떤 순서로
  전개되는지, 어떤 표현을 썼는지. 요약만 보고 쓴 대본은 "48.6배입니다"에서 멈추지만,
  전문을 읽은 대본은 "왜 48.6배인지"를 한 문장으로 풀 수 있다. 그 차이를 만들라고 주는 것이다.
  ★ 단, 전문에서 **새 수치를 끌어오지 마라.** 전문에 있고 Fact Sheet 에 없는 수치는
    검증을 안 거친 것이다. 맥락·논리·어감은 전문에서 가져오되, 숫자와 사실 주장은
    Fact Sheet 에서만 가져온다. 이 경계가 이 대본의 생명선이다.
전문이 주어지지 않았으면 Fact Sheet 만으로 쓴다(그때는 해석을 얕게, 사실 위주로).

[대본 생성 규칙 — 절대 준수]
■ 금지 (하나라도 어기면 실패):
  - 매수/매도/보유 등 투자행동 권유 표현 ("사라","지금 담아라","비중 확대" 등)
  - 미실현 수익률·상승여력 광고 ("+35% 상승여력","목표 수익률","2배 간다")
  - 단정적 미래 예측 ("무조건 오른다","확실히","반드시")
  - 리포트를 '내 분석'인 것처럼 서술 (반드시 "OO증권에 따르면"으로 귀속)
  - Fact Sheet에 없는 수치·주장 창작
■ 필수:
  - 목표가·의견은 "사실 인용" 형태로만 ("OO증권은 목표가를 9만원으로 제시했다")
  - 출처(증권사·애널리스트) 최소 1회 명시
  - 리스크 한 줄 포함 — **Fact Sheet 의 risks 가 있을 때만**. ★ risks 가 빈 배열이면
    리스크 씬을 만들지 말고 그 자리를 다른 팩트 비트로 채워라. 없는 리스크를 지어내는 것이
    바로 이 규칙이 막으려는 환각이다.
  - script_md 엔딩에 면책 문구 포함: "정보 제공 목적이며 투자 권유가 아닙니다. 판단·책임은 본인에게."
  - ★ 면책은 script_md 엔딩 텍스트로만 둔다. scenes[] 에 면책 문구만 담은 전용 씬을 만들지 마라
    (면책은 영상에서 하단 고정 자막으로 렌더되므로 나레이션으로 낭독하지 않는다).

[대본 구조 — 숏폼 리텐션 문법] 총 20~30초, 씬 6~7개, 씬당 2~5초(빠른 컷 전환).
""" + NARRATIVE_ARC + """
리포트에 얹으면 이렇게 된다:

씬1 후크 (2~3초) = ① 문제 제기: 스크롤을 멈추게 하는 한마디. 질문·역설형
  ("주가는 반토막인데 이익은 2배?"). 도입부 인사·제목 낭독 절대 금지.

씬2 = ② 문제 상황 (3~4초): 지금 무엇이 막혀·어긋나 있나(시장이 흔히 보는 시각이 있으면 그것).
  회사 + 출처 귀속은 **여기서 한 번**("SK증권은 …라고 봅니다"). 근거: company, source.broker.

씬3~5 = ③ 반전·원리 (각 3~5초): 논증 단위 순서대로 한 씬 = 한 단계(driver → 실적 → 밸류).
  "그래서·하지만"으로 잇고, 주어는 사물·현상으로 둔다(증권사 이름 반복 금지).
  수치는 나레이션+화면 카드로. 근거: what[], numbers[], basis[], opinion.
  데이터가 풍부하면 단계 3개(총 7씬), 적으면 2개(총 6씬). 억지로 늘리지 마라.

씬(끝) = ④ 결과/결론 페이오프 (2~4초): 그래서 무엇이 달라지나 + 후크의 질문에 답한다.
  risks[] 가 있으면 여기서 "다만—" 한 줄로 붙인다(없으면 생략). CTA 는 반 문장 이내.

[씬 구성 원칙]
- 마지막 씬까지 콘텐츠다. 면책·경고 전용 씬 금지(면책은 script_md 엔딩 텍스트
  + 영상 하단 고정 자막으로 자동 처리 — scenes 와 무관).
- source_facts 에 "source.disclaimer" 만 있는 씬을 만들지 마라.
- 정보 밀도: 씬당 주제 1개. 넘치면 씬을 쪼개고, 모자라면 합쳐라.
- 비주얼 실현성: 추상 개념(변동성·경쟁)은 아이콘/차트로, 실물(제품·로봇)은 장면으로.

[각 씬 필수] source_facts 에 근거가 된 Fact Sheet 키를 적는다(예: "numbers[0]","basis[1]","opinion").
근거 없는 씬 금지.

[각 씬 필수] source_facts 에 근거가 된 Fact Sheet 키를 적는다(예: "numbers[0]","basis[1]","opinion").
근거 없는 씬 금지.

[각 씬 필수] scene_role — 이 씬이 화면에서 하는 일. 훅·질문·마무리(CTA)·연결부(BRIDGE)는
사실 주장이 아니라 수사적 문장이므로 근거 대조에서 면제된다. **면제받으려고 아무 씬에나
HOOK/CTA 를 붙이지 마라** — 수치를 말하는 씬은 EVIDENCE 다.

[story_plan 필수] 논증 설계를 먼저 적는다. thesis 는 한 문장이고, 모든 claim 은 그 thesis 를
향한다. hook 을 제외한 claim 에는 evidence_refs 가 있어야 한다. 결론을 증거보다 먼저 놓지 마라.
쓰지 않기로 한 근거는 excluded_evidence 에 이유와 함께 남긴다(고른 이유가 보이게).

[업로드 제목 — 수수께끼형] (2026-09-28 실측) 설명형 제목("삼성전자 목표가 63만원? 증권사가 보는 핵심 근거")보다
역설·의문형이 훨씬 잘 됐다 — "주가는 반토막인데 이익은 2배? 조선업의 새 엔진은 '이것'"(시청 비율 67.5%).
틀: "A인데 B?" · "왜 …할까?" · "…의 새 …은 '이것'". 답은 제목에 넣지 말고 영상에서 풀어라.
수익률·매수 권유·"오른다" 단정은 여전히 금지다(컴플라이언스).

[OUTPUT JSON SCHEMA]
{
  "upload_title_ko": "<대중이 클릭할 한국어 제목 — **수수께끼형**(역설·의문). 사실 왜곡·수익률 훅 금지>",
  "upload_title_en": "<영어 제목>",
  "script_md": "<전체 대본 마크다운>",
  "video_flow": {
    "logline": "<한 줄 컨셉>",
    "total_duration_sec": <int>,
    "beats": [{"order": <int>, "label": "<구간>", "summary": "<요약>", "transition": "<전환>"}]
  },
  "story_plan": {
    "thesis": "<이 영상이 증명하려는 **한 문장**. 곁가지 금지>",
    "content_profile": "<company_update|earnings_review|industry_report|market_wrap|event_flash|paper_explainer>",
    "audience_question": "<시청자가 품는 질문 한 줄>",
    "claim_chain": [
      { "role": "<hook|reveal|proof|mechanism|valuation|risk|closing>",
        "claim": "<주장 한 줄>",
        "evidence_refs": ["<이 주장을 지불하는 Fact Sheet 의 fact_id>"] }
    ],
    "excluded_evidence": [ { "evidence_ref": "<쓰지 않기로 한 fact_id>", "reason": "<왜 뺐나>" } ]
  },
  "scenes": [
    {
      "scene": <int>,
      "scene_role": "<HOOK|QUESTION|CLAIM|EVIDENCE|MECHANISM|RISK|WATCHPOINT|CTA|BRIDGE>",
      "arc_stage": "<problem|situation|turn|result — 4막 중 이 씬의 자리>",
      "title": "<씬 제목>",
      "narration_ko": "<한국어 나레이션>", "narration_en": "<영어 나레이션>",
      "duration_sec": <int>,
      "image_prompt": "<영문 text-to-image 프롬프트>", "image_prompt_ko": "<한글 설명>",
      "video_prompt": "<영문 image-to-video 프롬프트>", "video_prompt_ko": "<한글 설명>",
      "source_facts": ["numbers[0]"],
      "reasoning_id": "<이 씬이 화면으로 옮기는 논증 단위 id. 논증 구간이 주어졌을 때만. 없으면 \"\">"
    }
  ]
}"""

# ── 논증 단위 계약(설명엔진 v2 §7) — 단위가 실제로 있을 때만 얹는다 ──
# ★ 왜 별도 블록인가: 논증 단위는 요약 기반 리포트에서는 비어 있을 수 있다. 계약을 상시로
#   박아 두면 참조할 것이 없는 대본이 id 를 지어낸다(dangling). 있을 때만 건다.
REASONING_CONTRACT = """

[논증 단위 — <<REASONING_UNITS>> … <</REASONING_UNITS>> 구간이 주어졌다]
이 단위들은 **대본보다 먼저** 만들어졌다. 인과를 새로 지어내지 말고 **여기 있는 경로를 옮겨라.**
- carries_thesis=true 인 단위의 단계는 **반드시 화면에 나가야 한다**(최소 한 씬).
- 어떤 단위를 옮긴 씬은 `reasoning_id` 에 그 단위 id 를 적는다. 목록에 없는 id 를 쓰지 마라.
- 단위에 없는 인과를 나레이션에 추가하지 마라. 단위의 `assumption`·`breaks_if` 는 리스크·확인
  포인트 씬의 재료다 — "무엇이 깨지면 이 이야기가 틀리는가"가 거기 있다.
- `attributed_to` 가 있으면 그 증권사를 주어로 말하라("OO증권은 …로 봤다"). 전망을 사실로
  단정하지 마라."""


def script_user_prompt(fact_sheet: dict[str, Any], instruction: str = "",
                       packet: dict[str, Any] | None = None,
                       reasoning: dict[str, Any] | None = None) -> str:
    """대본 입력. 근거 묶음(Fact Sheet) + 원문 전문을 **함께** 넣는다(지시서 §4-2).

    두 구간을 마커로 감싸는 이유는 §11-1 ② 가 그 존재를 CI 로 검사하기 때문이다. 마커가
    없으면 프롬프트를 다듬다가 어느 쪽이 조용히 빠져도 아무도 모른다 — 실제로 그렇게 빠져
    있었다(추출에는 전문이 들어가는데 대본에는 안 들어갔다).
    """
    base = (f"{config.DRAFT_EVIDENCE_MARKER}\n"
            + json.dumps(fact_sheet, ensure_ascii=False, indent=2)
            + f"\n{config.DRAFT_EVIDENCE_END_MARKER}")
    base += source_adequacy.guidance(fact_sheet, "report")
    if config.DRAFT_INCLUDE_FULLTEXT:
        block = report_source.fulltext_block(packet or {})
        if block:
            base += "\n\n" + block
    # ★ 논증 단위(설명엔진 v2 §7). 대본보다 **먼저** 만들어진 것을 여기서 소비한다 —
    #   대본이 인과를 새로 지어내지 않게. 단위가 없으면 구간 자체를 넣지 않는다(빈 마커 금지).
    units = report_reasoning.units_block(reasoning)
    if units:
        base += "\n\n" + units
    if instruction.strip():
        base += (
            "\n\n★사용자 수정 요청(Fact Sheet 사실 범위 내에서만 반영, 규칙 위반 금지):\n"
            + instruction.strip()
        )
    return base


def _normalize_flow(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {"logline": "", "total_duration_sec": 0, "beats": []}
    beats_in = obj.get("beats") or []
    beats: list[dict[str, Any]] = []
    for i, b in enumerate(beats_in):
        if not isinstance(b, dict):
            continue
        try:
            order = int(b.get("order"))
        except (TypeError, ValueError):
            order = i + 1
        beats.append({
            "order": order,
            "label": str(b.get("label") or ""),
            "summary": str(b.get("summary") or ""),
            "transition": str(b.get("transition") or ""),
        })
    try:
        total = int(obj.get("total_duration_sec"))
    except (TypeError, ValueError):
        total = 0
    return {"logline": str(obj.get("logline") or ""), "total_duration_sec": total, "beats": beats}


def _enum_role(value: Any) -> str:
    """씬 역할을 화이트리스트로 강제. 모르는 값은 기본값 — 자유 텍스트가 들어오면 면제 판정이
    무력해진다(모델이 'hook!' 같은 값을 쓰면 면제도 검사도 안 걸린다)."""
    raw = str(value or "").strip().upper()
    return raw if raw in config.SCENE_ROLES else config.SCENE_ROLE_DEFAULT


def _reasoning_coverage(scenes: list[dict[str, Any]],
                        known: tuple[str, ...]) -> dict[str, Any]:
    """논증 단위가 화면으로 옮겨졌는지. **개수가 아니라 커버리지**를 본다(명세 D4 와 같은 자세)."""
    used = {s["reasoning_id"] for s in scenes if s.get("reasoning_id")}
    return {"units": list(known), "used": sorted(used),
            "uncovered": [r for r in known if r not in used],
            "coverage": round(len(used) / len(known), 3) if known else None}


def _normalize_story_plan(obj: Any, scene_count: int) -> dict[str, Any]:
    """§6 story_plan 정규화. **독립 LLM 스테이지가 아니라 초안 출력의 필드**다(§0-1 #9) —
    스테이지를 늘리면 비용·지연·실패 표면적이 함께 는다."""
    src = obj if isinstance(obj, dict) else {}
    chain: list[dict[str, Any]] = []
    for i, c in enumerate(src.get("claim_chain") or []):
        if not isinstance(c, dict):
            continue
        role = str(c.get("role") or "").strip().lower()
        refs = c.get("evidence_refs") or []
        if isinstance(refs, str):
            refs = [refs] if refs else []
        chain.append({
            "order": i + 1,
            "role": role if role in config.STORY_CLAIM_ROLES else "proof",
            "claim": str(c.get("claim") or ""),
            "evidence_refs": [str(x) for x in refs],
        })
    excluded: list[dict[str, str]] = []
    for e in (src.get("excluded_evidence") or []):
        if isinstance(e, dict) and e.get("evidence_ref"):
            excluded.append({"evidence_ref": str(e["evidence_ref"]),
                             "reason": str(e.get("reason") or "")})
    return {
        "thesis": str(src.get("thesis") or ""),
        "content_profile": (str(src.get("content_profile") or "").strip()
                            if str(src.get("content_profile") or "").strip()
                            in config.EVIDENCE_PROFILES else config.EVIDENCE_PROFILE_DEFAULT),
        "audience_question": str(src.get("audience_question") or ""),
        "claim_chain": chain,
        "excluded_evidence": excluded,
        "scene_count": scene_count,
    }


def normalize_script(obj: dict[str, Any],
                     reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    """★ reasoning 을 주면 씬의 reasoning_id 를 **실재하는 것만** 남긴다(dangling 금지).
    안 주면 형태 보정만 하고 통과시킨다(레거시 초안·재검사 경로)."""
    known = report_reasoning.reasoning_ids(reasoning)
    scenes_in = obj.get("scenes") or []
    scenes: list[dict[str, Any]] = []
    for i, s in enumerate(scenes_in):
        if not isinstance(s, dict):
            continue
        try:
            scene_no = int(s.get("scene"))
        except (TypeError, ValueError):
            scene_no = i + 1
        try:
            dur = int(s.get("duration_sec"))
        except (TypeError, ValueError):
            dur = 0
        sf = s.get("source_facts") or []
        if isinstance(sf, str):
            sf = [sf] if sf else []
        scenes.append({
            "scene": scene_no,
            # v3 §5-4 — 씬 역할. 지금까지 없어서 자기검증이 훅·마무리까지 사실 대조 대상으로
            # 삼았고, 최근 초안 6/6 에서 첫·마지막 씬이 오탐으로 찍혔다.
            "scene_role": _enum_role(s.get("scene_role")),
            "arc_stage": narrative.arc_stage(s.get("arc_stage")),
            "title": str(s.get("title") or ""),
            "narration_ko": str(s.get("narration_ko") or ""),
            "narration_en": str(s.get("narration_en") or ""),
            "duration_sec": dur,
            "image_prompt": str(s.get("image_prompt") or ""),
            "image_prompt_ko": str(s.get("image_prompt_ko") or ""),
            # 레거시 단일 visual_prompt → video_prompt 폴백(논문과 동일).
            "video_prompt": str(s.get("video_prompt") or s.get("visual_prompt") or ""),
            "video_prompt_ko": str(s.get("video_prompt_ko") or ""),
            "source_facts": [str(x) for x in sf],
            # 이 씬이 어느 논증 단위를 화면으로 옮기는가(설명엔진 v2 §7). 원장에 없는 id 는
            # 버린다 — 지시서·승인 화면이 존재하지 않는 논증을 가리키게 두지 않는다.
            "reasoning_id": (rid if (rid := str(s.get("reasoning_id") or "").strip()) in known
                             else ""),
        })
    return {
        "upload_title_ko": str(obj.get("upload_title_ko") or ""),
        "upload_title_en": str(obj.get("upload_title_en") or ""),
        "script_md": str(obj.get("script_md") or ""),
        "video_flow": _normalize_flow(obj.get("video_flow")),
        "story_plan": _normalize_story_plan(obj.get("story_plan"), len(scenes)),
        "scenes": scenes,
        # 논증 단위 중 실제로 화면에 옮겨진 것 / 버려진 것. 승인 화면이 "설명이 빠진 논증"을
        # 짚을 수 있어야 한다(명세 §6 E3 의 리포트판).
        "reasoning_coverage": _reasoning_coverage(scenes, known),
    }


_VISUAL_SCHEMA_LINES = (
    '      "image_prompt": "<영문 text-to-image 프롬프트>", "image_prompt_ko": "<한글 설명>",\n',
    '      "video_prompt": "<영문 image-to-video 프롬프트>", "video_prompt_ko": "<한글 설명>",\n',
)


def _narration_only(system: str) -> str:
    """V2 용 — 장면 그림·영상 프롬프트를 쓰지 않는다. 논문 `scriptgen._narration_only` 와 같은 이유(지시서가 화면을
    다시 정한다, 2026-10-08 운영자 "대본 단가 줄이는 작업"). 말·논증 규칙은 그대로다."""
    for line in _VISUAL_SCHEMA_LINES:
        assert line in system, line
        system = system.replace(line, "")
    return system + "\n★ scenes 에 image_prompt·video_prompt 를 쓰지 마라 — 화면은 다음 단계(지시서)가 정한다.\n"


def generate(fact_sheet: dict[str, Any], instruction: str = "",
             packet: dict[str, Any] | None = None,
             reasoning: dict[str, Any] | None = None, *, narration_only: bool = False) -> dict[str, Any]:
    """★ 논증 단위가 있을 때만 REASONING_CONTRACT 를 얹는다.

    없는데 계약만 붙이면 모델이 "논증 단위를 참조하라"는 지시를 받고 참조할 것이 없어
    **id 를 지어낸다** — 그러면 하류가 dangling reasoning_id 를 받는다(코드가 버리긴 하지만
    씬 하나가 근거를 잃는다). 요약 기반 재고가 아직 많아서 실제로 자주 걸리는 분기다.
    """
    has_units = bool(report_reasoning.reasoning_ids(reasoning))
    set_text_purpose("script")     # 비용 원장 용도 라벨 — 없으면 앞 단계 라벨이 그대로 찍힌다(2026-10-08 실측)
    obj = call_json(
        model=config.MODEL_REPORT_SCRIPT,
        system=((_narration_only(SCRIPT_SYSTEM) if narration_only else SCRIPT_SYSTEM)
                + (REASONING_CONTRACT if has_units else "")),
        user=script_user_prompt(fact_sheet, instruction, packet, reasoning),
        max_tokens=config.LLM_REPORT_SCRIPT_MAX_TOKENS,
    )
    return normalize_script(obj, reasoning)
