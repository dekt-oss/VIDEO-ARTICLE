// AI 사실 확인 요약(2026-11-06, 운영자 승인 — docs/deviation-drinks-auto-factcheck.md). 근거 칸 맨 위에 둔다.
// 운영자가 할 일은 이 상자를 읽고 [승인]을 누르는 것이다. '불확실'·'AI 가 확인하지 못한 주장'만 직접 본다.
// 훅이 없어 서버·클라이언트 어디서나 쓸 수 있다. 판정 계산은 lib/drinks/factcheck.ts.
import { FACTCHECK_STATUS_TEXT, VERDICT_LABEL, VERDICT_TONE, type FactcheckResult } from "@/lib/drinks/factcheck";
import { safeHref } from "@/lib/drinks/trends";

export default function FactcheckSummary({ fc, sameReview }: { fc: FactcheckResult; sameReview: boolean }) {
  const { counts } = fc;
  return (
    <section className="dk-fc" aria-label="AI 사실 확인">
      <p className="dk-fc-head">
        AI 사실 확인: 맞음 <b>{counts.TRUE}</b> · 틀림 <b>{counts.FALSE}</b> · 불확실 <b>{counts.UNCERTAIN}</b>
      </p>
      <p className="dk-fc-sub">
        소재 질문이 담은 주장을 AI 가 원문 인용만 보고 판정했고, 코드가 다시 확인했습니다(없는 근거 번호·인용에 없는 숫자는 &lsquo;불확실&rsquo;로 내림).
        맞음·틀림의 근거가 된 주장은 &lsquo;확인됨&rsquo;으로 미리 채웠습니다. 읽어 보고 맞으면 승인하세요.
        {!sameReview && " ※ 지금 근거는 그 뒤에 고친 버전이라, 아래 판정은 이전 버전 기준입니다."}
      </p>
      {fc.status !== "ok" && <p className="banner-warn" role="status">{FACTCHECK_STATUS_TEXT[fc.status]}{fc.note ? ` (${fc.note})` : ""}</p>}
      {fc.status === "ok" && fc.assertions.length === 0 && <p className="muted">AI 가 판정할 주장을 찾지 못했습니다 — 아래 주장을 직접 확인하세요.</p>}
      <ol className="dk-fc-list">
        {fc.assertions.map((a, i) => (
          <li key={i} className="dk-fc-item">
            <span className={`pill dk-${VERDICT_TONE[a.verdict]}`}>{VERDICT_LABEL[a.verdict]}</span>{" "}
            <b>{a.assertion_ko}</b>
            {a.reason_ko && <div className="dk-fc-reason">{a.reason_ko}</div>}
            {a.code_note && <div className="dk-fc-note">코드 확인: {a.code_note}{a.model_verdict && a.model_verdict !== a.verdict ? ` (AI 는 ${VERDICT_LABEL[a.model_verdict as keyof typeof VERDICT_LABEL] ?? a.model_verdict}라고 함)` : ""}</div>}
            {a.sources.length > 0 && (
              <div className="dk-fc-src">
                근거:{" "}
                {a.sources.map((s, j) => {
                  const href = s.url ? safeHref(s.url) : null;
                  return (
                    <span key={j}>
                      {j > 0 && " · "}
                      <span className="pill">{s.claim_id}</span>{" "}
                      {href ? <a href={href} target="_blank" rel="noreferrer noopener">{s.title}</a> : s.title}
                      {s.publisher ? ` (${s.publisher})` : ""}
                    </span>
                  );
                })}
              </div>
            )}
          </li>
        ))}
      </ol>
      {fc.notSupported.length > 0 && (
        <div className="dk-fc-todo" role="status">
          <b>직접 확인할 주장 {fc.notSupported.length}개</b> — AI 가 &lsquo;확인됨&rsquo;으로 채우지 않았습니다. 아래 근거표에서 원문 인용을 읽고 &lsquo;뒷받침 확인&rsquo;을 고르세요.
          <ul>
            {fc.notSupported.map((n) => (
              <li key={n.claim_id}><span className="pill">{n.claim_id}</span> {n.text} <span className="muted">— {n.why}</span></li>
            ))}
          </ul>
        </div>
      )}
      {fc.status === "ok" && fc.notSupported.length === 0 && fc.autoSupported.length > 0 && (
        <p className="dk-fc-done">사실 주장 {fc.autoSupported.length}개 모두 AI 확인을 통과했습니다. 핵심 메시지 한 줄을 확인하고 승인하면 됩니다.</p>
      )}
    </section>
  );
}
