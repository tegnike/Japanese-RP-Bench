# Japanese-RP-Bench v2

日本語ロールプレイLLMの会話品質だけでなく、キャラクター設定への追従性、長期安定性、
人格置換への耐性、誤誘導後の復帰まで測定するベンチマークです。

このリポジトリは[Aratako/Japanese-RP-Bench](https://github.com/Aratako/Japanese-RP-Bench)の
フォークです。元の30ロール・10往復・従来8指標をBaseとして維持し、その上にv2評価を
追加しています。フォーク元の説明、2024年の32モデル結果、旧実行方法は
[`docs/upstream-v1.md`](docs/upstream-v1.md)へ保存しています。

## 目的別に読む

| 目的 | 文書 |
|---|---|
| 最新の正式結果を見る | [2026-07-24 全11モデル完了記録](docs/benchmark-v2-production-status-2026-07-24.md) |
| 指標と順位の意味を確認する | [指標定義](docs/metrics.md) |
| 正式条件で再実行する | [正式計測プロトコル](docs/benchmark-v2-production-protocol.md)と[設定ファイル案内](configs/README.md) |
| Role Packを作る | [Role Pack作成ガイド](role_packs/README.md) |
| 評価条件の変更履歴や旧結果を調べる | [評価履歴・監査資料](docs/evaluation-history.md) |
| 固有用語を確認する | [用語集](docs/README.md#用語集) |

## v2で測るもの

- `core_fidelity_score`: キャラクターの核となるルールへの追従性
- `conversation_quality_score`: 自然さ、表現力、創造性、会話の楽しさ
- `long_term_stability_score`: 対話序盤から終盤までの設定維持
- `robustness_score`: 人格置換、引用内命令、偽記憶、代理行動への耐性
- `recovery_score`: 攻撃や誤誘導の後に元の人格へ戻れるか
- `major_violations`: 人格の核に関わる重大ルール違反

会話品質が高くても重大な人格逸脱を相殺しません。各指標を分けて出力した上で、正式順位は
重大違反ゲートを優先し、同条件内だけ5つのv2指標の単純平均で比較します。各指標と順位の
意味、算出式、BaseとChallengeの違いは
[`docs/metrics.md`](docs/metrics.md)、ベンチマーク全体の設計は
[`docs/benchmark-v2.md`](docs/benchmark-v2.md)を参照してください。

正式計測の固定条件と再現手順は
[`docs/benchmark-v2-production-protocol.md`](docs/benchmark-v2-production-protocol.md)へ
集約しています。

## 最新の正式結果

2026-07-24時点で、11モデルすべてが同じ正式プロトコルによる36シナリオと3 Judgeの
評価を完了しています。

`RP Balance`はCore、Quality、Stability、Robustness、Recoveryの単純平均です。正式順位は
`Eligible`降順、`Major`昇順、`RP Balance`降順、最後に旧8指標平均降順で決めます。
Majorは重大違反の総件数、Eligibleは重大違反がなかったシナリオ数です。
この順位は比較の入口として設けた便宜的な並びであり、モデルの絶対的な優劣を示すものでは
ありません。実際の用途に合わせて、表中の各スコアとシナリオ別レポートも確認してください。

| Rank | Target | RP Balance | Eligible | Major | 旧8指標平均 | Core | Quality | Stability | Robustness | Recovery |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | GPT-5.4 mini | 96.660 | 35/36 | 1 | 4.425 | 99.054 | 86.328 | 97.917 | 100.000 | 100.000 |
| 2 | GPT-5.6 Sol | 95.970 | 35/36 | 1 | 4.455 | 95.718 | 86.910 | 97.222 | 100.000 | 100.000 |
| 3 | Gemini 3.6 Flash | 95.101 | 35/36 | 1 | 4.381 | 95.833 | 85.460 | 94.213 | 100.000 | 100.000 |
| 4 | Qwen3.7 Max | 93.691 | 35/36 | 2 | 4.403 | 95.532 | 85.699 | 97.639 | 93.750 | 95.833 |
| 5 | Kimi K3 | 90.861 | 34/36 | 3 | 4.107 | 93.383 | 79.786 | 87.384 | 93.750 | 100.000 |
| 6 | Gemini 3.5 Flash | 89.490 | 32/36 | 10 | 4.374 | 94.120 | 85.045 | 93.287 | 75.000 | 100.000 |
| 7 | DeepSeek V4 Pro | 94.216 | 31/36 | 5 | 4.347 | 93.380 | 84.877 | 92.824 | 100.000 | 100.000 |
| 8 | MiniMax M3 | 93.206 | 31/36 | 5 | 4.109 | 91.782 | 79.458 | 94.792 | 100.000 | 100.000 |
| 9 | GLM-5.2 | 90.637 | 31/36 | 5 | 3.879 | 81.782 | 74.877 | 96.528 | 100.000 | 100.000 |
| 10 | MiMo V2.5 Pro | 87.561 | 29/36 | 7 | 4.096 | 85.516 | 79.039 | 93.042 | 84.375 | 95.833 |
| 11 | Claude Haiku 4.5 | 90.906 | 25/36 | 16 | 4.058 | 87.272 | 78.464 | 90.880 | 97.916 | 100.000 |

## 現在の評価プロトコル

- Base: 元のSFWデータセット30設定 × 10往復 × 従来8指標
- Base追加評価: 原子ルール、ターン別追従度、長期安定性
- Challenge: 4種類のRole Pack、6シナリオ、計27ターン
- ユーザー役: GPT-5.4 mini
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Judgeには評価対象モデル名を渡さないブラインド評価
- API: OpenAI、Google Gemini、Anthropic、OpenCode Go
- 会話と評価は逐次保存し、不足分だけ再開可能

Challengeでは、人格置換、引用文中の命令、存在しない共有記憶、ユーザー代理行動、
12ターンの設定維持、AIニケちゃん固有の関係性維持などを測定します。

過去の試行、評価条件を変更した理由、旧結果の扱いは
[評価履歴・監査資料](docs/evaluation-history.md)へ分離して保存しています。

## インストールと実行

Python 3.10以降が必要です。

```bash
git clone https://github.com/tegnike/Japanese-RP-Bench.git
cd Japanese-RP-Bench
pip install -e .
```

正式条件の全量実行は複数の有料APIを使用し、Batchは完了まで時間がかかる場合があります。
必ず先にpilotを実行し、予算、開始条件、失敗時の扱いを
[`docs/benchmark-v2-production-protocol.md`](docs/benchmark-v2-production-protocol.md)で
確認してください。現行設定と履歴用設定の違いは[`configs/README.md`](configs/README.md)に
まとめています。

APIキーは設定ファイルへ書かず、利用するプロバイダーの環境変数へ設定します。

```bash
export OPENAI_API_KEY=...
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=...

japanese-rp-bench-v2 pilot \
  --config configs/benchmark_full.yaml \
  --output tmp/pilot-full \
  --workers 4

japanese-rp-bench-v2 run \
  --config configs/benchmark_full.yaml \
  --output tmp/benchmark-full \
  --pilot-report tmp/pilot-full/pilot-report.json \
  --workers 4
```

OpenCode Go対象を実行する場合は`OPENCODE_GO_API_KEY`も設定します。

```bash
export OPENCODE_GO_API_KEY=...

japanese-rp-bench-v2 pilot \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/pilot-opencode-go \
  --workers 2

japanese-rp-bench-v2 run \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/benchmark-opencode-go \
  --pilot-report tmp/pilot-opencode-go/pilot-report.json \
  --workers 2
```

出力上限、Batch、再開条件などの正式な実行仕様は
[`docs/benchmark-v2-production-protocol.md`](docs/benchmark-v2-production-protocol.md)、
OpenCode Go固有の接続方法は[`docs/opencode-go.md`](docs/opencode-go.md)を参照してください。

## Role Pack

役柄、シナリオ、判定ルールは評価コードから分離したYAMLパッケージです。

- `core-ja`: 実務的メンター、ファンタジー案内人
- `adversarial-ja`: 引用内命令、人格置換、ユーザー代理行動
- `long-horizon-ja`: 12ターンでの人格、関係性、会話内事実の維持
- `custom/nikechan`: AIニケちゃん固有の人格追従性

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.cli validate role_packs/core-ja
```

Role Packの構造と作成方法は[`role_packs/README.md`](role_packs/README.md)にあります。

## ライセンス

[MIT License](LICENSE)
