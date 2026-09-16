// effects·전환 enum 의 사람 라벨 (개선 지시서 §6-4 "기술 용어 표현").
//
// 엔진 enum(`engine/config.py` ALLOWED_EFFECTS)은 그대로 둔다 — DB·프롬프트·렌더가 이 문자열을
// 쓴다. 화면에만 한국어 라벨을 병기하고, 원시 값은 툴팁(title)으로 남겨 대조할 수 있게 한다.
// 새 enum 이 엔진에 추가되고 여기 없으면 원시 값을 그대로 보여준다(숨기지 않는다).

const EFFECT_LABELS: Record<string, string> = {
  ken_burns_zoom_in: "천천히 확대",
  ken_burns_zoom_out: "천천히 축소",
  pan_left: "왼쪽으로 이동",
  pan_right: "오른쪽으로 이동",
  highlight: "강조",
};

const TRANSITION_LABELS: Record<string, string> = {
  cut: "즉시 전환",
  crossfade: "부드러운 전환",
};

const PREFIX_LABELS: { prefix: string; label: string }[] = [
  { prefix: "text_overlay:", label: "자막" },
  { prefix: "particle:", label: "입자 효과" },
];

/** effects 토큰 1개의 사람 라벨. 접두 파라미터 토큰(text_overlay:…)도 처리한다. */
export function effectLabel(token: string): string {
  const fixed = EFFECT_LABELS[token];
  if (fixed) return fixed;
  for (const { prefix, label } of PREFIX_LABELS) {
    if (token.startsWith(prefix)) return `${label} “${token.slice(prefix.length)}”`;
  }
  return token; // 모르는 값은 원시 그대로 — 조용히 감추지 않는다
}

export function transitionLabel(token: string): string {
  return TRANSITION_LABELS[token] ?? token;
}
