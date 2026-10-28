"use client";

// 주류 화면 공용 쓰기 훅. POST /api/drinks → 성공이면 토스트 + 화면 새로고침(router.refresh),
// 실패면 서버가 준 한국어 문장을 그대로 띄운다. 서버가 막은 이유(detail)는 호출부가 받아 화면에 펼친다.
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { useToast } from "@/components/Toast";
import { apiErrorText, networkErrorText } from "@/lib/apiError";

export interface DrinksResult {
  ok: boolean;
  status: number;
  result?: Record<string, unknown>;
  error?: string;
  code?: string;
  detail?: unknown;
  /** request_run 뒤 수집 워커를 깨웠는지(토큰 없으면 triggered=false) */
  dispatch?: { triggered: boolean; reason?: string };
}

export function useDrinksAction() {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (action: string, payload: Record<string, unknown>, okMsg: string, what = "저장"): Promise<DrinksResult> => {
      setBusy(true);
      try {
        const res = await fetch("/api/drinks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, payload }),
        });
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          toast.show(apiErrorText(body, res.status, what), "err");
          return { ok: false, status: res.status, error: body?.error, code: body?.code, detail: body?.detail };
        }
        toast.show(okMsg, "ok");
        router.refresh();
        return { ok: true, status: res.status, result: body?.result, dispatch: body?.dispatch };
      } catch {
        toast.show(networkErrorText(what), "err");
        return { ok: false, status: 0, error: networkErrorText(what), code: "network" };
      } finally {
        setBusy(false);
      }
    },
    [router, toast]
  );

  return { run, busy };
}
