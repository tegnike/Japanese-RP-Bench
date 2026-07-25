# Japanese-RP-Bench v2

日本語ロールプレイLLMの会話品質だけでなく、役柄への追従性、人格安定性、
人格置換への耐性、誤誘導後の復帰まで測定するベンチマークです。

このリポジトリは[Aratako/Japanese-RP-Bench](https://github.com/Aratako/Japanese-RP-Bench)の
フォークです。元の30ロール・10往復・従来8指標をBaseとして維持し、その上にv2評価を
追加しています。フォーク元の説明、2024年の32モデル結果、旧実行方法は
[`docs/upstream-v1.md`](docs/upstream-v1.md)へ保存しています。

## v2で測るもの

- `role_fidelity_score`: 人格、設定、関係性、知識境界、口調などのルールへの追従性
- `conversation_quality_score`: 自然さ、表現力、創造性、会話の楽しさ
- `persona_stability_score`: 対話の進行に伴う人格・設定追従度の低下
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

2026-07-25時点で、15モデルが正式プロトコルによる36シナリオと3 Judgeの評価を
完了しています。GPT-5.6 TerraとGPT-5.6 Luna、Claude Opus 5、Claude Sonnet 5は、OpenAI経路を
通常API、ClaudeとGemini経路をBatch APIに固定した追加shardとして計測しました。

Claude Fable 5も同じ条件でpilotに合格しました。Base 2ターン目の本文なし`cyber` refusalを
同一条件で合計5回まで再試行しましたが、すべて拒否されたため該当シナリオだけを除外し、
残り35/36シナリオを参考評価として完了しました。正式順位とモデル数には含めません。

### 結果ダッシュボード

最新の正式結果は、同梱の[`dashboard`](dashboard)でグラフ表示できます。RP Summary、
役柄追従度、会話品質、人格安定性、攻撃耐性、復帰力を切り替え、モデルごとのトラック別結果や
旧8指標の内訳まで確認できます。

[公開中の結果ダッシュボード](https://japanese-rp-bench.tegnike.chatgpt.site/)から、
ブラウザですぐに確認できます。

```bash
cd dashboard
npm install
npm run dev
```

`RP Summary`はRole Fidelity、Quality、Persona Stability、Robustness、Recoveryの単純平均です。
BaseのQualityは旧8指標平均を正規化した値なので、RP Summaryは旧8指標を間接的に含みます。
正式順位は`Major-free`降順、`Major`昇順、`RP Summary`降順、最後に旧8指標平均降順で決めます。
Majorは重大違反の総件数、Major-freeは重大違反がなかったシナリオ数です。
この順位は比較の入口として設けた便宜的な並びであり、モデルの絶対的な優劣を示すものでは
ありません。実際の用途に合わせて、表中の各スコアとシナリオ別レポートも確認してください。

| Rank | Target | RP Summary | Major-free | Major | 旧8指標平均 | Role Fidelity | Quality | Persona Stability | Robustness | Recovery |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | GPT-5.6 Luna | 96.074 | 36/36 | 0 | 4.453 | 96.551 | 87.062 | 96.759 | 100.000 | 100.000 |
| 2 | GPT-5.4 mini | 96.660 | 35/36 | 1 | 4.425 | 99.054 | 86.328 | 97.917 | 100.000 | 100.000 |
| 3 | GPT-5.6 Sol | 95.970 | 35/36 | 1 | 4.455 | 95.718 | 86.910 | 97.222 | 100.000 | 100.000 |
| 4 | Gemini 3.6 Flash | 95.101 | 35/36 | 1 | 4.381 | 95.833 | 85.460 | 94.213 | 100.000 | 100.000 |
| 5 | Qwen3.7 Max | 93.691 | 35/36 | 2 | 4.403 | 95.532 | 85.699 | 97.639 | 93.750 | 95.833 |
| 6 | Claude Opus 5 | 95.559 | 34/36 | 2 | 4.507 | 95.278 | 88.537 | 93.981 | 100.000 | 100.000 |
| 7 | GPT-5.6 Terra | 93.817 | 34/36 | 3 | 4.514 | 97.226 | 88.178 | 96.181 | 87.500 | 100.000 |
| 8 | Kimi K3 | 90.861 | 34/36 | 3 | 4.107 | 93.383 | 79.786 | 87.384 | 93.750 | 100.000 |
| 9 | Gemini 3.5 Flash | 89.490 | 32/36 | 10 | 4.374 | 94.120 | 85.045 | 93.287 | 75.000 | 100.000 |
| 10 | DeepSeek V4 Pro | 94.216 | 31/36 | 5 | 4.347 | 93.380 | 84.877 | 92.824 | 100.000 | 100.000 |
| 11 | MiniMax M3 | 93.206 | 31/36 | 5 | 4.109 | 91.782 | 79.458 | 94.792 | 100.000 | 100.000 |
| 12 | GLM-5.2 | 90.637 | 31/36 | 5 | 3.879 | 81.782 | 74.877 | 96.528 | 100.000 | 100.000 |
| 13 | Claude Sonnet 5 | 92.984 | 29/36 | 7 | 4.290 | 92.593 | 83.669 | 88.657 | 100.000 | 100.000 |
| 14 | MiMo V2.5 Pro | 87.561 | 29/36 | 7 | 4.096 | 85.516 | 79.039 | 93.042 | 84.375 | 95.833 |
| 15 | Claude Haiku 4.5 | 90.906 | 25/36 | 16 | 4.058 | 87.272 | 78.464 | 90.880 | 97.916 | 100.000 |
| - | Claude Fable 5 | 95.645※ | 31/35※ | 4※ | 4.493※ | 93.714※ | 88.082※ | 96.429※ | 100.000 | 100.000 |

※ Claude Fable 5は`legacy_case_01`の2ターン目で本文なしの`cyber` refusalが5回続いたため、
この1シナリオだけ未取得・除外した。欠損元は1件だけだが、このBaseシナリオを集計対象にする
RP Summary、Major-free、Major、旧8指標平均、Role Fidelity、Quality、Persona Stabilityは
残り35/36シナリオ
（旧8指標平均は29/30設定）から計算した参考値となるため※を付けた。Challengeだけから計算する
RobustnessとRecoveryは欠損の影響を受けない。正式順位は`-`としている。5回の拒否記録、
除外方法、費用は
[追加評価記録](docs/claude-fable-5-results-2026-07-25.md)を参照してください。

## 現在の評価プロトコル

- Base: 元のSFWデータセット30設定 × 10往復 × 従来8指標
- Base追加評価: 原子ルール、ターン別追従度、人格安定性
- Challenge: 4種類のRole Pack、6シナリオ、計27ターン
- ユーザー役: GPT-5.4 mini
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Judgeには評価対象モデル名を渡さないブラインド評価
- API: OpenAI、Google Gemini、Anthropic、OpenCode Go
- 会話と評価は逐次保存し、不足分だけ再開可能

Challengeでは、人格置換、引用文中の命令、存在しない共有記憶、ユーザー代理行動、
12ターンの設定維持、AIニケちゃん固有の関係性維持などを測定します。

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
- `multi-turn-ja`: 12ターンでの人格、関係性、会話内事実の維持
- `custom/nikechan`: AIニケちゃん固有の人格追従性

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.cli validate role_packs/core-ja
```

Role Packの構造と作成方法は[`role_packs/README.md`](role_packs/README.md)にあります。

## 関連ドキュメント

### 結果と指標を詳しく読む

[GPT-5.6 Terra・Luna追加評価記録](docs/gpt-5.6-terra-luna-results-2026-07-25.md)、
[Claude Fable 5追加評価記録](docs/claude-fable-5-results-2026-07-25.md)、
[Claude Sonnet 5追加評価記録](docs/claude-sonnet-5-results-2026-07-25.md)と
[Claude Opus 5追加評価記録](docs/claude-opus-5-results-2026-07-25.md)には、追加shardの
完了状態、実行費用、停止理由または重大違反、成果物とSHA-256を記録しています。先行11モデルの
出典は[全11モデル完了記録](docs/benchmark-v2-production-status-2026-07-24.md)にあります。

[指標定義](docs/metrics.md)では、Role Fidelity、Quality、Persona Stability、Robustness、Recovery、
Major、Major-free、RP Summary、旧8指標について、意味、計算式、値の読み方、
BaseとChallengeでの違いを説明しています。

### 設計と実行条件を確認する

[v2設計概要](docs/benchmark-v2.md)は、BaseとChallenge、Role Pack、成果物、対応する
providerなど、ベンチマーク全体の構成を説明する文書です。

[正式計測プロトコル](docs/benchmark-v2-production-protocol.md)は、モデル、出力上限、
Reasoning、pilot、停止・再開・公開条件を固定する基準文書です。正式結果を再現するときは、
[設定ファイル案内](configs/README.md)で現行設定と履歴用設定を区別して使用してください。
OpenCode Go経由で実行する場合の接続方法と注意点は
[OpenCode Go実行ガイド](docs/opencode-go.md)にまとめています。

### 拡張方法、用語、履歴を調べる

[Role Pack作成ガイド](role_packs/README.md)では、YAMLの構造、各フィールド、原子ルール、
Probe、作成手順、検証方法を説明しています。

[ドキュメント案内・用語集](docs/README.md)は、リポジトリ内の文書を分類し、`track`、
`pilot`、`fingerprint`など、このプロジェクト固有の用語を定義しています。

[評価履歴・監査資料](docs/evaluation-history.md)には、過去の試行、評価条件を変更した理由、
旧結果の扱いを時系列で保存しています。フォーク元の説明、2024年の結果、旧実行方法は
[フォーク元v1保存版](docs/upstream-v1.md)で確認できます。

## ライセンス

[MIT License](LICENSE)
