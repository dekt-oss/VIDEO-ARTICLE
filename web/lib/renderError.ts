// 렌더/업로드 실패 로그 → 사람이 읽는 원인 + 다음 행동 (개선 지시서 RENDER-01).
//
// 지금까지 실패 잡은 error_log 원문(ffmpeg stderr, 파이썬 트레이스백)을 화면에 그대로 쏟았고,
// 재시도 버튼도 없었다 — 운영자가 "무엇이 왜 실패했고 뭘 눌러야 하는지"를 알 수 없었다.
// 이 함수는 로그를 분류만 한다(순수 함수). UI 는 components/ErrorDisclosure.tsx.
//
// 패턴은 실제 파이프라인에서 나오는 문자열을 기준으로 골랐다:
//   engine/assemble.py(ffmpeg), engine/render.py(예산 게이트), engine/publish.py(유튜브 OAuth).

export type RenderErrorKind =
  | "board_contract"
  | "board_underfilled"
  | "corrupt_media"
  | "unreadable_asset"
  | "budget"
  | "youtube_auth"
  | "youtube_metadata"
  | "tts"
  | "provider_quota"
  | "timeout"
  | "unknown";

export interface ParsedRenderError {
  kind: RenderErrorKind;
  /** 무엇이 잘못됐는가(한 문장). */
  cause: string;
  /** 운영자가 다음에 할 일(한 문장). */
  action: string;
  /** 재시도(재렌더/재업로드)가 의미 있는 실패인가. */
  retryable: boolean;
}

interface Rule {
  kind: RenderErrorKind;
  test: RegExp;
  cause: string;
  action: string;
  retryable: boolean;
}

// 순서가 우선순위다 — 위에서 처음 걸리는 규칙을 쓴다(구체적인 것부터).
const RULES: Rule[] = [
  {
    kind: "budget",
    test: /예산|budget|cost cap|VEO_MAX|MAX_COST/i,
    cause: "설정된 렌더 비용 상한을 넘어 중단됐습니다.",
    action: "컷 수나 영상 클립 수를 줄이거나, 비용 상한(config)을 조정한 뒤 재렌더하세요.",
    retryable: false,
  },
  {
    // ★ 충전율 미달은 **위 규칙보다 먼저** 걸러야 한다. 아래 board_contract 규칙에 삼켜지면
    //   "같은 문장이 두 번 나오거나 글자가 칸을 넘침"이라고 안내하는데, 원인은 정반대다 —
    //   화면이 **비어서** 막힌 것이다. 그 안내를 따라 문장을 줄이면 더 나빠진다(실측 신고).
    //   재렌더도 소용없다: 충전율은 지시서의 요소 좌표만으로 계산하는 순수 기하 연산이라
    //   같은 지시서면 몇 번을 돌려도 같은 값이 나온다(engine/board_layout.core_coverage).
    kind: "board_underfilled",
    test: /core_underfilled/i,
    cause: "설명판 화면의 가운데가 너무 비어서 중단됐습니다(요소가 차지한 면적이 기준 미만).",
    action:
      "재렌더로는 풀리지 않습니다 — 같은 지시서면 같은 결과가 나옵니다. 로그에 찍힌 컷의 내용을 늘려야 합니다: 그 컷에 숫자 근거를 더 붙이거나, 지시서를 다시 생성하세요.",
    retryable: false,
  },
  {
    // 설명판형 시각 계약(v3.4 §22 K8~K11). engine/visual_contract.py · engine/board_render.py 가
    // 던지는 문구 그대로 잡는다 — 이 실패는 "대본·지시서를 고쳐라"는 신호라 재렌더만으로는 안 풀린다.
    kind: "board_contract",
    test: /DUPLICATE ON-SCREEN TEXT|TEXT TOO LONG|보드 규격 위반|FONT (CONTRACT|MISSING)/i,
    cause: "설명판 화면이 규격을 어겨 중단됐습니다(같은 문장이 두 번 나오거나 글자가 칸을 넘침).",
    action:
      "재렌더해 보세요. 같은 문장이 또 잡히면 로그에 찍힌 그 문장을 지시서에서 고쳐야 합니다 — 중복이면 한쪽을 지우고, 너무 길면 줄입니다.",
    retryable: true,
  },
  {
    kind: "youtube_auth",
    test: /invalid_grant|unauthorized|401|refresh token|oauth/i,
    cause: "유튜브 인증이 만료됐거나 거부됐습니다.",
    action: "채널 OAuth 리프레시 토큰을 다시 발급해 시크릿을 갱신한 뒤 업로드를 재시도하세요.",
    retryable: true,
  },
  {
    kind: "youtube_metadata",
    test: /invalidDescription|invalidTitle|invalidVideoMetadata/i,
    cause: "유튜브가 제목·설명란 형식을 거부했습니다.",
    action: "발행 제목·설명에 HTML 태그나 금지 문자가 있는지 확인하고 고친 뒤 재시도하세요.",
    retryable: true,
  },
  {
    kind: "corrupt_media",
    test: /moov atom not found|Invalid NAL|truncated|Output file is empty/i,
    cause: "영상 파일이 불완전하거나 손상됐습니다(생성이 중간에 끊긴 경우).",
    action: "재렌더하세요. 반복되면 해당 컷의 클립 생성 단계를 확인해야 합니다.",
    retryable: true,
  },
  {
    kind: "unreadable_asset",
    test: /Invalid data found|No such file or directory|does not contain any stream|Cannot open/i,
    cause: "입력 에셋(이미지·클립·오디오)을 읽지 못했습니다.",
    action: "해당 컷 에셋을 다시 생성한 뒤 재렌더하세요.",
    retryable: true,
  },
  {
    kind: "tts",
    test: /edge[-_ ]?tts|NoAudioReceived|synthes/i,
    cause: "나레이션 음성 합성(TTS)이 실패했습니다.",
    action: "나레이션 텍스트에 이상 문자가 없는지 확인하고 재렌더하세요(일시 오류면 재시도로 해결됩니다).",
    retryable: true,
  },
  {
    kind: "provider_quota",
    test: /quota|rate limit|429|RESOURCE_EXHAUSTED/i,
    cause: "생성 API 사용량 한도에 걸렸습니다.",
    action: "잠시 뒤 재렌더하세요. 반복되면 일일 한도가 소진된 것입니다.",
    retryable: true,
  },
  {
    kind: "timeout",
    test: /timed? ?out|deadline exceeded|ETIMEDOUT/i,
    cause: "외부 호출이 시간 안에 끝나지 않았습니다.",
    action: "재렌더하세요. 같은 컷에서 반복되면 그 컷의 프롬프트를 단순화하세요.",
    retryable: true,
  },
];

const UNKNOWN: ParsedRenderError = {
  kind: "unknown",
  cause: "원인을 자동 분류하지 못했습니다.",
  action: "아래 기술 로그를 확인한 뒤 재렌더하세요.",
  retryable: true,
};

export function parseRenderError(log: string | null | undefined): ParsedRenderError {
  const text = (log ?? "").trim();
  if (!text) {
    return {
      kind: "unknown",
      cause: "실패 로그가 남지 않았습니다.",
      action: "재렌더해 보고, 다시 실패하면 워커 로그(GitHub Actions)를 확인하세요.",
      retryable: true,
    };
  }
  for (const r of RULES) {
    if (r.test.test(text)) {
      return { kind: r.kind, cause: r.cause, action: r.action, retryable: r.retryable };
    }
  }
  return UNKNOWN;
}
