-- 0048 — updated_at 은 **대본 내용이 바뀔 때만** 올린다 (0046·0047 후속, 2026-09-11 리뷰).
--
-- 0046/0047 트리거는 행이 UPDATE 되기만 하면 now() 를 찍었다. 그런데 updated_at 의 쓰임새는 딱
-- 하나 — "지시서가 옛 대본 기준인가"(web/lib/work/decision.ts::isStale) — 이고, 대본이 아닌 칸을
-- 쓰는 UPDATE 가 지시서 이후에도 있다:
--   · 논문: 발행 제목만 저장(/api/draft-update 의 upload_title_*) → 모든 지시서가 "옛 대본 기준",
--     주 버튼이 [지시서 재생성](유료 LLM 호출)으로 바뀌고 승인이 잠긴다.
--   · 리포트: [재검사](engine/report_db.py · 엣지 폴백)가 compliance·evidence·fact_sheet·
--     self_check·scenes 를 쓴다 → 재생성 → "재검사 권장" → 재검사 → 또 낡음, 고리가 돈다.
-- 그래서 테이블마다 "지시서 생성기가 대본으로 읽는 칸"만 본다:
--   · drafts        : script_md, video_prompts(씬 — 논문 지시서 생성기 입력)
--   · report_drafts : script_md 만. 리포트 지시서 생성기는 script_md 가 정본이고 scenes 는
--                     대본과 맞을 때만 싣는다(engine/report_directive.py · scenes_match_script).
--                     재검사가 scenes 를 대본에 다시 맞추는 것은 낡음이 아니다.
-- 명시 지정(0047 백필)은 계속 존중한다.
create or replace function drafts_touch_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.updated_at is not distinct from old.updated_at
     and (new.script_md is distinct from old.script_md
          or new.video_prompts is distinct from old.video_prompts) then
    new.updated_at = now();
  end if;
  return new;
end $$;

create or replace function report_drafts_touch_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.updated_at is not distinct from old.updated_at
     and new.script_md is distinct from old.script_md then
    new.updated_at = now();
  end if;
  return new;
end $$;

drop trigger if exists drafts_set_updated_at on drafts;
create trigger drafts_set_updated_at before update on drafts
  for each row execute function drafts_touch_updated_at();
drop trigger if exists report_drafts_set_updated_at on report_drafts;
create trigger report_drafts_set_updated_at before update on report_drafts
  for each row execute function report_drafts_touch_updated_at();

-- 0046/0047 의 범용 함수는 이제 쓰는 곳이 없다. cascade 없이 지운다 — 다른 트리거가 쓰고
-- 있으면 여기서 실패해 알려준다.
drop function if exists set_updated_at();
