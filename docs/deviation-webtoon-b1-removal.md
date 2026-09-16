# 이탈/결정 기록 — 웹툰(장면 파생) 버전 도입 · 에디토리얼 폐기 · 버전×언어 동시 발주

> CLAUDE.md 작업규칙 6 — "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고
> `docs/`를 갱신하며 근거를 남긴다." 에 따른 기록.
> 원본 지시서: 업로드본 `claude_code_task_v2_webtoon_continuity.md`(이하 **지시서 v2**).
> 프로덕션 명세: `docs/수정명세서_웹툰버전_v1.md`.
> 작성 기준일: 2026-07-28

---

## 0. 결론 (두괄식)

| 항목 | 결정 | 상태 |
|---|---|---|
| 새 버전 `webtoon` | 도입 — 장면 몇 장만 생성하고 컷은 크롭으로 파생 | 구현 |
| 종횡비 ①9:16 | 프롬프트 텍스트 → **API 파라미터** | 구현. **실측 미완**(§4) |
| 화풍 ②부정어 | webtoon 프롬프트에 구조적으로 덧붙임 | 구현 |
| 레퍼런스 이미지 ③ | **범위 밖** — 별도 PR | 미착수(§3) |
| 크롭 파생 ④ | 렌더가 실제로 잘라낸다 | 구현 |
| 톤 그레이딩 ⑤ | 새 이미지 대신 색 입히기 | 구현 |
| editorial(B타입) | **완전 폐기** — 코드차트 경로 포함 | 구현(§2) |
| 버전×언어 동시 발주 | 지시서 생성·승인 양쪽 체크박스 | 구현 |

---

## 1. 왜 이 작업인가 — 1차 샘플이 실패한 이유

지시서 v2 §0 이 정리한 1차 실행 결과와, 그것을 코드에서 확인한 내용:

| 관찰된 실패 | 코드상 원인 | 이번 대응 |
|---|---|---|
| 생성 이미지 8장 전부 1024×1024 | `_image_request_body` 가 텍스트 파트 하나만 보내고 종횡비 파라미터가 없었다 | §4 |
| 컷마다 화풍이 튐(실사/페인팅/CG 혼재) | 부정어가 없고 `"high detail"` 이 실사를 유도했다 | §5 |
| 운석이 매 컷 다른 물체 | 접두사 텍스트로는 특정 물체를 지정할 수 없다 | 지속 오브젝트를 단순 형태로 고르라는 가이드(부분 대응) |
| `zoom_in`·`time_shift` 미성립, 스케일 붕괴 | **이미지 모델은 "같은 대상을 더 가까이"를 못 지킨다** | §6 — 크롭으로 전환 |

지시서 v2 의 핵심 결론이 그대로 이번 작업의 뼈대다:
**카메라 이동은 이미지 생성으로 하면 안 된다. 크롭으로 해야 한다.**

---

## 2. editorial(B타입) 폐기 — 기존 결정을 뒤집었다

### 뒤집은 결정
`docs/수정명세서_editorial앵커_언어추가_클립길이_v1.md` 는 이렇게 못박았다.

> editorial 노선은 폐기하지 않는다 / `version_type` enum 의 `editorial` 은 그대로 둔다(롤백 여지 유지)

**운영자 결정(2026-07-28)으로 이를 뒤집는다.** 근거는 그 문서 자신이 남긴 진단이다 —
`docs/deviation-clip-fit-add-language.md` §1[A] 가 `viz_template`·`viz_params`·`asset_source`·
`overlay_plan` 이 **저장소 전체 grep 0건**임을 확인했고, 결론이 "editorial 은 프롬프트 가이드만
있고 시각 산출 경로는 comic 과 동일"이었다. 즉 롤백해 봐야 돌아갈 구현이 없다. 그 자리를
웹툰 버전이 대신한다.

### 지운 것
- `engine/config.py` — `VIDEO_VERSIONS`·`VERSION_VISUAL_TYPE`·`VERSION_DEFAULT_SCENE_KIND`
- `engine/directive.py` + 엣지 트윈 — `VERSION_GUIDANCE["editorial"]`
- `engine/render.py` — `render_kind_for_scene` 의 `editorial + data_viz → 코드차트` 분기
- `web/lib/recommend.ts` + 테스트 — A/B 규칙기반 추천(추천할 대상이 사라졌다)
- UI 탭·라우트 enum(`directive-generate`, `DirectiveClient`, `directive/[paperId]`)

### 잃는 것 (명시)
1. **A/B 규칙기반 추천 배지.** Fact Sheet 4신호로 comic/editorial 을 추천하던 기능. 지금은
   운영자가 두 버전을 **둘 다 만들어 비교**하므로 추천의 역할이 줄었다.
2. **data_viz 코드차트(Manim).** 화면에 뜨는 숫자는 `overlay_plan`(ASS 레이어)이 담당하므로
   기능 공백은 없지만, 도형 기반 비교 그래픽은 사라졌다.
3. **저장된 `version_type='editorial'` 행의 조용한 품질 변화.** 그 행들은 계속 렌더되지만
   `data_viz` 컷이 코드차트 대신 스틸로 나간다. DB 마이그레이션이 없어(`version_type` 은
   CHECK 없는 free text) 행 자체는 그대로다.

### 지우지 **않은** 것과 그 이유
- `engine/claim_viz.py`·`engine/manim_templates.py` — 고아가 아니다. `manim_templates.py:19` 가
  `claim_viz` 를 import 하고 `:66` 이 호출하며, `--demo-anim`(`_demo_anim_directive`) 경로가
  살아 있다. 지우려면 데모 경로와 테스트 4건을 함께 걷어내야 해 **별건**이다.
  프로덕션 버전에서는 도달 불가 = 기능적으로 폐기다.
- `engine/render.py:attach_fact_sheet` — 20줄, 통과 테스트 3건. 코드차트를 되살릴 때 다시 필요하다.
- `scene_kind = data_viz` — editorial 전용이 **아니다.** 컷 길이 상한 12초
  (`config.DATA_VIZ_CUT_MAX_SEC`, `content_mode.cut_max_sec`)와 `SCENE_HIGH_EFFORT_KINDS` 멤버로
  `enforce_scene_variety` 의 대체 우선순위에 쓰인다 — comic 도 쓴다. 없애면 comic 출력이 조용히 바뀐다.

### ★ 문자열 오탐 — 건드리면 안 되는 "editorial" 4종
폐기 작업에서 가장 위험한 것은 문자열 일괄 치환이다. 아래는 **버전과 무관**하다.

| 대상 | 위치 | 정체 |
|---|---|---|
| `editorial_inference` | `engine/selfcheck.py`, `generate-draft/index.ts`, `web/lib/types.ts` | 주장충실도 자기검증 축 |
| `work_type == "editorial"` | `engine/models.py` | OpenAlex 문서 유형 필터 |
| `editorial_composite` | `engine/config.py` `FIN_ASSET_SOURCES` | 금융 라인 에셋 소스 |
| `clean editorial illustration` | `VERSION_GUIDANCE["image_sequence"]` | 레거시 폴백 톤 앵커 |

`tests/test_prompt_sync.py::test_editorial_false_positives_are_left_alone` 이 이 넷을 지킨다.
그리고 부재 단언은 맨 `"editorial"` 이 아니라 **버전 토큰 형태**(`'"editorial":'`,
`'"editorial",'`, `'  editorial:'`)로만 잡는다.

### 되돌리는 법
삭제 PR 을 revert 하면 된다. 마이그레이션도, 데이터 변경도 없다.

---

## 3. 레퍼런스 이미지 입력(지시서 v2 §4)을 범위 밖으로 뒀다

지시서 v2 §1 은 "Gemini 는 `contents` 배열에 이미지 파트를 담을 수 있다. 1차에서 '미지원'으로
판단했다면 실제로는 현재 코드가 텍스트만 보내고 있을 가능성이 높다"고 했고, 그 추측은 맞다 —
`scripts/sample_continuity/PATHS.md` 가 `_image_request_body` 가 `parts` 에 `text` 하나만 넣는다는
것을 코드로 확인했다.

그럼에도 이번에 넣지 않았다.
1. 요청 바디 **구조**를 바꾸는 일이고, 실시간·Batch 가 같은 함수를 공유해 영향 범위가 넓다.
2. **라이브 키 없이 검증할 수 없다.** 개발 샌드박스에 `GEMINI_API_KEY` 가 없어서 "레퍼런스가
   실제로 화풍을 고정하는가"를 확인할 방법이 없고, 검증되지 않은 채로 넣으면 실패해도 모른다.
3. 종횡비(§4)조차 아직 실측 전이다. 지시서 v2 절대규칙 4 는 "§2 종횡비가 확보되지 않으면 §4로
   넘어가지 않는다"고 했다 — 그 순서를 지킨다.

→ **별도 PR.** 화풍 일관성은 그때까지 `global_style` 접두사 + 부정어가 책임진다.

---

## 4. 종횡비 필드 경로가 확정되지 않았다 (열린 항목)

공식 문서에서 두 형태가 동시에 나온다.

```
generationConfig.imageConfig.aspectRatio            # SDK ImageConfig 의 REST 직렬화
generationConfig.responseFormat.image.aspectRatio   # 현행 image-generation 문서의 curl 예시
```

그리고 `ai.google.dev/api/generate-content` 의 GenerationConfig 필드 목록에는 **어느 쪽도**
렌더되지 않는다. 지시서 v2 §2 가 "추측하지 말 것"이라고 한 이유가 이것이다.

**대응 3층**
1. 필드 경로를 `config.IMAGE_ASPECT_CONFIG_SHAPE` 상수로 빼고 두 형태를 모두 지원한다.
   `IMAGE_ASPECT_RATIO_PARAM=false` 로 즉시 이전 동작으로 되돌아간다(Batch API 계약 주석의 선례).
2. `scripts/verify_image_aspect.py` 가 **두 형태를 실제로 호출**하고 `PIL.Image.open(p).size` 를
   찍는다. 통과한 형태를 config 기본값으로 확정한다.
3. 파라미터가 먹었는지 믿지 않는다 — `_gen_still` 이 생성 직후 크기를 재고 9:16 이 아니면
   에러 로그 + `render_assets.meta.aspect_mismatch=true` 를 남긴다. **예외는 던지지 않는다**
   (던지면 유료 호출이 재시도된다).

**미검증:** 개발 샌드박스에 `GEMINI_API_KEY` 가 없어 실측하지 못했다. Actions 탭 →
`sample-continuity` 워크플로 → step=`verify-aspect` 로 러너에서 확인한다.
**9:16 이 확보되기 전에는 webtoon 을 운영에 쓰지 않는다**(지시서 v2 절대규칙 4).

---

## 5. 화풍 부정어를 프로바이더가 구조적으로 덧붙인다

지시서 v2 §3 이 "부정어가 핵심이다. 없으면 모델이 실사 쪽으로 되돌아간다. 1차 실패의 직접
원인이다"라고 했다. 그래서 두 겹으로 넣었다.

1. `VERSION_GUIDANCE["webtoon"]` — LLM 에게 실사 유도 표현을 쓰지 말라고 지시(Python·TS 양쪽).
2. `engine/providers/image.py` — LLM 이 그 지시를 무시해도 프로바이더가
   `config.WEBTOON_NEGATIVE_PROMPT` 를 붙인다. 문구는 지시서 v2 §3 원문 그대로다.

그리고 `"high detail"`(실사 유도)을 webtoon 에서만 `"clean flat colors"` 로 바꿨다.

**comic 의 프롬프트 문자열은 바이트 단위로 불변이다.** A/B 비교에서 화면 설계 말고 다른 변수가
끼면 판정이 무의미해진다. `tests/test_image_prompt.py::test_comic_prompt_is_byte_identical_to_the_legacy_string`
이 이를 고정한다.

---

## 6. `source_scene` 대신 기존 `base_asset_ref` 를 썼다 (명세 이탈)

지시서 v2 §7 은 컷에 `"source_scene": "scene_B"` 를 두라고 했다. 그렇게 하지 않았다.

- **"이 컷은 어느 이미지를 쓰는가"의 진실원이 이미 있다.** `asset_strategy` +
  `base_asset_ref` 는 프롬프트 → 정규화 → 역참조 검증(`validate_reuse_refs`) → 렌더
  `asset_index` → 비용 계상(`compute_cost_plan`)까지 관통 배선이 끝나 있다.
- **비용 계산이 눈이 먼다.** `compute_cost_plan` 은 `ASSET_STRATEGY_REUSE` 멤버십으로 유료/무료를
  가른다. `source_scene` 만 있고 `asset_strategy=new_asset` 인 컷은 유료로 계상돼, 하필 이
  기능이 공짜로 만들려는 컷에서 확인 모달 금액이 틀린다.
- **"장면"은 곧 "그 장면을 만든 컷"이다.** 지시서 v2 의 "생성 4장 / 파생 4컷"은
  `new_asset` 컷 4개 + `reuse_crop|reuse_zoom` 컷 4개로 정확히 표현된다. 장면 태그는 이미 있는
  `visual_reuse_group` 이 맡는다.

→ 스키마 델타는 선택 필드 **2개**뿐: `crop{cx,cy,scale}`, `tone_grade`.
없으면 오늘 동작 그대로라 저장된 모든 지시서가 유효하다.

### 발견: 크롭 계약이 선언만 있고 죽어 있었다
`reuse_crop`·`reuse_zoom` 은 예전부터 스키마에 있었고 프롬프트도 쓰라고 지시했지만,
`engine/render.py:_reuse_base_image` 는 `shutil.copyfile` 뿐이었다 — **"확대"를 선언한 컷이
기준 컷과 픽셀 단위로 같은 그림으로 렌더됐다.** 지시서 v2 §6 이 지적한 문제의 코드상 실체다.

### 인접 결함 1건 동시 수정
영상 컷(`motion_source=video`)은 재사용 경로를 건너뛰고 무조건 새 스틸을 만들었고, 그 스틸이
`asset_index` 에 들어가지도 않았다. 그래서 "첫 장면으로 되돌아오는 마지막 영상 컷"이 같은
그림을 돈 주고 다시 만들었다 — 지시서 v2 컷 매핑의 마지막 컷이 정확히 이 경우다.

---

## 7. 안전 속성 — 파생 실패가 과금으로 이어지지 않는다

`_reuse_base_image` 는 크롭 중 어떤 예외가 나도 잡아서 **기준 이미지를 그대로 쓰는 것**으로
강등한다. 확대가 안 된 화면이 틀린 화면보다 낫고, 둘 다 새 이미지값보다 낫다.
`tests/test_shared_assets.py::test_broken_derive_falls_back_to_copy_not_generation` 이 이를 고정한다.

파생 컷은 `_gen_still` 에 들어가지 않으므로 캐시 조회·업서트·원장 기록·생성 호출이 전부 없다 —
**비용 0 이 구조적으로 보장된다.** 언어 독립도 유지된다(파일 연산에는 locale 이 없다).

**후속 주의:** 파생 컷을 나중에 `render_assets` 에 캐시하려면 `assemble.content_hash` 에
`crop`·`tone_grade` 를 **먼저** 넣어야 한다. 안 그러면 같은 기준에서 배율만 다른 두 파생 컷이
같은 캐시 키로 충돌한다. `assemble.py` 독스트링에 남겼다.

---

## 8. 버전×언어 동시 발주

언어 동시 렌더는 이미 있었다(`directive-approve` 의 `langs`). 없던 것은 **버전 동시**다.

- `web/components/VersionOrderBar.tsx`(신규)가 ⑤ 화면에서 버전 체크 × 언어 체크를 소유한다.
- `DirectiveClient` 를 다중 지시서로 만들지 **않았다.** 673줄이 지시서 1건의 편집 상태
  (`cuts`/`dirty`/`saving`/`locked`/`serverIdRef`)로 짜여 있어 N개를 들면 저장 충돌 표면이
  그만큼 늘어난다. 편집은 버전 탭 뒤에서 한 번에 하나만 마운트한다.
- API 둘 다 배치화하되 기존 단수 필드를 별칭으로 계속 받는다(하위호환).

### 실패 의미론 (지금 정해 둔다)
**하나가 차단돼도 배치를 중단하지 않는다.** 나머지는 큐에 넣고 버전별 결과를 돌려준다.
전부 차단됐을 때만 409. 전부 되돌리면 운영자가 무엇이 왜 막혔는지 알 수 없다.

### 비용 규칙 — 언어는 곱하지 않는다
이미지·Veo 클립은 언어 독립 캐시라 두 번째 언어는 $0 다(`content_hash` 에 lang 필드 없음,
`tests/test_shared_assets.py` 가 고정). TTS 는 edge-tts 로 $0. 그래서 총액은 **버전 수**로만
늘어난다. 확인 모달에 `언어 추가 비용 $0 — 이미지·클립은 언어 공유(캐시)` 를 명시한다.
`web/lib/orderCost.test.ts` 가 "언어 2개가 비용을 2배로 만들지 않는지"를 단언한다.

**운영자가 알아야 할 것:** `config.RENDER_BUDGET_CAP_USD`(기본 $1.2)는 **잡 단위** 가드다
(`engine/render.py:_on_cost`). 2버전×2언어에 총액 상한은 없다 — 이 확인 모달이 총액을 보는
유일한 지점이다.

---

## 9. 검증

**통과(이 환경에서 실행)**
- `pytest` 570 passed / 8 skipped (착수 전 기준선 511 passed / 8 skipped).
- `node --test web/lib/*.test.ts` 26 passed.
- `npm run lint` 무경고, `next build` 통과.
- 크롭은 **픽셀로 확인**했다: `cx=0.0` 확대는 빨강, `cx=1.0` 확대는 파랑, 출력 1080×1920
  (`tests/test_crop_image.py`). 크기만 보면 단순 리사이즈와 구별되지 않아 색으로 증명했다.
- 신규 렌더 테스트 4건은 **수정을 되돌려 실제로 실패하는 것까지 확인**했다
  (생성 호출 2회·인덱스 없음). 기존 `test_shared_assets` 3건은 수정 없이 통과한다.

**미검증 (라이브에서만 닫힌다)**
1. **9:16 실측** — §4. `sample-continuity` 워크플로 `verify-aspect` 스텝. **DoD ① 미완.**
2. **화풍 일관성** — 웹툰체로 나오는가, 실사로 되돌아가는가. 장면 3~4장을 나란히 놓고 사람이 판정.
3. **크롭 화질** — 2.5배에서 뭉개짐이 눈에 띄는지. 무너지는 배율을 찾아 `CROP_MAX_SCALE` 조정.
4. **관통 비교** — 같은 논문으로 `만화식×KO` / `웹툰×KO` mp4 를 뽑아 나란히.
5. **대시보드 라우트·엣지 함수** — Supabase 키가 없어 실주행하지 못했다. 엣지 트윈은 오직
   `tests/test_prompt_sync.py` 의 문자열 앵커로만 지켜진다.

---

## 10. 후속 백로그

1. **레퍼런스 이미지 입력**(지시서 v2 §4) — §3. 별도 PR.
2. **`manim_templates`·`claim_viz` 물리 삭제** — 프로덕션 도달 불가 상태다. 데모 경로까지
   정리할 때 별도 PR 로.
3. **`CROP_MAX_SCALE` 실측 조정** — 2.5는 지시서 v2 의 제안값이고 화질 실측으로 확정해야 한다.
4. **파생 컷 캐시** — 필요해지면 `content_hash` 확장이 선행(§7).
5. **`engine/clip_fit.py`**(Codex 소유, 여전히 부재) — 이번 작업과 무관하나 미해결로 남아 있다.
