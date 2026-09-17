# 편차 기록 — 내부 링크를 `<Link>` 로 되돌리고 lint 규칙을 다시 켰다 (2026-09-17)

> Next 15 업그레이드(`docs/deviation-next15-upgrade.md` §2-3)에서 **껐던** 규칙
> `@next/next/no-html-link-for-pages` 를 다시 켰다. 그때 적어 둔 "되돌리는 법" 그대로 밟았다.

## 1. 왜 껐었나

검수 화면의 클라이언트 컴포넌트들이 서버 props 를 `useState(initialXxx)` 의 초기값으로 잡는다.
**초기값은 첫 마운트에서만** 쓰인다. `<Link>` 로 바꿔 소프트 내비게이션이 되면 Next 가 같은
자리의 컴포넌트를 재사용하므로, 다른 논문·리포트로 넘어가도 **앞 화면의 상태가 그대로 남는다.**

이미 한 번 낸 사고다. `CandidateList` 는 홈에서 배치일을 옮겨도 목록이 안 바뀌어
"3일 내내 같은 후보"로 보였다(2026-09-04 실측).

## 2. 먼저 고친 것 — `key` 로 다시 마운트시킨다

`CandidateList` 가 이미 쓰고 있던 처방을 검수 화면에도 걸었다.

| 자리 | 무엇 |
|---|---|
| `app/review/[paperId]/page.tsx` | `<WorkspaceClient key={params.paperId}>` · `<PublishTitles key={params.paperId}>` |
| `app/finance/review/[reportId]/page.tsx` | `<WorkspaceClient key={reportId}>` |

`WorkspaceClient` 는 `useState(published)` 로 props 를 초기값으로 잡고(159~200줄 부근),
`PublishTitles` 는 `useState(initialKo)`·`useState(initialEn)` 을 잡는다. id 가 바뀌면 key 가
바뀌므로 React 가 통째로 새로 마운트한다 — 초기값이 다시 읽힌다.

★ **지금 당장은 이 경로로 갈 수 없다.** 논문→논문 이동 링크는 `href={\`/review/${id}\`}` 라
  경로가 템플릿 문자열이고, lint 규칙은 **정적 경로만** 잡는다. 그래서 그 링크들은 여전히
  `<a>`(전체 새로고침)다. `key` 는 나중에 그것들까지 `<Link>` 로 바꿀 때를 위한 안전장치다.

## 3. 바꾼 링크 — 규칙이 잡은 9곳 중 8곳

| 파일 | 링크 |
|---|---|
| `app/archive/page.tsx` | `/review` |
| `app/directive/page.tsx` | `/review` |
| `app/finance/directive/page.tsx` | `/finance/review` |
| `app/finance/review/[reportId]/page.tsx` | `/finance/review` (← 검수 목록) |
| `app/review/page.tsx` | `/` |
| `app/review/[paperId]/page.tsx` | `/review` (← 목록) |
| `components/RenderList.tsx` | `/directive` |
| `components/ReportRenderList.tsx` | `/finance/review` |

### 남긴 한 곳 — `/unlock` → `/`

`<a>` 로 두고 `eslint-disable-next-line` 한 줄과 이유를 코드에 적었다.
**게이트 상태 자체가 바뀌는 화면**이라 전체 새로고침이 맞다 — 소프트 내비게이션은 클라이언트
라우터 캐시를 탈 수 있어 잠금이 풀린 뒤에도 풀리기 전 화면이 보일 여지가 있다.
같은 이유로 성공 경로도 `window.location.replace` 를 쓴다(그 파일 45줄).

## 4. 실측 확인 (라이브 데이터, 무료)

로컬 dev 서버를 띄워 **실제 Supabase 데이터**(낙점 논문 155편)로 확인했다.
"소프트 내비게이션이 됐는가"는 전역 표식이 살아남는지로 판별했다 — 전체 새로고침이면 사라진다.

| 화면 | 이동 | 결과 |
|---|---|---|
| 논문 검수 → 목록 | `/review/7f49662a…` → `/review` | 표식 **살아남음**, 제목이 "코딩 대회 금메달…" → "④ 초안 검수" |
| 리포트 검수 → 목록 | `/finance/review/c0cb1874…` → `/finance/review` | 표식 **살아남음**, 제목이 "삼성전기…" → "④ 리포트 초안 검수" |

페이지 9곳(`/` `/review` `/directive` `/render` `/archive` `/unlock` `/finance`
`/finance/review` `/finance/directive`) 전부 200.
`npm run lint`(규칙 켠 상태) · `npx tsc --noEmit` · `npm run build` 전부 깨끗.

## 5. 되돌리는 법

`web/.eslintrc.json` 에 다시 `"@next/next/no-html-link-for-pages": "off"` 를 넣고 `<Link>` 를
`<a>` 로 되돌리면 된다. `key` 는 그대로 둬도 해가 없다(오히려 안전 쪽이다).

## 6. 남은 것

- 논문→논문·리포트→리포트 이동 링크(템플릿 경로)는 아직 `<a>` 다. 바꾸면 화면이 빨라지지만
  **소프트 내비게이션 경로가 새로 열리는** 변경이라 따로 다룬다. `key` 는 이미 걸려 있다.
- 검증은 로컬 dev 서버다. **Vercel 실측은 아니다** — 플랫폼이 앞단에서 가로채는 경로는 진짜
  주소에서 다시 재야 한다(`/_next/image` 에서 한 번 틀린 교훈).
