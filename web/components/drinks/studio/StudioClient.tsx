"use client";

// 콘텐츠 스튜디오 — 운영자 확정 목업(sooljjerigo-simple-studio, 2026-11-07)의 3단계: ① 소재 고르기 ② 초안 다듬기 ③ 버전·생성.
// ★ 화면은 서버 상태(drinks_studio_status)만 보여 준다. 진행률·비용·완료 표시를 지어내지 않는다.
// ★ 편집은 서버에 저장한다(studio_save_draft). 저장 전/저장 중/저장됨/실패를 나눠 보이고, 실패를 저장됨으로 표시하지 않는다.
// ★ 준비·생성 중에만 몇 초마다 새로 읽는다(router.refresh). 편집 중에는 새로 읽지 않아 입력이 사라지지 않는다.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  cardCost, cardPlan, draftFromPlan, draftProblem, isPhotoPlan, orderTotal, progressText, sameDraft, studioPhase, versionOptions,
  type DraftEdit, type StudioScreen, type StudioStatus, type VersionId,
} from "@/lib/drinks/studio";

export interface StudioCollectItem {
  key: string; topicId: string | null; candidateId: string | null; title: string; question: string; kind: string; origin: string;
  angle: string | null; inProgress: boolean; payload: Record<string, unknown>;
  /** 설명형(영상) 초안만 있는 소재 — 이어 만들기는 작업공간이다. */
  videoDraft?: boolean;
}
export interface StudioResultFile {
  role: string; position: number; mime: string; url: string | null; urlError: string | null; width: number | null; height: number | null;
  jobId: string; reviewStatus: string | null; qa: boolean | null;
}

type Post = { ok: boolean; status: number; result?: Record<string, unknown>; error?: string; code?: string; detail?: unknown; dispatch?: { triggered: boolean } };
async function post(action: string, payload: Record<string, unknown>): Promise<Post> {
  try {
    const res = await fetch("/api/drinks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, payload }) });
    const body = await res.json().catch(() => null);
    return { ok: res.ok, status: res.status, result: body?.result, error: body?.error, code: body?.code, detail: body?.detail, dispatch: body?.dispatch };
  } catch {
    return { ok: false, status: 0, error: "네트워크에 연결하지 못했어요. 잠시 후 다시 시도하세요.", code: "network" };
  }
}

const STEPS: { id: "collect" | "draft" | "versions"; label: string }[] = [
  { id: "collect", label: "소재 고르기" }, { id: "draft", label: "초안 다듬기" }, { id: "versions", label: "버전·생성" },
];
const LOGICAL: Record<StudioScreen, "collect" | "draft" | "versions"> = {
  collect: "collect", preparing: "collect", blocked: "collect", choice: "collect", draft: "draft", versions: "versions", generating: "versions", result: "versions",
};
const POLL_MS = 5000;

export default function StudioClient({ items, problems, status, statusProblem, files, resultProblem, selectedTopicId, summary, header, footer }: {
  items: StudioCollectItem[]; problems: string[]; status: StudioStatus | null; statusProblem: string | null;
  files: StudioResultFile[]; resultProblem: string | null; selectedTopicId: string | null;
  /** 목록 머리 설명 · ① 화면 위·아래에 붙는 서버 칸(탭·한도, 손으로 넣기) */
  summary?: string; header?: ReactNode; footer?: ReactNode;
}) {
  const router = useRouter();
  const phase = studioPhase(status);
  const plan = cardPlan(status);
  // 사람이 고른 화면(뒤로 가기·버전 고르기). 서버 단계가 바뀌면 서버 단계를 따른다.
  const [override, setOverride] = useState<StudioScreen | null>(null);
  const [selKey, setSelKey] = useState<string | null>(() => (selectedTopicId ? items.find((i) => i.topicId === selectedTopicId)?.key : null) ?? items[0]?.key ?? null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<VersionId[]>(["card"]);
  // 초안 화면이 마지막으로 저장한 버전·숫자 검사(자동 저장은 화면을 새로 읽지 않으므로 여기로 올린다).
  // 뒤로 갔다 와도 방금 저장한 글이 보이도록 저장본을 여기 둔다(서버 props 는 다음 새로 읽기 전까지 옛 값이다).
  const [saved, setSaved] = useState<{ planId: string; version: number; nums: string[]; edit: DraftEdit } | null>(null);
  const livePlan = plan && saved && saved.planId === plan.plan_revision_id && saved.version > plan.version
    ? { ...plan, version: saved.version, unverified_numbers: saved.nums,
        plan_json: { ...plan.plan_json, pages: (plan.plan_json.pages ?? []).map((pg, i) => ({ ...pg, heading: saved.edit.pages[i]?.heading ?? pg.heading,
          body: saved.edit.pages[i]?.body || null })), reel: { hook_title: saved.edit.hook_title, share_line: saved.edit.share_line } } }
    : plan;
  useEffect(() => setOverride(null), [phase.screen, status?.topic.id]);
  const screen: StudioScreen = override ?? (selectedTopicId ? phase.screen : "collect");

  // 준비·생성 중에만 새로 읽는다(서버 상태가 정본 — 창을 닫았다 열어도 같은 상태).
  useEffect(() => {
    if (screen !== "preparing" && screen !== "generating") return;
    const t = window.setInterval(() => router.refresh(), POLL_MS);
    return () => window.clearInterval(t);
  }, [screen, router]);

  const go = (topicId: string | null) => router.push(topicId ? `/drinks/studio?topic=${topicId}` : "/drinks/studio");
  const sel = items.find((i) => i.key === selKey) ?? null;

  const prepare = async (item: StudioCollectItem) => {
    setBusy(true); setMsg(null);
    const r = await post("studio_prepare", item.topicId ? { topic_id: item.topicId, format_intent: "card" } : { ...item.payload, format_intent: "card" });
    setBusy(false);
    if (!r.ok) { setMsg({ text: r.error ?? "초안 준비를 시작하지 못했어요.", bad: true }); return; }
    const tid = String(r.result?.topic_id ?? item.topicId ?? "");
    const act = r.result?.action;
    if (act === "stopped" || act === "needs_choice" || act === "none") {
      setMsg({ text: act === "needs_choice" && r.result?.code === "recovery_limit" ? "자동 복구를 여러 번 했지만 끝내지 못했어요. 다른 소재를 골라 주세요."
        : act === "needs_choice" ? `다시 시작하지 못했어요: ${String(r.result?.message ?? r.result?.code ?? "")}` : "자동으로 다시 할 수 없는 상태예요. 아래 이유를 확인해 주세요.", bad: true });
    }
    if (r.dispatch && !r.dispatch.triggered && r.result?.queued) setMsg({ text: "작업 순서에 넣었어요. 작업기가 깨어나는 대로(최대 몇 시간) 준비를 시작해요." });
    if (tid === selectedTopicId) router.refresh(); else go(tid);
  };

  return (
    <div className="sj" lang="ko">
      <nav className="sj-steps" aria-label="콘텐츠 제작 단계">
        {STEPS.map((s, i) => {
          const cur = LOGICAL[screen] === s.id;
          const reachable = s.id === "collect" || (s.id === "draft" && Boolean(plan)) || (s.id === "versions" && Boolean(plan));
          return (
            <span key={s.id} className="sj-step-wrap">
              {i > 0 && <span className="sj-chevron" aria-hidden="true">→</span>}
              <button type="button" className="sj-step" aria-current={cur ? "step" : undefined} disabled={!reachable || busy}
                onClick={() => setOverride(s.id === "versions" && plan?.plan_status === "approved" ? phase.screen : s.id)}>
                <b>{i + 1}</b>{s.label}
              </button>
            </span>
          );
        })}
      </nav>
      {statusProblem && <p className="sj-error" role="alert">소재 상태를 읽지 못했어요: {statusProblem}</p>}
      {msg && <p className={msg.bad ? "sj-error" : "sj-message"} role={msg.bad ? "alert" : "status"}>{msg.text}</p>}

      {screen === "collect" && <div className="sj-slot">{header}</div>}
      {screen === "collect" && (
        <Collect summary={summary} items={items} problems={problems} selKey={selKey} onSelect={setSelKey} sel={sel} busy={busy}
          current={status && sel?.topicId === status.topic.id ? phase : null} hasPlan={Boolean(plan) && sel?.topicId === status?.topic.id}
          onPrepare={prepare} onOpen={(id) => (id === selectedTopicId ? setOverride(null) : go(id))} />
      )}
      {screen === "collect" && <div className="sj-slot">{footer}</div>}
      {screen === "preparing" && status && <Preparing status={status} onCancel={async () => {
        if (!status.active) return;
        setBusy(true);
        const r = await post("cancel_develop", { request_id: status.active.request_id });
        setBusy(false);
        setMsg(r.ok ? { text: "취소를 요청했어요. 새 작업과 재시도는 멈추고, 이미 쓴 비용 기록은 남아요." } : { text: r.error ?? "취소하지 못했어요.", bad: true });
        router.refresh();
      }} busy={busy} />}
      {screen === "blocked" && <Blocked code={phase.code} status={status} onBack={() => setOverride("collect")} />}
      {screen === "choice" && status && <Choice phase={phase} status={status} busy={busy} onBack={() => setOverride("collect")}
        onRetry={() => { const it = items.find((i) => i.topicId === status.topic.id); if (it) prepare(it); }} />}
      {screen === "draft" && status && plan && (
        <Draft key={plan.plan_revision_id} status={status} plan={livePlan!} onBack={() => setOverride("collect")}
          onSaved={(version, nums, edit) => setSaved({ planId: plan.plan_revision_id, version, nums, edit })}
          onNext={() => setOverride(plan.plan_status === "approved" ? phase.screen : "versions")} onRefresh={() => router.refresh()} />
      )}
      {screen === "versions" && status && plan && (
        <Versions status={status} plan={livePlan!} picked={picked} setPicked={setPicked} onBack={() => setOverride("draft")} onDone={() => { setOverride(null); router.refresh(); }} />
      )}
      {(screen === "generating" || screen === "result") && status && plan && (
        <Results status={status} plan={plan} files={files} problem={resultProblem} generating={screen === "generating"}
          onEdit={() => setOverride("draft")} onAdd={() => setOverride("versions")} onNext={() => go(null)} onRefresh={() => router.refresh()} />
      )}

      <footer className="sj-footer"><span>술째리고 · 콘텐츠 스튜디오</span><span>콘텐츠 생성은 공개 게시가 아니에요. 게시 승인·예약은 <Link href="/drinks/publish">발행</Link>에서 따로 해요.</span></footer>
    </div>
  );
}

// ── ① 소재 고르기 ────────────────────────────────────────────────────────────
function Collect({ summary, items, problems, selKey, onSelect, sel, busy, current, hasPlan, onPrepare, onOpen }: {
  summary?: string; items: StudioCollectItem[]; problems: string[]; selKey: string | null; onSelect: (k: string) => void; sel: StudioCollectItem | null; busy: boolean;
  current: ReturnType<typeof studioPhase> | null; hasPlan: boolean; onPrepare: (i: StudioCollectItem) => void; onOpen: (topicId: string) => void;
}) {
  return (
    <section aria-labelledby="sj-collect-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">COLLECT / SELECT</p><h1 id="sj-collect-h">어떤 이야기를 만들까요?</h1>
          <p>수집된 질문에서 소재를 고르면, 초안까지 준비해 드려요.</p></div>
        <span className="sj-note">고를 수 있는 소재 · {items.length}개</span>
      </div>
      {summary && <p className="sj-note">{summary}</p>}
      {problems.map((p) => <p key={p} className="sj-error" role="alert">읽지 못한 칸이 있어요 — {p}</p>)}
      {items.length === 0 ? <p className="sj-empty">지금 자동으로 초안까지 만들 수 있는 소재가 없어요. 수집이 돌면 여기에 나타나요.</p> : (
        <div className="sj-layout">
          <ul className="sj-stack" aria-label="수집된 소재">
            {items.map((t) => (
              <li key={t.key}>
                <button type="button" className="sj-topic" aria-pressed={t.key === selKey} onClick={() => onSelect(t.key)}>
                  <span className="sj-thumb" aria-hidden="true"><strong>{t.kind.split(" · ")[0] || "소재"}</strong><span>술째리고</span></span>
                  <span className="sj-topic-copy">
                    <span className="sj-label">{t.kind || "주제 미정"}{t.inProgress ? " · 이어 만들 소재" : ""}</span>
                    <strong className="sj-topic-name">{t.title}</strong>
                    <small>{t.origin}</small>
                  </span>
                  <span aria-hidden="true">{t.key === selKey ? "✓" : "→"}</span>
                </button>
              </li>
            ))}
          </ul>
          {sel && (
            <aside className="sj-picked" aria-label="선택한 소재">
              <div><span className="sj-label">선택한 소재</span><h2>{sel.title}</h2></div>
              <p className="sj-question">“{sel.question}”</p>
              <hr />
              <div><span className="sj-label">이런 초안으로 준비해요</span>
                <p>{sel.angle ?? "질문에 답하는 카드뉴스 초안부터 준비해요. 버전은 초안을 본 뒤에 골라요."}</p></div>
              {current?.reason && <p className="sj-note">{current.reason}</p>}
              <p className="sj-note">자료 확인과 구성은 자동으로 진행돼요.<br />완성된 초안을 읽고 다듬어 주세요.</p>
              {sel.videoDraft && sel.topicId ? (
                <Link className="sj-btn sj-main" href={`/drinks/work/${sel.topicId}`}>설명형 초안 이어보기 <span aria-hidden="true">→</span></Link>
              ) : hasPlan && sel.topicId ? (
                <button type="button" className="sj-btn sj-main" onClick={() => onOpen(sel.topicId!)}>초안 이어보기 <span aria-hidden="true">→</span></button>
              ) : (
                <button type="button" className="sj-btn sj-main" disabled={busy} onClick={() => onPrepare(sel)}>
                  {busy ? "시작하는 중…" : "이 소재로 초안 만들기"} <span aria-hidden="true">→</span>
                </button>
              )}
              <span className="sj-note">이번 주 AI 초안 한도 안에서 만들어요. 초안 확인 후 생성할 버전을 골라요.</span>
            </aside>
          )}
        </div>
      )}
    </section>
  );
}

// ── 초안 준비 중 ─────────────────────────────────────────────────────────────
function Preparing({ status, onCancel, busy }: { status: StudioStatus; onCancel: () => void; busy: boolean }) {
  const a = status.active!;
  return (
    <section aria-labelledby="sj-prep-h">
      <div className="sj-progress-wrap">
        <p className="sj-kicker">DRAFT IN PROGRESS</p>
        <div className="sj-progress-icon" aria-hidden="true">↻</div>
        <h1 id="sj-prep-h">읽을 수 있는 초안으로<br />준비하고 있어요.</h1>
        <p className="sj-status" role="status" aria-live="polite">{progressText(a)}</p>
        <p className="sj-note">{status.topic.title} · {a.kind === "evidence" ? "자료 확인" : "초안 쓰기"} 단계</p>
        <p className="sj-note">이 과정에서 입력하거나 승인할 것은 없어요. 창을 닫아도 서버에서 이어져요.</p>
      </div>
      <div className="sj-actions">
        <button type="button" className="sj-btn" disabled={busy || a.cancel_requested} onClick={onCancel}>{a.cancel_requested ? "취소 중…" : "준비 취소"}</button>
        <span className="sj-note">진행 상태는 몇 초마다 새로 읽어요.</span>
      </div>
    </section>
  );
}

function Blocked({ code, status, onBack }: { code?: string; status: StudioStatus | null; onBack: () => void }) {
  const script = code === "script_check_failed";
  return (
    <section aria-labelledby="sj-block-h" className="sj-progress-wrap">
      <p className="sj-kicker">NEEDS A DIFFERENT TOPIC</p>
      <h1 id="sj-block-h">{script ? "이 질문으로는 믿을 만한 초안을\n아직 만들지 못했어요." : "이 질문에 답할 자료가\n아직 충분하지 않아요."}</h1>
      <p className="sj-status">{script ? "확인된 내용 안에서 다시 써 봤지만 검사를 통과하지 못했어요." : "추가 자료까지 확인했지만, 핵심 내용을 뒷받침하지 못했어요."}</p>
      <p className="sj-note">확인되지 않은 내용으로 초안을 만들지 않았어요.<br />자료를 직접 입력하지 않고 다른 소재를 고를 수 있어요.</p>
      <button type="button" className="sj-btn sj-main" onClick={onBack}>다른 소재 고르기 <span aria-hidden="true">→</span></button>
      {status?.last?.excluded && status.last.excluded.length > 0 && (
        <details className="sj-details"><summary>확인 내역 보기</summary>
          <ul>{status.last.excluded.map((x) => <li key={x.claim_id}>{x.text} — <span className="sj-muted">{x.why}</span></li>)}</ul>
        </details>
      )}
    </section>
  );
}

function Choice({ phase, status, busy, onBack, onRetry }: { phase: ReturnType<typeof studioPhase>; status: StudioStatus; busy: boolean; onBack: () => void; onRetry: () => void }) {
  const retry = phase.code === "recoverable";
  const legacy = phase.code === "draft_has_edits";
  return (
    <section aria-labelledby="sj-choice-h" className="sj-progress-wrap">
      <p className="sj-kicker">PAUSED</p>
      <h1 id="sj-choice-h">준비가 멈췄어요.</h1>
      <p className="sj-status" role="status">{phase.reason}</p>
      <div className="sj-row">
        {retry && <button type="button" className="sj-btn sj-main" disabled={busy} onClick={onRetry}>멈춘 곳부터 다시 준비하기</button>}
        {legacy && <Link className="sj-btn sj-main" href={`/drinks/work/${status.topic.id}`}>기존 작업공간에서 열기</Link>}
        {phase.code?.startsWith("budget") && <Link className="sj-btn" href="/drinks/studio">이번 주 한도 보기</Link>}
        <button type="button" className="sj-btn" onClick={onBack}>다른 소재 고르기</button>
      </div>
      <details className="sj-details"><summary>상세 이력</summary>
        <p>마지막 요청: {status.last?.kind === "plan" ? "초안 쓰기" : "자료 확인"} · {status.last?.error_code ?? "-"} · 24시간 자동 복구 {status.recoveries_24h}/{status.limits.max_recoveries_24h}회</p>
        {status.last?.error_message && <p className="sj-muted">{status.last.error_message.slice(0, 400)}</p>}
      </details>
    </section>
  );
}

// ── ② 초안 다듬기 ────────────────────────────────────────────────────────────
type SaveState = "saved" | "dirty" | "saving" | "failed";

function Draft({ status, plan, onBack, onNext, onRefresh, onSaved }: {
  status: StudioStatus; plan: NonNullable<ReturnType<typeof cardPlan>>; onBack: () => void; onNext: () => void; onRefresh: () => void;
  onSaved: (version: number, nums: string[], edit: DraftEdit) => void;
}) {
  const locked = plan.plan_status !== "draft";
  const roles = (plan.plan_json.pages ?? []).map((p) => p.role);
  const server = useMemo(() => draftFromPlan(plan), [plan]);
  const [edit, setEdit] = useState<DraftEdit>(server);
  const [version, setVersion] = useState(plan.version);
  const [save, setSave] = useState<SaveState>("saved");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [nums, setNums] = useState<string[]>(plan.unverified_numbers ?? []);
  const [instr, setInstr] = useState("");
  const [rewriteMsg, setRewriteMsg] = useState<string | null>(null);
  const lastSaved = useRef<DraftEdit>(server);
  const current = useRef<DraftEdit>(server);   // 타이머가 부를 때의 최신 글(오래된 클로저로 비교하지 않게)
  const versionRef = useRef(plan.version);
  const timer = useRef<number | null>(null);

  const doSave = useCallback(async (d: DraftEdit): Promise<boolean> => {
    if (locked || sameDraft(d, lastSaved.current)) { setSave("saved"); return true; }
    const problem = draftProblem(d, roles);
    if (problem) { setSave("failed"); setSaveMsg(problem); return false; }
    setSave("saving");
    const r = await post("studio_save_draft", { plan_revision_id: plan.plan_revision_id, expected_version: versionRef.current, pages: d.pages,
      reel: { hook_title: d.hook_title, share_line: d.share_line } });
    if (!r.ok) {
      setSave("failed");
      setSaveMsg(r.code === "version_conflict" ? "다른 곳에서 먼저 저장됐어요. 내 수정은 화면에 남아 있어요 — 새로 불러오기 전에 복사해 두세요." : r.error ?? "저장하지 못했어요.");
      return false;
    }
    lastSaved.current = d;
    const v = Number(r.result?.version ?? versionRef.current);
    versionRef.current = v;
    const n = (r.result?.unverified_numbers as string[] | undefined) ?? [];
    setVersion(v);
    setNums(n);
    onSaved(v, n, d);
    setSaveMsg(null);
    setSave(sameDraft(d, current.current) ? "saved" : "dirty");
    return true;
  }, [locked, plan.plan_revision_id, roles, onSaved]);

  const change = (d: DraftEdit) => {
    current.current = d;
    setEdit(d); setSave("dirty"); setSaveMsg(null);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { void doSave(d); }, 1500);
  };
  // 위쪽 단계 버튼 등으로 이 화면이 닫히면 남은 글을 저장한다(결과는 부모의 저장본으로 올라간다).
  const saveRef = useRef(doSave);
  saveRef.current = doSave;
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
    if (!sameDraft(current.current, lastSaved.current)) void saveRef.current(current.current);
  }, []);
  // 저장 안 된 글이 있으면 창을 닫기 전에 묻는다.
  useEffect(() => {
    if (save !== "dirty" && save !== "failed") return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [save]);

  const setPage = (i: number, k: "heading" | "body", v: string) => change({ ...edit, pages: edit.pages.map((p, j) => (j === i ? { ...p, [k]: v } : p)) });
  // 화면을 떠나기 전에 저장한다(앱 안 이동은 beforeunload 가 잡지 못한다). 저장이 실패하면 머문다.
  const leave = async (then: () => void) => {
    if (timer.current) window.clearTimeout(timer.current);
    if (await doSave(current.current)) then();
  };
  const next = () => leave(onNext);
  const rewrite = async () => {
    if (instr.trim().length < 2) { setRewriteMsg("원하는 수정 방향을 적어 주세요."); return; }
    if (!(await doSave(current.current))) { setRewriteMsg("먼저 지금 수정한 내용을 저장해야 해요."); return; }
    const r = await post("studio_rewrite", { plan_revision_id: plan.plan_revision_id, expected_version: versionRef.current, instruction: instr.trim() });
    if (!r.ok) { setRewriteMsg(r.error ?? "수정을 시작하지 못했어요. 지금 초안은 그대로예요."); return; }
    setRewriteMsg("수정 방향을 반영하고 있어요. 새 초안이 저장될 때까지 지금 초안은 그대로 남아요.");
    onRefresh();
  };
  const SAVE_TEXT: Record<SaveState, string> = { saved: "✓ 서버에 저장됨", dirty: "저장 전 — 잠시 뒤 자동 저장", saving: "저장 중…", failed: "저장 실패" };
  const supported = (status.review?.claims ?? []).filter((c) => (status.review?.core_claim_ids ?? []).includes(c.claim_id));

  return (
    <section aria-labelledby="sj-draft-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">DRAFT / EDIT</p><h1 id="sj-draft-h">이 이야기는 어때요?</h1>
          <p>{locked ? "이 초안으로 콘텐츠를 만들었어요. 결과와 묶여 있어 여기서는 읽기만 해요." : "제목과 내용을 다듬고, 마음에 들면 다음으로 넘어가세요."}</p></div>
        <span className="sj-versiontag">카드뉴스 초안 · 버전 {version}</span>
      </div>
      <div className="sj-editor-layout">
        <div className="sj-editor">
          <label className="sj-field">제목<input value={edit.pages[0]?.heading ?? ""} readOnly={locked} maxLength={120}
            onChange={(e) => setPage(0, "heading", e.target.value)} /></label>
          {edit.pages.slice(1).map((p, k) => {
            const i = k + 1;
            if (roles[i] === "source") return <p key={i} className="sj-note">{i + 1}장 · 출처 — 사용한 출처 목록이 자동으로 들어가요.</p>;
            return (
              <fieldset key={i} className="sj-page">
                <legend>{i + 1}장</legend>
                <label className="sj-field">소제목<input value={p.heading} readOnly={locked} maxLength={120} onChange={(e) => setPage(i, "heading", e.target.value)} /></label>
                <label className="sj-field">내용<textarea value={p.body} readOnly={locked} maxLength={1200} rows={4} onChange={(e) => setPage(i, "body", e.target.value)} /></label>
              </fieldset>
            );
          })}
          <details className="sj-details"><summary>릴스 첫 화면·마지막 한 줄</summary>
            <label className="sj-field">첫 화면 질문<input value={edit.hook_title} readOnly={locked} maxLength={60} onChange={(e) => change({ ...edit, hook_title: e.target.value })} /></label>
            <label className="sj-field">마지막 한 줄<input value={edit.share_line} readOnly={locked} maxLength={60} onChange={(e) => change({ ...edit, share_line: e.target.value })} /></label>
          </details>
          {!locked && <p className={`sj-checkline${save === "failed" ? " sj-bad" : ""}`} role="status" aria-live="polite">{SAVE_TEXT[save]}{saveMsg ? ` — ${saveMsg}` : ""}</p>}
          {nums.length > 0 && <p className="sj-warnline" role="alert">근거 자료에 없는 숫자가 있어요: {nums.join(", ")} — 고치거나 지워야 생성할 수 있어요.</p>}
          {!locked && (
            <details className="sj-details"><summary>다른 방향으로 다듬기</summary>
              <div className="sj-direction">
                <label className="sj-field">수정 방향<textarea value={instr} maxLength={500} placeholder="예: 더 짧고 친근하게, 첫 문장은 질문으로" onChange={(e) => setInstr(e.target.value)} /></label>
                <button type="button" className="sj-btn" onClick={rewrite}>이 방향으로 수정</button>
              </div>
              {rewriteMsg && <p className="sj-note" role="status">{rewriteMsg}</p>}
            </details>
          )}
          <details className="sj-details"><summary>출처·확인 내역 보기</summary>
            <p>사용한 출처</p>
            <ul>{status.sources.filter((s) => s.role === "evidence").map((s) => (
              <li key={s.snapshot_id}>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title ?? s.url}</a> : s.title}{s.publisher ? ` · ${s.publisher}` : ""}</li>
            ))}</ul>
            <p>초안에 쓴 확인된 내용(AI 사실 확인 — 원문 인용 대조 통과, 사람 확인 아님)</p>
            <ul>{supported.map((c) => <li key={c.claim_id}>{c.text}{c.source_refs?.[0] ? <q className="sj-quote">{c.source_refs[0].original_quote}</q> : null}</li>)}</ul>
            {status.last?.excluded && status.last.excluded.length > 0 && (<>
              <p>제외한 내용</p>
              <ul>{status.last.excluded.map((x) => <li key={x.claim_id}>{x.text} — <span className="sj-muted">{x.why}</span></li>)}</ul>
            </>)}
            <p className="sj-muted">직접 고친 문장은 숫자만 근거와 다시 대조해요. 뜻이 근거를 넘는지는 자동으로 보지 못하니 읽으며 확인해 주세요.</p>
          </details>
        </div>
        <aside aria-label="미리보기">
          <div className="sj-preview-head"><span>표지 미리보기</span><span>{edit.pages.length}장</span></div>
          <div className="sj-preview"><span className="sj-cover-mark">술째리고<br /><small>알고 마시는 한 잔</small></span>
            <span className="sj-cover-title">{edit.pages[0]?.heading}</span>
            <span className="sj-cover-meta">{edit.share_line}</span></div>
          <ol className="sj-strip" aria-label="장 구성">{edit.pages.map((p, i) => <li key={i}>{i + 1}. {roles[i] === "source" ? "출처" : p.heading}</li>)}</ol>
        </aside>
      </div>
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={() => leave(onBack)}>← 다른 소재 보기</button>
        <div><span className="sj-note">{locked ? "확정된 초안" : "수정은 서버에 저장돼요"}</span>
          <button type="button" className="sj-btn sj-main" disabled={save === "saving"} onClick={next}>{locked ? "결과 보기" : "버전 고르기"} <span aria-hidden="true">→</span></button></div>
      </div>
    </section>
  );
}

// ── ③ 버전·생성 ──────────────────────────────────────────────────────────────
function Versions({ status, plan, picked, setPicked, onBack, onDone }: {
  status: StudioStatus; plan: NonNullable<ReturnType<typeof cardPlan>>; picked: VersionId[]; setPicked: (v: VersionId[]) => void; onBack: () => void; onDone: () => void;
}) {
  const opts = versionOptions(status.topic.id, plan);
  const usable = picked.filter((id) => opts.find((o) => o.id === id)?.enabled);
  const total = orderTotal(opts, usable);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const nums = plan.unverified_numbers ?? [];
  const why = usable.length === 0 ? "만들 버전을 하나 이상 골라 주세요." : nums.length > 0 ? `초안에 근거 없는 숫자(${nums.join(", ")})가 있어요 — 초안에서 고쳐 주세요.` : null;
  const generate = async () => {
    setBusy(true); setMsg(null);
    // 사진형이면 화면에 보인 금액을 그대로 보낸다 — 서버가 지금 예상과 대조해, 같거나 크면 그 금액으로 결재를 열고 사진을 산다(0077).
    const r = await post("studio_generate", { topic_id: status.topic.id, format_intent: "card", plan_revision_id: plan.plan_revision_id,
      expected_topic_version: status.topic.version, expected_review_version: status.review?.version, expected_plan_version: plan.version,
      ...(isPhotoPlan(plan) && total !== null ? { approve_usd: total } : {}) });
    setBusy(false);
    if (!r.ok) {
      setMsg({ text: r.code === "version_conflict" ? "초안이 다른 곳에서 바뀌었어요. 새로 불러온 뒤 다시 확인해 주세요."
        : r.code === "spend_confirm_required" ? `금액이 바뀌었어요 — ${r.error ?? ""} 새로 불러온 뒤 다시 확인해 주세요.` : r.error ?? "생성을 시작하지 못했어요.", bad: true });
      return;
    }
    onDone();
  };
  return (
    <section aria-labelledby="sj-ver-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">VERSION / CREATE</p><h1 id="sj-ver-h">어떤 콘텐츠로 만들까요?</h1><p>같은 초안으로 필요한 버전을 골라 한 번에 만드세요.</p></div>
        <span className="sj-versiontag">여러 개 선택 가능</span>
      </div>
      <div className="sj-layout">
        <fieldset className="sj-format-list"><legend className="sj-sr">만들 버전</legend>
          {opts.map((o) => (
            <label key={o.id} className="sj-format" data-disabled={!o.enabled}>
              <input type="checkbox" checked={o.enabled && picked.includes(o.id)} disabled={!o.enabled}
                onChange={(e) => setPicked(e.target.checked ? [...picked, o.id] : picked.filter((x) => x !== o.id))} aria-describedby={`sj-why-${o.id}`} />
              <span className="sj-format-copy"><strong>{o.label}</strong> {o.id === "card" && <span className="sj-label">추천</span>}
                <p>{o.desc}</p>
                {!o.enabled && <p id={`sj-why-${o.id}`} className="sj-muted">{o.why}{o.href && <> <Link href={o.href}>기존 화면에서 만들기 →</Link></>}</p>}</span>
              <span className="sj-cost">{o.enabled ? o.costText : "선택 불가"}</span>
            </label>
          ))}
        </fieldset>
        <aside className="sj-order" aria-label="이번에 만들 콘텐츠">
          <span className="sj-label">이번에 만들 콘텐츠</span>
          <h3>{plan.plan_json.pages?.[0]?.heading}</h3>
          {usable.length ? usable.map((id) => { const o = opts.find((x) => x.id === id)!; return <div key={id} className="sj-order-line"><span>{o.label}</span><span>{o.costText.split(" · ")[0]}</span></div>; })
            : <p className="sj-empty">만들 버전을 골라 주세요.</p>}
          <div className="sj-order-total"><span>예상 총비용</span><span>{total === null ? "알 수 없음" : `$${total.toFixed(2)}`}</span></div>
          <p className="sj-note">{isPhotoPlan(plan)
            ? <>적용 상한: 위 금액까지만 배경 사진을 사요(이 초안 전용, 하루 유효). 글자 배치·릴스 조립은 서버에서 무료로 해요.<br />누르면 이 금액을 승인하고 초안을 확정해 제작을 요청해요. 게시는 하지 않아요.</>
            : <>적용 상한: 유료 생성 호출 없음(카드뉴스는 서버에서 조립해요).<br />누르면 이 초안을 확정하고 제작을 요청해요. 게시는 하지 않아요.</>}</p>
        </aside>
      </div>
      {msg && <p className={msg.bad ? "sj-error" : "sj-message"} role={msg.bad ? "alert" : "status"}>{msg.text}</p>}
      {why && <p className="sj-message" role="status">{why}</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onBack}>← 초안 다시 보기</button>
        <button type="button" className="sj-btn sj-main" disabled={Boolean(why) || busy} onClick={generate}>
          {busy ? "생성 요청 중…" : `이 초안으로 콘텐츠 생성 · ${usable.length}개${total ? ` · $${total.toFixed(2)}` : ""}`} <span aria-hidden="true">→</span></button>
      </div>
    </section>
  );
}

// ── 생성 중·결과 ─────────────────────────────────────────────────────────────
function Results({ status, plan, files, problem, generating, onEdit, onAdd, onNext, onRefresh }: {
  status: StudioStatus; plan: NonNullable<ReturnType<typeof cardPlan>>; files: StudioResultFile[]; problem: string | null; generating: boolean;
  onEdit: () => void; onAdd: () => void; onNext: () => void; onRefresh: () => void;
}) {
  const job = plan.jobs[0] ?? null;
  const failed = job && (job.status === "failed" || job.status === "canceled");
  const done = job?.status === "succeeded" && files.length > 0;
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const retry = async () => {
    if (!job) return;
    setBusy(true);
    const cost = cardCost(plan);
    const r = await post("studio_generate", { topic_id: status.topic.id, format_intent: "card", plan_revision_id: plan.plan_revision_id, retry_of: job.job_id,
      ...(isPhotoPlan(plan) && cost.usd !== null ? { approve_usd: cost.usd } : {}) });
    setBusy(false);
    setMsg(r.ok ? "이 버전만 다시 만들고 있어요. 이미 산 사진은 다시 사지 않아요." : r.error ?? "다시 만들지 못했어요.");
    onRefresh();
  };
  // 확정된 글자 카드 → 같은 확정 근거로 사진형 새 초안(0077). 옛 결과는 새 초안을 확정할 때까지 그대로 남는다.
  const photoRedo = async () => {
    setBusy(true);
    const r = await post("studio_rewrite", { plan_revision_id: plan.plan_revision_id, expected_version: plan.version,
      instruction: "사진형 카드(배경 사진 위 제목·본문 2줄)로 다시 써 주세요. 원문이 직접 말하지 않는 표현은 빼 주세요." });
    setBusy(false);
    setMsg(r.ok ? "사진형으로 새 초안을 쓰고 있어요. 다 되면 초안 다듬기 화면이 열려요." : r.error ?? "새 초안을 요청하지 못했어요.");
    onRefresh();
  };
  const retryCost = failed ? cardCost(plan) : null;
  const images = files.filter((f) => f.mime.startsWith("image/")).sort((a, b) => a.position - b.position);
  const videos = files.filter((f) => f.mime.startsWith("video/"));
  return (
    <section aria-labelledby="sj-res-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">{generating ? "CREATING YOUR CONTENT" : "YOUR CONTENT"}</p>
          <h1 id="sj-res-h">{generating ? "고른 버전으로 콘텐츠를 만들고 있어요." : failed ? "완료한 콘텐츠부터 확인하세요." : done ? "콘텐츠가 준비됐어요." : "결과 파일을 확인하고 있어요."}</h1>
          <p role="status" aria-live="polite">{generating ? (job?.status === "queued" ? "제작 순서를 기다리고 있어요. 검사와 조립은 자동으로 이어져요." : "카드를 조립하고 자동 검사를 하고 있어요.")
            : failed ? "이 버전은 제작을 마치지 못했어요." : done ? "실제 파일과 자동 검사 결과가 확보된 버전이에요." : "제작은 끝났지만 파일을 아직 읽지 못했어요."}</p></div>
        <span className="sj-versiontag">카드뉴스 · {job ? `${job.attempt_no}번째 제작` : "제작 전"}</span>
      </div>
      {problem && <p className="sj-error" role="alert">결과를 읽지 못했어요: {problem}</p>}
      <article className="sj-result">
        {images.length > 0 ? (
          <div className="sj-gallery">{images.map((f) => f.url ? <a key={f.position} href={f.url} target="_blank" rel="noreferrer" download>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={f.url} alt={`카드 ${f.position}장`} loading="lazy" /></a> : <span key={f.position} className="sj-muted">{f.position}장: {f.urlError ?? "미리보기 불가(로컬 저장)"}</span>)}</div>
        ) : <div className="sj-preview sj-preview--wide"><span className="sj-cover-mark">술째리고</span><span className="sj-cover-title">{plan.plan_json.pages?.[0]?.heading}</span>
          <span className="sj-cover-meta">{generating ? "만드는 중" : "결과 파일 없음"}</span></div>}
        {videos.map((v) => v.url && <video key={v.position} src={v.url} controls preload="metadata" className="sj-video" aria-label="세로 릴스" />)}
        <div className="sj-result-footer">
          <div><strong>카드뉴스</strong>
            <p className="sj-note">{failed ? `제작 실패(${job?.error_code ?? "원인 미상"})` : done ? `✓ 생성 완료 · 검수 ${files[0]?.reviewStatus === "approved" ? "승인됨" : "대기(게시 전 발행 화면에서)"}` : generating ? "만드는 중" : "확인 중"}</p></div>
          {failed && <button type="button" className="sj-btn" disabled={busy || retryCost?.usd === null} onClick={retry}>
            {busy ? "다시 만드는 중…" : `이 버전만 다시 만들기${retryCost?.usd ? ` · $${retryCost.usd.toFixed(2)}` : ""}`}</button>}
          {!generating && !isPhotoPlan(plan) && <button type="button" className="sj-btn" disabled={busy} onClick={photoRedo}>사진형으로 다시 만들기</button>}
          {done && images[0]?.url && <a className="sj-btn" href={images[0].url} download>표지 내려받기</a>}
        </div>
        {msg && <p className="sj-message" role="status">{msg}</p>}
      </article>
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onEdit}>← 초안 보기</button>
        <div><span className="sj-note">공개 게시 없이 결과만 확인해요</span>
          <button type="button" className="sj-btn" onClick={onAdd}>다른 버전 추가</button>
          <button type="button" className="sj-btn sj-main" onClick={onNext}>다음 소재 고르기 <span aria-hidden="true">→</span></button></div>
      </div>
    </section>
  );
}
