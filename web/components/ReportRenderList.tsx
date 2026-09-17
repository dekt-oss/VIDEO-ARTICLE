"use client";

// ⑥ 리포트 렌더 결과. 논문 RenderList 미러(경량) — 유튜브/캡션 복사 블록 제외.
// 종목별 그룹 · 상태 필터 · mp4 미리보기 · 저장/휴지통 · 지금 렌더.
import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { ReportRenderJob } from "@/lib/reportTypes";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import { dayLabelWithDate, seoulDateOf } from "@/lib/date";
import { apiErrorText } from "@/lib/apiError";
import ErrorDisclosure from "@/components/ErrorDisclosure";
import { parseRenderError } from "@/lib/renderError";
import { RENDER_TABS, classifyRenderJob, countByTab, type RenderTab } from "@/lib/work/renderQueue";
import AsyncJobStatus from "@/components/AsyncJobStatus";
import { useJobPolling } from "@/lib/useJobPolling";
import { RENDER_STATUS_AWAITING_HUMAN } from "@/lib/renderStatus";

const STATUS_LABEL: Record<string, string> = {
  queued: "대기", assets: "에셋 생성", tts: "나레이션 TTS", assembling: "조립", qa_pending: "확인 필요", degraded: "승인 필요", done: "완료", failed: "실패",
};


interface Group {
  reportId: string;
  title: string;
  titleKo: string | null;
  jobs: ReportRenderJob[];
  latest: string;
  doneCount: number;
  cost: number;
}

// 탭 판정·주요행동은 lib/work/renderQueue.ts 를 쓴다(논문 공장과 같은 규칙 — RENDER-02).

export default function ReportRenderList({ jobs }: { jobs: ReportRenderJob[] }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  // ASYNC-01: 진행 중 잡이 있을 때만 자동 갱신(전부 끝나면 폴링 중단).
  const activeCount = jobs.filter((j) => j.status !== "done" && j.status !== "failed").length;
  const { polling, lastCheckedAt } = useJobPolling(activeCount);
  // RENDER-02: 조치 필요 → 진행 중 → 완료 → 보관. 기본은 조치 필요.
  const [tab, setTab] = useState<RenderTab>("action");
  const tabCounts = useMemo(() => countByTab(jobs), [jobs]);
  const [trashTarget, setTrashTarget] = useState<ReportRenderJob | null>(null);
  // degraded 승인은 되돌리기 어렵다(발행이 열린다) — 집 관례대로 ConfirmModal 을 거친다.
  const [approveTarget, setApproveTarget] = useState<ReportRenderJob | null>(null);

  const groups = useMemo<Group[]>(() => {
    const filtered = jobs.filter((j) => classifyRenderJob(j) === tab);
    const by = new Map<string, Group>();
    for (const j of filtered) {
      const key = j.report_id ?? j.directive_id ?? j.id;
      let g = by.get(key);
      if (!g) {
        g = { reportId: key, title: j.title ?? "(제목 없음)", titleKo: j.title_ko ?? null,
              jobs: [], latest: j.created_at, doneCount: 0, cost: 0 };
        by.set(key, g);
      }
      g.jobs.push(j);
      if (j.created_at > g.latest) g.latest = j.created_at;
      if (j.status === "done") g.doneCount += 1;
      g.cost += Number(j.cost_estimate ?? 0);
    }
    return [...by.values()].sort((a, b) => b.latest.localeCompare(a.latest));
  }, [jobs, tab]);

  const dateGroups = useMemo(() => {
    const out: { date: string; items: Group[] }[] = [];
    const idx = new Map<string, number>();
    for (const g of groups) {
      const key = seoulDateOf(g.latest) ?? "__none__";
      if (!idx.has(key)) { idx.set(key, out.length); out.push({ date: key, items: [] }); }
      out[idx.get(key)!].items.push(g);
    }
    return out;
  }, [groups]);

  async function kickRender() {
    setBusy("__trigger__");
    const res = await fetch("/api/report-render-trigger", { method: "POST" });
    setBusy(null);
    if (res.ok) toast.show("렌더 워커를 시작했습니다. 진행 상황은 이 화면에서 자동으로 갱신됩니다.", "ok");
    else toast.show("렌더 트리거 실패", "err");
  }

  async function manage(
    jobId: string,
    action: "save" | "unsave" | "trash" | "approve_degraded",
  ) {
    setBusy(jobId);
    const res = await fetch("/api/report-render-manage", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show(
        action === "save" ? "보관함에 저장했습니다."
          : action === "unsave" ? "보관 해제."
            : action === "approve_degraded" ? "승인했습니다 — 이제 업로드할 수 있습니다."
              : "휴지통으로 이동.", "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "보관·휴지통 상태를 저장"), "err");
    }
  }

  // 재렌더 — /api/report-render-retry. 실패 카드에서 원인을 확인한 뒤 다시 돌린다.
  async function retryRender(jobId: string) {
    setBusy(jobId);
    const res = await fetch("/api/report-render-retry", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show(
        e?.status === "already_queued"
          ? "이미 같은 언어의 렌더가 대기 중입니다 — 새로 넣지 않았습니다."
          : "재렌더 큐에 적재했습니다. 진행 상황은 이 화면에서 자동으로 갱신됩니다.",
        "ok"
      );
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "재렌더를 요청"), "err");
    }
  }

  // 유튜브 업로드 — /api/report-youtube-upload. 리포트는 별도 금융 채널(KO)로 큐 적재 + 워커 트리거.
  async function uploadYoutube(jobId: string) {
    setBusy(jobId);
    const res = await fetch("/api/report-youtube-upload", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show("유튜브 업로드 큐에 적재했습니다(비공개). 상태는 자동으로 갱신됩니다.", "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "유튜브 업로드를 요청"), "err");
    }
  }

  if (jobs.length === 0) {
    return (
      <p className="empty">
        렌더 잡이 없습니다. <Link href="/finance/review">④ 초안 검수</Link>에서 지시서를 만들어 승인하면 여기 나타납니다.
      </p>
    );
  }

  return (
    <>
      <div className="controls">
        <div className="toggle" aria-label="렌더 작업 분류">
          {RENDER_TABS.map((t) => (
            <button key={t.key} data-active={tab === t.key} onClick={() => setTab(t.key)}>
              {t.label} {tabCounts[t.key]}
            </button>
          ))}
        </div>
        <span className="muted">{groups.length}건 · 렌더 {groups.reduce((n, g) => n + g.jobs.length, 0)}개</span>
        <button className="btn" disabled={busy === "__trigger__"} onClick={kickRender}>지금 렌더</button>
      </div>

      {groups.length === 0 && (
        <p className="muted">
          {tab === "action"
            ? "조치할 렌더가 없습니다. 진행 중·완료 탭을 확인하세요."
            : "이 분류에 렌더가 없습니다."}
        </p>
      )}

      {dateGroups.map((dg) => (
        <div key={dg.date}>
          <h3 className="group-header" style={{ marginTop: 18 }}>
            {dg.date === "__none__" ? "날짜 미상" : dayLabelWithDate(dg.date)} <span className="muted">· {dg.items.length}건</span>
          </h3>
          {dg.items.map((g) => (
            <details className="render-group" key={g.reportId}>
              <summary className="group-header">
                <span><b>{g.titleKo || g.title}</b></span>
                <span className="muted"> · 완료 {g.doneCount}/{g.jobs.length}{g.cost ? ` · $${g.cost.toFixed(3)}` : ""}</span>
              </summary>
              <div className="render-versions">
                {g.jobs.map((j) => {
                  const done = j.status === "done";
                  const failed = j.status === "failed";
                  // ★ RenderList 와 같은 이유 — degraded 는 영상이 있으므로 보여야 한다.
                  const rendered =
                    done || RENDER_STATUS_AWAITING_HUMAN.includes(j.status as never);
                  // 중요 요소가 빠진 채 렌더된 영상 — 사람이 보고 승인해야 발행할 수 있다(§8-3).
                  const needsApproval = j.status === "degraded" && !j.degraded_approved_at;
                  const saved = !!j.saved_at;
                  return (
                    <div className={failed ? "scene flagged" : "scene"} key={j.id}>
                      <div className="meta">
                        <span className="pill">{(j.lang ?? "ko") === "en" ? "🇬🇧 EN" : "🇰🇷 KO"}</span>{" "}
                        · {STATUS_LABEL[j.status] ?? j.status} · {j.progress}%
                        {j.cost_estimate ? ` · $${Number(j.cost_estimate).toFixed(3)}` : ""}
                        {saved && <span className="pill badge-saved" style={{ marginLeft: 6 }}>★ 보관</span>}
                      </div>
                      {!rendered && !failed && (
                        <AsyncJobStatus
                          stageLabel={STATUS_LABEL[j.status] ?? j.status}
                          startedAt={j.created_at}
                          autoRefresh={polling}
                          lastCheckedAt={lastCheckedAt}
                        />
                      )}
                      {failed && <ErrorDisclosure log={j.error_log} />}
                      {rendered && j.output_url && (
                        <video src={j.output_url} controls style={{ maxWidth: 240, marginTop: 8, borderRadius: 6 }} />
                      )}

                      {done && j.youtube_status && (
                        <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                          {j.youtube_status === "done" && j.youtube_url ? (
                            <>
                              ▶️ 유튜브 업로드됨(비공개) —{" "}
                              <a href={j.youtube_url} target="_blank" rel="noreferrer">{j.youtube_url}</a>
                            </>
                          ) : j.youtube_status === "error" ? (
                            <span className="unsupported">유튜브 업로드 실패: {j.youtube_error ?? "원인 미상"}</span>
                          ) : (
                            <>⏳ 유튜브 업로드 {j.youtube_status === "processing" ? "진행 중" : "대기"}… (자동 확인 중)</>
                          )}
                        </div>
                      )}

                      <div className="actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
                        {/* 실패 카드의 유일한 회복 수단 — 논문 라인과 같이 항상 보이고,
                            재시도로 안 풀릴 분류면 강조만 낮춘다(숨기지 않는다). */}
                        {failed && (
                          <button
                            className={parseRenderError(j.error_log).retryable ? "btn pick" : "btn btn-quiet"}
                            disabled={busy === j.id}
                            onClick={() => retryRender(j.id)}
                            title={parseRenderError(j.error_log).action}
                          >
                            ↻ 재렌더
                          </button>
                        )}
                        {needsApproval && (
                          <button
                            className="btn pick"
                            disabled={busy === j.id}
                            onClick={() => setApproveTarget(j)}
                            title="중요 요소가 빠진 영상입니다 — 확인 후 승인해야 업로드할 수 있습니다"
                          >
                            확인하고 승인
                          </button>
                        )}
                        {done && (
                          <button className="btn" disabled={busy === j.id} onClick={() => manage(j.id, saved ? "unsave" : "save")}>
                            {saved ? "보관 해제" : "★ 저장"}
                          </button>
                        )}
                        {done && (!j.youtube_status || j.youtube_status === "error") && (
                          <button
                            className="btn pick"
                            disabled={busy === j.id || !j.output_url}
                            onClick={() => uploadYoutube(j.id)}
                            title="금융 채널에 비공개로 업로드"
                          >
                            ▶️ 유튜브 업로드{j.youtube_status === "error" ? "(재시도)" : ""}
                          </button>
                        )}
                        <button className="btn reject" disabled={busy === j.id} onClick={() => setTrashTarget(j)}>삭제</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </details>
          ))}
        </div>
      ))}

      <ConfirmModal
        open={!!approveTarget}
        title="결함이 있는 영상을 승인"
        message={
          "중요 요소가 빠진 채 렌더된 영상입니다. 영상을 확인했고 이대로 발행해도 된다면 승인하세요. " +
          "승인해도 '결함이 있었다'는 기록은 남습니다."
        }
        confirmLabel="확인했습니다 — 승인"
        busy={!!approveTarget && busy === approveTarget.id}
        onCancel={() => setApproveTarget(null)}
        onConfirm={() => {
          if (approveTarget) {
            const id = approveTarget.id;
            setApproveTarget(null);
            manage(id, "approve_degraded");
          }
        }}
      />

      <ConfirmModal
        open={!!trashTarget} title="렌더를 휴지통으로 이동"
        message="이 렌더를 휴지통으로 옮깁니다. 목록에서 사라지지만 휴지통에서 복원할 수 있습니다."
        confirmLabel="휴지통으로 이동" danger
        busy={!!trashTarget && busy === trashTarget.id}
        onCancel={() => setTrashTarget(null)}
        onConfirm={() => { if (trashTarget) { const id = trashTarget.id; setTrashTarget(null); manage(id, "trash"); } }}
      />
    </>
  );
}
