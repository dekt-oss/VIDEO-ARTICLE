# Explanation Engine v2 — Phase 4 Prerequisite Knowledge Resolver

**기준일:** 2026-10-02

**기준 main:** `5bac6e330767a8f4ebda6bf5d5d9292c74830836`

**선행:** Phase 1 Source Adequacy, Phase 2 Evidence Pack, Phase 3 Explanation IR

## 1. 결론

Phase 4는 `explanation-ir-v1`이 요구하는 선행개념을 검증 가능한 지식으로 해결하는
shadow layer다. Production 대본·지시서·렌더 경로는 바꾸지 않는다.

```text
Evidence Pack ──────────────┐
                            ├─→ Prerequisite Resolver ─→ resolution-v1
Explanation IR ─────────────┤                              │
                            │                              ├─→ Phase 5 input
Reviewed Project Glossary ──┘                              └─→ shadow comparison
```

정본 작업지시서의 순서를 따른다. Phase 4는 선행개념 해결이고, Core Question/Causal
Story 구성은 Phase 5 Narrative Planner 책임이다.

## 2. 현재 문제와 목표 계약

기존 지시서는 Fact Sheet와 reasoning을 갖고도 시청자가 먼저 알아야 하는 개념을 별도로
관리하지 않았다. 그 결과 Personality GWAS 영상은 `1,260 variants`와 수치를 먼저 말하고,
GWAS의 연관과 다유전자 형질을 설명하지 않아 `association → determination` 오류가 발생했다.

Phase 4의 원칙은 다음과 같다.

1. Primary Source Evidence Pack 항목
2. 검토된 프로젝트 glossary
3. 둘 다 없으면 `NARROW_SCOPE`

LLM 일반상식이나 출처 없는 배경지식을 세 번째 근거처럼 사용하지 않는다.

## 3. Source-backed 판정의 추가 조건

Phase 2의 `verification_scope.semantic_entailment=false`를 그대로 존중한다. quote가 실제
원문에 존재한다는 사실만으로 선행개념 설명 전체가 입증됐다고 보지 않는다.

`RESOLVED_SOURCE`가 되려면 모두 만족해야 한다.

- Evidence Pack item이 `SUPPORTED`
- `verification_scope.semantic_entailment=true`
- item의 `domain_fields.prerequisite_concept_id`가 요청 concept ID와 일치
- 설명으로 사용할 text/display가 존재

현재 Production Fact Sheet에는 `prerequisite_concept_id`가 없으므로 대부분 source-backed로
승격되지 않는 것이 정상이다. 이 명시적 연결이 없으면 glossary로 넘어가고, glossary에도
없으면 범위를 줄인다.

## 4. Reviewed Glossary

첫 버전은 Gold Set의 실제 P0/P1 오류를 닫는 데 필요한 두 항목만 둔다.

| concept_id | 설명 목적 | 정본 |
|---|---|---|
| `gwas_association` | 통계적 연관을 직접 원인·결정으로 해석하지 않음 | NHGRI, Genome-Wide Association Studies |
| `polygenic_trait` | 하나의 유전자가 형질을 결정한다는 오해를 막음 | NHGRI, Polygenic Trait |

각 항목은 `publisher`, `title`, `url`, `locator`, `checked_at`, 쉬운 설명, semantic guardrail을
가진다. 출처가 비거나 URL이 HTTPS가 아니면 glossary 전체를 거부한다.

Glossary 후보를 한꺼번에 채우지 않았다. Heel-strike mechanics, retinotopic representation,
memory cycle, Mid Cycle, shipbuilding pipeline은 이번 PR에서 검증된 설명 출처를 확보하지
않았으므로 `UNRESOLVED`로 남긴다.

## 5. 출력 계약

```yaml
contract_version: prerequisite-resolution-v1
domain: paper|report
content_id: string
concepts:
  - concept_id: string
    label: string
    reason: string
    required: true|false
    simple_explanation: string
    status: RESOLVED_SOURCE|RESOLVED_GLOSSARY|UNRESOLVED
    evidence_ids: [string]
    knowledge_refs: [evidence:...|glossary:...]
    guardrails: [string]
    source: {}
unresolved_concepts: [string]
scope_action: KEEP|NARROW_SCOPE
warnings: [string]
```

중복 concept 요청은 첫 항목만 유지하고 warning을 남긴다. required concept 하나라도 해결되지
않으면 `scope_action=NARROW_SCOPE`다.

## 6. 기존 지시서와의 Shadow 비교

`explanation-shadow-comparison-v1`은 기존 Gold Set의 저장 지시서 finding과 새 구조를 같은
case ID로 비교한다. 측정 축은 기계적으로 확인 가능한 것만 사용한다.

| Case | 기존 대표 문제 | 현재 shadow 판정 |
|---|---|---|
| Heel strike | exclusivity scope 확대 | prerequisite 미해결 → 범위 축소 필요; 의미 개선은 미확인 |
| Retinotopic remapping | cross-sensory mechanism 발명 | prerequisite 미해결 → 범위 축소 필요; 의미 개선은 미확인 |
| Personality GWAS | association→determination, prerequisite 누락 | GWAS association + polygenic trait glossary 해결; semantic guardrail 존재 |
| Samsung report | reasoning/claim link 소실 | Explanation IR의 evidence/raw-ref trace는 개선; 최종 directive는 미생성 |
| NH Mid Cycle | partial source 과확장 | BRIEF IR 상한은 개선; prerequisite는 미해결 |
| Shipbuilding | opportunity→현재 replacement, claim link 소실 | IR trace는 개선; replacement 의미 오류 해결은 미확인 |

### 개선을 주장할 수 있는 범위

- Personality prerequisite coverage: `improved`
- Personality association calibration: `improved`
- Samsung/Shipbuilding IR evidence trace: `improved`
- NH source-depth IR safety: `improved`
- 미해결 concept은 지어내지 않고 `NARROW_SCOPE`

### 개선을 주장할 수 없는 범위

- spoken narration 자연스러움
- 실제 directive 품질
- render의 시각 설명력
- retention/시청지표

따라서 단일 “몇 % 개선” 점수는 만들지 않는다. 축별 `improved`, `unchanged`, `unresolved`,
`not_applicable`, `not_measured`만 기록한다.

## 7. 변경 경계

- `engine/explanation_glossary.json`: 검토된 glossary 정본
- `engine/prerequisite_resolver.py`: pure resolver/validator
- `engine/explanation_shadow_compare.py`: Gold Set 구조 비교
- `tests/test_prerequisite_resolver.py`: resolver, fail-closed, comparison 회귀
- `tests/fixtures/prerequisite_resolution_gold_cases.json`: 6개 case의 explicit concept 요청

기존 `scriptgen.py`, `report_scriptgen.py`, directive, render, web, Supabase, DB schema는 변경하지
않는다.

## 8. Rollback

신규 Phase 4 모듈·glossary·fixture·테스트·문서를 제거하면 된다. Production 경로와 저장 데이터는
변경하지 않았으므로 데이터 rollback은 없다.

## 9. 다음 단계

Phase 5 Narrative Planner는 Explanation IR과 이 resolution을 함께 읽는다. `UNRESOLVED` required
concept을 포함한 story를 확장하지 않고, core question 하나에 필요한 chain만 선택해야 한다.
기존 지시서와의 shadow 비교는 Phase 5에서도 동일 case ID와 축별 판정을 유지한다.
