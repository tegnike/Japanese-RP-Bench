# Japanese-RP-Bench v2 OpenCode Go Results（2026-07-21）

## 実行条件

- Base: 元のSFWデータセット30設定、各10往復、従来8指標
- Base追加評価: 同じ会話に対する原子ルール、ターン別追従度、長期安定性
- Challenge: 追加Role Packの6シナリオ、計27ターン
- 対象: Kimi K3、GLM-5.2、Qwen3.7 Max、DeepSeek V4 Pro、MiniMax M3、MiMo-V2.5-Pro
- 対象API: OpenCode Go
- ユーザー役: GPT-5.4 mini
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Judgeは評価対象モデル名を渡さないブラインド評価
- 成果物: 216会話、1,962対象応答、1,026 Judge判定、216レポート

ユーザー役、Judge、Baseデータセット、Role Pack、採点・集計処理は
[`full-results-openai-user-2026-07-20.md`](full-results-openai-user-2026-07-20.md)と共通である。
OpenCode Goモデルだけを評価対象へ追加している。

## OpenCode Go 6モデルの結果

`旧8指標平均`は元ベンチと同じ8指標の平均（1〜5）、ほかはv2指標（0〜100）である。
`Eligible`は重大違反がなく、総合評価対象となったシナリオ数（全36件）を表す。

| Target | 旧8指標平均 | Core fidelity | Quality | Stability | Robustness | Recovery | Major violations | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.7 Max | 4.454 | 94.306 | 86.883 | 96.296 | 87.500 | 100.000 | 1 | 35 |
| Kimi K3 | 4.435 | 93.790 | 85.514 | 92.278 | 100.000 | 100.000 | 3 | 33 |
| DeepSeek V4 Pro | 4.344 | 92.133 | 83.628 | 91.157 | 100.000 | 95.833 | 7 | 29 |
| MiniMax M3 | 4.240 | 92.106 | 81.999 | 96.528 | 100.000 | 100.000 | 6 | 30 |
| MiMo-V2.5-Pro | 4.136 | 88.476 | 79.761 | 91.435 | 93.750 | 100.000 | 11 | 27 |
| GLM-5.2 | 3.958 | 83.244 | 76.407 | 89.236 | 81.250 | 100.000 | 3 | 33 |

この6モデルではQwen3.7 Maxが旧8指標平均、Core fidelity、Qualityで首位だった。
Kimi K3はRobustnessとRecoveryがともに100で、旧8指標平均もQwen3.7 Maxに次ぐ。
DeepSeek V4 ProとMiniMax M3はCore fidelityがほぼ同等だが、MiniMax M3は長期安定性、
DeepSeek V4 Proは旧8指標平均で上回った。

## 既存OpenAI・Google・Anthropic対象との比較

比較対象は、同じGPT-5.4 miniユーザー役と同じ3 Judgeで取得した2026-07-20完全版である。

| Target | Provider | 旧8指標平均 | Core fidelity | Quality | Stability | Robustness | Recovery | Major violations |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | OpenAI | 4.549 | 96.647 | 88.549 | 95.949 | 100.000 | 100.000 | 0 |
| Qwen3.7 Max | OpenCode Go | 4.454 | 94.306 | 86.883 | 96.296 | 87.500 | 100.000 | 1 |
| GPT-5.4 mini | OpenAI | 4.446 | 96.991 | 86.022 | 96.759 | 100.000 | 100.000 | 0 |
| Kimi K3 | OpenCode Go | 4.435 | 93.790 | 85.514 | 92.278 | 100.000 | 100.000 | 3 |
| Gemini 3.1 Flash-Lite | Google | 4.432 | 95.602 | 86.293 | 94.583 | 82.291 | 95.833 | 2 |
| Gemini 3.5 Flash | Google | 4.399 | 93.502 | 84.998 | 90.959 | 62.500 | 95.833 | 8 |
| DeepSeek V4 Pro | OpenCode Go | 4.344 | 92.133 | 83.628 | 91.157 | 100.000 | 95.833 | 7 |
| MiniMax M3 | OpenCode Go | 4.240 | 92.106 | 81.999 | 96.528 | 100.000 | 100.000 | 6 |
| MiMo-V2.5-Pro | OpenCode Go | 4.136 | 88.476 | 79.761 | 91.435 | 93.750 | 100.000 | 11 |
| Claude Haiku 4.5 | Anthropic | 4.096 | 88.059 | 78.705 | 90.278 | 90.625 | 100.000 | 8 |
| GLM-5.2 | OpenCode Go | 3.958 | 83.244 | 76.407 | 89.236 | 81.250 | 100.000 | 3 |

Qwen3.7 Maxは旧8指標平均でGPT-5.4 miniとGemini 3.1 Flash-Liteをわずかに上回り、
Kimi K3も同水準だった。一方、Core fidelityではGPT-5.6 Sol、GPT-5.4 mini、
Gemini 3.1 Flash-Liteが上位であり、会話品質と厳密な人格追従性は分けて見る必要がある。

## 使用量と費用

- 入力: 13,045,032 token
- 出力: 2,758,288 token（うちreasoningとして明示されたもの189,087 token）
- cached input: 6,086,417 token
- 定価換算合計: `$30.380`
  - OpenCode Go対象生成: `$11.920`相当
  - OpenAI Judgeとユーザー役: `$6.944`相当
  - Gemini・Anthropic Judge: `$11.516`相当

OpenCode Go対象生成の金額はモデル別定価に基づく比較値であり、定額契約の実支払額ではない。
成功成果物に記録された呼び出しから算出しているため、APIが生成前に拒否した要求や、
不正JSONなどで成果物へ採用されなかった応答が請求対象の場合は実請求と一致しない。

## 完了性と評価方式

- manifest: `complete`
- failures: 0
- 各対象: 36/36レポート、全体216/216レポート
- MiMo-V2.5-Pro: 36/36、各評価のJudge数・ターン網羅性に不一致0
- 全レポートで同じ3 Judgeを使用
- テスト: 25件成功
- APIキーのリポジトリ混入: 0件

GeminiとAnthropicのJudgeは、無駄な有料再実行を避けるため1要求につき自動呼び出し1回とし、
成功済み評価を再開時に再利用する。JudgeのJSONは構造化出力で制約し、ClaudeのBase評価は
10ターンを欠落させない固定キー形式を使う。これは対象モデルによる分岐ではなく、
すべての対象へ共通するJudgeプロバイダー別の転送形式であり、採点項目と集計方法は同じである。

```bash
japanese-rp-bench-v2 run \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/benchmark-opencode-go-20260721 \
  --workers 2
```
