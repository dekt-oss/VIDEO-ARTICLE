-- 검수 화면 인라인 장면 편집(drafts.video_prompts) 저장 허용.
-- drafts 는 0002/0007 에서 select 전용이었다(엔진이 service_role 로 insert/갱신). 이제 사람이
-- 대시보드에서 장면(나레이션·프롬프트)을 직접 다듬어 저장하므로 update 권한이 필요하다.
-- 0007 의 공개(anon 쓰기) 포스처와 일관 — 데이터는 비민감(대본/프롬프트)이며 service_key 는 여전히 서버 전용.
-- insert/delete 는 부여하지 않는다(초안 생성/대체는 계속 엔진·엣지함수의 service_role 담당).
drop policy if exists drafts_public_update on drafts;
create policy drafts_public_update on drafts
  for update to anon, authenticated
  using (true) with check (true);
