# 작업지시서 — 모션그래픽 엔진에 '뉴스 출처' 편 정식 지원 (Codex 구현용)

> 2026-11-27 · 운영자 지시: "엔진에 정식으로 올리는건 코덱스에서 진행" · 브랜치 `claude/motion-news-source`

## 배경 (사실만)
- 2026-11-26 운영자가 국고채 담합 사건(공정위 2026-11-11 발표)을 뉴스 기사로 조사해 영상화를 지시했다.
- 모션 엔진(`engine/motion/`, PR #196)은 증권 리포트 전용이라, 1회용 스크립트로 만들었다:
  - 지시서·근거표: `tests/fixtures/motion_news_ktb.json` (뉴스 사실 9줄 → `fact_sheet.what`, 컷 9개)
  - 렌더: `schema.normalize_motion_directive` → `build.build_project` → **생성된 HTML 문자열을 치환** → `npx hyperframes render` → loudnorm.
  - 치환한 문구(엔진에 리포트 전용으로 박혀 있는 것):
    | 원래 | 뉴스 편 |
    |---|---|
    | `출처 · 증권사 리포트` (끝 카드 머리) | `출처 · 공정위 발표 · 언론 보도` |
    | `자세한 내용은 리포트 원문을 확인하세요` | `업체 측 불복 예정 · 법원 판단 전` |
    | `투자 권유 아님` (끝 카드 배지) | `공정위 판단 기준` |
    | `자료: 증권사 리포트` (장면마다 출처 줄, broker 가 빈 값일 때) | `자료: 공정위 발표 · 언론 보도` |
  - 결과는 하루지식하나 채널에 비공개 업로드됨(video id `WEgaO0ISW0M`).

## 할 일
1. **출처 종류를 메타로 받기.** `meta`(또는 fixture 최상위)에 출처 문구를 넣을 수 있게 해서, 위 4곳이 하드코딩 대신 메타 값을 쓰게 한다.
   리포트 경로(`engine/report_render.py` 의 `motion_meta`)는 **값을 안 주면 지금 문구 그대로** 나와야 한다(기존 리포트 영상 회귀 0).
   폴백 카드 제목 `리포트 요약`(`schema._fallback_slots`) 등 다른 리포트 전용 문구가 있으면 같이 찾아 같은 방식으로.
2. **CLI:** `python -m scripts.motion_preview tests/fixtures/motion_news_ktb.json` 한 줄로 위 1회용 결과와 같은 영상이 나오게(치환 스크립트 불필요).
3. **테스트:** 뉴스 fixture 로 `build_project` 한 HTML 에 `증권사 리포트`·`투자 권유 아님`·`리포트 원문` 이 **없음**,
   리포트 fixture(`motion_usedcar.json`)는 기존 문구가 **있음**. 숫자 검문 경고 0건.
4. **이탈 기록:** `docs/deviation-motion-news-source.md` — 리포트·논문 밖(뉴스) 재료로 영상을 만드는 범위 예외. 무엇이/왜/지키는 원칙
   (화면 숫자는 근거표에 단위째 있어야 함 · 의혹 제기 톤은 '공정위 판단'처럼 주체를 밝힘 · 법원 판단 전 표기)/되돌리는 법. CLAUDE.md 승인된 예외 목록에 한 줄.
5. (선택, 작으면) 로컬 mp4 를 채널 가드 거쳐 **비공개로만** 올리는 스크립트 `scripts/motion_upload_local.py`
   (`engine.providers.youtube.upload_video(..., channel_key="report_ko", privacy_status="private")`). 공개 업로드 옵션은 만들지 않는다.

## 하지 말 것
- 대시보드·DB 스키마·워크플로 변경(뉴스 수집 자동화는 이번 범위 아님).
- 화풍·photo 관련 상수, `VIDEO_VERSIONS` 변경.
- 유료 API 호출, 실제 유튜브 업로드, push·머지.

## 검증
- `python -m pytest -q tests/test_motion_engine.py` 와 전체 `pytest -q` 통과(메모리: 웹 변경 없어도 전체).
- `python -m scripts.motion_preview tests/fixtures/motion_news_ktb.json --build-only` 경고 0, 길이 약 70초.
- 커밋은 작게, 브랜치 `claude/motion-news-source` 에만. 마지막에 변경 요약과 검증 출력 줄을 남긴다.
