# Japanese-RP-Bench v2 正式再評価の進捗と判断記録

記録日: 2026-07-23
状態: **11モデル中6モデル完了、5モデル未完了、実行一時停止**

この文書は、384 token問題の発見から正式プロトコルによる再評価、2026-07-23時点の
部分完了までを監査可能な形で残す。測定条件のsource of truthは
[`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)であり、
本書は実行結果、判断、再開条件の記録である。

現在の成果物は全11モデルが揃っていないため、正式ランキングではない。不完全モデルを0点や
最下位として扱わず、完了済み6モデルのスコアも先行公開しない。READMEに残る数値表は
384 token条件による旧計測であり、正式結果とは明確に分離する。

## 1. なぜ全件を再評価したか

旧計測では、少額smoke用の`max_output_tokens: 384`が完全版にも使われていた。旧11モデルの
3,597対象返答中316件（約8.8%）が380 token以上となり、文の途中で終了した返答をJudgeが
実際に減点していた。一方、旧成果物はproviderの`finish_reason`や`stop_reason`を保存して
おらず、自然終了と上限打ち切りを確実に区別できなかった。

フォーク元は生成上限に1,024 tokenを使っており、384は上流由来でもユーザー指定でもない。
このため旧値を一般的な能力ランキングとして採用せず、次を追加した正式プロトコルで
ユーザー役、対象モデル、Judgeを最初から生成・評価し直す方針を決めた。

- 対象4,096、動的ユーザー役2,048、Challenge Judge 4,096、Base Judge 8,192 token
- provider終了理由、実usage、Reasoning設定、Batch課金区分の保存
- truncation、incomplete、安全block、空本文、終了理由不明を採点しないゲート
- 会話依存順のBatch wave、要求単位の永続化、同条件で最大2試行
- protocol／run／conversation fingerprintによる異条件成果物の再利用防止
- 不完全モデルを0点にせず順位対象外とする公開ゲート

根拠は正式プロトコルの
[必要性](benchmark-v2-production-protocol.md#1-このプロトコルが必要になった理由)、
[出力上限](benchmark-v2-production-protocol.md#4-出力token上限)、
[終了理由と再試行](benchmark-v2-production-protocol.md#5-終了理由打ち切り再試行)、
[Batch実行](benchmark-v2-production-protocol.md#8-batch実行)を参照。

## 2. 変更せず固定した条件

- Baseは元のSFW 30設定×10往復×従来8指標を保持する
- v2のCore fidelity、Quality、Stability、Robustness、Recovery、Major violationsは別軸で出す
- 重み付き総合点を作らない
- AIニケちゃんは`custom/nikechan` Role Packの一つとし、評価器を専用化しない
- ユーザー役はGPT-5.4 mini、Reasoning `none`
- JudgeはGPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5の3モデル
- 本採点は自動評価とし、人手補正を公式スコアへ混ぜない
- sampling値は明示せずprovider既定、Reasoningはモデルごとの最小値へ明示固定する
- 直接API対象、ユーザー役、3 JudgeはBatch、OpenCode Go対象だけ同期実行する

モデル、上限、Reasoning、Batch設定は
[`configs/benchmark_full.yaml`](../configs/benchmark_full.yaml)と
[`configs/benchmark_opencode_go_candidates.yaml`](../configs/benchmark_opencode_go_candidates.yaml)、
実装箇所は正式プロトコルの
[対応表](benchmark-v2-production-protocol.md#15-実装上の対応箇所)に記録している。

## 3. 実行までの経緯

1. 384 token監査後、正式プロトコルと実行ゲートを実装した。
2. Gemini 3.1 Flash-Liteは同一prompt、4,096 token、最小ThinkingでBatchと同期の双方が
   `MALFORMED_RESPONSE`となった。他の現行Gemini候補は同条件で正常終了したため、
   ユーザー承認のうえ対象だけをGemini 3.5 Flash-Liteへ置換した。Gemini Judgeは
   Gemini 3.5 Flashのまま変更していない。
3. 直接API 5モデルpilotは10/10会話、155生成、30 Judge、打ち切り0で合格した。
4. Kimiを除くOpenCode Go 5モデルpilotも10/10会話、155生成、30 Judge、打ち切り0で
   合格した。
5. Kimi K3はOpenCode Goの対象モデルだが、購入後にZen残高フォールバックを有効化しても
   `provider_rate_limit_exceeded`のHTTP 429が継続した。通常Zen endpointのモデル一覧には
   Kimi K3がなく、Kimiだけを独立shardとして待つ判断になった。
6. ユーザーの「まずKimi以外を完了」の指示により、Kimiを除くOpenCode 5モデル用の
   [`benchmark_opencode_go_without_kimi.yaml`](../configs/benchmark_opencode_go_without_kimi.yaml)
   を追加し、直接API側と並行して正式全量を進めた。
7. Gemini 3.5 Flash-Liteの終端異常とClaude Judgeのschema違反を補正せず隔離し、
   影響を受けない6モデルの集計まで完了した。

Gemini置換の技術的根拠と公式資料は正式プロトコルの
[Reasoning設定](benchmark-v2-production-protocol.md#7-reasoning設定)、
Kimiを含むOpenCode Goの経路は[`opencode-go.md`](opencode-go.md)を参照。

## 4. 2026-07-23時点の結果

各モデルの予定数はBase 30＋Challenge 6の36シナリオである。

| モデル | 正式完了 | 状態 |
|---|---:|---|
| GPT-5.4 mini | 36/36 | 完了 |
| Gemini 3.5 Flash | 36/36 | 完了 |
| Claude Haiku 4.5 | 36/36 | 完了 |
| GLM-5.2 | 36/36 | 完了 |
| Qwen3.7 Max | 36/36 | 完了 |
| MiMo V2.5 Pro | 36/36 | 完了 |
| GPT-5.6 Sol | 35/36 | Claude Judge 1件欠落のためモデル全体を順位対象外 |
| DeepSeek V4 Pro | 35/36 | Claude Judge 1件欠落のためモデル全体を順位対象外 |
| MiniMax M3 | 35/36 | Claude Judge 1件欠落のためモデル全体を順位対象外 |
| Gemini 3.5 Flash-Lite | 0/36 | 会話生成がnon-scorableとなり、全シナリオを順位対象外 |
| Kimi K3 | 0/36 | OpenCode GoのHTTP 429により正式run未実行 |

未完了4モデルの直接原因は次のとおり。

- Gemini 3.5 Flash-Lite: Base case 0のtarget turn 9が本文なし、
  `MALFORMED_RESPONSE`、reasoning 86 token、上限4,096、Thinking `minimal`で終了した。
  正式ルールでは自動再試行できない。
- GPT-5.6 Sol: Claude Judgeが`guide.values.safety_and_choice`を初回と許可済み再試行の
  両方で重複出力した。
- DeepSeek V4 Pro: Claude Judgeが`guide.values.safety_and_choice`を2試行とも重複出力した。
- MiniMax M3: Claude Judgeが`nike.behavior.practical_support`を2試行とも重複出力した。

Claude Batch自体はいずれもprovider上は成功しており、欠落は通信失敗ではなくJudge JSONの
rule coverage schema違反である。重複項目を後処理で捨てれば数値は作れるが、それは確定済み
schemaと公式スコアへの人手補正禁止を破るため採用しなかった。

`leaderboard.json`には35シナリオの暫定集計も含まれるが、正式プロトコル上はモデル全体を
順位対象外とする。全11モデルが揃うまで、この部分値をモデル比較やランキングへ使わない。

## 5. 費用

正式全量runの成果物に記録されたeffective estimateは次のとおり。

| 実行 | Effective estimate |
|---|---:|
| 直接API側 | $10.580022 |
| Kimiを除くOpenCode側 | $11.389181 |
| 合計 | **$21.969203** |

これは各呼び出しに記録したusageと価格から算出した推定額で、直接APIとJudgeのBatch 50%係数を
反映している。free tier、データ共有特典、OpenCode Go定額契約の実請求差は反映しない。
pilotや診断probeも上表の外にある。

未完了のGPT-5.6 Sol、DeepSeek V4 Pro、MiniMax M3を空の出力先から再実行し、
Flash-Lite枠も別のGeminiへ再置換して再実行する前タスク時点の追加見積もりは約$8.53、
全量run累計は約$30.50＋pilot・変動分である。このため既存の$25開始上限では続行せず、
$35への上限変更案を提示した。

**$35上限への変更、3モデルのfresh rerun、Flash-Liteの再置換はまだ承認済みとして扱わない。**
次回作業日に改めて明示確認し、価格と対象モデルを再確認してから実行する。

## 6. 決定事項

- 旧384 token結果は履歴として保持するが、正式ランキングには使わない。
- 完了済み6モデルの会話・Judge・集計成果物は保持する。
- 35/36や0/36のモデルを0点、最下位、欠損補完済みとして扱わない。
- Claude Judgeの重複rule_idを後処理で削除しない。
- GPT-5.6 Sol、DeepSeek V4 Pro、MiniMax M3を再開するときは、空の出力先から
  同一条件で新規実行する。
- Gemini 3.5 Flash-Lite枠は、別の現行Geminiを同じ4,096 token・対応する最小Reasoningで
  単発probeし、正式pilotを通した候補へ置換する案を次回判断する。
- Kimi K3はOpenCode Goの429解消後、同条件の独立shardで実行する。
- 全11モデル完了後だけ、正式leaderboard、READMEの結果表、結果docs、ブログを同時更新する。
- 秘密値は過去タスクやチャットから復元せず、次回は4環境変数の存在だけをpreflightする。
- 2026-07-23時点で再評価プロセスは停止し、残タスクは別日に再開する。

## 7. 次回の再開条件

1. $35上限、3モデルのfresh rerun、Gemini再置換について明示承認を得る。
2. `OPENAI_API_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`、
   `OPENCODE_GO_API_KEY`の存在だけを、値を表示せず確認する。
3. 現行Gemini候補とKimi K3へ最小限の単発probeを行う。
4. 置換後のcanonical configと新しいprotocol fingerprintを確定する。
5. 空の出力先でpilotを通し、費用ゲートを再計算する。
6. 未完了モデルをfresh full runし、全11モデルの完全性を監査する。
7. 全11モデル完了後にだけ正式結果とブログを公開する。

## 8. 内部成果物と検証情報

`tmp/`はGit管理対象外である。次の相対パス、run fingerprint、SHA-256を、ローカル成果物を
照合するための証拠台帳として残す。

| ID | 成果物 | 主な根拠 | SHA-256 |
|---|---|---|---|
| D-PILOT | `tmp/pilot-full-20260723-094634/pilot-report.json` | 直接5モデルpilot合格、protocol fingerprint `00359c...2290` | `6f88cbec7836a9e19d2472e06344d5a95c3a5c95e3f774d3ffba2f88dd44b989` |
| O-PILOT | `tmp/pilot-opencode-go-without-kimi-20260723-113316/pilot-report.json` | OpenCode 5モデルpilot合格、protocol fingerprint `bafde3...4fc6` | `8019bfa72bcf36e192d362521d5d25021390b5460338f1807b8f5b54460ebfb1` |
| D-MANIFEST | `tmp/benchmark-full-20260723-094634/manifest.json` | status `partial`、failures 37、run fingerprint `00359c...2290` | `fd9b334bc9551eeaa3e0d3ca045b71b220dceacc26fb86ab43b345967ac389e0` |
| D-BOARD | `tmp/benchmark-full-20260723-094634/leaderboard.json` | 3モデル36/36、GPT-5.6 35/36、Flash-Lite 0/36、$10.580022 | `024dbcb3d2d79a1190cdd9ebecdbba3574e7ceca4c571b5f78ad286d48a98270` |
| O-MANIFEST | `tmp/benchmark-opencode-go-without-kimi-20260723-113316/manifest.json` | status `partial`、failures 2、run fingerprint `bafde3...4fc6` | `b14c1fc865eedc2f1f25cac8770ee90b84553b0bc91e9e4aa07556867e433c02` |
| O-BOARD | `tmp/benchmark-opencode-go-without-kimi-20260723-113316/leaderboard.json` | 3モデル36/36、2モデル35/36、$11.389181 | `e8d8dfe3dbbc07fb14abbe4f0ed763997d3131ea86395ba99c3a8999847c9f54` |
| D-CLAUDE-A2 | `tmp/benchmark-full-20260723-094634/batches/judging/judge-claude-haiku-4.5-20251001/attempt-02.json` | GPT-5.6の再試行schema違反 | `6c21e158307f6d7a2a5262047e212dd821bbabdcfb9888fe67efcf8dde925cc9` |
| O-CLAUDE-A2 | `tmp/benchmark-opencode-go-without-kimi-20260723-113316/batches/judging/judge-claude-haiku-4.5-20251001/attempt-02.json` | DeepSeek／MiniMaxの再試行schema違反 | `74ee8be11009110a58df3f33155e45695cf370ccb7776eec97e0b97726e4ed15` |

Gemini 3.5 Flash-Liteの直接証拠は
`tmp/benchmark-full-20260723-094634/batches/generation/gemini-3.5-flash-lite/attempt-0017.json`
および同run内の
`conversations/gemini-3.5-flash-lite/legacy-base-ja__legacy_case_00.generation-attempts.jsonl`
にある。

判断経緯の会話記録はCodex task
`019f8c1e-2cff-7c01-b79c-304faa5c5756`
（Japanese-RP-Bench v2 全11モデル正式再評価）に保存されている。秘密値は本書へ転記しない。

外部の一次資料、フォーク元commit、Batch／Reasoning／価格資料へのリンクは正式プロトコルの
[一次資料](benchmark-v2-production-protocol.md#16-一次資料)へ集約している。
