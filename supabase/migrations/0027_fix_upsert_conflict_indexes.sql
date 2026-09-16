-- 0026 핫픽스 — PostgREST on_conflict 은 coalesce() 표현식 unique 인덱스를 대상으로 못 삼는다(42P10).
-- 이미 0026 을 적용한 환경(라이브 포함)에서 잘못된 표현식 인덱스를 평문 컬럼 NULLS NOT DISTINCT 로 교체.
-- (0026 파일 자체도 올바른 형태로 수정돼 있어, 신규 배포는 0026 만으로 정상 — 이 파일은 기존 환경 정정용.)

drop index if exists uq_unresolved_buzz;
create unique index if not exists uq_unresolved_buzz
  on unresolved_buzz_items (route, source_item_url) nulls not distinct;

drop index if exists uq_paper_discovery_event;
create unique index if not exists uq_paper_discovery_event
  on paper_discovery_events (route, external_id, source_item_url) nulls not distinct;
