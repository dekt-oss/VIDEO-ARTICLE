// 주류 공장 B단계 화면 규칙(순수 함수) — 수집원 상태·실행 결과 문장·비슷한 소재 후보. 2026-10-22.
// ★ 값 import 없음(node --test 가 경로 별칭을 못 푼다). 타입만 가져온다.
import type { ItemRow, RunRow, RunStatus, SourceMethod, SourceRow, SourceState } from "./types";

export const SOURCE_STATE_LABEL: Record<SourceState, string> = {
  proposed: "제안", validated: "검증 완료", active: "활성", paused: "일시 중지", retired: "종료",
};
export const METHOD_LABEL: Record<SourceMethod, string> = {
  manual_url: "수동 URL 등록(수집 안 함)", approved_page: "승인한 고정 페이지", listing: "승인한 목록 페이지의 글", feed: "확인된 피드",
};
export const TERMS_LABEL: Record<SourceRow["terms_status"], string> = {
  unverified: "이용 조건 미확인", verified: "이용 조건 확인됨", restricted: "이용 조건이 수집을 막음",
};

/** 실행 결과 — "정상 0건"과 "실패"가 같은 모양으로 보이지 않게 문장·색을 따로 둔다. */
export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: "대기", running: "실행 중", succeeded: "성공", empty: "정상 0건", partial: "부분 성공", failed: "실패",
  aborted: "실행 중단",
};
export function runTone(s: RunStatus): "ok" | "warn" | "bad" | "info" {
  if (s === "succeeded" || s === "empty") return "ok";
  if (s === "partial" || s === "aborted") return "warn";
  if (s === "failed") return "bad";
  return "info";
}
export const RUN_MODE_LABEL: Record<RunRow["mode"], string> = { collect: "수집", validate: "검증", retry: "실패분 재시도" };

export const ITEM_STATUS_LABEL: Record<ItemRow["status"], string> = {
  new: "새 문서", changed: "본문 바뀜(새 버전)", unchanged: "변화 없음", metadata_only: "제목·요약만",
  skipped: "건너뜀", failed: "실패", checked: "검증용 확인(저장 안 함)",
};

const ERROR_TEXT: Record<string, string> = {
  robots_disallowed: "robots.txt 가 막음", http_error: "사이트가 오류 응답", timeout: "시간 초과", transport: "연결 실패",
  too_large: "응답이 크기 상한 초과", unsupported_type: "본문으로 읽지 않는 형식", host_not_allowed: "승인 밖 호스트",
  private_address: "공개 주소가 아님", too_many_redirects: "리다이렉트 과다", request_cap: "요청 상한 도달",
  time_budget: "시간 예산 초과", limit_exceeded: "실행 상한 도달", lease_expired: "워커 응답 끊김(임대 만료)",
  queue_expired: "대기 시간 초과", source_not_runnable: "대기 중 수집원 상태 변경", no_body_extracted: "본문을 하나도 못 뽑음",
  some_items_failed: "일부 문서 실패", dns_failed: "주소를 찾지 못함", db_error: "기록 실패",
  limit_reached: "상한 때문에 새 글을 다 못 가져옴", no_candidates: "목록에서 글을 하나도 못 찾음(사이트 개편 의심)",
  all_skipped: "전부 건너뜀 — 수집 0건", robots_unavailable: "robots.txt 를 받지 못함", worker_error: "워커 예외",
  parser_config_invalid: "파서 설정 오류", api_key_missing: "API 키 없음(키 설정 필요)", api_error: "API 오류 응답",
};
export function errorText(code: string | null | undefined): string {
  if (!code) return "";
  return ERROR_TEXT[code] ?? code;
}

/** 실행 한 줄 요약. 0건이면 "정상 0건"인지 "목록을 못 가져온 실패"인지 문장이 다르다. */
export function runSummary(r: Pick<RunRow, "status" | "item_count" | "new_count" | "changed_count" | "unchanged_count"
  | "metadata_count" | "skipped_count" | "failed_count" | "error_code">): string {
  if (r.status === "queued") return "대기 중 — 워커가 가져가면 시작합니다";
  if (r.status === "running") return "실행 중";
  if (r.status === "empty") return "정상 0건 — 목록은 가져왔고 새 글이 없습니다";
  if (r.status === "failed" && r.item_count === 0) return `실패 — 문서를 하나도 기록하지 못했습니다(${errorText(r.error_code)})`;
  const parts = [`문서 ${r.item_count}건`];
  if (r.new_count) parts.push(`새 ${r.new_count}`);
  if (r.changed_count) parts.push(`바뀜 ${r.changed_count}`);
  if (r.unchanged_count) parts.push(`변화 없음 ${r.unchanged_count}`);
  if (r.metadata_count) parts.push(`제목·요약만 ${r.metadata_count}`);
  if (r.skipped_count) parts.push(`건너뜀 ${r.skipped_count}`);
  if (r.failed_count) parts.push(`실패 ${r.failed_count}`);
  if (r.status === "aborted") parts.push(`중단: ${errorText(r.error_code)}`);
  return parts.join(" · ");
}

/** 임대가 끝났는데 아직 running — 워커가 죽었다. 다음 요청·실행이 '중단'으로 닫는다. 정상 진행처럼 보이면 안 된다. */
export function runStuck(r: Pick<RunRow, "status" | "lease_expires_at">, now: number = Date.now()): boolean {
  return r.status === "running" && r.lease_expires_at !== null && new Date(r.lease_expires_at).getTime() < now;
}

/** 재시도 버튼을 보여줄 실행: 부분 성공·실패·중단된 수집 실행(검증 실행은 아님). */
export function canRetry(r: Pick<RunRow, "status" | "mode">): boolean {
  return r.mode !== "validate" && (r.status === "partial" || r.status === "failed" || r.status === "aborted");
}

/** 수집원에서 지금 누를 수 있는 운영자 동작. DB 가 다시 막지만, 안 되는 버튼은 처음부터 보이지 않게. */
export function sourceActions(s: Pick<SourceRow, "state" | "terms_status" | "method">, lastValidation: RunStatus | null) {
  const collectable = s.method !== "manual_url";
  return {
    validateRun: collectable && s.terms_status !== "restricted" && ["proposed", "validated", "paused"].includes(s.state),
    markValidated: collectable && s.state === "proposed" && lastValidation === "succeeded" && s.terms_status !== "restricted",
    // DB 와 같은 규칙: 가장 최근에 끝난 검증 실행이 성공이어야 한다.
    activate: (s.state === "validated" || s.state === "paused") && s.terms_status === "verified" && lastValidation === "succeeded",
    collectNow: s.state === "active",
    pause: s.state === "active",
    retire: s.state !== "retired",
  };
}

// ── 비슷한 소재 후보(규칙 기반, LLM 없음) ──
// 수집 문서 제목과 기존 소재(제목+질문)의 글자 조각(2-gram) 겹침. "같은 소재"라고 판정하지 않는다 — 후보로 보여주기만.

function grams(s: string): Set<string> {
  const t = s.toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
  const out = new Set<string>();
  for (let i = 0; i < t.length - 1; i++) out.add(t.slice(i, i + 2));
  return out;
}

export function similarity(a: string, b: string): number {
  const x = grams(a);
  const y = grams(b);
  if (x.size === 0 || y.size === 0) return 0;
  let both = 0;
  for (const g of x) if (y.has(g)) both++;
  return both / Math.min(x.size, y.size);
}

export const SIMILAR_MIN = 0.5;

export function similarTopics<T extends { id: string; title: string; question: string; status: string }>(
  text: string, topics: readonly T[], limit = 3,
): { topic: T; score: number }[] {
  if (!text.trim()) return [];
  return topics
    .filter((t) => t.status !== "duplicate")
    .map((t) => ({ topic: t, score: Math.max(similarity(text, t.title), similarity(text, t.question)) }))
    .filter((x) => x.score >= SIMILAR_MIN)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}
