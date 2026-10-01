# Explanation Engine v2 — Phase 1 Source Adequacy Gate

**기준일:** 2026-10-01  
**브랜치:** `claude/explanation-v2-phase1-source-adequacy`  
**선행:** Phase 0 Gold Set / `docs/phase0_ExplanationEngine_v2.md`

## 1. 무엇이 이미 있었고 무엇이 없었나

기존 저장소에는 원문 확보와 깊이 판정이 이미 있었다.

- 논문: `full_body / partial_body / abstract_only`
- 리포트: `full_text / partial_text / summary_only`

따라서 이번 Phase 1은 **원문을 새로 수집하는 작업이 아니다.**

빠져 있던 것은 다음 계약이다.

> 확보한 Source 깊이가 실제 영상의 설명 깊이·길이·컷 수·논증 규모를 제한해야 한다.

종전에는 source_depth가 주로 시각의 `LITERAL_OBSERVATION` 허용 여부에 쓰였고,
영상 전체가 얼마나 깊게 설명해도 되는지는 충분히 제한하지 않았다.

---

## 2. Production에서 확인한 실패

2026-10-01 Production DB를 읽기 전용으로 감사했다.

최근 `partial_text` 리포트 초안은 대체로 이미 짧았다.

| source chars | draft 길이 | draft scenes |
|---:|---:|---:|
| 807 | 22초 | 6 |
| 1,072 | 24초 | 6 |
| 1,384 | 26초 | 7 |
| 1,853 | 23초 | 6 |
| 2,451 | 27초 | 7 |

그러나 Gold Set의 NH AI/Mid Cycle 사례는:

```text
partial_text 1,072자
→ 초안 약 24초 / 6 scene
→ 지시서 약 50초 / 12 cut
```

으로 다시 팽창했다.

즉 문제는 **대본 프롬프트 하나가 아니라 단계 사이 계약이 끊긴 것**이었다.

---

## 3. 실제 실행경로 감사에서 추가로 발견한 것

논문은 두 초안 경로가 남아 있다.

### 정상 통합 작업화면

버전을 선택해 초안을 요청하면 Next route가 GitHub `draft.yml` worker를 먼저 깨운다.

```text
draft_requests
→ engine.draft
→ paper_source.resolve
→ full-body 확보 시도
→ Fact Sheet
→ script
→ directive
```

이 경로는 원문 확보 체인을 탄다.

### Edge fallback

worker dispatch가 불가능하거나 버전 없이 초안만 요청하면
`supabase/functions/generate-draft`가 fallback으로 실행된다.

이 경로는 현재 논문 **초록만** 읽고 full-body 확보를 하지 않는다.

따라서 Phase 1에서 Edge fallback은 자신을:

```text
abstract_only
BRIEF_EXPLAINER
35초 이하
5컷 이하
```

로 명시하게 했다.

full source를 본 것처럼 행동하는 것보다 품질·사실성 측면에서 안전하다.

---

## 4. 공통 Source Adequacy Contract

정본: `engine/source_adequacy.py`

DB migration을 만들지 않고 기존 Fact Sheet JSON에 다음을 저장한다.

```json
{
  "source_adequacy": {
    "contract_version": "source-adequacy-v1",
    "domain": "paper|report",
    "source_depth": "...",
    "source_chars": 0,
    "source_mode": "...",
    "max_duration_sec": 0,
    "max_cuts": 0,
    "max_content_mode": "...",
    "max_reasoning_units": 0,
    "max_reasoning_steps": 0
  }
}
```

이 값은 Script에서 끝나지 않고 최종 Directive header에도 남는다.

---

## 5. 정책

### 논문

| Source depth | Mode | 길이 상한 | 컷 상한 | content mode 상한 |
|---|---|---:|---:|---|
| full_body | FULL_EXPLAINER | 80초 | 기존 규칙 | extended |
| partial_body | SOURCE_EXPLAINER | 50초 | 7 | standard |
| abstract_only | BRIEF_EXPLAINER | 35초 | 5 | flash |
| parse_failed / none | BRIEF_EXPLAINER | 35초 | 5 | flash |

### 리포트

| Source depth | Mode | 길이 상한 | 컷 상한 | Reasoning |
|---|---|---:|---:|---|
| full_text | FULL_EXPLAINER | 80초 | 기존 규칙 | 기존 최대 5 unit × 5 step |
| partial_text | BRIEF_EXPLAINER | 35초 | 7 | 최대 1 unit × 3 step |
| summary_only / none | SUMMARY_ONLY | 30초 | 6 | 독립 Reasoning 생성 안 함 |

**의도:** full source는 이번 Phase에서 기존 동작을 거의 건드리지 않는다.
실제 Production 사고가 확인된 shallow source만 우선 제한한다.

---

## 6. 단계별 소비자

### Paper

```text
paper_source.resolve
→ paper_evidence.source_provenance
→ source_adequacy.attach
→ scriptgen guidance + content mode ceiling
→ content_mode duration gate
→ directive guidance
→ directive final source gate
→ web approval gate
```

### Report

```text
report_source.resolve
→ report_factsheet source_depth/source_chars
→ source_adequacy.attach
→ report_reasoning unit/step ceiling
→ report_scriptgen guidance
→ report_directive source-sized target
→ directive final source gate
→ web approval gate
```

---

## 7. 최종 하드 게이트

최종 Directive에서 실제 초수와 컷 수를 다시 센다.

사유 코드:

- `source_depth_duration_exceeded:<actual>><max>`
- `source_depth_cut_count_exceeded:<actual>><max>`

예:

```text
partial_text / max 35초·7컷
실제 50초·12컷

→ source_depth_duration_exceeded:50>35
→ source_depth_cut_count_exceeded:12>7
→ approval_blocked=true
```

운영자가 지시서 컷을 편집한 뒤에도 `web/lib/approvalGate.ts`가 같은 값을 다시 계산한다.

---

## 8. 왜 Report Directive 프롬프트도 바꿨나

기존 report photo 지시서는 Source와 관계없이 `TARGET_TOTAL_SEC=60`을 기준으로 컷 수를 요구했다.

그러면 24초짜리 shallow draft를 지시서가 다시 60초 방향으로 팽창시킬 수 있다.

이제:

```text
target = min(TARGET_TOTAL_SEC, source_max_duration)
```

을 사용한다.

partial_text라면 35초를 목표로 하고 Source 컷 상한도 함께 적용한다.

---

## 9. Edge fallback 정책

`generate-draft/index.ts`는 full-body source acquisition을 하지 않는다.

Phase 1에서는 이를 숨기지 않는다.

- `source_provenance.source_depth = abstract_only`
- `provider = edge_abstract`
- `source_adequacy = BRIEF_EXPLAINER`
- content mode를 최대 flash로 강등
- 35초 초과 시 self-check block reason 기록

정상 worker 경로를 Edge 수준으로 낮춘 것이 아니다.
**Edge fallback만 자신이 실제로 본 근거 수준으로 제한한 것**이다.

---

## 10. 회귀 기준

`tests/test_source_adequacy.py`

고정 사례:

1. paper abstract-only → 35초/5컷/flash
2. paper partial-body → 50초/7컷/standard
3. report partial-text 1,072자 → 35초/7컷/1×3 reasoning
4. report summary-only → reasoning LLM 생략
5. NH형 24초/6컷 → 통과
6. NH형 50초/12컷 → 길이+컷 하드 차단
7. full report → 기존 envelope 유지
8. report directive prompt가 shallow source에서 60초가 아니라 35초를 사용
9. Edge fallback이 abstract-only contract를 명시

---

## 11. 이번 Phase에서 하지 않은 것

- Explanation IR 구현
- Paper/Report Reasoning Adapter v2
- Narration rewrite
- Visual Explainer Renderer
- 새로운 DB schema
- 기존 full-source 영상 길이 축소
- 기존 저장 Draft/Directive 백필

이들은 후속 Phase 범위다.

---

## 12. Rollback

Source Adequacy를 되돌려야 할 경우 변경 경계는 한 곳이다.

1. `engine/source_adequacy.py`의 정책을 완화하거나 호출을 제거
2. `source_adequacy.output_block_reasons` 소비 제거
3. web mirror 제거
4. Edge fallback의 source policy 제거

기존 source acquisition / Fact Sheet / visual source-depth 제한은 독립적으로 유지된다.

---

## 13. 완료 판정

다음이 모두 충족돼야 Phase 1 완료다.

- [x] 기존 source_depth 판정 경로 재확인
- [x] Production shallow-source 분포 실측
- [x] Source policy를 Fact Sheet에 지속
- [x] 논문 content mode 상한 연결
- [x] 리포트 reasoning 상한 연결
- [x] report directive의 고정 60초 팽창 제거
- [x] 최종 directive 길이/컷 하드 게이트
- [x] 운영 화면 편집 후 재검증 mirror
- [x] Edge fallback을 abstract-only로 명시
- [ ] 전체 Python tests
- [ ] Web typecheck/lint/tests
- [ ] GitHub Actions CI
- [ ] Vercel check
- [ ] 실제 신규 shallow-source 1편 Production 생성 검증

마지막 항목은 merge·배포 이후에만 검증 가능하므로 PR 단계에서는 **미검증**으로 남긴다.
