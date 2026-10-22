// 실행 상태 배지 — 정상 0건(초록)과 실패(빨강)·부분 성공/중단(주황)이 같은 모양으로 보이지 않게.
import { RUN_STATUS_LABEL, runStuck, runTone } from "@/lib/drinks/collect";
import type { RunRow } from "@/lib/drinks/types";

const TONE_CLASS = { ok: "pill dk-ok", warn: "pill dk-warn", bad: "pill dk-bad", info: "pill" } as const;

export default function RunPill({ r }: { r: Pick<RunRow, "status" | "lease_expires_at"> }) {
  if (runStuck(r)) return <span className="pill dk-bad">응답 끊김(다음 요청 때 중단 처리)</span>;
  return <span className={TONE_CLASS[runTone(r.status)]}>{RUN_STATUS_LABEL[r.status]}</span>;
}

export const fmtTime = (t: string | null) => (t ? new Date(t).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "—");
