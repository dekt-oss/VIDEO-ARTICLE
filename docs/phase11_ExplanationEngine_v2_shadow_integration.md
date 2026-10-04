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
```

`--with-model`은 해당 Fact Sheet의 trace-limited prompt를 저장소에 설정된 대본/검증 모델로
전송한다. 결과는 기본적으로 `artifacts/explanation-v2-phase11/`에만 저장되며 이 디렉터리는
gitignore 대상이다. GitHub/Vercel 아티팩트 업로드는 없다.

## 안전 경계

- exact content ID가 없으면 실행 거절
- 최신 자료 자동 탐색 없음
- 조회는 draft 1건과 해당 콘텐츠의 최신 directive 1건만 사용
- DB insert/update/upsert/RPC 없음
- 기본 모드에서 외부 모델 호출 없음
- `BLOCKED_*`, `REJECTED`, `ACTION_REQUIRED` 결과는 Phase 10 지시서로 승격하지 않음
- 실제 Production과 Shadow가 동일 Fact Sheet revision인지 증명할 필드가 없어 항상 `미검증`
- 최종 영상 품질과 시청자 이해도는 항상 `미검증`

## 출력 판독법

Markdown은 다음 순서로 보여 준다.

1. 현재 Production 저장 대본
2. 현재 Production 지시서 컷
3. 생성된 V2 Shadow 대본(안전 게이트 차단 시에도 표시)
4. V2 Shadow 지시서 또는 차단 사유
5. Phase 2~10 단계별 상태

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

## Rollback

`engine/explanation_shadow_pipeline.py`, `scripts/compare_explanation_v2.py`, 두 테스트 파일,
이 문서와 `.gitignore`의 `artifacts/` 항목을 제거하면 된다. 기존 Production 경로에는 변경이
없으므로 DB/배포 rollback은 필요 없다.
