# 범위 이탈/정합 기록: 설명판형 코드 렌더 보드 (최종명세 v3.3 §20~21)

> CLAUDE.md 작업 규칙 6: "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고 `docs/`를 갱신하며 근거를 남긴다."
> 기준 명세: `최종 명세서 — 하루한리포트 설명판형 데이터 에디토리얼 (v3.3 · 단일 통합본)` — 특히 §20-3 밴드 그리드와 §21 구현 킬 스위치.
> 선행: `docs/deviation-explainer-v3_3.md`(주장 귀속·게이트 계층).

---

## 0. 왜 이 작업이 생겼나 — 실측된 사고

설명판형 첫 산출물(MS/Azure 편)을 운영자가 검수한 결과:

1. **가짜 대시보드·가짜 수치.** AI 생성 이미지가 화면에 243.5%·45.4%·27.5% 를 근거 없이 그렸다.
   시청자는 그 픽셀을 리포트 데이터로 읽는다 — 품질 문제가 아니라 **컴플라이언스 사고**다.
2. **나레이션 수치가 화면에 없음.** "43%"를 말하는데 화면엔 추상 그래픽만.
3. **레터박스.** 상 200 / 하 420px 검은 바가 화면의 32%.
4. **근거·출처가 한 글자도 안 보임.**

### 원인 (전부 파일:라인 실측)

| # | 원인 | 근거 |
|---|---|---|
| 1 | **내가 쓴 프롬프트가 사고를 유발했다** — explainer 가이드가 `"dark financial editorial data board"` 를 이미지 모델에 넘겼다. "데이터 보드를 그려라"라고 시킨 셈이다. 공통 네거티브에 `no numbers` 는 있으나 **`no charts/dashboards` 가 없어** 차트 모양 자체는 막지 못했다 | `directive.py:255`(수정 전), `config.py:565-568` |
| 2 | **코드 렌더 경로가 도달 불가** — `render_kind_for_scene` 는 `version_type=="animation"` 일 때만 `clip` 을 주는데 그 값은 제공 버전 enum 에 없다 | `render.py:40-57`, `config.py:242` |
| 3 | **fin_charts 는 껍데기** — `templates/`·`validate.py` 부재, 3함수 `NotImplementedError`, engine 내 import 0 | `fin_charts/types.py:225,233,243` |
| 4 | **★ 리포트 렌더가 오버레이를 통째로 버렸다** — `overlay_out`·`overlays=` 미전달로 근거 카드가 ASS 에 스타일조차 없었다. 지시서는 만드는데 렌더가 폐기 | `report_render.py:52-53,67-69`(수정 전) |
| 5 | **레터박스** — `pad=1080:1920:0:200:color=black`. 리포트도 논문과 같은 경로 | `assemble.py:73-81` |

---

## 1. 구현 결정

### BD1 — 렌더 기술: **PIL**(Manim 아님)

**결정:** 보드를 Pillow 로 그린다. `engine/manim_templates.py` 는 **무수정**으로 둔다.

**근거:**
- Pillow 는 `engine/requirements.txt:10` 상시. manim 은 `requirements.txt:12-14` 가
  "libcairo2-dev·libpango1.0-dev 때문에 수집·채점 잡이 깨진다"고 **명시적으로 배제**했고,
  그 조건부 설치를 잘못 걸어 워커가 죽은 이력이 `report-video.yml` 주석에 남아 있다.
- §20-3 은 **픽셀 절대 좌표** 판정이다. PIL 은 그 좌표로 바로 그리고, §20-7 검사가 레이아웃
  시점에 끝난다(mp4 디코드 0회). Manim 은 scene unit 좌표계라 변환 레이어가 더 필요하다.
- Manim 경로는 제공 버전에서 **한 번도 돈 적이 없다** — 검증되지 않은 208줄에 얹지 않는다.

**트레이드오프:** 이징 트윈이 없다. 3~8초 보드에서 하드컷 단계 등장과의 체감 차이는 작다고
판단했고, 대가는 CI 에서 한 번 죽인 적 있는 의존성이다.

### BD2 — `fin_charts/` 는 **동결 유지**, 데이터 계약만 재사용

`ManimSceneSpec` 은 Manim 전제이고 5종 차트 계약이 다른 명세(C안 v1.1)에 묶여 있어, 보드
렌더러가 그 이름을 구현하면 실제와 어긋난다. 미구현 3함수는 `NotImplementedError` 그대로 둔다.
Manim 차트 라인을 부활시킬 때를 위해 계약은 살려 둔다.

### BD3 — 보드는 **`kind="clip"`** 으로 반환한다

스틸(`kind="image"`)로 내면 `_render_cut_clips` 가 켄번스(zoompan z=1.18 크롭)를 자동 주입해
**밴드 좌표가 깨진다.** 그걸 피하려면 논문 라인이 공유하는 `_render_cut_clips` 를 고쳐야 한다.
clip 으로 내면 **그 함수를 한 줄도 고치지 않는다.** 대가는 보드당 ffmpeg 인코드 1회(로컬·무료).

### BD4 — 분기 위치가 K2 를 **구조로** 강제한다

보드 분기를 `_gen_cut_assets` 의 `motion_source=="video"` 분기보다 **앞**에 뒀다. 보드 컷은
Veo·이미지 생성 경로에 **도달할 수 없다** — 정책이 아니라 도달 불가다
(`tests/test_board_wiring.py:test_board_cut_returns_clip_and_costs_nothing` 이 유료 함수에
지뢰를 심어 이를 고정한다).

### BD5 — 레터박스: `config.LAYOUT_MODE` **전역 스왑**(인자 전달 아님)

검은 바 생성 지점이 assemble 안에 4곳이고 전부 `config.LAYOUT_MODE` 를 호출 시점에 읽는다.
인자로 넘기려면 그 4함수와 **논문 라인 호출자까지** 고쳐야 한다. 같은 방식의 선례가 이미 있다
— `render.py:159-165` 가 placeholder 폴백 때 `config.IMAGE_PROVIDER` 를 스왑한다.

**한계:** 스레드 안전하지 않다. 리포트 워커는 `poll_once` 가 잡을 **직렬** 처리하므로 현재
안전하다. 병렬화하면 깨진다 — 그때는 인자 전달로 바꿔야 한다(코드 주석에 명시).

### BD6 — ★ CORE 밀도를 **픽셀이 아니라 면적**으로 잰다 (명세 문구와 다름)

§20-7 은 "CORE 밴드의 **비배경 픽셀** 비율 < 30% → warn"으로 썼다. 그대로 구현했더니 잘 채운
화면도 **4~5%** 가 나왔다(실측) — 글자는 획이 얇아 픽셀 점유가 원래 낮다. 그 수치로는 "허전한
화면"을 구분할 수 없다(늘 경고가 뜨거나, 임계를 낮추면 진짜 빈 화면을 놓친다).

→ **요소가 차지한 면적**(placement 박스 합집합)으로 잰다. 같은 데모에서 텍스트 보드 37~53%,
차트 보드 63%, 빈 화면 <10% 로 갈렸다 — 운영자가 보는 '허전함'과 일치한다.
구현: `board_layout.core_coverage`(순수, 격자 합집합).

### BD7 — K1 네거티브는 **explainer 전용 상수**로 추가

`config.BURN_IN_NEGATIVE_PROMPT` 를 건드리면 comic 이미지 프롬프트가 바뀐다 —
`providers/image.py` 주석과 `tests/test_image_prompt.py` 가 **출력 바이트 불변**을 계약으로
못박고 있다(A/B 비교에서 화면 설계 말고 다른 변수가 끼면 판정이 무의미해진다).
→ `EXPLAINER_IMAGE_NEGATIVE_PROMPT` 를 신설해 explainer 일 때만 합류. `WEBTOON_NEGATIVE_PROMPT`
가 쓰는 것과 같은 형태다.

### BD8 — 폰트는 **폴백하지 않고 예외**

PIL 은 `.ttf` 파일 경로가 필요하다. 기본 비트맵 폰트로 폴백하면 한글이 두부(□□□)로 나가는데,
그건 렌더 실패보다 나쁘다(운영자가 산출물을 보기 전까지 모른다).
→ 후보 사슬(NanumGothic → unifont → DejaVu)에서 하나도 못 찾으면 `BoardFontError`.
러너는 `fonts-nanum` 을 설치한다(`report-video.yml`). 로컬 미리보기는 unifont 로 돈다(픽셀 느낌).

---

## 2. 무엇이 바뀌었나

```
신규   engine/board_layout.py        밴드 해소 · §20-7 판정 · 단계 길이 (순수)
       engine/board_render.py        보드 5종 PIL 렌더 · 차트 · payload 추출
       scripts/preview_board.py      DB·ffmpeg 없이 보드 PNG 확인
       tests/test_board_layout.py    14건 — 밴드·안전선·밀도·단계 길이
       tests/test_board_wiring.py    12건 — K1/K2/K3 · 레터박스 · 논문 격리
확장   engine/config.py              EXPLAINER_BANDS · 폰트 후보 · 캡 · 네거티브
       engine/render.py              _gen_cut_assets 보드 분기(유료 경로보다 앞)
       engine/assemble.py            build_board_clip_command 추가만
       engine/report_render.py       레터박스 컨텍스트 · overlays 배선
       engine/subtitles.py           caption/footer margin 선택 인자(None=기존)
       engine/providers/image.py     explainer 네거티브 합류
       engine/directive.py · report_directive.py   "데이터 보드 그려라" → 실사 맥락 사진
무수정  render_kind_for_scene · _render_cut_clips · effect_filter ·
       manim_templates.py · fin_charts/ · BURN_IN_NEGATIVE_PROMPT
마이그레이션  없음
```

---

## 3. 아직 안 된 것 (다음 단계)

| 항목 | 내용 |
|---|---|
| **K4** | 나레이션 발화 수치가 화면에 있는지 검사. 정규식 오탐("2026년"·"3분기")이 커서 warn 으로 시작해야 한다 |
| **K5** | 편당 $0.25 하드캡. 현재 작동하는 것은 `RENDER_BUDGET_CAP_USD`($1.2 사후 중단)뿐. `EXPLAINER_COST_CAP_USD` 상수는 넣었으나 **아직 강제하지 않는다** |
| **비용 원장** | `report_render.py` 가 `directive_id=None` 이라 `generation_attempts` 0행 + 이미지 캐시 미사용(재렌더마다 재과금). `generation_attempts.directive_id` 가 **`directives(id)` FK** 라 리포트 id 를 그냥 넣으면 조용히 실패한다 — 마이그레이션 필요 |
| **렌더 QA** | `report_render` 가 `render_qa` 를 호출하지 않는다. K3 픽셀 판정(상·하 200px 검정 비율)도 미구현. `report_render_jobs.qa` 컬럼 자체가 없다 |
| **§20-2 배경** | 텍스트 보드 배경을 실사 맥락 이미지 딤 처리로 까는 것(현재는 단색 `#0B1220`) |
| **Veo OFF** | explainer 에서 Veo 금지는 보드 컷에만 구조적으로 적용된다. CONTEXT_BOARD 컷은 아직 Veo 로 갈 수 있다 |
| **명세 커밋** | 이 저장소의 `docs/개선명세서_설명판형_v3_3.md` 는 §14 에서 끝난다 — §20·§21 본문이 없다. 합격 기준을 재현하려면 통합본을 커밋해야 한다 |

## 4. 범위 밖(불변)

- 논문 라인 전체 · 만화식 리포트 경로 · `BURN_IN_NEGATIVE_PROMPT` · `manim_templates.py`.
- 시리즈 타이틀은 운영자 결정대로 `"오늘의 리포트"` 유지(§21 K6 의 "하루 리포트 하나" 문구는 따르지 않는다).
