# 편차 기록 — 표현방식 3종 병행(만화식·설명판형·실사형) (2026-08-19 결정)

## 결정
운영자 결정: **만화식(comic) · 설명판형(explainer) · 실사형(photo)** 세 가지를 리포트 라인에서
나란히 발주하고, 성과로 비교한다.

리뷰에서는 설명판형 중단을 권고했다(렌더 8건 중 5건 실패, 마지막 성공 2026-08-04, 보드 화면
결함). 운영자는 **셋 다 유지**를 택했다. 그러면 설명판형이 "발주는 되는데 렌더가 안 되는"
상태로 남을 수 없으므로, 이 변경은 실사형 추가와 **설명판형 렌더 복구**를 함께 담는다.

## 1. 실사형(photo) 추가
- `config.VIDEO_VERSIONS` / `VERSION_VISUAL_TYPE` / `VERSION_DEFAULT_SCENE_KIND` 에 `photo`.
- 화면 계약: `directive.VERSION_GUIDANCE["photo"]` + `report_directive.PHOTO_CONTRACT`.
  - 화면의 글자·숫자는 **전부 `overlay_plan`** 이 담당한다. 이미지에 글자를 굽지 않는다.
  - `visual_prompt` 는 사진 지시만 — 차트·그래프·대시보드·퍼센트·라벨 금지.
  - 얼굴 클로즈업보다 현장(제품·생산라인·물류·데이터센터). 얼굴은 컷마다 다른 사람이 되기
    쉬워 실사에서 특히 눈에 띈다.
- 이미지 프롬프트: `IMAGE_QUALITY_SUFFIX_BY_VERSION["photo"]` + 신설 `PHOTO_NEGATIVE_PROMPT`.

### ★ 함께 고친 구조적 함정
예전 `providers/image.py` 는 **"품질 접미사 표에 키가 있으면 webtoon 부정어를 붙인다"** 는
대리 판정을 썼다. 실사형을 그 표에 넣는 순간 실사형 프롬프트에 `NOT photorealistic` 이 붙어
정확히 반대로 동작한다. 버전별 부정어 표(`IMAGE_STYLE_NEGATIVE_BY_VERSION`)로 분리했다.
comic·image_sequence 는 표에 없으므로 **출력 문자열이 예전과 바이트 단위로 같다**
(`tests/test_image_prompt.py` 가 계속 지킨다).

## 2. 설명판형 렌더 복구

### (a) 대형 숫자와 라벨이 겹치던 버그
`draw.text((x, y), …)` 는 **줄 상자 위쪽**을 기준으로 그리는데, 코드는 `y + text_size()[1]`
(= 잉크 높이)을 "글자 아래"로 썼다. 큰 폰트일수록 윗여백만큼 어긋난다 — Anton 220pt 의
"18.5%" 는 bbox `(0, 67, 573, 262)` 라 **67px** 차이다. 그래서 앰버 밑줄과 라벨이 숫자 위로
올라타 NUMBER_BOARD·CHART_BOARD 의 글자가 서로 겹쳤다(실제 렌더 화면으로 확인).

`visual_contract.text_ink_span()` 을 신설해 실제 잉크 범위로 배치한다.

### (b) 숫자가 카드의 절반만 쓰던 문제
폭에 맞춰 숫자를 키우는 코드가 **폴백 컷에서만** 돌았다. 숫자가 주인공인 NUMBER_BOARD 조차
카드 폭의 절반만 쓰고 아래가 비었다. 상한(`EXPLAINER_FALLBACK_NUMBER_MAX_SIZE`)은 그대로 두고
확대 루프를 일반 경로로 옮겼다. 충전율 실측: **0.224 → 0.383**(기준 0.25 통과).
CHART·VALUATION·COMPARISON 도 같이 통과한다.

### (c) 허전한 보드가 잡을 죽이던 문제
`core_underfilled` 는 v3 §9 에서 warn→fail 로 승격됐다. 판정은 옳다(빈 보드가 그대로 발행되는
것을 막았다). 틀린 것은 **처리 방식**이다: 이미지·TTS·조립 비용을 다 쓴 뒤 산출물을 버리고,
운영자에게는 실패 로그 한 줄만 남았다.

이제 `config.LAYOUT_FAIL_REVIEWABLE` 에 있는 사유는 mp4 를 만들어 올린 뒤 잡을
**degraded(사람 승인 대기)** 로 둔다 — ⑥ 화면 "조치 필요" 탭에서 영상을 보고 정한다.
화면 규격 위반(밴드 침범·안전선 초과·중복 텍스트)은 **그대로 즉시 실패**다.
`render_manifest.terminal_status` 가 `layout_fail` 을 읽어 이 판정을 내린다 — 이 줄이 없으면
빈 보드가 done 으로 조용히 통과해 승격 이전으로 되돌아간다.

## 3. 골든 해시 갱신 절차 (신설)
보드 화면을 의도적으로 바꾸면 `tests/test_board_render_golden.py` 의 기준 해시가 깨진다.
그런데 **해시는 실행 환경을 탄다** — 윈도우 로컬 Pillow 에는 raqm/harfbuzz 가 없어 글자 배치가
리눅스와 미세하게 달라, 로컬에서 만든 기준값을 커밋하면 CI 가 그날로 빨개진다.

그래서 `.github/workflows/golden-refresh.yml`(수동 실행)을 뒀다. CI 와 같은 환경에서 기준값을
다시 만들어 **그 브랜치에 커밋**한다. 화면 불변이 합격기준인 리팩터에는 돌리면 안 된다.

## 되돌리는 법
- 실사형만 내리기: `web/lib/versions.ts` 의 `REPORT_VERSION_META` 에서 photo 항목 제거
  (엔진은 그대로 둬도 된다 — 저장된 지시서는 계속 렌더된다).
- 허전한 보드를 다시 즉시 실패로: `config.LAYOUT_FAIL_REVIEWABLE = ()`.
- 숫자 확대 되돌리기: `board_render` 의 확대 루프를 `core_is_fallback` 조건 안으로 되돌린 뒤
  골든 해시를 다시 갱신한다.

## 관련
- 파이프라인 진단(실측 근거): 이 결정의 배경. `docs/deviation-density-warning.md` 와 같은 조사.
- 남은 개선 1~3번(BGM 사인파·차트 금지·참조 이미지)은 이 변경에 포함되지 않았다.
