# 3단계(카드뉴스)·4단계(밈형) — 돈 쓰기 직전까지 준비한 기록 (2026-11-02~03)

총괄 계획(`docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md`) §3(결정 1)·§4-2·§4-3·§6 3·4단계·§7 의 **0원 부분**이다.
기획 v2 §4·§5·§6-1·§6-5·§6-7·§7, Apify 검토 §8 을 따랐다. 운영자 지시 "묵묵하게 끝까지" — 막힌 자리는 아래 "제가 정한 것"에 적고 진행했다.
**이번에 하지 않은 것:** 유료·Apify·모델 실제 호출, 공개 게시, 운영 DB 쓰기, 푸시·PR, 토큰 출력, 크론. 0070 은 파일만 있다.

## 만든 것

| 항목 | 어디 | 무엇 |
|---|---|---|
| 카드 대본 실제 생성 준비 | `scripts/card_plan_run.py` | 운영 Supabase 를 **읽기만** 해 승인된 근거가 있는 소재 1건을 가져와 워커 경로(`drinks_develop.process_job → drinks_card_plan.run_card_plan`)를 가짜 응답으로 끝까지 돌린다. 저장 호출은 가짜 RPC 가 받는다(DB 쓰기 0). `--yes --approve "결재 문장"` 이면 실제 모델 1회, 상한 $0.10(`DRINKS_CARD_PLAN_RUN_CAP_USD`) — 예상액×2회가 상한을 넘으면 부르지 않는다. 산출물 `docs/preview-2026-11-02/card-plan/` |
| 질문 지도 × 규칙 검사기 | 같은 스크립트 | 네이버 질문 지도 8유형 × 3주종(48문항)마다 운영자 규칙 넷(쉬운 구어체·없는 양/처방 금지·왜가 중심·규칙은 곁가지)을 하나씩 어긴 가짜 답을 넣어 `check_card_plan` 이 넷 다 잡는지, 지키는 답은 통과하는지 표로 남긴다 → `question_map_check.md`. **결과: 48문항 전부 잡고 통과.** |
| 음원 시험 게시 | `scripts/card_reel_trial_publish.py` | 음원 붙은 카드 릴스 발행 요청을 찾아 내용·음원·계정·게시 성격을 보여 준다. `--yes` 로만 1건 게시(`drinks_publish.run(max_items=1)`). 공개 게시 경고를 항상 띄우고, 게시 뒤 앱에서 확인할 10항목 체크리스트를 찍는다. 게시 워커 코드는 건드리지 않았다 |
| Apify 밈 틀 정밀화 | `engine/drinks_meme_refine.py`, `.github/workflows/drinks-apify.yml` | [쓰자] 카드의 릴스(≤3, 공식 API 가 고른 주소만)를 Apify `instagram-reel-scraper` 로 받아(`maxTotalChargeUsd` 상한) 컷 길이·비트 수는 ffmpeg 장면 감지로, 반전 시점·첫 1.5초·동기화·구조·표지 글자는 영상 분석 모델(flash, 60초·20MB 이하)에 묻고 **허용 어휘로 걸러** 카드 칸(근거 `video`)에 옮긴다. 남의 영상은 임시 폴더에서 한 편 잴 때마다 지우고 시작 때 24시간 넘은 폴더를 청소한다. `--yes` 없이는 실제 호출 0 |
| 월 상한·요청 표 | `supabase/migrations/0070_drinks_apify_refine.sql` | `drink_apify_requests`(클릭 1회 = 요청 1건), `drinks_apify_request`(월 $3 넘으면 `apify_budget_exhausted`), `drinks_ig_card_use_refine`([쓰자] + 요청을 한 트랜잭션으로, 정밀 틀이면 0원), 워커 함수(claim·finish·reap), `drinks_ig_create_manual_card`(손으로 만드는 정밀 틀 카드). 영상·음성 주소가 섞인 결과는 표 제약이 저장을 거부한다 |
| 화면 | `/drinks/memes` | [쓰자] 옆에 "이번 상한 $0.02 · 이달 누적 $x / $3"(기획 v2 §6-1 "실행 전에 말한다"). T4 줄이 이달 요청 수·누적액. 카드 아래 정밀화 결과 한 줄. [밈 제작] 위에 **"원본 릴스를 보고 정밀 틀 카드 직접 만들기"** 폼 — 정상 관측일 전에도 제작으로 간다. 0070 미적용이면 옛 동작(결정만) |
| 리허설 | `scripts/meme_refine_rehearsal.py` | 가짜 Apify(릴스 2편 + 연령 제한 1편) + 가짜 분석 → 칸 채움 → 카드가 정밀 틀 → **리허설(`meme_rehearsal.py`)과 같은 함수 `drinks_meme.produce`** 로 제작(게시 대기)까지. 11개 검사 전부 합격. 산출물 `docs/preview-2026-11-02/meme-refine/` |
| 시험 | `tests/test_drinks_meme_refine.py`(18) · `tests/test_drinks_stage34_scripts.py`(7) · `web/lib/drinks/apify.test.ts`(6) · `web/lib/drinks/apify.db.test.ts`(7, PGlite 0050~0070) | 돈·주소·운영자 칸·같은 제작 경로·--yes 안전장치 |

## 드러난 결함 하나(고침)

`drinks_script_check._FORMAL` 이 `습니다|입니다|됩니다|ㅂ니다` 만 봐서 **"못합니다·합니다·갑니다"가 문어체 검사를 통과했고** `ㅂ니다` 는 낱자라 어떤 글에도 안 걸렸다. 질문 지도 검사기(48문항)가 첫 실행에서 48건 전부 "놓침"으로 드러냈다. `(?<!아)니다` 로 바꿨다("아니다"는 뺀다). 두 공장의 대본 검사·캡션 검사가 같은 상수를 쓰므로 함께 넓어졋다 — 기존 시험 128건 통과.

## 기획이 정하지 않아 제가 정한 것

| 정한 것 | 이유 | 바꾸려면 |
|---|---|---|
| [쓰자] 가 **결정 + 요청**이고, 요청이 막혀도(월 상한·릴스 없음) 결정은 남는다 | 운영자가 쓰겠다는 뜻은 돈과 무관하다. 막힌 이유를 돌려주고 칸을 직접 넣는 길을 남겼다 | `drinks_ig_card_use_refine` |
| 이미 정밀 틀인 카드는 Apify 를 부르지 않는다 | 돈을 쓸 이유가 없다 | 〃 |
| 월 상한 계산에서 **끝나지 않은 요청은 상한으로** 센다. 워커가 사라진 실행도 상한으로 적는다 | 얼마가 될지 모르면 많게 잡아 $3 을 지킨다(결재 가잡기와 같은 원칙) | `drinks_apify_month_spent`, `drinks_apify_reap` |
| 분석 예상액 $0.003/편 → 릴스 3편 = Apify $0.0088 + 분석 $0.009 = $0.0178 ≤ $0.02 | 기획 v2 의 1회 상한 $0.02 안에 3편이 들어가야 한다. ★ 실측 전 계획값 — 정산은 실제 토큰 | `DRINKS_APIFY_ANALYSIS_EST_USD` |
| 컷 길이·비트 수는 **ffmpeg** 가 재고(확신 high), 모델 답은 걸러서(확신 low) | 결정적·0원. 모델에는 영상을 봐야 아는 것만 묻는다(§6-5 근거 없는 필드 0%) | `measure_video`, `fields_from_analysis` |
| 릴스 여럿이면 분석된 것 중 **재생 수 최대** 1편의 칸만 카드로 | 카드 칸은 하나다. 나머지는 `analysis.per_video` 에 남는다 | `pick_fields` |
| 모델이 `music_sync=required` 라 하면 칸 값을 "박자에 맞춰야 함(필수)" 로 적는다 | 밈 엔진의 박자 맞춤 판정 낱말(`DRINKS_MEME_SYNC_REQUIRED_PATTERN`)에 걸리게 — 자동 게시 차단이 그대로 산다 | 〃 |
| T4 는 0063 `drink_ig_trend_runs` 에 적지 않고 0070 표가 기록이다 | 0063 함수가 t4 를 거부한다(그 결정 유지). 정상 관측일 계산과 무관 | — |
| [이걸로](설명형 형식 참고, A)는 **상한·칸만** 두고 화면 동작은 안 만들었다 | 이번 목표가 B(밈 틀)다. A 는 설명형 2단계 때 같은 표로 잇는다 | `drinks_apify_request(kind='explainer_reference')` |
| 손으로 만드는 카드는 `merge_key='manual:<uuid>'`, 결정 `use`, 종류 `structure_hook` | 0063 카드 만들기가 정상 관측일을 요구해 그 전에는 제작으로 갈 카드가 하나도 없었다. 기획 v2 §6-5 두 번째 길(운영자 입력)을 카드 생성까지 넓혔다 | `drinks_ig_create_manual_card` |
| 음원 시험 게시는 "지금 워커가 가져갈 요청 = 이 1건"일 때만 `--yes` 가 돈다 | 점유 함수가 예약 순서로 가져가서, 게시 워커를 고치지 않고 1건만 올리려면 이 조건이 필요하다 | `first_claimable` |
| 카드 대본 실제 호출은 **DB 에 저장하지 않는다**(파일만) | 운영 저장은 [이걸로]→워커 경로 하나로 둔다. 이 스크립트는 "실제 모델이 쓴 대본을 한 번 보는" 용도다 | — |
| 질문 지도의 "뜻 단위 자막" 은 알림(`line_long`)이라 검사기 표에서는 세지 않았다 | 차단이 아니고, 줄 끊기는 렌더가 `meaning_lines` 로 다시 본다 | — |

## 미검증

| 무엇 | 왜 못 봤나 | 틀리면 |
|---|---|---|
| **실제 Apify 응답 칸 이름**(`videoUrl`·`videoDuration`·`musicInfo.audio_id`·`inputUrl`·`x-apify-run-id` 헤더·`usageTotalUsd`) | 검토 §1 실측 기록을 따라 적었다. 이번엔 호출 0 | `result_rows` 가 전부 failed 로 보고 돈만 나간다 — 첫 `--yes` 1건($0.02 상한) 뒤 고친다 |
| Gemini 영상 inline_data 호출·`mediaResolution` 칸·가격 | 호출 0. 이미지 경로(providers/image)의 모양을 따랐다 | `analysis_unavailable` 로 멈추고 ffmpeg 측정만 남는다(카드는 정밀 틀이 된다 — twist_at 은 비어서 안 된다 → 운영자가 넣는다) |
| ffmpeg 장면 감지 문턱 0.30 이 실제 릴스에서 컷을 맞게 세는가 | 가짜 영상(색이 다른 단색)에서만 봤다 | 비트 수가 어긋난다 — 운영자가 칸을 덮어 쓴다(운영자 입력은 코드가 덮지 않는다) |
| 0070 운영 적용 | 결재 대상. PGlite 로만 | 화면이 "0070 미적용"이라 말하고 [쓰자] 는 결정만 기록 |
| `drinks-apify.yml` 실제 실행 · `APIFY_TOKEN` GitHub 시크릿 | 머지 전·운영자 몫 | 워커가 `token_missing` 으로 실패, 요청은 상한으로 적혀 닫힌다 |
| 실제 모델이 쓴 카드 대본 품질 | `--yes` 는 운영자 결재 뒤 | — |
| 음원 붙은 게시가 실제로 되는가(토큰 종류·`audio_configuration`) | 운영에 0065 가 없어 후보 0건. 공개 게시라 결재 대상 | `audio_failed` 로 멈춘다(음원 없이 올리지 않는다) |
| 화면을 브라우저로 열어 보기 | 0063·0066·0070 이 운영에 없어 볼 대상이 없다. tsc·lint·node 시험만 | — |

## 운영자가 할 것(순서)

1. `gh secret set APIFY_TOKEN` (값은 `.env` 의 것. 채팅에 붙이지 않는다). `GEMINI_API_KEY` 는 이미 있다.
2. 0063 → 0064 → 0065 → 0066 → 0067 → **0070** 운영 적용(결재).
3. 밈 보드에서 [쓰자] → 요청 1건 → `drinks-apify` 실행 → 카드 칸 확인(약 $0.02). 또는 `DRINKS_APIFY_*` 환경에서 `python -m engine.drinks_meme_refine --yes --max 1`.
4. 카드 대본 실제 1회: `python -m scripts.card_plan_run --yes --approve "<결재 문장>"` (≤ $0.10, DB 저장 없음) → 대본을 눈으로 본다.
5. 음원 시험 게시(공개, 별도 결재): 발행 화면에서 카드 릴스 발행안 + 음원 → 승인·예약 → `DRINKS_IG_LIVE=1 python -m scripts.card_reel_trial_publish --yes --request <id>` → 체크리스트를 이 문서 아래에 적는다.

## 음원 시험 게시 결과

(아직 없음)

## 되돌리기

- 화면: `MemeBoardControls.CardDecisionButtons` 의 `use()` 를 `ig_card_decide` 한 줄로, `ManualCardForm` 과 `page.tsx` 의 Apify 줄·`loadApifyBoard` 를 뺀다. `actions.ts` 의 두 줄, `route.ts` 의 `drinks-apify.yml` 블록, 가드 시험 목록 한 줄.
- 워커: `.github/workflows/drinks-apify.yml` 삭제. 큐의 요청은 남고 돈은 나가지 않는다.
- 표: 0070 머리말의 되돌리기 문장.
- 검사기: `_FORMAL` 을 옛 값으로 되돌리면 "못합니다" 가 다시 통과한다 — 권하지 않는다.
