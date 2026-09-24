# CLAUDE.md — video-article (하루 한 편 논문 선별·초안 시스템)

> 이 파일은 Claude Code가 **이 프로젝트를 가능한 한 자동으로 개발**하도록 돕는 가이드다.
> 새 세션은 작업 시작 전 이 파일과 `docs/작업계획서.md`를 먼저 읽는다.

## 한 줄 요약
매일 신선 논문을 수집·5축 LLM 채점해 **상위 10편을 웹 대시보드에 차리고**(P0), 사람이 1편 낙점하면 **Fact Sheet 기반으로 환각 없이 숏폼 대본 + 영상 생성 프롬프트 초안을 만든다**(P1).

## 범위
- **포함:** P0(선별) + P1(텍스트 산출물: 대본 + 영상 프롬프트까지).
- **제외(P2 이후):** 영상 렌더링, TTS, 멀티플랫폼 자동 발행, cron 무인 실행/클라우드 엔진 배포. **이 범위 밖 작업은 하지 않는다.**
  - **예외(사용자 승인):** 초안 생성만은 대시보드에서 즉시 자동 생성되도록 Supabase Edge Function(`supabase/functions/generate-draft`)으로 이식했다(로컬 워커 병행 유지). 근거·트레이드오프는 `docs/deviation-cloud-draft.md`. **논문 라인** 수집/채점은 여전히 로컬이다.
    - **정정(2026-08-02) — 리포트 라인은 반대로 뒤집혔다.** 리포트 초안은 **워커가 정본**이고 엣지는 폴백이다(`REPORT_DRAFT_EDGE_FALLBACK`). 근거 게이트(§5)·논증 설계(§6)·원문 인용 대조가 `engine/report_draft.py` 에만 있어서, 엣지가 먼저 큐를 닫으면 그 검증이 통째로 건너뛰어진다. [초안 생성]·[재검사] 둘 다 `report_draft_requests` 에 적재하고 `report-draft.yml` 이 처리한다. `GITHUB_DISPATCH_TOKEN` 이 설정돼 있으면 버튼이 워커를 즉시 깨우고, 없으면 크론을 기다린다. **크론 주기는 2026-08-12 부터 하루 3번(KST 09:00/15:00/21:00)이다** — 빈 폴링 비용 때문에 `*/15` 에서 낮췄다(`docs/deviation-cron-cost.md`). 리포트 라인 수집/채점도 로컬이 아니라 `report.yml`(일일 크론, GitHub Actions)이다.
  - **예외(사용자 승인) — 유튜브 업로드:** 렌더 완료 mp4 를 대시보드 버튼으로 유튜브에 업로드한다(P-V2). 트리거=버튼, 기본 공개=비공개(private), KO/EN=언어별 채널. 워커 `engine/publish.py`(큐 `upload_requests`) + `.github/workflows/publish.yml`. 근거·OAuth 설정법은 `docs/deviation-youtube-upload.md`. IG/TikTok 등 타 플랫폼 발행은 여전히 제외.
  - **예외(사용자 승인) — 유튜브 쇼츠 성과 수집:** 최근 N일(기본 7일) 올린 쇼츠 성과(조회/시청지속/CTR/좋아요/구독전환)를 YouTube Data+Analytics API 로 읽어 Supabase(`youtube_analytics`)에 스냅샷 저장, 대시보드 `/analytics` 에서 조회(P-V3). 추가로 일간/주간/월간 추이 + '잘된점/잘못된점/개선방향'(규칙+LLM 하이브리드)을 `/analytics/report` 에서 본다(`engine/perf_report.py`, `performance_reports`·`youtube_analytics_daily`). **읽기 전용·수동 실행**(로컬 또는 `analytics` 워크플로 버튼), 무인 크론 없음. 조회 스코프 토큰은 업로드 토큰과 분리. 근거·OAuth 설정법은 `docs/deviation-youtube-analytics.md`. IG/TikTok 등 타 플랫폼 분석은 여전히 제외.
  - **예외(사용자 승인) — 표현방식 2종 병행(만화식 + 웹툰 장면파생):** 제공 버전은 `comic`(만화식, 컷마다 새 장면)과 `webtoon`(장면 파생 — 장면 몇 장만 생성하고 나머지 컷은 **크롭**으로 만든다) **두 가지**다. 운영자가 ⑤ 화면에서 **버전 × 언어를 체크해 한 번에 발주**하고 나란히 비교한다. 명세는 `docs/수정명세서_웹툰버전_v1.md`, 근거·편차는 `docs/deviation-webtoon-b1-removal.md`.
    **운영상 꼭 알아야 할 것:** ① **9:16 실측이 아직 안 끝났다** — 종횡비를 API 파라미터로 보내도록 고쳤지만 필드 경로가 문서마다 달라 `IMAGE_ASPECT_CONFIG_SHAPE`/`IMAGE_ASPECT_RATIO_PARAM` 로 토글하게 뒀다. Actions → `sample-continuity` → step=`verify-aspect` 로 확인한 뒤 확정한다. **그 전에는 webtoon 을 운영에 쓰지 않는다.** ② 언어를 늘려도 이미지·클립은 공유돼 **추가 비용이 0**이다(총액은 버전 수로만 늘어난다). ③ `RENDER_BUDGET_CAP_USD` 는 **잡 단위** 가드라 2버전×2언어에 총액 상한이 없다 — ⑤ 확인 모달이 총액을 보는 유일한 지점이다.
    - **폐기(2026-07-28):** B타입 `editorial`(잡지형 데이터 에디토리얼)과 A/B 규칙기반 추천, `data_viz` → Manim 코드차트 경로를 **제거**했다. 근거: editorial 은 프롬프트 가이드만 있고 전용 시각 경로가 없었다(`viz_template`·`viz_params` 저장소 전체 grep 0건). 이력 문서 `docs/deviation-b1-editorial.md`·`docs/수정명세서_B1_editorial_v3.1.md` 는 폐기 배너를 달아 남겼다. 저장된 `version_type='editorial'` 행은 계속 렌더되지만 `data_viz` 컷이 스틸로 나간다.
    - **후속(v1, 2026-07):** `docs/수정명세서_editorial앵커_언어추가_클립길이_v1.md` — ③클립↔나레이션 길이 보정(구현, `engine/clip_fit.py` 는 Codex 인계 대기) + ②언어 추가 렌더(구현). ①editorial 앵커 교정은 대상 폐기로 **무효**.
  - **예외(사용자 승인) — 설명판형 explainer(리포트 해석 영상):** 리포트 라인에 `version_type='explainer'` 버전을 추가했다. 만화 패널이 아니라 **데이터 설명판(보드)** 으로 설명하고, "어느 증권사가 어떤 이유로 무엇을 전망했는지"를 화면에 명시한다. 명세 `docs/개선명세서_설명판형_v3_3.md`, 리뷰·구현 결정 `docs/deviation-explainer-v3_3.md`.
    **운영상 꼭 알아야 할 것:** ① ~~**리포트 원문(PDF)을 수집하지 않으므로**(`reports.summary` = 핵심요약) `source_mode` 는 최대 `PARTIAL_REPORT`~~ → **정정(2026-08-02):** 이제 ARIA 포털 리포트의 **원문 전문**을 받아 `report_sources` 에 보관하고 Fact Sheet 추출 프롬프트에 주입한다(`engine/report_source.py`, v3 §4). 실측 25건 중 21건이 `source_depth='full_text'`(평균 10,903자). 다만 **PDF 를 우리가 파싱하는 것은 아니어서**(ARIA 가 추출한 텍스트다) 페이지 번호는 여전히 없다 — **페이지는 Fact Sheet 의 `source_page` 로 해소되는 것만** 화면에 나가고 나머지는 코드가 버린다(지어낸 페이지 금지). ② `CHART_BOARD`·`VALUATION_BOARD` 는 아직 코드 도표가 아니라 **스틸 + 오버레이 카드**다(`engine/fin_charts` 템플릿 미구현). ③ ⑤ 화면 승인은 **필수 조건 미달 시 잠긴다**(주장 귀속·근거 보드·숫자 근거·확인 포인트). 원칙은 재생성이고 우회는 서버 로그에 남는다. ④ 마이그레이션 없음 — 신규 필드는 `report_directives.header/cuts`(jsonb) 안에 들어간다.
  - **예외(사용자 승인) — UI/UX 개선 + 비용·발행 게이트:** 대시보드를 "결정 중심 작업 콘솔"로 개선했다(지시서 `docs/개선지시서_UIUX_v1.md`, 구현 기록 `docs/deviation-uiux-phase0-2.md`). 화면: 홈=다음 작업 카드+타일 3개, ④⑤⑥ 단계형(`?step=`), ⑥=조치필요/진행/완료/보관 탭, 상단 메뉴 3축.
    **정정(2026-08-19) — 동선 통합:** ④⑤⑥ 은 **두 공장 모두** 한 라우트의 `?step=` 이다
    (`/review/[paperId]?step=`, `/finance/review/[reportId]?step=`). 옛 주소 `/directive/[id]`·
    `/finance/directive/[id]` 는 새 주소로 넘긴다. 날짜 이동·확인 처리·밀린 날 일괄 확인은
    홈 **맨 위** 바에 있다. ④ 에는 [승인하고 ⑤ 지시서 만들기] 가 있어 승인·발주·이동이
    한 번에 된다. 근거·되돌리기: `docs/deviation-flow-draft-to-directive.md`.
    **재정정(2026-08-20) — 선별 동선 4건**(두 공장 동일. 근거: `docs/deviation-home-triage-flow.md`):
    ① 홈 기본 배치일을 다시 **"가장 오래된 미확인"** 으로 되돌렸다(8/19 의 "최신" 결정 취소).
    선별은 오래된 날부터 순서대로 훑는 작업이라 최신부터 열리면 어디까지 봤는지 매번 찾아야
    했다. 밀린 날은 [✓ 확인하고 다음 날짜로]·[밀린 N일 한번에 확인]으로 앞에서부터 지운다.
    ② 배치일 글자를 26px 로 키웠다 — 과거 날짜로 열리므로 며칠 것인지 안 보이면 위험하다.
    ③ 홈 [다음 작업] 카드는 **렌더 큐 작업(실패·완료확인)을 띄우지 않는다**(`HOME_SKIP`).
    카운트는 그대로라 요약 타일 [렌더·업로드 필요] 와 ⑥ 화면에서 본다.
    ④ **확인 완료된 날의 미결정 후보는 "후보 미결정" 카운트에서 빠진다.** 탈락을 일일이
    누르지 않아도 [확인]이 그 날을 닫는다(`decisions` 행은 그대로 — 카운트만 바뀐다).
    목록 맨 아래에도 같은 확인·날짜이동 바 + [↑ 맨 위로] 가 있다(`BatchDateFooter`).
    **재정정(2026-09-11) — 통합 작업 화면.** 운영자 결정("초안 생성이랑 작업지시서를 하나로 합쳐
    초안 생성에서 바로 스타일 고르게 / 화면까지 하나로")으로 ④⑤⑥ 이 **한 화면**이 됐다
    (`web/components/WorkspaceClient.tsx`, 두 공장 공용 — `factory="paper"|"report"`).
    세로로 붙인 것이 아니라 **결정 바 하나(sticky) + 두 칸(대본 | 지시서) + 접힌 렌더 패널**이라
    2026-08-19 에 화면을 나눴던 이유(버튼이 화면 밖으로)가 돌아오지 않는다. 주 버튼은 하나이고
    무엇이 될지는 `web/lib/work/decision.ts` 상태표가 정한다(테스트 `decision.test.ts`).
    옛 `?step=` 주소는 그대로 열린다. **발주도 하나다**: 초안 요청에 `version_types`(0046)를 실으면
    워커가 초안 저장 뒤 같은 실행에서 그 버전 지시서를 잇는다(`engine/draft.py::chain_directives`,
    리포트 미러). 초안 프롬프트에서 **웹툰 화풍 앵커를 뺐다** — 화풍은 지시서/렌더에서 코드가 붙인다
    (다섯째 자리를 없앤 것). 대본을 지시서 뒤에 고치면 `drafts.updated_at`(0046 트리거) 비교로
    주 버튼이 [지시서 재생성]으로 바뀐다. 근거·되돌리기: `docs/deviation-workspace-merge.md`.
    **후속(2026-08-21) — 조회 계층·실사형 배선**(`docs/deviation-query-overflow-photo-edge.md`):
    ① Supabase 조회의 조용한 상한 2종을 `web/lib/supabase/chunked.ts` 로 막았다 —
    `.in()` 은 id 350~400개에서 **응답 헤더 오버플로**로 fetch 가 통째로 죽고(→ 150개씩 청크),
    `select()` 는 **1,000행에서 조용히 잘린다**(→ range 페이징). 호출부가 error 를 버려서
    실패가 "데이터 없음"으로 보였다(실측: `/scored` 가 프로덕션에서 1,000행 전부 "(제목 없음)").
    **새 조회를 쓸 때 id 목록은 반드시 `selectIn`, 전체 목록은 `selectAll` 을 쓴다.**
    **정정(2026-09-22) — 엔진 쪽은 그때 안 막혔고, 1년 가까이 돈이 새고 있었다.**
    같은 1,000행 잘림이 `engine/db.py` 에 그대로 있었다. 실측 시점 papers 6,016행 ·
    scores 4,650행 · daily_batch 1,140행이 전부 1,000행으로 보였고, 그래서
    `fetch_papers_to_score` 의 "이미 채점된 것" 집합이 1,000개뿐이라
    **이미 채점한 3,650편이 '미채점'으로 보여 실행마다 다시 채점됐다.** 저장된 채점의
    7.6%(353행)가 그 과정에서 `429 from gemini` 로 0점이 된 것이고, 0점은 영영 후보에
    못 오르는데 화면에서는 그냥 점수 낮은 논문으로 보인다(사장님이 그중 하나를 낙점한
    기록이 남아 있다). **엔진에서 조건 없는 `.select()` 를 쓰지 마라 — `db.select_all`
    을 쓴다.** 곁가지 둘이 함께 드러났다: ⓐ 잘림이 우연히 **나이 창(≈21일)** 노릇을 하고
    있어서, 고치면 후보 풀이 2007년까지 열린다 → `config.BATCH_MAX_AGE_DAYS` 로 명시했다.
    ⓑ 사고(429·타임아웃)로 실패한 채점은 이제 **행을 만들지 않는다** — 다음 실행이 다시
    집어 간다(`score.TransientScoringError`). 옛 실패 행은 `python -m engine.score
    --retry-failed` 로만 되살린다(돈이 든다).
    ② 논문 라인 실사형(photo)이 계획대로 안 나오던 원인은 **엣지 함수**였다 —
    지시서를 실제로 만드는 것은 `supabase/functions/generate-directive` 인데 거기 photo 계약이
    한 줄 스텁이었고 컷의 `visual_role` 을 버렸다(→ 3D 도해 컷 소멸). 계약 전문·역할 필드·
    버전별 영상 상한을 이식했고 `tests/test_prompt_sync.py` 가 파이썬↔엣지 드리프트를 감시한다.
    ③ 지시서 단계의 예산·비용 산정이 4초 티어로 계산하고 렌더는 8초를 사던 어긋남도 고쳤다.
    ⑤ **두 공장 모두** ④ 의 [승인하고 ⑤ 지시서 만들기 (N건)] 이 **만들 버전을 체크**해서
    발주한다(기본 만화식 1건). 논문 ④ 에는 [승인만] 버튼도 함께 둔다. 논문 ⑤ 의
    `VersionOrderBar` 기본 체크도 **전 버전 → 만화식 하나**로 줄였다 — 손대지 않고 누르면
    3버전이 통째로 발주·렌더되던 문제. 비교하려면 체크를 늘린다.
    **운영상 꼭 알아야 할 것:** 로그인은 계속 없지만(0007 결정 유지) **돈이 나가거나 외부로 발행되는 라우트 14개는 운영자 키 게이트**를 통과해야 한다(`web/lib/apiGuard.ts`, 해제 화면 `/unlock`). 큐 테이블 4개는 anon 쓰기가 막혀(`0031_lock_cost_queues.sql`) Next 라우트가 service key 로 쓴다(`web/lib/supabase/admin.ts`). **배포 순서: ① `OPERATOR_KEY`·`SUPABASE_SERVICE_KEY` 설정 → ② 0031 적용.** 거꾸로 하면 승인·업로드·보관이 RLS 로 거부된다. 근거·되돌리기는 `docs/deviation-cost-surface-guard.md`.

---

## 작업 진행 규칙 (★ 자동 개발의 핵심)
1. **항상 `docs/작업계획서.md`의 "가장 낮은 번호의 미완료 마일스톤"부터** 진행한다(M0→M6 순).
2. **M0(결정 항목 D1~D7)이 미확정이면 코드부터 짜지 말고** 먼저 확정한다. 사용자 결정이 필요하면 질문한다.
3. 마일스톤 내 체크박스를 작업 단위로 쓰고, 완료 시 체크 + 커밋.
4. **마일스톤 종료 시 합격기준을 자가 점검**하고 결과를 커밋/PR에 기록한다.
5. 작은 단위로 자주 커밋. 브랜치 `claude/dev-spec-planning-ht9ybi`에 푸시, **draft PR** 유지.
6. 명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고 `docs/`를 갱신하며 근거를 남긴다.
7. **작업을 끝내고 보고할 때는 항상 `verify-before-done` 스킬을 적용한다.** 무언가를 고쳤거나
   여러 단계를 거친 작업이면, 그 스킬의 완료 보고 템플릿("무슨 문제였나 / 어떻게 고쳤나 /
   지금 어떻게 됐나 / 이렇게 확인하세요")을 쉬운 언어로 쓴다. 머지·배포·PR 생성은 "완료"가 아니다.

관련 문서:
- 기술 명세 원본: `docs/` 내 명세서, 그리고 그 절 번호를 역참조하는 `docs/작업계획서.md`.
- 비판적 리뷰·정정 사항·결정 항목: `docs/기획안_리뷰.md` (특히 D1~D7).
- **★★★ 남은 단계는 `docs/로드맵_실사형엔진_완성까지.md` 를 본다**(2026-09-03 작성).
  지시서 승인 통과 → G2(8초 검증) → G4(후보 2발 검증) → **G3(품질 합격 판정)**.
  G3 전에는 "돌아간다"고만 말하고 "품질이 됐다"고 하지 않는다(기획 §12-3).

- **★★ 진행 중인 것은 `photo`(실사형) 등급제다 — 아래 v3 문서가 아니다.**
  지금 개발 중인 것은 **실사(REALITY) + 3D 도해(MECHANISM)** 로 설명하는 `photo` 버전이고,
  시퀀스 등급제(invest 8초·후보 2발)가 **오직 photo 에만** 붙는다(`SEQUENCE_TIER_VERSIONS`).
  기획·명세는 `docs/기획서_시퀀스등급제_v2.md`·`docs/작업명세서_시퀀스등급제_v2.md`.
  진입점: `python -m scripts.regen_from_draft <paper_id>` → 지시서 → `engine.render`.
  ▸ **편 전체를 사기 전에 시퀀스 하나만 본다**(2026-09-18):
    `python -m scripts.preview_sequence <directive_id>` 가 기전 컷이 가장 많은 시퀀스를 골라
    계획·비용을 먼저 찍고, `--yes` 를 붙여야 만든다(`--stills` 그림만·`--free` 비용 0).
    산출은 `docs/preview-<날짜>/`(gitignore) — 단계별 그림·최종 프레임·report.json.
  ▸ **화면이 바뀌는 작업은 `--reuse` 로 먼저 본다**(비용 0). 돈이 드는 것은 그림 생성 하나뿐이고
    자막·범례·키워드 카드·화살표·전후 분할·조립은 전부 로컬 ffmpeg 라, 지난 렌더의 **진짜 그림**
    위에서 그 전부를 사실대로 검증할 수 있다:
    `python -m scripts.preview_sequence <id> --reuse <지난 preview 폴더> --yes`.
    이 모드로만 잡힌 결함이 이미 둘이다(8초 컷에 3초짜리 이름표, 6초 컷의 2초 분할 캡션).
    **이걸로 검증 안 되는 것은 하나뿐이다 — 새 프롬프트가 그리는 그림 자체.** 그때만 비용을
    말하고 승인을 받는다.
  ▸ **한 번만 사서 최종본에 그대로 쓰려면 `--keep`**(2026-09-19). 기본 미리보기는 컷 번호를
    1..N 으로 다시 매겨 에셋 캐시를 못 쓴다 — **돌릴 때마다 다시 산다**(모르고 세 번 돌려
    계획의 3배를 쓴 적이 있다). `--keep` 은 번호를 그대로 두고 캐시에 남겨, 나중에 편 전체를
    렌더하면 그 컷들을 다시 사지 않는다. `--free`·`--reuse` 와는 같이 못 쓴다(가짜·빌려온
    그림이 정본 자리에 앉는다).
  ▸ **리포트 라인도 이제 에셋 캐시를 탄다**(2026-09-19). v1 은 `directive_id=None` 으로 불러
    캐시를 통째로 포기했다 — `render_assets.directive_id` 가 논문 `directives` 만 참조해서
    리포트 id 를 넣으면 FK 위반이었기 때문이다(실측 확인). 이제 `engine/asset_cache.py` 가
    `render_job_kind` 로 표를 갈라 리포트는 `report_render_assets`(0020)로 간다. **원장
    (`generation_attempts`)은 표가 하나뿐이라 그대로 `render_job_id` 로만 묶인다** —
    `cost.build_attempt` 가 그 경계에서 directive_id 를 떨군다.

- **★★★ 실사형 화풍은 2026-09-08 에 확정됐다 — 임의로 바꾸지 말 것.**
  운영자 판정: "저 화풍이 마음에 들어. 저 화풍으로 이제 고정해서 유지해주세요."
  화풍은 **무광 CG** 다. REALITY 와 MECHANISM 이 재질·조명·색을 **공유**하고 시점(단면)만
  다르다 — 그래야 실험실 컷과 세포 컷이 한 작품으로 보인다.
  정본은 `config.VISUAL_ROLE_STYLE` / `VISUAL_ROLE_NEGATIVE` / `PHOTO_GLOBAL_STYLE` 셋이고,
  `tests/test_photo_style_is_locked.py` 가 못박는다. **그 파일이 깨지면 회귀가 아니라
  "의도한 변경이냐"는 질문이다** — 바꾼다면 실측 렌더로 판정하고 핸드오프에 기록을 남긴다.
  ▸ **화풍이 정해지는 자리는 넷이다**(여기서 여러 번 발목을 잡혔다):
    ① 코드의 역할별 접미사 ② 지시서의 `visual_prompt` ③ 지시서의 `world` 선언
    ④ `global_style`. ③④ 는 이제 코드가 통제한다 — ④ 는 코드가 덮어쓰고,
    ②③ 은 게이트가 화풍 어휘를 막고 렌즈 어휘는 코드가 치환한다
    (`photo_contract.normalize_optics`).
  ▸ **부정어로는 아웃라인을 못 막는다**(실측 4회). 막는 것은 긍정 어휘와 장면 묘사다.
  ▸ 배경 계기와 실측 기록은 `docs/핸드오프_화풍전환_2026-09-07.md`.
  ▸ **정정(2026-09-18, 운영자 승인 "T5 색까지 승인"):** MECHANISM 문자열만 "앰버 1색" →
    "앰버 + 비교용 탁한 파랑·산호"(`config.MECHANISM_COLOR_CODE`)로 바꿨다. 두 집단·전후를
    한 색으로는 구별할 수 없었기 때문이다. 재질·조명·배경·REALITY 는 그대로. 같이 들어간
    것: 도해 구조가 이미지 프롬프트에 실림(T1), 상태가 바뀌는 stage 는 전·후 분할 스틸(T2),
    legend/label_pair 오버레이(T3). 기록: `docs/핸드오프_기전교육력_2026-09-18.md`,
    연구: `docs/연구_기전시퀀스_교육력_2026-09-17.md`.
  ▸ **증권 리포트의 "원리"는 논증 단위다**(2026-09-24, 운영자 승인). 리포트에는 논문의 "왜
    그런가" 대신 `financial_reasoning`(driver → 실적 → 밸류에이션, 단계마다 원문 인용으로 대조)이
    있고, 그것이 실사형 도해의 소재다. 단계의 **종류**를 코드가 가른다(`report_reasoning.step_kind`):
    **과정**(병목 → 우회, 수요 A → B) → MECHANISM 도해 · **숫자**(13.7조, P/E) → REALITY + 숫자 카드 ·
    **리스크**(규제, 선가 정체) → REALITY + 한 줄 카드. 배경: 프롬프트가 종류를 안 가르고 "기전
    5~7컷"만 요구하자 모델이 숫자를 **블록 막대그래프**로, 규제를 **쇠쐐기 은유**로 그렸다(저장
    11편 중 10편). 게이트 `photo_mechanism_on_number` / `_on_risk` 가 막고 처방을 되먹인다.
    리포트의 원리 공급량은 Fact Sheet 의 claim 이 아니라 **과정 단계 수**다(`process_step_count`) —
    종전엔 claim 으로 재서 모든 리포트에 "원리 없는 소재" 경고가 떴다. A/B(같은 리포트 3발):
    1차 시도 오용 3건 → 0·0·2. 숫자 단계를 도해로 그리면 "4GW"를 **엔진 네 대**로 그린다(실측).
  ▸ **화면 구성 계약 — "장면 자체가 설명이다"**(2026-09-24, 운영자 지시 "화살표·게이지 같은
    단순한 표현이 아니라 전체적으로 이해를 돕는 화면 구성"). 참고 영상(시화호·고기 핏물)은
    나레이션이 던진 질문에 장면이 **물건과 행위**로 답한다("물이 얼마나 더러운지" → 손이 병으로
    물을 뜬다 → 흙탕이 가라앉는다). 실측(`scripts/staging_shadow.py`, 565컷): 실사 컷이 나레이션에
    답하는 비율 리포트 41%·논문 31%. 그래서 컷마다 `answers_ko`(답하는 질문)·`staging_ko`(연출)를
    먼저 쓰게 한다(`directive.STAGING_CONTRACT`, 두 공장 공용, photo 전용). 첫 렌더 샘플
    ($1.40, `docs/preview-2026-09-24/618f6548`)에 대한 운영자 판정: **화풍 "너무 괜찮아"**(유지),
    밀도 조금 높다, "전력망"이 안 읽힌다, 왼쪽 아래 색 범례는 의미 없다, 부유식 데이터센터는
    진짜 그 형태로, "자리가 없어서 바다로"의 **원인**이 화면에 없다. → 계약 ⑤~⑧(알아볼 사물·
    원인을 화면에·주인공만 남기기·범례 없음) + `OVERLAY_LEGEND_ENABLED=False`(렌더·프롬프트·
    게이트 셋을 한 스위치로). 리포트 지시서 한 장 ≈ $0.15, 시퀀스 렌더 3컷 ≈ $1.40.
  ▸ **화면 주석 레이어는 코드가 그린다**(2026-09-18 저녁, 운영자 참고 영상 기준): 낱말 카드
    (`keyword`)·지시 화살표(`pointer`)·색 범례(`legend`)·전후 캡션(`label_pair`). 전부 ASS 라
    추가 비용 0이고 언어별로 나간다. 색은 `OVERLAY_ANNOTATION_COLOR_ASS` **하나**를 공유한다.
    수치·출처 카드(`EVIDENCE_OVERLAY_ENABLED`)는 2026-09-08 운영자 지시대로 **꺼진 채**이고,
    주석 레이어만 `MECHANISM_LABEL_OVERLAYS_ENABLED`(기본 켜짐)로 나간다.

- **⚠️ 아래 v3 문서는 폐기된 형식(설명판형)의 것이다 — 순서를 그대로 따라가지 말 것.**
  `docs/작업지시서_영상엔진품질_v3.md`(작성 2026-08-02) + `docs/phase0-영상엔진품질_v3.md`.
  **설명판형(explainer)은 2026-08-28 운영자 지시로 폐기됐다**(`docs/deviation-drop-explainer-webtoon.md`
  — "설명판형은 없습니다. 그런건 안쓸거에요"). 문서가 폐기보다 **26일 앞서** 쓰였고 갱신되지 않았다.
  그래서 그 문서의 Phase 4 합격기준(§14-1)은 **보드(코드 렌더) 전제**라 새 콘텐츠로는 판정할
  수 없다 — 새 지시서는 `board` 필드를 안 만들어 `code_render_board()` 가 항상 False 다.
  ▸ **살아 있는 것:** 보드 렌더 경로 자체(옛 explainer 지시서 재생용), Q1 정지 화면·Q4 출처
    노출시간(최종 영상·자막 기준이라 버전 무관), 그리고 후보 채점의 freezedetect 수정.
  ▸ **죽은 것:** Q3 애니메이션 계약 검사(`engine/animation_qa.py`)는 **보드 전용**이라
    새 콘텐츠에 안 붙는다. 옛 explainer 재렌더에서만 작동한다.
  ▸ 2026-09-03 세션이 이 문서를 "진행 중"으로 믿고 Phase 2→3 을 따라가다 Q3 에 반나절을
    썼다. **같은 함정을 반복하지 말 것.**
  재현 스크립트는 그대로 돈다: `python3 scripts/repro_phase0_board.py`.
  - **Phase 0·1 완료**(PR #78 머지). §8 결정 3건은 운영자가 확정했다 — 원문은 ARIA 전문을
    우리 Supabase 에 보관, 편당 비용 2배·시간 1.5배까지 허용, 강제 승인은 허용하되 흔적을 남긴다.
  - **Phase 2·3 대부분 완료**(2026-09-03 실사). 레지스트리·라우터·criticality·manifest 선언/대조·
    `terminal_status`(critical=failed / important=degraded)가 다 들어가 배선까지 확인했다.
    **Phase 0 이 실측한 두 결함은 이미 해소됐다** — 위 문단이 오래 낡아 있었으니 다시 적는다:
    ① 충전율 0.235 는 이제 `core_underfilled` 로 **차단**된다(문턱 0.25, 잡은 죽이지 않고
    degraded 로 보낸다). ② `generation_attempts` 는 텍스트 호출을 정상 기록한다(실측 200행+).
    다만 **이미지·영상 원장 경로는 렌더 0회라 미검증**이다.
  - **Q3 애니메이션 계약 검사 추가**(2026-09-03, `engine/animation_qa.py`). 레지스트리가
    컴포넌트마다 `min_change_ratio` 를 선언해 놨는데 **읽는 코드가 없었다** — §14-1 이 Phase 4
    조건으로 걸어 둔 항목이라 렌더보다 먼저 넣었다. 실사 보드 11종 전부 통과(ratio 1.00).
    ★ **한계를 알고 쓸 것**: 계약이 "첫↔끝"이라 "첫 프레임에 통째로 나타나 멈춘" 경우는
    통과한다. 그 구분은 `mid_to_last` 에 **기록만** 한다(문턱 근거가 아직 없다).
  - **Q1 정지 화면·Q4 출처 가시성 추가**(2026-09-03). 둘 다 "선언은 있는데 검사가 없던" 자리다.
    ① 최종 mp4 에 freezedetect 가 없어 **멈춘 화면이 통과**했다(컷 후보에는 있었다).
    고치면서 파싱 결함도 잡았다 — freezedetect 는 정지가 *끝날 때* duration 을 찍으므로
    **끝까지 얼어붙은 영상은 0.00s 로 보였다**(8초 정지 영상 실측). 후보 채점
    (`clip_candidates`)에도 같은 결함이 있어 함께 고쳤다(정지 후보가 만점을 받고 있었다).
    ② `OVERLAY_MIN_SEC`(2초)를 선언 단계는 강제하는데 `build_overlay_cues` 가 컷 경계에서
    큐를 잘라 **0.1초짜리 출처 카드**가 나갈 수 있었다 → `cue_visibility_warnings`.
    ★ 둘 다 **경고**다. 문턱을 실제 렌더 분포에 대고 잰 적이 없다(렌더 0회) —
    `RENDER_QA_FREEZE_BLOCKS` 로 올릴 수 있고, 그 판단 근거는 Phase 4 가 준다.
  - **다음은 Phase 4 검증 렌더.** 렌더 없이 판정 가능한 항목은 이것으로 정리됐다.
    §14-1 의 나머지 하드 게이트는 **렌더를 돌려야 판정된다**(실패 error_code 기록·
    degraded 경로·fallback 원장·이미지/영상 비용 원장).

---

## 아키텍처 & 디렉터리 규약
```
engine/     Python 엔진: 수집 → 1차 필터 → 5축 채점 → P1(Fact Sheet/대본/자기검증). 로컬 수동 실행.
  config    가중치·윈도우·정규화식 등 모든 튜닝 상수(코드 분리).
web/        Next.js(App Router) 대시보드. Vercel 배포.
supabase/   SQL 마이그레이션 + RLS 정책.
docs/       명세·계획·리뷰.
```
데이터 흐름: **엔진(로컬)이 Supabase에 기록 → 대시보드(Vercel)가 클라우드 데이터를 읽음.** 대시보드는 처음부터 클라우드 데이터를 본다.

## 기술 스택 (고정)
- **엔진:** Python. 채점/추출/대본 생성은 Anthropic API.
- **대시보드:** Next.js (App Router) + Vercel.
- **DB/Auth:** Supabase (Postgres + Auth 매직링크).
- **LLM 모델 ID (정확히 사용):**
  - 5축 채점·Fact Sheet 추출·자기검증: **`claude-sonnet-4-6`** (비용·품질 균형).
  - 복잡한 대본 합성 등 품질이 더 필요한 단계: **`claude-opus-4-8`**.
  - 모델 선택·파라미터·툴 사용이 헷갈리면 추측하지 말고 `claude-api` 스킬을 참조한다.

---

## 코딩 규약
- **config 상수 분리:** 가중치(재미=0.4/0.35/0.25, 중요=0.7/0.3), ④보정 on/off, ⑤buzz 정규화식, 수집 윈도우 길이, 채점 컷오프 N — 전부 `engine/config`에. 코드에 매직넘버 금지.
- **LLM 출력은 JSON only** 로 받고, **파싱 실패 시 1회 재시도 → 실패 시 0점 처리 + 로그.** API 5xx/타임아웃은 지수 백오프.
- **환각 방지 불변식(P1):** 대본 생성 입력은 **Fact Sheet "만"**. "Fact Sheet에 없는 내용 추가 금지"를 프롬프트에 명시. 각 씬은 `source_facts`로 근거를 남긴다.
  - **정정(2026-08-03) — 리포트 라인은 예외다.** 작업지시서 v3 §4-2 에 따라 리포트 초안(대본) 단계는 **Fact Sheet + 원문 전문을 함께** 받는다(`DRAFT_INCLUDE_FULLTEXT`, 기본 on). 사장님 원지시가 "초안·세부지시는 **전체를 읽고**"였고 §1-1 이 그것을 §4-2 에 걸어 뒀다. 불변식의 **목적**(검증 안 된 수치가 화면에 못 나간다)은 유지한다 — 프롬프트가 두 입력의 쓰임새를 갈라 못박는다: 전문은 **맥락용**, 화면에 나가는 수치·주장은 **Fact Sheet 에 있는 것만**. 근거·트레이드오프·되돌리는 법은 `docs/deviation-draft-fulltext-injection.md`. 논문 라인은 불변식 그대로다.
- **대본 한국어 검수(2026-09-10, 운영자 지시):** 두 공장 모두 자기검증(`selfcheck.py`·`report_selfcheck.py`)에
  `korean_natural`·`awkward_spans`·`fluency_issues` 축이 **같은 호출로** 얹혀 있다(추가 비용 0). 어색한 씬만
  `engine/script_polish.py` 가 한 번 다시 쓰고, **사실이 바뀌면 코드가 그 교정을 버린다**(숫자 다중집합·
  뜻 갈래·줄기 보존율·길이 — 문턱은 실측 분포에서 정했고 표본이 얇다). 경고이지 차단이 아니다.
  리포트 **재검사**에서는 다듬지 않는다(운영자가 손으로 고친 대본을 덮어쓰면 안 된다).
  엣지 `generate-draft` 에 트윈이 있고 `tests/test_polish_twin_parity.py` 가 같은 답을 내는지 대조한다;
  `generate-report-draft` 엣지(폴백)에는 이 축이 **없다**(v2 축도 원래 없었다).
- **멱등 수집:** `papers.external_id` unique + upsert. 같은 날 재실행해도 중복/배치 깨짐 없어야 함.
- **시크릿 분리:** `SUPABASE_SERVICE_KEY`·`ANTHROPIC_API_KEY` 등은 **서버사이드/엔진 전용.** Next.js에서 `NEXT_PUBLIC_` 접두사로 노출 금지.
- **레이트리밋 준수:** arXiv 요청 간 3초 + User-Agent 연락처, OpenAlex는 `mailto` polite pool.
- **타임존:** 모든 "어제/윈도우/배치 날짜" 계산은 config의 `TIMEZONE` 기준으로 통일.

---

## 개발 명령어
> SessionStart 훅(`.claude/hooks/session-start.sh`)이 `web/`·`engine/` 존재 시 의존성을 자동 설치한다.
> 진행 현황: **M0~M6 구현 완료**(엔진 수집/채점/P1 + P0·검수 대시보드 + 측정 자동화).
> 라이브 가동(Supabase 프로젝트·키)과 P0/P1 7일 측정은 운영 단계. P1 추가 단계: `python -m engine.draft`(큐 폴링).

```bash
# 엔진
python3 -m pip install -r engine/requirements.txt
python -m engine.collect      # 수집 (주 수집 + 플래그십 created_date 워터마크; 최초 실행은 90일 소급 백필)
python -m engine.collect backfill  # 플래그십 초기 백필 1회(과거 누락 구제, docs/deviation-collection-coverage-v2.md)
python -m engine.diagnose <doi>    # 누락 DOI 원인 진단(등록지연/매핑오류/유형탈락)
python -m engine.score        # 5축 채점 + daily_batch (+ 채점 시 title_ko 폴백)
                              #   대상 = 미채점 ∩ 최근 BATCH_MAX_AGE_DAYS(21)일.
                              #   사고(429/타임아웃)로 실패한 것은 저장하지 않고 다음 실행에 넘긴다.
python -m engine.score --retry-failed   # 옛 '채점 실패' 0점 행을 다시 채점(비용 발생)
python -m scripts.score_axis_audit      # 채점이 사람 판정을 맞히나 — 읽기 전용·0원
python -m engine.translate    # title_ko 백필 (배치/낙점 논문 중 한글 제목 빈 것만, 멱등)
python -m engine.paper_source <paper_id>   # 낙점 논문 원문 확보·보관(paper_sources, 0041)
                                           #   체인: arXiv→OpenAlex OA→PMC→Unpaywall. 멱등(doc_hash).
                                           #   ★ 수집 때 부르지 않는다 — 낙점 이후에만. PDF 경로는 pypdf 필요.
pytest                        # 순수 로직 테스트 (tests/)

# 웹툰 버전 — 종횡비 실측(라이브 GEMINI_API_KEY 필요. 샌드박스엔 없다)
python -m scripts.verify_image_aspect   # 후보 필드 형태를 실제 호출해 산출물 크기를 잰다
# GitHub Actions: Actions 탭 → sample-continuity 워크플로 → step=verify-aspect

# 대시보드
cd web && npm install
npm run dev                   # 로컬 개발
npm run lint && npm run build # 린트 + 빌드

# Supabase 마이그레이션 (supabase/migrations/*.sql)
supabase db push              # 또는 대시보드 SQL 에디터에 순서대로 실행

# Supabase Edge Function — 초안 클라우드 자동생성 (대시보드 "초안 생성 요청" 버튼이 호출)
supabase functions deploy generate-draft
supabase secrets set GEMINI_API_KEY=…      # 기본 백엔드는 Gemini(무료 등급). Anthropic 은 ANTHROPIC_API_KEY.

# 유튜브 쇼츠 성과 수집 — 최근 7일 쇼츠 성과를 youtube_analytics 에 스냅샷 저장(대시보드 /analytics)
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
python -m engine.analytics                  # 쇼츠 스냅샷 + 채널 날짜별 시계열 수집(조회 스코프 토큰 필요)
python -m engine.perf_report                # 일간/주간/월간 하이브리드 분석 리포트 생성(대시보드 /analytics/report)
# GitHub Actions: Actions 탭 → analytics 워크플로 → Run workflow (위 두 단계를 순서대로 실행)

# 유튜브 자동 업로드 — 렌더 완료 mp4 를 대시보드 "▶️ 유튜브 업로드" 버튼으로 큐잉(비공개 게시)
python -m engine.publish                    # upload_requests 큐 폴링(GitHub Actions publish.yml 이 자동 실행)
# 선행조건: OAuth 리프레시 토큰(채널별) 등 YOUTUBE_* 시크릿. 발급법은 docs/deviation-youtube-upload.md.
# 선행조건: 로그인 이메일을 app_allowed_emails 에 넣어야 RLS 통과(초안 요청/상태조회).
#   insert into app_allowed_emails(email) values ('you@example.com');
```

> 비고: `langdetect`·`feedparser`는 일부 환경에서 wheel 부재로 sdist 빌드가 필요할 수 있다(로컬 정상). `langdetect` 미설치 시 1차 필터 언어판별은 보수적으로 통과 처리된다.

---

## 환경변수 (`.env.example`로 관리, 값은 커밋 금지)
```
OPENALEX_MAILTO=          # OpenAlex polite pool용 이메일 (API 키 아님 — 리뷰 D1)
ANTHROPIC_API_KEY=        # 채점·추출·대본 생성 (핵심 비용)
REDDIT_CLIENT_ID=         # 무료 앱 등록
REDDIT_CLIENT_SECRET=
SUPABASE_URL=
SUPABASE_ANON_KEY=        # 클라이언트 공개 가능
SUPABASE_SERVICE_KEY=     # 서버/엔진 전용 — 절대 클라이언트 노출 금지
TIMEZONE=Asia/Seoul       # 수집/배치 기준 (리뷰 D5)
COLLECT_WINDOW_DAYS=      # 수집 윈도우 (리뷰 D2, 예: 3~7)
# HN, arXiv: 키 불필요
```

### 대시보드(Vercel) 서버 전용 변수 — `NEXT_PUBLIC_` 금지
```
OPERATOR_KEY=             # /unlock 에서 입력하는 운영자 키. 사이트 전체 + 모든 쓰기 라우트 게이트.
                          #   ★ 2026-09-15 부터 미설정이면 **전부 막힌다**(fail-closed, 개발만 통과).
                          #   긴 무작위 값을 쓴다(오답 지연만 있고 레이트리밋 저장소는 없다).
EDGE_INVOKE_SECRET=       # 엣지 함수 호출용 공유 비밀(32자+). Vercel 과 `supabase secrets` 에 같은 값.
                          #   없으면 엣지 함수가 403 — 초안·지시서는 워커 경로로 처리된다.
                          #   근거: docs/deviation-public-repo-lockdown.md
SUPABASE_SERVICE_KEY=     # 0031 이후 큐 테이블(render_jobs·upload_requests 등) 쓰기용.
                          #   미설정이면 anon 폴백 → RLS 거부. 반드시 0031 적용 *전에* 설정.
GITHUB_DISPATCH_TOKEN=    # 렌더·발행·**리포트 초안** 워커 workflow_dispatch.
                          #   ★ 2026-08-12 부터 이 토큰이 사실상 필수다. 안전망 크론을 하루 3번
                          #     (KST 09/15/21)으로 낮췄기 때문에, 미설정이면 버튼이 큐에만 넣고
                          #     다음 크론 시각까지 최대 6시간(야간 12시간) 아무 일도 안 일어난다.
                          #     이전엔 */15 라 최대 15분이었다. 근거: docs/deviation-cron-cost.md
```

---

## 완료의 정의(DoD) & 합격기준
- **마일스톤 DoD:** 해당 마일스톤의 모든 체크박스 완료 + 합격기준 자가 점검 통과 + 커밋/PR 반영.
- **P0 합격:** 상위 10편 중 "낙점 가능(shortlisted+picked)" ≥3편인 날이 **7일 중 5일 이상.** 미달 시 가중치·1차 필터를 config로 조정.
- **P1 합격:** 낙점→승인까지 **사람 작업 ≤30분/편**, 발행 가능 초안의 **사실오류 0건**(자기검증 빨간 깃발이 오류를 실제로 잡는지 포함).

---

## 구현 전 확인 체크리스트 (M0 — 미확정이면 먼저 해소)
- [ ] **D1** OpenAlex 인증: 키 불필요·`mailto` polite pool로 확정(공식 문서 재확인).
- [ ] **D2** 수집 윈도우 & 1차 필터: 최근 3~7일 롤링 + buzz는 *가점*(필수조건 아님).
- [ ] **D3** buzz 매칭: 소셜 글 먼저 수집 → DOI/arXiv 추출 → 정규화 후 조인.
- [ ] **D4** P1 트리거: P0는 로컬 엔진 폴링(`drafts`/큐 행), P2에서 클라우드 승격.
- [ ] **D5** 타임존: `Asia/Seoul` 고정.
- [ ] **D6** ④ 학술중요성 보정: P0는 off, 데이터로 on/off 비교.
- [ ] **D7** ⑤ buzz 정규화식: config 상수(로그 스케일 권장).
- [ ] 차용 공개 스킬(scriptwriting/Screenwriter류) **라이선스·품질 직접 검증** 후 사용.

자세한 근거는 `docs/기획안_리뷰.md`, 실행 순서는 `docs/작업계획서.md` 참조.
