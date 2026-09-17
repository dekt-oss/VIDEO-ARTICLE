// ④⑤⑥ 단계 상태 판정 (개선 지시서 FLOW-01). 논문·리포트 공장이 **같은 규칙**을 쓴다.
//
// 두 공장 모두 한 라우트의 `?step=` 으로 단계를 쪼갠다(리포트도 2026-08-19 부터 통합).
// 판정도 화면 구조도 같다 — 두 공장의 단계 표시가 어긋나지 않게(지시서 금지사항 9).
//
// 순수 함수 — 테스트: lib/work/steps.test.ts
import type { StepState, StepNo } from "@/components/StageStepper";
import type { DirectiveStatusMap } from "@/lib/queries";
import type { RenderProgress } from "@/lib/work/renderQueue";

const DIRECTIVE_LABEL: Record<string, string> = {
  draft: "검수 필요",
  approved: "✓ 승인 · 렌더 대기",
  rendering: "렌더 진행 중",
  rendered: "✓ 렌더 완료",
  failed: "렌더 실패",
};

/** 버전이 여러 개일 때 가장 진행된 상태 하나. */
export function mostAdvanced(m: DirectiveStatusMap): string | null {
  const order = ["rendered", "rendering", "approved", "failed", "draft"];
  const values = Object.values(m) as string[];
  return order.find((s) => values.includes(s)) ?? null;
}

/** 지시서가 사람 손을 떠났는가(승인 이후). */
export function directiveHandedOff(m: DirectiveStatusMap): boolean {
  const s = mostAdvanced(m);
  return s === "approved" || s === "rendering" || s === "rendered";
}

export interface StageInput {
  hasDraft: boolean;
  /** 대본 승인(=published 기록) 여부 */
  scriptApproved: boolean;
  directiveStatus: DirectiveStatusMap;
  /** 이 콘텐츠의 렌더 진행 상황 — renderQueue.renderProgress(jobs) 로 만든다. */
  render: RenderProgress;
  /** 단계별 경로. 생략하면 stepper 가 `?step=N` 을 만든다. */
  hrefFor?: (no: StepNo) => string | undefined;
}

export interface StageResult {
  steps: StepState[];
  /** 손댈 것이 있는 가장 앞선 단계(없으면 마지막으로 진행된 단계) */
  defaultStep: StepNo;
}

export function buildStages(input: StageInput): StageResult {
  // scriptApproved 는 합친 뒤 단계 판정에 안 쓴다 — 대본 확정은 승인 버튼이 함께 처리한다.
  const { hasDraft, directiveStatus, render, hrefFor } = input;
  const href = (no: StepNo) => hrefFor?.(no);

  const dStatus = mostAdvanced(directiveStatus);
  const handedOff = directiveHandedOff(directiveStatus);

  const { total, failed, running, action } = render;

  // ★ ④ 초안 검수와 ⑤ 영상 지시서를 **한 단계로 합쳤다**(2026-09-17 운영자 지시:
  //   "번호 순서인 초안생성이랑 영상지시서 따로 구분 필요 있겠나? 통합해").
  //   화면이 이미 한 장이고(SequenceEditor) 발주도 한 번에 나가는데, 머리에만 두 칸이
  //   남아 있어 "지금 어느 단계인가"를 쓸데없이 묻게 만들었다.
  // ★ `no` 는 5 로 둔다 — 옛 주소 `?step=4` 와 `?step=5` 가 둘 다 이 단계로 들어온다.
  const work: StepState = {
    no: 5,
    label: "영상 지시서",
    status: !hasDraft
      ? "아직 없음"
      : dStatus
        ? DIRECTIVE_LABEL[dStatus] ?? dStatus
        : "지시서 만드는 중",
    done: handedOff,
    needsWork: !hasDraft || !handedOff,
    href: href(5),
  };

  const step6: StepState = {
    no: 6,
    label: "렌더 결과",
    status:
      total === 0
        ? "렌더 없음"
        : failed > 0
          ? `실패 ${failed}건`
          : running > 0
            ? `진행 중 ${running}건`
            : action > 0
              ? `확인 필요 ${action}건`
              : `완료 ${total}건`,
    done: total > 0 && failed === 0 && running === 0 && action === 0,
    needsWork: failed > 0 || action > 0,
    locked: total === 0 && !handedOff,
    href: href(6),
  };

  const steps = [work, step6];
  const firstNeeds = steps.find((s) => s.needsWork && !s.locked);
  const defaultStep = (firstNeeds?.no ?? (step6.locked ? 5 : 6)) as StepNo;
  return { steps, defaultStep };
}

/**
 * 리포트 공장 — 논문과 같은 한 라우트 안에서 `?step=` 으로 단계를 바꾼다.
 *
 * 예전에는 ⑤ 가 /finance/directive/[id], ⑥ 이 /finance/render 로 흩어져 있어 단계를 옮길
 * 때마다 화면(과 문맥)이 갈아엎어졌다. 이제 셋 다 /finance/review/[id]?step= 이다.
 */
export function reportStages(reportId: string, input: Omit<StageInput, "hrefFor">): StageResult {
  return buildStages({
    ...input,
    hrefFor: (no) => `/finance/review/${reportId}?step=${no}`,
  });
}
