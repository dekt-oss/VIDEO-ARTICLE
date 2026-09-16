"use client";

// 숏츠 발행 캡션(설명란) — KO/EN 각각 표시 + 복사. 게시 시 이 텍스트를 설명란에 붙여넣는다.
import { useState } from "react";

export default function PublishCaption({ captionKo, captionEn }: {
  captionKo: string;
  captionEn: string;
}) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(text: string, which: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  if (!captionKo && !captionEn) return null;

  const block = (label: string, text: string, key: string) =>
    text ? (
      <div style={{ marginTop: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <b>{label}</b>
          <button className="btn" onClick={() => copy(text, key)}>
            {copied === key ? "복사됨 ✓" : "복사"}
          </button>
        </div>
        <pre style={{ whiteSpace: "pre-wrap", lineHeight: 1.6, marginTop: 6,
                      background: "var(--card)", color: "var(--text)",
                      border: "1px solid var(--border)", padding: 12, borderRadius: 8 }}>
          {text}
        </pre>
      </div>
    ) : null;

  return (
    <div className="section">
      <h3>숏츠 발행 캡션(설명란)</h3>
      <p className="muted">게시할 때 이 텍스트를 설명란에 붙여넣으세요. 출처·링크·해시태그 포함.</p>
      {block("한국어", captionKo, "ko")}
      {block("English", captionEn, "en")}
    </div>
  );
}
