// 소재 개발이 자동으로 읽는 공식·전문 출처의 요약(이름·소재 낱말·글자 수). 순수 모듈 — 값 import 없음(node --test).
//
// ★ 정본은 engine/config.py 의 DRINKS_DEVELOP_OFFICIAL_SOURCES 다. 형식 추천이 근거 수를 세려면 화면도 이 목록을 알아야 해서 옮겨 적었고,
//   이름·낱말이 어긋나면 tests/test_drinks_develop.py 가 막는다. 글자 수는 2026-11-02 실측(메뉴 글 포함)이라 대강의 값이다.
// ★ 낱말이 걸렸다는 것은 "답이 있다"가 아니다. 진짜 판정은 근거 초안 단계의 글자 단위 인용 대조다.

export interface OfficialSourceHint {
  name: string;
  keywords: readonly string[];
  /** 소재에 이 낱말이 있으면 이 쪽에 답이 없어 집어 들지 않는다 */
  notFor: readonly string[];
  chars: number;
}

// prettier-ignore
export const OFFICIAL_SOURCE_HINTS: readonly OfficialSourceHint[] = [
  { name: "한국민족문화대백과사전 — 탁주", keywords: ["탁주", "막걸리"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "시큼", "신맛", "숙취"], chars: 4580 },
  { name: "한국민족문화대백과사전 — 막걸리", keywords: ["막걸리"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "시큼", "신맛", "숙취"], chars: 3963 },
  { name: "한국민족문화대백과사전 — 막걸리 빚기", keywords: ["막걸리", "누룩"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "시큼", "신맛", "숙취"], chars: 4727 },
  { name: "한국민족문화대백과사전 — 청주", keywords: ["청주", "약주"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], chars: 4226 },
  { name: "한국민족문화대백과사전 — 술", keywords: ["전통주", "누룩", "증류식", "소주"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], chars: 29501 },
  { name: "일본 국세청 — 清酒 표시기준 개요", keywords: ["사케", "일본주", "준마이", "다이긴조", "긴조", "정미", "제조 시기"], notFor: ["보관", "개봉", "숙취"], chars: 5583 },
  { name: "일본 국세청 — 清酒 표시기준 고시", keywords: ["사케", "일본주", "준마이", "다이긴조", "긴조", "정미"], notFor: ["보관", "개봉", "숙취"], chars: 5304 },
  { name: "일본 국세청 — お酒 Q&A", keywords: ["일본주", "주류 분류"], notFor: ["보관", "개봉", "숙취"], chars: 4510 },
  { name: "영국 Scotch Whisky Regulations 제3조", keywords: ["스카치", "싱글몰트", "블렌디드"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], chars: 8205 },
  { name: "영국 Scotch Whisky Regulations 제12조", keywords: ["스카치", "싱글몰트", "12년", "숙성 표기"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], chars: 7183 },
  { name: "미국 27 CFR §5.143 Whisky", keywords: ["버번", "라이 위스키", "테네시"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], chars: 10343 },
  { name: "미국 NIAAA — 숙취", keywords: ["숙취", "hangover"], notFor: [], chars: 7153 },
  { name: "미국 NIAAA — 알코올 대사", keywords: ["숙취", "알코올 분해", "아세트알데히드", "얼굴 빨개", "대사"], notFor: [], chars: 8480 },
];

/** 질문에 낱말이 걸리는 출처 수와 글자 수. 질문이 없으면 0. */
export function officialSourceHits(question: string | null): { count: number; chars: number } {
  const q = (question ?? "").toLowerCase();
  let count = 0;
  let chars = 0;
  if (!q) return { count, chars };
  for (const s of OFFICIAL_SOURCE_HINTS) {
    if (s.keywords.some((k) => q.includes(k)) && !s.notFor.some((k) => q.includes(k))) {
      count += 1;
      chars += s.chars;
    }
  }
  return { count, chars };
}

/** DB 수집 글 수(못 읽었으면 없음)에 출처 목록 수를 더한다. 걸린 것이 없으면 "못 읽음"을 0 으로 바꾸지 않고 그대로 둔다. */
export function withOfficialHits(base: { count: number; chars: number } | undefined, question: string | null): { count: number; chars: number } | undefined {
  const hit = officialSourceHits(question);
  if (hit.count === 0) return base;
  return { count: (base?.count ?? 0) + hit.count, chars: (base?.chars ?? 0) + hit.chars };
}
