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

## 最新結果

同じGPT-5.4 miniユーザー役と同じ3 Judgeで評価した11モデルの比較です。
`旧8指標平均`は1〜5、ほかは0〜100です。

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

実行条件、モデル別内訳、token使用量、費用、比較上の注意は以下に記録しています。

- [OpenCode Go 6モデル結果と11モデル比較](docs/opencode-go-results-2026-07-21.md)
- [OpenAI・Google・Anthropic 5モデル完全版](docs/full-results-openai-user-2026-07-20.md)
- [旧Geminiユーザー役による比較実行](docs/full-results-2026-07-20.md)
- [初回パイロットと評価器監査](docs/pilot-results-2026-07-20.md)

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

japanese-rp-bench-v2 run \
  --config configs/benchmark_full.yaml \
  --output tmp/benchmark-full \
  --workers 4
```

OpenCode Go対象を実行する場合は`OPENCODE_GO_API_KEY`も設定します。

```bash
export OPENCODE_GO_API_KEY=...

japanese-rp-bench-v2 run \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/benchmark-opencode-go \
  --workers 2
```

途中で停止しても、同じ設定と出力先で再実行すれば保存済みの会話・評価を再利用します。
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
