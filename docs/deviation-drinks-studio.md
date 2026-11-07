# 편차 기록 — 주류 콘텐츠 스튜디오: 3단계 화면 · 저장 충돌 방지 · 자동 복구 (2026-11-07)

**운영자 지시(2026-11-07):** 확정 목업(`sooljjerigo-simple-studio.html`)대로 "① 소재 고르기 ② 초안 다듬기 ③ 버전·생성".
"출처 등록, 원출처 묶음, 주장 선택, 지지 판정, 평가 점수, 공통 기획, 제작 지시서, 중간 검수를 필수 수동 작업으로 요구하지 마세요.
… 정상 제작에서 그 입력·승인 없이 다음 단계로 이어지도록 서버 계약도 바꿔야 합니다."

화면: `/drinks/studio` (`web/app/drinks/studio/page.tsx`, `web/components/drinks/studio/StudioClient.tsx`, 상태 계산 `web/lib/drinks/studio.ts`).
서버: `supabase/migrations/0076_drinks_studio.sql`. 워커: `engine/drinks_develop.py`, `engine/drinks_card_plan.py`.
옛 화면(`/drinks/topics`, `/drinks/work/…`, `/drinks/review/…`)은 그대로 남는다.

## 1. 이 문서가 뒤집는 기존 정책

| 기존 | 이제 | 근거 |
|---|---|---|
| 0050 `drinks_review_blockers`: 5축 점수가 없으면 승인 불가(`scores_incomplete`) | **경고**(`scores_not_evaluated`). 점수는 소재를 고르는 참고값이고, 스튜디오에서는 운영자가 소재를 직접 고르는 것이 선택 판단이다. discovery-v1 의 형식 적합성 두 칸은 완성된 평가로 치지 않는다(가중 합 null → 경고) | 운영자 지시 "평가 점수를 필수 수동 작업으로 요구하지 마세요" |
| 0064 머리말·0075: AI 가 확인하지 못한 주장은 사람이 '뒷받침 확인'을 고른다 | 워커가 **AI 사실 확인을 통과한 주장만 핵심 주장**으로 고른다(`pick_core`). 통과 못 한 주장은 이유와 함께 빼고(`result.excluded`) 근거 기록에는 그대로 둔다. 확인된 핵심 주장이 2건 미만이면 '자료 부족'(`evidence_insufficient`, blocked)으로 멈춘다 | "지지 판정을 필수 수동 작업으로 요구하지 마세요" · "근거 없는 주장은 제외·수정 후 재검사" |
| 0050 `drinks_save_review`: 아무 때나 사람이 저장 | AI 가 그 소재의 초안을 만드는 중이면 **서버가 거절**(`develop_in_progress`). 워커는 같은 트랜잭션에서 `drinks.worker_save=on` 을 켜고 부른다 | 2026-11-06 사케 소재 저장 충돌 |
| 0072 `drinks_request_develop` · 0060 `drinks_develop_save_evidence`: 작성 중 근거가 있으면 `draft_exists` | **빈** 작성 중 근거(주장·질문·핵심 메시지·핵심 주장·점수 모두 없음, `drinks_review_is_blank`)는 막지 않고 워커가 이어 쓴다. 사람이 쓴 내용이 있으면 덮어쓰지 않고 `draft_has_edits` 로 멈춘다 | 같은 사건 |

**바뀌지 않는 것:** 필수 조건의 나머지(핵심 질문·핵심 메시지·핵심 주장·인용 대조·사용 조건·지지 확인·시효)는 그대로 막는다. 승인 함수 `drinks_approve_content`
와 그 안쪽(`drinks_review_action → drinks_select → drinks_plan_action`)은 고치지 않았다. 워커는 승인·제출·편성을 부르지 않는다. AI 판정은 한계 칸의
자동 문구(0075)로 사람 확인과 구분되고, 화면도 "AI 사실 확인 — 사람 확인 아님"으로 적는다. 생성은 게시가 아니다(게시 승인·예약은 `/drinks/publish`).

## 2. 사람이 하는 일 = 세 번

1. **[이 소재로 초안 만들기]** — `drinks_studio_prepare`. 후보면 소재로 올리고(제목·질문·술 종류는 `pickDefaults` 기본값), 형식 의도 카드뉴스, 편성 주차 = 이번 주,
   예산 = 이번 주 AI 초안 한도(0073)로 근거 요청까지 한 번에(0072 `drinks_pick_topic` 그대로). 이미 진행 중이면 그 요청, 초안이 있으면 "초안 이어보기", 정해진 실패면 복구.
2. **초안 다듬기** — `drinks_studio_save_draft`: 페이지 수·순서·근거 연결(claim_ids)은 그대로 두고 글만 저장(자동 저장 1.5초, 버전 대조). 근거 인용·출처 표기에 없는
   **숫자**는 저장은 되지만 돌려주고, 생성이 막는다(`numbers_unverified`). 뜻이 근거를 넘었는지는 자동으로 못 본다 — 화면에 그렇게 적었다.
   [이 방향으로 수정] = `drinks_studio_rewrite`: 지시·지금 초안을 실은 카드 대본 요청. 새 초안이 저장될 때(`drinks_develop_save_rewrite`) 같은 트랜잭션에서 옛 초안을 막는다 —
   실패하면 옛 초안이 그대로 남고, 그 사이 사람이 고쳤으면 저장하지 않는다(`draft_changed`).
3. **[이 초안으로 콘텐츠 생성 · N개]** — `drinks_studio_generate`: 숫자 대조 → `drinks_approve_content`(사람의 이 클릭이 그 승인이다, 메모에 '스튜디오'를 남긴다) →
   `drinks_request_render`(로컬 조립, 유료 호출 없음)를 한 트랜잭션으로. 이미 성공한 제작이 있으면 다시 만들지 않고, 실패한 작업만 `retry_of` 로.

## 3. 자동 복구

- 복구하는 실패: `draft_exists · version_conflict · lease_expired · lease_lost · worker_error · transient_error · factcheck_unavailable · review_changed · db_error`
  (SQL `drinks_studio_recoverable` = TS `RECOVERABLE`, `web/lib/drinks/studio.test.ts` 가 대조).
- 하지 않는 것: 자료 부족·대본 검사 실패·예산·권리·취소·`draft_has_edits` — 화면이 이유와 선택지(다른 소재·한도 보기·기존 작업공간)를 보여 준다.
- 한도: 소재당 24시간 3번(`drinks_studio_limits`), 같은 결재(이번 주 한도) 안에서만, 요청 1건 상한·호출 상한은 워커 가잡기(0060)가 그대로 센다. 새 요청을 만들어 한도를 우회하지 못한다(복구 요청은 `recovery_of` 로 세어진다).
- 누가 복구하나: ① 운영자가 그 소재에서 [초안 만들기] ② 워커가 큐를 집기 전마다 `drinks_studio_recover_all` — **최근 2시간 안**의 실패만(이 파일 적용 전 다른 소재의 옛 실패를 몰래 돌려 돈을 쓰지 않게).
  ★ 새 상시 크론은 만들지 않았다. 브라우저가 닫혀 있으면, 워커가 다시 돌 때(다른 요청·디스패치) 또는 운영자가 화면을 열어 누를 때 복구된다.
- 보관 결과 재사용: 저장만 실패한 근거는 `result.unsaved_evidence`(주장·판정·출처 보고)에 남는다. 다음 요청은 `drinks_develop_context.reusable` 로 받아 **모델을 다시 부르지 않는다** —
  출처가 지금도 근거로 붙어 있고 사용 조건이 `quote_ok/summary_only` 일 때만(바뀌었으면 다시 만든다). 사실 확인만 실패했으면 판정은 비워 보관해 사실 확인만 다시 한다.
- 외부 공급자 중복 과금: 텍스트 모델은 요청 ID 조회 API 가 없다 — 타임아웃 뒤 과금 여부는 알 수 없고, 그 호출은 가잡기 상한 금액으로 확정된다(0060 `Ledger`). 보관 결과가 있으면 재호출 자체를 하지 않는다.

## 4. 지금 못 하는 것(코드로 멈춘다)

- **설명형 영상·밈은 스튜디오에서 만들지 않는다.** 설명형은 그림·영상 구매 결재와 장면 후보 판정·과정/품질/산출물 검수(0067)가 사람 단계로 남아 있고, 밈은 밈 보드의 틀이 먼저다.
  화면은 선택지를 보여 주되 고를 수 없게 하고 기존 화면 링크를 단다. 서버도 `format_not_supported` 로 거절한다.
- 생성 뒤 초안 수정: 확정된 초안은 결과와 묶여 있어 읽기만 된다(`immutable`). 승인된 형식의 두 번째 초안 경로는 이번 범위 밖이다.
- 후보의 술 종류를 글에서 못 알아보면(`pickDefaults` 가 빈 배열) 소재 만들기가 서버에서 거절된다 — 화면이 그 이유를 보여 준다.

## 5. 되돌리기

1. 0050 `drinks_review_blockers`·`drinks_save_review`, 0072 `drinks_request_develop`·`drinks_develop_request_json`, 0060 `drinks_develop_save_evidence` 를 다시 실행한다.
2. 워커: `pick_core` 를 쓰지 않게 `save_evidence` 의 `core` 를 전부 주장으로 되돌린다(또는 `DRINKS_DEVELOP_FACTCHECK_ENABLED=false` — 그때는 예전처럼 전부 핵심, 사람 확인).
3. 0076 머리말의 drop 목록으로 새 함수를 지운다. 새 칸(`instruction`·`recovery_of`·`supersedes_plan_*`)은 남겨도 된다. 메뉴는 `web/lib/nav.ts` 한 줄.

## 6. 확인

- DB 통합(PGlite, 비용 0): `web/lib/drinks/studio.db.test.ts` — 사케 사건 재현(도는 중 사람 저장 거절, 빈 초안 이어쓰기), 사람 편집 보존, 복구·한도·재사용, 끝까지 생성, 실패한 제작만 다시. 기존 `singleApproval·factcheck·cardReel·multiFormat·develop·drinks·production·weeklyBudget` DB 테스트 통과.
- 워커(가짜 공급자): `tests/test_drinks_develop.py`(0076 6건 추가)·`tests/test_drinks_factcheck.py`·`tests/test_drinks_card_reel.py`(수정 지시 1건 추가).
- 화면: `web/lib/drinks/studio.test.ts`(단계·문구·버전·빈 칸). 브라우저 확인은 보고서에 적는다.
- 실제 모델로 판정·초안 품질이 쓸 만한지는 운영 소재로만 안다(미검증).

## 7. 사케 소재 복구 절차(운영 적용 뒤)

대상 `a27480ba-6ff1-429a-ab43-1425a0d1eb45`. 2026-11-07 조회: 작성 중 근거 `fcd35da5…` 는 비어 있다(주장 0·점수 {}·질문·결론 없음, 11-07 05:48 UTC 에 같은 지문으로 한 번 더 저장됐을 뿐 내용 없음).
실패 요청 `d5e191dd…`(`draft_exists`, 결과에 비용 $0.006 만 — 주장 결과는 없다). 출처: 질문 3·근거 2(国税庁 清酒の製法品質表示基準).

1. 직전에 다시 조회한다 — 근거가 여전히 비었는지(`drinks_review_is_blank`), 다른 요청·제작이 없는지.
2. 스튜디오에서 그 소재 → [이 소재로 초안 만들기] (= `drinks_studio_prepare {topic_id}`) → 복구 요청 1건(`recovery_of = d5e191dd…`, 같은 이번 주 한도) + 워커 디스패치.
3. 보관 결과가 없으므로 재추출 + AI 사실 확인 + 카드 초안. 예상 상한: 근거 요청 1건 상한 $0.5(실측 기준 수 센트), 카드 초안 1건 상한 $0.5. 이번 주 한도 $5 안.
4. "유통기한 며칠"을 뒷받침하는 인용이 없으면 기간을 지어내지 않는다 — 확인된 주장이 2건 미만이면 '자료 부족' 화면이 정상 결과다.
