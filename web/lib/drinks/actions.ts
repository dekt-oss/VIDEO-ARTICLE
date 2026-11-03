// 주류 공장 쓰기 동작 — POST /api/drinks 의 본체 (A단계 2026-10-22, B단계 수집원·실행 추가 2026-10-22).
//
// ★ 라우트는 이 파일의 runDrinksAction 에 Supabase rpc 실행기만 넘긴다. 실행기를 바꿔 끼울 수 있어서
//   supabase/tests/drinks_phase_a.test.mjs 가 **실제 Postgres(PGlite) 위에서** 같은 코드 경로를 돈다.
//   그래서 이 파일은 값 import 가 없다(node --test 가 경로 별칭을 못 푼다).
//
// ★ 상태 전이·소유 관계·동시 수정 검사는 전부 DB 함수(0050_drinks_factory_phase_a.sql)가 한다.
//   여기서는 (1) 허용된 동작인지 (2) URL 정규화 (3) DB 오류를 HTTP 상태·한국어 문장으로 바꾸기만 한다.
//   UI 버튼을 숨기는 것은 편의일 뿐이고, 막는 것은 DB 다.

/** A단계에서 실행할 수 있는 동작 → DB 함수. 이 목록 밖은 전부 거부한다. */
export const DRINKS_ACTIONS = {
  create_topic: "drinks_create_topic",
  add_source: "drinks_add_source",
  set_origin_group: "drinks_set_origin_group",
  attest_source: "drinks_attest_source",
  triage: "drinks_triage",
  topic_action: "drinks_topic_action",
  save_review: "drinks_save_review",
  review_action: "drinks_review_action",
  select: "drinks_select",
  save_plan: "drinks_save_plan",
  plan_action: "drinks_plan_action",
  // B단계(0051): 수집원 등록부·실행 요청·수집 문서 연결. 워커 전용 함수(start/collect/finish)는 여기 없다.
  register_source: "drinks_register_source",
  source_action: "drinks_source_action",
  request_run: "drinks_request_run",
  link_snapshot: "drinks_link_snapshot",
  create_topic_from_snapshot: "drinks_create_topic_from_snapshot",
  // B 보완(0052): 소재 발견. 자료 기록·후보 묶기(워커 전용)는 여기 없다.
  register_discovery_source: "drinks_register_discovery_source",
  add_discovery: "drinks_add_discovery",
  promote_candidate: "drinks_promote_candidate",
  candidate_action: "drinks_candidate_action",
  set_discovery_origin: "drinks_set_discovery_origin",
  // C단계(0053): 제작 요청·취소·최종 파일 검수. 렌더·파일 등록·끝내기(워커 전용)는 여기 없다.
  request_render: "drinks_request_render",
  cancel_render: "drinks_cancel_render",
  output_review_action: "drinks_output_review_action",
  // 유료 생성 결재(0054): 결재 열기·닫기. 가잡기·확정·파일 등록(워커 전용)은 여기 없다 — 화면은 돈을 쓰지 못한다.
  open_spend_approval: "drinks_open_spend_approval",
  close_spend_approval: "drinks_close_spend_approval",
  // D단계 순환(0055): 계정 등록·발행 스위치, 발행안 작성·고치기·승인·예약·멈춤·취소, 전략 제안 반영·기각.
  // 점유·게시·대조·성과 기록·전략 계산(워커 전용)은 여기 없다 — 화면은 인스타에 직접 올리지 못한다.
  register_account: "drinks_register_account",
  account_action: "drinks_account_action",
  create_publication: "drinks_create_publication",
  update_publication: "drinks_update_publication",
  publication_action: "drinks_publication_action",
  // 음원 고르기·바꾸기(0065). 승인 뒤 바꾸면 승인이 풀린다. 게시 직전 재조회·컨테이너 음원 설정(워커 전용)은 여기 없다.
  set_publication_audio: "drinks_set_publication_audio",
  // 밈 발행안(0068): 게시 대기(publish_waiting)·박자 무관 제작안만. 박자 맞춤은 DB 가 거부한다. 같은 승인·예약 경로(publication_action)를 탄다.
  create_meme_publication: "drinks_create_meme_publication",
  strategy_action: "drinks_strategy_action",
  // 소재 개발(0060): 근거 초안·대본 초안 요청/취소, 개발 결재 열기·닫기. 초안을 쓰는 LLM 호출·결재 가잡기·확정(워커 전용)은
  // 여기 없다 — 화면은 요청을 큐에 넣을 뿐이다. 아래 PHASE_A_EXCLUDED 의 research_llm·generate_plan·generate_script 와는 다른 이름이다.
  request_develop: "drinks_request_develop",
  cancel_develop: "drinks_cancel_develop",
  open_develop_budget: "drinks_open_develop_budget",
  close_develop_budget: "drinks_close_develop_budget",
  // 밈 보드(0063): 카드 결정·칸 직접 입력·관찰 계정 체크·운영자 링크. 수집·카드 만들기·수명 계산(워커 전용)은 여기 없다.
  // [쓰자]는 결정만 기록한다 - 분석·구매를 시작하는 함수가 이 목록에 없다.
  ig_card_decide: "drinks_ig_card_decide",
  ig_set_card_field: "drinks_ig_set_card_field",
  ig_watch_action: "drinks_ig_watch_action",
  ig_add_link: "drinks_ig_add_link",
  // Apify 정밀화(0070, 총괄 §3 결정 1): [쓰자] 클릭 1회 = Apify 실행 1회 승인(상한 $0.02, 월 $3 — DB 가 센다). 결정 기록 + 요청 큐를 한 트랜잭션으로.
  // 실행(점유·끝내기)은 워커 전용이라 여기 없다. 손으로 만드는 정밀 틀 카드(정상 관측일 전 제작 경로)도 여기.
  ig_card_use_refine: "drinks_ig_card_use_refine",
  ig_manual_card: "drinks_ig_create_manual_card",
  // 내용 승인 한 번(0064): [이걸로](후보→소재·형식 의도·이어 만들기 요청), [승인](근거·편성·제작안을 한 트랜잭션으로).
  // 이어 만들기의 저장·끝내기(워커 전용)는 여기 없다. 워커는 승인 함수를 부르지 않는다.
  pick_topic: "drinks_pick_topic",
  approve_content: "drinks_approve_content",
  // 밈 제작(0066): 제작안 저장·글 초안 요청·승인·되돌리기·버리기·앱 게시 링크 등록. 렌더·끝내기·가잡기(워커 전용)는 여기 없다.
  // 게시 요청은 위의 create_meme_publication(0068)으로만 만든다 — 발행 화면에서, 다른 형식과 같은 승인·예약을 거친다.
  meme_save_draft: "drinks_meme_save_draft",
  meme_request_text: "drinks_meme_request_text",
  meme_draft_action: "drinks_meme_draft_action",
  // 설명형 제작(0067): 지시서·구매·조립 요청, 후보 사람 판정·선택, 결과 불명 닫기, 사람 검수. 시도 기록·가잡기·자동 판정·파일 등록(워커 전용)은 여기 없다 —
  // 화면은 큐에 넣고 사람 판정만 적는다. 공급자를 부르는 길이 없다.
  explainer_request_plan: "drinks_explainer_request_plan",
  explainer_request_buy: "drinks_explainer_request_buy",
  explainer_request_assemble: "drinks_explainer_request_assemble",
  explainer_verdict: "drinks_explainer_verdict",
  explainer_select: "drinks_explainer_select",
  explainer_close_unknown: "drinks_explainer_close_unknown",
  explainer_review: "drinks_explainer_review",
} as const;

export type DrinksAction = keyof typeof DRINKS_ACTIONS;

/**
 * 아직 연결하지 않은 기능 이름(C·D단계, 그리고 B단계에서 일부러 뺀 LLM·OCR·번역·크롤링).
 * 누가 이 이름으로 요청해도 "아직 연결되지 않음"으로 거부한다(명세 §13).
 * B단계 수집은 request_run(승인된 수집원의 실행 요청)으로만 들어온다 — 임의 URL 을 여는 동작은 없다.
 * 목록에 없더라도 DRINKS_ACTIONS 밖이면 거부되지만, 이 이름들은 **의도적으로 닫았다**는 것을
 * 응답 코드(not_in_phase_a)로 구별해 보여준다.
 */
export const PHASE_A_EXCLUDED = [
  "fetch_url", "crawl", "ocr", "translate",
  "research_llm", "auto_score", "generate_plan", "generate_script",
  "render", "generate_media", "tts",
  "approve_output", "mark_rendered",
  "connect_account", "publish", "schedule_publish", "upload",
] as const;

// ── URL 정규화(명세 §5.4-1): 추적 파라미터만 지우고 의미 있는 식별자는 남긴다 ──

const TRACKING_PARAM = /^(utm_[a-z_]+|fbclid|gclid|dclid|msclkid|igshid|igsh|mc_cid|mc_eid|_hsenc|_hsmi|yclid|si)$/i;

// 내부망 주소는 출처로 받지 않는다(§10). 지금은 서버가 URL 을 열지 않지만, 나중에 수집기가
// 이 행을 이어받아도 내부망으로 요청이 나가지 않게 입구에서 막는다.
function isPrivateHost(host: string): boolean {
  const h = host.toLowerCase().replace(/^\[|\]$/g, "");
  if (h === "localhost" || h.endsWith(".localhost") || h.endsWith(".local") || h.endsWith(".internal")) return true;
  if (h.includes(":")) return h === "::1" || h === "::" || /^(fc|fd|fe80)/.test(h) || h.startsWith("::ffff:");
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31)
    || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);
}

export type UrlResult = { ok: true; url: string } | { ok: false; error: string };

export function normalizeUrl(raw: string): UrlResult {
  const s = raw.trim();
  let u: URL;
  try {
    u = new URL(s);
  } catch {
    return { ok: false, error: "URL 형식이 잘못됐습니다(https:// 로 시작하는 주소를 넣으세요)" };
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    return { ok: false, error: "http(s) 주소만 등록할 수 있습니다" };
  }
  if (u.username || u.password) return { ok: false, error: "계정 정보가 든 URL 은 등록할 수 없습니다" };
  if (isPrivateHost(u.hostname)) return { ok: false, error: "내부망 주소는 출처로 등록할 수 없습니다" };
  u.hash = "";
  for (const key of [...u.searchParams.keys()]) {
    if (TRACKING_PARAM.test(key)) u.searchParams.delete(key);
  }
  // URL 객체가 호스트는 소문자로, 기본 포트는 생략해 준다. 경로·나머지 파라미터 순서는 그대로 둔다.
  let out = u.toString();
  if (u.search === "" && out.endsWith("?")) out = out.slice(0, -1);
  return { ok: true, url: out };
}

// ── 인스타 릴스 링크(T3): 서버는 이 주소를 열지 않는다. 짧은 코드와(있으면) 계정 이름만 꺼낸다 ──

export type IgLinkResult = { ok: true; url: string; shortcode: string; username: string | null } | { ok: false; error: string };

export function parseIgReelLink(raw: string): IgLinkResult {
  let u: URL;
  try {
    u = new URL(raw.trim());
  } catch {
    return { ok: false, error: "릴스 주소 형식이 잘못됐습니다(https://www.instagram.com/reel/… 를 넣으세요)" };
  }
  if (u.protocol !== "https:" || !/^(www\.|m\.)?instagram\.com$/i.test(u.hostname)) {
    return { ok: false, error: "인스타그램 릴스 주소만 넣을 수 있습니다" };
  }
  const m = /^\/(?:([A-Za-z0-9._]{1,30})\/)?(reel|reels|p)\/([A-Za-z0-9_-]{5,40})\/?$/.exec(u.pathname);
  if (!m) return { ok: false, error: "릴스 주소에서 릴스 코드를 찾지 못했습니다" };
  return { ok: true, url: `https://www.instagram.com/${m[2] === "p" ? "p" : "reel"}/${m[3]}/`, shortcode: m[3], username: m[1]?.toLowerCase() ?? null };
}

// ── DB 오류 → HTTP ──

const STATUS_BY_CODE: Record<string, number> = {
  invalid_input: 400, invalid_pack: 400, invalid_plan: 400, scores_incomplete: 400,
  not_found: 404,
  ownership: 403,
  version_conflict: 409, draft_exists: 409, review_in_progress: 409, duplicate_suggested: 409, review_not_current: 409,
  plan_not_current: 409, review_changed: 409, plan_changed: 409, invalid_state: 409,
  invalid_transition: 409, immutable: 409,
  review_blocked: 422, review_not_approved: 422, below_threshold: 422,
  format_not_selected: 422, format_in_use: 422, plan_blocked: 422, plan_claim_not_core: 422,
  ref_not_owned: 403, ref_not_evidence: 422,
  // B단계
  duplicate_source: 409, run_in_progress: 409, run_limit: 429, source_not_active: 422, terms_unverified: 422,
  terms_restricted: 422, not_validated: 422, active_limit: 422, nothing_to_retry: 422, host_not_allowed: 422,
  // C단계
  paid_disabled: 422, not_renderable: 422, checklist_incomplete: 422, invalid_manifest: 422, asset_in_use: 409, asset_missing: 422,
  format_fit_low: 422, required_claims_missing: 422, plan_coverage: 422, plan_claim_unknown: 422,
  // 유료 결재(0054)
  approval_closed: 422, approval_expired: 422, kind_not_approved: 422, budget_exceeded: 422, budget_insufficient: 422,
  already_bought: 409, hold_in_progress: 409, retry_limit: 429,
  // 순환(0055)
  duplicate_account: 409, output_not_usable: 422, capability_missing: 422, duplicate_publication: 409,
  digest_mismatch: 409, not_publishable: 422, too_late: 422, stale_strategy: 409, insufficient_sample: 422,
  // 5단계 게시 연결(0068). meme_sync_blocked 는 아래 0066 묶음에 이미 있다
  ai_label_missing: 422, audio_mismatch: 422,
  // 소재 개발(0060)
  budget_missing: 422, evidence_insufficient: 422, script_check_failed: 422, develop_in_progress: 409,
  // 밈 보드(0063)
  not_normal_day: 409,
  // 내용 승인 한 번(0064)
  evidence_not_usable: 422, review_not_draft: 422, plan_stale: 409,
  // 음원 계약(0065)
  audio_required: 422, audio_not_for_carousel: 422, audio_not_found: 422, audio_connection_unsupported: 422, licensed_mix_not_rendered: 422,
  // 밈 제작(0066)
  meme_invalid: 422, meme_duration: 422, meme_sync_blocked: 422, meme_foreign_media: 422, meme_ai_label_missing: 422, meme_info_undeclared: 422,
  meme_evidence_missing: 422, meme_encourages_drinking: 422, meme_minor: 422, meme_overdrinking: 422, meme_drunk_driving: 422, meme_pregnancy: 422,
  card_not_precise: 422,
  // Apify 정밀화(0070)
  apify_budget_exhausted: 422, request_exists: 409, no_reels: 422, media_url_rejected: 422,
  // 설명형 제작(0067·0062)
  directive_missing: 422, selection_incomplete: 422, order_changed: 409, unknown_billed_open: 409, not_passed: 422, no_pass: 422, attempt_cap: 429, attempt_open: 409,
};

export interface DbError {
  message: string;
  details?: string | null;
  code?: string | null;
}

export interface ActionResponse {
  status: number;
  body: Record<string, unknown>;
}

export function mapDbError(err: DbError): ActionResponse {
  const m = /^drinks:([a-z_]+):(.*)$/s.exec(err.message ?? "");
  if (m) {
    let detail: unknown = null;
    if (err.details) {
      try {
        detail = JSON.parse(err.details);
      } catch {
        detail = err.details;
      }
    }
    return { status: STATUS_BY_CODE[m[1]] ?? 409, body: { error: m[2], code: m[1], detail } };
  }
  // 고유 제약 충돌 = 같은 요청이 동시에 두 번 들어왔다. 승인·버전은 바뀌지 않았다.
  // 교착·직렬화 실패: 두 요청이 같은 행을 동시에 건드렸다. 아무것도 저장되지 않았으니 다시 시도하면 된다.
  if (err.code === "40P01" || err.code === "40001") {
    return { status: 409, body: { error: "다른 작업과 동시에 처리돼 저장하지 않았습니다 — 화면을 새로 불러와 다시 시도하세요", code: "retry" } };
  }
  if (err.code === "23505") {
    return { status: 409, body: { error: "같은 요청이 동시에 처리됐습니다 — 화면을 새로 불러오세요", code: "conflict" } };
  }
  if (err.code === "23503" || err.code === "23514") {
    return { status: 400, body: { error: "입력값이 저장 규칙에 맞지 않습니다", code: "constraint", detail: err.message } };
  }
  if (err.code === "42883" || err.code === "42P01" || err.code === "PGRST202") {
    return {
      status: 503,
      body: { error: "주류 공장 DB 가 준비되지 않았습니다(0050·0051 마이그레이션 미적용)", code: "schema_missing" },
    };
  }
  return { status: 500, body: { error: "저장하지 못했습니다. 잠시 후 다시 시도하세요.", code: "db_error", detail: err.message } };
}

/** rpc 실행기. Supabase 라우트에서는 `(fn, p) => admin.rpc(fn, { p })`. */
export type RpcExec = (
  fn: string,
  p: Record<string, unknown>
) => PromiseLike<{ data: unknown; error: DbError | null }>;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** 출처 입력의 URL 을 정규화한다. 원래 문자열은 url_raw 로 남긴다. */
function prepareSource(src: unknown): { ok: true; source: Record<string, unknown> } | { ok: false; error: string } {
  if (!isRecord(src)) return { ok: false, error: "출처 형식이 잘못됐습니다" };
  const out: Record<string, unknown> = { ...src };
  delete out.content_hash; // 해시는 서버가 계산한다
  delete out.quote_check;
  const raw = typeof src.url === "string" ? src.url.trim() : "";
  delete out.url;
  if (raw) {
    const n = normalizeUrl(raw);
    if (!n.ok) return n;
    out.url_raw = raw;
    out.canonical_url = n.url;
  } else {
    delete out.canonical_url;
    delete out.url_raw;
  }
  return { ok: true, source: out };
}

/** 수집원 주소 정리: 공개 https 만, 추적 파라미터 제거. 허용 호스트는 DB 가 수집 주소에서 만든다(입력 무시). */
function prepareRegistry(p: Record<string, unknown>): { ok: true } | { ok: false; error: string } {
  const one = (raw: unknown, what: string): string | { error: string } => {
    const n = normalizeUrl(typeof raw === "string" ? raw : "");
    if (!n.ok) return { error: `${what}: ${n.error}` };
    if (!n.url.startsWith("https://")) return { error: `${what}: https 주소만 수집원으로 등록합니다` };
    return n.url;
  };
  const home = one(p.home_url, "대표 주소");
  if (typeof home !== "string") return { ok: false, error: home.error };
  p.home_url = home;
  const raw = Array.isArray(p.entry_urls) ? p.entry_urls : [];
  const urls: string[] = [];
  for (const u of raw) {
    if (typeof u !== "string" || !u.trim()) continue;
    const n = one(u, "수집 주소");
    if (typeof n !== "string") return { ok: false, error: n.error };
    if (!urls.includes(n)) urls.push(n);
  }
  p.entry_urls = urls;
  delete p.allowed_hosts;
  return { ok: true };
}

export async function runDrinksAction(exec: RpcExec, body: unknown): Promise<ActionResponse> {
  if (!isRecord(body) || typeof body.action !== "string") {
    return { status: 400, body: { error: "action 이 필요합니다", code: "invalid_input" } };
  }
  const action = body.action;
  if ((PHASE_A_EXCLUDED as readonly string[]).includes(action)) {
    return {
      status: 403,
      body: {
        error: "이 기능은 주류 공장에 연결되지 않았습니다(임의 URL 열기·LLM·유료 생성·발행은 꺼져 있음)",
        code: "not_in_phase_a",
      },
    };
  }
  if (!Object.prototype.hasOwnProperty.call(DRINKS_ACTIONS, action)) {
    return { status: 400, body: { error: "알 수 없는 동작입니다", code: "unknown_action" } };
  }
  const fn = DRINKS_ACTIONS[action as DrinksAction];
  const p: Record<string, unknown> = isRecord(body.payload) ? { ...body.payload } : {};

  if (action === "create_topic" || action === "add_source") {
    if (p.source !== undefined && p.source !== null) {
      const s = prepareSource(p.source);
      if (!s.ok) return { status: 400, body: { error: s.error, code: "invalid_input" } };
      p.source = s.source;
    } else if (action === "add_source") {
      return { status: 400, body: { error: "출처를 입력하세요", code: "invalid_input" } };
    }
  }

  if (action === "register_source") {
    const s = prepareRegistry(p);
    if (!s.ok) return { status: 400, body: { error: s.error, code: "invalid_input" } };
  }
  if (action === "add_discovery") {
    // 수동 발견 자료: 서버는 이 URL 을 열지 않는다. 정규화(추적 파라미터 제거)와 내부망 주소 거부만 한다.
    const n = normalizeUrl(typeof p.url === "string" ? p.url : "");
    if (!n.ok) return { status: 400, body: { error: n.error, code: "invalid_input" } };
    p.canonical_url = n.url;
    delete p.url;
  }
  if (action === "open_spend_approval") {
    // 결재는 화면에서 운영자 키를 가진 사람만 연다. 결재자 이름은 입력값을 믿지 않는다. 결재 문장은 필수(DB 도 검사).
    p.approved_by = "operator";
    if (typeof p.approver_words !== "string" || !p.approver_words.trim()) {
      return { status: 400, body: { error: "결재 문장(승인한 말 그대로)을 적으세요", code: "invalid_input" } };
    }
  }
  if (action === "request_develop") {
    if (p.kind !== "evidence" && p.kind !== "plan") {
      return { status: 400, body: { error: "만들 초안 종류(evidence·plan)를 고르세요", code: "invalid_input" } };
    }
  }
  if (action === "pick_topic" && p.format !== "explainer" && p.format !== "card" && p.format !== "meme") {
    return { status: 400, body: { error: "형식(설명형·카드뉴스·밈형)을 고르세요", code: "invalid_input" } };
  }
  if (action === "explainer_verdict") {
    // 화면에서 오는 판정은 사람 판정뿐이다. 자동 판정 칸은 입력을 믿지 않고 지운다.
    delete p.auto_verdict;
    delete p.auto_report;
    if (p.human_verdict !== "pass" && p.human_verdict !== "fail") {
      return { status: 400, body: { error: "사람 판정(합격·불합격)을 고르세요", code: "invalid_input" } };
    }
  }
  if (action === "explainer_select") p.selected_by = "operator"; // 고른 사람·닫은 사람 이름은 입력값을 믿지 않는다(운영자 키 게이트를 통과한 사람)
  if (action === "explainer_close_unknown") p.closed_by = "operator";
  if (action === "explainer_request_buy" && p.through_n !== undefined && p.through_n !== null) {
    const n = Number(p.through_n);
    if (!Number.isInteger(n) || n < 1) return { status: 400, body: { error: "슬롯 번호는 1 이상의 정수입니다", code: "invalid_input" } };
    p.through_n = n;
  }
  if (action === "open_develop_budget") {
    // 개발 결재도 운영자 키를 가진 사람만 연다. 결재자 이름은 입력값을 믿지 않고, 결재 문장은 필수(DB 도 검사).
    p.approved_by = "operator";
    if (typeof p.approver_words !== "string" || !p.approver_words.trim()) {
      return { status: 400, body: { error: "결재 문장(승인한 말 그대로)을 적으세요", code: "invalid_input" } };
    }
    if (typeof p.stage !== "string" || !p.stage.trim()) {
      return { status: 400, body: { error: "결재 단계 이름을 적으세요", code: "invalid_input" } };
    }
    const cap = Number(p.cap_usd);
    if (!Number.isFinite(cap) || cap <= 0) {
      return { status: 400, body: { error: "상한 금액은 0보다 커야 합니다", code: "invalid_input" } };
    }
    p.cap_usd = cap;
    if (p.days !== undefined && p.days !== null) {
      const days = Number(p.days);
      if (!Number.isInteger(days) || days < 1) return { status: 400, body: { error: "유효 기간(일)은 1 이상의 정수여야 합니다", code: "invalid_input" } };
      p.days = days;
    }
  }
  if (action === "publication_action" || action === "strategy_action") {
    p.actor = "operator"; // 승인·반영한 사람 이름은 입력값을 믿지 않는다(운영자 키 게이트를 통과한 사람)
  }
  if (action === "register_account") {
    // 토큰 원문은 받지 않는다 — 비밀 이름(credential_ref)만. 토큰처럼 보이는 칸이 오면 저장 전에 거부한다.
    for (const k of ["access_token", "token", "refresh_token", "app_secret"]) {
      if (k in p) return { status: 400, body: { error: "토큰 원문은 넣지 않습니다 — 서버 비밀 이름만 적으세요", code: "invalid_input" } };
    }
  }
  if (action === "ig_add_link") {
    const l = parseIgReelLink(typeof p.url === "string" ? p.url : "");
    if (!l.ok) return { status: 400, body: { error: l.error, code: "invalid_input" } };
    const typed = typeof p.username === "string" ? p.username.trim().replace(/^@/, "").toLowerCase() : "";
    const username = typed || l.username;
    if (!username) return { status: 400, body: { error: "이 주소에는 계정 이름이 없습니다 — 계정 이름을 같이 적으세요", code: "invalid_input" } };
    p.canonical_url = l.url;
    p.shortcode = l.shortcode;
    p.username = username;
    delete p.url;
  }
  if (action === "request_run") {
    // 화면에서는 운영자 요청만 만든다. 예약 실행은 워커(--schedule)만 만든다.
    p.requested_by = "operator";
    delete p.scheduled_for;
  }

  const { data, error } = await exec(fn, p);
  if (error) return mapDbError(error);
  return { status: 200, body: { ok: true, result: data } };
}
