# 범위 이탈 기록: 유튜브 자동 업로드 (P-V2)

> CLAUDE.md 작업 규칙 6 — "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고
> `docs/`를 갱신하며 근거를 남긴다." 에 따른 기록.
> 선행 이탈: `deviation-render-pipeline.md`(렌더까지), `deviation-cloud-draft.md`(초안 클라우드화).

## 무엇이 추가되나
렌더 완료 mp4(`⑥ 렌더 결과`, `render_jobs.status='done'`)를 **대시보드 버튼 한 번으로 유튜브에
업로드**하는 층을 추가한다. 지금까지는 사람이 mp4 를 내려받아 제목·설명란을 복붙해 수동 업로드했다
(`RenderList.tsx` 의 복사 버튼). 이 이탈은 그 마지막 수동 단계를 자동화한다.

## CLAUDE.md 범위와의 충돌
CLAUDE.md 범위는 "멀티플랫폼 자동 발행"을 **P2 이후로 명시적 제외**한다. 본 기능은 그 경계를 넘는다.
`deviation-render-pipeline.md`가 "자동 발행(YouTube/IG)은 여전히 P-V2 이후로 제외"라 적어둔 바로 그
단계를, **사용자의 명시적 요청·승인** 하에 P-V2 로 착수한다. 수집·채점·초안·렌더는 그대로다.

## 확정 결정 (사용자 승인)
- **트리거 = 대시보드 버튼(자동 아님).** 렌더가 끝나자마자 무인 업로드하지 않고, 사람이 `⑥ 렌더
  결과`에서 "▶️ 유튜브 업로드"를 눌러야 큐에 적재된다. 기존 낙점·검수 human-in-the-loop 철학과 일치,
  잘못된 영상이 채널에 올라가는 것을 방지.
- **기본 공개 = 비공개(private).** 업로드는 항상 private 로 올라간다. 사람이 유튜브 스튜디오에서 최종
  확인 후 공개로 전환한다(사실오류 0건 원칙·되돌리기 어려움 대비). config `YOUTUBE_DEFAULT_PRIVACY`.
- **KO/EN = 언어별 다른 채널.** `render_jobs.lang`(ko|en)에 따라 서로 다른 채널(리프레시 토큰)로
  업로드한다. `config.YOUTUBE_REFRESH_TOKEN_SECRET_BY_LANG` 로 lang→토큰 매핑.
- **정체 잡 자동 재큐 없음.** 렌더 잡과 달리 watchdog 재큐를 하지 않는다 — 업로드는 되돌리기 어려운
  외부 행위라, 이미 업로드됐지만 `done` 기록 전 크래시한 잡을 재큐하면 채널에 **중복 영상**이 생긴다.
  `processing` 방치 잡은 사람이 유튜브 스튜디오를 확인하고 수동 재시도한다. DB 유니크 인덱스
  `upload_requests_job_active`(render_job_id 당 활성 1건)로 중복 적재도 막는다.
- **인증 = OAuth 리프레시 토큰.** 채널 업로드는 서비스계정으로 불가하다(서비스계정은 유튜브 채널을
  소유할 수 없음). OAuth2 `youtube.upload` 스코프의 리프레시 토큰 흐름을 쓴다. 클라이언트 ID/시크릿은
  채널 공통(같은 GCP 프로젝트), 리프레시 토큰만 채널(계정)마다 발급한다.

## 아키텍처 (렌더 파이프라인 미러링)
```
⑥ 렌더 결과(done) ─[대시보드 "유튜브 업로드" 버튼]→ upload_requests(queued)
                                                        │
                          publish.yml(workflow_dispatch │ + 15분 크론 안전망)
                                                        ▼
                              engine.publish (폴러) ── mp4 다운로드 → YouTube videos.insert
                                                        │
                              upload_requests(done, youtube_url) + published.platforms.youtube_{lang}
```
- **DB:** `supabase/migrations/0015_youtube_upload.sql` — `upload_requests` 큐 테이블(`render_jobs`
  패턴: 상태 enum·원자적 클레임·public RLS·언어·공개상태·유튜브 결과).
- **엔진:** `engine/publish.py`(워커 + 제목/설명 순수 조립) + `engine/providers/youtube.py`(YouTube
  Data API v3 클라이언트, google 라이브러리 지연 임포트) + `engine/db.py` 헬퍼.
- **제목/설명:** 제목은 `drafts.upload_title_{lang}`(초안 LLM 산출) 우선, 없으면 번역제목→원제 폴백.
  설명란은 `attribution.build_publish_caption`(대시보드 복붙과 동일 문구). YouTube 하드 제한(제목
  100자·설명 5000자) 안전 절단.
- **웹:** `POST /api/youtube-upload`(잡 검증→큐 적재→워커 트리거), `RenderList.tsx` 버튼·상태 표시,
  `queries.joinRenderMeta`가 `upload_requests`를 조인해 잡별 업로드 상태/링크를 채운다.
- **CI:** `.github/workflows/publish.yml` — 큐에 대기가 있을 때만 google 라이브러리를 설치하고
  `python -m engine.publish` 실행(ffmpeg/manim 불요, 렌더 워크플로보다 가벼움).

## OAuth 설정법 (채널마다 리프레시 토큰 1회 발급)
> 핵심: **OAuth 클라이언트(client_id/secret)는 1개만**, **리프레시 토큰은 채널(KO/EN)마다 1개씩**.
> 유튜브 "채널"은 구글계정/브랜드계정이 소유하므로, 토큰 발급 시 **어느 채널로 동의하는지**가 곧
> 업로드될 채널이다. 아래 5단계를 KO·EN 각각 한 번씩 돈다.

### 1. GCP 프로젝트 준비
- 콘솔: https://console.cloud.google.com/ · 새 프로젝트: https://console.cloud.google.com/projectcreate
- 기존 Gemini 프로젝트가 있으면 재사용해도 된다(새로 안 만들어도 됨). 상단에서 프로젝트 선택 확인.

### 2. YouTube Data API v3 활성화
- 바로 이 링크로 → https://console.cloud.google.com/apis/library/youtube.googleapis.com → **[사용/Enable]**.

### 3. OAuth 동의 화면 구성
- → https://console.cloud.google.com/apis/credentials/consent ("Google Auth Platform"으로 보일 수 있음)
- **User Type: External(외부)** → 만들기. 앱 이름·지원 이메일(본인)만 채우면 됨.
- **스코프**: [Add or Remove Scopes] → 검색창에 `https://www.googleapis.com/auth/youtube.upload` 붙여넣고 체크.
- **테스트 사용자(Test users/Audience)**: [Add Users] 로 **업로드할 두 채널의 구글계정 이메일을 모두 추가**
  (여기 없는 계정은 동의가 막힌다). 게시 상태는 일단 "테스트"로 둔다(§7 만료 주의).

### 4. OAuth 클라이언트 ID 만들기 (공통 1개)
- → https://console.cloud.google.com/apis/credentials → [+ 사용자 인증 정보 만들기] → [OAuth 클라이언트 ID].
- **애플리케이션 유형: 웹 애플리케이션(Web application)**.
- **승인된 리디렉션 URI**에 정확히 추가: `https://developers.google.com/oauthplayground`
- 만들기 → 뜨는 **클라이언트 ID/보안 비밀** = `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`.

### 5. 리프레시 토큰 받기 — OAuth Playground (코드 불필요, 채널마다 1번)
1. → https://developers.google.com/oauthplayground/
2. 오른쪽 위 **톱니바퀴(⚙️)** → **"Use your own OAuth credentials"** 체크 → 4단계 Client ID/Secret 붙여넣기.
3. 왼쪽 **"Input your own scopes"** 칸에 `https://www.googleapis.com/auth/youtube.upload` → **[Authorize APIs]**.
4. **KO 채널 계정으로 로그인**(브랜드/채널 선택 화면이 뜨면 KO 채널 선택) → "확인되지 않은 앱" 경고는
   [고급]→[(앱 이름)(으)로 이동] 으로 진행 → 동의.
5. **[Exchange authorization code for tokens]** → 아래 뜨는 **`Refresh token`** 복사 → `YOUTUBE_REFRESH_TOKEN_KO`.
6. **EN 채널도 반복**: 시크릿창(또는 로그아웃 후) 3~5 재실행, 이번엔 **EN 채널 계정으로 로그인·선택** →
   `Refresh token` → `YOUTUBE_REFRESH_TOKEN_EN`.
> 리프레시 토큰이 안 보이면 https://myaccount.google.com/permissions 에서 이 앱 접근을 삭제(revoke) 후 재시도.

### 6. 시크릿 등록
- **GitHub**(레포 Settings → Secrets and variables → Actions): `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/
  `YOUTUBE_REFRESH_TOKEN_KO`/`YOUTUBE_REFRESH_TOKEN_EN` + 기존 `SUPABASE_*`.
- **Vercel**(즉시 트리거 원할 때): `GITHUB_DISPATCH_TOKEN`(기존 렌더용과 공유) + `PUBLISH_WORKFLOW=publish.yml`.
  (미설정이어도 15분 크론 안전망이 큐를 주워 올린다.)

### 7. ⚠️ 7일 만료 주의
동의 화면이 **"테스트(Testing)"** 상태면 `youtube.upload`(민감 스코프) 리프레시 토큰은 **7일 뒤 만료**된다.
- **(권장)** 3단계 화면에서 **[앱 게시/Publish app] → 프로덕션(In production)** 으로 전환하면 만료가 사라진다
  (개인용은 구글 심사 없이 동작, 경고창은 여전히 [고급]으로 우회).
- 아니면 만료 시마다 5단계를 재실행해 토큰을 갱신.

### (대안) 로컬 파이썬으로 발급
브라우저 있는 로컬 머신이면 Playground 대신 스크립트로도 된다(이땐 4단계 클라이언트 유형을 **데스크톱 앱**으로).
```bash
pip install google-auth-oauthlib
python - <<'PY'
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_config(
    {"installed": {"client_id": "…", "client_secret": "…",
                   "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                   "token_uri": "https://oauth2.googleapis.com/token",
                   "redirect_uris": ["http://localhost"]}},
    scopes=["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0)   # 업로드할 채널 계정으로 로그인·동의
print("refresh_token =", creds.refresh_token)
PY
```

## 트레이드오프 / 유지보수 주의
- **google 라이브러리 격리:** `google-api-python-client`·`google-auth`는 `requirements.txt`에 넣지 않고
  `publish.yml`에서만 설치한다(manim 선례 — 수집·채점 잡을 무겁게 하지 않기 위함). 코드도 지연 임포트라
  라이브러리 없이 순수 로직 임포트·테스트가 가능하다.
- **published.platforms 병합:** `published` PK 는 paper_id 라 upsert 가 platforms 를 통째로 덮어쓴다.
  `record_youtube_publish`는 기존 행을 읽어 `platforms.youtube_{lang}`만 병합한다(렌더 `video_url` 등 보존).
- **시크릿 분리:** 모든 YOUTUBE_* 는 서버/엔진 전용. `NEXT_PUBLIC_` 노출 금지(CLAUDE.md 규약).
- **범위 유지:** IG/TikTok 등 타 플랫폼 발행은 여전히 제외. 이번 이탈은 YouTube 로 한정한다.

## 합격기준 (운영 실업로드 필요, 현재 미검증)
- 대시보드에서 완료 mp4 "유튜브 업로드" → 사람 추가 개입 없이 해당 언어 채널에 **비공개** 영상 게시,
  제목=업로드용 자극 제목, 설명란=출처·링크·해시태그(복붙과 동일).
- 같은 잡 재클릭·동시 워커에서도 중복 영상 안 생김(DB 유니크 + 활성 요청 재적재 차단).
- 실패 시 잡이 `error`로 표시되고 대시보드에 원인 노출·재시도 버튼 제공.
- **엔진 단위 자가검증(완료):** `tests/test_publish.py` 순수 로직(제목 폴백·절단·설명 조립·공개상태
  검증) 통과. **잔여(운영, 미검증):** 실제 OAuth 토큰으로 videos.insert 관통, 7일 토큰 만료 운영 확인.

---

## 리포트 공장 유튜브 업로드 (동일 파이프라인, 별도 금융 채널)
사용자 결정으로 리포트 공장에도 동일 기능을 붙였다(논문 pipeline 그대로 미러). **차이는 채널뿐**:
- **별도 금융 채널**(논문=과학 채널과 콘텐츠 분리), **KO 만**. 리프레시 토큰만 분리하고
  client_id/secret·카테고리·공개상태(private)·제목/설명 규칙은 논문과 공유.
- 채널 토큰 맵: `config.YOUTUBE_REPORT_REFRESH_TOKEN_SECRET_BY_LANG = {"ko": "youtube_refresh_token_report_ko"}`.
  `providers/youtube.upload_video(..., refresh_token_secret_by_lang=...)` 로 채널만 바꿔 재사용.

미러 구성요소:
- 큐: `report_upload_requests`(마이그레이션 0029, `upload_requests` 미러 — 부분 unique 로 중복 업로드 차단).
- 워커: `engine/report_publish.py`(`engine/publish.py` 미러). 설명란은 `report_attribution.build_publish_caption`
  (출처·**면책 고정** 포함)로 조립. 발행 기록은 `report_published.platforms.youtube_{lang}` 병합.
- DB 헬퍼: `report_db.get_report_upload_meta`/`claim_report_upload_requests`/`update_report_upload_request`/
  `record_report_youtube_publish`.
- 웹: `/api/report-youtube-upload`(라우트) + `ReportRenderList` "▶️ 유튜브 업로드" 버튼·상태 표시 +
  `reportQueries` 업로드 조인. 트리거는 `trigger-publish(workflow="report-publish.yml")`.
- 워크플로: `.github/workflows/report-publish.yml`(`publish.yml` 미러, `report_upload_requests` 폴링).

**선행조건(사용자 액션):** 금융 채널로 `youtube.upload` 스코프 리프레시 토큰을 위 5절 절차대로 발급 →
GitHub Secret **`YOUTUBE_REFRESH_TOKEN_REPORT_KO`** 등록(`YOUTUBE_CLIENT_ID/SECRET`은 기존 재사용).
**자가검증(완료):** `tests/test_report_publish.py` 순수 로직 통과. **잔여(운영, 미검증):** 실 OAuth
videos.insert 관통 — done 리포트 렌더 1건 + 위 토큰 등록 후 `report-publish` 워크플로 dispatch 로 확인.
