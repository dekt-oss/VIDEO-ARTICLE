-- 초안(P1) 강화: 전체 세부 영상 흐름(스토리보드)을 drafts 에 저장.
-- 씬별 이미지/영상 프롬프트는 기존 video_prompts(jsonb) 안에 필드로 들어가므로 스키마 변경 불필요.
-- video_flow 만 신규 컬럼(nullable — 기존 초안 하위호환).
alter table drafts add column if not exists video_flow jsonb;
