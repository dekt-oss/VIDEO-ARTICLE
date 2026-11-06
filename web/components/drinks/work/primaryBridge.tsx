"use client";

// 결정 바 ↔ 기존 폼의 다리. 기획 v2 §6-3 "결정 바와 같은 버튼을 두 곳에 두지 않는다 — 기존 폼의 동일 버튼은 제거하거나
// 결정 바가 그 폼의 submit 을 호출한다".
//
// 어떻게: 기존 컴포넌트(ContentApprovalTab·ExplainerProduction·OutputReview·CreatePublication…)가 `hidePrimary` 를 받으면
// 자기 주 버튼의 submit 을 열쇠(동작 이름[:하위 action])로 여기에 등록한다. 결정 바는 결정 함수가 고른 동작의 열쇠와
// 같은 등록이 있으면 **그 폼의 submit** 을 부른다(폼 안의 금액·체크·캡션이 그대로 실린다). 등록이 그 열쇠로 "채택"됐을 때만
// 폼이 자기 버튼을 숨긴다 — 결정 바가 다른 일을 가리키면 폼 버튼은 그대로 남아 아무 버튼도 사라지지 않는다.
//
// ★ Provider 가 없는 옛 화면(/drinks/review, /drinks/production, /drinks/publish)에서는 모두 no-op 이라 바뀌는 것이 없다.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export interface PrimaryBridge {
  /** 결정 바 버튼이 부른다. 폼의 검증·확인창·useDrinksAction 호출이 그 안에 있다. */
  submit: () => void | Promise<unknown>;
  disabled: boolean;
  /** 비활성 이유(버튼 title) */
  title?: string;
}

interface Ctx {
  primaryKey: string | null;
  register: (key: string, bridge: PrimaryBridge | null) => void;
  bridges: Record<string, PrimaryBridge>;
}

const BridgeContext = createContext<Ctx | null>(null);

export function PrimaryBridgeProvider({ primaryKey, children }: { primaryKey: string | null; children: ReactNode }) {
  const [bridges, setBridges] = useState<Record<string, PrimaryBridge>>({});
  const register = useCallback((key: string, bridge: PrimaryBridge | null) => {
    setBridges((prev) => {
      if (bridge === null) {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      }
      const cur = prev[key];
      if (cur && cur.submit === bridge.submit && cur.disabled === bridge.disabled && cur.title === bridge.title) return prev;
      return { ...prev, [key]: bridge };
    });
  }, []);
  const value = useMemo(() => ({ primaryKey, register, bridges }), [primaryKey, register, bridges]);
  return <BridgeContext.Provider value={value}>{children}</BridgeContext.Provider>;
}

/** 결정 바가 쓴다: 지금 주 동작의 열쇠로 등록된 다리(없으면 null). */
export function usePrimaryBridge(key: string | null): PrimaryBridge | null {
  const ctx = useContext(BridgeContext);
  if (!ctx || !key) return null;
  return ctx.bridges[key] ?? null;
}

/**
 * 기존 폼이 쓴다. `enabled`(= hidePrimary) 가 아니면 등록하지 않고 false 를 돌려준다.
 * 돌려주는 값 = "결정 바가 이 버튼을 가져갔다" — true 일 때만 폼이 자기 버튼을 숨긴다.
 */
export function useRegisterPrimary(key: string, bridge: PrimaryBridge, enabled: boolean): boolean {
  const ctx = useContext(BridgeContext);
  const register = ctx?.register;
  const latest = useRef(bridge);
  latest.current = bridge;
  // submit 은 렌더마다 새 함수가 되기 쉬우므로 안정된 포장을 등록하고, 안에서 최신 함수를 부른다.
  const stableSubmit = useCallback(() => latest.current.submit(), []);
  const { disabled, title } = bridge;
  useEffect(() => {
    if (!register || !enabled) return;
    register(key, { submit: stableSubmit, disabled, title });
    return () => register(key, null);
  }, [register, enabled, key, stableSubmit, disabled, title]);
  return Boolean(ctx && enabled && ctx.primaryKey === key);
}
