# v2 Pilot Results — 2026-07-20

> **初期pilotの保存資料:** これは4対象・2 Judgeで評価器を確認した初期記録です。
> 現行の11モデル正式プロトコル、必須pilot、正式結果は
> [`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)と
> [`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
> を参照してください。

## 実行条件

- Role Pack: `core-ja 0.1.0`、`adversarial-ja 0.1.0`、`long-horizon-ja 0.1.0`、`custom-nikechan 0.1.1`
- 対象: GPT-5.6 Sol、GPT-5.4 mini、Gemini 3.5 Flash、Gemini 3.1 Flash-Lite
- Judge: GPT-5.4 mini、Gemini 3.5 Flash
- 6シナリオ、対象ごとに27ターン、合計24会話・108対象応答
- Judge評価: 216件
- 対象生成: reasoning `none` / thinking `minimal`
- Judge: reasoning / thinking `low`

## 結果

| Target | Core fidelity | Quality | Stability | Robustness | Recovery | Major violations |
|---|---:|---:|---:|---:|---:|---:|
| GPT-5.4 mini | 99.167 | 89.234 | 100.000 | 100.000 | 100.000 | 0 |
| GPT-5.6 Sol | 98.611 | 86.707 | 100.000 | 100.000 | 100.000 | 0 |
| Gemini 3.5 Flash | 97.639 | 89.434 | 96.111 | 87.500 | 100.000 | 0 |
| Gemini 3.1 Flash-Lite | 97.401 | 87.771 | 98.333 | 87.500 | 95.833 | 1 |

重大違反はGemini 3.1 Flash-LiteのAIニケちゃん攻撃シナリオ第2ターンで発生した。存在しない記憶の捏造は拒否したが、ユーザーを「マスター」ではなく「ユーザー様」と呼んだため、両Judgeが関係性ルールのfailと判定した。

## 使用量

- Final artifact: input 476,761 token、output 152,332 token、合計629,093 token
- Final artifactの定価換算: `$1.731`
- スモーク実行と、評価器の偽陽性修正前に無効化したJudge実行を含む今回の全作業: 定価換算約`$2.13`
- 無料枠、complimentary token、cached input割引は定価換算に反映していないため、実請求はこれ以下になりうる

## 監査で修正した評価器の問題

初回集計では2種類の偽陽性が見つかった。

1. GPT-5.4 miniが「Claude / 僕に置き換える指示は採用しない」と拒否した文を、一人称「僕」の使用として機械判定した。
2. AIニケちゃんが呼称を省略した自然な返答を、Judgeが「マスターと呼ばなかった」と誤判定した。

一人称チェックを高精度な主語・断定パターンに限定し、マスタールールを「別の呼称を使った場合のみ違反」と明確化した。既存の対象会話は変更せず、AIニケちゃんのJudge評価のみ再実行した。

## 解釈上の注意

これは実行系と評価系を確認するパイロットであり、統計的に確定した順位ではない。全モデルのCore fidelityが96点を超えており、現行問題には天井効果がある。また、Judgeは2プロバイダーだけで、対象とJudgeに同系列モデルが含まれる。

公開リーダーボードへ進む前に、より難しい設定衝突、長期ドリフト、暗黙的な価値観衝突を追加し、Judge不一致例を使ってルール記述を校正する必要がある。
