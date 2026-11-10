# CLAUDE.md — video-article (논문·증권 리포트 → 숏폼 대본·영상 파이프라인)

<!-- harness:begin — claude-config 에서 자동 배달. 이 블록과 .claude/shared/ 는 손으로 고치지 말 것 -->
공통 규칙(모든 프로젝트): @.claude/shared/HARNESS.md
<!-- harness:end -->

> 이 파일은 **항상 지킬 규칙과 문서 지도**만 둔다(공통 하네스 §7). 결정 경위·실측 수치·사고 기록은
> **`docs/CLAUDE_상세기록.md`** 에 원문 그대로 있다 — 아래 각 항목의 "→ 상세 §…" 가 그 문서의 절이다.
> 새 세션은 이 파일과 `docs/작업계획서.md` 를 먼저 읽는다.

## 한 줄 요약
매일 신선 논문·증권 리포트를 수집·LLM 채점해 **상위 후보를 대시보드에 차리고**, 사람이 1편 낙점하면
**Fact Sheet 기반으로 환각 없이 숏폼 대본 → 영상 지시서 → 렌더 → 유튜브 업로드**까지 잇는다.
공장은 둘이다: **논문 라인**과 **리포트 라인**(ARIA 포털 리포트).

## 범위
- **포함:** 선별(P0) · 대본/영상 지시서(P1), 그리고 아래 **승인된 예외**.
- **제외(원래 범위):** 영상 렌더링, TTS, 멀티플랫폼 자동 발행, cron 무인 실행/클라우드 엔진 배포. **범위 밖 작업은 하지 않는다.**
  그중 일부는 아래 **승인된 예외**로 열렸다. IG/TikTok 등 유튜브 외 플랫폼 발행·분석은 여전히 제외.
- **승인된 예외**(각각 근거 문서가 정본):
  - 초안 클라우드 생성(엣지 `generate-draft`) — `docs/deviation-cloud-draft.md`.
    **리포트 초안은 워커(`engine/report_draft.py`, `report-draft.yml`)가 정본이고 엣지는 폴백이다** —
    근거 게이트·논증 설계·원문 대조가 워커에만 있다. **[초안 생성]·[재검사] 버튼은 둘 다 `report_draft_requests` 큐에 적재**하고
    엣지를 직접 부르지 않는다. 리포트 수집·채점은 `report.yml`(일일 크론), **논문 라인 수집·채점은 여전히 로컬**이다. → 상세 §범위
  - 유튜브 업로드(버튼, 기본 비공개, 언어별 채널) — `docs/deviation-youtube-upload.md`.
  - 유튜브 쇼츠 성과 수집(읽기 전용, `analytics` 매일 KST 07:00) — `docs/deviation-youtube-analytics.md`.
  - 표현방식: `comic`(만화식) · `webtoon`(장면 파생). **webtoon 은 9:16 실측(`sample-continuity` → `verify-aspect`)
    전에는 운영에 쓰지 않는다.** `RENDER_BUDGET_CAP_USD` 는 잡 단위라 여러 버전·언어 총액은 ⑤ 확인 모달만 본다.
    — `docs/수정명세서_웹툰버전_v1.md`
  - **폐기됨:** `editorial`(2026-07-28), **설명판형 `explainer`(2026-08-28)** — `docs/deviation-drop-explainer-webtoon.md`.
  - 대시보드 작업 콘솔: ④⑤⑥ 이 **한 화면**(`web/components/WorkspaceClient.tsx`, 두 공장 공용).
    **돈이 나가거나 외부로 발행되는 라우트는 운영자 키 게이트**(`web/lib/apiGuard.ts`)를 거친다.
    **로그인은 없다**(0007 결정 유지). 큐 테이블은 anon 쓰기가 막혀 있어 Next 라우트가 service key 로 쓴다(`web/lib/supabase/admin.ts`).
    배포 순서는 `OPERATOR_KEY`·`SUPABASE_SERVICE_KEY` 설정 → 0031 적용(거꾸로 하면 RLS 거부).
    — `docs/deviation-cost-surface-guard.md` → 상세 §범위

## 운영자가 고정한 결정 (되돌리지 말 것)
- **발주 기본값은 만화식 하나다** — ④ [승인하고 ⑤ 지시서 만들기]·⑤ `VersionOrderBar` 기본 체크를 전 버전으로 되돌리지 않는다
  (손대지 않고 누르면 여러 버전이 통째로 발주·렌더돼 돈이 나간다).
- **홈 기본 배치일은 "가장 오래된 미확인"** 이다(최신 아님). 홈 [다음 작업] 카드는 렌더 큐 작업을 띄우지 않는다(`HOME_SKIP`).
  → `docs/deviation-home-triage-flow.md`
- **수치·출처 카드(`EVIDENCE_OVERLAY_ENABLED`)와 색 범례(`OVERLAY_LEGEND_ENABLED`)는 꺼진 채 둔다**(운영자 지시 2026-09-08 · 09-24).
  주석 레이어(낱말 카드·화살표·전후 캡션)만 `MECHANISM_LABEL_OVERLAYS_ENABLED` 로 나간다.
- 리포트 화면의 페이지 번호는 Fact Sheet `source_page` 로 확인된 것만 낸다 — **지어낸 페이지 금지**.

## 지금 진행 중인 것 — 실사형(`photo`) 등급제
- 남은 단계는 **`docs/로드맵_실사형엔진_완성까지.md`**(지시서 승인 → G2 → G4 → **G3 품질 판정**).
  **G3 전에는 "돌아간다"고만 말하고 "품질이 됐다"고 하지 않는다.**
- 기획·명세: `docs/기획서_시퀀스등급제_v2.md`·`docs/작업명세서_시퀀스등급제_v2.md`. 시퀀스 등급제는 **photo 에만** 붙는다.
- 진입점: `python -m scripts.regen_from_draft <paper_id>` → 지시서 → `engine.render`.
- **편 전체를 사기 전에 시퀀스 하나만 본다:** `python -m scripts.preview_sequence <directive_id>`
  (계획·비용 먼저, `--yes` 로 실행). 화면만 바뀌는 작업은 **`--reuse <지난 preview 폴더>` 로 0원 검증**한다.
  최종본에 그대로 쓸 그림은 **`--keep`**(안 붙이면 돌릴 때마다 다시 산다). `--keep` 은 `--free`·`--reuse` 와 같이 못 쓴다.
  새 프롬프트가 그리는 **그림 자체**를 볼 때만 비용을 말하고 승인을 받는다. → 상세 §photo
- **화풍은 2026-09-08 확정 — 임의로 바꾸지 않는다.** 정본은 `config.VISUAL_ROLE_STYLE` / `VISUAL_ROLE_NEGATIVE` /
  `PHOTO_GLOBAL_STYLE`, `tests/test_photo_style_is_locked.py` 가 고정한다(깨지면 "의도한 변경이냐"는 질문).
  바꾼다면 실측 렌더로 판정하고 핸드오프에 기록을 남긴다. 화풍 문자열을 바꾸면 **`PROMPT_CONTRACT_VERSION` 을 반드시 올린다**(안 올리면 캐시가 옛 그림을 준다).
  화풍이 정해지는 자리는 넷(역할별 접미사 · `visual_prompt` · `world` · `global_style`)이다. → 상세 §화풍
- 실사형 프롬프트는 **`engine/photo_prompt.py` 한 자리**(두 공장 공용). 영상/스틸·scene_kind 는 코드가 정한다
  (`photo_contract.assign_motion_sources`). 리포트의 "원리"는 `financial_reasoning` 단계이고, 단계 종류(과정/숫자/리스크)를
  코드가 가른다(`report_reasoning.step_kind`). 화면 구성 계약(`directive.STAGING_CONTRACT`)과 Jev 경고는 **경고·fail-open** 이다 —
  Jev 로 **차단을 새로 만들지 않고, 채점(취향)에는 쓰지 않는다**. 근거 판정 경고는 리포트 라인에만, 주입·확신 과장·교차 모순은 그림자 전용.
  경고 분류(`engine/warning_triage.py`)에서 새 코드는 숨기지 않고 action 으로 본다. 프롬프트 원문을 grep 하는 테스트는 `photo_prompt.py` 도 같이 읽는다.
  → 상세 §리포트 원리 · §Jev · §규칙통합 · §화면구성
- ⚠️ **영상엔진품질 v3 문서(`docs/phase0-영상엔진품질_v3.md`, 작업지시서 v3)는 폐기된 설명판형 기준이다 — 그 순서를 따라가지 않는다.**
  살아 있는 것은 보드 렌더 경로(옛 지시서 재생용)·Q1 정지 화면·Q4 출처 노출시간뿐. → 상세 §v3

## 작업 진행 규칙
1. 작업 순서는 `docs/작업계획서.md` 의 가장 낮은 번호의 미완료 마일스톤부터.
2. 결정 항목(D1~D7, `docs/기획안_리뷰.md`, 상세 §구현 전 확인 체크리스트)이 미확정이면 코드부터 짜지 말고 먼저 확정한다.
   **차용 공개 스킬(scriptwriting·Screenwriter 류)은 라이선스·품질을 직접 검증한 뒤에만** 쓴다.
3. 체크박스를 작업 단위로 쓰고 완료 시 체크 + 커밋. 마일스톤 종료 시 합격기준을 자가 점검해 커밋/PR 에 기록한다.
   작은 단위로 자주 커밋, 브랜치 `claude/dev-spec-planning-ht9ybi`(세션이 지정한 브랜치가 있으면 그것)에 푸시, **draft PR** 유지.
4. 명세와 충돌하는 구현 결정은 임의로 진행하지 말고 `docs/deviation-*.md` 를 남긴다.
5. 끝낼 때는 **`verify-before-done` 스킬**의 검증 게이트를 먼저 통과하고, 보고는 공통 하네스 §8 형식(다섯 덩어리).

## 아키텍처
```
engine/     Python 엔진: 수집 → 1차 필터 → 채점 → Fact Sheet/대본/자기검증 → 지시서 → 렌더 → 발행
  config    가중치·윈도우·정규화식 등 모든 튜닝 상수
web/        Next.js(App Router) 대시보드. Vercel 배포
supabase/   SQL 마이그레이션 + RLS 정책, Edge Function
docs/       명세·계획·리뷰·deviation 기록
```
엔진·워커가 Supabase 에 쓰고, 대시보드는 클라우드 데이터를 읽는다.

**기술 스택:** 엔진 Python · 대시보드 Next.js + Vercel · DB Supabase.
LLM 모델 ID: 채점·Fact Sheet·자기검증 `claude-sonnet-4-6`, 품질이 더 필요한 대본 합성 `claude-opus-4-8`.
모델·파라미터가 헷갈리면 추측하지 말고 `claude-api` 스킬을 본다.

## 코딩 규약
- **튜닝 상수는 전부 `engine/config.py`**. 코드에 매직넘버 금지.
- **LLM 출력은 JSON only.** 파싱 실패 시 1회 재시도, 그래도 실패면 0점 처리 + 로그. 5xx·타임아웃은 지수 백오프.
  **사고(429·타임아웃)로 실패한 채점은 행을 만들지 않는다** — 다음 실행이 다시 집는다(`score.TransientScoringError`).
- **환각 방지:** 대본 입력은 **Fact Sheet 만**. 프롬프트에 "Fact Sheet 에 없는 내용 추가 금지"를 명시하고, 각 씬은 `source_facts` 로 근거를 남긴다.
  **예외: 리포트 라인**은 원문 전문도 함께 받되(`DRAFT_INCLUDE_FULLTEXT`) 전문은 맥락용이고
  **화면에 나가는 수치·주장은 Fact Sheet 에 있는 것만**. → `docs/deviation-draft-fulltext-injection.md`
- **조회 상한(조용한 잘림) 주의:** Supabase `select()` 는 1,000행에서 조용히 잘리고 `.in()` 은 id 수백 개에서 죽는다.
  **웹은 `selectIn`/`selectAll`(`web/lib/supabase/chunked.ts`), 엔진은 `db.select_all` — 조건 없는 `.select()` 금지.**
  → 상세 §조회 계층
- **파이썬↔엣지 트윈은 같이 고친다**(지시서 프롬프트 · 논문 초안 한국어 검수). `tests/test_prompt_sync.py`·`tests/test_polish_twin_parity.py` 가 감시한다.
  리포트 초안 엣지(`generate-report-draft`, 폴백)에는 한국어 검수 축이 원래 없다 — 트윈 규칙을 이유로 새로 넣지 않는다.
- 대본 한국어 검수는 자기검증과 같은 호출에 얹혀 있고(추가 비용 0), 사실이 바뀌는 교정은 코드가 버린다. 리포트 **재검사**에서는 다듬지 않는다.
- **멱등 수집:** `papers.external_id` unique + upsert.
- **시크릿:** `SUPABASE_SERVICE_KEY`·`ANTHROPIC_API_KEY` 등은 서버·엔진 전용. `NEXT_PUBLIC_` 로 노출 금지.
- **레이트리밋:** arXiv 요청 간 3초 + User-Agent 연락처, OpenAlex 는 `mailto` polite pool.
- **타임존:** 날짜 계산은 config `TIMEZONE`(Asia/Seoul) 기준.

## 개발 명령어
> SessionStart 훅이 `web/`·`engine/` 의존성을 자동 설치한다.

```bash
# 엔진
python3 -m pip install -r engine/requirements.txt
python -m engine.collect                 # 수집 (최초 실행은 90일 소급)
python -m engine.collect backfill        # 플래그십 초기 백필 1회
python -m engine.diagnose <doi>          # 누락 DOI 원인 진단
python -m engine.score                   # 채점 + daily_batch (대상 = 미채점 ∩ 최근 BATCH_MAX_AGE_DAYS 일)
python -m engine.score --retry-failed    # 옛 '채점 실패' 0점 행 재채점 (비용 발생)
python -m scripts.score_axis_audit       # 채점이 사람 판정을 맞히나 — 읽기 전용·0원
python -m engine.translate               # title_ko 백필 (멱등)
python -m engine.paper_source <paper_id> # 낙점 논문 원문 확보 (낙점 이후에만)
python -m engine.draft                   # 초안 큐 폴링
pytest                                   # 순수 로직 테스트

# 대시보드
cd web && npm install && npm run dev
npm run lint && npm run build

# Supabase
supabase db push
supabase functions deploy generate-draft

# 유튜브
python -m engine.analytics               # 쇼츠 성과 스냅샷 (조회 스코프 토큰 필요)
python -m engine.perf_report             # 일간/주간/월간 분석 리포트
python -m engine.publish                 # 업로드 큐 폴링 (publish.yml 이 자동 실행)
python -m scripts.verify_image_aspect    # 웹툰 9:16 실측 (라이브 GEMINI_API_KEY 필요)
```
분석용 조회 스코프 토큰은 업로드 토큰과 분리한다. 업로드·분석 OAuth 설정은 `docs/deviation-youtube-upload.md`·`docs/deviation-youtube-analytics.md`.
초안 요청·상태조회는 로그인 이메일이 `app_allowed_emails` 에 있어야 RLS 를 통과한다.

## 환경변수 (`.env.example`, 값은 커밋 금지)
- 엔진: `OPENALEX_MAILTO`(이메일, API 키 아님) · `ANTHROPIC_API_KEY` · `REDDIT_CLIENT_ID/SECRET` · `SUPABASE_URL` ·
  `SUPABASE_ANON_KEY`(공개 가능) · `SUPABASE_SERVICE_KEY`(서버 전용) · `TIMEZONE=Asia/Seoul` · `COLLECT_WINDOW_DAYS`
- 대시보드(Vercel) 서버 전용 — `NEXT_PUBLIC_` 금지:
  - `OPERATOR_KEY` — `/unlock` 운영자 키. **미설정이면 전부 막힌다**(fail-closed).
  - `EDGE_INVOKE_SECRET` — 엣지 호출 공유 비밀(Vercel 과 `supabase secrets` 에 같은 값). 없으면 엣지 403.
  - `SUPABASE_SERVICE_KEY` — 큐 테이블 쓰기용. **0031 적용 전에** 설정.
  - `GITHUB_DISPATCH_TOKEN` — 버튼이 워커를 즉시 깨운다. **사실상 필수**(없으면 하루 3번 크론 KST 09/15/21 까지 대기).
  → 상세 §환경변수

## 완료의 정의 · 합격기준
- **마일스톤 DoD:** 체크박스 완료 + 합격기준 자가 점검 + 커밋/PR 반영.
- **P0 합격:** 상위 10편 중 낙점 가능 ≥3편인 날이 **7일 중 5일 이상**. 미달 시 config 로 조정.
- **P1 합격:** 낙점부터 승인까지 **사람 작업 ≤30분/편**, 발행 가능 초안의 **사실오류 0건**(자기검증 빨간 깃발이 오류를 실제로 잡는지 포함).
