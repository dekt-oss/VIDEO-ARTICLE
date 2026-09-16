// 버전×언어 동시 발주의 예상 생성비. 순수 — 테스트: web/lib/orderCost.test.ts
//
// ★ 반드시 맞아야 하는 규칙 하나: **언어는 비용을 곱하지 않는다.**
//   이미지·Veo 클립은 언어 독립 캐시라 KO 렌더가 만든 에셋을 EN 렌더가 그대로 쓴다
//   (engine/assemble.py content_hash 에 lang 필드가 없다 — tests/test_shared_assets.py 가 고정).
//   TTS 는 edge-tts 로 $0. 그래서 총액은 **버전 수**로만 늘어난다.
//   이걸 틀리면 확인 모달이 실제의 두 배를 보여주고, 운영자가 하지 않아도 될 걱정을 한다.
//
// ★ 단가를 여기서 다시 계산하지 않는다. `header.cost_plan.estimated_total_generation_cost_usd`
//   는 엔진(engine/directive.compute_cost_plan)이 컷에서 계산해 저장한 값이다. 웹이 산수를
//   다시 하면 두 번째 진실원이 생긴다.
import type { Directive, VersionType } from "@/lib/types";

export interface VersionOrder {
  key: VersionType;
  directive: Directive | null;
}

export interface VersionCostLine {
  key: VersionType;
  /** 지시서가 아직 없으면 null — 컷이 없으니 계상할 것도 없다. */
  usd: number | null;
  uniqueAssets: number | null;
  videoClips: number | null;
  videoSec: number | null;
  /** 등급 분포(시퀀스 등급제 v2). 승인 직전에 "어디에 투자했는지"를 한 줄로 본다. */
  tiers?: Record<string, number>;
}

export interface OrderCostEstimate {
  /** 지시서가 있는 버전들의 예상 생성비 합계(언어 무관). */
  total: number;
  perVersion: VersionCostLine[];
  /** 아직 지시서가 없어 산정 불가한 버전 — 합계에서 빠졌다는 걸 UI 가 밝혀야 한다. */
  unknown: VersionType[];
  /** 이번 발주로 생길 렌더 잡 수 = 지시서 있는 버전 × 언어. */
  renderJobCount: number;
}

export function estimateOrder(versions: VersionOrder[], langs: string[]): OrderCostEstimate {
  const perVersion: VersionCostLine[] = [];
  const unknown: VersionType[] = [];
  let total = 0;
  let withDirective = 0;

  for (const v of versions) {
    const plan = v.directive?.header?.cost_plan;
    if (!plan) {
      unknown.push(v.key);
      perVersion.push({ key: v.key, usd: null, uniqueAssets: null, videoClips: null,
                        videoSec: null });
      continue;
    }
    const usd = Number(plan.estimated_total_generation_cost_usd) || 0;
    total += usd;
    withDirective += 1;
    perVersion.push({
      key: v.key,
      usd,
      uniqueAssets: plan.unique_asset_count ?? null,
      videoClips: plan.video_clip_count ?? null,
      videoSec: plan.video_generated_sec ?? null,
      // ★ 등급제 밖 버전에는 키 자체를 넣지 않는다 — `tiers: undefined` 를 넣으면
      //   객체 모양이 달라져 기존 계약(deepStrictEqual)이 깨진다. 실제로 깨졌다.
      ...(plan.tiers ? { tiers: plan.tiers } : {}),
    });
  }

  return {
    total: Math.round(total * 10000) / 10000,
    perVersion,
    unknown,
    renderJobCount: withDirective * Math.max(langs.length, 0),
  };
}

/** 모달에 그대로 넣는 한 줄. 언어가 공짜라는 사실을 운영자가 매번 다시 계산하지 않게 한다. */
export const LANG_COST_NOTE = "언어 추가 비용 $0 — 이미지·클립은 언어 공유(캐시)";

export function formatUsd(n: number): string {
  return `$${n.toFixed(2)}`;
}
