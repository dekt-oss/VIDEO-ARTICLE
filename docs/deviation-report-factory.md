# 범위 이탈 기록: 리포트 팩토리 — "하루 한 리포트" 확장 (PF0~PF1)

> CLAUDE.md 작업 규칙 6: "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고 `docs/`를 갱신하며 근거를 남긴다."
> 기준 명세(업로드본): 개발명세서 — 금융 리포트→숏츠 파이프라인 PF0~PF1 (ARIA 수집 연동).
> 기준 재사용: P0-P1(선별·초안) + PV0-PV1(대본→영상). 신규 개발은 (a) ARIA 어댑터 (b) 컴플라이언스 게이트 둘로 국한.

## 무엇이 추가되나

기존 논문 파이프라인("공장 1")에 **두 번째 공장**을 추가한다: 증권사 리포트를 ARIA에서 받아
숏폼으로 만드는 **"하루 한 리포트"**. 같은 사이트·같은 코드베이스를 쓰되 **화면·테이블을 완전 분리**해
두 공장이 섞이지 않게 한다(사용자 요구: "같은 사이트지만 화면은 안 헷갈리게 구분").

- **수집 블록 대체:** OpenAlex/arXiv/HN/Reddit 4종 수집 → **ARIA MCP 호출**로 압축(명세 §2).
- **채점 경량화:** 5축 → **4축**(시의성/이해가능성/스토리성/안전도). 대상이 하루 수~수십 건뿐(명세 §3).
- **컴플라이언스 게이트(PF1, 신규 핵심):** 논문의 "한 줄 의심" 자리에 3층 방어 게이트(명세 §5).
- **화면 분리:** 라우트 `/finance/*` + 공장 스위처 + 바이올렛 강조색(논문=파랑).

## CLAUDE.md 범위와의 충돌

CLAUDE.md 범위는 "P0+P1(논문)"으로 한정된다. 리포트 팩토리는 **명시적 범위 밖의 신규 라인**이므로
이 이탈 문서로 근거를 남긴다. 재사용 전제(P0/P1/PV 코드베이스 미러링)라 신규 표면은 최소.

## 확정 결정 (PFD1~PFD5 / 추천 기본값 — 승인 시 확정)

| # | 항목 | 결정(기본값) | 근거 |
|---|---|---|---|
| **PFD1** | 이번 범위 | **PF0 먼저**(스캐폴딩+ARIA 수집+4축 채점+대시보드+시각분리), 7일 측정 후 PF1 | 명세 로드맵 = PF0 우선. CLAUDE.md "낮은 마일스톤 먼저" |
| **PFD2** | 리포트 공장 강조색 | **바이올렛 `#a855f7`** | 논문 파랑·경고 amber·성공 green 과 안 겹침. 색맹 접근성. 브랜드 📈 병행 |
| **PFD3** | ARIA 연동 방식 | **`engine/aria/client.py` 뒤 추상화.** 우선순위 `ARIA_MCP_URL`(MCP) → `ARIA_BASE`(REST) → fixture | 사용자의 ARIA 는 REST 가 아니라 **MCP 서버**. 엔진이 MCP(streamable HTTP)를 직접 말하도록 `McpAriaClient` 추가(2026-07 확정). 상세는 아래 "PFD3 확정" |
| **PFD4** | 컴플라이언스 block 권한(PF1) | **절대 하드블록** — block 이면 승인 불가 + 서버 라우트 재검증 거부 | 명세 5-3 원칙. 자본시장법 영역 = 미탐지 1건이 규제/소송 리스크 |
| **PFD5** | 채널 통합 vs 분리 | 사용자 확정: **같은 사이트, 화면만 분리**(별도 채널 아님) | 사용자 요구 |

## 아키텍처

```
                 [공장 1 · 논문]                    [공장 2 · 리포트]  ← 신규
수집   OpenAlex/arXiv/HN/Reddit          ARIA list_signals/get_signal/broker_targets
          │ engine/collect.py                  │ engine/report_collect.py (+aria/client.py)
채점   5축 engine/score.py                  4축 engine/report_score.py
DB     papers/scores/daily_batch/...      reports/report_scores/report_daily_batch/...  (병렬 테이블)
화면   /  /review  /render ... (파랑)      /finance/* (바이올렛)  ← data-factory 스코핑
                         └────────── 공유: llm.call_json · db.client() · config · SECRETS · Supabase 클라 ──────────┘
```

**시각 분리 메커니즘:** `globals.css` 의 모든 브랜드 요소가 `--accent` 토큰 하나에서 파생 →
`AppShell` 이 경로로 공장을 판정해 `.app-shell[data-factory]` 를 부여 → `[data-factory="finance"]`
블록이 `--accent`(+`--accent-soft`/`--accent-faint`)만 바이올렛으로 덮어 **전 화면 자동 재색상**.
컴포넌트별 수정은 거의 0. (하드코딩 파랑 리터럴 2곳만 토큰화.)

## 트레이드오프 / 유지보수 주의

- **병렬 테이블(디스크리미네이터 아님):** 두 공장 완전 격리 + 미러 기계적. 대신 테이블/쿼리/타입이
  2배(report_*). 공유 테이블 + kind 컬럼은 FK 정체성·공개 RLS 데이터 혼입 문제로 기각.
- **ARIA 전송방식(PFD3):** fixture 모드는 로컬/테스트 전용. 프로덕션 라이브는 아래 "PFD3 확정" 참조.

### PFD3 확정 — ARIA 는 REST 가 아니라 MCP (2026-07)
런칭 전 미확정으로 남겨뒀던 "실제 HTTP 규격"이, 사용자의 ARIA 가 **REST API 가 아니라 본인이 만든
MCP 서버**임이 확인되며 정리됐다. 엔진이 세션 MCP 를 못 쓰는 제약은 그대로지만, MCP 서버 자체는
로컬/CI 어디서든 HTTP 로 도달 가능하므로 **엔진이 MCP 프로토콜(JSON-RPC streamable HTTP)을 직접
말하도록** `engine/aria/client.py` 에 `McpAriaClient` 를 추가했다.

- **전송 선택 우선순위**(`get_client`): `ARIA_MCP_URL`(MCP) → `ARIA_BASE`(순수 REST, 대안) → fixture.
- **인증:** ARIA MCP 엔드포인트 **URL 경로에 토큰이 포함**돼 별도 헤더 키가 없다. 그래서 `ARIA_MCP_URL`
  자체가 시크릿(GitHub Actions Secret / `.env`). 절대 커밋 금지.
- **프로토콜 관찰(실측):** stateless — `initialize`/세션 핸드셰이크 없이 `tools/call` 단건 POST 로 동작.
  응답은 SSE(`event: message` / `data: {json}`), 도구 반환값은 `result.content[0].text` 에 JSON 문자열.
  트레일링 슬래시 경로에서 응답(그 외엔 307). `McpAriaClient` 가 이 셋을 모두 흡수해 `list_signals` 등
  기존 계약(dict 반환)을 그대로 만족한다 — 나머지 파이프라인(`report_collect`/`report_score`)은 불변.
- **자동화:** `.github/workflows/report.yml` 이 `ARIA_MCP_URL` Secret 을 읽는다. 등록만 하면 매일
  07:10 KST 크론이 라이브 후보를 채운다. 미등록이면 워크플로가 경고 후 fixture 모드로 돈다.
- **검증:** `tests/test_aria_mcp_client.py`(SSE 파싱·인자 매핑·에러 전파, 네트워크 없음). 라이브 관통은
  이 세션에서 실측 확인(2026-07-19 신호 수집→4축 채점→`report_daily_batch` 15건 생성).
- **컴플라이언스 프롬프트 동기화(PF1):** 클라우드 트윈을 만들면 가장 민감한 프롬프트가 이중 관리.
  → 컴플라이언스 LLM 심사관은 **엔진 전용** 권장(동기화 표면 최소화).

## 저작권·컴플라이언스 안전장치 (수집/저장 단계)

- 원문 전문(ARIA `raw_content`)은 **저장하지 않음** — `summary` 요약만 `REPORT_SUMMARY_MAX_CHARS` 로 제한.
  산출물(자막·나레이션)은 사실 재구성 자체 표현만(표현 복제=침해, 사실 재구성=안전).
- 목표가·의견은 **사실 인용용**으로만 부착(정규화·가공 금지). 상승여력%·수익률 훅 금지(PF1 게이트가 검사).
- **⚠️ 열린 확인(부록 C, 최우선):** ARIA 리포트 원 소스가 공개 채널인지 고객게이트 뒤인지 —
  런칭 전 적법성 확정 필요. 개발과 별개(법률 판단). 코드에는 조사 결과만 주석/문서로.

## 합격기준 (명세 §10)

**PF0(선별):** 상위 후보 중 사람 낙점 가능 ≥3건 / 7일 중 5일. 미달 시 4축 가중치·ARIA 상위 N 조정(config).
- *코드 단위 자가검증:* 순수 로직 테스트(`tests/test_report_scoring.py`) 통과 + web lint/build 통과 +
  ARIA fixture→정규화 관통(원문 미저장·멱등 키 유니크 확인).

**PF1(초안+게이트):** 낙점→승인 ≤30분/건 + **게이트 미탐지 0건**(위반 대본 20개 재현율 사전 측정) +
발행 판정 대본 사실오류 0건.

## 운영 선행조건

- **PF0:** `0018_report_pipeline.sql` 적용(Supabase). `ANTHROPIC_API_KEY`(채점). ARIA 연동은
  fixture 로 우선 검증, 실데이터는 `ARIA_BASE`/`ARIA_API_KEY` 설정 시(PFD3 확정 후).
- **PF1:** `0019_report_p1.sql` 적용. 초안 생성 = 대시보드 버튼 → `report_draft_requests` 큐 →
  로컬 워커(`python -m engine.report_draft`) 또는 엣지 함수(`generate-report-draft`) 소비.
- 런칭 전 **변호사 자문 1회**(상대가 실제 소송 중인 증권사 + 자본시장법 영역).

---

## PF1 확정 사항 (초안 + 컴플라이언스 게이트)

### 컴플라이언스 게이트 3층 (명세 §5, 이 확장의 심장)
- **층1 규칙기반**(`engine/report_compliance.py::scan_rules`, 순수 함수): config 정규식으로
  투자권유·미실현수익률·단정예측 스캔 + 출처(broker)·면책 누락 검사. 단위 테스트로 검증.
- **층2 LLM 심사관**(`_llm_judge`): 권유/수익률광고/단정/출처/면책 예-아니오 판정. 호출 실패 시
  **보수적 전부 위반**(통과시키지 않음).
- **층3 자기검증 접합**: 근거 없는 문장 = 환각+컴플라이언스 이중 플래그.
- **`blocked` 는 증거에서 재계산**(selfcheck `all_grounded` 재계산 패턴 — LLM boolean 불신).
  규칙 block 위반 / LLM 위반 / 출처·면책 missing / 미근거 문장 중 하나라도 있으면 차단.

### 하드게이트 (PFD4) — 이중 방어
- **UI**: `CompliancePanel` 이 `blocked` 시 [승인] 버튼 비활성.
- **서버(진짜 게이트)**: `/api/report-approve` 가 `report_drafts.compliance.blocked` 를 재검증해
  차단 시 403 거부. UI 우회로 승인 불가. 사람이 대본 수정 → [재검사] 통과해야 발행 가능.

### 클라우드 트윈 (이중관리 주의)
- `supabase/functions/generate-report-draft/index.ts` = 논문 `generate-draft` 미러 + 컴플라이언스
  + recheck 모드. 프롬프트·정규식·정규화·모델 ID 를 Python(`engine/report_*`)과 **반드시 동기화**.
  특히 컴플라이언스가 가장 민감 — 규칙을 어긋나게 두지 말 것.
- ★ 미검증: Deno 런타임 부재로 이 세션에서 함수 실행/타입체크 불가. 컴플라이언스 정규식 층만
  node 로 Python 파리티 확인함. **첫 `supabase functions deploy` 시 관통 검증 필요.**

### 네비게이션 (사용자 피드백)
- 단일 상단 고정 바(`TopBar`) — 공장 스위처 + 주요 탭 상시 노출. 모바일 햄버거 왕복 불편 해소.
  `lib/nav.ts` 로 두 공장 네비 정의 공유. `data-factory` 강조색(논문 파랑 / 리포트 바이올렛) 유지.

### 범위 밖(다음 단계, 사용자 승인)
- 영상 지시서·렌더·유튜브 업로드는 PF2 로 보류(논문 PV 파이프라인 재사용 + 출처·면책 자막 레이어).
