// 주류 발행 (/drinks/publish) — 계정·발행안·승인·예약·게시 여부 확인(명세 §9.3, D단계 2026-10-27).
// ★ 이 화면은 인스타에 직접 올리지 않는다. 승인·예약까지 하고, 게시는 워커(engine.drinks_publish)가 예약 시각에
//   DB 재확인(지문·검수·계정·발행 스위치) 뒤에 한다. unknown 은 '확인 필요'에 두고 다시 게시 버튼을 주지 않는다.
import Link from "next/link";

import LoadProblem from "@/components/drinks/LoadProblem";
import { AccountActions, CreatePublication, RegisterAccount, RequestActions } from "@/components/drinks/PublishControls";
import {
  ACCOUNT_STATUS_LABEL, CONNECTION_LABEL, PUB_STATUS_LABEL, PUB_TABS, kst, loadPublishBoard, pubTab, type PubTab,
} from "@/lib/drinks/publishQueries";

export const dynamic = "force-dynamic";

const SLOT_LABEL: Record<string, string> = { morning: "아침(06–11시)", afternoon: "낮(11–17시)", evening: "저녁(17–22시)", night: "밤(22–06시)" };

export default async function DrinksPublishPage(props: { searchParams: Promise<{ tab?: string }> }) {
  const { tab: raw } = await props.searchParams;
  const tab: PubTab = raw && raw in PUB_TABS ? (raw as PubTab) : "attention";
  const board = await loadPublishBoard();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 발행</h1>
        <span className="muted">인스타 카드뉴스·릴스 — 승인·예약·게시 확인</span>
      </div>
      <p className="banner-info" style={{ marginTop: 12 }}>
        게시는 <b>승인 → 예약</b> 뒤 워커가 예약 시각에 합니다. 예약 시각보다 2시간 넘게 늦으면 게시하지 않고 멈춥니다.
        게시 여부를 모르는 것(응답 끊김)은 <b>다시 게시하지 않고</b> 인스타 조회로 대조합니다. 실제 계정 게시는 계정 연결과
        운영자 승인 전까지 꺼져 있습니다(시험용 가짜 계정만 돕니다).
      </p>
      {board.state !== "ok" ? (
        <LoadProblem state={board.state} error={board.state === "failed" ? board.error : undefined} />
      ) : (() => {
        const { accounts, requests, ready_outputs: ready, slot_weights: slots } = board.data;
        const accLabel = new Map(accounts.map((a) => [a.id, `${a.display_name} (${a.external_account_id})`]));
        const publishable = accounts.filter((a) => a.status !== "disabled").map((a) => ({ id: a.id,
          label: `${a.display_name} · ${a.external_account_id}${a.connection === "fake" ? " · 시험" : ""}${a.publish_enabled ? "" : " · 발행 꺼짐"}`,
          postTypes: a.capabilities?.post_types ?? [] }));
        const best = slots && Object.keys(slots).length
          ? Object.entries(slots).sort((x, y) => y[1] - x[1])[0] : null;
        const slotHint = best && best[1] > 0 ? SLOT_LABEL[best[0]] ?? best[0] : null;
        const counts = Object.fromEntries((Object.keys(PUB_TABS) as PubTab[]).map((k) => [k, requests.filter((r) => pubTab(r.status) === k).length]));
        const rows = requests.filter((r) => pubTab(r.status) === tab);
        return (
          <>
            <h2>계정</h2>
            {accounts.length === 0 ? <p className="muted">등록된 계정이 없습니다(미연결).</p> : accounts.map((a) => (
              <div key={a.id} className="list-row">
                <span>
                  <b>{a.display_name}</b> <span className="muted">· {a.external_account_id} · {CONNECTION_LABEL[a.connection] ?? a.connection}</span>{" "}
                  <span className="pill">{ACCOUNT_STATUS_LABEL[a.status] ?? a.status}</span>{" "}
                  <span className="pill">{a.publish_enabled ? "발행 켜짐" : "발행 꺼짐"}</span>
                  {a.status_reason && <span className="muted"> — {a.status_reason}</span>}
                  <span className="muted"> · 형식: {(a.capabilities?.post_types ?? []).join(", ") || "없음"}</span>
                </span>
                <AccountActions id={a.id} version={a.version} status={a.status} publishEnabled={a.publish_enabled} />
              </div>
            ))}
            <details style={{ margin: "8px 0 16px" }}>
              <summary>계정 등록</summary>
              <RegisterAccount />
            </details>

            <h2>발행안을 만들 수 있는 결과물 ({ready.length})</h2>
            {ready.length === 0 ? <p className="muted">검수 승인된(그리고 지금도 근거가 유효한) 파일 묶음 중 발행안이 없는 것이 없습니다.</p>
              : ready.map((o) => (
                <div key={o.output_review_id} className="list-row" style={{ alignItems: "flex-start" }}>
                  <span>
                    <Link href={`/drinks/production/${o.plan_revision_id}`}>{o.topic_title}</Link>{" "}
                    <span className="pill">{o.format === "carousel" ? `카드뉴스 ${o.pages}장` : "릴스"}</span>
                    <span className="muted"> · 검수 {kst(o.reviewed_at)}</span>
                  </span>
                  <CreatePublication outputReviewId={o.output_review_id} accounts={publishable}
                    postType={o.format === "carousel" ? "carousel" : "reel"} slotHint={slotHint} />
                </div>
              ))}

            <h2 style={{ marginTop: 20 }}>발행 요청</h2>
            <nav className="dk-tabs" aria-label="발행 탭">
              {(Object.keys(PUB_TABS) as PubTab[]).map((k) => (
                <Link key={k} href={`/drinks/publish?tab=${k}`} data-active={k === tab}>{PUB_TABS[k]} ({counts[k]})</Link>
              ))}
            </nav>
            {board.data.requests_truncated && <p className="banner-block">최근 300건만 보입니다 — 오래된 요청은 잘렸습니다.</p>}
            {rows.length === 0 ? <p className="muted">{requests.length === 0 ? "발행 요청이 없습니다(정상 0건)." : "이 탭에 해당하는 요청이 없습니다."}</p>
              : rows.map((r) => {
                const pages = (r.files ?? []).filter((f) => f.role === "page").length;
                const what = r.post_type === "carousel" ? `카드뉴스 ${pages}장` : "릴스(영상 + 커버)";
                const summary = `계정: ${accLabel.get(r.account_id) ?? r.target_external_account_id}\n파일: ${what}\n시각: ${kst(r.publish_at)} (한국)\n캡션: ${r.caption || "(없음)"}`;
                return (
                  <div key={r.id} className="list-row" style={{ alignItems: "flex-start" }}>
                    <span style={{ maxWidth: 640 }}>
                      <b>{r.topic_title}</b> <span className="pill">{what}</span>{" "}
                      <span className="pill" data-tone={r.status === "unknown" ? "warn" : undefined}>{PUB_STATUS_LABEL[r.status]}</span>
                      <div className="muted">{accLabel.get(r.account_id) ?? r.target_external_account_id} · 게시 시각 {kst(r.publish_at)} (한국)
                        {r.published_at && <> · 게시됨 {kst(r.published_at)}</>}</div>
                      <div style={{ whiteSpace: "pre-wrap" }}>{r.caption || <span className="muted">(캡션 없음)</span>}</div>
                      {r.status === "unknown" && <div className="banner-block">게시 여부 확인 필요 — 응답이 끊겨 게시됐는지 모릅니다. 다시 게시하지 않고, 다음 워커 실행이 인스타 조회로 대조합니다.{r.cancel_requested && " (취소 요청 있음 — 이미 게시됐으면 취소되지 않습니다)"}</div>}
                      {r.status === "paused" && <div className="banner-info">멈춤: {r.pause_reason ?? r.pause_code}</div>}
                      {r.status === "failed" && <div className="banner-info">실패(게시 안 됨 확인): {r.error_message ?? r.error_code}</div>}
                      {r.block && r.status !== "paused" && <div className="muted">지금 게시 조건: {r.block}</div>}
                      {r.reconcile_state === "cancel_not_applied" && <div className="banner-info">취소 요청 전에 이미 게시돼 취소되지 않았습니다.</div>}
                      {r.external_url && <div><a href={r.external_url} target="_blank" rel="noreferrer">게시물 보기</a></div>}
                      {r.approval_digest && <div className="muted">승인 지문 {r.approval_digest.slice(0, 12)}…{r.approval_digest !== r.current_digest && " ⚠ 지금 내용과 다름"}</div>}
                    </span>
                    <RequestActions id={r.id} version={r.version} status={r.status} digest={r.approval_digest} summary={summary} />
                  </div>
                );
              })}
          </>
        );
      })()}
    </main>
  );
}
