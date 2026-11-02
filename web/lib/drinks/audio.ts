// 음원 전달 계약(기획 v2 §7-3, 0065) 순수 계산 — 화면이 보내는 값과 보여 주는 문장.
// ★ 판정의 정본은 DB(drinks_pub_audio_clean·drinks_pub_block)와 게시 워커(engine/drinks_publish.py)다.
// ★ 값 import 금지 — node --test 가 이 파일을 직접 읽는다.

/** 나레이션 없는 카드뉴스 릴스의 기본 볼륨(§7-4) — engine/config.py DRINKS_CARD_REEL_*_VOLUME 과 같아야 한다(tests/test_drinks_card_reel.py 가 대조). */
export const CARD_REEL_AUDIO_VOLUME = 90;
export const CARD_REEL_VIDEO_VOLUME = 10;

export type AudioMode = "ig_audio" | "licensed_mix" | "none";
export type SyncGrade = "sync_free" | "sync_required";

/** 발행 요청에 저장된 음원 묶음(서버가 만든다). */
export interface AudioBundle {
  mode: AudioMode;
  audio_id?: string | null;
  audio_type?: string | null;
  title_snapshot?: string | null;
  artist_snapshot?: string | null;
  audio_volume?: number | null;
  video_volume?: number | null;
  sync_grade?: SyncGrade | null;
}

/** 고를 수 있는 음원(drink_ig_audio_latest). */
export interface AudioOption {
  audio_id: string;
  audio_type: string;
  title: string | null;
  display_artist: string | null;
  duration_ms: number | null;
  preview_url: string | null;
  list_position: number | null;
}

export interface AudioChoice {
  audioId: string;
  audioVolume: number;
  videoVolume: number;
  syncGrade: SyncGrade;
}

/** 화면 선택 → 서버로 보낼 값. 제목·가수는 보내지 않는다(서버가 음원 표에서 복사한다). */
export function audioPayload(c: AudioChoice): Record<string, unknown> {
  return { mode: "ig_audio", audio_id: c.audioId, audio_volume: c.audioVolume, video_volume: c.videoVolume, sync_grade: c.syncGrade };
}

export function audioSummary(a: AudioBundle | null | undefined): string {
  if (!a || a.mode === "none") return "음원 없음";
  if (a.mode === "licensed_mix") return "영상에 라이선스 음악이 깔려 있음";
  const name = [a.title_snapshot ?? a.audio_id, a.artist_snapshot].filter(Boolean).join(" — ");
  return `${name} · 음원 ${a.audio_volume} / 영상 ${a.video_volume}${a.sync_grade === "sync_required" ? " · 박자 맞춤(자동 게시 안 됨)" : ""}`;
}

const AUDIO_BLOCK_KO: Record<string, string> = {
  audio_missing: "음원을 고르지 않았습니다(카드뉴스 릴스는 음원 필수)",
  audio_connection_unsupported: "인스타 음원은 Facebook 로그인 연결 계정으로만 붙입니다",
  audio_sync_required: "박자를 맞춰야 하는 편이라 자동 게시하지 않습니다",
  // 0068
  ai_label_missing: "캡션에 'AI 생성 영상' 한 줄이 없습니다(설명형·산 장면 밈 필수)",
  meme_not_publishable: "밈 제작안이 게시 대기 상태가 아닙니다(되돌림·버림·박자 맞춤)",
  audio_mismatch: "밈 제작안이 정한 음원과 다른 음원입니다",
};

export function pubBlockLabel(code: string): string {
  return AUDIO_BLOCK_KO[code] ?? code;
}
