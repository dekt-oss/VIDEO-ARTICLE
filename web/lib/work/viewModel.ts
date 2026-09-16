// 여러 테이블의 상태 → WorkCounts 로 환산 (개선 지시서 T1-2 "통합 작업 ViewModel").
//
// DB 스키마는 바꾸지 않는다. 홈 화면이 이미 읽고 있는 데이터(후보·낙점·렌더잡·발행) + 지시서
// 상태맵만으로 "지금 무엇을 해야 하는가"를 계산한다.
//
// 단계 판정 사슬(기존 화면 흐름과 같다):
//   미결정 후보 → 낙점(초안 없음) → 초안 있음·대본 미승인 → 대본 승인·지시서 미승인 → 렌더
import type { DirectiveStatusMap } from "@/lib/queries";
import { classifyRenderJob, type QueueJob } from "@/lib/work/renderQueue";
import type { WorkCounts } from "@/lib/work/nextAction";

/** 공장 무관 최소 입력. 논문·리포트 어댑터가 각자 자기 타입에서 이 모양으로 줄인다. */
export interface WorkInput {
  /** 이번 배치 후보의 결정 상태(null = 미결정) */
  candidateDecisions: (string | null)[];
  /** 낙점된 편: 초안 유무 */
  picked: { paperId: string; hasDraft: boolean }[];
  /** 대본 승인(=published 기록)이 있는 편 id */
  approvedScriptIds: Set<string>;
  /** 편별 지시서 상태맵(getDirectiveStatusMap 결과) */
  directiveStatus: Map<string, DirectiveStatusMap>;
  /** 활성 렌더 잡(휴지통 제외) */
  renders: QueueJob[];
}

/** 지시서가 "사람 손을 떠난" 상태인가(승인 이후 단계). */
function directiveHandedOff(m: DirectiveStatusMap | undefined): boolean {
  if (!m) return false;
  return Object.values(m).some(
    (s) => s === "approved" || s === "rendering" || s === "rendered"
  );
}

export function workCounts(input: WorkInput): WorkCounts {
  const undecided = input.candidateDecisions.filter((d) => !d).length;

  let draftMissing = 0;
  let draftPending = 0;
  let directivePending = 0;
  for (const p of input.picked) {
    if (!p.hasDraft) {
      draftMissing += 1;
      continue;
    }
    if (!input.approvedScriptIds.has(p.paperId)) {
      draftPending += 1;
      continue;
    }
    // 대본까지 승인된 편 — 지시서 승인이 남았는가.
    if (!directiveHandedOff(input.directiveStatus.get(p.paperId))) directivePending += 1;
  }

  // 렌더는 renderQueue 분류를 재사용한다 — 화면 탭과 홈 카운트가 어긋나지 않게.
  let renderFailed = 0;
  let renderNeedsCheck = 0;
  for (const j of input.renders) {
    if (classifyRenderJob(j) !== "action") continue;
    if (j.status === "failed") renderFailed += 1;
    else renderNeedsCheck += 1;
  }

  return { renderFailed, renderNeedsCheck, directivePending, draftPending, draftMissing, undecided };
}
