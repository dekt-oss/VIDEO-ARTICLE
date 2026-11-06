// 소재 개발이 자동으로 읽는 공식·전문 출처의 요약(이름·주소·소재 낱말·글자 수). 순수 모듈 — 값 import 없음(node --test).
//
// ★ 정본은 engine/config.py 의 DRINKS_DEVELOP_OFFICIAL_SOURCES 다. 형식 추천이 근거 수를 세려면 화면도 이 목록을 알아야 해서 옮겨 적었고,
//   이름·주소·낱말이 어긋나면 tests/test_drinks_develop.py 가 막는다. 글자 수는 실측(메뉴 글 포함)이라 대강의 값이다.
// ★ 낱말이 걸렸다는 것은 "답이 있다"가 아니다. 진짜 판정은 근거 초안 단계의 글자 단위 인용 대조다.
// ★ 2026-11-06: 보관·기한 질문 전용 두 쪽을 더했다(requiresAny — 소재에 그 낱말이 하나라도 있어야 쓴다). docs/deviation-drinks-auto-factcheck.md

export interface OfficialSourceHint {
  name: string;
  /** 워커가 이 주소에서 본문을 가져온다 — 화면이 '직접 입력'과 구분하는 데 쓴다 */
  url: string;
  keywords: readonly string[];
  /** 소재에 이 낱말이 있으면 이 쪽에 답이 없어 집어 들지 않는다 */
  notFor: readonly string[];
  /** 비어 있지 않으면 소재에 이 낱말이 하나라도 있어야 쓴다(보관·기한 전용 쪽) */
  requiresAny: readonly string[];
  chars: number;
}

// prettier-ignore
export const OFFICIAL_SOURCE_HINTS: readonly OfficialSourceHint[] = [
  { name: "한국민족문화대백과사전 — 탁주", url: "https://encykorea.aks.ac.kr/Article/E0058756", keywords: ["탁주", "막걸리"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "시큼", "신맛", "숙취"], requiresAny: [], chars: 4580 },
  { name: "한국민족문화대백과사전 — 막걸리", url: "https://encykorea.aks.ac.kr/Article/E0017498", keywords: ["막걸리"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "시큼", "신맛", "숙취"], requiresAny: [], chars: 3963 },
  { name: "한국민족문화대백과사전 — 막걸리 빚기", url: "https://encykorea.aks.ac.kr/Article/E0079922", keywords: ["막걸리", "누룩"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "시큼", "신맛", "숙취"], requiresAny: [], chars: 4727 },
  { name: "한국민족문화대백과사전 — 청주", url: "https://encykorea.aks.ac.kr/Article/E0056708", keywords: ["청주", "약주"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], requiresAny: [], chars: 4226 },
  { name: "한국민족문화대백과사전 — 술", url: "https://encykorea.aks.ac.kr/Article/E0032021", keywords: ["전통주", "누룩", "증류식", "소주"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], requiresAny: [], chars: 29501 },
  { name: "일본 국세청 — 清酒 표시기준 개요", url: "https://www.nta.go.jp/taxes/sake/hyoji/seishu/gaiyo/02.htm", keywords: ["사케", "일본주", "준마이", "다이긴조", "긴조", "정미", "제조 시기"], notFor: ["보관", "개봉", "숙취"], requiresAny: [], chars: 5583 },
  { name: "일본 국세청 — 清酒 표시기준 고시", url: "https://www.nta.go.jp/taxes/sake/hyoji/seishu/kokuji891122/03.htm", keywords: ["사케", "일본주", "준마이", "다이긴조", "긴조", "정미"], notFor: ["보관", "개봉", "숙취"], requiresAny: [], chars: 5304 },
  { name: "일본 국세청 — お酒 Q&A", url: "https://www.nta.go.jp/taxes/sake/qa/01.htm", keywords: ["일본주", "주류 분류"], notFor: ["보관", "개봉", "숙취"], requiresAny: [], chars: 4510 },
  { name: "영국 Scotch Whisky Regulations 제3조", url: "https://www.legislation.gov.uk/uksi/2009/2890/regulation/3", keywords: ["스카치", "싱글몰트", "블렌디드"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], requiresAny: [], chars: 8205 },
  { name: "영국 Scotch Whisky Regulations 제12조", url: "https://www.legislation.gov.uk/uksi/2009/2890/regulation/12", keywords: ["스카치", "싱글몰트", "12년", "숙성 표기"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], requiresAny: [], chars: 7183 },
  { name: "미국 27 CFR §5.143 Whisky", url: "https://www.ecfr.gov/api/renderer/v1/content/enhanced/current/title-27?part=5&section=5.143", keywords: ["버번", "라이 위스키", "테네시"], notFor: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "숙취"], requiresAny: [], chars: 10343 },
  { name: "미국 NIAAA — 숙취", url: "https://www.niaaa.nih.gov/publications/brochures-and-fact-sheets/hangovers", keywords: ["숙취", "hangover"], notFor: [], requiresAny: [], chars: 7153 },
  { name: "미국 NIAAA — 알코올 대사", url: "https://www.niaaa.nih.gov/publications/alcohol-metabolism", keywords: ["숙취", "알코올 분해", "아세트알데히드", "얼굴 빨개", "대사"], notFor: [], requiresAny: [], chars: 8480 },
  { name: "일본 국세청 — 酒類 표시기준 해석(生酒 보관 주의·제조시기)", url: "https://www.nta.go.jp/law/tsutatsu/kihon/sake/8-09a.htm", keywords: ["사케", "일본주", "생주", "나마자케"], notFor: ["숙취"], requiresAny: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질", "냉장", "제조일"], chars: 8286 },
  { name: "영국 식품정보 규정(EU 1169/2011) 부속서 X — 소비기한 표시 면제", url: "https://www.legislation.gov.uk/eur/2011/1169/annex/X", keywords: ["위스키", "스카치", "버번", "증류주"], notFor: ["숙취"], requiresAny: ["보관", "개봉", "유통기한", "소비기한", "상하", "변질"], chars: 11099 },
];

/** 이 주소가 워커가 자동으로 읽는 공식 출처 쪽인가(옛 기록은 연결 메모가 없어 주소로 알아본다). */
export function isOfficialSourceUrl(url: string | null | undefined): boolean {
  return Boolean(url) && OFFICIAL_SOURCE_HINTS.some((s) => s.url === url);
}

/** 질문에 낱말이 걸리는 출처 수와 글자 수. 질문이 없으면 0. */
export function officialSourceHits(question: string | null): { count: number; chars: number } {
  const q = (question ?? "").toLowerCase();
  let count = 0;
  let chars = 0;
  if (!q) return { count, chars };
  for (const s of OFFICIAL_SOURCE_HINTS) {
    if (s.keywords.some((k) => q.includes(k)) && !s.notFor.some((k) => q.includes(k))
      && (s.requiresAny.length === 0 || s.requiresAny.some((k) => q.includes(k)))) {
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
