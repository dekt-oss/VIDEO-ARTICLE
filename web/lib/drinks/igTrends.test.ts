// 밈 보드 화면 규칙 순수 테스트 — 정상 관측일·동결·토큰 경고·음원 표기·카드 묶기·릴스 링크 해석.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  boardHealth, groupCards, isMissingIgTables, isNormalDay, isoToday, latestRuns, positionLabel, reasonsText, sortAudio, tokenView, noteAfterUse,
  type IgRunRow, type IgTokenRow,
} from "./igTrends.ts";
import { DRINKS_ACTIONS, parseIgReelLink, runDrinksAction } from "./actions.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const TODAY = "2026-11-10";
const NOW = Date.parse("2026-11-10T00:00:00+09:00");

const ago = (n: number): string => new Date(Date.parse(`${TODAY}T00:00:00Z`) - n * 86_400_000).toISOString().slice(0, 10);
function run(source: IgRunRow["source"], observed_on: string, status: IgRunRow["status"], attempted = 8, succeeded = attempted): IgRunRow {
  return { source, observed_on, status, attempted, succeeded, items: status === "ok" ? 10 : 0, failure_reasons: null, excluded_no_views: null, detail: null, finished_at: `${observed_on}T00:00:00Z` };
}
const normal = (d: string): IgRunRow[] => [run("t1", d, "ok"), run("t2", d, "ok", 10, 10)];
const failed = (d: string): IgRunRow[] => [run("t1", d, "failed", 2, 0), run("t2", d, "failed", 10, 0)];

test("정상 관측일: T1 ok + T2 성공률 80% 이상. 활성 계정 0개는 정상이 아니다", () => {
  assert.equal(isNormalDay({ status: "ok" }, { attempted: 10, succeeded: 8 }), true);
  assert.equal(isNormalDay({ status: "ok" }, { attempted: 10, succeeded: 7 }), false);
  assert.equal(isNormalDay({ status: "partial" }, { attempted: 10, succeeded: 10 }), false);
  assert.equal(isNormalDay({ status: "ok_empty" }, { attempted: 10, succeeded: 10 }), false);
  assert.equal(isNormalDay({ status: "ok" }, { attempted: 0, succeeded: 0 }), false);
  assert.equal(isNormalDay(undefined, { attempted: 1, succeeded: 1 }), false);
});

test("기록이 없으면 끊긴 것이 아니라 시작 전이다", () => {
  const h = boardHealth([], TODAY, 3);
  assert.equal(h.neverRun, true);
  assert.equal(h.frozen, false);
  assert.deepEqual(h.scope, { succeeded: 0, listed: 3, on: null });
});

test("관찰 범위·마지막 정상 관측일·최근 7일 정상 관측 수", () => {
  const rows = [...normal(ago(8)), ...normal(ago(6)), ...failed(ago(1)), run("t1", TODAY, "ok"), run("t2", TODAY, "partial", 10, 9)];
  const h = boardHealth(rows, TODAY, 12);
  assert.deepEqual(h.scope, { succeeded: 9, listed: 10, on: TODAY }, "목록 수는 그날 실제로 시도한 수");
  assert.equal(h.lastNormalDay, TODAY);
  assert.equal(h.normalLast7, 2, "8일 전은 창 밖");
  assert.equal(h.frozen, false);
});

test("not_run 인 날의 관찰 범위는 성공 0 / 현재 목록 수로 보여 준다", () => {
  const h = boardHealth([run("t1", TODAY, "not_run", 0, 0), run("t2", TODAY, "not_run", 0, 0)], TODAY, 5);
  assert.deepEqual(h.scope, { succeeded: 0, listed: 5, on: TODAY });
});

test("정상 관측일이 3일 이상 끊기면 동결: 실패·안 돌아서 기록 없음·80% 미만 모두 센다", () => {
  assert.equal(boardHealth([...normal(ago(2)), ...failed(ago(1)), ...failed(TODAY)], TODAY, 1).frozen, false);
  const three = boardHealth([...normal(ago(3)), ...failed(ago(2)), ...failed(ago(1)), run("t1", TODAY, "ok"), run("t2", TODAY, "partial", 10, 7)], TODAY, 1);
  assert.equal(three.frozen, true);
  assert.equal(three.missingStreak, 3);
  assert.equal(three.lastNormalDay, ago(3));
  // 워크플로가 아예 안 돌아 기록이 없는 날도 끊긴 날이다 - 다음 실행이 채우기 전에 화면이 먼저 안다
  assert.equal(boardHealth(normal(ago(5)), TODAY, 1).frozen, true);
  assert.equal(boardHealth(normal(ago(5)), TODAY, 1).missingStreak, 4, "오늘은 아직 실행 전일 수 있어 세지 않는다");
});

test("정상 관측일이 돌아오면 동결이 풀린다", () => {
  assert.equal(boardHealth([...normal(ago(5)), ...failed(ago(1)), ...normal(TODAY)], TODAY, 1).frozen, false);
});

test("T4 는 정상 관측일 계산에 들어가지 않는다", () => {
  const h = boardHealth([...normal(TODAY), run("t4", ago(1), "ok")], TODAY, 1);
  assert.equal(h.lastNormalDay, TODAY);
  assert.equal(h.missingStreak, 0);
});

test("수집원별 최근 기록·실패 사유 문장", () => {
  const l = latestRuns([...failed(ago(1)), ...normal(ago(2))]);
  assert.equal(l.t1?.status, "failed");
  assert.equal(reasonsText({ token_expired: 2, invalid_user: 1, zero: 0 }), "토큰 만료 2 · 계정을 못 찾음(개인 계정·없는 이름) 1");
  assert.equal(reasonsText(null), "");
});

const token = (o: Partial<IgTokenRow>): IgTokenRow => ({ checked_on: TODAY, status: "ok", expires_at: null, data_access_expires_at: null, error_code: null, ...o });
const inDays = (n: number) => new Date(NOW + n * 86_400_000 + 3_600_000).toISOString();

test("토큰 경고는 만료 14일 전부터, 만료·없음은 막힘으로", () => {
  assert.equal(tokenView(null, NOW).level, "none");
  assert.equal(tokenView(token({ expires_at: inDays(14) }), NOW).level, "ok");
  const w = tokenView(token({ expires_at: inDays(13) }), NOW);
  assert.equal(w.level, "warn");
  assert.equal(w.daysLeft, 13);
  assert.match(w.text, /13일/);
  assert.equal(tokenView(token({ status: "expired" }), NOW).level, "bad");
  assert.equal(tokenView(token({ status: "missing" }), NOW).level, "bad");
  assert.equal(tokenView(token({ expires_at: inDays(-2) }), NOW).level, "bad", "기록 뒤에 만료된 경우도");
  assert.equal(tokenView(token({ status: "unavailable", error_code: "network" }), NOW).level, "warn");
  assert.equal(tokenView(token({ expires_at: null }), NOW).level, "ok", "만료 없음");
});

test("음원 표기: 우리 계정 기준 목록 자리. 오늘 것이 아니면 날짜를 적는다", () => {
  assert.equal(positionLabel(7, TODAY, TODAY), "목록 7번째(우리 계정 기준, 오늘)");
  assert.equal(positionLabel(7, ago(1), TODAY), `목록 7번째(우리 계정 기준, ${ago(1)} 관측)`);
});

test("화면 어디에도 '인스타 전체 순위' 라는 말을 쓰지 않는다", () => {
  for (const rel of ["../../app/drinks/memes/page.tsx", "./igTrends.ts", "../../components/drinks/MemeBoardControls.tsx"]) {
    const src = readFileSync(join(HERE, rel), "utf8");
    assert.ok(!/인스타\s*전체\s*순위|전체 인기 순위|인기 순위/.test(src), rel);
  }
});

test("오르는 음원이 앞, 그 안에서는 목록 자리 순", () => {
  const rows = [
    { audio_id: "a", rising_reason: null, list_position: 1 },
    { audio_id: "b", rising_reason: "new", list_position: 9 },
    { audio_id: "c", rising_reason: "three_days", list_position: 3 },
  ] as const;
  assert.deepEqual(sortAudio(rows).map((r) => r.audio_id), ["c", "b", "a"]);
});

const cardRow = (o: Record<string, unknown>) => ({ id: "x", decision: null, state: "new", archived_on: null, first_seen_on: "2026-11-01", ...o }) as never;

test("카드 묶기: 결정별로 나누고, 쓰자는 식어도 쓰자에 남는다", () => {
  const g = groupCards([
    cardRow({ id: "1" }), cardRow({ id: "2", decision: "use", state: "cooled", archived_on: TODAY }), cardRow({ id: "3", decision: "pass" }),
    cardRow({ id: "4", decision: "later" }), cardRow({ id: "5", state: "cooled", archived_on: TODAY }), cardRow({ id: "6", state: "rising" }),
  ]);
  const ids = (r: { id: string }[]) => r.map((c) => c.id);
  assert.deepEqual(ids(g.undecided), ["6", "1"], "오르는 중이 앞");
  assert.deepEqual(ids(g.use), ["2"]);
  assert.deepEqual(ids(g.pass), ["3"]);
  assert.deepEqual(ids(g.later), ["4"]);
  assert.deepEqual(ids(g.archived), ["5"]);
});

test("[쓰자] 문장: 참고 카드·정밀 틀을 말하고, 돈이 안 나갔다고 말하고, 식었으면 다시 판단하라고 한다", () => {
  assert.match(noteAfterUse({ precision: "reference", state: "new" }), /참고 카드.*돈은 나가지 않았습니다/);
  assert.match(noteAfterUse({ precision: "precise", state: "peak" }), /정밀 틀.*돈은 나가지 않았습니다/);
  assert.match(noteAfterUse({ precision: "reference", state: "cooled" }), /^식었음/);
});

test("0063 미적용 판별: 0건과 구별한다", () => {
  assert.equal(isMissingIgTables("실행 기록: Could not find the table 'public.drink_ig_trend_runs' in the schema cache"), true);
  assert.equal(isMissingIgTables(`밈 카드: relation "public.drink_ig_board_cards" does not exist`), true);
  assert.equal(isMissingIgTables("밈 카드: permission denied for view drink_ig_board_cards"), false, "권한 오류는 미적용이 아니다");
  assert.equal(isMissingIgTables("timeout"), false);
  assert.equal(isMissingIgTables(null), false);
});

test("KST 오늘 날짜", () => {
  assert.equal(isoToday(Date.parse("2026-11-09T15:00:00Z")), "2026-11-10");
  assert.equal(isoToday(Date.parse("2026-11-09T14:59:59Z")), "2026-11-09");
});

test("릴스 링크 해석: 코드와 계정만 꺼내고 추적값을 버린다", () => {
  assert.deepEqual(parseIgReelLink("https://www.instagram.com/reel/AbC_d-123/?igsh=xyz&utm_source=a"),
    { ok: true, url: "https://www.instagram.com/reel/AbC_d-123/", shortcode: "AbC_d-123", username: null });
  assert.deepEqual(parseIgReelLink("https://instagram.com/9GAG/reel/AbCdE12/"),
    { ok: true, url: "https://www.instagram.com/reel/AbCdE12/", shortcode: "AbCdE12", username: "9gag" });
  assert.equal((parseIgReelLink("https://www.instagram.com/reels/AbCdE12") as { shortcode: string }).shortcode, "AbCdE12");
  assert.deepEqual((parseIgReelLink("https://m.instagram.com/p/AbCdE12/") as { url: string }).url, "https://www.instagram.com/p/AbCdE12/");
});

test("릴스 링크 해석: 인스타 아닌 주소·http·형식 안 맞는 주소 거부", () => {
  for (const bad of ["http://www.instagram.com/reel/AbCdE12/", "https://evil.com/reel/AbCdE12/", "https://instagram.com.evil.com/reel/AbCdE12/",
    "https://www.instagram.com/9gag/", "https://www.instagram.com/reel/a/", "not a url", ""]) {
    assert.equal(parseIgReelLink(bad).ok, false, bad);
  }
});

test("링크 동작: 서버가 정규화해 rpc 로 넘기고, 계정 이름이 없으면 rpc 전에 거부", async () => {
  const calls: { fn: string; p: Record<string, unknown> }[] = [];
  const exec = async (fn: string, p: Record<string, unknown>) => { calls.push({ fn, p }); return { data: { ok: 1 }, error: null }; };
  const bad = await runDrinksAction(exec, { action: "ig_add_link", payload: { url: "https://www.instagram.com/reel/AbCdE12/" } });
  assert.equal(bad.status, 400);
  assert.equal(calls.length, 0);
  const good = await runDrinksAction(exec, { action: "ig_add_link", payload: { url: "https://www.instagram.com/reel/AbCdE12/?igsh=x", username: "@Daquan", note: "봤다" } });
  assert.equal(good.status, 200);
  assert.deepEqual(calls[0], { fn: "drinks_ig_add_link", p: { username: "daquan", note: "봤다", canonical_url: "https://www.instagram.com/reel/AbCdE12/", shortcode: "AbCdE12" } });
});

test("밈 보드 동작은 여섯뿐이고, 워커 전용 함수(점유·끝내기·수집)는 화면에서 부를 수 없다", () => {
  const ig = Object.entries(DRINKS_ACTIONS).filter(([k]) => k.startsWith("ig_")).map(([, f]) => f).sort();
  // 2026-11-02 총괄 §7 결정 1: [쓰자] + 정밀화 요청(drinks_ig_card_use_refine)과 손으로 만드는 카드(drinks_ig_create_manual_card)가 더해졌다.
  assert.deepEqual(ig, ["drinks_ig_add_link", "drinks_ig_card_decide", "drinks_ig_card_use_refine", "drinks_ig_create_manual_card",
    "drinks_ig_set_card_field", "drinks_ig_watch_action"]);
  for (const f of Object.values(DRINKS_ACTIONS)) assert.ok(!/drinks_apify_(claim|finish|reap)|drinks_ig_(record|upsert|apply|mark|finish_link|worker_state)/.test(f), f);
});

test("[쓰자] 는 Apify 요청을 큐에 넣을 뿐 — 화면·보드 코드가 돈이 드는 경로를 직접 열지 않는다", () => {
  const route = readFileSync(join(HERE, "../../app/api/drinks/route.ts"), "utf8");
  assert.ok(!/ig_card_decide/.test(route), "결정만 기록하는 [넘기기]·[나중에] 에는 후속 동작이 없다");
  assert.match(route, /ig_card_use_refine[\s\S]*refine\?\.queued === true[\s\S]*drinks-apify\.yml/, "요청이 실제로 큐에 들어갔을 때만 정밀화 워커를 깨운다");
  const page = readFileSync(join(HERE, "../../app/drinks/memes/page.tsx"), "utf8") + readFileSync(join(HERE, "../../components/drinks/MemeBoardControls.tsx"), "utf8");
  assert.ok(!/apify\.com|request_develop|request_render|triggerWorkflow|APIFY_TOKEN/i.test(page));
  assert.match(page, /refineCostLine|이달 누적/, "버튼 옆에 이번 예상액·이달 누적액을 보여 준다(기획 v2 §6-1)");
});

test("미적용·실패 때도 관찰 범위 줄이 화면에 남는다", () => {
  const page = readFileSync(join(HERE, "../../app/drinks/memes/page.tsx"), "utf8");
  assert.match(page, /관찰 범위: /);
  assert.match(page, /마지막 정상 관측일: /);
  assert.match(page, /최근 7일 중 정상 관측: /);
  assert.match(page, /<ScopeLine h=\{null\} \/>/);
  assert.match(page, /관측 중단 — 상태 고정/);
});

test("주류 메뉴에 밈 보드가 있다", () => {
  const nav = readFileSync(join(HERE, "../nav.ts"), "utf8");
  assert.match(nav, /href: "\/drinks\/memes", label: "밈 보드"/);
});
