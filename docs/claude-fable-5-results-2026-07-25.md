# Claude Fable 5 追加評価

記録日: 2026-07-25
状態: **35/36シナリオの参考評価完了、1シナリオ除外、正式順位対象外**

Anthropicの`claude-fable-5`をJapanese-RP-Bench v2の現行条件で追加評価した記録である。
`legacy_case_01`の2ターン目だけが本文なしの`cyber` refusalとなったため、同一入力・同一上限で
合計5回まで再試行した。5回とも拒否されたため、このシナリオ全体だけを採点から除外し、
残り35シナリオを最後まで評価した。

36シナリオを完備していないので正式Leaderboardへは加えない。以下の値は、35/36シナリオを
対象とする**参考値**である。

## 1. 実行条件

- Base: SFW 30設定、各10往復、従来8指標
- Challenge: 4 Role Pack、6シナリオ、計27ターン
- 対象出力上限: 4,096 token
- ユーザー役: GPT-5.4 mini、2,048 token、Reasoning `none`
- Judge: GPT-5.4 mini、Gemini 3.5 Flash、Claude Haiku 4.5
- Challenge Judge: 4,096 token、Base Judge: 8,192 token
- sampling: 明示せずprovider既定
- 対象Fable 5とClaude Judge: Anthropic Message Batches API
- Gemini Judge: Gemini Batch API
- OpenAIユーザー役・Judge: 通常Responses API

Fable 5はAdaptive Thinkingが常時有効で、`thinking: {type: disabled}`を送るとAPIが拒否する。
そのため現行プロトコルの最小Reasoning条件は、thinking設定を送らず
`output_config: {effort: low}`だけを指定する形へ対応付けた。通常価格は入力10 USD/MTok、
出力50 USD/MTok、Batch実効価格は入力5 USD/MTok、出力25 USD/MTokである。

一次資料:

- Anthropic, [Introducing Claude Fable 5 and Claude Mythos 5](https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5)
- Anthropic, [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- Anthropic, [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
- Anthropic, [Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

実行設定は
[`configs/benchmark_claude_fable_5.yaml`](../configs/benchmark_claude_fable_5.yaml)に保存した。

## 2. pilot

pilotは合格した。

| 経路 | 完了数 | billing mode | 終了 |
|---|---:|---|---|
| Claude Fable 5対象生成 | 22/22 | Batch | 全件completed |
| GPT-5.4 miniユーザー役 | 9/9 | Standard | 全件completed |
| GPT-5.4 mini Judge | 2/2 | Standard | 全件completed |
| Gemini 3.5 Flash Judge | 2/2 | Batch | 全件completed |
| Claude Haiku 4.5 Judge | 2/2 | Batch | 全件completed |

truncation、refusal、終了理由異常、Reasoning設定欠落、出力上限不一致、billing mode不一致は
すべて0だった。Fable対象22件のThinkingは合計371 tokenで、4,096 token上限内に収まった。

## 3. Fable refusalと5回再試行

対象は`claude-fable-5|legacy-base-ja|legacy_case_01|target|turn-2`である。直前のユーザー役応答
には、監視を避けるため正規物流へ資材を紛れ込ませ、拠点を分散する提案が含まれていた。
初回と追加4回は、入力、会話履歴、モデル、`effort: low`、4,096 token上限を変更していない。

| 試行 | 終了 | input/output token | response ID |
|---:|---|---:|---|
| 1 | 本文なし`cyber` refusal | 1,456 / 5 | `msg_011CdNtE6afadBLnuQvoSyKC` |
| 2 | 本文なし`cyber` refusal | 1,456 / 5 | `msg_011CdNwAUs6wyDNzhGY9qXW3` |
| 3 | 本文なし`cyber` refusal | 1,456 / 3 | `msg_011CdNwHHLkZER1oZsihtPnj` |
| 4 | 本文なし`cyber` refusal | 1,456 / 5 | `msg_011CdNwSR8Zr1ZmgFnX3ybbi` |
| 5 | 本文なし`cyber` refusal | 1,456 / 9 | `msg_011CdNwWtvm8LJC7wiM8bk9s` |

保存済みBatch結果はリクエスト自体が`succeeded`で、`stop_reason: refusal`、
`stop_details.category: cyber`、content block 0だった。これは通信失敗ではなく、
Fable 5が同じ入力に対して返したモデル終端結果である。

5回でも本文が得られなかったため、未生成の後続ターンを推測や別モデルで補完せず、
`legacy_case_01`全体だけを除外した。除外した指標は、この1シナリオのBase従来8指標、
v2指標、重大違反判定である。

## 4. 35/36シナリオの参考結果

| 項目 | 参考値 |
|---|---:|
| 正式順位 | - |
| 評価完了 | 35/36 |
| Eligible | 31/35 |
| Major violation | 4 |
| RP Balance | **95.645** |
| Core Fidelity | 93.714 |
| Deterministic Compliance | 100.000 |
| Judge Fidelity | 93.714 |
| Conversation Quality | 88.082 |
| Long-term Stability | 96.429 |
| Robustness | 100.000 |
| Recovery | 100.000 |

Base従来指標は29/30設定の参考値である。

| 指標 | 参考値 |
|---|---:|
| Overall | **4.493** |
| Roleplay Adherence | 4.310 |
| Consistency | 4.701 |
| Contextual Understanding | 4.701 |
| Expressiveness | 4.425 |
| Creativity | 4.379 |
| Naturalness of Japanese | 4.621 |
| Enjoyment of the Dialogue | 4.437 |
| Appropriateness of Turn-Taking | 4.368 |

重大違反4件はすべてBaseで、Challengeの重大違反は0だった。

- `legacy_case_03`: セリフのみ指定に対し、9ターン目へ`（静かに）`という状況描写が混入
- `legacy_case_04`: 6ターン目へ応答方針を説明するメタ注記が混入
- `legacy_case_13`: 指定された括弧内セリフ形式を一貫して使用しなかった
- `legacy_case_28`: 田村の発話や会議室の他メンバーの反応まで生成し、単一キャラクター境界を違反

除外した`legacy_case_01`については、取得できなかった値を0や部分点にせず、次のとおり
`-`として扱う。

| `legacy_case_01`の未取得項目 | 値 |
|---|---:|
| Base従来8指標 | - |
| Core Fidelityなどのv2指標 | - |
| Eligible / Major判定 | - |

Judgeは各56件、合計168件を完了した。Gemini Judgeの
`nikechan_adversarial` 3ターン目だけは初回が4,096 tokenで`MAX_TOKENS`となり、同一入力・同一
上限の2回目で完了した。採択したのは2回目の完全なJudge結果である。

## 5. 費用

全量runの集計には、採択した35シナリオだけでなく、Fable refusal 5回、除外直前までに完了した
ユーザー役と対象生成、Gemini Judgeの`MAX_TOKENS` 1回目も含めた。

| 区分 | List estimate | Effective estimate |
|---|---:|---:|
| pilot全経路 | $0.909481 | $0.474489 |
| 35/36参考評価全経路 | $18.275749 | $9.735691 |
| 合計 | **$19.185230** | **$10.210180** |

Fable refusal 5回だけの保存usageに基づく保守的な実効見積もりは`$0.037075`である。
Effective estimateはAnthropic/Gemini Batchへ50%割引を適用し、OpenAI通常APIは標準価格の
まま計算した。free tier、data-sharing incentive、provider側のrefusal課金調整は差し引かず、
保存された全usageを単価計算している。

## 6. 成果物と指紋

| ID | ローカル成果物 | SHA-256 |
|---|---|---|
| FABLE5-PILOT | `tmp/pilot-claude-fable-5-20260725/pilot-report.json` | `1774b7711545d283ac852caba5643ea780c298879ee6263aaac1fee9ddcfdcb5` |
| FABLE5-MANIFEST | `tmp/benchmark-claude-fable-5-20260725/manifest.json` | `735e0bf2dd9a4b1a66d4c0479597da181472789c9f9662af4cf732b667cdc124` |
| FABLE5-BOARD | `tmp/benchmark-claude-fable-5-20260725/leaderboard.json` | `aa5fee3e9490208a5cba551a8b98a905d7f06a3fe27fa67a959bad47074bb013` |
| FABLE5-REFUSALS | `tmp/benchmark-claude-fable-5-20260725/conversations/claude-fable-5/legacy-base-ja__legacy_case_01.generation-attempts.jsonl` | `2a531b18ba96f2a9cf183b6bc8ba45539c7ad0187f96afbabb6c7a8c43d2a5a5` |

全量runのprotocol fingerprintは
`231f5aa5ee0dd65064e33203ba246ddc51ec92932fa9a45afa5fd26f0e019518`、
fingerprint内の設定SHA-256は
`67ddc47e891b609e7dc15b97300c95096955b0be137a07cd4bded2ccad795902`である。
manifestとleaderboardは`status: partial`、期待36、評価35、除外1、正式rankなしとして保存した。
資格情報は設定、成果物、文書、Gitへ保存していない。
