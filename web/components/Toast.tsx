"use client";

// 의존성 없는 경량 토스트. layout 에 <ToastProvider> 를 한 번 마운트하고,
// 클라이언트 컴포넌트에서 useToast().show(메시지, 종류) 로 띄운다.
import { createContext, useCallback, useContext, useState } from "react";

type ToastKind = "ok" | "err";
interface ToastItem {
  id: number;
  msg: string;
  kind: ToastKind;
}
interface ToastCtx {
  show: (msg: string, kind?: ToastKind) => void;
}

const Ctx = createContext<ToastCtx | null>(null);

// 모듈 스코프 카운터(Math.random 회피, 렌더 무관 증가).
let seq = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const show = useCallback((msg: string, kind: ToastKind = "ok") => {
    const id = ++seq;
    setItems((cur) => [...cur, { id, msg, kind }]);
    setTimeout(() => setItems((cur) => cur.filter((t) => t.id !== id)), 3200);
  }, []);

  return (
    <Ctx.Provider value={{ show }}>
      {children}
      {/* A11Y-05: 성공은 polite(작업 흐름을 끊지 않게), 오류는 role="alert" 로 즉시 알린다. */}
      <div className="toast-host" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "err" ? "alert" : undefined}>
            {t.msg}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastCtx {
  const ctx = useContext(Ctx);
  // Provider 밖에서 호출돼도 앱이 죽지 않도록 no-op 폴백.
  return ctx ?? { show: () => {} };
}
