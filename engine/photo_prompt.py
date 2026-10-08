"""실사형(photo) 지시서 프롬프트 — 두 공장이 같은 글을 쓴다. 한 뜻은 한 자리에만 (2026-09-28, 규칙 통합 2단계).

왜 생겼나
--------
운영자 결정: "규칙 통합하고 정리. 뼈대 묶고 코드 정리한 다음 개선 방향은 다시 고민."
실측(docs/규칙통합_분석_2026-09-28.md): 실사형 프롬프트의 규칙 글이 29~32k자(★150개)였고 같은 뜻이
여덟 군데에 흩어져 있었다("세계" 58~76회, "글자" 36~56회). 규칙이 많을수록 모델은 덜 지켰다 —
지시서 한 장 경고 중앙값 56. 이 모듈은 그 글을 **한 자리에 절 하나씩**으로 다시 쓴 것이다.

원칙
----
- **규칙만 남긴다.** "실측 사고 서술"은 프롬프트가 아니라 이 파일의 주석과 docs/ 에 둔다. 모델에게는
  무엇을 하라/하지 마라 + 좋은 예/나쁜 예 하나면 충분하다.
- **코드가 정하는 것은 묻지 않는다.** 화풍·색·재사용·전환·효과·영상/스틸·scene_kind 는 코드가 정한다
  (3단계). 스키마도 그만큼 짧다.
- **게이트는 그대로다.** 이 파일이 줄인 것은 글이지 검사가 아니다. 검사 코드 이름(photo_*)은 모델이
  되돌아온 경고를 알아보도록 그대로 적는다.
- 두 공장 차이는 `_FACTORY` 표 하나로 끝낸다(논문: claim_ids / 리포트: 논증 단위·컴플라이언스).

★ 화풍 문자열을 바꾸면 `config.PROMPT_CONTRACT_VERSION` 을 올려야 한다 — 이 파일은 화풍을 건드리지
  않는다(화풍은 config.VISUAL_ROLE_STYLE 셋이 정본).
"""

from __future__ import annotations

from . import config, narrative

_SEQUENCE_ROLES = "|".join(config.SEQUENCE_ROLES)
_VISUAL_OPERATIONS = "|".join(config.VISUAL_OPERATIONS)
_CAMERA_OPERATIONS = "|".join(config.CAMERA_OPERATIONS)
_CONTINUITY_MODES = "|".join(config.CONTINUITY_MODES)
_CAMERA_BASES = "|".join(config.CAMERA_BASES)
_MUTATION_OPERATIONS = "|".join(config.MUTATION_OPERATIONS)
_REPRESENTATION_MODES = "|".join(config.REPRESENTATION_MODES)
_BEAT_KINDS = "|".join(config.BEAT_KINDS)
_EVIDENCE_ROLES = "|".join(config.EVIDENCE_ROLES)
_OVERLAY_TYPES = "|".join(config.OVERLAY_TEXT_TYPES)
_POINTER_ZONES = " / ".join(config.OVERLAY_POINTER_ZONES)
_CAMERA_OPS = "|".join(config.CAMERA_OPERATIONS)
_MUTATIONS = "|".join(config.MUTATION_OPERATIONS)

# ─────────────────────────────────────────────────────────────
# 시스템 프롬프트 — 역할·사실 규칙·출력 형식. 계약은 아래 guidance() 가 사용자 프롬프트에 싣는다.
# ─────────────────────────────────────────────────────────────
_FACTORY: dict[str, dict[str, str]] = {
    "paper": {
        "role": "논문 대중화 숏폼 영상의 연출가 겸 스토리 작가",
        "source_key_example": '"what_found[0]", "numbers[1]"',
        "fact_rules": (
            "- 각 컷은 claim_ids 로 자기가 지불하는 주장을 명시한다(원장에 있는 id 만). 연결어·질문 컷만 예외다.\n"
            "- 출처는 구체 지칭한다(기관 > 저자명 > 게재처, source 에 있는 것만). 없는 기관·저자를 지어내지 마라.\n"
            f"{config.EVIDENCE_RULES_SHARED}\n"),
        "compliance": "",
    },
    "report": {
        "role": "증권사 리포트 대중화 숏폼 영상의 연출가 겸 스토리 작가",
        "source_key_example": '"numbers[0]", "basis[1]", "opinion"',
        "fact_rules": (
            "- 한 컷에 소리 내 읽는 숫자는 대표값 1개. 나머지 수치는 화면 카드가 담당한다.\n"
            "- 출처는 \"OO증권에 따르면\"처럼 증권사를 구체 지칭한다(source 에 있는 것만). 한두 번이면 된다.\n"),
        "compliance": (
            "\n★ [컴플라이언스 금지] 매수/매도/보유 등 투자행동 권유, 미실현 수익률·상승여력% 광고, 단정적 미래 예측,\n"
            "  리포트를 '내 분석'인 척 서술(반드시 \"OO증권에 따르면\"으로 귀속) — 하나라도 어기면 실패.\n"
            "  [컴플라이언스 필수] 목표가·의견은 사실 인용만, 출처(증권사) 최소 1회, 리스크 한 줄 포함.\n"
            "  면책 문구를 나레이션으로 낭독하는 전용 컷을 만들지 마라(면책은 하단 자막으로 렌더된다).\n"),
    },
}


def system_prompt(factory: str) -> str:
    f = _FACTORY[factory]
    return f"""너는 {f['role']}다. 입력은 "대본(script_md)" + "Fact Sheet" + 기존 "장면들(scenes 초안)"이다.
이것들만으로 실사형(photo) "컷별 제작 지시서"를 JSON 으로만 출력한다 — 설명·마크다운·코드펜스 금지.

★ 절대 규칙(사실):
- Fact Sheet/대본에 근거 없는 내용은 절대 넣지 마라. 각 컷은 source_facts 로 근거 키를 명시하라
  (예: {f['source_key_example']}). 근거가 없으면 그 컷을 만들지 마라.
{f['fact_rules']}- 나레이션은 KO/EN 둘 다 쓴다. EN 은 KO 의 자연스러운 번역(직역 금지). 한 컷은 나레이션 한 문장이다.
- 화면에 읽히는 글자는 전부 overlay_plan(코드 그래픽)이 담당한다. 이미지에 글자를 굽지 않는다.
{f['compliance']}
출력 형식과 규칙은 사용자 메시지의 [실사형 계약]·[출력 스키마]를 따른다. 필드 이름과 허용 토큰은 그대로 쓴다."""


# ─────────────────────────────────────────────────────────────
# 계약 — 절 하나에 한 뜻. 순서가 곧 작업 순서다(서사 → 컷 → 세계 → 화면 구성 → 도해 → 글자 없음 → 움직임 → 카드).
# ─────────────────────────────────────────────────────────────

# 첫 3초 규칙(2026-09-28, 운영자 승인). 벤치마크 첫 컷: "피일까요?" + 핏물 고인 고기.
# 우리 첫 컷 중앙값은 26자(≈5초)였고 수수께끼형 제목의 조선업 편이 시청 비율 67.5% 로 가장 잘 됐다.
# 3.11 호환 — f-string 안에 같은 따옴표를 쓰지 않으려고 밖에서 만든다.
_HOOK_EXAMPLES_TXT = " · ".join(f'"{p}"' for p in config.HOOK_EXAMPLE_PHRASES)
HOOK_CUT_RULE: str = f"""
[첫 3초 — 컷1] 시청자는 첫 3초에 넘길지 정한다.
  ① 컷1 나레이션은 **질문·역설 한마디, 한국어 {config.HOOK_CUT_MAX_CHARS_KO}자 이내(약 3초)**다.
     **이 영상 대본의 첫 문장을 줄여서** 만든다 — 소재가 그 영상의 것이어야 한다.
     형식 예시(다른 영상의 것 — **그대로 쓰면 차단된다**, photo_hook_copied_example): {_HOOK_EXAMPLES_TXT}
     나쁨(너무 김): "삼성전자 목표주가가 63만 원까지 상향된 이유, …였습니다."
     설명·출처·수치는 **컷2 부터**. 넘으면 photo_hook_cut_too_long 으로 되돌아온다.
  ② 컷1 화면은 그 질문을 **사건으로** — 원인이 주인공에게 작용하는 순간(소리의 파동이 상처 난 세포층에 닿는다). 물건만
     가까이 놓으면(스피커 앞 접시) 아무 일도 안 일어난다. 전경·사무실·전광판 금지.
  ③ 컷1 뒤는 **대본의 4막 순서**(문제 제기 → 오해 또는 문제 상황 → 반전 또는 원리 → 결과/결론)를 그대로 따른다.
     마지막 컷은 컷1 의 질문에 답한다. 출처 이름은 한두 번만 — 매 컷 "OO은 …했습니다"로 시작하지 마라.
  ④ header.hook_ko/hook_en 은 **상단 고정 부제**다 — 컷1 나레이션과 다른 문장, 제목처럼 20자 내외.
"""

CUT_RULES: str = f"""
[컷] 한 컷 = 나레이션 한 문장(2~4초), 문장이 끝나는 곳에서 화면이 바뀐다. 컷 수·기전 컷 수는 아래 [컷 수]가 정한다.
  · 컷마다 visual_role 을 선언한다 — **MECHANISM**(원리를 보여주는 도해: 단면·흐름·전후) 또는 **REALITY**(실제 현장·물건·사람).
    **도해할 물리적 대상이 없는 문장**(메타분석·통계 재분석·연구 설계 언급·'효과가 일관적이었다' 류)은 MECHANISM 이 아니라
    REALITY 다 — 데이터를 들여다보는 연구자, 쌓인 논문, 실험실 책상. **추상 3D 로 도망가지 마라.** 사람은 실제 사람으로.
  · evidence_role 은 정직하게: 그 컷의 claim 이 실제로 그 역할을 지불해야 한다(photo_role_claim_mismatch).
  · 원리(evidence_role='mechanism')는 결과·숫자를 말한 **직후**에 둔다. 연구 조건(대상·기간·표본)은 한 컷에 합친다 —
    시청자는 원리를 만나기 전에 떠난다.
  · 연구 대상(동물·시료·장비)이 화면의 35% 를 넘지 않게. 절차 컷(주사·케이지·측정)은 한 컷까지.
  · **주인공이 세포·조직·분자 크기면 관찰 결과도 그 눈높이로**: "세포가 빈틈을 메웠다"는 실험대 위 접시가 아니라 **세포 단면
    도해**(MECHANISM) — 세포들이 돌기를 뻗어 빈틈으로 기어 들어간다. 세포는 둥근 핵·반투명한 막·뻗는 돌기로(덩어리·자갈은
    모래알이 된다). 실험실 장면은 여는 앵커로 한두 컷만.
  · 영상/스틸·전환·효과·scene_kind 는 **코드가 정한다** — 적지 마라.
"""

WORLD_RULES: str = """
[세계 — 시퀀스] 컷 하나에 세계 하나를 만들지 마라. **같은 세계가 단계적으로 변하면서** 설명이 진행된다(전체 → 내부 → 흐름 → 결과).
  · [세계는 물리적 장소다] world 는 **실제로 가 볼 수 있는 장소나 만질 수 있는 실물** 한 곳이다(실험실·공장 라인·현장·
    단면을 연 장치). 장소를 둘 적으면(공장과 사무실) 모든 컷 그림이 칸으로 쪼개진다 — 장소가 다르면 시퀀스를 나눠라
    (photo_world_multi_place). 주제가 추상적일수록(성격·협업·신뢰) 세계는 **더 구체여야** 한다 — 그 연구가 실제로 벌어진 방,
    참가자가 앉은 자리, 결과가 인쇄된 종이.
  · **화면 속을 세계로 잡지 마라**(인터페이스·대시보드·앱·피드·'digital space'·'abstract space'·'holographic'). 세계가 화면이면
    그 시퀀스의 모든 컷이 UI 렌더가 된다. **소재 자체가 화면일 때**(광고·앱·소셜미디어 연구) — 여기서 대부분 틀린다 —
    화면을 세계로 잡지 말고 **그 화면을 보는 사람과 자리**를 세계로 잡아라: 화면은 세계가 아니라 **세계 안의 물건**(손에 든 폰)
    이고 작게·비스듬히·부분만 보인다. 화면이 집기로 들어간 세계는 통과한다('모니터 여러 대가 놓인 오픈플랜 사무실').
  · [비교·결론 대목의 실물 대안] 그릴 실물이 없어 보이는 대목에도 **연구가 실제로 만들어 낸 물건**이 있다 — 두 결과 비교 →
    **인쇄물 두 장을 나란히** 놓고 한쪽에 손이 얹힌다 / 폰 두 대를 나란히 든 손 / 서류 두 묶음의 두께 차이 · 성과가 늘었다 →
    같은 책상에 **쌓인 양이 달라진** 두 더미 · 결론 → 회의 탁자 위의 인쇄물. 이미지에는 **라벨 없이 차이만**(같은 조명·구도,
    양만 다르게) — 어느 쪽이 무엇인지는 카드가 말한다. **인쇄물을 쓸 때 그 위에 도표를 그리지 마라**('읽을 수 없게'라고 해도
    가짜 도표다) — 보여줄 것은 글자 블록의 결과 종이가 몇 장인지다.
  · 장소가 없는 주제(세포·분자·힘)의 세계는 **주인공이 실제로 있는 자리를 연 단면**('a cutaway of the cell layer covering the
    dish floor, cells with round nuclei and translucent membranes'). 'Microscopic view of …'·탁자 위 교육용 모형·수지 조각은
    쓰지 마라(세포가 자갈·유리 격자 탑이 됐다). 분자·힘은 그 작용을 받는 실물로(섬유 다발이 휜다).
  · 원리 구간은 세계 하나. 바뀌는 것은 장소가 아니라 **축척**(stage 의 camera_base: 광역 → 중경 → 근접).
    연속한 stage 가 같은 camera_base 면 같은 그림이 된다. 최소 하나는 close_detail 이어야 한다(photo_no_close_scale).
  · [결과·한계·결론은 실험실 밖으로 나가라] "세계는 하나"는 원리 구간의 규칙이다. 결과·한계·결론처럼 **시청자의 세계**를
    말하는 구간까지 실험실 탁자에 가두면 영상 전체가 한 장면이 된다 — 그 구간은 사람과 일상 장소(출근길·식탁·거리)로 REALITY
    세계를 새로 연다. 기전 구간은 하나의 세계, 결과·결론 구간은 사람의 세계 — 둘이다.
  · [연결 문장 처방] 물리적 주어가 없는 짧은 연결·평가 문장('…에 직접적인 영향을 미쳤습니다', '결과는 놀라웠습니다')에는
    새 세계를 만들지 마라 — 그릴 것이 없으면 모델은 글자·계기판으로 화면을 채운다. 대신 **앞 컷의 세계를 이어라**(같은 장면·
    같은 개체가 **하던 일을 계속한다** — 카메라만 움직이는 컷은 만들지 마라). 그것도 애매하면 **그 연구가 실제로 벌어진 자리**로 돌아가라(참가자가 앉은 실험실, 쌓인
    결과물). 연결 문장에 **영상 클립을 배정하지 마라** — 그 값은 기전 컷에서 빠진다.
  · **세계를 여는 컷**(NEW_WORLD stage 의 첫 컷)이 그 세계의 유일한 새 그림이다. 뒤 stage 가 움직일 개체는 **전부 여는
    컷의 visual_prompt 에 물체로**(모양·색·개수·자리) 적어라. 여는 컷에 없는 물체는 뒤에서 줄일 수도 키울 수도 없다.
    여는 컷은 world 가 말한 장소와 물건을 그대로 그린다(photo_world_lead_disagrees).
  · 주인공이 바뀌는 stage 는 앞 그림을 참조하지 않는다 — "세계가 하나"는 같은 장소·재질이지 같은 픽셀이 아니다.
  · [같은 사진을 두 번 틀지 마라] 실사형에서 asset_strategy 는 항상 new_asset 이다(적지 마라 — 코드가 정한다). 통일성은
    앞 stage 그림을 참조해 **새 프레임**을 그리는 것으로 얻는다 — 같은 파일을 복사해 나레이션만 바꾸는 것이 아니다.
"""

# 화면 구성 계약 — "장면 자체가 설명이다"(2026-09-24, 운영자 지시). 실측(scripts/staging_shadow.py, 565컷): 실사 컷이
# 나레이션에 답하는 비율 리포트 41%·논문 31%. 도해는 구조를 강제하니 답하고, 실사는 강제가 없어 사진이 됐다.
# ⑤~⑩은 첫 렌더 샘플에 대한 운영자 판정(2026-09-24)이다.
STAGING_CONTRACT: str = """
[화면 구성 — 장면 자체가 설명이다] 컷마다 아래 두 칸을 **먼저** 쓰고, visual_prompt 는 그것을 영어로 옮긴다:
  "answers_ko": "<이 컷이 답하는 질문 — 나레이션이 방금 던진 것. 한 문장. 예: '물이 얼마나 더러운가'>"
  "staging_ko": "<그 답을 보여주는 물리적 연출 — 무엇이 무엇을 한다. 예: '손이 유리병으로 호수 물을 뜨고, 병 바닥에 흙탕이 가라앉는다'>"
  ① 한 컷에 **주인공 하나**. 배경은 비운다(스튜디오·단색 바닥). 부감·터미널·나열·군중은 답이 아니다.
  ② 추상적인 말은 **행위**로 — 돈을 쏟아부었다 → 돌덩이를 구덩이에 쏟는다 / 효과가 없다 → 그 물건 위에 큰 X /
     수요가 몰린다 → 한 입구로 상자가 밀려든다. 수치를 **사물 개수·더미 높이·막대**로 바꾸지 마라 — "4GW"를 엔진 네 대로
     그리면 억지 비교다(photo_number_as_objects). 숫자·글자는 그리지 않는다 — 카드가 쓴다.
  ③ 앞 컷의 물건을 **이어받거나 그 안으로 들어간다**(고기 팩 → 소 → 혈관 → 근육 단면). 새 물건은 이유가 있을 때만.
  ④ 답이 되지 않는 장면은 쓰지 않는다 — "주가는 떨어졌는데 이익은 2배?"에 조선소 전경은 답이 아니다.
     답은 '작은 저울 접시에 놓인 작은 배 모형 하나가, 반대 접시의 큰 엔진 블록에 들려 올라간다' 같은 것이다.
  ⑤ **한눈에 알아볼 사물**로 — "전력망"은 송전탑과 전선, 데이터센터는 서버 랙이 줄지어 선 건물, 부유식 데이터센터는
     **바다 위 바지선에 얹힌 각진 데이터센터 건물**. 그 사물의 대표 형태로 그려라.
  ⑥ **"~해서 ~한다"는 원인이 화면에 있어야 한다.** "자리가 없어서 바다에 짓는다"면 앞 stage 는 빈틈없이 꽉 찬 해안이고
     다음 stage 는 그 앞바다로 플랫폼이 밀려 나가는 그림이다. 결과만 그리면 왜인지 아무도 모른다.
  ⑦ **세계를 이어가되 화면에는 이번 컷의 주인공만.** 앞 컷의 물건은 프레임 밖으로 밀거나 흐려라 — 이어받기는
     "다 남겨 두라"가 아니다.
  ⑧ 범례(legend)는 쓰지 않는다. 색이 무엇인지는 사물이 말해야 한다 — 범례가 필요하면 그림이 덜 된 것이다.
  ⑨ **"~해서 ~한다"는 한 장에 못 넣는다 — 두 stage 로 나눠라.** 원인 stage(꽉 찬 해안) 다음에 결과 stage(밀려 나간
     플랫폼). 같은 세계·같은 카메라, 바뀌는 것은 상태다. 나레이션도 그 두 컷에 나눠 얹어라(photo_cause_not_shown).
  ⑩ 도해 구조의 components 는 **시청자가 한눈에 알아볼 물건**(송전탑·서버 랙·엔진·바지선)이어야 한다. "냉각 채널"·
     "동력 통로" 같은 추상 부품은 정체불명의 코일·상자가 된다(photo_component_unrecognizable).
  검사: 실사 컷의 장면이 나레이션의 주장에 답하는지 판정 모델이 본다. 주제만 같은 사진은 되돌아온다(photo_scene_not_answering).
"""

MECHANISM_RULES: str = """
[도해 — MECHANISM 컷] 화면이 설명을 한다: 단면·절개·분해·흐름 추적·전후 비교·크기 대비. 관련 있는 장면을 적으면 그 컷은
  배경이 된다 — 나쁨 'a modern factory interior' / 좋음 'cutaway cross-section of a battery cell showing the separator
  layer between anode and cathode, one layer highlighted'.
  · **mechanism 구조를 먼저 채우고** visual_prompt 는 거기서 파생시킨다: subject / components(2개 이상) / relationship /
    initial_state / transformation / final_state / highlighted_element — 전부 **영어**(그대로 이미지 프롬프트에 실린다),
    components 는 화면에 보일 **물체 이름**(a damaged neuron, a stacked battery cell — 개념어·지표명·기업명 금지).
    visual_prompt 는 그 components 를 **같은 이름으로** 그린다(photo_mechanism_prompt_detached). 사람이 읽을 한 줄은 mechanism_ko.
    구조를 못 채우면 그 컷은 MECHANISM 이 아니다 — REALITY 로.
  · 기전은 **상태가 아니라 과정**이다: A 가 B 에 작용해서 C 가 된다. 한 화면 안에 왼쪽 원인 → 가운데 작용 → 오른쪽 결과로
    벌리거나, 일이 실제로 벌어지는 지점을 가운데 둔다(화살표·라벨을 그리라는 말이 아니다 — 물체의 **배치**로).
  · 두 대상·전과 후를 비교하는 컷은 **한 장을 반으로 가르지 마라**('Split screen'·'Side-by-side'·'왼쪽에는 …, 오른쪽에는 …'
    는 차단된다). 한 장에 둘을 넣지 마라 — 같은 장면을 유지한 채 **상태를 바꿔라**(같은 파이프가 좁았다가 넓어진다).
    상태가 바뀌는 stage(TRANSFORM·GROW·SHRINK·SPLIT_OFF·MERGE_INTO)는 코드가 전·후를 위·아래로 붙인 한 장으로 만든다 —
    그 컷의 visual_prompt 는 '후'만 그리고, label_pair(payload.top/bottom, 한글 짧게)로 위·아래가 무엇인지 말한다.
  · **차이는 판정이 아니라 물체로** — 생성 모델은 '건강함·개선·더 활발함'을 그릴 수 없다(photo_undrawable_difference).
    금지: healthier, more active, improved, better, enhanced, more pronounced, vibrant, glowing, revitalized, superior.
    눈으로 셀 수 있는 차이(형태·색·개수·거리·높이·기울기)로: 'the right model is assembled from whole, tightly packed parts;
    the left one has gaps and two pieces lying detached beside it'.
  · 색은 셋뿐이다 — amber=설명하는 부분, muted blue=첫 집단·변화 전, muted coral=둘째 집단·변화 후. **표면색**으로 적는다
    ('the left model is muted blue'). 한 개체는 처음부터 끝까지 한 색이고, 그 두 색을 **개체 안의 부위 구분**으로 다시 쓰지
    마라(photo_color_code_reused). 부위는 amber 강조로, 커지고 작아지는 것은 크기·모양으로.
  · 금지(그대로 쓰면 폐기): abstract, conceptual, symbolic representation, data visualization, data points, glowing orb/cube/blocks,
    floating particles, aura, clusters merging. **아이콘 인포그래픽도 같은 금지다**: icon(s), pictogram, gauge, meter bar, bar graph
    rising, dashboard-like panel, 'clean digital interface'. 이 버전은 REALITY 와 MECHANISM 둘뿐이고 **인포그래픽은 셋째 선택지가
    아니다** — 아이콘을 그리고 싶어지면 그 컷은 REALITY 다(사람·장비·결과물이 있는 실제 장면).
    절차·집단·비교도 **셀 수 있는 실물**(사람·약병·동전·서류 묶음)을 배치하면 도해가 된다.
  · 소재에 기전이 정말 없으면(순수 상관·메타분석) 지어내지 마라 — 연구진의 해석을 그 자리에 놓고 해석임을 밝혀라.
"""

# 화면 그래픽·글자 요구 금지(2026-08-31 개정). 필드 중립 — visual_prompt·motion_prompt 어느 쪽에 적든 같다.
SCREEN_GRAPHIC_BAN_GUIDANCE: str = """
[화면 그래픽 금지 — visual_prompt·motion_prompt **둘 다**] 화면에 그래픽·오버레이·라벨·치수선·계기판·로고·글자가 있거나
  나타난다고 쓰지 마라. 생성 모델은 필드를 구분하지 않고 합쳐서 그린다. 부정문('no on-screen text', 'fictional')을 붙여도
  금지다 — 요구와 금지를 한 문장에 넣으면 글자가 그려진다.
  금지 예: 'a graphic overlay appears indicating…', 'annotation lines mark…', 'a readout shows…', 'a subtle logo of a fictional
  university', "text animation of the word 'Astonishing'", 'a computer screen showing a data visualization'.
  · **대상에 따옴표로 이름을 붙이지 마라**('the left model represents "Calorie Restriction"') — 그 이름이 글자로 그려지고
    한국어판·영어판이 공유하는 이미지가 깨진다. 두 대상은 **생김새로** 구별되게 적어라.
  · **지도·지구본도 그리지 마라** — 나라 경계를 틀리고 지명을 지어낸다. 지역 편중은 물체의 양으로.
  · **화풍 형용사를 쓰지 마라** — 화풍은 코드가 역할에 따라 붙이고, 네가 쓰면 네 쪽이 이겨 원하지 않은 그림이 나온다(차단):
    stylized, photorealistic, 3D render, CGI, illustration,
    painterly, cel shading, line art, anime, cartoon, low poly, cinematic still, depth of field, bokeh, macro detail, lens flare,
    film grain, motion blur, blurred, out of focus. world.style·lighting·background 에도 똑같다.
  · 대신: 화면에 얹히는 글자·수치·출처는 overlay_plan 이 코드로 그린다(아래 [카드]). 소속·기관은 로고가 아니라 **장소로**.
"""

MOTION_RULES: str = f"""
[움직임] 영상(I2V)으로 만들 컷은 **코드가 정한다** — 도해 컷 전부와 훅·마무리 컷을 우선하고, 붙어 있게 배치한다.
  너는 **도해 컷·컷1·마지막 컷**에 아래를 적는다(그 밖의 컷은 비워 둔다):
  · motion_prompt(영문): **주인공이 무엇을 하는지 먼저**(세포가 돌기를 뻗어 기어간다), 카메라는 그 행동을 따라갈 때만.
    카메라만 움직이는 motion 금지 — 컷마다 줌이 되풀이돼 슬라이드쇼가 된다(photo_motion_camera_only).
  · [끊기지 않게] 같은 주인공이 이어지는 문장 2~4개는 **한 stage**(cut_refs 여럿) — 이어지는 영상 하나가 된다(photo_stages_fragmented).
  · temporal_plan: 8초를 **비트 2~3개**로 — 예) 0-2.5s 세포층이 빈틈 양쪽에 있다(HOLD) → 2.5-5.5s 세포가 돌기를 뻗는다(MOVE·TRACK) → 5.5-8s 빈틈이 닫힌다(MERGE_INTO·DOLLY_IN).
    비트마다 시간 구간·변하는 개체(entity_id)·변화(mutation)·카메라(camera). 토큰만 쓴다: mutation {_MUTATIONS} / camera {_CAMERA_OPS}.
    ① 카메라 중 하나는 HOLD 가 아니어야 하고 비트마다 다르게 ② 변이 중 하나는 실제 변형(MOVE·GROW·SHRINK·ROTATE·TRANSFORM·
    SPLIT_OFF·MERGE_INTO·IMPACT)이어야 한다 — **APPEAR·HIGHLIGHT 만으로 끝내지 마라**, 정지 화면으로도 성립해 8초를 못 받는다
    (photo_stage_no_transformation).
"""


def overlay_rules(factory: str) -> str:
    legend = (" · legend: payload.items=[{color, label(한글)}] — 기전 시퀀스마다 하나."
              if config.OVERLAY_LEGEND_ENABLED else "")
    source_card = ("  · 수치가 나오는 컷은 **반드시** 그 수치의 출처를 같은 화면에 둔다(source_card) — 나레이션에서 증권사를\n"
                   "    말했더라도 카드는 별도로 필요하다.\n" if factory == "report" else "")
    return f"""
[카드 — overlay_plan] 화면의 글자·숫자는 전부 여기다. 한 컷에 최대 {config.OVERLAY_MAX_PER_CUT}개, 각 {config.OVERLAY_MIN_SEC:g}초 이상.
  · 숫자를 말하는 **모든** 컷(컷1 포함)에 number_punch — **수치와 단위만**('254MW', '+16.9%', '12.7km'). 문장을 넣지 마라
    (설명은 evidence_card 로). 표본·기간·대상 → scope_tag / 출처 → source_card / 단서 → caveat_tag.
{source_card}  · 풀이 카드(type: keyword)는 **약어·어려운 개념·뜻이 안 와닿는 수치가 나오는 컷에만** — term + gloss_ko + gloss_en:
    HBM → "고대역폭 메모리" · PBR 3.5배 → "자산 가치의 3.5배" · 중속 엔진 → "발전소용 중형 엔진". 용어 {config.OVERLAY_GLOSS_TERM_MAX_CHARS}자·풀이
    {config.OVERLAY_GLOSS_MAX_CHARS}자 이내, 컷당 하나. 나레이션이 이미 쉬운 말로 풀었거나 영어 요약어(GRID BOTTLENECK)뿐이면 붙이지 마라.
  · 위·아래 전후 분할 컷 → label_pair(payload.top/bottom){legend}.
  · pointer(화살표)는 웬만하면 쓰지 마라 — 설명할 대상이 화면에서 제일 크고 한가운데 오게 구도를 짜라. 그래도 필요하면
    구역 이름({_POINTER_ZONES})만 적는다(좌표 금지 — 너는 그 그림을 본 적이 없다).
  · visual_prompt·motion_prompt 에 '카드가 나타난다'·'숫자가 뜬다'를 적지 마라 — 카드는 렌더가 그린다.
"""


# 리포트 전용 — 증권 리포트의 "원리"는 논증 단위다(2026-09-24, 운영자 승인). 단계의 종류는 코드가 가른다(report_reasoning.step_kind).
REPORT_MECHANISM_RULES: str = """
[리포트의 원리 = 논증 단위] 리포트에는 논문의 "왜 그런가" 대신 아래 논증 단위(driver → 실적 → 밸류에이션)가 있고,
  각 단계에 코드가 kind 를 적어 뒀다 — **그 kind 가 화면을 정한다**:
  · kind 가 **과정** 인 단계 → MECHANISM 도해. 전·후가 있는 **물리적 과정**만: 공급망 흐름(광산 → 셀 → 데이터센터), 수요 전이
    (전기차용 → ESS용), 병목 → 우회(전력망이 막힌다 → 바다 위 바지선이 우회한다), 설비 증설. 논증 단위 하나가 시퀀스 하나다.
  · kind 가 **숫자** 인 단계 → **REALITY 실사 장면 + 숫자 카드**. MECHANISM 금지 —
    크기 다른 블록·막대·높이 차이로 수치를 보이는 것은 그래프다(차단된다).
  · kind 가 **리스크** 인 단계 → **REALITY 실사 장면 + 한 줄 카드**, 또는 나레이션만. MECHANISM 금지 — 규제를 장벽·쇠쐐기로
    그리면 원문에 없는 은유가 된다(차단된다).
  · 도해에 숫자를 그리지 마라. 도해는 구조와 방향만 보여주고 숫자는 카드가 얹는다.
  · stage·mutation 의 claim_ids 에는 **논증 단계 참조(R01_2)** 또는 Fact Sheet 키(basis[1]·numbers[0]·num_*)를 쓴다.
  · REALITY 소재: 공장·생산라인·물류·항만·제품 실물. 얼굴 클로즈업·정장 인물·악수·증권 전광판·돈다발·상승 화살표 클리셰 금지.
"""


# ─────────────────────────────────────────────────────────────
# 출력 스키마 — 모델이 정하는 칸만. 나머지(화풍·색·전환·효과·영상/스틸·scene_kind·재사용)는 코드가 채운다(3단계).
# ─────────────────────────────────────────────────────────────
SEQUENCE_SCHEMA: str = f"""
  "visual_sequences": [
    {{ "sequence_id": "<SEQ1 …>",
       "sequence_role": "<{_SEQUENCE_ROLES} 중 1>",
       "world": {{ "world_id": "<이 시퀀스가 머무는 세계의 이름>",
                  "style": "<이 세계가 **어디인가** 한 구절 — 장소·공간·거기 놓인 것. 화풍·재질·렌더 방식·카메라·렌즈 금지."
                  " 좋음 'A cell culture room with incubators and a steel bench'. **장소는 한 곳만** — 둘을 적으면 모든 컷"
                  " 그림이 칸으로 쪼개진다(photo_world_multi_place). 장소가 다르면 시퀀스를 나눠라>",
                  "lighting": "<그 장소의 **광원** 한 구절(창·형광등·작업등). 분위기·발광 효과 금지>",
                  "background": "<뒤에 **무엇이 있는가** 한 구절. 'blurred' 금지 — 거리로 말한다('further back along the far wall')>",
                  "camera_base": "<{_CAMERA_BASES} 중 1>",
                  "style_ko": "<style 을 한국어로>", "lighting_ko": "<lighting 을 한국어로>", "background_ko": "<background 를 한국어로>" }},
       "entities": [
         {{ "entity_id": "<PARTICIPANT_A / TOKEN_SET 처럼 대문자 식별자>",
            "entity_type": "<person|object|structure>",
            "visual_identity": "<이 개체를 매 stage 같게 만들 외형 한 구절>",
            "visual_identity_ko": "<위 외형을 한국어로>" }} ],
       "stages": [
         {{ "stage_id": "<S1 …>",
            "cut_refs": [<이 stage 가 담당하는 컷 번호들>],
            "operation": "<{_VISUAL_OPERATIONS} 중 1>",
            "camera_operation": "<{_CAMERA_OPERATIONS} 중 1>",
            "camera_base": "<{_CAMERA_BASES} 중 1 — **이 stage 의 축척**. 세계가 하나여도 stage 마다 바꿔라. 최소 하나는 close_detail>",
            "continuity_mode": "<{_CONTINUITY_MODES} 중 1>",
            "continuity_from": "<이어받는 **앞선** stage_id. NEW_WORLD 면 빈값>",
            "entity_refs": ["<이 stage 에서 유지되는 entity_id>"],
            "representation_mode": "<{_REPRESENTATION_MODES} 중 1>",
            "allow_connective": false,
            "mutations": [
              {{ "entity_id": "<위 entities 에 선언한 id>",
                 "property": "<무엇이 바뀌는가 — position/size/state/rotation …>",
                 "operation": "<{_MUTATION_OPERATIONS} 중 1>",
                 "visible_change": true,
                 "result_state": "<바뀐 뒤 그 개체가 어떻게 보이는가 한 구절>",
                 "claim_ids": ["<이 변화가 지불하는 claim_id>"] }} ],
            "state_before": {{ "<개체 id>": "<이전 상태>" }},
            "state_after":  {{ "<개체 id>": "<이후 상태>" }},
            "observable_change": "<화면에서 눈에 보이게 달라지는 것 한 문장(영어)>",
            "observable_change_ko": "<바로 위 문장을 한국어로>",
            "claim_ids": ["<이 stage 가 지불하는 claim_id>"] }} ] }}
  ],
"""


def output_schema(factory: str) -> str:
    paper = factory == "paper"
    header_extra = (
        '    "content_mode": "<입력 content_plan 을 따르라>",\n'
        '    "primary_claim_id": "<핵심 주장 claim_id>", "supporting_claim_ids": ["<보조 주장 claim_id>"],\n'
        '    "essential_evidence_units": ["<E1~E8 중 이번 영상에 필수인 것>"],\n'
        '    "duration_reason": "<왜 이 길이인지 한 문장>",\n' if paper else "")
    cut_extra = (
        '      "claim_ids": ["<이 컷이 지불하는 claim_id — 원장에 있는 것만>"],\n' if paper else
        '      "reasoning_id": "<이 컷이 옮기는 논증 단위 id(예: R01) — 아래 목록에 있는 것만. 옮기지 않으면 빈값>",\n'
        '      "reasoning_step": <그 논증의 단계 번호(목록의 step). 옮기지 않으면 0>,\n')
    return f"""
[출력 스키마] JSON only.
{{
  "header": {{
    "hook_ko": "<상단 고정 부제 — 컷1 나레이션과 다른 문장, 20자 내외>",
    "hook_en": "<top caption — a different sentence from cut 1, title-short>",
    "bgm": {{ "mood": "<차분|긴장|경쾌 등>", "track_ref": "" }},
    "total_estimated_sec": <int>,
{header_extra}  }},
{SEQUENCE_SCHEMA}  "cuts": [
    {{
      "cut_no": <int>,
      "narration_ko": "<한국어 나레이션 한 문장>", "narration_en": "<영어 나레이션>",
      "estimated_sec": <int — 나레이션 길이에서. 한 컷 {config.PHOTO_CUT_SEC_MAX}초를 넘기지 마라>,
      "source_facts": ["<Fact Sheet 항목 키>"],
{cut_extra}      "evidence_role": "<{_EVIDENCE_ROLES} 중 1>",
      "beat": "<{_BEAT_KINDS} 중 1 — 이 컷이 설명에서 맡은 역할>",
      "visual_role": "<MECHANISM|REALITY>",
      "answers_ko": "<이 컷이 답하는 질문(한 문장)>",
      "staging_ko": "<그 답을 보여주는 물리적 연출(한두 문장)>",
      "visual_prompt": "<staging_ko 를 그대로 옮긴 이미지 생성용 영문 프롬프트 — 무엇을 보여줄지만>",
      "visual_prompt_ko": "<위 영문이 무엇을 그리라는 것인지 한국어 한두 문장>",
      "mechanism": {{ "subject": "", "components": [], "relationship": "", "initial_state": "", "transformation": "",
                     "final_state": "", "highlighted_element": "", "claim_ids": [] }},
      "mechanism_ko": "<MECHANISM 컷만: 위 구조를 한국어 한 문장으로>",
      "overlay_plan": [ {{ "type": "<{_OVERLAY_TYPES} 중 1>", "text": "<카드 문구>",
                           "payload": {{ "<label_pair>": "top / bottom", "<pointer>": "at: [구역]", "<legend>": "items: [{{color, label}}]" }},
                           "term": "<keyword 일 때>", "gloss_ko": "<쉬운 풀이>", "gloss_en": "<English gloss>",
                           "claim_ids": [], "start_sec": <컷 시작 기준 초>, "duration_sec": <int>, "priority": "primary|supporting" }} ],
      "motion_prompt": "<도해 컷·컷1·마지막 컷만: 카메라·피사체 모션 영문. 그 밖은 빈값>",
      "temporal_plan": [ {{ "t0": <초>, "t1": <초>, "entity_id": "<변하는 개체>", "mutation": "<토큰>", "camera": "<토큰>" }} ]
    }}
  ]
}}
"""


def guidance(factory: str) -> str:
    """사용자 프롬프트 앞머리 — [실사형 계약] 전체. 동적인 것(모드·컷 수·원문 확보 수준·골격)은 호출부가 뒤에 붙인다."""
    parts = [
        "[실사형 계약 — photo] 이 버전의 핵심은 화풍이 아니라 **화면이 설명을 하는가**다. 아래 절 순서대로 정하라.",
        narrative.NARRATIVE_ARC,
        HOOK_CUT_RULE,
        CUT_RULES,
        WORLD_RULES,
        STAGING_CONTRACT,
        MECHANISM_RULES,
        REPORT_MECHANISM_RULES if factory == "report" else "",
        SCREEN_GRAPHIC_BAN_GUIDANCE,
        MOTION_RULES,
        overlay_rules(factory),
        output_schema(factory),
    ]
    return "".join(p for p in parts if p)
