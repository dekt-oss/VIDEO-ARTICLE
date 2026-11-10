-- 편성(drinks_select)의 필수 주장 검사를 공용 규칙(drinks_format_required, 0065)에 맞춘다 (2026-11-10).
--
-- 계기: 버번 소재는 카드뉴스로만 근거가 승인돼 required_claims.video 가 [] 였다. 스튜디오에서 릴스를 더해(0076 pick_topic)
--   초안까지 만들었는데 [이 초안 승인] 이 "영상 형식의 필수 주장이 승인 기획에 없습니다"로 막혔다.
--   워커 코드 검사·0065·0072 는 이미 "비어 있으면 다른 형식의 목록, 그것도 없으면 핵심 주장 앞 3개" 규칙을 쓴다. 편성만 옛 규칙이었다.
-- 바뀌는 것: drinks_select 와 drinks_plan_coverage 에서 필수 주장을 읽는 한 줄씩. 나머지 본문은 0050 그대로 옮겼다.
-- 되돌리기: 0050 의 drinks_select·drinks_plan_coverage 본문을 다시 실행한다(search_path 설정은 0056 이 붙였던 값을 이 파일이 명시한다).

create or replace function drinks_select(p jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare
  t drink_topics; r drink_topic_reviews; rd jsonb; fmts text[]; f text; v_week date; v_exc text;
  v_before text; v_score numeric; fx jsonb := coalesce(p -> 'format_exceptions', '{}'); fx_out jsonb := '{}';
begin
  t := drinks_lock_topic(drinks_uuid(p, 'topic_id'), drinks_int(p, 'expected_version'));
  v_before := t.status;
  if t.status not in ('ready','selected') then
    perform drinks_fail('invalid_state', '근거·기획이 승인된(편성 가능) 소재만 편성할 수 있습니다');
  end if;
  select * into r from drink_topic_reviews where id = drinks_uuid(p, 'review_id') for update;
  if not found or r.topic_id <> t.id then perform drinks_fail('ownership', '이 소재의 근거·기획 버전이 아닙니다'); end if;
  if r.status <> 'approved' or r.revoked_at is not null then
    perform drinks_fail('review_not_approved', '승인된(철회되지 않은) 근거·기획 버전으로만 편성할 수 있습니다');
  end if;
  if not (r.id = t.approved_review_id or (t.status = 'selected' and r.id = t.selected_review_id)) then
    perform drinks_fail('review_not_current', '가장 최근 승인 버전(또는 이미 편성에 쓴 버전)으로만 편성할 수 있습니다');
  end if;
  if drinks_text(p, 'review_input_hash') is distinct from r.approved_hash or r.approved_hash <> r.input_hash then
    perform drinks_fail('review_changed', '화면에서 본 승인 버전과 서버의 버전이 다릅니다 — 새로 불러오세요');
  end if;
  rd := drinks_review_blockers(r.id);
  if jsonb_array_length(rd -> 'blockers') > 0 then
    perform drinks_fail('review_blocked', '필수 조건이 다시 깨졌습니다(유효 기한·사용 조건 등)', rd -> 'blockers');
  end if;
  if jsonb_typeof(p -> 'formats') is distinct from 'array' then perform drinks_fail('invalid_input', '형식을 고르세요'); end if;
  if jsonb_typeof(fx) <> 'object' then perform drinks_fail('invalid_input', '형식 예외 사유 형식이 잘못됐습니다'); end if;
  fmts := drinks_text_array(p -> 'formats');
  if cardinality(fmts) = 0 or not fmts <@ array['video','carousel'] then
    perform drinks_fail('invalid_input', '형식은 영상·카드뉴스 중 하나 이상 고르세요');
  end if;
  foreach f in array fmts loop
    if jsonb_array_length(drinks_format_required(r.brief, f)) = 0 then   -- 0080: 공용 규칙(0065)
      perform drinks_fail('required_claims_missing', case f when 'video' then '영상' else '카드뉴스' end
        || ' 형식의 필수 주장이 승인 기획에 없습니다 — 기획에서 형식과 필수 주장을 정해 다시 승인하세요');
    end if;
    if coalesce((r.scores ->> ('fit_' || f))::int, 0) < 2 then
      if drinks_text(fx, f) is null then
        perform drinks_fail('format_fit_low', case f when 'video' then '영상' else '카드뉴스' end
          || ' 적합성이 2점 미만입니다 — 이 형식으로 편성하려면 형식 예외 사유를 입력하세요');
      end if;
      fx_out := fx_out || jsonb_build_object(f, drinks_text(fx, f));
    end if;
  end loop;
  if t.selected_formats is not null then
    foreach f in array t.selected_formats loop
      if not f = any(fmts) and exists (select 1 from drink_plan_revisions
          where topic_id = t.id and format = f and blocked_at is null) then
        perform drinks_fail('format_in_use', '제작안이 있는 형식은 편성에서 뺄 수 없습니다');
      end if;
    end loop;
  end if;
  v_week := drinks_date(p, 'editorial_week');
  if v_week is null then perform drinks_fail('invalid_input', '편성 주차를 고르세요'); end if;
  v_week := v_week - (extract(isodow from v_week)::int - 1);   -- 그 주 월요일로 맞춘다
  v_score := drinks_weighted_score(r.scores);
  v_exc := drinks_text(p, 'score_exception_reason');
  if v_score < 65 and v_exc is null then
    perform drinks_fail('below_threshold', '점수 ' || v_score || '점(기준 65점 미만) — 점수 예외 편성 사유를 입력하세요');
  end if;
  update drink_topics set status = 'selected', selected_review_id = r.id, selected_formats = fmts,
    editorial_week = v_week, score_exception_reason = case when v_score < 65 then v_exc end,
    format_exception_reasons = case when fx_out = '{}'::jsonb then null else fx_out end
    where id = t.id returning * into t;
  perform drinks_log(t.id, 'topic', t.id, 'selected', v_before, t.status, r.id::text, v_exc,
    jsonb_build_object('formats', fmts, 'editorial_week', v_week, 'score', v_score, 'review_hash', r.approved_hash,
      'score_exception_reason', t.score_exception_reason, 'format_exception_reasons', t.format_exception_reasons,
      'warnings', rd -> 'warnings'));
  return jsonb_build_object('topic_id', t.id, 'status', t.status, 'version', t.version,
    'selected_formats', to_jsonb(fmts), 'editorial_week', v_week, 'format_exception_reasons', t.format_exception_reasons);
end $$;

-- 대본 승인의 전달 검사(drinks_plan_coverage)도 같은 공용 규칙으로. 편성만 고치면 다음 관문에서 "필수 주장 목록 없음"으로 막힌다(시험 실측).
-- 바뀌는 것: req 를 읽는 한 줄. 나머지는 0050 그대로.
create or replace function drinks_plan_coverage(p_format text, p_plan jsonb, p_review drink_topic_reviews)
returns jsonb language plpgsql stable set search_path = public, pg_temp as $$
declare
  k text := case p_format when 'video' then 'scenes' else 'pages' end;
  el jsonb; i int := 0; no_claim int[] := '{}'; used text[] := '{}'; ref_only text[] := '{}';
  req text[] := drinks_text_array(drinks_format_required(p_review.brief, p_format));   -- 0080: 공용 규칙(0065)
  missing text[];
begin
  for el in select * from jsonb_array_elements(coalesce(p_plan -> k, '[]')) loop
    i := i + 1;
    if drinks_plan_item_is_fact(p_format, el) then
      if cardinality(drinks_text_array(el -> 'claim_ids')) = 0 then no_claim := array_append(no_claim, i); end if;
      used := used || drinks_text_array(el -> 'claim_ids');
    else
      -- 표지·출처·전환에 붙은 주장은 참고 연결일 뿐 "전달"이 아니다(전달 계산에서 뺀다).
      ref_only := ref_only || drinks_text_array(el -> 'claim_ids');
    end if;
  end loop;
  missing := array(select x from unnest(req) x where not x = any(used) order by 1);
  return jsonb_build_object('required', to_jsonb(req), 'covered', to_jsonb(array(select distinct unnest(used) order by 1)),
    'reference_only', to_jsonb(array(select distinct x from unnest(ref_only) x where not x = any(used) order by 1)),
    'missing_required', to_jsonb(missing), 'facts_without_claims', to_jsonb(no_claim),
    'required_defined', cardinality(req) > 0,
    'ok', cardinality(req) > 0 and cardinality(missing) = 0 and cardinality(no_claim) = 0);
end $$;
