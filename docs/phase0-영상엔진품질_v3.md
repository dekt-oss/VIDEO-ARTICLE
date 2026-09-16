# Phase 0 탐색 결과 — 영상제작 엔진 품질 간극 해소 v3

- 지시서: `docs/작업지시서_영상엔진품질_v3.md` (§2 Phase 0)
- 실행일: 2026-08-02 / 대상 커밋: `912ef29`
- 실패 재현물: 코스피 리포트 explainer `0bceb278-d5fe-4af3-b489-29c6b5815793` (ko, 48.52s)
- 재현 스크립트: `scripts/repro_phase0_board.py`
- 화면 증거: `docs/evidence/phase0-v3/`

> 이 문서는 지시서 §2가 요구한 "탐색 결과를 PR 본문 + 본 문서 개정에 기록"의 기록물이다.
> **§0의 결론 3개(P0-A·P0-B·P0-C)는 지시서 §4·§5-4·§8-2의 처방을 바꾼다.** 지시서 §2 마지막 문장
> ("확정 결과가 처방과 다르면 처방을 고치고 freeze한다")에 따라 §9 개정안을 함께 싣는다.

---

## 0. 결론 (두괄식)

| # | 확정 사실 | 지시서에 미치는 영향 |
|---|---|---|
| **P0-A** | 리포트 **원문은 ARIA 안에 이미 있는데 우리 엔진이 그 경로를 쓰지 않는다.** `reports` 162건이 전부 `source='aria_signal'`(텔레그램 계열)이고 `summary` 평균 366자가 전부다. 반면 ARIA `search_research`/`get_research` 는 증권사 정식 리포트의 **PDF 추출 전문(`content_raw`)과 PDF 직링크**를 돌려준다 — `engine/aria/client.py` 에 그 두 도구가 구현돼 있지 않을 뿐이다 | §4 Source Pipeline 은 **새 크롤러 없이 성립 가능**하다. 대신 "무엇을 영상 소재로 삼을지"와 "전문을 저장할지"를 정해야 한다 → 결정 필요(§8-1) |
| **P0-B** | 코스피 실패작의 빈 화면은 **에셋 누락도 렌더 예외도 아니다.** 현 HEAD 로 같은 컷을 재현하면 내용이 그려진다(구버전 산출물). 그러나 현 HEAD 에도 **CORE 밴드 충전율 0.235**(명세 목표 0.70)이고 `layout_qa` 는 **fail 0 · warn 1** 로 통과시킨다 | §8-2 처방("예외 삼킴 수리")은 **오진**이다. 실제 계층은 **판정기**다 — 화면이 비어도 QA 가 PASS 를 준다. §9 Q1·Q2 가 주 수리 대상 |
| **P0-C** | 비용 원장이 **0행**이다(`generation_attempts` total=0). 리포트 렌더가 `directive_id=None` 으로 호출되고, `cost_ledger.record` 3곳이 전부 `if use_cache:` 안에 있어 `use_cache=False` 로 통째로 건너뛴다 | §0-1 #19 복원 항목이 **정확히 확인됨.** 일반론이 아니라 특정 라인 3곳 수리 |

부수 확정: 자기검증 오탐(§0-1 #18)은 **6/6 초안에서 100% 재현**되며, 플래그된 씬은 예외 없이 **첫 씬과 마지막 씬**이다. 다만 면제 키로 쓰려던 `evidence_role` 이 **초안 씬 스키마에 없다** — §5-4 처방을 고쳐야 한다.

---

## 1. §2-A/B — 초안 단계의 실제 입력과 원문 저장 형태

### 1-1. 입력 (전문 미주입 확정)
| 단계 | 함수 | 실제 입력 |
|---|---|---|
| Fact Sheet | `engine/report_factsheet.py:47 factsheet_user_prompt` | 종목/제목/증권사/목표가/투자의견 + **`요약:` 1줄** |
| 대본 | `engine/report_scriptgen.py:91 script_user_prompt` | Fact Sheet **만** |
| 지시서 | `engine/report_directive.py:132 report_directive_user_prompt` | 대본 + Fact Sheet + scenes |
| TS 트윈 | `supabase/functions/generate-report-draft/index.ts:404` | 동일하게 `요약:` 1줄 |

전문 주입은 **미배선이 아니라 배선할 원문이 없다.**

### 1-2. 원문 저장 형태 (§15-1 답)
- `engine/report_collect.py:86` 주석: "원문 전문은 저장하지 않는다 — summary 는 요약만".
- `supabase/migrations/0018_report_factory.sql`: `summary text -- 핵심요약 (원문 전문 아님)`, `report_url text -- 원문 링크 (본문은 여기 두고 안 옮김)`. 저작권 안전장치로 **의도된 설계**다.
- 실측(2026-08-02, `reports` 162행):

| 지표 | 값 |
|---|---:|
| 전체 리포트 | 162 |
| `report_url` 보유 | 137 (84.6%) |
| `summary` 평균 길이 | 366자 |
| `summary` 최대 길이 | 399자 (`REPORT_SUMMARY_MAX_CHARS`=1200 에 미달 — 원본 ARIA 메시지 자체가 짧다) |

- `report_url` 상위값: `https://t.me/shinhan_park`(12), `https://telegram.me/daishinstrategy`(3), `https://bbn.kiwoom.com/rfCC1574`(2), `https://naver.me/...`(1). **채널 링크가 다수**라 URL 을 따라가도 해당 리포트 본문에 도달하지 못한다.

**따라서 지시서 §4 의 `source_depth` 는 현재 저장된 162건 전부가 `summary_only` 다.**

### 1-3. 그러나 ARIA 에는 전문이 있다 (§15-1 의 진짜 답)
`engine/aria/client.py` 는 `list_signals` · `get_signal` · `broker_targets` · `list_briefings` 네 도구만 구현한다.
ARIA 가 제공하는 **`search_research` · `get_research` 는 호출조차 하지 않는다.** 실제로 불러본 결과:

```
get_research(4902)  # 하나증권 [LG전자] 강해진 이익 체력과 신사업 가속화
  source_url  = https://stock.pstatic.net/stock-research/company/57/20260731_company_25386000.pdf
  content_raw = PDF 추출 전문 — 본문 3개 섹션 + 분기별 실적 전망표(수정 전/후) + 추정 재무제표
```

ARIA `research_reports` 에는 두 계열이 섞여 있다:

| | 텔레그램 계열 (지금 쓰는 것) | 포털 리포트 계열 (안 쓰는 것) |
|---|---|---|
| 예 | id 4975 대신 시황 "코스피 +18.50%" | id 4902 하나증권 "[LG전자]…" |
| `report_title`·`report_date` | null | 있음 |
| `source_url` | `t.me/채널` | 네이버 리서치 PDF 직링크 |
| `content_raw` | 텔레그램 메시지 전문(짧음) | **PDF 추출 전문(본문+표)** |
| 인용·페이지·chunk | 불가 | **가능** |

`search_research(status='selected', limit=50)` 한 번에 포털 계열 기업/산업 리포트가 30건 이상 나온다.
**즉 §4 는 새 크롤러 없이 성립한다** — 필요한 것은 ARIA 클라이언트에 두 도구를 추가하고, 수집원을
어느 계열로 삼을지 정하는 것이다.

---

## 2. §2-D — 코스피 실패작 재현 (실패 계층 확정)

### 2-1. 배포된 산출물 실측
`ffmpeg` 로 48.52s / 1080x1920 / 30fps 확인. 2fps 프레임 추출 후 CORE 밴드(세로 25~72%) 엣지 점유율 측정 → 시각 증거 `docs/evidence/phase0-v3/kospi_48s_frames.png`.

| 구간 | 컷 | 화면 |
|---|---|---|
| 0~6.5s | 1 HOOK_BOARD | 정상(문장 페이드인) |
| 6.5~12s | 2 NUMBER_BOARD | 정상 — `7.3조원 → 7.6조원` **카운트업 동작** |
| 12~19s | 3 NUMBER_BOARD | **빈 패널** (숫자 없음) |
| 19~26s | 4 EVIDENCE_BOARD | 카드는 뜨나 본문 글자가 매우 작음 |
| 26~34s | 5 MECHANISM_BOARD | 정상 |
| 34~40s | 6 CONTEXT_BOARD | 실사 배경 — **자막 2줄이 겹쳐 렌더**(38s) |
| 40~48.5s | 7 WATCHPOINT_BOARD | **빈 패널** |

### 2-2. 현 HEAD 재현 (`scripts/repro_phase0_board.py`)
저장된 지시서 필드를 그대로 넣고 `board_render.render_board` 실행:

```
=== cut 2 (NUMBER_BOARD) === payload.number='7.6조원'  frames=180 core_fill=0.244
    layout_qa={"fail": [], "warn": ["core_underfilled:0.24"]}   frame_qa={"fail": [], "warn": []}
=== cut 3 (NUMBER_BOARD) === payload.number='27.48%'  frames=195 core_fill=0.235
    layout_qa={"fail": [], "warn": ["core_underfilled:0.24"]}   frame_qa={"fail": [], "warn": []}
=== cut 7 (WATCHPOINT_BOARD) === payload.title='Watch Point:…'  frames=240 core_fill=0.496
    layout_qa={"fail": [], "warn": []}                          frame_qa={"fail": [], "warn": []}
```

**컷 3·7 모두 현 HEAD 에서는 내용이 그려진다.** 배포된 mp4(2026-08-01 07:28)는 `877a025`(30fps 모션 렌더)·`de98e8f`(밴드 이중배정 수리) 이전 산출물이다. → 빈 패널의 직접 원인은 이미 수리됐고, **재발을 막는 판정기가 없다는 것이 남은 결함**이다.

### 2-3. 남아 있는 결함 (현 HEAD, 재현 가능)
1. **CORE 충전율 0.235** — 명세 §20-3 목표 0.70. 판정은 `warn` 뿐이라 화면의 76%가 비어도 렌더가 나간다. 운영자가 본 "빈 박스"의 정체가 이것이다.
2. **선언 bbox 와 실제 잉크의 불일치** — 컷 3 의 배치 목록은 겹침 0으로 보고한다:
   ```
   number  CORE  '27.48%'          box=(274,555)-(744,702)
   rule    CORE  ''                box=(274,718)-(744,725)
   text    CORE  '전기·전자 업종 상승률'  box=(330,740)-(688,795)
   ```
   그런데 실제 프레임에서는 170px 대형 숫자의 글리프가 아래로 흘러 라벨·구분선을 **덮는다**(`docs/evidence/phase0-v3/cut3_core_collision.png`). 즉 판정이 텍스트 박스 좌표만 보고 **그려진 픽셀을 보지 않는다.**
3. **자막 겹침(6번 컷, 38s)** — ASS 자막 2줄이 서로 겹쳐 렌더. 지시서 §9 Q2 의 대상.

**§8-2 처방 수정 근거:** `engine/report_render.py` 의 `except` 는 2곳뿐이고 둘 다 `log.exception` 후 잡을 `failed` 로 내린다 — **예외를 삼키지 않는다.** `engine/render.py:318` 은 보드 계약 위반(폰트·초과·중복)을 **일부러 re-raise** 하고 있어 이미 지시서가 원하는 자세다. 고칠 곳은 예외 처리가 아니라 **판정 기준**이다.

---

## 3. §2-C/E/F — 렌더 계약 배선 가능성

| 질문(§15) | 답 | 근거 |
|---|---|---|
| 3. board_render 반환 메타데이터 | **이미 충분하다.** `BoardResult{frame_paths, fps, placements[Placement{kind,box,text,band,stage,meta}], layout_qa, core_fill, frame_qa, chart_spec}` | `engine/board_render.py:56-70` |
| 4. 컷 directive ↔ 최종 프레임 연결 ID | **없다.** `engine/report_render.py` 에 `cut_no`/`cut_id` 문자열이 0건. 프레임 파일은 `cut_{idx}.png`(0-based enumerate)라 역산은 되지만 명시 ID 가 없다 | grep 0건 |
| 5. 비용 원장 기록 단위 | `generation_attempts` 행 = (directive_id, cut_no, asset_type, attempt_no). **리포트 라인은 0행** | `engine/cost.py:91`, DB count=0 |
| 7. 폰트·라이선스 | **확정됨.** `assets/fonts/` 에 Pretendard(OFL)·Anton(OFL) 동봉, 없으면 `visual_contract.load_font` 가 예외 | `assets/fonts/LICENSE-*.txt` |
| §2-E 자막 좌표 | `engine/subtitles.py` 가 `FOOTER_MARGIN_V`·overlay MarginV 로 하단 기준 배치, 보드는 `visual_contract` 밴드 좌표계 — **두 좌표계가 서로를 모른다**(Q2 충돌의 구조적 원인) | `engine/subtitles.py:105-137` |
| §2-G TS 트윈 | `supabase/functions/generate-report-draft` 존재. Fact Sheet·대본·자기검증·컴플라이언스 4단계를 미러 | 파일 확인 |

**호재:** manifest(§8-1)의 `expected_layers` 대조에 필요한 재료(`placements`)가 이미 반환된다. 새 자료구조를 만들 필요 없이 **선언과 대조**만 붙이면 된다.

---

## 4. §0-1 #18 — 자기검증 오탐 (실측)

`report_drafts` 최근 6건 전수:

| report_id | 씬 수 | all_grounded | 플래그된 씬 |
|---|---:|---|---|
| 00ad3c1b | 7 | false | **1, 7** |
| ae10ce83 | 6 | false | **1, 6** |
| 818be1d4 (코스피) | 7 | false | **1, 7** |
| 6f6d7010 | 7 | false | **1, 7** |
| 6d184110 | 7 | false | **1, 7** |
| 74f45bd3 | 6 | false | **1, 6** |

**6/6 모두 첫 씬과 마지막 씬**이 "근거 불충분"으로 찍혔다. 훅과 마무리는 원래 사실 주장이 아니므로 전형적 오탐이고, 빨간 깃발이 상시 켜져 신호로서 죽어 있다.

**§5-4 처방 수정 필요:** 지시서는 `evidence_role ∈ (hook, question, cta, bridge)` 로 면제하라고 하지만, 초안 씬 스키마에 그 키가 없다. 실제 키는 `scene, title, narration_ko/en, duration_sec, image_prompt(_ko), video_prompt(_ko), source_facts` 뿐이다. `evidence_role` 은 **지시서 컷**에만 있다. → 면제를 걸려면 `report_scriptgen` 출력 스키마에 역할 필드를 **추가**해야 한다(순서 기반 추정은 6컷/7컷이 섞여 있어 취약).

---

## 5. §0-1 #19 — 비용 원장 (실측)

- `engine/report_render.py:87` — `_render_cut_clips(..., directive_id=None, ...)`
- `engine/render.py:140` — `use_cache = bool(directive_id) and config.IMAGE_PROVIDER not in ("placeholder", "")`
- `cost_ledger.record` 호출 3곳(`engine/render.py:190, 244, 257`)이 **전부 `if use_cache:` 블록 안**
- 결과: `select count(*) from generation_attempts` → **0**

리포트 렌더는 유료 이미지·Veo 를 쓰고도 원장에 한 행도 남기지 않는다. `report_render_jobs.cost_estimate` 만 남는데(코스피 $0.039, MSFT $0.556) 컷·자산·재시도 단위 분해가 없다.

---

## 6. 교정용 표본 3편 (§2)

지시서가 요구한 3종을 현 DB 에서 확정했다. Phase 4 전후 비교 기준선으로 쓴다.

| 유형 | directive_id | 리포트 | 현재 상태 |
|---|---|---|---|
| 실적 리뷰 | `87063e6a-6485-4340-a876-611e195d04a5` | 키움 · MSFT FY4Q26 | rendered / **게이트 blocked(`evidence_board_missing`) 인데 승인·렌더됨** |
| 기업 업데이트 | `b47dbbef-437c-49b8-84fa-c30bb8dac2db` | 메리츠 · LG전자 × 엔비디아 | draft (승인 전) |
| 근거 빈약(시황) | `0bceb278-d5fe-4af3-b489-29c6b5815793` | 대신 · 코스피 급등 | rendered (본 문서의 실패 재현물) |

부수 발견: MSFT 건은 `approval_blocked=true` 인 채로 승인·렌더까지 갔다. `EXPLAINER_GATE_FORCE_ALLOWED` 기본값이 `True` 라 운영자 강제 승인이 가능하고 그 사실이 **서버 로그에만** 남는다. 지시서 §8-3("done = critical QA 전부 PASS")과 직접 충돌하므로 Phase 3 에서 함께 다룬다.

---

## 7. 지시서 §16 해석표에 비춘 진단

| 현상 | 지시서가 지목한 계층 | 실측 결과 |
|---|---|---|
| 숫자가 빈약 | Source/Evidence | **적중** — 366자 요약이 유일한 입력 |
| 특정 컷 빈 화면·정지 | Manifest/Renderer | **부분 적중** — 렌더러는 그렸고, **판정기**가 통과시켰다 |
| 비용 급증 | 전문 중복 주입·캐시 미사용 | **해당 없음** — 애초에 원장이 없어 급증 여부를 볼 수 없다 |

---

## 8. freeze 전 미해소 결정 (사용자 결정 필요)

> **결정됨(2026-08-02, 운영자): (가) + 런타임 주입.** 구현은 Phase 1 첫 단위로 들어갔다 —
> ARIA 클라이언트에 `search_research`·`get_research` 추가, `engine/report_source.py`(원문 해소·
> depth 판정·chunk), Fact Sheet 프롬프트 `<<FULL_SOURCE>>` 주입, 포털 리포트 수집
> (`report_collect.collect_research`), 회귀 가드 `tests/test_fulltext_injection.py`(20건).
> 아래 8-1 은 결정 근거 기록으로 남긴다.

### 8-1. 영상 소재를 무엇으로 삼을 것인가 — §4 전체가 여기에 달려 있다
§1-3 이 확인한 대로 전문은 ARIA 안에 이미 있다. 정할 것은 "새 크롤러를 만들까"가 아니라 **어느 계열을 소재로 삼고, 전문을 저장할 것인가**다. 지시서 §4-3 의 `summary_only` 차단을 지금 켜면 162편 전부가 멈춘다.

- **(가) 포털 리포트 계열을 소재로 추가** — `search_research(status='selected')` 로 정식 리포트를 수집원에 넣고 `get_research(id).content_raw` 를 Fact Sheet 추출 입력으로 쓴다. 지시서 §4·§5 가 요구한 인용·페이지·chunk 가 성립한다. 서브 결정: **전문을 `reports` 에 저장**(재현 가능, 0018 주석의 저작권 자세를 뒤집음) vs **런타임에만 주입**(저작권 자세 유지, ARIA 에서 사라지면 재현 불가).
- **(나) 텔레그램 계열 유지 + `raw_content` 전문만 제대로 사용** — 366자 절단을 없앤다. 지금보다 낫지만 텔레그램 메시지 자체가 요약이라 페이지·인용은 여전히 불가능하다.
- **(다) §4 를 이번 PR 범위에서 제외** — Phase 1 을 evidence 계약·게이트·story_plan(요약 입력 기준)으로 축소하고, Source Contract 는 별도 PR.

권고: **(가) + 런타임 주입.** 전문이 이미 상류 시스템 안에 있어 새 수집기가 필요 없고, 저장하지 않으면 저작권 자세를 건드리지 않는다.

### 8-2. §15-8 편당 비용·처리 시간 증가 허용 상한
지시서가 "freeze 전 필수"로 못박은 항목이며 미정이다. 현 실측 기준선: 렌더 비용 코스피 $0.039 / MSFT $0.556, 렌더 소요 5~6분. `EXPLAINER_COST_CAP_USD` 는 0.25(잡 단위).

### 8-3. §8-3 done 정의와 강제 승인의 충돌
`EXPLAINER_GATE_FORCE_ALLOWED=True` 를 유지할지. 유지하면 "done = critical QA 전부 PASS"가 우회 가능해진다.

---

## 9. 처방 개정안 (지시서 §2 마지막 문장에 따름)

| 지시서 항목 | 원안 | 개정안 | 근거 |
|---|---|---|---|
| §8-2 | "예외를 `continue` 로 삼키지 않는다(§2-D에서 확정한 지점 수리)" | **삭제.** 삼키는 지점이 없다. 대신 **판정 강화**: `core_fill < EXPLAINER_CORE_TARGET_FILL` 을 warn → **fail** 로 승격하고, 실패 시 요소 확대/배경 보강 후 재판정 | §2-2, §2-3 |
| §9 Q1 | "픽셀 stddev 는 보조 신호" | 유지하되 **선언 bbox 대조로는 부족**함을 명시. 대형 숫자 글리프가 선언 박스를 벗어난다 → **실제 잉크 픽셀 범위**를 재서 대조 | §2-3-2 |
| §9 Q2 | "렌더된 텍스트 bbox ↔ subtitle/footer/overlay safe zone 교차" | **범위 확대:** 보드 내부 요소끼리의 잉크 겹침도 대상. 두 좌표계(ASS MarginV ↔ 밴드)를 하나의 px 좌표계로 환산하는 단계를 선행 | §3, §2-3-3 |
| §5-4 | `evidence_role` 로 면제 | **선행 작업 추가:** `report_scriptgen` 출력 스키마에 씬 역할 필드 신설(없는 키로는 면제 불가) | §4 |
| §4 | Source Pipeline 전면 구현 | **§8-1 결정 전까지 보류.** 단 "원문이 없다"는 전제는 틀렸다 — ARIA `get_research` 가 전문을 준다. 결정 (가)면 선행 작업은 **`engine/aria/client.py` 에 `search_research`·`get_research` 추가**(새 크롤러 아님) | §1-3 |
| §12 소유권 | Codex 병렬 | 유지. 단 Phase 1 의 Codex 몫(evidence validator)은 §8-1 결정 후 착수 | — |

---

## 10. 재현 방법

```bash
python3 -m pip install pillow imageio-ffmpeg python-dotenv httpx tenacity
python3 scripts/repro_phase0_board.py          # 컷 2/3/7 보드 재현 + 배치 겹침 측정
```

배포 mp4 프레임 분석은 `report_render_jobs.output_url` 을 받아 `ffmpeg -vf fps=2` 로 추출한 뒤
CORE 밴드 엣지 점유율을 재는 방식이다(본문 §2-1).
