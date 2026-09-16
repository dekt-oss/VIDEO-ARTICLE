# 수집 커버리지 개정 v2 — 최상위 저널 누락 해결

> 근거: 사용자 제공 "수정 명세서 — 수집 커버리지 개정 v2" + 프로덕션 DB 실측(2026.07.19).
> CLAUDE.md 작업 규칙 6에 따른 기록. 사용자 승인 범위: **P0+P1+P2**, 머지 후 라이브 백필 즉시 실행.

## 문제 (SQL 실측으로 확정)
- 플래그십 본지(Nature/Science/Cell/Lancet/NEJM) **역대 수집 0편**, 자매지 4편, LHS 1140b(Science) 부재.
- 원인: 수집기가 `from_publication_date`(게재일) 창만 긁는데, OpenAlex 등록일(`created_date`)이 며칠~수
  주 늦는 플래그십은 게재일 창으로는 지연 폭에 무관하게 항상 놓친다.

## 리뷰 — 명세가 과대평가해 안 건드린 것
- **커서 페이지네이션은 이미 구현돼 있었다**(openalex.py `cursor="*"`→`next_cursor`). §3-4 신규 아님.
- **`per_page=200`은 OpenAlex 공식 최대값** — "규격 위반" 지적은 사실이 아니라 유지.
- **DOI 정규화도 이미 존재**(`util.normalize_doi`), `external_id`=정규화 DOI라 중복제거가 이미 정규화
  기준. §5의 "표기 차이 중복"은 이미 방지됨. 가시성용 `doi` 컬럼만 추가.
- 현재 1차 필터는 buzz를 **하드 게이트로 안 쓴다**(전부 통과→buzz 정렬→상위 N 컷). 바이패스의 실효는
  "탈락 방지"가 아니라 "플래그십을 컷 위로 보장". 근본 원인은 created_date 축이라 그게 1순위.

## 무엇을 바꿨나
### P0 — 규격·config·진단·백필
- `engine/sources/openalex.py`: `select` 필드 제한 + per-work 에 `created_date`·`type`·OpenAlex id·
  `source.id` 보존. `_build_paper`(플래그십 판정), `_run_query`(공통 커서 루프).
- `engine/config.py`: `FLAGSHIP_SOURCES`(source_id·ISSN-L·이름, Nature/Science/Cell/NEJM/Lancet/PNAS —
  OpenAlex API 로 해석, config 확장 가능), `FLAGSHIP_ALLOWED_TYPES`, 워터마크/백필/하한 상수, `PRESS_FEEDS`.
- `engine/diagnose.py`(신규): 누락 DOI 를 OpenAlex 에 직접 질의해 원인 분류(index_lag/source_mapping/
  type_filter/not_in_openalex). CLI `python -m engine.diagnose <doi>`.
- `models.Paper`: `doi`·`work_type`·`openalex_id`·`source_id`·`source_created_date`·`is_flagship` 추가.

### P1 — 플래그십 넓은 게재일 롤링 수집 (핵심)
> ★ 명세 §3-1 은 `created_date` 워터마크를 지정했으나, **OpenAlex `from_created_date` 필터는 유료
>   플랜 전용**("Plan upgrade required")이라 무료 polite pool 로는 불가하다(실측 확인). 그래서 동등한
>   무료 방식으로 대체: **플래그십 6개 source_id 로만 좁힌 넓은 게재일 롤링 창**(기본 30일, 백필 90일)을
>   매 실행 훑는다. 소스가 좁아 볼륨이 작으므로 주 수집의 1000컷 손실이 없고, 게재 당시 미색인이던
>   논문도 창이 넓어 다음 실행에서 반드시 잡힌다(멱등 upsert 라 재수집 안전). LHS 1140b 로 실측 검증.
- `openalex.collect_flagship(pub_from)`: `primary_location.source.id:(목록)` +
  `from_publication_date` + `type:(article|review)` + paratext/retracted 제외, `FLAGSHIP_MAX_RESULTS`.
- 워터마크(`collection_state`)·`get/set_watermark` 는 미사용(향후 유료 전환 대비 코드/테이블만 유지).
- `collect.py`: 주 수집 + 플래그십 워터마크 패스 + `run_flagship_backfill()`(명시 백필) + 발견 이벤트 기록.
- `pipeline.primary_filter`: 프리스티지 바이패스 — 플래그십은 컷오프(상위 N) 밖으로 밀려나지 않고 2차
  채점 진입 보장(진입 보장이지 최종 선정 보장 아님).
- 발견 이벤트 `paper_discovery_events`(0026, §7): 경로별 다건 기록(flagship_openalex/main_openalex/
  arxiv/buzz), papers 는 여전히 1건.

### P2 — 과학 언론 RSS + 다단계 DOI 매칭
- `engine/sources/press.py`(신규): EurekAlert·phys.org·Nature/Science 피드(`feedparser`). **역할=발견 +
  화제성 신호**(품질 근거 아님, 본문 복제 금지). 파서 실패는 로그+무시(전체 중단 금지).
- 다단계 매칭: ①DOI 직접 ②URL 추출 ③arXiv(`extract_external_ids`) ④⑤ 제목 유사도(≥0.94 AND 연도 AND
  제1저자). 해결분은 buzz_map 합류(메타 fetch 로 논문 인입), 미달은 `unresolved_buzz_items`(0026) 큐로.

## 범위에서 뺀 것 (명세 §9 준수)
Crossref 보조 수집(P2 이후)·의료 검증 가드(P1/컴플라이언스 소관, medical_tag 태깅만)·강제 분야 쿼터(P3)·
풀 관측 지표셋. "플래그십 누락 해결" 단일 목표에 집중해 검증 변수를 섞지 않음.

## 검증
- 순수 로직: `tests/test_collection_coverage.py`(플래그십 판정·바이패스·진단 분류·언론 DOI 매칭·제목
  유사도) + 기존 전체 — **pytest 236건 통과**(무회귀).
- 라이브 DB: `0026`(papers 컬럼 + collection_state + paper_discovery_events + unresolved_buzz_items)
  적용(additive nullable).
- **라이브 end-to-end(머지 후)**: engine 워크플로 dispatch → 최초 워터마크 실행이 90일 소급(초기 백필) →
  `select count(*) from papers where title ilike '%LHS 1140%'` ≥ 1 및 플래그십 본지 count > 0 확인.
- **런타임 미검증**: OpenAlex created_date 필터 실호출 결과(플래그십 실수집 편수), RSS 실파싱은 실제
  실행으로 확정(코드·순수 로직 검증까지 완료).
