# 設定ファイル案内

このディレクトリには、現行の正式実行用設定、特定の再実行に使った設定、フォーク元v1の
設定例が同居しています。名前だけで判断せず、用途と状態を確認してから使ってください。

## 現行の入口

| 設定 | 用途 |
|---|---|
| [`benchmark_full.yaml`](benchmark_full.yaml) | OpenAI、Gemini、Anthropic経路の5対象を正式条件で実行 |
| [`benchmark_opencode_go_candidates.yaml`](benchmark_opencode_go_candidates.yaml) | OpenCode Go経路の6対象を正式条件で実行 |

11モデル比較は、この2設定の完全な成果物を統合して行います。全量実行の前に、それぞれ同じ設定で
`pilot`を実行し、別の空出力先で`run`してください。固定条件と開始ゲートは
[`docs/benchmark-v2-production-protocol.md`](../docs/benchmark-v2-production-protocol.md)、
コマンド例は[リポジトリREADME](../README.md)を参照してください。

## 特定実行の記録として残す設定

以下は2026-07-20〜24の比較、部分実行、復旧実行に使った設定です。一般的な開始点では
ありません。日付付き結果を検証するときだけ、対応する記録と一緒に参照してください。

| 設定 | 対象・目的 | 対応する記録 |
|---|---|---|
| [`benchmark_full_gemini_user.yaml`](benchmark_full_gemini_user.yaml) | Gemini 3.5 Flashをユーザー役にした旧比較 | [`full-results-gemini-user-2026-07-20.md`](../docs/full-results-gemini-user-2026-07-20.md) |
| [`benchmark_v2.yaml`](benchmark_v2.yaml) | v2初期pilotの4対象・2 Judge構成 | [`pilot-results-2026-07-20.md`](../docs/pilot-results-2026-07-20.md) |
| [`benchmark_opencode_go_without_kimi.yaml`](benchmark_opencode_go_without_kimi.yaml) | Kimiを除くOpenCode Go 5対象の2026-07-23 shard | [`benchmark-v2-production-status-2026-07-23.md`](../docs/benchmark-v2-production-status-2026-07-23.md) |
| [`benchmark_direct_remaining.yaml`](benchmark_direct_remaining.yaml) | GPT-5.6 SolとGemini 3.6 Flashの再実行 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_opencode_go_judge_rerun.yaml`](benchmark_opencode_go_judge_rerun.yaml) | DeepSeek V4 ProとMiniMax M3の再実行 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_opencode_go_kimi.yaml`](benchmark_opencode_go_kimi.yaml) | Kimi K3の独立実行 | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |
| [`benchmark_gpt56_recovery.yaml`](benchmark_gpt56_recovery.yaml) | GPT-5.6 Solの最終recovery run | [`benchmark-v2-production-status-2026-07-24.md`](../docs/benchmark-v2-production-status-2026-07-24.md) |

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
`benchmark_opencode_go_candidates.yaml`を参照するため、現行の正式実行や旧結果の厳密な再現には
使用しないでください。

## 安全な使い方

- APIキーをYAMLやGitへ書かず、READMEに記載した環境変数を使う
- `pilot`と全量実行には別の空出力先を使う
- 既存成果物とfingerprintが一致しない場合は、新しい出力先から始める
- 現行設定を変更すると正式計測の指紋が変わるため、過去のpilot合格票を流用しない
