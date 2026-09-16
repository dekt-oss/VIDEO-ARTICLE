// ⑤ 영상 지시서 목록: 초안이 있는(=지시서 생성 가능) 논문. 상세에서 버전 선택·생성·승인한다.
import { createClient } from "@/lib/supabase/server";
import { getPicked, getDirectiveStatusMap } from "@/lib/queries";
import type { DirectiveStatus } from "@/lib/types";
import { VERSION_META } from "@/lib/versions";

export const dynamic = "force-dynamic";

// ★ 예전에는 여기 **자기 사본**이 있었고 `comic` 하나뿐이었다(2026-09-08 발견).
//   그래서 3D 그래픽 지시서가 이미 있어도 이 목록에는 상태 뱃지가 안 뜨고
//   "지시서 만들기 →" 로 보였다 — 조용한 드리프트다. 정본을 쓴다.
const STATUS_BADGE: Record<DirectiveStatus, string> = {
  draft: "badge-draft",
  approved: "badge-approved",
  rendering: "badge-approved",
  rendered: "badge-rendered",
  failed: "badge-trash",
};
const STATUS_LABEL: Record<DirectiveStatus, string> = {
  draft: "초안",
  approved: "승인",
  rendering: "렌더중",
  rendered: "렌더됨",
  failed: "실패",
};

export default async function DirectiveListPage() {
  const supabase = createClient();
  const picked = await getPicked(supabase);
  const ready = picked.filter((p) => p.has_draft);
  const statusMaps = await getDirectiveStatusMap(
    supabase,
    ready.map((p) => p.paper_id)
  );

  return (
    <main className="container">
      <div className="header">
        <h1>⑤ 영상 지시서</h1>
        <span className="muted">초안 완료 {ready.length}편</span>
      </div>
      <div className="flow">
        ④ 초안 → <b>⑤ 지시서(버전 선택·승인)</b> → ⑥ 렌더
      </div>

      {ready.length === 0 ? (
        <p className="empty">
          지시서를 만들 초안이 없습니다. <a href="/review">④ 초안</a>에서 대본을 먼저 생성하세요.
        </p>
      ) : (
        <div className="section">
          {ready.map((p) => {
            const sm = statusMaps.get(p.paper_id) ?? {};
            const hasAny = VERSION_META.some((v) => sm[v.key]);
            return (
              <div className="list-row" key={p.paper_id}>
                <a href={`/review/${p.paper_id}?step=5`}>{p.title_ko || p.title}</a>
                <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
                  {hasAny ? (
                    VERSION_META.map((v) => {
                      const st = sm[v.key];
                      return st ? (
                        <span key={v.key} className={`status-pill ${STATUS_BADGE[st]}`}>
                          {v.label} {STATUS_LABEL[st]}
                        </span>
                      ) : null;
                    })
                  ) : (
                    <span className="status-pill">지시서 만들기 →</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
