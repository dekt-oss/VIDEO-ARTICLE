"use client";

// 유튜브 업로드용 제목(한/영) — 인라인 편집 + 복사. 초안 생성 LLM 이 자극적 제목을 산출하고,
// 여기서 사람이 다듬어 저장한다(drafts.upload_title_ko/en, /api/draft-update). 게시 시 제목란에 붙여넣는다.
import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { apiErrorText } from "@/lib/apiError";

export default function PublishTitles({
  paperId,
  initialKo,
  initialEn,
  fallback,
}: {
  paperId: string;
  initialKo: string | null;
  initialEn: string | null;
  fallback?: string | null; // 제목이 비었을 때 참고용(논문 제목) — 저장값은 아님
}) {
  const toast = useToast();
  const [ko, setKo] = useState(initialKo ?? "");
  const [en, setEn] = useState(initialEn ?? "");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  // 서버값이 실제로 바뀐 경우에만(그리고 미저장 편집이 없을 때만) 반영 — ReviewClient 패턴과 동일.
  const serverRef = useRef({ ko: initialKo ?? "", en: initialEn ?? "" });
  useEffect(() => {
    const nk = initialKo ?? "";
    const ne = initialEn ?? "";
    if (nk !== serverRef.current.ko || ne !== serverRef.current.en) {
      serverRef.current = { ko: nk, en: ne };
      if (!dirty) {
        setKo(nk);
        setEn(ne);
      }
    }
  }, [initialKo, initialEn, dirty]);

  async function copy(text: string, which: string) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      toast.show("복사 실패 — 텍스트를 직접 선택해 복사하세요", "err");
    }
  }

  async function save() {
    setSaving(true);
    const res = await fetch("/api/draft-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, upload_title_ko: ko, upload_title_en: en }),
    });
    setSaving(false);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      serverRef.current = { ko, en };
      setDirty(false);
      toast.show("발행 제목을 저장했습니다.", "ok");
    } else {
      toast.show(apiErrorText(e, res.status, "제목을 저장"), "err");
    }
  }

  const row = (label: string, val: string, onChange: (v: string) => void, key: string, placeholder: string) => (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <b>{label}</b>
        <button className="btn" onClick={() => copy(val, key)} disabled={!val}>
          {copied === key ? "복사됨 ✓" : "복사"}
        </button>
      </div>
      <input
        className="search"
        style={{ width: "100%", marginTop: 6 }}
        value={val}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setDirty(true);
        }}
      />
    </div>
  );

  return (
    <div className="section">
      <h3>발행용 제목 (유튜브 업로드)</h3>
      <p className="muted">
        업로드 시 제목란에 붙여넣으세요. 자극적 훅으로 초안 생성 시 자동 작성됩니다 — 필요하면 여기서 직접 다듬어 저장하세요.
      </p>
      {row("한국어", ko, setKo, "ko", fallback ? `예: ${fallback}` : "자극적 한국어 제목")}
      {row("English", en, setEn, "en", "punchy English title")}
      {dirty && (
        <button className="btn pick" style={{ marginTop: 10 }} onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "제목 저장"}
          <span className="dirty-dot" />
        </button>
      )}
    </div>
  );
}
