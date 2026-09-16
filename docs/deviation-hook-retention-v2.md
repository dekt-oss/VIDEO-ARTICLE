# 수정지시서 v2 적용 기록 — 훅·리텐션 + 선별 루브릭 + 렌더 QA

> 근거 문서: 사용자 제공 "수정 지시서 — 대본→지시서 파이프라인 훅·리텐션 개정 (v2)".
> CLAUDE.md 작업 규칙 6에 따른 이탈/변경 기록. 사용자 승인 범위: **전체 적용(①②③)**, 새 PR 분리.

## 무엇을 바꿨나 (3개 축)

### ① 지시서 훅·리텐션 개정 (§4·§5) — 파이프라인 1순위 병목
- **프롬프트**(`engine/directive.py` `DIRECTIVE_SYSTEM_BASE`): P1 증거 선공개 훅(예고형 문구 전면
  금지) / P2 앵글 9종 중 1개 / P3 훅↔본문 정합 자기검증 + 근거강도 게이트 / P5 CTA 5택1(강제 아님) +
  루프 / 리텐션 골격(LS v2 DNA)을 하드 룰로 주입.
- **스키마 신규 필드**(header, jsonb 라 마이그레이션 불필요): `hook_type`(H1~H4), `hook_reframe_angle`
  (9종), `hook_promise_check`{pass,promise,payoff_cut_no,reason}, `science_reliability`{claim_type,
  evidence_strength,generalization_risk,required_caveat}, `cta_type`(5택1), `loop_match`, `series_id`.
- **정규화**: `_sanitize_enum`/`normalize_hook_promise_check`/`normalize_science_reliability` 로 enum
  강제·형식 보장(자유 텍스트 금지). `bold_hook_gate_violation`: 대담 훅(H1/H2)인데 evidence_strength≠high
  또는 generalization_risk≠low 이면 승인 화면 경고.
- **동기화 3곳**(이중관리): `engine/directive.py` + `supabase/functions/generate-directive/index.ts`
  (프롬프트·normalize 미러) + `web/lib/types.ts`(Cut/DirectiveHeader 타입).
- **승인 UI**(`web/components/DirectiveClient.tsx`): 훅/앵글/CTA/루프 표시 + 정합 실패·근거강도 게이트
  위반 경고 배너(기존 "근거 없는 컷" 배너 옆).

### ② 선별 루브릭 5축 0~2점 (§6) — **additive**(기존 파괴 없음)
- 기존 4축(0~10, 정렬용 fun/importance/golden)과 buzz 는 **그대로 유지**한다. 그 위에 "제작 여부"를
  가르는 5축·각 0~2점(총 10) 게이트를 **추가**했다: novelty/audience_value/hook_fit/explain_60s/
  visualizable, 각 한 문장 근거.
- **결정(중요)**: 명세는 "5축 0~2로 교체"를 말하지만, 실제 코드는 이미 4축 0~10(100점표 아님)이고 그
  스케일에 **채점된 논문 1,300+편**이 쌓여 있으며 daily_batch 정렬·measure 합격기준까지 엮여 있다.
  통째 교체는 기존 데이터 비교 불가 + 명세 자신의 "한 번에 한 변수" 원칙과 충돌한다. 그래서 정렬 체계는
  건드리지 않고 **제작 게이트를 얹는** 방식으로 적용했다(더 안전·가역적).
- `engine/scoring.py`: SCORING_SYSTEM 에 5축 블록 추가, `parse_production`/`production_gate`
  (make≥8 / redesign 6~7 / backlog 4~5 / hold≤3). `scores.production` jsonb(`0024`, nullable 하위호환).
- 대시보드 `/scored`: 게이트 배지(제작우선/재설계/후순위/보류 + 총점).

### ③ 렌더 QA 게이트 (§7) — 신규
- **결정**: "번인 자막 프레임 OCR 자동판정"은 과투자 + 불안정. 우리 파이프라인은 `assemble.py` 에서
  ASS 를 **결정적으로 번인**하므로 자막 "존재"는 구조적으로 보장된다(명세 §1이 정정한 그 오해). 따라서
  자동 판정 가능한 하드 신호만 게이트로: 끝 검은프레임 · >250ms 무음 · 오디오 클리핑 · 길이 · 오디오
  트랙 유무. 자막 가독성/싱크는 **승인 UI 의 렌더 프리뷰(video 태그)**로 육안 확인.
- `engine/render_qa.py`: `evaluate_qa`(순수, ffprobe 신호 → passed/hard_fail/warnings) +
  `probe_signals`(ffprobe/ffmpeg silencedetect·blackdetect·astats) + `run_qa`. `render.py` 가 렌더
  직후 호출, `render_jobs.qa` jsonb(`0025`)에 저장. `web/components/RenderList.tsx` 배지.

## 부수 항목 (§1·§8)
- **§8 series_id**: 지시서 header `series_id` 필드로 태깅 지원(위 ①). 플레이리스트 자동정리·댓글 질문
  자동생성은 이번 범위 밖(경량 운영 습관 — 수동으로 시작).
- **§1 engaged_views / view_choice_rate — 의도적 보류(Phase B)**: 지금 성과 수집(youtube_analytics)은
  **실측으로 정상 작동 확인**된 상태다. `engagedViews` 는 YouTube Analytics API 에서 채널/쿼리에 따라
  가용성이 달라 검증 없이 지표 목록에 넣으면 수집 전체가 400 으로 깨질 위험이 있다. 명세 §9 자신이
  "측정은 지금 최소, 볼륨 임계(월 5,000뷰/30편) 도달 후 확장"이라 했으므로, 이 지표는 **Phase B 항목으로
  문서화하고 보류**한다(작동하는 수집을 깨지 않는 것을 우선).

## 범위 경계
- **논문 파이프라인만** 적용(사용자 명세가 "논문 대중화 숏폼" 대상). 금융 리포트 공장의 병렬 지시서
  (`engine/report_directive.py`)는 이번 범위에서 제외 — 필요 시 같은 패턴으로 후속 적용.

## 검증
- 순수 로직: `tests/test_hook_retention_v2.py`(훅 필드·게이트·제작 루브릭·렌더 QA) + 기존 전체 —
  **pytest 226건 통과**(기존 동작 무회귀 확인).
- 대시보드: `npm run build` + `npm run lint` 통과.
- 라이브 DB: `scores.production`·`render_jobs.qa` 컬럼을 라이브 Supabase 에 적용(additive nullable).
- **미검증(런타임)**: LLM 이 실제로 새 필드를 규격대로 채우는지, 렌더 QA 가 실제 mp4 에서 신호를 뽑는지는
  실제 지시서 생성·렌더 1회로 확인해야 완결(프롬프트/ffprobe 경로는 코드 검증까지만).
