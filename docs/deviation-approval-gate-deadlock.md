# 편차 기록 — 승인 게이트가 스스로 잠갔다 (2026-08-05)

관련 명세: `docs/수정명세서_근거밀도_가변길이_v1.md` §5-1·§6-4·§14-3(결정 D-E4)·§8 열린 질문 2.
운영자 결정 근거: `docs/작업지시서_영상엔진품질_v3.md` §8("강제 승인은 허용하되 흔적을 남긴다").

## 무슨 일이 있었나

논문 라인(⑤ 영상 지시서)에서 **승인 → 렌더가 100% 막혔다.** 실측 대상은 논문
`9f6f2e8b-0961-4072-9304-0f1f0f00b621` 의 지시서 `bda5e14e…`(comic, 2026-08-05 09:49 생성):

```
block_reasons = ["missing_required_claims", "series_split_required"]
```

두 사유는 성격이 다르고, **둘 다 운영자가 화면에서 풀 수 없었다.**

### ① `series_split_required` — 출구가 없는 차단

`engine/content_mode.select_mode()` 는 `independent_main_claims >= 2` 면 무조건
`series_split` 을 고른다. 그 개수는 Fact Sheet 에서 `claim_kind == "main_result"` 인 주장 수다
(`engine/factsheet.primary_claim_candidates`). 이 논문은 5개 주장 중 **4개가 main_result** 로
추출돼 자동으로 `series_split` 이 됐고, `content_plan.mode_warnings` 에 그 흔적이 남았다:

```
["forced_series_split_multiple_main_claims", "mode_overridden:standard->series_split"]
```

그런데 명세 §8 열린 질문 2 는 **"2편으로 실제 쪼개는 UI·데이터 모델은 범위 밖"** 이라고 못박아 뒀다.
즉 차단은 하는데 차단을 푸는 기능이 존재하지 않는다. 지시서를 다시 만들어도 계획은 **초안**
(`drafts.video_flow.content_plan`)에 있으므로 그대로다. 초안을 다시 만들어도 Fact Sheet 가 같으면
같은 판정이 나온다. 데드락이다.

### ② `missing_required_claims` — 프롬프트와 게이트가 서로 반대였다

게이트는 `primary_claim_id` + `supporting_claim_ids` 가 **전부** 어느 컷의 `claim_ids` 에
실렸는지를 본다. 그런데 지시서 프롬프트(`_mode_guidance`)는 이렇게 말하고 있었다:

> [핵심 주장] C03 — **이 주장 하나만 지불한다.** 독립적인 두 번째 결과를 나열하지 마라.

보조 주장(C01·C02·C04·C05)을 지불하라는 말이 어디에도 없다. 모델이 지시를 잘 따를수록 차단된다.
실제 산출물은 C01·C02·C03·C05 만 실었고 **C04 가 빠져** 차단됐다.

## 무엇을 고쳤나

| # | 파일 | 조치 |
|---|---|---|
| 1 | `engine/directive.py` · `supabase/functions/generate-directive/index.ts` | `_mode_guidance`/`modeGuidance` 에 `[반드시 지불할 주장]` 줄 추가 — primary + supporting 을 **전부 나열**하고 각각 최소 한 컷의 `claim_ids` 에 넣으라고 지시한다. "하나만 지불한다"는 "이 영상의 결론은 하나다"로 교체(보조 주장은 결론이 아니라 근거로 쓴다) |
| 2 | `web/app/api/directive-approve/route.ts` | `force: true` 로 게이트를 지날 때 `console.warn` 으로 우회 기록을 남긴다(리포트 라인 `report-directive-approve` 와 같은 처리) |
| 3 | `web/components/DirectiveClient.tsx` · `web/components/VersionOrderBar.tsx` | 409 차단을 토스트로 끝내지 않고 **2차 확인 모달**을 띄운다: 사유를 사람이 읽고 "그대로 렌더"를 고르면 `force` 로 재요청 |

게이트 판정 자체는 **하나도 약화하지 않았다.** 첫 승인은 여전히 게이트를 그대로 통과해야 하고,
우회는 사람이 모달에서 명시적으로 고른 경우에만, 서버 로그에 남기며 일어난다.

## 왜 게이트를 푸는 대신 우회 길을 냈나

D-E4 표는 `series_split_required` 를 "코드가 데이터로 확정하는 사유 → 차단(409)"에 넣어 뒀다.
그 판정을 경고로 강등하면 명세를 거스르고, 진짜로 두 편짜리 소재인 경우를 놓친다. 반대로 차단만
남기면 분할 UI 가 생길 때까지 그 논문은 영상이 될 수 없다. 그래서 **판정은 그대로 두고 사람이
책임지고 지나가는 길**을 냈다 — 운영자가 이미 `작업지시서_영상엔진품질_v3.md` §8 에서 확정한
방침("강제 승인은 허용하되 흔적을 남긴다")이고, 리포트 라인에 이미 같은 구조가 있다.

## 남은 것 (이번 범위 밖)

- `series_split` 을 **실제 2편으로 쪼개는** UI·데이터 모델(명세 §8 열린 질문 2). 그때까지 이 사유는
  사실상 "권고 + 강제 승인"으로 운영된다.
- `claim_kind="main_result"` 판정이 너무 헐겁다(5개 중 4개). Fact Sheet 추출 프롬프트에서
  "main_result 는 논문의 headline 결과 하나"에 가깝게 좁히는 것이 근본 교정이다. 이번에는
  손대지 않았다 — 채점·초안 전 구간의 산출물이 바뀌므로 별도 측정이 필요하다.
