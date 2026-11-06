// [내 소재] — 작업 단위(소재 × 형식)를 소재별로 묶어 형식 칩 + 단계 칩(decide().primary.label) + 작업공간 링크를 보인다.
//   카드 소유 밈(topic null)은 "카드 밈" 묶음 하나로 모은다. 카드와 소재를 잇지 않는다(G5 — 연결 RPC 없음).
import Link from "next/link";

import { FORMAT_SHORT, workHref, type Decision, type WorkItem } from "@/lib/drinks/work/types";

export default function MineTab({ items, decisions }: { items: WorkItem[]; decisions: Decision[] }) {
  if (items.length === 0) return <p className="muted">아직 고른 소재가 없습니다(정상 0건). [후보] 탭에서 [이걸로 ▾]를 누르세요.</p>;
  const byUnit = new Map(decisions.map((d) => [d.unitId, d]));
  const groups = new Map<string, WorkItem[]>();
  for (const it of items) {
    const k = it.topic_id ?? "meme_card";
    groups.set(k, [...(groups.get(k) ?? []), it]);
  }
  const order = [...groups.entries()].sort(([, a], [, b]) => (b[0].updated_at ?? "").localeCompare(a[0].updated_at ?? ""));
  return (
    <>
      <p className="muted">단계 칩은 서버 상태로 계산한 &ldquo;지금 할 일&rdquo;입니다. 막힌 작업은 칩에 이유가 붙습니다.</p>
      {order.map(([k, list]) => {
        const head = list[0];
        return (
          <article key={k} className="card">
            <h2 style={{ margin: 0, fontSize: 17 }}>{k === "meme_card" ? "카드 밈(트렌드 카드에서 만든 것)" : head.title}</h2>
            {head.question && k !== "meme_card" && <p className="oneliner">Q. {head.question}</p>}
            {k !== "meme_card" && head.editorial_week && <p className="dk-kv">편성 주차 <b>{head.editorial_week}</b> 주</p>}
            {list.map((it) => {
              const d = byUnit.get(it.unit_id);
              const blocked = d && d.blocks.length > 0;
              return (
                <div key={it.unit_id} className="list-row">
                  <span>
                    <span className="pill on">{FORMAT_SHORT[it.format_intent]}</span>{" "}
                    {it.source === "card" && <b>{it.title} </b>}
                    <span className={blocked ? "pill dk-bad" : d?.primary.busy ? "pill" : "pill pick"}>
                      {d ? d.primary.label : "상태 계산 전"}
                    </span>
                    {blocked && <span className="muted"> · {d.blocks[0].message}</span>}
                    {d && d.warnings.length > 0 && <span className="muted"> · {d.warnings[0]}</span>}
                  </span>
                  <Link className="btn" href={workHref(it, d?.primary.panel)}>작업공간 →</Link>
                </div>
              );
            })}
          </article>
        );
      })}
    </>
  );
}
