# 評価履歴・監査資料

この文書は、Japanese-RP-Bench v2で評価条件がどのように確定したかを時系列でたどるための
案内です。現在の使い方や結果だけを知りたい場合は、履歴を読む必要はありません。

- [リポジトリREADME](../README.md): 概要、最新の正式結果、実行方法
- [正式計測プロトコル](benchmark-v2-production-protocol.md): 現在の固定条件と再現手順
- [2026-07-25 Claude Fable 5追加評価](claude-fable-5-results-2026-07-25.md):
  1件を5回拒否後に除外し、残り35/36を完了した参考結果
- [2026-07-25 GPT-5.6 Terra・Luna追加評価](gpt-5.6-terra-luna-results-2026-07-25.md):
  2モデルとも36/36を完了した追加正式結果
- [2026-07-25 Claude Sonnet 5追加評価](claude-sonnet-5-results-2026-07-25.md):
  最新の追加正式結果
- [2026-07-25 Claude Opus 5追加評価](claude-opus-5-results-2026-07-25.md):
  Opus 5の追加正式結果
- [2026-07-24 全11モデル完了記録](benchmark-v2-production-status-2026-07-24.md):
  先行11モデルの正式結果

## 現在の扱い

2026-07-24に先行11モデル、2026-07-25にClaude Opus 5、Claude Sonnet 5、GPT-5.6 Terra、
GPT-5.6 Lunaが、同じ36シナリオと3 Judgeの正式条件を完了しました。READMEの表には、この
完全性条件を満たした結果だけを掲載しています。2026-07-25の追加shardはユーザー指定により、
OpenAI経路を同期、AnthropicとGemini経路をBatchで実行しています。

Claude Fable 5は同条件のpilotに合格した。本文なしrefusalとなった1シナリオを同一条件で
合計5回まで再試行し、すべて拒否されたためその1件だけを除外した。残り35/36の参考値は
完了したが、完了済み15モデルの正式順位へは混ぜていない。

それ以前の結果は、設計判断、失敗原因、費用、実行方法を確認するための監査資料として保持
しています。現在の順位へ混ぜたり、現行設定の推奨値として扱ったりしません。

## 時系列

### 2024年: フォーク元の公開版

フォーク元は30ロール、各10往復、8指標で32モデルを比較していました。元の説明、結果、
実行方法は[フォーク元v1保存版](upstream-v1.md)に保存しています。

- [旧32モデルの会話](../conversations)
- [旧32モデルの評価結果](../evaluations)
- [2024年版を再集計する方法](benchmark-v2.md#2024年版との比較)

### 2026-07-20: v2の初期検証

Role Pack、原子ルール、長期安定性などを追加したv2について、最初のpilotと比較計測を
行いました。この段階の結果は、ユーザー役、Judge数、出力条件が現在と異なります。

- [初期pilot](pilot-results-2026-07-20.md)
- [Geminiユーザー役による比較](full-results-gemini-user-2026-07-20.md)
- [GPT-5.4 miniユーザー役による比較](full-results-openai-user-2026-07-20.md)

### 2026-07-21〜22: OpenCode Go候補の比較

OpenCode Go経由の6モデルを比較しました。7月21日の結果は対象モデルのReasoning設定が
provider既定で、7月22日の結果は最小Reasoningを明示した一方、対象出力上限が384 token
でした。どちらも現在の正式順位には使用していません。

- [2026-07-21 provider既定Reasoning結果](opencode-go-results-2026-07-21.md)
- [2026-07-22 最小Reasoning結果](opencode-go-results-2026-07-22.md)

### 2026-07-23: 正式条件の確定と計測停止

少額試行用だった対象出力上限384 tokenが全量計測にも使われ、一部の応答が途中で終了して
いたことを確認しました。旧結果を正式比較から外し、出力上限、終了理由、pilot、失敗時の
扱いを固定した正式プロトコルで最初から計測し直しました。

この日は11モデル中6モデルが完了した時点で、未完了モデルと費用を確認するため実行を停止
しています。調査内容と当時の判断は
[2026-07-23 進捗・判断記録](benchmark-v2-production-status-2026-07-23.md)に保存しています。

### 2026-07-24: 全11モデル完了

評価パイプラインと実行方法を検証し、未完了モデルを正式条件で実行しました。11モデル
すべてについて36シナリオと3 Judgeが揃い、現在の正式結果になりました。

途中失敗、再実行、費用、成果物のSHA-256、統合結果の出典は
[2026-07-24 全11モデル完了記録](benchmark-v2-production-status-2026-07-24.md)に保存しています。

### 2026-07-25: Claude Opus 5追加評価

Anthropicの新モデル`claude-opus-5`を、先行11モデルと同じ36シナリオ、対象4,096 token、
固定ユーザー役、3 Judge、最小Reasoning条件で追加評価しました。Opus 5では既定thinkingと
effortが従来Claudeと異なるため、`thinking: disabled`と`output_config.effort: low`を
明示してpilotからfresh runを行いました。

36/36、対象生成327/327、各Judge 57/57を完了し、打ち切り・provider失敗は0でした。結果、
費用、重大違反、成果物hashは
[2026-07-25 Claude Opus 5追加評価](claude-opus-5-results-2026-07-25.md)に保存しています。

### 2026-07-25: Claude Sonnet 5追加評価

同じ追加shard条件で`claude-sonnet-5`を評価した。Sonnet 5もthinking既定有効、
effort既定`high`であるため、`thinking: disabled`と`output_config.effort: low`を明示した。
36/36、対象生成327/327、各Judge 57/57を完了し、打ち切り・provider失敗は0だった。

結果、費用、重大違反、成果物hashは
[2026-07-25 Claude Sonnet 5追加評価](claude-sonnet-5-results-2026-07-25.md)に保存している。

### 2026-07-25: Claude Fable 5追加評価

`claude-fable-5`はAdaptive Thinkingを無効化できないため、最小Reasoningを
`output_config.effort: low`へ対応付けた。pilotは対象22/22、各Judge 2/2、refusal・打ち切り0で
合格した。

全量runでは`legacy_case_01`の2ターン目で本文なしrefusalが発生し、保存済みBatch結果の
`stop_details.category`は`cyber`だった。ユーザーの明示指示により入力と上限を変えず
初回込み5回まで再試行したが、5回とも同じ本文なしrefusalだった。この1シナリオ全体だけを
除外し、残り35/36を3 Judgeで評価した。RP Balance 95.645、旧8指標平均4.493は参考値であり、
正式順位対象外とした。完了範囲、未取得指標、費用、成果物hashは
[2026-07-25 Claude Fable 5追加評価](claude-fable-5-results-2026-07-25.md)に保存している。

### 2026-07-25: GPT-5.6 Terra・Luna追加評価

`gpt-5.6-terra`と`gpt-5.6-luna`を同一shardで評価した。対象2モデル、GPT-5.4 miniユーザー役、
OpenAI Judgeは通常Responses API、Gemini JudgeとClaude JudgeはBatch APIを使用した。
両モデルとも36/36、対象生成327/327、各Judge 57/57を完了し、打ち切り・provider失敗は0だった。

LunaはMajor 0、RP Summary 96.074で、15モデル統合時の正式順位1位となった。TerraはMajor 3、
RP Summary 93.817で7位となった。条件、重大違反、費用、成果物hashは
[2026-07-25 GPT-5.6 Terra・Luna追加評価](gpt-5.6-terra-luna-results-2026-07-25.md)に保存している。

## 履歴文書を読む際の注意

- 日付付き文書の「現在」「次回」「完了後」は、その記録日時点の意味です。
- 旧結果文書のコマンドが参照する設定ファイルは、文書作成後に更新されている場合があります。
- 現在の指標と順位規則は[指標定義](metrics.md)、実行条件は
  [正式計測プロトコル](benchmark-v2-production-protocol.md)を基準としてください。
