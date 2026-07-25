# Claude Sonnet 5 追加正式評価

記録日: 2026-07-25
状態: **36/36完了、3 Judge完備**

Anthropicの`claude-sonnet-5`を、Japanese-RP-Bench v2の現行正式条件で追加評価した記録である。
Claude Opus 5の追加結果は
[`claude-opus-5-results-2026-07-25.md`](claude-opus-5-results-2026-07-25.md)、
先行11モデルは
[`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)
を参照する。

## 1. 実行条件

- Base: SFW 30設定、各10往復、従来8指標
- Challenge: 4 Role Pack、6シナリオ、計27ターン
- 対象出力上限: 4,096 token
- ユーザー役: GPT-5.4 mini、2,048 token、Reasoning `none`
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Challenge Judge: 4,096 token、Base Judge: 8,192 token
- sampling: 明示せずprovider既定
- 対象Sonnet 5とClaude Judge: Anthropic Message Batches API
- Gemini Judge: Gemini Batch API
- OpenAIユーザー役・Judge: 通常Responses API

Sonnet 5はadaptive thinking既定有効、effort既定`high`であるため、対象の最小Reasoning条件を
`thinking: {type: disabled}`と`output_config: {effort: low}`へ対応付けた。APIモデルIDは
`claude-sonnet-5`である。2026-08-31までの導入価格として標準入力2 USD/MTok、出力10 USD/MTok、
Batch入力1 USD/MTok、出力5 USD/MTokを使用した。

一次資料:

- Anthropic, [What's new in Claude Sonnet 5](https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5)
- Anthropic, [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- Anthropic, [Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

実行設定は
[`configs/benchmark_claude_sonnet_5.yaml`](../configs/benchmark_claude_sonnet_5.yaml)に保存した。

## 2. 完全性

pilotは会話2/2、Sonnet 5生成22/22、各Judge 2/2を完了し、truncation、終了理由異常、
Reasoning設定欠落、出力上限不一致、billing mode不一致はすべて0だった。

全量runは次を完了した。

| 経路 | 完了数 | billing mode | 終了 |
|---|---:|---|---|
| Claude Sonnet 5対象生成 | 327/327 | Batch | 全件completed |
| GPT-5.4 miniユーザー役 | 270/270 | Standard | 全件completed |
| GPT-5.4 mini Judge | 57/57 | Standard | 全件completed |
| Gemini 3.5 Flash Judge | 57/57 | Batch | 全件completed |
| Claude Haiku 4.5 Judge | 57/57 | Batch | 全件completed |

manifestは`status: complete`、`failures: []`で、provider失敗、再投入、打ち切りは0である。

## 3. 結果

| 指標 | Claude Sonnet 5 |
|---|---:|
| Eligible | 29/36 |
| Major violations | 7 |
| RP Balance | 92.984 |
| Core fidelity | 92.593 |
| Conversation quality | 83.669 |
| Long-term stability | 88.657 |
| Robustness | 100.000 |
| Recovery | 100.000 |
| 旧8指標平均 | 4.290 |

Challengeは全6シナリオでMajor 0だった。adversarial、core-ja、custom、long-horizonの
トラック別Core fidelityはすべて100.000、legacy-baseは91.111である。

先行12モデルの完了値へ同じ順位規則を適用すると、Claude Sonnet 5は**13モデル中11位**となる。
Eligible 29/36、Major 7でMiMo V2.5 Proと並ぶが、RP Balanceが高いためSonnet 5が先になる。

## 4. 重大違反

7件はすべてBaseで、Challengeにはなかった。

- `legacy_case_02`: 最終ターンに括弧付き動作描写を追加
- `legacy_case_10`: 指定された括弧形式ではなく引用符形式を継続
- `legacy_case_13`: 指定形式外の引用符と最終ターンの内面描写
- `legacy_case_17`: 引用符付き発話と括弧付き動作描写
- `legacy_case_19`: 複数ターンで地の文による動作・状況描写
- `legacy_case_20`: 物語ナレーションとロールプレイ終了のメタ文
- `legacy_case_23`: ユーザー行動の代筆と複数NPCの直接操作

`legacy_case_10`、`17`、`20`はJudge間に各1件の不一致があったが、3 Judge集約ではmajor ruleの
failとなった。ほか4ケースの不一致は0である。

## 5. 費用

| 区分 | List estimate | Effective estimate |
|---|---:|---:|
| Claude Sonnet 5対象生成 | $2.641362 | $1.320681 |
| 全経路合計 | $5.677741 | $3.405357 |

Effective estimateは保存されたBatch区分へ50%割引を適用し、OpenAI通常APIは標準価格のまま
計算した値である。free tier、契約割引、実請求の丸めは反映しない。pilot費用は含めない。

## 6. 成果物と指紋

| ID | ローカル成果物 | SHA-256 |
|---|---|---|
| SONNET5-PILOT | `tmp/pilot-claude-sonnet-5-20260725/pilot-report.json` | `b9e57f68a885c546a3c223018783f1d55ea9eab2b241f844562f25b4b0cde1e6` |
| SONNET5-MANIFEST | `tmp/benchmark-claude-sonnet-5-20260725/manifest.json` | `1f158c5f41db3cdcad7d528c8f89f59fd99f64b22be4b26b5710e764ef1ca855` |
| SONNET5-BOARD | `tmp/benchmark-claude-sonnet-5-20260725/leaderboard.json` | `795ffcdbe31b4568286b815ad66d609aa054deaf1e2b594dc3057bfb5259c080` |

全量runの`run_fingerprint`は
`d0893364c292eea6f482718d685400bf05ba85bf76b514aa400e692a6c19bf13`、
設定SHA-256は
`8c89b832fd5a58936f67bf5e024040acce68ae9772e2d908eea45f5a8db70b04`である。
資格情報は設定、成果物、文書、Gitへ保存していない。
