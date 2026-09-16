-- 업로드 출처·분류 기록 (채널 통합 M2)
-- docs/specs/20260730-report-merge-into-paper-ko.md §3-2
--
-- 배경: 리포트 공장 산출물도 하루한편 KO 채널로 발행하게 되면서, 한 채널에 두 공장의 영상이
--   섞인다. 유튜브 성과 데이터만으로는 "이 영상이 어느 공장에서 나왔는지" 알 수 없어
--   되돌림 판정(§5-1)도 소재 비교(§5-2)도 불가능해진다. 그래서 업로드 시점에 출처를 남긴다.
--
-- ★ 게이트가 아니라 태그다. 이 컬럼들은 무엇도 막지 않는다 — 나중에 사람이 데이터로
--   판단할 수 있게 하는 것이 전부다(§3-4: 자동 비교·알림·차트는 만들지 않는다).

do $$
declare t text;
begin
  foreach t in array array['upload_requests', 'report_upload_requests']
  loop
    -- 어느 공장 산출물인가. 'paper' | 'report'
    execute format('alter table %I add column if not exists source_factory text', t);
    -- 리포트 소재 분류. 'entity'(개별 종목) | 'industry'(테마·산업·매크로). 논문은 NULL.
    -- 파생 규칙은 engine 쪽에 있다(reports.ticker/company 구조에서 파생 — 텍스트 분류기 없음).
    execute format('alter table %I add column if not exists content_type text', t);
    -- 시리즈 필러 코드(지시서 header.series_id). 미확정이면 빈 문자열이 들어온다.
    execute format('alter table %I add column if not exists series_id text', t);
    -- ★ 실제로 업로드된 채널(videos.insert 응답의 snippet.channelId).
    --   레지스트리가 기대한 채널이 아니라 **결과**를 적는다 — 오배송 사후 감사의 유일한 근거다.
    execute format('alter table %I add column if not exists channel_id text', t);
  end loop;
end $$;

-- 성과 조회는 "공장별 + 기간" 으로 훑는다.
create index if not exists upload_requests_factory_idx
  on upload_requests (source_factory, requested_at desc);
create index if not exists report_upload_requests_factory_idx
  on report_upload_requests (source_factory, requested_at desc);

-- 확인용(적용 후):
--   select source_factory, content_type, series_id, channel_id, youtube_url
--   from report_upload_requests order by requested_at desc limit 5;
