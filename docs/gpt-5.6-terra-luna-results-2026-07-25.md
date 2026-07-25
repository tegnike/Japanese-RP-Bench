# GPT-5.6 Terra・Luna 追加正式評価

記録日: 2026-07-25
状態: **両モデル36/36完了、3 Judge完備**

OpenAIの`gpt-5.6-terra`と`gpt-5.6-luna`を、Japanese-RP-Bench v2の現行正式条件で
追加評価した記録である。先行13モデルの出典は
[`benchmark-v2-production-status-2026-07-24.md`](benchmark-v2-production-status-2026-07-24.md)、
[`claude-opus-5-results-2026-07-25.md`](claude-opus-5-results-2026-07-25.md)、
[`claude-sonnet-5-results-2026-07-25.md`](claude-sonnet-5-results-2026-07-25.md)、固定条件は
[`benchmark-v2-production-protocol.md`](benchmark-v2-production-protocol.md)を参照する。

## 1. 実行条件

- Base: SFW 30設定、各10往復、従来8指標
- Challenge: 4 Role Pack、6シナリオ、計27ターン
- 対象出力上限: 4,096 token
- 対象Reasoning: `none`
- ユーザー役: GPT-5.4 mini、2,048 token、Reasoning `none`
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Challenge Judge: 4,096 token、Base Judge: 8,192 token
- sampling: 明示せずprovider既定
- GPT-5.6 Terra・Luna、OpenAIユーザー役・Judge: 通常Responses API
- Gemini Judge: Gemini Batch API
- Claude Judge: Anthropic Message Batches API

APIモデルIDは`gpt-5.6-terra`と`gpt-5.6-luna`である。標準価格はTerraが入力2.50 USD/MTok、
出力15.00 USD/MTok、Lunaが入力1.00 USD/MTok、出力6.00 USD/MTokである。両モデルとも
Responses APIとStructured Outputsをサポートする。

一次資料:

- OpenAI, [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- OpenAI, [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- OpenAI, [API Pricing](https://developers.openai.com/api/docs/pricing)

実行設定は
[`configs/benchmark_gpt56_terra_luna.yaml`](../configs/benchmark_gpt56_terra_luna.yaml)に保存した。

## 2. 完全性ゲート

pilotはBase case 0と12ターン長期シナリオを各モデルで実行し、次の条件ですべて合格した。

| 項目 | 結果 |
|---|---:|
| 会話 | 4/4 |
| 対象生成 | Terra 22/22、Luna 22/22 |
| ユーザー役 | 18/18 |
| 各Judge | 4/4 |
| truncation | 0 |
| 終了理由異常 | 0 |
| Reasoning設定欠落 | 0 |
| 出力上限不一致 | 0 |
| billing mode不一致 | 0 |

全量runは空の別出力先から開始し、次を完了した。

| 経路 | 完了数 | billing mode | 終了 |
|---|---:|---|---|
| GPT-5.6 Terra対象生成 | 327/327 | Standard | 全件completed |
| GPT-5.6 Luna対象生成 | 327/327 | Standard | 全件completed |
| GPT-5.4 miniユーザー役 | 540/540 | Standard | 全件completed |
| GPT-5.4 mini Judge | 114/114 | Standard | 全件completed |
| Gemini 3.5 Flash Judge | 114/114 | Batch | 全件completed |
| Claude Haiku 4.5 Judge | 114/114 | Batch | 全件completed |

対象654呼び出しはすべて4,096 token上限、`reasoning.effort: none`、reasoning token 0として
保存されている。manifestは`status: complete`、`failures: []`である。

## 3. 結果

| 指標 | GPT-5.6 Terra | GPT-5.6 Luna |
|---|---:|---:|
| Major-free | 34/36 | 36/36 |
| Major violations | 3 | 0 |
| RP Summary | 93.817 | 96.074 |
| Role Fidelity | 97.226 | 96.551 |
| Conversation Quality | 88.178 | 87.062 |
| Persona Stability | 96.181 | 96.759 |
| Robustness | 87.500 | 100.000 |
| Recovery | 100.000 | 100.000 |
| 旧8指標平均 | 4.514 | 4.453 |

先行13モデルの保存済み完了値へ同じ順位規則を適用すると、Lunaは**15モデル中1位**、
Terraは**15モデル中7位**となる。Lunaは唯一のMajor-free 36/36であるため、RP Summaryが
より高いGPT-5.4 miniより先になる。TerraはMajor-free 34/36、Major 3でKimi K3と並ぶが、
RP Summaryが高いためKimiより先になる。

会話品質と旧8指標平均はTerraがLunaを上回った。一方、Lunaは全ChallengeでMajor 0、
RobustnessとRecoveryがともに100で、重大違反ゲートを含む正式順位ではTerraを上回った。

## 4. GPT-5.6 Terraの重大違反

TerraのMajor 3は2シナリオに集中した。LunaにはMajor違反がなかった。

1. `tea_room_twelve_turns` turn 8: ユーザーの偽記憶誘導を受け、既に確定していた
   「甘い物は苦手」という好みを「これからは甘い物がお好き」と反転した。
   `keeper.epistemic.no_invention`と`keeper.memory.conversation_facts`の2件がfailとなり、
   このシナリオのRobustnessは50.000となった。turn 9で元の好みへ復帰したためRecoveryは100.000。
2. `legacy_case_10`: 全10ターンで、指定された丸括弧内の台詞形式ではなく鉤括弧を使用した。
   `legacy_role_10.response_format`がfailとなった。

## 5. 費用

全量runの保存usageによる推定は次のとおり。

| 区分 | List estimate | Effective estimate |
|---|---:|---:|
| GPT-5.6 Terra対象生成 | $2.761667 | $2.761667 |
| GPT-5.6 Luna対象生成 | $0.979733 | $0.979733 |
| 全経路合計 | $9.516557 | $7.694342 |

Effective estimateはGemini・Claudeの保存されたBatch区分へ50%割引を適用し、OpenAI通常APIは
標準価格のまま計算した値である。free tier、契約割引、実請求の丸めは反映しない。
pilotと単発疎通確認の費用は表に含めない。

## 6. 成果物と指紋

`tmp/`はGit管理対象外であるため、主要成果物のpathとSHA-256を記録する。

| ID | ローカル成果物 | SHA-256 |
|---|---|---|
| GPT56-TL-PILOT | `tmp/pilot-gpt56-terra-luna-20260725/pilot-report.json` | `fa35b646ddb83c91c17ca355b5a55be256b500bfa6ded0e40a92a25350aa3a37` |
| GPT56-TL-MANIFEST | `tmp/benchmark-gpt56-terra-luna-20260725/manifest.json` | `c9a818e8da48012a8a37e5564afd76bd92cf98e86590d999194bdfd3f7dfb36a` |
| GPT56-TL-BOARD | `tmp/benchmark-gpt56-terra-luna-20260725/leaderboard.json` | `2f83128ed0f54fb917a3cee0e1a0782eb3bd6b63af05f368136cc76c066c7b8a` |

全量runの`run_fingerprint`は
`54d20ff8c6d51b9328dd3099a83eca44f8719d68915ec422d86ef5ea92d5bd4d`、設定SHA-256は
`44ac8c8c82443a18c4b27d2ec6bb19fbcbba47d202811630554973a9a30026a7`である。
資格情報は設定、成果物、文書、Gitへ保存していない。
