-- 0090 주류 발행 계정에 유튜브(쇼츠)를 더한다 (2026-11-24 운영자 지시: 'a Paper a Day' 채널을 술째리고 홍보 채널로).
-- docs/deviation-drinks-youtube-channel.md
--
-- 발행 흐름(승인·예약·임대·대조)은 그대로다. 계정 하나가 더 생길 뿐이다:
--   platform 'youtube' + connection 'google_oauth'(구글 OAuth 리프레시 토큰, credential_ref 는 그 비밀 이름).
--   워커는 connection 으로 공급자를 고른다(engine/providers/instagram.provider_for → DrinksYouTube).
-- 플랫폼과 연결 방식이 엇갈리지 않게 표에서 묶는다(유튜브 = 구글 OAuth, 그 밖 = 인스타).

alter table drink_social_accounts drop constraint if exists drink_social_accounts_platform_check;
alter table drink_social_accounts add constraint drink_social_accounts_platform_check
  check (platform in ('instagram', 'youtube'));
alter table drink_social_accounts drop constraint if exists drink_social_accounts_connection_check;
alter table drink_social_accounts add constraint drink_social_accounts_connection_check
  check (connection in ('instagram_login', 'facebook_login', 'google_oauth', 'fake'));
alter table drink_social_accounts drop constraint if exists drink_social_accounts_platform_connection_check;
alter table drink_social_accounts add constraint drink_social_accounts_platform_connection_check
  check ((platform = 'youtube') = (connection = 'google_oauth'));

-- 0055 판 그대로 + google_oauth 허용, 플랫폼은 연결 방식에서 정한다(화면이 platform 을 따로 보내지 않아도 된다).
create or replace function drinks_register_account(p jsonb) returns jsonb language plpgsql as $$
declare a drink_social_accounts; caps jsonb := coalesce(p -> 'capabilities', '{}');
begin
  if jsonb_typeof(caps) <> 'object' then perform drinks_fail('invalid_input', '기능(capabilities) 형식이 잘못됐습니다'); end if;
  if coalesce(drinks_text(p, 'connection'), '') not in ('instagram_login','facebook_login','google_oauth','fake') then
    perform drinks_fail('invalid_input', '연결 방식을 고르세요(Instagram 로그인 / Facebook 로그인 / YouTube)');
  end if;
  if (drinks_text(p, 'connection') = 'fake') <> coalesce(drinks_text(p, 'external_account_id') like 'fake\_%', false) then
    perform drinks_fail('invalid_input', '시험용 가짜 계정은 fake_ 로 시작하는 ID 만, 실제 계정은 그 접두어를 쓸 수 없습니다');
  end if;
  if drinks_text(p, 'connection') <> 'fake' and coalesce(drinks_text(p, 'credential_ref'), '') !~ '^[A-Z][A-Z0-9_]{2,63}$' then
    perform drinks_fail('invalid_input', '토큰을 둔 비밀 이름(대문자·숫자·밑줄)을 적으세요 — 토큰 원문은 넣지 않습니다');
  end if;
  if drinks_text(p, 'connection') = 'google_oauth' and caps -> 'post_types' is not null and caps -> 'post_types' <> '["reel"]'::jsonb then
    perform drinks_fail('invalid_input', '유튜브 계정은 릴스(쇼츠)만 올립니다 — 카드뉴스는 고를 수 없습니다');
  end if;
  begin
    insert into drink_social_accounts (platform, external_account_id, display_name, account_type, connection, capabilities,
      credential_ref)
    values (case when drinks_text(p, 'connection') = 'google_oauth' then 'youtube' else 'instagram' end,
      drinks_text(p, 'external_account_id'), drinks_text(p, 'display_name'),
      coalesce(drinks_text(p, 'account_type'), 'business'), drinks_text(p, 'connection'),
      case when drinks_text(p, 'connection') = 'google_oauth' then '{"post_types":["reel"]}'::jsonb else caps end,
      drinks_text(p, 'credential_ref'))
    returning * into a;
  exception when unique_violation then
    perform drinks_fail('duplicate_account', '같은 외부 ID 의 계정이 이미 있습니다 — 재인증은 그 계정에서 하세요');
  end;
  return jsonb_build_object('account_id', a.id, 'status', a.status, 'version', a.version);
end $$;

revoke all on function drinks_register_account(jsonb) from public, anon, authenticated;
grant execute on function drinks_register_account(jsonb) to service_role;
