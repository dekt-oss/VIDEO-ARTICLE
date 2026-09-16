-- RLS + 이메일 allowlist (리뷰 3-2)
-- 공개 Vercel URL + 매직링크는 누구나 로그인 시도 가능 → 허용 이메일만 데이터 접근.
-- 엔진은 service_role 키로 접속하며 RLS 를 우회한다(서버 전용).

-- 허용 사용자 이메일 목록 (단일 사용자). 운영 시 본인 이메일을 insert.
create table if not exists app_allowed_emails (
  email text primary key
);
-- 예: insert into app_allowed_emails(email) values ('you@example.com');

-- 현재 로그인 사용자가 allowlist 에 있는지 판정.
create or replace function public.is_allowed_user()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from app_allowed_emails a
    where a.email = (auth.jwt() ->> 'email')
  );
$$;

-- 모든 데이터 테이블에 RLS 활성화.
alter table papers          enable row level security;
alter table scores          enable row level security;
alter table daily_batch     enable row level security;
alter table decisions       enable row level security;
alter table drafts          enable row level security;
alter table published       enable row level security;
alter table draft_requests  enable row level security;
alter table app_allowed_emails enable row level security;

-- 읽기 전용 테이블(엔진이 쓰고 사람은 봄): papers/scores/daily_batch/drafts/published.
do $$
declare t text;
begin
  foreach t in array array['papers','scores','daily_batch','drafts','published'] loop
    execute format($f$
      drop policy if exists %1$s_select on %1$s;
      create policy %1$s_select on %1$s
        for select to authenticated using (public.is_allowed_user());
    $f$, t);
  end loop;
end $$;

-- 사람이 쓰는 테이블: decisions(낙점/탈락), draft_requests(초안 요청).
do $$
declare t text;
begin
  foreach t in array array['decisions','draft_requests'] loop
    execute format($f$
      drop policy if exists %1$s_all on %1$s;
      create policy %1$s_all on %1$s
        for all to authenticated
        using (public.is_allowed_user())
        with check (public.is_allowed_user());
    $f$, t);
  end loop;
end $$;

-- allowlist 자체는 본인만 조회(수정은 service_role/대시보드 관리에서).
drop policy if exists allowed_emails_select on app_allowed_emails;
create policy allowed_emails_select on app_allowed_emails
  for select to authenticated using (email = (auth.jwt() ->> 'email'));
