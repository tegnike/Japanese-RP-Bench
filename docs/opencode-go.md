# OpenCode Go評価対象の準備

確認日: 2026-07-21

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

## 候補

`configs/benchmark_opencode_go_candidates.yaml`は、コード特化版ではなく汎用上位モデルを各系列から一つずつ選んだ比較候補である。

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

モデル選定後、候補設定から不要な`targets`を削除する。まず小規模な疎通確認用設定で1ケースを実行し、応答形式、token usage、再開処理を確認してから完全版を開始する。

完全版の実行例:

```bash
japanese-rp-bench-v2 run \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/benchmark-opencode-go \
  --workers 4
```

`generation.max_output_tokens`は1024に設定している。Goの推論型モデルは、表示される本文を
返す前に数百トークンを内部推論へ使うことがあり、低い上限では本文なしの`length`終了に
なるためである。会話・判定・レポートはターン単位で保存されるので、同じコマンドと出力先で
再実行すれば保存済み地点から再開できる。

## Judgeの使用量制御

対象生成とJudge評価は分離し、全対象会話をチェックポイントへ保存してから評価を開始する。
OpenAI Judgeは従来どおり再試行可能だが、単価の高いGemini・Anthropic Judgeは次の制約を
適用する。

- 1回の評価要求につき、HTTP呼び出しと形式検証はそれぞれ最大1回
- 成功済みのJSONL判定は再開時に必ず再利用
- 1件のJudge形式エラーで、未生成のOpenCode対象会話を止めない
- 評価失敗はmanifestへ記録し、残りを続行して`partial`で正常停止
- `partial`を監視スクリプトが自動再実行しない

これにより、形式エラーを返す同一Judge要求を5分おきに繰り返すことを防ぐ。必要な再評価は、
原因を修正した後に明示的に再開する。

OpenCode Goの上限は金額ベースで、公式ドキュメント上は5時間`$12`、週`$30`、月`$60`。既存完全版の対象生成実績を基にした6候補の単純な定価換算は合計およそ`$7`〜`$9`で、Judgeとユーザー役の利用分はOpenCode Go枠へ入らない。既存実績を6対象へ比例させると、別枠の3 JudgeとGPTユーザー役は合わせて約`$17.6`の定価換算になる。ただしモデルごとのtoken量、キャッシュ、失敗再試行で変動する。
