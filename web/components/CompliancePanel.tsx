"use client";

// 컴플라이언스 참고 패널 (명세 5-3). ★ 하드 차단 제거(사용자 요청) — 승인을 잠그지 않고
// 검토 결과만 참고로 보여준다. 3층 표시: 층1 규칙 / 층2 LLM 심사 / 층3 자기검증(근거).
import type { ReportCompliance } from "@/lib/reportTypes";

const VERDICT_LABEL: Record<string, string> = {
  권유: "투자권유",
  수익률광고: "미실현수익률",
  단정: "단정예측",
  출처: "출처표기",
  면책: "면책문구",
};

export default function CompliancePanel({ compliance }: { compliance: ReportCompliance | null }) {
  if (!compliance) {
    return (
      <section className="section compliance">
        <h3>컴플라이언스 게이트</h3>
        <p className="muted">초안을 생성하면 게이트 결과가 표시됩니다.</p>
      </section>
    );
  }

  const { rule_flags = [], llm_verdict, hallucination_flags = [] } = compliance;
  const blockFlags = rule_flags.filter((f) => f.severity === "block");
  const warnFlags = rule_flags.filter((f) => f.severity === "warn");
  const hasFlags = blockFlags.length > 0 || warnFlags.length > 0 || hallucination_flags.length > 0;

  return (
    <section className="section compliance">
      <h3>컴플라이언스 검토 <span className="muted" style={{ fontWeight: 400 }}>· 참고용</span></h3>

      {/* 참고 배너 — 차단이 아니라 안내. 최종 판단은 사람이. */}
      <div className="banner banner-ok">
        {hasFlags
          ? "ℹ️ 참고 — 아래 항목을 검토하세요. 발행 여부는 사람이 판단합니다(자동 차단 없음)."
          : "✅ 특이사항 없음 — 발행 판단은 사람이 확인합니다."}
      </div>

      {/* 층1 — 규칙 위반 */}
      <div className="comp-block">
        <h4>층1 · 규칙 스캔</h4>
        {blockFlags.length === 0 && warnFlags.length === 0 ? (
          <p className="grounded-ok">금지 패턴 없음</p>
        ) : (
          <ul className="comp-flags">
            {blockFlags.map((f, i) => (
              <li key={`b${i}`} className="unsupported">
                🚫 [{f.category}] {f.hit ? `"${f.hit}"` : "누락"}
              </li>
            ))}
            {warnFlags.map((f, i) => (
              <li key={`w${i}`} className="redflag" style={{ margin: "4px 0" }}>
                ⚠️ [{f.category}] {f.hit}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 층2 — LLM 심사관 */}
      {llm_verdict && (
        <div className="comp-block">
          <h4>층2 · LLM 심사관</h4>
          <div className="verdict-grid">
            {(["권유", "수익률광고", "단정", "출처", "면책"] as const).map((k) => {
              const v = llm_verdict[k];
              const bad = v === "yes" || v === "missing";
              return (
                <span key={k} className={bad ? "verdict bad" : "verdict good"}>
                  {VERDICT_LABEL[k]}: {v}
                </span>
              );
            })}
          </div>
          {llm_verdict.근거 && <p className="muted" style={{ marginTop: 6 }}>{llm_verdict.근거}</p>}
        </div>
      )}

      {/* 층3 — 자기검증(환각) */}
      <div className="comp-block">
        <h4>층3 · 자기검증(근거)</h4>
        {hallucination_flags.length === 0 ? (
          <p className="grounded-ok">근거 없는 문장 없음</p>
        ) : (
          <ul className="comp-flags">
            {hallucination_flags.map((h, i) => (
              <li key={i} className="unsupported">
                씬 {h.scene ?? "?"}: {(h.unsupported ?? []).join(" / ") || "근거 미확인"}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
