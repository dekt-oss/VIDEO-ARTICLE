// 실패 토스트 문구 통일. 개선 지시서 FEED-01: `실패: 500` 처럼 사용자가 다음에 뭘 해야 할지
// 알 수 없는 문구를 금지하고, 원인 + 다음 행동을 한 문장에 담는다.
//
//   const res = await fetch(...);
//   const body = await res.json().catch(() => null);
//   if (!res.ok) toast.show(apiErrorText(body, res.status, "보관 상태를 저장"), "err");
//   → "보관 상태를 저장하지 못했습니다. 잠시 후 다시 시도하세요. (서버 오류 500)"

export interface ApiErrorBody {
  error?: string;
  code?: string;
  message?: string;
}

/**
 * @param body   서버 JSON 본문(파싱 실패면 null)
 * @param status HTTP 상태코드
 * @param what   "…하지 못했습니다" 앞에 붙일 동작. 예: "보관 상태를 저장", "유튜브 업로드를 요청"
 */
export function apiErrorText(body: ApiErrorBody | null, status: number, what: string): string {
  // 서버가 이미 사람이 읽을 문장을 준 경우(운영자 키 게이트·검증 실패 등)는 그대로 쓴다.
  if (body?.error && /[가-힣]/.test(body.error)) return body.error;

  if (status === 401 || body?.code === "operator_required") {
    return "잠금 해제가 필요합니다 — /unlock 에서 운영자 키를 한 번 입력한 뒤 다시 시도하세요.";
  }
  if (status === 409) {
    return `${what}할 수 없는 상태입니다. 화면을 새로 불러와 현재 상태를 확인하세요.${detail(body)}`;
  }
  if (status === 404) {
    return `대상을 찾지 못했습니다. 이미 삭제됐을 수 있습니다 — 화면을 새로 불러오세요.${detail(body)}`;
  }
  if (status === 503) {
    return `${what}할 수 없습니다. 워커 트리거 설정을 확인하세요.${detail(body)}`;
  }
  if (status >= 500) {
    return `${what}하지 못했습니다. 잠시 후 다시 시도하세요. (서버 오류 ${status})${detail(body)}`;
  }
  return `${what}하지 못했습니다. (오류 ${status})${detail(body)}`;
}

/** 네트워크 자체가 실패한 경우(fetch 예외). */
export function networkErrorText(what: string): string {
  return `${what}하지 못했습니다. 네트워크 연결을 확인하고 다시 시도하세요.`;
}

function detail(body: ApiErrorBody | null): string {
  const raw = body?.error ?? body?.message;
  if (!raw) return "";
  return ` — ${String(raw).slice(0, 120)}`;
}
