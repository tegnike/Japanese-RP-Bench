# Japanese-RP-Bench v2 正式計測プロトコル

最終更新: 2026-07-24
状態: **9/11モデル完了・2モデル除外**

この文書は、Japanese-RP-Bench v2で現行11モデルを正式に比較するための基準文書である。
設定ファイル、実装、pilot、本実行、集計、公開結果はこの文書と一致しなければならない。
この条件によるpilotと全量計測を行い、2026-07-24時点では9モデルが36/36完了した。
GPT-5.6 SolとKimi K3は不完全結果を混ぜずモデル単位で除外した。実行結果、失敗理由、費用、
Kimiの課金経路調査、決定事項は
[`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
に分離して記録する。全11モデルが揃った正式ランキングは未公開である。

## 1. このプロトコルが必要になった理由

従来の試行では、少額smoke用に導入した`max_output_tokens: 384`が、その根拠を文書化しない
まま完全版へ引き継がれていた。384はユーザーが指定した値でも、フォーク元が推奨した値でも
ない。フォーク元実装は会話生成に`max_tokens=1024`を使っていた。

384 token条件では、全11モデル3,597対象返答のうち316件（約8.8%）が380 token以上となり、
DeepSeek V4 Proを中心に文の途中で終了する返答が確認された。動的ユーザー役も8件で上限へ
達した。Judgeはこれらを、応答形式、turn-taking、スタイル、会話品質、要求された説明の未完了
として実際に減点していた。また当時の正規化成果物には`finish_reason`や`stop_reason`がなく、
自然終了と上限打ち切りを集計時に確実に区別できなかった。

したがって、旧384 token条件の値は一般的なモデル能力ランキングとして採用しない。正式計測は、
単に上限を増やすだけでなく、終了理由、実使用量、Reasoning設定、Batch課金区分を保存し、
不完全な生成をスコアへ混ぜない実行ゲートを含める。

フォーク元の条件は、固定commitの
[`src/japanese_rp_bench/models.py`](https://github.com/Aratako/Japanese-RP-Bench/blob/1b26519897ed8cffce8908f7b4032e2883aa5236/src/japanese_rp_bench/models.py)
で確認できる。フォーク元はMIT Licenseであり、元の成果物と帰属を保持する。

## 2. 測定対象と変えないもの

### 2.1 評価トラック

- **Base**: フォーク元と同じSFW 30設定、各10往復、従来8指標
- **Base追加評価**: 同じ会話へ原子ルール、ターン別追従度、長期安定性を追加
- **Challenge**: 4種類のRole Pack、6シナリオ、計27ターン
- **2024 frozen**: 保存済み旧32モデル結果の再集計。現行モデルとの比較ではプロトコル差を明記

元データは
[`Japanese-RP-Bench-testdata-SFW`](https://huggingface.co/datasets/Aratako/Japanese-RP-Bench-testdata-SFW)
の30行（ID 0〜29）を固定revisionで参照する。AIニケちゃんは`custom/nikechan`というRole Pack
の一つであり、評価エンジンへ固有ロジックを入れない。

### 2.2 出力する評価軸

- 従来8指標は1〜5の平均として保持する
- v2はCore fidelity、Quality、Stability、Robustness、Recoveryを別々に出す
- Major violationsと`eligible_for_overall`を別に出す
- 根拠のない重み付き総合点や、単一の総合順位を定義しない
- BaseとChallengeを混同せず、該当シナリオのマクロ平均を使う

本採点は自動評価とする。人間評価を行う場合も、Judgeの小規模なブラインド校正に限定し、
公式スコアへ混ぜない。

## 3. 固定するモデル構成

### 3.1 評価対象11モデル

| 経路 | 対象モデル | 実行方式 |
|---|---|---|
| OpenAI | GPT-5.6 Sol | OpenAI Batch `/v1/responses` |
| OpenAI | GPT-5.4 mini | OpenAI Batch `/v1/responses` |
| Google | Gemini 3.5 Flash | Gemini Batch API |
| Google | Gemini 3.6 Flash | Gemini Batch API |
| Anthropic | Claude Haiku 4.5 | Message Batches API |
| OpenCode Go | Qwen3.7 Max | 同期Anthropic互換API |
| OpenCode Go | MiniMax M3 | 同期Anthropic互換API |
| OpenCode Go | Kimi K3 | 同期OpenAI互換API |
| OpenCode Go | MiMo V2.5 Pro | 同期OpenAI互換API |
| OpenCode Go | GLM-5.2 | 同期OpenAI互換API |
| OpenCode Go | DeepSeek V4 Pro | 同期OpenAI互換API |

### 3.2 ユーザー役とJudge

- 動的ユーザー役: GPT-5.4 mini、Reasoning `none`、OpenAI Batch
- Judge 1: GPT-5.4 mini、Reasoning `low`、OpenAI Batch
- Judge 2: Gemini 3.5 Flash、Thinking `low`、Gemini Batch
- Judge 3: Claude Haiku 4.5、ベンチ上の`low`、Anthropic Message Batches
- 全対象へ同じ3 Judgeを使い、Judge依頼に評価対象モデル名を含めない
- 正式スコアでは各ターン3 Judgeを必須とする

## 4. 出力token上限

| 用途 | 上限 | 適用範囲 |
|---|---:|---|
| 評価対象の返答 | 4,096 | 全11モデルで同一 |
| 動的ユーザー役 | 2,048 | 全会話で同一 |
| Challenge Judge | 4,096 | 全対象・全Judgeで同一 |
| Base Judge | 8,192 | 全対象・全Judgeで同一 |

Base Judgeだけを8,192にするのは、10ターン分の従来8指標、原子ルール、ターン別評価を一つの
構造化応答へ含めるためである。評価対象モデル間で上限は変えない。Judgeの4,096と8,192は
タスクの出力schema差であり、特定モデルを優遇するものではない。

上限は「必ずその量を使わせる予算」ではなく、安全な最大値である。自然終了した短い応答は
そのまま採点する。一つのモデルだけ上限へ達した場合も、そのモデルだけ8,192、16,384と倍増
して再生成しない。追加の出力・Reasoning予算を一部モデルだけへ与えると比較条件が変わるため
である。

各呼び出しについて次を成果物へ保存する。

- `requested_max_output_tokens`
- providerの生の`finish_reason`、`stop_reason`またはresponse `status`
- 正規化した`termination_category`
- `incomplete_reason`またはblock reason
- input、output、reasoning、cached token usage（APIが返す範囲）
- 実際に送ったReasoning／thinking設定
- 同期またはBatchの課金区分

## 5. 終了理由、打ち切り、再試行

### 5.1 正式スコアへ入れる条件

次をすべて満たす生成だけを採点する。

1. providerが正常な結果を返している
2. 終了理由が自然終了または明示的なrefusalである
3. 応答本文が存在する
4. `max_tokens`、`length`、`incomplete`、安全block、失敗、終了理由不明ではない
5. 要求した上限とReasoning設定が成果物で確認できる

内容を伴う明示的refusalはモデルの挙動として採点対象にする。空応答や安全blockは会話を続ける
ための有効な返答ではないため、正式スコアへ入れない。

### 5.2 打ち切り時の扱い

- 上限到達や不完全終了を検出した時点で、そのモデルの当該実行を停止する
- 上限を増やした自動再試行は行わない
- 途中まで生成した会話やJudge結果を公式leaderboardへ混ぜない
- 0点にも最下位にもせず、`incomplete`として順位対象外にする
- 公開時は完了シナリオ数と失敗理由を表示する
- 他モデルの完了結果は保持できるが、「全11モデル正式比較」は全モデル合格まで公開しない

これは一般的なベンチマークで、実行失敗と能力上の0点を分ける考え方に合わせたものでもある。
途中切れを低品質回答として採点すると、モデル能力ではなくAPI上限設計を測ることになる。

### 5.3 providerエラーの再試行

- Batch経路は、APIが失敗と確定した個別要求だけを同じ入力・同じ上限で最大2回再投入する
- `batch.max_attempts: 3`は初回とschema-invalid時の再投入2回を意味する
- 上限到達、safety block、refusal、終了理由不明などの終端結果は再投入しない
- OpenCode Go同期経路でHTTP 429になった場合は、成功済み要求を確定したまま429の要求だけを再投入する
- 同期429の再投入ではworker数を各試行で半減し、標準設定では`4 → 2 → 1`まで縮退する
- `generation.sync_rate_limit_max_attempts: 3`は初回を含む最大試行数、
  `generation.sync_rate_limit_backoff_seconds: 30`は段階的待機の基準値とする
- 各縮退は`rate-limit-events.jsonl`へ対象task、変更前後のworker数、結果を保存する
- retryでprompt、Reasoning、出力上限を変更しない
- retry上限後も成功しなければ、そのモデルを`incomplete`にする

同じ要求を偶然二重送信しないよう、Batch要求と送信予定状態を送信前にローカル保存する。
送信直後の通信切断などで受付成否が不明な場合は、自動で新規Batchを作らず停止して確認する。
Gemini Batchの作成はidempotentではないため、この扱いが特に重要である。

## 6. Sampling設定

評価対象、ユーザー役、Judgeのいずれにも、次のsamplingパラメータを明示送信しない。

- `temperature`
- `top_p`
- `top_k`

各provider／モデルの既定値を使用する。旧実装の`temperature: 0.7`をv2へ引き継がない。
理由は、providerごとに推奨値と対応パラメータが異なり、特にGemini 3.5は公式資料で
`temperature`、`top_p`、`top_k`を既定値のまま使うことを推奨しているためである。

これは「ランダム性を最小化する」設定ではない。モデルが通常提供される既定の生成挙動を比較
する選択である。再現監査のため、モデルID、実行日、送信payloadにsampling指定がないことを
残す。provider既定値の将来変更は完全には固定できないため、異なる実行日の結果を同一条件と
断定しない。

## 7. Reasoning設定

### 7.1 評価対象とユーザー役

評価対象は、各APIが明示的に受理する最小Reasoningへ固定する。ユーザー役も`none`とする。
これは能力上限ではなく、追加の推論計算を極力使わない通常会話での人格追従性を測る主トラック
である。

| 経路 | モデル | APIへ送る設定 |
|---|---|---|
| OpenAI | GPT-5.6 Sol、GPT-5.4 mini | `reasoning.effort: none` |
| Gemini | Gemini 3.5 Flash、3.6 Flash | `thinkingLevel: minimal` |
| Anthropic | Claude Haiku 4.5 | `thinking: {type: disabled}` |
| OpenCode OpenAI互換 | Kimi K3、GLM-5.2、MiMo V2.5 Pro | `reasoning_effort: none` |
| OpenCode OpenAI互換 | DeepSeek V4 Pro | `reasoning_effort: low` |
| OpenCode Anthropic互換 | Qwen3.7 Max、MiniMax M3 | `thinking: {type: disabled}` |

DeepSeek V4 Proは`none`を拒否するため、受理される最小値`low`を使う。Geminiの`minimal`は
通常ほぼthinkingなしだが、複雑な要求で少量のthinkingが生じる可能性があり、完全無効を保証
しない。OpenCode Goの値は、公開されているAPI経路に加え、各モデルへの短い疎通で受理可否を
確認した実装上の値である。

Gemini 3.5 Flash-Liteは、同一prompt、4,096 token上限、`minimal`条件でGemini 3.1
Flash-LiteがBatchと同期APIの双方で本文のない`MALFORMED_RESPONSE`を再現したため、
Googleが後継として案内するモデルへ置き換えた。3.5 Flash-Liteは同じ条件の同期疎通で
自然終了と本文を確認している。この置換は評価対象だけに適用し、Gemini Judgeは従来どおり
Gemini 3.5 Flash、Thinking `low`を維持する。置換後は旧pilotや部分成果物を再利用せず、
新しい指紋と空の出力先で全11モデルpilotからやり直す。

その後、3.5 Flash-Liteも正式全量のBase case 0・turn 9で本文のない
`MALFORMED_RESPONSE`を返した。pilot合格だけでは全量安定性を保証できないことが判明したため、
ユーザー承認後に同一4,096 token、`minimal`、同じユーザー役・3 Judge条件でGemini 3.6
Flashを単発確認し、空の出力先でpilotと全量をやり直した。Gemini 3.6は36/36を完了し、
3.5 Flash-Liteの部分成果物は正式スコアへ混ぜていない。

高Reasoningの能力上限を測る場合は、正式主トラックへ混ぜず、別の
`capability-ceiling`トラックとして実行する。

### 7.2 Judge

Judgeは測定器なので、最小値ではなく全対象共通の抽象設定`low`へ固定する。

| Judge | 実設定 |
|---|---|
| GPT-5.4 mini | `reasoning.effort: low` |
| Gemini 3.5 Flash | `thinkingLevel: low` |
| Claude Haiku 4.5 | `thinking: enabled`, `budget_tokens: 1024` |

Claude Haiku 4.5はAnthropicのeffortパラメータ対象外であるため、手動extended thinkingの最小値
1,024 tokenを、ベンチ上の`low`へ対応付ける。Anthropicではthinking tokenも現在ターンの
`max_tokens`へ含まれるため、Judgeの出力上限とthinking budgetを両方記録する。

Reasoning量は同じモデルの性能、費用、レイテンシ、本文へ残る出力枠を変えうる。したがって
sampling既定値とは異なり、Reasoningはprovider既定へ任せず明示する。

## 8. Batch実行

### 8.1 Batch対象

- OpenAI対象2モデル: Batch
- Gemini対象2モデル: Batch
- Anthropic対象1モデル: Batch
- GPT-5.4 miniユーザー役: Batch
- OpenAI、Gemini、Anthropicの全Judge: Batch
- OpenCode Go対象6モデル: 同期（契約内の既存経路）

`batch: true`を設定するだけで会話全体を一括投入するのではない。会話は前ターンへ依存する
ため、同じ時点で作成可能な要求をまとめるwave方式を使う。

```text
初期ユーザー発言
  → target turn 1（同一provider・modelごとにBatch）
  → user turn 2（OpenAI Batch）
  → target turn 2
  → user turn 3
  → ...
  → 会話完成後にJudge（provider・modelごとにBatch）
```

OpenCode Go対象も、相手となるGPT-5.4 miniユーザー役はOpenAI Batchで生成する。そのため
OpenCode対象の返答は同期でも、会話全体はwave単位で進む。

### 8.2 永続化と再開

- Batch投入前に要求一覧、`custom_id`、入力hash、送信予定状態を保存する
- 投入後にprovider job IDと状態を追記する
- 同じ出力先で再開した場合は既存jobをpollし、新しいjobを重複作成しない
- 結果順序を信用せず`custom_id`で元要求へ対応付ける
- 成功、失敗、期限切れを要求単位で保存する
- APIが明示した失敗要求だけを再投入する
- 同期429でも成功済み要求を再送せず、失敗要求だけを低いworker数で続行する
- 全会話生成が完了してからJudge評価を開始する

OpenAI Batchは`/v1/responses`を使用する。OpenAI Judgeは同期／BatchともStrict JSON Schemaを
使う。GeminiとAnthropicもproviderのBatch APIを使い、同期APIへ黙ってfallbackしない。
Anthropic Judgeでは原子rule IDをJSON objectの固定keyにして、同じIDを構造上重複できない
schemaを使う。providerが配列形式で同じrule IDを複数返した場合は、verdictがすべて同一の
ときだけ一件へ統合する。confidenceは最小値、evidenceとrationaleは重複を除いて併記し、
正規化したrule IDを成果物へ記録する。verdictが競合する重複はschema-invalidのまま再試行し、
人手で判定を選ばない。providerの生応答は`raw_response`として保持する。

各社のBatchは50%割引だが即時完了を保証しない。OpenAIとGeminiは目標／完了枠が24時間、
Anthropicも処理中Batchが24時間で失効しうる。会話生成は複数waveを順番に待つため、全量完了
までの経過時間は同期実行より長くなる可能性がある。

## 9. 成果物の再利用防止

旧条件の会話やJudge結果を、新しい正式計測へ暗黙に再利用しない。次の指紋を保存して照合する。

- `protocol_fingerprint`: config、全Role Pack、Baseデータ、従来rubric、生成・採点コード
- `run_fingerprint`: 実行全体の条件
- `conversation_fingerprint`: 会話本文と、その生成条件

再開時に指紋が一致しない、指紋のない旧形式である、会話本文が編集されている、pilot後に
コードや設定が変わった、という場合は停止する。Judge結果は`run_fingerprint`と
`conversation_fingerprint`の両方が一致した場合だけ再利用できる。

pilotと本実行は別の空出力先を使う。正式条件を変更した実行も新しい空出力先を使う。
これにより384 token条件、異なるReasoning、別ユーザー役、古いJudge結果が混ざらない。

## 10. 資格情報の事前検査

必要な環境変数は次の4つである。キー自体は設定、ログ、成果物、Gitへ保存しない。

```bash
export OPENAI_API_KEY=...
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=...
export OPENCODE_GO_API_KEY=...
```

pilotまたは本実行は、設定された全providerの資格情報を最初の送信前に一括検査する。1つでも
不足していれば、利用可能なproviderだけを先行送信せず、外部リクエスト0件で停止する。

## 11. 必須pilot

全量計測の前に、全11対象、同じユーザー役、同じ3 Judgeで次を実行する。

- Base: case ID `0`、10往復
- Challenge: `tea_room_twelve_turns`、12ターン
- Judge: 各対象についてBase全体を1回、長期シナリオ最終ターンを3 Judgeで評価

設定ファイルごとの予定呼び出し数は次の通り。

| Pilot | Target | User | Judge |
|---|---:|---:|---:|
| 直接API 5モデル | 110 | 45 | 30 |
| OpenCode Go 6モデル | 132 | 54 | 36 |
| 合計 | 242 | 99 | 66 |

### 11.1 合格条件

次をすべて満たす場合だけ`pilot-report.json`を合格とする。

- 全対象・全予定ターンが完了している
- 全3 Judgeの予定評価が完了し、構造化JSON schemaへ適合している
- target、user、Base Judge、Challenge Judgeの要求上限が正しい
- 打ち切り、incomplete、安全block、空応答、終了理由不明が0件
- 全対象とJudgeの実Reasoning設定が決定表どおり
- OpenAI、Gemini、Anthropic経路がBatchとして記録されている
- usage、終了理由、job ID、課金区分が保存されている
- `protocol_fingerprint`が現在の本実行条件と一致する
- 予定件数と成果物件数が一致する

1件でも満たさなければ全量計測を開始しない。原因を修正した場合は、修正後の新しい指紋と空の
pilot出力先で再確認する。

## 12. 全量計測の開始条件と手順

開始条件は次の通り。

1. 4つのAPIキーが事前検査を通る
2. 直接API用pilotとOpenCode Go用pilotが同じprotocolで合格する
3. 設定、コード、Role Pack、rubric、データがpilot後に変わっていない
4. Batch jobを追跡できる永続化先と、十分な予算がある
5. 既存成果物を含まない新しい本実行出力先を用意する

実行例では、実際の日付を含む新しいdirectory名を使う。

```bash
japanese-rp-bench-v2 pilot \
  --config configs/benchmark_full.yaml \
  --output tmp/pilot-full-YYYYMMDD \
  --workers 4

japanese-rp-bench-v2 pilot \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/pilot-opencode-go-YYYYMMDD \
  --workers 2

japanese-rp-bench-v2 run \
  --config configs/benchmark_full.yaml \
  --output tmp/benchmark-full-YYYYMMDD \
  --pilot-report tmp/pilot-full-YYYYMMDD/pilot-report.json \
  --workers 4

japanese-rp-bench-v2 run \
  --config configs/benchmark_opencode_go_candidates.yaml \
  --output tmp/benchmark-opencode-go-YYYYMMDD \
  --pilot-report tmp/pilot-opencode-go-YYYYMMDD/pilot-report.json \
  --workers 2
```

直接APIとOpenCode Goの結果は、両方が完全性検査を通った後にだけ11モデル比較へ統合する。

## 13. 予算

正式実行開始時の予算判断は次の前提で行った。

旧成果物の実測tokenを2026-07-22時点のBatch価格へ換算した基準値は20.72 USDだった。
上限拡大後の自然な長文化、失敗要求の再投入、価格変動を見込み、全量の想定を**21〜25 USD**、
準備予算を**25 USD**とする。

Gemini 3.5 Flash-Liteへの置換後、直前pilot usageを現行Batch価格へ換算した全量推計は
約20.04 USDである。新しいpilot自体を含めても約20.80 USDであり、25 USDの開始ゲート内に
収まる。新しいpilot完了後には実usageで再計算し、この推計を再確認する。

目安はOpenAI 9〜11 USD、Gemini 5〜6 USD、Anthropic 7〜8 USDである。OpenCode Go対象の
生成は定額契約内として増分0 USD扱いだが、契約条件が変われば再見積もりする。これは保証額
ではない。pilot完了後に実usageと現行価格で再計算し、25 USDを超える見込みなら本実行前に
停止する。

2026-07-23の部分完了後、直接runのeffective estimateは`$10.580022`、Kimiを除く
OpenCode runは`$11.389181`、合計`$21.969203`となった。未完了4モデルのfresh rerunと
Gemini再置換には約`$8.53`の追加を見込み、従来の$25上限を超えるため停止した。
2026-07-24に上限40 USDでfresh rerunとGemini再置換が承認された。追跡できる全量runの
effective estimate累計は`$31.247622`である。pilot、probe、途中停止したKimi、providerの
実請求差はこの合計に含まない。詳細と成果物hashは
[`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
を参照。

## 14. 正式結果の公開条件

- 全11モデル正式比較として公開する場合は、11モデルすべての予定会話と予定Judge評価が揃っている
- truncation、終了理由不明、指紋不一致、未解決Batchが0件
- 各モデルの件数、usage、Reasoning、上限、Batch区分を集計できる
- Base従来8指標とv2指標を別々に表示する
- 不完全実行を0点として順位へ混ぜない
- 2024 frozen結果とはユーザー役、Judge、モデル時点が異なることを明記する
- 旧384 token条件の表と新条件の表を混在させない
- 11モデル正式比較を公開する場合はREADME、結果docs、ブログを同時に反映する

2026-07-24時点では9モデルだけがこの完全性条件を満たす。9モデルの値は完了セットとして
記録できるが、11モデル正式leaderboardや単一順位として公開しない。除外理由と予定件数を
必ず併記する。

ブログでは読者を混乱させる再実行の経緯を本文へ持ち込まず、新しい正式条件と結果だけを自然に
記載する。一方、この技術プロトコルには監査可能性のため、384 token問題と設計変更理由を残す。

## 15. 実装上の対応箇所

| 内容 | Source of truth |
|---|---|
| モデル、上限、Reasoning、Batch、pilot | [`configs/benchmark_full.yaml`](../configs/benchmark_full.yaml)、[`configs/benchmark_opencode_go_candidates.yaml`](../configs/benchmark_opencode_go_candidates.yaml) |
| 会話wave、資格情報検査、指紋、停止ゲート | [`runner.py`](../src/japanese_rp_bench/v2/runner.py) |
| provider要求、終了理由、usage、Reasoning変換 | [`providers.py`](../src/japanese_rp_bench/v2/providers.py) |
| Batch投入、永続化、poll、個別retry | [`batch.py`](../src/japanese_rp_bench/v2/batch.py) |
| pilot／run CLI、完全性検査 | [`cli.py`](../src/japanese_rp_bench/v2/cli.py) |
| 回帰テスト | [`tests/test_v2.py`](../tests/test_v2.py) |
| 指標定義 | [`metrics.md`](metrics.md) |
| v2設計 | [`benchmark-v2.md`](benchmark-v2.md) |

## 16. 一次資料

### 内部実測の根拠

384 token監査と費用基準値は、次の保存済み成果物にある会話本文、`usage`、Judge結果、
`leaderboard.json`を集計した。これらは旧条件の監査証拠であり、新しい正式スコアへは再利用しない。

- `tmp/benchmark-v2-openai-user-20260720/` — 直接API 5モデル
- `tmp/benchmark-opencode-go-min-reasoning-batch-20260722/` — OpenCode Go 6モデル
- [`full-results-openai-user-2026-07-20.md`](full-results-openai-user-2026-07-20.md) — 直接API結果の保存資料
- [`opencode-go-results-2026-07-22.md`](opencode-go-results-2026-07-22.md) — OpenCode Go結果の保存資料

`tmp/`はローカル実行成果物でありGit管理対象外である。公開時に必要な集計値、条件、監査結果は
追跡可能な結果文書へ転記し、正式計測の生成果物は別途保存する。

### フォーク元

- Aratako, [Japanese-RP-Bench](https://github.com/Aratako/Japanese-RP-Bench) — 10往復、従来8指標、実行構成
- Aratako, [SFW test data](https://huggingface.co/datasets/Aratako/Japanese-RP-Bench-testdata-SFW) — Base 30設定
- Aratako, [original generation settings](https://github.com/Aratako/Japanese-RP-Bench/blob/1b26519897ed8cffce8908f7b4032e2883aa5236/src/japanese_rp_bench/models.py) — `temperature=0.7`、`max_tokens=1024`
- Aratako, [MIT License](https://github.com/Aratako/Japanese-RP-Bench/blob/48faa68acbc4da90bc317075ef6011a34cdef24e/LICENSE)

### OpenAI

- [Batch API guide](https://developers.openai.com/api/docs/guides/batch) — 50%割引、24時間枠、`/v1/responses`、`custom_id`、順不同結果
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs#structured-outputs-vs-json-mode) — Responses／BatchでのStrict JSON Schema
- [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) — Responses、Batch対応
- [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) — 固定snapshot、Reasoning、Batch対応
- [Latest model guidance](https://developers.openai.com/api/docs/guides/latest-model) — GPT-5系Reasoning設定

### Google Gemini

- [Batch API](https://ai.google.dev/gemini-api/docs/batch-api) — 50%割引、24時間目標、評価用途、非idempotentなBatch作成
- [Gemini 3](https://ai.google.dev/gemini-api/docs/generate-content/gemini-3) — `minimal` thinking levelの対応範囲
- [Gemini 3.5 changes](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5) — thinking levelとsampling既定値の推奨
- [Gemini model deprecations](https://ai.google.dev/gemini-api/docs/deprecations) — Gemini 3.1 Flash-Liteの後継モデル
- [Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking) — thinking設定とtoken accounting
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) — Standard／Batch価格

### Anthropic

- [Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing) — 50%割引、非同期処理、24時間失効
- [Create a Message Batch](https://platform.claude.com/docs/en/api/messages/batches/create) — `custom_id`、順不同結果、`max_tokens`
- [Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking) — Haiku 4.5、最小`budget_tokens: 1024`、出力上限との関係
- [Effort](https://platform.claude.com/docs/en/build-with-claude/effort) — effort対応モデル
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) — Haiku 4.5とBatch価格

### OpenCode Goと評価方法

- OpenCode, [OpenCode Go](https://dev.opencode.ai/docs/go/) — 対象モデルとモデル別API経路
- Percy Liang et al., [Holistic Evaluation of Language Models](https://arxiv.org/abs/2211.09110) — 標準化条件と複数指標による評価
- Charlie Snell et al., [Scaling LLM Test-Time Compute Optimally](https://arxiv.org/abs/2408.03314) — test-time computeが性能へ与える影響
