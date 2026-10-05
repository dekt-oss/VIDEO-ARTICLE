import type { ExplanationV2Info } from "@/lib/types";

const VERDICT_KO: Record<string, string> = {
  PUBLISHABLE: "발행 가능",
  NEEDS_REVIEW: "사람 확인 필요",
  BLOCKED: "차단",
  INCOMPLETE: "렌더 전(판정 미완)",
};

/**
 * V2 설명 엔진이 만든 지시서 안내(2026-10-05). 두 공장 공용.
 * ★ 왜: 이 지시서의 컷 나레이션은 V2 대본이라 왼쪽 칸(초안 표의 Production 대본)과 다르다 — 모르고 보면
 *   대본과 지시서가 어긋난 것처럼 보인다.
 */
export default function ExplanationV2Banner({ info }: { info?: ExplanationV2Info }) {
  if (!info) return null;
  const verdict = info.publish_gate_verdict ? VERDICT_KO[info.publish_gate_verdict] ?? info.publish_gate_verdict : "";
  return (
    <div className="banner-info" style={{ margin: "8px 0" }}>
      🧪 V2 설명 엔진 지시서 — 컷 나레이션은 V2 대본입니다(왼쪽 초안 대본과 다를 수 있어요).
      {verdict && <> 저장 당시 최종 관문: {verdict}.</>}
      {info.run_at && <> 생성 {info.run_at.slice(0, 16).replace("T", " ")} UTC</>}
    </div>
  );
}
