# VIDEO-ARTICLE Explanation Engine v2
## 단계별 구현 작업지시서
**기준일:** 2026-10-01  
**대상 저장소:** `dekt-oss/VIDEO-ARTICLE`  
**Source of Truth:** 최신 GitHub main + Production DB + 실제 Render  
**자동 Merge:** 금지  
**목표:** “논문/리포트를 요약해 읽는 영상”에서 “복잡한 내용을 실제로 이해시키는 Visual Explainer”로 전환

---

# 0. 작업 원칙

이 작업은 새로운 영상 엔진을 옆에 하나 더 만드는 프로젝트가 아니다.

현재 저장소에 이미 존재하는 다음 구조를 최대한 재사용한다.

```text
Fact Sheet
Claim Ledger
Financial Reasoning
Story Plan
Narrative Arc
Beat
Resolved Visual Plan
Visual Sequence
Stage
Mutation
Camera
Photo Contract
Render QA
Analytics
```

새로 필요한 것은 이 구조 앞·사이의 약한 계약을 강화하는 것이다.

최종 목표 Architecture:

```text
SOURCE
↓
SOURCE ADEQUACY GATE
↓
EVIDENCE PACK
↓
DOMAIN REASONING ADAPTER
↓
EXPLANATION IR
↓
NARRATIVE PLAN
↓
SPOKEN NARRATION
↓
EXISTING VISUAL PLANNER
↓
VISUAL EXPLAINER RENDERER
↓
QA
↓
ANALYTICS FEEDBACK
```

---

# 1. Architecture 결정

## 1.1 기본 구조

**공통 Explanation Core + 도메인별 Reasoning Adapter**를 기본으로 한다.

```text
Paper Source
↓
Paper Reasoning Adapter
                  \
                   → Explanation IR
                  /
Report Source
↓
Report Reasoning Adapter
```

그 이후는 공통:

```text
Explanation IR
↓
Narrative Composer
↓
Narration Composer
↓
Visual Planner
↓
Renderer
↓
QA
↓
Analytics
```

---

## 1.2 왜 완전 분리하지 않는가

논문과 증권 리포트는 사고 방식이 다르다.

그러나 다음은 공통이다.

- 시청자 질문
- 설명 순서
- prerequisite
- causal chain
- claim/evidence 연결
- 불확실성
- 정보 삭제
- spoken narration
- visual beat
- transition
- rendering
- retention 분석

따라서 두 엔진 전체를 복제하면:

```text
Narration 개선
→ 논문 엔진 수정
→ 리포트 엔진도 별도 수정

Renderer 개선
→ 논문 엔진 수정
→ 리포트 엔진도 별도 수정
```

이 반복된다.

이 문제를 막기 위해 **Reasoning Adapter까지만 분리**한다.

---

# 2. Phase 0 — Baseline Quality Audit

## 목적

구현 전에 현재 품질을 숫자와 사례로 고정한다.

이번 3편 감사 결과를 Seed Set으로 사용한다.

추가로 최근 제작물에서:

```text
논문 3~5편
리포트 3~5편
```

을 더 샘플링한다.

---

## 평가 축

각 영상마다 다음을 독립 평가한다.

```text
SOURCE ADEQUACY
FACT FIDELITY
REASONING QUALITY
EXPLANATION QUALITY
SCRIPT COHERENCE
NARRATION NATURALNESS
VISUAL EXPLANATORY POWER
VISUAL-NARRATION ALIGNMENT
PACING
UNCERTAINTY CALIBRATION
```

---

## 반드시 기록할 것

```text
source_depth
source_chars
primary claim
core question
script length
spoken number count
beat count
cut count
video duration
visual treatment distribution
generated-video seconds
render cost
average view percentage
average view duration
```

---

## Failure Origin

각 결함은 반드시 최초 발생 지점을 기록한다.

예:

```text
SOURCE
FACT
REASONING
SCRIPT
NARRATION
VISUAL_PLAN
RENDER
```

하류에서 발견됐더라도 최초 원인을 상류로 돌린다.

---

## 완료 조건

다음 질문에 답할 수 있어야 한다.

> 현재 최종 품질을 가장 많이 떨어뜨리는 상위 3개 failure class가 무엇인가?

이번 초기 감사 기준 예상:

```text
1. Explanation Reasoning 부재/약화
2. Script semantic fidelity + spoken quality
3. Visual Plan → actual Renderer gap
```

단, 확대 감사 결과로 최종 확정한다.

---

# 3. Phase 1 — Source Adequacy Gate

## 문제

현재 `source_depth`를 저장하지만 Source 깊이가 영상 깊이를 충분히 제어하지 않는다.

실측 사례:

```text
partial_text 1,072자
→ 50초 / 12컷 full explainer
```

---

## 목표

Source의 확보 수준에 따라 허용되는 설명 깊이를 코드가 결정한다.

---

## 권장 Source Modes

```text
FULL_EXPLAINER
SOURCE_EXPLAINER
BRIEF_EXPLAINER
SUMMARY_ONLY
REJECT_OR_FETCH
```

예시:

### 논문

```text
full_body + mechanism claims
→ FULL_EXPLAINER

full_body but mechanism 없음
→ SOURCE_EXPLAINER

abstract_only
→ BRIEF_EXPLAINER

title/metadata 중심
→ REJECT_OR_FETCH
```

### 리포트

```text
full_text
→ FULL_EXPLAINER

partial_text but thesis/driver chain 명확
→ BRIEF_EXPLAINER

짧은 메시지/요약만 있음
→ SUMMARY_ONLY 또는 원문 fetch
```

---

## 강제 규칙

Source가 얕으면:

- mechanism을 새로 만들어내지 않는다.
- 영상 길이를 억지로 늘리지 않는다.
- scene/cut 수를 제한한다.
- 결과 소개형으로 낮춘다.
- 필요하면 full source 확보를 우선한다.

---

## 완료 조건

Source depth가 낮은 사례에서:

```text
50초 12컷 deep explainer
```

가 자동 생성되지 않아야 한다.

---

# 4. Phase 2 — Common Evidence Pack 정리

현재 Fact Sheet / Claim Ledger / Financial Reasoning의 좋은 부분은 유지한다.

새 엔진을 만들지 않는다.

대신 Explanation Engine이 소비할 공통 Evidence Pack을 만든다.

---

## 최소 계약

```yaml
content_id:
domain:
source_depth:
source_mode:

claims:
  - claim_id:
    text:
    claim_type:
    causal_strength:
    evidence_grade:
    source_refs:
    uncertainty:

numbers:
risks:
limitations:
background_context:
```

---

## Claim Type 공통화

예:

```text
measured_fact
reported_fact
author_interpretation
company_guidance
analyst_estimate
forecast
hypothesis
scenario
background_context
```

도메인별 세부값이 필요하면 Adapter 내부에서 추가한다.

---

# 5. Phase 3 — Explanation Reasoning Engine

이번 프로젝트의 가장 중요한 단계다.

**대본을 만들기 전에 독립 실행한다.**

---

# 5.1 공통 Explanation IR

Paper/Report Adapter는 모두 동일한 IR을 출력한다.

권장 형태:

```yaml
explanation_version:

core_question:
viewer_reason_to_care:

starting_assumption:
surprising_conflict:

prerequisite_concepts:
  - concept:
    simple_explanation:
    evidence_type:
    source_refs:

explanation_steps:
  - step_id:
    question:
    answer:
    relation_to_previous:
    claim_ids:
    source_refs:
    uncertainty:
    must_visualize:

payoff:

limitations:
excluded_details:

recommended_story_pattern:
target_complexity:
```

중요:

> 이 IR에는 최종 나레이션 문장을 쓰지 않는다.

여기는 **생각하는 단계**다.

---

# 5.2 Paper Reasoning Adapter

논문은 다음 질문에 답해야 한다.

```text
연구가 해결하려는 질문은 무엇인가?
기존에는 무엇을 알고 있었는가?
이번 연구에서 무엇이 달라졌는가?
시청자가 이해하려면 어떤 개념을 먼저 알아야 하는가?
실험/관찰은 무엇을 비교했는가?
핵심 결과는 무엇인가?
왜 이런 결과가 나왔는가?
논문이 실제 mechanism을 제공하는가?
어디까지가 관찰이고 어디부터가 저자 해석인가?
어디까지 일반화 가능한가?
```

---

## Paper Story Grammar 후보

### WHY

```text
현상
→ 왜?
→ 기존 설명
→ 새 결과
→ mechanism
→ 의미
```

### EXPERIMENT

```text
질문
→ 어떻게 확인?
→ 결과
→ 왜?
→ 한계
```

### TRADE-OFF

```text
장점
→ 그런데 비용
→ 왜 둘이 같이 생김?
→ 진화/기능적 의미
```

Heel-strike는 `TRADE-OFF`가 적합하다.

---

# 5.3 Report Reasoning Adapter

리포트는 다음 질문에 답해야 한다.

```text
애널리스트의 핵심 thesis는 무엇인가?
시장이 흔히 보는 반대 시각은 무엇인가?
실적/산업 변화의 driver는 무엇인가?
driver → 매출 → 이익 연결은 무엇인가?
valuation은 어떻게 연결되는가?
무엇이 사실이고 무엇이 전망인가?
어떤 가정이 깨지면 thesis가 무너지는가?
```

---

## Report Story Grammar 후보

### DRIVER CHAIN

```text
산업 변화
→ 공급/수요
→ 가격
→ 매출/이익
```

### BOTTLENECK

```text
수요 증가
→ 병목
→ 공급 제약
→ 가격/수주
```

### VALUATION

```text
실적 가정
→ BPS/EPS/FCF
→ multiple
→ 목표가
```

### CONTRARIAN

```text
시장 우려
→ 리포트 반론
→ 근거
→ breaks_if
```

삼성전자 사례는:

```text
왜 메모리 사이클이 더 길다고 보는가?
```

와

```text
왜 목표가가 63만원인가?
```

중 하나를 우선 질문으로 고르고,
다른 하나는 payoff 또는 후속 영상으로 보내야 한다.

---

# 6. Phase 4 — Prerequisite Knowledge Resolver

좋은 설명은 단순 Source 요약만으로 만들어지지 않는다.

시청자가 모를 개념을 먼저 풀어야 한다.

예:

```text
heel-strike
center of pressure
loading rate
PBR
HBM
FCF
```

---

## 원칙

Prerequisite는 다음 순서로 해결한다.

```text
1. Primary Source 안의 설명
2. 검증된 프로젝트 glossary
3. 신뢰 가능한 외부 reference
4. 없으면 설명 범위를 축소
```

LLM 일반상식을 사실 근거처럼 사용하지 않는다.

---

## 공통 Glossary 후보

### Science

```text
correlation
causation
sample size
confidence interval
metabolic cost
loading rate
```

### Finance

```text
PBR
PER
FCF
ASP
operating leverage
order backlog
HBM
DRAM
```

---

# 7. Phase 5 — Narrative Planner

Explanation IR이 완성된 뒤에만 Story를 만든다.

현재 4막 구조는 유지할 수 있다.

하지만 4막은 **형식**이고 Explanation IR은 **내용 논리**다.

---

## 기본 구조

```text
HOOK
↓
SETUP / PREREQUISITE
↓
CONFLICT
↓
EXPLANATION
↓
EVIDENCE
↓
PAYOFF
↓
BOUNDARY / RISK
```

모든 항목을 의무화하지 않는다.

짧은 주제는 4~5 Beat로 끝내도 된다.

---

## 금지

```text
연구 소개
→ 연구 방법
→ 숫자
→ 숫자
→ 한계
```

형식의 논문 요약 나열.

```text
목표가
→ 실적
→ 밸류
→ 위험
```

만 나열하는 리포트 압축.

---

# 8. Phase 6 — Spoken Narration Engine

Narrative Plan과 Spoken Narration을 분리한다.

---

## 1차 Draft

Explanation IR + Narrative Plan만 보고 작성한다.

가능하면 원문 전문을 다시 자유롭게 읽게 하지 않는다.

이유:

> 이미 선택·검증된 논리를 벗어나 새 이야기를 즉석에서 만들지 못하게 하기 위함.

---

## 2차 Spoken Polish

별도 pass로 수행한다.

검사:

```text
한 호흡이 너무 긴가?
명사형 표현이 많은가?
논문/리포트 문체가 남았는가?
앞 문장과 연결되는가?
같은 질문을 두 번 반복하는가?
전문용어를 설명 전에 쓰는가?
숫자를 너무 많이 읽는가?
TTS로 들었을 때 문장이 자연스러운가?
```

---

## 목표 문체

나쁨:

> 발뒤꿈치 보행은 발 아래 압력 중심의 전방 이동을 증가시켜 효과적인 사지 길이를 늘림으로써 보행의 대사 비용을 줄일 수 있습니다.

개선 방향:

> 뒤꿈치가 먼저 닿으면 접점이 발 뒤에서 앞으로 이동합니다.  
> 덕분에 다리가 조금 더 긴 지렛대처럼 움직이죠.  
> 같은 거리를 걸을 때 필요한 에너지가 줄어듭니다.

---

# 9. Phase 7 — Semantic Fidelity QA

현재 Self-check의 가장 중요한 개선 영역이다.

---

## 9.1 Clause-level Entailment

문장 전체가 “비슷한 Fact”를 갖고 있다고 통과시키지 않는다.

문장을 의미 단위로 쪼갠다.

예:

```text
인간은 / 모든 유인원 중 / 유일하게 / heel-strike한다
```

각 요소가 Source에서 지지되는지 본다.

---

## 9.2 Scope Intensifier Guard

다음 표현은 근거가 명시적으로 있어야 한다.

```text
모든
유일
항상
절대
오직
최초
전부
완전히
반드시
```

원문에 없으면 자동 강등 또는 차단한다.

Heel-strike 사례가 이 Gate를 통과하면 실패다.

---

## 9.3 Hook Grounding

Hook을 무조건 Self-check 면제하지 않는다.

구분:

### Rhetorical Hook

```text
“지금은 1997년일까요, 1999년일까요?”
```

→ evidence 없이 허용 가능

### Factual Hook

```text
“AI 거품 붕괴 공포가 시장에 번지고 있습니다.”
```

→ Evidence 필수

---

## 9.4 Independent Critic

작성 모델의 자기평가만 사용하지 않는다.

최소 한 번은 독립 Critic이:

```text
Source/Evidence Pack
vs
Explanation IR
vs
Final Narration
```

을 대조한다.

특히:

```text
contradiction
scope expansion
causal upgrade
missing qualifier
unsupported background
```

를 본다.

---

# 10. Phase 8 — Content Complexity Gate

현재 warning만 내고 Production이 계속 진행되는 문제를 고친다.

예:

```text
series_split
too_many_spoken_numbers
```

가 발생했으면 실제 행동이 따라야 한다.

---

## 행동 규칙

```text
series_split
→ 한 편 발행 금지 또는 명시적 override

too_many_spoken_numbers
→ Narration regenerate

source_too_shallow
→ length downgrade 또는 source fetch

mechanism_unavailable
→ mechanism scene 생성 금지
```

“경고했으니 됐다”를 금지한다.

---

# 11. Phase 9 — Existing Visual Planner 재배선

새 Visual Beat Schema를 만들지 않는다.

현재의:

```text
Beat
Resolved Visual Plan
Visual Sequence
Stage
Mutation
Camera
```

를 정본으로 사용한다.

정의:

> **Explanation Step 하나가 하나 이상의 기존 Stage에 매핑된다.**

---

## 반드시 연결할 필드

```text
Explanation step_id
↓
claim_ids
↓
reasoning_id
↓
stage_id
↓
mutation
```

상류 논리가 하류에서 사라지지 않게 한다.

---

## 회귀 테스트

삼성전자 사례에서:

```text
financial_reasoning R01/R02/R03
```

가 존재하는데 Directive의:

```text
claim_refs=[]
beat_declared=false
```

로 사라지는 현상을 재현 테스트로 고정한다.

---

# 12. Phase 10 — Transition Edge Planner

Transition은 랜덤 효과가 아니라 Explanation 관계에서 결정한다.

---

## 예

```text
question → answer
= hard cut / reveal

whole → detail
= push-in

external → internal
= cutaway

cause → effect
= follow / state change

process A → process B
= object/path continuation

phenomenon → data
= graphic match

micro → whole result
= pull-out
```

기존 Stage/Camera enum을 먼저 활용한다.

새 transition enum은 renderer가 실제 지원할 때만 추가한다.

---

# 13. Phase 11 — Visual Explainer Renderer

이 단계에서 Renderer 개선을 시작한다.

앞선 Explanation 단계가 안정되기 전까지 Renderer만 단독 확장하지 않는다.

---

## 목표

```text
정지 이미지 + 줌
```

이 아니라:

```text
State Change
Moving Information
```

을 구현한다.

---

## MVP Primitive

우선순위:

```text
MOVE
SCALE
REVEAL
MASK
PATH
ARROW
FOLLOW_PATH
PARTICLE_FLOW
COUNT_UP
LAYER_SPLIT
```

---

## 기존 Operation 매핑

```text
FLOW
→ path + particle_flow

TRANSFER
→ follow_path

ACCUMULATE
→ object/count accumulation

CUTAWAY
→ mask/layer reveal

ZOOM_INTO
→ scale + push

SPLIT
→ layer split

TRANSFORM
→ state replacement/morph
```

---

## 생성영상 정책

Generated Video는 기본값이 아니다.

우선순위:

```text
1. deterministic code motion
2. existing/generated still + compositing
3. generated video
```

Veo는:

```text
Hook
Hero Beat
Code Motion으로 현저히 표현하기 어려운 장면
```

에 우선 사용한다.

---

# 14. Phase 12 — Domain Visual Semantics

## Science

구분:

```text
Observed
Measured
Modelled
Proposed mechanism
Hypothesis
Metaphor
```

## Finance

구분:

```text
Actual
Company guidance
Broker estimate
Forecast
Scenario
Risk
```

화면에서도 다르게 보여준다.

예:

```text
Actual
────────▶

Forecast
- - - - ▶

Scenario
········▶
```

`LITERAL_OBSERVATION`과 `SCHEMATIC_PRINCIPLE / METAPHOR`를 엄격히 구분한다.

---

# 15. Phase 13 — QA 통합

최종 Publish Gate를 다음 순서로 구성한다.

```text
Source QA
↓
Reasoning QA
↓
Narration QA
↓
Visual Semantic QA
↓
Render QA
```

---

## 핵심 질문

### Source

> 이 깊이의 Source로 이 정도 설명을 해도 되는가?

### Reasoning

> 질문에 답하는 논리가 실제 Evidence로 연결되는가?

### Narration

> 사실이 맞고, 사람이 들어도 쉬운가?

### Visual

> 화면이 같은 내용을 설명하는가?

### Render

> 선언된 변화가 실제 픽셀 변화로 나타났는가?

---

# 16. Phase 14 — Analytics / A-B

현재 영상 전체 평균 지표는 이미 수집한다.

다음 단계:

```text
Beat timing
+
Audience retention timeline
```

을 연결한다.

---

## 실험 순서

### Experiment A — Explanation

```text
기존 Renderer
+ 기존 Script

VS

기존 Renderer
+ Explanation Engine v2 Script
```

---

### Experiment B — Visual Explainer

```text
v2 Script
+ 기존 Visual

VS

v2 Script
+ Code Motion Visual
```

---

### Experiment C — Hero Video

```text
Visual Explainer

VS

Visual Explainer + Veo Hook/Hero
```

---

# 17. Model Strategy

모델을 바꾸는 것만으로 해결하려 하지 않는다.

그러나 Reasoning/Script는 영상당 호출 수가 적고 품질 영향이 매우 크므로:

```text
Extraction / routine validation
→ cost-efficient model

Explanation Reasoning
→ quality-tier model 후보 A/B

Spoken Narration
→ language quality가 좋은 모델 후보 A/B
```

로 분리할 수 있다.

현재 기본 모델을 즉시 교체하지 말고 Gold Set으로 비교한다.

평가 축:

```text
factuality
explanation coherence
spoken naturalness
compression
latency
cost
```

---

# 18. 구현 PR 권장 순서

## PR 1 — Audit + Gold Set

- 감사 도구
- 단계별 품질 평가 구조
- 최근 샘플 Gold Set 고정
- 코드 동작 변경 없음

## PR 2 — Source Adequacy Gate

- source_mode
- 길이/복잡도 제한
- shallow source downgrade

## PR 3 — Explanation IR + Adapter Interface

- 공통 schema
- adapter registry
- contract tests
- 기존 출력 유지

## PR 4 — Paper Reasoning Adapter

- prerequisite
- mechanism availability
- observation/interpretation 구분

## PR 5 — Report Reasoning Adapter

- driver chain
- valuation
- forecast/risk semantics
- attribution

## PR 6 — Narrative + Spoken Narration v2

- IR → story
- spoken polish
- TTS QA

## PR 7 — Semantic Fidelity Gate

- clause entailment
- scope intensifier
- hook grounding
- independent critic

## PR 8 — Existing Visual Planner Integration

- reasoning_id / claim_id / stage 연결
- fallback 제거
- regression tests

## PR 9 — Transition Edge

- relation-based transition resolver

## PR 10 — Visual Explainer Renderer MVP

- deterministic primitives
- operation mapping
- render QA

## PR 11 — Domain Visual Semantics

- Science uncertainty
- Finance forecast/estimate

## PR 12 — Beat Analytics

- Beat timeline 저장
- retention 연계
- A/B metadata

---

# 19. Feature Flag / Rollout

기존 Production을 한 번에 교체하지 않는다.

권장:

```text
EXPLANATION_ENGINE_V2=false
```

기본으로 시작.

---

## Shadow Mode

동일 Source로:

```text
Current Script
+
V2 Explanation Script
```

두 개를 생성하되 V2는 발행하지 않는다.

사람이 비교한다.

---

## Limited Release

Gold Set과 Shadow 검증 후:

```text
10~20% 콘텐츠
```

에만 v2 사용.

그 이후 Analytics 확인 후 확대한다.

---

# 20. 반드시 하지 않는 것

```text
❌ 기존 Story/Visual 시스템 전체 재작성
❌ Paper/Report 전체 Pipeline 복제
❌ Renderer부터 대규모 재개발
❌ Source가 얕은데 LLM으로 내용 채우기
❌ Self-check 하나만 믿기
❌ Prompt만 길게 만드는 방식
❌ Field를 추가하고 consumer 연결을 확인하지 않는 방식
❌ CI 통과를 콘텐츠 품질 검증으로 간주
```

---

# 21. Adversarial Self-review

각 Phase 완료 전에 다음을 묻는다.

```text
이 필드는 실제 consumer가 읽는가?
이 Gate는 경고만 하고 실제 행동이 없는가?
모델이 라벨만 바꾸면 통과할 수 있는가?
Source보다 강한 주장이 생길 수 있는가?
Paper/Report 중 한쪽만 수정돼 drift가 생기지 않는가?
같은 질문을 두 모듈이 각자 판단하고 있지 않은가?
```

---

# 22. 최종 완료 기준

다음이 충족돼야 Explanation Engine v2 완료로 본다.

```text
[ ] Source depth가 콘텐츠 깊이를 실제로 제한한다.
[ ] Script 전에 독립 Explanation IR이 존재한다.
[ ] Paper/Report Adapter가 동일 IR contract를 통과한다.
[ ] Heel-strike와 같은 scope hallucination이 차단된다.
[ ] factual hook과 rhetorical hook이 구분된다.
[ ] series_split/too_many_numbers가 실제 행동으로 이어진다.
[ ] Spoken Narration이 별도 polish를 거친다.
[ ] Reasoning ID가 Visual Stage까지 유지된다.
[ ] Visual representation mode가 실제 의미와 맞는다.
[ ] Stage mutation 일부가 deterministic motion으로 실제 렌더된다.
[ ] 기존 영상과 v2 영상을 같은 Source로 A/B 생성할 수 있다.
[ ] Beat timing이 Analytics와 연결된다.
[ ] 실제 Render를 사람이 확인했다.
```

---

# 23. 최상위 품질 기준

VIDEO-ARTICLE이 목표로 해야 할 것은:

> “논문을 1분으로 요약했습니다.”

도 아니고,

> “AI로 멋진 3D 영상을 만들었습니다.”

도 아니다.

최종 목표는:

> **“내용은 전문적인데, 영상을 따라가다 보니 원리까지 이해됐다.”**

이다.

이를 위해 우선순위는 다음으로 고정한다.

```text
SOURCE QUALITY
↓
EXPLANATION QUALITY
↓
NARRATION QUALITY
↓
VISUAL PLANNING
↓
RENDER QUALITY
```

Renderer는 중요하지만,
좋은 설명을 시각화하는 마지막 증폭기이지
약한 설명을 구제하는 장치가 아니다.