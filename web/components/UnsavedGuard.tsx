"use client";

// 미저장 편집 이탈 방지 (개선 지시서 SAFE-01). 편집 화면에 <UnsavedGuard dirty={...} /> 하나만 둔다.
//
// 두 경로를 각각 다르게 막는다:
//   1) 브라우저 이탈(새로고침·탭 닫기·주소창 이동) → beforeunload. 브라우저 기본 경고를 쓴다
//      (웹 표준상 커스텀 문구·커스텀 UI 가 불가능하다).
//   2) 앱 내부 이동(next/link 클릭 — 상단바 탭·공장 전환·목록으로) → 클릭을 캡처 단계에서
//      가로채 ConfirmModal 로 확인받고, 확인 시 router.push 로 계속 이동한다.
//      window.confirm 은 쓰지 않는다(FEED-01 — 앱과 스타일·포커스·모바일 동작이 어긋난다).
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ConfirmModal from "@/components/ConfirmModal";

const DEFAULT_MESSAGE =
  "저장하지 않은 편집이 있습니다. 이동하면 편집 내용이 사라집니다. 계속할까요?";

export default function UnsavedGuard({
  dirty,
  message = DEFAULT_MESSAGE,
}: {
  dirty: boolean;
  message?: string;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  // 확인 후 재이동에서 다시 가드에 걸리지 않게 하는 1회용 통과 플래그.
  const bypass = useRef(false);

  // 1) 브라우저 이탈
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // 크롬은 문구를 무시하고 기본 경고를 띄운다
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  // 2) 앱 내부 링크 이동
  useEffect(() => {
    if (!dirty) return;
    const onClick = (e: MouseEvent) => {
      if (bypass.current) return;
      // 새 탭/새 창 의도는 막지 않는다(현재 화면이 남아 있으므로 유실이 없다).
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const anchor = (e.target as HTMLElement | null)?.closest?.("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("mailto:")) return;
      if (anchor.target && anchor.target !== "_self") return;
      if (anchor.hasAttribute("download")) return;
      // 외부 도메인은 beforeunload 가 처리한다(라우터로 이동할 수 없다).
      const url = new URL(href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname + url.search === window.location.pathname + window.location.search) return;

      e.preventDefault();
      e.stopPropagation();
      setPending(url.pathname + url.search);
    };
    // 캡처 단계 — next/link 의 자체 핸들러보다 먼저 잡아야 라우팅을 취소할 수 있다.
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [dirty]);

  const go = useCallback(() => {
    const href = pending;
    setPending(null);
    if (!href) return;
    bypass.current = true;
    router.push(href);
    // 이동이 끝나면(언마운트) 플래그는 함께 사라진다. 같은 화면에 남는 경우를 위해 되돌린다.
    setTimeout(() => {
      bypass.current = false;
    }, 1000);
  }, [pending, router]);

  return (
    <ConfirmModal
      open={!!pending}
      title="저장하지 않은 편집이 있습니다"
      message={message}
      confirmLabel="저장하지 않고 이동"
      danger
      onCancel={() => setPending(null)}
      onConfirm={go}
    />
  );
}
