"use client";

// 밈 제작안 — [쓰자] 뒤의 입력 칸과 승인·되돌리기·앱 게시 등록. 기획 v2 §5, 총괄 계획 §4-3.
// ★ 게시 버튼이 없다. 게시 대기까지가 끝이다. 돈이 나가는 길은 '글 초안 요청'(결재가 열려 있을 때만)뿐이다.
// ★ 막는 것은 DB 다(drinks_meme_blockers). 이 화면은 그 이유를 보여 준다.
import { useState } from "react";

import {
  FRAME_LABEL, MEME_MAX_SEC, MEME_MIN_SEC, MEME_PALETTES, SOUND_LABEL, buildMemeSpec, memeTotalSec, parseBeats,
  type MemeBudgetRow, type MemeDraftRow, type MemeFrame, type MemeReviewOption, type MemeSound,
} from "@/lib/drinks/meme";
import { useDrinksAction } from "./useDrinksAction";

const beatsToText = (d?: MemeDraftRow): string =>
  (d?.spec.beats ?? []).map((b) => {
    const t = b.keyword ? b.text.replace(b.keyword, `*${b.keyword}*`) : b.text;
    return `${t} | ${b.ms / 1000}`;
  }).join("\n");

export function MemeDraftForm({ cardId, topicId, draft, budgets, reviews }: {
  cardId?: string; topicId?: string; draft?: MemeDraftRow; budgets: MemeBudgetRow[]; reviews: MemeReviewOption[];
}) {
  const { run, busy } = useDrinksAction();
  const s = draft?.spec;
  const [frame, setFrame] = useState<MemeFrame>((s?.frame as MemeFrame) ?? "top_text");
  const [topLine, setTopLine] = useState(s?.top_line ?? "");
  const [titleKeyword, setTitleKeyword] = useState(s?.title_keyword ?? "");
  const [beatsText, setBeatsText] = useState(beatsToText(draft));
  const [caption, setCaption] = useState(s?.caption ?? "");
  const [palette, setPalette] = useState<string>(s?.scene?.palette ?? "amber");
  const [sound, setSound] = useState<MemeSound>((s?.audio?.mode as MemeSound) ?? "ambient_local");
  const [audioTitle, setAudioTitle] = useState(s?.audio?.title ?? "");
  const [audioId, setAudioId] = useState(s?.audio?.audio_id ?? "");
  const [startHint, setStartHint] = useState(s?.audio?.start_hint_sec === undefined ? "" : String(s.audio.start_hint_sec));
  const [containsInfo, setContainsInfo] = useState(s?.contains_info ?? false);
  const [reviewId, setReviewId] = useState(draft?.evidence_review_id ?? "");
  const [claimIds, setClaimIds] = useState((s?.claim_ids ?? []).join(", "));
  const [budgetId, setBudgetId] = useState("");
  const beats = parseBeats(beatsText);
  const total = memeTotalSec(beats);
  const owner = draft ? { draft_id: draft.id, expected_version: draft.version } : { ...(cardId ? { card_id: cardId } : {}), ...(topicId ? { topic_id: topicId } : {}) };
  const review = reviews.find((r) => r.review_id === reviewId);
  return (
    <div className="dk-sub" style={{ marginTop: 8 }}>
      <div className="dk-grid">
        <label className="dk-field">화면 틀
          <select value={frame} onChange={(e) => setFrame(e.target.value as MemeFrame)}>
            {(Object.keys(FRAME_LABEL) as MemeFrame[]).map((k) => <option key={k} value={k}>{FRAME_LABEL[k]}</option>)}
          </select>
        </label>
        <label className="dk-field">{frame === "top_text" ? "위쪽 글 한 줄" : "큰 제목"}<input value={topLine} maxLength={60} onChange={(e) => setTopLine(e.target.value)} /></label>
        {frame === "full_title" && <label className="dk-field">제목에서 강조할 낱말<input value={titleKeyword} maxLength={30} onChange={(e) => setTitleKeyword(e.target.value)} /></label>}
        <label className="dk-field">배경 색
          <select value={palette} onChange={(e) => setPalette(e.target.value)}>{MEME_PALETTES.map((p) => <option key={p} value={p}>{p}</option>)}</select>
        </label>
        <label className="dk-field">소리
          <select value={sound} onChange={(e) => setSound(e.target.value as MemeSound)}>
            {(Object.keys(SOUND_LABEL) as MemeSound[]).map((k) => <option key={k} value={k}>{SOUND_LABEL[k]}</option>)}
          </select>
        </label>
      </div>
      <label className="dk-field" style={{ marginTop: 8 }}>차례로 바뀌는 글 — 한 줄에 뜻 하나, 말하듯이. *낱말* 은 강조색, 글 뒤에 | 3.5 를 적으면 3.5초
        <textarea rows={4} value={beatsText} onChange={(e) => setBeatsText(e.target.value)} />
      </label>
      <p className={total < MEME_MIN_SEC || total > MEME_MAX_SEC ? "dk-bad" : "muted"} style={{ fontSize: 13, margin: "4px 0" }}>
        지금 {total.toFixed(1)}초 · 비트 {beats.length}개 (밈은 {MEME_MIN_SEC}~{MEME_MAX_SEC}초)
      </p>
      {sound === "app_manual" && (
        <div className="dk-grid">
          <label className="dk-field">앱에서 찾을 음원 이름<input value={audioTitle} onChange={(e) => setAudioTitle(e.target.value)} /></label>
          <label className="dk-field">음원 ID(있으면)<input value={audioId} onChange={(e) => setAudioId(e.target.value)} /></label>
          <label className="dk-field">시작 지점(초)<input value={startHint} inputMode="decimal" onChange={(e) => setStartHint(e.target.value)} /></label>
        </div>
      )}
      <label className="dk-field" style={{ marginTop: 8 }}>캡션<textarea rows={2} value={caption} onChange={(e) => setCaption(e.target.value)} /></label>
      <label style={{ display: "block", marginTop: 8 }}>
        <input type="checkbox" checked={containsInfo} onChange={(e) => setContainsInfo(e.target.checked)} /> 정보가 들어간 밈입니다(근거가 없으면 승인되지 않습니다)
      </label>
      {containsInfo && (
        <div className="dk-grid">
          <label className="dk-field">승인된 근거
            <select value={reviewId} onChange={(e) => setReviewId(e.target.value)}>
              <option value="">고르세요</option>
              {reviews.map((r) => <option key={r.review_id} value={r.review_id}>{r.title ?? r.review_id}</option>)}
            </select>
          </label>
          <label className="dk-field">쓰는 주장 ID(쉼표로)<input value={claimIds} onChange={(e) => setClaimIds(e.target.value)} /></label>
          {review && <p className="muted" style={{ fontSize: 13 }}>{review.claims.map((c) => `${c.claim_id}: ${c.text}`).join(" / ")}</p>}
        </div>
      )}
      <p className="muted" style={{ fontSize: 13 }}>장면은 코드가 만드는 배경입니다(0원). 우리가 산 반응 장면(한 장면 약 $0.45)을 넣는 길은 결재 전이라 꺼져 있습니다. 남의 영상은 넣을 수 없습니다.</p>
      <div className="actions">
        <button className="btn pick" disabled={busy || !topLine.trim() || beats.length === 0} onClick={() => run("meme_save_draft", {
          ...owner, ...(containsInfo && reviewId ? { evidence_review_id: reviewId } : {}),
          spec: buildMemeSpec({ frame, topLine, titleKeyword, beatsText, caption, palette, sound, audioTitle, audioId, startHintSec: startHint, containsInfo, claimIds }),
        }, "제작안을 저장했습니다", "제작안 저장")}>초안 저장</button>
      </div>
      {!draft && budgets.length > 0 && (
        <div className="dk-row" style={{ marginTop: 8 }}>
          <select value={budgetId} aria-label="개발 결재" onChange={(e) => setBudgetId(e.target.value)}>
            <option value="">글 초안을 모델에 맡기려면 결재를 고르세요</option>
            {budgets.map((b) => <option key={b.budget_id} value={b.budget_id}>{b.stage} (남은 ${b.remaining_usd.toFixed(2)})</option>)}
          </select>
          <button className="btn" disabled={busy || !budgetId} onClick={() => run("meme_request_text", { ...owner, budget_id: budgetId, frame },
            "글 초안을 요청했습니다 — 워커를 돌려야 처리됩니다", "글 초안 요청")}>글 초안 요청(1건 상한 $0.02)</button>
        </div>
      )}
    </div>
  );
}

export function MemeDraftActions({ draft }: { draft: MemeDraftRow }) {
  const { run, busy } = useDrinksAction();
  const [url, setUrl] = useState("");
  const act = (action: string, ok: string, extra: Record<string, unknown> = {}) =>
    run("meme_draft_action", { draft_id: draft.id, expected_version: draft.version, action, ...extra }, ok, "제작안 동작");
  const canReopen = ["approved", "stopped", "failed", "publish_waiting", "manual_audio"].includes(draft.status);
  const canReject = ["draft", "approved", "stopped", "failed", "publish_waiting", "manual_audio"].includes(draft.status);
  return (
    <div className="actions">
      {draft.status === "draft" && <button className="btn pick" disabled={busy || draft.blockers.length > 0} onClick={() => act("approve", "승인했습니다 — 제작 워커가 로컬로 만듭니다(0원)")}>승인</button>}
      {canReopen && <button className="btn" disabled={busy} onClick={() => act("reopen", "초안으로 되돌렸습니다")}>초안으로 되돌리기</button>}
      {canReject && <button className="btn" disabled={busy} onClick={() => act("reject", "버렸습니다")}>버리기</button>}
      {draft.status === "manual_audio" && (
        <span className="dk-row">
          <input value={url} aria-label="게시한 릴스 주소" placeholder="앱에서 올린 릴스 주소" onChange={(e) => setUrl(e.target.value)} />
          <button className="btn" disabled={busy || !url.trim()} onClick={() => act("manual_posted", "게시 링크를 등록했습니다", { url: url.trim() })}>링크 등록</button>
        </span>
      )}
    </div>
  );
}
