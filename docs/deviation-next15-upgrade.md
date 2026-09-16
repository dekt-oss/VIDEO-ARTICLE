# 편차 기록 — Next 14.2.35 → 15.5.25 업그레이드 (2026-09-16)

배경: `docs/핸드오프_취약점정리_2026-09-16.md`(보관 저장소). 공개 전환 직후 Dependabot 이
34건을 보고했고, 그중 **23건이 `next`** 였다. 여기가 그 처리 기록이다.

## 1. 무엇을 왜 했나

### 1-1. 먼저 — 업그레이드와 **별개로** `_next/image` 를 게이트 안으로 넣었다
`GHSA-2xp9-vwfh-vxw4` 는 Image Optimization API 의 **미인증 원격 코드 실행**이다(대상 `< 15.5.24`).
사이트 전체가 운영자 키로 잠겨 있었는데도 `web/middleware.ts` 의 matcher 가 이 경로를
예외로 두고 있었다 — **비로그인으로 닿는 유일한 실행 표면**이었다(실측 HTTP 400 = 살아 있음).

앱은 `next/image` 를 쓰지 않는다(import 0건). 그래서 막아도 잃는 기능이 없다.
**업그레이드 후에도 유지한다** — 안 쓰는 표면은 계속 닫아 둔다.
회귀 테스트: `tests/test_public_repo_guards.py::test_middleware_matcher_does_not_exempt_the_image_optimizer`.
두 번째 단언이 "next/image 를 쓰기 시작하면" 먼저 깨져서 다시 판단하게 만든다.

### 1-2. 본 작업 — `next` 15.5.25 / React 19
| 패키지 | 전 | 후 |
|---|---|---|
| next | ^14.2.35 | ^15.5.25 |
| react · react-dom | ^18.3.1 | ^19.3.0 |
| @types/react · @types/react-dom | ^18.3 | ^19.2 |
| eslint-config-next | ^14.2.35 | ^15.5.25 |
| recharts | ^2.13.0 | ^2.15.4 |

`npm audit` **34건 → 2건**. 남은 2건은 next 가 물고 있는 postcss 이고(빌드 도구),
닫으려면 next 16 이 필요하다 — 아래 §4.

recharts 는 **2.x 에 머물렀다**. 2.15.4 의 peer 가 이미 React 19 를 받는다
(`react: ^16 || ^17 || ^18 || ^19`). 3.x 는 차트 API 가 바뀌므로 보안 작업에 섞지 않았다.

## 2. 깨진 것과 고친 방법

### 2-1. `cookies()` 가 async — 호출부 번짐을 어떻게 줄였나
두 곳에서 쓴다. **서로 다르게** 처리했다.

**`web/lib/supabase/server.ts` — 번지지 않게 막았다.**
문서가 권하는 `export async function createClient()` 로 가면 `await createClient()` 가
**호출부 50여 곳**으로 번진다. 대신 쿠키 어댑터만 async 로 만들었다 —
`@supabase/ssr` 의 `getAll`/`setAll` 은 Promise 반환을 허용한다(`types.d.ts` 의
`GetAllCookies`/`SetAllCookies`). `createClient()` 는 계속 동기이고 호출부는 한 줄도 안 바뀐다.
▸ 달라지는 점 하나: 요청 컨텍스트 밖에서 부르면 예전엔 **생성 시점**에 터졌는데 이제는
  첫 질의 시점에 터진다. 이 저장소에는 모듈 최상위에서 만드는 곳이 없다(grep 확인).

**`web/lib/apiGuard.ts` — 번지게 뒀다(그래야 안전하다).**
`isOperator()`·`requireOperator()` 를 async 로 바꾸고 라우트 27개 파일 28곳에 `await` 를 붙였다.
여기서 어댑터 트릭을 쓰지 않은 이유: 게이트는 **값 자체가 판정**이라 숨기면 위험하다.
`await` 없는 `isOperator()` 는 Promise 라 **언제나 truthy** → 게이트가 통째로 통과로 뒤집힌다.
TS 는 조건식의 Promise 를 잡아주지 않으므로 소스 형태로 못박았다:
`tests/test_public_repo_guards.py::test_operator_checks_are_always_awaited` +
기존 게이트 테스트를 `await requireOperator()` 로 강화.

### 2-2. `params`·`searchParams` 가 Promise — 페이지 6개
본문을 건드리지 않으려고 props 로 받아 맨 앞에서 `await` 해 **같은 이름으로 다시 묶었다**.

```ts
export default async function HomePage(props: { searchParams: Promise<{ date?: string }> }) {
  const searchParams = await props.searchParams;   // 아래 본문은 그대로
```

리다이렉트 전용 페이지 2개(`/directive/[paperId]`·`/finance/directive/[reportId]`)는
동기 함수였어서 `async` 로 바꿨다.

### 2-3. ⚠️ lint 규칙 하나를 껐다 — `@next/next/no-html-link-for-pages`
`eslint-config-next` 15 부터 이 규칙이 App Router 에서도 걸린다. 14 에서는 안 걸려서
`<a href="/review/...">` 9곳이 통과했고 CI(`tests.yml` 의 `npm run lint`)도 초록이었다.

**고치지 않고 껐다.** 근거: 이 `<a>` 들은 **일부러 전체 새로고침**이다.
검수 화면들이 `useState(initialXxx)` 로 서버 props 를 초기값으로 잡는데(ReviewClient:82,
ReportReviewClient:48 등) useState 초기값은 **첫 마운트에서만** 쓰인다. `<Link>` 로 바꿔
소프트 내비게이션이 되면 다른 논문/리포트로 넘어가도 앞 화면 상태가 남는다 —
이미 한 번 낸 사고다(`components/CandidateList.tsx:51`·`ReportCandidateList.tsx:49` 주석).
**보안 업그레이드 커밋에서 화면 동작까지 바꾸지 않는다.**

되돌리는 법: 위 컴포넌트들이 props 변화를 따라가게 고친 뒤 `web/.eslintrc.json` 의
그 줄을 지우고 `<a>` 9곳을 `<Link>` 로 바꾼다. 남은 자리는 `npm run lint` 가 바로 짚어 준다.

### 2-4. fetch 캐시 기본값
Next 15 는 `fetch` 기본이 `no-store`(14 는 `force-cache`)이고 클라이언트 라우터 캐시의
`staleTimes.dynamic` 기본도 30초 → 0 이다. **둘 다 더 신선해지는 방향**이라 "목록이 옛
데이터를 보인다"는 위험은 반대로 줄었다. 페이지는 어차피 전부 `force-dynamic` 이다.

## 3. 실측 검증 (전부 무료·로컬)
1. `npx tsc --noEmit` · `npm run lint` · `node --test lib/*.test.ts lib/work/*.test.ts`(76개) · `npm run build` — 전부 통과, 경고 0.
2. `pytest` 2,054 통과. 유일한 실패는 `test_board_render_golden`(윈도우 로컬 고질 — 코드 회귀 아님).
3. **운영 빌드 실측** (`next start`, 게이트 음성·양성 양쪽):

   `OPERATOR_KEY` 미설정:

   | 경로 | 결과 |
   |---|---|
   | `/` · `/scored` · `/review/anything.png` | 307 → `/unlock?next=…` |
   | `POST /api/decide` | 401 |
   | `/unlock` · `/_next/static/chunks/*.js` | 200 |
   | `/_next/image?url=…` | **307 → `/unlock`** (전에는 게이트 밖) |

   `OPERATOR_KEY` 설정 + 올바른 쿠키:

   | 검사 | 결과 |
   |---|---|
   | `GET /api/unlock` (쿠키 없음 / 있음) | `unlocked:false` / `unlocked:true` |
   | `POST /api/unlock` 오답 | 401 |
   | `POST /api/decide` 쿠키 없음 / 위조 / 정상 | 401 / 401 / 게이트 통과 |
   | `/` · `/scored` | 200 |
   | `/_next/image` | 400 (엔드포인트 자신의 응답 — 게이트는 통과) |

   ★ 이 양성 검증이 §2-1 의 핵심이다. `await` 를 빠뜨렸다면 "쿠키 없음"이 통과하거나
   "정상 쿠키"가 막혔을 텐데 둘 다 정확히 갈렸다.

4. **아직 안 한 것:** 프로덕션(Vercel) 배포 후 같은 4가지 재확인. 배포는 운영자 몫이다.

## 4. 남은 것
- **next 16**: 남은 postcss 2건을 닫으려면 필요하다. `next lint` 가 16 에서 제거되므로
  ESLint CLI 로 옮겨야 하고(`npx @next/codemod@canary next-lint-to-eslint-cli .`),
  `cookies()` 의 동기 호환 계층도 완전히 사라진다(이번 작업으로 이미 대비됐다).
  postcss 는 빌드 도구라 급하지 않다 — 공격자가 우리 CSS·소스맵을 넣을 수 없다.
- `@supabase/ssr` 0.5 → 0.12: 이번엔 건드리지 않았다(취약점 없음, 별도 작업).
- §2-3 의 lint 규칙 되돌리기.
