"use client";

// 아카이브 "보관된 영상" 섹션. 보관 해제(unsave)만 제공 — 삭제는 ⑥ 렌더/휴지통에서.
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { RenderJob } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { apiErrorText } from "@/lib/apiError";

const VERSION_LABEL: Record<string, string> = {
  comic: "만화식",
  image_sequence: "이미지 나열식",
  animation: "애니메이션식",
};

export default function SavedRenderList({ jobs }: { jobs: RenderJob[] }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function unsave(jobId: string) {
    setBusy(jobId);
    const res = await fetch("/api/render-manage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action: "unsave" }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show("보관을 해제했습니다.", "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "보관을 해제"), "err");
    }
  }

  if (jobs.length === 0) {
    return (
      <p className="empty">
        보관된 영상이 없습니다. <a href="/render">⑥ 렌더 결과</a>에서 [★ 저장]하면 여기 모입니다.
      </p>
    );
  }

  return (
    <div className="render-versions" style={{ marginTop: 8 }}>
      {jobs.map((j) => (
        <div className="scene" key={j.id}>
          <div className="meta">
            <b>{j.title ?? "(제목 없음)"}</b> ·{" "}
            {VERSION_LABEL[j.version_type ?? ""] ?? j.version_type ?? "?"}
          </div>
          {j.output_url && (
            <video src={j.output_url} controls style={{ maxWidth: 240, marginTop: 8, borderRadius: 6 }} />
          )}
          <div className="actions" style={{ marginTop: 8 }}>
            {j.paper_id && (
              <a className="btn" href={`/review/${j.paper_id}`}>초안 보기</a>
            )}
            <button className="btn" disabled={busy === j.id} onClick={() => unsave(j.id)}>
              보관 해제
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
