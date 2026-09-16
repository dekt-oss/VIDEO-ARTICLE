"""(b) 대본 + 단계별 미디어 프롬프트 생성 (명세 5-2, 확장).

★ 환각 방지 불변식: 입력은 Fact Sheet "만". "Fact Sheet에 없는 내용 추가 절대 금지".
각 씬은 source_facts 로 어느 사실에서 나왔는지 근거를 남긴다.

산출 구조(단계별 미디어화):
- video_flow: 전체 세부 영상 흐름(스토리보드) — logline, 총 길이, 비트별 요약+전환.
- scenes[]: 주요 장면마다
    image_prompt  — 텍스트→이미지(스틸 한 장, 정적 요소)
    video_prompt  — 이미지→영상(그 스틸을 어떻게 움직일지: 카메라/모션)
    narration_ko/en — 그 장면 나레이션
제작 순서: 각 장면 이미지 생성 → 그 이미지를 영상화 → 나레이션으로 진행.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import config, content_mode, factsheet
from .llm import call_json, set_text_purpose

SCRIPT_SYSTEM = """너는 대중 과학 숏폼 대본 작가 겸 영상 연출자다. 입력으로 주어지는 것은 오직 "Fact Sheet"(JSON)뿐이다.
★ 절대 규칙: Fact Sheet에 없는 내용을 추가하지 마라. 수치·주장·예시는 Fact Sheet에 있는 것만 사용한다.
각 씬에는 그 씬이 근거한 Fact Sheet 항목 키를 source_facts 로 남긴다(예: "what_found[0]", "numbers[1]").
Fact Sheet 에 claims(주장 원장)가 있으면 각 씬에 claim_ids 로 **원장에 실제로 있는 id 만** 남겨라.
근거가 없으면 그 씬을 만들지 마라.

산출물은 "단계별로 미디어화 가능한 제작 지시서"다. 네 가지를 만든다:
(1) content_plan — 무엇을 몇 초에 담을지의 계획. ★대본보다 **먼저** 세운다.
(2) video_flow — 전체 세부 영상 흐름(스토리보드). 영상이 처음부터 끝까지 어떻게 흘러가는지.
(3) scenes — 주요 장면마다 [이미지 프롬프트 → 영상 프롬프트 → 나레이션]. 제작 순서는
    각 장면의 스틸 이미지를 먼저 만들고 → 그 이미지를 움직여 영상화 → 나레이션으로 진행한다.
(4) script_md — 사람이 읽는 전체 대본(나레이션 흐름 전문).

[★ content_plan — 길이를 먼저 고정하지 마라. 논문 복잡도가 길이를 정한다.]
순서: ①핵심 주장 1개(primary_claim_id) 선택 → ②정확한 이해에 꼭 필요한 Evidence Unit 선택 →
③그 개수로 content_mode 결정 → ④그 모드 범위 안에서 **가장 짧은** 길이 선택.
 Evidence Unit: E1 핵심결과 / E2 대상·지역·기간 / E3 비교방식·연구설계 / E4 효과크기·대표수치 /
   E5 작동원리 / E6 조건·예외·하위집단 / E7 한계·인과범위 / E8 논문이 직접 지지하는 의미
   ★ E1·E2·E7 은 모든 영상 필수. 나머지는 정말 필요할 때만 넣어라(넣을수록 영상이 길어진다).
   ★★ **E2(대상·지역·기간)는 한 씬으로 묶어라.** 계통·연령·표본 수·투여기간을 각각 독립
      씬으로 쪼개지 마라 — 연구 메타데이터가 여러 씬으로 팽창하면 화면이 통째로
      "연구 대상 사진"이 되고, 시청자가 원리를 만나기 전에 떠난다.
      실측 사고(2026-09-08): "20개월령 암컷 C57BL/6 생쥐에게" / "3개월간 투여하여" /
      "수명 기간 동안 진행되었고요" 가 **세 씬 18초**를 먹었고, 전반부 36초의 절반이 됐다.
      → "20개월 된 늙은 생쥐에게 석 달간 투여했습니다" 한 문장이면 된다.
      ★ 결론 해석이 달라지는 조건만 말로 하고, 나머지 세부(정확한 계통명·표본 수)는
        evidence_delivery 를 "caption"·"visual" 로 두어 화면이 담당하게 하라.
        사실을 **버리라는 것이 아니라** 나레이션 시간을 쓰지 말라는 것이다.
   조건부 필수: 수치 연구면 E4 / 인과 표현을 쓰면 E3 / 조절효과를 훅에 쓰면 E6 / 원리가 핵심이면 E5.
 content_mode: flash 25~35초(필수 근거 3개 이하 + 단일 수치나 명확한 반전)
   / standard 36~50초(범위·방법·결과·한계가 모두 필요 — 기본값)
   / deep 51~65초(조절효과·메커니즘이 결론에 중요해서 생략하면 인과 오해가 생김)
   / extended 66~80초(★예외 모드 — 65초로 압축하면 사실 왜곡이 생기는 경우만. compression_risk=high 근거 필수)
   / series_split(독립적인 핵심 주장이 2개 이상 — 한 편을 늘리지 말고 분할을 제안하라)
 ★ 60초를 채우려고 일상 예시·반복·CTA 를 늘리지 마라. 근거가 적으면 28초로 끝내는 게 정답이다.
 ★ 80초를 넘겨야 하면 한 편을 늘리지 말고 series_split 을 고르고 series_split_reason 을 적어라.
 evidence_delivery — 각 Evidence Unit 을 어떻게 전달할지 정한다:
   spoken(나레이션) / visual(화면에만) / both(말하고 강조) / caption(설명란) / omit(이번엔 안 씀).
   권장: 핵심 결과·대표 수치=both, 표본·기간=visual, 연구 방법=한 문장 spoken,
        상세 통계=visual, 부차 한계=caption, 핵심 일반화 한계=spoken.

[★ 서사 배치 — 근거를 "설명"으로 나열하지 말고 반전 장치로 써라]
나쁨: 결과 → 방법 설명 → 표본 설명 → 기간 설명 → 한계 설명(면책 문구)
좋음: 강한 결과 → "그런데 이건 X 자체를 조사한 게 아닙니다" → 실제 연구 범위 공개 →
     비교 결과 → 예외 조건 → 한계를 포함한 정확한 결론
★ 한 영상에 핵심 주장은 1개다. 보조 주장은 핵심 주장을 설명하거나 제한하는 역할만 한다.
  독립적인 두 번째 결과가 중요하면 나열하지 말고 series_split 을 제안하라.
각 씬은 evidence_role 로 자기가 맡은 근거 역할을 밝힌다:
  primary_result|scope|method|magnitude|mechanism|moderator|caveat|implication|connective|cta

[★ 나레이션 서사 규칙]
- 한 씬 = 한 메시지. 한 씬에 여러 사실·여러 수치를 몰아넣지 마라.
- 앞뒤 문맥 연결: 각 씬 나레이션은 이전 씬을 자연스럽게 이어받아라(그래서/하지만/즉 등). 순서대로 읽으면 하나의 이야기가 되게.
""" + config.EVIDENCE_RULES_SHARED + """
- 숫자 나열·괄호·기호·긴 수식은 나레이션에서 금지(소리 내 읽기 어렵다). 친구에게 말하듯 구어체로.
- 마지막 씬은 후크에서 던진 궁금증에 답한다.
- ★출처 구체화: "한 연구/어떤 연구"처럼 추상적으로 말하지 말고, Fact Sheet의 source로 구체적으로 지칭하라.
  ★지칭 우선순위: 기관 > 저자명 > 게재처. 기관(institutions)이 있으면 "스탠퍼드 연구팀이"처럼, 없으면
  저자명(authors)으로 "제인 도 연구진이", "○○○ 팀이"처럼 사람 이름을 써라. 게재처만으로 "arXiv에 발표된
  연구"처럼 밋밋하게 끝내지 마라 — 저자명이 있으면 반드시 사람 이름을 넣는다(예: "제인 도 등 연구진의
  이번 arXiv 논문은"). 저자·기관이 모두 없을 때만 게재처/분야로 특정한다("국제 학술지에 실린 연구").
  ★source에 있는 것만 써라 — 없는 기관·저자를 절대 지어내지 마라. 최소 1회는 도입부에서 누가 한 연구인지 밝혀라.

[image_prompt 작성 규칙 — 텍스트-투-이미지 AI(Midjourney/Imagen/Flux 등 도구 무관)에 그대로 붙여
스틸 한 장을 뽑을 수준으로. 영어로, 콤마로 이어지는 하나의 리치 프롬프트. "정지 이미지" 관점.]
반드시 아래 정적 요소를 순서대로 구체적으로 포함:
1) shot/framing — 예: extreme close-up, wide establishing shot, macro, split-screen
2) main subject + 구체적 외형 묘사
3) setting/environment
4) lens/optics — 예: 35mm, shallow depth of field, macro
5) lighting — 예: volumetric, soft rim light, chiaroscuro, high-key
6) color palette / mood
7) ★화풍·매체 어휘를 **쓰지 마라** — webtoon / comic / photorealistic / 3D render / illustration /
   cel shading / ink outlines 같은 말을 넣지 않는다. 화풍은 초안이 아니라 **지시서 단계에서 버전별로
   코드가 붙인다**(만화식·3D 그래픽 중 운영자가 고른다). 여기서는 장면만 적는다 — 누가·어디서·무엇을·
   어떤 구도로. 같은 인물이 다시 나오면 외형 묘사를 같게 유지한다(화풍이 아니라 **생김새**로).
8) technical tags — "vertical 9:16, 4K, high detail, no on-screen text"

[video_prompt 작성 규칙 — 이미지-투-영상 AI(Runway/Kling/Veo 등 도구 무관)에 그대로 붙여
위 스틸을 "움직이는 영상"으로 만들 지시. 영어로, 콤마로 이어지는 하나의 리치 프롬프트.
"animate the still image" 관점 — 정적 요소는 반복하지 말고 '움직임'만 지시.]
반드시 포함:
1) camera movement — 예: slow dolly-in, orbit, crane-up, whip-pan, rack-focus, parallax push
2) subject motion/action — 화면 안 피사체·요소의 구체적 움직임
3) pacing/speed — 예: slow-mo, steady, quick burst
4) 지속시간감과 루프 여부(예: seamless subtle loop)
공통 제약:
- 시각은 Fact Sheet 사실의 "시각화·은유"만. Fact Sheet에 없는 구체 수치·결과·객체를 지어내지 마라.
- 화면 안에 읽히는 글자/숫자/자막/워터마크 렌더 금지("no on-screen text" 명시).
- 영상이므로 정지컷 금지 — video_prompt엔 반드시 카메라 무빙과 모션 포함.
- ★만화 그림을 그대로 애니메이션하는 관점(웹툰 화풍 유지) — 실사화·3D화 금지, 정적 요소의 화풍은 image_prompt와 동일하게.

[한국어 설명 병기 — image_prompt_ko / video_prompt_ko]
image_prompt·video_prompt는 툴에 그대로 붙일 "영문"이고, 각각에 대응하는 한국어 설명을
image_prompt_ko(어떤 스틸 장면인지)·video_prompt_ko(어떻게 움직이는지)에 1~2문장으로 적어라.
사람이 영문을 안 읽어도 무엇을 만들지 이해하도록. 영문 프롬프트의 충실한 한국어 요약이어야 한다.

[★ 훅 후보 3개 — hook_candidates]
영상 첫 1.5초를 책임질 훅 후보를 **정확히 3개** 만들고, 그중 하나를 selected_hook_id 로 고른다.
- 각 훅은 반드시 claim_ids 로 특정 주장과 연결된다. 연결이 없는 훅은 만들지 마라.
- 자극성은 낮추지 말고 **범위를 좁혀라**. 허용: 반전 / 충격 수치 / 비교 / 개인 영향 / 인과 미스터리 /
  상식 충돌 / 도발적 질문.
- 금지: 연구 대상을 기술·산업·인류 전체로 확대 / 상관관계를 원인으로 단정 / 일부 기업·일부 지역의
  결과를 전체로 확대 / 수치 없는 결과에 "폭락·급감·압도적" 사용 / 논문이 검증하지 않은 피해·위험 추가 /
  본문에서 지불하지 못하는 약속.
- scope_preserved: 훅의 주어·범위가 연결된 Claim 의 범위를 넘지 않으면 true.
- causal_calibrated: 훅의 인과 표현이 그 Claim 의 causal_strength 를 넘지 않으면 true.
- ★ evidence_grade 가 C 인 Claim 에는 단정형 충격수치 훅을 쓰지 마라(보수적 표현만 가능).
- promise 에는 "이 훅이 시청자에게 약속하는 것"을 적어라. 본문이 그걸 실제로 지불해야 한다.
예) 나쁨 "블록체인 기술이 지구를 망친다고요?"(기술 전체·지구로 확대)
    좋음 "블록체인을 장려했더니 기업이 덜 친환경적으로 변했다고요?"(정책·기업으로 범위 축소, 반전 유지)

[★ 유튜브 업로드용 제목 — upload_title_ko / upload_title_en]
숏폼(유튜브 Shorts) 업로드 제목을 한국어·영어로 각각 만든다. 논문 원제는 밋밋하니 쓰지 마라.
- 클릭을 부르는 자극적·호기심 유발형 훅. 시청자가 "뭐라고?" 하고 멈추게.
- 짧게(한국어 대략 15~30자, 영어 대략 40~70자). 한 줄, 문장부호 최소.
- 언어별 독립 트랜스크리에이션(직역 금지) — 각 언어에서 자연스럽고 강한 표현으로.
- ★환각 금지: Fact Sheet에 없는 수치·주장·결과를 지어내지 마라. 과장 표현은 되지만 없는 사실은 금지.
- 낚시성 거짓(clickbait 허위)은 금지 — 영상 내용과 어긋나면 안 된다.

출력은 JSON only. 설명·마크다운·코드펜스 금지.
{
  "upload_title_ko": "<자극적 한국어 업로드 제목 한 줄>",
  "upload_title_en": "<자극적 영어 업로드 제목 한 줄>",
  "content_plan": {
    "primary_claim_id": "<핵심 주장 1개의 claim_id. 원장이 없으면 빈 문자열>",
    "supporting_claim_ids": ["<핵심 주장을 설명·제한하는 보조 주장 id>"],
    "essential_evidence_units": ["E1", "E2", "E7"],
    "evidence_delivery": { "E1": "both", "E2": "visual", "E7": "spoken" },
    "complexity": "<low|medium|high>",
    "visualizability": "<low|medium|high>",
    "compression_risk": "<low|medium|high — 더 짧게 줄이면 사실 왜곡·인과 오해가 생길 위험>",
    "selected_mode": "<flash|standard|deep|extended|series_split>",
    "target_duration_min_sec": <int>,
    "target_duration_max_sec": <int>,
    "duration_reason": "<왜 이 길이가 필요한지 한 문장>",
    "series_split_reason": "<series_split 일 때만: 무엇과 무엇으로 나눌지 한 문장. 아니면 빈 문자열>"
  },
  "hook_candidates": [
    { "hook_id": "H-A",
      "text_ko": "<훅 한 줄(한국어)>",
      "angle": "<counterintuition|personal_cost|competition|daily_life|risk|mechanism|future_impact|human_scale|scientific_wonder>",
      "claim_ids": ["<이 훅이 근거하는 claim_id>"],
      "scope_preserved": <bool>,
      "causal_calibrated": <bool>,
      "promise": "<이 훅이 약속하는 것>",
      "risk": "<low|medium|high>" }
  ],
  "selected_hook_id": "<hook_candidates 중 1개의 hook_id>",
  "video_flow": {
    "logline": "<이 영상 한 줄 컨셉(한국어)>",
    "total_duration_sec": <int>,
    "beats": [
      { "order": <int>, "label": "<후크/개념/수치/일상연결/의심/CTA 등>",
        "summary": "<이 비트에서 화면에 무엇이 보이고 무엇을 전달하는가(한국어)>",
        "transition": "<다음 장면으로의 전환 방식(예: 매치컷, 페이드, 급속 줌)>" }
    ]
  },
  "script_md": "<읽기용 대본 전문(한국어 나레이션 흐름)>",
  "scenes": [
    {
      "scene": <int>,
      "title": "<장면 짧은 제목(한국어)>",
      "narration_ko": "<한국어 나레이션>",
      "narration_en": "<영어 나레이션>",
      "duration_sec": <int>,
      "image_prompt": "<위 규칙대로 매우 상세한 영문 텍스트→이미지 프롬프트(스틸)>",
      "image_prompt_ko": "<image_prompt의 한국어 설명 — 어떤 스틸 장면인지 1~2문장>",
      "video_prompt": "<위 규칙대로 영문 이미지→영상 프롬프트(그 스틸의 모션)>",
      "video_prompt_ko": "<video_prompt의 한국어 설명 — 어떻게 움직이는지 1~2문장>",
      "source_facts": ["<Fact Sheet 항목 키>"],
      "claim_ids": ["<이 씬이 근거하는 claim_id — 원장에 있는 것만>"],
      "evidence_role": "<primary_result|scope|method|magnitude|mechanism|moderator|caveat|implication|connective|cta>",
      "evidence_delivery": "<spoken|visual|both|caption — 이 씬의 근거를 어떻게 전달하는가>"
    }
  ]
}"""


def mechanism_supply_block(fact_sheet: dict[str, Any] | None) -> str:
    """소재가 **왜 그런지**를 대는가를 코드가 단정해서 알려준다 (2026-09-09).

    ★ 무엇이 비어 있었나: 대본 프롬프트는 E5(작동원리)를 "원리가 핵심이면" 이라는
      **모델 판단**에 맡겨 뒀다. 그래서 기전 claim 이 원장에 있는데도 대본이 원리를 한 번도
      안 쓰는 일이 생긴다 — 실측(2026-09-09): E2 압축으로 8초를 벌었는데 그 시간이
      원리가 아니라 **결과 나열**로 갔고, 기전 비중이 28% → 0% 가 됐다.
      지시서 단계에는 이미 같은 성격의 블록이 있다(`[기전 컷 수]`). 대본에는 없었다.

    ★★ **없으면 요구하지 않는다.** 원장에 기전 claim 이 0개인 논문에 원리를 요구하면
      지어내거나 영원히 못 채운다 — 이 저장소가 이미 겪은 실패다.
    """
    kinds = {"mechanism", "author_interpretation"}
    ids = [str(c.get("claim_id")) for c in ((fact_sheet or {}).get("claims") or [])
           if isinstance(c, dict) and str(c.get("claim_kind") or "").lower() in kinds]
    if not ids:
        return ("\n\n[작동원리 소재] 이 논문은 **왜 그런지를 말하지 않는다**(원장에 기전·저자해석"
                " 주장이 없다). 그러니 원리 설명 씬을 억지로 만들지 마라 — 지어내는 것이 된다."
                " 대신 무엇이 관측됐는지를 또렷하게 보여라.")
    return ("\n\n[작동원리 소재] 이 논문은 **왜 그런지를 말한다** — 원장의 "
            f"{', '.join(ids[:6])} 가 기전·저자해석 주장이다."
            " ★ evidence_role='mechanism' 씬을 **반드시** 두어라(E5는 이 경우 필수다)."
            " 그리고 그 씬을 **결과와 숫자를 말한 직후**에 놓아라 — 뒤로 몰면 앞부분이 통째로"
            " 연구 소개가 되고 시청자는 원리를 만나기 전에 떠난다."
            " ★★ E2(대상·기간)를 한 씬으로 묶어 아낀 시간은 **여기에 쓴다.**"
            " 결과를 한 번 더 말하는 씬을 늘리는 데 쓰지 마라.")


def script_user_prompt(fact_sheet: dict[str, Any], instruction: str = "") -> str:
    base = "Fact Sheet:\n" + json.dumps(fact_sheet, ensure_ascii=False, indent=2)
    # ★ 코드가 단정하는 블록 — 모델의 짐작에 맡기지 않는다(지시서의 [기전 컷 수]와 같은 자세).
    base += mechanism_supply_block(fact_sheet)
    if instruction.strip():
        # 사용자 수정 요청은 표현·구성·난이도만 조정 — Fact Sheet 사실 범위 내에서만(환각 방지 유지).
        base += (
            "\n\n★사용자 수정 요청(반드시 반영하라. 단 Fact Sheet 사실 범위 내에서만 —"
            " 없는 사실을 지어내지 말고 표현·구성·난이도만 조정):\n" + instruction.strip()
        )
    return base


def _normalize_flow(obj: Any) -> dict[str, Any]:
    """video_flow 정규화 — 없거나 형식이 어긋나도 안전한 기본 shape 보장."""
    flow = obj if isinstance(obj, dict) else {}
    beats_in = flow.get("beats") or []
    beats: list[dict[str, Any]] = []
    for i, b in enumerate(beats_in if isinstance(beats_in, list) else []):
        if not isinstance(b, dict):
            continue
        try:
            order = int(b.get("order") or (i + 1))
        except (TypeError, ValueError):
            order = i + 1
        beats.append({
            "order": order,
            "label": str(b.get("label") or ""),
            "summary": str(b.get("summary") or ""),
            "transition": str(b.get("transition") or ""),
        })
    try:
        total = int(flow.get("total_duration_sec") or 0)
    except (TypeError, ValueError):
        total = 0
    return {
        "logline": str(flow.get("logline") or ""),
        "total_duration_sec": total,
        "beats": beats,
    }


# 나레이션에서 "소리 내 읽는 숫자" 세기용. 연도·순번이 아니라 값으로 읽히는 수를 대략 잡는다.
_SPOKEN_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|퍼센트|배|명|개|건|년|개월|일|시간|원|달러|p|%p)?")


def count_spoken_numbers(narration: str) -> int:
    """나레이션 한 줄에서 소리 내 읽는 수치 개수(§9-2 상한 검사용, 근사)."""
    return len(_SPOKEN_NUMBER_RE.findall(narration or ""))


def _normalize_hook_candidates(
    raw: Any, selected: Any, *, known_claims: tuple[str, ...] = (),
    fact_sheet: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """훅 후보 정규화 + 즉시탈락 판정(§8-2).

    ★ 코드가 판정하는 것: `hook_id`(H-A/B/C), `eligible`, `disqualify_reasons`, `selected_hook_id`.
      모델이 "이 훅 괜찮다"고 주장해도 범위·인과·근거등급 게이트는 여기서 다시 본다.
    """
    grades = {}
    for c in ((fact_sheet or {}).get("claims") or []):
        if isinstance(c, dict) and c.get("claim_id"):
            grades[str(c["claim_id"])] = str(c.get("evidence_grade") or config.DEFAULT_EVIDENCE_GRADE)

    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for i, h in enumerate(items):
        src = h if isinstance(h, dict) else {}
        ids = src.get("claim_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        ids = [str(x).strip() for x in ids if str(x).strip()]
        if known_claims:
            ids = [x for x in ids if x in known_claims]
        text = str(src.get("text_ko") or "").strip()
        angle = str(src.get("angle") or "").strip().lower()
        cand = {
            "hook_id": str(src.get("hook_id") or "").strip() or f"H-{chr(ord('A') + i)}",
            "text_ko": text,
            "angle": angle if angle in config.HOOK_ANGLES else config.DEFAULT_HOOK_ANGLE,
            "claim_ids": ids,
            "scope_preserved": bool(src.get("scope_preserved", False)),
            "causal_calibrated": bool(src.get("causal_calibrated", False)),
            "promise": str(src.get("promise") or "").strip(),
            "risk": str(src.get("risk") or "medium").strip().lower(),
        }
        # 즉시탈락(§8-2) — 하나라도 걸리면 선택 후보가 될 수 없다.
        bad: list[str] = []
        if not text:
            bad.append("empty_text")
        if known_claims and not ids:
            bad.append("no_claim_link")
        if not cand["scope_preserved"]:
            bad.append("scope_not_preserved")
        if not cand["causal_calibrated"]:
            bad.append("causal_not_calibrated")
        if not cand["promise"]:
            bad.append("no_promise")
        # C·D 등급 주장에 강도 부사를 붙인 단정형 훅은 근거가 감당하지 못한다.
        weak = [c for c in ids if grades.get(c, config.DEFAULT_EVIDENCE_GRADE) in ("C", "D")]
        if weak and any(w in text for w in config.HOOK_STRONG_CLAIM_WORDS):
            bad.append("bold_claim_on_weak_evidence")
        cand["disqualify_reasons"] = bad
        cand["eligible"] = not bad
        out.append(cand)

    if not out:
        return [], ""
    ids_by_hook = {c["hook_id"]: c for c in out}
    chosen = str(selected or "").strip()
    # 선택된 훅이 없거나 탈락했으면 통과한 첫 후보로 강제한다(모델 선택 불신).
    if chosen not in ids_by_hook or not ids_by_hook[chosen]["eligible"]:
        eligible = [c["hook_id"] for c in out if c["eligible"]]
        chosen = eligible[0] if eligible else ""
    return out, chosen


def normalize_script(
    obj: dict[str, Any], fact_sheet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LLM 대본 출력 정규화.

    `fact_sheet` 를 주면 Claim Ledger 대조까지 한다 — 원장에 없는 claim_id 는 드롭하고,
    모드·길이는 `content_mode` 규칙으로 재판정한다. 안 주면 형태 보정만 하고 통과시킨다(레거시).
    """
    known = factsheet.claim_ids(fact_sheet) if fact_sheet else ()
    scenes_in = obj.get("scenes") or []
    scenes: list[dict[str, Any]] = []
    for i, s in enumerate(scenes_in):
        if not isinstance(s, dict):
            continue
        sf = s.get("source_facts") or []
        if isinstance(sf, str):
            sf = [sf]
        cid = s.get("claim_ids") or []
        if isinstance(cid, str):
            cid = [cid]
        cid = [str(x).strip() for x in cid if str(x).strip()]
        if known:
            cid = [x for x in cid if x in known]   # 원장에 없는 참조는 드롭(dangling 금지)
        try:
            dur = int(s.get("duration_sec") or 0)
        except (TypeError, ValueError):
            dur = 0
        role = str(s.get("evidence_role") or "").strip().lower()
        delivery = str(s.get("evidence_delivery") or "").strip().lower()
        # 하위호환: 옛 단일 visual_prompt 만 온 경우 video_prompt 로 승계.
        video_prompt = str(s.get("video_prompt") or s.get("visual_prompt") or "")
        scenes.append({
            "scene": int(s.get("scene") or (i + 1)),
            "title": str(s.get("title") or ""),
            "narration_ko": str(s.get("narration_ko") or ""),
            "narration_en": str(s.get("narration_en") or ""),
            "duration_sec": dur,
            "image_prompt": str(s.get("image_prompt") or ""),
            "image_prompt_ko": str(s.get("image_prompt_ko") or ""),
            "video_prompt": video_prompt,
            "video_prompt_ko": str(s.get("video_prompt_ko") or ""),
            "source_facts": [str(x) for x in sf],
            "claim_ids": cid,
            "evidence_role": role if role in config.EVIDENCE_ROLES else config.DEFAULT_EVIDENCE_ROLE,
            "evidence_delivery": (delivery if delivery in config.EVIDENCE_DELIVERY
                                  else config.DEFAULT_EVIDENCE_DELIVERY),
        })

    # 계획·훅은 video_flow 안에 얹는다 — drafts 에 빈 컬럼이 없어 마이그레이션을 늘리지 않기 위해서다.
    flow = _normalize_flow(obj.get("video_flow"))
    splits = factsheet.primary_claim_candidates(fact_sheet) if fact_sheet else ()
    plan = content_mode.normalize_content_plan(
        obj.get("content_plan"),
        claim_ids=known,
        independent_main_claims=max(1, len(splits)),
    )
    # 실제로 읽는 숫자를 코드가 센다(모델 자기보고 없음). 상한 초과는 경고로만 남긴다.
    spoken = sum(count_spoken_numbers(s["narration_ko"]) for s in scenes
                 if s["evidence_delivery"] != "visual")
    plan["spoken_number_count"] = spoken
    if spoken > config.MAX_SPOKEN_NUMBERS:
        plan["mode_warnings"] = [*plan["mode_warnings"], "too_many_spoken_numbers"]

    hooks, selected = _normalize_hook_candidates(
        obj.get("hook_candidates"), obj.get("selected_hook_id"),
        known_claims=known, fact_sheet=fact_sheet,
    )
    flow["content_plan"] = plan
    flow["hook_candidates"] = hooks
    flow["selected_hook_id"] = selected

    return {
        "upload_title_ko": str(obj.get("upload_title_ko") or ""),
        "upload_title_en": str(obj.get("upload_title_en") or ""),
        "script_md": str(obj.get("script_md") or ""),
        "video_flow": flow,
        "scenes": scenes,
    }


def generate(
    fact_sheet: dict[str, Any], instruction: str = "",
) -> dict[str, Any]:
    set_text_purpose("script")     # 비용 원장의 용도 라벨(engine/llm.py)
    obj = call_json(
        model=config.MODEL_SCRIPT,
        system=SCRIPT_SYSTEM,
        user=script_user_prompt(fact_sheet, instruction),
        # content_plan·hook_candidates·씬별 근거 필드로 출력이 약 900토큰 늘었다. 6144 로 두면
        # 잘림 → JSON 파싱 실패 → 재시도 1회 → 하드 에러(파이프라인 정지)라 소프트 저하가 아니다.
        max_tokens=8192,
    )
    return normalize_script(obj, fact_sheet)
