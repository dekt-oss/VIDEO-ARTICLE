# 편차 기록 — 클립 길이 보정 · 언어 추가 렌더 · editorial 앵커 게이트

- 대상 명세: `수정명세서_하루한편_editorial앵커_언어추가_클립길이_v1.md`(업로드 원본, 이하 **v1**)
- 상태: Part ③·② 구현 완료(단, `engine/clip_fit.py` 는 Codex 인계 대기). Part ① 미착수(게이트 불통과).
- 작성 기준일: 2026-07-26

---

## 0. 결론 (두괄식)

| 항목 | 명세 판정 | 실제 처리 | 근거 |
|---|---|---|---|
| ③ 클립↔나레이션 길이 | P0 | **구현.** 단 진단이 절반 틀렸다 — 순서 역전은 이미 되어 있었다 | §2 [C] |
| ② 언어 추가 렌더 | P0 | **구현.** DB 컬럼 3개 중 1개만 채택(`source_job_id`) | §2 [B], §4 |
| ① editorial 앵커 교정 | P1 (조건부) | **미착수.** 선행 진단 불통과 — `viz_template`·`overlay_plan` 전부 미구현 | §2 [A] |

---

## 1. 런타임 탐색 결과 (v1 §1 — 구현 전 필수 보고)

### [A] editorial 구현 진단 — ①의 선행 조건

| 항목 | 판정 | 근거 |
|---|---|---|
| `engine/viz_templates/` 디렉터리 | **미구현** | 디렉터리 자체가 없다(`ls` 실패). 코드 그래픽은 `engine/manim_templates.py` 의 씬 템플릿 4종(`title`/`arrow_flow`/`step_reveal`/`number_compare`)뿐이고, 이는 v3.1 §5 의 viz_template 5종과 다른 물건이다 |
| `viz_template` | **미구현** | 저장소 전체 grep 0건(`engine/`·`web/`·`supabase/`) |
| `viz_params` | **미구현** | grep 0건 |
| `asset_source` | **미구현** | grep 0건 |
| `overlay_plan` | **미구현** | grep 0건 |
| `VERSION_GUIDANCE` | **구현됨** | `engine/directive.py:158`, `supabase/functions/generate-directive/index.ts:203`. `editorial` 항목 존재(잡지형 앵커 문구 포함) |

**판정:** v1 §Part① 선행 조건("`viz_templates` 5종 + `overlay_plan` 배선이 `구현됨`")이 **불충족**이다.
현재 editorial 은 "프롬프트 가이드만 있고 시각 산출 경로는 comic 과 동일"한 상태다 — 즉
`data_viz` 컷은 Manim 템플릿 4종으로 렌더되고, 나머지는 생성 이미지로 나간다. 그래서 v1 §0 의
판정("현 결과물은 `viz_template` 결손 상태의 산출물")은 **코드로 확인된다.**

**착수 비용 추정(v1 §191 이 요구한 보고):** viz_template 5종 + `overlay_plan` 배선 + 정규화
검증 + 컷 상한 게이트는 새 렌더 경로 하나를 추가하는 작업이다. 참고 규모로 기존 유사 작업인
`engine/manim_templates.py`(씬 템플릿 4종 + 선택 로직 + 렌더러)가 단일 모듈이고
`tests/test_manim_templates.py` 가 붙어 있다 — viz_template 는 그보다 넓다(템플릿 5종 +
`asset_source`/`viz_params` 스키마 + 정규화 하드 게이트 + overlay 합성). **PR 1건으로 묶지 말고
별도 PR 로 분리해야 하는 규모**이고, 노선 유지 여부(v1 §1-3 의 "3편 화면 QA")는 그 PR 이후에만
의미 있는 판정이 된다.

→ **이번 PR 에서는 ① 을 건드리지 않았다.** `global_style` 앵커 교체(§1-1)도 하지 않았다:
앵커만 바꾸면 `viz_template` 없이 "과학 도해형" 문구를 생성 이미지 모델에 던지는 셈이라, v1 이
지적한 결손 상태를 그대로 유지한 채 표면만 바꾸는 일이 된다. `version_type` enum 의 `editorial`
은 그대로 둔다(롤백 여지 유지, v1 §0 운영 조치).

### [B] 렌더 잡 · 언어 처리 현황 — ②

| 항목 | 판정 | 근거 |
|---|---|---|
| `render_jobs.lang` | **이미 존재** | `supabase/migrations/0012_render_job_lang.sql`. 워커가 소비(`engine/render.py` `poll_once`) |
| `render_jobs.source_job_id` | 없었음 → **신설** | `supabase/migrations/0030_render_job_source.sql` |
| `render_jobs.reuse_assets` | 없었음 → **신설하지 않음(기각)** | 아래 §4 |
| `render_assets` 유니크 제약 | **구현됨** | `0009_render_pipeline.sql`: `unique (directive_id, cut_no, asset_type)` |

**열린 질문 1(에셋 캐시 실효성) 해소 — 전제는 깨지지 않았다.**
논문 파이프라인은 `_render_cut_clips(..., directive_id=directive_id)` 로 호출되므로 캐시를 탄다.
`directive_id=None` 으로 캐시를 우회하는 것은 **리포트 파이프라인만**이고, 그 사실이
`engine/report_render.py:6` 주석에 명시돼 있다. 논문 쪽은 정상이다.

**더 중요한 발견: 에셋 재사용은 이미 언어 독립이다.**
- `assemble.content_hash`(`engine/assemble.py`)의 해시 payload 에 언어 필드가 없다.
- `_gen_still` 은 애초에 `lang` 인자를 받지 않는다(구조적 언어 독립성).
- `_gen_veo_clip` 의 docstring 이 "KO 렌더가 만든 클립을 EN 재렌더가 그대로 재사용" 을 선언한다.
- `tests/test_shared_assets.py` 가 "이미지 생성 호출 = 1회(언어 무관)" 를 이미 검증하고 있었다.

### [C] 에셋 생성 ↔ TTS 실행 순서 — ③의 근본 원인

`_gen_cut_assets`(`engine/render.py`) 현재 실행 순서 의사코드:

```
1. measured = tts_provider.synthesize(cut, aud_path, lang).sec   # ← TTS 가 이미 최우선
2. if motion_source == "video":  _gen_still(첫 프레임) → _gen_veo_clip(..., VEO_CLIP_SEC)
3. elif animation:               generate_clip(..., measured)     # Manim — 임의 길이 지원
4. else:                         _gen_still  (+ 켄번스)
```

**v1 §3-2 의 진단은 절반이 틀렸다.** "에셋을 먼저 생성하고 TTS를 나중에 돌린다"는 추정은
사실이 아니다 — TTS 가 함수 첫 줄이고, 나레이션 실측 길이를 이미 확정한 뒤 에셋을 만든다.
**순서 역전은 할 일이 없었다.**

진짜 결손은 다른 곳이었다:
1. `_gen_veo_clip` 이 이미 손에 든 `measured` 를 **쓰지 않고** `config.VEO_CLIP_SEC`(고정 4초)를
   넘긴다. 정답을 알면서 안 본다.
2. `providers/video.py` 의 `clip_sec = min(int(duration) or VEO_CLIP_SEC, VEO_CLIP_SEC)` 가
   상한을 `VEO_CLIP_SEC` 로 걸어, `measured` 를 넘겨도 4초로 깎였다.
3. 티어 목록 상수가 없었다(주석에만 "Veo 3.1: 4·6·8초").
4. 조립은 `tpad=stop_mode=clone` + `-t` + `-shortest` 뿐이라 **전 컷이 무조건 홀드(짧을 때)
   또는 페이드 없는 트림(길 때)** 이었다. ratio 구간·핑퐁·켄번스·플래그·로그 모두 없었다.

**열린 질문 2 해소:** TTS 는 `_gen_cut_assets` 내부에 있다 → 지역 변경으로 끝났다(함수 경계 조정 불필요).
**열린 질문 3 해소:** Veo 는 고정 티어(4/6/8초)다. 임의 길이 미지원 → §3-3 잔여 갭 보정이 필요하다.

---

## 2. Part ③ 구현 — 무엇을 했고 무엇이 남았나

### 한 것 (Claude Code 소유분)

| 파일 | 변경 |
|---|---|
| `engine/config.py` | `VEO_CLIP_SEC_TIERS`, `VEO_CLIP_MAX_TIER_SEC`, `CLIP_FIT_*` 임계값(매직넘버 금지 규약) |
| `engine/clip_fit_types.py` (신규) | `Strategy` 타입 계약 **FREEZE** + `decide()` 단일 진입점 + 보수 폴백 |
| `engine/providers/video.py` | `CLIP_SEC_TIERS` 상수 노출 + `pick_clip_tier()` + `_veo_i2v` 배선 |
| `engine/assemble.py` | `probe_duration()`, `clip_fit_video_filter()`, `pingpong_filter_complex()`, `build_clip_cut_command(strategy=…)` |
| `engine/render.py` | `measured` → 티어 선택 전달, `_decide_clip_fit()`, 컷별 로그, `fit_log` 수집 |
| `engine/render_qa.py` | `evaluate_clip_fit()`(순수) + `merge_clip_fit_qa()` — §3-6 빨간 플래그·노란 경고 |
| `engine/directive.py` + TS 사본 | `loop_safe` 스키마 필드 + 프롬프트 규칙 1줄 + 정규화(기본 `false`) |

핑퐁만 `-filter_complex` 를 쓴다 — `split`/`reverse`/`concat` 은 라벨이 필요한 다중 입출력
그래프라 `-vf`(단일 입출력)로는 표현할 수 없다. v1 §3-5 의 예시도 `-filter_complex` 였다.
`ratio > 0.60`(flagged) 컷도 화면 시간은 나레이션 길이를 유지하되 홀드로만 채운다 — 보정을
포기하는 것이 "뒤가 검은 화면"을 의미하면 안 되기 때문이다.

### 남은 것 — `engine/clip_fit.py` (소유: **Codex**, v1 §4 무간섭)

v1 §4 파일 소유권 표가 `clip_fit.py` 를 Codex 에 배정했으므로 **작성하지 않았다.** 대신:
- 계약(`engine/clip_fit_types.py`)을 FREEZE 로 확정했다 — `decide_strategy(clip_sec,
  narration_sec, loop_safe) -> Strategy`, 경계값 규칙(0/0.15/0.60 포함 관계)까지 docstring 에 명시.
- 임계값은 `engine/config.py` 에 있다(`CLIP_FIT_HOLD_RATIO_MAX`,
  `CLIP_FIT_PINGPONG_RATIO_MAX`, `CLIP_FIT_TRIM_FADE_SEC`).
- 그 파일이 없는 동안은 `clip_fit_types.fallback_decide_strategy` 가 **trim/hold 만** 내주고
  경고 로그를 남긴다. 즉 지금 배포해도 "나레이션이 잘리거나 영상이 먼저 끝나는 컷 = 0" 은
  지켜지고(현재 동작 + 트림 페이드아웃 개선), **핑퐁·QA 플래그는 비활성**이다.

**따라서 v1 §6 Part ③ DoD 중 아래 2건은 Codex 인계 후에 충족된다:**
- [ ] `ratio` 4구간 각각을 실제로 태우는 판정 테스트 4건 → `tests/test_clip_fit.py`(Codex)
- [ ] `loop_safe=false` + `ratio=0.4` 컷이 홀드로 처리됨 → 위와 동일

충족된 것: 컷별 `(clip_sec, narration_sec, ratio, strategy)` 로그, 전략별 ffmpeg 배선 4종,
QA 플래그/경고, `loop_safe` 스키마·기본값. `tests/test_clip_fit_wiring.py` 24건(argv 수준) +
`tests/test_clip_fit_ffmpeg.py` 8건(**실제 ffmpeg 실행**)이 이를 고정한다.

**DoD "나레이션이 잘리거나 영상이 먼저 끝나는 컷 = 0" 은 실행으로 검증됐다.**
`tests/test_clip_fit_ffmpeg.py` 는 합성 클립·오디오를 만들어 4전략을 전부 진짜 ffmpeg 에 태우고
산출 mp4 의 영상·오디오 실측 길이가 나레이션 길이와 같은지(±0.15s, 프레임 경계 오차) 본다:

| 전략 | 클립 → 나레이션 | 산출 영상 | 산출 오디오 |
|---|---|---|---|
| trim | 8.0s → 6.0s | 6.00s | 6.00s |
| hold | 5.5s → 6.0s | 6.00s | 6.00s |
| pingpong | 4.0s → 7.0s | 7.00s | 7.00s |
| pingpong(loops=2) | 4.0s → 15.0s | 15.00s | 15.00s |
| flagged | 4.0s → 12.0s | 12.00s | 12.00s |
| 레거시(전략 없음) | 4.0s → 5.0s | 5.00s | 5.00s |

핑퐁이 실제로 동작했다는 증거: 그 경로는 `tpad` 를 쓰지 않으므로(테스트가 argv 에서 먼저 확인)
4초 입력에서 7초가 나왔다면 `reverse`+`concat` 이 통과한 것이다. 이것이 argv 검증으로는 잡을 수
없던 지점이었다 — `-vf` 로는 라벨 그래프를 표현할 수 없어 실행 시점에 죽는다.

관통 테스트(`test_render_cut_clips_populates_fit_log_and_conforms_each_cut`)는 클립 제공자만
대체하고 `_render_cut_clips` → `_decide_clip_fit`(ffprobe 실측) → `fit_log` → `merge_clip_fit_qa`
를 실제 경로로 태운다. ffmpeg 없는 환경에서는 파일 전체가 skip 된다(저장소 기본 pytest 는 순수
로직 테스트라는 규약 유지).

### 편차 — 티어 상한 기본값을 비용 불변으로 뒀다

v1 §3-2 는 "나레이션 이상인 최소 티어" 를 무조건 요청하라고 한다. 그대로 켜면 **클립당 비용이
1.5~2배**가 된다(Veo 는 초당 과금: 4s $0.20 → 8s $0.40, 편당 4클립이면 +$0.80/편 ≈ +$24/월).
이 저장소는 비용 규율이 명시적이다(Lite 모델 고정, `VEO_MAX_CLIPS_PER_DRAFT` 개수 캡,
`VIDEO_MAX_*_PER_TOPIC` 이중 캡, `docs/cost-optimization-baseline.md`). v1 은 이 비용을 계산하지
않았다.

→ `VEO_CLIP_MAX_TIER_SEC` 기본값을 `VEO_CLIP_SEC`(=4)로 뒀다. **기본 동작의 비용은 정확히
불변**이고, 남는 갭은 무료 보정(hold/pingpong)이 흡수한다. 네이티브 길이 클립을 원하면
`VEO_CLIP_MAX_TIER_SEC=8` 로 올린다(비용 상승 감수). 티어 선택 코드는 완전히 배선돼 있어
env 한 줄로 켜진다.

부수 효과: 요청 티어가 가변이 되면서 비용 원장의 `requested_units` 도 고정값이 아니라 실제 요청
초수를 기록한다(`engine/render.py` `tier_sec`).

---

## 3. Part ② 구현 — MODE A(`asset_reuse`) 채택

- `POST /api/render-add-language` — body `{ source_job_id, lang, force? }`. 원본 잡 검증 →
  같은 `directive_id` · 지정 `lang` · `source_job_id` 로 `render_jobs` 1행 생성 → 렌더 트리거.
- 가드: 원본 `status != 'done'` → 409(에셋 캐시 불완전). 같은 `(directive_id, lang)` 완료 잡이
  이미 있으면 409 `exists` → UI 가 확인받고 `force: true` 로 재요청.
- ⑥ 렌더 결과 화면(`web/components/RenderList.tsx`): 잡별 `[🇬🇧 EN 버전 추가 생성]` /
  `[🇰🇷 KO 버전 추가 생성]` 버튼. 언어가 둘 이상인 그룹에는 "총 길이 차이는 결함이 아니다" 1줄 표기.
- MODE B(`timeline_lock`)는 v1 판정대로 백로그 — 구현하지 않았다.

### 편차 — `reuse_assets` 컬럼을 만들지 않았다 (DB 변경 3개 → 1개)

에셋 재사용은 **잡의 플래그가 아니라 파이프라인의 구조적 불변식**이다(§1 [B]). 플래그를 두면
같은 사실에 두 번째 진실원이 생기고, 둘이 어긋나면 어느 쪽이 맞는지 알 수 없다. 그래서
`source_job_id`(계보 — UI 표시·조사용)만 신설하고 `reuse_assets`·`lang`(이미 존재)은 두지 않았다.

**v1 §6 Part② DoD "`reuse_assets=true` 잡의 이미지·영상 생성 API 호출 = 0" 의 대체 검증:**
컬럼이 없으므로 원장 대신 테스트로 고정했다 —
- `tests/test_shared_assets.py::test_gen_still_shared_across_languages` (기존): 이미지 생성 1회
- `tests/test_shared_assets.py::test_gen_veo_clip_shared_across_languages` (**신규**): Veo 클립
  생성 1회 · 두 번째 언어 비용 0. 티어 선택 도입 후에도 유지되는지까지 고정.

라이브에서의 실측 확인은 `generation_attempts` 원장에 `(directive_id, cut_no, asset_type)`
행이 언어를 늘려도 1행에 머무는지로 본다(운영 점검 항목).

---

## 4. 후속 백로그

1. **`engine/clip_fit.py`(Codex)** — 4구간 판정 + 경계값 테스트. 이게 들어오면 핑퐁·플래그 활성.
   그때까지 전략 4종의 조립 경로는 이미 검증돼 있으니, Codex 는 판정만 채우면 된다.
2. **라이브 KO→EN 관통** — 실제 지시서로 KO 렌더 → ⑥ 화면에서 EN 추가(v1 §5 3단계). 조립·
   길이 보정·에셋 공유는 각각 테스트로 검증됐지만, **Veo 키가 필요한 I2V 경로와 Storage 업로드는
   미실행**이다. `render_jobs.source_job_id` 마이그레이션은 video-article 프로젝트
   (`<SUPABASE_PROJECT_REF>`)에 **적용 완료**(`information_schema` 로 확인: uuid, nullable).
3. **Part ①** — `viz_template` 5종 + `overlay_plan` 배선(별도 PR). 그 뒤에 앵커 교체(§1-1)·
   `scene_role` 기반 생성 이미지 상한(§1-2)·3편 화면 QA(§1-3).
4. **MODE B `timeline_lock`** — 필요해지면.
5. **`loop_safe` 판정 신뢰도**(v1 열린 질문 4) — LLM 이 이 플래그를 제대로 채우는지 미검증.
   기본값 `false` 가 안전측이라 최악의 경우도 "홀드로만 처리됨" 에 그친다.
