// 밈 제작(0066) — 화면 규칙·타입(순수). 값 import 없음(node --test).
// ★ 판정의 정본은 DB 함수(drinks_meme_blockers)와 engine/drinks_meme.py 다. 여기는 입력 칸을 제작안 모양으로 묶고 상태를 말로 바꾼다.
// ★ 숫자는 engine/config.py DRINKS_MEME_* 와 같아야 한다(tests/test_drinks_meme.py 가 대조).

export const MEME_MIN_SEC = 6;
export const MEME_MAX_SEC = 15;
export const MEME_BEAT_MS_PER_CHAR = 170;
export const MEME_BEAT_FLOOR_MS = 1800;
export const MEME_BEAT_MAX_MS = 8000;
export const MEME_PALETTES = ["amber", "wine", "night", "moss"] as const;

export type MemeFrame = "top_text" | "full_title";
export type MemeStatus = "text_requested" | "text_running" | "draft" | "approved" | "rendering" | "publish_waiting" | "manual_audio"
  | "posted_manual" | "published" | "stopped" | "failed" | "rejected";
export type MemeSound = "none" | "ambient_local" | "app_manual";

export const FRAME_LABEL: Record<MemeFrame, string> = {
  top_text: "① 검은 바탕 + 위쪽 글 한 줄 + 가운데 가로 장면",
  full_title: "② 세로 꽉 찬 장면 + 크고 굵은 제목",
};
export const SOUND_LABEL: Record<MemeSound, string> = {
  none: "음원 없음",
  ambient_local: "분위기 음원(코드로 합성, 박자 무관)",
  app_manual: "박자 맞춤 — 자동 게시 안 함, 앱에서 붙입니다",
};
export const MEME_STATUS_LABEL: Record<MemeStatus, string> = {
  text_requested: "글 초안 대기",
  text_running: "글 초안 쓰는 중",
  draft: "초안 — 승인 전",
  approved: "승인됨 — 제작 대기",
  rendering: "제작 중",
  publish_waiting: "게시 대기",
  manual_audio: "앱에서 음원 붙이기 대기(자동 게시 안 함)",
  posted_manual: "앱으로 게시됨",
  published: "게시됨(워커)",
  stopped: "멈춤",
  failed: "실패",
  rejected: "버림",
};

export interface MemeBeat { text: string; keyword: string; ms: number }
export interface MemeSpec {
  frame: MemeFrame;
  top_line: string;
  title_keyword: string;
  beats: MemeBeat[];
  caption: string;
  scene: { source: "text_bg"; palette: string };
  sync_grade: "sync_free" | "sync_required";
  audio: { mode: MemeSound; title?: string; artist?: string; audio_id?: string; start_hint_sec?: number };
  contains_info: boolean;
  claim_ids: string[];
}

export interface MemeFormInput {
  frame: MemeFrame;
  topLine: string;
  titleKeyword: string;
  /** 한 줄에 비트 하나. "글 | 3.5" 처럼 초를 적을 수 있다. *낱말* 은 강조색. */
  beatsText: string;
  caption: string;
  palette: string;
  sound: MemeSound;
  audioTitle: string;
  audioId: string;
  startHintSec: string;
  containsInfo: boolean;
  claimIds: string;
}

/** engine/drinks_meme.auto_beat_ms 와 같다. */
export function autoBeatMs(text: string): number {
  return Math.min(MEME_BEAT_MAX_MS, Math.max(MEME_BEAT_FLOOR_MS, text.length * MEME_BEAT_MS_PER_CHAR));
}

export function parseBeats(raw: string): MemeBeat[] {
  const out: MemeBeat[] = [];
  for (const line of raw.split("\n")) {
    const [body, sec] = line.split("|");
    const marked = (body ?? "").trim();
    if (!marked) continue;
    const kw = /\*([^*]+)\*/.exec(marked)?.[1] ?? "";
    const text = marked.replace(/\*/g, "");
    const s = Number(sec);
    out.push({ text, keyword: kw, ms: sec !== undefined && Number.isFinite(s) && s > 0 ? Math.round(s * 1000) : autoBeatMs(text) });
  }
  return out;
}

export function buildMemeSpec(f: MemeFormInput): MemeSpec {
  const manual = f.sound === "app_manual";
  const hint = Number(f.startHintSec);
  return {
    frame: f.frame,
    top_line: f.topLine.trim(),
    title_keyword: f.titleKeyword.trim(),
    beats: parseBeats(f.beatsText),
    caption: f.caption.trim(),
    scene: { source: "text_bg", palette: f.palette },
    sync_grade: manual ? "sync_required" : "sync_free",
    audio: manual
      ? { mode: "app_manual", title: f.audioTitle.trim(), ...(f.audioId.trim() ? { audio_id: f.audioId.trim() } : {}),
          ...(f.startHintSec.trim() !== "" && Number.isFinite(hint) ? { start_hint_sec: hint } : {}) }
      : { mode: f.sound },
    contains_info: f.containsInfo,
    claim_ids: f.containsInfo ? f.claimIds.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean) : [],
  };
}

export function memeTotalSec(beats: Pick<MemeBeat, "ms">[]): number {
  return beats.reduce((a, b) => a + b.ms, 0) / 1000;
}

/** 지금 운영자가 할 일 한 줄. */
export function memeNextStep(status: MemeStatus): string {
  switch (status) {
    case "draft": return "글과 소리를 확인하고 승인하세요. 승인해도 돈은 나가지 않습니다(로컬 렌더).";
    case "approved": return "제작 워커가 가져가길 기다립니다.";
    case "publish_waiting": return "완성본을 보세요. 발행 화면(/drinks/publish)의 '게시 대기 밈'에서 발행안을 만들어 승인·예약하면 워커가 올립니다.";
    case "published": return "워커가 인스타에 올렸습니다. 성과는 /drinks/analytics 에서 봅니다.";
    case "manual_audio": return "자동으로 올라가지 않습니다. 안내대로 앱에서 음원을 붙여 올린 뒤 링크를 등록하세요.";
    case "stopped": return "막힌 이유를 고치려면 초안으로 되돌리세요.";
    case "failed": return "초안으로 되돌려 다시 승인하세요.";
    default: return "";
  }
}

export function isMissingMemeTables(message: string | null | undefined): boolean {
  const m = message ?? "";
  return /drink_meme_/.test(m) && /does not exist|schema cache|not found|Could not find/i.test(m);
}

export interface MemeFileRow { role: string; storage_key: string; sha256: string; bytes: number; mime: string; width?: number | null; height?: number | null; duration_ms?: number | null }
export interface MemeBlocker { code: string; message: string }
export interface MemeDraftRow {
  id: string;
  card_id: string | null;
  topic_id: string | null;
  status: MemeStatus;
  spec: Partial<MemeSpec>;
  sync_grade: "sync_free" | "sync_required" | null;
  evidence_review_id: string | null;
  files: MemeFileRow[];
  guide: string | null;
  error_code: string | null;
  error_message: string | null;
  external_url: string | null;
  version: number;
  owner_name: string | null;
  blockers: MemeBlocker[];
}
export interface MemePickRow { topic_id: string; title: string | null; question: string | null }
export interface MemeBudgetRow { budget_id: string; stage: string; remaining_usd: number }
export interface MemeReviewOption { review_id: string; title: string | null; claims: { claim_id: string; text: string }[] }
