// 통합 작업 화면의 **결정 바** — 상태 → 주 버튼 하나 (설계안_초안지시서_통합발주_v2 §2-2).
//
// 왜 순수 함수인가: 화면이 "지금 눌러야 하는 버튼"을 하나만 보여주기로 했다. 그 판정이 JSX 안에
// 흩어져 있으면 상태 조합(초안 있음×지시서 없음×생성 중×낡음×승인됨…)이 늘 때마다 버튼이 둘 뜨거나
// 하나도 안 뜬다. 여기서 표로 정하고 테스트로 못박는다(`decision.test.ts`).
//
// 두 공장이 같은 함수를 쓴다 — 리포트만 컴플라이언스·검증지문이 더 있지만 주 버튼 판정은 같다.

export type DirectiveStatus = "draft" | "approved" | "rendering" | "rendered" | "failed";

export interface VersionState {
  key: string;
  /** 최신 지시서 상태. 없으면 null. */
  status: DirectiveStatus | null;
  /** 최신 지시서 생성 시각(ISO). */
  createdAt?: string | null;
  /** 큐에 걸린 생성 요청. */
  pending?: "queued" | "processing" | null;
  /** 엔진이 박아 둔 승인 차단 사유(참고용 — 서버가 승인 시점에 다시 센다). */
  blocked?: string[];
}

export interface DecisionInput {
  hasDraft: boolean;
  /** 초안 생성 요청이 큐에 걸려 있는가. */
  draftPending: "queued" | "processing" | null;
  /** 초안 마지막 수정 시각(0046 트리거). */
  draftUpdatedAt?: string | null;
  /** 대본 승인(published 기록) 여부. */
  scriptApproved: boolean;
  /** 운영자가 체크한 버전들. */
  chosen: string[];
  versions: VersionState[];
  /** 저장하지 않은 편집이 있는가(대본·씬·컷 합산). */
  dirty: boolean;
}

export type PrimaryAction =
  | "generate"        // 초안 + 지시서 생성
  | "choose_version"  // 초안은 있는데 고른 버전이 없다 → 고르라고 한다(버튼 비활성)
  | "wait_draft"      // 초안 만드는 중
  | "wait_directive"  // 지시서 만드는 중
  | "make_directive"  // 초안은 있는데 체크한 버전의 지시서가 없다 → 지시서 생성
  | "regen_stale"     // 대본이 지시서보다 새롭다 → 지시서 재생성
  | "approve_render"  // 승인 → 렌더
  | "blocked"         // 승인 차단 — 사유 보기(강제 승인은 그 안에서)
  | "view_render";    // 승인·렌더 이후 — 렌더 결과

export interface Decision {
  action: PrimaryAction;
  /** 버튼에 쓸 말. */
  label: string;
  /** 이 결정이 가리키는 버전들(생성/승인 대상). */
  targets: string[];
  /** 대본이 지시서보다 새로운 버전들(경고 배너용). action 이 regen_stale 이 아니어도 채운다. */
  stale: string[];
  /** 왜 이 버튼인지 한 줄(툴팁·빈 상태 문구). */
  reason: string;
}

const HANDED_OFF: DirectiveStatus[] = ["approved", "rendering", "rendered"];

/** 대본이 그 지시서보다 뒤에 고쳐졌는가 — 둘 다 시각이 있어야 판정한다(없으면 모른다 = 낡지 않음). */
export function isStale(draftUpdatedAt: string | null | undefined, directiveCreatedAt: string | null | undefined): boolean {
  if (!draftUpdatedAt || !directiveCreatedAt) return false;
  const d = Date.parse(draftUpdatedAt);
  const c = Date.parse(directiveCreatedAt);
  if (Number.isNaN(d) || Number.isNaN(c)) return false;
  // 같은 초 안의 저장(초안 생성 직후 지시서가 이어 만들어진 경우)은 낡은 것이 아니다 — 2초 여유.
  return d - c > 2000;
}

export function decide(input: DecisionInput): Decision {
  const { hasDraft, draftPending, draftUpdatedAt, scriptApproved, chosen, versions, dirty } = input;
  const byKey = new Map(versions.map((v) => [v.key, v]));
  const picked = chosen.map((k) => byKey.get(k) ?? { key: k, status: null });
  const pickedLabel = chosen.join(", ") || "(버전 없음)";

  if (draftPending) {
    return { action: "wait_draft", label: "초안 만드는 중…", targets: chosen, stale: [],
             reason: "초안이 끝나면 고른 버전의 지시서가 이어서 만들어집니다" };
  }
  if (!hasDraft) {
    return { action: "generate", label: `초안 + 지시서 생성 (${chosen.length}건)`, targets: chosen, stale: [],
             reason: chosen.length ? `${pickedLabel} 지시서까지 한 번에 만듭니다` : "만들 버전을 하나 이상 고르세요" };
  }

  // ★ 초안은 있는데 고른 버전이 없다 — "할 일 없음"이 아니라 "골라라"다. 실측: 체크를 다 풀면
  //   [렌더 결과 보기]가 떴고 버전 선택칸까지 숨어 다시 고를 길이 없었다.
  if (chosen.length === 0) {
    return { action: "choose_version", label: "만들·승인할 버전을 고르세요", targets: [], stale: [],
             reason: "위 체크에서 버전을 하나 이상 고르면 다음 할 일이 정해집니다" };
  }

  const generating = picked.filter((v) => v.pending);
  if (generating.length) {
    return { action: "wait_directive", label: `지시서 만드는 중 · ${generating.map((v) => v.key).join(", ")}`,
             targets: generating.map((v) => v.key), stale: [],
             reason: "보통 1~3분. 이 화면을 닫았다 열어도 이어집니다" };
  }

  // 승인·렌더로 넘어간 버전만 골랐으면 더 할 일이 없다 → 렌더 결과.
  const handedOff = picked.filter((v) => v.status && HANDED_OFF.includes(v.status));
  const missing = picked.filter((v) => !v.status);
  const stale = picked.filter((v) => v.status === "draft" && isStale(draftUpdatedAt, v.createdAt)).map((v) => v.key);

  if (missing.length) {
    return { action: "make_directive", label: `지시서 생성 (${missing.map((v) => v.key).join(", ")})`,
             targets: missing.map((v) => v.key), stale,
             reason: "초안은 있는데 이 버전의 지시서가 아직 없습니다" };
  }
  if (picked.length && handedOff.length === picked.length) {
    return { action: "view_render", label: "렌더 결과 보기", targets: chosen, stale: [],
             reason: "고른 버전이 전부 승인·렌더로 넘어갔습니다(편집 잠금)" };
  }
  if (stale.length) {
    return { action: "regen_stale", label: `지시서 재생성 (${stale.join(", ")})`, targets: stale, stale,
             reason: "대본을 지시서 이후에 고쳤습니다 — 옛 대본으로 렌더하지 않게 다시 만듭니다" };
  }
  const approvable = picked.filter((v) => v.status === "draft");
  if (!approvable.length) {
    return { action: "view_render", label: "렌더 결과 보기", targets: chosen, stale: [],
             reason: "승인할 지시서가 없습니다" };
  }
  const blocked = approvable.filter((v) => v.blocked?.length);
  if (blocked.length) {
    return { action: "blocked", label: `⛔ 승인 차단 — 사유 보기 (${blocked.map((v) => v.key).join(", ")})`,
             targets: approvable.map((v) => v.key), stale: [],
             reason: "원칙은 재생성입니다. 그래도 렌더하려면 사유를 보고 강제 승인합니다(흔적이 남습니다)" };
  }
  return { action: "approve_render",
           label: `${scriptApproved ? "" : "대본 확정 + "}승인 → 렌더 (${approvable.map((v) => v.key).join(", ")})`,
           targets: approvable.map((v) => v.key), stale: [],
           reason: dirty ? "저장하지 않은 편집을 먼저 저장하고 승인합니다" : "확인창에서 비용·언어를 보고 렌더를 시작합니다" };
}
