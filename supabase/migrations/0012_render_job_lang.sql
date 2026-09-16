-- 렌더 잡 언어 선택 (규격 v2 ⑤ 이중언어 운영) — docs/deviation-render-pipeline.md DV11.
-- 하나의 승인 지시서로 한국어/영어 mp4 를 각각(또는 둘 다) 발주할 수 있게 render_jobs 에 lang 추가.
-- 기존 잡은 ko 로 간주(하위호환). 워커(engine.render)가 이 값을 읽어 언어별로 렌더한다.
alter table render_jobs add column if not exists lang text not null default 'ko';
