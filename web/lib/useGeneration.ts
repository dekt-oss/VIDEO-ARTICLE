"use client";

// 초안·지시서 공통 비동기 생성 훅: kickoff(POST) → 상태 폴링(단계·경과 노출)
//   → 완료 시 router.refresh()(전체 새로고침 아님) + 토스트.
// window.location.reload() 를 쓰지 않으므로 클라이언트 컴포넌트는 언마운트되지 않는다 →
// 편집 중 상태를 잃지 않는다(호출부에서 prop 재동기화 패턴으로 새 서버데이터만 반영).
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import { apiErrorText, networkErrorText } from "@/lib/apiError";

// idle: 대기 없음 / starting: kickoff 요청 중 / queued|processing: 워커 단계
export type GenPhase = "idle" | "starting" | "queued" | "processing";

const POLL_INTERVAL_MS = 4000;
// ★ 12분. 리포트 초안은 GitHub Actions 워커가 만든다 — 러너 기동 + 의존성 설치 + LLM 3회.
//   실측(큐 59건)의 중앙값은 46초지만 상위 10%가 203초, 지시서는 276초다. 6분은 그 꼬리를
//   자꾸 잘라 "생성이 지연되고 있습니다"를 띄웠고, 실제로는 잘 만들어지고 있었다.
const POLL_TIMEOUT_MS = 720_000;

const PHASE_LABEL: Record<GenPhase, string> = {
  idle: "",
  starting: "요청 중…",
  queued: "대기 중…",
  processing: "생성 중…",
};

export function genPhaseLabel(p: GenPhase): string {
  return PHASE_LABEL[p] ?? "";
}

interface Options {
  kickoffUrl: string;
  kickoffBody: unknown;
  statusUrl: string; // GET, 반환 { status: queued|processing|done|error, error? }
  okMsg: string;
  /**
   * 화면을 열 때 이미 큐에 걸려 있던 요청의 상태(서버가 내려준다). 있으면 kickoff 없이
   * 폴링만 이어붙인다.
   *
   * ★ 왜 필요한가: 예전에는 진행 상태가 이 훅의 메모리에만 있었다. 생성을 눌러 두고
   *   새로고침하거나 다른 메뉴를 다녀오면 화면이 "아직 초안이 없습니다"로 돌아가,
   *   운영자가 "눌렀는데 아무 일도 안 일어났다"고 판단해 또 눌렀다.
   */
  resumeFrom?: "queued" | "processing" | null;
}

export function useGeneration({ kickoffUrl, kickoffBody, statusUrl, okMsg, resumeFrom }: Options) {
  const router = useRouter();
  const toast = useToast();
  const [phase, setPhase] = useState<GenPhase>("idle");
  const [elapsedSec, setElapsedSec] = useState(0);
  // 언마운트/완료 시 타이머 정리용.
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeRef = useRef(false);

  const stopTick = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  useEffect(() => () => stopTick(), [stopTick]); // 언마운트 정리

  /** kickoff 이후(또는 이미 걸려 있는 요청에 붙어서) 끝날 때까지 상태를 따라간다. */
  const pollUntilDone = useCallback(async () => {
    setPhase("queued");
    const started = Date.now();
    stopTick();
    tickRef.current = setInterval(
      () => setElapsedSec(Math.floor((Date.now() - started) / 1000)),
      1000
    );

    while (Date.now() - started < POLL_TIMEOUT_MS) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      let sres: Response;
      try {
        sres = await fetch(statusUrl);
      } catch {
        continue; // 일시 오류는 다음 폴로
      }
      if (!sres.ok) continue;
      const s = await sres.json().catch(() => null);
      if (!s) continue;
      if (s.status === "processing") setPhase("processing");
      else if (s.status === "queued") setPhase("queued");
      if (s.status === "done") {
        stopTick();
        activeRef.current = false;
        setPhase("idle");
        toast.show(okMsg, "ok");
        router.refresh(); // 서버 데이터만 갱신(언마운트 없음)
        return;
      }
      if (s.status === "error") {
        stopTick();
        activeRef.current = false;
        setPhase("idle");
        toast.show(`생성 오류: ${s.error ?? "알 수 없는 오류"}`, "err");
        router.refresh(); // 오류 상태도 화면에 반영한다
        return;
      }
    }
    // 타임아웃 — 큐에는 남아 있다. 다시 열면 이 훅이 resumeFrom 으로 이어붙는다.
    stopTick();
    activeRef.current = false;
    setPhase("idle");
    toast.show(
      "아직 만들어지는 중입니다. 이 화면을 다시 열면 진행 상태가 이어집니다.",
      "err"
    );
  }, [statusUrl, okMsg, router, toast, stopTick]);

  // 화면을 열었을 때 이미 큐에 걸려 있으면 자동으로 이어 본다(누른 적 없어도 표시된다).
  useEffect(() => {
    if (!resumeFrom) return;
    if (activeRef.current) return;
    activeRef.current = true;
    void pollUntilDone();
  }, [resumeFrom, pollUntilDone]);

  // extraBody: 이번 실행에만 kickoffBody 에 병합할 추가 필드(예: { instruction }).
  const run = useCallback(async (extraBody?: Record<string, unknown>) => {
    if (activeRef.current) return; // 중복 실행 방지
    activeRef.current = true;
    setPhase("starting");
    setElapsedSec(0);

    const bodyToSend = extraBody
      ? { ...(kickoffBody as Record<string, unknown>), ...extraBody }
      : kickoffBody;

    let res: Response;
    try {
      res = await fetch(kickoffUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bodyToSend),
      });
    } catch {
      activeRef.current = false;
      setPhase("idle");
      toast.show(networkErrorText("생성을 요청"), "err");
      return;
    }
    if (!res.ok) {
      activeRef.current = false;
      setPhase("idle");
      const e = await res.json().catch(() => null);
      toast.show(apiErrorText(e, res.status, "생성을 요청"), "err");
      return;
    }

    await pollUntilDone();
  }, [kickoffUrl, kickoffBody, toast, pollUntilDone]);

  return { phase, elapsedSec, run, busy: phase !== "idle" };
}
