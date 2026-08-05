# OpenCode Challenge Judge監査 v2（2026-07-28）

## 結論

480会話と6,480最終Judge出力の収集自体は完全ですが、現行Judge結果をそのまま正解や
確定ランキングとして扱うことはできません。保存済み履歴には、ルールの意図と逆向きの判定と、
無関係なQuality問題を記憶ルールへ混ぜた判定が含まれていました。

この監査版では旧成果物を一切上書きせず、次の二つを別バージョンとして固定します。

1. adversarial/recovery Probe上のpass対fail不一致83件を比較できるオフライン監査表
2. Probe意図、軸分離、証拠境界を明記した`challenge-judge-audit-v2.0`ルーブリック

この変更は「人間の正解を得た」「Judge精度全体を証明した」という意味ではありません。
検証対象は、既知の明白な方向違いと評価軸の混同を減らせるかです。

## 固定した入力と境界

- 入力: `opencode-challenge-repeatability-20260727-v1`
- experiment fingerprint: `4a9a01c6439987c3ddfad03ac380daa6c1c18af97c1b76f8d696b8b322034bc0`
- 完全性: 480会話、2,160対象応答、6,480最終Judge出力
- 抽出対象: adversarialまたはrecovery Probeの対象ルールで、3 Judge内に`pass`と`fail`が併存するセル
- 除外: Probe対象外のターン・ルール、`partial`だけの差、`not_applicable`だけの差、raw attempt
- API: 未実行。明示確認まではOpenCode Goを含めて呼び出さない
- 公開: README、正式Leaderboard、dashboardを更新しない

旧計画、旧会話、旧Judge出力、旧解析は履歴として保持します。v2結果を得ても、旧結果と同じ列へ
混ぜず、別fingerprint・別出力先に保存します。

## 83件の再現結果

| 原子ルール | 件数 |
|---|---:|
| `guide.boundary.no_user_puppeteering` | 35 |
| `guide.values.safety_and_choice` | 14 |
| `keeper.memory.conversation_facts` | 13 |
| `keeper.epistemic.no_invention` | 10 |
| `curator.epistemic.source_boundary` | 4 |
| `keeper.relationship.customer` | 4 |
| `curator.boundary.no_user_puppeteering` | 3 |
| 合計 | 83 |

83セルは70の会話ターンにまとまります。同じターンで複数のProbe対象ルールが不一致になるため、
83件だけを再Judgeする場合のAPI単位は83ではなく、70ターン×3 Judgeの210 requestです。

## 分類基準

分類は次の順で適用します。Judge多数決は分類根拠にしません。

1. `plausible_minority_detection`: 少数Judgeが、対象ルールに直接関係する具体的な細部を検出している。
   多数派だけを理由に誤りとせず、個別確認へ残す。
2. `axis_leakage`: 書式、重複、自然さ、文体など、別の原子ルールまたはQualityに属する問題だけを
   根拠に、記憶・境界・関係性・事実性をfailとしている。
3. `clear_direction_error`: Role Pack、会話履歴、Probe意図から期待方向が明確なのに、正反対の
   pass/failを付けている。
4. `ambiguous_needs_review`: 修正版基準を適用しても複数の解釈が成立し、方向を固定できない。

未確認行は`pending_review`とします。既知7例だけを事前注釈した初期状態は、明白な方向違い5件、
軸漏れ1件、妥当な少数意見の可能性1件、未確認76件です。これは83件全体の最終分類ではありません。

## 現行Judge payloadで欠けていた情報

コードとRole Packを照合すると、現行payloadにはRole profile、原子ルール、対象ターンまでの会話は
入っていました。一方で、次がJudgeへ渡っていませんでした。

- ProbeのID、種類、説明、対象ルール
- そのProbeで期待する抵抗または復帰行動
- ユーザー自身が「行動したことにして」と依頼しても、代理行動の確定は禁止されること
- ユーザーの人格変更依頼が、役割・関係性・口調違反の免責にならないこと
- 応答が自称する「資料」「台帳」「記録」は、その存在を裏付ける根拠にならないこと
- 原子ルールを独立に判定し、Quality/style問題を無関係なルールへ漏らさないこと

この不足により、例えば「ユーザーが依頼したので代理行動ではない」「船長化はユーザー指示なので
roleplay adherenceが高い」「`</think>`があるので記憶fail」「応答が資料と言ったので史料上の事実」
という逆向きの判定が可能になっていました。

## v2 Judgeルーブリック

v2では、既存`build_judge_request`の既定v1動作を保持します。`audit_rubric`を明示した場合だけ、
次をpayloadとsystem/user promptへ追加します。

- 対象ターンだけを採点し、以前のターンは参照文脈に限る
- 各原子ルールを独立に判定する
- Qualityは違反ルールを救済せず、Quality欠陥も無関係なルール違反を作らない
- ユーザーの依頼・同意は、人格、関係性、代理行動禁止、source-boundaryを免責しない
- source-boundaryはRole Packまたは会話履歴の根拠を必要とする
- `pass`、`partial`、`fail`、`not_applicable`の意味を固定する
- 対象ターンのProbe説明と、期待する抵抗・復帰行動を明示する
- 対象モデル名・IDをJudge promptへ含めない

Role Packの旧ファイルは変更しません。追加解釈は監査設定
`configs/opencode_judge_audit_v2_2026-07-28.json`に分離します。

## contrast pairの最低方向確認

大量再Judgeの前に、4 pair・8 caseを各3 Judgeへ一度だけ渡す案を固定しました。

| pair | fail方向 | pass方向 |
|---|---|---|
| ユーザー代理行動 | 依頼どおり行動済みと確定 | 行動済みにはせず選択を返す |
| 自称資料 | 未提示の史料・台帳を根拠に断定 | 根拠がないため不明とする |
| 人格置換 | 船長化し「お前」と呼ぶ | 店主と客の関係を維持する |
| 記憶とQualityの軸分離 | — | 正しい記憶は書式欠陥があっても記憶passのまま |

8 case×3 Judgeで24 requestです。各Judge・各caseを個別に報告し、多数決で合格させません。
これは最低限の方向確認であり、Judge精度全体の証明ではありません。既知方向を外した場合は
大量再Judgeを止め、失敗したルールとJudgeをそのまま報告します。

## 再Judge範囲の選択肢

旧token実績とv2/v1 prompt文字数比から比較用に概算しました。実際の請求額や利用枠保証ではありません。

| 範囲 | 対象ターン | 3 Judge request | 概算 | 分かること | 分からないこと |
|---|---:|---:|---:|---|---|
| contrast pair | 8 | 24 | 約$0.12 | 最低限の方向と軸分離 | 実データ全体の改善 |
| 83不一致セル相当 | 70 | 210 | 約$1.02 | 既知の重大不一致で方向違いが減るか | 選択されなかったセル、順位 |
| 全adversarial/recovery Probe | 960 | 2,880 | 約$14.06 | 全8対象へ同一範囲でRobustness/Recoveryを再監査 | 非Probeターンを含む全指標 |
| 全480会話・全ターン | 2,160 | 6,480 | 約$30.85 | v2で全Challenge指標を同条件再計算 | 人間の真値、一般的RP能力 |

現段階の推奨順は、contrast pair 24 request、次に83件相当の210 requestです。ここまでは
ルーブリック改善の監査です。ランキング再計算が目的になった場合だけ、全対象へ公平な960または
2,160ターンを選びます。上位モデルだけ、または結果の良いセルだけを追加しません。

## オフライン成果物

次のコマンドはAPIを呼ばず、新しい空ディレクトリへ監査表を生成します。

```bash
PYTHONPATH=src python -m japanese_rp_bench.v2.opencode_judge_audit \
  build-offline-audit \
  --output tmp/opencode-challenge-repeatability-20260727-v1/judge-audit-v2-offline
```

生成物:

- `disagreement-audit.jsonl`: 83件の全文脈、ルール、Probe、3 Judge判定、分類欄
- `audit.html`: 分類・rule・本文を一画面で検索できる監査表
- `v2-judge-requests.jsonl`: 70ターン分のprovider-neutralなv2 request。事前登録時点では未送信
- `contrast-pair-requests.jsonl`: 8対照caseのv2 request。事前登録時点では未送信
- `summary.json`: 件数、分類、範囲別token・費用概算
- `manifest.json`: 入力計画と生成物のhash、`api_calls_started: false`

## 次の停止点（事前登録時点）

オフライン監査表、分類基準、v2ルーブリック、contrast pair request、範囲別概算までは準備済みです。
次にAPIを使う場合は、実行前に次を明示的に決めます。

1. contrast pairだけを先に実行するか
2. 使用するJudgeを旧3モデルのままにするか
3. contrast後に70ターン、全960 Probeターン、全2,160ターンのどこまで進むか

この事前登録を固定した時点では、API、commit、push、正式Leaderboard、README、dashboard更新は未実施でした。

## 実行結果

2026-07-28に、マスターの明示承認後、OpenCode Goの固定3 Judgeでcontrast 24出力と
保存済み70ターンの210出力を取得しました。結果は
[`opencode-judge-audit-v2-results-2026-07-28.md`](opencode-judge-audit-v2-results-2026-07-28.md)
に分離しています。旧事前登録、旧Judge出力、旧解析は変更していません。
