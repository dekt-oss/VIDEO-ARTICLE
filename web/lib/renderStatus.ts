// 렌더 잡 상태 어휘 — engine/config.py 의 RENDER_STATUS_* 쌍둥이 (v3 §8-3).
//
// ★ 왜 파일 하나로 묶는가: 이 목록이 라우트 3곳에 각자 문자열 배열로 박혀 있었다
//   (directive-approve · report-directive-approve · report-render-retry). 새 상태를 추가할 때
//   **한 곳이라도 빠뜨리면** 승인 대기 중인 지시서에 두 번째 렌더 잡이 생긴다 — 같은 영상을
//   두 번 만들고 비용도 두 번 나간다.
//
// ★★ Python 과 갈리면 tests/test_schema_parity.py 가 잡는다. 값을 바꿀 때는 두 곳을 함께.

/** 워커가 돌고 있는 상태. 워치독이 정체 시 재큐하는 대상이다. */
export const RENDER_STATUS_IN_PROGRESS = ["assets", "tts", "assembling"] as const;

/** 사람이 봐야 끝나는 상태. **워치독이 절대 건드리면 안 된다** — 기계가 아니라 사람을 기다린다. */
export const RENDER_STATUS_AWAITING_HUMAN = ["qa_pending", "degraded"] as const;

/** "이 지시서에 이미 살아 있는 잡이 있는가" — 중복 발주 방지. 사람 대기도 살아 있는 잡이다. */
export const RENDER_STATUS_ACTIVE: string[] = [
  "queued",
  ...RENDER_STATUS_IN_PROGRESS,
  ...RENDER_STATUS_AWAITING_HUMAN,
];

export const RENDER_STATUS_TERMINAL = ["done", "failed"] as const;
