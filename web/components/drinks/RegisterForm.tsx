"use client";

// 소재 수동 등록 — 질문만, 또는 질문 + 출처(URL·직접 입력한 원문/발췌).
// 같은 주종·질문·대상·각도의 소재가 있으면 서버가 409(duplicate_suggested)로 멈추고, 여기서 사람이 고른다:
// [기존 소재 열기] / [기존 소재에 같은 질문 +1] / [다른 소재라서 새로 등록]. 자동 병합은 없다(명세 §5.4).
import Link from "next/link";
import { useState } from "react";

import {
  CATEGORY_LABEL, CATEGORIES, LANE_LABEL, QUESTION_KIND_LABEL, TOPIC_STATUS_LABEL, type Category, type Lane, type QuestionKind,
} from "@/lib/drinks/model";
import SourceFields, { EMPTY_SOURCE, hasSource, sourcePayload, type SourceInput } from "./SourceFields";
import { useDrinksAction } from "./useDrinksAction";

interface Dup {
  id: string;
  title: string;
  status: keyof typeof TOPIC_STATUS_LABEL;
  version: number;
}

const EMPTY = { title: "", question: "", reader_value: "", target_subject: "", angle: "" };

export default function RegisterForm() {
  const { run, busy } = useDrinksAction();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(EMPTY);
  const [cats, setCats] = useState<Category[]>([]);
  const [lane, setLane] = useState<Lane>("evergreen");
  const [kind, setKind] = useState<QuestionKind>("general");
  const [withSource, setWithSource] = useState(false);
  const [src, setSrc] = useState<SourceInput>(EMPTY_SOURCE);
  const [dups, setDups] = useState<Dup[] | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const reset = () => {
    setF(EMPTY);
    setCats([]);
    setKind("general");
    setSrc(EMPTY_SOURCE);
    setWithSource(false);
    setDups(null);
  };

  const submit = async (confirm: boolean) => {
    setNote(null);
    const payload: Record<string, unknown> = {
      ...f, categories: cats, lane, question_kind: kind, confirm_not_duplicate: confirm,
      source: withSource && hasSource(src) ? sourcePayload(src) : null,
    };
    const r = await run("create_topic", payload, "소재를 등록했습니다", "소재 등록");
    if (r.ok) {
      const s = r.result?.source as { depth?: string } | null | undefined;
      if (s?.depth === "metadata_only") setNote("출처는 URL 만 저장됐습니다(본문 미확보 — 근거로 쓰려면 본문·발췌를 추가하세요).");
      reset();
    } else if (r.code === "duplicate_suggested" && Array.isArray(r.detail)) {
      setDups(r.detail as Dup[]);
    }
  };

  const bump = async (id: string, version: number) => {
    const r = await run("topic_action", { topic_id: id, expected_version: version, action: "bump_signal" },
      "기존 소재에 같은 질문 1건을 더했습니다", "질문 기록");
    if (r.ok) reset();
  };

  if (!open) {
    return (
      <button className="btn pick" onClick={() => setOpen(true)}>
        + 소재·질문 직접 등록
      </button>
    );
  }

  const canSubmit = f.title.trim() && f.question.trim() && cats.length > 0 && !busy;
  return (
    <section className="card" aria-label="소재 등록">
      <h2>소재·질문 등록</h2>
      <p className="muted">질문만 등록해도 됩니다. 질문·인기 신호는 근거가 아니며, 사실 근거는 조사 단계에서 따로 붙입니다.</p>
      <div className="dk-grid">
        <label className="dk-field">
          <span>제목 *</span>
          <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} maxLength={200} />
        </label>
        <label className="dk-field">
          <span>공급 경로 *</span>
          <select value={lane} onChange={(e) => setLane(e.target.value as Lane)}>
            {Object.entries(LANE_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label className="dk-field">
          <span>질문 유형</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as QuestionKind)}>
            {Object.entries(QUESTION_KIND_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label className="dk-field">
          <span>대상 제품·공정</span>
          <input value={f.target_subject} onChange={(e) => setF({ ...f, target_subject: e.target.value })} />
        </label>
        <label className="dk-field">
          <span>각도</span>
          <input value={f.angle} onChange={(e) => setF({ ...f, angle: e.target.value })} placeholder="예: 라벨 읽는 법" />
        </label>
      </div>
      <label className="dk-field" style={{ marginTop: 10 }}>
        <span>애호가의 질문 *</span>
        <textarea value={f.question} onChange={(e) => setF({ ...f, question: e.target.value })} rows={2} />
      </label>
      <label className="dk-field" style={{ marginTop: 8 }}>
        <span>독자 효용 (보고 나서 무엇을 판단할 수 있나)</span>
        <input value={f.reader_value} onChange={(e) => setF({ ...f, reader_value: e.target.value })} />
      </label>
      <div className="dk-checks" style={{ marginTop: 10 }}>
        <span className="muted">주종 * (여러 개 가능)</span>
        {CATEGORIES.map((c) => (
          <label key={c}>
            <input
              type="checkbox"
              checked={cats.includes(c)}
              onChange={(e) => setCats(e.target.checked ? [...cats, c] : cats.filter((x) => x !== c))}
            />
            {CATEGORY_LABEL[c]}
          </label>
        ))}
      </div>
      <div className="dk-checks" style={{ marginTop: 10 }}>
        <label>
          <input type="checkbox" checked={withSource} onChange={(e) => setWithSource(e.target.checked)} />
          출처도 함께 등록
        </label>
      </div>
      {withSource && (
        <div className="dk-sub">
          <SourceFields value={src} onChange={setSrc} />
        </div>
      )}
      {dups && (
        <div className="banner-warn" role="alert" style={{ marginTop: 10 }}>
          <b>같은 주종·질문·대상·각도의 소재가 이미 있습니다.</b> 같은 소재면 새로 만들지 말고 기존 소재를 쓰세요.
          <ul>
            {dups.map((d) => (
              <li key={d.id}>
                <Link href={`/drinks/review/${d.id}`}>{d.title}</Link> ({TOPIC_STATUS_LABEL[d.status] ?? d.status}){" "}
                <button className="btn" disabled={busy} onClick={() => bump(d.id, d.version)}>
                  기존 소재에 같은 질문 +1
                </button>
              </li>
            ))}
          </ul>
          <button className="btn" disabled={busy} onClick={() => submit(true)}>다른 소재라서 새로 등록</button>
        </div>
      )}
      {note && <p className="dk-warn">{note}</p>}
      <div className="actions">
        <button className="btn pick" disabled={!canSubmit} onClick={() => submit(false)}>
          {busy ? "등록 중…" : "등록"}
        </button>
        <button className="btn" onClick={() => { reset(); setOpen(false); }}>닫기</button>
      </div>
    </section>
  );
}
