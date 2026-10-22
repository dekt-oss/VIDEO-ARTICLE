// 주류 설정·지원 범위 (/drinks/settings) — 지금 되는 것과 아직 연결되지 않은 것을 그대로 보여준다.
// ★ 저장 버튼이 없다. A단계에는 바꿀 설정이 없고, 작동하지 않는 스위치를 만들지 않는다(명세 §9.5 는 후속 단계).
// ★ 성과(/drinks/analytics)는 메뉴에 넣지 않았다 — 수집하는 지표가 하나도 없어서 보여줄 숫자가 없다.
import { FORMAT_FIT_MIN, RUBRIC_VERSION, SCORE_AXES, SELECT_THRESHOLD } from "@/lib/drinks/model";

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
];

const OFF = [
  ["자동 수집", "수집원 등록·크롤링·피드·댓글/DM 수집·주기 실행이 없습니다. 마지막 수집 시각도 없습니다."],
  ["URL 본문 확보", "URL 을 등록해도 서버가 열지 않습니다. OCR·번역도 없습니다."],
  ["LLM 조사·채점·대본 생성", "모든 점수와 제작안은 사람이 입력합니다."],
  ["유료 제작", "이미지·영상·TTS 생성과 렌더가 없습니다. 비용도 산정하지 않습니다."],
  ["파일 검수", "만들어진 파일이 없어 파일 검수 승인이 없습니다."],
  ["Instagram 연결·발행·예약", "계정 연결·토큰·업로드·예약 실행이 없습니다."],
  ["성과", "수집하는 지표가 없습니다. 성과 화면을 만들지 않았습니다."],
];

export default function DrinksSettingsPage() {
  return (
    <main className="container">
      <div className="header">
        <h1>🍶 설정·지원 범위</h1>
        <span className="muted">A단계 — 수동 작업 기반</span>
      </div>
      <section className="section">
        <h3>지금 되는 것</h3>
        <ul>{ON.map((x) => <li key={x}>{x}</li>)}</ul>
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
