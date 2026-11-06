# 편차 기록 — 술째리고 한 소재·여러 형식(복수 선택) + 오늘 할 일·소재 고르기·작업공간 (2026-11-05)

> 기준: 목업 인계 `claude/drinks-dashboard-mockups@a20ffb4`(docs/mockups/drinks), 코드 `claude/drinks-reels-verify-stage@4089660`(PR #142 + main #141).
> 작업 브랜치 `claude/drinks-multi-format`(로컬). 커밋·푸시·PR·운영 적용·유료 실행·공개 게시 없음.
> 이 파일은 하위 에이전트 4개가 공유하는 **계약서**이자 완료 뒤 편차 기록이다. 계약을 바꾸려면 여기부터 고친다.

## 1. 간극 (코드 근거)

| # | 합의 | 지금 코드 | 근거 |
|---|---|---|---|
| G1 | 소재 하나에 형식 1~3개 | `drink_topic_picks` PK = `topic_id`, `format_intent` 단일. `pick_topic` 은 `on conflict do update` 로 **형식·승인 시각·금액을 덮어쓴다** | 0064:52-65, 0065:440-444 |
| G2 | 형식별 대본 초안 | `drink_develop_requests` 에 형식 칸이 없다. 워커는 `drink_topic_picks.format_intent` 하나로 video/carousel 을 정한다. 활성 요청은 (topic, kind) 당 하나 | 0060:78, 0065 `drinks_start_develop`(v_intent), `drinks_develop_save_plan`:322, engine/drinks_develop.py:670 |
| G3 | 형식별 독립 승인 | `drinks_approve_content` 는 `researching` 소재만, 단일 pick 의 형식만, `drinks_select(formats=[그 형식])` 로 편성. 두 번째 형식 승인은 `invalid_state` | 0065:484-491 |
| G4 | 이미 근거 승인된 소재에 형식 추가 | `pick_topic` 이 `ready/selected` 를 거부 | 0065:424-425 |
| G5 | 밈은 `selected` 로 못 감 | `drinks_intent_format(meme)=null`, `selected_formats ⊂ {video,carousel}`. 밈은 `drink_meme_drafts`(card_id xor topic_id) | 0050:232, 0066:87 |
| G6 | 형식별 비용·합계 | 개발 결재(`drink_develop_budgets`)는 소재 단위 상한·요청 단위 가잡기. 형식별 예상은 `engine/drinks_develop.estimate_usd` 로 계산 가능, 화면엔 합계 없음 | 0060, DevelopCard |
| G7 | 공통 근거 변경 → 영향 계획 무효 | 이미 있다: `blocked_at`·`evidence_content_hash`·`plan_stale`(형식 무관, 제작안마다) | 0064 트리거, 0065:498-505 |
| G8 | 중복 요청 방지 | 활성 요청 고유 색인 + `existing:true` 응답. 형식별로 넓혀야 한다 | 0060:78, 0064:206-207 |
| G9 | 부분 실패 | 요청마다 status 독립. 형식 칸만 더하면 형식별 재시도 가능 | 0060 |
| G10 | 화면 | 홈(`/drinks`)=소재 목록, 후보는 `/discover`, 작업은 `/review/[id]` 탭 7개 + `/production/[planId]` + `/publish`. 메뉴 6묶음 | web/lib/nav.ts, app/drinks/* |
| G11 | 시험 로더 | `web/lib/drinks/*.db.test.ts` 9개가 `005x/006x`(apify 만 `|70`)만 올린다 → 0071·0072 를 못 본다 | 각 파일 L13 |
| G12 | 카드 릴스 | 이미 지원(0065, 제작안 `reel` 블록 → 묶음에 세로 영상, post_type reel, 음원 필수). "부가 옵션" 노출 여부는 운영자 결정 — **기본안: 기존 그대로 두고 발행안 단계에서 post_type 선택으로만 노출** | 0065, drinks_card_reel.py |

## 2. 결정(최소 변경) — 바꾸지 않는 것부터

- **바꾸지 않는다:** 승인·결재·제작·검수·게시·예약의 서버 규칙 전부. `drinks_approve_content` 의 검사 항목. 설명형 큐·검수. 밈 엔진·Apify 통제. 카드 릴스 음원 필수. 게시 창·지문·근거 유효성. 논문 공장 코드.
- **G1·G2·G8·G9 — 0072 `drink_topic_format_picks`:** 형식별 선택 행(PK topic_id+format_intent). `drink_topic_picks` 는 **첫 형식(대표)** 로 남겨 옛 화면·`memeQueries`·`approve_content` 옛 호출과 호환. `drink_develop_requests.format_intent` 칸 추가(null=옛 요청=대표 형식). 활성 고유 색인을 `(topic_id, kind, coalesce(format_intent,''))` 로.
- **G3·G4 — 형식별 승인:** `drinks_approve_content(p.format_intent)`: 그 형식의 제작안만 승인. 소재가 `researching` 이면 기존처럼 근거 승인 + 편성(그 형식). 소재가 이미 `ready/selected`(다른 형식이 먼저 승인됨)이면 근거는 현재 승인본이어야 하고 `drinks_select` 로 형식을 **합집합**으로 더한 뒤 제작안만 승인. `pick_topic` 은 `ready/selected` 소재에 형식 추가를 허용(승인된 근거로 일반 대본 요청, `draft_evidence=false`).
- **G5 — 밈:** 형식 선택에 밈을 포함하되 `selected_formats` 에는 넣지 않는다. 밈 선택 = `drink_topic_format_picks(meme)` 행 + 제작안은 기존 `meme_save_draft(topic_id)` 경로. 카드 밈은 뷰에서 작업 단위로 합친다(연결 RPC 없음 — 운영자 결정 전).
- **G6 — 비용:** 선택 모달이 형식별 예상(`drinks_develop_estimate` 신설 RPC, stable: `engine` 단가표와 같은 공식, 모르면 null)과 합계·결재 잔액을 보여 준다. "모르는 비용은 0 으로 쓰지 않는다".
- **G10 — 화면:** `/drinks`=오늘 할 일, `/drinks/topics`=소재 고르기, `/drinks/work/[topicId]?lane=`=작업공간(기존 컴포넌트 재사용), `/drinks/work`=만들기 목록. 옛 라우트는 **남겨 두고** 목적지 완성 뒤 메뉴·리다이렉트 전환(이번 범위 마지막 단계).
- **G11:** 로더 9개를 `/^00(5\d|6\d|7\d)_drinks_/` 로.

## 3. 계약 — 에이전트가 공유하는 인터페이스

### 3-1. 0072 `supabase/migrations/0072_drinks_multi_format.sql` (담당 A)

```sql
create table drink_topic_format_picks (
  topic_id uuid not null references drink_topics(id),
  format_intent text not null check (format_intent in ('explainer','card','meme')),
  recommended_format text, recommended_reason text,
  editorial_week date not null,           -- 월요일
  budget_id uuid references drink_develop_budgets(id),
  candidate_id uuid references drink_discovery_candidates(id),
  approved_at timestamptz, approved_amount_usd numeric(10,4),
  version int not null default 1, created_at timestamptz default now(), updated_at timestamptz default now(),
  primary key (topic_id, format_intent)
);
-- 백필: insert ... select from drink_topic_picks (on conflict do nothing)
alter table drink_develop_requests add column format_intent text check (format_intent in ('explainer','card'));
drop index drink_develop_one_active_uq;
create unique index drink_develop_one_active_uq on drink_develop_requests (topic_id, kind, coalesce(format_intent, ''))
  where status in ('queued','running');
```

RPC (모두 `service_role` 전용, `set search_path = public, pg_temp`):

| RPC | 입력 | 동작 | 출력 |
|---|---|---|---|
| `drinks_pick_topic` (교체) | 기존 + `formats: ["explainer","card","meme"]`(1~3, 중복 금지). `format` 단일도 계속 받음(= `formats:[format]`) | 후보면 승격·triage·조사 시작(기존). 소재 상태 `researching/ready/selected` 허용. 형식마다 `drink_topic_format_picks` **insert on conflict do nothing**(기존 행의 승인·금액 보존). `drink_topic_picks` 는 없을 때만 insert(대표=formats[0]). 형식마다 개발 요청: `researching` 이고 근거 없음 → evidence(chain) 1건(공유) / 근거 draft → plan(draft_evidence, format_intent) / `ready·selected` → plan(format_intent, 승인된 근거). meme → 요청 없음 | `{topic_id, created, status, picks:[{format_intent, existing, chain:{queued, existing, kind, request_id, code, message}}]}` |
| `drinks_request_develop` (교체) | 기존 + `format_intent`(plan 일 때 필수, explainer/card) | 활성 중복 검사에 형식 포함. `format_not_selected` 검사를 format_picks 로 | 기존 + `format_intent` |
| `drinks_start_develop` (교체) | 기존 | job 에 `format_intent` = 요청 칸 → 없으면 대표 pick | — |
| `drinks_finish_develop` chain (교체) | 기존 | evidence 성공 시 **선택된 explainer·card 각각** plan 요청(이미 초안 있으면 건너뜀) | `chain:[{format_intent, request_id, existing}]` |
| `drinks_develop_save_plan` (교체) | 기존 | `v_fmt` = 요청의 format_intent → 대표 pick 순 | — |
| `drinks_approve_content` (교체) | 기존 + `format_intent` | §2 G3·G4. 승인 기록은 `drink_topic_format_picks(approved_at, approved_amount_usd)`; 대표 pick 도 같은 형식이면 함께 | 기존 + `format_intent`, `spend_approval_opened:false` |
| `drinks_develop_estimate` (신설, stable) | `{topic_id?, formats:[…]}` | 형식별 `{kind, est_usd, known}`(evidence 1건 공유 + plan 형식별; meme null) + `total_est_usd`, 결재 잔액 | 읽기만 |
| `drinks_topic_formats` (신설, stable) | `{topic_id}` | format_picks 행 + 각 형식의 현재 제작안/개발 요청/제작 작업/게시 요청 요약 | 작업공간·홈 입력 |
| `drinks_work_items` (신설, stable) | `{filter?: 'approve'\|'publish'\|'all', limit?}` | 작업 단위 행 목록(§3-3) | 홈·만들기 목록 |

### 3-2. 워커 (담당 A) `engine/drinks_develop.py`
- `job["format_intent"]` 를 그대로 쓴다(이미 670·940 에서 읽음). 변경 최소: 없거나 `format_intent` 가 `card` 면 carousel. chain 응답이 배열이어도 로그만.

### 3-3. 작업 단위 행 (뷰 `drink_work_items`, 담당 A → B·C·D 가 읽음)

| 열 | 뜻 |
|---|---|
| `unit_id` text | `topic:<uuid>:<format_intent>` 또는 `meme_card:<draft uuid>` |
| `topic_id`, `title`, `question`, `topic_status`, `topic_version` | 소재(카드 밈은 topic null, title=카드 이름) |
| `format_intent` | explainer / card / meme |
| `source` | `topic` / `card` |
| `editorial_week`, `pick_approved_at`, `pick_amount_usd` | format_picks |
| `review_id`, `review_status`, `review_valid` boolean, `review_version` | 현재 근거 |
| `develop_kind`, `develop_status`, `develop_request_id`, `develop_error_code` | 이 형식의 최근 개발 요청(evidence 는 공유 — 형식 무관 최근 1) |
| `plan_revision_id`, `plan_status`, `plan_blocked` boolean, `plan_version`, `plan_format`(video/carousel) | 현재 제작안 |
| `job_id`, `job_status`, `job_error_code` | 최근 제작 작업 |
| `explainer_state` | 설명형 에피소드 state |
| `output_review_id`, `output_review_status`, `output_usable` boolean | 현재 산출물 검수 |
| `meme_draft_id`, `meme_status`, `meme_sync_grade`, `meme_external_url` | 밈 |
| `pub_request_id`, `pub_status`, `pub_pause_code`, `pub_publish_at`, `pub_external_url`, `pub_version` | 현재 발행 요청(끝나지 않은 것 우선, 없으면 최근) |
| `unknown_billed` boolean, `orphan_hold` boolean | 결과 불명 |
| `updated_at` | 정렬용 |

"현재 1건" 규칙: deliverable.current_revision_id / 최근 job / 끝나지 않은 발행 요청 → 최근. LATERAL 로 행 증식 없음. **행 수 = 작업 단위 수**를 시험이 단언.

### 3-4. 결정 함수 (담당 B) `web/lib/drinks/work/decision.ts`
입력: `WorkItem`(§3-3 행) + 설명형이면 `ExplainerStatus`(기존 `explainerQueue.nextStep` 재사용). 출력 `{ unitId, lane, blocks: Block[], primary: Primary, warnings: string[] }`.
계층: ① 대상 식별 실패 → `needs_review` ② 차단 B1~B8(`publish_unknown, spend_unknown, evidence_invalid, digest_mismatch, publish_blocked, budget_blocked, no_pass, develop_blocked`) ③ 형식별 단계 S1~S24 ④ 홈 우선순위 `rankForHome(items)`.
`Primary = { code, label, action?: { name, payload } | null, href?: string, panel: 'evidence'|'plan'|'approve'|'spend'|'buy'|'produce'|'review'|'publish'|'post'|'meme'|'none' }`. 서버가 거부할 버튼을 만들지 않는다. 알 수 없는 상태 → `needs_review`.

### 3-5. 화면 (담당 C·D)
- 액션은 전부 기존 `useDrinksAction().run(name, payload)`. 새 action 이름: `pick_topic`(formats 배열), `approve_content`(format_intent), `request_develop`(format_intent), 읽기 `develop_estimate`·`topic_formats`·`work_items`(허용 목록 `web/lib/drinks/actions.ts` 에 추가 — 담당 B).
- 라우트: `/drinks`(오늘 할 일, C) · `/drinks/topics`(C) · `/drinks/work`(목록, D) · `/drinks/work/[topicId]?lane=<intent>&panel=`(D). 옛 라우트 유지.
- `?lane=` 이 상태의 정본(새로고침 보존). 미저장 입력은 sessionStorage `drinks.work.<topicId>.<lane>` 에 초안 복원(서버 저장과 구분 표시).
- 메뉴(`web/lib/nav.ts`, D 마지막 단계): 오늘 할 일 `/drinks` · 소재 고르기 `/drinks/topics` · 만들기 `/drinks/work` · 발행·성과 ▾ · 자료·설정 ▾(소재 발견·커뮤니티 동향·밈 보드·수집 문서·수집원·실행 기록·설정). 리다이렉트: `/drinks/discover`→`/drinks/topics?tab=candidates`, `/drinks/review/[id]`→`/drinks/work/[id]`(+tab→lane/panel), `/drinks/production/[planId]`→동적 조회.

## 4. 분담·파일 경계

| 담당 | 파일 | 하지 않는 것 |
|---|---|---|
| **A DB·워커** | `supabase/migrations/0072_drinks_multi_format.sql`, `engine/drinks_develop.py`(최소), `web/lib/drinks/multiFormat.db.test.ts`(신규), 로더 9개 정규식, `tests/test_drinks_develop.py`(소스 검사가 0072 도 읽게) | 화면·nav |
| **B 결정·조회** | `web/lib/drinks/work/{decision.ts,decision.test.ts,types.ts,queries.ts}`, `web/lib/drinks/actions.ts`(허용 목록 3개 + payload 검증) | DB·화면 |
| **C 소재·홈** | `web/app/drinks/topics/page.tsx`, `web/components/drinks/topics/*`, `web/app/drinks/page.tsx`(오늘 할 일로 교체), `web/components/drinks/home/*` | 작업공간·nav |
| **D 작업공간·전환** | `web/app/drinks/work/page.tsx`, `web/app/drinks/work/[topicId]/page.tsx`, `web/components/drinks/work/*`, `web/lib/nav.ts`, `web/middleware.ts` 또는 `next.config` redirects(마지막) | DB·소재 화면 |

공통 금지: 유료 API·운영 DB·`.env`·커밋·푸시. 기존 시험을 지우지 않는다. 논문 공장 파일 금지. 새 쓰기 경로 금지(모두 `/api/drinks` 허용 목록).

## 5. 결과 (2026-11-06, 로컬만 — 커밋·푸시·운영 적용 없음)

### 5-1. 구현된 것
- **0072** `drink_topic_format_picks`(백필·가드·설명형 취소 트리거·대표 pick 미러), `drink_develop_requests.format_intent`, 활성 색인 (topic, kind, 형식), `drinks_pick_topic`(formats 1~3·옛 `format` 호환·승인 덮어쓰기 없음·ready/selected 에 형식 추가), `drinks_request_develop`·`_start_develop`·`_develop_save_plan`·`_finish_develop`(형식별 chain 배열), `drinks_approve_content(format_intent)`(researching 경로 그대로 / ready·selected 는 승인된 근거 + 편성 합집합 + 그 형식 제작안만), 읽기 `drinks_develop_estimate`·`drinks_topic_formats`·`drinks_work_items`, 뷰 `drink_work_items`.
- 웹: `/drinks`(오늘 할 일: 다음 작업 하나·미루기·타일·주간 진행표), `/drinks/topics`(후보·내 소재·밈 카드·보류, 형식 3개 체크 모달·형식별 예상 비용·결과 4분기), `/drinks/work`·`/drinks/work/[topicId]?lane=`(형식 카드·결정 바·레인·접힌 패널, 기존 컴포넌트 재사용 + `hidePrimary`), `/drinks/work/meme?meme=`(카드 밈), 결정 함수 4계층, 메뉴 5묶음, 리다이렉트(`/discover`·`/review/[id]`·`/production/[planId]` 동적, `?legacy=1` 로 옛 화면 유지). 옛 선별 보드는 `/drinks/board`.
- 시험 로더 9개가 007x 도 읽는다. CI `tests.yml` node --test 글롭에 `lib/drinks/work`·`components/drinks/topics` 추가.

### 5-2. 검증 결과
| 검사 | 결과 |
|---|---|
| 웹 `node --test`(기존 + 신규 `multiFormat.db`·`decision`·`lanes`·`redirects`·`actions`·`pickModal`·`home`) | **538 통과 / 0 실패** |
| `tsc --noEmit` / `eslint` / `next build` | 통과(새 라우트 4개 빌드됨) |
| `pytest tests/test_drinks_develop.py tests/test_drinks_explainer_queue.py` | 134 통과(담당 A) |
| `scripts.publish_loop_rehearsal` | 16/16 통과, 유료·네트워크 0 |
| 390/1280 스크린샷(`/drinks`·`/topics`·`/work`·`/work/[id]`·옛 주소 2개) | 가로 넘침 0, 리다이렉트 동작. 데이터는 서버 키 없음 상태("조회 못 함"이 "0건"과 구분돼 보임) |
| 전체 `pytest` | **3,839 통과 / 2 건너뜀(무관) / 0 실패** |
| `scripts.explainer_queue_rehearsal` · `scripts.meme_rehearsal` | 종료 코드 0(12 검사 / 8 검사), 유료·네트워크 0 |

### 5-3. 의도한 기존 시험 변경
- `singleApproval`·`cardReel` db 시험: `result.chain` 이 배열 → `chain[0]`; "설명형→카드로 바꾸면 옛 요청 취소" → "형식이 더해지고 옛 요청은 취소하지 않음"; selected 소재에 `pick_topic` 허용(G4); 승인된 제작안 재승인은 `invalid_state`.
- `approvePayload`·plan `request_develop` 호출에 `format_intent` 추가(형식 2개 이상일 때만 필수).

### 5-4. 검토 포인트(사장님·다음 리뷰어가 볼 것)
- `drinks_develop_save_plan` 이 편성에 아직 없는 형식의 **작성 중(draft) 제작안 행을 직접 넣는다**(0050 `drinks_save_plan` 의 `format_not_selected` 를 우회). 같은 검사(근거 승인·유효, 형식 선택됨, `drinks_validate_plan`, draft 중복, `drink_plans_guard` 트리거)는 그대로 지나고 승인은 여전히 편성 뒤 `drinks_plan_action` 만 한다 — 그래도 쓰기 경로가 하나 늘었으니 리뷰 대상.
- `web/tsconfig.json` 에 `allowImportingTsExtensions` 추가(결정 함수가 `.ts` 확장자로 값 import — `node --test` 용). `next build` 통과 확인.
- 밈 카드 ↔ 소재 연결 RPC 는 만들지 않았다(A안: 뷰로 합침). 카드 밈은 `/drinks/work/meme?meme=` 로 연다.
- 추천 형식 영속화 없음(선택 시 스냅샷은 기존대로).
- 홈 "확인했음 — 나중에"는 localStorage 24h, 표시 순서만 바꾼다. 실행 차단과 무관.

### 5-5. 미검증·남은 위험
- 운영 DB 적용 전. 0072 적용 순서: 0071 뒤. 되돌리기는 0072 머리말.
- 실제 데이터로 화면을 열어 본 적 없다(서버 키 없음). 운영 화면 읽기 확인은 배포·적용 뒤 사장님 Chrome 에서.
- 실제 공급자·청구·인스타·정시 게시는 보지 않았다. 목업 수치는 증거가 아니다.
- 기존 운영 데이터: 소재 4건의 `drink_topic_picks` 는 백필로 형식 표에 들어간다(운영 적용 때 행 수 확인).

## 6. 검증(통합, 최종에 한 번)
pytest 전체 · 웹 `node --test lib/*.test.ts lib/work/*.test.ts lib/drinks/*.test.ts` · `tsc` · `lint` · 리허설(`publish_loop`·`explainer_queue`·`meme`) · 작업명세서 §4 사례 → `multiFormat.db.test.ts` + `decision.test.ts` · 390/1280 스크린샷(Playwright, 가짜 데이터 페이지).
