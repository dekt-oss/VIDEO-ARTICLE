// ④⑤⑥ 단계 네비게이션 (개선 지시서 FLOW-01 / §6-2).
//
// 이전에는 ④ 초안 검수와 ⑤ 지시서가 한 페이지에 세로로 이어붙어 있어, 씬 수·컷 수에 비례해
// 페이지가 길어지고 "지금 눌러야 하는 버튼"이 화면 밖으로 사라졌다. 같은 URL 을 유지하면서
// `?step=` 으로 현재 단계만 렌더하고, 이전 단계는 링크로 언제든 되돌아가 근거를 재확인한다.
//
// 서버 컴포넌트다 — 상태가 없고 링크만 있다(클라이언트 번들을 늘리지 않는다).
import Link from "next/link";

export type StepNo = 4 | 5 | 6;

export interface StepState {
  no: StepNo;
  label: string;
  /** 한 줄 상태. 예: "검수 필요", "✓ 승인됨", "렌더 2건 진행 중" */
  status: string;
  /** 이 단계가 끝났는가(체크 표시) */
  done: boolean;
  /** 사람이 지금 손대야 하는 단계인가(강조) */
  needsWork: boolean;
  /** 아직 들어갈 수 없는 단계인가(선행 단계 미완) */
  locked?: boolean;
  /**
   * 이 단계로 가는 경로. 생략하면 `${basePath}?step=${no}`.
   * 리포트 공장은 ⑤·⑥ 이 별 화면이라 여기에 실제 경로를 넣는다(같은 stepper 를 공유).
   */
  href?: string;
}

export default function StageStepper({
  steps,
  current,
  basePath,
  /** 차단·경고·근거없음 요약(단계 공통). 없으면 표시하지 않는다. */
  summary,
}: {
  steps: StepState[];
  current: StepNo;
  /** `?step=` 을 붙일 경로. 예: `/review/<id>` */
  basePath: string;
  summary?: string | null;
}) {
  return (
    <nav className="stepper" aria-label="작업 단계">
      <ol>
        {steps.map((s, i) => {
          const active = s.no === current;
          // ★ 화면에 보이는 번호는 **순서**다(2026-09-17). `no` 는 주소(?step=)용 값이라
          //   단계를 합친 뒤에도 5·6 으로 남아 있는데, 그걸 그대로 찍으면 "①②가 어디 갔지"가 된다.
          const shown = i + 1;
          const cls = [
            "step",
            active ? "active" : "",
            s.done ? "done" : "",
            s.needsWork ? "needs" : "",
            s.locked ? "locked" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const body = (
            <>
              <span className="step-no" aria-hidden="true">
                {s.done ? "✓" : shown}
              </span>
              <span className="step-text">
                <span className="step-label">{s.label}</span>
                <span className="step-status">{s.status}</span>
              </span>
            </>
          );
          // 잠긴 단계는 링크로 만들지 않는다 — 눌러도 할 게 없는 곳으로 보내지 않는다.
          return (
            <li key={s.no} className={cls} aria-current={active ? "step" : undefined}>
              {s.locked || active ? (
                <span className="step-inner">{body}</span>
              ) : (
                <Link className="step-inner" href={s.href ?? `${basePath}?step=${s.no}`}>
                  {body}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
      {summary && <div className="stepper-summary">{summary}</div>}
    </nav>
  );
}
