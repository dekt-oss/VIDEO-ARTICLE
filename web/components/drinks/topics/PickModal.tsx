"use client";

// [이걸로 ▾] — 후보 하나를 소재로 올리면서 형식을 여러 개 고른다(한 소재 · 여러 형식, 2026-11-05 §3-5).
//   체크 셋(릴스·밈·카드뉴스) → 편성 주차(월요일) → 결재 → 형식별 예상 초안 비용(모르면 "모름") → pick_topic(formats 배열).
//   응답은 형식마다 네 갈래로 보여 준다(큐 등록+워커 깨움 / 큐 등록(다음 크론) / 이미 있음 / 실패). 규칙은 lib/drinks/pickModal.ts(순수).
// ★ 선택은 제작·구매·게시 승인이 아니다. 모델 호출은 AI 초안 한도(개발 결재 행) 안에서만 일어난다 — 막는 것은 DB 다.
//   모양은 승인 목업 docs/mockups/drinks/preview-format-choice-1280.png(큰 체크 줄 · 만들 주 · 안내 상자 · 비용 줄 · [취소]+[기획하기 →]).
import Link from "next/link";
import { useState } from "react";

import { CATEGORIES, CATEGORY_LABEL, QUESTION_KIND_LABEL } from "@/lib/drinks/model";
import {
  PICK_BRANCH_LABEL, PICK_FORMATS, PICK_FORMAT_HINT, PICK_FORMAT_LABEL, costSummary, pickOutcomes, toggleFormat, validateFormats,
  type EstimateMap, type PickFormat, type PickOutcome, type WeekOption,
  pickDefaults,
} from "@/lib/drinks/pickModal";
import { workHref } from "@/lib/drinks/work/types";
import { useDrinksAction } from "../useDrinksAction";

export interface PickModalProps {
  c: { id: string; version: number; key_question: string; reader_value: string | null };
  recommended: { format: PickFormat | "unknown"; reason: string };
  weeks: WeekOption[];
  /** 쓸 결재(pickBudget). null 이면 [예산 열기] 링크를 보인다 */
  budget: { budget_id: string; remaining_usd: number | string; expires_at: string } | null;
  /** 형식별 예상 초안 비용(drinks_develop_estimate). 못 읽었으면 전부 null */
  estimate: EstimateMap;
}

export default function PickModal({ c, recommended, weeks, budget, estimate }: PickModalProps) {
  const { run, busy } = useDrinksAction();
  const [open, setOpen] = useState(false);
  const [formats, setFormats] = useState<PickFormat[]>(recommended.format === "unknown" ? [] : [recommended.format]);
  const [week, setWeek] = useState(weeks[0]?.value ?? "");
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [value, setValue] = useState(c.reader_value ?? "");
  const defaults = pickDefaults(c.key_question);
  // 주종: 손대기 전에는 문장에서 고른 값(defaults.categories). 한 번 손대면 그 선택을 쓴다.
  const [cats, setCats] = useState<string[]>(defaults.categories);
  const [kind, setKind] = useState("");
  const [outcomes, setOutcomes] = useState<{ topicId: string | null; rows: PickOutcome[] } | null>(null);
  const check = validateFormats(formats);
  const cost = costSummary(estimate, formats);
  // 비워 둔 칸은 기본값으로(운영자 지시 2026-11-06). 운영자는 방향을 바꾸고 싶을 때만 입력한다.
  const effTitle = title.trim() || defaults.title;
  const effQuestion = question.trim() || defaults.question;
  const canSubmit = check.ok && Boolean(week && effTitle && effQuestion) && cats.length > 0 && !busy;

  const submit = async (confirm = false) => {
    if (!check.ok) return;
    const r = await run("pick_topic", {
      candidate_id: c.id, expected_version: c.version,
      formats: check.formats, format: check.formats[0],   // format = 대표(첫) 형식 — 옛 검증·drink_topic_picks 호환(G1)
      editorial_week: week, title: effTitle, question: effQuestion, reader_value: value, categories: cats, lane: "reader_question",
      recommended_format: recommended.format, recommended_reason: recommended.reason, confirm_not_duplicate: confirm,
      ...(kind ? { question_kind: kind } : {}), ...(budget ? { budget_id: budget.budget_id } : {}),
    }, "소재로 올렸습니다 — 형식별 결과는 아래에 있습니다", "[이걸로]");
    if (!r.ok && r.code === "duplicate_suggested" && window.confirm("같은 질문의 소재가 이미 있습니다. 그래도 새로 만들까요?")) return submit(true);
    if (!r.ok) return;
    const res = r.result as { topic_id?: string; picks?: { topic_id?: string }[] } | undefined;
    const topicId = res?.topic_id ?? res?.picks?.find((p) => p.topic_id)?.topic_id ?? null;
    setOutcomes({ topicId, rows: pickOutcomes(r.result as Parameters<typeof pickOutcomes>[0], check.formats, r.dispatch) });
  };

  return (
    <>
      <button className="btn pick dk-pick-trigger" type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}>이걸로 →</button>
      {open && (
        <div className="modal-backdrop" role="presentation" onClick={() => !busy && setOpen(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby={`pick-${c.id}`} style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
            <p className="dk-eyebrow" style={{ marginBottom: 6 }}>한 소재, 여러 형식</p>
            <h3 id={`pick-${c.id}`}>{defaults.question}</h3>
            {outcomes ? (
              <Outcomes topicId={outcomes.topicId} rows={outcomes.rows} onClose={() => setOpen(false)} />
            ) : (
              <>
                <p style={{ marginBottom: 12 }}>만들 형식을 모두 골라 주세요. 같은 근거로 각각 기획합니다.</p>
                <div className="dk-checks-big" role="group" aria-label="만들 형식">
                  {PICK_FORMATS.map((f) => (
                    <label key={f} className="dk-check">
                      <input type="checkbox" checked={formats.includes(f)} disabled={busy}
                        onChange={(e) => setFormats(toggleFormat(formats, f, e.target.checked))} />
                      <span>
                        <b>{PICK_FORMAT_LABEL[f]}</b>{recommended.format === f && <span className="pill dk-ok" style={{ marginLeft: 8 }}>추천</span>}
                        <small>{PICK_FORMAT_HINT[f]}</small>
                      </span>
                    </label>
                  ))}
                </div>
                {!check.ok && <p className="dk-warn" style={{ margin: "0 0 10px", fontSize: 14 }}>{check.reason}</p>}
                <p className="dk-defaults">
                  <b>이대로 진행합니다</b> — 제목 &ldquo;{effTitle}&rdquo; · 주종 {cats.length > 0 ? cats.map((k) => CATEGORY_LABEL[k as keyof typeof CATEGORY_LABEL] ?? k).join("·") : <b className="dk-bad">못 찾음</b>}
                </p>
                <details className="dk-optional" open={defaults.categories.length === 0 ? true : undefined}>
                  <summary>방향 직접 정하기 <span className="muted">(선택 — 바꾸고 싶을 때만)</span></summary>
                <label className="dk-modal-label">소재 제목<input value={title} maxLength={200} placeholder={defaults.title} onChange={(e) => setTitle(e.target.value)} /></label>
                <label className="dk-modal-label">독자 질문(한국어)<input value={question} maxLength={1000} placeholder={defaults.question} onChange={(e) => setQuestion(e.target.value)} /></label>
                <label className="dk-modal-label">독자 효용<input value={value} onChange={(e) => setValue(e.target.value)} /></label>
                <div className="dk-checks" style={{ margin: "12px 0 0" }} role="group" aria-label="주종">
                  <span style={{ fontWeight: 700 }}>주종</span>
                  {CATEGORIES.map((k) => (
                    <label key={k}><input type="checkbox" checked={cats.includes(k)}
                      onChange={(e) => setCats(e.target.checked ? [...cats, k] : cats.filter((x) => x !== k))} /> {CATEGORY_LABEL[k]}</label>
                  ))}
                </div>
                <label className="dk-modal-label">질문 유형 <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>(비우면 후보 신호에서 자동)</span>
                  <select value={kind} onChange={(e) => setKind(e.target.value)}>
                    <option value="">자동(후보 신호에서)</option>
                    {Object.entries(QUESTION_KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </label>
                </details>
                <label className="dk-modal-label">만들 주
                  <select value={week} onChange={(e) => setWeek(e.target.value)}>
                    {weeks.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                  </select>
                </label>
                <div className="dk-modal-info">
                  <p>선택은 제작·구매·게시 승인이 아닙니다.</p>
                  <p>
                    AI 초안 한도: {budget
                      ? <b>남은 ${Number(budget.remaining_usd).toFixed(2)} · {budget.expires_at.slice(0, 10)}까지</b>
                      : <><b className="dk-bad">이번 주 AI 초안 한도를 다 썼습니다</b> — <Link href="/drinks/studio?tab=candidates">소재 고르기 위 칸에서 [한도 +$1]</Link></>}
                  </p>
                  <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>영상 구매는 따로 승인합니다 · 모르는 비용은 0원으로 쓰지 않습니다.</p>
                </div>
                <p className="dk-cost-line">
                  예상 초안 비용: {cost.lines.length === 0 ? <span>형식을 고르면 보입니다</span>
                    : cost.lines.map((l) => <span key={l.format} style={{ marginRight: 8 }}>{PICK_FORMAT_LABEL[l.format]} <b>{l.text}</b></span>)}
                  {cost.lines.length > 0 && <> · 합계 <b>{cost.total}</b></>}
                </p>
                <p className="muted" style={{ fontSize: 12, margin: 0 }}>추천 이유: {recommended.reason}</p>
                <div className="dk-modal-actions">
                  <button className="btn" type="button" disabled={busy} onClick={() => setOpen(false)}>취소</button>
                  <button className="btn pick" type="button" disabled={!canSubmit} onClick={() => submit()}>
                    {busy ? "보내는 중…" : check.ok ? `선택한 ${check.formats.length}개 형식으로 기획하기 →` : "형식을 하나 이상 골라 주세요"}
                  </button>
                </div>
                {check.ok && !canSubmit && !busy && <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>이 질문에서 주종을 찾지 못했습니다 — 위 [방향 직접 정하기]에서 주종을 하나 골라 주세요.</p>}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function Outcomes({ topicId, rows, onClose }: { topicId: string | null; rows: PickOutcome[]; onClose: () => void }) {
  const tone = (b: PickOutcome["branch"]) => (b === "failed" ? "pill reject" : b === "existing" ? "pill" : "pill on");
  return (
    <>
      <p>소재로 올렸습니다. 형식마다 결과가 다릅니다 — 실패한 형식은 작업공간에서 다시 요청합니다.</p>
      {rows.map((o) => (
        <div key={o.format} className="list-row">
          <span><b>{PICK_FORMAT_LABEL[o.format]}</b> <span className={tone(o.branch)}>{PICK_BRANCH_LABEL[o.branch]}</span><br /><span className="muted">{o.text}</span></span>
          {topicId && <Link className="btn" href={workHref({ topic_id: topicId, format_intent: o.format, meme_draft_id: null, source: "topic" })}>작업공간 →</Link>}
        </div>
      ))}
      {!topicId && <p className="muted">응답에 소재 id 가 없어 작업공간 링크를 만들지 못했습니다 — [내 소재] 탭에서 찾으세요.</p>}
      <div className="actions"><button className="btn" type="button" onClick={onClose}>닫기</button></div>
    </>
  );
}
