-- 주류 — 작업 단위 뷰의 거짓 경고 고침 (2026-11-06)
--
-- 무엇이 — 왜: drink_work_items.review_valid 가 "현재 근거"(작업 중 초안일 때가 많다)가 승인본이 아니면 false 였다.
--   화면 결정 함수(web/lib/drinks/work/decision.ts B3)는 false 를 "근거가 철회·만료됐다"로 읽어, 근거 초안이 있는 모든 소재에
--   [근거 재확인 → 새 버전] 이 떴다(운영자 캡처 2026-11-06). 승인본이 아니면 null(판단 대상 아님)로 바꾼다.
--   승인본이면 그대로: 철회되지 않았고 지금도 유효한가.
-- 바뀌지 않는 것: 다른 열·조인·행 수. 승인·결재 함수는 손대지 않는다(이 뷰는 읽기 전용 화면 입력).
-- 되돌리기: 0072 의 create or replace view drink_work_items 를 다시 실행한다.

create or replace view drink_work_items with (security_invoker = true) as
with units as (
  select 'topic:' || fp.topic_id::text || ':' || fp.format_intent as unit_id, fp.topic_id, t.title, t.question, t.status as topic_status, t.version as topic_version,
    fp.format_intent, 'topic'::text as source, fp.editorial_week, fp.approved_at as pick_approved_at, fp.approved_amount_usd as pick_amount_usd,
    null::uuid as card_draft_id, fp.updated_at as pick_updated_at, t.current_review_id, t.approved_review_id
  from drink_topic_format_picks fp join drink_topics t on t.id = fp.topic_id
  union all
  select 'meme_card:' || m.id::text, null::uuid, c.name, null::text, null::text, null::int,
    'meme'::text, 'card'::text, null::date, null::timestamptz, null::numeric,
    m.id, m.updated_at, null::uuid, null::uuid
  from drink_meme_drafts m join drink_ig_cards c on c.id = m.card_id
  where m.card_id is not null
)
select u.unit_id, u.topic_id, u.title, u.question, u.topic_status, u.topic_version, u.format_intent, u.source,
  u.editorial_week, u.pick_approved_at, u.pick_amount_usd,
  rv.id as review_id, rv.status as review_status,
  case when rv.id is null or rv.status <> 'approved' then null
       else (rv.revoked_at is null and drinks_approval_valid(rv.id)) end as review_valid, rv.version as review_version,
  dq.kind as develop_kind, dq.status as develop_status, dq.id as develop_request_id, dq.error_code as develop_error_code,
  pl.id as plan_revision_id, pl.plan_status, (pl.id is not null and pl.blocked_at is not null) as plan_blocked, pl.version as plan_version, pl.format as plan_format,
  jb.id as job_id, jb.status as job_status, jb.error_code as job_error_code,
  ep.state as explainer_state,
  orv.id as output_review_id, orv.status as output_review_status, coalesce(ov.currently_usable, false) as output_usable,
  mm.id as meme_draft_id, mm.status as meme_status, mm.sync_grade as meme_sync_grade, mm.external_url as meme_external_url,
  pb.id as pub_request_id, pb.status as pub_status, pb.pause_code as pub_pause_code, pb.publish_at as pub_publish_at, pb.external_url as pub_external_url, pb.version as pub_version,
  coalesce(ep.state = 'unknown_billed', false) or coalesce(pb.status = 'unknown', false)
    or coalesce(dq.status = 'running' and dq.lease_expires_at < now(), false) as unknown_billed,
  (exists (select 1 from drink_develop_holds h where h.status = 'held'
      and ((h.request_id = dq.id and dq.status not in ('queued','running')) or (h.meme_draft_id = mm.id and mm.status not in ('text_running','rendering'))))
   or exists (select 1 from drink_spend_holds h join drink_spend_approvals a on a.id = h.approval_id
      where a.plan_revision_id = pl.id and h.status = 'held'
        and not exists (select 1 from drink_production_jobs j where j.id = h.job_id and j.status = 'running' and j.lease_expires_at > now()))) as orphan_hold,
  greatest(u.pick_updated_at, pl.updated_at, coalesce(dq.finished_at, dq.started_at, dq.created_at), coalesce(jb.finished_at, jb.started_at, jb.created_at),
    ep.updated_at, pb.updated_at, mm.updated_at) as updated_at
from units u
left join lateral (select r.* from drink_topic_reviews r where r.id = coalesce(u.current_review_id, u.approved_review_id)) rv on true
left join lateral (
  select q.* from drink_develop_requests q
  where u.source = 'topic' and u.format_intent in ('explainer','card') and q.topic_id = u.topic_id
    and (q.kind = 'evidence' or coalesce(q.format_intent, drinks_representative_intent(u.topic_id)) = u.format_intent)
  order by q.created_at desc limit 1) dq on true
left join lateral (
  select pr.* from drink_deliverables d join drink_plan_revisions pr on pr.id = d.current_revision_id
  where u.source = 'topic' and d.topic_id = u.topic_id and d.format = drinks_intent_format(u.format_intent) and d.locale = 'ko'
  limit 1) pl on true
left join lateral (select j.* from drink_production_jobs j where j.plan_revision_id = pl.id order by j.created_at desc limit 1) jb on true
left join lateral (select e.* from drink_explainer_episodes e where e.plan_revision_id = pl.id) ep on true
left join lateral (select o.* from drink_output_reviews o where o.plan_revision_id = pl.id order by o.created_at desc limit 1) orv on true
left join lateral (select v.currently_usable from drink_output_validity v where v.review_id = orv.id) ov on true
left join lateral (
  select m.* from drink_meme_drafts m
  where (u.source = 'card' and m.id = u.card_draft_id) or (u.source = 'topic' and u.format_intent = 'meme' and m.topic_id = u.topic_id)
  order by (m.status not in ('rejected','stopped','failed','posted_manual')) desc, m.updated_at desc limit 1) mm on true
left join lateral (
  select b.* from drink_publication_requests b
  where (mm.id is not null and b.meme_draft_id = mm.id) or (pl.id is not null and b.plan_revision_id = pl.id)
  order by (b.status in ('published','canceled')) asc, b.created_at desc limit 1) pb on true;

revoke all on table drink_work_items from anon, authenticated;
grant select on table drink_work_items to service_role;
