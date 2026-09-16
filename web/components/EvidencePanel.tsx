"use client";

// 근거 게이트 패널 (작업지시서 영상엔진품질 v3 §5·§6).
//
// ★ 왜 만들었나: 게이트 결과(block_reasons·warnings·story_warnings·density_warnings)가
//   계산되고 저장되는데 **화면에 하나도 나오지 않았다.** 안 보이는 게이트는 없는 게이트다.
//   운영자가 승인 버튼을 누를 때 "이 수치가 리포트에 실제로 있는가"를 볼 수 있어야 한다.
//
// 표시 자세: 지금 하드 차단은 기본 off 라(EVIDENCE_HARD_BLOCK_ENABLED) 여기 나오는 것은
// 대부분 **참고**다. 차단하지 않는 것을 빨갛게 칠해 겁주지 않는다 — 대신 무엇을 확인하면
// 되는지 사람 말로 적는다.
import type { ReportEvidence, ReportStoryPlan } from "@/lib/reportTypes";
import { gateLabel, gateSubject, SOURCE_DEPTH_LABELS } from "@/lib/gateLabels";

function ReasonList({ items, icon }: { items: string[]; icon: string }) {
  return (
    <ul className="comp-flags">
      {items.map((r, i) => {
        const subject = gateSubject(r);
        return (
          <li key={i} className="redflag" style={{ margin: "4px 0" }}>
            {icon} {gateLabel(r)}
            {subject && <span className="muted small"> · {subject}</span>}
          </li>
        );
      })}
    </ul>
  );
}

export default function EvidencePanel({
  evidence,
  storyPlan,
}: {
  evidence: ReportEvidence | null;
  storyPlan: ReportStoryPlan | null;
}) {
  // 엣지가 만든 옛 초안에는 이 블록이 없다 — 워커가 정본이 되기 전에 만들어진 것들이다.
  if (!evidence) {
    return (
      <section className="section">
        <h3>근거 게이트</h3>
        <p className="muted">
          이 초안에는 근거 게이트 결과가 없습니다(워커가 만들기 전의 초안).
          [초안 재생성]을 하면 원문 인용 대조 결과가 함께 붙습니다.
        </p>
      </section>
    );
  }

  const blocks = evidence.block_reasons ?? [];
  const warnings = evidence.warnings ?? [];
  const story = evidence.story_warnings ?? [];
  const density = evidence.density_warnings ?? [];
  const clean = !blocks.length && !warnings.length && !story.length && !density.length;
  const depth = SOURCE_DEPTH_LABELS[evidence.source_depth] ?? evidence.source_depth ?? "(미상)";

  return (
    <section className="section">
      <h3>
        근거 게이트{" "}
        <span className="muted" style={{ fontWeight: 400 }}>
          · 원문 {depth}
          {evidence.content_profile ? ` · ${evidence.content_profile}` : ""}
        </span>
      </h3>

      {/* ★ 무엇을 보고 만들어졌는가가 신뢰의 출발점이다 — 요약만 보고 만든 초안은 인용 대조가
          애초에 불가능하다. 그 사실을 게이트 결과보다 먼저 보여준다. */}
      {evidence.source_depth === "summary_only" && (
        <div className="banner banner-ok">
          ℹ️ 이 초안은 <b>리포트 요약만</b> 보고 만들어졌습니다 — 원문 인용 대조를 하지 못했습니다.
          화면에 나갈 수치는 사람이 원문과 직접 맞춰보세요.
        </div>
      )}

      {clean ? (
        <p className="grounded-ok">확인할 항목 없음 — 수치마다 원문 인용이 붙었고 대조를 통과했습니다.</p>
      ) : (
        <>
          {blocks.length > 0 && (
            <div className="comp-block">
              <h4>
                수치 근거{" "}
                <span className="muted" style={{ fontWeight: 400 }}>
                  {evidence.blocked ? "· 승인 잠금" : "· 참고(차단 안 함)"}
                </span>
              </h4>
              <ReasonList items={blocks} icon="🔍" />
            </div>
          )}
          {warnings.length > 0 && (
            <div className="comp-block">
              <h4>유형별 최소 기준</h4>
              <ReasonList items={warnings} icon="⚠️" />
            </div>
          )}
          {story.length > 0 && (
            <div className="comp-block">
              <h4>논증 설계</h4>
              <ReasonList items={story} icon="🧩" />
            </div>
          )}
          {density.length > 0 && (
            <div className="comp-block">
              <h4>화면·읽기 부담</h4>
              <ReasonList items={density} icon="⏱️" />
            </div>
          )}
        </>
      )}

      {/* §6 논증 설계 — 이 영상이 무엇을 증명하려는지 한 문장으로 */}
      {storyPlan?.thesis && (
        <div className="comp-block">
          <h4>이 영상이 증명하려는 것</h4>
          <p>{storyPlan.thesis}</p>
          {storyPlan.audience_question && (
            <p className="muted small">시청자 질문: {storyPlan.audience_question}</p>
          )}
          {(storyPlan.claim_chain ?? []).length > 0 && (
            <ol className="muted small" style={{ marginTop: 6 }}>
              {storyPlan.claim_chain.map((c, i) => (
                <li key={i}>
                  <b>{c.role}</b> — {c.claim}
                  {(c.evidence_refs ?? []).length > 0 && ` (근거: ${c.evidence_refs.join(", ")})`}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
