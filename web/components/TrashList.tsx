"use client";

// 휴지통: 소프트 삭제된 렌더 잡. 복원(restore) 또는 영구삭제(purge, Storage mp4까지 제거).
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { RenderJob } from "@/lib/types";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import { apiErrorText } from "@/lib/apiError";

const VERSION_LABEL: Record<string, string> = {
  comic: "만화식",
  image_sequence: "이미지 나열식",
  animation: "애니메이션식",
};

export default function TrashList({ jobs }: { jobs: RenderJob[] }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<RenderJob | null>(null);

  async function manage(jobId: string, action: "restore" | "purge") {
    setBusy(jobId);
    const res = await fetch("/api/render-manage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show(action === "restore" ? "복원했습니다." : "영구 삭제했습니다.", "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "휴지통 작업을 처리"), "err");
    }
  }

  if (jobs.length === 0) {
    return (
      <p className="empty">
        휴지통이 비어 있습니다. <a href="/render">⑥ 렌더 결과</a>에서 삭제한 렌더가 여기 모입니다.
      </p>
    );
  }

  return (
    <>
      <p className="muted" style={{ marginBottom: 12 }}>
        삭제된 렌더 {jobs.length}건. 복원하거나 영구 삭제할 수 있습니다. 영구 삭제는 되돌릴 수 없습니다.
      </p>
      {jobs.map((j) => (
        <div className="scene" key={j.id}>
          <div className="meta">
            <b>{j.title ?? "(제목 없음)"}</b> ·{" "}
            {VERSION_LABEL[j.version_type ?? ""] ?? j.version_type ?? "?"}
            {j.deleted_at ? ` · 삭제 ${new Date(j.deleted_at).toLocaleDateString("ko-KR")}` : ""}
          </div>
          {j.output_url && (
            <video src={j.output_url} controls style={{ maxWidth: 240, marginTop: 8, borderRadius: 6 }} />
          )}
          <div className="actions" style={{ marginTop: 8 }}>
            <button className="btn pick" disabled={busy === j.id} onClick={() => manage(j.id, "restore")}>
              복원
            </button>
            <button className="btn reject" disabled={busy === j.id} onClick={() => setPurgeTarget(j)}>
              영구 삭제
            </button>
          </div>
        </div>
      ))}

      <ConfirmModal
        open={!!purgeTarget}
        title="영구 삭제"
        message="이 렌더 잡과 저장된 mp4 파일을 완전히 삭제합니다. 되돌릴 수 없습니다."
        confirmLabel="영구 삭제"
        danger
        busy={!!purgeTarget && busy === purgeTarget.id}
        onCancel={() => setPurgeTarget(null)}
        onConfirm={() => {
          if (purgeTarget) {
            const id = purgeTarget.id;
            setPurgeTarget(null);
            manage(id, "purge");
          }
        }}
      />
    </>
  );
}
