-- 0038 — report_draft_requests.instruction: ④ 화면의 "세부 수정 요청"을 워커까지 나른다.
--
-- 왜 필요한가: 리포트 ④ 화면에는 "리스크를 더 강조" 같은 수정 요청 입력칸이 있는데,
-- 그 값이 **어디에도 저장되지 않았다**. 라우트(web/app/api/report-generate-draft)가 값을
-- 읽어 두기는 했지만 큐에 넣을 때 빠뜨렸고(워커 경로), 큐 테이블에 담을 칸도 없었다.
-- 결과: 운영자가 무엇을 적든 초안은 똑같이 나왔다. 논문 라인은 엣지 함수로 넘겨서 동작한다.
--
-- 워커가 정본인 리포트 라인(v3 P1 결정)에서는 큐가 유일한 전달 통로라 컬럼이 필요하다.
-- report_scriptgen.generate(fact_sheet, instruction, packet) 은 이미 instruction 을 받는다 —
-- 없던 것은 "큐 → 워커" 구간뿐이다.
--
-- 되돌리기: 이 컬럼을 무시하면 기존 동작(요청 무시)으로 돌아간다. 기본값이 빈 문자열이라
-- 이미 쌓인 행과 옛 코드가 쓰는 행은 그대로 처리된다.

alter table report_draft_requests
  add column if not exists instruction text not null default '';

comment on column report_draft_requests.instruction is
  '④ 화면에서 운영자가 적은 세부 수정 요청. 빈 문자열이면 기본 프롬프트로 생성(최대 800자).';
