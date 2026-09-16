"use client";

// ⑤ 단계 발주 바 — 버전(만화식/웹툰) × 언어(KO/EN) 를 체크해서 **한 번에** 발주한다.
//
// 왜 이 화면에 있나: 이 저장소에서 "지시서 생성"과 "승인 → 렌더"는 같은 화면의 두 상태다.
// 지시서가 없으면 생성, 있으면 승인. 그래서 버전별 상태에 따라 두 동작이 한 제출로 섞인다.
//
// 왜 DirectiveClient 를 다중 지시서로 만들지 않았나: 그 컴포넌트는 지시서 1건의 편집 상태
// (cuts/dirty/saving/locked/serverIdRef)로 짜여 있어 N개를 들면 저장 충돌 표면이 그만큼 늘어난다.
// 여기서는 발주만 소유하고, 편집은 버전 탭 뒤에서 한 번에 하나만 마운트한다.
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { Directive, DirectiveStatus, VersionType } from "@/lib/types";
import { VERSION_META, DEFAULT_VERSION_KEY } from "@/lib/versions";
import { estimateOrder, formatUsd, LANG_COST_NOTE } from "@/lib/orderCost";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import { apiErrorText } from "@/lib/apiError";
// 승인 차단 사유 표시 문자열 — DirectiveClient 와 같은 표를 쓴다.
import { blockLabel } from "@/lib/blockLabels";

const LANGS: { key: string; label: string }[] = [
  { key: "ko", label: "한국어" },
  { key: "en", label: "English" },
];

// 지시서 생성 폴링 — useGeneration 과 같은 간격/타임아웃. 여기는 버전 여러 개를 동시에 본다.
const GEN_POLL_MS = 4000;
const GEN_TIMEOUT_MS = 360_000;

function versionLabel(key: VersionType): string {
  return VERSION_META.find((m) => m.key === key)?.label ?? key;
}

const STATUS_LABEL: Record<DirectiveStatus, string> = {
  draft: "검수 필요",
  approved: "승인됨",
  rendering: "렌더 중",
  rendered: "렌더 완료",
  failed: "실패",
};

export interface VersionSlot {
  key: VersionType;
  directive: Directive | null;
}

/** 버전별로 이번 제출이 무엇을 할지. UI 와 제출 로직이 같은 판단을 쓰도록 한 곳에서 정한다. */
type Action = "generate" | "approve" | "none";

function actionFor(slot: VersionSlot): Action {
  if (!slot.directive) return "generate";
  return slot.directive.status === "draft" ? "approve" : "none";
}

export default function VersionOrderBar({
  paperId,
  slots,
  disabled = false,
}: {
  paperId: string;
  slots: VersionSlot[];
  disabled?: boolean;
}) {
  const router = useRouter();
  const toast = useToast();

  // ★ 기본은 **만화식 하나만** 체크(2026-08-20 운영자 요청 — "내가 체크해서 진행하게").
  //   예전에는 제공 버전 전부를 체크해 뒀다(비교가 목적이었다). 그런데 버전이 2개에서 3개로
  //   늘면서, 아무것도 손대지 않고 [선택한 버전 만들기]를 누르면 지시서 3벌이 생성되고 이미
  //   초안이 있던 버전은 곧바로 승인 → 렌더(=비용)까지 갔다. 비교하려면 체크를 늘리면 된다.
  const [versions, setVersions] = useState<Set<VersionType>>(
    () => new Set<VersionType>([DEFAULT_VERSION_KEY]),
  );
  const [langs, setLangs] = useState<Set<string>>(() => new Set(["ko", "en"]));
  const [showConfirm, setShowConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  // 발주한 지시서 생성이 끝날 때까지 이 화면에서 보여 줄 진행 상태. 예전에는 발주 직후 곧바로
  // router.refresh() 만 해서, 아직 만들어지지 않은 화면이 그대로 다시 그려졌다 —
  // 운영자 눈에는 "눌렀는데 아무 일도 안 일어남"이었다(생성에는 약 1분이 걸린다).
  const [genVersions, setGenVersions] = useState<VersionType[]>([]);
  const [genSec, setGenSec] = useState(0);
  // 승인이 차단됐을 때의 2차 확인(강제 승인). ⑤ 단계에서는 이 바가 유일한 승인 창구라,
  // 여기서 막고 끝내면 series_split_required 처럼 화면에서 풀 수 없는 사유는 출구가 없다.
  const [blocked, setBlocked] = useState<{ ids: string[]; reasons: string[] } | null>(null);

  const chosen = useMemo(() => slots.filter((s) => versions.has(s.key)), [slots, versions]);
  const toGenerate = chosen.filter((s) => actionFor(s) === "generate");
  const toApprove = chosen.filter((s) => actionFor(s) === "approve");
  const langList = useMemo(() => LANGS.map((l) => l.key).filter((k) => langs.has(k)), [langs]);

  const estimate = useMemo(
    () => estimateOrder(toApprove.map((s) => ({ key: s.key, directive: s.directive })), langList),
    [toApprove, langList],
  );

  const nothingToDo = toGenerate.length === 0 && toApprove.length === 0;
  const noLang = langList.length === 0;

  function toggle<T>(set: Set<T>, value: T, apply: (next: Set<T>) => void) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    apply(next);
  }

  /** 발주한 버전들의 지시서가 생길 때까지 폴링한다. 끝나면 화면을 갱신한다. */
  async function waitForDirectives(keys: VersionType[]) {
    setGenVersions(keys);
    setGenSec(0);
    const started = Date.now();
    const tick = setInterval(() => setGenSec(Math.floor((Date.now() - started) / 1000)), 1000);
    const pending = new Set(keys);
    try {
      while (pending.size > 0 && Date.now() - started < GEN_TIMEOUT_MS) {
        await new Promise((r) => setTimeout(r, GEN_POLL_MS));
        for (const key of [...pending]) {
          let s: { has_directive?: boolean; status?: string; error?: string } | null = null;
          try {
            const res = await fetch(
              `/api/directive-status?paper_id=${encodeURIComponent(paperId)}&version_type=${key}`,
            );
            if (res.ok) s = await res.json();
          } catch {
            continue; // 일시 오류는 다음 폴로
          }
          if (!s) continue;
          if (s.has_directive) {
            pending.delete(key);
            setGenVersions([...pending]);
            toast.show(`${versionLabel(key)} 지시서가 생성되었습니다.`, "ok");
            router.refresh();
          } else if (s.status === "error") {
            pending.delete(key);
            setGenVersions([...pending]);
            toast.show(`${versionLabel(key)} 생성 실패 — ${s.error ?? "사유 미기록"}`, "err");
          }
        }
      }
      if (pending.size > 0) {
        toast.show(
          `${[...pending].map(versionLabel).join(", ")} 생성이 지연되고 있습니다. 잠시 후 새로고침해 확인하세요.`,
          "err",
        );
      }
    } finally {
      clearInterval(tick);
      setGenVersions([]);
      router.refresh();
    }
  }

  /** 승인 → 렌더. force=true 는 차단 사유를 사람이 확인한 뒤에만 붙는다(서버 로그에 남는다). */
  async function approveDirectives(ids: string[], force: boolean): Promise<string[]> {
    const notes: string[] = [];
    const res = await fetch("/api/directive-approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directive_ids: ids, langs: langList, force }),
    });
    const j = await res.json().catch(() => null);
    if (!res.ok && !(res.status === 409 && (j?.results ?? []).length > 0)) {
      toast.show(apiErrorText(j, res.status, "지시서를 승인"), "err");
      return notes;
    }
    const blockedIds: string[] = [];
    const blockedReasons = new Set<string>();
    for (const r of j?.results ?? []) {
      const label = r.version_type ?? r.directive_id;
      if (r.blocked?.length) {
        notes.push(`${label}: 차단 — ${r.blocked.map(blockLabel).join(", ")}`);
        blockedIds.push(r.directive_id);
        for (const code of r.blocked) blockedReasons.add(code);
      } else if (r.error) {
        notes.push(`${label}: 실패 — ${r.error}`);
      } else {
        notes.push(`${label}: 렌더 잡 ${r.queued}건 적재`);
      }
    }
    if (j?.rendering === false) notes.push("워커 자동 트리거 없음 — ⑥에서 수동 실행");
    // 차단으로 끝내지 않는다 — 무엇에 걸렸는지 보여주고 그래도 진행할지 사람이 정한다.
    if (blockedIds.length > 0) setBlocked({ ids: blockedIds, reasons: [...blockedReasons] });
    return notes;
  }

  async function submit() {
    setBusy(true);
    const notes: string[] = [];
    const generating = toGenerate.map((s) => s.key);
    try {
      // ① 지시서가 없는 버전부터 발주한다. 생성은 비동기라 승인은 다음 라운드에서 한다.
      if (toGenerate.length > 0) {
        const res = await fetch("/api/directive-generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paper_id: paperId, version_types: generating }),
        });
        const j = await res.json().catch(() => null);
        if (!res.ok) {
          toast.show(apiErrorText(j, res.status, "지시서를 생성"), "err");
          generating.length = 0;
        } else {
          const warned = (j?.results ?? []).filter((r: { warn?: string }) => r.warn);
          notes.push(`지시서 생성 발주 ${toGenerate.length}건`);
          for (const w of warned) notes.push(`${w.version_type}: ${w.warn}`);
        }
      }

      // ② 이미 초안 지시서가 있는 버전은 승인 → 렌더 큐로.
      if (toApprove.length > 0) {
        notes.push(...(await approveDirectives(toApprove.map((s) => s.directive!.id), false)));
      }
      if (notes.length > 0) toast.show(notes.join(" · "), "ok");
      router.refresh();
    } finally {
      setBusy(false);
      setShowConfirm(false);
    }
    // ③ 생성은 약 1분이 걸린다 — 끝날 때까지 지켜보다가 화면을 갱신한다.
    if (generating.length > 0) await waitForDirectives(generating);
  }

  const summary = [
    toGenerate.length > 0 ? `지시서 생성 ${toGenerate.length}건` : null,
    toApprove.length > 0 ? `승인 → 렌더 ${estimate.renderJobCount}건` : null,
  ].filter(Boolean).join(" · ") || "선택된 작업 없음";

  return (
    <div className="section">
      <h3>버전 · 언어 선택</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
        체크한 버전만 만듭니다(기본 = 만화식 하나). 나란히 비교하려면 다른 버전도 체크하세요 —
        버전을 늘린 만큼 비용이 늡니다. 언어는 늘려도 이미지·클립을 공유해 추가 비용이 없습니다.
      </p>

      <div className="toggle" style={{ flexWrap: "wrap", gap: 8 }}>
        {slots.map((s) => {
          const action = actionFor(s);
          const status = s.directive?.status;
          const meta = VERSION_META.find((m) => m.key === s.key);
          return (
            <label key={s.key} className="check-chip" title={meta?.hint}>
              <input
                type="checkbox"
                checked={versions.has(s.key)}
                disabled={disabled || busy}
                onChange={() => toggle(versions, s.key, setVersions)}
              />
              <span>{meta?.label ?? s.key}</span>
              {status && <span className="muted"> · {STATUS_LABEL[status]}</span>}
              {action === "generate" && <span className="muted"> · 미생성</span>}
            </label>
          );
        })}
      </div>

      <div className="toggle" style={{ flexWrap: "wrap", gap: 8, marginTop: 8 }}>
        {LANGS.map((l) => (
          <label key={l.key} className="check-chip">
            <input
              type="checkbox"
              checked={langs.has(l.key)}
              disabled={disabled || busy}
              onChange={() => toggle(langs, l.key, setLangs)}
            />
            <span>{l.label}</span>
          </label>
        ))}
      </div>

      <p className="muted" style={{ marginTop: 10, fontSize: 13 }}>
        {summary}
        {toApprove.length > 0 && ` · 예상 생성비 ${formatUsd(estimate.total)}`}
        {estimate.unknown.length > 0 && " (지시서 없는 버전은 산정 제외)"}
      </p>

      {genVersions.length > 0 && (
        <div className="gen-progress">
          <span className="spinner" />
          <span>
            {genVersions.map(versionLabel).join(", ")} 지시서 생성 중… · {genSec}s 경과
            {" (약 1분 걸립니다 — 이 화면을 그대로 두세요)"}
          </span>
        </div>
      )}

      <button
        className="btn pick"
        onClick={() => setShowConfirm(true)}
        disabled={
          disabled || busy || genVersions.length > 0 || nothingToDo ||
          (toApprove.length > 0 && noLang)
        }
      >
        {busy ? "처리 중…" : genVersions.length > 0 ? "생성 중…" : "선택한 버전 만들기"}
      </button>
      {noLang && toApprove.length > 0 && (
        <span className="muted" style={{ marginLeft: 8 }}>언어를 하나 이상 선택하세요</span>
      )}

      <ConfirmModal
        open={showConfirm}
        title="버전 · 언어 발주"
        busy={busy}
        confirmLabel="발주"
        message={
          (toGenerate.length > 0
            ? `[지시서 생성]\n${toGenerate.map((s) => `· ${VERSION_META.find((m) => m.key === s.key)?.label ?? s.key}`).join("\n")}\n\n`
            : "") +
          (toApprove.length > 0
            ? `[승인 → 렌더]\n` +
              estimate.perVersion.map((line) => {
                const label = VERSION_META.find((m) => m.key === line.key)?.label ?? line.key;
                if (line.usd === null) return `· ${label}: 비용 산정 불가`;
                // 등급제 버전이면 **어디에 투자했는지**를 같이 보여 준다. 총액만으로는
                // 등급표를 고칠 근거가 안 된다(운영자 확정: 비용을 보고 조절한다).
                const tierNote = line.tiers
                  ? ` · 투자 ${line.tiers.invest ?? 0}컷`
                  : "";
                return `· ${label}: 고유 에셋 ${line.uniqueAssets}개 · I2V ${line.videoClips}개(${line.videoSec}초)${tierNote} · ${formatUsd(line.usd)}`;
              }).join("\n") +
              `\n\n· 렌더 언어: ${langList.join(", ")} → 렌더 잡 ${estimate.renderJobCount}건` +
              `\n· ${LANG_COST_NOTE}` +
              `\n· 예상 생성비 합계: ${formatUsd(estimate.total)}\n\n` +
              `승인하면 렌더가 시작되고 비용이 발생합니다.`
            : "")
        }
        onConfirm={submit}
        onCancel={() => setShowConfirm(false)}
      />

      <ConfirmModal
        open={blocked !== null}
        title="승인이 차단되었습니다"
        danger
        busy={busy}
        confirmLabel="사유를 확인했고 그대로 렌더"
        message={
          `⛔ 차단 사유\n${(blocked?.reasons ?? []).map((r) => `· ${blockLabel(r)}`).join("\n")}\n\n` +
          "원칙은 [지시서 재생성]입니다 — 다시 만들면 대부분의 사유가 풀립니다.\n" +
          "다만 '시리즈로 분할'처럼 이 화면에서 풀 수 없는 사유도 있습니다(2편 분할 기능은 아직 없음).\n" +
          "그대로 진행하면 렌더가 시작되고 비용이 발생합니다. 우회 기록은 서버 로그에 남습니다."
        }
        onCancel={() => setBlocked(null)}
        onConfirm={async () => {
          const ids = blocked?.ids ?? [];
          setBlocked(null);
          if (ids.length === 0) return;
          setBusy(true);
          try {
            const notes = await approveDirectives(ids, true);
            if (notes.length > 0) toast.show(notes.join(" · "), "ok");
            router.refresh();
          } finally {
            setBusy(false);
          }
        }}
      />
    </div>
  );
}
