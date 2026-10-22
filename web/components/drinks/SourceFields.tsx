"use client";

// 출처 입력 칸 — 소재 등록과 출처 추가에서 같이 쓴다.
// ★ URL 을 넣어도 서버가 그 페이지를 가져오지 않는다(A단계). 본문·발췌를 직접 붙여 넣지 않으면
//   metadata_only 로 저장되고 근거로 쓸 수 없다 — 그 사실을 입력 칸 바로 밑에 적어 둔다.
import { DEPTH_LABEL, RIGHTS_LABEL, ROLE_LABEL, SOURCE_KIND_LABEL } from "@/lib/drinks/model";

export interface SourceInput {
  url: string;
  title: string;
  publisher: string;
  source_kind: string;
  role: "discovery" | "evidence";
  depth: "excerpt" | "full_text";
  body_text: string;
  excerpt_locator: string;
  original_language: string;
  published_at: string;
  checked_at: string;
  rights_status: string;
  usage_terms: string;
  origin_group: string;
}

export const EMPTY_SOURCE: SourceInput = {
  url: "", title: "", publisher: "", source_kind: "official", role: "evidence", depth: "excerpt", body_text: "",
  excerpt_locator: "", original_language: "", published_at: "", checked_at: "", rights_status: "unknown",
  usage_terms: "", origin_group: "",
};

export function hasSource(s: SourceInput): boolean {
  return s.url.trim() !== "" || s.body_text.trim() !== "";
}

/** 빈 칸은 보내지 않는다(서버가 null 로 저장). */
export function sourcePayload(s: SourceInput): Record<string, string> {
  return Object.fromEntries(Object.entries(s).filter(([, v]) => typeof v === "string" && v.trim() !== ""));
}

export default function SourceFields({ value, onChange }: { value: SourceInput; onChange: (v: SourceInput) => void }) {
  const set = <K extends keyof SourceInput>(k: K, v: SourceInput[K]) => onChange({ ...value, [k]: v });
  const urlOnly = value.url.trim() !== "" && value.body_text.trim() === "";
  return (
    <div>
      <div className="dk-grid">
        <label className="dk-field">
          <span>URL (선택)</span>
          <input value={value.url} onChange={(e) => set("url", e.target.value)} placeholder="https://" inputMode="url" />
        </label>
        <label className="dk-field">
          <span>역할</span>
          <select value={value.role} onChange={(e) => set("role", e.target.value as SourceInput["role"])}>
            {Object.entries(ROLE_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label className="dk-field">
          <span>출처 종류</span>
          <select value={value.source_kind} onChange={(e) => set("source_kind", e.target.value)}>
            {Object.entries(SOURCE_KIND_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label className="dk-field">
          <span>제목</span>
          <input value={value.title} onChange={(e) => set("title", e.target.value)} />
        </label>
        <label className="dk-field">
          <span>발행처</span>
          <input value={value.publisher} onChange={(e) => set("publisher", e.target.value)} placeholder="예: 일본 국세청" />
        </label>
        <label className="dk-field">
          <span>원문 언어</span>
          <input value={value.original_language} onChange={(e) => set("original_language", e.target.value)} placeholder="ko / ja / en" />
        </label>
        <label className="dk-field">
          <span>자료 발행일 (모르면 비움)</span>
          <input type="date" value={value.published_at} onChange={(e) => set("published_at", e.target.value)} />
        </label>
        <label className="dk-field">
          <span>원문 확인일</span>
          <input type="date" value={value.checked_at} onChange={(e) => set("checked_at", e.target.value)} />
        </label>
        <label className="dk-field">
          <span>사용 조건</span>
          <select value={value.rights_status} onChange={(e) => set("rights_status", e.target.value)}>
            {Object.entries(RIGHTS_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
        </label>
        <label className="dk-field">
          <span>사용 조건 메모</span>
          <input value={value.usage_terms} onChange={(e) => set("usage_terms", e.target.value)} placeholder="이용약관 위치·허락 범위" />
        </label>
        <label className="dk-field">
          <span>원출처 묶음 (같은 보도자료면 같은 이름)</span>
          <input value={value.origin_group} onChange={(e) => set("origin_group", e.target.value)} />
        </label>
        <label className="dk-field">
          <span>입력한 본문의 범위</span>
          <select value={value.depth} onChange={(e) => set("depth", e.target.value as SourceInput["depth"])}>
            <option value="excerpt">{DEPTH_LABEL.excerpt}</option>
            <option value="full_text">{DEPTH_LABEL.full_text}</option>
          </select>
        </label>
      </div>
      <label className="dk-field" style={{ marginTop: 10 }}>
        <span>원문·발췌 직접 입력 (서버가 URL 을 열지 않습니다 — 확인한 글을 그대로 붙여 넣으세요)</span>
        <textarea value={value.body_text} onChange={(e) => set("body_text", e.target.value)} rows={4} />
      </label>
      <label className="dk-field" style={{ marginTop: 8 }}>
        <span>발췌 위치 (쪽·문단·섹션)</span>
        <input value={value.excerpt_locator} onChange={(e) => set("excerpt_locator", e.target.value)} />
      </label>
      {urlOnly && (
        <p className="dk-warn" style={{ fontSize: 13 }}>
          본문 없이 URL 만 저장하면 “{DEPTH_LABEL.metadata_only}”으로 기록됩니다.
        </p>
      )}
    </div>
  );
}
