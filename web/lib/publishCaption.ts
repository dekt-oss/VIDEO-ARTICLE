// 숏츠 발행 캡션(설명란) 구성 — 논문 상세정보 + 링크 + 해시태그.
// ★ engine/attribution.py 와 동기화되는 이중관리 지점. 출처는 있는 값만 사용(지어내지 않음).

export interface Source {
  title: string;
  venue: string;
  year: string;
  authors: string[];
  institutions: string[];
  url: string;
}

interface PaperMeta {
  title?: string | null;
  venue?: string | null;
  url?: string | null;
  published_date?: string | null;
  authors?: { name?: string; institution?: string | null }[] | null;
}

function year(pub?: string | null): string {
  const s = String(pub ?? "");
  return s.length >= 4 && /^\d{4}$/.test(s.slice(0, 4)) ? s.slice(0, 4) : "";
}

// draft.fact_sheet.source 우선, 없으면 papers 메타데이터로 source 구성.
export function sourceFrom(paper: PaperMeta | null, factSheetSource?: Partial<Source> | null): Source {
  if (factSheetSource && (factSheetSource.title || factSheetSource.url)) {
    return {
      title: factSheetSource.title ?? "",
      venue: factSheetSource.venue ?? "",
      year: factSheetSource.year ?? "",
      authors: factSheetSource.authors ?? [],
      institutions: factSheetSource.institutions ?? [],
      url: factSheetSource.url ?? "",
    };
  }
  const authors = Array.isArray(paper?.authors) ? paper!.authors! : [];
  const names = authors.map((a) => a?.name).filter(Boolean).slice(0, 3) as string[];
  const insts = [...new Set(authors.map((a) => a?.institution).filter(Boolean))].slice(0, 3) as string[];
  return {
    title: paper?.title ?? "",
    venue: paper?.venue ?? "",
    year: year(paper?.published_date),
    authors: names,
    institutions: insts,
    url: paper?.url ?? "",
  };
}

function who(s: Source): string {
  if (s.institutions.length) return s.institutions.join(" · ");
  if (s.authors.length) return s.authors[0] + (s.authors.length > 1 ? " 외" : "");
  return s.venue;
}

export function buildPublishCaption(
  s: Source, teaser = "", lang: "ko" | "en" = "ko", hashtags?: string[],
): string {
  const vy = [s.venue, s.year].filter(Boolean).join(", ");
  const lines: string[] = [];
  if (teaser) { lines.push(teaser.trim()); lines.push(""); }
  const w = who(s);
  if (lang === "en") {
    if (s.title) lines.push(`📄 Paper: ${s.title}${vy ? ` (${vy})` : ""}`);
    if (w) lines.push(`🏛️ ${w}`);
    if (s.url) lines.push(`🔗 ${s.url}`);
  } else {
    if (s.title) lines.push(`📄 원논문: ${s.title}${vy ? ` (${vy})` : ""}`);
    if (w) lines.push(`🏛️ ${w}`);
    if (s.url) lines.push(`🔗 ${s.url}`);
  }
  const tags = hashtags ?? (lang === "en"
    ? ["#research", "#science", "#paper", "#AI", "#shorts"]
    : ["#논문", "#연구", "#과학", "#지식", "#쇼츠"]);
  if (lines.length && (s.title || s.url)) lines.push("");
  lines.push(tags.join(" "));
  // YouTube 발행 안전: 논문 제목 등의 HTML 태그/홑화살괄호 제거(invalidDescription 방지, 엔진과 동기화).
  return stripMarkup(lines.join("\n").trim());
}

// '<i>..</i>' 같은 태그 + 남은 '<' '>' 제거. engine/attribution.py strip_markup 와 동기화.
export function stripMarkup(text: string): string {
  return (text ?? "").replace(/<[^>]*>/g, "").replace(/[<>]/g, "");
}

// ── 리포트 발행 캡션 ─────────────────────────────────────────────
// ★ engine/report_attribution.py::build_publish_caption 과 **글자 그대로** 같아야 한다 —
//   화면에서 복사한 설명란과 워커가 업로드하는 설명란이 다르면 운영자가 본 것이 올라가지 않는다.
//   tests/test_report_caption_twin.py 가 문구·면책·해시태그를 대조한다(이중관리 지점).
export const REPORT_DISCLAIMER_TEXT =
  "본 영상은 정보 제공 목적이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다.";

export interface ReportMeta {
  broker?: string | null;
  analyst?: string | null;
  company?: string | null;
  theme?: string | null;
  report_url?: string | null;
}

export function buildReportPublishCaption(
  r: ReportMeta | null, teaser = "", lang: "ko" | "en" = "ko", hashtags?: string[],
): string {
  let who = r?.broker ?? "";
  if (r?.analyst) who = `${who} ${r.analyst}`.trim();
  const company = r?.company || r?.theme || "";
  const url = r?.report_url ?? "";
  const lines: string[] = [];
  if (teaser) { lines.push(teaser.trim()); lines.push(""); }
  let tags: string[];
  if (lang === "en") {
    if (company) lines.push(`📊 ${company}`);
    if (who) lines.push(`🏛️ Source: ${who}`);
    if (url) lines.push(`🔗 ${url}`);
    lines.push("⚠️ For information only. Not investment advice.");
    tags = hashtags ?? ["#stocks", "#investing", "#finance", "#shorts"];
  } else {
    if (company) lines.push(`📊 ${company}`);
    if (who) lines.push(`🏛️ 출처: ${who}`);
    if (url) lines.push(`🔗 ${url}`);
    lines.push(`⚠️ ${REPORT_DISCLAIMER_TEXT}`);
    tags = hashtags ?? ["#증권", "#리포트", "#주식", "#투자", "#쇼츠"];
  }
  lines.push("");
  lines.push(tags.join(" "));
  return lines.join("\n").trim();
}
