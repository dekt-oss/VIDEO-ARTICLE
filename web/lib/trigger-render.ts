// 렌더 워커(GitHub Actions render.yml)를 대시보드 액션에서 즉시 트리거한다.
// 승인/재렌더/"지금 렌더" 시 render_jobs 큐만 쌓고 끝나는 게 아니라, 이 함수로
// workflow_dispatch 를 호출해 워커가 바로 큐를 소비하게 한다("내가 요청할 때마다 렌더").
//
// 필요한 서버 환경변수(Vercel, NEXT_PUBLIC_ 금지):
//   GITHUB_DISPATCH_TOKEN  — actions:write 권한 토큰(fine-grained PAT 권장). 없으면 no-op(수동 폴백).
//   RENDER_REPO            — 기본 "dekt-oss/video-article"
//   RENDER_WORKFLOW        — 기본 "render.yml"
//   RENDER_REF             — 기본 "main"(스케줄/디스패치는 기본 브랜치 기준)

export interface TriggerResult {
  triggered: boolean;
  reason?: string;
}

// workflow/mode 파라미터화: 논문은 render.yml(mode=poll), 리포트는 report-video.yml(mode=directive|render).
//
// ★ mode 를 null 로 주면 inputs 를 아예 보내지 않는다. GitHub 은 워크플로가 선언하지 않은
//   input 을 받으면 **422 로 거절**한다 — report-draft.yml 의 inputs 는 모델 ID 4개뿐이고
//   mode 가 없다. 여기를 그냥 재사용하면 초안 트리거가 조용히 실패한다.
export async function triggerWorkflow(
  workflow: string,
  mode: string | null = "poll",
): Promise<TriggerResult> {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    // 토큰 미설정: 큐만 쌓고 워커는 수동. 흐름을 막지 않는다.
    return { triggered: false, reason: "no_token" };
  }
  const repo = process.env.RENDER_REPO || "dekt-oss/video-article";
  const ref = process.env.RENDER_REF || "main";

  try {
    const res = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(mode === null ? { ref } : { ref, inputs: { mode } }),
      }
    );
    // 성공은 204 No Content.
    if (res.status === 204) return { triggered: true };
    const text = await res.text().catch(() => "");
    return { triggered: false, reason: `github ${res.status}: ${text.slice(0, 120)}` };
  } catch (e) {
    return { triggered: false, reason: String(e).slice(0, 120) };
  }
}

export function triggerRender(): Promise<TriggerResult> {
  return triggerWorkflow(process.env.RENDER_WORKFLOW || "render.yml", "poll");
}

// 논문 초안·지시서 워커(draft.yml — draft_requests 뒤 directive_requests 를 처리한다).
// 초안 요청에 version_types 를 실었을 때 부른다(0046): 엣지가 초안을 만들고 지시서는 큐에만
// 넣으므로, 워커가 안 돌면 지시서가 다음 크론까지 빈다.
// ★ inputs 없음 — draft.yml 은 모델 ID 4개만 선언하고 mode 가 없다(넣으면 422).
export function triggerDraft(): Promise<TriggerResult> {
  return triggerWorkflow(process.env.DRAFT_WORKFLOW || "draft.yml", null);
}

// 리포트 초안 워커(report-draft.yml). [초안 생성]·[재검사] 버튼이 큐에 넣은 뒤 바로 부른다.
// ★ inputs 없음 — 이 워크플로는 mode 를 선언하지 않는다(모델 ID 4개만). 넣으면 422.
//   실패해도 흐름을 막지 않는다: 안전망 크론(하루 3번, KST 09/15/21)이 폴백이다.
//   단 2026-08-12 부터 그 폴백은 "늦어도 15분"이 아니라 몇 시간이다 — 호출자가 그렇게 안내해야 한다.
export function triggerReportDraft(): Promise<TriggerResult> {
  return triggerWorkflow(process.env.REPORT_DRAFT_WORKFLOW || "report-draft.yml", null);
}

// 리포트 영상 워커(report-video.yml). mode=directive(지시서 생성) | render(렌더).
export function triggerReportRender(mode: "directive" | "render" = "render"): Promise<TriggerResult> {
  return triggerWorkflow(process.env.REPORT_RENDER_WORKFLOW || "report-video.yml", mode);
}
