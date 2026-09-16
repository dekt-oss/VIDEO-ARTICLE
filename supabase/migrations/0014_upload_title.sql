-- 유튜브 업로드용 자극적 제목(한/영) 저장: drafts 에 upload_title_ko/en 추가.
-- 대본 생성 LLM(SCRIPT_SYSTEM)이 script_md·scenes 와 같은 호출에서 함께 산출한다.
-- 논문 제목(papers.title)·번역제목(scores.title_ko)은 비자극적이라 업로드 훅으로 한계 →
-- 클릭 유도형 제목을 별도로 둔다. 값이 없으면 대시보드가 논문 제목으로 폴백(우아한 하위호환).
-- nullable — 기존 초안(제목 없는)도 그대로 동작. RLS 는 0013 의 anon update 정책이 커버.
alter table drafts add column if not exists upload_title_ko text;
alter table drafts add column if not exists upload_title_en text;
