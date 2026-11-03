# 5단계 — 게시 연결·게시 크론·성과 루프 (2026-11-02)

총괄 계획 `docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md` §5·§6 **5단계**, 기획 v2 `docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md` §3-4·§7,
결재 문서 `docs/계획_주류순환_발행성과전략_2026-10-27.md`. 앞 단계: `deviation-drinks-publish-loop.md`(0055), `deviation-drinks-meme-engine.md`(0066),
`deviation-drinks-explainer-queue.md`(0067), `deviation-drinks-card-reels.md`(0065).

**이 기능은 아직 운영에서 돌지 않는다.** 마이그레이션 0068 은 파일만 있고, 크론은 적혀 있지만 꺼져 있다. 운영자 지시("묵묵하게 끝까지")로 기획이 비워 둔 자리는
아래 "기획이 정하지 않아 제가 정한 것"에 근거를 적고 진행했다. 합격이라고 적힌 것은 전부 **가짜 공급자로 "경로가 끝까지 돈다"**이고, 실제 인스타 게시는 0건이다.

## 한 줄

밈형(`publish_waiting`)과 설명형(`ready_to_publish`)이 기존 게시 요청 표(0055)와 발행 워커에 이어졌고, 발행 워크플로에 예약 실행이 **기본 꺼짐**으로 들어갔으며,
성과·전략이 형식(카드뉴스·설명형·밈형)별로 묶인다. 가짜 공급자로 세 형식 한 편씩이 게시 요청 → 게시 → 성과 24h·72h → 전략 제안까지 돌았다(0원).

## 있는 것

| 무엇 | 어디 | 하는 일 |
|---|---|---|
| 표·함수 | `supabase/migrations/0068_drinks_stage5_publish_loop.sql` | 게시 요청에 `content_format`·`meme_draft_id`, 밈 발행안 함수, AI 표기 규칙, 전략 차원 `format`, 계정 고유키에 연결 방식. **파일만, 운영 미적용** |
| 워커 | `engine/drinks_publish.py::format_gate` | 밈 요청은 `drinks_meme.assert_auto_publishable` 을, 설명형·산 장면 밈은 'AI 생성 영상' 한 줄을 게시 호출 전에 다시 잰다 |
| 전략 | `engine/drinks_strategy.py` | 묶음에 콘텐츠 형식(card·explainer·meme) 추가. 성과 수집(`drinks_metrics.py`)은 형식을 로그·결과에 싣는다 |
| 크론 | `.github/workflows/drinks-publish.yml` | 게시 KST 07:00~23:30 매 30분 · 성과 매일 08:15 · 전략 월요일 08:45. 저장소 변수 `DRINKS_PUBLISH_CRON_ENABLED=1` 일 때만 일한다 |
| 화면 | `/drinks/publish` "게시 대기 밈" 칸, 형식 표시 · `/drinks/analytics` 형식별 편수·전략 묶음 | 밈 발행안 만들기(`create_meme_publication`), 설명형 AI 표기 안내 |
| 리허설 | `scripts/publish_loop_rehearsal.py` | 밈 1·설명형 1·카드 1 → 발행안 → 가짜 게시 → 성과 → 전략. 0원, 공개 게시 0, 소켓·공급자 줄 걸림 0 |
| 시험 | `tests/test_drinks_stage5_publish_loop.py`, `web/lib/drinks/publishLoop.db.test.ts` | 순수·DB·리허설. 워크플로 시험(`test_drinks_publish_units.py`)은 "크론 기본 꺼짐"으로 바뀌었다 |

## 규칙을 어디서 지키나

- **박자 맞춤 밈은 자동 게시되지 않는다 — 네 겹.** ① 0066 표 제약(`publish_waiting` 은 `sync_free` 만) ② 발행안 작성 `drinks_create_meme_publication` 이 `manual_audio` 를 거부
  ③ 게시 직전 재확인 `drinks_pub_block('meme_not_publishable')` ④ 워커 `format_gate` → `assert_auto_publishable`(0066 이 요구한 시험 `test_publish_worker_is_not_bridged_without_the_gate` 가 감시).
- **밈 발행안의 승인 지문에 제작안의 승인 지문이 들어간다.** 예약 뒤 제작안을 초안으로 되돌리면 지문이 달라져 `digest_changed` 로 멈춘다(DB 시험).
- **설명형 캡션 'AI 생성 영상'(기획 v2 §3-4)**: 작성(`drinks_create_publication`)·수정·승인 요청(가드)·게시 직전(`drinks_pub_block`)·워커 넷에서 잰다. 산 장면을 쓴 밈은 0066 규칙(`AI 생성`)을 캡션까지 이어 간다.
- **밈은 제작안의 캡션을 기본으로 쓴다**(사람이 승인한 글). 바꿔 적으면 그 캡션이 쓰이지만 숫자·양·권고는 0055 와 같은 코드 검사로 막힌다(농담 밈은 근거가 없어 숫자가 있으면 막힌다).
- **발행 꺼진 계정은 건드리지 않는다.** 0055 그대로 — `drinks_pub_block('publish_disabled')` 가 paused 로 보낸다. 크론은 "예약 시각이 된 요청"만 DB 에서 받는다.
- **옛 행의 승인 지문은 글자 하나까지 같다.** `meme_draft_id` 가 없으면 지문 식이 0065 와 같다(DB 시험이 0065 식을 그대로 적어 대조).
- **크론 스위치는 잡 단계 `if`** 다. 변수가 없으면 러너도 뜨지 않고 토큰도 읽지 않는다. 수동 실행은 변수와 무관.

## 기획이 정하지 않아 제가 정한 것

| 정한 것 | 이유 | 바꾸려면 |
|---|---|---|
| 밈은 게시 요청 표의 세 칸(제작안·검수·묶음)을 **비우고** `meme_draft_id` 로 잇는다 | 0066 머리말의 두 길 중 "묶음을 새로 만든다"는 밈마다 가짜 제작안·검수 행을 만들어야 해서 표의 뜻이 흐려진다. 표 제약 `drink_pub_source_ck` 가 둘 중 하나만 허용한다 | 0068 머리말 되돌리기 |
| 밈 제작안에 상태 `published` 하나를 더했다 | 게시된 밈이 다시 "게시 대기"로 보이면 두 번 올라간다. 되돌리기·버리기도 막힌다 | `drink_meme_drafts_status_check` |
| 게시 크론은 KST 07:00~23:30 **매 30분** | 총괄계획 §5 는 "예약 시각"만 적었다. 0055 가 2시간 넘게 늦으면 게시하지 않으므로 30분 간격이면 늦어도 30분 안에 집는다. 밤 23:30~07:00 은 전략 시간대(0055 `drinks_time_slot`)의 '밤' 대부분이라 뺐다 — 밤 게시가 필요하면 크론을 넓힌다. 빈 실행 1회 ≈ 1분, 하루 34회 ≈ 월 17시간(무료 2,000분 안) | `config.DRINKS_PUBLISH_CRON_PUBLISH` + yml (시험이 대조) |
| 성과 KST 08:15, 전략 월요일 08:45 | §5 "매일 성과 / 주 1회 제안". 수집 06:30·트렌드 07:30 뒤, 게시 크론(정각·30분)과 겹치지 않게 15·45분 | 같은 자리 |
| 어느 단계를 돌릴지는 크론 문자열로 정한다(`github.event.schedule`) | 워크플로 하나에 단계 셋. 파일을 셋으로 나누면 토큰 줄이 세 벌이 된다 | yml `STEP` |
| 전략 묶음 이름은 `format`(card·explainer·meme), 기존 `post_type`(carousel·reel)은 그대로 둔다 | 카드 릴스와 설명형 릴스가 같은 `reel` 이라 형식 비교가 안 됐다. 둘을 합치면 옛 가중치가 깨진다 | `DIMENSIONS` + 0068 검증 목록 |
| 전략 가점은 소재의 **형식 의도**(`drink_topic_picks.format_intent`)로 받는다 | 발견 후보에는 형식이 없다. 의도가 없는 옛 소재는 가점 0 | `drinks_strategy_rank` |
| 밈 카드에서 온 게시물은 주종·갈래·질문 유형 묶음에서 빠진다 | 소재가 없다(카드만 있다). 0 으로 치지 않고 그 묶음에서만 뺀다 | — |
| 같은 인스타 계정을 **Facebook 로그인 연결로 한 번 더** 등록할 수 있다(고유키에 연결 방식 추가) | 음원 릴스는 Facebook 로그인 연결로만 올라가는데(0065) 운영 계정은 Instagram 로그인이다. 계정 행의 연결 방식은 불변(0055)이라 둘째 행이 필요하다. 토큰 비밀 이름이 다르다 | 0068 머리말 4 |
| 밈 발행안의 음원: 제작안이 `ig_audio` 로 정했으면 그 음원만, 아니면 음원을 따로 안 받는다 | 영상에 분위기 음원이 이미 들어 있다. 다른 음원을 덧붙이면 소리가 겹친다 | `drinks_create_meme_publication` |

## 리허설 결과 (2026-11-02, 0원)

`python -m scripts.publish_loop_rehearsal` — 16개 점검 전부 통과. 가짜 인스타 게시물 3개(캐러셀 1 + 릴스 2, 파일은 `file://` 임시 주소), 성과 24h·72h 칸 형식별 3행,
전략 제안 "표본 부족(3편 < 6편)" + 형식 묶음 {card, explainer, meme} 각 1편, 밈 제작안 `published`, 박자 맞춤 밈 `manual_audio` + 발행안 거부, AI 표기 없는 설명형 발행안 거부,
소켓·실제 공급자 줄 걸림 0회. 설명형은 가짜 클립 공급자(`FakeAdapter`) 11회 호출로 샀다(가짜 금액). 산출물 `docs/preview-<날짜>/publish-loop/report.json`(gitignore).

## 미검증 · 아직 안 되는 것

| 무엇 | 왜 못 봤나 | 틀리면 |
|---|---|---|
| 0068 운영 적용 | 결재 대상. PGlite 로만 돌렸다 | 화면이 옛 모양(밈 칸 없음)이고 밈은 게시 대기에서 끝난다 |
| 크론 실제 실행(변수 켠 상태) | 변수를 켜는 것이 결재다. `github.event.schedule` 로 단계를 고르는 식은 문서 기준이고 실측하지 않았다 | 성과·전략 크론이 publish 로 돌 수 있다(게시는 DB 가 예약된 것만 주므로 추가 게시는 없다). 실행 로그의 STEP 으로 확인 |
| Facebook 로그인 둘째 계정 행으로 실제 게시·음원 부착 | 운영 DB 행 추가·시크릿 변경은 하지 않았다(아래 SQL 만 준비). Graph API 음원 호출은 0065 때부터 미검증 | `audio_connection_unsupported`·`credential_missing` 으로 paused |
| 설명형 '게시 대기'를 실제 큐로 만든 편 | 리허설은 가짜 클립이다. 실제 편은 2단계(S3) 뒤에 생긴다 | — |
| 밈 `ig_audio`(게시 때 음원 붙이기) 경로 | 제작안이 그 방식으로 승인된 사례가 없다. 작성 함수의 규칙만 DB 시험으로 봤다 | `audio_missing`·`audio_mismatch` 로 paused |
| 화면을 브라우저로 열어 보기 | 0068 이 운영에 없어 볼 데이터가 없다. tsc·lint·DB 시험만 | 적용 뒤 직접 본다 |
| 크론 비용 실측 | 추정(빈 실행 ≈ 1분). `docs/deviation-cron-cost.md` 의 사고처럼 늘면 간격을 넓힌다 | 월 분 사용량에서 보인다 |

## 켜려면 (운영자 결재 대상 — 순서대로)

1. **0068 운영 적용**(0065·0066·0067 뒤). 적용 뒤 확인 SQL 은 파일 끝에 있다.
2. **main 머지** — 그 전에는 워크플로의 크론·FB 토큰 줄이 없다.
3. **Facebook 로그인 둘째 계정 행**(음원 릴스용). GitHub 비밀 `SOOLJJERIGO_FB_TOKEN` 은 이미 있다(2026-11-02 실측: 유효, `instagram_content_publish`, 음원 재조회 200). 운영 DB 에서 한 줄:
   ```sql
   select drinks_register_account('{"external_account_id":"17841473765861006","display_name":"술째리고(Facebook 로그인·음원 릴스)","account_type":"creator","connection":"facebook_login","credential_ref":"SOOLJJERIGO_FB_TOKEN","capabilities":{"post_types":["reel"]}}'::jsonb);
   ```
   그다음 발행 워크플로를 수동으로 한 번 돌리면 계정 대조가 `active` 로 바뀌고, 화면에서 [발행 켜기]. Instagram 로그인 행은 그대로 두고 캐러셀에 쓴다.
4. **크론 켜기**: GitHub → Settings → Secrets and variables → Actions → Variables → `DRINKS_PUBLISH_CRON_ENABLED` = `1`. 끄기는 변수를 지우거나 `0`.
5. 첫 예약 게시는 비공개 시험 계정이 아니라 **공개 게시**다 — 기획 v2 §10 대로 따로 결재.

## 되돌리기

- 크론 끄기: 변수 삭제(코드 변경 없음). 크론 줄 자체를 빼려면 yml 의 `schedule:` 셋과 `if:`·`STEP` 을 지우고 `test_live_publish_workflow_cron_is_off_by_default_and_reads_token_from_secret` 를 옛 모양으로.
- 화면: `publish/page.tsx` 의 "게시 대기 밈" 블록과 `CreateMemePublication`, `actions.ts` 의 `create_meme_publication` 한 줄.
- 워커: `drinks_publish.py` 의 `format_gate` 호출 두 줄. 전략: `DIMENSIONS` 에서 `format` 제거.
- 표·함수: 0068 머리말의 되돌리기 1~4.
