# Explanation Engine v2 설계 점검 (2026-10-05)

> 기준: `main` `d89939b`(PR #100~#103 머지). 원 작업지시서 `docs/작업지시서_ExplanationEngine_v2.md`,
> 단계 문서 `docs/phase*_ExplanationEngine_v2_*.md`, 코드, 그리고 **실제 데이터**(파일럿 후보 6건 무료 실행 +
> 유료 실행 3회 × 2건, 합계 $0.089)를 대조했다. 운영 자료 원문은 싣지 않는다.

## 1. 결론

- **대본 단계(Phase 2~8)는 리포트 기준으로 처음 끝까지 통과했다.** 오늘 고친 단계 간 충돌 4건 덕분이다.
- **그러나 V2 전체는 아직 "대본 + 추적용 지시서 골격"까지다.** 화면을 만드는 쪽(원안 Phase 9~11)은 원안에서
  벗어나 있고 렌더에 쓸 수 없다(§3-A). 원안 Phase 11~13(Renderer·Domain Visual·QA 통합)은 시작 전이다.
- 오늘 막힌 원인은 대부분 **단계를 따로 설계·검증한 진행 방식**에서 나왔다. 단계 문서마다 규칙을 따로 정했고,
  테스트는 입력을 복사하는 가짜 모델만 써서 단계 사이 충돌이 실제 모델 실행 전까지 보이지 않았다.
  → `tests/test_explanation_v2_realistic_model.py` 로 막는다(§4).

## 2. 오늘 고친 것

| PR | 결함 | 분류 |
|---|---|---|
| #100 | 비교 도구: 원장 기록 0건 거짓 표기, 게이트에 가짜 계획, 실패 시 산출물 없음, 덮어쓰기 | 코딩 |
| #100 | 레거시 소스 모드: Phase 2 "추정 금지" vs Phase 8 "정책표와 일치" | 설계 |
| #101 | 도입 질문: Phase 6 "어간 60%" vs Phase 7 "완전 일치" | 설계 |
| #102 | 숫자: Phase 5 전부 넘김 / Phase 6 삭제 금지 / Phase 8 2개 상한 | 설계 |
| #103 | 불확실성 덧붙임 거절(과잉), "약간"→"약" 오탐 | 설계 + 코딩 |

## 3. 남은 설계 문제 (심각도순)

### A. 화면 단계가 원안과 다르다 — V2 지시서는 렌더에 못 쓴다 [구조]

원안 Phase 9 는 "새 Visual Beat Schema 를 만들지 않는다. 기존 Visual Sequence·Stage 를 정본으로 쓴다"이다.
구현은 새 결정론적 시각 계획기(`engine/visual_planner.py`)를 만들었고, Phase 10 은 그 결과를 Production 지시서
**모양**으로만 투영한다. 실측(Samsung `READY` 지시서):

- `visual_prompt` 가 장면 묘사가 아니라 틀 문장이다 — "Show only this source-backed statement: <대본 문장>"
  (`explanation_directive._prompt`). Production 은 장면을 쓴다("클린룸 레일을 따라 웨이퍼 포드가 이동").
- 컷 3개(Production 10컷). 한 컷에 세 문장(약 170자)이 들어가는데 길이가 8초로 적힌다 — `_duration` 이
  3~8초로 자른다.
- Production 의 장면 설계 장치(실사형 계약·화면 구성 계약·`photo_prompt`)를 전혀 쓰지 않는다.

**결정 필요:** ① 원안대로 V2 대본 + 추적 ID 를 **기존 지시서 생성기**(`engine/directive.py`/`photo_prompt`)에
입력으로 넣는다(추천 — 화풍·장면 계약을 다시 만들 필요가 없다), 또는 ② Phase 9/10 을 장면 설계까지 확장한다.

### B. 검증 상태 처리가 거꾸로다 [안전]

`explanation_ir.DISALLOWED_POSITIVE_STATES = {UNSUPPORTED, STALE}`. `NOT_CHECKED` 는 경고만 붙고 근거로 쓰인다.

- retinotopic(`6b2d092a`): 근거 6/6 `NOT_CHECKED` → V2 근거로 그대로 사용(골드셋이 지적한 "청각→시각 전이 발명"
  사례다).
- GWAS(`372055db`): 근거 10/10 `STALE`(옛 검증 규칙으로 검증됨) → V2 가 아예 시작되지 않음.

"한 번도 검증 안 된 근거"가 "옛 규칙으로 검증된 근거"보다 통과가 쉽다. **추천:** `NOT_CHECKED` 도 근거로 쓰지
않고, 두 상태 모두 "Fact Sheet 재검증 후 사용"으로 안내한다(재검증은 기존 파이프라인 비용).

### C. 연구 한계·리스크가 빠진다 [사실 보존]

어댑터가 주장에 직접 붙은 한계(논문)와 `RISK_PATH` 단위(리포트)만 읽는다. 실데이터에서 빠진 것:
heel strike 한계 3, GWAS 한계 5, Samsung 리스크 1, Shipbuilding 리스크 4. 원안 §0 "불확실성·정보 삭제" 원칙과
어긋나고, Samsung 은 기존 대본(피크아웃 우려)보다 후퇴했다.

### D. V2 에 길이·분할 판단이 없다 [구조]

Phase 8 은 Production 이 저장한 계획을 입력으로 받는다(Phase 8 문서). 파일럿 논문 3건이 모두 `series_split` 이라
V2 논문 지시서는 나올 수 없다. V2 가 Production 을 대체하려면 V2 자신의 길이 판단이 있어야 한다 — 원안에는
정의가 없다.

### E. 리포트 논증 단계에 근거 ID 가 안 붙어 있다 [데이터]

`report_step_without_evidence_id`·`reasoning_unit_without_evidence` 경고: Samsung 16건, Shipbuilding 29건.
증권사 논리 단계(`financial_reasoning.steps`)의 `fact_ids` 가 비어 근거 없는 단위가 빠지고 V2 대본이 짧아진다
(Samsung 5단위 → 3비트, Shipbuilding 2단위).

### F. 말하기 품질 [품질]

고정 도입 질문("이 연구는 무엇을 보여 주는가?"), 설명 없는 약어, 60자 초과 문장, 비트마다 증권사 귀속 반복.
전부 경고만 낸다.

### G. 선행 개념 자동 탐지 없음 [원안 대비 공백]

원안 Phase 4 는 "시청자가 모를 개념을 먼저 푼다"이지만 구현은 명시 요청만 해결한다. glossary 2개 항목.

### H. 작은 것

- 연도 단독 표기("1998")를 값으로 센다(NH 실데이터) — `spoken_numbers` 의 시점 패턴은 "년"이 붙어야 한다.
- 리포트 V2 에 면책 문구가 없다 — Production 연결 전 필수.
- Phase 2: `quote_verified=false` 인 claim 이 `SUPPORTED` 로 남는다 — 의도 미확인.

## 4. 재발 방지

`tests/test_explanation_v2_realistic_model.py` — 실제 모델이 파일럿에서 **실제로 한 일**(어미 변형, 존댓말,
화면 숫자를 말로 풀기, 완곡 표현, 귀속 덧붙이기)을 흉내 내는 가짜 모델로 Phase 2~10 을 한 번에 돌린다.
뜻이 같은 변형은 어느 단계도 막지 않아야 하고, 뜻이 바뀌는 변형(연관→결정, 귀속 삭제, "모든", 화면 숫자 읽기,
숫자 값 변경)은 계속 막혀야 한다. 오늘 이전 엔진(`4dcc041`)에 돌리면 첫 유료 실행이 막힌 바로 그 오류
(`rhetorical_exemption_invalid:SC01`)를 비용 0 으로 재현한다.

## 5. 우선순위 제안

1. **A 의 방향 결정** — 이게 정해져야 "V2 지시서 vs 기존 지시서" 비교가 의미를 갖는다.
2. **B** — 안전 문제. 작은 코드 변경 + 재검증 안내.
3. **C·E** — 사실 보존과 대본 분량.
4. **D** — A 방향에 따라 함께 설계.
5. F·G·H.
