// "손으로 넣기" — 접힌 칸. 소재 직접 등록(RegisterForm)과 발견 자료 직접 등록(ManualDiscoveryForm)을 그대로 쓴다.
import RegisterForm from "@/components/drinks/RegisterForm";
import { ManualDiscoveryForm } from "@/components/drinks/DiscoveryControls";

export default function ManualEntry() {
  return (
    <details className="section">
      <summary className="muted" style={{ cursor: "pointer" }}><b>손으로 넣기</b> — 질문을 직접 소재로 등록하거나, 자동 수집이 안 되는 채널의 발견 자료를 링크로 넣습니다</summary>
      <div style={{ marginTop: 10 }}>
        <RegisterForm />
        <ManualDiscoveryForm />
      </div>
    </details>
  );
}
