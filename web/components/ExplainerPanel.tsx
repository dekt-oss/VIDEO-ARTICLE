"use client";

// 설명판형 승인 패널 (개선명세 v3.3 §10) — 렌더 전에 "누구의 주장을 어떻게 귀속시키는가"를 본다.
//
// ★ 이 패널은 판정하지 않는다. 판정은 engine/explainer.py 가 지시서 생성 시점에 끝냈고
//   (header.explainer.gate), 여기서는 그 결과를 사람 말로 보여준다. 웹에서 재판정하면
//   두 곳의 규칙이 갈린다.
// ★ 이중관리 지점: GATE_LABEL 은 engine/explainer.py:GATE_LABELS 와 같은 문구를 쓴다.
import type { ExplainerBlock } from "@/lib/types";

const PROFILE_LABEL: Record<string, string> = {
  NUMERIC: "수치형 (목표주가·실적·수주·밸류에이션)",
  MECHANISM: "메커니즘형 (공급망·산업구조·실적 전환 논리)",
  EVENT: "이벤트형 (규제·정책·계약·인수합병)",
};

const SOURCE_MODE_LABEL: Record<string, string> = {
  FULL_REPORT: "리포트 원문 전문 확보",
  PARTIAL_REPORT: "리포트 부분 확보(증권사·원문 링크 있음)",
  NEWS_ONLY: "요약·뉴스만 (원문 링크 없음)",
};

const BOARD_LABEL: Record<string, string> = {
  HOOK_BOARD: "훅",
  CLAIM_BOARD: "핵심 주장",
  NUMBER_BOARD: "대형 숫자",
  CHART_BOARD: "차트",
  EVIDENCE_BOARD: "근거(출처)",
  REPORT_REASON_BOARD: "증권사가 좋게 본 이유",
  MECHANISM_BOARD: "메커니즘",
  VALUATION_BOARD: "밸류에이션",
  COMPARISON_BOARD: "비교",
  WATCHPOINT_BOARD: "확인 포인트",
  CONTEXT_BOARD: "맥락",
};

// 차단 사유 → 사람 말. engine/explainer.py:GATE_LABELS 와 동기화.
const GATE_LABEL: Record<string, string> = {
  contract_not_followed:
    "지시서가 설명판형 계약을 따르지 않았습니다(어떤 컷도 보드를 지정하지 않음). 컷을 고치지 말고 지시서를 재생성하세요.",
  claim_summary_missing: "리포트 핵심 주장 한 문장이 없습니다(누가 왜 무엇을 전망했는지).",
  claim_summary_speaker_missing: "주장을 누구에게 귀속시킬지(증권사)가 비어 있습니다.",
  numeric_profile_without_number_claims: "수치형(NUMERIC) 영상인데 숫자 주장이 없습니다.",
  number_claim_without_fact_ref: "Fact Sheet 근거가 없는 숫자 주장이 있습니다.",
  evidence_board_missing: "근거 보드(EVIDENCE_BOARD)가 한 컷도 없습니다.",
  watchpoint_missing: "확인 포인트(watchpoint)가 없습니다.",
  watchpoint_is_disclaimer: "확인 포인트가 면책 문구로 채워졌습니다(둘은 분리해야 합니다).",
};

// 경고 → 사람 말. 접미 "#컷번호" / ":값" 은 그대로 뒤에 붙여 보여준다.
const WARN_LABEL: Record<string, string> = {
  evidence_board_without_source: "근거 보드에 넣을 출처 정보(증권사·제목)가 없습니다",
  evidence_card_dropped_by_cap: "오버레이 개수 상한 때문에 출처 카드가 빠졌습니다",
  evidence_board_below_recommended: "근거 보드가 권장(2개)보다 적습니다",
  mechanism_beat_missing: "메커니즘 비트가 없습니다 — 숫자 나열형으로 남습니다",
  evidence_beats_below_min: "근거 비트가 2개보다 적습니다",
  beat_count_outside_reference: "비트 수가 참고 범위(6~8) 밖입니다",
  attribution_absent_in_narration: "증권사명이 어떤 나레이션에도 나오지 않습니다",
  insight_nuggets_below_min: "인사이트 조각이 2개보다 적습니다",
  required_board_missing: "이 프로필의 필수 보드가 없습니다",
  number_claim_without_comparison: "비교 기준이 없는 숫자 주장",
  claim_board_without_card: "핵심 주장 보드에 화면 카드가 없습니다(빈 화면이 됩니다)",
  claim_board_text_overflow: "핵심 주장 보드 문구가 너무 깁니다",
  number_board_without_claim_link: "대형 숫자 보드가 숫자 주장과 연결되지 않았습니다",
  big_number_without_basis: "비교 기준·근거가 부족한 숫자를 크게 내세웠습니다",
  valuation_board_without_meaning: "밸류에이션 보드가 숫자만 보여주고 끝납니다",
  board_repeated_consecutively: "같은 판이 3연속입니다 — 화면이 멈춘 것처럼 보입니다",
};

function warnText(raw: string): string {
  const token = raw.replace(/^explainer:/, "");
  const m = /^([a-z_]+)([#:].*)?$/.exec(token);
  const key = m?.[1] ?? token;
  const suffix = m?.[2] ?? "";
  const label = WARN_LABEL[key];
  return label ? `${label}${suffix ? ` (${suffix.slice(1)})` : ""}` : token;
}

export default function ExplainerPanel({ block }: { block: ExplainerBlock }) {
  const gate = block.gate;
  const summary = block.report_claim_summary;
  const boards = Object.entries(block.board_counts ?? {});

  return (
    <div className="section">
      <h3>설명판형 검수 (v3.3)</h3>

      {gate?.blocked ? (
        <div className="banner-warn" style={{ margin: "8px 0" }}>
          ⛔ 승인 차단 — 리포트 해석 영상의 필수 조건이 빠졌습니다. 지시서를 재생성하거나 컷을 고치세요.
          <ul style={{ margin: "6px 0 0 18px" }}>
            {gate.block_reasons.map((r) => (
              <li key={r}>{GATE_LABEL[r] ?? r}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="banner-ok" style={{ margin: "8px 0" }}>
          ✓ 필수 조건 통과 — 주장 귀속 · 근거 보드 · 숫자 근거 · 확인 포인트
        </div>
      )}

      <p className="muted">
        프로필: {PROFILE_LABEL[block.profile] ?? block.profile} · 원문 확보:{" "}
        {SOURCE_MODE_LABEL[block.source_mode] ?? block.source_mode}
      </p>

      {/* ① 누구의 주장을 어떻게 귀속시키는가 (§10-6) */}
      <div style={{ marginTop: 10 }}>
        <label className="prompt-label">리포트 핵심 주장 (화면에 최소 1회 나와야 함)</label>
        <p className="oneliner">
          🏛️ <b>{summary?.speaker || "⚠️ 증권사 미지정"}</b>
          {summary?.statement ? ` — ${summary.statement}` : " — ⚠️ 주장 문장 없음"}
        </p>
        <p className="muted">
          근거: {summary?.fact_refs?.length ? summary.fact_refs.join(", ") : "⚠️ 없음"}
          {summary?.page_refs?.length ? ` · p.${summary.page_refs.join(", ")}` : ""}
        </p>
      </div>

      {/* ② 숫자 주장 목록 — 비교 기준·근거·자격 (§6·§10-3) */}
      <div style={{ marginTop: 10 }}>
        <label className="prompt-label">숫자 주장 ({block.number_claims?.length ?? 0})</label>
        {(block.number_claims ?? []).length === 0 ? (
          <p className="muted">없음</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th>숫자</th>
                  <th>무엇</th>
                  <th>비교 기준</th>
                  <th>왜 중요한가</th>
                  <th>근거</th>
                  <th>대형 사용</th>
                </tr>
              </thead>
              <tbody>
                {block.number_claims.map((c) => (
                  <tr key={c.claim_no}>
                    <td>
                      <b>
                        {c.value}
                        {c.unit}
                      </b>
                    </td>
                    <td>{c.label || "—"}</td>
                    <td>
                      {c.comparison_basis || <span className="unsupported">없음</span>}
                      {c.comparison_value ? ` (${c.comparison_value})` : ""}
                    </td>
                    <td>{c.why_significant || <span className="unsupported">없음</span>}</td>
                    <td>
                      {c.fact_refs?.length ? c.fact_refs.join(", ") : <span className="unsupported">없음</span>}
                      {c.page_refs?.length ? ` · p.${c.page_refs.join(", ")}` : ""}
                    </td>
                    <td>{c.big_number_ok ? "가능" : "불가(자격 부족)"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ③ 보드 구성 + 비트 수(§7) */}
      <div style={{ marginTop: 10 }}>
        <label className="prompt-label">
          보드 구성 · 비트 {Object.values(block.beat_counts ?? {}).reduce((a, b) => a + b, 0)}개
        </label>
        <div className="chips">
          {boards.length === 0 ? (
            <span className="muted">보드 미지정</span>
          ) : (
            boards.map(([b, n]) => (
              <span key={b} className="chip" data-on={b === "EVIDENCE_BOARD"}>
                {BOARD_LABEL[b] ?? b} {n}
              </span>
            ))
          )}
        </div>
      </div>

      {/* ④ watchpoint 와 면책의 분리(§10-7) */}
      <div style={{ marginTop: 10 }}>
        <label className="prompt-label">확인 포인트 (면책과 분리)</label>
        <p className="oneliner">
          🔎 {block.watchpoint?.text || "⚠️ 없음"}
          {block.watchpoint?.metric ? ` · 지표: ${block.watchpoint.metric}` : ""}
        </p>
        <p className="muted">
          면책 문구는 나레이션이 아니라 영상 하단 고정 자막으로 나갑니다(별도 레이어).
        </p>
      </div>

      {/* ⑤ 인사이트 조각 */}
      {(block.insight_nuggets ?? []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <label className="prompt-label">인사이트 조각</label>
          <ul style={{ margin: "4px 0 0 18px" }}>
            {block.insight_nuggets.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ⑥ 경고(승인은 막지 않음) */}
      {(gate?.warnings ?? []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <label className="prompt-label">깊이·시각 경고 ({gate.warnings.length})</label>
          <ul style={{ margin: "4px 0 0 18px" }}>
            {gate.warnings.map((w) => (
              <li key={w} className="muted">
                {warnText(w)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
