# 이탈/결정 기록 — B1 데이터 에디토리얼 도입 + A/B 추천·선택 (집중 슬라이스)

> ★ **2026-07-28 폐기.** editorial(B타입)은 코드에서 제거됐다. 근거·되돌리는 법:
> `docs/deviation-webtoon-b1-removal.md`. 이 문서는 이력 보존용으로만 남긴다.

> CLAUDE.md 작업규칙 6 — "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고
> `docs/`를 갱신하며 근거를 남긴다." 에 따른 기록.
> 원본 명세: `docs/수정명세서_B1_editorial_v3.1.md`(업로드본, 커밋 후 frozen).

## 무엇을 하나
기존 A타입(만화 comic) 외에 **B타입 = 데이터 에디토리얼(editorial)** 버전을 추가하고, 논문마다
**A/B 를 규칙기반으로 추천**한 뒤 운영자가 **고른 타입으로 지시서→렌더**하게 한다. 명세 B1 v3.1 의
P0 항목 중 이번 PR 은 **집중 슬라이스**만 반영한다(사용자 승인).

## 확정 결정 (사용자)
- **B = 데이터 에디토리얼(명세 원안).** 사용자 요청 문구의 "과학실사(포토리얼)"가 아니라, 명세대로
  잡지형 에디토리얼 톤(타이포·데이터 시각화, 실사 최소)으로 확정. → 명세 수정 없이 freeze.
- **범위 = 집중 슬라이스.** editorial 버전(프롬프트+정규화+렌더 관통) · A/B 규칙기반 추천 배지 ·
  A/B 선택 UI · `motion_prompt` 컷 필드 배선 · Python↔TS 프롬프트 동기화 테스트.
- **추천 = 규칙기반**(Fact Sheet 신호, 명세 §7). LLM 추천은 후속 옵션.

## 런타임 탐색 결과 (명세 §2 — 경로를 추정하지 않고 확정)
명세가 "재사용"이라 표현한 일부는 **실제 코드에 존재하지 않는다.** 착수 전 grep/정독으로 확정:

- **`version_type` 현재값 = `comic` | `image_sequence` 둘뿐**(`engine/config.py:226` `VIDEO_VERSIONS`,
  기본 `image_sequence`). 구 `animation`/`hybrid` 는 config 에서 제거됨(레거시 렌더 분기·저장행만 잔존).
  대시보드는 `comic` 단일로 좁혀져 있음(`web/app/api/directive-generate/route.ts:9`,
  `web/components/DirectiveClient.tsx:27`, `web/app/directive/[paperId]/page.tsx:10`).
- **명세 §3-3 의 `$1.30` 경고 게이트·`cost_class`(STANDARD/ENHANCED)·`estimated_cost_usd` 헤더 필드는
  코드에 없다.** 실제 비용 게이트는 **주제당 이중 캡**(`VIDEO_MAX_COST_USD_PER_TOPIC`=$0.40 /
  `VIDEO_MAX_GENERATED_SEC_PER_TOPIC`=8초) preflight(`engine/directive.py:278`
  `preflight_video_budget`). `estimated_cost_usd` 는 호출별 원장 문자열일 뿐(`engine/cost.py`).
  → 명세의 비용 게이트는 **후속 PR** 에서 실제 비용모델과 정합해 구현(이번 슬라이스는 갭을 만들지 않음).
- **명세 §3-2 의 컷 필드 `scene_role`/`motion_prompt`/`overlay_plan`/`viz_template` 는 현재 전부 없음.**
  서사 역할은 `render_notes` 앞 대괄호 태그로만 존재(`directive.py:66`). 모션은 단일 플래그
  `motion_source`(video|still)뿐. 이번 PR 은 그중 **`motion_prompt` 만** 승격(명세 §3-2, 통합명세 §4-5
  "대본 video_prompt 가 렌더에서 미소비" 결함의 해법).
- **A/B 추천/라우팅 로직은 전무.** 버전 선택은 수동뿐이며 그마저 comic 단일로 닫혀 있었다.
- **Manim 은 4종 단일 모듈**(`engine/manim_templates.py`: title/arrow_flow/step_reveal/number_compare).
  `engine/viz_templates/` 디렉터리 없음. 명세 §5 의 5종은 후속.

## 이번 슬라이스 구현
1. **editorial 버전**: `config.VIDEO_VERSIONS`에 `editorial` 추가, `VERSION_VISUAL_TYPE["editorial"]="image"`,
   `VERSION_DEFAULT_SCENE_KIND["editorial"]="broll_stock"`. `directive.py`/edge TS 에 `VERSION_GUIDANCE["editorial"]`
   신설(명세 §4-1 문안: 잡지형 톤 앵커·장식보다 증거·색 1+1+1). **훅·리텐션 v2 블록(P1~P5)은 불변**(명세 §4-2).
   에디토리얼 톤 스틸이 기존 이미지 프로바이더로 렌더되고, LLM 이 수치 컷에 `data_viz`를 지정하면 기존
   `number_compare` Manim 템플릿이 쓰인다(신규 렌더러 없이 관통).
2. **motion_prompt**: 컷 스키마·정규화(양쪽)·출력 스키마 안내 추가. Veo 프롬프트 join
   `", ".join([global_style, visual_prompt, motion_prompt])`(`providers/video.py`), `content_hash`(`assemble.py`)
   에 포함. still 컷은 무시. `web/lib/types.ts` Cut + 지시서 UI 표시.
3. **규칙기반 추천**(`web/lib/recommend.ts`): Fact Sheet 4신호(대표수치·전후비교·규모차·추세) 중 2개 이상 →
   B(editorial) 추천, 근거 한 줄. 지시서 상세 페이지가 draft.fact_sheet 로 계산해 탭에 배지 표시.
4. **A/B 선택**: 버전 enum·메타·라우트를 editorial 까지 개방. 탭 클릭→`?v=editorial`→그 버전으로 생성.
5. **동기화 테스트**(`tests/test_prompt_sync.py`): editorial/comic 가이드 핵심 앵커가 Python·TS 양쪽에
   존재/일치하는지 단언(f-string↔template literal 이라 바이트 동일이 아닌 앵커 세트 동치).

## 후속 PR 백로그 (명세에 있으나 이번 제외)
- `overlay_plan` 구조화 오버레이 배선(ASS `[Events]` 레이어, `subtitles.build_ass`).
- Manim viz 템플릿 5종(split_compare/before_after/number_scale/threshold_reveal/causal_chain) +
  `viz_template`/`viz_params` 필드 + 생성호출 0 배선(명세 §5).
- `scene_role` 8종 필드 승격(현재 render_notes 대괄호).
- 비용 게이트(`estimated_cost_usd`/`cost_class`/$1.30 배지) — 실제 주제당 캡 모델과 정합.
- 첫 3초 QA 5항목(`render_qa`).

## 검증
- 순수 로직: `pytest`(기존 무회귀 + `test_prompt_sync` + motion_prompt Veo join 단언).
- 대시보드: `npm run lint && npm run build` + `recommend` 단위테스트.
- **미검증(운영)**: LLM 이 editorial 규격대로 채우는지·실제 mp4 렌더는 라이브 키/러너 필요 →
  editorial 1편 실렌더는 운영 단계에서 확인(명세 §10 DoD).
