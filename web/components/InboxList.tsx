// 작업함 목록(2026-09-30 운영자 결정 2-1) — 논문·리포트 공용 서버 컴포넌트.
// 편마다 "지금 단계" 하나를 보여 주고, 위 칩(?stage=)으로 거른다. 정렬(?sort=)은 낙점일순·초안 생성순.
// 단계 판정은 lib/work/inbox.ts(순수·테스트), 묶기·정렬은 lib/work/../reviewSort.ts 가 한다.
import Link from "next/link";
import { dayLabelWithDate, seoulDateTimeLabel } from "@/lib/date";
import { groupForReview, type ReviewSort } from "@/lib/reviewSort";
import { INBOX_CHIPS, STAGE_META, chipCounts, inChip, type InboxChip, type InboxStage } from "@/lib/work/inbox";
import { HOLD_AFTER_DAYS } from "@/lib/work/backlog";

export interface InboxRow {
  id: string;
  title: string;
  sub?: string | null;
  href: string;
  decided_at: string | null;
  draft_created_at?: string | null;
  stage: InboxStage;
}

const TONE_CLASS: Record<string, string> = {
  bad: "stage-bad",
  warn: "stage-warn",
  blue: "stage-blue",
  ok: "stage-ok",
  muted: "stage-muted",
};

function hrefWith(base: string, stage: InboxChip, sort: ReviewSort): string {
  const q = new URLSearchParams();
  if (stage !== "todo") q.set("stage", stage);
  if (sort !== "decided") q.set("sort", sort);
  const s = q.toString();
  return s ? `${base}?${s}` : base;
}

export default function InboxList({
  base, rows, chip, sort, unit,
}: {
  base: string;
  rows: InboxRow[];
  chip: InboxChip;
  sort: ReviewSort;
  /** "편" | "건" */
  unit: string;
}) {
  const counts = chipCounts(rows.map((r) => r.stage));
  const shown = rows.filter((r) => inChip(r.stage, chip));
  const groups = groupForReview(shown, sort);

  return (
    <>
      <div className="inbox-chips" role="group" aria-label="단계로 거르기">
        {INBOX_CHIPS.map((c) => (
          <Link key={c.key} href={hrefWith(base, c.key, sort)} scroll={false}
            className={`chip${c.key === chip ? " chip-on" : ""}`}
            title={c.key === "hold" ? `낙점 뒤 ${HOLD_AFTER_DAYS}일이 지나도 초안이 없는 편 — 초안을 만들면 되살아납니다` : undefined}>
            {c.label} <b>{counts[c.key]}</b>
          </Link>
        ))}
      </div>
      <div className="toggle" role="group" aria-label="정렬">
        <Link href={hrefWith(base, chip, "decided")} data-active={sort === "decided"} scroll={false}>낙점일순</Link>
        <Link href={hrefWith(base, chip, "draft")} data-active={sort === "draft"} scroll={false}>초안 생성순</Link>
      </div>

      {shown.length === 0 ? (
        <p className="muted" style={{ marginTop: 24 }}>
          {chip === "todo" ? "지금 손댈 것이 없습니다." : "이 단계에 해당하는 것이 없습니다."}
        </p>
      ) : (
        groups.map((g) => (
          <div className="section" key={g.date ?? "none"}>
            <h3 className="group-header">
              {sort === "draft"
                ? (g.date ? `초안 ${dayLabelWithDate(g.date)}` : "초안 없음")
                : (g.date ? `낙점 ${dayLabelWithDate(g.date)}` : "날짜 미상")}{" "}
              <span className="muted">· {g.items.length}{unit}</span>
            </h3>
            {g.items.map((r) => {
              const m = STAGE_META[r.stage];
              return (
                <div className="list-row" key={r.id}>
                  <span style={{ minWidth: 0 }}>
                    <a href={r.href}>{r.title}</a>
                    {r.sub && <span className="muted"> · {r.sub}</span>}
                  </span>
                  <span className="list-row-meta">
                    {r.draft_created_at && (
                      <span className="muted" title="초안을 처음 생성한 시각 (한국 시간)">
                        초안 {seoulDateTimeLabel(r.draft_created_at)}
                      </span>
                    )}
                    <span className={`status-pill ${TONE_CLASS[m.tone]}`}>{m.label}</span>
                  </span>
                </div>
              );
            })}
          </div>
        ))
      )}
    </>
  );
}
