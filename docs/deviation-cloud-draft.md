# 범위 이탈 기록: 초안 클라우드 자동생성 (Edge Function)

> CLAUDE.md 작업 규칙 6 — "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고
> `docs/`를 갱신하며 근거를 남긴다." 에 따른 기록.

## 무엇이 바뀌었나
초안 생성(P1)을 대시보드 버튼 클릭만으로 **클라우드에서 자동 생성**되도록,
Python 엔진의 3단계 파이프라인(Fact Sheet → 대본/영상프롬프트 → 자기검증)을
**Supabase Edge Function** `supabase/functions/generate-draft/index.ts` 로 이식했다.

- 대시보드 "초안 생성 요청" → `/api/generate-draft` 가 `draft_requests` 큐에 상태 행을 적재하고
  Edge Function 을 호출 → 함수가 백그라운드로 생성(`EdgeRuntime.waitUntil`) 후 `drafts` 기록 →
  UI 는 `/api/draft-status` 를 폴링해 완료 시 자동 새로고침.

## 왜 (문제)
운영자가 버튼을 눌러도 아무 일이 없었다. 기존 설계상 버튼은 큐 행만 넣고, 실제 생성은
로컬에서 사람이 `python -m engine.draft`(1회 폴링 후 종료, 데몬 아님)를 직접 돌려야 했다.
자동 소비자가 없어 "클릭 → 무반응"이 된다.

## CLAUDE.md 범위와의 충돌
CLAUDE.md 범위는 "cron 무인 실행/클라우드 엔진 배포"를 P2 이후로 **명시적 제외**한다.
Edge Function 은 클라우드에서 도는 생성 엔진이므로 이 경계를 넘는다.

## 결정
사용자가 두 선택지(로컬 상시가동 워커 vs 클라우드 완전자동) 중 **클라우드 완전자동**을
명시적으로 선택했다. 따라서 초안 생성에 한해 Edge Function 이식을 진행했다.

## 트레이드오프 / 유지보수 주의
- **이중 관리:** 프롬프트·정규화·모델 ID 가 Python(`engine/factsheet.py`·`scriptgen.py`·
  `selfcheck.py`·`llm.py`)과 TS(Edge Function)에 **양쪽 존재**한다. 한쪽을 고치면 다른 쪽도
  동기화해야 한다. Edge Function 상단 주석에 이 사실을 명시했다.
- **로컬 워커 유지:** `python -m engine.draft` 는 그대로 둔다(로컬 생성·테스트·백업 경로).
  둘 다 동일한 `drafts` 스키마에 쓴다.
- **환각 방지 불변식 보존:** 대본 입력 = Fact Sheet 만, 씬별 `source_facts`, JSON only,
  파싱 실패 1회 재시도, 5xx/타임아웃 지수 백오프 — Python 규약을 그대로 재현했다.
- **범위 유지:** 수집·채점은 여전히 로컬. 이번 이탈은 초안 생성 트리거 경로에 한정된다.

## LLM 백엔드: Gemini 기본 (운영자 지정)
운영자 지시로 초안 생성의 기본 LLM 은 **Gemini**(무료 등급)다. Edge Function 은 engine/llm.py 와
동일하게 **모델 id 로 백엔드를 라우팅**한다 — 모델 id 가 `gemini*` 면 Gemini REST, 아니면 Anthropic.
기본 모델은 `gemini-2.5-flash`(env `MODEL_FACTSHEET/MODEL_SCRIPT/MODEL_SELFCHECK` 로 교체 가능,
품질이 필요한 대본 합성은 `gemini-2.5-pro` 권장). 엔진(수집/채점/번역)도 `MODEL_*=gemini-*` +
`GEMINI_API_KEY` 로 동일하게 Gemini 를 쓴다(이미 `.env.example` 에 문서화됨). 이 선택은 CLAUDE.md
의 Claude 모델 고정과 다르지만, 저장소가 원래 Gemini 대체 백엔드를 갖추고 있어 그 경로를 활성화한 것이다.

## P1 산출물 강화: 단계별 미디어 프롬프트 (2026-07)
초안 영상 산출을 실제 제작 워크플로에 맞춰 확장했다. 초안 하나는 이제 다음을 담는다:
- **video_flow**(신규 컬럼, 마이그레이션 0006): 전체 세부 영상 흐름(스토리보드) — logline·총길이·beats(비트별 요약+전환).
- **scenes[]**: 장면마다 `image_prompt`(텍스트→이미지 스틸) → `video_prompt`(이미지→영상 모션) → `narration_ko`.
  제작 순서 = 장면 이미지 먼저 → 그 이미지를 영상화 → 나레이션. (기존 단일 `visual_prompt`는 UI에서 `video_prompt` 폴백.)
- 프롬프트는 **도구 무관(범용)**, 실제 렌더링은 안 함(P2 제외 유지). 환각 방지 불변식 유지 — 이미지/영상 프롬프트는 Fact Sheet 사실의 시각화만, `no on-screen text`.
- **자기검증은 나레이션만** 대상(이미지/영상 프롬프트는 사실주장이 아니라 오탐 방지).
- 품질 위해 대본 단계는 `MODEL_SCRIPT=gemini-2.5-pro` 권장(env, 기본 flash). Python `engine/scriptgen.py`와 Edge Function 프롬프트를 동기화 유지.

## 운영 선행조건
1. `supabase functions deploy generate-draft`
2. `supabase secrets set GEMINI_API_KEY=…` (기본 Gemini 백엔드). SUPABASE_URL·SUPABASE_SERVICE_ROLE_KEY 는 자동 주입.
3. 로그인 이메일을 `app_allowed_emails` 에 등록(없으면 RLS 로 요청 insert·상태조회가 막힘):
   `insert into app_allowed_emails(email) values ('you@example.com');`
