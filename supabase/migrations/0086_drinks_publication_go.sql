-- 주류 — [게시] 한 번 (2026-11-13). docs/deviation-drinks-one-click-publish.md
--
-- 무엇이 — 왜: 발행은 [발행안 만들기] → [승인 요청](시각 필수) → [승인](지문) → [예약] 네 번이었다. 운영자가 [발행안 만들기]를
--   '게시'로 알고 눌렀는데 "게시 시각을 정하세요"가 떴다(청주·탁주). 운영자 지시: 흐름이 거슬리지 않게 쭉.
--   → drinks_publication_go: 화면에 보인 버전(expected_version)의 발행안을 시각 채움 → 승인 요청 → 승인 → 예약까지 한 트랜잭션으로.
--   시각을 안 정했으면 '지금'이다. 각 단계는 기존 함수를 그대로 부른다(캡션·AI 표시·파일 유효성·발행 차단 검사 그대로).
-- 지문 확인: 승인 지문은 이 트랜잭션 안에서 방금 만든 것이고, 운영자가 본 내용은 expected_version 이 보장한다(다른 곳에서 바뀌면 거부).
-- 되돌리기: drop function drinks_publication_go(jsonb);

create or replace function drinks_publication_go(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare r drink_publication_requests; v_at timestamptz;
begin
  r := drinks_lock_publication(p);
  if r.status not in ('draft', 'awaiting_approval', 'approved') then
    perform drinks_fail('invalid_state', '작성·승인 대기·승인 상태의 발행안만 게시합니다(' || r.status || ')');
  end if;
  if r.status = 'draft' then
    v_at := coalesce(drinks_text(p, 'publish_at')::timestamptz, r.publish_at, now());
    if v_at < now() then v_at := now(); end if;
    perform drinks_update_publication(jsonb_build_object('request_id', r.id, 'expected_version', r.version, 'publish_at', v_at));
    select * into r from drink_publication_requests where id = r.id;
    perform drinks_publication_action(jsonb_build_object('request_id', r.id, 'expected_version', r.version, 'action', 'submit'));
    select * into r from drink_publication_requests where id = r.id;
  end if;
  if r.status = 'awaiting_approval' then
    perform drinks_publication_action(jsonb_build_object('request_id', r.id, 'expected_version', r.version, 'action', 'approve',
      'expected_digest', r.approval_digest, 'actor', coalesce(drinks_text(p, 'actor'), 'operator')));
    select * into r from drink_publication_requests where id = r.id;
  end if;
  perform drinks_publication_action(jsonb_build_object('request_id', r.id, 'expected_version', r.version, 'action', 'schedule'));
  select * into r from drink_publication_requests where id = r.id;
  return jsonb_build_object('request_id', r.id, 'status', r.status, 'version', r.version, 'publish_at', r.publish_at,
    'due_now', r.publish_at <= now() + interval '1 minute');
end $$;

revoke all on function drinks_publication_go(jsonb) from public, anon, authenticated;
grant execute on function drinks_publication_go(jsonb) to service_role;
