// "지금 무엇을 해야 하는가" 판정 (개선 지시서 §5-3 / HOME-01).
//
// 화면마다 목록을 보여주는 것과, 다음 행동 하나를 지목하는 것은 다르다. 이 파일은 후자를 담당한다.
// 순수 함수 — DB·React 를 모른다(테스트: lib/work/nextAction.test.ts).
//
// 상태 enum(지시서 §5-1)을 DB 에 새로 만들지 않는다. 기존 여러 테이블에서 이미 읽고 있는
// 값들(decisions·drafts·published·directives·render_jobs)을 카운트로 환산해 넘긴다.

export type NextAction =
  | "retry_render" // 렌더 실패 → 재렌더
  | "check_render" // 렌더 완료·미조치 → 결과 확인/업로드
  | "review_directive" // 지시서 초안 있음·미승인 → 지시서 검수
  | "review_draft" // 대본 초안 있음·미승인 → 대본 검수
  | "generate_draft" // 낙점됐지만 초안 없음 → 초안 생성
  | "decide" // 미결정 후보 → 후보 결정
  | "none"; // 오늘 처리할 것 없음

export interface WorkCounts {
  /** 렌더 실패 잡 수 */
  renderFailed: number;
  /** 렌더 완료됐지만 확인·업로드가 남은 잡 수 */
  renderNeedsCheck: number;
  /** 초안은 있고 지시서 승인이 남은 편 수 */
  directivePending: number;
  /** 초안은 있고 대본 승인이 남은 편 수 */
  draftPending: number;
  /** 낙점됐지만 초안이 없는 편 수 */
  draftMissing: number;
  /** 아직 결정하지 않은 후보 수 */
  undecided: number;
}

export interface NextStep {
  action: NextAction;
  /** 버튼 라벨 — 클릭하면 할 일이 무엇인지 */
  cta: string;
  /** 무슨 상태인지 한 줄 */
  headline: string;
  /** 해당 화면 경로 */
  href: string;
  /** 그 상태에 걸린 건수 */
  count: number;
}

/** 공장별 경로. 논문=루트, 리포트=/finance 접두. */
export interface WorkHrefs {
  home: string;
  review: string;
  directive: string;
  render: string;
}

export const PAPER_HREFS: WorkHrefs = {
  home: "/",
  review: "/review",
  directive: "/directive",
  render: "/render",
};

export const FINANCE_HREFS: WorkHrefs = {
  home: "/finance",
  review: "/finance/review",
  directive: "/finance/directive",
  render: "/finance/render",
};

/** 렌더 큐에서 오는 작업 2종. 홈에서 감출 때 한 덩어리로 쓴다. */
export const RENDER_ACTIONS: NextAction[] = ["retry_render", "check_render"];

/**
 * 홈("오늘의 작업")이 감추는 작업.
 *
 * ★ 2026-08-20 운영자 요청 — 홈은 "오늘 올라온 후보를 걸러내는 화면"이다. 그런데 렌더 큐에
 *   실패·미확인 잡이 하나라도 쌓이면 우선순위 규칙상 그것이 항상 맨 위를 차지해서, 홈을 열
 *   때마다 "렌더 실패 N건" 배너가 선별 작업을 가렸다. 렌더 큐는 요약 타일
 *   [렌더·업로드 필요] 와 ⑥ 화면이 이미 담당한다 — 홈 카드에서만 뺀다(카운트는 그대로).
 *   되돌리려면 홈 page.tsx 의 `HOME_SKIP` 인자를 지우면 된다.
 */
export const HOME_SKIP: NextAction[] = RENDER_ACTIONS;

/**
 * 우선순위는 지시서 §5-3 순서를 그대로 따른다. 앞선 것이 하나라도 있으면 그것이 "다음 작업"이다.
 * 실패를 맨 위에 두는 이유: 방치하면 그날 편이 나가지 않는다(막힌 것이 먼저).
 *
 * `skip` 에 든 종류는 건너뛴다 — 화면마다 "여기서 다룰 작업"이 다르다(홈=선별).
 */
export function nextStep(
  c: WorkCounts,
  hrefs: WorkHrefs = PAPER_HREFS,
  skip: NextAction[] = [],
): NextStep {
  const skipped = new Set(skip);
  if (c.renderFailed > 0 && !skipped.has("retry_render")) {
    return {
      action: "retry_render",
      cta: "실패 확인하기",
      headline: `렌더 실패 ${c.renderFailed}건 — 원인을 확인하고 재렌더하세요`,
      href: hrefs.render,
      count: c.renderFailed,
    };
  }
  if (c.renderNeedsCheck > 0 && !skipped.has("check_render")) {
    return {
      action: "check_render",
      cta: "렌더 결과 확인",
      headline: `완성된 영상 ${c.renderNeedsCheck}건 — 확인하고 업로드하세요`,
      href: hrefs.render,
      count: c.renderNeedsCheck,
    };
  }
  if (c.directivePending > 0 && !skipped.has("review_directive")) {
    return {
      action: "review_directive",
      cta: "지시서 검수 시작",
      headline: `승인 대기 중인 영상 지시서 ${c.directivePending}편`,
      href: hrefs.directive,
      count: c.directivePending,
    };
  }
  if (c.draftPending > 0 && !skipped.has("review_draft")) {
    return {
      action: "review_draft",
      cta: "초안 검수 시작",
      headline: `검수 대기 중인 초안 ${c.draftPending}편`,
      href: hrefs.review,
      count: c.draftPending,
    };
  }
  if (c.draftMissing > 0 && !skipped.has("generate_draft")) {
    return {
      action: "generate_draft",
      cta: "초안 생성하기",
      headline: `낙점했지만 초안이 없는 편 ${c.draftMissing}편`,
      href: hrefs.review,
      count: c.draftMissing,
    };
  }
  if (c.undecided > 0 && !skipped.has("decide")) {
    return {
      action: "decide",
      cta: "후보 검토 시작",
      headline: `미결정 후보 ${c.undecided}편`,
      href: hrefs.home,
      count: c.undecided,
    };
  }
  return {
    action: "none",
    cta: "",
    headline: "오늘 처리할 작업이 없습니다.",
    href: hrefs.home,
    count: 0,
  };
}

/** 홈 요약 타일 3개(지시서 §6-1: 5개 → 3개). 발행 누계는 홈에서 빼고 보관함·성과로 보낸다. */
export interface WorkSummaryCounts {
  undecided: number;
  reviewNeeded: number; // 초안 생성 + 대본 승인 + 지시서 승인 대기 = 사람이 판단할 것
  renderNeeded: number; // 렌더 실패 + 확인·업로드 대기
}

export function summarize(c: WorkCounts): WorkSummaryCounts {
  return {
    undecided: c.undecided,
    reviewNeeded: c.draftMissing + c.draftPending + c.directivePending,
    renderNeeded: c.renderFailed + c.renderNeedsCheck,
  };
}
