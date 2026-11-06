# 편차 기록 — 주류: AI 사실 확인 자동 표시 · 보관 질문용 공식 출처 (2026-11-06)

**운영자 원문(2026-11-06):** "둘 다 예. 바로 만들고 배포해"

1. "AI 가 사실 확인에 통과한 근거는 '확인됨'으로 자동 표시"
2. "유통기한·보관 질문에 쓸 공식 사이트를 더한다"

이 문서가 뒤집는 기존 정책:

- `supabase/migrations/0064_drinks_single_approval.sql` 머리말 18행 — "support_review 는 여기서 자동으로 채우지 않는다."
- `supabase/migrations/0050_drinks_factory_phase_a.sql` 196행 — `origin_group` "운영자가 확인한 원출처 묶음(자동으로 채우지 않는다)", 정책 ②("독립 원출처는 운영자가 묶음을 정한 것만 센다").

**바뀌지 않는 것:** 승인은 여전히 사람의 [승인] 한 번이다(`drinks_approve_content`). 필수 조건 검사(`drinks_review_blockers`)·이어 만들기 멈춤(`drinks_chain_stop_blockers`)·승인 함수는 한 글자도 고치지 않았다. 워커는 승인·제출 함수를 부르지 않는다(`tests/test_drinks_develop.py`·`tests/test_drinks_factcheck.py` 가 감시).

---

## A. AI 사실 확인 → '확인됨' 자동 표시

**어디서:** `engine/drinks_develop.py` — `run_factcheck` · `judge_verdicts` · `apply_factcheck`. 근거 추출(출처마다 모델 1회)과 원문 인용 대조가 끝난 뒤, 저장하기 직전에 모델을 **1회 더** 부른다.

**입력:** 소재 제목·질문, '질문이 나온 곳'(질문·인기 신호 출처·커뮤니티 글의 앞부분 600자, 최대 4개 — 사실 근거로 쓰지 않는다), 인용 대조를 통과한 주장(claim_id·문장·원문 인용).

**출력(JSON):** 소재 질문이 담은 주장마다 `verdict` TRUE·FALSE·UNCERTAIN + `claim_ids` + `reason_ko`, 그리고 근거 주장마다 `faithful`(주장 문장이 인용 범위 안인가).

**코드 규칙 — 모델을 믿지 않는다:**

| 경우 | 결과 |
|---|---|
| 판정 값이 셋 중 하나가 아님 | UNCERTAIN |
| 댄 claim_id 중 하나라도 근거 목록에 없음(지어낸 번호) | UNCERTAIN |
| TRUE·FALSE 인데 claim_ids 없음 | UNCERTAIN |
| 이유의 숫자가 댄 근거의 원문 인용에 없음(전각 숫자 정리, `c3` 같은 번호는 숫자로 안 침) | UNCERTAIN |
| 응답 모양이 틀림 · JSON 파싱 실패 · 네트워크 오류 | 한 번 더 묻고, 그래도 안 되면 **전부 불확실**(작업은 성공으로 끝낸다) |
| 주간 한도·요청 상한에 막힘 | 건너뜀(전부 불확실), 작업은 계속 |
| 운영자 취소 | 그대로 멈춘다 |

**'확인됨'이 되는 주장:** TRUE 또는 FALSE 판정(코드 규칙 통과 뒤)이 근거로 댄 주장 ∩ `faithful=true` ∩ Jev 가 걸지 않은 주장(Jev 를 켰을 때) ∩ 의견(opinion)이 아닌 주장. FALSE 판정이 댄 주장은 "사람들의 믿음이 틀렸다고 말하는" 정정 근거라 함께 '확인됨'이다. 그 주장의 한계·주의 칸에 `AI 사실 확인(자동) — 근거 인용 대조 통과`(`config.DRINKS_DEVELOP_FACTCHECK_NOTE`)를 적는다 — 화면이 이 글로 'AI 확인' 표시를 단다(`web/lib/drinks/factcheck.ts::isAutoSupported`).

나머지는 `not_reviewed` 그대로이고, 요청 기록(`drink_develop_requests.result.factcheck.not_supported`)에 이유와 함께 남아 화면 맨 위 "직접 확인할 주장"으로 나온다. 운영자가 할 일은 그 목록과 핵심 메시지 한 줄을 보고 [승인]하는 것이다.

**돈:** 모델 호출은 기존 가잡기 → 확정(`Ledger`)으로만 — 주간 한도·요청 1건 상한($0.5)·호출 20회 상한 안에서 센다. 모델은 추출과 같다(`DRINKS_DEVELOP_FACTCHECK_MODEL` = `DRINKS_DEVELOP_EXTRACT_MODEL`, 기본 gemini-2.5-flash). 한 번의 예상 상한 약 $0.02(결제 실패 대체 모델 단가 기준), 소재 1건 근거 단계 예상 상한은 출처 4곳 추출 $0.21 + 사실 확인 $0.02 ≈ $0.23. 실제 사용량 기준은 이보다 훨씬 작다(미검증 — 실측 전). `0075_drinks_auto_factcheck.sql` 이 화면의 비용 예상(`drinks_develop_estimate`)에 사실 확인 1회를 더한다.

**저장 위치:** 마이그레이션 없음 — 판정은 요청 기록 `result.factcheck`(jsonb), 주장 상태는 근거 버전(`evidence_pack.claims[].support_review`·`limitations`)에 기존 칸으로 들어간다.

**주의:** 한계·주의 칸은 근거 내용 지문(0064 `drinks_evidence_content_hash`)에 들어간다. 그래서 화면은 사람이 '뒷받침 확인'을 바꿔도 그 칸을 지우지 않는다(지우면 대본이 무효가 된다). 사람이 다른 값을 고르면 'AI 확인' 표시는 저절로 사라진다(확인됨 + 자동 문구일 때만 표시).

## B. 보관·유통기한 질문용 공식 출처

전에는 공식 출처 13쪽 전부의 `not_for` 에 보관·개봉·유통기한이 있어서, 그런 질문은 근거가 0건이었다. 아래 두 쪽을 **보관·기한 질문에만** 읽게 더했다(`requires_any` — 소재에 그 낱말이 하나라도 있어야 읽는다). 옛 13쪽은 바꾸지 않았다. 쪽과 약관 쪽을 2026-11-06 엔진 수집기(`SafeFetcher`·`parse_page`, robots.txt 판정 포함)로 다시 받아 읽었다. 아래 판정은 약관 문구를 읽은 판단이고 법률 자문이 아니다.

| 쪽 | 받은 글자 | 무엇에 답하나 | 약관(읽은 내용) |
|---|---:|---|---|
| [일본 국세청 — 第86条の6 酒類の表示の基準(법령해석통달)](https://www.nta.go.jp/law/tsutatsu/kihon/sake/8-09a.htm) | 8,286 | 生酒(살균 안 한 사케)의 「保存又は飲用上の注意事項」=「要冷蔵」「冷蔵庫に保管してください。」「冷やしてお早めにお飲みください。」, 製造時期 = 용기에 채워 밀봉한 시기, 賞味期限을 적으면 식품표시법을 따른다 | [利用規約](https://www.nta.go.jp/chuijiko/copy.htm): 저작권은 국세청, 권리 표기가 없으면 「公共データ利用規約(第1.0版)」 준거 — 출처 기재, 가공했으면 가공 표시. 이 쪽에 별도 권리 표기 없음 |
| [영국 legislation.gov.uk — Regulation (EU) No 1169/2011 Annex X](https://www.legislation.gov.uk/eur/2011/1169/annex/X) | 11,099 | "beverages containing 10 % or more by volume of alcohol" 은 최소 보존기한(date of minimum durability) 표시 의무에서 빠진다(영국 현행본) | [쪽 아래 문구](https://www.legislation.gov.uk/help): "All content is available under the Open Government Licence v3.0 except where otherwise stated. This site additionally contains content derived from EUR-Lex, reused under the terms of the Commission Decision 2011/833/EU" — 둘 다 출처 표기 조건의 재이용 허용 |

**등록하지 않은 곳과 이유(이번에 다시 확인):**

| 곳 | 내용 | 왜 안 되나 |
|---|---|---|
| 일본주조조합중앙회 [日本酒はどうやって保存管理するの？](https://japansake.or.jp/know/what/04.html) | 사케 보관 온도·빛·세워 두기 (6,071자 받힘) | 사이트에 이용 규약이 없다. 쪽 아래 "Copyright © 2022 Japan Sake and Shochu Makers Association." 뿐 — 인용 허락 문구 없음 |
| 酒類総合研究所(NRIB) お酒のはなし | 사케 보관·열화 | 「ご利用ガイド」에 "著作権について" 제목만 있고 내용이 없다(재이용 조건 없음). "All rights reserved". 자료 본문은 PDF |
| korea.kr 「Q&A로 알아보는 '소비기한 표시제'」①② | 소비기한 표시제 | 쪽에 공공누리 표시가 없다("공공누리가 부착되지 않은 자료는 담당자와 협의") |
| korea.kr 2022-01-28 식약처 명절 식품 안내 | "탁주와 약주는 유통기한을 표시하도록" | 공공누리 제1유형(텍스트)이라 약관은 되지만 **소비기한 표시제(2023~) 전 글**이라 지금은 틀린 사실이 될 수 있다 — 넣지 않았다 |
| 농사로 「곡주의 신맛 억제 방법」 | 막걸리 신맛 | 공공누리 유형을 화면에서 스크립트로 정한다 — 받은 HTML 에 1~4유형 문구가 다 들어 있어 어느 것인지 확인 불가 |
| 식약처(mfds.go.kr) 「식품등의 표시기준」 | 주류 날짜 표시 | 본문이 첨부 파일(HWP/PDF)이라 이 수집기가 못 읽는다. 국가법령정보센터는 스크립트로 그려 본문 0자 |
| 미국 TTB 용어집 | 숙성 연수 정의 | robots.txt 가 우리 수집기를 막는다(우회하지 않는다) |
| 스카치위스키협회 FAQ | — | 쪽 주소 404 |
| 제조사(Glenlivet·Jameson 등) 보관 안내 | 위스키 보관 | 판매 목적 글이고 상업 이용 약관을 확인하지 못했다 |

**여전히 빈칸:** 막걸리 보관·유통기한, 개봉 후 위스키 맛 변화의 공식 설명. 이런 소재는 지금처럼 근거 부족으로 멈추는 것이 맞다(지어내지 않는다).

## C. 원출처 묶음 자동

워커가 새 출처를 붙일 때 `origin_group` = 발행처(없으면 등록 도메인, 예 `nta.go.jp`·`aks.ac.kr`)를 채운다(`engine/drinks_develop.py::origin_group_of`). 이 값은 비교 주장("A가 B보다")의 '서로 다른 곳 2곳' **경고**에만 쓰이고 승인을 막지 않는다. 화면은 입력 칸을 카드의 '고급'에 접었다. 연결 메모(`relation_note`)에 `자동 개발: 공식 출처 목록에서 가져온 원문` 을 남겨, 화면이 그 출처를 "원문 전문 직접 입력"이 아니라 "AI 가 공식 출처에서 가져온 원문 전문"으로 부른다(옛 기록은 공식 출처 주소로 알아본다).

## D·E. 화면

- 근거 칸 맨 위 "AI 사실 확인: 맞음 N · 틀림 N · 불확실 N" — 주장마다 판정·이유·근거 출처 링크, 코드가 판정을 내렸으면 그 이유, 그리고 "직접 확인할 주장" 목록(`web/components/drinks/FactcheckSummary.tsx`).
- 질문·인기 신호·커뮤니티 출처는 근거 카드가 아니라 접힌 "질문이 나온 곳" 묶음에 둔다.
- AI 초안 요청이 대기·진행 중이면 근거 칸의 추가·저장 버튼을 잠그고 이유를 보여 준다(그 사이 저장하면 근거 요청이 `draft_exists` 로 실패하거나 대본이 무효가 된다).
- 작업공간의 "열린 개발 결재가 없습니다 — 아래 개발 카드에서…" 문구를 "이번 주 AI 초안 한도"로 바꿨고, 작업공간이 열릴 때 이번 주 한도 줄을 먼저 만든다(`loadWeeklyBudget()`, 소재 고르기 화면과 같은 순서).

## 되돌리기

1. 자동 '확인됨'을 끄기: 워커 환경변수 `DRINKS_DEVELOP_FACTCHECK_ENABLED=false`(코드 기본 켜짐). 이미 저장된 '확인됨'은 남는다 — 근거 화면에서 그 주장의 '뒷받침 확인'을 다시 고른다.
2. 보관 전용 쪽 빼기: `engine/config.py` 의 `DRINKS_DEVELOP_OFFICIAL_SOURCES` 맨 아래 두 항목과 `web/lib/drinks/officialSources.ts` 의 같은 두 줄을 지운다(테스트가 두 목록을 대조한다).
3. 원출처 자동 끄기: `origin_group_of` 호출 두 곳을 지운다(이미 저장된 묶음은 화면 '고급'에서 비운다).
4. 비용 예상: 0072 의 `drinks_develop_estimate_params()`·`drinks_develop_estimate(jsonb)` 를 다시 실행한다(0075 되돌리기).

## 확인

- `tests/test_drinks_factcheck.py` — 판정 규칙(좋은 응답·지어낸 번호·인용에 없는 숫자·근거 없는 판정·모양 오류·JSON 실패 재시도·한도·취소·끔), 비용 상한, 리허설 고정본이 지금 워커 출력과 같은지.
- `web/lib/drinks/factcheck.db.test.ts` — 그 고정본(워커가 보내는 RPC 그대로)을 PGlite 위 진짜 SQL 에 보내 '확인됨'이 필수 조건을 통과하고 이어 만들기가 멈추지 않는지(`drinks_chain_stop_blockers` = []).
- 실제 모델로 판정이 쓸 만한지는 아직 모른다(미검증) — 첫 실제 소재에서 판정과 원문을 사람이 대조해 본다.
