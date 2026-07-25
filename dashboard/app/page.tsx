import type { Metadata } from "next";
import { Dashboard } from "./dashboard";

export const metadata: Metadata = {
  title: "Japanese-RP-Bench v2 — 最新ベンチマーク",
  description:
    "日本語ロールプレイLLMの最新正式結果を、人格維持・会話品質・長期安定性・攻撃耐性・復帰力で比較できます。",
};

export default function Home() {
  return <Dashboard />;
}
