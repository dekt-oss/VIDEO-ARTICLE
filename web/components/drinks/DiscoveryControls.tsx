"use client";

// 소재 발견 운영자 동작 — 수동 링크 등록, 후보 → 소재(사람이 한국어 질문을 쓴다), 기각·병합, 발견 수집원 등록.
// ★ 후보는 규칙이 묶은 제안일 뿐이다. 소재로 올려도 경량 평가·조사·근거 승인·편성은 A단계 흐름에서 사람이 한다.
import { useState } from "react";

import { CATEGORIES, CATEGORY_LABEL, QUESTION_KIND_LABEL } from "@/lib/drinks/model";
import { PLATFORM_LABEL } from "@/lib/drinks/discovery";
import { useDrinksAction } from "./useDrinksAction";

export function ManualDiscoveryForm() {
  const { run, busy } = useDrinksAction();
  const [f, setF] = useState({ url: "", platform: "instagram", channel_name: "", title: "", question: "", note: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <details className="card">
      <summary><b>발견 자료 직접 등록</b> <span className="muted">— 인스타·레딧·카페 등 자동 수집이 안 되는 채널. 서버는 링크를 열지 않습니다</span></summary>
      <div className="dk-grid" style={{ marginTop: 8 }}>
        <label className="dk-field">링크<input value={f.url} onChange={set("url")} placeholder="https://" /></label>
        <label className="dk-field">플랫폼<select value={f.platform} onChange={set("platform")}>
          {Object.entries(PLATFORM_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="dk-field">채널·커뮤니티 이름<input value={f.channel_name} onChange={set("channel_name")} /></label>
        <label className="dk-field">제목(보이는 그대로)<input value={f.title} onChange={set("title")} maxLength={500} /></label>
      </div>
      <label className="dk-field">사람들이 묻는 질문(원문 그대로)<input value={f.question} onChange={set("question")} maxLength={300} /></label>
      <label className="dk-field">메모(무엇을 봤는지 — 지표를 추정해 적지 마세요)<textarea rows={2} value={f.note} onChange={set("note")} maxLength={1000} /></label>
      <button className="btn pick" disabled={busy || !f.url} onClick={async () => {
        const r = await run("add_discovery", f, "발견 자료를 등록했습니다", "발견 자료 등록");
        if (r.ok) setF({ ...f, url: "", title: "", question: "", note: "" });
      }}>등록</button>
    </details>
  );
}

export function DiscoverySourceForm() {
  const { run, busy } = useDrinksAction();
  const [platform, setPlatform] = useState("stackexchange");
  const [name, setName] = useState("");
  const [queries, setQueries] = useState("");
  const [lookback, setLookback] = useState("");
  const [cats, setCats] = useState<string[]>([]);
  const lookbackOk = lookback === "" || (/^[0-9]{1,4}$/.test(lookback) && Number(lookback) >= 1 && Number(lookback) <= 3650);
  return (
    <details className="card">
      <summary><b>발견 채널 등록</b> <span className="muted">— 공식 API 만. 등록 후 검증 실행 → 이용 조건 확인 → 활성화(수집원 화면)</span></summary>
      <div className="dk-grid" style={{ marginTop: 8 }}>
        <label className="dk-field">채널<select value={platform} onChange={(e) => setPlatform(e.target.value)}>
          <option value="stackexchange">Stack Exchange(Beer, Wine &amp; Spirits)</option>
          <option value="youtube">유튜브(키 필요)</option>
          <option value="naver">네이버 카페·블로그 검색(키 필요)</option>
        </select></label>
        <label className="dk-field">이름<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="dk-field">{platform === "stackexchange" ? "태그(쉼표로)" : "검색어(쉼표로)"}
          <input value={queries} onChange={(e) => setQueries(e.target.value)} placeholder={platform === "stackexchange" ? "sake, whisky" : "사케 보관, 막걸리 추천"} /></label>
        {platform === "stackexchange" && (
          <label className="dk-field">첫 실행 소급 일수(비우면 365일)
            <input value={lookback} onChange={(e) => setLookback(e.target.value)} inputMode="numeric" placeholder="예: 3000 (1~3650)" /></label>
        )}
      </div>
      <div className="dk-row">
        {CATEGORIES.map((c) => (
          <label key={c}><input type="checkbox" checked={cats.includes(c)}
            onChange={(e) => setCats(e.target.checked ? [...cats, c] : cats.filter((x) => x !== c))} /> {CATEGORY_LABEL[c]}</label>
        ))}
      </div>
      <button className="btn pick" disabled={busy || !name || !queries.trim() || cats.length === 0 || !lookbackOk} onClick={() =>
        run("register_discovery_source", { platform, name, categories: cats, queries: queries.split(",").map((x) => x.trim()).filter(Boolean),
          ...(platform === "stackexchange" && lookback ? { lookback_days: Number(lookback) } : {}) },
          "발견 채널을 제안 상태로 등록했습니다 — 수집원 화면에서 검증·활성화하세요", "발견 채널 등록")}>등록</button>
    </details>
  );
}

export function CandidateActions({ c, others }: {
  c: { id: string; version: number; key_question: string; reader_value: string | null };
  others: { id: string; key_question: string }[];
}) {
  const { run, busy } = useDrinksAction();
  const [mode, setMode] = useState<"none" | "promote" | "dismiss" | "merge">("none");
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [value, setValue] = useState(c.reader_value ?? "");
  const [cats, setCats] = useState<string[]>([]);
  const [kind, setKind] = useState("");   // 비우면 후보 신호에서 서버가 정한다
  const [reason, setReason] = useState("");
  const [into, setInto] = useState("");
  const promote = async (confirm = false) => {
    const r = await run("promote_candidate", { candidate_id: c.id, expected_version: c.version, title, question, reader_value: value,
      categories: cats, lane: "reader_question", confirm_not_duplicate: confirm, ...(kind ? { question_kind: kind } : {}) }, "소재로 올렸습니다(발견 자료는 질문·인기 신호로 연결)", "소재로 올리기");
    if (!r.ok && r.code === "duplicate_suggested" && window.confirm("같은 질문의 소재가 이미 있습니다. 그래도 새로 만들까요?")) await promote(true);
  };
  return (
    <div>
      <div className="actions">
        <button className="btn pick" onClick={() => setMode(mode === "promote" ? "none" : "promote")}>소재로 올리기</button>
        <button className="btn" onClick={() => setMode(mode === "dismiss" ? "none" : "dismiss")}>기각</button>
        {others.length > 0 && <button className="btn" onClick={() => setMode(mode === "merge" ? "none" : "merge")}>다른 후보와 합치기</button>}
      </div>
      {mode === "promote" && (
        <div className="dk-sub">
          <p className="muted">원문 질문: {c.key_question} — 남의 글을 옮기지 말고 술째리고의 질문·설명 각도로 다시 쓰세요.</p>
          <label className="dk-field">소재 제목<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
          <label className="dk-field">독자 질문(한국어)<input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000} /></label>
          <label className="dk-field">독자 효용<input value={value} onChange={(e) => setValue(e.target.value)} /></label>
          <label className="dk-field">질문 유형<select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">자동(후보 신호에서)</option>
            {Object.entries(QUESTION_KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
          <div className="dk-row">
            {CATEGORIES.map((k) => (
              <label key={k}><input type="checkbox" checked={cats.includes(k)}
                onChange={(e) => setCats(e.target.checked ? [...cats, k] : cats.filter((x) => x !== k))} /> {CATEGORY_LABEL[k]}</label>
            ))}
          </div>
          <button className="btn pick" disabled={busy || !title || !question || cats.length === 0} onClick={() => promote()}>올리기</button>
          <p className="muted">올린 뒤: 경량 평가 → 조사 → 공식·전문 원자료를 근거로 등록 → 근거 검토·승인. 발견 자료는 근거가 될 수 없습니다.</p>
        </div>
      )}
      {mode === "dismiss" && (
        <div className="dk-row">
          <input placeholder="기각 사유" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn" disabled={busy || !reason} onClick={() =>
            run("candidate_action", { candidate_id: c.id, expected_version: c.version, action: "dismiss", reason }, "기각했습니다", "기각")}>기각</button>
        </div>
      )}
      {mode === "merge" && (
        <div className="dk-row">
          <select value={into} onChange={(e) => setInto(e.target.value)} aria-label="합칠 후보">
            <option value="">합칠 후보 고르기</option>
            {others.map((o) => <option key={o.id} value={o.id}>{o.key_question.slice(0, 60)}</option>)}
          </select>
          <input placeholder="사유" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn" disabled={busy || !into} onClick={() =>
            run("candidate_action", { candidate_id: c.id, expected_version: c.version, action: "merge", into_candidate_id: into, reason },
              "합쳤습니다", "후보 합치기")}>합치기</button>
        </div>
      )}
    </div>
  );
}

export function ReopenCandidate({ id, version }: { id: string; version: number }) {
  const { run, busy } = useDrinksAction();
  return <button className="btn" disabled={busy} onClick={() =>
    run("candidate_action", { candidate_id: id, expected_version: version, action: "reopen" }, "다시 열었습니다", "다시 열기")}>다시 열기</button>;
}
