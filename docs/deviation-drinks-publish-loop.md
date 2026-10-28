# 주류 공장 순환 고리(D단계) — ③ 인스타 발행 · ④ 성과 · ⑤ 전략 · 2026-10-27

결재 문서: `docs/계획_주류순환_발행성과전략_2026-10-27.md`. 명세: `docs/주류공장_구조명세_v1_2026-10-21.md` §7·§8.4·§9.3~9.4·§11·§12·§13-D.
운영자 지시: "소재 수집과 인스타 카드뉴스 및 릴스 업로드 자동화 및 결과 수집 및 전략 수정으로 이어지는 순환 시스템 구축부터. 너무 영상에 집착 말고."

## 무엇이 생겼나

| 고리 | 저장(0055) | 일하는 쪽 | 화면 |
|---|---|---|---|
| 계정 | `drink_social_accounts` | `engine/drinks_publish.verify_accounts` | `/drinks/publish` |
| ③ 발행 | `drink_publication_requests`·`drink_publication_attempts` | `engine/drinks_publish.py`, 공급자 `engine/providers/instagram.py` | `/drinks/publish` |
| ④ 성과 | `drink_post_metric_snapshots` | `engine/drinks_metrics.py` | `/drinks/analytics` |
| ⑤ 전략 | `drink_strategy_versions`·`drink_strategy_proposals`, 순서 `drinks_strategy_rank` | `engine/drinks_strategy.py` | `/drinks/analytics` |

워크플로 `drinks-publish.yml` 은 **수동 실행만**(단계 선택: publish / metrics / strategy). 예약(cron)은 승인 뒤.

## 명세와 다르게 정한 것(근거)

1. **⑤ 전략은 명세에 없다** — 결재 문서에서 정했다. 비교 지표는 72시간 칸의 (저장+공유)÷도달 하나. 묶음은 주종·형식·소재
   갈래·게시 시간대. 표본 문턱(묶음 3편·전체 6편)과 한 번에 움직이는 폭(±0.2)·상한(±0.5)은 `drinks_publish_limits()` 한 곳.
   반영은 운영자 버튼으로만 → 새 전략 버전(옛 버전은 물러남, 가중치는 불변). 소재 점수 기준(rubric drinks-v1)은 **건드리지
   않는다** — 그건 "근거·제작 적합성"이고, 전략은 "다음에 무엇을 먼저 볼지" 순서다. 시간대 가중치는 발행안 작성 때 추천으로만 보인다.
2. **승인과 예약을 두 단계로 나눴다**(명세 §8.4 의 approved → scheduled). 승인은 화면이 보여 준 지문(파일 묶음·계정·외부 ID·형식·
   캡션·커버·예약시각)을 그대로 돌려줘야 통과한다. 예약은 계정 발행 스위치·검수 유효성·늦음을 다시 잰다.
3. **캡션은 운영자가 쓰고 워커가 게시 직전 코드로 검사**한다(`drinks_script_check.check_caption`) — 원문에 없는 숫자·양·권고면
   인스타에 아무것도 만들기 전에 paused. LLM 캡션 생성은 이번 범위가 아니다.
4. **숫자 추출 구멍 수정**(`drinks_script_check._NUM`): 앞 글자 검사가 `\w` 라 한자·한글 바로 뒤 숫자(`精米歩合50%`)를 못 읽었다.
   원문 숫자는 빠지고(근거 있는 숫자를 막음) 나레이션의 붙은 숫자는 검사를 빠져나갔다. 이제 영문·숫자만 본다. 기존 시험 전부 통과.
5. **릴스는 상태 기계만**: 영상 묶음(최종 영상 + 커버)을 reel 로 게시하는 경로는 있으나, 카드 → 슬라이드 릴스 변환은 다음 묶음.

## 정확히-한-번이 아닌 것(정직하게)

외부 게시와 DB 기록 사이는 한 트랜잭션이 아니다. 줄이는 장치: 살아 있는 요청 고유키 · 예약 점유 임대 · **게시 호출 단계를
호출 전에 기록** · 그 뒤 오류는 전부 unknown · unknown 은 다시 집지 않음 · 대조는 컨테이너 상태로만 정정.
가짜 공급자로 "게시됐는데 응답만 잃음"·"게시 안 됐는데 응답 잃음" 두 경우를 e2e 로 확인했다(인스타에 한 번만 올라감).

## 확인한 것 / 못 한 것

| 확인 | 결과 |
|---|---|
| Python 워커 한 바퀴 e2e(`tests/test_drinks_loop_e2e.py`, PGlite 다리) — 수집(가짜 사이트) → 근거 → 카드 PNG 렌더 → 검수 → 발행(가짜 인스타) → 24h/72h 스냅샷 → 표본 부족 제안 → 표본 충족 제안 → 반영 → 후보 순서 바뀜 | 통과 |
| 같은 e2e: 게시 후 응답 끊김 → unknown → 재게시 없음 → 대조로 published · 게시 전 끊김 → failed → 재시도 · 2시간 늦음 → paused · 근거 없는 캡션 → paused | 통과 |
| DB 규칙(PGlite, `web/lib/drinks/publish.db.test.ts` 7개) — 계정 접두어·토큰 원문 거부·외부 ID 불변·불일치, 지문 승인, 작성 중에만 수정, 중복, 스위치·철회·늦음, 게시 호출 뒤 failed 금지, 끊긴 임대 → unknown, 성과 칸·받은 지표만, 전략 상한·기준 변경 | 통과 |
| 공급자 단위(`tests/test_drinks_publish_units.py`) — 토큰은 헤더로만·오류 문장에 비밀 없음·실제 공급자 기본 꺼짐 | 통과 |
| 실제 Meta Graph API(읽기만, 2026-10-28) | 계정 `sooljjerigo`(ID 17841473765861006, 크리에이터) **Instagram 로그인** 토큰으로 계정 대조·게시 한도(100/일)·게시물 성과(reach·saved·shares·likes·comments·total_interactions) 조회 성공. **실측으로 결함 1건 수정**: 게시물 owner 가 앱 전용 ID 로 와서 매 게시가 unknown 이 될 뻔했다 → /me 로 계정 ID 에 이어 줌. 실제 게시·릴스 지표(`ig_reels_avg_watch_time`)는 아직 미검증 |
| 운영 DB 0055 적용·운영 배포·실게시 | 안 함(각각 승인 필요) |

## 운영 순서(승인 뒤)

1. 0050~0055 를 순서대로 운영 DB 에 적용(0050~0054 도 아직 미적용).
2. 계정 결정(Instagram 로그인 / Facebook 로그인) → Meta 앱·토큰 발급 → 토큰을 GitHub 비밀에 두고 그 이름을 `/drinks/publish` 계정 등록에 적는다.
3. ~~워크플로에 그 비밀과 `DRINKS_IG_LIVE=1` 을 넣는 변경(별도 승인)~~ → **2026-10-28 넣음**(운영자 지시). 수동 실행만, 토큰 비밀 `SOOLJJERIGO_IG_TOKEN`. 계정 등록은 연결 방식 **Instagram 로그인**, 비밀 이름 `SOOLJJERIGO_IG_TOKEN`, 외부 ID `17841473765861006`. 첫 게시는 별도 승인.
4. 성과·전략 크론(하루 1번) 켜기(별도 승인).

## 되돌리기

0055 의 표 6개와 새 `drinks_*` 함수를 drop. 화면 두 개(`/drinks/publish`, `/drinks/analytics`)와 메뉴 한 묶음을 지운다.
`_NUM` 수정은 독립적으로 되돌릴 수 있다(되돌리면 위 4의 구멍이 돌아온다).
