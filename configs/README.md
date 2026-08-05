# 設定ファイル案内

このディレクトリには、現行の反復評価設定、過去の単回実行・再実行に使った設定、フォーク元v1の
設定例が同居しています。名前だけで判断せず、用途と状態を確認してから使ってください。

## 現行の入口

| 設定 | 用途 |
|---|---|
| [`opencode_challenge_repeatability_2026-07-27.json`](opencode_challenge_repeatability_2026-07-27.json) | 現在の主結果。OpenCode Go 8対象をChallenge 6件×10生成×固定3 Judgeで測る反復評価 |
| [`opencode_judge_audit_v21_2026-07-29.json`](opencode_judge_audit_v21_2026-07-29.json) | 現在の主結果で使うv2.1ルーブリックと、保存済み全2,160応答の再Judge条件 |
| [`opencode_judge_calibration_2026-07-27.json`](opencode_judge_calibration_2026-07-27.json) | 中国系6対象の反復測定前に行うOpenCode Judge校正の機械可読な事前登録 |
| [`opencode_judge_calibration_analysis_2026-07-27.json`](opencode_judge_calibration_analysis_2026-07-27.json) | 元の事前登録hashを保ったまま、指標集計前に曖昧さを解消した解析規則 |
| [`opencode_judge_calibration_supplement_2026-07-27.json`](opencode_judge_calibration_supplement_2026-07-27.json) | 失格候補も同条件で2反復分の試行を収集する、結果確認後の補足実行記録 |
| [`opencode_challenge_repeatability_pilot_clarification_2026-07-27.json`](opencode_challenge_repeatability_pilot_clarification_2026-07-27.json) | target pilotで本文前に返った不透明なHTTP 400を、低Reasoning成功時だけ非対応と確定する補足規則 |
| [`opencode_judge_audit_v2_2026-07-28.json`](opencode_judge_audit_v2_2026-07-28.json) | 保存済み83重大不一致の抽出、分類基準、修正版Judgeルーブリック、API停止条件 |
| [`opencode_judge_audit_v2_contrast_pairs_2026-07-28.json`](opencode_judge_audit_v2_contrast_pairs_2026-07-28.json) | 修正版Judgeの最低方向と評価軸分離を確認する4 pair・8 case |
| [`opencode_judge_audit_v21_contrast_pairs_2026-07-29.json`](opencode_judge_audit_v21_contrast_pairs_2026-07-29.json) | v2.1の方向性と過剰判定を停止する9 pair・18 case |
| [`opencode_qwen38_repeatability_extension_2026-08-05.json`](opencode_qwen38_repeatability_extension_2026-08-05.json) | 現在の8モデルと同条件でQwen3.8 Maxだけを6シナリオ×10生成し、Judge v2.1で追加評価する事前登録 |

`benchmark_full.yaml`と`benchmark_opencode_go_candidates.yaml`は、過去の15モデル単回評価を
構成した入口です。現在の主結果へ追加する場合は、単回runを混ぜず、反復評価計画に同じモデル・
シナリオ・生成回数を事前登録してください。過去の単回条件は
[`docs/benchmark-v2-production-protocol.md`](../docs/benchmark-v2-production-protocol.md)、
現在の反復条件は[反復評価計画](../docs/opencode-challenge-repeatability-plan-2026-07-27.md)を参照してください。

## 特定実行の記録として残す設定

以下は2026-07-20〜24の比較、部分実行、復旧実行に使った設定です。一般的な開始点では
ありません。日付付き結果を検証するときだけ、対応する記録と一緒に参照してください。

| 設定 | 対象・目的 | 対応する記録 |
|---|---|---|
| [`benchmark_full.yaml`](benchmark_full.yaml) | OpenAI、Gemini、Anthropic経路の過去の単回評価 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_opencode_go_candidates.yaml`](benchmark_opencode_go_candidates.yaml) | OpenCode Go経路の過去の単回評価 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_full_gemini_user.yaml`](benchmark_full_gemini_user.yaml) | Gemini 3.5 Flashをユーザー役にした旧比較 | [`full-results-gemini-user-2026-07-20.md`](../docs/full-results-gemini-user-2026-07-20.md) |
| [`benchmark_v2.yaml`](benchmark_v2.yaml) | v2初期pilotの4対象・2 Judge構成 | [`pilot-results-2026-07-20.md`](../docs/pilot-results-2026-07-20.md) |
| [`benchmark_opencode_go_without_kimi.yaml`](benchmark_opencode_go_without_kimi.yaml) | Kimiを除くOpenCode Go 5対象の2026-07-23 shard | [`benchmark-v2-production-status-2026-07-23.md`](../docs/benchmark-v2-production-status-2026-07-23.md) |
| [`benchmark_direct_remaining.yaml`](benchmark_direct_remaining.yaml) | GPT-5.6 SolとGemini 3.6 Flashの再実行 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_opencode_go_judge_rerun.yaml`](benchmark_opencode_go_judge_rerun.yaml) | DeepSeek V4 ProとMiniMax M3の再実行 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_opencode_go_kimi.yaml`](benchmark_opencode_go_kimi.yaml) | Kimi K3の独立実行 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_gpt56_recovery.yaml`](benchmark_gpt56_recovery.yaml) | GPT-5.6 Solの最終recovery run | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_claude_opus_5.yaml`](benchmark_claude_opus_5.yaml) | Claude Opus 5の追加単回評価 | [`claude-opus-5-results-2026-07-25.md`](../docs/claude-opus-5-results-2026-07-25.md) |
| [`benchmark_claude_sonnet_5.yaml`](benchmark_claude_sonnet_5.yaml) | Claude Sonnet 5の追加単回評価 | [`claude-sonnet-5-results-2026-07-25.md`](../docs/claude-sonnet-5-results-2026-07-25.md) |
| [`benchmark_claude_fable_5.yaml`](benchmark_claude_fable_5.yaml) | Claude Fable 5の追加評価（5回拒否の1件を除外した35/36参考値） | [`claude-fable-5-results-2026-07-25.md`](../docs/claude-fable-5-results-2026-07-25.md) |
| [`benchmark_gpt56_terra_luna.yaml`](benchmark_gpt56_terra_luna.yaml) | GPT-5.6 TerraとLunaの追加単回評価 | [`gpt-5.6-terra-luna-results-2026-07-25.md`](../docs/gpt-5.6-terra-luna-results-2026-07-25.md) |

設定ファイルは日付付き文書の作成後にも更新されている場合があります。旧結果のコマンドを
現在の追跡版設定で再実行しても、当時の成果物を厳密には再現しません。正確な条件は結果文書、
保存済み成果物のfingerprint、該当時点のGit履歴を併せて確認してください。

## フォーク元v1

[`eval_config.yaml`](eval_config.yaml)は`japanese-rp-bench`コマンドで使うv1設定例です。
v2の`japanese-rp-bench-v2`コマンドには使いません。項目の意味は
[`docs/upstream-v1.md`](../docs/upstream-v1.md)に保存しています。

## 補助スクリプト

| スクリプト | 状態 |
|---|---|
| [`run_opencode_go_detached.sh`](../scripts/run_opencode_go_detached.sh) | 2026-07-21の旧provider既定Reasoning実行用 |
| [`run_opencode_go_min_reasoning_batch_detached.sh`](../scripts/run_opencode_go_min_reasoning_batch_detached.sh) | 2026-07-22の旧384 token実行用 |

両スクリプトは履歴用です。固定された当時の設定を内包せず、追跡中の
`benchmark_opencode_go_candidates.yaml`を参照するため、現行の反復評価や旧結果の厳密な再現には
使用しないでください。

## 安全な使い方

- APIキーをYAMLやGitへ書かず、READMEに記載した環境変数を使う
- `pilot`と全量実行には別の空出力先を使う
- 既存成果物とfingerprintが一致しない場合は、新しい出力先から始める
- 設定を変更すると評価の指紋が変わるため、過去のpilot合格票を流用しない
