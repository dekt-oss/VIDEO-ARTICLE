import type { Metadata } from "next";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { ToastProvider } from "@/components/Toast";

export const metadata: Metadata = {
  title: "video-article · 오늘의 후보",
  description: "하루 한 편 논문 선별·초안 시스템 + 하루 한 리포트",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <ToastProvider>
          <AppShell>{children}</AppShell>
        </ToastProvider>
      </body>
    </html>
  );
}
