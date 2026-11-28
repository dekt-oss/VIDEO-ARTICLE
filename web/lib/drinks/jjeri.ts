const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;

export type JjeriFormat = "jjeri_class" | "jjeri_anatomy";

export function jjeriPreview(plan: unknown, format: JjeriFormat = "jjeri_class") {
  const episode = object(object(plan)?.[format]);
  const layout = format === "jjeri_class" ? episode?.scenes : episode?.worlds;
  if (episode?.format !== format || episode.version !== 1 || typeof episode.topic !== "string"
      || !Array.isArray(layout) || layout.length === 0 || !Array.isArray(episode.chapters)) return null;
  const scenes = [];
  for (const value of layout) {
    const scene = object(value);
    const template = format === "jjeri_class" ? scene?.template : scene?.world;
    if (typeof scene?.id !== "string" || typeof template !== "string" || !Array.isArray(scene.beats)) return null;
    const beats = [];
    for (const value of scene.beats) {
      const text = object(value)?.text;
      if (typeof text !== "string") return null;
      beats.push({ text });
    }
    scenes.push({ id: scene.id, template, beats });
  }
  const chapters = [];
  for (const value of episode.chapters) {
    const row = object(value);
    const from = format === "jjeri_class" ? row?.from_scene : row?.world;
    if (!row || typeof from !== "string" || typeof row.title !== "string") return null;
    chapters.push({ from_scene: from, title: row.title });
  }
  return { topic: episode.topic, scenes, chapters };
}

export function jjeriQa(qa: unknown) {
  const row = object(qa);
  if (row?.renderer !== "jjeri_class" && row?.renderer !== "jjeri_anatomy") return null;
  const audio = object(row.audio);
  const evidence = object(row.evidence);
  const sceneSources = object(evidence?.source_ids_by_scene);
  return {
    lufs: typeof audio?.lufs === "number" ? audio.lufs : null,
    peak: typeof audio?.true_peak_dbtp === "number" ? audio.true_peak_dbtp : null,
    reviewedScenes: sceneSources ? Object.values(sceneSources).filter((ids) => Array.isArray(ids) && ids.length > 0).length : 0,
    humanReview: evidence?.human_source_review_required === true,
  };
}


type CapabilityResult = { data: unknown; error: { code?: string } | null };

export type JjeriAvailability =
  | { state: "ready"; episode: NonNullable<ReturnType<typeof jjeriPreview>> }
  | { state: "hidden" | "directive_invalid" | "db_missing" | "db_unavailable" };

export function jjeriAvailability(plan: unknown, enabled: boolean, capability: CapabilityResult | null, format: JjeriFormat = "jjeri_class"): JjeriAvailability {
  if (!enabled || !Object.hasOwn(object(plan) ?? {}, format)) return { state: "hidden" };
  const episode = jjeriPreview(plan, format);
  if (!episode) return { state: "directive_invalid" };
  if (capability?.error && ["PGRST202", "42883"].includes(capability.error.code ?? "")) return { state: "db_missing" };
  if (!capability || capability.error || object(capability.data)?.[format === "jjeri_class" ? "ready" : "anatomy_ready"] !== true) return { state: "db_unavailable" };
  return { state: "ready", episode };
}

export const JJERI_AVAILABILITY_WARNING = {
  directive_invalid: "째리의 술 수업 지시서 형식이 올바르지 않습니다. 제작안의 지시서를 확인해 주세요.",
  db_missing: "이 환경에 째리의 술 수업 제작 기능이 적용되지 않았습니다.",
  db_unavailable: "째리의 술 수업 제작 기능을 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.",
} as const;

const JJERI_JOB_WARNING: Record<string, string> = {
  source_label_invalid: "출처 칩에 넣을 발행처명이 비어 있거나 너무 깁니다. 출처에 짧고 정확한 발행처명을 입력해 주세요.",
  source_chip_overflow: "한 장면의 출처 표기가 화면 칸보다 깁니다. 지시서의 출처 연결과 발행처명을 점검해 주세요.",
  claim_unapproved: "인용한 주장에 지지 검토가 완료되지 않았습니다. 해당 주장의 원문을 대조한 뒤 근거 버전을 승인해 주세요.",
  health_claim_forbidden: "질병 치료나 건강 효능을 나타내는 문구를 제거해 주세요.",
  advice_unsupported: "권고 문구를 확인해 주세요. 해당 권고를 직접 뒷받침하는 검증된 원문이 필요합니다.",
};

export function jjeriJobMessage(renderer: string, code: string, fallback: string | null | undefined): string | null | undefined {
  return renderer === "jjeri_class" || renderer === "jjeri_anatomy" ? JJERI_JOB_WARNING[code] ?? fallback : fallback;
}
