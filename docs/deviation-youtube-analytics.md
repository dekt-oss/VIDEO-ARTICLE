# 범위 이탈 기록: 유튜브 쇼츠 성과 수집 (P-V3)

> CLAUDE.md 작업 규칙 6 — "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고
> `docs/`를 갱신하며 근거를 남긴다." 에 따른 기록.
> 선행 이탈: `deviation-render-pipeline.md`(렌더), `deviation-cloud-draft.md`(초안 클라우드화),
> `deviation-youtube-upload.md`(업로드, P-V2).

## 무엇이 추가되나
채널에 **최근 N일(기본 7일) 올린 쇼츠의 성과 데이터**(조회수·평균 시청 지속률·평균 시청 시간·
좋아요·댓글·공유·구독 전환, 가능 시 노출 CTR)를 유튜브에서 끌어와 Supabase 에 스냅샷으로 저장하고,
대시보드 `데이터 › 쇼츠 성과`(`/analytics`)에서 언어(채널)별로 본다. **읽기 전용** — 발행/수정 없음.

## CLAUDE.md 범위와의 충돌
CLAUDE.md 범위는 "멀티플랫폼 자동 발행"과 그 이후 운영 기능을 **P2 이후로 제외**한다. 성과 측정은
`deviation-youtube-upload.md`가 자동화한 "발행"의 다음 단계이며, 본래 범위 밖이다.
**사용자의 명시적 요청·승인**("유튜브 계정 성과 분석·데이터 수집 가능?") 하에 P-V3 로 착수한다.
수집·채점·초안·렌더·업로드 흐름은 그대로다. IG/TikTok 등 타 플랫폼 분석은 여전히 제외.

## 확정 결정 (사용자 승인)
- **읽기 전용·별도 스코프.** 업로드 토큰(`youtube.upload`, 쓰기 전용)에는 성과 조회 권한이 없다.
  성과 조회는 `youtube.readonly`(영상 목록·길이) + `yt-analytics.readonly`(지표) 스코프로 **새 토큰을
  재발급**해 쓴다. 업로드 토큰과 물리적으로 분리(`YOUTUBE_ANALYTICS_REFRESH_TOKEN_{KO,EN}`).
  - **폴백:** 사용자가 기존 업로드 토큰을 위 두 조회 스코프를 **추가해** 재발급한 경우, 전용 조회
    토큰을 비워두면 업로드 토큰으로 폴백한다. 폴백 토큰에 조회 스코프가 없으면 API 403 → 명확한 에러.
- **쇼츠 판정 = 길이 ≤ 180초.** Analytics API 는 "쇼츠"만 거르는 필터가 없다. Data API 로 영상 길이를
  받아 `config.YOUTUBE_SHORTS_MAX_SEC`(기본 180) 이하만 남긴다. 유튜브 정책 변경(60→180초) 반영,
  상수라 조정 가능.
- **트리거 = 사람이 직접 실행(로컬 또는 GitHub Actions 수동 버튼).** 기본은 로컬 `python -m
  engine.analytics`. 실사용에서 로컬 파이썬 환경 없이도 돌리고 싶다는 요청이 있어 `publish.yml`과
  같은 패턴의 `analytics.yml`을 추가했다 — 트리거는 **`workflow_dispatch`뿐**(스케줄 없음), Actions
  탭에서 사람이 직접 "Run workflow"를 눌러야 실행된다. **무인 크론은 여전히 도입하지 않는다**(CLAUDE.md
  "cron 무인 실행 제외" 유지 — 정기 자동 실행이 아니라 매번 사람이 누르는 수동 버튼이라는 점이 핵심).
  대시보드 자동 트리거(업로드처럼 버튼 하나로 큐잉)는 아직 없음 — Actions 탭에서 직접 실행.
- **일 단위 스냅샷.** `(video_id, snapshot_date)` 멱등 upsert — 같은 날 재실행하면 최신 지표로 갱신,
  날짜가 바뀌면 새 행. 추후 성장 추이(같은 영상의 날짜별 조회수)를 남기기 위한 시계열 설계.
- **CTR 은 있으면 저장.** 노출수/노출 CTR 은 Analytics 지표 구성에 따라 응답에 없을 수 있어, 없으면
  `ctr_percent = null` 로 둔다(대시보드는 "—" 표시). 필수 지표(조회/시청/좋아요/구독)는 항상 채운다.
- **OAuth 클라이언트도 조회 전용으로 분리 가능(선택).** 업로드가 어느 GCP 프로젝트를 쓰는지 몰라도
  또는 건드리고 싶지 않아도, **완전히 별도 프로젝트에서 새 OAuth 클라이언트**를 만들어 조회만 쓸 수
  있다(`YOUTUBE_ANALYTICS_CLIENT_ID/SECRET`, 비우면 업로드 클라이언트로 폴백). 프로젝트를 만든 구글
  계정과 실제 유튜브 채널 계정이 달라도 무방하다 — OAuth 인증(Authorize) 단계에서 로그인하는 계정이
  곧 권한을 주는 채널이며, 클라이언트를 등록한 프로젝트 소유 계정과는 별개다.

## 아키텍처
```
python -m engine.analytics
        │
        ├─ providers.youtube.list_channel_shorts(lang, since)  ── Data API: 업로드 재생목록에서
        │                                                          최근 게시분 → videos.list 길이로 쇼츠만
        ├─ providers.youtube.fetch_video_analytics(lang, ids)  ── Analytics API reports.query
        │                                                          (dimensions=video, metrics=조회/시청/…)
        ├─ analytics.merge_video_metrics (순수)                ── video_id 조인 + CTR·요약 계산
        └─ db.upsert_youtube_analytics                          ── youtube_analytics 멱등 upsert
                                                                  ▼
                              대시보드 /analytics (읽기 전용, 최근 스냅샷일·언어별 표)
```
- **DB:** `supabase/migrations/0021_youtube_analytics.sql` — `youtube_analytics` 스냅샷 테이블
  (`(video_id, snapshot_date)` unique·public RLS·언어·지표 컬럼).
- **엔진:** `engine/analytics.py`(순수 헬퍼 + 오케스트레이션 + CLI) + `engine/providers/youtube.py`
  (조회 자격증명·`list_channel_shorts`·`fetch_video_analytics`, google 라이브러리 지연 임포트) +
  `engine/db.py`(`upsert_youtube_analytics`).
- **웹:** `web/app/analytics/page.tsx`(서버 컴포넌트, anon 키로 읽기) + `web/lib/nav.ts` 데이터 탭.
- **설정 상수:** `engine/config.py` — `YOUTUBE_ANALYTICS_*`(스코프·윈도우·쇼츠 상한·지표·토큰 매핑).

## OAuth 설정법 (조회 스코프 토큰 재발급)
> `deviation-youtube-upload.md §3~5` 와 동일 절차이되 **스코프만 조회 2종으로** 바꾼다.
> 업로드 클라이언트(client_id/secret)는 그대로 재사용하고, 리프레시 토큰만 새로 받는다.

1. **OAuth 동의 화면 스코프에 2종 추가** (기존 `youtube.upload` 는 유지해도 무방):
   - `https://www.googleapis.com/auth/youtube.readonly`
   - `https://www.googleapis.com/auth/yt-analytics.readonly`
2. **OAuth Playground** → 톱니바퀴에서 "Use your own OAuth credentials"(업로드와 같은 client_id/secret).
3. "Input your own scopes" 칸에 위 2종을 공백으로 구분해 입력 → **[Authorize APIs]**.
4. **KO 채널 계정으로 로그인·동의** → [Exchange authorization code for tokens] →
   `Refresh token` 복사 → `.env` 의 `YOUTUBE_ANALYTICS_REFRESH_TOKEN_KO`.
5. **EN 채널 반복** → `YOUTUBE_ANALYTICS_REFRESH_TOKEN_EN`.
> 팁: 업로드 토큰을 새로 발급할 때 위 2종을 **함께** 체크해 받으면, 전용 조회 토큰을 비워두고
> 업로드 토큰 하나로 업로드+조회를 겸할 수 있다(코드가 자동 폴백). 토큰을 늘리기 싫으면 이 방식.

## 실행 방법 (둘 중 하나)
`engine.publish` 와 동일하게 `google-api-python-client`·`google-auth`(+`-httplib2`, `-oauthlib`)가
필요하다. 이 두 라이브러리는 수집·채점 잡을 무겁게 만들어 `requirements.txt` 에 두지 않는다(manim·
publish 선례).

**로컬:**
```bash
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
python -m engine.analytics        # 설정된 채널(언어) 전부, 최근 7일 쇼츠 성과 수집
```

**GitHub Actions(로컬 파이썬 환경 없이):** 레포 Settings → Secrets 에 아래를 등록한 뒤, Actions 탭
→ `analytics` 워크플로 → **Run workflow** 버튼.
- 필수(신규): `YOUTUBE_ANALYTICS_REFRESH_TOKEN_KO`, `YOUTUBE_ANALYTICS_REFRESH_TOKEN_EN`
- 필수(기존 재사용): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`
  — 업로드용을 그대로 재사용(폴백). 클라이언트의 기존 시크릿이 여전히 유효하면 새로 안 만들어도 됨
  (구글 OAuth 클라이언트는 여러 시크릿을 동시에 유효하게 둘 수 있어, 발급 당시 쓴 시크릿이 아니어도
  같은 클라이언트의 다른 유효한 시크릿으로 갱신이 통과된다).
- 선택: `YOUTUBE_ANALYTICS_CLIENT_ID`/`YOUTUBE_ANALYTICS_CLIENT_SECRET` — 조회 전용 클라이언트를
  완전히 분리하고 싶을 때만. 비워두면(=시크릿 미등록) 위 기존 클라이언트로 자동 폴백.

## 성과 리포트 레이어 (일간/주간/월간 + 하이브리드 분석)
`/analytics`(최신 스냅샷 표) 위에, 일간/주간/월간 추이와 '잘된점/잘못된점/개선방향'을 보여주는
`/analytics/report`(성과 리포트)를 얹었다. 사용자 결정: **하이브리드**(규칙으로 근거 추출 → LLM
문장화) + **차트**(recharts).

- **시계열 수집:** `providers.youtube.fetch_channel_daily`(Analytics `dimensions=day`) → 채널 단위
  날짜별 지표를 `youtube_analytics_daily`(0022)에 저장. per-video 롤링 스냅샷(`youtube_analytics`)과
  달리 진짜 일별 시계열이라 주/월 집계가 가능하다. `engine.analytics.run` 이 스냅샷과 함께 수집한다.
- **하이브리드 리포트:** `engine/perf_report.py` — ① 규칙(`compute_report_facts`)으로 best/worst
  영상·저지속률·주간 WoW·월간 MoM 등 근거 지표 산출 → ② LLM(`llm.call_json`, `MODEL_PERF_REPORT`)이
  그 facts 만 보고 문장화(환각 방지: facts 밖 수치·주장 금지). LLM 실패 시 규칙 요약(`rule_summary`)
  폴백으로 항상 발행. 결과는 `performance_reports`(0023)에 `(period_type, period_start, lang)` 멱등 저장.
- **대시보드:** `web/app/analytics/report/page.tsx`(서버 컴포넌트, anon 읽기) + `web/components/
  PerfCharts.tsx`(recharts 클라이언트 컴포넌트). KPI 타일(오늘/이번주/이번달 + 전주·전월 대비 증감),
  일/주/월 차트, 잘된점/잘못된점/개선방향 배너, 상·하위 쇼츠 표. 집계는 `web/lib/date.ts`
  (`mondayOf`/`monthKey`)로.
- **실행:** `python -m engine.analytics`(수집, 시계열 포함) → `python -m engine.perf_report`(분석 생성).
  GitHub Actions `analytics` 워크플로가 두 단계를 순서대로 돈다(수동 dispatch).

## 검증 상태
- **순수 로직:** `tests/test_analytics.py`(수집 헬퍼) + `tests/test_perf_report.py`(주/월 버킷·가중평균·
  증감률·facts 규칙) 통과 — pytest 26건.
- **대시보드:** `npm run build`(recharts 클라이언트 격리) + `npm run lint` 통과, `/analytics`·
  `/analytics/report` 라우트 생성 확인.
- **라이브 API 경로(미검증):** 실제 YouTube Data/Analytics 호출은 **조회 스코프 리프레시 토큰이
  필요**해 이 저장소에서 end-to-end 검증하지 못했다. 사용자가 토큰을 넣고 `analytics` 워크플로(또는
  로컬 `engine.analytics`+`engine.perf_report`)를 1회 실행해 `/analytics`·`/analytics/report` 에 값이
  차는지 확인해야 완결된다(응답 컬럼/지표 유무는 실측으로 확정).
