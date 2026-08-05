# Qwen3.8 Max Challenge反復評価追加計画（2026-08-05）

## 目的

現在の主結果である8モデルの反復評価へ、OpenCode GoのQwen3.8 Maxを比較可能な第9モデルとして
追加します。単回評価は公開せず、既存と同じChallenge 6シナリオを各10回生成します。

## 固定条件

- 対象: `qwen3.8-max`のみ
- API: OpenCode Go `anthropic_messages`
- Reasoning: `none`、`thinking.type=disabled`
- 対象出力上限: 4,096 token
- 反復: 10 block、各blockに6シナリオを1回ずつ含む
- 独立標本: 60会話
- 対象応答: 270
- Judge: Grok 4.5、Hy3、Qwen3.7 Plus
- Judge仕様: `challenge-judge-audit-v2.1`
- Judge出力: 810
- 自動的なZen残高fallback: 無効
- 旧8モデルの会話、Judge成果物、解析は変更しない

実行前に、登録標本へ含めない完全なblock 0をpilotとして実行します。対象本文、自然終了、Reasoning
payload、3 Judgeの構造化出力、v2.1ルーブリック記録がすべて揃った場合だけblock 1〜10へ進みます。

## 完了・公開条件

60会話、270対象応答、810 Judge出力が欠損0で揃うまで、READMEやダッシュボードへ追加しません。
完了後は、保存済み8モデルのv2.1解析とそのSHA-256を照合し、9モデルを同じ会話単位の階層
bootstrap、順位確率、全36ペア×8指標のHolm補正で再解析します。

機械可読な固定条件は
[`opencode_qwen38_repeatability_extension_2026-08-05.json`](../configs/opencode_qwen38_repeatability_extension_2026-08-05.json)
を正とします。
