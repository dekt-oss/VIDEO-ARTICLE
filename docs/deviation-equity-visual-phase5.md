# Phase 5 — Equity Visual Planner (2026-08-30)

정본: `docs/작업지시서_시각엔진v3_equity.md` · 계획서 `docs/작업계획서_시각엔진_v3.md` §6 Phase 5

**착수분(Phase A·B·D 일부).** 실제 리포트 1건으로 검증 — 비용 $0.025(약 35원). 남은 것은 §5·§7.

---

## 0. 무엇이 문제였나

리포트 라인은 `report_reasoning` 이 만든 **논증 단계**를 이미 갖고 있었다.
"전력망 투자 → 변압기 수주 → 수주잔고 → 매출 인식 → 마진 개선" 같은 경로가
`report_drafts.financial_reasoning` 에 저장돼 있다.

**그런데 화면이 그것을 몰랐다.** 저장소를 훑으니 `report_*.py` 전체에
`visual_sequences`·`resolved_visual_plan`·`sequence_render` 참조가 **정확히 0곳**이었다.

그래서 "왜 이 증권사가 이렇게 전망하는가"가 숫자 카드와 낱장 그림의 나열로 나갔다.
논증은 있는데 화면이 안 읽는 것 — 이 저장소가 여덟 번 반복한 **"만들어 놓고 한쪽만 연결"** 이다.

## 1. 무엇을 만들었나

`engine/equity_visual.py` — **순수 함수 모듈. LLM 호출 0.**

```
report_reasoning.reasoning_units[].steps  →  공용 visual_sequences
```

| | 내용 |
|---|---|
| 사업 의미 판정 | 단계 문장 → `ORDER`·`BACKLOG`·`RECOGNIZE_REVENUE` … (어휘표, 코드가 판정) |
| 번역 | 사업 의미 → **공용** 시각 연산·변이·카메라·지속 개체(§5 표) |
| 세계 | 논증 단위 하나 = 세계 하나. 첫 stage 가 세우고 나머지는 `CONTINUE_WORLD` |
| 라우팅 | 밸류에이션·비교는 시퀀스가 **안 된다**(§6.2 — 수치는 code viz) |
| 정밀 레이어 | 수치를 든 단계는 세계를 끊지 않고 `CODE_OVERLAY` 를 얹는다(코덱스 리뷰 R1) |

### ★ EQ-V5 를 게이트가 아니라 **구조**로 막았다

> "`수주 증가 → 매출 증가` 사이에 원문이 말하지 않은 단계가 추가되면 안 된다"

stage 는 step 에서 **1:1** 로 나온다. 그래서 리포트가 말하지 않은 단계가 **생길 자리가
없다.** 검사해서 잡는 것이 아니라 만들 수 없게 한 것이다. LLM 에게 다시 묻지 않는
설계(§4 "재추출 금지")가 그대로 이 성질을 준다.

리포트 문장은 `reasoning_text` 로 stage 에 **그대로** 남는다. 다만 **화면 계약**
(`observable_change`·`result_state`)에는 싣지 않는다 — 그 안의 정확한 수치를 생성
이미지에게 그리라고 요구하는 셈이기 때문이다(아래 실측 A-②). 층을 나눈 것이지
버리는 것이 아니다.

## 2. 어떻게 배선했나 (§1 — 새 파이프라인 금지)

`report_directive.generate` 가 **정규화 앞에** 시퀀스를 꽂는다:

```python
obj["visual_sequences"] = equity_visual.build_for_directive(
    obj.get("cuts"), draft_row.get("financial_reasoning"))
d = dv.normalize_directive(obj, version_type, cut_max_sec=config.CUT_MAX_SEC)
```

`normalize_directive` 는 시퀀스가 있으면 **라우팅·`resolved_visual_plan`·
`stage_mutations`·공용 게이트를 이미 전부** 돌린다. 그래서 이 한 줄로 금융 라인이
그 기계를 통째로 물려받는다. 금융용 스키마도 게이트도 새로 만들지 않았다.

**컷↔stage 는 컷이 스스로 말한 `(reasoning_id, reasoning_step)` 으로만 잇는다.**
"R01 을 옮기는 컷 3개를 stage 5개에 고르게 배분"은 **우리가 지어낸 정렬**이고,
그러면 논증은 5단계인데 화면은 3단계인 어긋남이 보이지 않는다.
없는 단계를 가리키면 버린다(`_filter_reasoning_ids` 와 같은 규율).

`reasoning_step` 은 워커 전용이다(`reasoning_id` 와 같다) — 엣지로 새지 않도록
`tests/test_prompt_sync.py` 의 `WORKER_ONLY_REPORT_FIELDS` 에 넣었다.

## 3. ★ 배선하다 드러난 결함 둘 — 컴파일만 보면 안 보인다

둘 다 "시퀀스는 잘 만들어졌는데 **하류가 다르게 읽는다**"였다.
지시서 JSON 만 보면 정상으로 보인다.

### ① 리포트 컷은 `claim_ids` 를 쓰지 않는다

라우터는 **주장을 지불하지 않는 컷**에 기전 자격을 주지 않는다(CTA 컷이 기전 도해가
되는 것을 막는 규칙이다). 그런데 리포트 컷은 `source_facts`(Fact Sheet 키)를 쓰고
`claim_ids` 를 안 쓴다. 그래서 배정만 하고 끝냈더니:

```
in_sequence: 0 · connective_in_world: 4 · CODE_VIZ: 6
```

**시퀀스를 만들어 놓고 화면 판정은 전부 기본값이었다.**
고침: 컷을 stage 에 묶을 때 그 stage 의 `claim_ids` 를 컷에 알려 준다.
지어낸 id 가 아니다 — `fact_ids` 는 `report_reasoning` 이 이미 `number_facts` 원장과
대조해 남긴 것이다. 컷이 스스로 선언했으면 덮어쓰지 않는다.

### ② stage 소속을 "판정"으로 읽었다 (§9-10 이 새 문으로 돌아왔다)

`_is_code_visual` 은 `beat_declared or stage_ref` 면 라우터의 base 를 믿었다.
금융 컷은 **beat 를 선언하지 않는다.** 그런데 컷을 stage 에 묶자 `stage_ref` 가 생겼고,
그 순간 라우터가 **채워 넣은** 기본 base(`CODE_VIZ`)가 판정으로 읽혀
**시퀀스 컷 4개가 전부 코드 시각화로 세어졌다 — 이미지 예산이 0이 된다.**

계획서 §9-10 이 적은 그 결함이다:

> **정본을 만들면 그 정본의 기본값도 정본으로 읽힌다.** 기본값에는 표시가 필요하다.

고침: 실제 판정의 표시는 라우터가 남기는 `in_visual_sequence` 다. 그것을 본다.
`stage_ref` 는 소속일 뿐 판정이 아니다.

## 4. 1차 실측 (LS ELECTRIC 논증 **구조를 손으로 넣은 것** · 생성 호출 0)

> 진짜 리포트로 돌린 결과는 이 문서 맨 끝 절이다. 아래는 설계가 의도대로 도는지 본 것이다.

```
논증 R01 (DRIVER_CHAIN, 유안타증권) 5단계
  S1_DEMAND_INCREASE  FLOW        TRACK          NEW_WORLD
  S2_ORDER            TRANSFER    FOLLOW_OBJECT  CONTINUE_WORLD ← S1
  S3_BACKLOG          ACCUMULATE  DOLLY_OUT      CONTINUE_WORLD ← S2
  S4_RECOGNIZE_REVENUE TRANSFORM  DOLLY_IN       CONTINUE_WORLD ← S3
  S5_MIX_SHIFT        SPLIT       TOP_DOWN       CONTINUE_WORLD ← S4
개체: DEMAND_FLOW · ORDER_BLOCK · BACKLOG_QUEUE · REVENUE_CONTAINER · PRODUCT_UNIT
```

작업지시서 §8 의 "Sequence POWER_INFRA"(수요 → 수주 → backlog → 생산 → 매출)가
**논증에서 그대로 나온다.** 우리가 공정을 지어내지 않았다.

| | 결과 |
|---|---|
| 공용 게이트 | `block_reasons: []` · progression `True` |
| 지표 | world_reset_rate 0.2 · continuity_rate 0.8 · 개체 해소율 1.0 |
| 라우팅 | MECHANISM_SEQUENCE 4 · in_sequence 4 · connective 1 |
| 비용 | code_viz 0 · unique_asset 5 · 이미지 $0.0975 |
| 렌더 판정 | `new_world → reference → reference → reference` |

**마지막 줄이 이 Phase 의 목적지다** — 리포트 컷이 앞 stage 그림을 시작 프레임으로 받는다.

> 4단계("2~3분기 뒤 매출로 인식된다")는 리포트가 숫자를 안 붙인 서술 단계라
> `connective_in_world` 다. 결함이 아니라 공용 규칙 그대로고, **세계는 그대로
> 물려받는다**(렌더 판정이 `reference`).

## 5. 미검증 — "됐다"고 말하지 않는 것

> **아래 첫 항목은 그 뒤 해소됐다.** 실제 리포트 1건으로 돌렸고 결과는 이 문서 맨 끝
> "실제 리포트 실측" 절에 있다 — **연속성이 한 번도 안 생겼다.**

- ~~실제 리포트로 한 번도 안 돌렸다~~ → 돌렸다. 결과는 §C.
- **렌더는 0회다.** 판단은 전부 지시서 JSON + 판정 함수 수준이다.
  화면에서 실제로 수주 블록이 잔고에 쌓이는지는 못 봤다.
- **EQ-V1~V7 게이트를 아직 안 만들었다.** EQ-V5 는 구조로 막혔지만
  EQ-V2(attribution) · EQ-V3(forecast≠actual) · EQ-V4(number integrity) ·
  EQ-V6 · EQ-V7 은 **없다.** 이것이 다음 작업이다.
- `attributed_to`·`carries_thesis` 를 시퀀스에 실어 뒀지만 **읽는 곳이 아직 없다**
  (EQ-V2 가 읽을 자리다). 지금은 진단용이다.
- LS ELECTRIC 골든 3자 비교(v2 directive vs v3 plan vs 실렌더)는 안 했다.
- 어휘표는 유한하다. 같은 사업 의미를 다른 말로 쓰면 기본값으로 떨어진다 —
  `summary().semantic_defaulted` 가 그 수를 보여 준다(많으면 표를 넓힌다).

## 6. 다음

1. **컷이 논증 단계를 순서대로 밟게 한다** — 실측이 지목한 1순위(§C). 이것이 없으면
   시퀀스를 아무리 잘 컴파일해도 화면은 안 이어진다.
2. **EQ-V2·V3·V4·V6·V7 게이트** — 특히 EQ-V3(전망을 실적처럼 그리지 않는다)는
   금융 라인의 컴플라이언스 표면이다.
3. LS ELECTRIC 골든 비교.


---

# ★ 실제 리포트 실측 (2026-08-30, iM증권 ESS)

리포트: iM증권 「국내 업체들의 ESS 전환 더욱 가속화될 전망」 · 원문 11,994자(full_text)
비용: 논증 생성 $0.011 + 지시서 생성 $0.014 ≈ **$0.025 (약 35원)**. Gemini 만, 직렬.
산출: `docs/review-2026-08-30/equity_real_{reasoning,sequences,directive}.json`

## A. 실측이 잡은 결함 셋 — 픽스처가 전부 숨기고 있었다

### ① ★★ 정본 키를 틀리게 읽었다 — Phase 5 전체가 무력화될 뻔했다

`compile_sequences` 가 `reasoning_units` 를 읽고 있었다. 그건 **LLM 출력의 키**이고,
`normalize_units` 를 지나 저장되는 정본 블록은 **`units`** 다
(`report_reasoning.empty`·`build`·`reasoning_ids`·`units_block` 전부 `units` 를 읽는다).

틀린 키를 읽으면 **조용히 빈 목록**이 나온다. 게이트도 경고도 없이 화면은 예전 그대로다.
그리고 **내 단위 테스트는 같은 오해를 픽스처에 담고 있어서 통과했다.**

> 교훈: 픽스처는 내 이해를 그대로 복사한다. **원장이 실제로 쓰는 모양**을 기준으로
> 못박아야 한다 — `test_the_planner_reads_the_key_the_ledger_actually_writes` 가
> `report_reasoning.empty()` 를 직접 보는 이유다.

관대하게 둘 다 받지 않았다. 정본 키가 흐려지는 순간 같은 사고가 돌아온다.

### ② 리포트 문장을 화면 계약에 그대로 실었다 (VSEQ-7 차단 2건)

```
vseq_quantitative_visual:SEQ_R01/S1_DEMAND_INCREASE   ← "MACR 55% 이상"
vseq_quantitative_visual:SEQ_R02/S2_PRODUCE           ← "지분 49.99%를 인수"
```

"지어내지 않으려고" 리포트 문장을 `observable_change`·`result_state` 에 그대로 넣었는데,
그것은 **생성 이미지에게 정확한 수치를 그리라고 요구하는 것**이었다.
Phase 0 이 잰 것이 정확히 그거다 — 생성모델은 개수를 의도대로 **읽지 지키지 않는다.**

**게이트가 옳다. 프롬프트를 조였다:** 화면 계약에는 **방향과 동작**만 싣고
(`config.EQUITY_CHANGE_PROSE`), 수치는 **정밀 레이어 + claim_ids** 가 정확히 담당한다(R1).
리포트 문장은 버리지 않고 `reasoning_text` 로 stage 에 그대로 남는다 —
지어내는 것이 아니라 **층을 나눈 것**이다.

### ③ 같은 사업 의미가 두 번 나오면 진행이 아니었다

한 논증에 `DEMAND_INCREASE` 가 두 번 나왔다(수요가 두 가지 이유로 는다).
화면 문장이 같아지자 **코드가 계산한 상태가 동일**해졌고 상태 원장이 차단했다:

```
vseq_no_progression:SEQ_R01/S3_DEMAND_INCREASE
```

게이트가 옳다 — 같은 화면이 두 번이면 진행이 아니다.
2회차부터 "앞 단계보다 한 번 더"가 된다. 이것은 게이트를 속이려고 문자열만 바꾸는 것이
**아니다**(코덱스 리뷰 S1 이 금지한 것) — 리포트가 "또 늘어난다"고 말했으므로
흐름은 **실제로 앞보다 굵어진다.**

## B. 고친 뒤 — 컴파일은 깨끗하다

```
시퀀스 3 · stage 12 · 진행 3/3 · 정밀 레이어 8 · 어휘 미매칭 1
공용 게이트 block: []   개체 해소율 1.0   연속성 0.75   world_reset 0.25
```

논증에서 나온 세계 셋: 수요→증설→수요→출하→생산 / 증설→생산→증설→생산 / 출하→리스크→재평가.
**우리가 공정을 지어내지 않았다** — 전부 리포트 문장에서 1:1 로 나왔다.

## C. ★★ 그런데 실제 지시서에서는 연속성이 **한 번도 안 생겼다**

진짜 지시서를 만들어(LLM) 렌더 판정까지 돌린 결과:

```
stages_rendered 3 · reference_conditioned 0 · world_reset 3
degraded_continuity: {"degraded_no_reference_frame": 2}
```

**이것이 이번 실측의 진짜 결론이다.** 기계는 다 이어졌는데 화면은 안 이어진다.

원인은 지시서 모델이 컷을 논증 단계에 **띄엄띄엄, 순서를 어겨** 붙이기 때문이다:

| 컷 | 논증 | 단계 |
|---|---|---|
| 4 | R01 | **4** |
| 5 | R01 | **2** ← 뒤로 돌아간다 |
| 6 | R03 | 1 |

컷 4가 `S4_SHIP` 을 먼저 그리는데 그 세계는 `S3` 에서 이어받아야 한다. `S3` 그림이 아직
없으니 참조를 못 붙이고 **새 세계로 떨어진다**(`degraded_no_reference_frame`).
7컷 중 논증에 붙은 것이 3개뿐이라 12 stage 중 9개는 화면이 아예 없다.

> 게이트는 거짓말하지 않았다 — `degraded_no_reference_frame` 로 정확히 그 사실을 남겼다.
> **그래서 "됐다"고 쓰지 않는다.**

### 다음에 고칠 것 (다음 작업의 1순위)

지시서 계약이 "논증을 옮기는 컷은 그 단계를 **순서대로, 연속으로** 밟아라"를 요구해야 한다.
그리고 그것을 **코드가 판정**해야 한다 — 순서가 뒤집히거나 건너뛰면 경고를 남긴다.
지금은 프롬프트가 `reasoning_step` 을 **받기만** 하고 순서에 대해 아무 말도 하지 않는다.
