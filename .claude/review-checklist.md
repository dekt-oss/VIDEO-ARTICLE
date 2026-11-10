# 리뷰 점검표 — VIDEO-ARTICLE (harness-reviewer 가 항목마다 판정)

근거는 전부 `CLAUDE.md` 에 적힌 규칙이다. 해당 없는 항목은 "해당 없음"으로 판정한다.

- [ ] 조건 없는 `.select()` 를 새로 쓰지 않았다 — 1,000행에서 조용히 잘린다. 엔진은 `db.select_all`, 웹은 `selectIn`/`selectAll`(`web/lib/supabase/chunked.ts`)
- [ ] 파이썬↔엣지 쌍둥이(지시서 프롬프트·논문 초안 한국어 검수)를 한쪽만 고치지 않았다 — `tests/test_prompt_sync.py`·`tests/test_polish_twin_parity.py`
- [ ] 화풍 문자열(`VISUAL_ROLE_STYLE`·`VISUAL_ROLE_NEGATIVE`·`PHOTO_GLOBAL_STYLE`)을 바꿨다면 의도·실측 근거가 있고 `PROMPT_CONTRACT_VERSION` 을 올렸다 — 안 올리면 캐시가 옛 그림을 준다(`tests/test_photo_style_is_locked.py`)
- [ ] 실사형 프롬프트는 `engine/photo_prompt.py` 한 자리에서만 만든다 — 두 공장 공용
- [ ] 대본·화면에 나가는 수치·주장은 Fact Sheet 에 있는 것만 쓴다(리포트 원문 전문은 맥락용) — 환각 방지, 각 씬 `source_facts`
- [ ] 리포트 페이지 번호는 Fact Sheet `source_page` 로 확인된 것만 낸다 — 지어낸 페이지 금지
- [ ] 리포트 [초안 생성]·[재검사] 버튼은 `report_draft_requests` 큐에 적재하고 엣지를 직접 부르지 않는다 — 워커가 정본
- [ ] 발주 기본값을 만화식 하나에서 전 버전으로 되돌리지 않았다(④ 승인 버튼·⑤ `VersionOrderBar`) — 손대지 않고 누르면 돈이 나간다
- [ ] 홈 기본 배치일은 "가장 오래된 미확인", [다음 작업] 카드는 렌더 큐를 띄우지 않는다(`HOME_SKIP`) — `docs/deviation-home-triage-flow.md`
- [ ] `EVIDENCE_OVERLAY_ENABLED`·`OVERLAY_LEGEND_ENABLED` 기본값은 꺼짐 그대로다 — 운영자 고정 결정
- [ ] 돈이 나가거나 외부로 발행되는 새·바뀐 라우트는 운영자 키 게이트(`web/lib/apiGuard.ts`)를 거친다
- [ ] 큐 테이블 쓰기는 service key(`web/lib/supabase/admin.ts`)로 서버 라우트에서만 한다 — anon 쓰기는 막혀 있다
- [ ] 튜닝 상수는 `engine/config.py` 에만 둔다 — 코드에 매직넘버 금지
- [ ] 시크릿(`SUPABASE_SERVICE_KEY`·`ANTHROPIC_API_KEY`·`OPERATOR_KEY` 등)을 `NEXT_PUBLIC_` 로 노출하지 않았다
- [ ] 429·타임아웃으로 실패한 채점은 행을 만들지 않는다(`score.TransientScoringError`) — 다음 실행이 다시 집어야 한다
- [ ] LLM 출력은 JSON only, 파싱 실패 1회 재시도 후 0점 + 로그 — 5xx·타임아웃은 지수 백오프
- [ ] 화면 구성 계약·Jev 경고는 경고·fail-open 이다 — Jev 로 차단을 새로 만들거나 채점에 쓰지 않았다
- [ ] 날짜 계산은 config `TIMEZONE`(Asia/Seoul) 기준이다
- [ ] 수집은 멱등이다 — `papers.external_id` unique + upsert
- [ ] 화풍을 바꿨다면 실측 렌더로 판정하고 핸드오프 문서에 기록했다 — CLAUDE.md "지금 진행 중인 것"
- [ ] id 목록 조회는 `.in()` 을 직접 쓰지 않고 `selectIn`(150개 청크)으로 — id 수백 개에서 헤더 오버플로로 죽는다(`web/lib/supabase/chunked.ts`)
- [ ] webtoon 은 9:16 실측 전 운영에 쓰지 않고, 폐기된 `editorial`·`explainer` 를 되살리지 않는다 — CLAUDE.md "범위"
- [ ] 유튜브 외 플랫폼(IG·TikTok) 발행·분석을 더하지 않는다. 명세와 충돌하는 결정은 `docs/deviation-*.md` 를 남긴다 — CLAUDE.md "범위"·"작업 진행 규칙"
- [ ] 외부 수집은 arXiv 요청 간 3초 + User-Agent 연락처, OpenAlex 는 `mailto` — CLAUDE.md "코딩 규약"
- [ ] 리포트 초안 엣지(`generate-report-draft`)에 한국어 검수 축을 새로 넣지 않는다 — CLAUDE.md "코딩 규약"
- [ ] 실사형 미리보기·렌더로 새 그림을 사는 변경은 비용을 말하고 승인받았다(화면만 바뀌면 `--reuse` 0원 검증) — CLAUDE.md "지금 진행 중인 것"
