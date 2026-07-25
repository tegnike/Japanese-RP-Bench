import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Japanese-RP-Bench v2",
  description: "日本語ロールプレイLLMの最新正式結果を比較するローカルダッシュボード。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
