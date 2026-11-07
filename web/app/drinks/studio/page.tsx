// 콘텐츠 스튜디오(/drinks/studio?topic=) — ① 소재 고르기 ② 초안 다듬기 ③ 버전·생성. 운영자 확정 목업(2026-11-07) 기준.
// 계약: docs/deviation-drinks-studio.md · supabase/migrations/0076_drinks_studio.sql. 규칙은 전부 DB 함수이고, 이 화면은 보여 주고 요청만 한다.
// ★ 실패를 빈 목록으로 바꾸지 않는다 — 읽기 실패는 그 칸에 이유를 적는다.
import "./studio.css";

import StudioClient, { type StudioCollectItem, type StudioResultFile } from "@/components/drinks/studio/StudioClient";
import { pickDefaults } from "@/lib/drinks/pickModal";
import { loadPlanProduction } from "@/lib/drinks/productionQueries";
import { cardPlan, type StudioStatus } from "@/lib/drinks/studio";
import { loadTopicCandidates } from "@/lib/drinks/topicsQueries";
import { PLATFORM_LABEL } from "@/lib/drinks/discovery";
import { CATEGORY_LABEL } from "@/lib/drinks/model";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

const ID = /^[0-9a-f-]{36}$/i;

/** "naver_cafe:온미르클럽 · naver_blog:…" → "네이버 카페 온미르클럽 · …"(앞 두 곳만). */
function pathLabel(path: string | null): string | null {
  if (!path) return null;
  const parts = path.split(" · ").map((x) => { const [p, ...rest] = x.split(":"); return `${PLATFORM_LABEL[p] ?? p}${rest.length ? ` ${rest.join(":")}` : ""}`; });
  return parts.slice(0, 2).join(" · ") + (parts.length > 2 ? ` 외 ${parts.length - 2}곳` : "");
}

export default async function StudioPage(props: { searchParams: Promise<{ topic?: string }> }) {
  const sp = await props.searchParams;
  const db = createAdminClient();
  if (!db) return <main className="container"><p className="banner-warn">서버에 SUPABASE_SERVICE_KEY 가 없어 읽을 수 없습니다.</p></main>;
  const topicId = sp.topic && ID.test(sp.topic) ? sp.topic : null;

  const [cands, mine, statusRes] = await Promise.all([
    loadTopicCandidates({ statuses: ["suggested"], page: 1 }),
    db.from("drink_topics").select("id, title, question, status, categories, discovery_platforms, updated_at")
      .in("status", ["researching", "ready", "selected"]).order("updated_at", { ascending: false }).limit(15),
    topicId ? db.rpc("drinks_studio_status", { p: { topic_id: topicId } }) : Promise.resolve(null),
  ]);

  const items: StudioCollectItem[] = [];
  const problems: string[] = [];
  if (mine.error) problems.push(`만들고 있는 소재: ${mine.error.message}`);
  for (const t of (mine.data ?? []) as { id: string; title: string; question: string; status: string; categories: string[] | null; discovery_platforms: string[] | null }[]) {
    items.push({ key: `t:${t.id}`, topicId: t.id, candidateId: null, title: t.title, question: t.question,
      kind: (t.categories ?? []).map((c) => CATEGORY_LABEL[c as keyof typeof CATEGORY_LABEL] ?? c).join(" · ") || "주제 미정",
      origin: (t.discovery_platforms ?? []).map((p) => PLATFORM_LABEL[p] ?? p).join(" · ") || "직접 등록한 소재",
      angle: null, inProgress: true, payload: {} });
  }
  if (cands.state !== "ok") problems.push(`수집함: ${cands.state === "failed" ? cands.error : "서버 키 없음"}`);
  else {
    for (const c of cands.data.candidates) {
      // shortcut: 임시 점수가 없는 후보는 [이걸로](0072)가 '경량 평가 먼저'로 거절한다 — 보여 주지 않는다. 점수 없이 올리는 경로가 생기면 뺀다.
      if (c.provisional_score === null || c.provisional_score === undefined) continue;
      if (c.promoted_topic_id && items.some((x) => x.topicId === c.promoted_topic_id)) continue;
      const d = pickDefaults(c.key_question);
      items.push({ key: `c:${c.id}`, topicId: c.promoted_topic_id, candidateId: c.promoted_topic_id ? null : c.id, title: d.title, question: d.question,
        kind: d.categories.map((x) => CATEGORY_LABEL[x]).join(" · ") || "주제 미정",
        origin: [pathLabel(c.discovery_path), c.interest?.items ? `글 ${c.interest.items}개에서 나온 질문` : null]
          .filter(Boolean).join(" · ") || "수집된 질문",
        angle: c.reader_value ?? c.first_scene ?? null, inProgress: false,
        payload: { candidate_id: c.id, title: d.title, question: d.question, categories: d.categories, ...(c.reader_value ? { reader_value: c.reader_value } : {}) } });
    }
  }

  let status: StudioStatus | null = null;
  let statusProblem: string | null = null;
  if (statusRes) {
    if (statusRes.error) statusProblem = statusRes.error.message;
    else status = statusRes.data as StudioStatus;
  }
  if (status && !items.some((x) => x.topicId === status!.topic.id)) {
    items.unshift({ key: `t:${status.topic.id}`, topicId: status.topic.id, candidateId: null, title: status.topic.title, question: status.topic.question,
      kind: "", origin: "", angle: null, inProgress: true, payload: {} });
  }

  // 결과: 확정된 카드뉴스 초안의 제작 묶음(서명 URL 1시간). 파일·검사 결과가 있는 것만 '완료'다.
  let files: StudioResultFile[] = [];
  let resultProblem: string | null = null;
  const plan = cardPlan(status);
  if (plan && plan.plan_status === "approved") {
    const prod = await loadPlanProduction(plan.plan_revision_id);
    if (prod.state !== "ok") resultProblem = prod.state === "failed" ? prod.error : "제작 결과를 읽지 못했습니다";
    else {
      const latest = prod.data.manifests[0] ?? null;
      files = latest ? latest.files.map((f) => ({ role: f.role, position: f.position, mime: f.mime, url: f.url, urlError: f.urlError,
        width: f.width, height: f.height, jobId: latest.manifest.job_id, reviewStatus: latest.review?.status ?? null,
        qa: (latest.review?.qa_summary as { ok?: boolean } | undefined)?.ok ?? null })) : [];
    }
  }

  return (
    <main className="container container--dw">
      <StudioClient items={items} problems={problems} status={status} statusProblem={statusProblem} files={files} resultProblem={resultProblem}
        selectedTopicId={topicId} />
    </main>
  );
}
