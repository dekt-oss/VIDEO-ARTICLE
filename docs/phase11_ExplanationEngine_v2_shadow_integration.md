# Phase 11 — Read-only Shadow Integration

## 결과

Phase 2~10을 저장된 Paper/Report Fact Sheet 한 건에 연결하는 read-only runner를 추가했다.
Production 대본·지시서를 함께 받아 로컬 Markdown/JSON 전후 비교 자료를 만들지만, DB 저장,
승인, 큐 적재, 렌더, 발행은 하지 않는다.

기본 실행은 Phase 5에서 멈춘다. Phase 6 Spoken Narration과 Phase 7 Semantic Fidelity는 외부
모델 호출이므로 `--with-model`을 명시해야만 실행한다.

## 실행

```powershell
python scripts/compare_explanation_v2.py paper <paper_uuid>
python scripts/compare_explanation_v2.py report <report_uuid>
```

기본 결과:

- Phase 2 Evidence Pack
- Phase 3 Explanation IR
- Phase 4 prerequisite resolution
- Phase 5 narrative plan
- 기존 Production 대본·지시서
- `MODEL_CALL_REQUIRED` 상태

실제 V2 대본·지시서까지 비교할 때만 다음을 사용한다.

```powershell
python scripts/compare_explanation_v2.py paper <paper_uuid> --with-model
# 선택: 비교할 Production 지시서 지정, Phase 4 선행 개념 명시 요청
python scripts/compare_explanation_v2.py paper <paper_uuid> --directive-id <directive_uuid> --concepts-file concepts.json
# 선택: Production 계획이 series_split 일 때 Phase 8 명시적 override(사유 필수, 결과에 기록)
python scripts/compare_explanation_v2.py paper <paper_uuid> --with-model --override-series-split "비교용: 첫 편만"
```

`<paper_uuid>` 는 자리 표시다. PowerShell 에서 `<` 를 그대로 치면 실행 전에 파서 오류가 난다 —
실제 UUID 로 바꿔 넣는다.

`--with-model`은 해당 Fact Sheet의 trace-limited prompt를 저장소에 설정된 대본/검증 모델로
전송한다. 결과는 기본적으로 `artifacts/explanation-v2-phase11/`에만 저장되며 이 디렉터리는
gitignore 대상이다. GitHub/Vercel 아티팩트 업로드는 없다.

## 안전 경계

- exact content ID가 없으면 실행 거절
- 최신 자료 자동 탐색 없음
- 조회는 draft 1건과 해당 콘텐츠의 최신 directive 1건만 사용
- Production 테이블 insert/update/upsert/RPC 없음 — **예외 하나:** `--with-model` 의 실제 모델 호출은
  `engine.llm` 이 비용 원장 `generation_attempts` 에 호출당 1행을 남긴다(아래 "리뷰 후속" 참고).
  CLI 가 성공한 기록 수를 세어 `database_writes` 로 출력하고 JSON `side_effects` 에 남긴다.
- 기본 모드에서 외부 모델 호출 없음(따라서 원장 기록도 0건)
- `BLOCKED_*`, `REJECTED`, `ACTION_REQUIRED` 결과는 Phase 10 지시서로 승격하지 않음
- 실제 Production과 Shadow가 동일 Fact Sheet revision인지 증명할 필드가 없어 항상 `미검증`
- 최종 영상 품질과 시청자 이해도는 항상 `미검증`

## 출력 판독법

Markdown은 다음 순서로 보여 준다.

1. 콘텐츠 정보 — domain, content ID, source depth/mode, 현재 Fact Sheet 스냅샷 sha256,
   revision 동일성(항상 미검증), 실행 시각·모델, run status, phase8 계획 출처, 선행 개념 요청 출처
2. 현재 Production 저장 대본
3. 현재 Production 지시서 — 지시서 id·version_type·status·생성 시각·선택 기준, 컷마다
   대사·연출(`staging_ko`)·시각 프롬프트·근거 참조
4. 생성된 V2 Shadow 대본 — 제목에 phase6 판정. 엔진이 거절한 대본이면 "거절한 대본" 경고를 단다
5. V2 추적 골격(간이 화면 계획 — 렌더용 아님) — 컷마다 대사·시각 모드·시각 상태·상태 변화·전환 관계·reasoning·evidence·raw ref
5-1. V2 지시서(기존 생성기로 만든 것, `--with-directive`) — 기존 Production 지시서와 **같은 생성기**
   (`directive.generate` / `report_directive.generate`)에 V2 대본을 넣어 만든 지시서. 승인 가능 여부·막힌 이유,
   컷마다 대사·연출·시각 프롬프트, 그리고 생성기가 지운 V2 추적 정보를 다시 붙인 출처(`v2_trace`).
   DB 지시서 표에 저장하지 않는다. 설계 근거: `docs/설계점검_ExplanationEngine_v2_2026-10-05.md` §3-A,
   구현 `engine/v2_directive_bridge.py`.
6. 차단·경고 — 실행 오류, phase5~10 의 qa 오류·경고 원문 코드, phase8 필요 조치, 미해결 선행 개념,
   한계(`non_claims`)
7. Phase 2~10 단계별 상태

`run_status` 는 `MODEL_CALL_REQUIRED` · `READY` · `BLOCKED` · `ERROR` 넷이다. `ERROR` 는 판정이 아니라
실행이 끝까지 못 간 것이다(예: 모델 타임아웃, 소스가 빈 Fact Sheet). 이때도 파일은 남고 CLI 는 종료코드 1.

JSON은 Evidence Pack, IR, prerequisite, narrative, narration, fidelity, complexity gate, visual
plan, directive를 모두 보존한다. 따라서 `reasoning_id → evidence_id → raw_ref → stage → mutation
→ shot` 손실 위치를 단계별로 조사할 수 있다.

## 검증 범위

- Paper READY 입력은 fully traced Phase 10 directive를 생성한다.
- Report READY 입력은 `broker_projection`과 증권사 attribution을 directive까지 보존한다.
- 근거가 없는 Paper는 `BLOCKED_NO_REASONING`이며 지시서를 만들지 않는다.
- 기본 모드는 외부 모델 호출 전에 멈춘다.
- directive 조회는 exact content ID에 제한된 SELECT-only query다.
- CLI는 저장소 루트에서 직접 실행할 수 있다.

## Production 미적용·미검증

- 기존 draft/directive 생성 워커에 연결하지 않았다.
- DB에 Shadow artifact를 저장하지 않는다.
- 라이브 Supabase ID를 사용한 실행은 환경 비밀값 부재로 미검증이다.
- `--with-model` 실제 호출과 유료 렌더는 미실행이다.
- 렌더 영상의 설명력·미학·시청자 이해도는 Phase 12 A/B 검증 대상이다.

## 리뷰 후속(2026-10-04, `claude/explanation-v2-phase11-review-fixes`)

독립 리뷰(Gate A)가 찾은 결함과 조치다.

| 등급 | 결함 | 조치 |
|---|---|---|
| P1 | `--with-model` 이 원장 `generation_attempts` 에 쓰는데 CLI 는 `database_writes: 0` 고정 출력 | 원장 기록은 **유지**한다(실제 지출이 원장에서 사라지면 2026-08-29 사고가 재발한다). 성공한 insert 만 세어 정직하게 출력 |
| P2 | Markdown 이 게이트 포장 오류만 보여 주고 진짜 원인(`association_upgraded` 등)을 숨김, 거절된 대본에 표시 없음 | phase5~10 qa 오류·경고 전부 출력, 거절 대본 경고 |
| P2 | phase8 계획을 소스 정책 상한으로 만들어 길이 초과 검사가 동어반복 | Production `video_flow.content_plan` 을 입력으로 사용. 없거나 형식이 틀리면 정책 상한으로 대신하고 `complexity_source_limit_not_evaluated` 로 공개 |
| P2 | phase4 선행 개념 요청이 항상 빈 목록인데 표시 없음 | `--concepts-file` 로 명시 요청만 받는다(지어내지 않음). 없으면 `prerequisite_explanation_not_evaluated` |
| P2 | 대본 모델 예외·빈 Fact Sheet 에서 예외로 종료, 산출물 없음 | 단계 예외를 `run_status=ERROR` + `error{phase,type,message}` 로 기록, 지시서는 항상 None |
| P2 | 같은 ID 재실행이 이전(유료) 결과를 덮어씀, 스냅샷·모델·시각 미기록 | 파일명 `{domain}-{id}-{dry|model}-{UTC시각}`, 충돌 시 접미사. sha256·모델·시각 기록 |
| P3 | 비교한 Production 지시서가 무엇인지 안 보임, V2 추적 ID 가 JSON 에만 | 지시서 식별 정보·선택 기준 표시, `--directive-id`(같은 콘텐츠 것만) 추가, V2 컷 추적 필드 표시 |
| P3 | CLI 가 content ID 를 검사하기 전에 DB 를 조회, 파일명에 원값 사용 | UUID 형식 검사를 DB 접근 **전**에 하고 정규형만 사용 |

### 2차 후속(같은 PR, 운영자 결정 2026-10-04)

| 결함 | 조치 |
|---|---|
| 출처 메타가 없는 레거시 Fact Sheet(실데이터: retinotopic `6b2d092a…`)가 유료 대본·검증 호출 **뒤** Phase 8 에서 `source_policy_mode_mismatch` 로 죽음 | Phase 2 는 원안(§8 "레거시는 모드를 추정하지 않는다")대로 `""` 를 유지한다. Phase 8 이 "모름 + 깊이 none" 만 가장 보수적인 `none` 정책으로 받아들인다 — 위조로 얻을 것이 없는 유일한 경우다. 다른 깊이에서 빈 모드는 계속 거절 |
| 같은 종류의 불일치를 돈을 쓰고 나서야 발견 | `content_complexity_gate.source_errors()` 로 소스 검사를 분리하고, Shadow 실행은 모델 호출 **전**에 같은 검사를 돌린다(`phase6_preflight`). 걸리면 호출 0회로 `ERROR` |
| Production 계획이 `series_split` 이면 V2 지시서가 항상 막힘(논문 후보 3건 전부) | 작업지시서 §10 이 허용하는 "명시적 override" 를 `--override-series-split "사유"` 로 추가. 기본 꺼짐, 빈 사유는 override 아님, 적용 사실은 결과·Markdown 에 남는다. **길이 초과(`DOWNGRADE_LENGTH`)는 override 로 못 푼다** |

남은 것(의도 확인 필요, 이번에 손대지 않음): Phase 2 에서 `quote_verified=false` 인 claim 이 `SUPPORTED`
로 남는 동작, 원안 Phase 4 의 "시청자가 모를 개념을 엔진이 찾는" 자동 탐지(현재는 명시 요청만 해결).

## 원 작업지시서와의 단계 번호 대응

`docs/작업지시서_ExplanationEngine_v2.md` 와 구현 문서의 번호는 Phase 10 부터 다르다. 구현은 Phase 9
문서(§"Phase 10은 … 기존 Production directive schema로 투영")에서 순서를 바꿨다.

| 원 작업지시서 | 구현 |
|---|---|
| Phase 9 Existing Visual Planner 재배선 | Phase 9 Visual Planner (전환 관계 `transition_relation` 포함 — 원안 Phase 10 일부) |
| Phase 10 Transition Edge Planner | Phase 9 에 흡수 + Phase 10 Directive Projection(원안에 없는 단계) |
| Phase 11 Visual Explainer Renderer | **미착수** |
| Phase 12 Domain Visual Semantics | **미착수** |
| Phase 13 QA 통합 | 미착수 |
| Phase 14 Analytics / A-B (실험 A: 기존 대본 vs V2 대본) | 이 문서의 Phase 11 Shadow 비교 도구 + 인수인계의 "Phase 12 실측 비교"가 **렌더 없는 실험 A** 에 해당 |

따라서 원안의 Renderer(Moving Information) 단계는 아직 시작되지 않았다. "Phase 12" 라는 이름이
문서마다 다른 것을 가리킬 수 있으니 원안 번호를 함께 적는다.

## Rollback

`engine/explanation_shadow_pipeline.py`, `scripts/compare_explanation_v2.py`, 두 테스트 파일,
이 문서와 `.gitignore`의 `artifacts/` 항목을 제거하면 된다. 기존 Production 경로에는 변경이
없으므로 DB/배포 rollback은 필요 없다.
