# Japanese-RP-Bench v2 正式再評価の完了範囲と除外判断

記録日: 2026-07-24
状態: **11枠中9モデルが36/36完了、GPT-5.6 SolとKimi K3はモデル単位で除外**

この文書は、
[`benchmark-v2-production-status-2026-07-23.md`](benchmark-v2-production-status-2026-07-23.md)
の続報である。測定条件のsource of truthは
[`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)であり、本書は
2026-07-24の再実行結果、Kimi K3の課金経路調査、未完了モデルの扱い、費用、成果物指紋を
記録する。

9モデルの完了値は同じ正式条件で取得した有効な結果である。ただし、当初予定した11モデルが
すべて揃ったleaderboardではない。GPT-5.6 SolとKimi K3を0点、最下位、35件平均として混ぜず、
以下では「36/36を満たした9モデルの完了セット」として表示する。

## 1. 固定条件

- Base: フォーク元と同じSFW 30設定、10往復、従来8指標
- Challenge: 4 Role Pack、6シナリオ、計27ターン
- 対象出力上限: 4,096 token
- GPT-5.4 miniユーザー役: 2,048 token、Reasoning `none`
- Challenge Judge: 4,096 token
- Base Judge: 8,192 token
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5の3モデル
- Judge Reasoning: 各社APIへ対応付けた共通抽象レベル`low`
- sampling: 全経路で明示せずprovider既定
- 直接API対象、ユーザー役、3 JudgeはBatch、OpenCode Go対象だけ同期
- Batchのschema-invalidは、入力、上限、Reasoningを変えず初回を含め最大3試行
- 不完全モデルは0点にせず、モデル単位で比較対象外

対象とユーザー役のReasoningは同一文字列へ無理に揃えるのではなく、各APIが受理する最小値へ
固定した。GPTとKimi・GLM・MiMoは`none`、Geminiは`minimal`、Claude・Qwen・MiniMaxは
`disabled`、`none`を拒否するDeepSeekだけ`low`である。詳細は正式プロトコルの
[Reasoning設定](benchmark-v2-production-protocol.md#7-reasoning設定)を参照。

## 2. 2026-07-24の再実行

予算上限を40 USDへ変更し、資格情報を設定ファイルや成果物へ保存しない条件で、未完了枠を
空の出力先から再実行した。

1. Gemini 3.5 Flash-Lite枠は、同じ4,096 tokenと`minimal`で単発確認と正式pilotを通過した
   Gemini 3.6 Flashへ置換した。
2. DeepSeek V4 ProとMiniMax M3は新しいOpenCode shardで会話と3 Judgeを最初から実行し、
   両方とも36/36、失敗0で完了した。
3. Gemini 3.6 FlashとGPT-5.6 Solも新しい直接API shardで最初から実行した。
4. Gemini 3.6 Flashは全36シナリオ、全3 Judgeが揃った。追加API呼び出しを行わず、
   保存済み成果物から36レポートを集計した。
5. GPT-5.6 Solは会話36件と大半のJudge結果を得たが、Claude Judgeの
   `core-ja/wind_guide_baseline` turn 3だけが3試行とも同じrule IDを重複出力した。
   重複削除や2 Judge平均へ緩和せず、モデル全体を除外した。

## 3. 36/36を満たした9モデル

表は順位ではなく、当初の経路順である。旧8指標平均は1〜5、v2指標は0〜100。Majorは重大
違反シナリオ数、Eligibleは重大違反ゲート通過数である。重み付き総合点は定義しない。

| Target | 旧8指標平均 | Core | Quality | Stability | Robustness | Recovery | Major | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.4 mini | 4.425 | 99.054 | 86.328 | 97.917 | 100.000 | 100.000 | 1 | 35/36 |
| Gemini 3.5 Flash | 4.374 | 94.120 | 85.045 | 93.287 | 75.000 | 100.000 | 10 | 32/36 |
| Gemini 3.6 Flash | 4.381 | 95.833 | 85.460 | 94.213 | 100.000 | 100.000 | 1 | 35/36 |
| Claude Haiku 4.5 | 4.058 | 87.272 | 78.464 | 90.880 | 97.916 | 100.000 | 16 | 25/36 |
| GLM-5.2 | 3.879 | 81.782 | 74.877 | 96.528 | 100.000 | 100.000 | 5 | 31/36 |
| Qwen3.7 Max | 4.403 | 95.532 | 85.699 | 97.639 | 93.750 | 95.833 | 2 | 35/36 |
| DeepSeek V4 Pro | 4.347 | 93.380 | 84.877 | 92.824 | 100.000 | 100.000 | 5 | 31/36 |
| MiniMax M3 | 4.109 | 91.782 | 79.458 | 94.792 | 100.000 | 100.000 | 5 | 31/36 |
| MiMo V2.5 Pro | 4.096 | 85.516 | 79.039 | 93.042 | 84.375 | 95.833 | 7 | 29/36 |

GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5、GLM-5.2、Qwen3.7 Max、
MiMo V2.5 Proは2026-07-23の合格成果物を保持した。DeepSeek、MiniMax、Gemini 3.6だけを
2026-07-24のfresh shardから採用し、旧35/36やFlash-Liteの失敗成果物は混ぜていない。

## 4. 除外した2モデル

| Target | 生成状況 | 除外理由 | 判断 |
|---|---:|---|---|
| GPT-5.6 Sol | 36会話 | Claude Judge 1要求が同一schema違反を3試行とも再現 | 35件平均を使わずモデル単位で除外 |
| Kimi K3 | 全量未完了 | OpenCode Goが継続実行中にHTTP 429 `provider_rate_limit_exceeded` | 追加再試行を停止し保留 |

GPT-5.6 Solの欠落task keyは
`gpt-5.6-sol|core-ja|wind_guide_baseline|judge-claude-haiku-4.5-20251001|turn-3`
である。Claude Batch自体は終了しており、通信失敗ではなく、返却JSONで
`guide.style.wind_metaphor`が重複したschema違反である。

### Kimi K3は別の実行方法だったか

[OpenCode Go公式資料](https://opencode.ai/docs/go/)では、Kimi K3の経路は
`https://opencode.ai/zen/go/v1/chat/completions`である。同資料の`Use balance`は、
Goの利用上限後も同じGo経路からZen残高へフォールバックする仕組みとして説明されている。
したがって、Go契約枠を使い切った後に追加した10 USDは、別endpointへ切り替えるためのものでは
なく、`Use balance`が有効なら同じ経路で消費される。

一方、通常の[OpenCode Zen](https://dev.opencode.ai/docs/zen/)のモデル一覧にはKimi K3がなく、
Kimi K2.7 Codeなど別モデルが掲載されている。このためKimi K3だけを通常Zen
`/zen/v1`へ変える根拠はない。

今回のKimi pilotは合格し、全量の合間に行った小さな疎通も成功したが、2回の全量runは
序盤の並行要求で429となった。エラー本文は残高不足ではなくprovider rate limitだったため、
単発可用性と継続負荷時の可用性が一致しないprovider側の制限と判断した。OpenCode Consoleの
`Use balance`と残高はブラウザが未ログインだったため2026-07-24時点の再確認はできていない。
現在の決定は、Kimiへ追加の有料試行を行わず保留することである。

## 5. 費用

保存済みleaderboardが記録した全量runのeffective estimateは次のとおり。

| 実行 | Effective estimate |
|---|---:|
| 2026-07-23 直接API shard | $10.580022 |
| 2026-07-23 Kimi除外OpenCode shard | $11.389181 |
| 2026-07-24 DeepSeek・MiniMax fresh shard | $3.290059 |
| 2026-07-24 GPT-5.6・Gemini 3.6 fresh shard | $5.988360 |
| 合計 | **$31.247622** |

この合計はBatch 50%係数を反映したusageベースの推定で、9モデルだけの純費用ではなく、除外した
GPT-5.6のfresh実行も含む。pilot、単発probe、途中で止まったKimi runは表の外である。
free tier、OpenCode Go定額枠、Zen残高、各社billingの丸めを反映した実請求額とも一致しない。
40 USDは作業上限であり、この表は請求額の保証ではない。

## 6. 決定事項

- 384 token条件の旧結果は履歴として保持し、正式能力ランキングへ使わない。
- 36/36と3 Judgeを満たした上記9モデルの結果を完了セットとして記録する。
- GPT-5.6 Solの35/36部分平均とKimi K3の途中成果物を比較表へ混ぜない。
- Claude Judgeの重複rule IDを人手または後処理で削除しない。
- Kimi K3への追加試行を停止する。provider側の安定利用が確認できた場合だけ独立shardで再開する。
- 当初の「全11モデル正式leaderboard」は未達のため、その名称で順位を公開しない。
- READMEは9モデル完了、2モデル除外へ更新するが、384 token条件の旧表は監査履歴として残す。
- ブログは全11モデル正式比較として更新しない。

## 7. 成果物と指紋

`tmp/`はGit管理対象外であるため、以下のpathとSHA-256を再現監査用に記録する。

| ID | ローカル成果物 | 内容 | SHA-256 |
|---|---|---|---|
| O-R3-MANIFEST | `tmp/benchmark-opencode-rerun-20260724-r3/manifest.json` | DeepSeek・MiniMax complete、failures 0 | `7e8c35d3a47564db3ddff3a59310122c9b7431546c71a1679f4e62ca2c072c92` |
| O-R3-BOARD | `tmp/benchmark-opencode-rerun-20260724-r3/leaderboard.json` | 2モデル各36/36、$3.290059 | `6835eadabca5968fafe07eed760706c92566fb421b85d405cdda872264ce1f97` |
| D-R3-MANIFEST | `tmp/benchmark-direct-remaining-20260724-r3/manifest.json` | Gemini eligible、GPT-5.6 excluded | `bdece1015e21f5893ea1de5995e13ccebcb2075ece5648868a9c7facb103c3a4` |
| D-R3-ELIGIBLE | `tmp/benchmark-direct-remaining-20260724-r3/eligible-leaderboard.json` | Gemini 3.6 36/36、GPT-5.6部分値なし | `5dc9cea84acecba4fb22a87e2a0f22c4bc47f6badaa3a7d0af2563abf19e473e` |
| D-R3-CLAUDE-A3 | `tmp/benchmark-direct-remaining-20260724-r3/batches/judging/judge-claude-haiku-4.5-20251001/attempt-03.json` | GPT-5.6の3回目schema違反 | `aed479dd6a05f68ffd6eba2f53a3ca963b5bf9a34b12862818f38f1941929c65` |
| D-R3-PILOT | `tmp/pilot-direct-remaining-20260724-r3/pilot-report.json` | direct fresh shard pilot passed | `111289b390c0a09d70ab8d5efd6fe00b44816891150197bfe4c883609b46daab` |
| O-R3-PILOT | `tmp/pilot-opencode-rerun-20260724-r3/pilot-report.json` | OpenCode fresh shard pilot passed | `e3e9684e43cdf5efb37f8b4679796a60a4a6425c20d60d2d59612bb6d44ccf79` |
| K-PILOT | `tmp/pilot-opencode-kimi-20260723-2227/pilot-report.json` | Kimi pilot passed | `bd8152409c443b9434bfef8e406a3878b0b217a00125d4aa2d6e673b424da9ac` |
| K-RUN-1 | `tmp/benchmark-kimi-20260724/manifest.json` | Kimi full attempt 1、429停止 | `c847c404c8e8468db17b83328b1602d3d7204ee3bdaff55b29600ba823ff8ef6` |
| K-RUN-2 | `tmp/benchmark-kimi-20260724-retry1/manifest.json` | Kimi full attempt 2、429停止 | `b014950a259f7294e9b9f3e987dbdd20419002734ba08f84f7b6774743debe88` |

2026-07-23の初回成果物とhashは前日の
[進捗記録](benchmark-v2-production-status-2026-07-23.md#8-成果物指紋)にある。秘密値は
成果物、文書、Gitへ保存していない。
