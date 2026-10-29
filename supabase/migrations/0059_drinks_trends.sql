-- 주류 공장 - 술 커뮤니티 언급·주류 이슈 수집 (2026-10-29). docs/deviation-drinks-trends.md
--
-- 운영자 요청: "주류 커뮤니티도 수집에 추가. 거기서 언급 많은 주류가 뭔지 수집해서 소재로 같이 보여줘.
--   부정인지 긍정인지도 점수화해서 보여주면 더 좋고. 구체적 제품 말고도 주류 관련 이슈가 있으면 수집."
-- 이 파일이 하는 일(전부 새 객체 - 기존 표·함수는 건드리지 않는다):
--   1) drink_trend_posts     : 커뮤니티 글(kind=community)·주류 이슈 기사(kind=issue). 주소가 같으면 한 건.
--   2) drink_trend_mentions  : 글 하나에서 언급된 제품(글×제품 한 건). sentiment(-1~1)·jev_p(좋게 평가할 확률)·jev_p_bad(나쁘게 평가할 확률)는 판정이 없으면 null - 추측해 채우지 않는다.
--   3) 보기 drink_trend_products : 최근 7일 언급 제품 집계(긍정 > 0.2·부정 < -0.2 개수, 평균, 예시 글 3개까지).
--      보기 drink_trend_issues   : 최근 14일 이슈 기사.
--   4) 워커 전용 함수 3개: drinks_trends_record_post / drinks_trends_record_mention / drinks_trends_pending_mentions.
-- 권한: 0049·0053·0055 방향 그대로 - 공개 역할(anon·authenticated)은 표·보기·함수 모두 접근 불가, service_role 만.
--   (대시보드는 서버에서 service key 로 읽는다.) 긍정/부정 문턱 0.2 는 engine/config.py DRINKS_TRENDS_POSITIVE_ABOVE·
--   NEGATIVE_BELOW 와 같아야 한다(tests/test_drinks_trends.py 가 대조).
-- 영향: 추가만 한다. 기존 데이터 변화 없음.
-- 되돌리기:
--   drop view if exists drink_trend_products, drink_trend_issues;
--   drop function if exists drinks_trends_record_post(jsonb), drinks_trends_record_mention(jsonb), drinks_trends_pending_mentions(jsonb);
--   drop table if exists drink_trend_mentions, drink_trend_posts;

create table if not exists drink_trend_posts (
  id             uuid primary key default gen_random_uuid(),
  kind           text not null check (kind in ('community','issue')),
  platform       text not null check (platform in ('naver_cafe','naver_news')),
  canonical_url  text not null unique check (canonical_url ~ '^https?://'),
  channel_name   text check (channel_name is null or length(channel_name) <= 200),   -- 카페 이름·언론사 이름
  channel_url    text check (channel_url is null or length(channel_url) <= 500),
  title          text not null check (length(title) between 1 and 500),
  summary        text check (summary is null or length(summary) <= 2000),           -- 검색 결과 요약만 - 본문 전문 아님
  posted_at      timestamptz,
  query          text check (query is null or length(query) <= 100),
  collected_at   timestamptz not null default now()
);
create index if not exists drink_trend_posts_kind_time_idx on drink_trend_posts (kind, (coalesce(posted_at, collected_at)) desc);

create table if not exists drink_trend_mentions (
  id         uuid primary key default gen_random_uuid(),
  post_id    uuid not null references drink_trend_posts(id) on delete cascade,
  product    text not null check (length(product) between 1 and 100),
  category   text not null check (category in ('sake','traditional','whisky')),
  sentiment  numeric check (sentiment is null or sentiment between -1 and 1),   -- p_good - p_bad. 판정이 없으면 null('판정 없음')
  jev_p      numeric check (jev_p is null or jev_p between 0 and 1),        -- p_good: 글쓴이가 좋게 평가할 확률
  jev_p_bad  numeric check (jev_p_bad is null or jev_p_bad between 0 and 1), -- 글쓴이가 나쁘게 평가할 확률(의견 없는 글은 둘 다 낮다 -> 중립)
  judged_at  timestamptz,
  constraint drink_trend_mentions_judged_ck check ((sentiment is null) = (judged_at is null)),
  constraint drink_trend_mentions_post_product_uq unique (post_id, product)
);
create index if not exists drink_trend_mentions_product_idx on drink_trend_mentions (product);

-- ─────────────────────────────────────────────────────────────
-- 워커 전용 쓰기 함수 (오류는 0050 의 drinks_fail 형식)
-- ─────────────────────────────────────────────────────────────

-- 글 한 건 기록. 같은 주소면 제목·요약만 새로 고치고 처음 모은 시각은 둔다. {post_id, created}
create or replace function drinks_trends_record_post(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_kind text := drinks_text(p, 'kind'); v_platform text := drinks_text(p, 'platform');
  v_url text := drinks_text(p, 'canonical_url'); v_title text := left(drinks_text(p, 'title'), 500);
  v_posted timestamptz; v_id uuid; v_created boolean;
begin
  if v_kind not in ('community','issue') then perform drinks_fail('invalid_input', 'kind 는 community·issue 중 하나입니다'); end if;
  if v_platform not in ('naver_cafe','naver_news') then perform drinks_fail('invalid_input', 'platform 이 잘못됐습니다'); end if;
  if v_url is null or v_url !~ '^https?://' or v_title is null then perform drinks_fail('invalid_input', 'canonical_url 과 title 이 필요합니다'); end if;
  begin
    v_posted := nullif(btrim(p ->> 'posted_at'), '')::timestamptz;
  exception when others then
    perform drinks_fail('invalid_input', 'posted_at 형식이 잘못됐습니다');
  end;
  insert into drink_trend_posts (kind, platform, canonical_url, channel_name, channel_url, title, summary, posted_at, query)
  values (v_kind, v_platform, v_url, left(drinks_text(p, 'channel_name'), 200), left(drinks_text(p, 'channel_url'), 500), v_title,
    left(drinks_text(p, 'summary'), 2000), v_posted, left(drinks_text(p, 'query'), 100))
  on conflict (canonical_url) do nothing
  returning id into v_id;
  v_created := v_id is not null;
  if not v_created then
    update drink_trend_posts set title = v_title, summary = coalesce(left(drinks_text(p, 'summary'), 2000), summary),
      posted_at = coalesce(v_posted, posted_at)
      where canonical_url = v_url returning id into v_id;
  end if;
  return jsonb_build_object('post_id', v_id, 'created', v_created);
end $$;

-- 언급 한 건 기록(글×제품). sentiment 를 주면 아직 판정 없는 언급에만 채운다(이미 판정된 값은 덮지 않는다). {mention_id, created, judged}
create or replace function drinks_trends_record_mention(p jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  v_post uuid := drinks_uuid(p, 'post_id'); v_product text := left(drinks_text(p, 'product'), 100); v_cat text := drinks_text(p, 'category');
  v_sent numeric; v_p numeric; v_pb numeric; v_id uuid; v_created boolean; m drink_trend_mentions;
begin
  if v_product is null then perform drinks_fail('invalid_input', 'product 가 필요합니다'); end if;
  if v_cat not in ('sake','traditional','whisky') then perform drinks_fail('invalid_input', '주종은 사케·전통주·위스키 중에서 고르세요'); end if;
  if not exists (select 1 from drink_trend_posts where id = v_post) then perform drinks_fail('not_found', '글을 찾지 못했습니다'); end if;
  begin
    v_sent := nullif(btrim(p ->> 'sentiment'), '')::numeric;
    v_p := nullif(btrim(p ->> 'jev_p'), '')::numeric;
    v_pb := nullif(btrim(p ->> 'jev_p_bad'), '')::numeric;
  exception when others then
    perform drinks_fail('invalid_input', 'sentiment·jev_p·jev_p_bad 는 숫자여야 합니다');
  end;
  if v_sent is not null and (v_sent < -1 or v_sent > 1) then perform drinks_fail('invalid_input', 'sentiment 는 -1~1 사이입니다'); end if;
  if (v_p is not null and (v_p < 0 or v_p > 1)) or (v_pb is not null and (v_pb < 0 or v_pb > 1)) then
    perform drinks_fail('invalid_input', 'jev_p·jev_p_bad 는 0~1 사이입니다');
  end if;
  insert into drink_trend_mentions (post_id, product, category) values (v_post, v_product, v_cat)
    on conflict (post_id, product) do nothing returning id into v_id;
  v_created := v_id is not null;
  if v_sent is not null then
    update drink_trend_mentions set sentiment = v_sent, jev_p = v_p, jev_p_bad = v_pb, judged_at = now()
      where post_id = v_post and product = v_product and sentiment is null;
  end if;
  select * into m from drink_trend_mentions where post_id = v_post and product = v_product;
  return jsonb_build_object('mention_id', m.id, 'created', v_created, 'judged', m.sentiment is not null);
end $$;

-- 아직 판정 없는 언급(최근 14일에 모은 글) - 워커가 Jev 에 묻는 대상. limit 기본 300, 상한 1000.
create or replace function drinks_trends_pending_mentions(p jsonb) returns jsonb
language sql stable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(jsonb_build_object('mention_id', x.id, 'post_id', x.post_id, 'product', x.product, 'category', x.category,
    'title', x.title, 'summary', x.summary)
    order by x.collected_at desc, x.id), '[]')
  from (select m.id, m.post_id, m.product, m.category, t.title, t.summary, t.collected_at
    from drink_trend_mentions m join drink_trend_posts t on t.id = m.post_id
    where m.sentiment is null and t.kind = 'community' and t.collected_at >= now() - interval '14 days'
    order by t.collected_at desc, m.id
    limit least(greatest(coalesce(drinks_int(p, 'limit', false), 300), 1), 1000)) x
$$;

-- ─────────────────────────────────────────────────────────────
-- 읽기 보기 - 최근 7일 제품 집계 / 최근 14일 이슈. 날짜 기준 = 글 게시일(없으면 모은 날)
-- ─────────────────────────────────────────────────────────────

create or replace view drink_trend_products with (security_invoker = true) as
select m.product, m.category,
  count(distinct t.id)                                         as posts,
  count(*)                                                     as mentions,
  count(m.sentiment)                                           as judged,
  round(avg(m.sentiment), 2)                                   as avg_sentiment,
  count(*) filter (where m.sentiment > 0.2)                    as positive,
  count(*) filter (where m.sentiment < -0.2)                   as negative,
  count(*) filter (where m.sentiment between -0.2 and 0.2)     as neutral,
  max(coalesce(t.posted_at, t.collected_at))                   as last_seen,
  (array_agg(t.canonical_url order by coalesce(t.posted_at, t.collected_at) desc, t.id))[1:3] as sample_urls,
  (array_agg(t.title order by coalesce(t.posted_at, t.collected_at) desc, t.id))[1:3]         as sample_titles
from drink_trend_mentions m join drink_trend_posts t on t.id = m.post_id
where t.kind = 'community' and coalesce(t.posted_at, t.collected_at) >= now() - interval '7 days'
group by m.product, m.category;

create or replace view drink_trend_issues with (security_invoker = true) as
select t.id, t.title, t.summary, t.canonical_url, t.channel_name, t.posted_at, t.query, t.collected_at
from drink_trend_posts t
where t.kind = 'issue' and coalesce(t.posted_at, t.collected_at) >= now() - interval '14 days';

-- ─────────────────────────────────────────────────────────────
-- 권한 - 0055 방향 그대로. 공개 역할 접근 없음, 쓰기·읽기는 service_role(워커·Next 서버)만
-- ─────────────────────────────────────────────────────────────

alter table drink_trend_posts enable row level security;
alter table drink_trend_mentions enable row level security;

revoke all on table drink_trend_posts, drink_trend_mentions, drink_trend_products, drink_trend_issues from anon, authenticated;
grant select, insert, update on table drink_trend_posts, drink_trend_mentions to service_role;
grant select on table drink_trend_products, drink_trend_issues to service_role;

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname like 'drinks\_trends\_%'
  loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    execute format('grant execute on function %s to service_role', f.sig);
  end loop;
end $$;
