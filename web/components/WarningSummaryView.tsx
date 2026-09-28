"use client";
// 지시서 경고 요약 — 위 3개만 크게, 나머지는 접는다 (2026-09-28, 운영자 결정 "규칙 통합·정리").
//
// ★ 왜: 지시서 한 장에 경고가 중앙값 56개 떴고(docs/규칙통합_분석_2026-09-28.md), 그 상태로 삼성전자
//   편이 경고 22개를 달고 승인됐다. 많을수록 안 읽힌다. 순서와 분류는 엔진(engine/warning_triage.py)이
//   정한다 — 여기서 다시 판정하지 않고 라벨만 붙인다(라벨은 blockLabels.ts 가 정본).
// ★ 요약이 없는 옛 지시서는 종전대로 한 줄로 전부 보여준다(회귀 없음).
import { warningLabel } from "@/lib/blockLabels";
import type { WarningSummary, WarningSummaryItem } from "@/lib/types";

const CATEGORY_LABEL: Record<WarningSummaryItem["category"], string> = {
  fact: "근거 확인",
  action: "고칠 것",
  source: "소재 한계",
  info: "코드가 처리함",
};

function itemText(g: WarningSummaryItem): string {
  const label = warningLabel(g.code);
  if (g.cuts.length) return `${label} — 컷 ${g.cuts.join(", ")}`;
  return g.count > 1 ? `${label} ×${g.count}` : label;
}

export default function WarningSummaryView({
  summary,
  all,
}: {
  summary?: WarningSummary;
  all?: string[];
}) {
  if (!summary) {
    if (!all?.length) return null;
    return (
      <p className="muted" style={{ marginTop: 4 }}>
        ⚠ {all.map((w) => warningLabel(w)).join(" · ")}
      </p>
    );
  }
  if (!summary.total) return null;
  const rest = summary.groups.slice(summary.top.length);
  const c = summary.counts;
  return (
    <div style={{ marginTop: 6 }}>
      <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
        {summary.top.map((g) => (
          <li key={g.code}>
            <span className="muted" style={{ marginRight: 6 }}>[{CATEGORY_LABEL[g.category]}]</span>
            {itemText(g)}
          </li>
        ))}
      </ul>
      {rest.length > 0 && (
        <details>
          <summary className="muted" style={{ cursor: "pointer" }}>
            나머지 {summary.hidden}개 — 근거 확인 {c.fact} · 고칠 것 {c.action} · 소재 한계 {c.source} · 코드가 처리함 {c.info}
          </summary>
          <ul className="muted" style={{ margin: "4px 0", paddingLeft: 18 }}>
            {rest.map((g) => (
              <li key={g.code}>
                [{CATEGORY_LABEL[g.category]}] {itemText(g)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
