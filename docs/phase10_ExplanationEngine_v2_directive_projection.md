# Phase 10 — Explanation Directive Projection

## 결과

Phase 9 `visual-plan-v1`을 현재 Production 지시서의 핵심 shape인
`version_type + header + cuts + visual_sequences`로 변환하는 Shadow projector를 추가했다.
기존 Production 생성·승인·저장·렌더 경로에는 연결하지 않았다.

추적 사슬은 각 컷의 `explanation_trace`에 다음 형태로 남는다.

```text
VB02 → SN02 → XR01 → paper:C01 → claims:C01 → VS02 → VM02 → SHOT02
```

## 동일 입력 전후 핵심 명세

아래 두 JSON은 저장소의 동일한 결정론적 Paper 검증 입력
`paper-complexity-1`에서 생성한 비교 핵심 필드다. 읽기 편하도록 prompt와
`visual_sequences`의 world/entity/stage 상세는 생략했으며, 테스트는 생략 없는 canonical
객체 전체를 검증한다. 라이브 Production DB 재생성 결과는 아니다.

### 전 — 기존 평면형 지시서

```json
{
  "domain": "paper",
  "content_id": "paper-complexity-1",
  "version_type": "image_sequence",
  "header": {
    "total_estimated_sec": 6
  },
  "cuts": [
    {
      "cut_no": 1,
      "narration_ko": "압력이 높아지면 왜 구조가 변하는가?",
      "estimated_sec": 3,
      "visual_prompt": "related illustrative image",
      "claim_ids": [],
      "reasoning_id": "",
      "source_facts": []
    },
    {
      "cut_no": 2,
      "narration_ko": "압력이 높아지면 구조가 변한다.",
      "estimated_sec": 3,
      "visual_prompt": "related illustrative image",
      "claim_ids": [],
      "reasoning_id": "",
      "source_facts": []
    }
  ]
}
```

### 후 — V2 Phase 10 추적형 지시서

```json
{
  "contract_version": "explanation-directive-shadow-v1",
  "projection_status": "READY",
  "domain": "paper",
  "content_id": "paper-complexity-1",
  "version_type": "image_sequence",
  "header": {
    "aspect_ratio": "9:16",
    "core_question": "압력이 높아지면 왜 구조가 변하는가?",
    "total_estimated_sec": 6,
    "source_constraints": {
      "source_depth": "full_body",
      "source_mode": "FULL_EXPLAINER",
      "max_duration_sec": 80,
      "max_content_mode": "extended",
      "mechanism_visual_allowed": true,
      "mechanism_reasoning_ids": ["XR01"]
    },
    "explanation_trace_summary": {
      "visual_beat_count": 2,
      "fully_traced_cut_count": 2,
      "sequence_count": 2
    },
    "visual_sequences": "아래 top-level visual_sequences와 동일한 consumer 정본"
  },
  "cuts": [
    {
      "cut_no": 1,
      "narration_ko": "압력이 높아지면 왜 구조가 변하는가?",
      "estimated_sec": 3,
      "visual_mode": "QUESTION",
      "visual_beat_id": "VB01",
      "narration_id": "SN01",
      "stage_id": "VS01",
      "mutation_ids": ["VM01"],
      "shot_id": "SHOT01",
      "reasoning_id": "",
      "claim_ids": [],
      "source_facts": [],
      "explanation_trace": {
        "visual_beat_id": "VB01",
        "narration_refs": ["SN01"],
        "reasoning_ids": [],
        "evidence_ids": [],
        "raw_refs": [],
        "stage_id": "VS01",
        "mutation_ids": ["VM01"],
        "shot_id": "SHOT01",
        "causal_levels": [],
        "uncertainties": [],
        "attributions": [],
        "concept_ids": [],
        "knowledge_refs": []
      }
    },
    {
      "cut_no": 2,
      "narration_ko": "압력이 높아지면 구조가 변한다.",
      "estimated_sec": 3,
      "visual_mode": "MECHANISM",
      "visual_beat_id": "VB02",
      "narration_id": "SN02",
      "stage_id": "VS02",
      "mutation_ids": ["VM02"],
      "shot_id": "SHOT02",
      "reasoning_id": "XR01",
      "claim_ids": ["C01"],
      "source_facts": ["claims:C01"],
      "causal_levels": ["causal"],
      "explanation_trace": {
        "visual_beat_id": "VB02",
        "narration_refs": ["SN02"],
        "reasoning_ids": ["XR01"],
        "evidence_ids": ["paper:C01"],
        "raw_refs": ["claims:C01"],
        "stage_id": "VS02",
        "mutation_ids": ["VM02"],
        "shot_id": "SHOT02",
        "causal_levels": ["causal"],
        "uncertainties": [],
        "attributions": [],
        "concept_ids": [],
        "knowledge_refs": []
      }
    }
  ],
  "visual_sequences": "2개 sequence의 world/entity/stage/mutation 상세 생략",
  "qa": {
    "errors": [],
    "metrics": {
      "cut_count": 2,
      "fully_traced_cut_count": 2,
      "reasoning_linked_cut_count": 1,
      "evidence_linked_cut_count": 1
    }
  }
}
```

## 비교 판정

```json
{
  "comparison_basis": "deterministic_repository_fixture",
  "same_input_comparison": true,
  "legacy_spec": {
    "cut_count": 2,
    "duration_sec": 6,
    "reasoning_linked_cut_count": 0,
    "evidence_linked_cut_count": 0,
    "fully_traced_cut_count": 0
  },
  "v2_spec": {
    "cut_count": 2,
    "duration_sec": 6,
    "reasoning_linked_cut_count": 1,
    "evidence_linked_cut_count": 1,
    "fully_traced_cut_count": 2
  },
  "axes": {
    "trace_chain": "COMPLETE_V2",
    "semantic_calibration": "PRESERVED_V2",
    "production_wiring": "SHADOW_ONLY"
  },
  "final_directive_visual_quality": "not_measured",
  "rendered_video_quality": "not_measured"
}
```

## Paper/Report 공통 안전장치

- `BLOCKED_GATE`는 지시서 생성 거절
- 다른 Beat의 narration을 빌려 쓰는 교차 연결 거절
- 존재하지 않는 reasoning/evidence/stage/shot ID 거절
- `UNSUPPORTED`, `STALE`, `NOT_CHECKED` 근거의 renderable cut 승격 거절
- Report의 broker attribution과 `broker_projection`을 컷과 trace에 모두 보존
- Visual Plan의 의미 보정값을 원본 narration과 대조해 인과 강화·귀속 제거 거절
- 모든 narration beat의 1:1 소비를 강제해 한정/반례 beat 삭제 거절
- factual beat의 provenance 제거와 허위 entity ref 거절
- Phase 1 source constraint와 IR mechanism 범위를 재계산해 shallow-source 확장 거절
- 기존 renderer가 읽는 `header.visual_sequences`를 정본으로 제공
- 비교기는 원본 narration과 canonical V2 전체를 다시 검증하며 ID만 같은 다른 입력을 거절
- 저장 결과가 canonical rebuild와 다르면 `directive_not_canonical`

## 미적용·미검증

- 기존 Production directive 생성/승인/DB 저장/렌더 경로에는 미적용이다.
- 라이브 Supabase 원본 한 편 재생성은 미실행이다.
- 이미지·영상 생성 및 렌더 품질은 미검증이다.
- 따라서 이번 비교가 증명하는 것은 구조적 추적성과 의미 보존이며, 최종 화면 미학은 아니다.
