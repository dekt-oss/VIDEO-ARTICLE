"use client";

// 콘텐츠 스튜디오 — 운영자가 정한 한 줄 흐름(2026-11-08, docs/deviation-drinks-studio-flow.md):
//   ① 소재 ② 초안(글로 된 구성표 + 코멘트 재생성) ③ 작업 명세서 승인 ④ 제작·검수 ⑤ 인스타 등록. 근거는 뒤에서 자동 검사하고 여기 보이지 않는다.
// ★ 화면은 서버 상태만 보여 준다. 진행률·비용·완료 표시를 지어내지 않는다. 막는 것은 전부 DB 다.
// ★ 준비·생성 중에만 몇 초마다 새로 읽는다(router.refresh). 코멘트를 쓰는 화면은 새로 읽지 않아 입력이 사라지지 않는다.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import ExplainerProduction from "@/components/drinks/ExplainerProduction";
import { CHECKS, REEL_CHECKS } from "@/components/drinks/ProductionControls";
import { RequestActions } from "@/components/drinks/PublishControls";
import { CLAY_PROVIDER, MAKE_METHOD_LABEL, clayStage, PROCESS_CHECKS, QUALITY_CHECKS, canJudge, kstMinute, neededKinds, nextStep, usableApproval, type ExplainerStatus, type MakeMethod } from "@/lib/drinks/explainerQueue";
import { blockerLabel } from "@/lib/drinks/model";
import { PICK_FORMATS, PICK_FORMAT_HINT, PICK_FORMAT_LABEL } from "@/lib/drinks/pickModal";
import { PUBLISH_WINDOW, publishWindowProblem } from "@/lib/drinks/publishWindow";
import {
  BATCH_MAX, activePlan, batchTargets, cardCost, defaultFormat, defaultPublishAt, draftRows, formatAction, isPhotoPlan, progressText, studioPhase,
  type FormatChoice, type StudioLane, type StudioPlan, type StudioScreen, type StudioStatus,
} from "@/lib/drinks/studio";

export interface StudioCollectItem {
  key: string; topicId: string | null; candidateId: string | null; title: string; question: string; kind: string; origin: string;
  angle: string | null; inProgress: boolean; payload: Record<string, unknown>;
  /** 이미 시작한 유형·초안이 있는 유형(card·explainer) */
  started: string[]; drafts: string[];
}
export interface StudioResultFile {
  role: string; position: number; mime: string; url: string | null; urlError: string | null; width: number | null; height: number | null;
  jobId: string; reviewStatus: string | null; qa: boolean | null;
}
/** 지금 초안의 제작 상태 */
export interface StudioProduction {
  explainer: ExplainerStatus | null;
  activeJob: { renderer: string; status: string } | null;
  outputReview: { id: string; version: number; status: string; hasReel: boolean } | null;
}
export interface StudioPublish {
  accounts: { id: string; label: string; postTypes: string[] }[];
  aiLabel: string | null;
  request: { id: string; version: number; status: string; approval_digest: string | null; caption: string | null; publish_at: string | null; external_url: string | null } | null;
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

const STEPS = [
  { id: "collect", label: "소재" }, { id: "draft", label: "초안" }, { id: "spec", label: "작업 명세서" }, { id: "make", label: "제작·검수" }, { id: "publish", label: "인스타 등록" },
] as const;
const LOGICAL: Record<StudioScreen, (typeof STEPS)[number]["id"]> = {
  collect: "collect", preparing: "draft", blocked: "collect", choice: "collect", draft: "draft", spec: "spec", generating: "make", result: "make", publish: "publish",
};
const POLL_MS = 5000;

export default function StudioClient({ items, problems, status, statusProblem, files, resultProblem, selectedTopicId, lane, production, publish, pickContext, summary, header, footer }: {
  items: StudioCollectItem[]; problems: string[]; status: StudioStatus | null; statusProblem: string | null;
  files: StudioResultFile[]; resultProblem: string | null; selectedTopicId: string | null;
  lane: StudioLane | null; production: StudioProduction | null; publish: StudioPublish | null;
  /** 시작한 소재에 유형을 더할 때 쓰는 값(pick_topic): 이번 주 편성·이번 주 한도 */
  pickContext: { week: string; budgetId: string | null };
  /** 목록 머리 설명 · ① 화면 위·아래에 붙는 서버 칸(탭·한도, 손으로 넣기) */
  summary?: string; header?: ReactNode; footer?: ReactNode;
}) {
  const router = useRouter();
  const phase = studioPhase(status, { lane, episodeState: production?.explainer?.episode?.state ?? null, outputStatus: production?.outputReview?.status ?? null });
  const plan = activePlan(status, lane);
  // 사람이 고른 화면(뒤로 가기). 서버 단계가 바뀌면 서버 단계를 따른다.
  const [override, setOverride] = useState<StudioScreen | null>(null);
  const [selKey, setSelKey] = useState<string | null>(() => (selectedTopicId ? items.find((i) => i.topicId === selectedTopicId)?.key : null) ?? items[0]?.key ?? null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [format, setFormat] = useState<FormatChoice>(() => lane ?? defaultFormat(items.find((i) => i.key === selKey) ?? null));
  const [checked, setChecked] = useState<string[]>([]);   // 한 번에 만들 소재들
  useEffect(() => setOverride(null), [phase.screen, status?.topic.id]);
  const screen: StudioScreen = override ?? (selectedTopicId ? phase.screen : "collect");

  // 준비·생성 중에만 새로 읽는다(서버 상태가 정본 — 창을 닫았다 열어도 같은 상태).
  useEffect(() => {
    const waitingSpec = screen === "spec" && plan?.format === "video" && !production?.explainer?.episode?.directive;
    if (screen !== "preparing" && screen !== "generating" && !waitingSpec) return;
    const t = window.setInterval(() => router.refresh(), POLL_MS);
    return () => window.clearInterval(t);
  }, [screen, router, plan?.format, production?.explainer?.episode?.directive]);

  const go = (topicId: string | null, f?: StudioLane) => router.push(topicId ? `/drinks/studio?topic=${topicId}${f ? `&lane=${f}` : ""}` : "/drinks/studio");
  const sel = items.find((i) => i.key === selKey) ?? null;
  // 유형을 더하면 그 유형의 초안을 만든다. 근거는 소재마다 하나를 함께 쓴다.
  const sendAdd = (item: StudioCollectItem, f: StudioLane) => post("pick_topic", { topic_id: item.topicId, formats: [f], format: f, editorial_week: pickContext.week, recommended_format: f,
    ...(pickContext.budgetId ? { budget_id: pickContext.budgetId } : {}) });
  const sendPrepare = (item: StudioCollectItem, f: StudioLane) => post("studio_prepare", item.topicId ? { topic_id: item.topicId, format_intent: f } : { ...item.payload, format_intent: f });
  const addFormat = async (item: StudioCollectItem, f: StudioLane) => {
    setBusy(true); setMsg(null);
    const r = await sendAdd(item, f);
    setBusy(false);
    if (!r.ok) { setMsg({ text: r.error ?? "유형을 더하지 못했어요.", bad: true }); return; }
    go(item.topicId, f);
    router.refresh();
  };

  const prepare = async (item: StudioCollectItem) => {
    setBusy(true); setMsg(null);
    const format_intent = format === "explainer" ? "explainer" : "card";   // 밈은 이 요청을 타지 않는다(밈 보드로 간다)
    const r = await sendPrepare(item, format_intent);
    setBusy(false);
    if (!r.ok) { setMsg({ text: r.error ?? "초안 준비를 시작하지 못했어요.", bad: true }); return; }
    const tid = String(r.result?.topic_id ?? item.topicId ?? "");
    const act = r.result?.action;
    if (act === "stopped" || act === "needs_choice" || act === "none") {
      setMsg({ text: act === "needs_choice" && r.result?.code === "recovery_limit" ? "자동 복구를 여러 번 했지만 끝내지 못했어요. 다른 소재를 골라 주세요."
        : act === "needs_choice" ? `다시 시작하지 못했어요: ${String(r.result?.message ?? r.result?.code ?? "")}` : "자동으로 다시 할 수 없는 상태예요. 아래 이유를 확인해 주세요.", bad: true });
    }
    if (r.dispatch && !r.dispatch.triggered && r.result?.queued) setMsg({ text: "작업 순서에 넣었어요. 작업기가 깨어나는 대로(최대 몇 시간) 준비를 시작해요." });
    if (tid === selectedTopicId && lane === format_intent) router.refresh(); else go(tid, format_intent);
  };

  // 여러 소재를 차례로 맡기고 이 화면에 머문다. 한 건이 실패해도 나머지는 계속하고, 실패한 소재만 체크를 남긴다.
  const startMany = async (list: StudioCollectItem[], f: StudioLane) => {
    setBusy(true); setMsg(null);
    const failed: { key: string; why: string }[] = [];
    let waitsForCron = false;
    for (const it of list) {
      const r = await (formatAction(it, f) === "add" ? sendAdd(it, f) : sendPrepare(it, f));
      const act = r.result?.action;
      if (!r.ok) failed.push({ key: it.key, why: `${it.title}: ${r.error ?? "시작하지 못했어요"}` });
      else if (act === "stopped" || act === "needs_choice" || act === "none") failed.push({ key: it.key, why: `${it.title}: 자동으로 다시 할 수 없는 상태예요. 소재를 눌러 이유를 확인해 주세요.` });
      else if (r.dispatch && !r.dispatch.triggered && r.result?.queued) waitsForCron = true;
    }
    setBusy(false);
    setChecked(failed.map((x) => x.key));
    const ok = list.length - failed.length;
    const head = ok > 0 ? `${ok}개 소재의 초안을 만들기 시작했어요. 편당 몇 분 걸려요. 새로고침하면 다 된 소재에 '초안 있음'이 붙어요.${waitsForCron ? " 작업기가 깨어나는 대로(최대 몇 시간) 시작해요." : ""}` : "";
    setMsg({ text: [head, ...failed.map((x) => x.why)].filter(Boolean).join(" "), bad: failed.length > 0 });
    router.refresh();
  };

  return (
    <div className="sj" lang="ko">
      <nav className="sj-steps" aria-label="콘텐츠 제작 단계">
        {STEPS.map((s, i) => {
          const cur = LOGICAL[screen] === s.id;
          // 앞 단계로만 돌아갈 수 있다. 다음 단계는 그 단계의 승인 버튼으로 간다.
          const target: StudioScreen | null = s.id === "collect" ? "collect" : s.id === "draft" && plan ? "draft" : null;
          return (
            <span key={s.id} className="sj-step-wrap">
              {i > 0 && <span className="sj-chevron" aria-hidden="true">→</span>}
              <button type="button" className="sj-step" aria-current={cur ? "step" : undefined} disabled={!target || busy} onClick={() => setOverride(target)}>
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
        <Collect summary={summary} items={items} problems={problems} selKey={selKey} sel={sel} busy={busy}
          onSelect={(k) => { setSelKey(k); setFormat(defaultFormat(items.find((i) => i.key === k) ?? null)); }}
          checked={checked} onCheck={(k) => setChecked((c) => (c.includes(k) ? c.filter((x) => x !== k) : c.length < BATCH_MAX ? [...c, k] : c))}
          onClearChecked={() => setChecked([])} onStartMany={startMany}
          current={status && sel?.topicId === status.topic.id ? phase : null}
          format={format} onFormat={setFormat} onPrepare={prepare} onAdd={addFormat}
          onOpen={(id, f) => { if (id === selectedTopicId && lane === f) setOverride(null); else go(id, f); }} />
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
      {screen === "draft" && plan && <Draft key={`${plan.plan_revision_id}-${plan.version}`} plan={plan} onBack={() => setOverride("collect")} onRefresh={() => router.refresh()} />}
      {screen === "spec" && status && plan && <Spec status={status} plan={plan} production={production} onBack={() => setOverride("draft")} onRefresh={() => router.refresh()} />}
      {screen === "generating" && plan?.format === "video" && production?.explainer && <VideoMaking plan={plan} production={production} onRefresh={() => router.refresh()} />}
      {(screen === "result" || (screen === "generating" && plan?.format !== "video")) && status && plan && (
        <Results status={status} plan={plan} files={files} problem={resultProblem} generating={screen === "generating"} production={production}
          onEdit={() => setOverride("draft")} onRefresh={() => router.refresh()} />
      )}
      {screen === "publish" && status && plan && <Publish status={status} plan={plan} files={files} publish={publish} production={production} onDone={() => go(null)} onRefresh={() => router.refresh()} />}

      <footer className="sj-footer"><span>술째리고 · 콘텐츠 스튜디오</span>{status && <span><Link href={`/drinks/work/${status.topic.id}?detail=1${plan ? `&lane=${plan.format === "video" ? "explainer" : "card"}` : ""}`}>자세히 보기(근거·이력)</Link></span>}</footer>
    </div>
  );
}

// ── ① 소재 고르기 ────────────────────────────────────────────────────────────
function Collect({ summary, items, problems, selKey, onSelect, checked, onCheck, onClearChecked, onStartMany, sel, busy, current, format, onFormat, onPrepare, onAdd, onOpen }: {
  checked: string[]; onCheck: (k: string) => void; onClearChecked: () => void; onStartMany: (list: StudioCollectItem[], f: StudioLane) => void;
  summary?: string; items: StudioCollectItem[]; problems: string[]; selKey: string | null; onSelect: (k: string) => void; sel: StudioCollectItem | null; busy: boolean;
  current: ReturnType<typeof studioPhase> | null; format: FormatChoice; onFormat: (f: FormatChoice) => void;
  onPrepare: (i: StudioCollectItem) => void; onAdd: (i: StudioCollectItem, f: StudioLane) => void; onOpen: (topicId: string, f: StudioLane) => void;
}) {
  const action = sel ? formatAction(sel, format) : null;
  const many = items.filter((i) => checked.includes(i.key));
  const manyTargets = batchTargets(many, format);
  const formats = (badges: StudioCollectItem | null) => (
    <fieldset className="sj-format-list"><legend className="sj-label">어떤 유형으로 만들까요?</legend>
      {PICK_FORMATS.map((f) => (
        <label key={f} className="sj-format">
          <input type="radio" name="sj-collect-format" checked={format === f} disabled={busy} onChange={() => onFormat(f)} />
          <span className="sj-format-copy"><strong>{PICK_FORMAT_LABEL[f]}</strong>
            {badges?.drafts.includes(f) ? <span className="sj-label"> · 초안 있음</span> : badges?.started.includes(f) ? <span className="sj-label"> · 시작함</span> : null}
            <p>{PICK_FORMAT_HINT[f]}</p></span>
        </label>
      ))}
    </fieldset>
  );
  return (
    <section aria-labelledby="sj-collect-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">COLLECT / SELECT</p><h1 id="sj-collect-h">어떤 이야기를 만들까요?</h1>
          <p>수집된 질문에서 소재를 고르면, 초안까지 준비해 드려요. 왼쪽 네모를 체크하면 여러 소재를 한 번에 만들 수 있어요(최대 {BATCH_MAX}개).</p></div>
        <span className="sj-note">고를 수 있는 소재 · {items.length}개</span>
      </div>
      {summary && <p className="sj-note">{summary}</p>}
      {problems.map((p) => <p key={p} className="sj-error" role="alert">읽지 못한 칸이 있어요 — {p}</p>)}
      {items.length === 0 ? <p className="sj-empty">지금 자동으로 초안까지 만들 수 있는 소재가 없어요. 수집이 돌면 여기에 나타나요.</p> : (
        <div className="sj-layout">
          <ul className="sj-stack" aria-label="수집된 소재">
            {items.map((t) => (
              <li key={t.key} className="sj-topic-row">
                <label className="sj-topic-check">
                  <input type="checkbox" aria-label={`${t.title} 함께 만들기`} checked={checked.includes(t.key)} disabled={busy || (!checked.includes(t.key) && checked.length >= BATCH_MAX)} onChange={() => onCheck(t.key)} />
                </label>
                {/* 여러 개를 고르는 중에는 줄을 눌러도 체크가 바뀐다(오른쪽 칸이 묶음 칸이라 한 소재 보기가 없다) */}
                <button type="button" className="sj-topic" aria-pressed={many.length > 0 ? checked.includes(t.key) : t.key === selKey} disabled={busy} onClick={() => (many.length > 0 ? onCheck(t.key) : onSelect(t.key))}>
                  <span className="sj-thumb" aria-hidden="true"><strong>{t.kind.split(" · ")[0] || "소재"}</strong><span>술째리고</span></span>
                  <span className="sj-topic-copy">
                    <span className="sj-label">{t.kind || "주제 미정"}{t.drafts.length > 0 ? " · 초안 있음" : t.inProgress ? " · 이어 만들 소재" : ""}</span>
                    <strong className="sj-topic-name">{t.title}</strong>
                    <small>{t.origin}</small>
                  </span>
                  <span aria-hidden="true">{(many.length > 0 ? checked.includes(t.key) : t.key === selKey) ? "✓" : "→"}</span>
                </button>
              </li>
            ))}
            {many.length > 0 && <li className="sj-many-jump"><button type="button" className="sj-btn sj-main" onClick={() => document.getElementById("sj-many")?.scrollIntoView({ behavior: "smooth" })}>선택한 {many.length}개 만들러 가기 <span aria-hidden="true">↑</span></button></li>}
          </ul>
          {many.length > 0 ? (
            <aside id="sj-many" className="sj-picked" aria-label="선택한 소재들">
              <div><span className="sj-label">선택한 소재 {many.length}개{many.length >= BATCH_MAX ? " · 한 번에 최대" : ""}</span>
                <ul className="sj-picked-list">{many.map((i) => <li key={i.key}>{i.title}</li>)}</ul></div>
              <hr />
              {formats(null)}
              {format === "meme" ? <>
                <p className="sj-note">밈은 소재마다 원본 릴스를 골라야 해서 한 번에 만들 수 없어요. 밈 보드에서 하나씩 시작해요.</p>
                <Link className="sj-btn sj-main" href="/drinks/memes">밈 보드에서 틀 고르기 <span aria-hidden="true">→</span></Link>
              </> : <>
                {manyTargets.length < many.length && <p className="sj-note">이미 {PICK_FORMAT_LABEL[format]} 초안이 있는 {many.length - manyTargets.length}개는 빼고 만들어요.</p>}
                <button type="button" className="sj-btn sj-main" disabled={busy || manyTargets.length === 0} onClick={() => onStartMany(manyTargets, format)}>
                  {busy ? "시작하는 중…" : `${PICK_FORMAT_LABEL[format]} 초안 ${manyTargets.length}개 만들기`} <span aria-hidden="true">→</span>
                </button>
                <span className="sj-note">이번 주 AI 초안 한도 안에서 만들어요. 한도가 먼저 차면 그 소재부터 멈추고 이유가 남아요. 사진·영상 구매는 초안을 본 뒤 금액을 보고 따로 승인해요.</span>
              </>}
              <button type="button" className="sj-btn" disabled={busy} onClick={onClearChecked}>선택 해제</button>
            </aside>
          ) : sel && (
            <aside className="sj-picked" aria-label="선택한 소재">
              <div><span className="sj-label">선택한 소재</span><h2>{sel.title}</h2></div>
              <p className="sj-question">“{sel.question}”</p>
              <hr />
              <div><span className="sj-label">이런 초안으로 준비해요</span>
                <p>{sel.angle ?? "소재의 질문에 답하는 초안을 준비해요."}</p></div>
              {current?.reason && <p className="sj-note">{current.reason}</p>}
              {formats(sel)}
              {action === "meme"
                ? <p className="sj-note">밈은 틀이 되는 원본 릴스를 먼저 골라야 해서 밈 보드에서 시작해요.</p>
                : action !== "open" && <p className="sj-note">자료 확인과 구성은 자동으로 진행돼요.<br />완성된 초안을 읽고 코멘트를 달아 주세요.</p>}
              {action === "open" && format !== "meme" ? (
                <button type="button" className="sj-btn sj-main" onClick={() => onOpen(sel.topicId!, format)}>초안 보기 <span aria-hidden="true">→</span></button>
              ) : action === "meme" ? (
                <Link className="sj-btn sj-main" href="/drinks/memes">밈 보드에서 틀 고르기 <span aria-hidden="true">→</span></Link>
              ) : (
                <button type="button" className="sj-btn sj-main" disabled={busy} onClick={() => (action === "add" && format !== "meme" ? onAdd(sel, format) : onPrepare(sel))}>
                  {busy ? "시작하는 중…" : `${PICK_FORMAT_LABEL[format]} 초안 만들기`} <span aria-hidden="true">→</span>
                </button>
              )}
              <span className="sj-note">이번 주 AI 초안 한도 안에서 만들어요. 사진·영상 구매는 초안을 본 뒤 금액을 보고 따로 승인해요.</span>
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
  const offTopic = code === "evidence_off_topic";
  return (
    <section aria-labelledby="sj-block-h" className="sj-progress-wrap">
      <p className="sj-kicker">NEEDS A DIFFERENT TOPIC</p>
      <h1 id="sj-block-h">{script ? "이 질문으로는 믿을 만한 초안을\n아직 만들지 못했어요." : offTopic ? "모은 자료가 이 질문에\n답하지 못해요." : "이 질문에 답할 자료가\n아직 충분하지 않아요."}</h1>
      <p className="sj-status">{script ? "확인된 내용 안에서 다시 써 봤지만 검사를 통과하지 못했어요."
        : offTopic ? "자료는 있지만 제목이 묻는 핵심과 다른 이야기라, 엉뚱한 영상이 되지 않게 멈췄어요."
        : "추가 자료까지 확인했지만, 핵심 내용을 뒷받침하지 못했어요."}</p>
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

// ── 공통: 코멘트로 다시 만들기 ────────────────────────────────────────────────
function CommentBox({ plan, label, note, onRefresh }: { plan: StudioPlan; label: string; note: string; onRefresh: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const send = async () => {
    setBusy(true);
    const r = await post("studio_rewrite", { plan_revision_id: plan.plan_revision_id, expected_version: plan.version, instruction: text.trim() });
    setBusy(false);
    if (!r.ok) { setMsg(r.error ?? "다시 만들기를 시작하지 못했어요. 지금 초안은 그대로예요."); return; }
    setMsg("코멘트를 반영해 다시 만들고 있어요.");
    onRefresh();
  };
  return (
    <div className="sj-comment">
      <label className="sj-field">{label}<textarea value={text} maxLength={500} rows={3} placeholder="예: 2번 장면은 술잔 대신 쌀을 깎는 모습으로, 말투를 더 짧게" onChange={(e) => setText(e.target.value)} /></label>
      <div className="sj-comment-foot">
        <span className="sj-note">{note}</span>
        <button type="button" className="sj-btn" disabled={busy || text.trim().length < 2} onClick={send}>{busy ? "요청 중…" : "코멘트대로 다시 만들기"}</button>
      </div>
      {msg && <p className="sj-note" role="status">{msg}</p>}
    </div>
  );
}

// ── 릴스 만드는 방식: 사진클레이(점토 그림 + 자막, 0079) / 영상 클립 ─────────────────
const MAKE_HINT: Record<MakeMethod, string> = {
  clay: "장면마다 점토 그림 1장 + 자막 + 목소리. 그림 장당 약 $0.04",
  omni: "장면마다 AI 영상 클립. 장면당 수백 원부터",
};
function MakeChoice({ value, onChange, disabled }: { value: MakeMethod; onChange: (v: MakeMethod) => void; disabled?: boolean }) {
  return (
    <fieldset className="sj-make" disabled={disabled}>
      <legend>만드는 방식</legend>
      {(["clay", "omni"] as const).map((m) => (
        <label key={m} className={value === m ? "is-on" : undefined}>
          <input type="radio" name="sj-make" value={m} checked={value === m} onChange={() => onChange(m)} />
          <b>{MAKE_METHOD_LABEL[m]}</b><span>{MAKE_HINT[m]}</span>
        </label>
      ))}
    </fieldset>
  );
}

// ── ② 초안: 어떤 화면에 무엇이 나오는지 글로 ─────────────────────────────────────
function Draft({ plan, onBack, onRefresh }: { plan: StudioPlan; onBack: () => void; onRefresh: () => void }) {
  const video = plan.format === "video";
  const draft = plan.plan_status === "draft";
  const rows = draftRows(plan);
  const totalSec = (plan.plan_json.scenes ?? []).reduce((n, s) => n + (typeof s.timing_sec === "number" ? s.timing_sec : 0), 0);
  const nums = plan.unverified_numbers ?? [];
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [make, setMake] = useState<MakeMethod>("clay");
  const approve = async () => {
    setBusy(true); setProblem(null);
    const r = await post("studio_approve_draft", { plan_revision_id: plan.plan_revision_id, expected_plan_version: plan.version });
    if (!r.ok) {
      setBusy(false);
      const detail = Array.isArray(r.detail) ? ` (${(r.detail as string[]).map(blockerLabel).join(", ")})` : "";
      setProblem(r.code === "version_conflict" ? "초안이 다른 곳에서 바뀌었어요. 새로고침한 뒤 다시 확인해 주세요." : `${r.error ?? "승인하지 못했어요."}${detail}`);
      return;
    }
    // 릴스는 승인과 함께 작업 명세서를 만든다(0원). 실패해도 승인은 끝났고 명세서 화면에서 다시 요청한다.
    if (video) await post("explainer_request_plan", { plan_revision_id: plan.plan_revision_id, provider: make });
    setBusy(false);
    onRefresh();
  };
  return (
    <section aria-labelledby="sj-draft-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">DRAFT</p><h1 id="sj-draft-h">이 구성으로 만들까요?</h1>
          <p>{draft ? "화면마다 무엇이 나오는지 읽어 보세요. 고칠 곳은 코멘트로 적으면 다시 만들어요." : "승인한 초안이에요."}</p></div>
        <span className="sj-versiontag">{video ? `릴스 ${rows.length}장면${totalSec ? ` · ${totalSec}초` : ""}` : `카드뉴스 ${plan.plan_json.pages?.length ?? 0}장`}</span>
      </div>
      <ol className="sj-scenes">
        {rows.map((row) => (
          <li key={row.title} className="sj-scene">
            <h2>{row.title}</h2>
            <dl>{row.lines.map((l) => <div key={l.label}><dt>{l.label}</dt><dd>{l.text}</dd></div>)}</dl>
          </li>
        ))}
      </ol>
      {nums.length > 0 && <p className="sj-warnline" role="alert">자동 검사: 근거 자료에 없는 숫자가 있어요({nums.join(", ")}). 코멘트로 고쳐 다시 만들어 주세요.</p>}
      {draft && <CommentBox plan={plan} label="수정 코멘트" note="다시 만들면 이번 주 AI 초안 한도에서 나가요." onRefresh={onRefresh} />}
      {draft && video && <MakeChoice value={make} onChange={setMake} disabled={busy} />}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onBack}>← 다른 소재 보기</button>
        {draft && (
          <div><span className="sj-note">승인해도 돈은 나가지 않아요. 근거는 자동으로 검사해요.</span>
            <button type="button" className="sj-btn sj-main" disabled={busy || nums.length > 0} onClick={approve}>{busy ? "승인 중…" : "이 초안 승인"} <span aria-hidden="true">→</span></button></div>
        )}
      </div>
    </section>
  );
}

// ── ③ 작업 명세서: 실제 제작에 쓰는 세부 지시 ───────────────────────────────────
function Spec({ status, plan, production, onBack, onRefresh }: { status: StudioStatus; plan: StudioPlan; production: StudioProduction | null; onBack: () => void; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const fail = (r: Post, fallback: string) => { setBusy(false); setProblem(r.error ?? fallback); };
  const generateCard = async () => {
    const c = cardCost(plan);
    setBusy(true); setProblem(null);
    const r = await post("studio_generate", { topic_id: status.topic.id, format_intent: "card", plan_revision_id: plan.plan_revision_id,
      expected_topic_version: status.topic.version, expected_review_version: status.review?.version, expected_plan_version: plan.version,
      ...(isPhotoPlan(plan) && c.usd !== null ? { approve_usd: c.usd } : {}) });
    if (!r.ok) { fail(r, "제작을 시작하지 못했어요."); return; }
    setBusy(false); onRefresh();
  };
  const ex = production?.explainer ?? null;
  const d = ex?.episode?.directive ?? null;
  const cap = d ? Math.min(10, d.estimate.suggested_cap_usd) : 0;
  const provider = ex?.episode?.provider ?? null;
  const isClay = provider === CLAY_PROVIDER;
  const open = ex ? usableApproval(ex.approvals, provider) : null;
  const [make, setMake] = useState<MakeMethod>("clay");
  const buyVideo = async () => {
    if (!d) return;
    setBusy(true); setProblem(null);
    let approvalId = open?.approval_id ?? null;
    if (!approvalId) {
      const a = await post("open_spend_approval", { plan_revision_id: plan.plan_revision_id, stage: "스튜디오 명세서 승인", purpose: isClay ? "사진클레이 릴스 그림" : "설명형 릴스 그림·클립", cap_usd: cap,
        allowed_kinds: neededKinds(provider), approver_words: `스튜디오 [승인하고 제작] — 명세서와 상한 $${cap.toFixed(2)} 확인 후 승인`, ...(ex?.episode?.order_hash ? { order_hash: ex.episode.order_hash } : {}) });
      if (!a.ok) { fail(a, "결재를 열지 못했어요. 돈은 나가지 않았어요."); return; }
      approvalId = String(a.result?.approval_id ?? a.result?.id ?? "");
    }
    const r = await post("explainer_request_buy", { plan_revision_id: plan.plan_revision_id, spend_approval_id: approvalId });
    if (!r.ok) { fail(r, "제작을 요청하지 못했어요."); return; }
    setBusy(false); onRefresh();
  };
  const requestPlan = async () => {
    setBusy(true); setProblem(null);
    const r = await post("explainer_request_plan", { plan_revision_id: plan.plan_revision_id, ...(ex?.episode ? {} : { provider: make }) });
    if (!r.ok) { fail(r, "명세서를 요청하지 못했어요."); return; }
    setBusy(false); onRefresh();
  };
  const cost = cardCost(plan);
  const card = plan.format === "carousel";
  const waiting = !card && !d;
  return (
    <section aria-labelledby="sj-spec-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">WORK SPEC</p><h1 id="sj-spec-h">{waiting ? "작업 명세서를 만들고 있어요." : "이 명세서대로 제작할까요?"}</h1>
          <p>{waiting ? "내레이션 길이를 재서 장면별 지시와 금액을 계산해요. 돈은 나가지 않아요." : "실제 제작에 그대로 들어가는 지시예요. 승인하면 제작을 시작해요."}</p></div>
        <span className="sj-versiontag">{card ? "카드뉴스" : isClay ? "릴스 · 사진클레이" : "릴스"} 명세서</span>
      </div>
      {card && (
        <div className="sj-spec"><table>
          <thead><tr><th>장</th><th>화면 글자</th><th>이미지 생성 지시</th></tr></thead>
          <tbody>{(plan.plan_json.pages ?? []).map((pg, i) => (
            <tr key={i}><td>{i + 1}</td><td><b>{pg.heading.replace(/\[|\]/g, "")}</b>{pg.body && <p>{pg.body}</p>}</td>
              <td>{pg.role === "source" ? "이미지 없음 · 출처 목록 자동" : pg.image_prompt ?? "이미지 없음 · 글자 카드"}</td></tr>
          ))}</tbody>
        </table></div>
      )}
      {d && isClay && (
        <div className="sj-spec"><table>
          <thead><tr><th>#</th><th>화면 자막</th><th>그림 지시</th><th>째리</th><th>금액</th></tr></thead>
          <tbody>{d.slots.map((s) => (
            <tr key={s.n}><td>{s.n}</td><td>{(s.lines ?? [s.narration]).map((l, i) => <p key={i}>{l}</p>)}</td><td>{s.visual_prompt}</td>
              <td>{s.mascot_in_scene ? "그림 속" : "모서리"}</td><td>${s.image_est_usd.toFixed(3)}</td></tr>
          ))}</tbody>
        </table></div>
      )}
      {d && !isClay && (
        <div className="sj-spec"><table>
          <thead><tr><th>#</th><th>유형·길이</th><th>내레이션</th><th>시작 그림 지시</th><th>움직임 지시</th><th>금액</th></tr></thead>
          <tbody>{d.slots.map((s) => (
            <tr key={s.n}><td>{s.n}</td><td>{s.role === "mechanism" ? "3D 도해" : "실사"}<br />{s.clip_sec}초{s.candidates_planned > 1 ? ` × 후보 ${s.candidates_planned}` : ""}</td>
              <td>{s.narration}</td><td>{s.visual_prompt}</td><td>{s.motion_prompt}</td><td>${(s.image_est_usd + s.clip_est_usd * s.candidates_planned).toFixed(3)}</td></tr>
          ))}</tbody>
        </table></div>
      )}
      {d && <p className="sj-note">완성 길이 {(d.final_ms / 1000).toFixed(1)}초 · 예상 ${d.estimate.estimate_usd.toFixed(2)}{isClay ? `(그림 ${d.slots.length}장)` : `(그림 $${d.estimate.images_usd.toFixed(2)} + 영상 $${d.estimate.clips_usd.toFixed(2)})`} · 실패 재시도 예비 ${d.estimate.reserve_usd.toFixed(2)}{d.unverified.length > 0 ? ` · 미검증: ${d.unverified.join(", ")}` : ""}</p>}
      {waiting && !production?.activeJob && !ex?.episode && <MakeChoice value={make} onChange={setMake} disabled={busy} />}
      {waiting && !production?.activeJob && <div className="sj-row"><button type="button" className="sj-btn sj-main" disabled={busy} onClick={requestPlan}>{busy ? "요청 중…" : "명세서 만들기 (0원)"}</button></div>}
      {ex?.episode?.last_message && <p className="sj-warnline" role="alert">{ex.episode.last_message}</p>}
      {!waiting && <CommentBox plan={plan} label="초안부터 고치려면" note="코멘트대로 초안을 새로 만들어요. 이번 주 AI 초안 한도에서 나가요." onRefresh={onRefresh} />}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onBack}>← 초안 다시 보기</button>
        {card && <div><span className="sj-note">{cost.text}. 게시는 하지 않아요.</span>
          <button type="button" className="sj-btn sj-main" disabled={busy || cost.usd === null} onClick={generateCard}>{busy ? "요청 중…" : `승인하고 제작${cost.usd ? ` · $${cost.usd.toFixed(2)}` : ""}`} <span aria-hidden="true">→</span></button></div>}
        {d && <div><span className="sj-note">누르면 이 금액을 상한으로 결재해요. 이 안에서만 사고, 게시는 하지 않아요.</span>
          <button type="button" className="sj-btn sj-main" disabled={busy} onClick={buyVideo}>{busy ? "요청 중…" : `승인하고 제작 · 상한 $${cap.toFixed(2)}`} <span aria-hidden="true">→</span></button></div>}
      </div>
    </section>
  );
}

// ── ④ 제작 중(릴스): 영상을 사고 클립을 잇는 동안 ────────────────────────────────
function VideoMaking({ plan, production, onRefresh }: { plan: StudioPlan; production: StudioProduction; onRefresh: () => void }) {
  const ex = production.explainer!;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const passable = ex.slots.filter((s) => !s.selection && s.status !== "no_pass" && s.candidates.some((c) => c.status === "stored" && c.auto_verdict === "pass"));
  // 클립마다 사람이 판정·이유를 적던 것을 한 번에: 자동 검사를 통과한 클립을 쓰고, 사람은 완성 영상을 검수한다(0078).
  const useAll = async () => {
    setBusy(true); setProblem(null);
    for (const slot of passable) {
      for (const c of slot.candidates) {
        if (!canJudge(slot, c)) continue;
        const v = await post("explainer_verdict", { candidate_id: c.candidate_id, human_verdict: "pass" });
        if (!v.ok) { setBusy(false); setProblem(v.error ?? `${slot.n}번 클립을 확정하지 못했어요.`); onRefresh(); return; }
      }
      const pick = slot.candidates.find((c) => c.status === "stored" && c.auto_verdict === "pass");
      const r = await post("explainer_select", { slot_id: slot.slot_id, candidate_id: pick!.candidate_id, reason: "자동 검사 통과 — 완성 영상 검수에서 확인" });
      if (!r.ok) { setBusy(false); setProblem(r.error ?? `${slot.n}번 클립을 고르지 못했어요.`); onRefresh(); return; }
    }
    setBusy(false); onRefresh();
  };
  const waitingWorker = production.activeJob?.renderer === "explainer_buy" && production.activeJob.status === "queued";
  if (ex.episode?.provider === CLAY_PROVIDER) {
    return <ClayMaking plan={plan} production={production} onRefresh={onRefresh} />;
  }
  return (
    <section aria-labelledby="sj-make-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">MAKING</p><h1 id="sj-make-h">{plan.plan_json.scenes?.length ?? 0}개 장면{ex.episode?.provider === CLAY_PROVIDER ? " 그림을 그리고" : "을 제작하고"} 있어요.</h1>
          <p role="status" aria-live="polite">{production.activeJob ? "작업이 돌고 있어요. 창을 닫아도 이어져요." : "다음 단계를 눌러 이어 가세요."}</p></div>
      </div>
      {waitingWorker && <p className="sj-warnline" role="status">{ex.episode?.provider === CLAY_PROVIDER
        ? "그림 구매 작업이 순서를 기다리고 있어요. 보통 1~2분 안에 시작해요."
        : <>영상 구매 작업이 대기 중이에요. 영상 클립 구매 작업기는 자동으로 깨어나지 않아서, Claude 에게 &ldquo;구매 작업 돌려 줘&rdquo;라고 말해 주세요.</>}</p>}
      {passable.length > 0 && nextStep(ex) === "review_candidates" && (
        <div className="sj-row"><button type="button" className="sj-btn sj-main" disabled={busy} onClick={useAll}>{busy ? "확정하는 중…" : `자동 검사 통과한 클립 ${passable.length}개 쓰기`}</button></div>
      )}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <ExplainerProduction planId={plan.plan_revision_id} status={ex} activeJob={production.activeJob} />
    </section>
  );
}

// ── ④ 제작 중(사진클레이): 그림 그리기 → 영상 조립 → 검수, 지금 어디인지 ─────────────────
const CLAY_STEPS = ["그림 그리기", "영상 조립", "검수"] as const;
function ClayMaking({ plan, production, onRefresh }: { plan: StudioPlan; production: StudioProduction; onRefresh: () => void }) {
  const ex = production.explainer!;
  const job = production.activeJob;
  const st = clayStage(ex.episode?.state, job, ex.episode?.last_message);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const assemble = async () => {
    setBusy(true); setProblem(null);
    const r = await post("explainer_request_assemble", { plan_revision_id: plan.plan_revision_id });
    setBusy(false);
    if (!r.ok) setProblem(r.error ?? "조립을 요청하지 못했어요.");
    onRefresh();
  };
  return (
    <section aria-labelledby="sj-make-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">MAKING · 사진클레이</p><h1 id="sj-make-h">{st.title}</h1>
          <p role="status" aria-live="polite">{st.note}</p></div>
      </div>
      <ol className="sj-progress" aria-label="진행 단계">
        {CLAY_STEPS.map((label, i) => {
          const n = i + 1;
          const now = n === st.step;
          return (
            <li key={label} className={n < st.step ? "is-done" : now ? (st.stopped ? "is-stop" : "is-now") : undefined} aria-current={now ? "step" : undefined}>
              <b>{n < st.step ? "✓" : n}</b>{label}{now && job && <small>{job.status === "queued" ? "대기 중" : "진행 중"}</small>}
            </li>
          );
        })}
      </ol>
      {st.canAssemble && !job && (
        <div className="sj-row"><button type="button" className="sj-btn sj-main" disabled={busy} onClick={assemble}>{busy ? "요청 중…" : "영상 조립하기 (0원)"}</button></div>
      )}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <details className="sj-more"><summary>자세히 보기 (장면별 지시서·비용)</summary>
        <ExplainerProduction planId={plan.plan_revision_id} status={ex} activeJob={job} />
      </details>
    </section>
  );
}

// ── ④ 검수: 만들어진 것을 보고 OK ───────────────────────────────────────────────
function Results({ status, plan, files, problem, generating, production, onEdit, onRefresh }: {
  status: StudioStatus; plan: StudioPlan; files: StudioResultFile[]; problem: string | null; generating: boolean; production: StudioProduction | null;
  onEdit: () => void; onRefresh: () => void;
}) {
  const card = plan.format === "carousel";
  const job = plan.jobs[0] ?? null;
  const failed = card && job && (job.status === "failed" || job.status === "canceled");
  const review = production?.outputReview ?? null;
  const done = !generating && files.length > 0 && (!card || job?.status === "succeeded");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const retry = async () => {
    if (!job) return;
    setBusy(true);
    const c = cardCost(plan);
    const r = await post("studio_generate", { topic_id: status.topic.id, format_intent: "card", plan_revision_id: plan.plan_revision_id, retry_of: job.job_id,
      ...(isPhotoPlan(plan) && c.usd !== null ? { approve_usd: c.usd } : {}) });
    setBusy(false);
    setMsg(r.ok ? "다시 만들고 있어요. 이미 산 사진은 다시 사지 않아요." : r.error ?? "다시 만들지 못했어요.");
    onRefresh();
  };
  // 검수 항목별 체크를 없애고 [OK] 하나로: 운영자가 완성물을 보고 누른 것이 전 항목 확인이다(0078). 서버 검사는 그대로 돈다.
  const checksOf = (items: readonly (readonly [string, string])[]) => Object.fromEntries(items.map(([k]) => [k, true]));
  const ok = async () => {
    if (!review) return;
    setBusy(true); setMsg(null);
    const state = production?.explainer?.episode?.state;
    const stages: [string, [string, string][]][] = state === "auto_qa_pass" ? [["process", PROCESS_CHECKS], ["quality", QUALITY_CHECKS]] : state === "process_review_pass" ? [["quality", QUALITY_CHECKS]] : [];
    for (const [stage, items] of stages) {
      const r = await post("explainer_review", { plan_revision_id: plan.plan_revision_id, stage, outcome: "pass", checks: checksOf(items) });
      if (!r.ok) { setBusy(false); setMsg(r.error ?? "검수를 기록하지 못했어요."); onRefresh(); return; }
    }
    const items = card ? [...CHECKS.carousel, ...(review.hasReel ? REEL_CHECKS : [])] : CHECKS.video;
    const r = await post("output_review_action", { review_id: review.id, expected_version: review.version, action: "approve", checklist: checksOf(items) });
    setBusy(false);
    if (!r.ok) setMsg(r.error ?? "검수를 기록하지 못했어요.");
    onRefresh();
  };
  const images = files.filter((f) => f.mime.startsWith("image/")).sort((a, b) => a.position - b.position);
  const videos = files.filter((f) => f.mime.startsWith("video/"));
  return (
    <section aria-labelledby="sj-res-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">{generating ? "MAKING" : "REVIEW"}</p>
          <h1 id="sj-res-h">{generating ? "콘텐츠를 만들고 있어요." : failed ? "제작을 마치지 못했어요." : done ? "완성본을 확인해 주세요." : "결과 파일을 확인하고 있어요."}</h1>
          <p role="status" aria-live="polite">{generating ? (job?.status === "queued" ? "제작 순서를 기다리고 있어요." : "조립하고 자동 검사를 하고 있어요.")
            : failed ? `실패 이유: ${job?.error_code ?? "원인 미상"}` : done ? "괜찮으면 OK, 고칠 곳이 있으면 코멘트를 적어 주세요." : "제작은 끝났지만 파일을 아직 읽지 못했어요."}</p></div>
      </div>
      {problem && <p className="sj-error" role="alert">결과를 읽지 못했어요: {problem}</p>}
      <article className="sj-result">
        {images.length > 0 && <div className="sj-gallery">{images.map((f) => f.url
          // eslint-disable-next-line @next/next/no-img-element
          ? <a key={f.position} href={f.url} target="_blank" rel="noreferrer"><img src={f.url} alt={`${f.role} ${f.position}`} loading="lazy" /></a>
          : <span key={f.position} className="sj-muted">{f.position}: {f.urlError ?? "미리보기 불가(로컬 저장)"}</span>)}</div>}
        {videos.map((v) => v.url && <video key={v.position} src={v.url} controls preload="metadata" className="sj-video" aria-label="세로 영상" />)}
        {failed && <div className="sj-result-footer"><button type="button" className="sj-btn" disabled={busy} onClick={retry}>{busy ? "요청 중…" : "다시 만들기"}</button></div>}
        {msg && <p className="sj-message" role="status">{msg}</p>}
      </article>
      {done && <CommentBox plan={plan} label="수정 코멘트" note="코멘트대로 초안부터 새로 만들어요. 제작비가 다시 들 수 있어요." onRefresh={onRefresh} />}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onEdit}>← 초안 보기</button>
        {done && <div><span className="sj-note">OK 를 눌러도 아직 게시되지 않아요.</span>
          <button type="button" className="sj-btn sj-main" disabled={busy || !review} onClick={ok}>{busy ? "기록 중…" : "OK — 인스타 등록으로"} <span aria-hidden="true">→</span></button></div>}
      </div>
    </section>
  );
}

// ── ⑤ 인스타 등록: 캡션·시각을 보고 한 번에 ─────────────────────────────────────
function Publish({ status, plan, files, publish, production, onDone, onRefresh }: {
  status: StudioStatus; plan: StudioPlan; files: StudioResultFile[]; publish: StudioPublish | null; production: StudioProduction | null; onDone: () => void; onRefresh: () => void;
}) {
  const reel = plan.format === "video";
  const postType = reel ? "reel" : "carousel";
  const usable = (publish?.accounts ?? []).filter((a) => a.postTypes.includes(postType));
  const req = publish?.request ?? null;
  const first = plan.plan_json.pages?.[0]?.heading?.replace(/\[|\]/g, "") ?? plan.plan_json.scenes?.[0]?.narration ?? status.topic.question;
  const [caption, setCaption] = useState(req?.caption ?? (reel ? `${first}\n\n${publish?.aiLabel ?? "AI 생성 영상"}` : first));
  const [acc, setAcc] = useState(usable[0]?.id ?? "");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => { setWhen((w) => w || defaultPublishAt(Date.now(), PUBLISH_WINDOW)); }, []);
  const stop = (r: Post, fallback: string) => { setBusy(false); setProblem(r.error ?? fallback); onRefresh(); };
  const register = async () => {
    const accLabel = usable.find((a) => a.id === acc)?.label ?? "";
    if (!window.confirm(`인스타에 공개 게시합니다.\n\n계정: ${accLabel}\n시각: ${when.replace("T", " ")} (한국)\n캡션: ${caption}\n\n진행할까요?`)) return;
    setBusy(true); setProblem(null);
    let id = req?.id ?? "", version = req?.version ?? 0, st = req?.status ?? "", digest = req?.approval_digest ?? null;
    if (!req) {
      const c = await post("create_publication", { output_review_id: production?.outputReview?.id, account_id: acc, caption, post_type: postType, publish_at: new Date(`${when}:00+09:00`).toISOString() });
      if (!c.ok) { stop(c, "발행안을 만들지 못했어요."); return; }
      id = String(c.result?.request_id); version = Number(c.result?.version); st = String(c.result?.status);
    }
    const NEEDS = { submit: "draft", approve: "awaiting_approval", schedule: "approved" } as const;
    for (const action of ["submit", "approve", "schedule"] as const) {
      if (st !== NEEDS[action]) continue;
      const r = await post("publication_action", { request_id: id, expected_version: version, action, ...(action === "approve" ? { expected_digest: digest } : {}) });
      if (!r.ok) { stop(r, "등록을 마치지 못했어요."); return; }
      version = Number(r.result?.version); st = String(r.result?.status); digest = (r.result?.approval_digest as string | null) ?? digest;
    }
    setBusy(false); onRefresh();
  };
  const windowProblem = publishWindowProblem(when);
  const canRegister = !req || ["draft", "awaiting_approval", "approved"].includes(req.status);
  return (
    <section aria-labelledby="sj-pub-h">
      <div className="sj-intro">
        <div><p className="sj-kicker">PUBLISH</p><h1 id="sj-pub-h">{req?.status === "published" ? "인스타에 게시됐어요." : req?.status === "scheduled" ? "등록했어요. 예약 시각에 게시돼요." : "인스타에 등록할까요?"}</h1>
          <p>{req?.status === "scheduled" ? `예약 ${kstMinute(req.publish_at)} (한국). 게시 작업기가 도는 때에 맞춰 늦어질 수 있어요.` : "캡션과 시각만 확인하면 돼요."}</p></div>
      </div>
      {!publish && <p className="sj-error" role="alert">게시 정보를 읽지 못했어요. 새로고침해 주세요.</p>}
      {files.filter((f) => f.mime.startsWith("video/")).map((v) => v.url && <video key={v.position} src={v.url} controls preload="metadata" className="sj-video" aria-label="세로 영상" />)}
      {req?.external_url && <p><a className="sj-btn" href={req.external_url} target="_blank" rel="noreferrer">게시물 보기</a></p>}
      {canRegister && publish && (
        <div className="sj-editor">
          {usable.length === 0 ? <p className="sj-warnline" role="alert">{reel ? "릴스" : "카드뉴스"}를 올릴 수 있는 계정이 없어요. <Link href="/drinks/publish">발행 화면</Link>에서 계정을 확인해 주세요.</p> : usable.length > 1 && (
            <label className="sj-field">계정<select value={acc} onChange={(e) => setAcc(e.target.value)}>{usable.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>
          )}
          <label className="sj-field">캡션<textarea value={caption} rows={5} readOnly={Boolean(req)} onChange={(e) => setCaption(e.target.value)} /></label>
          <label className="sj-field">게시 시각(한국)<input type="datetime-local" value={when} readOnly={Boolean(req)} onChange={(e) => setWhen(e.target.value)} /></label>
          {windowProblem && <p className="sj-warnline" role="alert">{windowProblem}</p>}
        </div>
      )}
      {req && !canRegister && req.status !== "published" && <RequestActions id={req.id} version={req.version} status={req.status} digest={req.approval_digest} summary={req.caption ?? ""} />}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onDone}>다음 소재 고르기</button>
        {canRegister && publish && usable.length > 0 && (
          <button type="button" className="sj-btn sj-main" disabled={busy || !when || !caption.trim() || Boolean(windowProblem)} onClick={register}>{busy ? "등록 중…" : "인스타에 등록"} <span aria-hidden="true">→</span></button>
        )}
      </div>
    </section>
  );
}
