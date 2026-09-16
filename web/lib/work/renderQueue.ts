// 렌더 잡 분류 + 상태별 주요 행동 1개 (개선 지시서 RENDER-02 / §6-5).
//
// 지금까지 ⑥ 렌더 결과는 날짜순 목록이라 "실패해서 막힌 것"과 "이미 끝난 것"이 섞여 있었고,
// 완료 카드에는 강조 버튼이 4개(발행 이관·유튜브·언어추가·보관) 나란히 있어 무엇이 다음인지
// 알 수 없었다. 여기서 잡 하나를 탭 하나로 보내고, 주요 행동을 하나만 고른다.
//
// 순수 함수 — RenderJob 모양만 안다(테스트: lib/work/renderQueue.test.ts).

// 사람이 봐야 끝나는 상태(§8-3). **정본은 lib/renderStatus.ts 다** — 여기에 다시 적는 이유는
// 이 모듈이 `node --test` 로 직접 도는 순수 모듈이기 때문이다: node 는 import 에 ".ts" 확장자를
// 요구하는데 tsc 는 프로젝트 내 파일에서 그 확장자를 거부한다(TS5097). 둘을 동시에 만족시킬
// 방법이 없어 두 줄을 복제하고, 대신 tests/test_schema_parity.py 가 두 파일이 갈리면 잡는다
// (engine/config.py ↔ lib/renderStatus.ts 쌍둥이를 지키는 것과 같은 방식이다).
const AWAITING_HUMAN = ["qa_pending", "degraded"];

export type RenderTab = "action" | "running" | "done" | "saved";

export const RENDER_TABS: { key: RenderTab; label: string }[] = [
  { key: "action", label: "조치 필요" },
  { key: "running", label: "진행 중" },
  { key: "done", label: "완료" },
  { key: "saved", label: "보관" },
];

/** 분류·행동 판정에 쓰는 최소 필드(RenderJob 의 부분집합 — 리포트 잡도 같은 모양이다). */
export interface QueueJob {
  status: string;
  output_url?: string | null;
  saved_at?: string | null;
  qa?: { hard_fail?: string[] } | null;
  youtube_status?: "queued" | "processing" | "done" | "error" | null;
}

/**
 * 탭 판정. 순서가 의미다 — 보관(사용자가 의도적으로 치운 것)이 아니라면 막힌 것부터 본다.
 *   action  : 실패 / QA 하드실패 / 업로드 실패 / 완료됐지만 아직 업로드하지 않음
 *   running : 큐·에셋·TTS·조립 진행 중 / 유튜브 업로드 진행 중
 *   done    : 유튜브 업로드까지 끝난 것
 *   saved   : 보관 표시한 것
 */
export function classifyRenderJob(j: QueueJob): RenderTab {
  if (j.saved_at) return "saved";
  if (j.status === "failed") return "action";
  // ★ 사람이 봐야 끝나는 상태(§8-3)는 '조치 필요'다. 아래 `status !== "done"` 한 줄이
  //   이것들을 전부 '진행 중'으로 삼켜서, degraded 잡이 **영원히 진행 중으로 보이고**
  //   승인 버튼이 뜰 자리조차 없었다. 워치독도 안 건드리니 정말로 영원하다.
  if (AWAITING_HUMAN.includes(j.status)) return "action";
  if (j.status !== "done") return "running";

  // 여기서부터 status === "done"
  if (j.youtube_status === "error") return "action";
  if (j.youtube_status === "queued" || j.youtube_status === "processing") return "running";
  if (j.youtube_status === "done") return "done";
  // 업로드 요청 전 — QA 하드실패면 먼저 봐야 하고, 아니어도 확인·업로드가 남았다.
  return "action";
}

export type PrimaryActionKey =
  | "approve_degraded"
  | "retry_render"
  | "review_video"
  | "upload"
  | "retry_upload"
  | "none";

export interface PrimaryAction {
  key: PrimaryActionKey;
  label: string;
  /** 이 행동이 왜 지금 필요한지(툴팁·보조 문구) */
  why: string;
}

/**
 * 카드에서 강조할 버튼 하나. 나머지는 낮은 강조로 내린다(지시서 §6-5 표).
 * QA 하드실패는 업로드보다 "영상 확인"이 먼저다 — 실검에서 문제가 잡힌 mp4 를 그대로 올리면 안 된다.
 */
export function primaryAction(j: QueueJob): PrimaryAction {
  if (j.status === "failed") {
    return { key: "retry_render", label: "↻ 재렌더", why: "실패 원인을 확인한 뒤 다시 렌더합니다" };
  }
  // ★ 사람이 봐야 끝나는 상태(§8-3). 아래 `status !== "done"` 보다 **먼저** 와야 한다 —
  //   그러지 않으면 "진행 중 — 끝나면 자동으로 갱신됩니다" 가 뜨는데, 워치독이 안 건드리므로
  //   그 말은 거짓이다. 아무도 안 누르면 영원히 그대로다.
  if (j.status === "degraded") {
    return {
      key: "approve_degraded",
      label: "확인하고 승인",
      why: "중요 요소가 빠진 채 렌더됐습니다 — 영상을 보고 승인해야 발행할 수 있습니다",
    };
  }
  if (j.status === "qa_pending") {
    return { key: "review_video", label: "영상 확인", why: "QA 경고가 있어 확인이 필요합니다" };
  }
  if (j.status !== "done") {
    return { key: "none", label: "", why: "진행 중 — 끝나면 자동으로 갱신됩니다" };
  }
  if (j.youtube_status === "error") {
    return { key: "retry_upload", label: "▶️ 업로드 재시도", why: "업로드 실패 원인을 해결한 뒤 재시도합니다" };
  }
  if (j.youtube_status === "queued" || j.youtube_status === "processing") {
    return { key: "none", label: "", why: "업로드 진행 중" };
  }
  if (j.youtube_status === "done") {
    return { key: "none", label: "", why: "업로드 완료" };
  }
  if (j.qa?.hard_fail?.length) {
    return { key: "review_video", label: "영상 확인", why: "렌더 QA 하드 실패 — 업로드 전에 영상을 확인하세요" };
  }
  if (!j.output_url) {
    return { key: "review_video", label: "영상 확인", why: "완료로 표시됐지만 mp4 주소가 없습니다" };
  }
  return { key: "upload", label: "▶️ 유튜브 업로드", why: "확인이 끝났으면 비공개로 업로드합니다" };
}

/** 탭별 건수(빈 탭을 숨기지 않고 0 으로 보여주기 위해 전부 계산). */
export function countByTab(jobs: QueueJob[]): Record<RenderTab, number> {
  const out: Record<RenderTab, number> = { action: 0, running: 0, done: 0, saved: 0 };
  for (const j of jobs) out[classifyRenderJob(j)] += 1;
  return out;
}

/** 단계 표시용 집계. 분류 규칙을 한 곳에 두기 위해 여기서 센다. */
export interface RenderProgress {
  total: number;
  failed: number;
  running: number;
  /** 사람 조치가 필요한 잡 수(실패 포함) */
  action: number;
}

export function renderProgress(jobs: QueueJob[]): RenderProgress {
  let failed = 0;
  let running = 0;
  let action = 0;
  for (const j of jobs) {
    const tab = classifyRenderJob(j);
    if (tab === "running") running += 1;
    if (tab === "action") {
      action += 1;
      if (j.status === "failed") failed += 1;
    }
  }
  return { total: jobs.length, failed, running, action };
}
