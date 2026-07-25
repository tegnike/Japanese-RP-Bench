# Claude Opus 5 追加正式評価

記録日: 2026-07-25
状態: **36/36完了、3 Judge完備**

Anthropicの`claude-opus-5`を、Japanese-RP-Bench v2の現行正式条件で追加評価した記録である。
先行11モデルの出典と結果は
[`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)、
固定条件は
[`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)を参照する。

## 1. 実行条件

- Base: SFW 30設定、各10往復、従来8指標
- Challenge: 4 Role Pack、6シナリオ、計27ターン
- 対象出力上限: 4,096 token
- ユーザー役: GPT-5.4 mini、2,048 token、Reasoning `none`
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Challenge Judge: 4,096 token、Base Judge: 8,192 token
- sampling: 明示せずprovider既定
- 対象Claude Opus 5: Anthropic Message Batches API
- Gemini Judge: Gemini Batch API
- Claude Judge: Anthropic Message Batches API
- OpenAIユーザー役・Judge: ユーザー指定により通常Responses API

Claude Opus 5はthinkingとeffortの既定が従来Claudeと異なる。Anthropic公式資料ではthinkingが
既定有効、effortが既定`high`であるため、対象モデルの最小Reasoning条件を
`thinking: {type: disabled}`と`output_config: {effort: low}`へ明示的に対応付けた。
APIモデルIDは`claude-opus-5`、標準価格は入力5 USD/MTok、出力25 USD/MTokで、
Message Batchesは50%割引である。

一次資料:

- Anthropic, [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- Anthropic, [Prompting Claude Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5)
- Anthropic, [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)

実行設定は
[`configs/benchmark_claude_opus_5.yaml`](../configs/benchmark_claude_opus_5.yaml)に保存した。

## 2. 完全性ゲート

pilotはBase case 0と12ターン長期シナリオを使用し、次の条件ですべて合格した。

| 項目 | 結果 |
|---|---:|
| 会話 | 2/2 |
| Claude Opus 5対象生成 | 22/22 |
| 各Judge | 2/2 |
| truncation | 0 |
| 終了理由異常 | 0 |
| Reasoning設定欠落 | 0 |
| 出力上限不一致 | 0 |
| billing mode不一致 | 0 |

全量runは空の別出力先から開始し、次を完了した。

| 経路 | 完了数 | billing mode | 終了 |
|---|---:|---|---|
| Claude Opus 5対象生成 | 327/327 | Batch | 全件completed |
| GPT-5.4 miniユーザー役 | 270/270 | Standard | 全件completed |
| GPT-5.4 mini Judge | 57/57 | Standard | 全件completed |
| Gemini 3.5 Flash Judge | 57/57 | Batch | 全件completed |
| Claude Haiku 4.5 Judge | 57/57 | Batch | 全件completed |

Claude Opus 5の327呼び出しはすべて4,096 token上限、thinking disabled、effort low、
reasoning token 0として保存されている。manifestは`status: complete`、`failures: []`である。

## 3. 結果

| 指標 | Claude Opus 5 |
|---|---:|
| Eligible | 34/36 |
| Major violations | 2 |
| RP Balance | 95.559 |
| Core fidelity | 95.278 |
| Conversation quality | 88.537 |
| Long-term stability | 93.981 |
| Robustness | 100.000 |
| Recovery | 100.000 |
| 旧8指標平均 | 4.507 |

Challengeは全6シナリオでMajor 0だった。トラック別Core fidelityはadversarial、core-ja、
custom、long-horizonがすべて100.000、legacy-baseが94.333である。

先行11モデルの保存済み完了値へ同じ順位規則を適用すると、Claude Opus 5は**12モデル中5位**
となる。Eligibleを最優先するため、RP Balanceが高くても、Eligible 35/36の上位4モデルより
後になる。旧8指標平均4.507は12モデル中で最も高い。

## 4. 重大違反

重大違反はBase 30ケース中2件で、Challengeにはなかった。

1. `legacy_case_04`: 8ターン目の末尾に`Word count: 47`というメタ文字列が混入し、
   `response_format`がfailとなった。
2. `legacy_case_07`: 最終ターンの「ロールプレイ終了」要求へ従い、役を外れて会話全体を
   メタ説明したため、`response_format`がfailとなった。途中には韓国語の混入もあった。

両ケースとも3 Judgeの集約結果に不一致はない。2件目ではprofile fidelity、
world/scene consistency、single character/user agencyもpartialとなり、最終ターンの
persona fidelityは0だった。

## 5. 費用

全量runの保存usageによる推定は次のとおり。

| 区分 | List estimate | Effective estimate |
|---|---:|---:|
| Claude Opus 5対象生成 | $6.575095 | $3.287547 |
| 全経路合計 | $9.656551 | $5.390320 |

Effective estimateは保存されたBatch区分へ50%割引を適用し、OpenAI通常APIは標準価格のまま
計算した値である。free tier、契約割引、実請求の丸めは反映しない。pilot費用は表に含めない。

## 6. 成果物と指紋

`tmp/`はGit管理対象外であるため、主要成果物のpathとSHA-256を記録する。

| ID | ローカル成果物 | SHA-256 |
|---|---|---|
| OPUS5-PILOT | `tmp/pilot-claude-opus-5-20260725/pilot-report.json` | `92a9cf5c5d41f704f2692784ced391daeebceb78e0322cdf6567905b625c018f` |
| OPUS5-MANIFEST | `tmp/benchmark-claude-opus-5-20260725/manifest.json` | `a6dc69f2cfd41a55b64edb3ffd228ec6dc573f1e42194aa86f1f5adfed544a03` |
| OPUS5-BOARD | `tmp/benchmark-claude-opus-5-20260725/leaderboard.json` | `e96c4481c89bc3c14dcdc0346728a07fe140a3cbad0db7479357d19937f41819` |
| ALL-11 | `tmp/benchmark-all-11-20260724/leaderboard.json` | `c6d15514ad84d9079a0d428aa5446f7d655d1e677ee90715bd434db7c7113cd1` |

全量runの`run_fingerprint`は
`73da4d174e186ceece111c94d73fbb2d43cafc122c8ad0fe2d0e7249d4cb64a7`、
設定SHA-256は
`988cc802111e43bcbcb33ddb48f0dad19ec2038bd22baae8dd728ac847eb8dc0`である。
資格情報は設定、成果物、文書、Gitへ保存していない。
