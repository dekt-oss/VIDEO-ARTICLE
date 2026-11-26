# 모션그래픽 뉴스 출처 범위 예외

2026-11-27 운영자 승인: `docs/plans/2026-11-27-motion-news-source.md`.

## 무엇이 달라지는가

논문·증권 리포트 밖의 뉴스도 운영자가 근거표와 지시서를 준비한 경우 기존 모션 엔진으로 로컬 영상화한다.
뉴스 수집 자동화, 대시보드, DB 스키마, 워크플로는 이번 예외에 포함하지 않는다.
기존 HTML 사후 치환을 없애고 fixture의 `meta`로 출처와 끝 카드 문구를 명시한다.
유료 API 호출, 실제 유튜브 업로드, push·머지는 이번 작업에서 실행하지 않는다.

## 왜 필요한가

국고채 입찰 담합 사건은 공정위 발표·언론 보도가 출처다. 증권사 리포트라는 고정 문구와 투자 면책 대신
실제 출처, 판단 주체와 법적 진행 상태를 보여줘야 한다. 템플릿·숫자 검문·렌더 흐름은 그대로 재사용한다.

## 메타 계약과 실행

운영자가 작성하는 fixture `meta`의 선택 항목:

| 항목 | 용도 | 생략·빈 값일 때 기존 기본값 |
|---|---|---|
| `source_label` | 끝 카드의 `출처 · …`, 장면의 `자료: …` | 끝 카드: 증권사 리포트 / 장면: broker, 없으면 증권사 리포트 |
| `end_note` | 끝 카드 안내 | 자세한 내용은 리포트 원문을 확인하세요 |
| `end_badge` | 끝 카드 배지 | 투자 권유 아님 |
| `fallback_title` | 숫자 검문 실패·알 수 없는 템플릿 등의 설명 카드 제목 | 리포트 요약 |
| `default_title` | 제목·훅이 없는 지시서의 상단 제목 | 오늘의 리포트 |

정규화 호출은 `normalize_motion_directive(..., meta=meta)`이며, 같은 메타를 `build_project` 또는 `render`에 넘긴다.
기존 리포트 경로 `motion_meta`는 새 항목을 지정하지 않으므로 기존 문구와 데이터 계약을 유지한다.
뉴스용 LLM 생성 경로는 추가하지 않는다. 리포트 지시서 생성 프롬프트는 기존 리포트 전용으로 유지한다.

```bash
python -m scripts.motion_preview tests/fixtures/motion_news_ktb.json --build-only
python -m scripts.motion_preview tests/fixtures/motion_news_ktb.json
```

build-only도 음성 길이·큐 계산을 위해 무료 Edge TTS와 ffmpeg가 필요하다. mp4 인코딩만 생략한다.

## 지키는 원칙

- 화면 숫자는 해당 컷의 `source_facts`가 가리키는 근거표에 단위째 있어야 한다. 기존 숫자 검문을 우회하지 않는다.
  출처 메타(`source_label`·`end_note`·`end_badge`)의 숫자는 지우지 않고 `motion_meta_number_ungrounded` 경고만 낸다(운영자 작성 문구라 fail-open).
- 의혹·행정 판단은 `공정위 판단`처럼 주체를 밝힌다. 법원의 확정 판단처럼 단정하지 않는다.
- 업체 측 반박·불복 예정과 `법원 판단 전` 상태를 명시한다.
- 쪽수는 근거표 `source_page`에서만 붙이고, 메타 문자열은 HTML 이스케이프한다.
- 새 메타는 LLM 출력이 아닌 운영자가 준비한 fixture에서 받는다. 출처 메타로 근거 사실을 추가하지 않는다.

## 되돌리는 법

뉴스 fixture의 사용을 중단하면 기존 리포트 경로는 그대로 동작한다. 메타 기능을 완전히 제거하려면
이번 구현 커밋을 `git revert`하고, 이 문서와 CLAUDE.md의 뉴스 예외 한 줄을 추가한 문서 커밋도 되돌린다.
DB·워크플로 변경이나 데이터 마이그레이션은 없다.
