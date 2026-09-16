// engine/report_evidence.GATE_LABELS 의 트윈 — 게이트 토큰을 사람 말로 옮긴다.
//
// ★ 왜 웹에도 두는가: 게이트 결과(evidence.block_reasons 등)는 `number_without_period:num_3`
//   같은 토큰 리스트로 저장된다. 운영자에게 그대로 보여주면 읽을 수 없다.
// ★ 이중관리 지점 — 키가 어긋나면 tests/test_prompt_sync.py 의 대조가 실패한다.
export const GATE_LABELS: Record<string, string> = {
  number_without_unit: "단위가 없는 수치가 있습니다.",
  number_without_period: "어느 시점의 수치인지가 확정되지 않았습니다(예: 2026F, 2Q26).",
  quote_not_in_source: "인용문이 원문에서 발견되지 않습니다(지어낸 인용 가능성).",
  number_not_in_quote: "인용문 안에 그 숫자가 없습니다.",
  conflicting_numbers: "같은 지표·기간에 서로 다른 값이 있습니다(어느 쪽이 맞는지 확인 필요).",
  evidence_below_min: "이 유형의 리포트에 필요한 근거 수치 개수가 모자랍니다.",
  comparator_below_min: "비교 기준이 붙은 수치가 모자랍니다(숫자만 크게 내보내지 않기 위함).",
  category_missing: "이 유형에 필요한 근거 범주가 빠졌습니다.",
  risks_missing: "리포트가 언급한 리스크가 Fact Sheet 에 없습니다.",
  no_fact_has_source_ref: "원문 인용이 붙은 수치가 하나도 없습니다.",
  thesis_missing: "이 영상이 증명하려는 한 문장이 없습니다.",
  claims_below_min: "핵심 주장이 너무 적습니다.",
  claims_above_max: "핵심 주장이 너무 많습니다(하나에 집중되지 않습니다).",
  claim_without_evidence: "근거 없이 주장만 있는 대목이 있습니다.",
  evidence_ref_unknown: "Fact Sheet 에 없는 근거를 가리킵니다.",
  closing_before_proof: "결론이 증거보다 먼저 나옵니다.",
  evidence_reused: "같은 수치를 여러 주장이 반복해서 씁니다.",
  duration_estimate_off: "계획한 길이와 나레이션 길이가 다릅니다 — 영상은 나레이션 길이로 나갑니다.",
  // 옛 검사(2026-08-19 이전 초안에 저장된 토큰). 라벨이 없으면 원시 토큰이 화면에 찍힌다.
  narration_too_long_for_cut: "(옛 검사) 컷 길이보다 나레이션이 깁니다 — 지금은 편당 1건으로 요약합니다.",
  too_many_numbers_in_scene: "한 씬에 소리 내 읽는 숫자가 너무 많습니다.",
};

/** 'number_without_unit:num_3' → 사람 말. 접미(:id)는 떼고 찾는다. */
export function gateLabel(reason: string): string {
  return GATE_LABELS[reason.split(":")[0]] ?? reason;
}

/** 토큰의 접미(:id)만 뽑는다 — 어느 수치·씬인지 화면에 함께 보여주기 위함. */
export function gateSubject(reason: string): string {
  const idx = reason.indexOf(":");
  return idx >= 0 ? reason.slice(idx + 1) : "";
}

/** 원문 확보 깊이를 사람 말로. Fact Sheet 가 무엇을 보고 만들어졌는지가 신뢰의 출발점이다. */
export const SOURCE_DEPTH_LABELS: Record<string, string> = {
  full_text: "원문 전문",
  partial_text: "원문 일부",
  summary_only: "요약만",
  parse_failed: "원문 파싱 실패",
};
