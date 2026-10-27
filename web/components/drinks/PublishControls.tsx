"use client";

// 주류 발행 운영자 동작 — 계정 등록·발행 스위치, 발행안 작성, 승인(지문 확인)·예약·멈춤·재개·취소·재시도, 전략 반영·기각.
// ★ 화면은 인스타에 직접 올리지 못한다. 게시는 워커(engine.drinks_publish)가 예약 시각에 DB 재확인 뒤에 한다.
// ★ 막는 것은 DB 다(0055). 버튼을 숨기는 것은 편의일 뿐이다.
import { useState } from "react";

import { useDrinksAction } from "./useDrinksAction";

export function RegisterAccount() {
  const { run, busy } = useDrinksAction();
  const [f, setF] = useState({ external_account_id: "", display_name: "", account_type: "business", connection: "instagram_login",
    credential_ref: "", carousel: true, reel: false });
  const set = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const fake = f.connection === "fake";
  return (
    <div className="dk-row" style={{ flexWrap: "wrap", gap: 6 }}>
      <select value={f.connection} onChange={(e) => set("connection", e.target.value)}>
        <option value="instagram_login">Instagram 로그인</option>
        <option value="facebook_login">Facebook 로그인(페이지 연결)</option>
        <option value="fake">시험용 가짜 계정</option>
      </select>
      <input placeholder={fake ? "fake_로 시작하는 ID" : "인스타 계정 ID(숫자)"} value={f.external_account_id}
        onChange={(e) => set("external_account_id", e.target.value)} />
      <input placeholder="표시 이름(예: 술째리고)" value={f.display_name} onChange={(e) => set("display_name", e.target.value)} />
      <select value={f.account_type} onChange={(e) => set("account_type", e.target.value)}>
        <option value="business">비즈니스</option><option value="creator">크리에이터</option><option value="test">시험</option>
      </select>
      {!fake && <input placeholder="토큰을 둔 서버 비밀 이름(예: DRINKS_IG_TOKEN)" value={f.credential_ref}
        onChange={(e) => set("credential_ref", e.target.value.toUpperCase())} />}
      <label className="muted"><input type="checkbox" checked={f.carousel} onChange={(e) => set("carousel", e.target.checked)} /> 카드뉴스</label>
      <label className="muted"><input type="checkbox" checked={f.reel} onChange={(e) => set("reel", e.target.checked)} /> 릴스</label>
      <button className="btn" disabled={busy || !f.external_account_id || !f.display_name || (!fake && !f.credential_ref)}
        onClick={() => run("register_account", { external_account_id: f.external_account_id.trim(), display_name: f.display_name.trim(),
          account_type: f.account_type, connection: f.connection, credential_ref: fake ? null : f.credential_ref.trim(),
          capabilities: { post_types: [f.carousel && "carousel", f.reel && "reel"].filter(Boolean) } },
          "계정을 등록했습니다 — 워커가 토큰 주인을 대조한 뒤 '연결 확인됨'이 됩니다", "계정 등록")}>계정 등록</button>
      <span className="muted">토큰 원문은 여기 넣지 않습니다. 서버 비밀 저장소에 두고 그 이름만 적습니다.</span>
    </div>
  );
}

export function AccountActions({ id, version, status, publishEnabled }: { id: string; version: number; status: string; publishEnabled: boolean }) {
  const { run, busy } = useDrinksAction();
  const go = (action: string, msg: string, extra: Record<string, unknown> = {}) =>
    run("account_action", { account_id: id, expected_version: version, action, ...extra }, msg, "계정");
  return (
    <span className="dk-row">
      {status === "active" && !publishEnabled && (
        <button className="btn pick" disabled={busy} onClick={() => {
          if (window.confirm("이 계정의 발행을 켭니다. 승인·예약한 게시물이 예약 시각에 실제로 공개 게시됩니다. 켤까요?"))
            go("enable_publish", "발행을 켰습니다");
        }}>발행 켜기</button>
      )}
      {publishEnabled && <button className="btn" disabled={busy} onClick={() => go("disable_publish", "발행을 껐습니다 — 이 계정의 예약은 멈춥니다")}>발행 끄기</button>}
      {["reauth_required", "mismatch"].includes(status) && (
        <button className="btn" disabled={busy} onClick={() => go("request_verification", "다음 워커 실행 때 다시 대조합니다")}>다시 대조</button>
      )}
      {status !== "disabled" && (
        <button className="btn" disabled={busy} onClick={() => {
          const reason = window.prompt("사용 중지 사유");
          if (reason) go("disable", "계정을 사용 중지했습니다", { reason });
        }}>사용 중지</button>
      )}
    </span>
  );
}

/** 발행안 작성: 계정을 고르고(기본 계정 없음) 캡션·게시 시각(한국 시각)을 적는다. */
export function CreatePublication({ outputReviewId, accounts, postType, slotHint }: {
  outputReviewId: string; accounts: { id: string; label: string; postTypes: string[] }[]; postType: "carousel" | "reel"; slotHint: string | null;
}) {
  const { run, busy } = useDrinksAction();
  const usable = accounts.filter((a) => a.postTypes.includes(postType));
  const [acc, setAcc] = useState("");
  const [caption, setCaption] = useState("");
  const [when, setWhen] = useState("");
  if (usable.length === 0) return <span className="muted">이 형식({postType === "carousel" ? "카드뉴스" : "릴스"})을 올릴 수 있는 계정이 없습니다 — 위에서 계정을 등록하세요.</span>;
  return (
    <div className="dk-row" style={{ flexWrap: "wrap", gap: 6 }}>
      <select value={acc} onChange={(e) => setAcc(e.target.value)}>
        <option value="">계정 고르기</option>
        {usable.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
      </select>
      <textarea rows={3} style={{ minWidth: 320 }} placeholder="캡션(원문에 없는 숫자·양·권고는 게시 직전 검사에서 막힙니다)" value={caption}
        onChange={(e) => setCaption(e.target.value)} />
      <label className="muted">게시 시각(한국) <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
      {slotHint && <span className="muted">전략 추천 시간대: {slotHint}</span>}
      <button className="btn" disabled={busy || !acc} onClick={() => run("create_publication", {
        output_review_id: outputReviewId, account_id: acc, caption,
        publish_at: when ? new Date(`${when}:00+09:00`).toISOString() : null,
      }, "발행안을 만들었습니다(작성 중)", "발행안 작성")}>발행안 만들기</button>
    </div>
  );
}

export function RequestActions({ id, version, status, digest, summary }: {
  id: string; version: number; status: string; digest: string | null; summary: string;
}) {
  const { run, busy } = useDrinksAction();
  const go = (action: string, msg: string, extra: Record<string, unknown> = {}) =>
    run("publication_action", { request_id: id, expected_version: version, action, ...extra }, msg, "발행");
  const ask = (q: string) => window.prompt(q) ?? "";
  return (
    <span className="dk-row" style={{ flexWrap: "wrap" }}>
      {status === "draft" && <button className="btn pick" disabled={busy} onClick={() => go("submit", "승인 요청했습니다")}>승인 요청</button>}
      {status === "awaiting_approval" && (
        <>
          <button className="btn pick" disabled={busy || !digest} onClick={() => {
            // 승인 모달(§9.3): 계정·파일·캡션·시각을 보여 주고, 공개 게시임을 밝힌다. 보여준 지문을 그대로 서버에 돌려준다.
            if (window.confirm(`${summary}\n\n승인하면 예약 시각에 인스타에 공개 게시됩니다(예약은 다음 단계에서).\n승인 지문 ${digest?.slice(0, 12)}…\n승인할까요?`))
              go("approve", "승인했습니다", { expected_digest: digest });
          }}>승인(공개 게시)</button>
          <button className="btn" disabled={busy} onClick={() => go("withdraw", "작성 중으로 되돌렸습니다")}>고치러 되돌리기</button>
        </>
      )}
      {status === "approved" && <button className="btn pick" disabled={busy} onClick={() => go("schedule", "예약했습니다 — 예약 시각에 워커가 게시합니다")}>예약</button>}
      {status === "paused" && <button className="btn" disabled={busy} onClick={() => go("resume", "다시 예약했습니다")}>다시 예약</button>}
      {status === "failed" && <button className="btn" disabled={busy} onClick={() => go("retry", "다시 예약했습니다")}>다시 시도</button>}
      {(status === "approved" || status === "scheduled") && (
        <button className="btn" disabled={busy} onClick={() => { const r = ask("멈추는 이유"); if (r) go("pause", "멈췄습니다", { reason: r }); }}>멈춤</button>
      )}
      {!["published", "canceled", "failed"].includes(status) && (
        <button className="btn" disabled={busy} onClick={() => {
          const r = ask(status === "unknown" || status === "publishing"
            ? "게시 여부가 정해지지 않아 취소 '요청'만 남습니다(이미 게시됐으면 취소되지 않습니다). 이유:" : "취소 이유");
          if (r) go("cancel", status === "unknown" || status === "publishing" ? "취소 요청을 남겼습니다" : "취소했습니다", { reason: r });
        }}>취소</button>
      )}
    </span>
  );
}

export function StrategyDecision({ proposalId, sufficient }: { proposalId: string; sufficient: boolean }) {
  const { run, busy } = useDrinksAction();
  return (
    <span className="dk-row">
      <button className="btn pick" disabled={busy || !sufficient} title={sufficient ? "" : "표본이 부족해 반영할 가중치가 없습니다"}
        onClick={() => {
          if (window.confirm("이 제안을 반영해 새 전략 버전을 만듭니다. 다음 편성 후보 순서가 바뀝니다. 반영할까요?"))
            run("strategy_action", { proposal_id: proposalId, action: "accept" }, "전략을 반영했습니다(새 버전)", "전략 반영");
        }}>반영</button>
      <button className="btn" disabled={busy} onClick={() => {
        const reason = window.prompt("기각 사유");
        if (reason) run("strategy_action", { proposal_id: proposalId, action: "reject", reason }, "제안을 기각했습니다", "전략 기각");
      }}>기각</button>
    </span>
  );
}
