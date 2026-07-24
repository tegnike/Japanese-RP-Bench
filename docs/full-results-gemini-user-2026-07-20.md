# Japanese-RP-Bench v2 Full Results — Geminiユーザー役（旧プロトコル、2026-07-20）

> **旧プロトコルの保存資料:** これはGemini 3.5 Flashをユーザー役にした2026-07-20時点の
> 比較記録で、現行の正式順位には使いません。同日のGPT-5.4 miniユーザー役による旧結果は
> [`full-results-openai-user-2026-07-20.md`](full-results-openai-user-2026-07-20.md)、
> 現行結果は
> [`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
> を参照してください。下記コマンドが参照する追跡版configは後日更新されているため、
> 当時の成果物を厳密には再現しません。

## 実行条件

- Base: 元のSFWデータセット30設定、各10往復、従来8指標
- Base追加評価: 同じ会話に対する原子ルール、ターン別追従度、長期安定性
- Challenge: `core-ja`、`adversarial-ja`、`long-horizon-ja`、`custom/nikechan`の6シナリオ
- 対象: GPT-5.6 Sol、GPT-5.4 mini、Gemini 3.5 Flash、Gemini 3.1 Flash-Lite、Claude Haiku 4.5
- ユーザー役: Gemini 3.5 Flash
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- 成果物: 180会話、1,635対象応答、450 Base判定、405 Challengeターン判定、180レポート

## 結果

`Legacy score`は元ベンチと同じ8指標の平均（1〜5）です。それ以外はv2の追加指標（0〜100）です。

| Target | Legacy score | Core fidelity | Quality | Stability | Robustness | Recovery | Major violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | 4.555 | 96.968 | 88.605 | 94.676 | 100.000 | 100.000 | 0 |
| GPT-5.4 mini | 4.479 | 97.639 | 87.329 | 95.370 | 100.000 | 100.000 | 0 |
| Gemini 3.5 Flash | 4.412 | 91.994 | 85.777 | 88.750 | 69.791 | 100.000 | 5 |
| Gemini 3.1 Flash-Lite | 4.396 | 92.946 | 85.231 | 90.463 | 68.750 | 95.833 | 6 |
| Claude Haiku 4.5 | 3.954 | 80.860 | 76.072 | 77.315 | 100.000 | 100.000 | 22 |

従来型の会話品質ではGPT-5.6 Sol、追加した追従性ではGPT-5.4 miniが僅差で首位でした。Claude Haiku 4.5はChallengeでは強く、攻撃耐性と復帰は100点でしたが、Baseの「セリフのみ」などの出力形式に地の文や動作描写を混ぜる傾向がありました。Baseで3 Judgeが記録した55件のルールfailのうち42件が`response_format`で、低得点の主因です。

## Judge追加による変化

Haiku Judge追加前後で、保存済みの4モデルの会話自体は変更していません。

| Target | Legacy score（2 Judge） | Legacy score（3 Judge） | 差 |
|---|---:|---:|---:|
| GPT-5.6 Sol | 4.600 | 4.555 | -0.045 |
| GPT-5.4 mini | 4.548 | 4.479 | -0.069 |
| Gemini 3.5 Flash | 4.446 | 4.412 | -0.034 |
| Gemini 3.1 Flash-Lite | 4.402 | 4.396 | -0.006 |

Baseの全5対象を平均したJudge別スコアは、Gemini Judgeが4.816、Haiku Judgeが4.288、GPT Judgeが3.974でした。Haikuは3 Judgeの中間で、単に最も厳しいJudgeではありません。Haiku対象自身もGPT Judge 3.596、Haiku Judge 3.904、Gemini Judge 4.363と全Judgeで他対象より低く、結果は特定Judgeだけの偏りでは説明できません。

## 2024年凍結版との参考比較

保存済み評価を再集計した旧版上位は次の通りです。

| Rank | 2024 target | Legacy score |
|---:|---|---:|
| 1 | Claude 3 Opus | 4.403 |
| 2 | Claude 3.5 Sonnet | 4.397 |
| 3 | GPT-4o mini | 4.324 |
| 4 | Gemini 1.5 Pro | 4.268 |
| 5 | CyberAgent Mistral-Nemo Japanese Instruct | 4.266 |

今回の上位3モデルは旧首位の4.403付近以上ですが、正式な同一ランキングにはしません。30設定、10往復、8指標は共通でも、旧版はユーザー役がClaude 3.5 Sonnet、Judgeが4モデル、今回はユーザー役がGemini 3.5 Flash、Judgeが3モデルだからです。モデル世代の進歩を示唆する参考値として扱います。

## 使用量と費用

- 入力: 11,517,130 token
- 出力: 1,796,777 token（うちreasoningとして明示されたもの44,910 token）
- cached input: 1,497,154 token
- 定価換算合計: `$28.246`
  - 対象モデル生成: `$9.698`
  - Judge: `$11.843`
  - ユーザー役: `$6.704`

Haiku追加による完全版成果物の増分は約`$10.186`でした。内訳はHaiku対象生成`$1.728`、Haiku Judge`$5.494`、Haiku対象を採点した既存2 Judge`$1.484`、追加Base会話のGeminiユーザー役`$1.481`です。Haiku Judgeは`low` thinkingを有効にしたため、非thinking前提の単純見積もりより出力tokenが増えています。

費用は設定ファイルの単価による概算です。無料枠、complimentary token、実請求時の割引は反映していません。

## 再現方法

```bash
japanese-rp-bench-v2 run \
  --config configs/benchmark_full_gemini_user.yaml \
  --output tmp/benchmark-full \
  --workers 4
```

ランナーは会話、Judge返答、レポートを逐次保存し、同じ出力先を指定すると不足分だけ再開します。APIの空レスポンスや不正なJudge JSONは最大3回再試行します。
