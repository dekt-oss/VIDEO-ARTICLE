// 주류 설정·지원 범위 (/drinks/settings) — 지금 되는 것과 아직 연결되지 않은 것을 그대로 보여준다.
// ★ 저장 버튼이 없다. 작동하지 않는 스위치를 만들지 않는다(명세 §9.5 는 후속 단계).
//   B단계의 수집 상한은 DB(0051 drinks_collect_limits)에서 읽어 그대로 보여준다 — 수집원별 상한은 /drinks/sources 에서 바꾼다.
// ★ 성과(/drinks/analytics)는 메뉴에 넣지 않았다 — 수집하는 지표가 하나도 없어서 보여줄 숫자가 없다.
import Link from "next/link";

import { FORMAT_FIT_MIN, RUBRIC_VERSION, SCORE_AXES, SELECT_THRESHOLD } from "@/lib/drinks/model";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

const ON = [
  "소재·질문 직접 등록(질문만, 또는 URL·직접 입력한 원문/발췌와 함께)",
  "출처 스냅샷 보관: 같은 URL·같은 본문은 재사용, 본문이 바뀌면 새 버전, 같은 본문의 다른 URL 은 ‘같은 본문 후보’로 알리고 원출처 묶음은 운영자가 확인해 정함",
  "출처 정보 정정·재확인·사용 조건 확인·권리 철회 기록(원문 불변, 기록은 추가만) · 권리 철회 시 영향 범위 표시",
  "경량 평가(임시 점수)와 편성 평가(근거·기획 버전 점수)를 따로 기록",
  "핵심 주장별 발췌 대조(서버 자동)와 지지 검토(사람)를 따로 기록, 필수 조건 미달 시 승인·편성 차단",
  "근거·공통 기획 버전 승인(승인 후 수정 불가, 고치면 새 버전) · 승인 철회 시 그 근거를 쓴 제작안 즉시 차단",
  "편성: 형식(영상·카드뉴스 각각)과 주차 · 형식별 적합성 2점 미만은 경고 — 형식 예외 사유를 남기면 편성(점수 예외와 따로 기록)",
  "형식별 필수 주장: 제작안의 사실 항목은 주장 연결 필수, 그 형식의 필수 주장을 모두 연결해야 검수·승인",
  "형식별 제작안(영상 장면 / 카드 페이지) 작성·검수·승인 — 형식끼리 독립",
  "모든 상태 변경의 감사 이력(추가만 가능)",
  "수집원 등록부: 제안 → 검증 실행 → 검증 완료 → 활성화(사람만, 이용 조건 확인 필수) · 일시 중지 · 종료",
  "승인한 수집원만 하루 한 번 수집(KST 06:30) + 운영자 [지금 수집]·[실패분 재시도] — 고정 페이지·목록 페이지·피드",
  "수집 실행 기록: 정상 0건 / 성공 / 부분 성공 / 실패 / 실행 중단을 구분, 실패 문서만 재시도, 성공한 실행만 워처마크 전진",
  "수집 문서 중복 규칙: 같은 URL·같은 본문 재사용, 본문 바뀌면 새 버전, 다른 URL 의 같은 본문은 원출처 후보로만 표시",
  "안전 요청: 승인 호스트·https·공개 주소만, 리다이렉트 재검사, 응답 크기·시간 상한, robots.txt 준수",
  "수집 문서 → 소재 후보 등록·기존 소재 조사 연결(사람), 비슷한 소재 후보 표시(규칙 기반)",
];

const OFF = [
  ["임의 URL 열기·크롤링", "수동으로 등록한 URL 은 서버가 열지 않습니다. 수집은 등록부의 승인 주소만, 사이트 전체 크롤링은 없습니다."],
  ["SNS·댓글·DM 수집", "연결하지 않았습니다."],
  ["OCR·번역", "본문이 없거나 PDF·이미지면 ‘제목·요약만’으로 남깁니다. 번역·OCR 로 대신하지 않습니다."],
  ["LLM 후보 생성·조사·채점·대본 생성", "LLM 호출이 0회입니다. 후보 질문·점수·제작안은 사람이 입력합니다."],
  ["유료 제작", "이미지·영상·TTS 생성과 렌더가 없습니다. 비용도 산정하지 않습니다."],
  ["파일 검수", "만들어진 파일이 없어 파일 검수 승인이 없습니다."],
  ["Instagram 연결·발행·예약", "계정 연결·토큰·업로드·예약 실행이 없습니다."],
  ["성과", "수집하는 지표가 없습니다. 성과 화면을 만들지 않았습니다."],
];

const LIMIT_LABEL: Record<string, string> = {
  max_active_sources: "동시에 활성인 수집원",
  max_items_ceiling: "실행 1회 문서(제목·메타데이터) 상한",
  max_bodies_ceiling: "실행 1회 본문 수집 상한",
  runs_per_day: "수집원 하나의 24시간 실행 수",
  min_interval_sec: "요청 간 최소 간격(초)",
  lease_sec: "실행 임대 시간(초) — 넘으면 다음 워커가 ‘실행 중단’으로 닫음",
  queued_ttl_hours: "대기 실행 유효 시간(시간)",
};

async function loadLimits(): Promise<Record<string, number> | string> {
  const db = createAdminClient();
  if (!db) return "서버에 SUPABASE_SERVICE_KEY 가 없습니다";
  const r = await db.rpc("drinks_collect_limits");
  if (r.error) return r.error.message;
  return (r.data ?? {}) as Record<string, number>;
}

export default async function DrinksSettingsPage() {
  const limits = await loadLimits();
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 설정·지원 범위</h1>
        <span className="muted">A단계 수동 작업 + B단계 수집·선정</span>
      </div>
      <section className="section">
        <h3>지금 되는 것</h3>
        <ul>{ON.map((x) => <li key={x}>{x}</li>)}</ul>
      </section>
      <section className="section">
        <h3>수집 상한 (DB 고정값 — 수집원별 값은 이 이하로 <Link href="/drinks/sources">수집원</Link>에서)</h3>
        {typeof limits === "string" ? (
          <p className="banner-warn">수집 상한을 읽지 못했습니다 — {limits}</p>
        ) : (
          <ul>{Object.entries(LIMIT_LABEL).map(([k, l]) => <li key={k}>{l}: <b>{limits[k] ?? "—"}</b></li>)}</ul>
        )}
      </section>
      <section className="section">
        <h3>아직 연결되지 않은 것 (전부 꺼짐)</h3>
        {OFF.map(([k, v]) => (
          <div key={k} className="list-row">
            <span><b>{k}</b> <span className="muted">— {v}</span></span>
            <span className="pill">미연결</span>
          </div>
        ))}
      </section>
      <section className="section">
        <h3>점수 기준 ({RUBRIC_VERSION}) — 코드 고정값, 화면에서 바꾸지 않음</h3>
        <ul>
          {SCORE_AXES.map((a) => (
            <li key={a.key}>
              {a.label}: {a.weight > 0 ? `${a.weight}점 만점` : "영상·카드 중 높은 값이 20점 만점"} — 0점 {a.low} / 4점 {a.high}
            </li>
          ))}
        </ul>
        <p className="muted">
          편성 후보 표시 기준 {SELECT_THRESHOLD}점(미만은 예외 사유 필요) · 형식별 적합성 {FORMAT_FIT_MIN}점 미만은 경고(형식 예외 사유 필요). 근거 필수 조건은 어떤 예외로도 넘지 않습니다.
          점수는 검증 전 기준값이며 자동 발주·발행 문턱이 아닙니다.
        </p>
      </section>
    </main>
  );
}
