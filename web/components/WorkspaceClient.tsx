"use client";

// 통합 작업 화면 — 한 화면 · 한 발주 · 한 승인 (docs/설계안_초안지시서_통합발주_v2.md).
//
// ★ 2026-09-17 재구성: 본문이 **시퀀스 한 장**이다(SequenceEditor). 종전의 [대본 | 지시서]
//   가로 2분할과, 그 아래 따로 있던 컷 목록을 **전부 하나로** 합쳤다. 운영자 지시 —
//   "굳이 이 과정을 하나로 통합하자 한 거였는데 그냥 화면만 가로 분할해서 이분만 되어 있어",
//   "이런 컷들도 위에 시퀀스랑 합쳐서 하나로 만들어줘".
//   같은 컷이 두 군데 있으면 어느 쪽을 고쳐야 하는지 매번 헷갈린다 — 이제 한 군데다.
// 위에 **결정 바 하나**가 붙어 있다 — 저장·생성·승인을 전부 소유한다.
//
// ★ 왜 결정 바가 sticky 인가: 2026-08-19 에 ④⑤ 를 나눈 이유가 "페이지가 길어져 눌러야 할 버튼이
//   화면 밖으로 사라진다"였다(FLOW-01). 다시 합치면서 그 문제가 돌아오지 않게, 버튼은 스크롤과
//   무관하게 항상 보이고, 두 칸은 각자 스크롤한다.
// ★ 주 버튼은 하나다. 무엇이 될지는 `lib/work/decision.ts` 가 상태표로 정한다(테스트로 못박음).
// ★ 두 공장이 **이 한 컴포넌트**를 쓴다(`factory`). 공장마다 다른 것은 API 경로·버전 목록·칸
//   컴포넌트뿐이고, 그것은 아래 FACTORY 표 한 곳에 있다.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import type { Directive, Draft, RenderJob, VersionType } from "@/lib/types";
import type { ReportDraft, ReportRenderJob } from "@/lib/reportTypes";
import type { PendingStatus } from "@/lib/queries";
import {
  VERSION_META, DEFAULT_VERSION_KEY, versionLabel,
  REPORT_VERSION_META, REPORT_DEFAULT_VERSION_KEY, reportVersionLabel,
  type VersionMeta,
} from "@/lib/versions";
import { decide, type VersionState } from "@/lib/work/decision";
import { pickInitialVersions } from "@/lib/work/versionSelection";
import type { ScriptPaneHandle, CutsPaneHandle } from "@/lib/work/panes";
import { estimateOrder, formatUsd, LANG_COST_NOTE } from "@/lib/orderCost";
import { blockLabel } from "@/lib/blockLabels";
import { useGeneration, genPhaseLabel } from "@/lib/useGeneration";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import SequenceEditor from "@/components/SequenceEditor";
import RenderList from "@/components/RenderList";
import ReportRenderList from "@/components/ReportRenderList";
import { apiErrorText } from "@/lib/apiError";

export type Factory = "paper" | "report";

export interface VersionSlot {
  key: VersionType;
  directive: Directive | null;
}

interface FactoryConfig {
  idParam: "paper_id" | "report_id";
  generateDraftUrl: string;
  draftStatusUrl: (id: string) => string;
  directiveGenerateUrl: string;
  approveScriptUrl: string;
  directiveApproveUrl: string;
  /** 시퀀스 화면이 컷·시퀀스를 저장하는 곳. */
  directiveUpdateUrl: string;
  /** 지시서 승인 라우트가 여러 id 를 한 번에 받는가(논문은 directive_ids, 리포트는 단건). */
  approveBatch: boolean;
  versionMeta: VersionMeta[];
  defaultVersion: VersionType;
  label: (v: VersionType | string) => string;
  hrefForVersion: (id: string, v: VersionType) => string;
  storageKey: string;
}

const FACTORY: Record<Factory, FactoryConfig> = {
  paper: {
    idParam: "paper_id",
    generateDraftUrl: "/api/generate-draft",
    draftStatusUrl: (id) => `/api/draft-status?paper_id=${encodeURIComponent(id)}`,
    directiveGenerateUrl: "/api/directive-generate",
    approveScriptUrl: "/api/approve",
    directiveApproveUrl: "/api/directive-approve",
    directiveUpdateUrl: "/api/directive-update",
    approveBatch: true,
    versionMeta: VERSION_META,
    defaultVersion: DEFAULT_VERSION_KEY,
    label: versionLabel,
    hrefForVersion: (id, v) => `/review/${id}?v=${v}`,
    storageKey: "va:workspace:versions:paper",
  },
  report: {
    idParam: "report_id",
    generateDraftUrl: "/api/report-generate-draft",
    draftStatusUrl: (id) => `/api/report-draft-status?report_id=${encodeURIComponent(id)}`,
    directiveGenerateUrl: "/api/report-directive-generate",
    approveScriptUrl: "/api/report-approve",
    directiveApproveUrl: "/api/report-directive-approve",
    directiveUpdateUrl: "/api/report-directive-update",
    approveBatch: false,
    versionMeta: REPORT_VERSION_META,
    defaultVersion: REPORT_DEFAULT_VERSION_KEY,
    label: reportVersionLabel,
    hrefForVersion: (id, v) => `/finance/review/${id}?v=${v}`,
    storageKey: "va:workspace:versions:report",
  },
};

const POLL_MS = 4000;
const POLL_TIMEOUT_MS = 720_000;

/** 화면을 열 때 체크해 둘 버전. 판단은 `lib/work/versionSelection` 이 하고(검사로 못박음),
 *  여기서는 localStorage 읽기만 맡는다(서버 렌더에서는 못 읽는다). */
function initialVersions(cfg: FactoryConfig, slots: VersionSlot[]): VersionType[] {
  const withDirective = slots.filter((s) => s.directive).map((s) => s.key as string);
  const known = cfg.versionMeta.map((m) => m.key as string);
  let stored: string[] | null = null;
  try {
    const raw = window.localStorage.getItem(cfg.storageKey);
    stored = raw ? (JSON.parse(raw) as string[]) : null;
  } catch { /* 저장소를 못 읽어도 동작한다 */ }
  return pickInitialVersions(withDirective, stored, known, cfg.defaultVersion) as VersionType[];
}

export default function WorkspaceClient({
  factory,
  id,
  draft,
  published,
  slots,
  jobs,
  draftPending,
  directivePending,
  activeVersion,
  initialStep,
  leftExtras,
  validationCurrent = true,
}: {
  factory: Factory;
  /** paper_id 또는 report_id. */
  id: string;
  draft: Draft | ReportDraft | null;
  published: boolean;
  slots: VersionSlot[];
  jobs: RenderJob[] | ReportRenderJob[];
  draftPending: PendingStatus;
  /** 버전별 지시서 생성 요청 상태(서버가 읽어 준다 — 새로고침해도 "만드는 중"이 이어진다). */
  directivePending: Partial<Record<VersionType, PendingStatus>>;
  activeVersion: VersionType;
  /** 옛 `?step=` 주소 호환 — 6 이면 렌더 패널을 펼치고, 5 면 좁은 화면에서 지시서 칸을 먼저 보인다. */
  initialStep: 4 | 5 | 6;
  /** 왼쪽 칸 맨 위(발행 제목·캡션·원문 정보 — 서버 컴포넌트). */
  leftExtras?: ReactNode;
  /** 리포트 공장: 화면의 검사 결과가 지금 대본의 것인가. */
  validationCurrent?: boolean;
}) {
  const cfg = FACTORY[factory];
  const router = useRouter();
  const toast = useToast();

  // ── 버전 선택. **있는 지시서를 먼저 체크**하고, 하나도 없으면 마지막 선택·기본값(만화식 1건).
  // ★ 초기값에서부터 있는 지시서를 본다 — 서버 렌더에도 같은 버튼이 찍힌다. 초기값이
  //   기본값이면 하이드레이션 전까지 "지시서 생성(만화식)"이 깜빡였다가 바뀐다.
  //   (localStorage 는 서버에서 못 읽으므로 그 경로는 아래 effect 가 맡는다.)
  const [versions, setVersions] = useState<VersionType[]>(() =>
    // 서버 렌더에서는 localStorage 를 못 읽으므로 ①(있는 지시서)·③(기본값)만으로 정한다.
    pickInitialVersions(
      slots.filter((s) => s.directive).map((s) => s.key as string),
      null, cfg.versionMeta.map((m) => m.key as string), cfg.defaultVersion) as VersionType[]);
  // ★ 의존성은 slots 배열이 아니라 "지시서가 있는 버전 목록"이다. slots 는 렌더마다 새 배열이라
  //   그대로 넣으면 매 렌더 초기화돼 운영자가 방금 켠 체크가 지워진다.
  const existingVersionKey = slots.filter((s) => s.directive).map((s) => s.key).join(",");
  useEffect(() => { setVersions(initialVersions(cfg, slots)); },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- slots 는 위 키로 대표한다(매 렌더 새 배열)
    [cfg, existingVersionKey]);
  function toggleVersion(v: VersionType) {
    setVersions((prev) => {
      const next = prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v];
      try { window.localStorage.setItem(cfg.storageKey, JSON.stringify(next)); } catch { /* 저장 못 해도 동작 */ }
      return next;
    });
  }

  const [renderLang, setRenderLang] = useState<"ko" | "en" | "both">("both");
  const langs = useMemo(() => (renderLang === "both" ? ["ko", "en"] : [renderLang]), [renderLang]);
  const [mobilePane, setMobilePane] = useState<"script" | "cuts">(initialStep === 5 ? "cuts" : "script");
  const [busy, setBusy] = useState(false);
  const [showApprove, setShowApprove] = useState(false);
  const [showRegenDraft, setShowRegenDraft] = useState(false);
  // ★ 방향 있는 재생성(2026-09-17 복구). 대본 칸을 없애면서 이 기능이 같이 사라졌다 —
  //   운영자 지적 "전체적인 늬앙스를 수정하도록 요청하는것도 필요해. 이전에 있던 건데 없어진 거라서".
  //   무작정 재생성이 아니라 **적은 방향대로** 다시 만든다. 사실은 Fact Sheet 범위 안에서만 바뀐다.
  const [instruction, setInstruction] = useState("");
  const [showRegenDirective, setShowRegenDirective] = useState<VersionType[] | null>(null);
  const [blocked, setBlocked] = useState<{ ids: string[]; reasons: string[] } | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [scriptApproved, setScriptApproved] = useState(published);
  useEffect(() => { setScriptApproved(published); }, [published]);

  const scriptRef = useRef<ScriptPaneHandle | null>(null);
  const cutsRef = useRef<CutsPaneHandle | null>(null);
  // 손잡이는 자식이 effect 로 갱신한다 — 결정 바가 dirty 를 보게 주기적으로 다시 읽는다.
  const [, bump] = useState(0);
  useEffect(() => {
    const t = setInterval(() => bump((n) => n + 1), 500);
    return () => clearInterval(t);
  }, []);
  const dirty = !!(scriptRef.current?.dirty || cutsRef.current?.dirty);

  // ── 초안(+지시서) 생성. 버전은 실행 시점에 실어 보낸다(0046).
  const gen = useGeneration({
    kickoffUrl: cfg.generateDraftUrl,
    kickoffBody: { [cfg.idParam]: id },
    statusUrl: cfg.draftStatusUrl(id),
    okMsg: "초안이 생성되었습니다. 고른 버전의 지시서를 이어서 만듭니다.",
    resumeFrom: draftPending,
  });

  // ── 이어지는 지시서 생성 폴링. 서버가 읽어 준 pending + 이 화면에서 발주한 것.
  const [chain, setChain] = useState<Set<VersionType>>(() => {
    const s = new Set<VersionType>();
    for (const [k, v] of Object.entries(directivePending)) if (v) s.add(k as VersionType);
    return s;
  });
  useEffect(() => {
    setChain((prev) => {
      const next = new Set(prev);
      for (const [k, v] of Object.entries(directivePending)) if (v) next.add(k as VersionType);
      return next;
    });
  }, [directivePending]);
  const [chainSec, setChainSec] = useState(0);
  useEffect(() => {
    if (chain.size === 0) return;
    let stop = false;
    const started = Date.now();
    const tick = setInterval(() => setChainSec(Math.floor((Date.now() - started) / 1000)), 1000);
    (async () => {
      while (!stop && Date.now() - started < POLL_TIMEOUT_MS) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        let s: { directive?: Record<string, { status: string; error: string | null }> } | null = null;
        try {
          const res = await fetch(cfg.draftStatusUrl(id));
          if (res.ok) s = await res.json();
        } catch { continue; }
        if (!s?.directive) continue;
        let changed = false;
        for (const key of [...chain]) {
          const st = s.directive[key]?.status;
          if (st === "done") {
            toast.show(`${cfg.label(key)} 지시서가 만들어졌습니다.`, "ok");
            changed = true;
            setChain((prev) => { const n = new Set(prev); n.delete(key); return n; });
          } else if (st === "error") {
            toast.show(`${cfg.label(key)} 지시서 생성 실패 — ${s.directive[key]?.error ?? "사유 미기록"}`, "err");
            changed = true;
            setChain((prev) => { const n = new Set(prev); n.delete(key); return n; });
          }
        }
        if (changed) router.refresh();
      }
      if (!stop) {
        toast.show("지시서 생성이 지연되고 있습니다. 잠시 후 새로고침해 확인하세요.", "err");
        setChain(new Set());
      }
    })();
    return () => { stop = true; clearInterval(tick); };
    // chain 의 내용이 바뀔 때마다 루프를 다시 세운다(끝난 버전을 빼면 새 루프가 나머지만 본다).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain.size, id]);

  // ── 결정
  const versionStates: VersionState[] = useMemo(
    () => slots.map((s) => ({
      key: s.key,
      status: s.directive?.status ?? null,
      createdAt: s.directive?.created_at ?? null,
      pending: chain.has(s.key) ? "processing" : (directivePending[s.key] ?? null),
      blocked: s.directive?.header?.approval_blocked ? (s.directive.header.block_reasons ?? ["approval_blocked"]) : [],
    })),
    [slots, chain, directivePending],
  );
  const decision = decide({
    hasDraft: !!draft,
    draftPending: gen.busy ? "processing" : draftPending,
    draftUpdatedAt: draft?.updated_at ?? null,
    scriptApproved,
    chosen: versions,
    versions: versionStates,
    dirty,
  });
  const targetSlots = slots.filter((s) => decision.targets.includes(s.key));
  const estimate = useMemo(
    () => estimateOrder(targetSlots.map((s) => ({ key: s.key, directive: s.directive })), langs),
    [targetSlots, langs],
  );

  // ── 동작들
  async function saveAll(): Promise<boolean> {
    setBusy(true);
    try {
      const a = scriptRef.current ? await scriptRef.current.save() : true;
      const b = cutsRef.current ? await cutsRef.current.save() : true;
      if (a && b) toast.show("변경사항을 저장했습니다.", "ok");
      return a && b;
    } finally {
      setBusy(false);
    }
  }

  const requestDirectives = useCallback(async (keys: VersionType[]) => {
    const res = await fetch(cfg.directiveGenerateUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [cfg.idParam]: id, version_types: keys }),
    });
    const j = await res.json().catch(() => null);
    if (!res.ok) {
      toast.show(apiErrorText(j, res.status, "지시서를 생성"), "err");
      return;
    }
    toast.show(`${keys.map(cfg.label).join(", ")} 지시서를 만들고 있습니다`, "ok");
    setChain((prev) => new Set([...prev, ...keys]));
  }, [cfg, id, toast]);

  async function approveDirectiveIds(ids: string[], force: boolean): Promise<{ results: Array<{ directive_id: string; version_type?: string; queued?: number; blocked?: string[]; error?: string }>; rendering?: boolean } | null> {
    if (cfg.approveBatch) {
      const res = await fetch(cfg.directiveApproveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directive_ids: ids, langs, force }),
      });
      const j = await res.json().catch(() => null);
      if (!res.ok && !(res.status === 409 && (j?.results ?? []).length > 0)) {
        toast.show(apiErrorText(j, res.status, "지시서를 승인"), "err");
        return null;
      }
      return j;
    }
    // 단건 라우트 — 버전마다 부르고 결과를 같은 모양으로 모은다.
    const results: Array<{ directive_id: string; version_type?: string; queued?: number; blocked?: string[]; error?: string }> = [];
    let rendering: boolean | undefined;
    for (const directiveId of ids) {
      const slot = slots.find((s) => s.directive?.id === directiveId);
      const res = await fetch(cfg.directiveApproveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directive_id: directiveId, langs, force }),
      });
      const j = await res.json().catch(() => null);
      if (res.ok) {
        results.push({ directive_id: directiveId, version_type: slot?.key, queued: j?.queued ?? langs.length });
        if (typeof j?.rendering === "boolean") rendering = j.rendering;
      } else if (res.status === 409 && (j?.block_reasons ?? []).length) {
        results.push({ directive_id: directiveId, version_type: slot?.key, blocked: j.block_reasons });
      } else {
        results.push({ directive_id: directiveId, version_type: slot?.key, error: j?.error ?? String(res.status) });
      }
    }
    return { results, rendering };
  }

  async function approveAndRender(force = false) {
    setBusy(true);
    try {
      // ① 저장하지 않은 편집을 먼저 저장한다. 실패하면 승인하지 않는다.
      // ★ 대본 칸(대본·씬)을 고친 채 눌렀으면 저장만 하고 **멈춘다**(2026-09-11 리뷰). 렌더는
      //   지시서의 컷·나레이션으로 나가므로, 저장 뒤 옛 지시서를 승인하면 방금 고친 문장이 영상에
      //   없다. 새로고침하면 updated_at(0048)이 올라가 주 버튼이 [지시서 재생성]으로 바뀐다.
      //   컷 칸만 고친 경우는 그 지시서 자체를 고친 것이라 그대로 승인한다.
      const scriptEdited = !!scriptRef.current?.dirty && targetSlots.some((s) => s.directive);
      if (dirty) {
        const ok = (scriptRef.current ? await scriptRef.current.save() : true)
          && (cutsRef.current ? await cutsRef.current.save() : true);
        if (!ok) { toast.show("저장에 실패해 승인을 중단했습니다.", "err"); return; }
      }
      if (scriptEdited) {
        toast.show("대본을 저장했습니다. 지시서가 옛 대본 기준이라 승인하지 않았습니다 — [지시서 재생성]으로 다시 만드세요.", "err");
        router.refresh();
        return;
      }
      // ② 대본 확정(아카이브). 이미 됐으면 건너뛴다.
      if (!scriptApproved) {
        const res = await fetch(cfg.approveScriptUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [cfg.idParam]: id, final_script: scriptRef.current?.getScript() ?? draft?.script_md ?? "" }),
        });
        if (!res.ok) {
          const e = await res.json().catch(() => null);
          toast.show(apiErrorText(e, res.status, "대본을 승인"), "err");
          return;
        }
        setScriptApproved(true);
      }
      // ③ 지시서 승인 → 렌더 잡.
      const ids = targetSlots.map((s) => s.directive?.id).filter((x): x is string => !!x);
      if (ids.length === 0) { toast.show("승인할 지시서가 없습니다.", "err"); router.refresh(); return; }
      const j = await approveDirectiveIds(ids, force);
      if (!j) return;
      const blockedIds: string[] = [];
      const reasons = new Set<string>();
      const notes: string[] = [];
      for (const r of j.results ?? []) {
        const label = cfg.label(r.version_type ?? r.directive_id);
        if (r.blocked?.length) {
          blockedIds.push(r.directive_id);
          for (const c of r.blocked) reasons.add(c);
          notes.push(`${label}: 차단`);
        } else if (r.error) notes.push(`${label}: 실패 — ${r.error}`);
        else notes.push(`${label}: 렌더 잡 ${r.queued ?? "?"}건`);
      }
      if (blockedIds.length) setBlocked({ ids: blockedIds, reasons: [...reasons] });
      else toast.show(`대본 확정 · ${notes.join(" · ")}${j.rendering === false ? " · 워커 자동 시작 없음(렌더 결과에서 수동)" : ""}`, "ok");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function archiveScriptOnly() {
    const ok = dirty ? await saveAll() : true;
    if (!ok) return;
    const res = await fetch(cfg.approveScriptUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [cfg.idParam]: id, final_script: scriptRef.current?.getScript() ?? draft?.script_md ?? "" }),
    });
    if (res.ok) { setScriptApproved(true); toast.show("대본을 확정(아카이브)했습니다. 렌더는 시작하지 않았습니다.", "ok"); router.refresh(); }
    else { const e = await res.json().catch(() => null); toast.show(apiErrorText(e, res.status, "대본을 승인"), "err"); }
  }

  function onPrimary() {
    switch (decision.action) {
      case "generate":
        if (versions.length === 0) { toast.show("만들 버전을 하나 이상 고르세요.", "err"); return; }
        void gen.run({ version_types: versions });
        return;
      case "make_directive":
        void requestDirectives(decision.targets as VersionType[]);
        return;
      case "approve_render":
        // ★ 막혀 있으면 사유 확인창으로, 아니면 보통 확인창으로. **버튼은 같은 자리 같은 이름**이다
        //   (2026-09-17). 운영자 눈에 렌더로 가는 길이 사라지지 않게 한다.
        if (decision.blockedReasons.length) {
          setBlocked({
            ids: targetSlots.map((s) => s.directive?.id).filter((x): x is string => !!x),
            reasons: decision.blockedReasons,
          });
        } else {
          setShowApprove(true);
        }
        return;
      case "view_render":
        document.getElementById("work-render")?.setAttribute("open", "");
        document.getElementById("work-render")?.scrollIntoView({ behavior: "smooth" });
        return;
      default:
        return;
    }
  }

  const waiting = decision.action === "wait_draft" || decision.action === "wait_directive";
  const primaryDisabled = busy || waiting || decision.action === "choose_version"
    || (decision.action === "generate" && versions.length === 0);
  const activeSlot = slots.find((s) => s.key === activeVersion) ?? null;
  const activePending: PendingStatus = chain.has(activeVersion) ? "processing" : (directivePending[activeVersion] ?? null);
  const flaggedFromDraft = draft
    ? (draft.self_check?.scenes ?? []).filter((s) => (("unsupported" in s && Array.isArray(s.unsupported) && s.unsupported.length > 0) || ("grounded" in s && s.grounded === false))).length
    : 0;
  const scriptSummary = scriptRef.current
    ? `근거 없는 씬 ${scriptRef.current.flaggedScenes}`
    : draft ? `근거 없는 씬 ${flaggedFromDraft}` : "초안 없음";
  const cutsSummary = cutsRef.current?.directiveId
    ? `근거 없는 컷 ${cutsRef.current.ungrounded}`
    : activeSlot?.directive ? `근거 없는 컷 ${(activeSlot.directive.cuts ?? []).filter((c) => (c.source_facts?.length ?? 0) === 0).length}` : "지시서 없음";

  const versionChooser = (
    <span className="work-versions" title="이 화면에서 만들·승인할 버전">
      {cfg.versionMeta.map((m) => (
        <label key={m.key} className="check-chip" title={m.hint}>
          <input type="checkbox" checked={versions.includes(m.key)} disabled={busy || gen.busy} onChange={() => toggleVersion(m.key)} />
          <span>{m.label}</span>
        </label>
      ))}
    </span>
  );

  return (
    <>
      {/* ── 결정 바 ── */}
      <div className="work-decision">
        <div className="work-decision-left">
          <span className="muted">{scriptSummary} · {cutsSummary}</span>
          {gen.busy && (
            <span className="gen-progress"><span className="spinner" /> {genPhaseLabel(gen.phase)} {gen.elapsedSec > 0 && `· ${gen.elapsedSec}s`}</span>
          )}
          {!gen.busy && chain.size > 0 && (
            <span className="gen-progress"><span className="spinner" /> 지시서 만드는 중 · {[...chain].map(cfg.label).join(", ")} {chainSec > 0 && `· ${chainSec}s`}</span>
          )}
          {decision.stale.length > 0 && (
            <span className="work-stale">⚠ {decision.stale.map(cfg.label).join(", ")} 지시서가 옛 대본 기준입니다</span>
          )}
          {decision.blockedReasons.length > 0 && (
            // ★ 버튼을 없애는 대신 여기서 알린다(2026-09-17). 눌러야 할 곳은 그대로 두고,
            //   "그냥 누르면 안 되는 상태"라는 것만 보이게 한다.
            <span className="work-stale" title={decision.blockedReasons.map(blockLabel).join("\n")}>
              ⚠ 승인 게이트 {decision.blockedReasons.length}건 — 누르면 사유를 보여줍니다
            </span>
          )}
          {!validationCurrent && (
            <span className="work-stale">⚠ 검사 이후 대본이 수정됨 — 재검사 권장</span>
          )}
        </div>
        <div className="work-decision-right">
          {/* 버전 선택은 기다리는 중이 아니면 늘 보인다 — 숨기면 체크를 다 풀었을 때 다시 고를 길이 없다(실측). */}
          {!waiting && versionChooser}
          {decision.action === "approve_render" && (
            <label className="render-lang" title="렌더할 언어(둘째 언어는 비용 $0 — 에셋 공유)">
              <select value={renderLang} onChange={(e) => setRenderLang(e.target.value as "ko" | "en" | "both")} disabled={busy}>
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="both">한·영 둘 다</option>
              </select>
            </label>
          )}
          {draft && (
            <button className="btn" onClick={() => void saveAll()} disabled={busy || !dirty} title="대본·씬·컷을 한 번에 저장">
              변경사항 저장{dirty && <span className="dirty-dot" />}
            </button>
          )}
          <button className="btn pick" onClick={onPrimary} disabled={primaryDisabled} title={decision.reason}>
            {/* 상태표는 버전 **키**로 말한다(순수 함수). 화면에서만 사람 말로 바꾼다 — 어디에 있든. */}
            {busy ? "처리 중…" : cfg.versionMeta.reduce(
              (s, m) => s.replace(new RegExp(`\\b${m.key}\\b`, "g"), m.label), decision.label)}
          </button>
          {/* ★ 낡았을 때의 권장 동작을 **주 버튼 옆에 보이게** 둔다(2026-09-17). ▾ 안에 숨겼더니
              운영자가 못 찾았고, 주 버튼으로 만들었더니 이번엔 승인·렌더가 사라졌다. 둘 다 보인다. */}
          {decision.stale.length > 0 && (
            <button className="btn" disabled={busy}
              title="지금 대본으로 지시서를 다시 만듭니다(LLM 비용)"
              onClick={() => setShowRegenDirective(decision.stale as VersionType[])}>
              지시서 재생성 ({decision.stale.map(cfg.label).join(", ")})
            </button>
          )}
          {draft && (
            <span className="work-menu">
              <button className="btn" onClick={() => setMenuOpen((o) => !o)} aria-label="다른 동작">▾</button>
              {menuOpen && (
                <div className="work-menu-list" onMouseLeave={() => setMenuOpen(false)}>
                  <button onClick={() => { setMenuOpen(false); setShowRegenDraft(true); }} disabled={gen.busy}>초안 재생성(지시서도 새로)</button>
                  <button onClick={() => { setMenuOpen(false); setShowRegenDirective(versions); }} disabled={versions.length === 0}>지시서만 재생성</button>
                  {!scriptApproved && <button onClick={() => { setMenuOpen(false); void archiveScriptOnly(); }}>대본만 확정(렌더 없음)</button>}
                </div>
              )}
            </span>
          )}
        </div>
      </div>

      {/* ── 한 장: 시퀀스 → 단계 → 컷 (2026-09-17) ──
          종전에는 [대본 | 지시서] 가로 2분할이었다. 두 칸은 같은 영상의 두 표현인데 따로 놓여
          있어서 "이 나레이션이 어느 화면에 붙나"를 눈으로 이어 붙여야 했다. 이제 한글과 시각
          지시가 같은 줄에 나란히 온다. 대본 칸은 없앴다(운영자 결정) — 나레이션은 시퀀스 안에서
          고치고, 렌더도 원래 **지시서의 나레이션**으로 나간다. */}
      <div className="work-one">
        <div className="toggle" style={{ margin: "0 0 10px" }}>
          {cfg.versionMeta.map((m) => {
            const st = slots.find((s) => s.key === m.key)?.directive?.status;
            return (
              <a key={m.key} href={cfg.hrefForVersion(id, m.key)} data-active={m.key === activeVersion} title={m.hint}>
                {m.label}{st ? ` · ${st === "draft" ? "검수" : st}` : chain.has(m.key) ? " · 만드는 중" : " · 미생성"}
              </a>
            );
          })}
        </div>

        {draft && (
          <details className="aux-panel nuance">
            <summary>✍️ 이 방향으로 다시 만들기 — 전체 뉘앙스·말투·강조점</summary>
            <p className="muted">
              어떤 방향으로 다듬을지 적으면 그 지시대로 다시 만듭니다(무작정 재생성이 아니라 방향 있는 재생성).
              예: &quot;어려운 용어를 일상 비유로 풀어써줘&quot;, &quot;훅을 더 자극적으로&quot;,
              &quot;숫자를 더 강조&quot;, &quot;더 짧고 간결하게&quot;.
              <br />★ 사실은 Fact Sheet 범위 안에서만 바뀌고, 없는 내용은 추가되지 않습니다.
              <br />★ 대본과 고른 버전의 지시서가 **함께** 새로 만들어집니다(LLM 비용).
            </p>
            <textarea
              rows={3}
              value={instruction}
              placeholder="예: 전문 용어를 일상 비유로 풀어서, 말투는 좀 더 차분하게"
              onChange={(e) => setInstruction(e.target.value)}
              disabled={gen.busy || busy}
            />
            <button
              className="btn pick"
              style={{ marginTop: 8 }}
              disabled={gen.busy || busy || !instruction.trim() || versions.length === 0}
              title={versions.length === 0 ? "만들 버전을 하나 이상 고르세요" : "적은 방향대로 다시 만듭니다"}
              onClick={() => void gen.run({ instruction: instruction.trim(), version_types: versions })}
            >
              {gen.busy ? "다시 만드는 중…" : "이 방향으로 다시 만들기"}
            </button>
          </details>
        )}

        {leftExtras}

        {!draft ? (
          <p className="muted">초안이 만들어지면 여기에 영상 구성이 옵니다.</p>
        ) : (
          <SequenceEditor
            directive={activeSlot?.directive ?? null}
            updateUrl={cfg.directiveUpdateUrl}
            paneRef={cutsRef}
            readOnly={(activeSlot?.directive?.status ?? "draft") !== "draft"}
          />
        )}
      </div>

      {/* ── 렌더 결과(접힘) ── */}
      <details className="aux-panel" id="work-render" open={initialStep === 6}>
        <summary>렌더 결과 · {jobs.length}건</summary>
        {jobs.length === 0
          ? <p className="muted">아직 렌더가 없습니다. 위 [승인 → 렌더]로 시작합니다.</p>
          : factory === "paper"
            ? <RenderList jobs={jobs as RenderJob[]} />
            : <ReportRenderList jobs={jobs as ReportRenderJob[]} />}
      </details>

      {/* ── 확인창들 ── */}
      <ConfirmModal
        open={showApprove}
        title="승인 → 렌더"
        message={
          `승인하면 렌더가 시작됩니다(비용이 발생합니다).\n\n` +
          `· 대본: 씬 ${scriptRef.current?.sceneCount ?? 0} · ${scriptSummary}${scriptApproved ? "" : " · 이 승인으로 대본이 확정(아카이브)됩니다"}\n` +
          targetSlots.map((s) => {
            const h = s.directive?.header;
            const ung = (s.directive?.cuts ?? []).filter((c) => (c.source_facts?.length ?? 0) === 0).length;
            return `· 지시서(${cfg.label(s.key)}): 컷 ${s.directive?.cuts?.length ?? 0} · 근거 없는 컷 ${ung}` +
              (h?.cost_plan ? ` · 예상 생성비 $${h.cost_plan.estimated_total_generation_cost_usd.toFixed(2)}` : "");
          }).join("\n") +
          `\n· 렌더 언어: ${renderLang === "both" ? "한국어 + 영어" : renderLang === "en" ? "영어" : "한국어"} (${LANG_COST_NOTE})` +
          `\n· 합계(추정): ${formatUsd(estimate.total)} · 렌더 잡 ${estimate.renderJobCount}건` +
          (dirty ? "\n\n저장하지 않은 편집을 먼저 저장합니다." : "")
        }
        confirmLabel="승인하고 렌더 시작"
        busy={busy}
        onCancel={() => setShowApprove(false)}
        onConfirm={() => { setShowApprove(false); void approveAndRender(false); }}
      />
      <ConfirmModal
        open={blocked !== null}
        title="승인이 차단되었습니다"
        message={
          `사유:\n${(blocked?.reasons ?? []).map((r) => `· ${blockLabel(r)}`).join("\n")}\n\n` +
          `원칙은 지시서를 다시 만드는 것입니다. 그래도 이대로 렌더하려면 강제 승인합니다 — 우회 기록이 서버 로그에 남습니다.`
        }
        confirmLabel="그래도 강제 승인 → 렌더"
        danger
        busy={busy}
        onCancel={() => setBlocked(null)}
        onConfirm={() => { setBlocked(null); void approveAndRender(true); }}
      />
      <ConfirmModal
        open={showRegenDraft}
        title="초안 재생성"
        message={`초안을 새로 만들고, 고른 버전(${versions.map(cfg.label).join(", ") || "없음"})의 지시서도 이어서 새로 만듭니다. 기존 초안과 저장하지 않은 편집은 사라집니다. 계속할까요?`}
        confirmLabel="재생성"
        danger
        onCancel={() => setShowRegenDraft(false)}
        onConfirm={() => { setShowRegenDraft(false); void gen.run({ version_types: versions }); }}
      />
      <ConfirmModal
        open={showRegenDirective !== null}
        title="지시서 재생성"
        message={`${(showRegenDirective ?? []).map(cfg.label).join(", ")} 지시서를 지금 대본으로 다시 만듭니다(LLM 비용). 현재 컷과 저장하지 않은 편집은 대체됩니다. 계속할까요?`}
        confirmLabel="재생성"
        danger
        onCancel={() => setShowRegenDirective(null)}
        onConfirm={() => { const keys = showRegenDirective ?? []; setShowRegenDirective(null); void requestDirectives(keys); }}
      />
    </>
  );
}
