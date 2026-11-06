"use client";

// [쓰자 ▾] — 트렌드 카드 결정. 두 갈래: [정밀화 포함 $0.02](ig_card_use_refine, Apify 1회) / [정밀화 없이](ig_card_decide use, 0원).
//   카드를 소재에 잇지 않는다(G5). 상한·월 한도는 DB 가 센다 — 여기 문구는 안내일 뿐이다.
import { useState } from "react";

import { APIFY_RUN_CAP_USD, refineCostLine, refinePlan, type ApifyMonth, usd } from "@/lib/drinks/apify";
import { DECISION_LABEL, type IgCardRow } from "@/lib/drinks/igTrends";
import { useDrinksAction } from "../useDrinksAction";

export default function MemeUseMenu({ card, month, apifyReady }: {
  card: Pick<IgCardRow, "id" | "decision" | "precision" | "examples_count">; month: ApifyMonth | null; apifyReady: boolean;
}) {
  const { run, busy } = useDrinksAction();
  const [open, setOpen] = useState(false);
  const plan = refinePlan(apifyReady ? month : null, card);
  const already = card.decision === "use";
  const withRefine = async () => {
    const r = await run("ig_card_use_refine", { card_id: card.id }, "[쓰자] 기록 + 정밀화 요청을 넣었습니다", "결정 기록");
    const refine = (r.result as { refine?: { queued?: boolean; message?: string } } | undefined)?.refine;
    if (r.ok && refine && refine.queued !== true && refine.message) window.alert(`정밀화는 하지 않았습니다: ${refine.message}`);
    if (r.ok) setOpen(false);
  };
  const without = async () => {
    const r = await run("ig_card_decide", { card_id: card.id, decision: "use" }, "[쓰자] 로 기록했습니다(정밀화 없음 · 0원)", "결정 기록");
    if (r.ok) setOpen(false);
  };
  return (
    <div>
      <div className="actions">
        <button className="btn pick" type="button" disabled={busy || already} aria-expanded={open} onClick={() => setOpen(!open)}>
          {already ? `이미 ${DECISION_LABEL.use}` : "쓰자 ▾"}
        </button>
      </div>
      {open && !already && (
        <div className="dk-sub">
          <div className="actions">
            <button className="btn pick" type="button" disabled={busy || !plan.runs} onClick={withRefine}>정밀화 포함 {usd(APIFY_RUN_CAP_USD.meme_refine)}</button>
            <button className="btn" type="button" disabled={busy} onClick={without}>정밀화 없이</button>
          </div>
          <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
            {plan.runs ? plan.reason : `정밀화 불가 — ${plan.reason}`}{apifyReady && ` (${refineCostLine(month)})`}
            {" "}· 결정만 기록합니다. 제작안은 밈 보드의 [밈 제작] 칸이나 작업공간에서 씁니다.
          </p>
        </div>
      )}
    </div>
  );
}
