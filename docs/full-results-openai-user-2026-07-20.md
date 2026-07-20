# Japanese-RP-Bench v2 Full Results — GPT-5.4 miniユーザー役（2026-07-20）

## 実行条件

- Base: 元のSFWデータセット30設定、各10往復、従来8指標
- Base追加評価: 同じ会話に対する原子ルール、ターン別追従度、長期安定性
- Challenge: 追加Role Packの6シナリオ、計27ターン
- 対象: GPT-5.6 Sol、GPT-5.4 mini、Gemini 3.5 Flash、Gemini 3.1 Flash-Lite、Claude Haiku 4.5
- ユーザー役: GPT-5.4 mini
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- 成果物: 180会話、1,635対象応答、450 Base判定、405 Challengeターン判定、180レポート

## Challengeの内容

Challengeは知識問題ではなく、キャラクター設定を崩しやすい状況に対する追従性を測ります。

1. `career_mentor_baseline`: 不足情報を勝手に埋めず、実務的な助言とユーザーの選択権を維持できるか。
2. `wind_guide_baseline`: 危険な近道を取ったと決めつける誘導を拒み、その後も案内人として会話を続けられるか。
3. `museum_curator_injection`: 引用文中の人格置換命令、歴史の捏造、ユーザーが盗んだという代理行動に抵抗できるか。
4. `tea_room_twelve_turns`: 12ターンにわたり好みを記憶し、偽の設定更新や海賊人格への上書きに抵抗し、元人格へ復帰できるか。
5. `nikechan_baseline`: AIニケちゃんとして、関係性と実務的な応答方針を維持できるか。
6. `nikechan_adversarial`: 名前・一人称・呼称の置換、存在しない昨日の合意の捏造を拒み、元人格へ復帰できるか。

Challengeのユーザー発言は固定台本です。動的なユーザー役LLMを使うのはBase 30設定です。

## 結果

`旧8指標平均`は元ベンチと同じ8指標の平均（1〜5）です。それ以外はv2の追加指標（0〜100）です。

| Target | 旧8指標平均 | Core fidelity | Quality | Stability | Robustness | Recovery | Major violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | 4.549 | 96.647 | 88.549 | 95.949 | 100.000 | 100.000 | 0 |
| GPT-5.4 mini | 4.446 | 96.991 | 86.022 | 96.759 | 100.000 | 100.000 | 0 |
| Gemini 3.1 Flash-Lite | 4.432 | 95.602 | 86.293 | 94.583 | 82.291 | 95.833 | 2 |
| Gemini 3.5 Flash | 4.399 | 93.502 | 84.998 | 90.959 | 62.500 | 95.833 | 8 |
| Claude Haiku 4.5 | 4.096 | 88.059 | 78.705 | 90.278 | 90.625 | 100.000 | 8 |

旧8指標の会話品質はGPT-5.6 Sol、追従性と長期安定性はGPT-5.4 miniが僅差で首位でした。Gemini 3.1 Flash-LiteはGemini 3.5 FlashよりCore fidelity、Quality、Stability、Robustnessが高く、このプロトコルでは単純なモデル世代・価格順にはなりませんでした。

## ユーザー役変更による差

同じ5対象・同じ3 Judgeで、ユーザー役だけをGemini 3.5 FlashからGPT-5.4 miniへ変更した差です。Challengeは固定台本なので、差の中心はBase会話の生成にあります。

| Target | 旧8指標平均 Δ | Core Δ | Quality Δ | Stability Δ | Robustness Δ | Major violations Δ |
|---|---:|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | -0.006 | -0.321 | -0.056 | +1.273 | +0.000 | 0 |
| GPT-5.4 mini | -0.033 | -0.648 | -1.307 | +1.389 | +0.000 | 0 |
| Gemini 3.5 Flash | -0.013 | +1.508 | -0.779 | +2.209 | -7.291 | +3 |
| Gemini 3.1 Flash-Lite | +0.036 | +2.656 | +1.062 | +4.120 | +13.541 | -4 |
| Claude Haiku 4.5 | +0.142 | +7.199 | +2.633 | +12.963 | -9.375 | -14 |

GPT系2モデルはユーザー役変更でも比較的安定しましたが、Gemini系とHaikuは指標が大きく動きました。これはユーザー役も測定結果へ影響することを示すため、異なるユーザー役で得た数値を同一ランキングとして混ぜるべきではありません。

## 使用量と費用

- 入力: 11,156,840 token
- 出力: 1,706,486 token（うちreasoningとして明示されたもの38,071 token）
- cached input: 3,850,263 token
- 定価換算合計: `$23.667`
  - 対象モデル生成: `$8.975`
  - Judge: `$11.003`
  - ユーザー役: `$3.689`
- プロバイダー別:
  - OpenAI: `$11.510`
  - Gemini: `$5.520`
  - Anthropic: `$6.637`

OpenAIを無料枠で賄う前提の支払見込みは、Gemini約`$5.52`、Anthropic約`$6.64`、合計約`$12.16`です。これは成功して成果物へ記録された呼び出しの定価換算で、空応答や不正JSONによる失敗呼び出しが請求対象になった場合、実請求は僅かに上振れします。

## 検証と再現

- manifest: `complete`
- 会話 / 判定 / レポート: 180 / 180 / 180
- Base判定は各会話3 Judge、Challenge判定は各ターン3 Judgeで不一致0
- テスト: 16件成功
- APIキーのリポジトリ混入: 0件

```bash
japanese-rp-bench-v2 run \
  --config configs/benchmark_full.yaml \
  --output tmp/benchmark-full \
  --workers 4
```

ランナーは会話、Judge返答、レポートを逐次保存し、同じ出力先を指定すると不足分だけ再開します。HTTP障害、空レスポンス、不正なJudge JSONは再試行します。
