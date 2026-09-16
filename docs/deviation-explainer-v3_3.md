# 범위 이탈/정합 기록 + 명세 리뷰: 설명판형 explainer (v3.3)

> CLAUDE.md 작업 규칙 6: "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고 `docs/`를 갱신하며 근거를 남긴다."
> 기준 명세: `docs/개선명세서_설명판형_v3_3.md` (2026-07-30 업로드 원본, 저장소에 그대로 커밋).
> 관련 선행 문서: `docs/deviation-report-factory.md`(리포트 라인) · `docs/deviation-fin-visual-v1.md`(금융 시각 C안) ·
> `docs/수정명세서_근거밀도_가변길이_v1.md`(근거 오버레이·비트) · `docs/deviation-webtoon-b1-removal.md`(editorial 폐기).

---

## 1. 명세 리뷰 — 구현 전에 확인한 것

### 1-1. ★ v3.2 는 이 저장소에 존재하지 않는다 (가장 중요한 발견)

v3.3 은 스스로를 "**v3.2 위에 덮어쓰는 개선 패치**"로 규정하고, v3.2 가 이미 도입했다고 전제한다:
`version_type="explainer"` · `report_analysis` · `source_mode` · `depth_core` · `core_thesis` ·
`insight_nuggets` · `HOOK_BOARD`/`NUMBER_BOARD`/`CHART_BOARD`/`EVIDENCE_BOARD`/`WATCHPOINT_BOARD`.

저장소 전체 grep 결과 **이 중 어느 것도 없다**(코드·마이그레이션·엣지함수·웹 0건). `docs/` 에도
`최종명세서_하루한리포트_설명판형_v3_2.md` 파일이 없다. 즉 v3.3 은 **없는 토대 위의 패치**다.

**결정:** v3.2 를 별도로 복원·구현하지 않고, **v3.3 이 실제로 요구하는 최소 토대까지 이번에 함께
만든다**(`version_type="explainer"` 등록 + 보드 시스템 + source_mode). v3.3 이 §13 완료 기준으로
열거한 항목이 곧 필요한 토대의 목록이고, v3.2 의 나머지 개념(`report_analysis`·`depth_core`·
`core_thesis`)은 이 저장소에 **이미 같은 일을 하는 것이 있다** — 아래 매핑을 따른다.

### 1-2. 기존 자산 매핑 — 새로 만들지 않고 이어붙인 것

| v3.3 / v3.2 개념 | 이 저장소의 기존 자산 | 처리 |
|---|---|---|
| `depth_core.question` · `core_thesis.statement` | `report_drafts.script_md` + `video_flow.logline` | 재사용(신규 필드 안 만듦) |
| `insight_nuggets` | 없음 | `header.explainer.insight_nuggets` 신규 |
| 보드가 화면에 글자를 띄우는 실제 경로 | `engine/evidence_overlay.py` + `subtitles.build_ass`(ASS 레이어) | **재사용** — 보드 문구는 `overlay_plan` 이 렌더한다 |
| `EVIDENCE_BOARD` 출처 표기 | `engine/report_attribution.py` · `report_render._disclaimer_footer` | 재사용 + `source_card` 자동 합성 |
| 숫자의 구조화 근거(`fact_refs`) | `report_factsheet.number_facts[].fact_id`(fin visual Phase 1) | **재사용** — v3.3 의 `fact_refs` 가 이 id 를 가리킨다 |
| 승인 차단 계약 | `header.block_reasons` · `header.approval_blocked` | 재사용(새 표면 안 만듦) — explainer 사유를 `explainer:` 접두로 합류 |
| `CHART_BOARD` 코드 도표 | `engine/fin_charts/`(types.py 만 존재, 템플릿 미구현) | **미배선** — §3-2 참조 |

### 1-3. ★ 명세와 저장소 현실의 정면 충돌: 리포트 원문이 없다

v3.3 의 핵심 요구는 §1-2 "**리포트를 실제로 읽었다는 증거가 화면에 필요하다**" — 증권사명·리포트
제목·**페이지 번호 또는 표/그림 번호**·핵심 근거 문장·그 문장의 숫자를 화면에 보여줄 것.

그런데 이 저장소의 수집 계층은 **리포트 원문 전문을 가져오지 않는다.**
`supabase/migrations/0018_report_pipeline.sql` 의 `reports` 테이블 주석이 그대로 말한다:
`summary text, -- 핵심요약 (원문 전문 아님)` · `report_url text, -- 원문 링크 (본문은 여기 두고 안 옮김)`.
Fact Sheet 추출(`engine/report_factsheet.py`)의 입력도 그 요약문이다.

즉 **페이지 번호를 검증할 근거가 시스템에 없다.** 그 상태로 `page_refs` 를 LLM 에게 요구하면
모델은 그럴듯한 숫자를 채워 넣고, 그 숫자가 "리포트 p.5" 로 화면에 박힌다. 이 저장소의 제1
불변식(환각 방지) 위반이며, 컴플라이언스상으로도 없는 출처를 표시하는 것이다.

**결정 (E1):**
- `page_refs` 는 **Fact Sheet 의 `number_facts[].source_page` 로 해소되는 값만** 남기고 나머지는
  코드가 버린다(`engine/explainer.py:filter_page_refs`). 지어낸 페이지는 화면에 못 올라간다.
- `source_mode` 는 모델에게 묻지 않고 **데이터로 판정**한다(`resolve_source_mode`):
  증권사 + 원문 링크가 있으면 `PARTIAL_REPORT`, 아니면 `NEWS_ONLY`.
  **`FULL_REPORT` 는 어떤 입력으로도 반환되지 않는다** — 원문 전문 수집 경로가 없기 때문이다.
- `EVIDENCE_BOARD` 는 "원문 캡처" 대신 **확보된 사실**로 구성한다: 증권사·애널리스트·리포트 제목·
  근거 문장·그 문장에서 뽑은 수치·(해소된 경우) 페이지. 발행일은 `collected_at`(수집 시각)뿐이라
  **쓰지 않는다** — 리포트 발행일로 오표기될 수 있다.
- 따라서 v3.3 §5-2 의 "실제 리포트의 문장·표·차트 일부를 보여준다"와 "발행일"은 **미충족**이며,
  PDF 수집(§4 백로그)이 생길 때까지 그대로 남는다. 숨기지 않고 여기 적는다.

### 1-4. 그 외 리뷰 지적

- **§9-1 이 `FULL_REPORT`/`PARTIAL_REPORT` 조건부로 쓴 차단 규칙**은 위 E1 때문에 조건이 사실상
  `PARTIAL_REPORT` 하나로 줄어든다. → 조건을 없애고 **모든 explainer 지시서에 동일 적용**한다(더 엄격).
- **§7 "초 단위 하드 규칙 완화"**: 컷 길이 3~8초 클램프는 렌더 타이밍(clip_fit·TTS 실측 정렬)이
  의존하므로 **유지**한다. 완화는 "총 길이 목표"에 적용해 **비트 수(6~8)** 기준으로 바꿨다.
  8컷 × 8초 = 64초로 기존 `TOTAL_SEC_MIN/MAX`(45~90) 안에 들어오므로 충돌 없다.
- **§10 승인 UI**: 요구 7항목 전부 구현. 단 "EVIDENCE_BOARD/CLAIM_BOARD 미리보기"는 **이미지
  미리보기가 아니라 화면 카드 문구(overlay_plan) 미리보기**다 — 승인 시점에는 이미지가 아직
  생성되지 않았다(렌더는 승인 후에 돈을 쓴다). 이미지 미리보기를 승인 전에 두려면 선결제가 필요하다.
- **§11 Phase D(샘플 재제작)**: 라이브 `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` 와 실제 리포트 행이
  필요해 이 세션(샌드박스)에서 **실행하지 못했다**. 절차는 §5 에 적어 뒀다.
- **§4-1 프로필 3종**: `NUMERIC`/`MECHANISM`/`EVENT` 를 enum 으로 넣되 **자동 분류는 하지 않는다**
  (모델이 고르고 코드가 enum 강제). 규칙기반 자동 라우팅은 A/B 규칙 추천이 폐기된 전례
  (`deviation-webtoon-b1-removal.md`)를 따라 데이터가 쌓인 뒤로 미룬다.

---

## 2. 구현 결정 (핵심 이탈)

### E1 — 페이지·원문 근거: 위 §1-3 참조 (해소되는 것만 남긴다)

### E2 — 보드는 신규 렌더 서브시스템이 아니라 `overlay_plan` 으로 화면에 나온다

**결정:** 보드(11종)를 컷의 `board` 필드 + `EXPLAINER_BOARD_SCENE_KIND` 매핑으로 표현하고,
**보드에 실제로 뜨는 글자는 기존 `overlay_plan`(ASS 레이어)** 이 담당한다. 보드 전용 렌더러를 새로
만들지 않는다.

**근거:** `engine/evidence_overlay.py` 가 이미 (a) 유형 enum(`source_card`/`evidence_card`/
`number_punch`/`caveat_tag`), (b) 최소 노출 2초, (c) 컷당 최대 2개, (d) 한 화면 핵심 숫자 1개를
강제하며 렌더에 배선돼 있다. 언어별 ASS 로 구워지므로 **에셋 언어 독립 불변식(I1)도 지켜진다**
(이미지에 글자를 굽지 않는다 → KO/EN 이 이미지·클립을 공유해 추가 비용 0).

**트레이드오프:** `CHART_BOARD`/`VALUATION_BOARD` 가 지금은 **코드 도표가 아니라 스틸 + 카드**로
나간다. `engine/fin_charts/` 는 계약(`types.py`)만 있고 템플릿 5종·`validate.py` 가 **미구현**
(Codex 인계분 미착수)이며, `render_kind_for_scene` 은 제공 버전 전체에서 `image` 를 돌려준다
(`deviation-webtoon-b1-removal.md` 결정). 도표를 살리는 일은 이 개정의 범위가 아니다 — §4 백로그.
그래서 `board` → `scene_kind` 매핑은 현재 **메타데이터·승인 화면·후속 도표 배선용**이고, 실제
시각 차이는 `visual_prompt`(다크 금융 에디토리얼 앵커) + `overlay_plan` 이 만든다.

### E3 — 판정은 엔진 한 곳에서, 승인 차단은 기존 계약에 합류

**결정:** 게이트 계산은 `engine/explainer.py` 만 한다. 웹은 `header.explainer.gate` 를 **표시만**
하고 재판정하지 않는다. 차단 사유는 `header.block_reasons` 에 `explainer:` 접두로 합류하고
`approval_blocked` 를 켠다(신규 승인 표면을 만들지 않는다).

**근거:** 같은 규칙을 두 언어로 두면 반드시 갈린다(이 저장소가 엣지 트윈 이중관리로 이미 겪는 문제).
`block_reasons`/`approval_blocked` 는 논문 라인이 쓰는 기존 계약이라 UI·라우트가 이미 안다.

### E4 — 게이트는 **하드 차단 + 명시적 우회**. 텍스트 컴플라이언스 차단은 건드리지 않는다

**결정:** §9-1 Source Gate 는 승인 라우트에서 **409 로 차단**한다(클라이언트 버튼만 잠그면
라우트를 직접 부르면 통과한다). 단 `force: true` 우회를 남기고, 우회 시 서버 로그에 사유를 남긴다.

**근거·트레이드오프:** `engine/report_compliance.check` 의 텍스트 하드블록은 **사용자 결정으로
의도적으로 비활성**(항상 `blocked: False`)이다. 이 개정은 그것을 되돌리지 않는다 — 새 게이트는
"구조적 완결성"(주장 귀속·근거 보드·숫자 근거·watchpoint 존재)만 보며, 컴플라이언스 판정과 별개다
(`deviation-fin-visual-v1.md` FVD4 와 같은 분리). 우회구를 남긴 이유는 신규 경로에서 LLM 출력
편차로 운영자가 락아웃되는 것을 막기 위함이고, `EXPLAINER_GATE_FORCE_ALLOWED` 로 끌 수 있다.
**우회를 없애려면** 그 상수를 `false` 로 두고 라우트의 `force` 분기를 제거하면 된다.

### E4-1 — "계약 미준수"를 개별 결함과 **다른 사유로** 보고한다 (운영자 락아웃 방지)

`sanitize_board` 는 모르는 값·빈 값을 조용히 `CONTEXT_BOARD` 로 떨어뜨린다. 그래서 모델이
explainer 계약을 통째로 무시한 지시서(보드 0개 선언)도 "보드는 다 있는데 EVIDENCE_BOARD 만
없는" 것처럼 보인다 — 운영자는 있지도 않은 보드를 찾아 컷을 헤집게 되고, 실제 처방(재생성)에
도달하지 못한다. **첫 사용에서 가장 일어나기 쉬운 실패**다.

**결정:** `declared_board_count` 가 0이면 `contract_not_followed` **하나만** 차단 사유로 내고
나머지 개별 사유는 내지 않는다. 라벨도 처방을 직접 말한다 — "컷을 고치지 말고 지시서를
재생성하세요". 일부라도 제대로 선언했으면 계약은 따른 것으로 보고 개별 사유로 안내한다.
(`test_contract_not_followed_is_reported_as_such_not_as_missing_board` ·
`test_partial_board_declaration_still_gets_specific_reasons`)

### E4-2 — 게이트는 판정만 했다 → **사유를 되먹여 1회 재생성** (운영 피드백, 2026-07-31)

**증상(운영자 보고):** 첫 실제 생성물이 `근거 보드(EVIDENCE_BOARD)가 한 컷도 없습니다` 로 승인
차단됐다. 보드는 7개 다 지정됐고(계약은 지켜졌다) EVIDENCE_BOARD 만 빠졌다. `source_mode` 는
`NEWS_ONLY`(원문 링크 없음)였다.

**원인:** 나는 **판정자만 만들고 수선자를 안 만들었다.** 생성은 LLM 1회 호출로 끝나고, 게이트는
그 뒤에 붙어 막기만 한다. 운영자가 [재생성]을 눌러도 **같은 프롬프트로 다시 부르는 것**이라 같은
결함이 반복될 수 있다. 게다가 원문 링크가 없으면 모델이 "보여줄 근거가 없다"고 판단해
EVIDENCE_BOARD 를 건너뛰기 쉽다 — 그러나 증권사명 + 근거 문장만으로도 근거 보드는 성립한다.

**결정:** `generate()` 가 explainer 에서 게이트에 걸리면 **차단 사유를 프롬프트에 되먹여 1회만**
재시도한다(이 저장소의 LLM 규약 "파싱 실패 시 1회 재시도"와 같은 자세). 되먹이는 것은 토큰이
아니라 **처방**이다 — 예: "컷 하나의 board 를 EVIDENCE_BOARD 로 지정하고 overlay_plan 에
증권사·제목·근거 문장 카드를 넣어라. **원문 링크가 없어도 만든다.**"
- 통과하면 재시도하지 않는다(비용) — `test_generate_does_not_retry_when_first_attempt_passes`
- 두 번째도 실패하면 **차단 사유가 적은 쪽**을 저장한다(운영자가 고칠 거리가 적다). 승인은
  여전히 잠기고 사유가 화면에 뜬다.
- 만화식은 이 경로를 타지 않는다 — `test_comic_version_never_retries`

### E5 — 근거 카드는 검사만 하지 않고 **코드가 만들어 넣는다**

`EVIDENCE_BOARD` 컷에 `source_card` 오버레이가 없으면, 확보된 메타(증권사·애널리스트·제목·해소된
페이지)로 카드를 **합성해 넣는다**(`ensure_evidence_cards`). 재료가 없으면(증권사 미상) 만들지 않고
경고를 남긴다 — 없는 출처를 지어내지 않는다.

★ 카드는 **맨 앞에** 넣는다. `normalize_overlay_plan` 은 컷당 상한(`OVERLAY_MAX_PER_CUT`)에 닿으면
뒤를 잘라내므로, 뒤에 붙이면 모델이 카드를 상한만큼 써 둔 컷에서 **출처 카드가 먼저 떨어진다** —
근거 보드에서 출처가 가장 덜 중요한 카드가 되는 셈이다. 잘려야 할 것은 모델의 보조 카드 쪽이다.
(`test_source_card_survives_the_per_cut_overlay_cap` — 고치기 전 이 테스트는 실제로 실패한다.)

**근거:** §9-3 V1("EVIDENCE_BOARD 에 증권사명과 페이지 정보가 보이는가")을 검사로만 두면 경고만
쌓이고 화면은 그대로다. 문구를 확정 데이터로만 합성하므로 환각 위험 없이 요구를 실제로 충족한다.

### E6 — `explainer` 는 공유 enum 에 등록하지만 발주는 리포트 라인에서만

`config.VIDEO_VERSIONS` 에 `explainer` 를 추가했다(`normalize_directive` 가 이 enum 밖 버전을
`DEFAULT_VERSION` 으로 강등하기 때문에 우회 불가). 파생 상수 3종(`VERSION_VISUAL_TYPE`
`VERSION_DEFAULT_SCENE_KIND` `VERSION_GUIDANCE`)과 **엣지 트윈**(`supabase/functions/
generate-directive/index.ts`)도 함께 갱신했다 — `tests/test_prompt_sync.py` 가 Python↔TS enum
일치를 강제한다. 논문 발주 화면(`web/lib/versions.ts:VERSION_META`)에는 **노출하지 않는다.**

### E7 — 두 버전을 **각각** 만들어 비교한다 (운영 피드백 후속, 2026-07-31)

**증상(운영자 보고):** 설명판형 지시서를 만들고 나니 만화식을 새로 만들 수 없었다.

**원인:** `getReportDirective` 가 버전 무관 **최신 1건**만 가져오고, ⑤ 화면의 버전 선택이
"지시서가 아직 없을 때"에만 보였다. 그래서 설명판형이 하나 생기는 순간 화면은 늘 설명판형을
보여주고, 만화식 발주 경로가 사라진다. 리포트 라인은 원래 단일 `comic` 전제로 만들어졌고
(`ReportDirectiveClient` 주석 "단일 comic 버전"), 이번에 버전이 둘이 되면서 드러난 구멍이다.

**결정:** 논문 라인이 이미 쓰는 **버전 탭(`?v=`) 계약을 그대로 미러**한다. 새 개념을 만들지 않는다.
- `getReportDirective(supabase, reportId, versionType?)` — 버전을 주면 그 버전의 최신 지시서.
- ⑤ 화면이 `?v=` 를 읽어 버전을 정하고, 탭에 **버전별 상태 뱃지**(초안/승인/렌더됨)를 붙인다
  — 어느 버전이 어디까지 갔는지가 비교의 출발점이다.
- 생성·재생성·승인·**상태 폴링**이 전부 현재 버전을 향한다. 폴링에 버전을 안 실으면 만화식을
  만드는 중에 예전 설명판형 요청의 `done` 을 보고 "생성 완료"로 끝난다(생기지도 않은 지시서를
  보러 새로고침하게 된다) — `report-directive-status` 에 `version_type` 을 추가했다.
- 버전 목록은 **공장별로 나눈다**(`VERSION_META` 논문 / `REPORT_VERSION_META` 리포트). 한 배열을
  공유하면 논문 화면에 설명판형이, 리포트 화면에 웹툰이 뜬다 — 둘 다 발주 불가 버전이다
  (`web/lib/versions.test.ts`).

**같이 발견해 고친 것 — ⑥ 렌더 결과가 버전을 구분하지 못했다.** `report_render_jobs` 에는 버전
컬럼이 없고 `reportJoinRenderMeta` 가 `report_directives` 에서 `id, report_id` 만 가져오고 있었다.
그래서 리포트 렌더 뱃지는 **처음부터 전부 `?`** 였다(리포트 라인이 단일 comic 이던 동안에는
눈에 띄지 않았다). 두 버전을 각각 렌더해도 어느 영상이 어느 버전인지 알 수 없으니 비교 자체가
불가능하다 → `version_type` 을 조인하고 `ReportRenderJob` 타입에 추가했다. `RenderList` 의
라벨 사전에도 `webtoon`·`explainer` 가 빠져 있어 함께 채웠다.

**범위 밖:** 두 버전을 한 번에 발주하는 일괄 체크박스(웹툰 v1 의 ⑤ 화면 패턴)는 넣지 않았다.
비용이 버전 수만큼 늘고 총액 상한이 잡 단위라(`RENDER_BUDGET_CAP_USD`) 확인 모달 설계가 함께
필요하다 — 지금은 탭을 오가며 하나씩 발주한다.

---

## 3. 무엇이 실제로 바뀌었나 (파일별)

```
신규
  engine/explainer.py                  정규화 + 3게이트(순수 모듈, 네트워크 없음)
  tests/test_explainer.py              28 테스트(참조 해소·페이지 폐기·숫자 자격·게이트·카드 합성)
  web/components/ExplainerPanel.tsx    §10 승인 패널(주장 귀속·숫자 표·보드 구성·watchpoint 분리·경고)
  docs/개선명세서_설명판형_v3_3.md      원본 명세(단일 진실원)
  docs/deviation-explainer-v3_3.md     이 문서

확장
  engine/config.py                     EXPLAINER_* 상수 일괄 + VIDEO_VERSIONS/파생 3종에 explainer
  engine/directive.py                  VERSION_GUIDANCE["explainer"](화면 미학 앵커)
  engine/report_directive.py           EXPLAINER_CONTRACT 프롬프트 + attach_explainer(정규화 뒤 재부착)
  supabase/functions/generate-directive/index.ts   enum 정합(발주 경로는 아님)
  web/lib/types.ts                     ExplainerBlock·NumberClaim·ReportClaimSummary·Cut.board 등
  web/components/ReportDirectiveClient.tsx  버전 선택(만화식/설명판형) + 패널 + 차단 버튼·우회 모달
  web/app/api/report-directive-generate/route.ts   version_type 화이트리스트
  web/app/api/report-directive-approve/route.ts    게이트 409 + force 우회 로그

마이그레이션: 없음
  신규 필드는 전부 report_directives.header / cuts(jsonb) 안에 들어간다. 컬럼을 늘리지 않았으므로
  배포 순서 리스크(0031 사례)가 없다 — 웹 배포와 엔진 배포의 순서 제약이 없다.
```

### 게이트 구성 (v3.3 §9)

| 게이트 | 성격 | 항목 |
|---|---|---|
| Source (§9-1) | **차단** | 핵심 주장 문장/화자 없음 · NUMERIC 인데 숫자 주장 없음 · 숫자 주장에 Fact Sheet 근거 없음 · EVIDENCE_BOARD 0개 · watchpoint 없음 · watchpoint 가 면책 문구 |
| Depth (§9-2) | 경고 | 프로필 필수 보드 없음 · 근거 보드 권장 미달 · 메커니즘 비트 없음 · 근거 비트 2개 미달 · 비트 수 6~8 밖 · 증권사명이 나레이션에 없음 · 비교 기준 없는 숫자 · 인사이트 2개 미달 |
| Visual (§9-3) | 경고 | CLAIM_BOARD 카드 없음/60자 초과 · 대형 숫자 보드가 숫자 주장과 미연결 · 자격 미달 숫자를 크게 씀 · VALUATION_BOARD 의미 설명 없음 · 같은 보드 3연속 |

---

## 3-1. 명세 §13 완료 기준 대조 (원본 체크박스는 건드리지 않고 여기서 판정)

> 원본 명세(`docs/개선명세서_설명판형_v3_3.md`)는 업로드본 그대로 둔다(단일 진실원).
> 완료 판정은 이 표가 정본이며, **코드로 확인한 것과 영상으로 봐야 아는 것을 구분**한다.

### 기능 완료 — 9/9 (코드·테스트로 확인)

| §13 항목 | 상태 | 근거 |
|---|---|---|
| `explainer_profile` 도입 | ✅ | `config.EXPLAINER_PROFILES` · `explainer.sanitize_profile` · `test_sanitize_falls_back_instead_of_accepting_free_text` |
| `report_claim_summary` 도입 | ✅ | `explainer.normalize_claim_summary` · `test_source_gate_blocks_structural_gaps[claim_summary_missing]` |
| `number_claims` 도입 | ✅ | `explainer.normalize_number_claims` · `test_big_number_needs_two_qualifiers` |
| `EVIDENCE_BOARD >= 1` 강제 | ✅ | `source_gate` 차단 · `test_missing_evidence_board_blocks` |
| `CLAIM_BOARD` 추가 | ✅ | `config.EXPLAINER_BOARDS` · `visual_gate` 과밀 검사 · `test_claim_board_text_overflow_warns` |
| `VALUATION_BOARD` 추가 | ✅ | `config.EXPLAINER_BOARDS` · `visual_gate` 의미설명 검사 |
| watchpoint/면책 분리 | ✅ | `watchpoint_is_disclaimer` 차단 · `test_source_gate_blocks_structural_gaps[watchpoint_is_disclaimer]` |
| 게이트 추가 | ✅ | Source(차단)/Depth/Visual 3종 + 승인 라우트 409 |
| 승인 UI 보강 | ✅ | `web/components/ExplainerPanel.tsx` (§10 7항목 — 단 미리보기는 이미지가 아니라 화면 카드 문구, §1-4 참조) |

### 콘텐츠 완료 — **미판정** (실제 영상 1편이 나와야 사람이 본다)

코드는 **조건을 강제**하지만 "잘 됐는지"는 판정하지 않는다. 아래는 Phase D 이후 사람이 채운다.

| §13 항목 | 코드가 보장하는 것 | 사람이 봐야 하는 것 |
|---|---|---|
| 누가·왜·무엇을 전망했는가 명확 | `report_claim_summary` 없으면 승인 차단 | 그 문장이 실제로 이해되는가 |
| 핵심 숫자에 비교 기준 | 없으면 경고 + 대형 사용 불가 | 비교 기준이 적절한가 |
| 증권사 근거 문장이 화면에 | `source_card` 자동 합성 | 화면에서 읽히는가 |
| 수주/실적/목표가가 메커니즘으로 연결 | 메커니즘 비트 없으면 경고 | 설명이 말이 되는가 |
| 결론이 추상적 판단 유보로 안 끝남 | watchpoint 필수 + 면책 분리 | 마무리가 힘이 있는가 |
| 구체적 watchpoint | 텍스트 필수 | 지표가 실제로 확인 가능한가 |

### 시각 완료 — **미판정** (같은 이유). 다만 지금 구조상 미리 아는 것:

- `CHART_BOARD`·`VALUATION_BOARD` 는 **코드 도표가 아니라 스틸 + 오버레이 카드**다(§2 E2·§4 백로그 2).
- `EVIDENCE_BOARD` 의 "실제 리포트 원문 캡처"는 **불가**(§1-3 E1) — 대신 증권사·제목·수치 카드.

---

## 4. 백로그 (순차 · 이 개정 범위 밖)

| 순위 | 내용 | 왜 미뤘나 |
|---|---|---|
| 1 | **리포트 원문(PDF) 수집** → `source_mode=FULL_REPORT`, 실제 문장·표 캡처, 검증된 페이지 번호 | 수집 계층 신규 작업(저작권·보관 정책 판단 포함). 이것 없이는 §5-2 의 "원문 캡처·발행일"이 영구 미충족 |
| 2 | `fin_charts` 템플릿 5종 구현 → `CHART_BOARD`/`VALUATION_BOARD` 를 코드 도표로 | Codex 인계분 미착수. 계약(`types.py`)은 이미 동결돼 있어 이 개정과 독립적으로 진행 가능 |
| 3 | 프로필 자동 분류(리포트 유형 → NUMERIC/MECHANISM/EVENT) | 규칙기반 추천 폐기 전례. 실데이터 누적 후 |
| 4 | 엣지 트윈(`generate-report-draft`)의 `number_facts` 산출 | fin visual Phase 1b 와 동일 — 클라우드 초안 경로엔 구조화 사실이 아직 없다(graceful) |
| 5 | Phase D 샘플 재제작(LS일렉트릭류 1편) | 라이브 키 필요 — §5 절차 |

## 5. Phase D(샘플 재제작) 실행 절차 — 라이브 환경에서

```bash
# 1) 리포트 하나를 낙점 → 대본 승인까지 기존 흐름 그대로
python -m engine.report_collect && python -m engine.report_score
python -m engine.report_draft          # Fact Sheet + 대본(+ number_facts 구조화 사실)

# 2) 설명판형 지시서 생성 (대시보드: ⑤ 화면 → 버전 [설명판형] → 지시서 생성)
python -m engine.report_directive <report_id> explainer

# 3) 승인 화면에서 확인할 것 (v3.3 §10)
#    - 증권사명이 report_claim_summary.speaker 로 잡혔는가
#    - 숫자 표의 '대형 사용' 열이 '가능' 인가(비교 기준·근거 2개 이상)
#    - 근거 보드 컷에 [source_card] 문구가 보이는가
#    - 확인 포인트가 면책 문구가 아닌 구체 지표인가
#    - ⛔ 차단이 뜨면 재생성이 원칙(우회는 사고 추적 대상)

# 4) 승인 → 렌더 → 산출 mp4 를 §13 시각 완료 기준으로 눈으로 검수
```

## 6. 범위 밖(불변)

- 논문 라인(comic/webtoon) 지시서·훅v2·selfcheck·PF1 대본 게이트는 **불변**.
- 리포트 만화식(`comic`) 경로도 불변 — `attach_explainer` 는 `version_type != "explainer"` 면 no-op
  (`tests/test_explainer.py:test_attach_explainer_is_a_noop_for_other_versions`).
- 텍스트 컴플라이언스 하드블록 비활성(사용자 결정) 유지.
- IG/TikTok 등 타 플랫폼 발행·분석, cron 무인 실행은 여전히 제외.
