# 편차 기록 — 비용·발행 표면 차단 (SEC-01 대체안)

- 날짜: 2026-07-27
- 관련 지시서: `docs/ui-ux-review-brief.md` → GPT 개선 지시서 SEC-01 / Phase 0 T0-1
- 관련 코드: `web/lib/apiGuard.ts`, `web/lib/supabase/admin.ts`, `supabase/migrations/0031_lock_cost_queues.sql`
- 결정자: 운영자(2026-07-27 세션에서 3택 중 "비용·발행 라우트만 보호" 선택)

## 1. 지시서 원안과 무엇이 다른가

GPT 지시서는 SEC-01 을 P0 1순위로 두고 **인증 전면 복구**를 요구했다: `0002_rls.sql` 의
`authenticated + is_allowed_user()` 정책 복구, `web/middleware.ts` 로그인 게이트, 매직링크 로그인 화면,
모든 mutation 라우트 세션 검증.

이 저장소에서 로그인 부재는 **버그가 아니라 요청된 상태**다. `supabase/migrations/0007_public_access.sql:1`
첫 줄이 `-- 로그인 제거(운영자 요청)` 이고, 같은 파일이 트레이드오프("공개 URL 을 아는 사람은 낙점/승인/
초안요청을 바꿀 수 있음")와 되돌리는 방법까지 적어놨다. `web/app/api/generate-draft/route.ts` 주석도
"로그인 제거 후에는 세션이 없으므로 anon 키를 Bearer 로 전달한다"고 명시한다. GPT 는 이 이력을 모른
채(브리핑 문서가 "0002 → 0007 교체" 사실만 적고 *사유* 를 빼먹었다) 되돌리라고 쓴 것이다.

운영자에게 3택을 제시했고 **"로그인은 그대로 없애고, 돈이 나가거나 외부로 발행되는 라우트만 막는다"**
가 선택됐다. 그래서 SEC-01 을 다음으로 대체한다.

## 2. 0007 이후 새로 생긴 사실 — 왜 아무 것도 안 하면 안 되는가

0007 은 "데이터는 비민감(논문 메타·점수·대본)"을 근거로 공개를 정당화했다. 그 판단 자체는 여전히
맞지만, 그 뒤 anon 표면에 **데이터가 아닌 것** 두 개가 들어왔다.

| 경로 | 결과 | 운영자 조작 필요? |
|---|---|---|
| `POST /api/render-trigger` 등 → `workflow_dispatch` | 렌더 워커 실행 → Veo/Gemini 유료 호출 | 불필요(anon 이 직접 호출 가능) |
| `render_jobs` 직접 INSERT (anon 키 + Supabase REST) | 다음 렌더 실행 때 소비 → 유료 호출 | 운영자가 렌더를 돌릴 때 함께 처리됨 |
| `upload_requests` 직접 INSERT | **`publish.yml` 이 15분 크론** → 유튜브 자동 업로드 | **불필요 — 15분 안에 자동 발행** |

마지막 줄이 이 작업의 방아쇠다. 라우트 가드만 넣으면 이 경로는 그대로 열려 있다. 그래서 라우트
게이트와 큐 테이블 잠금을 **한 쌍으로** 넣는다.

## 3. 무엇을 했는가

### 3-1. 라우트 게이트 — `web/lib/apiGuard.ts`

- `requireOperator()`: httpOnly 쿠키 `va_op` 의 토큰을 `OPERATOR_KEY` 파생 토큰(sha256)과 상수시간 비교.
  불일치면 401 `{error: "잠금 해제가 필요합니다 — /unlock …", code: "operator_required"}`.
  **쿠키에 원본 키를 넣지 않는다**(파생 토큰만). 기존 호출부가 `e?.error` 를 토스트에 그대로 띄우므로
  클라이언트를 고치지 않아도 사용자가 다음 행동을 안다.
- `OPERATOR_KEY` 미설정이면 **통과 + 경고 로그**. 키를 넣기 전에 배포가 죽지 않게 한 점진 도입이다
  (= 키를 설정하지 않으면 보호되지 않는다. 배포 후 Vercel 환경변수 설정이 필수 단계다).
- `/unlock` 화면에서 키 1회 입력 → 쿠키 180일. 기기당 1회이므로 매일 쓰는 흐름에는 등장하지 않는다.
  로그인 제거 후 유령처럼 남아 있던 `globals.css` 의 `.login-box` 스타일이 이 화면의 실제 사용처다.

**게이트를 적용한 라우트(14개)** — 지시서가 지목한 6개보다 넓다. 6개만 막으면 나머지가 같은 지출을
그대로 일으켜 게이트가 장식이 된다:

`render-trigger`, `youtube-upload`, `report-render-trigger`, `report-youtube-upload`,
`generate-draft`, `report-generate-draft`, `directive-approve`, `report-directive-approve`,
`directive-generate`, `report-directive-generate`, `render-add-language`,
`report-compliance-check`, `report-render-retry`, `render-result`(**`action=reject` 분기만** — `publish` 는 `published`
행 기록뿐이라 비용·외부발행이 없어 열어둔다).

게이트를 **넣지 않은** 것: 낙점·탈락(`decide`), 대본/컷 편집·저장(`draft-update`, `directive-update`),
대본 승인(`approve`), 배치 확인(`review-date`), 보관·휴지통(`render-manage`). 운영자 결정대로 매일
쓰는 판단 흐름은 키를 묻지 않는다.

### 3-2. 큐 테이블 잠금 — `supabase/migrations/0031_lock_cost_queues.sql`

`render_jobs`, `upload_requests`, `report_render_jobs`, `report_upload_requests` 네 테이블의
`*_public_all`(anon for-all) 정책을 **select 전용**으로 교체했다. 읽기는 그대로 열어둬 대시보드의
진행률·QA·유튜브 링크 표시가 깨지지 않고, 쓰기는 `service_role` 만 남는다(엔진 워커는 원래
service_role 이라 영향 없음). 기존 마이그레이션 파일은 수정하지 않았다(지시서 금지사항 1).

### 3-3. 서버 전용 service key 클라이언트 — `web/lib/supabase/admin.ts` ★ 관례 편차

0031 이후 anon 키로는 큐에 쓸 수 없으므로, 게이트를 통과한 정당한 라우트는 service key 로 쓴다.

**이것이 이 문서의 핵심 편차다.** `CLAUDE.md` 는 `SUPABASE_SERVICE_KEY` 를 "서버/엔진 전용"으로
규정하고, 지금까지 `web/` 에는 두지 않았다(`web/.env.example` 도 "SERVICE_KEY 같은 서버 전용 시크릿은
여기 넣지 않는다"고 적혀 있다).

- 규약의 문자: 서버사이드/엔진 전용, `NEXT_PUBLIC_` 노출 금지 → **위반하지 않는다.** 라우트 핸들러는
  서버이고, `NEXT_PUBLIC_` 을 붙이지 않으며, 클라이언트 컴포넌트에서 import 하지 않는다.
- 규약의 관행: 그래도 지금까지 `web/` 에는 키를 두지 않았다 → **여기서 깬다.**
- 대안과 왜 안 했나:
  - *SECURITY DEFINER 함수로 INSERT 를 감싸고 anon 에 execute 허용* — 함수가 곧 우회 경로가 되어
    RLS 잠금이 무의미해진다.
  - *렌더 트리거를 엔진 쪽으로 옮긴다* — 대시보드 버튼 즉시성(현재 UX)을 잃는다.
  - *anon 쓰기를 열어두고 라우트 가드만* — `publish.yml` 15분 크론 경로가 그대로 열린다(§2).
- 위험: Vercel 서버 환경변수가 유출되면 DB 전체 권한이 나간다(현재는 anon 권한만 나갔다). 완화:
  `createAdminClient()` 는 큐 쓰기 8곳에서만 쓰고 읽기는 계속 anon 클라이언트를 쓴다.

## 4. 필요한 환경변수 (배포 시 설정)

`web/.env.example` 은 이 저장소의 권한 설정으로 편집이 막혀 있어 여기에 남긴다. 둘 다 **서버 전용**,
`NEXT_PUBLIC_` 접두사 금지:

```
OPERATOR_KEY=            # /unlock 에서 입력하는 운영자 키. 미설정이면 게이트 비활성(경고 로그).
SUPABASE_SERVICE_KEY=    # 0031 이후 큐 쓰기용. 미설정이면 anon 폴백 → RLS 로 거부됨(경고 로그).
```

## 5. 검증

- `OPERATOR_KEY` 설정 + 쿠키 없음 → `POST /api/render-trigger` 401 `operator_required`.
- `/unlock` 에서 키 입력 후 같은 호출 → 정상.
- 0031 적용 후 anon 키로 `render_jobs`/`upload_requests` 직접 INSERT → RLS 거부.
- `SUPABASE_SERVICE_KEY` 설정 후 대시보드 승인·업로드·보관·휴지통 정상.
- 엔진(`python -m engine.render`, `engine.publish`)은 service_role 이라 회귀 없음.

## 6. 되돌리기

1. Vercel 에서 `OPERATOR_KEY` 삭제 → 게이트 즉시 비활성(코드 변경 없이).
2. 네 테이블에 `for all to anon, authenticated using(true) with check(true)` 정책 재생성 → 0007 상태.
3. `queueWriter(supabase)` 를 `supabase` 로 되돌리고 `SUPABASE_SERVICE_KEY` 삭제.

## 7. 남은 표면 (이번에 닫지 않은 것)

운영자 결정에 따라 **데이터 조작은 여전히 anon 에 열려 있다** — 공개 URL 을 아는 사람은 낙점·탈락을
바꾸고, 대본·컷을 편집하고, 대본을 승인할 수 있다. 0007 의 원래 판단(비민감 데이터)이 그대로 적용되는
범위다. 이걸 닫으려면 로그인 복구가 필요하고, 그건 운영자가 명시적으로 거부했다.
