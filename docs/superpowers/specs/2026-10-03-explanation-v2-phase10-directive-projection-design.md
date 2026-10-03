# Explanation Engine v2 Phase 10 Directive Projection Design

## Goal

Phase 9의 검증된 `visual-plan-v1`과 Explanation IR을 현재 Production 지시서의 핵심 shape인
`version_type + header + cuts + visual_sequences`로 결정론적으로 투영한다. 같은 검증 입력으로
기존 평면형 명세와 V2 추적형 명세를 생성해 사용자가 실제 JSON을 나란히 비교할 수 있게 한다.

## Scope

- `READY` Visual Plan만 지시서로 투영한다.
- `BLOCKED_GATE`는 fail-closed로 거절한다.
- narration, reasoning, evidence, raw source, stage, mutation, shot ID를 컷까지 보존한다.
- Paper와 Report 모두 같은 projector를 쓰되 Report의 broker attribution과 projection qualifier를 보존한다.
- 현재 Production 생성·승인·DB 저장·렌더 경로에는 연결하지 않는다.
- 모델 호출, DB 접근, 에셋 생성, 렌더는 하지 않는다.

## Contract

출력은 `explanation-directive-shadow-v1`이다.

- `projection_status`: `READY`
- `domain`, `content_id`, `version_type`
- `header`: core question, duration, source constraints, sequence summary, trace metrics
- `cuts`: 현재 Production 소비 필드와 `explanation_trace`
- `visual_sequences`: 현재 `visual_sequence.py`가 이해하는 world/entity/stage/mutation shape
- `qa`: 오류·경고·추적률

각 컷의 `explanation_trace`는 다음을 모두 가진다.

`visual_beat_id → narration_refs → reasoning_ids → evidence_ids/raw_refs → stage_id → mutation_ids → shot_id`

## Projection Rules

1. Visual Beat 하나를 Production cut 하나로 투영한다.
2. narration 문장은 `narration_id`로 조회하며 찾지 못하면 거절한다.
3. `estimated_sec`는 narration 글자 수 기반 결정론적 값(3~8초)으로 계산한다.
4. `visual_mode`는 기존 beat/role로 닫힌 매핑을 사용한다.
5. prompt는 source-backed narration과 이미 검증된 stage operation만 서술하며 새 도메인 사실을 추가하지 않는다.
6. `raw_ref`에서 기존 Fact Sheet key를 복원해 `source_facts`와 `claim_ids`에 싣는다.
7. Phase 9 sequence/stage를 현재 visual sequence shape로 확장하되 개체는 기존 `entity_ref`에서만 만든다.
8. 모든 ID와 attribution/causal level/uncertainty는 그대로 복사한다.

## Validation

- contract/status/content identity와 IR reasoning ID 검사
- narration coverage 및 중복 ID 검사
- 모든 sequence stage ID가 실제 Visual Beat stage에 존재하는지 검사
- cut trace가 원본 beat/shot/mutation과 정확히 같은지 검사
- 모든 READY cut이 reasoning/evidence/concept/knowledge 중 하나 이상으로 추적되는지 검사
- canonical rebuild와 결과가 다르면 거절

## Same-input Comparison

테스트의 canonical Paper/Report 입력으로 기존 평면형 명세와 Phase 10 명세를 함께 만든다.
비교기는 trace, attribution, causal calibration, stage/shot 연결을 축별로 판정한다. 이 비교는
실제 Production DB 재생성이 아니라 저장소 내 결정론적 검증 입력에 대한 비교이며 문서에 명시한다.

## Done Criteria

- Paper/Report READY 투영 성공
- BLOCKED_GATE fail-closed
- forged/dangling trace 거절
- deterministic canonical validation
- 기존 Phase 2~9 회귀 통과
- 전체 Python/Web/typecheck/lint/build 통과
- 기존 Production path import/wiring 없음

