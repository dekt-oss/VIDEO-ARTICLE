"use client";

// 밈 보드 운영자 동작 — [쓰자]/[넘기기]/[나중에], 형식 칸 직접 입력, 관찰 계정 체크, 운영자 링크(T3).
// ★ [쓰자]는 결정만 기록한다. 형식 분석·Apify·영상 구매를 시작하는 길이 이 화면에 없다(기획 v2 §6-1 의 클릭 승인은 아직 연결 전).
import { useState } from "react";

import { DECISION_LABEL, FORMAT_FIELDS, STRUCTURE_LABEL, type CardDecision, type IgCardRow } from "@/lib/drinks/igTrends";
import { useDrinksAction } from "./useDrinksAction";

const DECISIONS: CardDecision[] = ["use", "pass", "later"];

export function CardDecisionButtons({ id, decision }: { id: string; decision: CardDecision | null }) {
  const { run, busy } = useDrinksAction();
  return (
    <div className="actions">
      {DECISIONS.map((d) => (
        <button key={d} className={d === "use" ? "btn pick" : "btn"} disabled={busy || decision === d} aria-pressed={decision === d}
          onClick={() => run("ig_card_decide", { card_id: id, decision: d }, `[${DECISION_LABEL[d]}] 로 기록했습니다`, "결정 기록")}>
          {DECISION_LABEL[d]}
        </button>
      ))}
    </div>
  );
}

export function CardFieldForm({ card }: { card: Pick<IgCardRow, "id" | "fields"> }) {
  const { run, busy } = useDrinksAction();
  const [field, setField] = useState("beat_count");
  const [value, setValue] = useState("");
  return (
    <details className="dk-sub">
      <summary className="muted">원본 릴스를 보고 칸 직접 넣기 <span style={{ fontSize: 12 }}>— 비트 수·컷 길이·반전 시점이 다 차면 정밀 틀이 됩니다</span></summary>
      <div className="dk-row" style={{ marginTop: 8 }}>
        <select value={field} aria-label="칸" onChange={(e) => { setField(e.target.value); setValue(""); }}>
          {FORMAT_FIELDS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        {field === "structure" ? (
          <select value={value} aria-label="구조" onChange={(e) => setValue(e.target.value)}>
            <option value="">비우기</option>
            {Object.entries(STRUCTURE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        ) : (
          <input value={value} aria-label="값" maxLength={1000} placeholder={card.fields?.[field]?.value ?? "값(비우면 지웁니다)"} onChange={(e) => setValue(e.target.value)} />
        )}
        <button className="btn" disabled={busy} onClick={async () => {
          const r = await run("ig_set_card_field", { card_id: card.id, field, value }, value ? "운영자 입력으로 저장했습니다" : "칸을 비웠습니다", "칸 저장");
          if (r.ok) setValue("");
        }}>저장</button>
      </div>
    </details>
  );
}

export function WatchAccountAction({ username, status }: { username: string; status: "candidate" | "active" | "paused" }) {
  const { run, busy } = useDrinksAction();
  const active = status === "active";
  return (
    <button className={active ? "btn" : "btn pick"} disabled={busy} onClick={() =>
      run("ig_watch_action", { username, action: active ? "pause" : "activate" },
        active ? `${username} 를 관찰에서 뺐습니다` : `${username} 를 관찰합니다 — 첫 관측일에 본 릴스는 신호에 넣지 않습니다`, "관찰 계정 변경")}>
      {active ? "빼기" : "체크(관찰 시작)"}
    </button>
  );
}

export function AddWatchAccountForm() {
  const { run, busy } = useDrinksAction();
  const [username, setUsername] = useState("");
  const [kind, setKind] = useState("meme");
  return (
    <details className="card">
      <summary><b>후보 계정 넣기</b> <span className="muted">— 공개 비즈니스·크리에이터 계정만 읽힙니다. 이름을 넣어도 체크하기 전에는 관찰하지 않습니다</span></summary>
      <div className="dk-row" style={{ marginTop: 8 }}>
        <input value={username} aria-label="인스타 계정 이름" placeholder="계정 이름(@ 없이)" maxLength={31} onChange={(e) => setUsername(e.target.value)} />
        <select value={kind} aria-label="계정 종류" onChange={(e) => setKind(e.target.value)}>
          <option value="meme">밈</option>
          <option value="drinks">술</option>
          <option value="explainer">설명형</option>
          <option value="other">기타</option>
        </select>
        <button className="btn" disabled={busy || !username.trim()} onClick={async () => {
          const r = await run("ig_watch_action", { username, action: "add", kind }, "후보에 넣었습니다", "후보 넣기");
          if (r.ok) setUsername("");
        }}>넣기</button>
      </div>
    </details>
  );
}

export function AddLinkForm() {
  const { run, busy } = useDrinksAction();
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [note, setNote] = useState("");
  return (
    <details className="card">
      <summary><b>본 릴스 링크 넣기(T3)</b> <span className="muted">— 서버는 링크를 열지 않습니다. 다음 수집 때 그 계정의 최근 릴스 25개를 공식 API 로 읽어 맞춰 봅니다</span></summary>
      <div className="dk-grid" style={{ marginTop: 8 }}>
        <label className="dk-field">릴스 주소<input value={url} placeholder="https://www.instagram.com/reel/…" onChange={(e) => setUrl(e.target.value)} /></label>
        <label className="dk-field">계정 이름(주소에 없으면 필수)<input value={username} placeholder="@ 없이" maxLength={31} onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="dk-field">메모<input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></label>
      </div>
      <button className="btn pick" style={{ marginTop: 8 }} disabled={busy || !url.trim()} onClick={async () => {
        const r = await run("ig_add_link", { url, username, note }, "링크를 넣었습니다 — 다음 수집(매일 KST 07:30) 때 확인합니다", "링크 넣기");
        if (r.ok) { setUrl(""); setUsername(""); setNote(""); }
      }}>넣기</button>
    </details>
  );
}
