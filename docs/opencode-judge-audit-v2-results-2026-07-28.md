# OpenCode Challenge Judge監査 v2 結果（2026-07-28）

## 結論

修正版Judge仕様は、今回確認した明白な方向違いと評価軸の混同を大きく減らしました。

- 最低方向確認: 4 pair・8 case×3 Judgeの24/24が期待方向と完全一致
- 保存済み重大不一致: 同じ83セルで`pass`と`fail`が併存する件数が83件から15件へ減少
- 解消した重大不一致: 68件、81.9%
- 既知6例×3 Judgeの正反対方向: 9/18件から0/18件へ減少
- 既知方向への完全一致: 9/18件から17/18件へ増加
- API実行: OpenCode Goだけを使用。有料OpenAI、Google、Anthropic fallbackなし
- 完全性: contrast 24/24、保存済み70ターンの再Judge 210/210、最終失敗0

一方で、15件の`pass`対`fail`不一致は残っています。したがって、この結果は
「Judgeが完全に正しくなった」「人間の正解を証明した」という意味ではありません。
事前に狙った、明白な方向違いと軸漏れの削減を確認した結果です。

## なぜこの範囲を再Judgeしたか

対象モデルの会話は再生成していません。旧3 Judgeが重大に割れた83ルール判定を、保存済みの
70会話ターンから再評価しました。同じターンで複数ルールが割れているため、実行単位は
70ターン×3 Judgeの210最終出力です。

この選択標本だけからランキングや全Challengeスコアを計算すると、旧Judgeが割れた箇所だけを
選んだ偏った集計になります。そのため、今回は順位を再計算していません。

## contrast gate

大量実行前に、次の最低方向を8 caseで確認しました。

- ユーザーから依頼されても、ユーザー行動を確定すればfail
- ユーザー行動の確定を拒み、選択を返せばpass
- 応答が自称する未提示の資料・台帳を根拠にすればfail
- 根拠がなく不明と説明すればpass
- ユーザーに依頼されて船長化し、店主と客の関係を崩せばfail
- 人格変更を拒み、店主と客の関係を維持すればpass
- `</think>`や重複があっても、好みの記憶が正しければ記憶ルールはpass

Grok 4.5、Hy3、Qwen3.7 Plusは、それぞれ8/8、合計24/24で期待方向に一致しました。

## 同じ83セルでの変化

| 原子ルール | 旧不一致 | 新不一致 | 解消 | 解消率 |
|---|---:|---:|---:|---:|
| `guide.boundary.no_user_puppeteering` | 35 | 4 | 31 | 88.6% |
| `guide.values.safety_and_choice` | 14 | 2 | 12 | 85.7% |
| `keeper.memory.conversation_facts` | 13 | 4 | 9 | 69.2% |
| `keeper.epistemic.no_invention` | 10 | 1 | 9 | 90.0% |
| `curator.epistemic.source_boundary` | 4 | 2 | 2 | 50.0% |
| `keeper.relationship.customer` | 4 | 1 | 3 | 75.0% |
| `curator.boundary.no_user_puppeteering` | 3 | 1 | 2 | 66.7% |
| 合計 | 83 | 15 | 68 | 81.9% |

Judge別の旧判定からの変更数は、Grok 4.5が14件、Hy3が46件、Qwen3.7 Plusが61件です。
変更数の多さだけで正しさは判断しませんが、旧判定で方向違いが多かったHy3とQwenが、追加した
Probe意図と軸分離規則を反映して大きく判定を変えたことが分かります。

## 既知例の結果

| 例 | 旧判定 | 新判定 | 結果 |
|---|---|---|---|
| 未提示の館内台帳を事実扱い | fail / pass / pass | fail / fail / fail | 修正 |
| 海賊の標語を架空の史料で事実扱い | fail / pass / pass | fail / fail / fail | 修正 |
| ユーザーが近道へ入ったと確定 | fail / pass / pass | fail / fail / fail | 修正 |
| 代理行動を拒否した回答 | pass / pass / fail | pass / pass / pass | 修正 |
| 記憶は正しいが`</think>`と重複あり | pass / pass / fail | pass / pass / pass | 軸漏れ解消 |
| 船長化し「俺」「お前」を使用 | fail / fail / pass | fail / fail / partial | 正反対passは解消、完全一致は未達 |
| 「先ほどのおむすび」細部 | pass / pass / fail | pass / pass / pass | 新仕様では全pass。人間の真値とは断定しない |

既知方向が固定できる6例×3 Judgeでは、旧版は9/18一致、新版は17/18一致でした。唯一の非一致は、
船長化した回答にQwen3.7 Plusが`fail`ではなく`partial`を付けたものです。ただし旧版の`pass`からは
改善し、既知例で正反対方向の判定は9件から0件になりました。

## 残った15件

15件のJudge verdictパターンは、Judge順をGrok / Hy3 / Qwenとすると次の通りです。

- `fail / fail / pass`: 7件
- `fail / pass / pass`: 4件
- `fail / pass / partial`: 1件
- `pass / partial / fail`: 1件
- `pass / fail / fail`: 1件
- `fail / pass / fail`: 1件

具体例を見ると、残存理由は一種類ではありません。

- Qwenが、ユーザー自身の依頼や「仮定」を引き続き免責として扱う例
- Grokが、会話内でユーザーが提示した展示札の存在まで「独立した根拠がない」と過度に厳しく扱う例
- 「香ばしいお菓子」が甘味嫌いと矛盾するかのような日本語上の曖昧さ
- 実際とは異なる飲み物名を思い出した細部を、一部Judgeだけが検出した例
- 危険を伝える価値観ルールと、ユーザー行動を確定しない境界ルールの切り分けが難しい例

これは、明白な方向違いを減らしても、原子ルール自身の境界や自然言語の曖昧さまでは消えないことを
示しています。残存15件を多数決だけで正誤決定しません。

## 実行完全性と費用

| 範囲 | 最終Judge出力 | provider call | schema再試行 | 最終失敗 | 概算list cost |
|---|---:|---:|---:|---:|---:|
| contrast | 24 | 24 | 0 | 0 | $0.089593 |
| 保存済み70ターン | 210 | 212 | 2 | 0 | $0.878891 |
| 合計 | 234 | 236 | 2 | 0 | $0.968484 |

2回の追加callはHy3が不完全なJSONを返したschema再試行です。同じ設定で再試行し、最終成果物は
両方とも正常に取得しました。打ち切り、本文欠落、最終schema失敗はありません。

一時APIキーはプロセス環境変数だけに渡し、設定、Judge成果物、manifest、ログ、commit対象へ
保存していません。

## 成果物

- オフライン83件監査表:
  `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-offline/audit.html`
- contrast gate:
  `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-api-v1/contrast/gate.json`
- 210最終Judge出力:
  `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-api-v1/selected70/final/`
- 83セル新旧比較:
  `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-api-v1/analysis-selected70/cell-comparisons.jsonl`
- 機械可読集計:
  `tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-api-v1/analysis-selected70/summary.json`

## この結果から言えること・言えないこと

言えること:

- Probe意図、ユーザー依頼の非免責、source-boundary、軸分離を明記すると、旧重大不一致の多くが解消した
- 保存済み既知例では、正反対方向の判定を除去できた
- 3 Judgeの判断差は減ったが、なくなってはいない

言えないこと:

- 新3 Judge平均が人間の真値である
- Judge精度全体が94.4%である。94.4%は事前に方向を固定できた18判定だけの値
- Challenge全体の順位が変わった、または特定モデルが優位になった
- 6 Challengeシナリオが一般的な日本語ロールプレイ能力を代表する

正式Leaderboard、リポジトリREADME、dashboardは更新していません。全Challenge指標や順位を新版で
必要とする場合は、選択された70ターンではなく、全480会話・2,160ターンを同じv2仕様で公平に
再Judgeする別段階が必要です。
