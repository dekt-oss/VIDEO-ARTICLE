# 범위 이탈/정합 기록: 금융 리포트 영상 시각·서사 강화 (C안 v1.1 · PF2 렌더)

> CLAUDE.md 작업 규칙 6: "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고 `docs/`를 갱신하며 근거를 남긴다."
> 기준 명세(frozen): `docs/강화지시서_금융리포트시각화_C안_v1.1.md` (업로드 원본 + Claude Code 리뷰 반영).
> 골드 스탠다드: `docs/영상지시서_금융숏츠_01_LSELECTRIC_v2.md`.
> 상위 라인: `docs/deviation-report-factory.md`가 "영상 지시서·렌더·유튜브 업로드는 PF2로 보류"라 명시적으로 미룬 단계 = 이 작업.

## 무엇이 추가되나

리포트 영상은 현재 논문 comic 파이프라인을 물려받아 "정지 이미지+켄번스"로만 나온다. 이 작업은 그걸
골드 스탠다드(LS일렉트릭 v2) 수준 — **오프닝 Veo 1클립 + 본문 코드 도표 5종 + 미스터리형 서사(Arc A) 자동 생성** —
으로 끌어올린다. 신규 개발은 **금융 전용 코드 도표 서브시스템 `engine/fin_charts/`** 하나에 국한한다.

## 명세와의 정합 결정 (핵심 이탈)

### FVD1 — 지시서 §8의 `fin_*` 신규 파일 → 기존 `report_*` 확장으로 정합

**결정:** 지시서 §8은 `engine/fin_directive.py`·`engine/fin_overlay.py`를 **신규**로 지정했으나, 이를 만들지 않고
**기존 `report_*` 라인을 확장**한다. 신규 파일은 `engine/fin_charts/`(도표 서브시스템, Codex 경계)만.

**근거(런타임 탐색으로 확인):**
- 금융 파이프라인은 이미 `report_*` 접두사로 성숙하게 존재한다. `engine/report_directive.py`가 이미 금융
  지시서를 생성하고(`REPORT_DIRECTIVE_SYSTEM` 프롬프트 = 지시서 §5 FIN_DIRECTIVE의 사실상 강화판), 논문
  `directive.normalize_directive`를 재사용하며 `broker`를 normalize 뒤 재부착하는 패턴까지 갖췄다.
- 출처·면책 오버레이는 이미 `engine/report_render._disclaimer_footer` + `engine/report_attribution.py`가
  `subtitles.build_ass(footer_text=)` / `assemble_full(duck_spans=)`로 처리한다.
- 신규 `fin_directive.py`/`fin_overlay.py`는 논문 `directive.py` → 금융 `report_directive.py`에 이은
  **4번째 near-duplicate 파이프라인**이 되어 폴링·DB·스캐폴딩과 엣지함수 이중관리 표면을 증식시킨다.

**트레이드오프:** 지시서 §8의 Codex/Claude 파일소유 분리는 **계약 경계가 존재하는 `fin_charts/`에만**
정당하다(Codex가 frozen `types.py` 뒤에서 병렬 작업). 지시서·오버레이는 Claude 단독 작업이라 계약 경계가
없고 유지보수 비용만 늘므로 기존 `report_*` 확장이 옳다. `fin_charts/`는 지시서 그대로 신규 유지.

### FVD2 — ★ 폰트(§12-1): config 상수화, 기본 NanumGothic

DesignTokens 폰트를 `engine/config.py` 상수(`FIN_NUM_FONT_KO/EN`)로 두고 기본값을 **러너 설치·라이선스
확인된 NanumGothic**(=`MANIM_FONT`)으로 확정. Anton은 Google Fonts OFL로 임베딩 안전, 에스코어드림 9 Black은
임베딩 라이선스 최종 확인 후 env로 opt-in. 렌더 구조는 폰트 교체와 독립이라 확정 없이도 진행 가능.
**법률 판단(에스코어드림 임베딩 라이선스)만 사용자 몫으로 남김.**

### FVD3 — ★ Veo 폴백(§12-2): EDITORIAL_MOTION

`config.FIN_VEO_FALLBACK_DEFAULT = "EDITORIAL_MOTION"`(코드 오프닝 자동 폴백). Veo 생성 실패/캡 초과 시
유료 재시도 없이 코드 도표 오프닝으로 대체.

### FVD4 — 시각 하드블록은 텍스트 블록과 별개 게이트

`engine/report_compliance.check`는 텍스트 컴플라이언스 하드블록을 **의도적으로 비활성**(항상 `blocked:False`,
사용자 결정)했다. 지시서 §6 V1~V8 시각 게이트는 이를 되돌리지 않는다 — **`chart_ref` 기준의 별개
시각/차트-데이터 게이트**(`validate_fin_visual`)로 도입하고, 텍스트 `blocked`는 건드리지 않는다.

### FVD5 — Manim 제약을 계약에 내재(Codex 핸드오프)

`fin_charts` 템플릿은 (a) 자유 Manim 코드 생성 금지, (b) **LaTeX 금지(Tex/MathTex/DecimalNumber 금지, 숫자도
`Text`)**, (c) 순수 로직은 manim 없이 import 가능해야 한다(collect/score/draft 러너에 manim 없음 —
`engine/requirements.txt`에 미포함, `render.yml`만 별도 설치). `engine/manim_templates.py` 상단 규약을 계승해
`engine/fin_charts/types.py` 계약에 명시했다.

## 아키텍처 (정합 후)

```
신규 (Codex 경계):  engine/fin_charts/  types.py(FREEZE·Claude) + templates/*.py 5종·validate.py(Codex)
확장 (기존 report_*):
  지시서   engine/report_directive.py   (normalize 뒤 Arc A·reveal_policy·veo_policy·chart·overlay_plan 재부착)
  렌더     engine/report_render.py · engine/providers/video.py  (code_chart $0 seam·Veo≤1·motion 합류·cost 재계산)
  오버레이 engine/report_render._disclaimer_footer · engine/report_attribution.py  (overlay_plan·fact_ref·면책≥2s)
  QA/게이트 engine/render_qa.py · engine/report_compliance.py  (§9 + 시각 chart_ref 게이트)
  화면     web/*  (Violation 패널·차단 잠금)
  트윈     supabase/functions/generate-report-draft/index.ts  (Fact Sheet 구조화 시 동기화)
```

## 진행 상황 (Phase 0 완료)

- **Phase 0 (계약 FREEZE + config):** 완료·검증.
  - `engine/fin_charts/types.py` — DesignTokens·ChartMotion(§3-3)·5종 params·NumberFact(§3-1 구조화 사실)·
    ManimSceneSpec·Violation + `build_scene`/`validate_fin_visual`/`check_chart_data_fit` 시그니처 동결
    (Codex가 채움) + 순수 `resolve_fact`. **manim import 0.**
  - `engine/config.py` — `FIN_*` 상수(scene roles·reveal/veo policy·cost cap·disclaimer·design tokens).
  - `tests/test_fin_pipeline.py` — 계약 import 가드(manim 미설치 import)·토큰·모션 clamp·dual_marker 금지필드
    부재·resolve_fact·스텁 NotImplementedError. **9/9 통과**(+ config 소비 기존 테스트 회귀 없음).
- Codex는 이 시점부터 `fin_charts/templates/*`·`validate.py` 병렬 착수 가능.

### Phase 1 — 구조화 Fact Sheet (완료·검증)

**핵심 설계 결정 (FVD6): `numbers` 변형 대신 병렬 `number_facts` 추가.**
- 당초 계획은 `report_factsheet.numbers`(문자열 리스트)를 구조화 객체로 **치환**하는 것이었으나, 탐색 결과
  `numbers`는 `report_scriptgen`·`report_selfcheck`(직렬화 근거대조)·`web/lib/reportTypes.ts`·엣지트윈
  `generate-report-draft/index.ts`·기존 테스트가 **`list[str]`로 소비**한다. 치환 시 라이브 리포트 파이프라인과
  (Deno 부재로 이 세션에서 타입체크 불가한) 엣지 트윈을 동시에 건드려야 해 위험.
- → **`numbers`(문자열 리스트)는 불변 유지**하고, 구조화 사실을 **새 `number_facts[]` 필드**로 추가한다.
  `numbers`는 `number_facts[].display`에서 **파생**해 기존 소비자 계약을 그대로 만족. 차트는 `resolve_fact`로
  `number_facts`의 `fact_id`를 참조(안티-환각). 공개 계약 `resolve_fact(fact_sheet, fact_id)` 시그니처 불변이라
  Codex·검증기 무영향(내부 소스 필드만 number_facts 로).
- **트레이드오프:** 엣지 트윈은 아직 `number_facts`를 산출하지 않는다(클라우드 초안엔 구조화 사실 없음).
  단 이는 **graceful**(numbers 동작 동일, number_facts 부재 시 resolve_fact 가 None → V7 미참조로 잡음)하고
  fin 차트 경로는 엔진측(`python -m engine.report_draft`)이라 영향 없음. **Phase 1b(엣지 트윈 number_facts +
  web number_facts 표시)는 Deno 배포·타입체크 가능 시점의 후속**으로 유예(divergence 문서화 = 이 항목).

**변경:**
- `engine/report_factsheet.py` — `FACTSHEET_SYSTEM`에 `number_facts` 구조화 스키마(fact_id·value·unit·period·
  metric·scope·basis·attribution·interpretation·source_page·display). `normalize_factsheet`가 구조화 정규화 +
  **결정론적 fact_id**(LLM 값 없으면 `num_{i}`) + **중복 fact_id 유일화**(참조 dangling 방지) + `numbers` 파생.
  레거시(number_facts 없이 numbers 문자열)도 수용해 합성. `interpretation`은 근거 없으면 neutral(자동 risk 금지).
- `engine/fin_charts/types.py` — `resolve_fact`가 `number_facts`→`numbers`(dict) 순 스캔. 계약 시그니처 불변.
- `tests/test_report_p1.py`·`tests/test_fin_pipeline.py` — 구조화/레거시 정규화·fact_id 유일성·numbers 파생·
  resolve_fact from number_facts. **51/51 통과**(report_p1·report_video·report_scoring·paper p1·fin 회귀 없음).

## 후속 백로그 (순차)

| Phase | 내용 | 최고위험 |
|---|---|---|
| 1 | ✅ **완료** — 구조화 `number_facts`(fact_id) 병렬 추가 + numbers 파생 back-compat | (해소) |
| 1b | 엣지 트윈(`generate-report-draft`) number_facts 산출 + web number_facts 표시 | Deno 타입체크·배포 후 검증 필요 |
| 2 | 지시서 확장(`report_directive` normalize 뒤 fin 필드 재부착, Veo≤1 preflight) | normalize 키 유실(재부착 필수) |
| 3 | 렌더/차트 seam(`providers/video.py` code_chart 지연 import·$0, cost 재계산·$0.40 캡) | manim-optional 지연 import·$0 경로 |
| 4 | 오버레이(overlay_plan·fact_ref·면책≥2s+덕킹) | 타이밍 코드 보장 |
| 5 | QA §9 + 시각 하드블록 + web Violation 패널 | 텍스트 blocked 재활성 금지 |
| 6 | LS v2 골드 통합 테스트 + Codex 병합 | manim 실렌더는 render.yml에서만 |

## 범위 밖(불변)
- 논문 comic 가이드·훅v2·selfcheck·PF1 대본 게이트는 불변.
- IG/TikTok 등 타 플랫폼 발행·분석, cron 무인 실행은 여전히 제외.
- v2 유형 라우팅·차트 확장(`time_series`·`waterfall_bridge`)은 v1 검증(파일럿) 후 실데이터 근거로 증분.
