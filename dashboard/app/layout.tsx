import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Japanese-RP-Bench v2",
  description: "日本語ロールプレイLLMの反復評価を比較するダッシュボード。",
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
