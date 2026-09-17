// 서버 props 로 입력칸을 **다시 채울지** 판단하는 규칙 (2026-09-17).
//
// ★ 왜 생겼나 — 운영자 보고: "제목 바꿔서 저장했는데 내가 바꾼 내용이 저장 안 되고 원래 제목
//   그대로 되면서 '제목 저장 (고친 내용 없음)' 이라고 뜹니다."
//   실제로는 **저장은 됐다**(DB 확인). 화면이 저장 직후 스스로 옛 값으로 되돌렸다.
//
//   PublishTitles 의 되살리기 effect 가 이랬다:
//     useEffect(..., [initialKo, initialEn, dirty])
//   저장에 성공하면 dirty 가 true→false 로 바뀐다 → **그 변화가 effect 를 다시 깨운다** →
//   그때 props(initialKo)는 아직 서버를 다시 읽기 전이라 **옛 제목**이다 → 옛 제목으로 덮어쓴다.
//   사용자 눈에는 "저장했는데 안 됐다"로 보인다. 가장 나쁜 종류의 거짓말이다.
//
// ★ 고치는 규칙은 하나다: **우리가 방금 저장한 값**을 알고 있고, 서버가 그 값을 들고 올 때까지는
//   들어오는 props 를 믿지 않는다. 서버가 따라잡으면 그때부터 다시 서버를 정본으로 본다.

export interface ReseedState<T> {
  /** 우리가 아는 서버 값 — 저장에 성공하면 **저장한 값**으로 앞당겨 둔다. */
  known: T;
  /** 저장은 했는데 서버가 아직 그 값을 안 돌려준 상태. 이 동안은 들어오는 props 를 무시한다. */
  awaitingServer: boolean;
}

export interface ReseedResult<T> extends ReseedState<T> {
  /** 입력칸을 incoming 으로 갈아끼울 것인가. */
  reseed: boolean;
}

/**
 * @param incoming 서버가 준 현재 값(props)
 * @param state    우리가 아는 값 + 저장 반영 대기 여부
 * @param dirty    저장하지 않은 편집이 있는가
 * @param equals   값 비교(기본 ===). 여러 칸을 묶어 쓰려면 넘긴다.
 */
export function decideReseed<T>(
  incoming: T,
  state: ReseedState<T>,
  dirty: boolean,
  equals: (a: T, b: T) => boolean = (a, b) => a === b,
): ReseedResult<T> {
  // ① 서버가 우리가 아는 값을 들고 왔다 — 할 일 없음. 저장 반영도 끝났다.
  if (equals(incoming, state.known)) {
    return { reseed: false, known: state.known, awaitingServer: false };
  }
  // ② 저장 직후인데 서버가 아직 옛 값을 들고 있다 — **무시한다.** 이것이 원래 버그의 자리다.
  if (state.awaitingServer) {
    return { reseed: false, known: state.known, awaitingServer: true };
  }
  // ③ 서버 값이 진짜로 바뀌었다(다른 사람·다른 탭·재생성). 편집 중이 아니면 갈아끼운다.
  return { reseed: !dirty, known: incoming, awaitingServer: false };
}

/** 저장에 성공했을 때의 다음 상태 — 저장한 값을 **앞당겨** 알고, 서버를 기다린다. */
export function afterSave<T>(saved: T): ReseedState<T> {
  return { known: saved, awaitingServer: true };
}
