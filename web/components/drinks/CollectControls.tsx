"use client";

// 주류 B단계 운영자 동작 — 수집원 등록·상태 동작·실행 요청·재시도, 수집 문서 → 소재 후보·조사 연결.
// ★ 버튼은 편의다. 활성화 조건(이용 조건 확인·검증 성공·활성 12개 상한)·실행 상한은 DB 가 다시 막는다.
// ★ 자동 활성화·자동 승인·자동 편성은 없다. 여기 있는 동작도 전부 사람이 누른다.
import { useState } from "react";

import { CATEGORIES, CATEGORY_LABEL, LANE_LABEL, RIGHTS_LABEL } from "@/lib/drinks/model";
import { METHOD_LABEL, TERMS_LABEL, sourceActions } from "@/lib/drinks/collect";
import type { RunStatus, SourceRow } from "@/lib/drinks/types";
import { useDrinksAction, type DrinksResult } from "./useDrinksAction";

function dispatchNote(r: DrinksResult): string | null {
  if (!r.ok) return null;
  if (r.dispatch?.triggered) return "수집 워커를 깨웠습니다 — 몇 분 안에 실행 기록에 결과가 나옵니다.";
  return "실행을 대기열에 넣었습니다. 워커 자동 깨우기가 설정되지 않아 다음 일일 실행(KST 06:30)이나 수동 실행 때 처리됩니다.";
}

export function SourceRegisterForm() {
  const { run, busy } = useDrinksAction();
  const [f, setF] = useState({
    name: "", home_url: "", publisher: "", language: "ja", method: "approved_page", entry_urls: "",
    link_prefix: "", content_ids: "", terms_status: "unverified", terms_note: "", terms_url: "", terms_checked_at: "",
    robots_note: "", rights_default: "unknown", request_interval_sec: "5", max_items_per_run: "100", max_bodies_per_run: "20",
  });
  const [cats, setCats] = useState<string[]>([]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async () => {
    const parser_config: Record<string, unknown> = {};
    if (f.link_prefix.trim()) parser_config.link_prefix = f.link_prefix.trim();
    if (f.content_ids.trim()) parser_config.content_ids = f.content_ids.split(/[\s,]+/).filter(Boolean);
    const r = await run("register_source", {
      ...f, categories: cats, parser_config,
      entry_urls: f.entry_urls.split(/\s+/).filter(Boolean),
      request_interval_sec: Number(f.request_interval_sec), max_items_per_run: Number(f.max_items_per_run),
      max_bodies_per_run: Number(f.max_bodies_per_run), terms_checked_at: f.terms_checked_at || null,
    }, "수집원을 제안 상태로 등록했습니다 — 검증 실행 → 검증 완료 → 활성화 순서로 진행하세요", "수집원 등록");
    if (r.ok) setF({ ...f, name: "", home_url: "", entry_urls: "" });
  };
  return (
    <details className="card">
      <summary><b>수집원 제안 등록</b> <span className="muted">— 등록만으로는 수집하지 않습니다</span></summary>
      <div className="dk-grid" style={{ marginTop: 8 }}>
        <label className="dk-field">이름<input value={f.name} onChange={set("name")} maxLength={120} /></label>
        <label className="dk-field">대표 주소(https)<input value={f.home_url} onChange={set("home_url")} /></label>
        <label className="dk-field">발행처<input value={f.publisher} onChange={set("publisher")} /></label>
        <label className="dk-field">언어<select value={f.language} onChange={set("language")}>
          <option value="ko">한국어</option><option value="ja">일본어</option><option value="en">영어</option></select></label>
        <label className="dk-field">수집 방법<select value={f.method} onChange={set("method")}>
          {Object.entries(METHOD_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="dk-field">요청 간격(초, 3 이상)<input type="number" min={3} max={120} value={f.request_interval_sec} onChange={set("request_interval_sec")} /></label>
        <label className="dk-field">실행당 문서 상한(≤100)<input type="number" min={1} max={100} value={f.max_items_per_run} onChange={set("max_items_per_run")} /></label>
        <label className="dk-field">실행당 본문 상한(≤20)<input type="number" min={0} max={20} value={f.max_bodies_per_run} onChange={set("max_bodies_per_run")} /></label>
      </div>
      <fieldset className="dk-row" style={{ border: 0, padding: 0, margin: "8px 0" }}>
        <legend className="muted">주종</legend>
        {CATEGORIES.map((c) => (
          <label key={c}><input type="checkbox" checked={cats.includes(c)}
            onChange={(e) => setCats(e.target.checked ? [...cats, c] : cats.filter((x) => x !== c))} /> {CATEGORY_LABEL[c]}</label>
        ))}
      </fieldset>
      {f.method !== "manual_url" && (
        <>
          <label className="dk-field">
            {f.method === "approved_page" ? "승인한 페이지 주소(줄마다 하나, 최대 20)" : f.method === "listing" ? "목록 페이지 주소(하나)" : "피드 주소(하나)"}
            <textarea rows={3} value={f.entry_urls} onChange={set("entry_urls")} />
          </label>
          <div className="dk-grid">
            {f.method === "listing" && (
              <label className="dk-field">글 경로 접두어(예: /newsroom/)<input value={f.link_prefix} onChange={set("link_prefix")} /></label>
            )}
            <label className="dk-field">본문 영역 id·class(선택)<input value={f.content_ids} onChange={set("content_ids")} placeholder="contents" /></label>
          </div>
        </>
      )}
      <div className="dk-grid">
        <label className="dk-field">이용 조건<select value={f.terms_status} onChange={set("terms_status")}>
          {Object.entries(TERMS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="dk-field">이용 조건 확인일<input type="date" value={f.terms_checked_at} onChange={set("terms_checked_at")} /></label>
        <label className="dk-field">이용 조건 주소<input value={f.terms_url} onChange={set("terms_url")} /></label>
        <label className="dk-field">문서 기본 사용 조건<select value={f.rights_default} onChange={set("rights_default")}>
          {Object.entries(RIGHTS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
      </div>
      <label className="dk-field">이용 조건 요지<textarea rows={2} value={f.terms_note} onChange={set("terms_note")} /></label>
      <label className="dk-field">robots.txt 확인 메모<input value={f.robots_note} onChange={set("robots_note")} /></label>
      <div className="actions">
        <button className="btn pick" disabled={busy || !f.name || !f.home_url || cats.length === 0} onClick={submit}>제안 등록</button>
      </div>
    </details>
  );
}

export function SourceActionBar({ s, lastValidation }: { s: SourceRow; lastValidation: RunStatus | null }) {
  const { run, busy } = useDrinksAction();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [terms, setTerms] = useState({ terms_status: s.terms_status, terms_note: s.terms_note ?? "", terms_url: s.terms_url ?? "",
    terms_checked_at: s.terms_checked_at ?? "", rights_default: s.rights_default });
  const a = sourceActions(s, lastValidation);
  const act = (action: string, extra: Record<string, unknown>, msg: string) =>
    run("source_action", { source_id: s.id, expected_version: s.version, action, ...extra }, msg, "수집원 변경");
  const request = async (mode: "collect" | "validate") => {
    const r = await run("request_run", { source_id: s.id, mode }, mode === "validate" ? "검증 실행을 요청했습니다" : "수집 실행을 요청했습니다", "실행 요청");
    setNote(dispatchNote(r));
  };
  if (s.state === "retired") return null;
  return (
    <div>
      <div className="actions">
        {a.validateRun && <button className="btn" disabled={busy} onClick={() => request("validate")}>검증 실행(저장 안 함)</button>}
        {a.markValidated && <button className="btn" disabled={busy} onClick={() => act("validate", { reason }, "검증 완료로 바꿨습니다")}>검증 완료로 표시</button>}
        {a.activate && <button className="btn pick" disabled={busy} onClick={() => act("activate", { reason }, "활성화했습니다 — 다음 일일 실행부터 수집합니다")}>활성화</button>}
        {a.collectNow && <button className="btn pick" disabled={busy} onClick={() => request("collect")}>지금 수집</button>}
        {a.pause && <button className="btn" disabled={busy || !reason} onClick={() => act("pause", { reason }, "일시 중지했습니다")}>일시 중지</button>}
        {a.retire && <button className="btn" disabled={busy || !reason} onClick={() => act("retire", { reason }, "수집원을 종료했습니다")}>종료</button>}
        <input aria-label="사유" placeholder="사유(중지·종료에 필요)" value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {(s.state === "validated" || s.state === "paused") && s.terms_status !== "verified" && (
        <p className="muted">활성화하려면 이용 조건을 확인(verified)해야 합니다.</p>
      )}
      {note && <p className="banner-info">{note}</p>}
      <details>
        <summary className="muted">이용 조건·사용 조건 고치기</summary>
        <div className="dk-grid">
          <label className="dk-field">이용 조건<select value={terms.terms_status} onChange={(e) => setTerms({ ...terms, terms_status: e.target.value as SourceRow["terms_status"] })}>
            {Object.entries(TERMS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className="dk-field">확인일<input type="date" value={terms.terms_checked_at} onChange={(e) => setTerms({ ...terms, terms_checked_at: e.target.value })} /></label>
          <label className="dk-field">이용 조건 주소<input value={terms.terms_url} onChange={(e) => setTerms({ ...terms, terms_url: e.target.value })} /></label>
          <label className="dk-field">문서 기본 사용 조건<select value={terms.rights_default} onChange={(e) => setTerms({ ...terms, rights_default: e.target.value })}>
            {Object.entries(RIGHTS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        </div>
        <label className="dk-field">요지<textarea rows={2} value={terms.terms_note} onChange={(e) => setTerms({ ...terms, terms_note: e.target.value })} /></label>
        <button className="btn" disabled={busy} onClick={() => act("update_terms", { ...terms, terms_checked_at: terms.terms_checked_at || null },
          "이용 조건을 저장했습니다")}>저장</button>
        <span className="muted"> 확인됨에서 내리면 활성 수집원은 자동으로 일시 중지됩니다(다시 켜는 것은 사람).</span>
      </details>
    </div>
  );
}

export function RetryButton({ sourceId, runId, failed }: { sourceId: string; runId: string; failed: number }) {
  const { run, busy } = useDrinksAction();
  const [note, setNote] = useState<string | null>(null);
  return (
    <span>
      <button className="btn" disabled={busy} onClick={async () => setNote(dispatchNote(await run("request_run",
        { source_id: sourceId, mode: "retry", retry_of: runId }, "재시도를 요청했습니다", "재시도 요청")))}>
        {failed > 0 ? `실패 ${failed}건만 재시도` : "처음부터 다시 실행"}
      </button>
      {note && <span className="muted"> {note}</span>}
    </span>
  );
}

type TopicOption = { id: string; title: string; status: string };

export function CollectedDocActions({ snapshotId, defaultTitle, defaultCats, topics, suggested }: {
  snapshotId: string; defaultTitle: string; defaultCats: string[]; topics: TopicOption[]; suggested: TopicOption[];
}) {
  const { run, busy } = useDrinksAction();
  const [mode, setMode] = useState<"none" | "new" | "link">("none");
  const [title, setTitle] = useState(defaultTitle.slice(0, 200));
  const [question, setQuestion] = useState("");
  const [lane, setLane] = useState("timely");
  const [cats, setCats] = useState<string[]>(defaultCats);
  const [topicId, setTopicId] = useState(suggested[0]?.id ?? "");
  const [role, setRole] = useState("evidence");
  const create = async (confirm = false) => {
    const r = await run("create_topic_from_snapshot", { snapshot_id: snapshotId, title, question, categories: cats, lane,
      confirm_not_duplicate: confirm }, "소재 후보로 등록했습니다(질문·인기 신호로 연결)", "소재 후보 등록");
    if (!r.ok && r.code === "duplicate_suggested" && window.confirm("같은 주종·질문의 소재가 이미 있습니다. 그래도 새로 등록할까요?")) {
      await create(true);
    }
    if (r.ok) setMode("none");
  };
  return (
    <div>
      <div className="actions">
        <button className="btn" onClick={() => setMode(mode === "new" ? "none" : "new")}>소재 후보로 등록</button>
        <button className="btn" onClick={() => setMode(mode === "link" ? "none" : "link")}>기존 소재 조사에 연결</button>
      </div>
      {mode === "new" && (
        <div className="dk-sub">
          <label className="dk-field">제목<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
          <label className="dk-field">독자 질문(사람이 씁니다)<input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000} /></label>
          <div className="dk-row">
            {CATEGORIES.map((c) => (
              <label key={c}><input type="checkbox" checked={cats.includes(c)}
                onChange={(e) => setCats(e.target.checked ? [...cats, c] : cats.filter((x) => x !== c))} /> {CATEGORY_LABEL[c]}</label>
            ))}
            <select value={lane} onChange={(e) => setLane(e.target.value)} aria-label="공급 경로">
              {Object.entries(LANE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          <button className="btn pick" disabled={busy || !title || !question || cats.length === 0} onClick={() => create()}>등록</button>
          <p className="muted">문서는 ‘질문·인기 신호’로 붙습니다. 사실 근거로 쓰려면 조사 단계에서 근거로 올리고 인용을 대조하세요.</p>
        </div>
      )}
      {mode === "link" && (
        <div className="dk-sub">
          <select value={topicId} onChange={(e) => setTopicId(e.target.value)} aria-label="연결할 소재">
            <option value="">소재 고르기</option>
            {suggested.length > 0 && <optgroup label="비슷한 소재 후보">
              {suggested.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</optgroup>}
            <optgroup label="열린 소재 전체">
              {topics.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</optgroup>
          </select>
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="역할">
            <option value="evidence">사실 근거 후보</option>
            <option value="discovery">질문·인기 신호</option>
          </select>
          <button className="btn pick" disabled={busy || !topicId} onClick={async () => {
            const r = await run("link_snapshot", { topic_id: topicId, snapshot_id: snapshotId, role,
              relation_note: "수집 문서에서 연결" }, "소재에 연결했습니다 — 근거 탭에서 새 근거 버전에 쓸 수 있습니다", "조사 연결");
            if (r.ok) setMode("none");
          }}>연결</button>
          <p className="muted">연결해도 기존 승인·편성은 바뀌지 않습니다. 근거로 쓰려면 새 근거 버전을 만들어 검토·승인하세요.</p>
        </div>
      )}
    </div>
  );
}
