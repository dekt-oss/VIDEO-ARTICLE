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
import { autoCaption } from "@/lib/drinks/caption";
import { CLAY_PROVIDER, MAKE_METHOD_LABEL, clayStage, PROCESS_CHECKS, QUALITY_CHECKS, canJudge, kstMinute, neededKinds, nextStep, usableApproval, type ExplainerStatus, type MakeMethod } from "@/lib/drinks/explainerQueue";
import { blockerLabel } from "@/lib/drinks/model";
import { relativeDayLabel } from "@/lib/date";
import { PICK_FORMATS, PICK_FORMAT_HINT, PICK_FORMAT_LABEL } from "@/lib/drinks/pickModal";
import { PUBLISH_WINDOW, publishWindowProblem } from "@/lib/drinks/publishWindow";
import {
  BATCH_MAX, activePlan, batchTargets, cardCost, defaultFormat, defaultPublishAt, draftRows, formatAction, isPhotoPlan, progressText, studioPhase,
  type DraftRow, type FormatChoice, type StudioLane, type StudioPlan, type StudioScreen, type StudioStatus,
} from "@/lib/drinks/studio";

export interface StudioCollectItem {
  key: string; topicId: string | null; candidateId: string | null; title: string; question: string; kind: string; origin: string;
  angle: string | null; inProgress: boolean; payload: Record<string, unknown>;
  /** 이미 시작한 유형·초안이 있는 유형(card·explainer) */
  started: string[]; drafts: string[];
  /** 수집한 날(KST, YYYY-MM-DD). 이미 만들고 있는 소재는 null */
  collectedOn: string | null;
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
  /** 소재의 술 종류(캡션 해시태그) */
  categories?: string[];
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

export default function StudioClient({ items, problems, status, statusProblem, files, resultProblem, selectedTopicId, today, lane, production, publish, pickContext, summary, header, footer }: {
  items: StudioCollectItem[]; problems: string[]; status: StudioStatus | null; statusProblem: string | null;
  files: StudioResultFile[]; resultProblem: string | null; selectedTopicId: string | null;
  /** 서버가 정한 오늘(KST) — 자정 무렵 서버·브라우저의 "오늘/어제"가 갈리지 않게 */
  today: string;
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
    // 주소에 다른 소재가 열려 있으면 그 소재 화면(초안 등)으로 튀지 않게 소재 목록 주소로 간다(2026-11-12 운영자: 고른 것과 다른 초안이 떴다).
    if (selectedTopicId) go(null); else router.refresh();
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
        <Collect summary={summary} today={today} items={items} problems={problems} selKey={selKey} sel={sel} busy={busy}
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
      {screen === "blocked" && <Blocked code={phase.code} status={status} busy={busy} onBack={() => setOverride("collect")} onRefresh={() => router.refresh()}
        onRetry={() => { const it = status ? items.find((i) => i.topicId === status.topic.id) : null; if (it) prepare(it); }} />}
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
function Collect({ summary, today, items, problems, selKey, onSelect, checked, onCheck, onClearChecked, onStartMany, sel, busy, current, format, onFormat, onPrepare, onAdd, onOpen }: {
  checked: string[]; onCheck: (k: string) => void; onClearChecked: () => void; onStartMany: (list: StudioCollectItem[], f: StudioLane) => void;
  summary?: string; today: string; items: StudioCollectItem[]; problems: string[]; selKey: string | null; onSelect: (k: string) => void; sel: StudioCollectItem | null; busy: boolean;
  current: ReturnType<typeof studioPhase> | null; format: FormatChoice; onFormat: (f: FormatChoice) => void;
  onPrepare: (i: StudioCollectItem) => void; onAdd: (i: StudioCollectItem, f: StudioLane) => void; onOpen: (topicId: string, f: StudioLane) => void;
}) {
  const action = sel ? formatAction(sel, format) : null;
  const many = items.filter((i) => checked.includes(i.key));
  const manyTargets = batchTargets(many, format);
  // 목록을 수집한 날로 나눈다 — 날이 바뀌는 곳에 머리줄을 단다(items 는 서버가 날짜 최신순으로 준다).
  const perDay = new Map<string, number>();
  for (const i of items) if (i.collectedOn) perDay.set(i.collectedOn, (perDay.get(i.collectedOn) ?? 0) + 1);
  const dayHead = (t: StudioCollectItem, idx: number) => {
    if (idx > 0 && (items[idx - 1].collectedOn ?? "") === (t.collectedOn ?? "")) return null;
    if (!t.collectedOn) return <li key="h:mine" className="sj-day"><strong>이어 만들고 있는 소재</strong></li>;
    const rel = relativeDayLabel(t.collectedOn, new Date(`${today}T12:00:00+09:00`));
    return <li key={`h:${t.collectedOn}`} className="sj-day"><strong>{rel === "오늘" ? "오늘 새로 수집" : `${rel} 수집`}</strong> <span>{t.collectedOn} · {perDay.get(t.collectedOn)}개</span></li>;
  };
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
          <p>수집된 질문에서 소재를 고르면, 초안까지 준비해 드려요.</p>
          <p>여러 개 한 번에: 소재 앞 네모를 체크하면 ‘선택한 소재’ 칸에 모여요(최대 {BATCH_MAX}개). 빼려면 체크를 다시 누르거나 그 칸의 [빼기]를 눌러요.</p></div>
        <span className="sj-note">고를 수 있는 소재 · {items.length}개</span>
      </div>
      {summary && <p className="sj-note">{summary}</p>}
      {problems.map((p) => <p key={p} className="sj-error" role="alert">읽지 못한 칸이 있어요 — {p}</p>)}
      {items.length === 0 ? <p className="sj-empty">지금 자동으로 초안까지 만들 수 있는 소재가 없어요. 수집이 돌면 여기에 나타나요.</p> : (
        <div className="sj-layout">
          <ul className="sj-stack" aria-label="수집된 소재">
            {items.flatMap((t, idx) => [dayHead(t, idx), (
              <li key={t.key} className="sj-topic-row">
                <label className="sj-topic-check">
                  <input type="checkbox" id={`sj-chk-${t.key}`} aria-label={`${t.title} 함께 만들기`} checked={checked.includes(t.key)} disabled={busy || (!checked.includes(t.key) && checked.length >= BATCH_MAX)} onChange={() => onCheck(t.key)} />
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
            )])}
            {many.length > 0 && <li className="sj-many-jump"><button type="button" className="sj-btn sj-main" onClick={() => document.getElementById("sj-many")?.scrollIntoView({ behavior: "smooth" })}>선택한 {many.length}개 만들러 가기 <span aria-hidden="true">↑</span></button></li>}
          </ul>
          {many.length > 0 ? (
            <aside id="sj-many" className="sj-picked" aria-label="선택한 소재들">
              <div><span className="sj-label">선택한 소재 {many.length}개{many.length >= BATCH_MAX ? " · 한 번에 최대" : ""}</span>
                <ul className="sj-picked-list">{many.map((i) => (
                  <li key={i.key}><span>{i.title}</span>
                    <button type="button" className="sj-unpick" disabled={busy} aria-label={`${i.title} 빼기`} onClick={() => { onCheck(i.key); document.getElementById(`sj-chk-${i.key}`)?.focus(); }}>빼기</button></li>
                ))}</ul>
                {many.length < BATCH_MAX && <p className="sj-note">목록에서 {BATCH_MAX - many.length}개 더 체크할 수 있어요.</p>}</div>
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

function Blocked({ code, status, busy, onBack, onRefresh, onRetry }: { code?: string; status: StudioStatus | null; busy: boolean; onBack: () => void; onRefresh: () => void; onRetry: () => void }) {
  const script = code === "script_check_failed";
  const offTopic = code === "evidence_off_topic";
  // 2026-11-17 운영자: "막힌 이유 보여줘서 어쩌자는거야" — 해결안이 있으면 그것을 맨 앞에, 버튼 하나로.
  const rescue = status?.last?.rescue ?? null;
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const applyRescue = async () => {
    if (!status?.last) return;
    setWorking(true); setProblem(null);
    const r = await post("apply_rescue", { request_id: status.last.request_id });
    setWorking(false);
    if (!r.ok) { setProblem(r.error ?? "해결안을 적용하지 못했어요."); return; }
    onRefresh();
  };
  return (
    <section aria-labelledby="sj-block-h" className="sj-progress-wrap">
      <p className="sj-kicker">NEEDS A DIFFERENT TOPIC</p>
      <h1 id="sj-block-h">{script ? "이 질문으로는 믿을 만한 초안을\n아직 만들지 못했어요." : offTopic ? "모은 자료가 이 질문에\n답하지 못해요." : "이 질문에 답할 자료가\n아직 충분하지 않아요."}</h1>
      <p className="sj-status">{script ? "확인된 내용 안에서 다시 써 봤지만 검사를 통과하지 못했어요."
        : offTopic ? "자료는 있지만 제목이 묻는 핵심과 다른 이야기라, 엉뚱한 영상이 되지 않게 멈췄어요."
        : "추가 자료까지 확인했지만, 핵심 내용을 뒷받침하지 못했어요."}</p>
      {rescue?.question ? (
        <div className="sj-rescue">
          <p><b>이렇게 고칠게요:</b> 질문을 <b>“{rescue.question}”</b>(으)로 좁히면 모은 자료로 답할 수 있어요.</p>
          {rescue.why_ko && <p className="sj-note">이유: {rescue.why_ko}</p>}
          {rescue.answer_ko && <p className="sj-note">자료로 할 수 있는 답: {rescue.answer_ko}</p>}
          <button type="button" className="sj-btn sj-main" disabled={busy || working} onClick={applyRescue}>{working ? "적용 중…" : "해결안 적용하고 다시 만들기"} <span aria-hidden="true">→</span></button>
          <span className="sj-note">자료 확인과 초안을 다시 만들어요. 이번 주 AI 초안 한도에서 나가요.</span>
        </div>
      ) : script ? (
        <div className="sj-rescue">
          <p><b>이렇게 고칠게요:</b> 확인된 내용 안에서 초안을 한 번 더 써 볼게요. 그래도 안 되면 다른 소재를 권해요.</p>
          <button type="button" className="sj-btn sj-main" disabled={busy} onClick={onRetry}>초안 다시 만들기 <span aria-hidden="true">→</span></button>
          <span className="sj-note">이번 주 AI 초안 한도에서 나가요.</span>
        </div>
      ) : (
        <p className="sj-note">확인되지 않은 내용으로 초안을 만들지 않았어요. 이 질문으로는 고칠 방법을 찾지 못해서 다른 소재를 고르는 게 빨라요.</p>
      )}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <button type="button" className={rescue?.question || script ? "sj-btn" : "sj-btn sj-main"} onClick={onBack}>다른 소재 고르기 <span aria-hidden="true">→</span></button>
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
        {legacy && <Link className="sj-btn sj-main" href={`/drinks/work/${status.topic.id}?detail=1`}>기존 작업공간에서 열기</Link>}
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

// ── 장면 글 바로 고치기(0087, 0원) ─────────────────────────────────────────────
// 작성 중 초안은 그 자리에서 고치고, 승인한 초안(지시서 단계)은 고친 글로 새 초안이 된다 — 다시 [이 초안 승인] 한 번이면 지시서를 새로 만든다.
function SceneList({ plan, rows, editable, onRefresh, onDirty }: { plan: StudioPlan; rows: DraftRow[]; editable: boolean; onRefresh: () => void;
  /** 편집기가 열려 있거나 저장 중이면 true — 부모가 승인·제작 버튼을 잠근다(저장 안 한 글로 사지 않게, 코덱스 리뷰) */
  onDirty?: (dirty: boolean) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  useEffect(() => { onDirty?.(open !== null || busy); }, [open, busy, onDirty]);
  useEffect(() => () => onDirty?.(false), [onDirty]);   // 편집기가 사라지면 부모 잠금도 푼다
  // 한 장면의 칸을 한 번에 보낸다(반쪽 저장 없음). 실패하면 입력을 그대로 두고, 버전 충돌일 때만 새로 읽는다.
  const save = async (row: DraftRow) => {
    const edits = (row.edits ?? []).map((e) => ({ n: e.n, field: e.field, text: (vals[`${e.n}:${e.field}`] ?? e.text).trim(), was: e.text.trim() }))
      .filter((e) => e.text !== e.was).map(({ n, field, text }) => ({ n, field, text }));
    if (edits.length === 0) { setMsg({ text: "바뀐 글이 없어요." }); return; }
    setBusy(true); setMsg(null);
    const r = await post("studio_edit_scene", { plan_revision_id: plan.plan_revision_id, expected_version: plan.version, edits });
    setBusy(false);
    if (!r.ok) {
      const conflict = r.code === "version_conflict" || r.code === "plan_not_current";
      setMsg({ text: conflict ? "초안이 다른 곳에서 바뀌었어요. 새로 읽었으니 다시 고쳐 주세요." : `${r.error ?? "저장하지 못했어요."} 지금 초안은 그대로이고, 적은 글은 남아 있어요.`, bad: true });
      if (conflict) onRefresh();
      return;
    }
    setOpen(null); setVals({});
    setMsg({ text: r.result?.new_draft ? "고친 글로 새 초안을 만들었어요. [이 초안 승인]을 누르면 지시서를 새로 만들어요(0원)." : "저장했어요(0원)." });
    onRefresh();
  };
  return (
    <>
      <ol className="sj-scenes">
        {rows.map((row, idx) => (
          <li key={row.title} className="sj-scene">
            <div className="sj-scene-head">
              <h2>{row.title}</h2>
              {editable && row.edits && row.edits.length > 0 && (
                <button type="button" className="sj-btn sj-quiet sj-edit" disabled={busy} aria-expanded={open === idx} onClick={() => { setOpen(open === idx ? null : idx); setVals({}); }}>{open === idx ? "닫기" : "고치기"}</button>
              )}
            </div>
            {open === idx && row.edits ? (
              <div className="sj-edit-box">
                {row.edits.map((e) => (
                  <label key={`${e.n}:${e.field}`} className="sj-field">{e.label}
                    <textarea rows={3} maxLength={400} value={vals[`${e.n}:${e.field}`] ?? e.text} disabled={busy}
                      onChange={(ev) => setVals((m) => ({ ...m, [`${e.n}:${e.field}`]: ev.target.value }))} />
                  </label>
                ))}
                <div className="sj-row"><button type="button" className="sj-btn sj-main" disabled={busy} onClick={() => save(row)}>{busy ? "저장 중…" : "저장 (0원)"}</button></div>
              </div>
            ) : (
              <dl>{row.lines.map((l) => <div key={l.label}><dt>{l.label}</dt><dd>{l.text}</dd></div>)}</dl>
            )}
          </li>
        ))}
      </ol>
      {editable && <p className="sj-note">[고치기]로 글을 바로 고쳐요(0원). 고친 글은 지시서를 만들 때 대본 자동 검사를 다시 거치고, 근거에 없는 숫자는 승인 때 막혀요.</p>}
      {msg && <p className={msg.bad ? "sj-error" : "sj-message"} role={msg.bad ? "alert" : "status"}>{msg.text}</p>}
    </>
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
  const [editing, setEditing] = useState(false);
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
          <p>{draft ? "화면마다 무엇이 나오는지 읽어 보세요. 한 장면만 바꾸려면 [고치기], 전체 방향을 바꾸려면 아래에 수정 방향을 적어요." : "승인한 초안이에요."}</p></div>
        <span className="sj-versiontag">{video ? `릴스 ${rows.length}장면${totalSec ? ` · ${totalSec}초` : ""}` : `카드뉴스 ${plan.plan_json.pages?.length ?? 0}장`}</span>
      </div>
      <SceneList plan={plan} rows={rows} editable={draft} onRefresh={onRefresh} onDirty={setEditing} />
      {nums.length > 0 && <p className="sj-warnline" role="alert">근거 자료에 없는 숫자가 있어요({nums.join(", ")}). 그 장면을 [고치기]로 바로 고치거나, 아래에 수정 방향을 적어 주세요.</p>}
      {draft && <CommentBox plan={plan} label="수정 방향 (AI 가 대본 전체를 다시 써요)" note="한 장면만 바꿀 거면 위의 [고치기]가 빨라요. 다시 쓰기는 이번 주 AI 초안 한도에서 나가요." onRefresh={onRefresh} />}
      {draft && video && <MakeChoice value={make} onChange={setMake} disabled={busy} />}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onBack}>← 다른 소재 보기</button>
        {draft && (
          <div><span className="sj-note">승인해도 돈은 나가지 않아요. 근거는 자동으로 검사해요.</span>
            <button type="button" className="sj-btn sj-main" disabled={busy || editing || nums.length > 0} title={editing ? "고치던 글을 먼저 저장하거나 닫아 주세요" : undefined} onClick={approve}>{busy ? "승인 중…" : editing ? "고치던 글을 먼저 저장하세요" : "이 초안 승인"} <span aria-hidden="true">→</span></button></div>
        )}
      </div>
    </section>
  );
}

/** 지시서 작업 오류를 운영자 말로. 저장된 문장은 'code: 설명' 모양이라 코드명을 떼고 쉬운 설명을 앞에 둔다. */
function planErrorText(code: string | null | undefined, message: string | null | undefined): string {
  const body = (message ?? "").replace(/^[a-z_]+:\s*/, "").trim();
  const known: Record<string, string> = {
    hook_text_overflow: "첫 화면 자막이 한 줄에 다 들어가지 않아요.",
    visual_claims_missing: "장면별 화면 설명표가 없어요.",
    duration_out_of_range: "목소리로 읽은 길이가 정해진 범위를 벗어나요.",
  };
  return [code ? known[code] : null, body].filter(Boolean).join(" ") || "원인을 읽지 못했어요.";
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
  const requestPlan = async (switchTo?: MakeMethod) => {
    setBusy(true); setProblem(null);
    const r = await post("explainer_request_plan", { plan_revision_id: plan.plan_revision_id, ...(switchTo ? { provider: switchTo } : ex?.episode ? {} : { provider: make }) });
    if (!r.ok) { fail(r, "명세서를 요청하지 못했어요."); return; }
    setBusy(false); onRefresh();
  };
  const cost = cardCost(plan);
  const card = plan.format === "carousel";
  const waiting = !card && !d;
  // 지시서 작업이 실패해 멈춘 편: 원문 오류 대신 무엇이 막혔고 어떻게 고칠지 + 버튼 하나(2026-11-17).
  const failedPlan = waiting && !production?.activeJob && ex?.episode?.state === "plan_draft" && Boolean(ex.episode.last_message);
  // 고칠 수 있는 때: 작성 중이거나, 승인했어도 아직 돈·제작을 시작하지 않았을 때(서버가 같은 조건으로 다시 막는다).
  const editable = plan.plan_status === "draft" || (plan.plan_status === "approved" && (card ? plan.jobs.length === 0 : !open && !ex?.episode?.approval_id));
  const [editing, setEditing] = useState(false);
  const lockText = "고치던 글을 먼저 저장하세요";
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
      {failedPlan && (
        <div className="sj-rescue" role="alert">
          {provider !== CLAY_PROVIDER ? <>
            <p><b>영상 클립 방식의 검사에 걸려 지시서를 만들지 못했어요.</b> {planErrorText(ex?.episode?.last_code, ex?.episode?.last_message)}</p>
            <p><b>이렇게 고칠게요:</b> 사진클레이 방식으로 바꿔 지시서를 다시 만들어요. 돈은 들지 않아요.</p>
            <button type="button" className="sj-btn sj-main" disabled={busy} onClick={() => requestPlan(CLAY_PROVIDER)}>{busy ? "요청 중…" : "사진클레이로 다시 만들기 (0원)"}</button>
          </> : <>
            <p><b>지시서를 만들다 멈췄어요.</b> {planErrorText(ex?.episode?.last_code, ex?.episode?.last_message)}</p>
            <p><b>이렇게 고칠게요:</b> 아래 [장면 대사 고치기]에서 그 장면을 고치거나 수정 방향을 적어 주세요. 대본은 그대로 두고 다시 만들어도 되는 문제면 아래 버튼만 누르세요.</p>
            <button type="button" className="sj-btn sj-main" disabled={busy} onClick={() => requestPlan()}>{busy ? "요청 중…" : "지시서 다시 만들기 (0원)"}</button>
          </>}
        </div>
      )}
      {waiting && !production?.activeJob && !failedPlan && <div className="sj-row"><button type="button" className="sj-btn sj-main" disabled={busy} onClick={() => requestPlan()}>{busy ? "요청 중…" : "명세서 만들기 (0원)"}</button></div>}
      {editable && (
        <details className="sj-more" open={failedPlan}><summary>{card ? "카드 글 고치기" : "장면 대사 고치기"} (0원{plan.plan_status === "approved" ? " · 고치면 새 초안이 되고, [이 초안 승인]을 누르면 다시 만들어요" : ""})</summary>
          <SceneList plan={plan} rows={draftRows(plan)} editable onRefresh={onRefresh} onDirty={setEditing} />
        </details>
      )}
      {(!waiting || failedPlan) && <CommentBox plan={plan} label="수정 방향 (AI 가 대본 전체를 다시 써요)" note="코멘트대로 초안을 새로 만들어요. 이번 주 AI 초안 한도에서 나가요." onRefresh={onRefresh} />}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onBack}>← 초안 다시 보기</button>
        {card && <div><span className="sj-note">{cost.text}. 게시는 하지 않아요.</span>
          <button type="button" className="sj-btn sj-main" disabled={busy || editing || cost.usd === null} onClick={generateCard}>{busy ? "요청 중…" : editing ? lockText : `승인하고 제작${cost.usd ? ` · $${cost.usd.toFixed(2)}` : ""}`} <span aria-hidden="true">→</span></button></div>}
        {d && <div><span className="sj-note">누르면 이 금액을 상한으로 결재해요. 이 안에서만 사고, 게시는 하지 않아요.</span>
          <button type="button" className="sj-btn sj-main" disabled={busy || editing} onClick={buyVideo}>{busy ? "요청 중…" : editing ? lockText : `승인하고 제작 · 상한 $${cap.toFixed(2)}`} <span aria-hidden="true">→</span></button></div>}
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
  // 캡션 자동 채움(2026-11-18 운영자 "부실하다·술째리고 홍보"): 릴스는 첫 장면 질문 + 마지막 장면 답, 카드는 표지 제목 + 핵심 결론.
  const scenes = plan.plan_json.scenes ?? [];
  const lead = reel ? scenes[0]?.narration ?? status.topic.question : plan.plan_json.pages?.[0]?.heading?.replace(/\[|\]/g, "") ?? status.topic.title;
  const answer = reel ? scenes[scenes.length - 1]?.narration ?? status.review?.core_takeaway : status.review?.core_takeaway;
  const [caption, setCaption] = useState(req?.caption ?? autoCaption({ title: lead, takeaway: answer, categories: publish?.categories ?? [] }));
  const [acc, setAcc] = useState(usable[0]?.id ?? "");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // 예약 시각 초기값: 이미 적어 둔 발행안이면 그 시각(덮어쓰지 않는다), 없으면 15분 뒤.
  useEffect(() => { setWhen((w) => w || (req?.publish_at ? new Date(Date.parse(req.publish_at) + 9 * 3_600_000).toISOString().slice(0, 16) : defaultPublishAt(Date.now(), PUBLISH_WINDOW))); }, [req?.publish_at]);
  const stop = (r: Post, fallback: string) => { setBusy(false); setProblem(r.error ?? fallback); onRefresh(); };
  const [note, setNote] = useState<string | null>(null);
  // 작성 중(또는 아직 없음)일 때만 시각을 고를 수 있다. 승인 대기·승인된 발행안은 적어 둔 시각 그대로 마무리한다(0086 은 작성 중에만 시각을 바꾼다).
  const pickTime = !req || req.status === "draft";
  // [지금 게시] / [예약 게시] — 발행안 만들기 → 승인 요청 → 승인 → 예약을 publication_go 한 번으로(0086). 지금이면 발행 워커를 바로 깨운다.
  const register = async (now: boolean) => {
    const accLabel = usable.find((a) => a.id === acc)?.label ?? "";
    const at = now ? new Date() : new Date(`${when}:00+09:00`);
    if (!window.confirm(`인스타에 공개 게시합니다.\n\n계정: ${accLabel}\n시각: ${now ? "지금 바로" : `${when.replace("T", " ")} (한국) 예약`}\n캡션: ${caption}\n\n진행할까요?`)) return;
    setBusy(true); setProblem(null);
    let id = req?.id ?? "", version = req?.version ?? 0;
    if (!req) {
      const c = await post("create_publication", { output_review_id: production?.outputReview?.id, account_id: acc, caption, post_type: postType, publish_at: at.toISOString() });
      if (!c.ok) { stop(c, "발행안을 만들지 못했어요."); return; }
      id = String(c.result?.request_id); version = Number(c.result?.version);
    }
    const r = await post("publication_go", { request_id: id, expected_version: version, ...(pickTime ? { publish_at: at.toISOString() } : {}) });
    if (!r.ok) { stop(r, "게시를 걸지 못했어요."); return; }
    // 지금 게시인데 발행 작업기를 바로 못 깨웠으면 숨기지 않는다 — 예약 확인 작업이 돌 때 올라간다.
    if (r.result?.due_now && r.dispatch && !r.dispatch.triggered) setNote("게시를 걸었지만 작업기를 바로 깨우지 못했어요. 예약 확인 작업이 돌 때(보통 몇 분, 늦으면 몇 시간) 올라가요. 급하면 Claude 에게 \u201c게시 작업 돌려 줘\u201d라고 말해 주세요.");
    setBusy(false); onRefresh();
  };
  const windowProblem = publishWindowProblem(when);
  const nowProblem = publishWindowProblem(new Date(Date.now() + 9 * 3_600_000).toISOString().slice(0, 16));   // 지금(한국)이 게시 가능 시간인가
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
          <label className="sj-field">{pickTime ? "예약 시각(한국 · [예약 게시]에만 씀)" : "게시 시각(한국 · 이미 정한 시각)"}<input type="datetime-local" value={when} readOnly={!pickTime} onChange={(e) => setWhen(e.target.value)} /></label>
          {windowProblem && <p className="sj-warnline" role="alert">{windowProblem}</p>}
        </div>
      )}
      {req && !canRegister && req.status !== "published" && <RequestActions id={req.id} version={req.version} status={req.status} digest={req.approval_digest} summary={req.caption ?? ""} />}
      {problem && <p className="sj-error" role="alert">{problem}</p>}
      {note && <p className="sj-warnline" role="status">{note}</p>}
      {pickTime && nowProblem && <p className="sj-note">지금은 게시 가능 시간이 아니라 [지금 게시]가 잠겨 있어요. 예약 게시를 쓰세요.</p>}
      <div className="sj-actions">
        <button type="button" className="sj-btn sj-quiet" onClick={onDone}>다음 소재 고르기</button>
        {canRegister && publish && usable.length > 0 && (pickTime ? (
          <div className="sj-row">
            <button type="button" className="sj-btn" disabled={busy || !when || !caption.trim() || Boolean(windowProblem)} onClick={() => register(false)}>{busy ? "등록 중…" : "예약 게시"}</button>
            <button type="button" className="sj-btn sj-main" disabled={busy || !caption.trim() || Boolean(nowProblem)} title={nowProblem ?? undefined} onClick={() => register(true)}>{busy ? "등록 중…" : "지금 게시"} <span aria-hidden="true">→</span></button>
          </div>
        ) : (
          <button type="button" className="sj-btn sj-main" disabled={busy || Boolean(windowProblem)} onClick={() => register(false)}>{busy ? "등록 중…" : "정한 시각에 게시"} <span aria-hidden="true">→</span></button>
        ))}
      </div>
    </section>
  );
}
