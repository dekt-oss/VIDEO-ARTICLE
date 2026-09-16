"use client";

// 진행 중 잡 자동 갱신 (개선 지시서 ASYNC-01). 지금까지 ⑥ 렌더 결과는 "진행 중…
// (새로고침으로 상태 갱신)" 이라 운영자가 직접 F5 를 눌러야 했다.
//
// lib/useGeneration.ts 와 역할이 다르다: 그쪽은 "내가 방금 시작한 생성"을 끝까지 지켜보고,
// 이쪽은 "이미 큐에서 돌고 있는 잡들"을 목록 화면에서 폴링한다. 둘 다 router.refresh() 만 쓴다
// (window.location.reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다).
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export const POLL_FOREGROUND_MS = 10_000;
export const POLL_BACKGROUND_MS = 45_000; // 탭이 숨겨지면 완화(불필요한 서버 왕복 축소)

/**
 * @param activeCount 진행 중(대기·에셋·TTS·조립) 잡 수. 0 이면 폴링하지 않는다.
 * @returns lastCheckedAt 마지막 상태 확인 시각(사용자에게 "언제 확인했는지" 보여주기 위함)
 */
export function useJobPolling(activeCount: number): {
  polling: boolean;
  lastCheckedAt: Date | null;
} {
  const router = useRouter();
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    if (activeCount <= 0) return; // 전부 종료 → 폴링 중단(빈 폴링을 남기지 않는다)
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const interval = () =>
      document.visibilityState === "hidden" ? POLL_BACKGROUND_MS : POLL_FOREGROUND_MS;

    const schedule = () => {
      if (stopped) return;
      timer = setTimeout(() => {
        if (stopped) return;
        router.refresh();
        setLastCheckedAt(new Date());
        schedule();
      }, interval());
    };

    // 탭이 다시 보이면 즉시 한 번 확인하고 주기를 앞당긴다.
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (timer) clearTimeout(timer);
      router.refresh();
      setLastCheckedAt(new Date());
      schedule();
    };

    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [activeCount, router]);

  return { polling: activeCount > 0, lastCheckedAt };
}

/** "8분 42초" 처럼 사람이 읽는 경과 시간. */
export function elapsedLabel(fromIso: string | null | undefined, now = Date.now()): string {
  if (!fromIso) return "";
  const started = new Date(fromIso).getTime();
  if (!Number.isFinite(started)) return "";
  const sec = Math.max(0, Math.floor((now - started) / 1000));
  if (sec < 60) return `${sec}초 경과`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s === 0 ? `${m}분 경과` : `${m}분 ${s}초 경과`;
}
