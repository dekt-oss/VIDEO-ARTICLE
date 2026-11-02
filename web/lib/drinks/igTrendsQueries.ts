// 인스타 트렌드 보드(0063) 읽기 — 서버 컴포넌트 전용(service key). 실패를 빈 목록으로 바꾸지 않는다.
// 0063 이 운영 DB 에 아직 없으면 'missing' — 0건이 아니라 "적용 전"이라고 따로 보여주기 위해 구분한다.
import { createAdminClient } from "@/lib/supabase/admin";
import { fetchAllPages, type PageResult } from "@/lib/drinks/paging";
import {
  isMissingIgTables, type IgAccountRow, type IgAudioRow, type IgCardRow, type IgLinkRow, type IgRunRow, type IgTokenRow,
} from "@/lib/drinks/igTrends";

export interface IgBoardView {
  runs: IgRunRow[];
  token: IgTokenRow | null;
  accounts: IgAccountRow[];
  cards: IgCardRow[];
  audio: IgAudioRow[];
  links: IgLinkRow[];
}

export type IgBoardLoaded =
  | { state: "ok"; data: IgBoardView }
  | { state: "missing" }
  | { state: "failed"; error: string }
  | { state: "unconfigured" };

const num = (x: unknown): number => (typeof x === "number" ? x : Number(x ?? 0));
const numOrNull = (x: unknown): number | null => (x === null || x === undefined ? null : Number(x));

export async function loadIgBoard(): Promise<IgBoardLoaded> {
  const db = createAdminClient();
  if (!db) return { state: "unconfigured" };
  const [runs, tokens, accounts, cards, audio, links] = await Promise.all([
    fetchAllPages<IgRunRow>((f, to) => db.from("drink_ig_trend_runs").select("*", { count: "exact" })
      .order("observed_on", { ascending: false }).order("source").range(f, to), "실행 기록"),
    fetchAllPages<IgTokenRow>((f, to) => db.from("drink_ig_token_checks").select("*", { count: "exact" })
      .order("checked_on", { ascending: false }).range(f, to), "토큰 기록"),
    fetchAllPages<IgAccountRow>((f, to) => db.from("drink_ig_watch_accounts").select("*", { count: "exact" })
      .order("username").range(f, to), "관찰 계정"),
    fetchAllPages<IgCardRow>((f, to) => db.from("drink_ig_board_cards").select("*", { count: "exact" })
      .order("first_seen_on", { ascending: false }).order("id").range(f, to), "밈 카드"),
    fetchAllPages<IgAudioRow>((f, to) => db.from("drink_ig_audio_latest").select("*", { count: "exact" })
      .order("list_position").order("audio_id").range(f, to), "인기 음원"),
    fetchAllPages<IgLinkRow>((f, to) => db.from("drink_ig_links").select("*", { count: "exact" })
      .order("created_at", { ascending: false }).order("id").range(f, to), "운영자 링크"),
  ]);
  const all: PageResult<unknown>[] = [runs, tokens, accounts, cards, audio, links];
  for (const r of all) {
    if (!r.ok) return isMissingIgTables(r.error) ? { state: "missing" } : { state: "failed", error: r.error };
  }
  const rows = <T,>(r: PageResult<T>): T[] => (r.ok ? r.rows : []);
  return {
    state: "ok",
    data: {
      runs: rows(runs).map((r) => ({ ...r, attempted: num(r.attempted), succeeded: num(r.succeeded), items: num(r.items) })),
      token: rows(tokens)[0] ?? null,
      accounts: rows(accounts).map((a) => ({ ...a, followers_count: numOrNull(a.followers_count) })),
      cards: rows(cards).map((c) => ({
        ...c, examples_count: num(c.examples_count), accounts_count: num(c.accounts_count), same_audio_cards: num(c.same_audio_cards),
        quiet_normal_days: num(c.quiet_normal_days), max_multiple: numOrNull(c.max_multiple), audio_position: numOrNull(c.audio_position),
        examples: (c.examples ?? []).map((e) => ({ ...e, view_count: numOrNull(e.view_count), view_multiple: numOrNull(e.view_multiple) })),
      })),
      audio: rows(audio).map((a) => ({ ...a, list_position: num(a.list_position) })),
      links: rows(links),
    },
  };
}
