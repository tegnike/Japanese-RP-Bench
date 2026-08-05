import type { Metadata } from "next";
import { Dashboard } from "./dashboard";

export const metadata: Metadata = {
  title: "Japanese-RP-Bench v2 — 反復評価",
  description:
    "8モデル・480会話の日本語ロールプレイ反復評価を、95%区間や順位確率とともに比較できます。",
};

export default function Home() {
  return <Dashboard />;
}
