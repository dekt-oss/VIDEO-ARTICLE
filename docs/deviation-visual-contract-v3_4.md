# 편차 기록 — 설명판형 시각 구현 계약 v3.4 (§22 K8~K11) 반영

- 대상 명세: `최종 명세서 — 하루한리포트 설명판형 데이터 에디토리얼 v3.4` + 첨부 모듈 `visual_contract.py`
- 반영일: 2026-07-31
- 선행 기록: `docs/deviation-explainer-boards.md`(v3.3 보드 렌더러), `docs/deviation-explainer-v3_3.md`

---

## 0. 무엇이 달라졌나 (한 줄)

v3.4 는 "화면을 이렇게 그려라"를 **산문 대신 실행 가능한 모듈**로 줬다(§22-1: 산문과 충돌하면
모듈이 우선). 그래서 좌표·폰트·검증 로직을 `engine/visual_contract.py` 하나로 옮기고,
렌더러가 그 API 만 쓰도록 고쳤다.

---

## 1. 규범 모듈 채택 — `engine/visual_contract.py`

첨부 모듈을 거의 그대로 넣었다. 배선을 맞추느라 **4곳**을 바꿨고, 전부 모듈 상단 주석에
A1~A4 로 적어 뒀다.

| # | 무엇 | 왜 |
|---|---|---|
| A1 | PIL import 를 지연 import 로 | `config.py` 가 이 모듈을 참조하고, config 는 수집·채점 잡도 import 한다. 최상단 import 면 렌더와 무관한 잡이 Pillow 에 묶인다. 저장소 관례와 같다(`engine/crop.py`). |
| A2 | `FONT_DIR` 기본값을 저장소 루트 기준 절대경로로 | 원본의 상대경로 `"assets/fonts"` 는 워커 cwd 에 따라 빗나간다. 그 결과가 하필 K8 이 막으려는 "폰트 없음"이라 **진짜 결함과 구분이 안 된다**. 환경변수 `EXPLAINER_FONT_DIR` 오버라이드는 그대로. |
| A3 | `num_ko` = `SCDream9.otf` → `Pretendard-Black.otf` | 에스코어드림 9 Black 은 라이선스 미확인(`docs/deviation-fin-visual-v1.md` FVD2). §22-2 가 허용하는 **명시 지정 + 기록**이 이 문단이다. 침묵 폴백이 아니라, 파일이 없으면 여전히 예외로 죽는다. 라이선스가 확정되면 `FONT_FILES` 한 줄만 되돌리면 된다. |
| A4 | `fit_text()` 합격 조건에 "각 줄이 실제로 `max_w` 안에 든다" 추가 | `wrap_by_width` 는 `or not cur` 때문에 **어절 하나가 `max_w` 보다 길면 그 어절만으로 한 줄을 만든다.** 줄 수 기준은 통과하는데 글자는 안전선 밖으로 나간다 — v3.3 구현에서 한글이 x=930 을 1268px 까지 넘긴 그 결함(F2)이다. 줄 수만 보면 못 잡는다. |

**밴드 좌표의 원본이 바뀌었다.** `config.EXPLAINER_BANDS` 는 이제 절대 픽셀 표가 아니라
`visual_contract.BANDS`(비율)를 렌더 해상도로 해소한 값이다. 1px 안팎으로 값이 달라졌다
(CORE 501~1181 → 499~1180 등). 의도한 것이다 — 절대좌표를 두 곳에 적으면 해상도가 바뀌는
순간 어긋난다(F2).

---

## 2. 킬 스위치별 조치

### K8 — 폰트 폴백 금지

**전:** 시스템 폰트 후보 4개를 순서대로 훑어 존재하는 것을 조용히 썼다
(`config.EXPLAINER_FONT_CANDIDATES`). 러너는 나눔, 로컬은 유니폰트, 최악엔 한글 없는
데자뷰가 걸릴 수 있었다 — **환경마다 다른 화면이 나온다.**

**후:** 저장소가 폰트를 들고 다닌다. `assets/fonts/` (전부 SIL OFL, 라이선스 동봉):

| 파일 | 역할 | 출처 |
|---|---|---|
| `Pretendard-ExtraBold.otf` | `head` (제목·자막) | Pretendard v1.3.9 |
| `Pretendard-Bold.otf` | `body` | 〃 |
| `Pretendard-Medium.otf` | `small` (출처·라벨) | 〃 |
| `Pretendard-Black.otf` | `num_ko` (대형 숫자 KO) | 〃 · A3 대체 지정 |
| `Anton-Regular.ttf` | `num_en` (대형 숫자 EN) | Google Fonts ofl/anton |

`EXPLAINER_FONT_CANDIDATES` 는 **삭제**했고, 없어졌다는 사실 자체를 테스트가 지킨다
(`test_board_renderer_has_no_font_fallback_chain`). 렌더 시작 시 `preflight_fonts()` 가
`_explainer_layout` 안에서 1회 돈다 — 유료 생성이 나가기 **전**에 멈추기 위해서다.

대형 숫자 폰트 역할은 문자열을 보고 고른다: 순수 ASCII 면 `num_en`(Anton), 한글이 섞이면
`num_ko`. Anton 에는 한글 글리프가 없어 그대로 쓰면 두부가 된다.

### K9 — 말줄임(…) 금지

**전:** 두 군데서 잘랐다. `board_layout.wrap_text`(글자 수 근사 + `…`)와
`board_render._wrap_measured`(실측 폭 + `…`).

**후:** 둘 다 **삭제**했다. 줄바꿈·축소는 `visual_contract.fit_text` 만 하고, 최소 크기에서도
안 담기면 `ValueError` 를 던진다. `_draw_text_in` 은 그 예외를 삼키지 않고 위로 던진다 —
삼키면 K9 가 무력해진다. 세로로 넘칠 때도 마찬가지로 예외다(밴드를 넘어 아랫줄을 침범하느니
멈춘다). 화면에서 정보를 조용히 지우는 대신 "대본 문장을 줄여라"는 신호로 되돌린다.

### K10 — 같은 프레임 중복 문장 금지

`assert_no_duplicate_text()` 를 보드 렌더 끝에 배선했다. **판정 대상은 payload 후보가 아니라
실제로 그려진 텍스트(`Placement.text`)** 다. 후보로 검사하면 "제목 자리에 so_what 을 쓰고
SOWHAT 밴드는 비운" 정상 배치까지 중복으로 잡힌다(처음 그렇게 짰다가 걸렸다).

**이 게이트가 실제 결함을 하나 잡았다:** `EVIDENCE_BOARD` 가 같은 주장을 TITLE 밴드와 카드
본문에 두 번 찍고 있었다. 카드 본문을 "제목과 다른 한 줄만, 같으면 비움"으로 고쳤다.

### K11 — 차트 최소 요건

**전:** `bar_w = (box.w - gap*(n-1)) // n`. 2계열이면 막대 하나가 **400px = 화면의 37%**
였다. 차트가 아니라 거대 사각형이다.

**후:** `bar_w ≤ 0.22 × 화면폭`(= 237px)로 상한을 걸고, 폭이 줄었으니 그룹을 가운데로 모은다.
계열 ≤ 3, 앰버 강조 1계열, 값 라벨에 **단위**를 붙인다. `validate_chart_spec()` 결과를
`layout_qa["fail"]` 에 합류시킨다.

단위가 다른 값은 같은 축에 섞지 않고 버린다 — %와 억 달러를 한 막대 그래프에 놓으면 그 차트는
거짓말이 된다.

가로 비교 막대(`_draw_compare`, NUMBER_BOARD 안)는 길이가 데이터 인코딩이라 22% 상한이
적용되지 않는다. 두께는 이미 96px 상한이라 "거대 사각형" 문제가 없다.

### §22-6 — 프레임 판정 게이트

`validate_frame()` 을 완성된 보드 프레임에 돌려 결과를 `layout_qa` 에 합류시킨다.
`evaluate_layout` 은 "놓겠다고 계산한 박스"만 보므로, 그리는 중에 어긋나면(레터박스 · DEAD 밴드
침범 · 9:16 아님) 박스 계산은 멀쩡한데 화면이 틀린다. 실제로 그렇게 검은 바를 놓쳤었다.

**폴백 제거 — 이것이 이번 변경 중 가장 큰 동작 변화다.** `render.py` 의 보드 분기는
`except Exception` 으로 **계약 위반까지 삼켜 생성 스틸로 폴백**하고 있었다. 그 폴백 자체가
K2("보드에 생성 자산 금지") 위반이라 원래 틀린 길이었다. 지금은 K8/K9/K10/§22-6 위반이 나면
그 잡이 실패한다(§22-6 "fail 이 하나라도 있으면 렌더 차단"). 계약과 무관한 사고(디스크·ffmpeg)만
스틸 폴백을 남겼다.

---

## 3. 아직 하지 않은 것 (다음 작업)

| # | 항목 | 왜 미룸 |
|---|---|---|
| 1 | `report_render_jobs.qa` 컬럼 저장 | 마이그레이션 0033 이 아직 없다. 현재는 컷 단위로 잡을 실패시키므로 **차단은 이미 동작**하고, 저장만 빠져 있다. |
| 2 | CORE 밀도 warn 상시 발생 | `validate_frame` 의 픽셀 기준(30%)은 글자 획이 얇아 잘 채운 보드도 5~29% 로 나온다. §20-2 딤 처리 맥락 사진 배경이 들어가야 해소된다. 현재 warn 이고 차단하지 않는다. 선행 기록 `deviation-explainer-boards.md` BD6 와 같은 사안. |
| 3 | K4(나레이션↔화면 숫자 일치) 승격 | v3.3 계획대로 warn 유지. 표본 확인 후 block. |
| 4 | K5 $0.25 캡 3중 시행 | `EXPLAINER_COST_CAP_USD` 상수만 있고 preflight/사후 합산 미배선. |
| 5 | 비용 원장 배선 | `generation_attempts.directive_id` 가 `directives(id)` FK 라 리포트 id 를 넣으면 조용히 0행이 된다. 0033 에서 `report_directive_id` 추가 필요. |

---

## 4. 확인 방법

```bash
python -m engine.visual_contract          # §22-7 ② 스모크 (폰트 + fit_text + validate_frame)
python -m scripts.preview_board           # §22-7 ③ 보드 5종 PNG + fail 0 확인
python -m scripts.preview_explainer_video # 관통 mp4 (외부 API 호출 0 · 생성비 $0)
pytest tests/test_visual_contract.py      # K8~K11 회귀 감시 17건
```
