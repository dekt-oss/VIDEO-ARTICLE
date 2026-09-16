-- 제목 한글 번역 병기: scores.title_ko 추가.
-- 채점 LLM이 one_liner_ko 와 같은 호출에서 제목 번역을 함께 산출한다.
-- 대시보드는 영문 원제(papers.title) + 한글 번역(scores.title_ko)을 병기하고,
-- 값이 없으면 영문만 표시(우아한 폴백).
alter table scores add column if not exists title_ko text;
