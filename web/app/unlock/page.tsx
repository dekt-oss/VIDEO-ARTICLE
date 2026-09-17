"use client";

// /unlock — 운영자 키 1회 입력 화면. 로그인이 아니다(계정·이메일·매직링크 없음).
// 비용·발행 라우트(렌더 트리거·유튜브 업로드·초안/지시서 생성)만 이 키를 요구한다.
// globals.css 의 .login-box 스타일을 쓴다(로그인 제거 후 남아 있던 스타일의 실제 사용처).
import { useEffect, useState } from "react";

export default function UnlockPage() {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [state, setState] = useState<{ unlocked: boolean; enabled: boolean } | null>(null);

  useEffect(() => {
    fetch("/api/unlock")
      .then((r) => r.json())
      .then(setState)
      .catch(() => setState(null));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const res = await fetch("/api/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }).catch(() => null);
    setBusy(false);
    if (!res) {
      setMsg({ text: "네트워크 오류 — 연결을 확인하고 다시 시도하세요.", ok: false });
      return;
    }
    const body = await res.json().catch(() => null);
    if (res.ok) {
      setKey("");
      setState({ unlocked: true, enabled: true });
      setMsg({ text: "잠금이 해제됐습니다. 이 기기에서는 180일간 다시 묻지 않습니다.", ok: true });
      // 미들웨어가 막아서 온 경우 원래 가려던 곳으로 돌려보낸다(?next=…).
      // 열린 리다이렉트를 막으려고 **같은 사이트의 절대경로만** 허용한다.
      const next = new URLSearchParams(window.location.search).get("next");
      // ★ `/\evil.com` 은 브라우저가 `//evil.com` 으로 읽는다 — 역슬래시·제어문자가 있으면 버린다(2026-09-15).
      if (next && next.startsWith("/") && !next.startsWith("//") && !/[\\\x00-\x1f]/.test(next)) {
        window.location.replace(next);
      }
    } else {
      setMsg({ text: body?.error ?? `실패(${res.status})`, ok: false });
    }
  }

  return (
    <main className="container">
      <div className="login-box">
        <h1 style={{ fontSize: 20 }}>운영자 잠금 해제</h1>
        <p className="muted" style={{ textAlign: "left" }}>
          <b>사이트 전체가 이 키로 잠겨 있습니다.</b> 저장소를 공개로 전환하면서 대시보드
          주소도 드러나기 때문입니다(2026-09-05). 기기당 한 번만 입력하면 180일간 묻지 않습니다.
          로그인이 아니라 열쇠 하나입니다 — 계정·이메일이 없습니다.
        </p>

        {state?.enabled === false && (
          <div className="banner-warn" style={{ textAlign: "left" }}>
            서버에 <code>OPERATOR_KEY</code> 가 설정되지 않았습니다. 이 상태에서는{" "}
            <b>사이트 전체가 잠깁니다</b> — 미들웨어가 키 없이는 통과시키지 않기 때문입니다.
            Vercel 환경변수에 <code>OPERATOR_KEY</code> 를 추가하고 재배포하세요.
          </div>
        )}
        {state?.unlocked && state?.enabled && (
          <div className="banner-ok" style={{ textAlign: "left" }}>✓ 이 기기는 이미 잠금 해제 상태입니다.</div>
        )}

        <form onSubmit={submit}>
          <input
            type="password"
            value={key}
            placeholder="운영자 키"
            autoComplete="current-password"
            onChange={(e) => setKey(e.target.value)}
            disabled={busy}
          />
          <button className="btn pick" type="submit" disabled={busy || !key.trim()}>
            {busy ? "확인 중…" : "잠금 해제"}
          </button>
        </form>

        {msg && (
          <div className={msg.ok ? "banner-ok" : "banner-warn"} style={{ textAlign: "left" }}>
            {msg.text}
          </div>
        )}

        <p className="muted" style={{ marginTop: 16 }}>
          {/* ★ 여기만 <Link> 가 아니다. 이 화면은 **게이트 상태 자체가 바뀌는** 자리다.
              소프트 내비게이션은 클라이언트 라우터 캐시를 탈 수 있어, 잠금이 풀린 뒤에도
              풀리기 전 화면이 보일 여지가 있다. 게이트 화면에서는 전체 새로고침이 맞다.
              성공 경로도 같은 이유로 window.location.replace 를 쓴다(위 45줄). */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/">← 오늘의 후보로</a>
        </p>
      </div>
    </main>
  );
}
