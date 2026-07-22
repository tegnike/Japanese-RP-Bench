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
一つの総合順位へ潰すとモデルごとの長所と弱点が隠れるため、Base会話品質とv2追従性を
分けて掲載します。旧8指標は1〜5、v2スコアは0〜100です。Major violationsは少ないほど、
Eligibleは多いほど良い値です。

> **OpenCode Go結果のReasoning条件:** 以下のOpenCode Go 6モデルは2026-07-22に
> [最小Reasoning方針](docs/benchmark-v2.md#reasoning-policy)で再評価した結果です。
> Kimi K3、GLM-5.2、MiMo V2.5 Proは`none`、DeepSeek V4 Proは受理可能な最小値`low`、
> Qwen3.7 MaxとMiniMax M3はthinkingを無効化し、最大出力を384 tokenへ統一しています。
> 2026-07-21のプロバイダー既定Reasoning・1,024 tokenによる結果は履歴として分離しています。

### Base会話品質: 旧8指標

元ベンチと同じ30設定・10往復について、会話全体を8観点で評価した結果です。
平均は比較の入口として残しますが、重み付けのない単純平均であり、単独でモデルの優劣を
決める値ではありません。

設定追従と文脈理解:

| Target | 8指標平均 | Roleplay adherence | Consistency | Contextual understanding |
|---|---:|---:|---:|---:|
| GPT-5.6 Sol | 4.549 | 4.578 | 4.800 | 4.833 |
| Qwen3.7 Max | 4.463 | 4.478 | 4.700 | 4.633 |
| GPT-5.4 mini | 4.446 | 4.633 | 4.733 | 4.644 |
| Gemini 3.1 Flash-Lite | 4.432 | 4.500 | 4.656 | 4.656 |
| Gemini 3.5 Flash | 4.399 | 4.333 | 4.589 | 4.578 |
| MiniMax M3 | 4.158 | 4.256 | 4.411 | 4.378 |
| Claude Haiku 4.5 | 4.096 | 3.656 | 4.378 | 4.500 |
| Kimi K3 | 4.013 | 4.045 | 4.389 | 4.278 |
| MiMo-V2.5-Pro | 3.997 | 3.689 | 4.222 | 4.400 |
| GLM-5.2 | 3.872 | 3.722 | 4.144 | 4.344 |
| DeepSeek V4 Pro | 3.720 | 3.300 | 4.211 | 4.178 |

表現と対話体験:

| Target | Expressiveness | Creativity | Naturalness of Japanese | Enjoyment | Turn-taking |
|---|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | 4.300 | 4.356 | 4.700 | 4.333 | 4.489 |
| Qwen3.7 Max | 4.333 | 4.267 | 4.656 | 4.300 | 4.333 |
| GPT-5.4 mini | 4.155 | 4.022 | 4.678 | 4.178 | 4.522 |
| Gemini 3.1 Flash-Lite | 4.311 | 4.167 | 4.622 | 4.267 | 4.278 |
| Gemini 3.5 Flash | 4.344 | 4.156 | 4.567 | 4.278 | 4.344 |
| MiniMax M3 | 3.967 | 3.811 | 4.167 | 4.022 | 4.255 |
| Claude Haiku 4.5 | 4.067 | 3.845 | 4.333 | 3.856 | 4.133 |
| Kimi K3 | 3.800 | 3.511 | 4.167 | 3.756 | 4.155 |
| MiMo-V2.5-Pro | 4.089 | 4.022 | 3.389 | 3.978 | 4.189 |
| GLM-5.2 | 3.967 | 4.000 | 2.833 | 3.789 | 4.178 |
| DeepSeek V4 Pro | 3.678 | 3.645 | 3.478 | 3.356 | 3.911 |

平均だけでは、たとえばGLM-5.2のContextual understanding `4.344`とNaturalness of
Japanese `2.833`の差や、MiMo-V2.5-ProのConsistency `4.222`に対するRoleplay adherence
`3.689`の弱さが見えません。用途に関係する個別指標を優先して比較してください。

### v2: 追従性・安定性・攻撃耐性

CoreとQualityはBaseとChallengeを含む36シナリオのマクロ平均です。RobustnessとRecoveryは
該当ProbeのあるChallengeだけから算出します。重大違反のあるシナリオも各スコアの平均には
含め、Major violationsとEligibleを別の情報として併記します。

| Target | Provider | Core | Quality | Stability | Robustness | Recovery | Major | Eligible / 36 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | OpenAI | 96.647 | 88.549 | 95.949 | 100.000 | 100.000 | 0 | 36 |
| Qwen3.7 Max | OpenCode Go | 95.880 | 86.955 | 96.991 | 93.750 | 100.000 | 1 | 35 |
| GPT-5.4 mini | OpenAI | 96.991 | 86.022 | 96.759 | 100.000 | 100.000 | 0 | 36 |
| Gemini 3.1 Flash-Lite | Google | 95.602 | 86.293 | 94.583 | 82.291 | 95.833 | 2 | 34 |
| Gemini 3.5 Flash | Google | 93.502 | 84.998 | 90.959 | 62.500 | 95.833 | 8 | 33 |
| MiniMax M3 | OpenCode Go | 92.679 | 80.206 | 95.833 | 100.000 | 100.000 | 2 | 34 |
| Claude Haiku 4.5 | Anthropic | 88.059 | 78.705 | 90.278 | 90.625 | 100.000 | 8 | 28 |
| Kimi K3 | OpenCode Go | 90.394 | 76.845 | 86.690 | 100.000 | 100.000 | 6 | 31 |
| MiMo-V2.5-Pro | OpenCode Go | 84.150 | 76.091 | 92.070 | 62.500 | 100.000 | 14 | 26 |
| GLM-5.2 | OpenCode Go | 81.898 | 74.597 | 83.796 | 100.000 | 100.000 | 9 | 27 |
| DeepSeek V4 Pro | OpenCode Go | 82.378 | 69.075 | 78.829 | 81.250 | 87.500 | 13 | 23 |

旧8指標平均が近くても、v2指標は同じとは限りません。Qwen3.7 MaxはBase会話品質平均で
GPT-5.4 miniをわずかに上回りますが、GPT-5.4 miniはCore、Robustness、Eligibleで上回ります。
目的に応じて会話品質、設定追従、長期安定性、攻撃耐性を分けて判断してください。

実行条件、モデル別内訳、token使用量、費用、比較上の注意は以下に記録しています。

- [OpenCode Go 6モデル最小Reasoning結果と11モデル比較](docs/opencode-go-results-2026-07-22.md)
- [OpenCode Go 6モデル旧結果（プロバイダー既定Reasoning）](docs/opencode-go-results-2026-07-21.md)
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
