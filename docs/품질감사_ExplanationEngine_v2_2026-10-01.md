# VIDEO-ARTICLE 최근 제작물 품질 감사
## Source → Reasoning → Script → Narration → Visual 단계별 역추적
**기준일:** 2026-10-01  
**대상 저장소:** `dekt-oss/VIDEO-ARTICLE`  
**감사 범위:** 최근 실제 발행물 3편 + Production DB의 원문/Fact Sheet/Reasoning/대본/Directive/Analytics  
**코드 변경:** 없음

---

# 0. 감사 목적

이번 감사의 목적은 “현재 저장소에 어떤 기능이 있는가”를 확인하는 것이 아니다.

실제 최근 VIDEO-ARTICLE 제작물을 역추적하여 다음 질문에 답하는 것이 목적이다.

> **최종 영상이 여전히 ‘오래된 LLM이 논문/리포트를 요약해 읽어주는 느낌’이 나는 원인은 정확히 어느 단계에서 발생하는가?**

감사 단계:

```text
SOURCE
↓
FACT / EVIDENCE
↓
REASONING
↓
STORY / SCRIPT
↓
SPOKEN NARRATION
↓
VISUAL PLANNING
↓
RENDER
```

이번 감사에서는 최종 MP4 파일을 이 세션에서 직접 프레임 단위 재생하지 못했다.
따라서 Visual 평가는 Production에 실제 저장된 `directive / visual_sequence / stage / mutation / render QA`를 기준으로 한다.
최종 픽셀·음향 수준 평가는 후속 Render Audit에서 별도로 수행한다.

---

# 1. 감사 대상

## A. 논문 영상

### Heel-strike mechanics reveal evolutionary trade-offs in hominin bipedalism

- PNAS
- Production Source: `full_body`
- 확보 본문: 약 60,000자
- 한국어 발행 영상 길이: 67초
- 2026-10-01 Analytics snapshot:
  - 조회수 923
  - 평균 시청시간 38초
  - 평균 시청률 56.97%

---

## B. 증권사 리포트 영상

### 삼성전자 — 메모리 가격 상승폭 둔화보다 사이클 장기화!

- 유안타증권
- Production Source: `full_text`
- 확보 원문: 약 11,997자
- 한국어 발행 영상 길이: 66초
- 2026-10-01 Analytics snapshot:
  - 조회수 198
  - 평균 시청시간 79초
  - 평균 시청률 120.41%
- 표본이 작고 재시청/루프 영향을 받을 수 있으므로 성과 우열의 근거로 사용하지 않는다.

---

## C. 투자전략 리포트 영상

### NH 전략인사이드/경제 — AI 투자 / Mid Cycle

- NH 리서치
- Production Source: `partial_text`
- 확보 원문: 약 1,072자
- 한국어 발행 영상 길이: 50초
- 2026-10-01 Analytics snapshot:
  - 조회수 13
  - 시청지속 데이터 아직 유효 표본 없음

---

# 2. 전체 감사 결론

가장 중요한 결론은 다음과 같다.

> **현재 VIDEO-ARTICLE의 근본 병목은 Renderer 하나가 아니다.**
>
> 저장소에는 이미 Story Plan, Claim Ledger, Reasoning Unit, Beat, Visual Sequence, Stage, Mutation 등의 구조가 존재하지만, 실제 콘텐츠 품질을 보장하는 `Explanation Reasoning` 단계가 약하고 각 단계 사이의 계약도 일부 끊겨 있다.

현재 문제를 크게 5개로 분류한다.

```text
1. Source의 깊이에 비해 영상의 설명 깊이를 과도하게 확장한다.
2. Fact/Evidence가 있어도 Explanation 구조로 재구성되지 않는다.
3. Script 단계에서 원문보다 강한 주장·부정확한 일반화가 생긴다.
4. Self-check가 “근거 존재”만 확인하고 실제 문장의 함의를 놓친다.
5. Visual Planner가 좋은 구조를 만들어도 Renderer와 연결되지 않거나,
   반대로 약한 논리를 그럴듯한 화면으로 포장한다.
```

즉 현재 상태는:

> **“좋은 촬영/렌더링 시스템을 만들고 있지만, 앞단의 작가·PD·설명 설계 엔진이 그만큼 발전하지 못한 상태”**

에 가깝다.

---

# 3. 사례 A — Heel-strike 논문

## 3.1 SOURCE

Source 상태는 오히려 좋다.

- Abstract만 확보한 것이 아니라 `full_body` 약 60,000자 확보
- 논문 본문에는 다음 내용이 충분히 존재함
  - 인간과 침팬지 보행 차이
  - heel-strike / midfoot-strike
  - 충격력
  - 대사 비용
  - center of pressure
  - 진화적 trade-off
  - 실험 방법
  - 표본 한계

따라서 이 영상의 품질 저하는 **원문 부족이 주원인이 아니다.**

### 판정

`SOURCE: 양호`

---

# 3.2 FACT / EVIDENCE

Fact Sheet 역시 상당히 풍부하다.

예:

- 침팬지의 발 접촉 각도 범위는 인간보다 2.4~8.6배 넓음
- 인간이 forefoot-first로 걸으면 대사 에너지를 26~41% 더 사용
- heel-strike 시 impact force / loading rate 증가
- heel-strike가 center of pressure의 전방 이동을 통해 기능적 사지 길이를 늘릴 수 있다는 기전
- 침팬지 표본 n=3이라는 한계

Claim Ledger도 원문 quote와 연결되어 있다.

즉 Fact Extraction 자체는 상당히 발전했다.

### 판정

`FACT/EVIDENCE: 양호`

---

# 3.3 SCRIPT 단계에서 실제 사실 왜곡 발생

원문은 명확히 말한다.

> African apes도 heel-strike를 사용하는 동물들에 포함되며, 침팬지는 heel-strike를 덜 자주 사용할 뿐이다.

그런데 생성 대본은 다음과 같이 바뀌었다.

> **“인간은 모든 유인원 중 유일하게 발뒤꿈치부터 땅에 닿는 독특한 보행 방식을 사용합니다.”**

이것은 단순 표현 차이가 아니다.

`African apes도 heel-strike한다`는 원문과 충돌한다.

더 심각한 문제는 Self-check가 이 장면을:

```text
grounded = true
scope_match = true
unsupported = []
korean_natural = true
```

로 통과시켰다는 것이다.

### 원인

현재 검증이 다음 정도만 확인하는 것으로 보인다.

```text
문장에 연결 가능한 Fact가 있는가?
숫자는 맞는가?
대략 같은 주제를 말하는가?
```

하지만 다음 차이를 잡지 못한다.

```text
“인간은 heel-strike를 항상 한다”
≠
“인간만 heel-strike를 한다”
```

`항상 / 유일하게 / 모든 / 절대 / 최초 / 오직` 같은 **범위·수량·배타성 표현**은 문장의 진실조건을 완전히 바꾼다.

### 판정

`SOURCE → SCRIPT fidelity gate: 실패`

---

# 3.4 Explanation 구조 문제

대본은 다음 흐름이다.

```text
효율적인데 충격이 크다?
↓
인간/침팬지 차이
↓
12명 / 침팬지 3마리 / 4년
↓
26~41%
↓
168~206% / 121~162%
↓
center of pressure
↓
trade-off + n=3 한계
```

정보는 많다.

하지만 시청자에게 가장 필요한 설명 순서는 아니다.

좋은 Explanation이라면 먼저 다음 질문을 설계했어야 한다.

```text
왜 우리는 굳이 뒤꿈치부터 닿을까?
↓
뒤꿈치부터 닿으면 발이 어떻게 굴러가는가?
↓
그 움직임이 왜 에너지를 아끼는가?
↓
대신 충격은 왜 커지는가?
↓
침팬지는 왜 더 다양한 방식으로 착지하는가?
↓
이 trade-off가 진화적으로 무엇을 의미하는가?
```

현재 대본은 `연구 결과 나열 → 뒤늦게 원리` 구조다.

벤치마크 Shorts가 보여준:

> 질문 → 내부 원리 → 결과

가 아니라,

> 결과 → 결과 → 수치 → 수치 → 원리

에 가깝다.

### 판정

`REASONING / EXPLANATION DESIGN: 미흡`

---

# 3.5 Content Mode 계약도 실제 산출과 충돌

Draft self-check에는:

```text
forced_series_split_multiple_main_claims
mode_overridden: standard -> series_split
too_many_spoken_numbers
spoken_number_count = 9
```

경고가 있다.

그런데 실제 결과는:

- 한 편으로 제작됨
- 67초
- 다수 숫자 사용
- Directive에서 17 cuts로 확장

즉 시스템 스스로:

> “이건 한 편에 너무 많다.”

라고 판단했지만 Production은 그대로 진행했다.

### 판정

`CONTENT MODE GATE: 선언은 있으나 실행력이 약함`

---

# 3.6 Narration 문제

문장 자체는 문법적으로 틀리지 않더라도 TTS용 spoken language로는 무겁다.

예:

> “발뒤꿈치 보행은 발 아래 압력 중심의 전방 이동을 증가시켜 효과적인 사지 길이를 늘림으로써 보행의 대사 비용을 줄일 수 있습니다.”

논문 문장에 가깝다.

시청자에게는 다음 식의 단계적 설명이 더 적합하다.

```text
뒤꿈치가 먼저 닿으면,
발바닥의 접점이 뒤에서 앞으로 이동합니다.

그러면 다리가 조금 더 긴 지렛대처럼 작동합니다.

같은 거리를 걸을 때
근육이 해야 할 일이 줄어드는 겁니다.
```

현재 Self-check의 `korean_natural=true`는 **문법 자연스러움과 음성 설명 자연스러움을 구별하지 못한다.**

### 판정

`NARRATION / TTS LISTENABILITY: 미흡`

---

# 3.7 Visual Planning

흥미로운 점은 Visual Planner가 대본보다 오히려 더 발전해 있다는 것이다.

Directive에는 이미:

```text
CUTAWAY
FLOW
IMPACT
GROW
TRACK
DOLLY_IN
Stage Mutation
Mechanism Specification
```

등이 존재한다.

하지만 일부 장면은 여전히:

```text
연구자 손 + 데이터 시트
서류철 3권
연구실 책상
```

같은 간접적 visual metaphor로 빠진다.

특히 `mechanism`을 설명할 수 있는 소재가 있는데도, 결과/한계 장면에서 문서·책상·폴더 같은 generic visual이 많이 사용된다.

### 판정

`VISUAL PLAN: 중간 이상`

단, 앞단 Explanation이 약해 Visual Planner도 무엇을 가장 중요한 원리로 보여줘야 하는지 흔들린다.

---

# 4. 사례 B — 삼성전자 리포트

# 4.1 SOURCE / FINANCIAL REASONING

이 사례는 반대다.

- `full_text` 약 11,997자 확보
- Financial Reasoning은 4개 unit / 13 step
- Source quote 검증률 100%
- Driver chain / Valuation logic / Catalyst / Risk가 구조화되어 있음

즉 금융 Reasoning의 **원재료는 상당히 좋다.**

예:

```text
HBM4 판매 본격화
↓
DRAM/NAND 가격
↓
DS 실적
```

```text
HBM의 DRAM 생산능력 잠식
+
AI 추론 수요
↓
공급 제약 장기화
↓
업사이클 장기화
↓
FCF 확대 가능성
```

```text
2027 실적 추정
↓
Target PBR 3.5x
↓
목표주가 630,000원
```

### 판정

`SOURCE: 양호`
`FINANCIAL REASONING: 양호`

---

# 4.2 Story Plan은 여전히 “리포트 압축”에 가까움

Audience Question:

> 왜 목표주가를 63만원까지 올렸을까?

Thesis:

> HBM과 AI 수요 → 메모리 업사이클 장기화 → 2027 실적 상향 → 목표가 63만원

방향은 맞다.

그러나 실제 대본은:

```text
63만원
↓
반도체 100조
↓
HBM / AI
↓
PBR 3.5배
↓
피크아웃
```

정도로 압축되어 있다.

중요한 Explanation Bridge가 빠졌다.

예:

```text
왜 HBM이 일반 DRAM 생산능력을 잠식하는가?
왜 AI 추론 확산이 고용량 메모리 수요를 늘리는가?
공급이 타이트하면 왜 가격과 이익이 크게 움직이는가?
PBR 3.5배는 무엇을 뜻하는가?
```

시청자가 산업·밸류에이션을 이미 아는 것으로 가정한다.

따라서 “이해시키는 영상”보다는 “리포트 핵심을 빠르게 읽는 영상”이다.

### 판정

`EXPLANATION DESIGN: 미흡`

---

# 4.3 Domain profile 이상

Story Plan의 `content_profile`이:

```text
paper_explainer
```

로 저장돼 있다.

하지만 실제 콘텐츠는 삼성전자 증권사 리포트다.

이는 단순 이름 문제가 아니라, Domain별 Story Grammar가 앞으로 중요해질수록 잘못된 라우팅 원인이 된다.

### 판정

`DOMAIN ROUTING CONTRACT: 결함`

---

# 4.4 Rich Reasoning이 Directive까지 제대로 전달되지 않음

가장 중요한 발견 중 하나다.

Financial Reasoning에는:

```text
R01
R02
R03
R04
```

가 풍부하게 존재한다.

하지만 실제 Directive의 주요 컷은:

```text
claim_refs = []
beat_declared = false
evidence_role = connective
```

상태가 반복된다.

즉 상류에서 좋은 논증 구조를 만들어 놓고 하류 Visual Planning에서 상당 부분 잃고 있다.

이 결과 Visual Router는 대부분:

```text
RESULT
CODE_VIZ
connective
```

같은 fallback 성격으로 처리한다.

### 판정

`REASONING → VISUAL CONTRACT: 실패`

---

# 4.5 Visual은 원리 장면과 숫자 장면의 품질 편차가 큼

좋은 장면:

```text
HBM stack이 wafer 영역을 차지
↓
DRAM 영역 축소
```

이것은 실제 Explanation Visual이다.

반면:

```text
DRAM 가격 상승
→ 완성 칩 패키지

DS 영업이익
→ 반도체 공장 외경

PBR
→ 애널리스트 책상
```

같은 장면은 내용과 관련은 있지만 **설명하지 않는다.**

즉 현재 시스템에서도 좋은 Visual Explainer의 씨앗은 이미 있으나,
Story/Reasoning과 Visual을 연결하는 선택 기준이 약하다.

---

# 5. 사례 C — NH Mid Cycle 리포트

# 5.1 가장 중요한 문제: Source Depth와 영상 깊이 불일치

Source:

```text
partial_text
1,072자
```

사실상 짧은 Web/SMS 요약이다.

그런데 시스템은 이것으로:

- 3 Reasoning units
- 9 steps
- 12 cuts
- 50초 영상

을 만들었다.

이것은 매우 중요한 문제다.

> **Source가 얕은데도 시스템이 깊은 Explainer처럼 행동한다.**

Source Depth는 저장하고 있지만 콘텐츠 제작 깊이를 충분히 제한하지 않는다.

### 판정

`SOURCE ADEQUACY GATE: 실패`

---

# 5.2 Hook에서 근거 없는 사실적 분위기 추가

Story Plan Hook:

> “AI 투자가 벌써 거품의 끝물에 다다랐다는 시장의 공포가 번지고 있다.”

Evidence Ref:

```text
[]
```

Source에는 이런 “시장 공포가 번지고 있다”는 사실이 없다.

Self-check는 Hook을 exempt 처리한다.

문제는 Hook이 단순 질문이면 괜찮지만,
**사실처럼 들리는 Context Claim까지 exemption을 받는다는 것**이다.

다음은 허용 가능하다.

> “지금 AI 투자는 1999년일까요, 1997년일까요?”

다음은 근거가 필요하다.

> “시장에서는 AI 거품 붕괴 공포가 빠르게 번지고 있습니다.”

### 판정

`HOOK GROUNDING POLICY: 결함`

---

# 5.3 Visual Representation Mode 문제

일부 Visual은 실제 macro data를 물리적인 장면으로 치환한다.

예:

```text
기업부채 비율
→ 두꺼운/얇은 binder

낮은 제조업 재고비율
→ 비어 있는 물류 선반

주택투자 감소
→ 멈춘 타워크레인
```

은유 자체는 사용할 수 있다.

하지만 일부 stage가:

```text
representation_mode = LITERAL_OBSERVATION
```

으로 선언된다.

이건 의미적으로 맞지 않는다.

실제 연구·경제 데이터와 illustrative metaphor를 구분해야 한다.

### 판정

`VISUAL SEMANTICS: 결함`

---

# 6. 세 사례를 종합한 Failure Map

| 단계 | 현재 수준 | 핵심 문제 |
|---|---|---|
| Source 확보 | 중~상 | source_depth가 제작 깊이를 충분히 제한하지 않음 |
| Fact/Evidence | 상 | 풍부하지만 explanation에 필요한 prerequisite는 별도 관리 안 됨 |
| Reasoning | 중 | 구조는 있으나 Summary/Report logic과 Explanation logic이 혼재 |
| Story | 중 | 4막은 있으나 “왜 이해가 안 되는지”를 설계하지 않음 |
| Script | 중하 | 과잉 일반화, 결과 나열, 전문문체 |
| Narration | 중하 | 문법은 자연스러워도 듣기에는 무거움 |
| Self-check | 중하 | semantic entailment/quantifier/implication 오류를 놓침 |
| Visual Planning | 중상 | Stage/Mutation은 강함 |
| Renderer | 중 | Planner의 상태변화를 충분히 실행하지 못함 |
| Analytics | 중 | 전체 평균은 있으나 Beat-level retention 없음 |

---

# 7. 근본 원인

현재 pipeline은 대체로:

```text
원문
↓
Fact Sheet
↓
Reasoning / Story / Script를 빠르게 생성
↓
Visual Directive
```

이다.

앞으로는 다음이 필요하다.

```text
원문
↓
Evidence
↓
★ Explanation Reasoning
↓
Narrative Plan
↓
Spoken Narration
↓
Visual Plan
↓
Renderer
```

즉 **“무엇이 사실인가?”와 “어떻게 설명해야 이해되는가?” 사이에 독립적인 사고 단계가 필요하다.**

---

# 8. Architecture 권고

완전한 논문 엔진 / 리포트 엔진 두 벌을 만드는 것은 권장하지 않는다.

1차 권고:

# Shared Explanation Core + Domain Reasoning Adapters

```text
                  Shared Core
                     │
        ┌────────────┴────────────┐
        │                         │
Paper Reasoning Adapter     Report Reasoning Adapter
        │                         │
        └────────────┬────────────┘
                     ↓
              Explanation IR
                     ↓
             Narrative Composer
                     ↓
             Narration Composer
                     ↓
              Visual Planner
                     ↓
              Renderer / QA
```

분리할 것은:

```text
Source interpretation
Domain reasoning grammar
Domain risk / uncertainty policy
Domain terminology
```

공유할 것은:

```text
Explanation IR
Narrative structure engine
Spoken narration engine
Visual Beat/Stage contract
Renderer
QA orchestration
Analytics
```

이 구조라면 Renderer, Narration, Analytics, QA를 한 번 개선하면 두 도메인이 같이 개선된다.

도메인별 Adapter만 따로 발전시키면 된다.

---

# 9. 완전 분리 엔진으로 전환할 조건

아래 조건이 실제 실측으로 확인될 때만 분리를 확대한다.

```text
1. 두 Adapter가 Explanation IR 필드의 30~40% 이상을 서로 사용하지 않는다.
2. Narrative Composer에서 domain if/else가 계속 증가한다.
3. 동일 QA 규칙이 두 도메인에서 반복적으로 상반된 판정을 낸다.
4. 동일 Story Grammar로 품질을 유지하기 어렵다는 Gold Set 평가가 반복된다.
```

그 전에는 두 엔진을 복제하지 않는다.

---

# 10. 감사 최종 판정

현재 VIDEO-ARTICLE의 최우선 과제는:

> **Renderer만 개선하는 것이 아니라, Explanation Intelligence를 먼저 강화하고 그 결과를 기존 Visual Sequence/Renderer가 소비하도록 재배선하는 것**

이다.

우선순위:

```text
1. Source Adequacy Gate
2. Explanation Reasoning
3. Spoken Narrative
4. Cross-stage Fidelity QA
5. Existing Visual Planner 연결 정비
6. Visual Explainer Renderer
7. Beat-level Analytics
```

Renderer는 반드시 필요하지만 **P1이 아니라 후속 핵심 단계**다.