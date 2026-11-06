"use client";

// 미저장 입력의 새로고침 복원(기획 v2 §6-3 편집 안전). 서버 저장과 구분한다 — 복원된 값은 "복원됨(서버 저장 아님)" 표시가 붙는다.
//
// 어떻게: 작업공간 본문 안의 textarea·글 input 에 사람이 입력하면 그 값을 sessionStorage(`drinks.work.<topicId>.<lane>`)에
// 자리 열쇠(섹션 키 + 이름/aria-label/placeholder + 순번)로 모아 둔다. 다시 열릴 때 같은 자리가 비어 있으면 되살린다.
// React 가 제어하는 input 이라 원래 setter 로 값을 넣고 input 이벤트를 띄운다(React 18 제어 컴포넌트가 이 경로를 받는다).
// 저장이 성공해 화면이 새로 그려지면(router.refresh) 폼이 비워지므로, 폼이 **제출된 뒤** 남은 값은 사람이 지우거나 [버리기]로 비운다.
// ★ 되살린 값이 옛것일 수 있다 — 그래서 표시를 붙이고, 서버 저장을 대신하지 않는다.
import { useCallback, useEffect, useState, type RefObject } from "react";

type Store = Record<string, string>;

const FIELD_SELECTOR = "textarea, input[type=text], input[type=url], input[type=number], input[type=date], input[type=datetime-local], input:not([type])";

function read(key: string): Store | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const v = JSON.parse(raw) as unknown;
    return v && typeof v === "object" ? (v as Store) : null;
  } catch {
    return null;
  }
}
function write(key: string, store: Store | null) {
  try {
    if (!store || Object.keys(store).length === 0) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(store));
  } catch {
    /* 저장 불가(사생활 모드 등) — 복원 없이 동작한다 */
  }
}

/** 요소의 자리 열쇠: 가장 가까운 섹션 + 식별자 + 같은 식별자 안 순번. 구조가 바뀌면 열쇠가 어긋나 복원이 안 될 뿐 잘못 들어가지 않는다. */
function slotKeys(root: HTMLElement): Map<HTMLInputElement | HTMLTextAreaElement, string> {
  const out = new Map<HTMLInputElement | HTMLTextAreaElement, string>();
  const counts = new Map<string, number>();
  root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(FIELD_SELECTOR).forEach((el) => {
    if (el.type === "password" || el.type === "checkbox" || el.type === "radio" || el.type === "hidden") return;
    const section = el.closest<HTMLElement>("[data-section]")?.dataset.section ?? "root";
    const ident = el.name || el.getAttribute("aria-label") || el.placeholder || el.tagName.toLowerCase();
    const base = `${section}|${ident}`;
    const n = counts.get(base) ?? 0;
    counts.set(base, n + 1);
    out.set(el, `${base}#${n}`);
  });
  return out;
}

function setNativeValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

export function useDraftRestore(rootRef: RefObject<HTMLElement | null>, storageKey: string) {
  const [restored, setRestored] = useState(0);
  const [dirty, setDirty] = useState(false);

  // 되살리기: 처음 그려진 뒤 한 번. 비어 있는 자리만 채운다(서버 값이 있으면 그것이 이긴다).
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const store = read(storageKey);
    if (!store) return;
    let n = 0;
    for (const [el, key] of slotKeys(root)) {
      const v = store[key];
      if (typeof v === "string" && v !== "" && el.value === "") {
        setNativeValue(el, v);
        el.dataset.restored = "1";
        n += 1;
      }
    }
    if (n > 0) setRestored(n);
    // 복원된 수를 알린 뒤에는 dirty 로 본다(아직 서버에 없다).
    if (n > 0) setDirty(true);
  }, [rootRef, storageKey]);

  // 입력 모으기.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onInput = (e: Event) => {
      const t = e.target;
      if (!(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement)) return;
      const keys = slotKeys(root);
      const key = keys.get(t);
      if (!key) return;
      const store = read(storageKey) ?? {};
      if (t.value === "") delete store[key];
      else store[key] = t.value;
      write(storageKey, store);
      setDirty(Object.keys(store).length > 0);
      delete t.dataset.restored;
    };
    root.addEventListener("input", onInput);
    return () => root.removeEventListener("input", onInput);
  }, [rootRef, storageKey]);

  // 미저장 변경 이탈 경고.
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const discard = useCallback(() => {
    write(storageKey, null);
    setRestored(0);
    setDirty(false);
    const root = rootRef.current;
    root?.querySelectorAll<HTMLElement>("[data-restored]").forEach((el) => delete el.dataset.restored);
  }, [rootRef, storageKey]);

  return { restored, dirty, discard };
}
