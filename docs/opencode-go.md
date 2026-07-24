# OpenCode Go実行ガイド

確認日: 2026-07-24

> 2026-07-24の正式プロトコル実行では、OpenCode Goの6モデルすべてが36/36完了した。
> Kimi K3は当初2回の全量runがHTTP 429で停止したが、同期429時の並列度縮退を実装し、
> 新しいpilotと空の出力先から再実行して完了した。現在地、課金経路調査、証拠は
> [`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
> を参照。

## 接続

OpenCode Goのモデル一覧とAPI仕様は公式ドキュメントを正とする。

1. OpenCode TUIで`/connect`を実行し、`OpenCode Go`を選んで契約時のAPIキーを登録する。
2. `/models`で契約から利用できるモデルを確認する。
3. ベンチマークを実行するシェルにAPIキーを渡す。

```bash
export OPENCODE_GO_API_KEY='OpenCode GoのAPIキー'
```

OpenCodeが資格情報を標準パスへ保存している場合は、キーを画面へ出さずに次のように読み込める。

```bash
export OPENCODE_GO_API_KEY="$(jq -r '."opencode-go".key' ~/.local/share/opencode/auth.json)"
```

このリポジトリはキーを設定ファイル、成果物、例外へ保存しない。

公開モデル一覧は認証なしでも確認できる。

```bash
curl -fsS https://opencode.ai/zen/go/v1/models | jq -r '.data[].id'
```

## API互換性

OpenCode GoではモデルによってAPI形式が異なる。候補設定では公式表に合わせて`api_style`を明示する。

- `openai_chat`: `https://opencode.ai/zen/go/v1/chat/completions`
- `anthropic_messages`: `https://opencode.ai/zen/go/v1/messages`

[OpenCode Go公式資料](https://dev.opencode.ai/docs/go/)では、`Use balance`を有効にするとGoの
利用上限後も同じ`/zen/go/v1`経路からZen残高へフォールバックする。Go枠消費後に追加した
残高のためにKimi K3を別endpointへ変更する仕様ではない。通常の
[OpenCode Zen](https://dev.opencode.ai/docs/zen/)にはKimi K3が掲載されていないため、
`/zen/v1`をKimi K3の代替経路として使用しない。

## 正式評価対象

`configs/benchmark_opencode_go_candidates.yaml`は、コード特化版ではなく汎用上位モデルを
各系列から一つずつ選んだ正式評価用設定である。設定ファイル全体の使い分けは
[`configs/README.md`](../configs/README.md)を参照する。

| 系列 | 候補 | 選定理由 |
|---|---|---|
| Moonshot | Kimi K3 | 最新の上位汎用モデルとして品質上限を見る |
| Zhipu | GLM-5.2 | GLM系列の最新上位モデル |
| Alibaba | Qwen3.7 Max | Qwen系列の上位モデル。日本語性能の有力候補 |
| DeepSeek | DeepSeek V4 Pro | Pro/Flash差のうち、まず品質側を測る |
| MiniMax | MiniMax M3 | MiniMax系列の最新代表 |
| Xiaomi | MiMo-V2.5-Pro | 通常版より品質側の代表を選ぶ |

Kimi K2.7 Codeはコーディング特化のため、ロールプレイ評価の初回候補から外す。DeepSeek V4 Flash、Qwen3.7 Plus、MiMo-V2.5は、上位版との品質差より価格・速度を測りたい第2段階の候補とする。

既存のGPT-5.4 miniユーザー役と、OpenAI・Google・Anthropicの3 Judgeは変更しない。OpenCode Goのモデルは`targets`にだけ置くため、自己採点や中国系モデルによるユーザー発話生成は発生しない。

## 実行前確認と実行

完全版の前に、設定済みのBase 1ケースと12ターン長期シナリオを全6対象で生成するpilotを実行する。終了理由、token usage、Reasoning、再開処理を確認し、打ち切りゼロの`pilot-report.json`ができた場合だけ完全版を開始する。

完全版の実行例:

```bash
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

対象モデルは4,096 token、動的ユーザー役は2,048 tokenに分離する。対象モデルの
ReasoningはKimi K3、GLM-5.2、MiMo V2.5 Proで`none`、DeepSeek V4 Proで受理可能な
最小値`low`、Qwen3.7 MaxとMiniMax M3で`disabled`を明示する。方針と根拠は
[`benchmark-v2.md`のReasoning policy](benchmark-v2.md#reasoning-policy)を参照する。

会話・判定・レポートはターン単位で保存されるので、同じコマンドと出力先で再実行すれば
保存済み地点から再開できる。

同期対象がHTTP 429を返した場合、実行器はそのwaveで成功した要求を保存し、429になった要求
だけを再投入する。worker数は標準で`4 → 2 → 1`と半減し、各縮退を
`<output>/rate-limit-events.jsonl`へ記録する。prompt、token上限、Reasoningは変更しない。
3試行後も429なら従来どおり`incomplete`で停止する。

Kimi K3の最終fresh runは327/327 target turnを完了し、429による縮退は発生しなかった。
当初の失敗は削除せず監査履歴として保持し、最終スコアには途中成果物を混ぜていない。

## Judgeの使用量制御

対象生成とJudge評価は分離し、全対象会話をチェックポイントへ保存してから評価を開始する。
OpenCode Goの6対象は同期実行する。GPT-5.4 miniユーザー役とOpenAI、Gemini、Anthropicの
3 Judgeは`batch: true`により各社の非同期Batch APIへ投入する。Reasoningは同期／Batchの
どちらでも変更しない。

- BatchジョブIDと要求対応表を`<output>/batches/generation/`と`judging/`へ保存
- 成功済みのJSONL判定は再開時に必ず再利用
- 1件のJudge形式エラーで、未生成のOpenCode対象会話を止めない
- エラー、期限切れ、不正JSONになった個別要求だけを、初回を含め最大3試行まで新しいBatchへ再投入
- 定価換算とBatch割引後の推定費用をleaderboardへ別々に記録

これにより、完了待ちや結果回収の途中でプロセスが終了しても、同じBatch全体を重複投入せず
再開できる。

## 旧384 token・最小Reasoning再評価結果

2026-07-22の旧384 token再評価は6モデルすべて36/36レポート、全体216/216レポート、
失敗0で完了した。
スコア、モデル別Reasoning token、旧実行との差、Batch割引後の費用は
[`opencode-go-results-2026-07-22.md`](opencode-go-results-2026-07-22.md)に記録している。
2026-07-21の結果はプロバイダー既定Reasoningによる履歴として分離し、現行ランキングには
使用しない。

OpenCode Goの上限は金額ベースで、公式ドキュメント上は5時間`$12`、週`$30`、月`$60`。
今回の成功成果物による定価換算は、OpenCode Go対象生成が`$7.527`、Judgeとユーザー役が
`$17.780`だった。Gemini・AnthropicのBatch割引を反映した全体推定額は`$19.670`である。
OpenCode Go対象生成額はモデル別定価による比較値であり、定額契約の実支払額ではない。
