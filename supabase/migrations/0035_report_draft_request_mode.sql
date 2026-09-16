-- 0035 — report_draft_requests.mode: 초안 생성과 재검사를 같은 큐로 나른다.
--
-- 왜 필요한가: [재검사] 버튼(web/app/api/report-compliance-check)이 **엣지 함수**를 부르고
-- 있었다. 그런데 근거 게이트(§5)·논증 설계(§6) 재계산은 engine/report_draft.recheck_compliance
-- 에만 있다 — 엣지에는 없다. 그래서 "대본을 고치고 재검사를 눌러도 근거 경고가 옛날 것으로
-- 남는" 상태였고, recheck_compliance 자체는 HTTP 호출자가 하나도 없는 죽은 함수였다.
--
-- 워커를 정본으로 삼은 결정(v3 P1)을 재검사에도 그대로 적용한다. 대가는 초안 생성과 같다 —
-- 즉시가 아니라 워커 주기(report-draft.yml, */15) 안에 처리된다.
--
-- 되돌리기: 이 컬럼을 무시하면 기존 동작(전부 초안 생성)으로 돌아간다. 기본값이 'draft' 라
-- 이미 쌓인 행과 옛 코드가 쓰는 행은 그대로 초안 생성으로 처리된다.

alter table report_draft_requests
  add column if not exists mode text not null default 'draft';

comment on column report_draft_requests.mode is
  '''draft'' = 초안 전체 생성 | ''recheck'' = 편집된 대본으로 컴플라이언스·근거 게이트만 재실행';

-- 큐 폴링이 status 로만 고르므로 mode 는 인덱스에 넣지 않는다(선택도가 낮다).
