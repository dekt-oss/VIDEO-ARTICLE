// 작업함 행 만들기 — 두 공장이 각자 읽은 데이터를 같은 규칙으로 InboxRow 로 바꾼다(결정 2-1).
// 단계 판정 자체는 lib/work/inbox.ts(순수·테스트)가 한다. 여기는 데이터를 그 입력 모양으로 줄이는 어댑터다.
import type { VersionType } from "@/lib/types";
import type { DirectiveMeta, DirectiveStatusMap } from "@/lib/queries";
import type { InboxRow } from "@/components/InboxList";
import { inboxStage, renderStateOf } from "@/lib/work/inbox";
import { isOnHold, isStalled } from "@/lib/work/backlog";
import { isOutdatedEngine } from "@/lib/work/decision";

export interface InboxSource {
  id: string;
  title: string;
  sub?: string | null;
  href: string;
  hasDraft: boolean;
  requestStatus: string | null;
  decidedAt: string | null;
  draftCreatedAt?: string | null;
}

type RenderLike = { status: string; youtube_status?: string | null; created_at?: string | null; saved_at?: string | null };

export function buildInboxRows(
  items: InboxSource[],
  offered: VersionType[],
  statusMap: Map<string, DirectiveStatusMap>,
  metaMap: Map<string, Partial<Record<VersionType, DirectiveMeta>>>,
  jobsById: Map<string, RenderLike[]>,
  now: Date = new Date(),
): InboxRow[] {
  return items.map((it) => {
    const st = statusMap.get(it.id) ?? {};
    // 지금 발주하는 버전 중 지시서가 있는 첫 버전을 본다(쉬는 버전은 보지 않는다).
    const v = offered.find((k) => st[k]);
    const meta = v ? metaMap.get(it.id)?.[v] : undefined;
    const directive = v ? { status: String(st[v]), outdated: isOutdatedEngine(meta?.engine ?? null) } : null;
    const stage = inboxStage({
      hasDraft: it.hasDraft,
      requestStatus: it.requestStatus,
      onHold: isOnHold({ hasDraft: it.hasDraft, decidedAt: it.decidedAt }, now),
      // 마지막 산출물(최신 지시서, 없으면 초안) 뒤로 14일 멈췄나 — 결정 3-1 을 지시서까지.
      stalled: it.hasDraft && isStalled(meta?.createdAt ?? it.draftCreatedAt ?? null, now),
      directive,
      render: renderStateOf(jobsById.get(it.id) ?? []),
    });
    return {
      id: it.id, title: it.title, sub: it.sub ?? null, href: it.href,
      decided_at: it.decidedAt, draft_created_at: it.draftCreatedAt ?? null, stage,
    };
  });
}

/** 렌더 잡 목록 → 편 id 별 묶음. `idOf` 는 잡에서 편 id 를 꺼낸다(논문 paper_id · 리포트 report_id). */
export function groupJobs<T extends RenderLike>(jobs: T[], idOf: (j: T) => string | undefined): Map<string, T[]> {
  const m = new Map<string, T[]>();
  for (const j of jobs) {
    const id = idOf(j);
    if (!id) continue;
    const arr = m.get(id) ?? [];
    arr.push(j);
    m.set(id, arr);
  }
  return m;
}

/** 편마다 "마지막 산출물" 시각 — 지금 발주하는 버전의 최신 지시서, 없으면 초안. 홈 카운트의 보류 판정에 쓴다. */
export function lastMadeAt(
  id: string,
  draftCreatedAt: string | null | undefined,
  offered: VersionType[],
  metaMap: Map<string, Partial<Record<VersionType, DirectiveMeta>>>,
): string | null {
  const m = metaMap.get(id) ?? {};
  const times = offered.map((v) => m[v]?.createdAt).filter((t): t is string => !!t).sort();
  return times.at(-1) ?? draftCreatedAt ?? null;
}
