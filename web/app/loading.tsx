// 라우트 전환 중 스켈레톤. 서버 컴포넌트가 데이터를 페치하는 동안 표시된다.
export default function Loading() {
  return (
    <main className="container">
      <div className="skeleton skeleton-row" style={{ width: "40%", height: 22 }} />
      <div className="skeleton skeleton-row" style={{ width: "60%" }} />
      <div className="skeleton skeleton-card" style={{ marginTop: 20 }} />
      <div className="skeleton skeleton-card" />
      <div className="skeleton skeleton-card" />
    </main>
  );
}
