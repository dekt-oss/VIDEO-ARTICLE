// 밀린 일 정리 규칙(2026-09-30 운영자 결정 3-1) — 낙점 쪽.
//
// "검수 필요 168"은 낙점만 하고 초안을 안 만든 편까지 셌다. 늘 큰 숫자라 무엇이 급한지 알려 주지 못했다.
// 낙점 뒤 HOLD_AFTER_DAYS 가 지나도 초안이 없으면 **보류**로 본다 — 할 일 숫자에서 빠지고, 작업함의
// [보류] 칩에 모인다. 데이터는 건드리지 않는다(규칙이 계산할 뿐이다). 초안을 만들면 자동으로 되살아난다.
// 순수 모듈 — import 없음(node --test 로 직접 돈다). 테스트: lib/work/backlog.test.ts
export const HOLD_AFTER_DAYS = 14;

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * 검수 단계에서 멈춘 편(2026-09-30 운영자: "지시서도 같은 규칙으로"). 초안은 있는데 **마지막 산출물**
 * (가장 최근 지시서, 없으면 초안)이 만들어진 뒤 HOLD_AFTER_DAYS 동안 승인되지 않았으면 보류다.
 * 지시서를 새로 만들면(재생성) 시각이 바뀌어 자동으로 되살아난다. 승인·렌더로 넘어간 편은 부르지 않는다.
 */
export function isStalled(lastMadeAt: string | null | undefined, now: Date = new Date()): boolean {
  if (!lastMadeAt) return false;
  const t = new Date(lastMadeAt).getTime();
  return Number.isFinite(t) && now.getTime() - t > HOLD_AFTER_DAYS * DAY_MS;
}

export function isOnHold(
  p: { hasDraft: boolean; decidedAt: string | null | undefined },
  now: Date = new Date(),
): boolean {
  if (p.hasDraft || !p.decidedAt) return false;
  const t = new Date(p.decidedAt).getTime();
  return Number.isFinite(t) && now.getTime() - t > HOLD_AFTER_DAYS * DAY_MS;
}
