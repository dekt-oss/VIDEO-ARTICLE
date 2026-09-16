# WORK ORDER — Equity Report Visual Explanation Engine v3

## 목표

`dekt-oss/VIDEO-ARTICLE`의 기존 금융 리포트 파이프라인을 기반으로 **Equity Report Visual Explanation Engine v3**를 구현한다.

핵심 목표:

> 증권사 리포트의 투자 논리를 숫자 카드와 개별 이미지의 나열로 보여주는 것이 아니라, “왜 이 증권사가 이런 실적·목표가를 전망하는가”를 사업 구조와 인과 흐름이 작동하는 Visual Sequence로 설명한다.

단, 모든 금융 정보를 3D화하지 않는다.

**원리·사업흐름은 3D Sequence, 정확한 수치는 Code Viz, 실제 기업/제품은 Reality Media로 routing한다.**

자동 merge하지 않는다.

---

# 1. 가장 중요한 아키텍처 원칙

## 금융 파이프라인을 새로 만들지 않는다

현재 repository에는 이미 다음 계층이 있다.

- `report_source.py`
- `report_factsheet.py`
- `report_evidence.py`
- `report_reasoning.py`
- `report_scriptgen.py`
- `report_directive.py`
- `report_render.py`
- `report_attribution.py`
- `report_compliance.py`

관련 workflow와 finance UI도 이미 있다.

따라서 다음 같은 신규 병렬 파이프라인을 만드는 것은 금지한다.

```text
finance_v3_source.py
finance_v3_factsheet.py
finance_v3_directive.py
...
```

현재 `report_*`를 유지한다.

Visual layer만 Paper v3와 공유한다.

---

# 2. 작업 전 Source of Truth 복구

반드시 최신 branch/HEAD와 repository 지침을 다시 확인한다.

특히 읽을 것:

- `CLAUDE.md`
- 관련 AGENTS/README/ADR
- `docs/강화지시서_금융리포트시각화_C안_v1.1.md`
- `docs/영상지시서_금융숏츠_01_LSELECTRIC_v2.md`
- `docs/deviation-fin-visual-v1.md`
- `docs/deviation-report-factory.md`
- `engine/report_reasoning.py`
- `engine/report_factsheet.py`
- `engine/report_evidence.py`
- `engine/report_directive.py`
- `engine/report_render.py`
- `engine/report_compliance.py`
- 기존 chart/manim/visual modules
- report 관련 migrations
- report tests/workflows

문서와 코드가 다르면 **코드와 실제 execution path를 우선 확인하고 divergence를 기록한다.**

---

# 3. Shared Visual Engine 의존성

Paper v3에서 Shared Visual Explanation Engine이 이미 구현돼 있다면 반드시 재사용한다.

공통:

- VisualSequence
- VisualStage
- VisualWorld
- PersistentEntity
- StateTransition
- VisualOperation
- CameraOperation
- VisualRouter
- SequenceContract
- SequenceMetrics

금융용으로 위 구조를 복사해서 별도 버전을 만들지 않는다.

Paper와 Report가 다른 것은 **Domain Reasoning/Planner**다.

---

# 4. 기존 `report_reasoning.py`를 Equity Planner의 핵심 입력으로 사용

현재 `report_reasoning.py`는 이미 다음 reasoning unit을 만든다.

- DRIVER_CHAIN
- EARNINGS_BRIDGE
- VALUATION_LOGIC
- CATALYST_PATH
- RISK_PATH
- SCENARIO
- COMPARISON

그리고 각 unit을 여러 `steps`로 분해한다.

예:

`전력망 투자`
→ `변압기 수주 증가`
→ `수주잔고 증가`
→ `매출 인식`
→ `고마진 제품 비중 상승`
→ `영업이익 개선`

이 구조를 새로 다시 추출하지 않는다.

**reasoning_units.steps를 Visual Sequence로 compile하는 Equity Visual Planner를 만든다.**

---

# 5. Equity Semantic Operation

금융 Planner는 raw reasoning step을 우선 금융 의미 operation으로 해석할 수 있다.

예:

- DEMAND_INCREASE
- ORDER
- BACKLOG
- PRODUCE
- SHIP
- RECOGNIZE_REVENUE
- EXPAND_CAPACITY
- PRICE_CHANGE
- COST_INCREASE
- PASS_THROUGH_COST
- MIX_SHIFT
- ACCUMULATE_PROFIT
- REVALUE
- RISK_BREAK

그 후 공통 visual operation으로 번역한다.

예:

```text
ORDER
→ TRANSFER + ACCUMULATE

BACKLOG
→ QUEUE/ACCUMULATE

EXPAND_CAPACITY
→ EXPLODE + ASSEMBLE + SCALE

RECOGNIZE_REVENUE
→ TRANSFER + TRANSFORM

PASS_THROUGH_COST
→ FLOW + SPLIT

REVALUE
→ CODE_VIZ
```

금융 semantic operation 자체와 실제 render operation을 혼동하지 않는다.

---

# 6. Visual Router — 금융 전용 규칙

## 6.1 3D Mechanism Sequence

다음은 우선 3D/technical sequence 후보:

- 산업 구조
- supply chain
- 데이터센터 전력 흐름
- 공장 생산 과정
- 수주 → backlog → 생산 → 납품
- CAPA 증설
- 원가 전가
- 제품 믹스 변화
- 공급 부족/bottleneck
- 수요→설비투자→기업 수혜

---

## 6.2 Code Data Viz

다음은 3D 은유보다 code viz를 우선:

- 매출액
- 영업이익
- 영업이익률
- QoQ/YoY
- 목표주가
- PER/PBR
- valuation
- historical series
- analyst estimate
- actual vs estimate
- 경쟁사 정량 비교

예:

`+130%`

를 13개의 물체로 보여주지 않는다.

정확한 수치는 기존 `fact_ref` 기반 chart/overlay 체계를 유지한다.

---

## 6.3 Reality

다음은 실제 media가 설명력이 높을 수 있다.

- 공장
- 제품
- 변압기
- 데이터센터
- 기업 본사
- 산업 현장

AI reconstruction을 실제 회사의 특정 공장/설비처럼 오인시키지 않는다.

필요하면 내부적으로:

- REALITY_SOURCE
- REALITY_RECONSTRUCTION

을 구분한다.

현재 enum과 충돌한다면 기존 contract를 먼저 확인하고 가장 작은 확장으로 처리한다.

---

# 7. 금융 Claim Type / Attribution 유지

기존 Fact Sheet/Evidence에서 이미 표현 가능한 타입을 우선 사용한다.

필요한 의미 구분은 최소 다음 수준이어야 한다.

- actual
- company guidance
- analyst estimate
- analyst interpretation/opinion
- derived value
- valuation assumption
- scenario

단, 기존 config/schema에 이미 다른 명칭이 있다면 새 enum을 중복해서 만들지 않는다.

가장 중요한 규칙:

> 증권사가 전망한 것을 객관적 미래 사실처럼 화면에서 보여주지 않는다.

예:

나쁜 표현:

> “내년 매출이 20% 증가합니다.”

좋은 표현:

> “유안타증권은 수주 증가를 근거로 내년 매출 증가를 전망했습니다.”

Visual Sequence에서도 마찬가지다.

미래 예상 매출이 실제 확정된 물량처럼 보이지 않도록 provenance/forecast status를 보존한다.

---

# 8. LS ELECTRIC Golden Sample v3

현재 `영상지시서_금융숏츠_01_LSELECTRIC_v2.md`를 v3 golden sample로 사용한다.

v2의 좋은 점은 유지한다.

### S1 — 목표가 변화

`CODE_VIZ`

유지.

### S2 — 골드러시 → 데이터센터

Veo/Reality-transition.

유지 가능.

### 기존 S3 이후를 v3 핵심 실험 대상으로 확장

현재는 데이터센터 cutaway가 한 장의 의미 이미지다.

v3에서는 이를 하나의 persistent world로 만든다.

예:

## Sequence POWER_INFRA

### Stage 1

데이터센터 외관.

### Stage 2 — CUTAWAY

외피가 열리며 서버랙과 전력실 공개.

### Stage 3 — FLOW

전력이 변압기/배전반을 통해 서버로 흐름.

### Stage 4 — ISOLATE

핵심 전력 장비만 남김.

### Stage 5

해당 설비에 주문 block 유입.

### Stage 6 — ACCUMULATE

order가 backlog queue에 누적.

### Stage 7 — TRANSFER

backlog → factory/production.

### Stage 8

납품 → revenue bridge.

단, 각 단계는 실제 리포트 reasoning/evidence가 지지하는 범위에서만 만든다.

근거가 없는 생산기간/납품구조/공장 프로세스를 임의로 만들지 않는다.

---

# 9. Code Viz와 Sequence의 연결

중요한 것은:

`3D → 차트 → 완전히 새 세계 → 3D`

처럼 분절되지 않게 만드는 것이다.

가능하면:

3D business world에서 카메라가 빠지거나 결과를 freeze하고,

그 위에 정확한 code data visualization이 자연스럽게 연결되도록 한다.

예:

`backlog accumulates`
→ 화면 일부 freeze
→ `신규수주 1조원` fact_ref overlay
→ code chart
→ 다시 같은 business world로 return

이를 `RETURN_WORLD`로 표현할 수 있다.

---

# 10. Persistent Entity — 금융

금융 영상에서도 continuity 대상이 필요하다.

예:

- DATA_CENTER_A
- TRANSFORMER_A
- ORDER_BLOCK
- BACKLOG_QUEUE
- FACTORY_LINE
- PRODUCT_UNIT
- REVENUE_CONTAINER

“돈”을 모든 장면에 무조건 쓰지 않는다.

설명 대상에 가장 자연스러운 persistent entity를 선택한다.

예:

수주 설명에는 주문서/contract block이 더 좋을 수 있고,

전력에는 energy flow,

생산에는 product unit,

매출에는 code overlay가 더 정확할 수 있다.

---

# 11. Sequence Contract — 금융 추가 규칙

공통 Sequence Gate 외에 다음을 검사한다.

### EQ-V1 — Reasoning linkage

각 business mechanism sequence는 최소 하나의 `reasoning_id/step`을 참조한다.

### EQ-V2 — Attribution

analyst estimate/opinion을 시각화하는 sequence는 해당 attribution을 잃지 않는다.

### EQ-V3 — Forecast status

forecast를 actual처럼 표시하지 않는다.

### EQ-V4 — Number integrity

정확한 수치를 생성형 이미지의 개수/크기로 임의 근사하지 않는다.

### EQ-V5 — Business causal fidelity

`수주 증가 → 매출 증가`

사이에 원문이 말하지 않은 단계가 추가되면 안 된다.

### EQ-V6 — World progression

동일 데이터센터/공장/설비를 다시 보여줄 경우 명확한 progression 또는 return reason이 있어야 한다.

### EQ-V7 — Visual metaphor boundary

스노우볼·골드러시 등 은유는 factual claim과 분리한다.

은유가 회사의 실제 사업구조로 오해되지 않도록 한다.

---

# 12. 기존 금융 시각화 계약 보존

현재 금융 명세의 좋은 안전장치를 유지한다.

특히:

> 차트 숫자를 LLM이 다시 복사하지 않고 `fact_ref`로 Fact Sheet에서 가져오는 방식

은 유지한다.

Sequence 도입 때문에 이 정확성을 포기하면 안 된다.

따라서 최종 영상은 Hybrid가 기본이다.

```text
3D Mechanism Sequence
+
Code Chart
+
Fact Overlay
+
Reality Media
```

이다.

---

# 13. 비용 설계

기존 목표:

- 이미지 수 제한
- Veo clip 제한
- code chart 활용

은 유지하되 비용 KPI를 확장한다.

새 관점:

> 고유 이미지 몇 장을 썼는가

보다

> 몇 개의 새 world를 생성했는가

를 본다.

가능하면:

1 base world
+ multiple state mutation
+ I2V chain

으로 만든다.

단, continuity 생성이 매번 별도 고비용 provider 호출을 요구한다면 실제 비용 측정 후 판단한다.

추정으로 “더 싸다”고 단정하지 않는다.

---

# 14. 테스트

## Shared regression

Paper v3의 Sequence Core tests를 재사용한다.

## Report-specific

최소:

- reasoning step → visual sequence mapping
- dangling reasoning id
- unsupported financial operation
- forecast/actual distinction
- attribution preservation
- fact_ref preservation
- exact number → code viz routing
- mechanism → sequence routing
- return to same world
- meaningful recurrence
- static recurrence
- metaphor/evidence separation

기존 report tests 전부 통과해야 한다.

특히:

- report_evidence
- report_reasoning
- report_video
- report_scoring
- report_publish
- schema parity
- relevant workflow contracts

를 깨지 않는다.

---

# 15. Golden Validation — LS ELECTRIC

다음 3개를 비교 보고한다.

### A. 기존 LS v2 directive

현재 baseline.

### B. Equity v3 sequence plan

각 reasoning unit이 어떤 sequence와 stage로 변환됐는지.

### C. 실제 렌더

가능하면 1편 생성.

비교 항목:

- 서사 이해도
- business mechanism 이해도
- world continuity
- 같은 구성 반복
- 정확한 수치 전달
- visual/narration alignment
- world reset 수
- 생성 비용

---

# 16. 성공 기준

단순히 “3D 컷이 4개 생겼다”가 성공이 아니다.

LS sample에서 최소 다음이 관찰돼야 한다.

1. 데이터센터/전력 구조가 동일 world에서 2단계 이상 진행
2. 전력설비의 존재 이유가 화면만으로도 이해 가능
3. 수주→실적 논리가 적어도 하나의 연속 sequence로 표현
4. 정확한 숫자는 code viz 유지
5. 같은 설비가 재등장해도 progression이 있으면 허용
6. 동일 의미의 고정 화면 반복 감소
7. 리포트 attribution 유지
8. unsupported business mechanism 없음
9. 기존 report pipeline regression 없음

---

# 17. Schema / Migration 주의

Sequence metadata를 DB에 persist해야 한다면 migration history를 먼저 확인한다.

기존 JSONB 안에서 backward-compatible하게 확장할 수 있으면 불필요한 migration을 만들지 않는다.

persistent contract를 변경해야 한다면:

- migration
- rollback/compatibility
- old directives
- web consumer
- workflow
- API

까지 확인한다.

---

# 18. UI 범위

이번 작업의 주목적은 영상 엔진이다.

UI 전면개편은 하지 않는다.

다만 현재 directive review 화면에서 sequence 검수가 불가능하다면 최소한 다음 정도는 보여줄 수 있다.

- Sequence ID
- World
- Stage
- Operation
- continuity source
- state transition
- reasoning/claim ref

필요 최소 범위만 구현한다.

---

# 19. Procedural 3D

Blender Python 등의 procedural 3D는 이번 v3의 필수 완료조건이 아니다.

현재 generative image/video + code render로 먼저 검증한다.

단, 실제 테스트에서 다음 문제가 반복되면 별도 ADR을 만든다.

- 동일 object identity 유지 실패
- 정확한 geometry 유지 실패
- 특정 경로/개수 animation 실패
- I2V drift
- Stage 연결 실패

그때:

`Procedural geometry + Generative material/environment`

Hybrid를 Phase 2 후보로 제안한다.

---

# 20. 작업 순서

권장:

### Phase A

Shared Visual Sequence Core 확인/재사용

### Phase B

`report_reasoning` → Equity Visual Planner

### Phase C

Visual Router

### Phase D

report directive wiring

### Phase E

report renderer wiring

### Phase F

Sequence contract/QA

### Phase G

LS ELECTRIC golden sample

### Phase H

기존 report regression / runtime validation

---

# 21. Adversarial self-review

구현 완료 후 반드시 스스로 다음을 공격적으로 검토한다.

- 기존 `report_reasoning`을 두 번 계산하고 있지 않은가?
- 새로운 finance pipeline을 우회적으로 또 만들지 않았는가?
- 3D가 더 화려해졌지만 숫자 정확성이 떨어지지 않았는가?
- analyst forecast를 사실처럼 만들지 않았는가?
- fact_ref가 중간 단계에서 raw value로 복사되고 있지 않은가?
- 동일 데이터센터가 이유 없이 계속 나오지 않는가?
- world continuity라는 명목으로 같은 화면을 복붙하지 않는가?
- reasoning step과 화면 operation이 실제로 같은 의미인가?
- 리포트에 없는 공급망 단계가 추가되지 않았는가?
- 생성 이미지가 실제 LS 공장/제품처럼 오인될 여지는 없는가?
- schema field를 만들었지만 renderer가 무시하고 있지 않은가?

---

# 22. 완료 및 PR

다음 검증을 가능한 범위에서 모두 실행한다.

- unit tests
- report regression
- lint
- typecheck
- build
- CI
- actual directive
- actual render
- LS golden comparison

검증하지 못한 것은 반드시 `미검증`으로 표시한다.

PR 생성이나 CI 성공을 기능 검증으로 간주하지 않는다.

별도 branch에서 commit/push 후 Draft PR 생성.

자동 merge 금지.

PR 본문:

- Current state
- Target state
- Architecture
- Shared vs Equity-specific boundary
- Changed files
- Schema change
- Tests
- Runtime result
- LS v2 vs v3 comparison
- Cost comparison
- Known limitations
- Procedural 3D follow-up 여부

를 명확히 기록한다.