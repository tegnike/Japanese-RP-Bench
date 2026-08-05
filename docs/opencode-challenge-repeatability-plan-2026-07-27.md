# OpenCode Go Challenge反復評価 計画（2026-07-27）

この文書は、OpenCode Goで利用できる8モデルを、既存のChallenge 6シナリオで繰り返し
比較する次段階のsource of truthです。現行Leaderboardを更新する正式計測ではなく、
固定Challengeにおける人格維持、攻撃耐性、復帰能力と回答のばらつきを調べる独立した
探索的ベンチマークです。

この文書より前に作成した
[`repeatability-and-opencode-sampling-plan-2026-07-27.md`](repeatability-and-opencode-sampling-plan-2026-07-27.md)
と
[`opencode-judge-calibration-preregistration-2026-07-27.md`](opencode-judge-calibration-preregistration-2026-07-27.md)
は、監査とOpenCode Judge安定性調査の履歴として残します。今後のChallenge反復評価について
両文書と本書が異なる場合は、本書を優先します。

## 今回決まったこと

### 公表する評価の範囲

今回の結果は「Japanese-RP-Bench Challenge Repeatability Track」のような、Challenge限定の
反復評価として扱います。次の能力については公表できます。

- キャラクター設定に従えるか
- 人格変更、偽記憶、引用内命令、ユーザー代理行動などに耐えられるか
- 攻撃や誤誘導の後に元の人格へ戻れるか
- 同じ条件で回答を繰り返したときに、成績がどの程度変動するか
- 3 Judgeの採点がどの程度一致または不一致になるか

一方、既存6シナリオだけでは、あらゆる日本語ロールプレイ能力を代表できません。結果を
「日本語ロールプレイ総合ランキング」や現行36シナリオの再計測とは表現しません。

### 評価対象

中国系モデルだけに限定せず、次の8モデルを同条件で扱います。

| 表示名 | OpenCode GoモデルID |
|---|---|
| Grok 4.5 | `grok-4.5` |
| Hy3 | `hy3` |
| Qwen3.7 Max | `qwen3.7-max` |
| Kimi K3 | `kimi-k3` |
| DeepSeek V4 Pro | `deepseek-v4-pro` |
| MiniMax M3 | `minimax-m3` |
| GLM-5.2 | `glm-5.2` |
| MiMo V2.5 Pro | `mimo-v2.5-pro` |

結果を見て対象を追加・除外しません。実行不能なモデルが出た場合は0点にせず、不完全として
理由、終了状態、成功済み件数を報告します。

### Judge

全8対象を、次の固定3 Judgeが採点します。

| Judge | モデルID | Reasoning | 最大出力 |
|---|---|---|---:|
| Grok 4.5 | `grok-4.5` | `low` | 8,192 token |
| Hy3 | `hy3` | `low` | 8,192 token |
| Qwen3.7 Plus | `qwen3.7-plus` | `low` | 8,192 token |

Judgeには評価対象モデルの名前やIDを渡しません。Grok 4.5とHy3が評価対象でも、同じモデルを
Judgeから外しません。全対象へ同じ3 Judgeを使用し、自己Judgeだけを特別に除外しません。

3 Judgeの平均を唯一の正解とは扱いません。Judge別スコア、Judge間の差、不一致したルールと
Major判定を保存して併記します。Judgeを一つずつ外した感度解析は全対象へ同じ方法で行い、
特定系列だけに適用しません。

### 既存3 Judgeとの比較の位置づけ

GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5は、現行Leaderboardで固定使用したJudge
ですが、人間による真の正解ではありません。OpenCode Judgeの採点がこの3モデルに似ているかは、
既存Leaderboardとの互換性を示す参考情報に限ります。新しいJudgeの正しさや採否を決める
hard gateには使用しません。

2026-07-27に収集したOpenCode Judge候補の反復結果は破棄しません。次の技術情報として使います。

- Grok 4.5とQwen3.7 Plusは、2反復とも243/243件を初回の構造化出力で完了した
- Hy3は2反復合計486/486件を最終完了し、5件だけschema再試行を必要とした
- Hy3に打ち切り、本文欠落、未解決失敗はなかった
- Kimi K2.6とDeepSeek V4 Flashには打ち切りまたは不足判定が残った

したがって、この6時間超の結果は「どのJudgeが正しいか」ではなく、「どのモデルがJudge用の
構造化出力を安定して返せるか」を確認した調査として扱います。

## Challenge 6シナリオと指標

今回使うのは、前回の36シナリオのうちChallengeに該当する次の6件です。

| シナリオ | 主な確認内容 | Role Fidelity | Quality | Persona Stability | Robustness | Recovery | Major |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `career_mentor_baseline` | 情報を捏造せず、決定権をユーザーへ残す | ○ | ○ | ○ | — | — | ○ |
| `wind_guide_baseline` | 危険な代理行動を拒み、安全な案内へ戻る | ○ | ○ | ○ | ○ | ○ | ○ |
| `museum_curator_injection` | 人格置換、史実捏造、代理行動に抵抗する | ○ | ○ | ○ | ○ | ○ | ○ |
| `tea_room_twelve_turns` | 長期記憶、偽の好み、人格置換、復帰 | ○ | ○ | ○ | ○ | ○ | ○ |
| `nikechan_baseline` | ニケちゃんとして実務支援を行う | ○ | ○ | ○ | — | — | ○ |
| `nikechan_adversarial` | 名前・一人称変更、偽記憶に抵抗して復帰する | ○ | ○ | ○ | ○ | ○ | ○ |

Role Fidelity、Quality、Persona Stability、Major/Major-freeは全6シナリオから算出します。
RobustnessとRecoveryは対応Probeがある4シナリオだけから算出します。Challengeでは旧8指標を
算出しないため、現行LeaderboardのBaseを含む値とは直接比較しません。

## 固定する測定規模

各モデル・各シナリオについて、独立した会話を10回生成します。5回時点は通信状態と成果物の
完全性を確認する運用checkpointに限り、そこで優劣を発表しません。

| 項目 | 固定値 |
|---|---:|
| 対象モデル | 8 |
| Challengeシナリオ | 6 |
| 各モデル・各シナリオの独立生成 | 10 |
| 独立会話 | 480 |
| 対象モデル応答 | 2,160 |
| 固定Judge | 3 |
| Judge出力 | 6,480 |

10個の完全な実行blockを作り、各blockに8モデル×6シナリオの48会話を1回ずつ含めます。
時間帯や利用上限の影響が特定モデルへ偏らないよう、block内の順序は事前固定seedで
ランダム化します。429が発生しても成功済み成果物を残し、不足分だけ再開します。

独立標本は480会話です。1会話内の複数ターンや、同じ回答に対する3 Judgeの採点を、別々の
独立回答として数えません。

## Reasoningとtoken上限

Judgeは、安定性調査で受理を確認した`low`と8,192 token上限を維持します。sampling値は
provider既定とし、明示しません。

既存6対象の生成条件は、正式実行で受理済みの最小Reasoningを出発点とします。

| 対象 | 生成時のReasoning |
|---|---|
| Qwen3.7 Max | thinking disabled |
| Kimi K3 | `reasoning_effort: none` |
| DeepSeek V4 Pro | `reasoning_effort: low` |
| MiniMax M3 | thinking disabled |
| GLM-5.2 | `reasoning_effort: none` |
| MiMo V2.5 Pro | `reasoning_effort: none` |

Grok 4.5とHy3を評価対象として生成する際のReasoning payloadは、全量実行前のtarget pilotで
受理可能な最小設定を確認し、結果を見る前に機械可読な事前登録へ固定します。対象生成の
最大出力は全8モデルで4,096 tokenを基本値とし、pilotで自然終了と本文保持を確認します。
モデルごとに成績を見てReasoningや上限を変更しません。

## 集計と結論の出し方

モデルごと、シナリオごと、Judgeごとに元の結果を残し、少なくとも次を報告します。

- 10生成の平均、中央値、標準偏差
- 会話単位の95%信頼区間
- Judge別スコアとJudge間の差
- 各Probeの成功率
- Major発生率とMajor-free率
- 各モデルが各順位になる確率
- 8モデル全28ペアの差とHolm補正後の結果

3 Judgeが大きく異なる場合や信頼区間が広い場合は、無理に勝敗を付けず「判定困難」とします。
統計的な差だけでなく、実用上意味のある最小差も満たした場合だけ「優位」と表現します。
最小実用差、同等性の範囲、10回から20回へ追加する条件は、API call前の機械可読な事前登録で
固定します。追加する場合は、良く見えた一部モデルだけでなく8モデルすべてを同じ20回へ
増やします。

機械可読な事前登録は
[`configs/opencode_challenge_repeatability_2026-07-27.json`](../configs/opencode_challenge_repeatability_2026-07-27.json)
です。連続スコアは3点、率は10ポイントを最小実用差とします。8モデルの全28ペアは指標ごとに
Holm補正し、統計的な差と最小実用差の両方を満たした場合だけ「優位」とします。同等性は
90%区間全体がこの実用差範囲内に入り、補正後の同等性検定も通った場合だけ認めます。

10回から20回への追加は、10 blockを完全取得して初回解析を終えた時点で一度だけ判定します。
上位候補が複数残り、その差の95%区間が0を含む一方で実用差の外側まで広がる場合に限り、
全8対象・全6シナリオを一括して20回へ増やします。一部モデルだけを追加測定しません。

## Baseを今回含めない理由

Baseは30設定をそれぞれ10往復し、ユーザー役AIの発言も毎回生成します。8モデルを各設定10回
実行すると、Baseだけで2,400会話、対象モデル約24,000応答に加え、同程度のユーザー役応答が
必要です。ユーザー役の変動も結果へ混ざります。

Challengeはユーザー発話が固定されているため、まず評価対象モデルの生成分散とJudge分散を
切り分けやすく、追加の有料ユーザー役も不要です。そのため今回はChallengeを独立した公開可能な
trackとして完成させます。

Baseは不要と判断したのではありません。Challenge完了後に、固定OpenCodeユーザー役を使う
探索的Baseとして別計画を作ります。現行のGPT-5.4 miniユーザー役による正式Baseや現行36件の
Leaderboardとは混ぜません。

## これからすること

1. 本書を基に、8対象、6シナリオ、10生成、3 Judge、解析条件をJSONへ事前登録する。
2. Grok 4.5とHy3のtarget用Reasoning payloadと4,096 token上限を小規模pilotで確認する。
3. 既存の分析補助関数にある`Conversation.to_dict()`呼び出し不整合を修正し、回帰テストを追加する。
4. 10個の完全block、manifest、設定hash、resumeを持つChallenge反復runnerを実装する。
5. `Use balance`が無効であることとOpenCode Go利用枠を確認し、8対象×6シナリオのpilotを行う。
6. pilotが完全成功した場合だけ、空の`tmp/`出力先で480会話と6,480 Judge出力を収集する。
7. 完全性、終了理由、Reasoning、token usage、429、retryを検証してから事前登録済み解析を行う。
8. 結果文書にはChallenge限定であること、Judgeは真の正解ではないこと、標本数と不確実性を
   結果表より前に記載する。
9. 現行README、正式Leaderboard、dashboardは自動更新せず、完全な結果を確認した後に
   公開範囲を別途決める。

## 成功条件と停止条件

データ収集の成功は、特定モデルが勝つことや有意差が出ることではありません。登録した480会話、
2,160対象応答、6,480 Judge出力が揃い、事前登録した解析を完了することです。

途中で出力上限到達、本文欠落、設定拒否、繰り返す未解決schema違反が出た場合は、成功済み
成果物を保持して不足分だけ再開します。異なる条件で一部モデルだけを救済したり、不完全な結果を
0点として順位へ入れたりしません。利用上限に達した場合も追加残高へ自動移行せず、枠の回復後に
同じ設定で再開します。
