"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { RenderJob, VersionType } from "@/lib/types";
import { useToast } from "@/components/Toast";
import ConfirmModal from "@/components/ConfirmModal";
import { dayLabelWithDate, seoulDateOf } from "@/lib/date";
import { apiErrorText } from "@/lib/apiError";
import ErrorDisclosure from "@/components/ErrorDisclosure";
import { parseRenderError } from "@/lib/renderError";
import {
  RENDER_TABS,
  classifyRenderJob,
  countByTab,
  primaryAction,
  type RenderTab,
} from "@/lib/work/renderQueue";
import AsyncJobStatus from "@/components/AsyncJobStatus";
import { useJobPolling } from "@/lib/useJobPolling";
import { RENDER_STATUS_AWAITING_HUMAN } from "@/lib/renderStatus";

const STATUS_LABEL: Record<string, string> = {
  queued: "대기",
  assets: "에셋 생성",
  tts: "나레이션 TTS",
  assembling: "조립",
  qa_pending: "확인 필요",
  degraded: "승인 필요",
  done: "완료",
  failed: "실패",
};

const VERSION_LABEL: Record<string, string> = {
  comic: "만화식",
  webtoon: "웹툰 (장면 파생)",
  explainer: "설명판형",
  image_sequence: "이미지 나열식",
  animation: "애니메이션식",
  hybrid: "만화식+영상 혼합",
};

// 요약줄 버전 뱃지용 짧은 라벨.
const VERSION_SHORT: Record<string, string> = {
  comic: "만화",
  webtoon: "웹툰",
  explainer: "설명판",
  image_sequence: "이미지",
  animation: "애니",
  hybrid: "혼합",
};

// 그룹 내 버전 표시 순서(고정).
const VERSION_ORDER: VersionType[] = [
  "image_sequence", "comic", "webtoon", "explainer", "animation", "hybrid",
];

// 그룹의 렌더 잡을 버전별로 묶어 상태색 뱃지로 요약. 완료=초록, 진행중=파랑, 실패=회색.
function versionBadges(jobs: RenderJob[]): { key: string; label: string; cls: string }[] {
  const byV = new Map<string, RenderJob[]>();
  for (const j of jobs) {
    const v = j.version_type ?? "?";
    (byV.get(v) ?? byV.set(v, []).get(v)!).push(j);
  }
  const order = (v: string) => {
    const i = VERSION_ORDER.indexOf(v as VersionType);
    return i === -1 ? 99 : i;
  };
  return [...byV.entries()]
    .sort((a, b) => order(a[0]) - order(b[0]))
    .map(([v, js]) => {
      const done = js.some((j) => j.status === "done");
      const running = js.some((j) => j.status !== "done" && j.status !== "failed");
      const short = VERSION_SHORT[v] ?? v;
      const label = done ? `${short} 완료` : running ? `${short} 진행중` : `${short} 실패`;
      const cls = done ? "badge-rendered" : running ? "badge-approved" : "badge-trash";
      return { key: v, label, cls };
    });
}

type SortMode = "recent" | "oldest";

interface PaperGroup {
  paperId: string;
  title: string; // 영문 제목(papers.title)
  titleKo: string | null; // 한글 제목(scores.title_ko)
  jobs: RenderJob[];
  latest: string; // 그룹 내 가장 최근 created_at (정렬 기준)
  doneCount: number;
  cost: number;
  // 발행용(유튜브 업로드) 복붙 필드 — 렌더결과에서 제목·설명란을 바로 복사.
  uploadTitleKo: string | null;
  uploadTitleEn: string | null;
  captionKo: string;
  captionEn: string;
}

// 탭 판정·주요행동은 lib/work/renderQueue.ts(순수 함수·테스트 있음)를 쓴다 — 홈의 "다음 작업"
// 카운트와 같은 규칙이라 두 화면의 숫자가 어긋나지 않는다(RENDER-02).

export default function RenderList({ jobs }: { jobs: RenderJob[] }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  // ASYNC-01: 진행 중 잡이 있을 때만 자동 갱신(전부 끝나면 폴링 중단).
  const activeCount = jobs.filter((j) => j.status !== "done" && j.status !== "failed").length;
  const { polling, lastCheckedAt } = useJobPolling(activeCount);
  // RENDER-02: 날짜순 목록이 아니라 조치 필요 → 진행 중 → 완료 → 보관 탭. 기본은 조치 필요.
  const [tab, setTab] = useState<RenderTab>("action");
  const [sort, setSort] = useState<SortMode>("recent");
  const tabCounts = useMemo(() => countByTab(jobs), [jobs]);
  // 삭제(휴지통) 확인 모달 대상 job.
  const [trashTarget, setTrashTarget] = useState<RenderJob | null>(null);
  // degraded 승인은 되돌리기 어렵다(발행이 열린다) — 집 관례대로 ConfirmModal 을 거친다.
  const [approveTarget, setApproveTarget] = useState<RenderJob | null>(null);
  // 언어 버전 재생성 확인(같은 언어 완료 잡이 이미 있을 때). window.confirm 대체.
  const [forceTarget, setForceTarget] = useState<
    { jobId: string; lang: "ko" | "en"; message: string | null } | null
  >(null);
  // 발행 제목·설명란 복사 피드백(그룹+필드 키).
  const [copied, setCopied] = useState<string | null>(null);

  async function copyText(text: string, key: string) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      toast.show("복사 실패 — 텍스트를 직접 선택해 복사하세요", "err");
    }
  }

  const groups = useMemo<PaperGroup[]>(() => {
    const filtered = jobs.filter((j) => classifyRenderJob(j) === tab);
    const byPaper = new Map<string, PaperGroup>();
    for (const j of filtered) {
      const key = j.paper_id ?? j.directive_id ?? j.id;
      let g = byPaper.get(key);
      if (!g) {
        g = {
          paperId: key,
          title: j.title ?? "(제목 없음)",
          titleKo: j.title_ko ?? null,
          jobs: [],
          latest: j.created_at,
          doneCount: 0,
          cost: 0,
          uploadTitleKo: j.upload_title_ko ?? null,
          uploadTitleEn: j.upload_title_en ?? null,
          captionKo: j.caption_ko ?? "",
          captionEn: j.caption_en ?? "",
        };
        byPaper.set(key, g);
      }
      g.jobs.push(j);
      if (j.created_at > g.latest) g.latest = j.created_at;
      if (j.status === "done") g.doneCount += 1;
      g.cost += Number(j.cost_estimate ?? 0);
    }
    // 그룹 내 버전 정렬(고정 순서 → 그 외 → 최신순).
    for (const g of byPaper.values()) {
      g.jobs.sort((a, b) => {
        const ai = VERSION_ORDER.indexOf(a.version_type as VersionType);
        const bi = VERSION_ORDER.indexOf(b.version_type as VersionType);
        if (ai !== bi) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
        return b.created_at.localeCompare(a.created_at);
      });
    }
    const list = [...byPaper.values()];
    list.sort((a, b) =>
      sort === "recent" ? b.latest.localeCompare(a.latest) : a.latest.localeCompare(b.latest)
    );
    return list;
  }, [jobs, tab, sort]);

  // 렌더(그룹) 최신 시각의 KST 달력일별로 구획. groups 가 날짜순 정렬이라 같은 날짜는 연속.
  const dateGroups = useMemo(() => {
    const out: { date: string; items: PaperGroup[] }[] = [];
    const idx = new Map<string, number>();
    for (const g of groups) {
      const key = seoulDateOf(g.latest) ?? "__none__";
      if (!idx.has(key)) {
        idx.set(key, out.length);
        out.push({ date: key, items: [] });
      }
      out[idx.get(key)!].items.push(g);
    }
    return out;
  }, [groups]);

  async function kickRender() {
    setBusy("__trigger__");
    const res = await fetch("/api/render-trigger", { method: "POST" });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) toast.show("렌더 워커를 시작했습니다. 진행 상황은 이 화면에서 자동으로 갱신됩니다.", "ok");
    else toast.show(apiErrorText(e, res.status, "렌더 워커를 시작"), "err");
  }

  // 발행/반려 — 기존 /api/render-result.
  async function act(jobId: string, action: "publish" | "reject") {
    setBusy(jobId);
    const res = await fetch("/api/render-result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show(action === "publish" ? "발행 대기로 이관되었습니다." : "재렌더 큐에 적재되었습니다.", "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "이 작업을 처리"), "err");
    }
  }

  // 유튜브 업로드 — /api/youtube-upload. 언어별 채널(잡의 lang)로 큐 적재 + 워커 트리거.
  async function uploadYoutube(jobId: string) {
    setBusy(jobId);
    const res = await fetch("/api/youtube-upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show("유튜브 업로드 큐에 적재했습니다(비공개). 상태는 자동으로 갱신됩니다.", "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "유튜브 업로드를 요청"), "err");
    }
  }

  // 언어 추가 렌더 — /api/render-add-language (수정명세 v1 §2).
  // 이미지·클립은 언어 독립 캐시(render_assets.content_hash)라 그대로 재사용되고 TTS·자막·
  // 타임라인만 다시 계산된다 → 추가 비용은 사실상 TTS 뿐. 총 길이는 언어별로 다를 수 있다.
  async function addLanguage(jobId: string, lang: "ko" | "en", force = false) {
    setBusy(jobId);
    const res = await fetch("/api/render-add-language", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_job_id: jobId, lang, force }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      toast.show(
        `${lang.toUpperCase()} 버전을 렌더 큐에 적재했습니다(에셋 재사용). 진행 상황은 자동으로 갱신됩니다.`,
        "ok",
      );
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
      return;
    }
    if (res.status === 409 && e?.error === "exists") {
      // 이미 같은 언어의 완료 잡이 있음 → ConfirmModal 로 확인받고 force 재요청.
      // window.confirm 을 쓰지 않는다(FEED-01): 브라우저 기본 대화상자는 스타일·포커스·모바일
      // 동작이 앱과 어긋나고, 확인 문구에 비용 안내를 담을 수도 없다.
      setForceTarget({ jobId, lang, message: e?.message ?? null });
      return;
    }
    toast.show(apiErrorText(e, res.status, "언어 버전을 추가"), "err");
  }

  // 저장/삭제 — /api/render-manage.
  async function manage(
    jobId: string,
    action: "save" | "unsave" | "trash" | "approve_degraded",
  ) {
    setBusy(jobId);
    const res = await fetch("/api/render-manage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action }),
    });
    setBusy(null);
    const e = await res.json().catch(() => null);
    if (res.ok) {
      const label =
        action === "save" ? "보관함에 저장했습니다."
          : action === "unsave" ? "보관을 해제했습니다."
            : action === "approve_degraded" ? "승인했습니다 — 이제 업로드할 수 있습니다."
              : "휴지통으로 이동했습니다.";
      toast.show(label, "ok");
      router.refresh(); // 전체 reload 금지 — 펼친 그룹·스크롤 위치를 잃지 않는다
    } else {
      toast.show(apiErrorText(e, res.status, "보관·휴지통 상태를 저장"), "err");
    }
  }

  if (jobs.length === 0) {
    return (
      <p className="empty">
        렌더 잡이 없습니다. <Link href="/directive">⑤ 영상 지시서</Link>에서 승인하면 여기 나타납니다.
      </p>
    );
  }

  return (
    <>
      <div className="controls">
        {/* 탭 — 건수를 함께 보여 조치할 것이 있는지 한눈에(0 이어도 숨기지 않는다). */}
        <div className="toggle" aria-label="렌더 작업 분류">
          {RENDER_TABS.map((t) => (
            <button key={t.key} data-active={tab === t.key} onClick={() => setTab(t.key)}>
              {t.label} {tabCounts[t.key]}
            </button>
          ))}
        </div>
        <div className="toggle" aria-label="정렬">
          <button data-active={sort === "recent"} onClick={() => setSort("recent")}>최신순</button>
          <button data-active={sort === "oldest"} onClick={() => setSort("oldest")}>오래된순</button>
        </div>
        <span className="muted">
          논문 {groups.length}편 · 렌더 {groups.reduce((n, g) => n + g.jobs.length, 0)}건
        </span>
        <button className="btn" disabled={busy === "__trigger__"} onClick={kickRender}>
          지금 렌더
        </button>
        <a className="btn btn-quiet" href="/render/trash">휴지통</a>
      </div>

      {groups.length === 0 && (
        <p className="muted">
          {tab === "action"
            ? "조치할 렌더가 없습니다. 진행 중·완료 탭을 확인하세요."
            : "이 분류에 렌더가 없습니다."}
        </p>
      )}

      {dateGroups.map((dg) => (
        <div key={dg.date}>
          <h3 className="group-header" style={{ marginTop: 18 }}>
            {dg.date === "__none__" ? "날짜 미상" : dayLabelWithDate(dg.date)}{" "}
            <span className="muted">· {dg.items.length}편</span>
          </h3>
          {dg.items.map((g) => (
        <details className="render-group" key={g.paperId}>
          <summary className="group-header">
            <span>
              <b>{g.titleKo || g.title}</b>
              {g.titleKo && g.title && g.titleKo !== g.title && (
                <span className="muted" style={{ display: "block", fontSize: 12, fontWeight: 400 }}>
                  {g.title}
                </span>
              )}
            </span>
            <span className="muted">
              {" "}· 완료 {g.doneCount}/{g.jobs.length}
              {g.cost ? ` · $${g.cost.toFixed(3)}` : ""}
            </span>
            <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", marginLeft: 8 }}>
              {versionBadges(g.jobs).map((b) => (
                <span key={b.key} className={`status-pill ${b.cls}`}>{b.label}</span>
              ))}
            </span>
          </summary>

          {(g.uploadTitleKo || g.uploadTitleEn || g.captionKo || g.captionEn) && (
            <div className="publish-copy" style={{ margin: "8px 0 4px", padding: "10px 12px", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                📋 유튜브 업로드용 — 제목·설명란을 바로 복사하세요
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                <button
                  className="btn"
                  disabled={!g.uploadTitleKo}
                  onClick={() => copyText(g.uploadTitleKo ?? "", `${g.paperId}-tko`)}
                  title={g.uploadTitleKo ?? "제목 없음(초안 재생성 필요)"}
                >
                  {copied === `${g.paperId}-tko` ? "제목(한) 복사됨 ✓" : "제목(한) 복사"}
                </button>
                <button
                  className="btn"
                  disabled={!g.uploadTitleEn}
                  onClick={() => copyText(g.uploadTitleEn ?? "", `${g.paperId}-ten`)}
                  title={g.uploadTitleEn ?? "no title"}
                >
                  {copied === `${g.paperId}-ten` ? "제목(EN) 복사됨 ✓" : "제목(EN) 복사"}
                </button>
                <button
                  className="btn"
                  disabled={!g.captionKo}
                  onClick={() => copyText(g.captionKo, `${g.paperId}-cko`)}
                >
                  {copied === `${g.paperId}-cko` ? "설명란(한) 복사됨 ✓" : "설명란(한) 복사"}
                </button>
                <button
                  className="btn"
                  disabled={!g.captionEn}
                  onClick={() => copyText(g.captionEn, `${g.paperId}-cen`)}
                >
                  {copied === `${g.paperId}-cen` ? "설명란(EN) 복사됨 ✓" : "설명란(EN) 복사"}
                </button>
              </div>
              {(g.uploadTitleKo || g.uploadTitleEn) && (
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  {g.uploadTitleKo && <div>🇰🇷 {g.uploadTitleKo}</div>}
                  {g.uploadTitleEn && <div>🇬🇧 {g.uploadTitleEn}</div>}
                </div>
              )}
            </div>
          )}

          {new Set(g.jobs.map((j) => j.lang ?? "ko")).size > 1 && (
            <div className="muted" style={{ fontSize: 12, margin: "6px 0 2px" }}>
              ℓ 언어별 총 길이가 다른 것은 결함이 아닙니다 — 컷 화면 시간이 그 언어 나레이션의 실측
              길이라서 한국어 52초가 영어로는 47초가 될 수 있습니다. 컷 순서와 이미지·클립은 동일합니다.
            </div>
          )}

          <div className="render-versions">
            {g.jobs.map((j) => {
              const done = j.status === "done";
              const failed = j.status === "failed";
              // ★ mp4 는 있는데 사람 승인을 기다리는 상태(§8-3). `done` 으로만 게이트하면
              //   degraded 잡의 **영상 링크와 QA 패널이 안 보여서** 운영자가 무엇을 승인하는지
              //   볼 수가 없다. 업로드는 계속 done 만 허용한다(승인은 별도 액션).
              const rendered = done || RENDER_STATUS_AWAITING_HUMAN.includes(j.status as never);
              // 중요 요소가 빠진 채 렌더된 영상 — 사람이 보고 승인해야 발행할 수 있다(§8-3).
              const needsApproval = j.status === "degraded" && !j.degraded_approved_at;
              const saved = !!j.saved_at;
              const lang = (j.lang ?? "ko") === "en" ? "en" : "ko";
              const otherLang: "ko" | "en" = lang === "en" ? "ko" : "en";
              // 같은 지시서에 반대 언어 잡이 이미 있는지(진행중 포함) — 버튼 라벨을 바꿔 중복 발주를 줄인다.
              const otherExists = g.jobs.some(
                (o) => o.directive_id === j.directive_id && (o.lang ?? "ko") === otherLang
              );
              const primary = primaryAction(j);
              return (
                <div className={failed ? "scene flagged" : "scene"} key={j.id}>
                  <div className="meta">
                    <b>{VERSION_LABEL[j.version_type ?? ""] ?? j.version_type ?? "?"}</b>
                    <span className="pill" style={{ marginLeft: 6 }}>
                      {(j.lang ?? "ko") === "en" ? "🇬🇧 EN" : "🇰🇷 KO"}
                    </span>{" "}
                    · {STATUS_LABEL[j.status] ?? j.status} · {j.progress}%
                    {j.cost_estimate ? ` · $${Number(j.cost_estimate).toFixed(3)}` : ""}
                    {saved && <span className="pill badge-saved" style={{ marginLeft: 6 }}>★ 보관</span>}
                  </div>

                  {!rendered && !failed && (
                    <AsyncJobStatus
                      stageLabel={STATUS_LABEL[j.status] ?? j.status}
                      startedAt={j.created_at}
                      autoRefresh={polling}
                      lastCheckedAt={lastCheckedAt}
                    />
                  )}
                  {failed && <ErrorDisclosure log={j.error_log} />}

                  {rendered && j.qa && (j.qa.hard_fail?.length || j.qa.warnings?.length) ? (
                    <div className={j.qa.hard_fail?.length ? "banner-warn" : "muted"} style={{ marginTop: 6, fontSize: 12 }}>
                      {j.qa.hard_fail?.length
                        ? `⚠️ 렌더 QA 하드 실패: ${j.qa.hard_fail.join(" · ")} — 발행 전 확인/재렌더`
                        : `QA 경고: ${j.qa.warnings.join(" · ")}`}
                    </div>
                  ) : rendered && j.qa?.passed ? (
                    <div className="grounded-ok" style={{ marginTop: 6, fontSize: 12 }}>✓ 렌더 QA 통과</div>
                  ) : null}

                  {rendered && j.output_url && (
                    <video src={j.output_url} controls style={{ maxWidth: 240, marginTop: 8, borderRadius: 6 }} />
                  )}

                  {done && j.youtube_status && (
                    <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                      {j.youtube_status === "done" && j.youtube_url ? (
                        <>
                          ▶️ 유튜브 업로드됨(비공개) —{" "}
                          <a href={j.youtube_url} target="_blank" rel="noreferrer">{j.youtube_url}</a>
                        </>
                      ) : j.youtube_status === "error" ? (
<ErrorDisclosure log={j.youtube_error} title="유튜브 업로드 실패" />
                      ) : (
                        <>⏳ 유튜브 업로드 {j.youtube_status === "processing" ? "진행 중" : "대기"}… (자동 확인 중)</>
                      )}
                    </div>
                  )}

                  {/* RENDER-02: 강조 버튼은 1개(상태별 주요 행동). 나머지는 낮은 강조로 내린다. */}
                  <div className="actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
                    {/* ★ 실패 카드에는 재렌더 버튼을 **항상** 둔다. 예전에는 분류가 "재시도해도
                        소용없음"이면 버튼 자체를 숨겨, 운영자가 실패한 편을 다시 만들 방법이
                        화면에서 사라졌다(남는 건 삭제뿐). 지금은 숨기는 대신 강조를 낮추고
                        권장 조치를 툴팁으로 말해 준다 — 판단은 사람이 한다. */}
                    {primary.key === "retry_render" && (
                      <button
                        className={parseRenderError(j.error_log).retryable ? "btn pick" : "btn btn-quiet"}
                        disabled={busy === j.id}
                        onClick={() => act(j.id, "reject")}
                        title={parseRenderError(j.error_log).action}
                      >
                        {primary.label}
                      </button>
                    )}
                    {(primary.key === "upload" || primary.key === "retry_upload") && (
                      <button
                        className="btn pick"
                        disabled={busy === j.id || !j.output_url}
                        onClick={() => uploadYoutube(j.id)}
                        title={`${primary.why} (${(j.lang ?? "ko") === "en" ? "EN" : "KO"} 채널)`}
                      >
                        {primary.label}
                      </button>
                    )}
                    {primary.key === "review_video" && (
                      <span className="muted" style={{ fontSize: 12, alignSelf: "center" }}>
                        {primary.why}
                      </span>
                    )}
                    {needsApproval && (
                      <button
                        className="btn pick"
                        disabled={busy === j.id}
                        onClick={() => setApproveTarget(j)}
                        title="중요 요소가 빠진 영상입니다 — 확인 후 승인해야 업로드할 수 있습니다"
                      >
                        확인하고 승인
                      </button>
                    )}
                    {done && (
                      <>
                        <button
                          className="btn btn-quiet"
                          disabled={busy === j.id || !j.output_url}
                          onClick={() => act(j.id, "publish")}
                        >
                          발행 대기 이관
                        </button>
                        <button
                          className="btn btn-quiet"
                          disabled={busy === j.id}
                          onClick={() => addLanguage(j.id, otherLang)}
                          title={
                            otherExists
                              ? `${otherLang.toUpperCase()} 버전이 이미 있습니다 — 다시 만들면 기존 것과 별개 잡이 생깁니다`
                              : "이미지·클립은 재사용하고 나레이션·자막만 새로 만듭니다(추가 비용 ≈ TTS)"
                          }
                        >
                          {otherLang === "en" ? "🇬🇧 EN" : "🇰🇷 KO"} 버전 {otherExists ? "재생성" : "추가 생성"}
                        </button>
                        <button className="btn btn-quiet" disabled={busy === j.id} onClick={() => manage(j.id, saved ? "unsave" : "save")}>
                          {saved ? "보관 해제" : "★ 저장"}
                        </button>
                        <button className="btn reject" disabled={busy === j.id} onClick={() => act(j.id, "reject")}>
                          반려(재렌더)
                        </button>
                      </>
                    )}
                    <button className="btn reject" disabled={busy === j.id} onClick={() => setTrashTarget(j)}>
                      삭제
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </details>
          ))}
        </div>
      ))}

      <ConfirmModal
        open={!!approveTarget}
        title="결함이 있는 영상을 승인"
        message={
          "중요 요소가 빠진 채 렌더된 영상입니다. 영상을 확인했고 이대로 발행해도 된다면 승인하세요. " +
          "승인해도 '결함이 있었다'는 기록은 남습니다."
        }
        confirmLabel="확인했습니다 — 승인"
        busy={!!approveTarget && busy === approveTarget.id}
        onCancel={() => setApproveTarget(null)}
        onConfirm={() => {
          if (approveTarget) {
            const id = approveTarget.id;
            setApproveTarget(null);
            manage(id, "approve_degraded");
          }
        }}
      />

      <ConfirmModal
        open={!!trashTarget}
        title="렌더를 휴지통으로 이동"
        message="이 렌더를 휴지통으로 옮깁니다. 목록에서 사라지지만 휴지통에서 복원할 수 있습니다."
        confirmLabel="휴지통으로 이동"
        danger
        busy={!!trashTarget && busy === trashTarget.id}
        onCancel={() => setTrashTarget(null)}
        onConfirm={() => {
          if (trashTarget) {
            const id = trashTarget.id;
            setTrashTarget(null);
            manage(id, "trash");
          }
        }}
      />

      <ConfirmModal
        open={!!forceTarget}
        title={`${forceTarget?.lang === "en" ? "EN" : "KO"} 버전 재생성`}
        message={
          (forceTarget?.message ?? "같은 언어의 완료된 렌더가 이미 있습니다.") +
          " 다시 만들면 기존 것과 별개의 렌더 잡이 생깁니다(이미지·클립은 재사용되고 나레이션만 다시 만듭니다)."
        }
        confirmLabel="재생성"
        busy={!!forceTarget && busy === forceTarget.jobId}
        onCancel={() => setForceTarget(null)}
        onConfirm={() => {
          if (forceTarget) {
            const { jobId, lang } = forceTarget;
            setForceTarget(null);
            addLanguage(jobId, lang, true);
          }
        }}
      />
    </>
  );
}
