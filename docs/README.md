# ドキュメント案内

Japanese-RP-Benchには、現行仕様、実行ガイド、日付時点の結果記録、フォーク元の保存資料が
あります。このページは、それぞれの役割と読む順序を示す索引です。

## 目的別の読み方

| 目的 | 最初に読む文書 | 次に読む文書 |
|---|---|---|
| ベンチマークの概要を知る | [リポジトリREADME](../README.md) | [v2設計概要](benchmark-v2.md) |
| 最新の主結果を確認する | [OpenCode Go Challenge反復評価](opencode-challenge-repeatability-results-2026-07-28.md) | [リポジトリREADME](../README.md) |
| 過去の単回15モデル評価を確認する | [評価履歴](evaluation-history.md) | [2026-07-25 GPT-5.6 Terra・Luna追加評価](gpt-5.6-terra-luna-results-2026-07-25.md) |
| 結果を正しく解釈する | [OpenCode Go Challenge反復評価](opencode-challenge-repeatability-results-2026-07-28.md) | [指標定義](metrics.md) |
| Challenge反復評価の計画を確認する | [OpenCode Go Challenge反復評価計画](opencode-challenge-repeatability-plan-2026-07-27.md) | [指標定義](metrics.md) |
| Challenge Judgeの問題と修正版を確認する | [OpenCode Challenge Judge監査 v2](opencode-judge-audit-v2-2026-07-28.md) | [Challenge反復評価計画](opencode-challenge-repeatability-plan-2026-07-27.md) |
| Challenge Judge v2の再評価結果を確認する | [OpenCode Challenge Judge監査 v2結果](opencode-judge-audit-v2-results-2026-07-28.md) | [Judge監査 v2仕様](opencode-judge-audit-v2-2026-07-28.md) |
| 残存15件の分類とJudge v2.1を確認する | [OpenCode Challenge Judge監査 v2.1](opencode-judge-audit-v21-2026-07-29.md) | [Judge監査 v2結果](opencode-judge-audit-v2-results-2026-07-28.md) |
| 過去の単回条件を再実行する | [単回評価プロトコル](benchmark-v2-production-protocol.md) | [設定ファイル案内](../configs/README.md) |
| OpenCode Goで実行する | [OpenCode Go実行ガイド](opencode-go.md) | [設定ファイル案内](../configs/README.md) |
| OpenCode Judge校正を実行する | [OpenCode Judge校正の事前登録](opencode-judge-calibration-preregistration-2026-07-27.md) | [反復計測計画](repeatability-and-opencode-sampling-plan-2026-07-27.md) |
| Role Packを作る | [Role Pack作成ガイド](../role_packs/README.md) | [v2設計概要](benchmark-v2.md) |
| 評価条件の変更履歴や旧結果を調べる | [評価履歴・監査資料](evaluation-history.md) | [フォーク元v1保存版](upstream-v1.md) |

## 文書の分類

### 現行仕様とガイド

| 文書 | 役割 |
|---|---|
| [`metrics.md`](metrics.md) | 指標、集計、順位規則の基準文書 |
| [`benchmark-v2.md`](benchmark-v2.md) | v2の設計、Role Pack、成果物、モデル構成の概要 |
| [`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md) | 過去の11モデル単回評価で固定した条件、停止条件、再開条件 |
| [`opencode-go.md`](opencode-go.md) | OpenCode Goの接続、API形式、実行、429時の再開方法 |
| [`repeatability-and-opencode-sampling-plan-2026-07-27.md`](repeatability-and-opencode-sampling-plan-2026-07-27.md) | 現行値の再現性監査、読み方、OpenCode Go優先の反復測定計画 |
| [`opencode-judge-calibration-preregistration-2026-07-27.md`](opencode-judge-calibration-preregistration-2026-07-27.md) | OpenCode Judge校正の分割、Reasoning、token上限、合格・停止条件 |
| [`opencode-challenge-repeatability-plan-2026-07-27.md`](opencode-challenge-repeatability-plan-2026-07-27.md) | 8対象、Challenge 6件、10生成、固定3 Judgeによる次段階のsource of truth |
| [`opencode-judge-audit-v2-2026-07-28.md`](opencode-judge-audit-v2-2026-07-28.md) | 保存済み83重大不一致のオフライン監査、修正版Judgeルーブリック、再Judge範囲 |
| [`opencode-judge-audit-v2-results-2026-07-28.md`](opencode-judge-audit-v2-results-2026-07-28.md) | contrast 24/24と保存済み83重大不一致のv2再Judge結果 |
| [`opencode-judge-audit-v21-2026-07-29.md`](opencode-judge-audit-v21-2026-07-29.md) | 残存15件の3分類、v2.1の限定修正、54/54 contrast、全体再Judge条件 |
| [`opencode-challenge-repeatability-results-2026-07-28.md`](opencode-challenge-repeatability-results-2026-07-28.md) | 現在の主結果。9モデル540会話、v2.1の7,290 Judge出力、区間、順位確率、全ペア比較 |
| [`role_packs/README.md`](../role_packs/README.md) | Role Packの構造、各フィールド、作成・検証手順 |
| [`configs/README.md`](../configs/README.md) | 現行設定、履歴用設定、補助スクリプトの使い分け |

### 最新の結果

| 文書 | 状態 |
|---|---|
| [`opencode-challenge-repeatability-results-2026-07-28.md`](opencode-challenge-repeatability-results-2026-07-28.md) | **現在の主結果**。9モデル×6シナリオ×10生成、v2.1で7,290 Judge出力完了 |
| [`gpt-5.6-terra-luna-results-2026-07-25.md`](gpt-5.6-terra-luna-results-2026-07-25.md) | 過去の単回15モデル評価を構成した追加結果 |
| [`claude-fable-5-results-2026-07-25.md`](claude-fable-5-results-2026-07-25.md) | 過去の単回参考値。1件を5回拒否後に除外し、残り35/36を完了 |
| [`claude-sonnet-5-results-2026-07-25.md`](claude-sonnet-5-results-2026-07-25.md) | 過去の単回追加評価。36/36完了 |
| [`claude-opus-5-results-2026-07-25.md`](claude-opus-5-results-2026-07-25.md) | 過去の単回追加評価。36/36完了 |
| [`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md) | 過去の先行11モデル単回評価。全モデル36/36完了 |

### 評価履歴と監査資料

[`evaluation-history.md`](evaluation-history.md)に、過去の試行、評価条件を変更した理由、
旧結果の扱い、日付付き監査文書への導線を時系列でまとめています。

2026-07-26〜27の固定会話Judge再現性監査と次段階の標本設計は
[`repeatability-and-opencode-sampling-plan-2026-07-27.md`](repeatability-and-opencode-sampling-plan-2026-07-27.md)
にまとめています。

### フォーク元の保存資料

| 文書・成果物 | 役割 |
|---|---|
| [`upstream-v1.md`](upstream-v1.md) | フォーク元README、2024年結果、旧CLIの保存版 |
| [`conversations/`](../conversations) | 2024年版32モデルの会話 |
| [`evaluations/`](../evaluations) | 2024年版32モデルの評価結果 |
| [`annotated_sample/`](../annotated_sample) | フォーク元の注釈サンプル |
| [`configs/eval_config.yaml`](../configs/eval_config.yaml) | v1 CLI用の設定例 |
| [`visualize.ipynb`](../visualize.ipynb) | v1成果物の可視化ノートブック |

## 基準文書の境界

- 指標名、算出式、順位規則は[`metrics.md`](metrics.md)を基準とします。
- 現在の主結果の対象、反復数、Judge、解析条件は
  [`opencode-challenge-repeatability-plan-2026-07-27.md`](opencode-challenge-repeatability-plan-2026-07-27.md)と
  [`opencode-judge-audit-v21-2026-07-29.md`](opencode-judge-audit-v21-2026-07-29.md)を基準とします。
- 過去の単回評価のモデル、上限、Reasoning、失敗時の扱いは
  [`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)に保存しています。
- 実際の実行値は設定ファイルと保存済み成果物、算出処理は`src/japanese_rp_bench/v2/`の
  実装を最終的な確認先とします。
- 日付付き文書は判断経緯を保存する記録であり、後日の状態に合わせて本文を書き換えません。

## 用語集

| 用語 | このリポジトリでの意味 |
|---|---|
| Base | フォーク元と同じSFW 30設定、各10往復、旧8指標を維持する評価部分 |
| Challenge | Role Packで追加した、敵対的指示、複数ターン維持、復帰などを測る追加シナリオ |
| 評価対象（target） | 能力を測られるモデル |
| ユーザー役（user simulator） | Base会話で評価対象の相手を生成するモデル |
| Judge | 会話や発話を指標・原子ルールに沿って採点する評価モデル |
| Role Pack | 役柄、原子ルール、シナリオ、ProbeをまとめたYAMLパッケージ |
| track | シナリオを集計上まとめる分類。Role Packのフォルダー名とは独立して`track:`で決まる |
| scenario | 1つの会話条件。役柄、ユーザー発話列、Probeを参照する |
| turn | ユーザー発話と評価対象の返答からなる1往復 |
| 原子ルール | 一度に1つの観点だけを判定する、最小単位の人格・行動ルール |
| Probe | 特定ターンとルールを取り出してbaseline、adversarial、recoveryを測る指定 |
| 疎通確認 | APIがモデルと設定を受理するかを見る小さな試行。Role PackのProbeとは別物 |
| pilot | 全量計測前に、上限、終了理由、Reasoning、Judge、成果物の完全性を確認する必須実行 |
| 全量実行（full run） | 設定された全シナリオを生成・評価する本実行 |
| artifact（成果物） | 会話、Judge結果、レポート、manifest、leaderboardなど保存された実行結果 |
| fingerprint（指紋） | 設定、データ、Role Pack、rubric、実装の組み合わせを識別するSHA-256値 |
| shard | 対象モデルの一部だけを独立して実行した成果物のまとまり |
| fresh run | 旧成果物を再利用せず、新しい指紋と空の出力先から始めた実行 |
| recovery run | 失敗原因を修正した後、同じ固定条件で対象をやり直した実行 |
| wave | 前ターンへ依存する会話を、同時に作成可能な要求単位で順番に処理する段階 |
| provider | OpenAI、Google、Anthropic、OpenCode Goなど、APIを提供する経路 |
| transport | 同じモデル・設定を送る同期APIまたはBatch APIという通信方式 |
| `incomplete` | 必須成果物が揃わず、0点ではなく順位対象外になった実行状態 |
| Major-free | 現在の反復評価では`major_violations == 0`だった会話の割合。総合順位の第1キー |
| Major | 重大ルールの`fail`件数を全シナリオで合計した値。少ないほど良い |
| RP Summary | Role Fidelity、Quality、Persona Stability、Robustness、Recoveryの単純平均。順位用の補助表示。Qualityを通じて旧8指標を間接的に含む |
| `ALL-11` | 2026-07-24の11モデル完了記録で使う、統合公開成果物の台帳ID |
| `Claude 5 shard` | 2026-07-25に追加したClaude Opus 5またはSonnet 5の単回pilot・全量成果物 |
| r3 / r6 / r7 | 同日の再実行を区別するローカルな反復番号。モデル性能上の意味はない |
| 定価換算 | 各社の表示単価をusageへ掛けた比較用見積もり |
| effective estimate | 成果物に記録されたBatch割引を反映した推定額。実請求額の保証ではない |
| SFW | フォーク元の`Japanese-RP-Bench-testdata-SFW`データセットを指す名称 |
| 2024 frozen | 保存済みの2024年版会話・評価をAPI再実行なしで再集計する凍結結果 |
| `legacy-base` | 現行モデルをフォーク元と同じ30設定・10往復で評価するBase track |

指標の表示名、JSONキー、算出式は[`metrics.md`](metrics.md)を参照してください。
