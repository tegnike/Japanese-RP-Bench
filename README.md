# Japanese-RP-Bench v2

日本語ロールプレイLLMの会話品質だけでなく、キャラクター設定への追従性、長期安定性、
人格置換への耐性、誤誘導後の復帰まで測定するベンチマークです。

このリポジトリは[Aratako/Japanese-RP-Bench](https://github.com/Aratako/Japanese-RP-Bench)の
フォークです。元の30ロール・10往復・従来8指標をBaseとして維持し、その上にv2評価を
追加しています。フォーク元の説明、2024年の32モデル結果、旧実行方法は
[`docs/upstream-v1.md`](docs/upstream-v1.md)へ保存しています。

## v2で測るもの

- `core_fidelity_score`: キャラクターの核となるルールへの追従性
- `conversation_quality_score`: 自然さ、表現力、創造性、会話の楽しさ
- `long_term_stability_score`: 対話序盤から終盤までの設定維持
- `robustness_score`: 人格置換、引用内命令、偽記憶、代理行動への耐性
- `recovery_score`: 攻撃や誤誘導の後に元の人格へ戻れるか
- `major_violations`: 人格の核に関わる重大ルール違反

会話品質が高くても重大な人格逸脱を相殺しません。根拠のない重み付き総合点は定義せず、
各指標を分けて出力します。各指標の意味、算出式、BaseとChallengeの違いは
[`docs/metrics.md`](docs/metrics.md)、ベンチマーク全体の設計は
[`docs/benchmark-v2.md`](docs/benchmark-v2.md)を参照してください。

11モデル正式計測で固定したtoken上限、Reasoning、Batch wave、失敗時の扱い、
pilot合格条件、予算、一次資料は
[`docs/benchmark-v2-production-protocol.md`](docs/benchmark-v2-production-protocol.md)へ集約しています。
2026-07-24の全11モデル完了結果、途中失敗、Kimiの課金経路調査、費用、決定事項は
[`docs/benchmark-v2-production-status-2026-07-24.md`](docs/benchmark-v2-production-status-2026-07-24.md)
に記録しています。前日までの経緯は
[`docs/benchmark-v2-production-status-2026-07-23.md`](docs/benchmark-v2-production-status-2026-07-23.md)
へ保存しています。

## 正式再評価の現在地

384 token問題を修正した正式プロトコルで再評価し、11モデルすべてが36/36シナリオと
3 Judgeを完了しました。GPT-5.6 SolとKimi K3は、評価パイプライン修正後に新しいpilotと
空の出力先から再実行しています。不完全だった旧成果物は0点、最下位、部分平均として
混ぜていません。

表は順位ではなく当初の経路順です。旧8指標平均は1〜5、v2指標は0〜100です。Majorは重大
違反シナリオ数、Eligibleは重大違反ゲート通過数です。重み付き総合点は定義しません。

| Target | 旧8指標平均 | Core | Quality | Stability | Robustness | Recovery | Major | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | 4.455 | 95.718 | 86.910 | 97.222 | 100.000 | 100.000 | 1 | 35/36 |
| GPT-5.4 mini | 4.425 | 99.054 | 86.328 | 97.917 | 100.000 | 100.000 | 1 | 35/36 |
| Gemini 3.5 Flash | 4.374 | 94.120 | 85.045 | 93.287 | 75.000 | 100.000 | 10 | 32/36 |
| Gemini 3.6 Flash | 4.381 | 95.833 | 85.460 | 94.213 | 100.000 | 100.000 | 1 | 35/36 |
| Claude Haiku 4.5 | 4.058 | 87.272 | 78.464 | 90.880 | 97.916 | 100.000 | 16 | 25/36 |
| GLM-5.2 | 3.879 | 81.782 | 74.877 | 96.528 | 100.000 | 100.000 | 5 | 31/36 |
| Qwen3.7 Max | 4.403 | 95.532 | 85.699 | 97.639 | 93.750 | 95.833 | 2 | 35/36 |
| DeepSeek V4 Pro | 4.347 | 93.380 | 84.877 | 92.824 | 100.000 | 100.000 | 5 | 31/36 |
| MiniMax M3 | 4.109 | 91.782 | 79.458 | 94.792 | 100.000 | 100.000 | 5 | 31/36 |
| MiMo V2.5 Pro | 4.096 | 85.516 | 79.039 | 93.042 | 84.375 | 95.833 | 7 | 29/36 |
| Kimi K3 | 4.107 | 93.383 | 79.786 | 87.384 | 93.750 | 100.000 | 3 | 34/36 |

GPT-5.6の旧35/36成果物とKimiの途中成果物は監査履歴として残し、正式値には使っていません。
Kimi型の同期429では、成功済み要求を保持しながら失敗要求だけを`4 → 2 → 1`へ並列度を
下げて再開します。今回の最終Kimi runは327/327 target turnを完了し、429は0件でした。

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

## 旧計測の監査資料

384 token条件の旧結果は、途中打ち切りの影響があるため正式比較には使いません。READMEには
正式11モデル結果だけを掲載し、旧条件の表、使用量、費用、当時の判断は次の資料へ保存します。

- [384 token問題の発見と正式再評価の判断記録](docs/benchmark-v2-production-status-2026-07-23.md)
- [OpenAI・Google・Anthropic 5モデルの旧結果](docs/full-results-openai-user-2026-07-20.md)
- [OpenCode Go 6モデルの旧最小Reasoning結果](docs/opencode-go-results-2026-07-22.md)
- [OpenCode Go 6モデルの旧provider既定Reasoning結果](docs/opencode-go-results-2026-07-21.md)
- [旧Geminiユーザー役による比較実行](docs/full-results-2026-07-20.md)
- [初回pilotと評価器監査](docs/pilot-results-2026-07-20.md)

## インストールと実行

Python 3.10以降が必要です。

```bash
git clone https://github.com/tegnike/Japanese-RP-Bench.git
cd Japanese-RP-Bench
pip install -e .
```

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

対象は4,096 token、動的ユーザー役は2,048 token、Challenge Judgeは4,096 token、
Base Judgeは8,192 tokenへ分離しています。OpenAI、Gemini、Anthropicは会話生成とJudgeを
Batch APIで実行し、ターン依存の会話はwave単位で保存します。途中で停止しても、同じ設定と
出力先で再実行すれば、送信済みBatchと保存済みの会話・評価を追跡して再開します。
必要な資格情報は最初の送信前に一括検査し、1つでも不足していればリクエストを送信しません。
OpenCode Goの接続方法と有料Judgeの呼び出し制御は
[`docs/opencode-go.md`](docs/opencode-go.md)を参照してください。

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

## フォーク元の保存資料

元実装と公開済み成果物は削除せず保持しています。

- [フォーク元README保存版](docs/upstream-v1.md)
- [旧32モデルの会話](conversations)
- [旧32モデルの評価結果](evaluations)
- [2024年版を再集計する方法](docs/benchmark-v2.md#2024年版との比較)

## ライセンス

[MIT License](LICENSE)
