# 수정명세서 — 하루한편 표현방식 개선 B1 도입 (v3.1 · GPT v3 리뷰 반영판)

> ★ **2026-07-28 폐기.** editorial(B타입)은 코드에서 제거됐다. 근거·되돌리는 법:
> `docs/deviation-webtoon-b1-removal.md`. 이 문서는 이력 보존용으로만 남긴다.
- 상태: draft (GitHub 커밋 후 frozen)
- 대상: video-article 기존 코드베이스 (Python 엔진 + Supabase Edge Function + Next.js)
- 원본 검토 문서: `논문_Shorts_영상표현방식_개선_통합명세서_v3.md` (GPT 작성)
- 정합 기준 문서: `수정지시서_하루한편_훅리텐션_파이프라인개정_v2.md` / `규격서_트렌디숏폼_v2.md` / `영상제작_프롬프트_통합명세.md`

---

## 0. 결론 (두괄식)

**GPT v3에서 실행할 것은 "B1 데이터 에디토리얼 1종 + motion_prompt 분리 + overlay_plan + Manim 5종 + 첫 3초 QA"뿐이다.** 나머지(길이 40~60s 고정, BGM 수동화, 템플릿 15종, format_type 신설, B2/B3)는 기각 또는 P1 이후로 미룬다. 훅·리텐션 규칙은 이미 v2로 `DIRECTIVE_SYSTEM`에 반영돼 있으므로 재작업하지 않는다.

**단일 변수 원칙:** 이번 변경의 실험 변수는 "표현방식(comic vs editorial)" 하나다. 길이·훅·BGM·업로드 시간은 이번 변경에서 건드리지 않는다 (EN 업로드 시간 분리는 코드 무관 운영 변경이므로 별도·병행 가능).

---

## 1. GPT v3 판정표 (수용/수정/기각 근거 고정)

| GPT v3 항목 | 판정 | 근거 |
|---|---|---|
| B타입 철학 (증거가 화면에서 작동) | ✅ 수용 | LS일렉트릭 v2가 이미 이 문법. 이긴 축(담합 107%·격차4배 65%)이 전부 수치·비교형 |
| `motion_prompt` 분리 | ✅ 수용 (P0) | 프롬프트 통합명세 §4-5와 독립 수렴 — 대본 `video_prompt`가 렌더에서 미소비되는 기존 결함의 해법 |
| `overlay_plan` + 생성 텍스트 금지 | ✅ 수용 (P0) | 불변식 I1(`BURN_IN_NEGATIVE_PROMPT`)과 일치, 구조화 승격 |
| 비용 하드게이트($1.30 경고)·실패 기록 | ✅ 수용 (P0) | `generation_attempts` 레저 패턴 재사용 |
| `scene_role` 8종 | ✅ 수용 (P0) | 현행 render_notes 대괄호 표기의 필드 승격 |
| 첫 3초 QA | ✅ 수용 (P0) | 훅 v2 P1과 정합 |
| 영상 길이 40~60s (중심 42~52s) | ✏️ 수정 | 격차4배 64s·LS 70s·틱톡 65~75s와 충돌. M(40~54s) "우선 가설"로만, 강제 금지. 길이는 별도 실험 변수 |
| BGM YouTube Studio 수동 적용 | ❌ 기각 | Stable Audio 3 + `bgm_library` + ffmpeg 믹싱 기확정(비용 0·자동화). 단 SFX 큐 토큰은 P1 수용 |
| Manim 템플릿 15종 | ✏️ 수정 | 5종만 P0 (§5). 솔로 스케일 과투자 방지 |
| `format_type`/`b_style` 신규 필드 | ✏️ 수정 | `version_type` enum 확장으로 대체 (§3). 이중 체계 금지 |
| B2 시네마틱 / B3 테크 시뮬레이션 | ⏸ P1 보류 | B1 판정(10편 중앙값) 후 |
| 초기 30일 B 50~70% | ✏️ 수정 | "B1 적합 주제에만 B1" 라우팅. 비율 강제 없음 (v2 §8 고착방지 원칙과 동일 사상) |
| 훅·리텐션 절(§2.2, 5.4~5.5 일부) | ❌ 중복 기각 | v2로 기구현 (`DIRECTIVE_SYSTEM` P1~P5). 재작성 금지 — 드리프트 원천 |
| 90일 게이트 수치 | ✏️ 수정 | 목표는 가설로 유지하되 판정 방식은 v2 §9(중앙값·길이구간·주제군 통제·표본 규칙) 준수 |

---

## 2. 런타임 탐색 (구현 전 필수 — 경로를 추정하지 말 것)

Claude Code는 코드 수정 전 아래를 grep으로 확정하고 결과를 커밋 메시지/PR 본문에 기록한다.

```bash
# 1) 지시서 생성·정규화 실제 위치
grep -rn "DIRECTIVE_SYSTEM_BASE\|normalize_directive\|VERSION_GUIDANCE" engine/
# 2) 렌더가 컷 필드를 소비하는 지점 (visual_prompt → 이미지/Veo)
grep -rn "visual_prompt\|motion_source\|global_style" engine/providers/ engine/assemble* engine/render*
# 3) Manim 템플릿 선택기
grep -rn "select_template" engine/manim_templates.py
# 4) 이중관리 TS 사본
ls supabase/functions/generate-directive/ supabase/functions/generate-draft/
# 5) 오버레이/자막 합성 경로 (overlay_plan 배선 지점)
grep -rn "text_overlay\|ass\|drawtext" engine/subtitles* engine/assemble*
```

---

## 3. 스키마 변경 (인터페이스 계약 — Claude Code만 변경)

### 3-1. `version_type` 확장 (신규 필드 대신)

```
version_type: "comic" | "editorial" | "image_sequence"(deprecated)
```
- `comic` = 기존 A타입. 변경 없음.
- `editorial` = B1 데이터 에디토리얼. 신규.
- `image_sequence` = deprecated 마킹만 (제거는 별도 결정 — 통합명세 §4-6).
- B2/B3은 이번에 enum에 넣지 않는다 (P1에서 추가).

### 3-2. 컷 스키마 추가 필드 (directive.cuts[])

```json
{
  "scene_role": "HERO|COMPARE|MECHANISM|SCALE|EVIDENCE|IMPACT|CAVEAT|PAYOFF",
  "motion_prompt": "<카메라·피사체·레이어 모션 전용 영문. visual_prompt와 분리>",
  "overlay_plan": [
    { "type": "NUMBER|LABEL|GRAPH|LINE|MASK|HIGHLIGHT",
      "content": "<렌더 레이어가 그릴 정확한 텍스트/수치/그래프 파라미터>",
      "timing": "<in_sec,out_sec>" }
  ],
  "viz_template": "<split_compare|before_after|number_scale|threshold_reveal|causal_chain|''>",
  "viz_params": { }
}
```
- `motion_prompt` 소비 규칙: `motion_source=video` 컷의 Veo 프롬프트 = `", ".join([global_style, visual_prompt, motion_prompt])`. still 컷에서는 무시.
- `overlay_plan.content`의 수치는 반드시 `source_facts`가 가리키는 Fact Sheet 값과 문자열 일치해야 한다 (정규화 단계 검증).

### 3-3. header 추가 필드

```json
{ "estimated_cost_usd": 0.0, "cost_class": "STANDARD|ENHANCED" }
```
- `normalize_directive`가 컷 구성(이미지 수·video 컷 수)으로 **재계산** (모델 자기보고 불신 패턴 유지).
- STANDARD 예상비용 > **$1.30** → 승인 UI 경고 배지 (렌더 차단 아님).
- ENHANCED는 사람 승인 시에만 렌더 가능. Veo 클립 +1 허용, 그 외 상한 동일.

---

## 4. 프롬프트 변경

### 4-1. `VERSION_GUIDANCE["editorial"]` 신설 (기존 comic 가이드는 불변)

```
[버전=에디토리얼 editorial] 논문의 증거·수치·비교가 화면에서 직접 변화하는 데이터 에디토리얼로 만든다.
★원칙: 장식보다 증거 / 이미지 추가보다 한 에셋의 상태 변화 / 생성영상보다 코드 그래픽·합성.
- global_style: 잡지형 에디토리얼 톤 앵커 한 줄 고정 (예: 'clean editorial magazine layout,
  high-contrast typography zones, structured grid, limited palette: 1 base + 1 support + 1 accent,
  generous negative space'). 모든 컷 visual_prompt는 이 앵커로 시작.
- 각 컷에 scene_role을 지정하고 HERO는 반드시 컷1이다 (훅 v2 P1 '증거 선공개'와 동일 — 규칙을 재기술하지 말고 따르라).
- 수치·그래프·비교가 핵심인 컷은 asset을 생성 이미지 대신 viz_template + viz_params로 지정하라
  (허용: split_compare / before_after / number_scale / threshold_reveal / causal_chain).
  viz_params의 모든 수치는 source_facts의 Fact Sheet 값 그대로만.
- 화면 텍스트·숫자는 전부 overlay_plan으로. visual_prompt에는 'no on-screen text' 유지 (불변식 I1).
- motion_source=video 컷은 motion_prompt에 모션만 별도 작성 (visual_prompt에 모션 구절 넣지 말 것).
- 색: 기본 1 + 보조 1 + 강조 1. 강조색은 위험·반전·핵심수치에만.
- 동일 구도 4초 이상 금지, 동일 전환 2연속 금지, 1.5~2.5초마다 작은 상태 변화 (overlay 등장/마스크/확대 포함).
```

### 4-2. 건드리지 않는 것 (명시적 금지)
- `DIRECTIVE_SYSTEM_BASE`의 훅·리텐션 블록(P1~P5) — **수정 금지.** GPT v3의 유사 문구로 교체하지 않는다.
- `SCRIPT_SYSTEM`의 웹툰 화풍 앵커 — comic 경로 전용으로 유지. editorial 초안은 지시서 단계에서 재연출되므로 대본 프롬프트는 이번에 변경하지 않는다.
- Fact Sheet / selfcheck 프롬프트 — 불변.

### 4-3. 이중관리 동기화
- `supabase/functions/generate-directive/index.ts`에 위 변경을 동일 반영.
- 통합명세 §4-8 권고대로, 이번 PR에 **Python↔TS 프롬프트 문자열 diff 테스트**를 함께 추가한다 (`tests/test_prompt_sync.py` — 두 소스에서 핵심 블록을 추출해 비교, diff 0 요구).

---

## 5. Manim/코드 그래픽 템플릿 5종 (P0)

기존 4종(`title/arrow_flow/step_reveal/number_compare`)에 추가. **자유 코드 생성 금지 원칙 유지** — 고정 템플릿 + 검증된 파라미터만.

| 템플릿 | 용도 | 필수 params |
|---|---|---|
| `split_compare` | A vs B 좌우 분할 비교 | left/right {label, value, unit}, winner_side |
| `before_after` | 전후 슬라이드/와이프 | before/after {label, value}, wipe_dir |
| `number_scale` | 대표 수치 카운트업 + 단위 맥락 | value, unit, count_dur_sec, context_label |
| `threshold_reveal` | 기준선·임계치 등장 후 실측값 배치 | threshold {label, value}, actual {label, value} |
| `causal_chain` | 원인→과정→결과 단계 변화 | steps[] {label, icon_token}, reveal_interval |

공통 규격: 1080×1920 내 콘텐츠 박스(규격서 §0.2), 디자인 토큰은 header `global_style`에서 파생한 3색 팔레트, 숫자 폰트 에스코어드림 9 Black(KO)/Anton(EN) — 임베딩 라이선스 확인 항목은 기존 open item 유지.

렌더 배선: `asset_source`가 viz_template인 컷은 이미지 생성 호출을 **건너뛰고** Manim 렌더 → 비용 $0, 비용 계산기에서 생성 호출 수 미포함 (GPT §7.4 수용).

---

## 6. QA 추가 (첫 3초 + editorial 재질)

`render_qa`에 추가 — 실패 시 승인 UI 경고 (자동 재생성은 P1):
- [ ] 컷1이 HERO인가 / 첫 프레임 핵심 문구가 KO 4~10자·EN 2~5단어 이내인가
- [ ] 첫 3초 내 화면 상태 변화 ≥2회인가 (overlay in/out 포함, 타임라인으로 판정)
- [ ] overlay_plan 수치 ↔ Fact Sheet 문자열 일치 (불일치 = 빨간 플래그)
- [ ] editorial인데 comic_panel 컷 비중 > 30% (혼합 금지 위반)
- [ ] 동일 transition 3연속 / 동일 viz_template 3연속

기존 QA(MP4 프레임 자막 실검·싱크·세이프존·무음·검은 프레임)는 v2 §7 그대로.

---

## 7. 운영·측정 (코드 외)

- **EN 채널 예약 발행 시간 분리 (즉시, 이 명세와 독립 실행):** EN = US ET 11:00~13:00 창(KST 00:00~02:00), KR = 기존 유지. 4주 후 EN `view_choice_rate`·트래픽 소스 지역 비중으로 판정.
- B1 판정 규칙 = v2 §9 그대로: 중앙값, 같은 길이구간·주제군끼리, 5편=오류탐지/10편=방향성/20편+=전략. 지표는 PA 명세 공식 용어(`engaged_views`, `view_choice_rate`, `avg_percentage_viewed`)만 사용.
- B1 라우팅: 대표 수치·전후 비교·규모차·그래프화 가능 중 **2개 이상** → editorial 후보 (GPT §6.2 수용). 비율 강제 없음.
- B2/B3·SFX 큐·첫 프레임 자동 평가 = P1 백로그.

---

## 8. 파일 소유권 (무간섭)

| 경로 | 소유 | 내용 |
|---|---|---|
| `engine/directive.py` (+TS 사본) | Claude Code | enum 확장·editorial 가이드·normalize 검증·비용 재계산 |
| `engine/providers/video.py` | Claude Code | motion_prompt 합류 |
| `engine/assemble*` / `subtitles*` | Claude Code | overlay_plan 배선 |
| `engine/render_qa.py` | Claude Code | §6 게이트 배선 |
| `engine/viz_templates/*.py` (신규) | **Codex** | 5종 템플릿 순수 파라미터→Scene 빌더 + 단위테스트 (I/O 금지) |
| `engine/viz_templates/types.py` | Claude Code | params 타입 계약 (FREEZE) |
| `tests/test_prompt_sync.py` | Claude Code | Python↔TS diff 가드 |
| `web/components/ReviewClient.tsx` | Claude Code | 비용·QA 경고 배지 |

## 9. 구현 순서

1. Claude Code: §2 런타임 탐색 → §3 계약 확정 → spec 커밋 (freeze)
2. 병렬: Claude Code(스키마·프롬프트·배선) / Codex(viz_templates 5종 + 테스트)
3. Claude Code: 통합 + TS 동기화 + diff 테스트
4. editorial 1편 실렌더 → QA 통과 → 운영 투입 (수치·비교형 논문부터)
5. Codex: read-only 적대 리뷰 (`normalize_directive` 검증 로직·overlay 수치 대조 중심)

## 10. Definition of Done

- [ ] editorial 지시서 1편이 LLM 자동 생성 → 승인 → mp4 (KO/EN, 에셋 공유) 완주
- [ ] viz_template 컷의 생성 API 호출 = 0 (비용 로그로 확인)
- [ ] editorial 1편 실비용 ≤ $1.25 (한·영 합산, 실패 호출 포함)
- [ ] Python↔TS 프롬프트 diff 테스트 통과
- [ ] 첫 3초 QA 5항목이 승인 UI에 표시

## 11. 열린 질문 (가정으로 진행, 확인 필요)

1. **훅 v2가 엣지 함수(TS)에도 이미 반영됐는가** — Python 원문 기준으로만 확인됨(통합명세 §4-8 미해결). 탐색 단계에서 diff로 확정.
2. 에스코어드림 9 Black / Anton **임베딩 라이선스** — 기존 미결 항목, editorial 숫자 렌더에 쓰기 전 확정.
3. `hook_promise_check.pass=false` 시 실제 차단 여부(통합명세 §4-4) — 이번 범위 밖이나, 탐색 시 겸사 확인해 기록.
