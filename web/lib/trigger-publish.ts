// 유튜브 업로드 워커(GitHub Actions publish.yml)를 대시보드 액션에서 즉시 트리거한다.
// "유튜브 업로드" 시 upload_requests 큐만 쌓고 끝나는 게 아니라, 이 함수로 workflow_dispatch 를
// 호출해 워커가 바로 큐를 소비하게 한다(트리거 없으면 안전망 크론이 폴백 — 2026-08-12 부터
// 하루 3번, KST 09/15/21 이라 대기가 몇 시간이다).
//
// 필요한 서버 환경변수(Vercel, NEXT_PUBLIC_ 금지) — 렌더 트리거와 토큰/레포 공유:
//   GITHUB_DISPATCH_TOKEN  — actions:write 권한 토큰. 없으면 no-op(수동/크론 폴백).
//   RENDER_REPO            — 기본 "dekt-oss/video-article"
//   PUBLISH_WORKFLOW       — 논문 기본 "publish.yml"
//   REPORT_PUBLISH_WORKFLOW— 리포트 기본 "report-publish.yml"
//   RENDER_REF             — 기본 "main"
//
// workflow 인자로 대상 워크플로를 바꾼다(논문=기본, 리포트=report-publish.yml). 토큰/레포/ref 공유.

export interface TriggerResult {
  triggered: boolean;
  reason?: string;
}

export async function triggerPublish(workflow?: string): Promise<TriggerResult> {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    return { triggered: false, reason: "no_token" };
  }
  const repo = process.env.RENDER_REPO || "dekt-oss/video-article";
  const wf = workflow || process.env.PUBLISH_WORKFLOW || "publish.yml";
  const ref = process.env.RENDER_REF || "main";

  try {
    const res = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/${wf}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref }),
      }
    );
    if (res.status === 204) return { triggered: true };
    const text = await res.text().catch(() => "");
    return { triggered: false, reason: `github ${res.status}: ${text.slice(0, 120)}` };
  } catch (e) {
    return { triggered: false, reason: String(e).slice(0, 120) };
  }
}
