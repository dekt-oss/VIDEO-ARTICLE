# 수정지시서 — 리포트 공장 → 하루한편 KO 채널 통합 (v2)

- **상태:** M1·M2 구현 완료 · 실업로드 관통 대기. §3-1 파생 규칙은 §1-1 로 재설계했다.
- **커밋 경로:** `docs/specs/20260730-report-merge-into-paper-ko.md`
- **선행 명세서:** `docs/specs/20260730-youtube-multichannel-upload.md` (이하 **PY 명세서**)
- **v1 대비 변경:** 채널 적합성 게이트(block/warn) 전면 삭제. 콘텐츠 제약 없음. 분류·측정으로 대체.

---

## 0. 결정과 범위

### 0-1. 결정
**금융 리포트 영상의 유튜브 자동 업로드 대상을 "오늘의 컨센선스" 채널에서 하루한편 KO 채널로 변경한다.**

### 0-2. 콘텐츠 제약 — 없음
- 개별 종목 리뷰를 포함해 기존 리포트 공장 산출물은 전부 그대로 발행한다.
- 본 지시서는 **콘텐츠 규칙을 신설하지 않는다.**
- 기존 `report_compliance.check` 3층 게이트(자본시장법)는 **그대로 유지**한다.

### 0-3. 통합의 트레이드오프
| 얻는 것 | 감수하는 것 |
|---|---|
| 관리 부담 절감 (채널 1개, 토큰 1개) | **blast radius** — 채널 단위 제재 시 논문 채널까지 영향 |
| 하락장·박스권에서 채널 동면 회피 | 시청자 기대 불일치 시 신작 초기 유통 저하 가능 (크기 미지) |
| 신규 채널 콜드스타트 회피 | 구독자 이탈 가능 (크기 미지) |

"크기 미지" 항목은 §5로 측정하고, 신호가 나오면 §4로 되돌린다.

---

## 1. 런타임 탐색 결과 (2026-07-29 확정)

| 항목 | 값 | 상태 |
|---|---|---|
| PY 명세서 구현 여부 | **구현됨** — `engine/youtube_channels.py`(레지스트리·가드), `engine/youtube_types.py`(계약) | ✅ |
| 기존 KO 채널 시크릿 이름 | `YOUTUBE_REFRESH_TOKEN_KO` | ✅ |
| 리포트 업로드 워커 경로 | `engine/report_publish.py` (`upload_video` 호출은 104행) | ✅ |
| 업로드 실행부 | `engine/providers/youtube.py:upload_video` (`videos().insert`) | ✅ |
| publish 워크플로 파일명 | `report-publish.yml`(리포트) · `publish.yml`(논문) | ✅ |
| 업로드 결과 테이블 | `report_upload_requests`(0029) · 발행기록 `report_published` | ✅ |
| `paper_ko` 채널 | 하루지식하나 · `UCHKqm3lkVYkS1xwGjF1M9ug` | ✅ |
| `report_ko` 기존 채널(되돌리기용) | 오늘의 컨센선스 · `UCdxvMA1f8U50d5OUmxoNsDw` | ✅ |
| `fact_sheet.company` | 존재하나 **종목·테마를 함께 담는다** — §1-1 참조 | ⚠️ 가정 불일치 |
| `series_id` | 지시서 header 키로 존재하나 리포트 라인에서 채우는 코드 없음(빈값) | ⚠️ §6-1 결정 대기 |

### 1-1. ★ §3-1 파생 규칙 재설계 (지시서 §6-2 가 예고한 경우)

지시서 §3-1 은 `content_type = "entity" if fact_sheet.get("company") else "industry"` 를 제안했다.
**이 규칙은 이 저장소에서 동작하지 않는다.**

`engine/report_factsheet.py:18` 의 프롬프트가 `"company": "<종목/테마>"` 로 정의돼 있어, 테마
리포트에서도 이 필드가 채워진다. 실제 데이터로 확인:

```sql
select ticker, company, theme, fact_sheet->>'company' from reports r join report_drafts d …
→ theme='로봇',   fact_sheet.company='로봇'
   theme='시황',   fact_sheet.company='시황'
   theme='메모리반도체', fact_sheet.company='메모리반도체'
```

즉 `fact_sheet.company` 는 사실상 "대상명"이라 **전부 `entity` 로 분류된다.**

집계는 더 분명하다(`reports` 146행 기준):

| 컬럼 | 채워진 행 |
|---|---|
| `ticker` | **0** |
| `company` | **1** |
| `theme` | **143** |

**재설계한 규칙 — `reports` 테이블의 구조 필드에서 파생한다(텍스트 분류기 없음):**

```python
content_type = "entity" if (report.get("ticker") or report.get("company")) else "industry"
```

`reports.ticker`(종목코드)와 `reports.company`(종목명)는 ARIA 수집기가 **개별 종목 신호일 때만**
채우는 컬럼이고, 테마 신호는 `theme` 로 들어온다. 지시서가 요구한 "구조에서 파생, 정규식 분류기
금지" 원칙은 그대로 지킨다.

> **정직하게 남기는 한계:** 현재 데이터로는 실질적으로 전부 `industry` 로 분류된다(ticker 0건).
> 따라서 **§5-2 의 entity vs industry 비교는 지금은 돌릴 수 없다** — ARIA 가 종목 단위 신호를
> 채우기 시작해야 표본이 생긴다. 컬럼은 그때를 위해 미리 남긴다(비용 0).
> 이는 §3-4 "판정은 표본이 모인 뒤 수동으로" 원칙과 일치한다.

---

## 2. M1 — 업로드 라우팅 변경

### 2-1. `CHANNEL_REGISTRY` 최종 상태

`report_ko` 의 **값 3개만** 바꾼다. 키·구조·호출부는 그대로다.

```python
"report_ko": {
    "key": "report_ko",                          # 출처(공장) 식별자 — 유지
    "title": "하루지식하나",                       # 목적지 채널명
    "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug",    # paper_ko 와 동일
    "secret_env": "YOUTUBE_REFRESH_TOKEN_KO",    # paper_ko 와 동일
    "lang": "ko",
    "tz": "Asia/Seoul",
}
```

> **채널명 정정:** 지시서 초안은 채널명을 "하루한편"으로 적었으나 실제 채널명은 **하루지식하나**
> (`@paperaday`)다. PY 명세서 §9-2 에서 공개 채널 페이지로 확인한 값을 쓴다.

### 2-2. `report_ko` 키를 삭제하지 않는 이유
키를 지우고 호출부를 `paper_ko` 로 바꾸면 "이 영상이 리포트 공장 산출물"이라는 정보가 소실되어
§5 측정과 §4 되돌리기가 불가능해진다. **키는 출처(공장), 값은 목적지(채널)** 로 역할을 분리한다.

### 2-3. 수정 태스크
- [x] `CHANNEL_REGISTRY["report_ko"]` 값 변경 (§2-1)
- [x] `YOUTUBE_REFRESH_TOKEN_REPORT_KO` 직접 참조 제거 → `CHANNEL_REGISTRY[key]["secret_env"]` 경유
- [x] publish 워크플로 env 주입 정리
- [x] `assert_correct_channel()` 유지 — 업로드 경로에 **실제 배선**(PY 명세서 A4 를 여기서 완료)
- [x] 업로드 결과 기록에 `channel_id` 저장 (M2, 0032)
- [x] 음성 테스트 대상 교체: `paper_en` 토큰으로 `report_ko` 업로드 → `ChannelMismatchError`
      (paper_ko ↔ report_ko 는 이제 같은 채널이라 음성 테스트로 쓸 수 없다)

---

## 3. M2 — 분류·측정 (게이트 아님)

### 3-1. `content_type` 파생
§1-1 의 재설계 규칙을 쓴다. `reports.ticker` / `reports.company` 에서 파생.

### 3-2. 스키마 추가
| 컬럼 | 타입 | 값 |
|---|---|---|
| `source_factory` | text | `"paper"` \| `"report"` |
| `content_type` | text | `"entity"` \| `"industry"` (paper 는 NULL) |
| `series_id` | text | §6-1 결정 대기 — 확정 전까지 지시서 header 값 그대로(빈값 가능) |
| `channel_id` | text | 실제 업로드된 채널(사후 감사용) |

### 3-3. 태그
- `engine/config.py` 에 `CHANNEL_CORE_TAGS_KO` 신설 — 하루한편 공통 태그 ✅
- 최종 태그 = 공통 태그 + 영상별 태그, 500자 제한 준수 (`providers/youtube._fit_tags`) ✅

### 3-3-1. ★ 아카이브 필터는 "한 줄 수준"이 아니다 — 보류

지시서는 대시보드 아카이브에 `source_factory`/`content_type` 필터를 한 줄 수준으로 추가하라고
했으나, 실제 `web/app/finance/archive/page.tsx` 는 **초안 목록**(`getReportDraftList`)을 그리고
있고 업로드 레코드를 읽지 않는다. 필터를 붙이려면 업로드 테이블 조인·쿼리·타입까지 손봐야 해서
한 줄이 아니다.

**보류하고 SQL 로 대체한다.** §5 측정은 어차피 유튜브 성과 데이터와 함께 SQL 로 뽑는다:

```sql
select source_factory, content_type, series_id, channel_id, youtube_url, requested_at
from report_upload_requests where status='done' order by requested_at desc;
```

필터 UI 가 실제로 필요해지는 시점(발행 5~10편 이후, §5 판정 때)에 만든다.

### 3-4. 만들지 않는 것
자동 리텐션 비교, 알림, 차트, 발행 비율 제한 코드. **판정은 표본이 모인 뒤 수동으로 한다.**

---

## 4. 되돌리기 절차 (Rollback)

되돌림 신호가 나오면 아래만 바꾼다. **코드 로직 변경 0.**

```
1. engine/youtube_channels.py 의 CHANNEL_REGISTRY["report_ko"] 3개 값을 컨센선스로 교체
     title       "하루지식하나"              → "오늘의 컨센선스"
     channel_id  UCHKqm3lkVYkS1xwGjF1M9ug  → UCdxvMA1f8U50d5OUmxoNsDw
     secret_env  YOUTUBE_REFRESH_TOKEN_KO  → YOUTUBE_REFRESH_TOKEN_REPORT_KO
2. report-publish.yml 에 YOUTUBE_REFRESH_TOKEN_REPORT_KO env 주입 복원
3. CHANNEL_CORE_TAGS_KO 적용 대상에서 report 제외
```

**전제:** 유튜브는 채널 간 영상 이동을 지원하지 않는다. 이미 올라간 금융 영상은 옮기지 않는다.

**되돌릴 옵션 보존:**
- "오늘의 컨센선스" 채널을 **삭제하지 않는다.**
- `YOUTUBE_REFRESH_TOKEN_REPORT_KO` GitHub Secret 을 **삭제하지 않고 방치**한다(재발급 생략용).
  단 코드 참조는 0건이어야 한다(§9 DoD).

---

## 5. 측정

금융 소재 **5~10편 발행 후** 판정. 5편 미만으로 판단하지 않는다. 비교는 중앙값, 같은 길이 구간끼리.

### 5-1. 되돌림 판정
| 지표 | 되돌릴 신호 |
|---|---|
| ① 금융 영상 **직후** 비금융 영상의 `avg_percentage_viewed` | 기존 중앙값 대비 명확히 하락 |
| ② 금융 영상 발행일의 `subscribers_lost` | 평상시 대비 증가 |

①과 ②가 함께 나빠지면 → §4 복귀. 하나만 흔들리면 표본을 더 모은다.

### 5-2. 부수 실험 — `entity` vs `industry`
**현재 실행 불가**(§1-1 — ticker 0건). ARIA 가 종목 단위 신호를 채우기 시작하면 그때 돌린다.

§5-1 이 나쁘고 §5-2 에서 한쪽 `content_type` 만 나쁘면 **채널 문제가 아니라 소재 문제**다.
이 경우 되돌리지 말고 소재 비중을 조절한다. 두 판정을 섞지 않는다.

---

## 6. 열린 질문

### 6-1. 사람이 결정 (미해소)
| 항목 | 선택지 | 상태 |
|---|---|---|
| 시리즈 타이틀 (화면 상단 헤더) | **"오늘의 리포트" 로 변경** | ✅ 결정(2026-07-30) — `config.REPORT_SERIES_TITLE` |
| `series_id` 필러 코드 | 기존 `C`(AI·경제) 편입 / 신규 `F` | **결정 대기** — 구분 가능한 쪽이 §5 측정에 유리 |
| 발행 비율 제한 | 코드로 강제하지 않음 | 운영 습관으로 관리 |

### 6-2. 확인 완료
- 하루한편 KO refresh token 발급·동작 중 — `youtube-token-check` 로 확인(2026-07-29).
- 리포트 파이프라인은 KO 전용. EN 리포트는 범위 밖.
- `fact_sheet.company` 가정 → **불일치. §1-1 로 재설계.**

---

## 7. 유지되는 것 (변경 금지)
| 항목 | 이유 |
|---|---|
| `report_compliance.check` 3층 게이트 | 자본시장법 |
| 하단 고정 면책 자막 (`출처 {broker} · {면책}`) | 법적 요구 + 시리즈 시각 구분 |
| 출처·증권사 귀속 규칙 | 저작권·귀속 |
| 리포트 지시서·대본 프롬프트의 소재·제목 규칙 | 콘텐츠 규칙 신설 안 함 |
| `assert_correct_channel()` | 채널 오배송 방지 |

---

## 9. Definition of Done
- [x] `grep -rn "REFRESH_TOKEN_REPORT" .` → `docs/` 외 **기능 참조 0건**
      (되돌리기 안내 주석 3줄은 §4 가 요구하는 복원 절차라 의도적으로 남겼다)
- [x] 채널 ID 하드코딩이 `youtube_channels.py` 밖에 **0건**(단독 실행 도구 2개는 테스트로 대조)
- [ ] 리포트 영상 1편이 하루한편 KO 채널에 실제 업로드, `assert_correct_channel` 통과
- [ ] **음성 테스트:** `paper_en` 토큰으로 `report_ko` 업로드 → 업로드 전 `ChannelMismatchError`
- [ ] 업로드된 영상에 하단 면책·출처 자막 존재(프레임 캡처 확인)
- [x] 기존 `report_compliance.check` 동작 변화 없음(회귀 테스트)
- [x] 업로드 레코드에 `source_factory`·`content_type`·`series_id`·`channel_id` 기록 (0032 적용 완료)
- [x] `CHANNEL_CORE_TAGS_KO` 가 최종 태그에 포함되고 500자 미초과 (테스트로 고정)
- [x] §4 되돌리기 절차가 런북에 기록됨 (`docs/runbook-youtube-token.md` §5)

---

*작성 2026-07-30 (v2). §1 탐색에서 `fact_sheet.company` 가정이 깨져 §3-1 을 재설계했다(§1-1).
채널명은 실제 값(하루지식하나)으로 정정했다.*
