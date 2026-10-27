# 핸드오프 — 주류 공장 순환 시스템(수집 → 카드뉴스·릴스 → 인스타 발행 → 성과 → 전략 수정) · 2026-10-27

## 운영자 지시(원문)

> "일단 영상 만드는 건 둘째치고 소재 수집과 인스타 카드뉴스 및 릴스 업로드 자동화 및 결과 수집 및 전략 수정으로
> 이어지는 순환 시스템 구축부터 합시다. 너무 영상에 집착 말고."

**목표:** 한 바퀴가 사람 손을 최소로 돈다. 사람이 하는 일은 셋뿐이다 — 소재·게시 **승인**, 돈 **결재**, 전략 변경 **확인**.

```
① 소재 수집·선정 → ② 카드뉴스(주력)·릴스(간단형) 제작 → ③ 인스타 예약 발행
        ↑                                                         ↓
⑤ 전략 수정(다음 편성 가중치·주제·형식·시간대) ← ④ 성과 수집(24h/72h/7d)
```

## 우선순위(중요)

1. **카드뉴스가 주력이다.** 릴스는 지금 있는 **무료 경로**로만 만든다 — 카드 페이지를 넘기는 슬라이드 릴스, 또는
   기존 로컬 렌더(대체 이미지 + 무료 TTS + ffmpeg). **유료 그림·영상 품질 개선(위스키 시범)은 멈춘다.**
2. 순환의 **빈 고리부터** 채운다: 지금 없는 것은 ③ 발행, ④ 성과, ⑤ 전략 수정이다. ①②는 대부분 있다.
3. 각 단계는 끝까지 한 번 돌게 먼저 만들고, 그다음 다듬는다(과한 검증·차단 금지 — 메모리 "먼저 완성").

## 지금 있는 것(코드는 쌓인 PR 위에 있다 — 아직 어디에도 머지·적용 안 됨)

PR 이 **겹겹이 쌓여 있다**: #121(A, `claude/drinks-factory-phase-a-9287b8`) → #122(B, `claude/drinks-factory-phase-b`)
→ #123(B 보완 + C, `claude/drinks-factory-phase-c`) → #124(유료 0단계, `claude/drinks-paid-pilot`). 전부 draft.
**새 작업은 `claude/drinks-paid-pilot`(최신 꼭대기, e978a35)에서 브랜치를 따서** 시작한다.
마이그레이션 0050~0054 는 **운영 DB 에 미적용**이다(로컬 시험 DB 에서만 돌렸다).

| 고리 | 있는 것 | 문서 |
|---|---|---|
| ① 수집 | 수집원 등록부·실행 기록·안전 요청기(`engine/drinks_fetch.py`·`drinks_collect.py`·`drinks_parse.py`) | `docs/deviation-drinks-phase-b.md` |
| ① 발견 | Stack Exchange(연결됨), 유튜브·네이버(키 필요, 네이버는 술째리고 API HUB 키로 200 확인), 인스타·레딧은 수동 링크. 규칙 묶기·임시 점수 discovery-v1(LLM 0회) — `engine/drinks_discover.py`, 화면 `/drinks/discover` | `docs/deviation-drinks-discovery.md` |
| ① 선정 | 근거 승인·편성함·점수(rubric) — 0050/0051 | `docs/deviation-drinks-phase-a.md` |
| ② 카드뉴스 | 승인된 카드 제작안 → 1080×1350 PNG 묶음(`engine/drinks_cards.py`), 파일 묶음(manifest)·결과 검수(`drink_output_reviews`) | `docs/deviation-drinks-production.md` |
| ② 릴스 | 영상 제작안 → 엔진 로컬 렌더(`engine/drinks_render.py`), 커버·장면 유형 표기 | 같은 문서 |
| ② 대본 검사 | 원문에 없는 숫자·양·권고 차단(`engine/drinks_script_check.py`), 화면 엔진 게이트(`engine/drinks_screen.py`) | `docs/deviation-drinks-script-engine.md` |
| 돈 | 결재 잠금·보류·정산·주문 해시·그림 재사용(0054, `engine/drinks_paid.py`) | `docs/deviation-drinks-paid-pilot.md` |
| ③ 발행 | **없음.** 명세만 있다 — §8.4 발행 요청 상태(draft→…→published/failed/unknown/paused), §11 Instagram 연동 계약 | `docs/주류공장_구조명세_v1_2026-10-21.md` |
| ④ 성과 | **없음.** 명세 §9.4. 참고로 유튜브용 `engine/analytics.py`·`perf_report.py` 가 있다(이름만 바꿔 쓰지 말 것 — 명세 §3) | 같은 명세 |
| ⑤ 전략 | **없음.** 명세에 정의도 없다 — 새로 설계해야 한다 | — |

명세 §13 의 D단계(발행 연결)가 ③④ 에 해당한다. ⑤ 는 명세 밖이라 설계 문서를 먼저 쓴다.

## 해야 할 일(제안 순서 — 첫 단계에서 운영자와 계획을 확정한다)

0. **선행 확인(운영자에게 물을 것, 명세 §16.3):** 쓸 인스타 계정(술째리고?)의 유형(비즈니스/크리에이터)·연결 방식
   (Instagram Login vs Facebook Login)·Meta 앱 보유 여부. 이게 정해져야 ③④ 가 실제 연결된다. 정해지기 전에도
   상태 기계·큐·화면·가짜 공급자(테스트용)로 끝까지 만들 수 있다.
1. **③ 발행 큐**: `publication_requests`(명세 §7 표 + §8.4 상태). 승인 digest(파일 묶음·계정·캡션·일정)·예약 워커
   (publish_at 점유, 2시간 늦으면 paused)·unknown 은 자동 재발행 금지·조회 대조. 공급자 `providers/instagram.py`
   (Meta Graph API: 컨테이너 생성 → 상태 확인 → publish; 캐러셀은 자식 컨테이너가 다 준비된 뒤 부모).
   파일은 공급자가 가져갈 서명 URL 로(토큰을 URL·로그에 넣지 않는다). 유튜브 업로드 경로(`engine/publish.py`,
   `docs/deviation-youtube-upload.md`)의 경계·기록 방식을 참고.
2. **④ 성과 수집**: 게시물 ID 별 스냅샷(append-only), 게시 후 24h/72h/7d 같은 경과시간 비교. **제공된 지표만**
   저장(미제공은 0 이 아니라 키 없음). 크론은 하루 1번(비용·쿼터). 화면 `/drinks/analytics`.
3. **⑤ 전략 수정**: 성과 → 다음 편성 제안(주종·질문 유형·형식·시간대 가중치). **제안만 만들고 운영자가 확인**하면
   rubric 버전을 올린다(자동 반영 금지 — 근거가 몇 편 안 될 때는 우연이다; 표본 수를 같이 보여준다).
4. **② 다듬기**: 카드뉴스 캡션·해시태그 생성(근거 안에서만), 카드 → 슬라이드 릴스(무료) 변환.
5. **한 바퀴 시험**: 로컬 시험 DB + 가짜 공급자로 수집 → 카드 → 발행 → 성과 → 제안이 이어지는지 e2e.
   실제 계정 게시는 **별도 승인**(공개 발행이다).

## 지켜야 할 것(운영자 규칙 — 반드시)

- **머지·운영 DB 적용·운영 배포·실제 공개 게시·삭제 금지**(각각 운영자 승인 필요). 첫 실게시도 비공개/테스트 계정으로 승인 후.
- 유료 LLM·이미지·영상·음성 호출은 **계획을 결재 문서로 먼저 승인 → 돈은 단계별 소액 결재**. 1센트 미만 Jev 검사·무료 작업은 묻지 말고 진행.
- 시크릿은 명령·로그·URL 에 넣지 않는다. 서비스 키는 브라우저에 노출 금지, anon 전체 쓰기 정책 금지(0031·0049 경계 유지 — 쓰기는 Next 라우트 + `apiGuard` + service key).
- 로그인·차단 우회·비공개 콘텐츠 수집 금지(인스타 해시태그 검색은 공식 API 권한 없으면 수동 링크 유지).
- 대본·캡션: 쉬운 구어체, 원문에 없는 처방·양·결론 금지(`drinks_script_check` 통과 필수).
- 대체 이미지 렌더를 품질 검증이라 보고하지 않는다. Preview 와 Production 은 따로 보고한다.
- 보고는 CLAUDE.md 다섯 덩어리(시키신 것 / 문제가 뭐였나 / 어떻게 해결했나 / 이렇게 확인하세요 / 다음 작업), 쉬운 말.
- 웹 변경도 `pytest` 전체를 돌린다(테스트가 web 소스를 grep 한다).

## 로컬 시험 DB(필요하면)

임베디드 Postgres `C:/Users/Public/drinkspg`(포트 54329, DB `pilot`) + PostgREST 대역 54321 — **지금 꺼져 있다.**
켜는 법: `cd /c/Users/Public/drinkspg && node boot_pg.mjs C:/Users/Public/drinkspg/data` (백그라운드). 역할은 인증 헤더로
`service-local` / `anon-local`. 운영 DB 아님.

## 멈춘 것(돌아올 때 참고)

위스키+물 시범(유료 그림 경로): v6.1 1단계 그림 3장 $0.307 구매·검수 완료(운영자 "이 정도면 괜찮은 것 같긴 해").
누적 지출 $0.921. 다음이었던 2단계(4번 장면 6초 영상, 약 $0.30)는 **보류**. 열린 결재 둘(25eea84f 잔액 $0.093,
옛 36694b47 잔액 $0.148)은 로컬 시험 DB 안의 것이다. 기록: `docs/deviation-drinks-paid-pilot.md`.
