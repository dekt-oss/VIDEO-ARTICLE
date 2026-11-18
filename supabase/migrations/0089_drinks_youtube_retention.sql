-- 주류 — 유튜브 발견 원자료 30일 정리(2026-11-18).
--
-- YouTube API 개발자 정책 III.E.4(2026-11-15 원문 확인): 승인받지 않은 API 데이터(검색 결과·공개 댓글·지표)는
--   "no longer than 30 calendar days" — 30일이 지나면 지우거나 새로 받아야 한다.
-- 발견 자료·실행 문서·지표 관측은 지우지 못하게 막혀 있다(0051·0052 — 기록 보존). 그래서 행은 남기고 **유튜브에서 받은 내용만 비운다**:
--   · drink_discovery_items: 제목·설명·채널명·댓글 질문·최신 지표(주소·영상 ID·신호 낱말은 남긴다 — 중복 방지·후보 연결용)
--   · drink_collection_items: 유튜브 수집원 실행 문서의 제목·요약
--   · drink_discovery_observations: 유튜브 자료의 지표 관측 행 삭제
-- 막힌 표는 이 함수 안에서만 열린다(트랜잭션 한정 설정 drinks.youtube_purge — 다른 경로의 수정·삭제는 종전대로 막힌다).
-- 호출: 수집 워커가 실행마다 drinks_purge_expired_youtube({"days": 30}) (engine/drinks_collect.main).
-- 되돌리기: 두 트리거를 drink_append_only_guard 로 다시 걸고 함수 두 개를 지운다(비운 내용은 돌아오지 않는다 — 정책상 의도).

create or replace function drink_append_only_or_youtube_purge() returns trigger language plpgsql
  set search_path = public, pg_temp as $$
begin
  if coalesce(current_setting('drinks.youtube_purge', true), '') = 'on' then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  perform drinks_fail('immutable', tg_table_name || ' 는 추가만 할 수 있습니다');
  return null;
end $$;

drop trigger if exists drink_disc_obs_append_only on drink_discovery_observations;
create trigger drink_disc_obs_append_only before update or delete on drink_discovery_observations
  for each row execute function drink_append_only_or_youtube_purge();
drop trigger if exists drink_items_append_only on drink_collection_items;
create trigger drink_items_append_only before update or delete on drink_collection_items
  for each row execute function drink_append_only_or_youtube_purge();

create or replace function drinks_purge_expired_youtube(p jsonb) returns jsonb language plpgsql
  set search_path = public, pg_temp as $$
declare
  v_days int := coalesce(drinks_int(p, 'days', false), 30);
  v_cut timestamptz; n_items int; n_obs int; n_runs int;
begin
  if v_days < 1 or v_days > 30 then perform drinks_fail('invalid_input', '보관 일수는 1~30일입니다(유튜브 정책 상한 30일)'); end if;
  v_cut := now() - make_interval(days => v_days);
  perform set_config('drinks.youtube_purge', 'on', true);

  delete from drink_discovery_observations o using drink_discovery_items d
    where o.item_id = d.id and d.platform = 'youtube' and o.observed_at < v_cut;
  get diagnostics n_obs = row_count;

  update drink_discovery_items set title = null, summary = null, summary_hash = null, channel_name = null,
      questions = '{}', latest_metrics = null, metrics_observed_at = null,
      rights_note = '유튜브 API 정책: 30일 지나 원자료를 비움'
    -- 기준 = 마지막으로 새로 받은 시각(지표 관측 시각, 없으면 처음 발견한 날). 관련도순이라 같은 인기 영상이 다시 오면
    --   제목·질문·지표가 새로 채워지고 그때부터 다시 30일이다 — 처음 발견한 날로 자르면 다시 받자마자 또 비워진다(검사 지적).
    where platform = 'youtube' and coalesce(metrics_observed_at, discovered_at) < v_cut
      and (title is not null or summary is not null or channel_name is not null or cardinality(questions) > 0 or latest_metrics is not null);
  get diagnostics n_items = row_count;

  update drink_collection_items i set title = null, summary = null
    from drink_sources s
    where s.id = i.source_id and s.platform = 'youtube' and i.created_at < v_cut
      and (i.title is not null or i.summary is not null);
  get diagnostics n_runs = row_count;

  perform set_config('drinks.youtube_purge', 'off', true);
  return jsonb_build_object('days', v_days, 'discovery_items', n_items, 'observations', n_obs, 'run_items', n_runs);
end $$;

-- 함수는 호출자(service_role) 권한으로 돈다 — 0052 는 관측 표에 delete 를 주지 않았다(검사 지적: 0건이어도 permission denied 로 통째 롤백).
grant delete on table drink_discovery_observations to service_role;
revoke all on function drinks_purge_expired_youtube(jsonb) from public, anon, authenticated;
grant execute on function drinks_purge_expired_youtube(jsonb) to service_role;
revoke all on function drink_append_only_or_youtube_purge() from public, anon, authenticated;
