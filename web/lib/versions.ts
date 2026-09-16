// 제공 영상 버전의 단일 출처. engine/config.py VIDEO_VERSIONS 와 동기화(이중관리 주의).
//
// ★ 페이지 파일에서 export 하면 안 된다 — Next.js App Router 는 page.tsx 의 export 를
//   엄격히 제한해서 빌드가 깨진다. 그래서 lib 로 뺐다.
// ★ 폐기된 버전(새로 발주 불가, 저장된 옛 행은 계속 열림):
//   - editorial  2026-07-28 (docs/deviation-webtoon-b1-removal.md)
//   - webtoon    2026-08-28 (운영자 결정 — docs/deviation-drop-explainer-webtoon.md)
//   - explainer  2026-08-28 (운영자 결정 — 같은 문서)
import type { VersionType } from "@/lib/types";

export interface VersionMeta {
  key: VersionType;
  label: string;
  /** 운영자가 두 버전의 차이를 한 줄로 알 수 있게. 발주 체크박스 옆에 붙는다. */
  hint: string;
}

export const VERSION_META: VersionMeta[] = [
  { key: "comic", label: "만화식", hint: "컷마다 새 장면을 그린다(기존 방식)" },
  // 2026-08-20 부터 두 공장 모두에서 발주한다(운영자 결정: 논문·리포트 각각 준비).
  // ★ 이름이 "실사형" → "3D 그래픽" 으로 바뀌었다(2026-09-08 운영자 지시).
  //   화풍을 무광 CG 로 확정하면서 REALITY 컷도 더는 사진이 아니다 — 이름이 화면과
  //   달라지면 운영자가 무엇을 발주하는지 헷갈린다. **키(`photo`)는 그대로다**:
  //   저장된 지시서·렌더·업로드가 전부 그 키를 쓴다.
  { key: "photo", label: "3D 그래픽", hint: "무광 CG 한 화풍. 원리는 단면 도해로, 현장은 같은 재질의 3D 장면으로" },
];

export const VERSION_KEYS: VersionType[] = VERSION_META.map((v) => v.key);
export const DEFAULT_VERSION_KEY: VersionType = "comic";

// ── 리포트 공장이 발주할 수 있는 버전 ──
// 설명판형·웹툰을 걷어낸 뒤로 두 공장의 목록이 같아졌다. 그래도 배열은 나눠 둔다 —
// 한쪽만 버전을 늘리는 일이 지금까지 반복됐고, 합쳐 두면 그때 다른 공장 화면에 새 버전이
// 조용히 나타난다.
export const REPORT_VERSION_META: VersionMeta[] = [
  { key: "comic", label: "만화식", hint: "컷마다 장면을 그린다(기존 방식)" },
  {
    key: "photo",
    label: "3D 그래픽",
    hint: "무광 CG 한 화풍. 원리는 단면 도해로, 현장은 같은 재질의 3D 장면으로",
  },
];

export const REPORT_VERSION_KEYS: VersionType[] = REPORT_VERSION_META.map((v) => v.key);
export const REPORT_DEFAULT_VERSION_KEY: VersionType = "comic";

/**
 * 초안 요청에 실어 보낼 "이어서 만들 지시서 버전"(0046). 미허용 값·중복을 걷어낸다.
 * ★ 서버 라우트(generate-draft·report-generate-draft)가 큐에 넣기 전에 거른다 — 미허용 값이
 *   워커까지 가면 VERSION_GUIDANCE 가 기본 버전으로 조용히 갈아치운다(2026-08-20 사고).
 */
export function chainableVersions(raw: unknown, offered: VersionType[] = VERSION_KEYS): VersionType[] {
  const list = Array.isArray(raw) ? raw : [];
  return [...new Set(list.map(String).filter((v): v is VersionType => (offered as string[]).includes(v)))];
}

export function isOfferedVersion(v: string | undefined | null): v is VersionType {
  return !!v && (VERSION_KEYS as string[]).includes(v);
}

export function isOfferedReportVersion(v: string | undefined | null): v is VersionType {
  return !!v && (REPORT_VERSION_KEYS as string[]).includes(v);
}

export function reportVersionLabel(v: VersionType | string): string {
  return REPORT_VERSION_META.find((m) => m.key === v)?.label ?? String(v);
}

export function versionLabel(v: VersionType | string): string {
  return VERSION_META.find((m) => m.key === v)?.label ?? String(v);
}
