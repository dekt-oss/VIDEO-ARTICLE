# 편차 기록 — 공개 저장소 전환 전 잠금 (2026-09-15)

## 무엇을 바꿨나
공개 저장소에서는 공격자가 라우트·큐 이름·마이그레이션·워크플로를 전부 읽는다고 가정한다.
"브라우저/anon 자격만으로 비용·발행·운영 변경을 시작할 수 없다"를 코드와 DB 양쪽에서 강제했다.

| 층 | 변경 | 근거 |
|---|---|---|
| DB | `0049_public_repo_lockdown.sql` — public 스키마의 anon/authenticated **쓰기 정책 전부 제거**(ALL 은 읽기 전용으로 대체) + 표 쓰기 권한 회수 + 기본 권한 회수 + RLS 꺼진 백업 표 잠금 | 라이브 실측: anon 쓰기 정책 24개(비용 큐 5 · 렌더 캐시 · 지시서/대본 · 원장 등) |
| Web 라우트 | 쓰기 라우트 24개 전부 `queueWriter`(service key) + 핸들러 **맨 앞** `requireOperator()` | 0049 뒤 anon 쓰기는 RLS·권한으로 거부된다 |
| Web 가드 | `apiGuard` 미설정 시 **fail-closed**(개발만 통과) · middleware 확장자 제외 삭제(동적 페이지 `.png` 우회) · `/api/unlock` 상수시간 비교 + 오답 지연 · `?next=` 역슬래시 차단 | |
| Edge 함수 | 4개 모두 `x-edge-secret`(=`EDGE_INVOKE_SECRET`) 없으면 403. 미설정이면 거부 | `verify_jwt` 는 anon 키도 통과시킨다. 서버 키가 JWT 가 아닌 신형 형식이라 역할 클레임 검사는 못 쓴다 |
| 워크플로 | 15개 최상위 `permissions: contents: read` · 액션 전부 커밋 SHA 고정 · Supabase CLI 버전 고정 · 입력값 셸 주입 제거 · 브랜치 푸시 가드 허용목록화(`sample/*`) · 로그에 프로젝트 ref·GCP 프로젝트 번호·응답 본문 안 찍기 · 옛 브랜치 push 트리거 삭제 · 아티팩트 보존 단축 | 공개 저장소의 로그·아티팩트는 누구나 본다 |

강제: `tests/test_public_repo_guards.py`(라우트 게이트·쓰기 클라이언트·엣지 검사·워크플로 권한/SHA/주입·마이그레이션).

## 적용 기록 (2026-09-16 · 운영자 승인 후 실행)
| 단계 | 결과 |
|---|---|
| ① 시크릿 | 운영자가 Vercel·Supabase 양쪽에 `EDGE_INVOKE_SECRET` 설정 |
| ② web 배포 | 커밋 `7a7eb393` 푸시 → Vercel 프로덕션 READY |
| ③ 엣지 배포 | 4개 배포. ★ **첫 실행에서 2개(generate-draft·generate-directive)가 조용히 반영되지 않았다** — CLI 는 "Deployed Functions." 를 찍었지만 배포본 소스에 가드가 없었다. 재배포 후 반영 확인 |
| ④ 0049 적용 | 라이브 적용 완료 |

검증(적용 후 라이브):
- 엣지 4개: 비밀값 없는 호출 → **403 forbidden** (배포 전에는 400 이었다 = 가드 없음)
- REST 음성 테스트(anon 키): `draft_requests`·`image_batch_jobs`·`render_assets` INSERT, `drafts` UPDATE,
  `decisions` DELETE, 백업 표 SELECT → **전부 401/42501**
- REST 양성: `papers`·`render_jobs`·`drafts` SELECT → 200 (대시보드 읽기 유지)
- DB: anon 쓰기 정책 0 · anon 쓰기 권한 0 · RLS 꺼진 표 0 · service_role 은 38/38 테이블 INSERT 유지(워커 무영향)
- 프로덕션 사이트: `/`·`/scored`·`/review/anything.png` → `/unlock` 리다이렉트, `/api/decide` → 401(운영자 키 필요)

**미검증:** 운영자 잠금 해제 뒤의 양성 경로(낙점·대본 수정·승인·초안 생성 버튼)는 운영자 키가 있어야 해서 확인하지 못했다.

## 배포 순서 (거꾸로 하면 버튼이 막힌다)
1. Vercel 환경변수: `SUPABASE_SERVICE_KEY`·`OPERATOR_KEY` 존재 확인, `EDGE_INVOKE_SECRET`(32자 이상 무작위) 추가
2. Supabase 함수 시크릿: `supabase secrets set EDGE_INVOKE_SECRET=<같은 값>`
3. web 배포(이 커밋) → 대시보드 낙점·대본 수정·승인 버튼 동작 확인
4. 엣지 함수 배포(`deploy-edge` 워크플로 또는 `supabase functions deploy`)
5. `0049` 적용 → 음성 테스트: anon 키로 `draft_requests` insert 가 `42501` 로 거부되는지

## 되돌리기
- DB: 필요한 테이블에 `for all to anon, authenticated using(true) with check(true)` 정책 + `grant insert, update, delete`.
- 엣지: `isTrustedCaller` 검사 줄 제거 후 재배포.
- 가드: `apiGuard.ts` 의 미설정 분기를 `return null` 로.

## 한계(정직하게)
- `/api/unlock` 오답 지연은 서버리스 인스턴스별이라 병렬 대입을 완전히 막지 못한다. 실제 방어는 **긴 무작위 `OPERATOR_KEY`** 다.
- anon **읽기**는 그대로 열려 있다(대시보드가 anon 으로 읽는다). 표에 비밀값 열은 없음을 라이브로 확인했다.
