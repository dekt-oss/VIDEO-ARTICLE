// 홈 최상단 "다음 작업" 카드 (개선 지시서 HOME-01 / §6-1).
// 접속 후 3초 안에 "오늘 할 일이 있는가 · 가장 먼저 처리할 것은 무엇인가 · 몇 건인가"에 답한다.
// 기존 홈은 요약 타일 5개·날짜 네비·필터 3줄을 먼저 보여줘 후보 카드가 첫 화면 밖으로 밀렸다.
import type { NextStep } from "@/lib/work/nextAction";

export default function NextActionCard({
  step,
  /** 배치일 안내(오래된 미확인 일자) — 후보 결정 단계에서만 의미가 있다. */
  batchNote,
}: {
  step: NextStep;
  batchNote?: string | null;
}) {
  const done = step.action === "none";
  return (
    <section className={done ? "next-action done" : "next-action"} aria-label="다음 작업">
      <div className="next-action-body">
        <div className="next-action-kicker">{done ? "오늘 작업 완료" : "다음 작업"}</div>
        <div className="next-action-headline">
          {done ? "처리할 작업이 없습니다. 수집·채점이 돌면 새 후보가 올라옵니다." : step.headline}
        </div>
        {batchNote && !done && <div className="muted">{batchNote}</div>}
      </div>
      {!done && (
        <a className="btn pick next-action-cta" href={step.href}>
          {step.cta} →
        </a>
      )}
    </section>
  );
}
