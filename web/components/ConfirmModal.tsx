"use client";

// 파괴적·되돌리기 어려운 액션(삭제·재생성·승인) 확인 모달. open 이 true 일 때만 렌더.
// 공개 대시보드라 로그인 게이트 대신 이 확인이 실수 조작의 마지막 방어선이다.
//
// 접근성(A11Y-01): 열릴 때 확인 버튼으로 포커스 이동, 닫힐 때 원래 버튼으로 복귀, Esc 로 닫기,
// Tab 이 모달 밖으로 나가지 않게 순환. 이전에는 키보드만으로 모달을 닫을 수 없었다.
import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** 메시지 아래에 덧붙일 내용(예: 여러 날짜 체크 목록). 없으면 기존과 동일. */
  children?: ReactNode;
}

export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = "확인",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
  children,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // 열기 직전에 포커스를 갖고 있던 요소 — 닫을 때 여기로 돌려준다.
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => {
      restoreRef.current?.focus?.();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (!busy) onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      // 포커스 순환 — 모달이 열린 동안 뒤 화면으로 Tab 이 새지 않게.
      const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!nodes || nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onCancel]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        aria-describedby="confirm-modal-message"
        ref={dialogRef}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="confirm-modal-title">{title}</h3>
        <p id="confirm-modal-message">{message}</p>
        {children}
        <div className="actions">
          <button className="btn" onClick={onCancel} disabled={busy}>
            취소
          </button>
          <button
            className={danger ? "btn reject" : "btn pick"}
            onClick={onConfirm}
            disabled={busy}
            ref={confirmRef}
          >
            {busy ? "처리 중…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
