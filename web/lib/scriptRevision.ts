// 대본 지문 — engine/script_revision.py 의 쌍둥이 (PR #94 후속 리뷰 P1-3).
//
// ★ 왜 양쪽에 있나: 판정을 만드는 쪽은 엔진(초안 생성·재검사)이고, 그 판정이 지금 대본의
//   것인지 **보여 주는** 쪽은 ④ 화면이다. 화면이 매번 워커를 부를 수는 없으니 같은 계산을
//   여기서도 한다.
// ★★ 계약이 갈리면 경고가 늑대소년이 된다 — 늘 "검증 이후 수정됨"이 뜨면 아무도 안 읽는다.
//    계약: sha256(대본 원문 utf-8) 의 앞 16글자. 파리티는 tests/test_script_revision.py 와
//    tests/test_schema_parity.py 가 지킨다.
import { createHash } from "node:crypto";

/** 대본의 지문. 같은 글이면 같은 값, 한 글자만 달라도 다른 값. 빈 대본은 빈 문자열. */
export function fingerprint(scriptMd: string | null | undefined): string {
  const text = (scriptMd ?? "").trim();
  if (!text) return "";
  return createHash("sha256").update(text, "utf8").digest("hex").slice(0, 16);
}

/**
 * 화면에 뜬 검사 결과가 지금 대본의 것인가.
 *
 * false 면 "검사 이후 대본이 수정됐다"는 뜻이다. 승인을 막지는 않는다(운영자 결정) —
 * 표시하고, 그 상태로 승인하면 발행 기록에 흔적을 남긴다.
 */
export function isValidationCurrent(
  scriptMd: string | null | undefined,
  validatedHash: string | null | undefined,
): boolean {
  const current = fingerprint(scriptMd);
  const validated = (validatedHash ?? "").trim();
  // 지문이 아직 없는 옛 초안은 판단하지 않는다(경고를 띄우면 전부 빨개진다).
  if (!validated) return true;
  return current === validated;
}
