// 조회 실패·설정 누락을 "0건"과 다르게 보여준다(주류 명세 §10). 서버 컴포넌트에서 쓴다.
export default function LoadProblem({ state, error }: { state: "failed" | "unconfigured"; error?: string }) {
  if (state === "unconfigured") {
    return (
      <div className="banner-block" role="alert">
        <b>주류 공장 데이터를 읽을 수 없습니다 — 서버에 SUPABASE_SERVICE_KEY 가 없습니다.</b>
        <p className="muted" style={{ margin: "6px 0 0" }}>
          주류 표는 공개 읽기가 막혀 있어 서버 키로만 읽습니다. 목록이 비어 있는 것이 아니라 조회를 못 한 것입니다.
        </p>
      </div>
    );
  }
  return (
    <div className="banner-block" role="alert">
      <b>데이터를 불러오지 못했습니다 — 0건이 아니라 조회 실패입니다.</b>
      <p className="muted" style={{ margin: "6px 0 0" }}>
        {error}
        {error && /drink_|does not exist|schema cache/.test(error) && " (0050 마이그레이션이 적용됐는지 확인하세요)"}
      </p>
    </div>
  );
}
