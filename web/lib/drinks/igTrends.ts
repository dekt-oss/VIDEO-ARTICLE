// 인스타 트렌드 보드·밈 보드(0063) — 화면 규칙·타입(순수). 값 import 없음(node --test).
// 기획 v2 §6. 0059 의 커뮤니티 동향(trends.ts)과 다른 기능이다.
// ★ 판정의 정본은 engine/drinks_ig_trends.py·DB 함수다. 화면은 실행 기록을 읽어 "지금 믿어도 되는 상태인가"만 계산한다
//   (워크플로가 아예 안 돌면 아무도 기록을 남기지 못하므로, 오늘 날짜 기준 계산은 화면에서 해야 한다).
// ★ 문턱 값은 engine/config.py DRINKS_IG_* 와 같아야 한다(tests/test_drinks_ig_trends.py 가 대조).

export const NORMAL_T2_MIN_RATE = 0.8;
export const FREEZE_MISSING_DAYS = 3;
export const TOKEN_WARN_DAYS = 14;

export type IgRunStatus = "ok" | "ok_empty" | "partial" | "failed" | "not_run";
export type IgSource = "t1" | "t2" | "t3" | "t4";
export type CardState = "new" | "rising" | "peak" | "cooled";
export type CardDecision = "use" | "pass" | "later";
export type CardPrecision = "reference" | "precise";

export const RUN_STATUS_LABEL: Record<IgRunStatus, string> = {
  ok: "정상",
  ok_empty: "정상 — 결과 0건",
  partial: "일부 실패",
  failed: "실패",
  not_run: "안 돌았음",
};

export const SOURCE_LABEL: Record<IgSource, string> = {
  t1: "T1 인기 음원",
  t2: "T2 관찰 계정",
  t3: "T3 운영자 링크",
  t4: "T4 형식 조사(Apify)",
};

export const STATE_LABEL: Record<CardState, string> = { new: "새로 뜸", rising: "오르는 중", peak: "정점", cooled: "식음" };
export const DECISION_LABEL: Record<CardDecision, string> = { use: "쓰자", pass: "넘기기", later: "나중에" };
export const PRECISION_LABEL: Record<CardPrecision, string> = { reference: "참고 카드", precise: "정밀 틀" };

export const STRUCTURE_LABEL: Record<string, string> = { pov: "POV", before_after: "전후", twist: "반전", list: "리스트", reaction: "반응" };

export const EVIDENCE_LABEL: Record<string, string> = {
  video: "영상", cover: "표지", caption: "캡션", api_metrics: "API 값", operator: "운영자 입력",
};

/** §6-5 표의 칸. video_only 는 영상을 봐야만 채울 수 있다(표지·캡션 근거는 DB 가 거부한다). */
export const FORMAT_FIELDS: { key: string; label: string; videoOnly: boolean }[] = [
  { key: "structure", label: "구조", videoOnly: false },
  { key: "cover_text", label: "표지 글자", videoOnly: false },
  { key: "caption_hook", label: "캡션 훅 문장", videoOnly: false },
  { key: "audio_type", label: "음원 종류", videoOnly: false },
  { key: "beat_count", label: "비트 수", videoOnly: true },
  { key: "cut_lengths", label: "컷 길이", videoOnly: true },
  { key: "twist_at", label: "반전 시점", videoOnly: true },
  { key: "first_1_5s", label: "첫 1.5초 내용", videoOnly: true },
  { key: "music_sync", label: "음악 동기화", videoOnly: true },
];

const FAILURE_LABEL: Record<string, string> = {
  token_expired: "토큰 만료",
  token_missing: "토큰 없음",
  invalid_user: "계정을 못 찾음(개인 계정·없는 이름)",
  no_data: "응답에 계정 정보 없음",
  rate_limited: "호출 한도",
  request_cap: "요청 상한",
  permission: "권한 없음",
  bad_request: "요청 거부(묻는 칸 확인 필요)",
  bad_shape: "응답 모양이 다름",
  network: "연결 실패",
  api_error: "API 오류",
  record_failed: "기록 거절",
  not_in_recent: "최근 릴스에 없음",
};

export const failureText = (code: string | null | undefined): string => (code ? FAILURE_LABEL[code] ?? code : "");

export interface IgRunRow {
  source: IgSource;
  observed_on: string;
  status: IgRunStatus;
  attempted: number;
  succeeded: number;
  items: number;
  failure_reasons: Record<string, number> | null;
  excluded_no_views: number | null;
  detail: Record<string, unknown> | null;
  finished_at: string;
}

export interface IgTokenRow {
  checked_on: string;
  status: "ok" | "expired" | "missing" | "unavailable";
  expires_at: string | null;
  data_access_expires_at: string | null;
  error_code: string | null;
}

export interface IgAccountRow {
  username: string;
  status: "candidate" | "active" | "paused";
  kind: "meme" | "drinks" | "explainer" | "other";
  origin: "doc_measured" | "operator";
  note: string | null;
  first_observed_on: string | null;
  last_ok_on: string | null;
  last_error_code: string | null;
  last_error_on: string | null;
  followers_count: number | null;
}

export interface IgAudioRow {
  audio_id: string;
  audio_type: "music" | "original_sound";
  title: string | null;
  display_artist: string | null;
  ig_username: string | null;
  duration_ms: number | null;
  preview_url: string | null;
  first_seen_on: string;
  observed_on: string;
  list_position: number;
  rising_reason: "new" | "three_days" | null;
}

export interface IgExample {
  media_id: string;
  username: string;
  permalink: string | null;
  origin: "rising_reel" | "operator_link";
  view_multiple: number | null;
  view_count: number | null;
  hook: string | null;
}

export interface IgCardRow {
  id: string;
  merge_key: string;
  kind: "audio" | "challenge" | "structure_hook" | "single_reel";
  name: string;
  audio_id: string | null;
  challenge_name: string | null;
  structure: string | null;
  state: CardState;
  first_seen_on: string;
  last_signal_on: string | null;
  last_evaluated_on: string | null;
  quiet_normal_days: number;
  archived_on: string | null;
  decision: CardDecision | null;
  decision_note: string | null;
  precision: CardPrecision;
  examples_count: number;
  accounts_count: number;
  max_multiple: number | null;
  same_audio_cards: number;
  examples: IgExample[];
  fields: Record<string, { value: string; evidence: string; confidence: string }>;
  audio_position: number | null;
  audio_position_on: string | null;
}

export interface IgLinkRow {
  id: string;
  canonical_url: string;
  shortcode: string;
  username: string;
  note: string | null;
  status: "pending" | "resolved" | "not_found" | "account_unavailable" | "failed";
  attempts: number;
  error_code: string | null;
  created_at: string;
}

export const LINK_STATUS_LABEL: Record<IgLinkRow["status"], string> = {
  pending: "다음 수집 때 확인",
  resolved: "찾음",
  not_found: "최근 릴스 25개에 없음",
  account_unavailable: "공개 비즈니스·크리에이터 계정이 아님",
  failed: "세 번 실패",
};

/** 읽기에서 0063 이 아직 적용되지 않은 오류인가(표/보기가 없다). 0건과 구별해 보여준다. */
export function isMissingIgTables(message: string | null | undefined): boolean {
  const m = message ?? "";
  return /drink_ig_/.test(m) && /does not exist|schema cache|not found|Could not find/i.test(m);
}

/** T1 이 ok 이고 T2 계정 성공률 80% 이상. engine/drinks_ig_trends.is_normal_day 와 같은 규칙. */
export function isNormalDay(t1: Pick<IgRunRow, "status"> | undefined, t2: Pick<IgRunRow, "attempted" | "succeeded"> | undefined): boolean {
  if (!t1 || t1.status !== "ok" || !t2 || t2.attempted <= 0) return false;
  return t2.succeeded / t2.attempted >= NORMAL_T2_MIN_RATE;
}

function shiftDay(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export interface BoardHealth {
  /** 실행 기록이 하나도 없다 — 끊긴 것이 아니라 시작 전이다 */
  neverRun: boolean;
  lastNormalDay: string | null;
  normalLast7: number;
  /** 최근부터 이어진 정상 아닌 날 수(기록 없는 날 포함). 오늘 기록이 아직 없으면 오늘은 세지 않는다 */
  missingStreak: number;
  frozen: boolean;
  /** '관찰 범위: 계정 성공 N / 목록 M' */
  scope: { succeeded: number; listed: number; on: string | null };
  noActiveAccounts: boolean;
}

export function boardHealth(runs: readonly IgRunRow[], today: string, activeCount: number): BoardHealth {
  const daily = runs.filter((r) => r.source !== "t4");
  const byDay = new Map<string, Partial<Record<IgSource, IgRunRow>>>();
  for (const r of daily) {
    const day = r.observed_on.slice(0, 10);
    byDay.set(day, { ...(byDay.get(day) ?? {}), [r.source]: r });
  }
  const normal = (day: string) => {
    const s = byDay.get(day);
    return s ? isNormalDay(s.t1, s.t2) : false;
  };
  const days = [...byDay.keys()].sort();
  const t2Rows = daily.filter((r) => r.source === "t2").sort((a, b) => b.observed_on.localeCompare(a.observed_on));
  const latestT2 = t2Rows[0];
  const scope = latestT2 && latestT2.attempted > 0
    ? { succeeded: latestT2.succeeded, listed: latestT2.attempted, on: latestT2.observed_on.slice(0, 10) }
    : { succeeded: 0, listed: activeCount, on: latestT2 ? latestT2.observed_on.slice(0, 10) : null };
  const noActiveAccounts = activeCount === 0;
  if (days.length === 0) {
    return { neverRun: true, lastNormalDay: null, normalLast7: 0, missingStreak: 0, frozen: false, scope, noActiveAccounts };
  }
  const normals = days.filter(normal);
  let normalLast7 = 0;
  for (let i = 0; i < 7; i++) if (normal(shiftDay(today, -i))) normalLast7 += 1;
  let d = byDay.has(today) ? today : shiftDay(today, -1);
  let missingStreak = 0;
  while (d >= days[0] && !normal(d)) {
    missingStreak += 1;
    d = shiftDay(d, -1);
  }
  return {
    neverRun: false,
    lastNormalDay: normals.length ? normals[normals.length - 1] : null,
    normalLast7,
    missingStreak,
    frozen: missingStreak >= FREEZE_MISSING_DAYS,
    scope,
    noActiveAccounts,
  };
}

/** 수집원별 가장 최근 기록. */
export function latestRuns(runs: readonly IgRunRow[]): Partial<Record<IgSource, IgRunRow>> {
  const out: Partial<Record<IgSource, IgRunRow>> = {};
  for (const r of runs) {
    const cur = out[r.source];
    if (!cur || r.observed_on > cur.observed_on) out[r.source] = r;
  }
  return out;
}

export function reasonsText(reasons: Record<string, number> | null | undefined): string {
  const e = Object.entries(reasons ?? {}).filter(([, n]) => n > 0);
  return e.map(([k, n]) => `${failureText(k)} ${n}`).join(" · ");
}

export interface TokenView {
  level: "none" | "ok" | "warn" | "bad";
  text: string;
  daysLeft: number | null;
}

/** 토큰 상태 문장. 만료 14일 전부터 warn, 만료·없음은 bad. 기록이 없으면 none(모른다고 말한다). */
export function tokenView(row: IgTokenRow | null, nowMs: number): TokenView {
  if (!row) return { level: "none", text: "토큰 확인 기록이 아직 없습니다", daysLeft: null };
  if (row.status === "missing") return { level: "bad", text: "토큰이 이 실행 환경에 없습니다 — GitHub 비밀을 확인하세요. 그동안 수집은 실패로 기록되고 카드 상태는 멈춥니다", daysLeft: null };
  const left = row.expires_at ? Math.floor((Date.parse(row.expires_at) - nowMs) / 86_400_000) : null;
  if (row.status === "expired" || (left !== null && left < 0)) {
    return { level: "bad", text: "토큰이 만료됐습니다 — 다시 받기 전까지 수집은 실패로 기록되고 카드 상태는 멈춥니다", daysLeft: left };
  }
  if (row.status === "unavailable") return { level: "warn", text: `토큰 만료일을 확인하지 못했습니다(${failureText(row.error_code) || "사유 없음"})`, daysLeft: null };
  if (left === null) return { level: "ok", text: "토큰: 만료일 없음", daysLeft: null };
  if (left < TOKEN_WARN_DAYS) return { level: "warn", text: `토큰 만료까지 ${left}일 남았습니다 — 다시 받는 절차: docs/안내_페이스북로그인전환_2026-10-30.md 4~6번`, daysLeft: left };
  return { level: "ok", text: `토큰 만료까지 ${left}일`, daysLeft: left };
}

/** '인스타가 우리 계정에 준 추천 순서' 안의 자리. 오늘 관측이 아니면 그 날짜를 적는다. */
export function positionLabel(position: number, observedOn: string, today: string): string {
  const day = observedOn.slice(0, 10);
  return day === today ? `목록 ${position}번째(우리 계정 기준, 오늘)` : `목록 ${position}번째(우리 계정 기준, ${day} 관측)`;
}

export const RISING_AUDIO_LABEL: Record<"new" | "three_days", string> = { new: "목록에 처음 들어옴", three_days: "3일 연속 목록에 남음" };

/** 오르는 음원을 앞으로, 목록 자리 순으로. */
export function sortAudio<T extends Pick<IgAudioRow, "rising_reason" | "list_position" | "audio_id">>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => Number(!a.rising_reason) - Number(!b.rising_reason) || a.list_position - b.list_position || a.audio_id.localeCompare(b.audio_id));
}

export interface CardGroups<T> {
  undecided: T[];
  use: T[];
  later: T[];
  pass: T[];
  archived: T[];
}

const STATE_ORDER: Record<CardState, number> = { rising: 0, new: 1, peak: 2, cooled: 3 };

/** 결정별로 나눈다. 쓰자로 고른 카드는 식어도 '쓰자'에 남는다 — 화면이 '식었음'을 띄워 다시 판단하게 한다. */
export function groupCards<T extends Pick<IgCardRow, "decision" | "state" | "archived_on" | "first_seen_on" | "id">>(rows: readonly T[]): CardGroups<T> {
  const out: CardGroups<T> = { undecided: [], use: [], later: [], pass: [], archived: [] };
  const sorted = [...rows].sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || b.first_seen_on.localeCompare(a.first_seen_on) || a.id.localeCompare(b.id));
  for (const c of sorted) {
    if (c.decision === "use") out.use.push(c);
    else if (c.decision === "pass") out.pass.push(c);
    else if (c.archived_on) out.archived.push(c);
    else if (c.decision === "later") out.later.push(c);
    else out.undecided.push(c);
  }
  return out;
}

/** [쓰자] 뒤 화면 문장. 돈이 나가는 일이 시작되지 않는다는 것을 그대로 말한다. */
export function noteAfterUse(c: Pick<IgCardRow, "precision" | "state">): string {
  const cooled = c.state === "cooled" ? "식었음 — 만들지 말지 다시 판단하세요. " : "";
  if (c.precision === "precise") return `${cooled}정밀 틀입니다. 밈 제작 엔진이 연결되면 이 틀로 넘어갑니다(아직 연결 전). 결정만 기록했고 돈은 나가지 않았습니다.`;
  return `${cooled}참고 카드입니다. 원본 릴스를 보고 비트 수·컷 길이·반전 시점을 직접 넣으면 정밀 틀이 됩니다. 결정만 기록했고 돈은 나가지 않았습니다.`;
}

export const compactNum = (n: number | null | undefined): string => (typeof n === "number" ? n.toLocaleString("ko-KR") : "미제공");

export const isoToday = (nowMs: number): string => new Date(nowMs + 9 * 3_600_000).toISOString().slice(0, 10);
