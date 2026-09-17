// 통합 작업 화면을 열 때 **어느 버전을 체크해 둘 것인가** (설계안_초안지시서_통합발주_v2 §2-2 보조).
//
// ★ 왜 순수 함수로 빼는가: 이 판단이 컴포넌트 안에 있던 동안 실제 사고를 냈다(2026-09-17).
//   운영자 보고 — "초안 생성하면 작업지시서도 같이 생성되는데 그다음 렌더 지시하는 버튼이 없다".
//   원인은 결정 바가 **실제로 있는 지시서를 안 보고** 기본값(`comic`)만 봤기 때문이다.
//   초안 발주가 `photo` 로 나가면 지시서도 `photo` 로 만들어지는데, 화면은 `comic` 을 체크한 채
//   "지시서 생성(만화식)"을 띄웠다. 오른쪽 칸은 photo 지시서를 제대로 보여주고 있었기 때문에
//   "지시서는 있는데 렌더 버튼만 없다"로 보였다.
//   실측(논문 e826a5fa…): 고치기 전 "지시서 생성 (만화식)" → 고친 뒤
//   "대본 확정 + 승인 → 렌더 (3D 그래픽)".

/**
 * 화면을 열 때 체크해 둘 버전 목록.
 *
 * 우선순위는 셋이고 순서가 곧 규칙이다:
 *   ① 지시서가 **실제로 있는** 버전 — 지금 눌러야 할 일이 거기 있다.
 *   ② 마지막 선택(localStorage) — 아직 아무것도 안 만든 화면에서 운영자의 습관을 이어준다.
 *   ③ 기본값 한 건 — 손대지 않고 눌렀을 때 3버전이 통째로 발주되던 사고의 처방(CLAUDE.md).
 *
 * @param withDirective 지시서가 존재하는 버전 키들
 * @param stored        localStorage 에 저장된 마지막 선택(없으면 null)
 * @param known         이 공장이 제공하는 버전 키들 — 모르는 값은 버린다
 * @param defaultKey    최후 기본값
 */
export function pickInitialVersions(
  withDirective: readonly string[],
  stored: readonly string[] | null | undefined,
  known: readonly string[],
  defaultKey: string,
): string[] {
  const keep = (list: readonly string[]) => {
    const seen = new Set<string>();
    return list.filter((v) => known.includes(v) && !seen.has(v) && seen.add(v) !== undefined);
  };

  const existing = keep(withDirective);
  if (existing.length) return existing;

  const remembered = keep(stored ?? []);
  if (remembered.length) return remembered;

  return [defaultKey];
}
