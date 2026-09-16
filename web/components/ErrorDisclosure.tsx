"use client";

// 실패 표시 (개선 지시서 RENDER-01). 원인 + 권장 조치를 먼저 보여주고 원시 로그는 접는다.
// 이전에는 error_log(ffmpeg stderr·트레이스백) 원문이 카드에 그대로 노출돼, 운영자가
// "무엇을 눌러야 하는지"를 로그에서 직접 읽어내야 했다.
import { parseRenderError } from "@/lib/renderError";

export default function ErrorDisclosure({
  log,
  title = "렌더 실패",
}: {
  log: string | null | undefined;
  title?: string;
}) {
  const p = parseRenderError(log);
  return (
    <div className="banner-block" style={{ marginTop: 6 }} role="alert">
      <div>
        <b>⛔ {title}</b>
      </div>
      <div style={{ marginTop: 2 }}>원인: {p.cause}</div>
      <div>권장 조치: {p.action}</div>
      {log ? (
        <details style={{ marginTop: 6 }}>
          <summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>
            기술 로그 보기
          </summary>
          <pre className="raw-log">{log}</pre>
        </details>
      ) : null}
    </div>
  );
}
