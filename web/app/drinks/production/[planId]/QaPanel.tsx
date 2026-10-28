// 파일 묶음의 기계 검사 한 장 — 경고 · 릴스 규격 · 대본 검사 · 말 속도 · 화면 출처. 판정이 아니라 참고다.
// 데이터가 있는 구역만 그린다(옛 행에는 새 키가 없다).
import { qaView, qaWarningLabel } from "@/lib/drinks/model";

const nums = (a: number[]) => (a.length ? a.map((n) => `${n}번`).join(", ") : "없음");

export default function QaPanel({ qa }: { qa: unknown }) {
  const v = qaView(qa);
  const script = v.script && (v.script.blocks.length > 0 || v.script.warns.length > 0 || v.script.ok != null) ? v.script : null;
  if (!v.warnings.length && !v.reel.length && !script && !v.speech && !v.visual) return null;
  return (
    <div className="dk-sub">
      <b>기계 검사</b> <span className="muted">(참고용 — 판정은 사람이 합니다)</span>
      {v.warnings.length > 0 && (
        <ul className="banner-warn" style={{ margin: "6px 0", paddingLeft: 20 }}>
          {v.warnings.map((c) => <li key={c}>{qaWarningLabel(c)}{qaWarningLabel(c) !== c && <span className="muted"> ({c})</span>}</li>)}
        </ul>
      )}
      {v.reel.length > 0 && (
        <table style={{ borderCollapse: "collapse", margin: "6px 0", fontSize: 13 }}>
          <tbody>
            {v.reel.map((r) => (
              <tr key={r.label}>
                <td style={{ padding: "1px 12px 1px 0" }} className="muted">{r.label}</td>
                <td style={{ padding: "1px 12px 1px 0" }}>{r.value}</td>
                <td className={r.ok ? "dk-ok" : "dk-bad"}>{r.ok ? "✔" : "✖"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {script && (
        <div style={{ margin: "6px 0" }}>
          <div className={script.blocks.length ? "dk-bad" : "dk-ok"}>
            대본 검사: {script.blocks.length ? `막힌 문장 ${script.blocks.length}건` : "막힌 문장 없음"}
            {script.warns.length > 0 && ` · 확인할 문장 ${script.warns.length}건`}
          </div>
          {script.blocks.map((b, i) => <div key={`b${i}`} className="dk-bad">{b.scene != null ? `${b.scene}번 장면` : "전체"} — {b.message}</div>)}
          {script.warns.map((w, i) => <div key={`w${i}`} className="muted">{w.scene != null ? `${w.scene}번 장면` : "전체"} — {w.message}</div>)}
        </div>
      )}
      {v.speech && <div className={v.speech.fast ? "dk-warn" : undefined}>말 속도: {v.speech.text}{v.speech.fast && " — 빠른 편입니다"}</div>}
      {v.visual && (
        <div className="muted">화면 출처: 대체 카드 {nums(v.visual.standIn)} · 카드 페이지 {nums(v.visual.cardPages)} · 생성 그림 {nums(v.visual.generated)}</div>
      )}
    </div>
  );
}
