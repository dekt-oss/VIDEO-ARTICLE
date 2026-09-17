"use client";

// 유튜브 업로드용 제목(한/영) — 인라인 편집 + 복사. 초안 생성 LLM 이 자극적 제목을 산출하고,
// 여기서 사람이 다듬어 저장한다(drafts.upload_title_ko/en, /api/draft-update). 게시 시 제목란에 붙여넣는다.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { decideReseed, afterSave, type ReseedState } from "@/lib/work/reseed";
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
  const router = useRouter();
  const [ko, setKo] = useState(initialKo ?? "");
  const [en, setEn] = useState(initialEn ?? "");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  // ★ 되살리기 규칙은 lib/work/reseed 가 진다(검사로 못박음). 여기서 직접 조건을 쓰지 않는다.
  //
  // ★★ 원래 버그(2026-09-17 운영자 보고 "저장했는데 원래 제목 그대로 됩니다"):
  //   deps 에 `dirty` 가 들어 있어서, 저장 성공으로 dirty 가 false 가 되는 **그 순간** effect 가
  //   다시 돌았다. 그때 props 는 아직 서버를 다시 읽기 전이라 옛 제목이었고, 그 값으로 덮어썼다.
  //   저장은 됐는데 화면이 "안 됐다"고 거짓말을 한 것이다.
  //   → deps 에서 dirty 를 뺐고, 저장한 값을 앞당겨 기억한 뒤 서버가 따라올 때까지 무시한다.
  const stateRef = useRef<ReseedState<{ ko: string; en: string }>>({
    known: { ko: initialKo ?? "", en: initialEn ?? "" },
    awaitingServer: false,
  });
  const dirtyRef = useRef(false);
  useEffect(() => {
    const incoming = { ko: initialKo ?? "", en: initialEn ?? "" };
    const r = decideReseed(incoming, stateRef.current, dirtyRef.current,
                           (a, b) => a.ko === b.ko && a.en === b.en);
    stateRef.current = { known: r.known, awaitingServer: r.awaitingServer };
    if (r.reseed) {
      setKo(r.known.ko);
      setEn(r.known.en);
    }
  }, [initialKo, initialEn]);

  function markDirty(v: boolean) {
    dirtyRef.current = v;
    setDirty(v);
  }

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
      // 저장한 값을 **앞당겨** 기억하고 서버가 따라올 때까지 들어오는 props 를 무시한다.
      stateRef.current = afterSave({ ko, en });
      markDirty(false);
      toast.show("발행 제목을 저장했습니다.", "ok");
      router.refresh();   // 서버 props 가 따라오게 — 그래야 대기가 풀린다

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
          markDirty(true);
        }}
      />
    </div>
  );

  return (
    <div className="section">
      <h3>발행용 제목 (유튜브 업로드)</h3>
      <p className="muted">
        ✏️ <b>아래 칸을 직접 고칠 수 있습니다.</b> 고치면 [제목 저장]이 켜집니다.
        업로드 시 제목란에 붙여넣으세요. 초안 생성 시 자동 작성됩니다.
      </p>
      {row("한국어", ko, setKo, "ko", fallback ? `예: ${fallback}` : "자극적 한국어 제목")}
      {row("English", en, setEn, "en", "punchy English title")}
      {/* ★ 버튼을 dirty 일 때만 보여 줬더니 운영자가 "수정하는 게 없다"고 읽었다(2026-09-17).
          칸은 원래 편집 가능했는데 저장 수단이 안 보이니 읽기 전용으로 보인 것이다.
          이제 항상 두고, 고친 것이 없으면 비활성으로 둔다. */}
      <button className="btn pick" style={{ marginTop: 10 }} onClick={save} disabled={saving || !dirty}>
        {saving ? "저장 중…" : dirty ? "제목 저장" : "제목 저장 (고친 내용 없음)"}
        {dirty && <span className="dirty-dot" />}
      </button>
    </div>
  );
}
