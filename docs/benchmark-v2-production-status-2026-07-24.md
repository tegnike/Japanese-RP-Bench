# Japanese-RP-Bench v2 正式再評価の全11モデル完了記録

記録日: 2026-07-24
状態: **11モデルすべて36/36完了**

この文書は、
[`benchmark-v2-production-status-2026-07-23.md`](benchmark-v2-production-status-2026-07-23.md)
の続報である。測定条件のsource of truthは
[`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)であり、本書は
2026-07-24の再実行結果、Kimi K3の課金経路調査、未完了モデルの扱い、費用、成果物指紋を
記録する。

当初除外していたGPT-5.6 SolとKimi K3は、事後分析で評価パイプライン側の問題を修正し、
新しいfingerprintと空の出力先でpilotとfull runをやり直した。これにより11モデルすべてで
36会話と3 Judgeが揃った。不完全だった旧成果物を0点、最下位、部分平均として混ぜていない。

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
- 原則は直接API対象、ユーザー役、3 JudgeをBatch、OpenCode Go対象を同期
- GPT-5.6・Kimi recovery shardはユーザー承認によりOpenAI経路だけ同期APIを使用
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
   この旧成果物は重複削除や2 Judge平均へ緩和せず、モデル全体を除外した。
6. 失敗原因を対象モデルの能力と評価パイプラインの問題に分けて再監査し、Challenge Judgeの
   rule ID固定key、同一verdict重複の決定的正規化、同期429時の並列度縮退、同期Judgeを含む
   pilot検査を実装した。
7. GPT-5.6 SolとKimi K3は、新しいfingerprint、合格pilot、空の出力先でfresh full runを
   実施し、両方とも36/36、失敗0で完了した。
8. GPT-5.6 Solのfresh runではClaude Base Judge 1件がBatchで2回とも`max_tokens`となった。
   同じモデル、prompt、8,192 token、Reasoning `low`の同期APIで当該1件だけを取得し、
   `billing_mode: standard`を保存した上で同じfingerprintのrunを再開した。採点条件や
   出力内容を手作業で変更していない。

## 3. 36/36を満たした11モデル

`RP Balance`はCore、Quality、Stability、Robustness、Recoveryの単純平均である。正式順位は
Eligible降順、Major昇順、RP Balance降順、旧8指標平均降順で決める。Majorは重大違反の
総件数、Eligibleは重大違反がなかったシナリオ数であり、高いRP Balanceで違反を相殺しない。

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

順位とRP Balanceは、保存済み`ALL-11`成果物の数値から決定的に算出した表示指標である。
対象生成、Judge評価、個別スコアを変更せず、追加のAPI呼び出しも行っていない。

GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5、GLM-5.2、Qwen3.7 Max、
MiMo V2.5 Proは2026-07-23の合格成果物を保持した。DeepSeek、MiniMax、Gemini 3.6、
GPT-5.6、Kimi K3は2026-07-24のfresh shardから採用し、旧35/36、Kimiの途中会話、
Flash-Liteの失敗成果物は混ぜていない。

## 4. GPT-5.6 SolとKimi K3の完了

| Target | fresh run | 解消内容 | 最終状態 |
|---|---:|---|---|
| GPT-5.6 Sol | `benchmark-gpt56-recovery-20260724-r7-sync` | Challenge rule ID固定key、同一verdict重複正規化、同期Judge対応 | 36/36、失敗0 |
| Kimi K3 | `benchmark-kimi-recovery-20260724-r6-sync-openai` | 同期429時の並列度縮退、OpenAIユーザー役の同期実行 | 36/36、失敗0、429なし |

旧fresh shardでGPT-5.6 Solの欠落task keyは
`gpt-5.6-sol|core-ja|wind_guide_baseline|judge-claude-haiku-4.5-20251001|turn-3`
である。Claude Batch自体は終了しており、通信失敗ではなく、返却JSONで
`guide.style.wind_metaphor`が重複したschema違反である。

最終recovery runでは別のBase Judge 1件がClaude Batchで2回とも出力上限に達した。隠れた
thinkingが7,195 token、7,347 tokenを消費していたためで、同条件の同期APIでは正常終了した。
この1件だけ同期transportを使い、入力、モデル、Reasoning、上限、schemaは変更していない。

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
修正後のfresh pilotとfull runではKimi K3が22/22 pilot、327/327 fullターンを完了し、
`rate-limit-events.jsonl`は生成されなかった。つまり今回の完了runでは429が一度も発生していない。

## 5. 費用

保存済みleaderboardが記録した全量runのeffective estimateは次のとおり。

| 実行 | Effective estimate |
|---|---:|
| 2026-07-23 直接API shard | $10.580022 |
| 2026-07-23 Kimi除外OpenCode shard | $11.389181 |
| 2026-07-24 DeepSeek・MiniMax fresh shard | $3.290059 |
| 2026-07-24 GPT-5.6・Gemini 3.6 fresh shard | $5.988360 |
| 2026-07-24 GPT-5.6 recovery full | $7.065854 |
| 2026-07-24 Kimi recovery full | $5.697636 |
| 合計 | **$44.011112** |

この合計は保存済み各runの課金区分を反映したusageベースの推定で、最終採用した11モデルだけの
純費用ではなく、不完全だったGPT-5.6の旧fresh実行も含む。pilot、単発probe、途中で止まった
Kimi runは表の外である。
free tier、OpenCode Go定額枠、Zen残高、各社billingの丸めを反映した実請求額とも一致しない。
後半2runは結果完了を優先してOpenAIの同期APIを使用したため、累計effective estimateは
従来の40 USD作業上限を超えた。この表は請求額の保証ではない。

## 6. 決定事項

- 384 token条件の旧結果は履歴として保持し、正式能力ランキングへ使わない。
- 36/36と3 Judgeを満たした上記11モデルを正式完了セットとして記録する。
- 正式順位はEligible、Major、RP Balance、旧8指標平均の順で決め、個別指標も併記する。
- GPT-5.6 Solの旧35/36部分平均とKimi K3の途中成果物を比較表へ混ぜない。
- 同一verdictの重複rule IDだけを決定的に統合し、競合する重複は失敗のままにする。
- Kimi K3の429対策は成功済みtaskを保持し、失敗taskだけを`4 → 2 → 1`へ縮退する。
- READMEとブログを全11モデルの正式結果へ更新し、384 token条件の旧表は監査履歴として残す。

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
| GPT-R7-PILOT | `tmp/pilot-gpt56-recovery-20260724-r7-sync/pilot-report.json` | GPT-5.6 recovery pilot passed | `cd840eac1807900e954e673172b99da533e456ad431178a89f91ae6fd2da901d` |
| GPT-R7-MANIFEST | `tmp/benchmark-gpt56-recovery-20260724-r7-sync/manifest.json` | GPT-5.6 complete、failures 0 | `4e937a3ece7c1d7ccc77a60e7ceadd473c70289accc8d3aeac2ce36547cecb5f` |
| GPT-R7-BOARD | `tmp/benchmark-gpt56-recovery-20260724-r7-sync/leaderboard.json` | GPT-5.6 36/36、$7.065854 | `553f1be28e7b3af76d2c5bc7a64fbd20d4eaab768423f96f75a0e319decc2f2f` |
| K-R6-PILOT | `tmp/pilot-kimi-recovery-20260724-r6-sync-openai/pilot-report.json` | Kimi recovery pilot passed | `e51e739cd2848026b8d23345e7acf9a0ab2a3f2f11ec2919b81d12a1f7ec3c1f` |
| K-R6-MANIFEST | `tmp/benchmark-kimi-recovery-20260724-r6-sync-openai/manifest.json` | Kimi complete、failures 0 | `8aa6a44de3a5822bd9cbbd352bddb4b767d90bb6c31794575eaaf2dc1f11e044` |
| K-R6-BOARD | `tmp/benchmark-kimi-recovery-20260724-r6-sync-openai/leaderboard.json` | Kimi 36/36、$5.697636 | `8e1bbd2259e909a28b48c97280e4b96bd2b5f9072b5aebfd521d174675efe65a` |
| ALL-11 | `tmp/benchmark-all-11-20260724/leaderboard.json` | 正式11モデル統合、各36/36 | `c6d15514ad84d9079a0d428aa5446f7d655d1e677ee90715bd434db7c7113cd1` |

2026-07-23の初回成果物とhashは前日の
[進捗記録](benchmark-v2-production-status-2026-07-23.md#8-成果物指紋)にある。秘密値は
成果物、文書、Gitへ保存していない。

## 8. 事後分析と評価パイプライン修正

同日、除外原因を実装と保存済み成果物から再点検し、次の訂正を行った。
本節の修正方針は、第6節に記録した当初の「重複を後処理せずKimiを保留する」判断を、
監査可能性を維持した上で次回実行向けに更新するものである。

- GPT-5.6 Solは対象モデルとして36会話を正常生成している。「GPT-5.6が失敗した」のではなく、
  Claude Judge 1要求の構造化JSONがrule IDを重複し、評価成果物が1件欠けた。
- Kimi K3はpilotと単発疎通には成功し、2回の全量runはいずれも`workers: 4`の並行要求中に
  HTTP 429となった。provider自体が常時利用不能だったとは断定できず、継続負荷と並列度が
  rate limitを誘発した可能性が高い。

この分析に基づき、評価パイプラインを次のように変更した。

1. AnthropicのChallenge Judgeはrule findingsをrule ID固定keyのobject schemaに変更し、
   同一IDの重複を構造上発生しにくくした。10ターン分を含むBase Judgeはproviderのcompiled
   grammar上限を超えるため配列schemaを維持し、次項の正規化を適用する。
2. 既存の配列形式で重複が返った場合も、verdictが同一のときだけ決定的に統合する。
   confidenceは最小値を採用し、evidenceとrationaleを保持し、正規化履歴と生応答を保存する。
   verdictが競合する重複は引き続きschema-invalidとする。
3. OpenCode Goなど同期生成のHTTP 429では、成功済みtaskを再送せず、429のtaskだけを
   `4 → 2 → 1`へworker数を落として再試行する。各縮退を`rate-limit-events.jsonl`へ残す。
4. prompt、Reasoning、token上限は再試行で変更しない。標準の最大試行数は初回を含め3回である。
5. pilotも同期Judgeを実行し、Batch Judgeだけを数えて同期Judgeを欠落扱いする実装漏れを修正した。

この修正は評価コードと設定のfingerprintを変更した。したがって、過去のGPT-5.6成果物を
後付けで正式完了へ昇格したり、Kimiの途中成果物へ新コードを混ぜたりしていない。両モデルは
新しいpilotに合格した後、空の出力先から正式再評価し、36/36まで完了した。旧9モデルの
保存済み完了値と過去の除外判断は監査履歴として変更せず、最終11モデル統合成果物で出典を
明示した。
