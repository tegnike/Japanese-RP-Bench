# OpenCode Go Challenge反復評価（Judge v2.1確定版）

> **現在のREADME・ダッシュボードで主表示する結果です。** 8モデルをChallenge 6シナリオで
> 各10回生成した反復評価であり、従来の各シナリオ1生成による15モデル点推定を置き換えます。
> 対象はOpenCode Goで評価した8モデルとChallenge 6シナリオに限られ、日本語RP全般や
> 未評価モデルへ一般化できる総合能力ランキングではありません。

## 完了条件

- 対象モデル: 8
- Challengeシナリオ: 6
- 生成: モデル・シナリオごとに10回
- 独立標本: 480会話
- 評価対象応答: 2,160
- Judge: Grok 4.5、Hy3、Qwen3.7 Plus
- Judge出力: 6,480 / 6,480
- 失敗: 0
- 元の会話・旧Judge成果物の変更: なし

Judge v2.1では、Probeの意図、期待する抵抗・復帰、原子ルールの判定範囲、評価軸の分離を
明確化しました。保存済み会話は再生成せず、同じ480会話だけを再Judgeしています。

## 主結果

順位は`Major-free率`降順、`Major率`昇順、`Challenge RP Summary`降順です。`Major率`は
100会話あたりのMajor件数で、1会話に複数のMajorがあれば100を超え得ます。

| 順位 | モデル | Major-free率 | Major率 | RP Summary (95% CI) | 1位確率 |
|---:|---|---:|---:|---:|---:|
| 1 | Grok 4.5 | 96.7% | 5.0 | 95.76 [93.56, 96.95] | 79.3% |
| 2 | Hy3 | 86.7% | 15.0 | 94.56 [91.60, 96.58] | 10.3% |
| 3 | MiniMax M3 | 86.7% | 23.3 | 93.62 [89.90, 96.27] | 1.1% |
| 4 | GLM-5.2 | 85.0% | 16.7 | 93.73 [91.06, 96.00] | 5.6% |
| 5 | Kimi K3 | 78.3% | 40.0 | 89.59 [78.19, 96.31] | 3.1% |
| 6 | Qwen3.7 Max | 71.7% | 46.7 | 88.24 [75.52, 96.02] | 0.1% |
| 7 | DeepSeek V4 Pro | 68.3% | 46.7 | 88.19 [77.47, 95.95] | 0.4% |
| 8 | MiMo V2.5 Pro | 55.0% | 75.0 | 85.67 [75.53, 93.84] | 0.0% |

点順位とRP Summaryの大小は、そのまま統計的な優位を意味しません。事前登録した最小実用差
（連続指標3点、率10ポイント）、95%区間、Holm補正後p値をすべて満たした場合だけ「優位」と
判定しました。

- 優位: 0 / 224 指標別ペア
- 登録範囲内で同等: 1 / 224 指標別ペア
- 保留: 223 / 224 指標別ペア

したがって、READMEとダッシュボードでは点順位を表示しますが、「Grok 4.5が他の全モデルより
確定的に優れている」とは主張しません。順位、95%区間、1位確率、Major率、シナリオ別結果を
合わせて読みます。

## 解析方法

- 独立標本は会話。ターンや同じ回答への3 Judge判定を独立標本として数えない
- 10,000回のpaired hierarchical block-and-scenario bootstrap
- blockとシナリオを全モデルで対応させて再標本化
- Role Fidelity、Quality、Persona Stability、Major/Major-freeは6シナリオのマクロ平均
- Robustness、RecoveryはProbeを持つ4シナリオのマクロ平均
- RP Summaryは上記5連続指標のモデル単位マクロ平均
- 28モデルペアを指標ごとに一つのfamilyとしてHolm補正
- 同順位時は占有順位の確率を均等分配

## Judge差と限界

v2.1でも3 Judgeを人間の真値とは扱いません。

- 大きなpass/fail不一致: 354ルール判定
- 大きな不一致を含む会話: 156 / 480
- Judge v2.1で明確化した15セルのうち、Judge間pass/fail不一致が残ったもの: 2

Judge別集計とleave-one-judge-out解析でも順位・スコアが動きます。反復生成による区間を得られた
一方、Judge選択とルーブリック解釈の不確実性は残ります。今後対象モデルやBaseを拡張するときも、
単回評価を主結果へ混ぜず、同じ反復単位と解析条件で追加します。

## 成果物

主解析は次に保存しています。

- `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/full2160/summary.json`
- `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/analysis-full2160/analysis.json`
- `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/analysis-full2160/report.md`
- `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/analysis-full2160/model-scenario-statistics.json`
- `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/analysis-full2160/pairwise-comparisons.jsonl`
- `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v21-api-v1/analysis-full2160/old-vs-v21.json`

事前登録とJudge変更理由は
[`opencode-challenge-repeatability-plan-2026-07-27.md`](opencode-challenge-repeatability-plan-2026-07-27.md)と
[`opencode-judge-audit-v21-2026-07-29.md`](opencode-judge-audit-v21-2026-07-29.md)を参照してください。
