# 구현 기록 — UI/UX 개선 지시서 Phase 0~2

- 날짜: 2026-07-27
- 지시서 원본: `docs/개선지시서_UIUX_v1.md` (GPT 작성, 브리핑 `docs/ui-ux-review-brief.md` 기반)
- 기준 커밋: `ba77971` → 구현 커밋 `ffd873b`(Phase 0) · `fb137fa`·`4f83b12`(Phase 1) · `a719fac`(Phase 2)
- 보안 항목 별도 문서: `docs/deviation-cost-surface-guard.md`

지시서를 코드와 대조한 결과 **진단 6건이 실제와 달랐고**, 구현 중 **계획과 다르게 판단한 것이 6건**
있다. 나중에 "왜 지시서대로 안 했나"를 다시 조사하지 않도록 근거를 남긴다.

## 1. 지시서 진단 정정 (코드 대조)

| 지시서 | 실제 | 조치 |
|---|---|---|
| SEC-01 인증 전면 복구가 P0 1순위 | `supabase/migrations/0007_public_access.sql:1` = `-- 로그인 제거(운영자 요청)`. **요청된 상태**이고 트레이드오프·롤백까지 문서화돼 있다 | 운영자에게 3택 제시 → "비용·발행 라우트만 차단" 선택. `docs/deviation-cost-surface-guard.md` |
| `alert` 는 CandidateList 1곳 | **3곳** (`CandidateList`, `ReportCandidateList`, `ReviewDateButton`) | 전부 토스트로 |
| `window.location.reload` 는 RenderList | **8곳** (RenderList 4 · TrashList · ReportRenderList 2 · SavedRenderList) | 전부 `router.refresh()` |
| 게이트 대상 라우트 6개 | **13개** — `directive-approve`·`render-add-language`·`directive-generate` 등도 같은 지출을 일으킨다 | 13개 적용. 6개만 막으면 게이트가 장식이 된다 |
| 렌더 실패에 "재시도 버튼으로 교체" | 실패 잡에는 **조치 버튼이 아예 없었다**(삭제만) | `↻ 재렌더` 신설 |
| ④·⑤ 결합은 양쪽 공장 | 논문만 결합. 리포트는 이미 ⑤·⑥ 이 별 화면 | 단계형으로 맞춰 비대칭 해소(리포트는 라우트 유지 + stepper 만) |

추가로 지시서가 예상하지 못한 위험 하나를 발견했다: `publish.yml` 이 **15분 크론**이라 anon 이
`upload_requests` 에 직접 INSERT 하면 운영자 조작 없이 유튜브로 자동 발행된다. 그래서 지시서가
"분리 가능"으로 둔 큐 테이블 잠금(0031)을 **필수**로 올렸다.

## 2. 계획과 다르게 판단한 것

### 2-1. `lib/factory/*Adapter.ts` 를 만들지 않았다 (T1-2)

`viewModel.workCounts()` 가 공장 무관 `WorkInput` 을 받고 각 페이지가 자기 타입을 인라인으로
줄여 넘긴다. 어댑터 파일 2개는 위임만 하는 껍데기가 됐을 것이다.

### 2-2. `WorkItem` 단일 객체 대신 두 축으로 나눴다 (T1-2)

지시서 §5-2 는 `WorkItem{stage,state,nextAction,blockingCount,warningCount}` 하나를 제안했다.
실제로는 홈은 **집계**(`WorkCounts`)만, ⑥ 화면은 **잡 단위**(`renderQueue`)만 필요해서 하나로
합치면 양쪽에서 안 쓰는 필드가 생긴다. 대신 `viewModel` 이 렌더 카운트를 셀 때
`renderQueue.classifyRenderJob` 을 재사용해 홈 숫자와 ⑥ 탭 숫자가 한 규칙에서 나온다.

### 2-3. DecisionRail(우측 결정 레일)을 넣지 않았다 (FLOW-01)

승인 버튼을 레일로 올리려면 `ReviewClient`·`DirectiveClient` 의 dirty/saving/승인 로직을 부모로
끌어내야 한다 — 2-C 리팩터 영역이고, 반쯤 끌어내면 저장 유실 위험이 생긴다. 대신 레일이 주려던
정보(근거 없는 씬·컷 수)를 stepper 아래 한 줄로 **상시** 노출하고, 승인 버튼은 각 단계의 기존
sticky 액션바에 뒀다. 승인 전 확인은 모달의 카운트 표시로 보강했다.

### 2-4. "결정 후 카드 위치 튐 방지"는 손대지 않았다 (HOME-01 규칙 7)

`CandidateList` 의 정렬은 점수 기준이고 결정 상태와 무관하다. 필터가 `전체`면 낙점해도 카드가
움직이지 않는다 — 고칠 결함이 없었다.

### 2-5. `/data` 허브 페이지를 만들지 않았다 (NAV-01 §4-2)

"데이터" 드롭다운이 이미 5개 화면을 한 그룹으로 묶고, 폭 모드는 화면별로 적용했다. 허브를 두면
링크를 한 번 더 거치는 화면이 생길 뿐이다. 상단 메뉴 3축이라는 목표는 달성했다.

### 2-6. 2-C 공통 컴포넌트 추출은 절반만 했다 (ARCH-01)

지시서 권장 순서 1~4(상태 배지 → 피드백 → async → 렌더 카드)에 해당하는 것은 추출했다:
`SaveStatus`, `UnsavedGuard`, `ErrorDisclosure`, `AsyncJobStatus`, `StageStepper`, `lib/apiError`,
`lib/work/*`(nextAction·renderQueue·steps·viewModel). 두 공장이 **판정 로직을 공유**한다.

하지 않은 것은 5~7(작업 큐·후보 카드·상세 작업공간의 JSX 통합) = `RenderList`↔`ReportRenderList`,
`CandidateList`↔`ReportCandidateList` 를 하나의 generic 컴포넌트로 합치는 일이다. 지시서 자신이
"한 번에 전체 generic rewrite 금지"(§13 ARCH-01, 금지사항 4)라고 못박았고, 두 공장의 카드 필드가
실제로 다르다(논문: 재미/중요/황금 · 리포트: 관심/스토리/안전 + 목표가·투자의견·ARIA 신호).
지금은 **로직 중복 0, JSX 중복 유지** 상태다. 남은 통합은 별도 PR 로.

### 2-7. 2-E 측정 이벤트(ui_events)는 미착수

마이그레이션 `0032` 가 필요하고 `0031` 이 아직 적용되지 않았다. 0031 적용 후 별도로 올린다.

## 3. 검증 상태

| 관문 | 결과 |
|---|---|
| `npx tsc --noEmit` | 0 |
| `npm run lint` | 경고 0 |
| `npm run build` | 전 라우트 성공 |
| `node --test web/lib/**/*.test.ts` | 39 passed (신규 34: renderError 8 · nextAction·renderQueue 15 · steps 11) |
| `python3 -m pytest -q` | 316 passed (엔진 회귀 없음) |
| 금지 패턴 검색 | `alert(` · `window.confirm(` · `window.location.reload(` → 0건 |
| 운영자 게이트 | dev 서버 + curl 로 5경로 실행 검증(문서 §5) |

**미검증:** 브라우저 실제 조작. 미저장 이탈 경고, 모달 포커스 순환·Esc, 씬·컷 접힘, 자동 갱신,
모바일 터치 영역은 코드·타입·빌드 수준까지만 확인했다. 뷰포트 기준(1440×900 에서 첫 후보 카드가
스크롤 없이 보이는지, 390×844 에서 문서 가로 스크롤 0)도 실측하지 않았다.

## 4. 배포 순서 (중요)

1. Vercel 서버 환경변수 `OPERATOR_KEY`·`SUPABASE_SERVICE_KEY` 설정
2. `supabase/migrations/0031_lock_cost_queues.sql` 적용

거꾸로 하면 대시보드의 승인·업로드·보관이 RLS 로 거부된다. 1 을 건너뛰면 게이트가 비활성인 채
경고 로그만 남는다(기능은 정상).
