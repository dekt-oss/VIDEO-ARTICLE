// 주류 수집 문서 (/drinks/collected) — 수집 실행이 저장한 문서. 여기서 소재 후보를 만들거나 기존 소재 조사에 연결한다.
// ★ 수집 문서는 신뢰하지 않는 데이터다. 소재·근거가 되는 것은 사람이 등록·연결·검토한 뒤다(자동 후보·자동 승인 없음).
// ★ "비슷한 소재"는 제목 글자 조각 겹침으로 고른 후보일 뿐 같은 소재라는 판정이 아니다.
import Link from "next/link";

import { CollectedDocActions } from "@/components/drinks/CollectControls";
import LoadProblem from "@/components/drinks/LoadProblem";
import { fmtTime } from "@/components/drinks/RunPill";
import { CATEGORY_LABEL, RIGHTS_LABEL, ROLE_LABEL, depthLabel } from "@/lib/drinks/model";
import { similarTopics } from "@/lib/drinks/collect";
import { COLLECTED_LIMIT, loadCollected } from "@/lib/drinks/collectQueries";

export const dynamic = "force-dynamic";

type SP = { source?: string; depth?: string; linked?: string; cat?: string };

export default async function DrinksCollectedPage(props: { searchParams: Promise<SP> }) {
  const sp = await props.searchParams;
  const v = await loadCollected(COLLECTED_LIMIT, sp.source);
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 수집 문서</h1>
        <span className="muted"><Link href="/drinks/sources">수집원</Link> · <Link href="/drinks/runs">실행 기록</Link></span>
      </div>
      {v.state !== "ok" ? (
        <LoadProblem state={v.state} error={v.state === "failed" ? v.error : undefined} />
      ) : (() => {
        const topicById = new Map(v.data.topics.map((t) => [t.id, t]));
        const docs = v.data.docs.filter((d) => {
          if (sp.depth === "body" && d.snapshot.depth === "metadata_only") return false;
          if (sp.depth === "meta" && d.snapshot.depth !== "metadata_only") return false;
          if (sp.linked === "no" && d.linked.length > 0) return false;
          if (sp.linked === "yes" && d.linked.length === 0) return false;
          if (sp.cat && !(d.source?.categories ?? []).includes(sp.cat as never)) return false;
          return true;
        });
        return (
          <>
            <form className="dk-row" method="get" action="/drinks/collected" style={{ marginBottom: 12 }}>
              <select name="source" defaultValue={sp.source ?? ""} aria-label="수집원">
                <option value="">수집원 전체</option>
                {v.data.sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <select name="cat" defaultValue={sp.cat ?? ""} aria-label="주종">
                <option value="">주종 전체</option>
                {Object.entries(CATEGORY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              <select name="depth" defaultValue={sp.depth ?? ""} aria-label="본문">
                <option value="">본문 상태 전체</option>
                <option value="body">본문 있음</option>
                <option value="meta">제목·요약만</option>
              </select>
              <select name="linked" defaultValue={sp.linked ?? ""} aria-label="연결">
                <option value="">연결 전체</option>
                <option value="no">아직 소재 없음</option>
                <option value="yes">소재에 연결됨</option>
              </select>
              <button className="btn" type="submit">적용</button>
              <Link className="btn" href="/drinks/collected">초기화</Link>
            </form>
            {v.truncated && <p className="banner-warn">전체 {v.data.total}건 중 최근 {v.data.docs.length}건만 보여줍니다.</p>}
            {docs.length === 0 && (
              <p className="muted">{v.data.docs.length === 0 ? "수집 문서가 없습니다(정상 0건 — 활성 수집원이 아직 수집하지 않았습니다)." : "조건에 맞는 문서가 없습니다."}</p>
            )}
            {docs.map((d) => {
              const s = d.snapshot;
              const label = s.title || d.summary || s.canonical_url || "";
              const similar = similarTopics(label, v.data.topics).map((x) => x.topic);
              return (
                <article key={s.id} className="card">
                  <div className="dk-row">
                    <span className={s.depth === "metadata_only" ? "pill dk-warn" : "pill"}>{depthLabel(s.depth, "collected")}</span>
                    {d.source && <span className="pill">{d.source.name}</span>}
                    {(d.source?.categories ?? []).map((c) => <span key={c} className="pill">{CATEGORY_LABEL[c]}</span>)}
                    <span className="pill">사용 조건 {RIGHTS_LABEL[s.rights_status as keyof typeof RIGHTS_LABEL] ?? s.rights_status}</span>
                    {s.supersedes_id && <span className="pill">본문 바뀐 새 버전</span>}
                    {d.sameBody > 0 && <span className="pill dk-warn">같은 본문 다른 URL {d.sameBody} — 원출처 후보</span>}
                  </div>
                  <h2 style={{ marginTop: 8 }}>
                    <a href={s.canonical_url ?? "#"} target="_blank" rel="noreferrer noopener">{s.title || "(제목 없음 — 원문에서 확인)"}</a>
                  </h2>
                  {d.summary && <p className="muted">{d.summary.slice(0, 300)}</p>}
                  <p className="dk-kv">
                    자료 발행일 {s.published_at ?? "모름"} · 수집 {fmtTime(s.created_at ?? null)} · 언어 {s.original_language ?? "—"}
                    {s.collected_run_id && <> · <Link href={`/drinks/runs?run=${s.collected_run_id}`}>수집 실행</Link></>}
                  </p>
                  {d.linked.length > 0 && (
                    <p className="dk-kv">연결된 소재:{" "}
                      {d.linked.map((l) => (
                        <span key={l.topic_id}>
                          <Link href={`/drinks/review/${l.topic_id}?tab=evidence`}>{topicById.get(l.topic_id)?.title ?? "소재"}</Link>
                          ({ROLE_LABEL[l.role as keyof typeof ROLE_LABEL] ?? l.role}){" "}
                        </span>
                      ))}
                    </p>
                  )}
                  {similar.length > 0 && (
                    <p className="dk-kv">비슷한 소재 후보(규칙 기반, 판정 아님):{" "}
                      {similar.map((t) => <span key={t.id}><Link href={`/drinks/review/${t.id}`}>{t.title}</Link>{" "}</span>)}
                    </p>
                  )}
                  <CollectedDocActions snapshotId={s.id} defaultTitle={s.title ?? ""} defaultCats={d.source?.categories ?? []}
                    topics={v.data.topics.map((t) => ({ id: t.id, title: t.title, status: t.status }))}
                    suggested={similar.map((t) => ({ id: t.id, title: t.title, status: t.status }))} />
                </article>
              );
            })}
          </>
        );
      })()}
    </main>
  );
}
