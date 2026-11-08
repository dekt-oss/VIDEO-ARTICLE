"use client";

// 작업공간 껍데기(클라이언트) — 형식 카드 · 고정 결정 바(주 버튼 하나) · 레인 섹션(현재 것만 펼침) · ▾ 메뉴(보류·되돌리기·이력) ·
// 미저장 입력 복원. 섹션 **내용**은 서버가 기존 컴포넌트로 만들어 ReactNode 로 넘긴다(여기서는 배치만 한다).
// 계약: docs/deviation-drinks-multi-format.md §3-5 · 기획 v2 §6-3. 결정은 web/lib/drinks/work/decision.ts 가 하고, 여기는 그 결과를 보여 줄 뿐이다.
//
// ★ 주 버튼 하나의 규칙:
//   ① 같은 열쇠로 등록된 폼(primaryBridge)이 있으면 그 폼의 submit 을 부른다(폼의 금액·체크·캡션이 실린다).
//   ② 없고 결정이 동작(payload)을 줬으면 그대로 보낸다 — 단 지문(expected_digest)이 드는 동작은 보내지 않고 그 칸으로 간다
//      (사람이 지문을 보고 눌러야 한다. RequestActions 가 그 자리에 있다).
//   ③ 그 밖에는 결정이 가리키는 섹션을 펼치고 포커스를 옮긴다.
//   서버가 "다른 곳에서 바뀜"(409) 을 돌려주면 새로 불러오기 안내를 띄운다.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { useDrinksAction } from "@/components/drinks/useDrinksAction";
import { primaryKey, requiresInPanelConfirm, type SectionKey } from "@/lib/drinks/work/lanes";
import { FORMAT_LABEL, type Decision, type FormatIntent } from "@/lib/drinks/work/types";
import { FLOW_STATE_LABEL, flowSteps, weekRangeLabel } from "./flowSteps";
import { PrimaryBridgeProvider, usePrimaryBridge } from "./primaryBridge";
import { useDraftRestore } from "./useDraftRestore";

export interface FormatCardView {
  lane: FormatIntent;
  /** 결정 함수의 primary.label — 단계 이름으로 쓴다 */
  stage: string;
  href: string;
  current: boolean;
  blocked: boolean;
}

export interface SectionView {
  key: SectionKey;
  label: string;
  node: ReactNode;
}

const CONFLICT_CODES = new Set(["version_conflict", "review_changed", "plan_changed", "review_not_current", "plan_not_current", "digest_mismatch", "stale_strategy"]);

export default function DrinksWorkspace({
  topicId, lane, title, question, formats, decision, decisionProblem, sections, openKey, primarySection, history, hold, storageKey, legacyHref, editorialWeek = null,
}: {
  topicId: string;
  lane: FormatIntent;
  title: string;
  question: string | null;
  formats: FormatCardView[];
  decision: Decision | null;
  /** 작업 단위를 못 읽었을 때 그 이유(결정 없음 ≠ 할 일 없음) */
  decisionProblem: string | null;
  sections: SectionView[];
  openKey: SectionKey;
  /** 결정이 가리키는 섹션(lanes.primarySectionOf). 바의 버튼이 스크롤·포커스할 곳이고 "지금 할 일" 표가 붙는다 */
  primarySection: SectionKey | null;
  history: ReactNode;
  /** 소재 보류(topic_action hold)에 필요한 것. 카드 밈은 null */
  hold: { topicId: string; version: number } | null;
  storageKey: string;
  legacyHref: string | null;
  /** 작업 단위 행의 편성 주차(월요일). 오른쪽 "이 소재의 흐름" 칸에 보이기만 한다 */
  editorialWeek?: string | null;
}) {
  const key = primaryKey(decision?.primary.action);
  return (
    <PrimaryBridgeProvider primaryKey={key}>
      <Body topicId={topicId} lane={lane} title={title} question={question} formats={formats} decision={decision} decisionProblem={decisionProblem}
        sections={sections} openKey={openKey} primarySection={primarySection} history={history} hold={hold} storageKey={storageKey} legacyHref={legacyHref}
        editorialWeek={editorialWeek} />
    </PrimaryBridgeProvider>
  );
}

function Body({ lane, title, question, formats, decision, decisionProblem, sections, openKey, primarySection, history, hold, storageKey, legacyHref, editorialWeek }: {
  topicId: string; lane: FormatIntent; title: string; question: string | null; formats: FormatCardView[]; decision: Decision | null;
  decisionProblem: string | null; sections: SectionView[]; openKey: SectionKey; primarySection: SectionKey | null; history: ReactNode;
  hold: { topicId: string; version: number } | null; storageKey: string; legacyHref: string | null; editorialWeek: string | null;
}) {
  const router = useRouter();
  const { run, busy } = useDrinksAction();
  // null = 사람이 펼친 칸을 직접 닫았다(모두 접힘).
  const [open, setOpen] = useState<SectionKey | null>(openKey);
  const [showHistory, setShowHistory] = useState(false);
  const [menu, setMenu] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const { restored, dirty, discard } = useDraftRestore(bodyRef, storageKey);

  const primary = decision?.primary ?? null;
  const bridge = usePrimaryBridge(primaryKey(primary?.action));

  useEffect(() => setOpen(openKey), [openKey, lane]);

  const focusSection = useCallback((k: SectionKey, scroll: boolean) => {
    setOpen(k);
    // 펼쳐진 뒤 제목으로 포커스. 바에서 눌렀을 때만 스크롤한다(처음 열릴 때는 형식 카드·결정 바가 위에 있어야 한다).
    window.setTimeout(() => {
      const el = bodyRef.current?.querySelector<HTMLElement>(`[data-section="${k}"] > summary`);
      if (!el) return;
      if (scroll) el.scrollIntoView({ block: "start", behavior: "smooth" });
      el.focus({ preventScroll: true });
    }, 0);
  }, []);

  // 처음 그려질 때 '지금 할 일' 섹션에 포커스(스크롤 없음).
  useEffect(() => { focusSection(openKey, false); }, [openKey, focusSection]);

  const onPrimary = async () => {
    if (!primary || primary.busy) return;
    setConflict(false);
    if (bridge) {
      if (primarySection) focusSection(primarySection, true);
      await bridge.submit();
      return;
    }
    if (primary.action && !requiresInPanelConfirm(primary.action)) {
      const r = await run(primary.action.name, primary.action.payload, `${primary.label} — 처리했습니다`, primary.label);
      if (!r.ok && (r.status === 409 || (r.code && CONFLICT_CODES.has(r.code)))) setConflict(true);
      return;
    }
    if (primarySection) { focusSection(primarySection, true); return; }
    if (primary.href) router.push(primary.href);
  };

  const onHold = async () => {
    setMenu(false);
    if (!hold) return;
    const reason = window.prompt("보류 사유(필수)") ?? "";
    if (!reason.trim()) return;
    const until = window.prompt("재검토일(YYYY-MM-DD, 비우면 없음)") ?? "";
    const r = await run("topic_action", { topic_id: hold.topicId, expected_version: hold.version, action: "hold", reason: reason.trim(), hold_until: until.trim() || null },
      "보류했습니다", "소재 보류");
    if (!r.ok && r.status === 409) setConflict(true);
  };
  const onUndo = () => {
    setMenu(false);
    // 되돌리기는 단계마다 서버 규칙이 달라 여기서 보내지 않는다 — 그 칸의 버튼([고치러 되돌리기]·[초안으로 되돌리기]·[승인 철회]·[초안으로])으로 한다.
    const target: SectionKey = sections.some((s) => s.key === "post") && decision?.primary.panel === "post" ? "post" : open ?? openKey;
    focusSection(target, true);
    setHint("되돌리기는 펼친 칸 안의 버튼으로 합니다 — 게시 요청은 [고치러 되돌리기], 밈은 [초안으로 되돌리기], 파일은 [승인 철회].");
  };

  const disabled = busy || Boolean(primary?.busy) || (bridge ? bridge.disabled : false) || !primary;
  const btnTitle = bridge?.disabled ? bridge.title ?? "펼친 칸의 조건을 먼저 채우세요" : primary?.busy ? "진행 중" : "";

  return (
    <div className="dw" ref={bodyRef}>
      <div className="dk-head dk-head-row">
        <div>
          <p className="dk-eyebrow">MAKE / {FORMAT_LABEL[lane]}</p>
          <h1 className="dw-title dk-h1">{title}</h1>
          {question ? <p className="dk-lead">Q. {question}</p> : <p className="dk-lead">한 화면에서, 지금 필요한 결정부터.</p>}
        </div>
        <span className="dk-badge">{FORMAT_LABEL[lane]}</span>
      </div>

      <section className="card dw-formats-card" aria-label="이 소재로 만드는 형식">
        <h2>이 소재로 만드는 {formats.length}가지 콘텐츠</h2>
        <p className="muted">소재·근거는 함께, 기획·승인·제작·게시는 형식마다 따로 갑니다. 카드를 누르면 그 형식의 작업으로 바뀝니다.</p>
        <div className="dw-formats">
          {formats.map((f) => (
            <Link key={f.lane} href={f.href} className="dw-format" data-current={f.current} data-blocked={f.blocked} aria-current={f.current ? "page" : undefined}>
              <b>{FORMAT_LABEL[f.lane]}</b>
              <span>{f.stage}</span>
            </Link>
          ))}
        </div>
      </section>

      <div className="dw-decision" role="region" aria-label="지금 할 일">
        <div className="dw-decision-left">
          <span style={{ flexBasis: "100%", minWidth: 0 }}>
            <span className="dw-now-label">지금 할 일 · {FORMAT_LABEL[lane]}</span>
            <strong className="dw-now-title">{primary ? primary.label : "지금 할 일이 없습니다"}</strong>
          </span>
          {decision?.blocks.map((b) => (
            <span key={b.code} className="dw-chip dw-chip--block">
              {b.message}{b.href && <> · <Link href={b.href}>복구 →</Link></>}
            </span>
          ))}
          {decision?.warnings.map((w) => <span key={w} className="dw-chip dw-chip--warn">{w}</span>)}
          {decisionProblem && <span className="dw-chip dw-chip--block">결정을 못 읽음 — {decisionProblem}</span>}
          {conflict && (
            <span className="dw-chip dw-chip--block">
              다른 곳에서 바뀜 — <button type="button" className="btn" onClick={() => { setConflict(false); router.refresh(); }}>새로 불러오기</button>
            </span>
          )}
          {restored > 0 && (
            <span className="dw-chip dw-chip--warn">
              복원됨(서버 저장 아님) {restored}칸 <button type="button" className="btn" onClick={discard}>버리기</button>
            </span>
          )}
          {dirty && restored === 0 && <span className="muted">미저장 입력 있음</span>}
          {hint && <span className="muted">{hint}</span>}
        </div>
        <div className="dw-decision-right">
          <button type="button" className="btn pick dw-primary" disabled={disabled} title={btnTitle} onClick={onPrimary}>
            {primary ? (primary.busy ? `${primary.label}…` : primary.label) : "할 일 없음"}
          </button>
          <div className="dw-menu">
            <button type="button" className="btn" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((v) => !v)}>▾</button>
            {menu && (
              <div className="dw-menu-list" role="menu">
                <button type="button" role="menuitem" disabled={!hold || busy} onClick={onHold}>보류</button>
                <button type="button" role="menuitem" onClick={onUndo}>되돌리기…</button>
                <button type="button" role="menuitem" onClick={() => { setMenu(false); setShowHistory((v) => !v); }}>{showHistory ? "이력 닫기" : "이력"}</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {showHistory && <section className="card dw-history" aria-label="이력">{history}</section>}

      {sections.length > 1 && (
        <nav className="dw-steps" aria-label="진행 단계">
          {sections.map((s) => (
            <button key={s.key} type="button" data-open={open === s.key} data-now={primarySection === s.key}
              aria-current={primarySection === s.key ? "step" : undefined} onClick={() => focusSection(s.key, true)}>{s.label}</button>
          ))}
        </nav>
      )}

      <div className="dw-layout">
      <div className="dw-sections">
        {sections.map((s, i) => (
          <details key={s.key} className="dw-section" data-section={s.key} open={open === s.key}
            onToggle={(e) => {
              const isOpen = (e.currentTarget as HTMLDetailsElement).open;
              setOpen((cur) => (isOpen ? s.key : cur === s.key ? null : cur));
            }}>
            <summary tabIndex={-1}>
              <span className="dw-step">{i + 1}</span> {s.label}
              {primarySection === s.key && <span className="pill on dw-now">지금 할 일</span>}
            </summary>
            <div className="dw-section-body">{s.node}</div>
          </details>
        ))}
      </div>
      <FlowAside lane={lane} sections={sections} primarySection={primarySection} decision={decision} editorialWeek={editorialWeek}
        onPick={(k) => focusSection(k, true)} />
      </div>

      <details className="dw-flow-help">
        <summary>이전 단계와 이후 단계는 어떻게 이어지나요?</summary>
        <p>{sections.map((s) => s.label).join(" → ")}</p>
        <p className="muted">승인, 금액 결재, 제작 시작, 게시 승인, 예약은 각각 따로 확인합니다. 한 단계를 누른다고 다음 단계가 저절로 진행되지 않습니다.</p>
      </details>

      <footer className="dw-foot">
        승인·결재·제작·게시의 규칙은 서버가 지킵니다. 이 화면은 상태를 보여 주고 요청만 보냅니다.<br />
        <Link href="/drinks/work">만들기 목록</Link> · <Link href="/drinks">오늘 할 일</Link>
        {legacyHref && <> · <Link href={legacyHref}>옛 화면으로 보기</Link>(같은 데이터)</>}
      </footer>
    </div>
  );
}

/** 오른쪽 "이 소재의 흐름" 칸(목업 03·04·05). 결정 함수가 고른 칸과 섹션 순서만으로 칠한다(flowSteps) — 새 판단 없음. */
function FlowAside({ lane, sections, primarySection, decision, editorialWeek, onPick }: {
  lane: FormatIntent; sections: SectionView[]; primarySection: SectionKey | null; decision: Decision | null; editorialWeek: string | null;
  onPick: (k: SectionKey) => void;
}) {
  const steps = flowSteps(sections, primarySection, decision);
  const week = weekRangeLabel(editorialWeek);
  return (
    <aside className="dw-aside" aria-label="이 소재의 흐름">
      <div className="dw-flow">
        <h3>이 소재의 흐름</h3>
        <p className="dw-flow-sub">선택 → 대본 → 제작 → 게시</p>
        <ol className="dw-flow-steps">
          {steps.map((st) => (
            <li key={st.key} data-state={st.state} aria-current={st.state === "now" || st.state === "blocked" || st.state === "busy" ? "step" : undefined}>
              <button type="button" onClick={() => onPick(st.key as SectionKey)}>
                <span className="dw-flow-dot" aria-hidden="true">{st.state === "done" ? "✓" : ""}</span>
                <span className="dw-flow-label">{st.label}</span>
                <span className="dw-flow-state">{FLOW_STATE_LABEL[st.state]}</span>
              </button>
            </li>
          ))}
        </ol>
        <div className="dw-timeline">
          <p><b>형식</b><br />{FORMAT_LABEL[lane]}</p>
          <p><b>편성</b><br />{week ?? "아직 없음"}</p>
          <p><b>내가 할 일</b><br />{decision ? decision.primary.label : "정하지 못함"}</p>
        </div>
      </div>
      <div className="dw-aside-note">승인, 금액 결재, 제작 시작, 게시 승인, 예약은 각각 따로 확인합니다.</div>
      <Link href="/drinks/studio?tab=mine" className="dk-text-link">내 소재로 돌아가기 →</Link>
    </aside>
  );
}
