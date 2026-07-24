# Japanese-RP-Bench v2 OpenCode Go Minimum-Reasoning Results（2026-07-22）

> **旧384 tokenプロトコルの保存資料:** Reasoning設定は明示されていますが、対象出力上限が
> 384 tokenの旧計測です。途中打ち切りの影響があるため現行の正式順位には使いません。
> 現行結果は
> [`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
> を参照してください。下記コマンドが参照する追跡版configは後日更新されているため、
> 当時の成果物を厳密には再現しません。

## 実行条件

- Base: 元のSFWデータセット30設定、各10往復、従来8指標
- Base追加評価: 同じ会話に対する原子ルール、ターン別追従度、長期安定性
- Challenge: 追加Role Packの6シナリオ、計27ターン
- 対象: Kimi K3、GLM-5.2、Qwen3.7 Max、DeepSeek V4 Pro、MiniMax M3、MiMo-V2.5-Pro
- 対象API: OpenCode Go
- ユーザー役: GPT-5.4 mini、`reasoning: none`
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5、すべて`low`
- Gemini・Claude Judge: 各社のBatch API
- 対象の最大出力: 384 token
- 成果物: 216会話、1,962対象応答、216レポート

対象モデルのReasoning設定は次の通り。

| Target | API形式 | Reasoning設定 | 記録されたreasoning token |
|---|---|---|---:|
| Kimi K3 | OpenAI互換 | `reasoning_effort: none` | 0 |
| GLM-5.2 | OpenAI互換 | `reasoning_effort: none` | 0 |
| Qwen3.7 Max | Anthropic互換 | `thinking: {type: disabled}` | 0 |
| DeepSeek V4 Pro | OpenAI互換 | 受理可能な最小値`reasoning_effort: low` | 84,988 |
| MiniMax M3 | Anthropic互換 | `thinking: {type: disabled}` | 0 |
| MiMo-V2.5-Pro | OpenAI互換 | `reasoning_effort: none` | 0 |

方針と根拠は[`benchmark-v2.md`のReasoning policy](benchmark-v2.md#reasoning-policy)を参照。

## OpenCode Go 6モデルの結果

`旧8指標平均`は元ベンチと同じ8指標の平均（1〜5）、ほかはv2指標（0〜100）である。
`Eligible`は重大違反がなく、総合評価対象となったシナリオ数（全36件）を表す。

| Target | 旧8指標平均 | Core | Quality | Stability | Robustness | Recovery | Major | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.7 Max | 4.463 | 95.880 | 86.955 | 96.991 | 93.750 | 100.000 | 1 | 35 |
| MiniMax M3 | 4.158 | 92.679 | 80.206 | 95.833 | 100.000 | 100.000 | 2 | 34 |
| Kimi K3 | 4.013 | 90.394 | 76.845 | 86.690 | 100.000 | 100.000 | 6 | 31 |
| MiMo-V2.5-Pro | 3.997 | 84.150 | 76.091 | 92.070 | 62.500 | 100.000 | 14 | 26 |
| GLM-5.2 | 3.872 | 81.898 | 74.597 | 83.796 | 100.000 | 100.000 | 9 | 27 |
| DeepSeek V4 Pro | 3.720 | 82.378 | 69.075 | 78.829 | 81.250 | 87.500 | 13 | 23 |

Qwen3.7 Maxが会話品質、Core、QualityでOpenCode Go内の首位となった。MiniMax M3は
RobustnessとRecoveryがともに100で、重大違反も2件に抑えた。Kimi K3も攻撃耐性と復帰は
100だが、Base会話品質と長期安定性はQwen3.7 Max、MiniMax M3を下回る。

## 2026-07-21結果との差

旧実行はOpenCode GoへReasoning設定が転送されず、プロバイダー既定Reasoningかつ
最大出力1,024 tokenだった。今回はReasoningを明示し、最大出力を384 tokenへ統一している。
したがって、この差分はReasoningだけの因果効果ではなく、出力上限変更も含む実行条件差である。

| Target | 旧8指標平均 旧→新 | Core 旧→新 | Quality 旧→新 | Eligible 旧→新 |
|---|---:|---:|---:|---:|
| Qwen3.7 Max | 4.454 → 4.463 | 94.306 → 95.880 | 86.883 → 86.955 | 35 → 35 |
| MiniMax M3 | 4.240 → 4.158 | 92.106 → 92.679 | 81.999 → 80.206 | 30 → 34 |
| Kimi K3 | 4.435 → 4.013 | 93.790 → 90.394 | 85.514 → 76.845 | 33 → 31 |
| MiMo-V2.5-Pro | 4.136 → 3.997 | 88.476 → 84.150 | 79.761 → 76.091 | 27 → 26 |
| GLM-5.2 | 3.958 → 3.872 | 83.244 → 81.898 | 76.407 → 74.597 | 33 → 27 |
| DeepSeek V4 Pro | 4.344 → 3.720 | 92.133 → 82.378 | 83.628 → 69.075 | 29 → 23 |

## 使用量と費用

- 入力: 12,801,302 token
- 出力: 2,074,102 token
- reasoning: 124,564 token
- cached input: 5,826,063 token
- 定価換算合計: `$25.307`
- Batch割引反映後の推定合計: `$19.670`
  - OpenCode Go対象生成: `$7.527`相当
  - Judge・ユーザー役: 定価`$17.780`、Batch割引反映後`$12.143`相当

費用は成果物に保存された呼び出しから計算した推定値である。OpenCode Goは定額契約の
実支払額ではなくモデル別定価換算で、無料枠、データ共有特典、失敗要求の実請求は含まない。

## 完了性と評価方式

- manifest: `complete`
- failures: 0
- 各対象: 36/36レポート、全体216/216レポート
- 全レポートで同じ3 Judgeを使用
- Gemini Batch: 342/342判定を回収
- Claude Batch: 初回エラー66件、重複ルールを含んだ18判定、再度重複した1判定を個別再投入して完全化
- テスト: 28件成功

Claudeが同じ`rule_id`を複数回返した判定は不正として保存前に拒否し、不足した判定だけを
Batchへ再投入した。成功済みの対象生成、OpenAI Judge、Gemini Judge、Claude Judgeは再利用し、
再評価対象モデルの会話生成はやり直していない。

```bash
japanese-rp-bench-v2 run \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/benchmark-opencode-go-min-reasoning-batch-20260722 \
  --workers 2
```
